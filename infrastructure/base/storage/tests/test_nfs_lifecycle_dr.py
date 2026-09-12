"""NFS / PVC lifecycle — disaster-recovery / chaos test  (TALOS-23l.7)

Guards the STORAGE reclaim/reuse data-hygiene design after the 2026-05-09 incident. Two
StorageClasses back the cluster: local-path (default, reclaim=Delete) and fatboy-nfs-appdata
(Synology dynamic NFS, reclaim=Retain, RWX, archiveOnDelete). The subtle hygiene invariant:
because the NFS class ARCHIVES a deleted PVC's directory, recreating a PVC with the SAME name must
land on a FRESH, empty volume — never inherit the old PVC's bytes.

READ-ONLY (always) asserts the machinery EXISTS + is healthy. DESTRUCTIVE (armed: pytest
--destructive / NFS_DR_DESTRUCTIVE=1) provisions/deletes real PVCs on NFS, targeting ONLY the
nfs-dr-canary namespace/PVC.

Needs `kubectl` (context = the cluster) on PATH.
"""
import json
import os
import shlex
import sys
import time
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pytest.ini").exists())
sys.path.insert(0, str(_ROOT / "tests"))

from lib import dr  # noqa: E402

pytestmark = pytest.mark.disaster_recovery

# ---- config (env-overridable, preserved from the Jest suite) ----
APPDATA_SC = os.environ.get("NFS_APPDATA_SC", "fatboy-nfs-appdata")
LOCAL_SC = os.environ.get("NFS_LOCAL_SC", "local-path")
PROV_NS = os.environ.get("NFS_PROVISIONER_NS", "kube-system")
PROV_DEPLOY = os.environ.get("NFS_PROVISIONER_DEPLOY", "nfs-subdir-external-provisioner")
CANARY_NS = os.environ.get("NFS_CANARY_NS", "nfs-dr-canary")
CANARY_PVC = os.environ.get("NFS_CANARY_PVC", "nfs-dr-canary-pvc")
CANARY_POD = os.environ.get("NFS_CANARY_POD", "nfs-dr-canary")
MAX_PROVISION_S = float(os.environ.get("NFS_MAX_PROVISION_S", "60"))
MAX_RECREATE_S = float(os.environ.get("NFS_MAX_RECREATE_S", "90"))
PVC_YAML = _HERE / "canary-pvc.yaml"
POD_YAML = _HERE / "canary-pod.yaml"
DESTRUCTIVE_ENV = "NFS_DR_DESTRUCTIVE"

M = dr.Metrics("NFS-lifecycle DR")
_canary = {"sentinel": f"dr-sentinel-{int(time.time() * 1000)}", "wrote_bytes": 0}


@pytest.fixture(autouse=True)
def _require_cluster():
    dr.require_cluster()


@pytest.fixture(scope="module", autouse=True)
def _summary():
    yield
    if dr.armed(DESTRUCTIVE_ENV):
        teardown_canary()
    M.summary()


# ---- helpers ----
def sc_json(name):
    raw = dr.kubectl(f"get storageclass {name} -o json")
    if not raw or not raw.startswith("{"):
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def is_default_sc(sc):
    return (((sc or {}).get("metadata", {}).get("annotations", {}) or {})
            .get("storageclass.kubernetes.io/is-default-class")) == "true"


def default_sc_names():
    raw = dr.kubectl("get storageclass -o json")
    if not raw or not raw.startswith("{"):
        return []
    items = json.loads(raw).get("items", [])
    return [i["metadata"]["name"] for i in items if is_default_sc(i)]


def provisioner_available():
    n = dr.kubectl(f"get deploy {PROV_DEPLOY} -n {PROV_NS} -o jsonpath={{.status.availableReplicas}}")
    return int(n or "0") >= 1


def pvc_phase(name, ns):
    return dr.kubectl(f"get pvc {name} -n {ns} -o jsonpath={{.status.phase}}")


def apply_pvc():
    dr.kubectl(f"apply -f {PVC_YAML}", check=True)


def apply_pod():
    dr.kubectl(f"apply -f {POD_YAML}", check=True)


def wait_bound(timeout_s=90):
    return dr.wait_until(lambda: pvc_phase(CANARY_PVC, CANARY_NS) == "Bound", timeout_s=timeout_s, interval_s=2)


def wait_pod_ready(timeout_s=120):
    dr.kubectl(f"wait --for=condition=Ready pod/{CANARY_POD} -n {CANARY_NS} --timeout={round(timeout_s)}s")
    return dr.kubectl(
        f'get pod {CANARY_POD} -n {CANARY_NS} '
        f'-o jsonpath="{{.status.conditions[?(@.type==\'Ready\')].status}}"') == "True"


def pod_exec(cmd):
    return dr.kubectl(f"exec {CANARY_POD} -n {CANARY_NS} -c probe -- sh -c {shlex.quote(cmd)}")


def delete_pod():
    dr.kubectl(f"delete pod {CANARY_POD} -n {CANARY_NS} --ignore-not-found --wait=true --timeout=60s")


def delete_pvc():
    dr.kubectl(f"delete pvc {CANARY_PVC} -n {CANARY_NS} --ignore-not-found --wait=true --timeout=90s")


def stale_bytes():
    o = pod_exec("find /data -type f -exec cat {} + 2>/dev/null | wc -c")
    try:
        return int((o or "0").strip())
    except ValueError:
        return -1


def file_count():
    o = pod_exec("find /data -type f | wc -l")
    try:
        return int((o or "0").strip())
    except ValueError:
        return -1


def reap_released_canary_pvs():
    raw = dr.kubectl("get pv -o json")
    if not raw or not raw.startswith("{"):
        return
    for pv in json.loads(raw).get("items", []):
        cr = pv.get("spec", {}).get("claimRef")
        if cr and cr.get("namespace") == CANARY_NS and cr.get("name") == CANARY_PVC:
            dr.kubectl(f"delete pv {pv['metadata']['name']} --ignore-not-found --wait=false")


def teardown_canary():
    delete_pod()
    delete_pvc()
    reap_released_canary_pvs()
    dr.kubectl(f"delete namespace {CANARY_NS} --ignore-not-found --wait=false")


# ---- READ-ONLY tier (always runs) ----
def test_exactly_one_default_storageclass_is_local_path():
    defaults = default_sc_names()
    M.record("Default StorageClass count", len(defaults), "= 1", len(defaults) == 1)
    M.record("Default StorageClass is local-path", defaults[0] if defaults else "none", LOCAL_SC,
             defaults == [LOCAL_SC])
    assert defaults == [LOCAL_SC], f"default StorageClasses = {defaults or 'none'} (expected [{LOCAL_SC}])"


def test_local_path_storageclass():
    sc = sc_json(LOCAL_SC)
    assert sc is not None, f"{LOCAL_SC} StorageClass missing"
    prov = sc.get("provisioner", "")
    reclaim = sc.get("reclaimPolicy", "Delete")
    M.record("local-path StorageClass exists", "yes", "yes", True)
    M.record("local-path reclaimPolicy", reclaim or "none", "Delete", reclaim == "Delete")
    assert prov == "rancher.io/local-path", f"provisioner={prov}"
    assert reclaim == "Delete", f"reclaimPolicy={reclaim}"


def test_appdata_storageclass_exists():
    sc = sc_json(APPDATA_SC)
    M.record("fatboy-nfs-appdata StorageClass exists", "yes" if sc else "no", "yes", bool(sc))
    assert sc is not None, f"{APPDATA_SC} StorageClass missing"


def test_appdata_is_rwx_retain():
    sc = sc_json(APPDATA_SC)
    assert sc is not None, f"{APPDATA_SC} StorageClass missing"
    reclaim = sc.get("reclaimPolicy", "Delete")
    prov = sc.get("provisioner", "")
    nfs_prov = "nfs-subdir-external-provisioner" in prov
    M.record("fatboy-nfs-appdata reclaimPolicy", reclaim, "Retain", reclaim == "Retain")
    assert reclaim == "Retain", f"reclaimPolicy={reclaim}"
    assert nfs_prov, f"provisioner={prov} is not the nfs-subdir provisioner"


def test_nfs_provisioner_healthy():
    avail = provisioner_available()
    M.record("NFS provisioner healthy", "available" if avail else "down", "available", avail)
    assert avail, f"{PROV_DEPLOY} not Available in {PROV_NS}"


# ---- DESTRUCTIVE tier (armed only; canary) ----
@pytest.mark.destructive
def test_provision_canary_pvc_and_sentinel():
    dr.require_destructive(DESTRUCTIVE_ENV)
    teardown_canary()
    dr.wait_until(lambda: dr.kubectl(f"get ns {CANARY_NS} -o name") == "", timeout_s=60, interval_s=2)

    t0 = time.time()
    apply_pvc()
    bound = wait_bound(90)
    apply_pod()
    ready = wait_pod_ready(120)
    provision_s = time.time() - t0

    assert bound, f"canary PVC did not reach Bound (phase={pvc_phase(CANARY_PVC, CANARY_NS)})"
    assert ready, "canary pod did not mount the PVC (Ready)"
    dr.assert_within(provision_s, MAX_PROVISION_S, "provision wall-time")

    pod_exec(f"printf '%s' {shlex.quote(_canary['sentinel'])} > /data/SENTINEL")
    read_back = pod_exec("cat /data/SENTINEL 2>/dev/null").strip()
    _canary["wrote_bytes"] = len(_canary["sentinel"])
    wrote = read_back == _canary["sentinel"]
    M.record("Canary provision wall-time", f"{provision_s:.2f}s", f"<= {MAX_PROVISION_S}s",
             bound and ready and provision_s <= MAX_PROVISION_S)
    M.record("Sentinel written to NFS PVC", _canary["wrote_bytes"], "> 0", wrote)
    assert wrote, "sentinel did not read back through the NFS mount"


@pytest.mark.destructive
def test_reclaim_reuse_same_name_zero_stale_bytes():
    dr.require_destructive(DESTRUCTIVE_ENV)
    delete_pod()
    t_del = time.time()
    delete_pvc()
    reap_released_canary_pvs()

    apply_pvc()
    rebound = wait_bound(120)
    apply_pod()
    ready = wait_pod_ready(120)
    recreate_s = time.time() - t_del

    assert rebound, f"same-name PVC did not re-bind (phase={pvc_phase(CANARY_PVC, CANARY_NS)})"
    assert ready, "canary pod did not re-mount the reused PVC"
    dr.assert_within(recreate_s, MAX_RECREATE_S, "reclaim->reuse wall-time")

    files = file_count()
    bytes_ = stale_bytes()
    sentinel = pod_exec("test -f /data/SENTINEL && echo LEAK || echo CLEAN").strip()
    clean = bytes_ == 0 and files == 0 and sentinel == "CLEAN"
    M.record("Reclaim->reuse wall-time", f"{recreate_s:.2f}s", f"<= {MAX_RECREATE_S}s",
             rebound and ready and recreate_s <= MAX_RECREATE_S)
    M.record("Stale bytes on reused same-name PVC", bytes_, "0", bytes_ == 0)
    M.record("Stale files on reused same-name PVC", files, "0", files == 0)
    M.record("No data leak (fresh volume)", "clean" if clean else "LEAK", "clean", clean)
    assert bytes_ == 0, f"reused PVC has {bytes_} stale bytes"
    assert files == 0, f"reused PVC has {files} stale files"
    assert sentinel == "CLEAN", "old sentinel leaked into the reused PVC"
