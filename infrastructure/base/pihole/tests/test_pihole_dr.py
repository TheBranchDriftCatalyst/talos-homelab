"""Pi-hole HA disaster-recovery / chaos test  (TALOS-0nt.2)

Validates the StatefulSet + single-VIP (DNS+web, eTP:Local) + nebula-sync design and MEASURES
DNS failover downtime with a high-frequency background probe against the VIP.

Read-only checks always run (skipped when the cluster is unreachable). DESTRUCTIVE scenarios
(they delete pods) run only when armed:  pytest -m disaster_recovery --destructive   (or the
per-suite PIHOLE_DR_DESTRUCTIVE=1), so this can never disrupt DNS by accident.

Needs `kubectl` (context = the cluster) and `dig` on PATH for the DNS probe.
"""
import os
import re
import sys
import time
from pathlib import Path

import pytest

# make `from lib import dr` resolve for this co-located suite regardless of how pytest is invoked
_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pytest.ini").exists())
sys.path.insert(0, str(_ROOT / "tests"))

from lib import dr  # noqa: E402

pytestmark = pytest.mark.disaster_recovery

# ---- config (env-overridable, preserved from the Jest suite) ----
VIP = os.environ.get("PIHOLE_VIP", "192.168.1.240")
NS = os.environ.get("PIHOLE_NS", "pihole")
LEASE = os.environ.get("PIHOLE_LEASE", "cilium-l2announce-pihole-pihole")
PROBE_DOMAIN = os.environ.get("PIHOLE_PROBE_DOMAIN", "cloudflare.com")
SYNC_INTERVAL = int(os.environ.get("PIHOLE_SYNC_INTERVAL", "300"))
MAX_FAILOVER_S = float(os.environ.get("PIHOLE_MAX_FAILOVER_S", "5"))
MAX_NOIMPACT_S = float(os.environ.get("PIHOLE_MAX_NOIMPACT_S", "2"))
DESTRUCTIVE_ENV = "PIHOLE_DR_DESTRUCTIVE"

M = dr.Metrics("Pi-hole HA DR")


@pytest.fixture(autouse=True)
def _require_cluster():
    dr.require_cluster()


@pytest.fixture(scope="module", autouse=True)
def _summary():
    yield
    M.summary()


# ---- helpers ----
def dns_ok(timeout_s=1):
    out = dr.sh(f"dig +short +time={timeout_s} +tries=1 @{VIP} {PROBE_DOMAIN}",
                timeout=timeout_s + 2, check=False)
    return bool(re.search(r"\d+\.\d+\.\d+\.\d+", out))


def lease_holder():
    return dr.kubectl(f"get lease {LEASE} -n kube-system -o jsonpath={{.spec.holderIdentity}}")


def lease_count():
    out = dr.kubectl("get leases -n kube-system -o name")
    return len([ln for ln in out.splitlines() if "l2announce-pihole" in ln])


def pods():
    jp = ("jsonpath={range .items[*]}{.metadata.name}|{.spec.nodeName}|"
          "{.status.podIP}|{.status.phase}{'\\n'}{end}")
    out = dr.kubectl(f'get pods -n {NS} -l app=pihole -o "{jp}"')
    res = []
    for ln in filter(None, out.splitlines()):
        parts = (ln.split("|") + ["", "", "", ""])[:4]
        res.append({"name": parts[0], "node": parts[1], "ip": parts[2], "phase": parts[3]})
    return res


def active_pod():
    node = lease_holder()
    if not node:
        return None
    return next((p for p in pods() if p["node"] == node), None)


def ready_replicas():
    return dr.kubectl(f"get statefulset pihole -n {NS} -o jsonpath={{.status.readyReplicas}}")


def _await_healthy():
    dr.wait_until(lambda: ready_replicas() == "5", timeout_s=180, interval_s=3)


# ---- READ-ONLY tier (always runs) ----
def test_statefulset_5_5_ready():
    ready = ready_replicas()
    M.record("StatefulSet pihole 5/5 ready", ready, "5", ready == "5")
    assert ready == "5", f"readyReplicas={ready}"


def test_dns_resolves_via_vip():
    ok = dns_ok()
    M.record("DNS resolves via VIP", "yes" if ok else "no", "yes", ok)
    assert ok, f"dig @{VIP} {PROBE_DOMAIN} returned no A record"


def test_single_l2_lease_no_split_brain():
    n = lease_count()
    act = active_pod()
    M.record("L2 leases (split-brain check)", n, "= 1", n == 1)
    assert n == 1, f"expected exactly one l2announce-pihole lease, got {n}"
    assert act is not None, "active pod not resolvable from lease holder"


def test_pihole_hostname_resolves_to_vip():
    out = dr.sh(f"dig +short +time=2 +tries=1 @{VIP} pihole.talos00", timeout=6, check=False)
    assert VIP in out, f"pihole.talos00 → {out.strip() or '(no answer)'}"


# ---- DESTRUCTIVE tier (armed only) ----
@pytest.mark.destructive
def test_failover_delete_active_pod_measures_downtime():
    dr.require_destructive(DESTRUCTIVE_ENV)
    _await_healthy()
    before = active_pod()
    assert before is not None, "no active pod to kill"
    probe = dr.Probe(dns_ok, interval_s=0.2)
    time.sleep(1.2)
    dr.kubectl(f"delete pod {before['name']} -n {NS} --wait=false")
    recovered = dr.wait_until(dns_ok, timeout_s=120, interval_s=1)
    time.sleep(4)
    probe.stop()
    dt = probe.worst_downtime()
    M.record("Failover DNS downtime (active-pod kill)", f"{dt:.2f}s", f"<= {MAX_FAILOVER_S}s",
             recovered and dt <= MAX_FAILOVER_S)
    M.record("DNS availability during failover", f"{probe.availability() * 100:.1f}%", "-", recovered)
    assert recovered, "DNS did not recover after active-pod kill"
    dr.assert_within(dt, MAX_FAILOVER_S, "DNS failover downtime")
    assert lease_count() == 1, "split-brain: more than one L2 lease after failover"


@pytest.mark.destructive
def test_isolation_delete_standby_no_blip():
    dr.require_destructive(DESTRUCTIVE_ENV)
    _await_healthy()
    act = active_pod()
    standby = next((p for p in pods() if p["name"] != act["name"]), None)
    assert standby is not None, "no standby pod found"
    probe = dr.Probe(dns_ok, interval_s=0.2)
    time.sleep(1)
    dr.kubectl(f"delete pod {standby['name']} -n {NS} --wait=false")
    time.sleep(15)
    probe.stop()
    dt = probe.worst_downtime()
    M.record("Standby-kill DNS downtime", f"{dt:.2f}s", f"<= {MAX_NOIMPACT_S}s", dt <= MAX_NOIMPACT_S)
    dr.assert_within(dt, MAX_NOIMPACT_S, "DNS downtime on standby kill")


@pytest.mark.destructive
def test_isolation_kill_nebula_sync_zero_impact():
    dr.require_destructive(DESTRUCTIVE_ENV)
    _await_healthy()
    p = dr.kubectl(
        f"get pods -n {NS} -l app.kubernetes.io/component=config-sync "
        f"-o jsonpath={{.items[0].metadata.name}}")
    probe = dr.Probe(dns_ok, interval_s=0.2)
    time.sleep(1)
    dr.kubectl(f"delete pod {p} -n {NS} --wait=false")
    time.sleep(10)
    probe.stop()
    dt = probe.worst_downtime()
    healed = dr.wait_until(
        lambda: dr.kubectl(f"get deploy nebula-sync -n {NS} -o jsonpath={{.status.availableReplicas}}") == "1",
        timeout_s=90)
    M.record("nebula-sync-kill DNS downtime", f"{dt:.2f}s", f"<= {MAX_NOIMPACT_S}s", dt <= MAX_NOIMPACT_S)
    M.record("nebula-sync self-heals", "yes" if healed else "no", "yes", healed)
    dr.assert_within(dt, MAX_NOIMPACT_S, "DNS downtime on nebula-sync kill")
    assert healed, "nebula-sync did not self-heal"


@pytest.mark.destructive
def test_persistence_pvc_survives_restart():
    dr.require_destructive(DESTRUCTIVE_ENV)
    _await_healthy()
    act = active_pod()
    marker = f"/etc/pihole/dr-marker-{int(time.time() * 1000)}"
    dr.kubectl(f'exec {act["name"]} -n {NS} -c pihole -- sh -c "echo dr-test > {marker}"')
    dr.kubectl(f'delete pod {act["name"]} -n {NS} --wait=false')
    dr.kubectl(f'wait --for=condition=Ready pod/{act["name"]} -n {NS} --timeout=180s')
    time.sleep(2)
    found = dr.kubectl(
        f'exec {act["name"]} -n {NS} -c pihole -- sh -c "test -f {marker} && echo YES || echo NO"')
    dr.kubectl(f'exec {act["name"]} -n {NS} -c pihole -- rm -f {marker}')  # cleanup
    ok = "YES" in found
    M.record("PVC data survives pod restart", "YES" if ok else "NO", "YES", ok)
    assert ok, f"PVC data did not survive restart (marker → {found.strip()})"
