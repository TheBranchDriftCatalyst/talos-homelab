"""Cilium LB-IPAM + L2 announcement — disaster-recovery / chaos test  (TALOS-23l.3)

Validates the Cilium LoadBalancer IPAM design: a CiliumLoadBalancerIPPool hands VIPs to
type=LoadBalancer Services and a CiliumL2AnnouncementPolicy ARP-announces each VIP from one elected
node. When that node's announcer dies the lease must be re-elected and the VIP re-announced. This
suite MEASURES that VIP failover downtime — on a THROWAWAY canary VIP, never a production one.

READ-ONLY (always) asserts the LB-IPAM machinery EXISTS + is healthy. DESTRUCTIVE (armed: pytest
--destructive / CILIUM_LBIPAM_DR_DESTRUCTIVE=1) stands up a canary LoadBalancer in its OWN pool and
takes out the announcing node. The VIP-reachability probe curls the canary VIP over the LAN, so run
the destructive tier from a host on the same L2 segment.

Needs `kubectl` (context = the cluster) on PATH.
"""
import os
import re
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
POOL_KIND = "ciliumloadbalancerippools.cilium.io"
L2_KIND = "ciliuml2announcementpolicies.cilium.io"
KNOWN_POOL = os.environ.get("CILIUM_LBIPAM_POOL", "lan-pihole-pool")
KNOWN_L2 = os.environ.get("CILIUM_LBIPAM_L2", "lan-pihole-l2")
PROD_NS = os.environ.get("CILIUM_LBIPAM_PROD_NS", "pihole")
PROD_SVC = os.environ.get("CILIUM_LBIPAM_PROD_SVC", "pihole")
PROD_VIP = os.environ.get("CILIUM_LBIPAM_PROD_VIP", "192.168.1.240")
PROD_LEASE = os.environ.get("CILIUM_LBIPAM_PROD_LEASE", "cilium-l2announce-pihole-pihole")

CANARY_NS = os.environ.get("CILIUM_LBIPAM_CANARY_NS", "lbipam-dr")
CANARY_SVC = os.environ.get("CILIUM_LBIPAM_CANARY_SVC", "lbipam-canary")
CANARY_VIP = os.environ.get("CILIUM_LBIPAM_CANARY_VIP", "192.168.1.251")
CANARY_LEASE = os.environ.get("CILIUM_LBIPAM_CANARY_LEASE",
                              f"cilium-l2announce-{CANARY_NS}-{CANARY_SVC}")
CANARY_YAML = _HERE / "canary-lb.yaml"
CHAOS = os.environ.get("CILIUM_LBIPAM_CHAOS", "lease").lower()
MAX_FAILOVER_S = float(os.environ.get("CILIUM_LBIPAM_MAX_FAILOVER_S", "30"))
DESTRUCTIVE_ENV = "CILIUM_LBIPAM_DR_DESTRUCTIVE"

IPV4 = re.compile(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})")
M = dr.Metrics("Cilium LB-IPAM DR")


@pytest.fixture(autouse=True)
def _require_cluster():
    dr.require_cluster()


@pytest.fixture(scope="module", autouse=True)
def _summary():
    yield
    M.summary()


# ---- helpers ----
def names(kind):
    o = dr.kubectl(f"get {kind} -o name")
    return [ln.strip().split("/")[-1] for ln in o.splitlines() if ln.strip()]


def lb_services_with_ip():
    jp = ("jsonpath={range .items[?(@.spec.type=='LoadBalancer')]}"
          "{.metadata.namespace}/{.metadata.name}|{.status.loadBalancer.ingress[0].ip}{'\\n'}{end}")
    o = dr.kubectl(f'get svc -A -o "{jp}"')
    res = []
    for ln in filter(None, o.splitlines()):
        parts = (ln.split("|") + ["", ""])[:2]
        res.append({"svc": parts[0], "ip": parts[1].strip()})
    return res


def svc_external_ip(ns, name):
    return dr.kubectl(f"get svc {name} -n {ns} -o jsonpath={{.status.loadBalancer.ingress[0].ip}}")


def lease_holder(name):
    return dr.kubectl(f"get lease {name} -n kube-system -o jsonpath={{.spec.holderIdentity}}")


def lease_exists(name):
    return name in dr.kubectl(f"get lease {name} -n kube-system -o name")


def resolve_canary_lease():
    if lease_exists(CANARY_LEASE):
        return CANARY_LEASE
    o = dr.kubectl("get leases -n kube-system -o name")
    for ln in o.splitlines():
        n = ln.split("/")[-1]
        if "l2announce" in n and CANARY_SVC in n:
            return n
    return CANARY_LEASE


def vip_http_ok(vip, timeout_s=1):
    o = dr.sh(f'curl -s -o /dev/null -w "%{{http_code}}" --max-time {timeout_s} http://{vip}/',
              timeout=timeout_s + 2, check=False)
    return bool(re.match(r"^(2|3|4)\d\d$", o.strip()))


def create_canary():
    dr.kubectl(f"apply -f {CANARY_YAML}", check=True)
    dr.kubectl(f"rollout status deploy/{CANARY_SVC} -n {CANARY_NS} --timeout=120s")
    dr.wait_until(lambda: svc_external_ip(CANARY_NS, CANARY_SVC) == CANARY_VIP, timeout_s=120, interval_s=3)
    dr.wait_until(lambda: bool(lease_holder(resolve_canary_lease())), timeout_s=120, interval_s=3)


def delete_canary():
    dr.kubectl(f"delete -f {CANARY_YAML} --ignore-not-found --wait=false")


@pytest.fixture(scope="module")
def canary():
    if not dr.armed(DESTRUCTIVE_ENV):
        yield None
        return
    dr.require_cluster()
    create_canary()
    yield CANARY_SVC
    delete_canary()


# ---- READ-ONLY tier (always runs) ----
def test_lb_ippools_exist_and_known_pool_present():
    # fail loudly (not silently green) if Cilium CRDs are absent
    crds = dr.kubectl(f"get crd {POOL_KIND} {L2_KIND} -o name")
    assert "ippool" in crds, f"Cilium LB-IPAM CRDs not installed: {crds!r}"
    pools = names(POOL_KIND)
    assert len(pools) > 0, "no CiliumLoadBalancerIPPool exists"
    assert KNOWN_POOL in pools, f'known pool "{KNOWN_POOL}" absent (pools={pools})'
    conflict = dr.kubectl(
        f'get {POOL_KIND} {KNOWN_POOL} '
        f'-o jsonpath="{{.status.conditions[?(@.type==\'cilium.io/PoolConflict\')].status}}"')
    no_conflict = conflict != "True"
    M.record("CiliumLoadBalancerIPPools exist", len(pools), ">= 1", len(pools) > 0)
    assert no_conflict, f'pool "{KNOWN_POOL}" reports PoolConflict={conflict}'


def test_loadbalancer_service_has_external_ip():
    svcs = lb_services_with_ip()
    with_ip = [s for s in svcs if IPV4.search(s["ip"])]
    prod_ip = svc_external_ip(PROD_NS, PROD_SVC)
    M.record("LoadBalancer Services with external IP", len(with_ip), ">= 1", len(with_ip) > 0)
    M.record(f"Prod VIP {PROD_NS}/{PROD_SVC} allocated", prod_ip or "pending", PROD_VIP, prod_ip == PROD_VIP)
    assert len(with_ip) > 0, "no type=LoadBalancer Service has an allocated external IP"
    assert prod_ip == PROD_VIP, f"prod {PROD_NS}/{PROD_SVC} → {prod_ip or '(pending)'}, expected {PROD_VIP}"


def test_l2_policy_present_and_prod_vip_has_lease():
    pols = names(L2_KIND)
    assert len(pols) > 0, "no CiliumL2AnnouncementPolicy exists"
    assert KNOWN_L2 in pols, f'known L2 policy "{KNOWN_L2}" absent (policies={pols})'
    holder = lease_holder(PROD_LEASE)
    M.record("CiliumL2AnnouncementPolicies exist", len(pols), ">= 1", len(pols) > 0)
    M.record("Prod VIP has an active L2 announcer", holder or "none", "1 node", bool(holder))
    assert holder, f"prod VIP not announced (lease {PROD_LEASE} has no holder)"


# ---- DESTRUCTIVE tier (armed only; canary) ----
@pytest.mark.destructive
def test_t0_baseline_canary_vip_up(canary):
    dr.require_destructive(DESTRUCTIVE_ENV)
    ip = svc_external_ip(CANARY_NS, CANARY_SVC)
    lease = resolve_canary_lease()
    holder = lease_holder(lease)
    reachable = dr.wait_until(lambda: vip_http_ok(CANARY_VIP), timeout_s=30, interval_s=2)
    M.record("Canary VIP baseline (T0)", ip or "none", CANARY_VIP, ip == CANARY_VIP)
    assert ip == CANARY_VIP, f"canary VIP allocated {ip or '(pending)'}, expected {CANARY_VIP}"
    assert holder, "canary VIP has no L2 announcer at baseline"
    assert reachable, f"canary VIP {CANARY_VIP} does not answer HTTP over the LAN"


@pytest.mark.destructive
def test_failover_reannounces_and_measures_downtime(canary):
    dr.require_destructive(DESTRUCTIVE_ENV)
    lease = resolve_canary_lease()
    holder_before = lease_holder(lease)
    prod_holder_before = lease_holder(PROD_LEASE)

    probe = dr.Probe(lambda: vip_http_ok(CANARY_VIP), interval_s=0.25)
    time.sleep(1.5)
    t0 = time.time()
    if CHAOS == "lease":
        dr.kubectl(f"delete lease {lease} -n kube-system --wait=false")
    else:
        agent = dr.kubectl(
            f"get pods -n kube-system -l k8s-app=cilium "
            f"--field-selector spec.nodeName={holder_before} -o jsonpath={{.items[0].metadata.name}}")
        assert agent, f"no cilium-agent found on {holder_before}"
        dr.kubectl(f"delete pod {agent} -n kube-system --wait=false")

    holder_after = {"v": ""}

    def _reannounced():
        holder_after["v"] = lease_holder(lease) or lease_holder(resolve_canary_lease())
        if not holder_after["v"]:
            return False
        return holder_after["v"] != holder_before if CHAOS == "agent" else True

    reannounced = dr.wait_until(_reannounced, timeout_s=MAX_FAILOVER_S + 15, interval_s=1)
    reannounce_wall = time.time() - t0

    dr.wait_until(lambda: vip_http_ok(CANARY_VIP), timeout_s=30, interval_s=1)
    time.sleep(3)
    probe.stop()
    dt = probe.worst_downtime()

    moved = bool(holder_after["v"]) and holder_after["v"] != holder_before
    prod_holder_after = lease_holder(PROD_LEASE)
    prod_untouched = bool(prod_holder_after) and prod_holder_after == prod_holder_before

    M.record("VIP re-announce wall time", f"{reannounce_wall:.2f}s", f"<= {MAX_FAILOVER_S}s",
             reannounced and reannounce_wall <= MAX_FAILOVER_S + 15)
    M.record("VIP failover downtime (HTTP blip)", f"{dt:.2f}s", f"<= {MAX_FAILOVER_S}s", dt <= MAX_FAILOVER_S)
    M.record("Canary VIP availability during failover", f"{probe.availability() * 100:.1f}%", "-", reannounced)
    M.record("Prod VIP untouched (blast radius)", "untouched" if prod_untouched else "DISTURBED",
             "untouched", prod_untouched)

    assert reannounced, f"VIP not re-announced ({holder_before} → TIMEOUT)"
    if CHAOS == "agent":
        assert moved, "VIP did not move to a different node under 'agent' chaos"
    dr.assert_within(dt, MAX_FAILOVER_S, "VIP failover downtime")
    assert prod_untouched, f"prod VIP announcer disturbed: {prod_holder_before} → {prod_holder_after}"


@pytest.mark.destructive
def test_recovery_agent_self_heals(canary):
    dr.require_destructive(DESTRUCTIVE_ENV)

    def _healed():
        raw = dr.kubectl(
            'get ds cilium -n kube-system '
            '-o jsonpath="{.status.desiredNumberScheduled}/{.status.numberReady}"')
        desired, _, ready = raw.partition("/")
        return bool(desired) and desired == ready

    healed = dr.wait_until(_healed, timeout_s=180, interval_s=4)
    holder = lease_holder(resolve_canary_lease())
    M.record("cilium-agent self-heals", "yes" if healed else "no", "yes", healed)
    assert healed, "cilium DaemonSet did not become fully Ready again"
    assert holder, "canary VIP not single-announced after recovery (no lease holder)"
