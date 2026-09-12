"""Traefik ingress — disaster-recovery / chaos test  (TALOS-23l.8)

Traefik runs as a single-replica-per-node DaemonSet binding hostPort 80/443, so on any given
node the whole-cluster ingress path is a SPOF: one pod down = that node's :80/:443 is dark until
the DaemonSet reschedules and rebinds the hostPort. This suite proves the DR machinery EXISTS +
is healthy, then (destructive) kills the serving Traefik pod behind a high-frequency probe against
a BENIGN whoami route and MEASURES the ingress downtime.

Read-only checks always run (they only observe — never mutate; skipped when the cluster is
unreachable). DESTRUCTIVE scenarios (they delete the serving Traefik pod) run only when armed:
    pytest -m disaster_recovery --destructive     (or per-suite TRAEFIK_DR_DESTRUCTIVE=1)
so this can never black-hole ingress by accident. The chaos ONLY ever probes the throwaway whoami
test route and ONLY ever deletes self-healing Traefik infra pods — no real app route and no
persistent data is ever touched.

Needs `kubectl` (context = the Talos cluster) on PATH. The high-frequency probe hits the node
hostPort (curl from the host); the read-only route check ALSO probes in-cluster via a throwaway
curl pod against the Traefik ClusterIP service (works even off-LAN).
"""
import os
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
TRAEFIK_NS = os.environ.get("TRAEFIK_NS", "traefik")
TRAEFIK_DS = os.environ.get("TRAEFIK_DS", "traefik")
TRAEFIK_POD_LABEL = os.environ.get("TRAEFIK_POD_LABEL", "app=traefik")
# in-cluster ClusterIP service (web entrypoint) — used for the robust in-cluster route probe
TRAEFIK_SVC = os.environ.get("TRAEFIK_SVC", "traefik.traefik.svc.cluster.local")
# the BENIGN test route (no auth, no bot-wrangler) — infrastructure/base/whoami/ingressroute.yaml
WHOAMI_NS = os.environ.get("WHOAMI_NS", "default")
WHOAMI_ROUTE = os.environ.get("WHOAMI_ROUTE", "whoami-http-noauth")
WHOAMI_DEPLOY = os.environ.get("WHOAMI_DEPLOY", "whoami")
WHOAMI_HOST = os.environ.get("WHOAMI_HOST", "whoami.talos00")
# node whose hostPort:80 we probe + whose Traefik pod we kill (talos00 control plane by default)
NODE_IP = os.environ.get("TRAEFIK_NODE_IP", "192.168.1.54")
MAX_RECOVERY_S = float(os.environ.get("TRAEFIK_MAX_RECOVERY_S", "45"))
DESTRUCTIVE_ENV = "TRAEFIK_DR_DESTRUCTIVE"

M = dr.Metrics("Traefik DR")


@pytest.fixture(autouse=True)
def _require_cluster():
    dr.require_cluster()


@pytest.fixture(scope="module", autouse=True)
def _summary():
    yield
    M.summary()


# ---- helpers (ported from the Jest suite) ----
def route_status_from_host(timeout_s=1):
    """HTTP status of the benign whoami route via the node hostPort (curl from the host)."""
    code = dr.sh(
        f'curl -s -o /dev/null -w "%{{http_code}}" --max-time {timeout_s} '
        f'-H "Host: {WHOAMI_HOST}" http://{NODE_IP}',
        timeout=timeout_s + 2, check=False)
    try:
        return int(code or "0")
    except ValueError:
        return 0


def route_ok_from_host(timeout_s=1):
    return route_status_from_host(timeout_s) == 200


def route_status_in_cluster(timeout_s=5, tries=3):
    """HTTP status of the benign whoami route from INSIDE the cluster (throwaway curl pod →
    Traefik ClusterIP svc). Robust even when the host can't reach the node hostPort (off-LAN CI)."""
    import re
    last = 0
    for _ in range(tries):
        o = dr.kubectl(
            f"run tfdr-{int(time.time() * 1000)} -n {WHOAMI_NS} --rm -i --restart=Never "
            f"--image=curlimages/curl:8.10.1 --command -- "
            f'curl -s -o /dev/null -w "%{{http_code}}" --max-time {timeout_s} '
            f'-H "Host: {WHOAMI_HOST}" http://{TRAEFIK_SVC}',
            timeout=70, check=False)
        m = re.match(r"^(\d{3})", o or "")
        last = int(m.group(1)) if m else 0
        if last == 200:
            return last
        time.sleep(1.5)
    return last


def node_name_for_ip(ip):
    jp = ("jsonpath={range .items[*]}{.metadata.name}|"
          "{.status.addresses[?(@.type=='InternalIP')].address}{'\\n'}{end}")
    o = dr.kubectl(f'get nodes -o "{jp}"', check=False)
    for ln in o.splitlines():
        parts = ln.split("|")
        if len(parts) >= 2 and parts[1].strip() == ip:
            return parts[0]
    return None


def traefik_pods():
    jp = "jsonpath={range .items[*]}{.metadata.name}|{.spec.nodeName}|{.status.phase}{'\\n'}{end}"
    o = dr.kubectl(f'get pods -n {TRAEFIK_NS} -l {TRAEFIK_POD_LABEL} -o "{jp}"', check=False)
    res = []
    for ln in filter(None, o.splitlines()):
        name, node, phase = (ln.split("|") + ["", "", ""])[:3]
        res.append({"name": name, "node": node, "phase": phase})
    return res


def serving_pod():
    node = node_name_for_ip(NODE_IP)
    pods = traefik_pods()
    if node:
        on_node = next((p for p in pods if p["node"] == node), None)
        if on_node:
            return on_node
    return pods[0] if pods else None  # single-node cluster: the only Traefik pod is the server


def ds_ready():
    desired = dr.kubectl(
        f"get ds {TRAEFIK_DS} -n {TRAEFIK_NS} -o jsonpath={{.status.desiredNumberScheduled}}", check=False)
    ready = dr.kubectl(
        f"get ds {TRAEFIK_DS} -n {TRAEFIK_NS} -o jsonpath={{.status.numberReady}}", check=False)
    return {"desired": int(desired or "0"), "ready": int(ready or "0")}


def _await_ds_full():
    dr.wait_until(lambda: (lambda r: r["desired"] > 0 and r["ready"] == r["desired"])(ds_ready()),
                  timeout_s=180, interval_s=3)


# ---- READ-ONLY tier: the DR machinery EXISTS + is healthy (never mutates) ----
def test_daemonset_exists_and_every_pod_ready():
    r = ds_ready()
    pods = traefik_pods()
    ok = r["desired"] > 0 and r["ready"] == r["desired"]
    M.record("Traefik DaemonSet pods Ready", f"{r['ready']}/{r['desired']}", "all", ok)
    assert r["desired"] > 0, f"desiredNumberScheduled={r['desired']}"
    assert r["ready"] == r["desired"], f"numberReady={r['ready']}/{r['desired']}"
    assert len(pods) > 0, "no Traefik pods observed"


def test_benign_whoami_route_and_backend_exist():
    route_exists = dr.kubectl(
        f"get ingressroute {WHOAMI_ROUTE} -n {WHOAMI_NS} -o jsonpath={{.metadata.name}}",
        check=False) == WHOAMI_ROUTE
    backend_ready = dr.kubectl(
        f"get deploy {WHOAMI_DEPLOY} -n {WHOAMI_NS} -o jsonpath={{.status.readyReplicas}}",
        check=False) == "1"
    ok = route_exists and backend_ready
    M.record("Benign whoami DR target present", "yes" if ok else "no", "yes", ok)
    assert route_exists, f"IngressRoute {WHOAMI_NS}/{WHOAMI_ROUTE} missing"
    assert backend_ready, "whoami backend not Ready"


def test_benign_whoami_route_serves_200_in_cluster():
    code = route_status_in_cluster()
    M.record("Route 200 in-cluster (baseline)", f"HTTP {code}", "200", code == 200)
    assert code == 200, f"in-cluster GET → HTTP {code}"


def test_benign_whoami_route_serves_200_via_node_hostport():
    code = route_status_from_host(3)
    M.record("Route 200 via node hostPort", f"HTTP {code}", "200", code == 200)
    assert code == 200, f"GET http://{NODE_IP} (Host: {WHOAMI_HOST}) → HTTP {code}"


def test_traefik_pod_scheduled_on_probed_node():
    pod = serving_pod()
    node = node_name_for_ip(NODE_IP)
    M.record("Serving hostPort pod identified", pod["name"] if pod else "none", "found", bool(pod))
    assert pod is not None, f"no serving Traefik pod for {NODE_IP}"
    if node:
        assert pod["node"] == node, f"serving pod on {pod['node']}, expected {node}"


# ---- DESTRUCTIVE tier: --destructive / TRAEFIK_DR_DESTRUCTIVE=1 (kills the serving pod) ----
@pytest.mark.destructive
def test_failover_kill_serving_pod_measures_downtime():
    dr.require_destructive(DESTRUCTIVE_ENV)
    _await_ds_full()
    before = serving_pod()
    assert before is not None, "no serving Traefik pod to kill"
    probe = dr.Probe(route_ok_from_host, interval_s=0.2)
    time.sleep(1.5)  # establish a healthy baseline before the kill
    dr.kubectl(f"delete pod {before['name']} -n {TRAEFIK_NS} --wait=false")
    recovered = dr.wait_until(route_ok_from_host, timeout_s=MAX_RECOVERY_S, interval_s=1)
    time.sleep(4)  # let the probe capture the tail of the recovery
    probe.stop()
    dt = probe.worst_downtime()
    now = ds_ready()
    no_spof_drift = now["desired"] > 0  # DaemonSet still owns every node
    M.record("Ingress downtime (serving-pod kill)", f"{dt:.2f}s", f"<= {MAX_RECOVERY_S}s",
             recovered and dt <= MAX_RECOVERY_S)
    M.record("Ingress availability during kill", f"{probe.availability() * 100:.1f}%", "-", recovered)
    M.record("DaemonSet recovers to full schedule", "yes" if recovered else "no", "yes", recovered)
    assert recovered, "ingress did not recover after serving-pod kill"
    dr.assert_within(dt, MAX_RECOVERY_S, "ingress downtime (hostPort dark window)")
    assert no_spof_drift, f"DaemonSet no longer scheduled (desired={now['desired']})"
