"""Velero backup / disaster-recovery chaos test  (TALOS-23l.1)

Validates the Velero DR machinery (MinIO S3 backend, BackupStorageLocation, node-agent Kopia
fs-backup, automated Schedules) and PROVES a real backup->restore round-trip recovers data with
zero loss: write a file with a known sha256, back it up, DELETE the whole namespace, restore, and
assert the restored sha256 matches. Restore wall-time is measured.

Read-only checks ALWAYS run (they only assert the DR machinery EXISTS + is healthy). The
DESTRUCTIVE round-trip runs only when armed (pytest --destructive / VELERO_DR_DESTRUCTIVE=1) and
operates exclusively on a throwaway CANARY namespace (velero-dr-canary).

Needs `kubectl` (context = the cluster where Velero runs) on PATH.
"""
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pytest.ini").exists())
sys.path.insert(0, str(_ROOT / "tests"))

from lib import dr  # noqa: E402

pytestmark = pytest.mark.disaster_recovery

# ---- config (env-overridable, preserved from the Jest suite) ----
NS = os.environ.get("VELERO_NS", "backup")
BSL = os.environ.get("VELERO_BSL", "default")
CANARY_NS = os.environ.get("VELERO_CANARY_NS", "velero-dr-canary")
CANARY_FILE = "/data/canary.bin"
BACKUP_RECENCY_H = float(os.environ.get("VELERO_BACKUP_RECENCY_H", "24"))
MAX_BACKUP_S = float(os.environ.get("VELERO_MAX_BACKUP_S", "300"))
MAX_RESTORE_S = float(os.environ.get("VELERO_MAX_RESTORE_S", "300"))
CANARY_YAML = _HERE / "canary.yaml"
DESTRUCTIVE_ENV = "VELERO_DR_DESTRUCTIVE"

M = dr.Metrics("Velero DR")


@pytest.fixture(autouse=True)
def _require_cluster():
    dr.require_cluster()


@pytest.fixture(scope="module", autouse=True)
def _summary():
    yield
    if dr.armed(DESTRUCTIVE_ENV):
        # best-effort teardown of every throwaway artifact this suite created
        dr.kubectl(f"delete ns {CANARY_NS} --ignore-not-found --wait=false")
        dr.kubectl(f"delete backup.velero.io,restore.velero.io -n {NS} "
                   f"-l velero-dr.talos00/throwaway=true --ignore-not-found")
    M.summary()


# ---- helpers ----
def apply_manifest(text):
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(text)
        path = f.name
    try:
        dr.kubectl(f"apply -f {path}", check=True)
    finally:
        os.unlink(path)


def bsl_phase():
    return dr.kubectl(f"get backupstoragelocation {BSL} -n {NS} -o jsonpath={{.status.phase}}")


def backup_phase(name):
    return dr.kubectl(f"get backup.velero.io {name} -n {NS} -o jsonpath={{.status.phase}}")


def restore_phase(name):
    return dr.kubectl(f"get restore.velero.io {name} -n {NS} -o jsonpath={{.status.phase}}")


def _age_h(ts):
    return (datetime.now(timezone.utc) - datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds() / 3600


def recent_successful_backup():
    import json
    raw = dr.kubectl(f"get backups.velero.io -n {NS} -o json")
    try:
        items = json.loads(raw or "{}").get("items", [])
    except Exception:
        return None
    newest = None
    for b in items:
        st = b.get("status", {})
        if st.get("phase") != "Completed":
            continue
        ts = st.get("completionTimestamp") or st.get("startTimestamp")
        if not ts:
            continue
        age = _age_h(ts)
        if newest is None or age < newest["ageH"]:
            newest = {"name": b["metadata"]["name"], "ageH": age}
    return newest


def canary_pod():
    return dr.kubectl(f"get pods -n {CANARY_NS} -l app=velero-canary -o jsonpath={{.items[0].metadata.name}}")


def read_canary_sha():
    import re
    pod = canary_pod()
    if not pod:
        return ""
    o = dr.kubectl(f'exec {pod} -n {CANARY_NS} -- sh -c "sha256sum {CANARY_FILE} 2>/dev/null || true"')
    m = re.search(r"([0-9a-f]{64})", o)
    return m.group(1) if m else ""


def write_canary_data():
    pod = canary_pod()
    dr.kubectl(f'exec {pod} -n {CANARY_NS} -- sh -c '
               f'"dd if=/dev/urandom of={CANARY_FILE} bs=1024 count=4096 2>/dev/null; sync"')
    return read_canary_sha()


def create_canary():
    apply_manifest(CANARY_YAML.read_text())
    dr.kubectl(f"rollout status deploy/velero-canary -n {CANARY_NS} --timeout=120s")
    dr.wait_until(
        lambda: bool(canary_pod()) and dr.kubectl(
            f"get deploy velero-canary -n {CANARY_NS} -o jsonpath={{.status.availableReplicas}}") == "1",
        timeout_s=120, interval_s=3)


def create_backup(name):
    apply_manifest(f"""apiVersion: velero.io/v1
kind: Backup
metadata:
  name: {name}
  namespace: {NS}
  labels:
    velero-dr.talos00/throwaway: "true"
spec:
  includedNamespaces: ["{CANARY_NS}"]
  storageLocation: {BSL}
  defaultVolumesToFsBackup: true
  snapshotVolumes: false
  ttl: 1h0m0s""")


def create_restore(name, backup_name):
    apply_manifest(f"""apiVersion: velero.io/v1
kind: Restore
metadata:
  name: {name}
  namespace: {NS}
  labels:
    velero-dr.talos00/throwaway: "true"
spec:
  backupName: {backup_name}
  includedNamespaces: ["{CANARY_NS}"]
  existingResourcePolicy: update""")


# ---- READ-ONLY tier (always runs) ----
def test_velero_deployment_healthy():
    avail = dr.kubectl(f"get deploy velero -n {NS} -o jsonpath={{.status.availableReplicas}}")
    ok = int(avail or "0") >= 1
    M.record("Velero deployment healthy", "yes" if ok else "no", "yes", ok)
    assert ok, f"deploy/velero availableReplicas={avail or '0'}"


def test_node_agent_daemonset_rolled_out():
    import json
    ds = json.loads(dr.kubectl(f"get daemonset node-agent -n {NS} -o json") or "{}")
    st = ds.get("status", {})
    desired, ready = st.get("desiredNumberScheduled"), st.get("numberReady")
    ok = desired is not None and desired > 0 and ready == desired
    M.record("node-agent DaemonSet ready", f"{ready}/{desired}", "all", ok)
    assert ok, f"node-agent ready={ready}/{desired}"


def test_backup_storage_location_available():
    phase = bsl_phase()
    M.record("BackupStorageLocation Available", phase or "none", "Available", phase == "Available")
    assert phase == "Available", f"BSL {BSL} phase={phase or '(none)'}"


def test_at_least_one_schedule():
    import json
    doc = json.loads(dr.kubectl(f"get schedules.velero.io -n {NS} -o json") or "{}")
    names = [s["metadata"]["name"] for s in doc.get("items", [])]
    M.record("Backup Schedule(s) present", len(names), ">= 1", len(names) >= 1)
    assert len(names) >= 1, "no Velero Schedule found"


def test_recent_successful_backup():
    newest = recent_successful_backup()
    ok = bool(newest) and newest["ageH"] <= BACKUP_RECENCY_H
    M.record("Recent successful backup",
             f"{newest['ageH']:.1f}h" if newest else "none", f"{BACKUP_RECENCY_H}h", ok)
    assert ok, ("no Completed backup" if not newest
                else f"newest backup {newest['name']} is {newest['ageH']:.1f}h old (> {BACKUP_RECENCY_H}h)")


# ---- DESTRUCTIVE tier (armed only) ----
@pytest.mark.destructive
def test_roundtrip_backup_delete_restore_no_data_loss():
    dr.require_destructive(DESTRUCTIVE_ENV)
    import re
    create_canary()

    sha_before = write_canary_data()
    assert re.match(r"^[0-9a-f]{64}$", sha_before or ""), f"canary data not written (sha={sha_before or 'none'})"

    backup_name = f"velero-dr-canary-{int(time.time() * 1000)}"
    t_b = time.time()
    create_backup(backup_name)

    def _backup_done():
        p = backup_phase(backup_name)
        if p == "Completed":
            return True
        if p and p not in ("InProgress", "New"):
            raise AssertionError(f"backup phase={p}")
        return False

    backed_up = dr.wait_until(_backup_done, timeout_s=MAX_BACKUP_S + 60, interval_s=4)
    backup_s = time.time() - t_b
    assert backup_phase(backup_name) == "Completed", f"backup did not complete in {backup_s:.1f}s"
    dr.assert_within(backup_s, MAX_BACKUP_S, "backup wall-time")
    M.record("Backup wall-time", f"{backup_s:.1f}s", f"<= {MAX_BACKUP_S}s", backed_up)

    # DISASTER: nuke the whole namespace (PVC data goes with it)
    dr.kubectl(f"delete ns {CANARY_NS} --wait=true --timeout=120s")
    gone = dr.wait_until(
        lambda: dr.kubectl(f"get ns {CANARY_NS} --ignore-not-found -o name") == "",
        timeout_s=150, interval_s=3)
    assert gone, "canary namespace was not fully deleted"

    # RESTORE
    restore_name = f"velero-dr-restore-{int(time.time() * 1000)}"
    t_r = time.time()
    create_restore(restore_name, backup_name)

    def _restore_done():
        p = restore_phase(restore_name)
        if p == "Completed":
            return True
        if p and p not in ("InProgress", "New"):
            raise AssertionError(f"restore phase={p}")
        return False

    restored = dr.wait_until(_restore_done, timeout_s=MAX_RESTORE_S + 60, interval_s=4)
    restore_s = time.time() - t_r
    assert restore_phase(restore_name) == "Completed", f"restore did not complete in {restore_s:.1f}s"
    dr.assert_within(restore_s, MAX_RESTORE_S, "restore wall-time")

    # VERIFY: restored file sha256 must equal the pre-disaster sha
    dr.wait_until(
        lambda: bool(canary_pod()) and dr.kubectl(
            f"get deploy velero-canary -n {CANARY_NS} -o jsonpath={{.status.availableReplicas}}") == "1",
        timeout_s=180, interval_s=4)
    sha_after = ""
    dr.wait_until(lambda: bool(re.match(r"^[0-9a-f]{64}$", read_canary_sha())), timeout_s=60, interval_s=4)
    sha_after = read_canary_sha()
    no_loss = bool(sha_before) and sha_after == sha_before

    M.record("Restore wall-time", f"{restore_s:.1f}s", f"<= {MAX_RESTORE_S}s", restored)
    M.record("Data integrity after restore (sha256)", "match" if no_loss else "MISMATCH", "match", no_loss)
    assert sha_after == sha_before, f"data loss: {sha_before[:12]}… → {(sha_after or 'none')[:12]}…"
