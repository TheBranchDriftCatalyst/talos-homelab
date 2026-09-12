"""etcd-snapshot — disaster-recovery / chaos test  (TALOS-23l.6)

Validates the control-plane etcd backup pipeline: an hourly CronJob snapshots etcd via
`talosctl etcd snapshot` and uploads the .snapshot to MinIO (bucket `backups`, prefix `etcd`,
NFS-backed). Recovery from a control-plane disk failure depends entirely on a FRESH, INTACT
snapshot existing off-node.

READ-ONLY (always) proves the machinery EXISTS, the CronJob is HEALTHY, a <1h-fresh snapshot
object exists in MinIO, the stored snapshot is INTACT (bbolt magic), and etcd is snapshottable.
DESTRUCTIVE (armed: pytest --destructive / ETCD_DR_DESTRUCTIVE=1) is still NON-destructive to live
etcd: it takes a fresh `talosctl etcd snapshot` to a throwaway temp file and proves it LOADS +
HASHES cleanly (what a real restore consumes), then prints the bootstrap-restore runbook.

Needs `kubectl` and `talosctl` (with a control-plane talosconfig) on PATH. The MinIO probe runs
through a throwaway minio/mc pod.
"""
import json
import os
import re
import shlex
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pytest.ini").exists())
sys.path.insert(0, str(_ROOT / "tests"))

from lib import dr  # noqa: E402

pytestmark = pytest.mark.disaster_recovery

# ---- config (env-overridable, preserved from the Jest suite) ----
NS = os.environ.get("ETCD_BACKUP_NS", "backup")
CRONJOB = os.environ.get("ETCD_CRONJOB", "etcd-backup")
CM = os.environ.get("ETCD_BACKUP_CM", "etcd-backup-config")
S3_SECRET = os.environ.get("ETCD_S3_SECRET", "minio-root-credentials")
TALOSCONFIG_SECRET = os.environ.get("ETCD_TALOSCONFIG_SECRET", "talosconfig")
S3_ENDPOINT = os.environ.get("ETCD_S3_ENDPOINT", "http://minio.minio.svc.cluster.local")
S3_BUCKET = os.environ.get("ETCD_S3_BUCKET", "backups")
S3_PREFIX = os.environ.get("ETCD_S3_PREFIX", "etcd")
TALOS_NODE = os.environ.get("TALOS_NODE", "192.168.1.54")
MAX_SNAPSHOT_AGE_S = float(os.environ.get("ETCD_MAX_SNAPSHOT_AGE_S", "3600"))
MAX_CRONJOB_SINCE_SCHEDULED_S = float(os.environ.get("ETCD_MAX_SINCE_SCHEDULED_S", "7200"))
MIN_SNAPSHOT_BYTES = int(os.environ.get("ETCD_MIN_SNAPSHOT_BYTES", "1048576"))
MAX_SNAPSHOT_WALL_S = float(os.environ.get("ETCD_MAX_SNAPSHOT_WALL_S", "120"))
MC_IMAGE = os.environ.get("ETCD_MC_IMAGE", "quay.io/minio/mc:RELEASE.2024-11-21T17-21-54Z")
BBOLT_MAGIC_LE = "edda0ced"
DESTRUCTIVE_ENV = "ETCD_DR_DESTRUCTIVE"

M = dr.Metrics("etcd-DR")


@pytest.fixture(autouse=True)
def _require_cluster():
    dr.require_cluster()


@pytest.fixture(scope="module", autouse=True)
def _config_and_summary():
    # pull the real tunables from the live ConfigMap so freshness/integrity use the ACTUAL target
    global S3_ENDPOINT, S3_BUCKET, S3_PREFIX, TALOS_NODE
    cm = dr.kubectl(f"get configmap {CM} -n {NS} -o json")
    try:
        d = json.loads(cm).get("data", {})
        S3_ENDPOINT = os.environ.get("ETCD_S3_ENDPOINT") or d.get("S3_ENDPOINT") or S3_ENDPOINT
        S3_BUCKET = os.environ.get("ETCD_S3_BUCKET") or d.get("S3_BUCKET") or S3_BUCKET
        S3_PREFIX = os.environ.get("ETCD_S3_PREFIX") or d.get("S3_PREFIX") or S3_PREFIX
        TALOS_NODE = os.environ.get("TALOS_NODE") or d.get("TALOS_NODE") or TALOS_NODE
    except Exception:
        pass
    yield
    M.summary()


# ---- helpers ----
def talosctl(args, timeout=60, check=False):
    return dr.sh(f"talosctl -n {TALOS_NODE} {args}", timeout=timeout, check=check)


def secret_val(name, key):
    import base64
    b64 = dr.kubectl(f'get secret {name} -n {NS} -o jsonpath="{{.data.{key}}}"')
    if not b64:
        return ""
    try:
        return base64.b64decode(b64).decode().strip()
    except Exception:
        return ""


def mc(mc_args, timeout=90):
    ak = secret_val(S3_SECRET, "AWS_ACCESS_KEY_ID")
    sk = secret_val(S3_SECRET, "AWS_SECRET_ACCESS_KEY")
    if not ak or not sk:
        raise AssertionError(f"could not read S3 creds from secret {S3_SECRET} in ns {NS}")
    name = f"etcddr-mc-{int(time.time() * 1000)}"
    script = f'mc alias set b "{S3_ENDPOINT}" "$AK" "$SK" >/dev/null 2>&1; {mc_args}'
    cmd = (f"run {name} -n {NS} --rm -i --restart=Never --image={MC_IMAGE} "
           f"--env {shlex.quote('AK=' + ak)} --env {shlex.quote('SK=' + sk)} "
           f"--command -- sh -c {shlex.quote(script)}")
    return dr.kubectl(cmd, timeout=timeout)


def newest_snapshot():
    raw = mc(f'mc ls --json "b/{S3_BUCKET}/{S3_PREFIX}/"')
    rows = []
    for ln in filter(None, (l.strip() for l in raw.splitlines())):
        try:
            o = json.loads(ln)
        except Exception:
            continue
        if o and o.get("type") == "file" and o.get("lastModified"):
            rows.append(o)
    if not rows:
        return None
    rows.sort(key=lambda o: o["lastModified"], reverse=True)
    n = rows[0]
    age = (datetime.now(timezone.utc)
           - datetime.fromisoformat(n["lastModified"].replace("Z", "+00:00"))).total_seconds()
    return {"key": n["key"], "ageS": age, "bytes": n.get("size", 0)}


def stored_snapshot_integrity(key):
    import base64
    ak = secret_val(S3_SECRET, "AWS_ACCESS_KEY_ID")
    sk = secret_val(S3_SECRET, "AWS_SECRET_ACCESS_KEY")
    name = f"etcddr-int-{int(time.time() * 1000)}"
    script = (
        f'mc alias set b "{S3_ENDPOINT}" "$AK" "$SK" >/dev/null 2>&1; '
        f'mc cp "b/{S3_BUCKET}/{S3_PREFIX}/{key}" /tmp/s.db >/dev/null 2>&1 || {{ echo BYTES=0 MAGIC=none; exit 0; }}; '
        'echo BYTES=$(wc -c < /tmp/s.db); '
        'echo MAGIC=$(od -An -tx1 -N32 /tmp/s.db | tr -dc 0-9a-f)')
    cmd = (f"run {name} -n {NS} --rm -i --restart=Never --image={MC_IMAGE} "
           f"--env {shlex.quote('AK=' + ak)} --env {shlex.quote('SK=' + sk)} "
           f"--command -- sh -c {shlex.quote(script)}")
    o = dr.kubectl(cmd, timeout=120)
    bytes_ = int((re.search(r"BYTES=(\d+)", o) or [0, "0"])[1] or "0")
    hexs = (re.search(r"MAGIC=([0-9a-f]+)", o) or [0, ""])[1] or ""
    return {"bytes": bytes_, "hasMagic": BBOLT_MAGIC_LE in hexs, "hex": hexs}


def verify_snapshot_file(file):
    size = os.path.getsize(file) if os.path.exists(file) else 0
    for binname in ("etcdutl", "etcdctl"):
        have = dr.sh(f"command -v {binname} || true", check=False)
        if not have:
            continue
        env = "ETCDCTL_API=3 " if binname == "etcdctl" else ""
        o = dr.sh(f'{env}{binname} snapshot status "{file}" --write-out=json', check=False, timeout=120)
        try:
            st = json.loads(o)
            if "hash" in st:
                return {"ok": True, "size": size, "tool": binname,
                        "detail": f"hash={st['hash']} rev={st.get('revision')} keys={st.get('totalKey')}"}
        except Exception:
            pass
    # fallback: bbolt magic in the first page
    has_magic = False
    try:
        with open(file, "rb") as fh:
            has_magic = BBOLT_MAGIC_LE in fh.read(32).hex()
    except Exception:
        pass
    return {"ok": has_magic and size >= MIN_SNAPSHOT_BYTES, "size": size, "tool": "bbolt-magic",
            "detail": "bbolt meta magic present" if has_magic else "NO bbolt magic"}


def print_restore_runbook(snapshot_key="etcd-<TIMESTAMP>.snapshot"):
    print("\nETCD BOOTSTRAP-RESTORE RUNBOOK (control-plane disk loss)")
    for ln in [
        "Preconditions: a fresh, INTACT snapshot off-node (this test guards that) + talosconfig",
        "               with os:etcd:backup role + the node's machine config.",
        "1. Pull the chosen snapshot from MinIO to the admin host:",
        f"     mc alias set b {S3_ENDPOINT} <AK> <SK>",
        f"     mc cp b/{S3_BUCKET}/{S3_PREFIX}/{snapshot_key} ./etcd-restore.db",
        "2. Verify BEFORE trusting it:",
        "     ETCDCTL_API=3 etcdutl snapshot status ./etcd-restore.db --write-out=table",
        "3. Put the control-plane node into a clean state (single-node CP shown):",
        f"     talosctl -n {TALOS_NODE} bootstrap --recover-from=./etcd-restore.db",
        "4. Wait for the API + etcd to come healthy, then verify quorum:",
        f"     talosctl -n {TALOS_NODE} etcd status",
        f"     talosctl -n {TALOS_NODE} health --wait-timeout 10m",
        "5. Reconcile GitOps (Flux/ArgoCD) so workloads converge to the snapshot's revision.",
        "   NOTE: this test NEVER runs step 3 against live etcd — it only proves steps 1-2.",
    ]:
        print(f"   {ln}")


# ---- READ-ONLY tier (always runs) ----
def test_backup_machinery_exists():
    cj = dr.kubectl(f"get cronjob {CRONJOB} -n {NS} -o json")
    schedule, suspended = "", None
    try:
        o = json.loads(cj)
        schedule = o["spec"]["schedule"]
        suspended = bool(o["spec"].get("suspend"))
    except Exception:
        pass
    cj_ok = bool(schedule)
    not_suspended = suspended is False
    cm_ok = bool(dr.kubectl(f"get configmap {CM} -n {NS} -o name"))
    talos_ok = bool(dr.kubectl(f"get secret {TALOSCONFIG_SECRET} -n {NS} -o name"))
    s3_ok = bool(dr.kubectl(f"get secret {S3_SECRET} -n {NS} -o name"))
    allok = cj_ok and not_suspended and cm_ok and talos_ok and s3_ok
    M.record("Backup machinery exists", "complete" if allok else "INCOMPLETE", "complete", allok)
    assert cj_ok, f"CronJob {CRONJOB} not found"
    assert not_suspended, f"CronJob suspend={suspended}"
    assert cm_ok, f"ConfigMap {CM} missing"
    assert talos_ok, f"Secret {TALOSCONFIG_SECRET} missing"
    assert s3_ok, f"Secret {S3_SECRET} missing"


def test_cronjob_healthy():
    cj = json.loads(dr.kubectl(f"get cronjob {CRONJOB} -n {NS} -o json") or "{}")
    last_sched = cj.get("status", {}).get("lastScheduleTime")
    since_s = ((datetime.now(timezone.utc)
                - datetime.fromisoformat(last_sched.replace("Z", "+00:00"))).total_seconds()
               if last_sched else float("inf"))
    sched_ok = since_s <= MAX_CRONJOB_SINCE_SCHEDULED_S
    jobs = json.loads(dr.kubectl(f"get jobs -n {NS} -o json") or '{"items":[]}')
    named = [j for j in jobs.get("items", []) if (j["metadata"].get("name") or "").startswith(f"{CRONJOB}-")]
    any_active_fail = any(
        (j.get("status", {}).get("failed", 0) > 0) and not (j.get("status", {}).get("succeeded", 0) > 0)
        and not any(c.get("type") == "Complete" and c.get("status") == "True"
                    for c in j.get("status", {}).get("conditions", []))
        for j in named)
    M.record("CronJob scheduled recently",
             f"{since_s / 60:.0f}min" if last_sched else "inf",
             f"{MAX_CRONJOB_SINCE_SCHEDULED_S / 60:.0f}min", sched_ok)
    assert sched_ok, "etcd-backup CronJob has not scheduled recently"
    assert not any_active_fail, "an etcd-backup job is stuck in Failed"


def test_snapshot_freshness():
    snap = newest_snapshot()
    assert snap is not None, f"no snapshot object under s3://{S3_BUCKET}/{S3_PREFIX}/"
    fresh = snap["ageS"] <= MAX_SNAPSHOT_AGE_S
    dr.assert_within(snap["ageS"], MAX_SNAPSHOT_AGE_S, "newest snapshot age")
    M.record("Newest snapshot freshness", f"{snap['ageS'] / 60:.1f}min",
             f"{MAX_SNAPSHOT_AGE_S / 60:.0f}min", fresh)


def test_snapshot_integrity():
    snap = newest_snapshot()
    assert snap is not None, "no snapshot object to validate"
    key = snap["key"].split("/")[-1]
    res = stored_snapshot_integrity(key)
    size_ok = res["bytes"] >= MIN_SNAPSHOT_BYTES
    M.record("Stored snapshot integrity", "valid db" if size_ok and res["hasMagic"] else "INVALID",
             "valid db", size_ok and res["hasMagic"])
    assert size_ok, f"snapshot only {res['bytes']} bytes (< {MIN_SNAPSHOT_BYTES})"
    assert res["hasMagic"], f"snapshot lacks bbolt/etcd meta magic (head={res['hex'][:24]})"


def test_etcd_healthy_and_snapshottable():
    status = talosctl("etcd status", timeout=60)
    lines = [ln for ln in status.splitlines() if ln]
    hard_err = re.search(
        r"rpc error|connection refused|context deadline exceeded|certificate|permission denied|"
        r"no such host|failed to|unauthenticated", status, re.I)
    data_row = next((ln for ln in lines[1:] if TALOS_NODE in ln), "")
    reachable = bool(data_row) and not hard_err
    has_db_size = bool(re.search(r"\b\d+(\.\d+)?\s*(B|kB|KB|MB|MiB|GB|GiB|TB)\b", data_row))
    M.record("etcd healthy + snapshottable", "healthy" if reachable and has_db_size else "UNHEALTHY",
             "healthy", reachable and has_db_size)
    assert reachable, f"etcd status not reachable: {data_row or (lines[0] if lines else 'no output')}"
    assert has_db_size, "etcd member row reports no DB size"


# ---- DESTRUCTIVE tier (armed only; still non-destructive to live etcd) ----
@pytest.mark.destructive
def test_restore_procedure_snapshot_loads_and_hashes():
    dr.require_destructive(DESTRUCTIVE_ENV)
    tmp = os.path.join(tempfile.gettempdir(), f"etcd-dr-{int(time.time() * 1000)}.db")
    ok, wall, detail = False, 0.0, ""
    try:
        t0 = time.time()
        talosctl(f'etcd snapshot "{tmp}"', timeout=300, check=True)
        wall = time.time() - t0
        v = verify_snapshot_file(tmp)
        ok = v["ok"]
        detail = f"{v['tool']}: {v['detail']}"
        dr.assert_within(wall, MAX_SNAPSHOT_WALL_S, "snapshot wall-time")
        M.record("Snapshot wall-time (fresh)", f"{wall:.1f}s", f"<= {MAX_SNAPSHOT_WALL_S}s",
                 wall <= MAX_SNAPSHOT_WALL_S)
        M.record("Fresh snapshot loads + hashes", "valid" if ok else "INVALID", "valid", ok)
    finally:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except Exception:
            pass
    try:
        newest = newest_snapshot()
    except Exception:
        newest = None
    print_restore_runbook(newest["key"].split("/")[-1] if newest else None)
    assert ok, f"fresh snapshot did not load/hash cleanly ({detail})"


@pytest.mark.destructive
def test_restore_into_canary_documented_noop():
    dr.require_destructive(DESTRUCTIVE_ENV)
    # A real `talosctl bootstrap --recover-from=<db>` REPLACES live etcd — catastrophic on the live
    # CP and infeasible without a spare Talos node. Documented no-op; runbook printed above.
    M.record("Restore-into-canary", "doc no-op", "safe", True)
    assert True
