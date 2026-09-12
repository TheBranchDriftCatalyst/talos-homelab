"""MinIO tenant — disaster-recovery / chaos test  (TALOS-23l.2)

Validates the operator-managed MinIO Tenant that is the cluster's S3 backend (Loki / Mimir /
Tempo + Velero). A SINGLE server on an RWO PVC backed by Synology NFS: killing the one MinIO pod
must lose NO objects — it reschedules, re-mounts the same PVC, and every object is byte-identical.

READ-ONLY (always) asserts the machinery EXISTS + is healthy and a canary object round-trips
byte-identical through the S3 API (throwaway bucket only). DESTRUCTIVE (armed: pytest --destructive
/ MINIO_DR_DESTRUCTIVE=1) kills the pod, proves the canary object survives on NFS, and measures the
S3 recovery wall-time. All S3 I/O runs through an ephemeral in-cluster minio/mc pod.

Needs `kubectl` (context = the cluster) on PATH.
"""
import base64
import os
import re
import shlex
import sys
import time
from pathlib import Path

import pytest

_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pytest.ini").exists())
sys.path.insert(0, str(_ROOT / "tests"))

from lib import dr  # noqa: E402

pytestmark = pytest.mark.disaster_recovery

# ---- config (env-overridable, preserved from the Jest suite) ----
NS = os.environ.get("MINIO_NS", "minio")
S3_SVC = os.environ.get("MINIO_S3_SVC", "minio")
ENDPOINT = os.environ.get("MINIO_ENDPOINT", f"http://{S3_SVC}.{NS}.svc.cluster.local")
ROOT_SECRET = os.environ.get("MINIO_ROOT_SECRET", "minio-root-credentials")
TENANT_SELECTOR = os.environ.get("MINIO_TENANT_LABEL", "v1.min.io/tenant=minio")
CORE_BUCKETS = [b.strip() for b in os.environ.get(
    "MINIO_CORE_BUCKETS", "mimir,loki,tempo,velero,cnpg-backups").split(",") if b.strip()]
CANARY_BUCKET = os.environ.get("MINIO_CANARY_BUCKET", "minio-dr-canary")
MC_IMAGE = os.environ.get("MINIO_MC_IMAGE", "quay.io/minio/mc:RELEASE.2024-11-21T17-21-54Z")
MAX_RECOVERY_S = float(os.environ.get("MINIO_MAX_RECOVERY_S", "180"))
DESTRUCTIVE_ENV = "MINIO_DR_DESTRUCTIVE"

CANARY_OBJ = "canary.txt"
M = dr.Metrics("MinIO DR")


@pytest.fixture(autouse=True)
def _require_cluster():
    dr.require_cluster()


@pytest.fixture(scope="module", autouse=True)
def _summary():
    yield
    M.summary()


# ---- helpers ----
def tenant_pods():
    jp = ("jsonpath={range .items[*]}{.metadata.name}|{.status.phase}|{.status.podIP}|"
          "{range .status.conditions[?(@.type=='Ready')]}{.status}{end}{'\\n'}{end}")
    o = dr.kubectl(f'get pods -n {NS} -l {TENANT_SELECTOR} -o "{jp}"')
    res = []
    for ln in filter(None, o.splitlines()):
        parts = (ln.split("|") + ["", "", "", ""])[:4]
        res.append({"name": parts[0], "phase": parts[1], "ip": parts[2], "ready": parts[3] == "True"})
    return res


def tenant_pod_ready():
    return any(p["ready"] for p in tenant_pods())


def root_creds():
    def dec(s):
        try:
            return base64.b64decode(s or "").decode()
        except Exception:
            return ""
    access = dec(dr.kubectl(f"get secret {ROOT_SECRET} -n {NS} -o jsonpath={{.data.AWS_ACCESS_KEY_ID}}"))
    secret = dec(dr.kubectl(f"get secret {ROOT_SECRET} -n {NS} -o jsonpath={{.data.AWS_SECRET_ACCESS_KEY}}"))
    return access, secret


def mc_run(script, timeout=120):
    """Run an mc script inside a throwaway in-cluster pod (alias `local` = the tenant)."""
    access, secret = root_creds()
    if not access or not secret:
        raise AssertionError(f"could not read {ROOT_SECRET} (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY)")
    name = f"minio-dr-mc-{int(time.time() * 1000)}"
    inner = ("set -e\n"
             f'mc alias set local {ENDPOINT} "$AK" "$SK" --api S3v4 >/dev/null 2>&1 || '
             '{ echo __MC_ALIAS_FAIL__; exit 40; }\n' + script)
    cmd = (f"run {name} -n {NS} --rm -i --restart=Never --image={MC_IMAGE} "
           f"--env=AK={shlex.quote(access)} --env=SK={shlex.quote(secret)} "
           f"--command -- sh -c {shlex.quote(inner)}")
    return dr.kubectl(cmd, timeout=timeout)


def canary_content(tag):
    return f"minio-dr-canary|{tag}|{'0123456789abcdef' * 8}"


def _extract(o):
    m = re.search(r"__BEGIN__\n([\s\S]*?)\n__END__", o)
    return m.group(1) if m else ""


def canary_round_trip(content):
    o = mc_run(
        f"mc mb --ignore-existing local/{CANARY_BUCKET} >/dev/null 2>&1\n"
        f"printf '%s' {shlex.quote(content)} | mc pipe local/{CANARY_BUCKET}/{CANARY_OBJ}\n"
        "echo __BEGIN__\n"
        f"mc cat local/{CANARY_BUCKET}/{CANARY_OBJ}\n"
        "echo\n"
        "echo __END__\n"
        f"mc rm --force local/{CANARY_BUCKET}/{CANARY_OBJ} >/dev/null 2>&1 || true\n"
        f"mc rb --force local/{CANARY_BUCKET} >/dev/null 2>&1 || true\n")
    return _extract(o)


# ---- READ-ONLY tier (always runs) ----
def test_tenant_server_pod_ready():
    ready = [p for p in tenant_pods() if p["ready"]]
    M.record("Tenant server pod Ready", f"{len(ready)}", ">= 1", len(ready) >= 1)
    assert len(ready) >= 1, "no MinIO server pod Ready"


def test_data_pvc_bound_on_nfs():
    jp = ("jsonpath={range .items[*]}{.metadata.name}|{.status.phase}|"
          "{.spec.storageClassName}|{.spec.accessModes[0]}{'\\n'}{end}")
    o = dr.kubectl(f'get pvc -n {NS} -o "{jp}"')
    pvcs = []
    for ln in filter(None, o.splitlines()):
        parts = (ln.split("|") + ["", "", "", ""])[:4]
        pvcs.append({"name": parts[0], "phase": parts[1], "sc": parts[2], "mode": parts[3]})
    data = [p for p in pvcs if "minio-pool" in p["name"]]
    bound = [p for p in data if p["phase"] == "Bound"]
    rwo_nfs = [p for p in bound if p["mode"] == "ReadWriteOnce" and re.search(r"nfs", p["sc"] or "", re.I)]
    M.record("Data PVC Bound (NFS RWO)", f"{len(bound)} bound", ">= 1", len(bound) >= 1)
    assert len(bound) >= 1, "no tenant data PVC Bound"
    assert len(rwo_nfs) >= 1, "tenant data PVC is not ReadWriteOnce on an NFS class"


def test_s3_service_exists():
    ip = dr.kubectl(f"get svc {S3_SVC} -n {NS} -o jsonpath={{.spec.clusterIP}}")
    ok = bool(ip) and ip != "None"
    M.record("S3 service present", ip or "none", "exists", ok)
    assert ok, f"service {S3_SVC} clusterIP={ip or 'none'}"


def test_root_credentials_secret():
    access, secret = root_creds()
    ok = bool(access) and bool(secret)
    M.record("Root-cred secret populated", "yes" if ok else "no", "yes", ok)
    assert ok, f"{ROOT_SECRET} missing AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY"


def test_core_buckets_exist():
    probe = "\n".join(
        f'if mc ls local/{b} >/dev/null 2>&1; then echo "{b} OK"; else echo "{b} MISSING"; fi'
        for b in CORE_BUCKETS)
    o = mc_run(probe, timeout=120)
    present = {b: bool(re.search(rf"^{re.escape(b)} OK$", o, re.M)) for b in CORE_BUCKETS}
    all_ok = len(CORE_BUCKETS) > 0 and all(present.values())
    M.record("Core buckets exist", f"{sum(present.values())}/{len(CORE_BUCKETS)}", str(len(CORE_BUCKETS)), all_ok)
    missing = [b for b, ok in present.items() if not ok]
    assert all_ok, f"missing buckets: {missing}"


def test_canary_object_round_trips_byte_identical():
    content = canary_content(f"ro-{int(time.time() * 1000)}")
    got = canary_round_trip(content)
    M.record("Canary write->GET byte-identical", "identical" if got == content else "MISMATCH",
             "identical", got == content)
    assert got == content, f"PUT {len(content)}B / GET {len(got)}B not identical"


# ---- DESTRUCTIVE tier (armed only) ----
@pytest.mark.destructive
def test_pod_kill_object_survives_on_nfs_and_recovery():
    dr.require_destructive(DESTRUCTIVE_ENV)
    content = canary_content(f"dr-{int(time.time() * 1000)}")
    wrote = mc_run(
        f"mc mb --ignore-existing local/{CANARY_BUCKET} >/dev/null 2>&1\n"
        f"printf '%s' {shlex.quote(content)} | mc pipe local/{CANARY_BUCKET}/{CANARY_OBJ}\n"
        f"mc stat local/{CANARY_BUCKET}/{CANARY_OBJ} >/dev/null 2>&1 && echo __WROTE_OK__ || echo __WROTE_FAIL__\n")
    assert "__WROTE_OK__" in wrote, "canary object failed to stage pre-kill"

    pods = tenant_pods()
    before = next((p for p in pods if p["ready"]), pods[0] if pods else None)
    assert before is not None, "no tenant pod to kill"
    t0 = time.time()
    dr.kubectl(f"delete pod {before['name']} -n {NS} --wait=false")

    pod_back = dr.wait_until(tenant_pod_ready, timeout_s=MAX_RECOVERY_S, interval_s=3)
    pod_ready_dt = time.time() - t0

    got = {"v": ""}

    def _s3_serves():
        o = mc_run("echo __BEGIN__\n"
                   f"mc cat local/{CANARY_BUCKET}/{CANARY_OBJ} 2>/dev/null\n"
                   "echo\necho __END__\n", timeout=90)
        got["v"] = _extract(o)
        return got["v"] == content

    s3_back = dr.wait_until(_s3_serves, timeout_s=MAX_RECOVERY_S, interval_s=4)
    s3_dt = time.time() - t0

    # cleanup
    try:
        mc_run(f"mc rm --force local/{CANARY_BUCKET}/{CANARY_OBJ} >/dev/null 2>&1 || true\n"
               f"mc rb --force local/{CANARY_BUCKET} >/dev/null 2>&1 || true\n", timeout=90)
    except Exception:
        pass

    identical = got["v"] == content
    dr.assert_within(s3_dt if s3_back else MAX_RECOVERY_S + 1, MAX_RECOVERY_S, "S3 recovery wall-time")
    M.record("Pod-Ready recovery wall-time", f"{pod_ready_dt:.1f}s", f"<= {MAX_RECOVERY_S}s", pod_back)
    M.record("S3 recovery wall-time (kill->read)", f"{s3_dt:.1f}s", f"<= {MAX_RECOVERY_S}s",
             s3_back and s3_dt <= MAX_RECOVERY_S)
    M.record("Object survived pod kill (NFS)", "byte-identical" if identical else "LOST/CORRUPT",
             "byte-identical", identical)
    assert pod_back, "tenant pod did not become Ready again after kill"
    assert s3_back, "S3 did not serve the canary object again after kill"
    assert got["v"] == content, "canary object not byte-identical after pod kill"
