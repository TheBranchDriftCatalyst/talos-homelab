"""VPN gateway/rotator — chaos/DR test  (companion to the Pi-hole DR suite)

Validates the gluetun + ProtonVPN rotator system: exit traffic goes through the VPN (never the
home WAN), rotation changes the exit IP WITHOUT restarting the consuming app pods, the kill-switch
holds when the tunnel drops (no leak), and it recovers.

Read-only checks always run (skipped when the cluster is unreachable). DESTRUCTIVE scenarios
(kill containers / force a rotation) run only when armed:
    pytest -m disaster_recovery --destructive     (or per-suite VPN_DR_DESTRUCTIVE=1)
so they can't disrupt egress by accident.

Needs `kubectl` (context = the cluster) on PATH. Probes run through pods (the proxy is in-cluster
only). Exit-IP truth = actual egress (gluetun's control-API public_ip is empty).
"""
import base64
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
NS = os.environ.get("VPN_NS", "vpn-gateway")
PROXY = os.environ.get("VPN_PROXY", "http://gluetun.vpn-gateway.svc.cluster.local:8080")
HOME_WAN = os.environ.get("VPN_HOME_WAN", "108.64.138.156")  # a home-WAN egress = LEAK
MAX_ROTATION_DOWNTIME_S = float(os.environ.get("VPN_MAX_ROTATION_S", "20"))
MAX_RECOVERY_S = float(os.environ.get("VPN_MAX_RECOVERY_S", "90"))
DESTRUCTIVE_ENV = "VPN_DR_DESTRUCTIVE"
# exit surfaces (per-pod sidecars). gluetun-exporter (busybox) shares the pod netns + has wget.
SIDECAR = {"deploy": "securexng", "probeContainer": "gluetun-exporter", "vpnContainer": "gluetun"}

CANARY = "vpn-canary"
CANARY_YAML = str(Path(__file__).resolve().parent / "canary-pod.yaml")
IPV4 = re.compile(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})")

M = dr.Metrics("VPN DR")


@pytest.fixture(autouse=True)
def _require_cluster():
    dr.require_cluster()


def _armed():
    return dr.armed(DESTRUCTIVE_ENV)


@pytest.fixture(scope="module", autouse=True)
def _canary_lifecycle():
    """Spin up the ad-hoc VPN canary (chaos target — real services stay untouched) when armed."""
    created = False
    if _armed() and dr.cluster_reachable():
        create_canary()
        created = True
    yield
    if created:
        delete_canary()
    M.summary()


# ---- helpers (ported from the Jest suite) ----
def is_public_ipv4(ip):
    return bool(re.match(r"^\d+\.\d+\.\d+\.\d+$", ip or "")) and not re.match(
        r"^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|127\.)", ip or "")


def first_pod(deploy):
    n = dr.kubectl(f"get pods -n {NS} -l app={deploy} -o jsonpath={{.items[0].metadata.name}}", check=False)
    if n:
        return n
    return dr.sh(f"kubectl get pods -n {NS} -o name | grep {deploy} | head -1 | cut -d/ -f2", check=False)


def restart_count(pod, container):
    n = dr.kubectl(
        f'get pod {pod} -n {NS} -o jsonpath="{{.status.containerStatuses[?(@.name==\'{container}\')].restartCount}}"',
        check=False)
    try:
        return int(n or "-1")
    except ValueError:
        return -1


def pod_ready(pod):
    return dr.kubectl(
        f'get pod {pod} -n {NS} -o jsonpath="{{.status.conditions[?(@.type==\'Ready\')].status}}"',
        check=False) == "True"


def proxy_exit_ip(tries=3):
    """Exit IP as seen THROUGH the shared HTTP proxy (throwaway curl pod — proxy is in-cluster only)."""
    for _ in range(tries):
        o = dr.kubectl(
            f"run vpndr-{int(time.time() * 1000)} -n {NS} --rm -i --restart=Never "
            f"--image=curlimages/curl:8.10.1 --command -- "
            f"curl -s --max-time 15 -x {PROXY} https://api.ipify.org",
            check=False, timeout=70)
        m = IPV4.search(o or "")
        if m:
            return m.group(1)
        time.sleep(1.5)
    return ""


def pod_egress_ip(pod, container):
    o = dr.kubectl(
        f'exec {pod} -n {NS} -c {container} -- sh -c '
        f'"wget -qO- --timeout=3 http://api.ipify.org 2>/dev/null || true"',
        check=False, timeout=20)
    m = IPV4.search(o or "")
    return m.group(1) if m else ""


def vpn_running(pod):
    o = dr.kubectl(
        f'exec {pod} -n {NS} -c gluetun -- sh -c '
        f'"wget -qO- --timeout=5 http://localhost:8000/v1/vpn/status 2>/dev/null || true"',
        check=False, timeout=20)
    return "running" in o


# ---- ad-hoc canary (destructive chaos target — real services untouched) ----
def canary_egress_ip():
    o = dr.kubectl(
        f'exec {CANARY} -n {NS} -c probe -- sh -c '
        f'"wget -qO- --timeout=4 http://api.ipify.org 2>/dev/null || true"',
        check=False, timeout=25)
    m = IPV4.search(o or "")
    return m.group(1) if m else ""


def canary_tunnel_up():
    o = dr.kubectl(
        f'exec {CANARY} -n {NS} -c gluetun -- sh -c '
        f'"wget -qO- --timeout=5 http://localhost:8000/v1/vpn/status 2>/dev/null || true"',
        check=False, timeout=20)
    return "running" in o


def create_canary():
    dr.kubectl(f"apply -f {CANARY_YAML}", check=False)
    dr.kubectl(f"wait --for=condition=Ready pod/{CANARY} -n {NS} --timeout=120s", check=False, timeout=140)
    dr.wait_until(canary_tunnel_up, timeout_s=120, interval_s=4)
    dr.wait_until(lambda: (lambda ip: is_public_ipv4(ip) and ip != HOME_WAN)(canary_egress_ip()),
                  timeout_s=120, interval_s=4)


def delete_canary():
    dr.kubectl(f"delete pod {CANARY} -n {NS} --ignore-not-found --wait=false", check=False)


def rotate_canary():
    """Rotate the canary to a different ProtonVPN country via ITS OWN control API (as the real
    rotator does). Belgium→India: both keys unused by real pods, so no duplicate-connection conflict."""
    in_key = base64.b64decode(dr.kubectl(
        f"get secret protonvpn-credentials -n {NS} -o jsonpath={{.data.se-in-1}}", check=False)
        or "").decode().strip()
    ip = dr.kubectl(f"get pod {CANARY} -n {NS} -o jsonpath={{.status.podIP}}")
    import json
    body = json.dumps({"wireguard": {"private_key": in_key},
                       "provider": {"server_selection": {"countries": ["India"]}}})
    dr.kubectl(
        f"run rot-{int(time.time() * 1000)} -n {NS} --rm -i --restart=Never "
        f"--image=curlimages/curl:8.10.1 --command -- "
        f"curl -s -X PUT --max-time 15 --data '{body}' http://{ip}:8000/v1/vpn/settings",
        check=False, timeout=45)


# ---- READ-ONLY tier (always runs) ----
def test_gateway_tunnel_up():
    pod = first_pod("gluetun")
    up = vpn_running(pod)
    M.record("Gateway tunnel up", "yes" if up else "no", "yes", up)
    assert up, f"gluetun VPN status != running (pod {pod})"


def test_proxy_egress_is_vpn_not_home_wan():
    ip = proxy_exit_ip()
    ok = is_public_ipv4(ip) and ip != HOME_WAN
    M.record("Proxy exit IP is VPN (not home WAN)", ip or "none", f"!= {HOME_WAN}", ok)
    assert ip != HOME_WAN, f"proxy exit IP is the HOME WAN — LEAK ({ip})"
    assert is_public_ipv4(ip), f"proxy exit IP not a public IPv4: {ip or '(none)'}"


def test_secure_chrome_excluded_from_rotation():
    rot = dr.kubectl(
        f'get deploy secure-chrome -n {NS} '
        f'-o jsonpath="{{.spec.template.metadata.labels.vpn-gateway\\.io/rotation}}"', check=False)
    M.record("secure-chrome excluded from rotation", rot, "disabled", rot == "disabled")
    assert rot == "disabled", f"secure-chrome rotation label = {rot}"


def test_every_gluetun_pod_carries_stale_route_cleanup():
    """table-51820 cleanup must exist on every gluetun workload [TALOS-4qwy]."""
    import json
    deps = json.loads(dr.kubectl(f"get deploy -n {NS} -o json", check=False) or '{"items":[]}')
    gluetun_deps = [d for d in deps["items"]
                    if any(c.get("name") == "gluetun"
                           for c in d["spec"]["template"]["spec"].get("containers", []))]
    all_ok = len(gluetun_deps) > 0
    for d in gluetun_deps:
        spec = d["spec"]["template"]["spec"]
        init_ok = any("51820" in json.dumps(c.get("command", ""))
                      for c in spec.get("initContainers", []))
        g = next(c for c in spec["containers"] if c["name"] == "gluetun")
        prestop_ok = bool(g.get("lifecycle", {}).get("preStop"))
        all_ok = all_ok and init_ok and prestop_ok
    M.record("gluetun pods have stale-route cleanup",
             f"all {len(gluetun_deps)}" if all_ok else "MISSING", "all", all_ok)
    assert all_ok, "not every gluetun workload carries the table-51820 cleanup (init + preStop)"


def test_no_gluetun_pod_crash_looping():
    """bounded gluetun restart rate — a table-51820 crashloop spikes it [TALOS-4qwy]."""
    import json
    max_rate = float(os.environ.get("VPN_MAX_RESTART_RATE", "5"))  # restarts/day
    pods = json.loads(dr.kubectl(f"get pods -n {NS} -o json", check=False) or '{"items":[]}')
    worst, all_ok, seen = 0.0, True, 0
    now_ms = time.time() * 1000
    for p in pods["items"]:
        cs = next((c for c in p["status"].get("containerStatuses", []) if c["name"] == "gluetun"), None)
        if not cs:
            continue
        seen += 1
        start = p["status"].get("startTime")
        start_ms = _iso_ms(start) if start else now_ms
        age_days = max((now_ms - start_ms) / 86400000, 1 / 24)  # floor at 1h
        rate = cs["restartCount"] / age_days
        all_ok = all_ok and rate < max_rate
        worst = max(worst, rate)
    M.record("gluetun restart rate (worst pod)", f"{worst:.2f}/day", f"< {max_rate}/day", all_ok)
    assert seen > 0, "no gluetun containers observed"
    assert all_ok, f"a gluetun pod exceeds {max_rate} restarts/day (worst {worst:.2f})"


def _iso_ms(iso):
    from datetime import datetime, timezone
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc).timestamp() * 1000


# ---- DESTRUCTIVE tier (armed only) ----
@pytest.mark.destructive
def test_t0_baseline_canary_egress_is_vpn():
    dr.require_destructive(DESTRUCTIVE_ENV)
    ip = [""]

    def _ready():
        x = canary_egress_ip()
        if is_public_ipv4(x) and x != HOME_WAN:
            ip[0] = x
            return True
        return False

    dr.wait_until(_ready, timeout_s=30, interval_s=3)
    tunnel_up = canary_tunnel_up()
    vpn_ok = is_public_ipv4(ip[0]) and ip[0] != HOME_WAN
    M.record("Canary baseline egress (T0)", ip[0] or "none", f"!= {HOME_WAN}", vpn_ok)
    assert tunnel_up, "canary tunnel not up (control API != running)"
    assert vpn_ok, f"canary egress not a public VPN IP: {ip[0] or 'none'}"


@pytest.mark.destructive
def test_rotation_does_not_disrupt_canary_app_container():
    dr.require_destructive(DESTRUCTIVE_ENV)
    before = canary_egress_ip()
    rc_before = restart_count(CANARY, "probe")
    rotate_canary()
    after = [""]

    def _rotated():
        ip = canary_egress_ip()
        if is_public_ipv4(ip) and ip != HOME_WAN:
            after[0] = ip
            return True
        return False

    dr.wait_until(_rotated, timeout_s=120, interval_s=4)
    rc_after = restart_count(CANARY, "probe")
    vpn_ok = is_public_ipv4(after[0]) and after[0] != HOME_WAN
    no_restart = rc_after == rc_before
    M.record("Rotation keeps a VPN exit", after[0] or "none", f"!= {HOME_WAN}", vpn_ok)
    M.record("Rotation does NOT restart the app", rc_after - rc_before, 0, no_restart)
    assert vpn_ok, f"exit IP not a VPN IP after rotation: {before} → {after[0]}"
    assert no_restart, f"app container restarted by rotation ({rc_before} → {rc_after})"


@pytest.mark.destructive
def test_kill_switch_holds_no_home_wan_leak():
    dr.require_destructive(DESTRUCTIVE_ENV)
    # kill gluetun PID 1 → container exits + restarts; the pod netns (kill-switch iptables) persists
    dr.kubectl(f'exec {CANARY} -n {NS} -c gluetun -- sh -c "kill 1"', check=False)
    leaked, samples = False, 0
    for _ in range(12):
        ip = canary_egress_ip()  # "" = blocked (good)
        samples += 1
        if ip == HOME_WAN:
            leaked = True
            break
        time.sleep(1)
    M.record("Kill-switch: no home-WAN leak", "LEAK" if leaked else "held", "held", not leaked)
    assert not leaked, f"home-WAN leak during tunnel outage ({samples} samples)"


@pytest.mark.destructive
def test_recovery_canary_vpn_egress_restored():
    dr.require_destructive(DESTRUCTIVE_ENV)
    t0 = time.time()
    recovered = dr.wait_until(
        lambda: (lambda ip: is_public_ipv4(ip) and ip != HOME_WAN)(canary_egress_ip()),
        timeout_s=MAX_RECOVERY_S, interval_s=3)
    dt = time.time() - t0
    restarts = restart_count(CANARY, "gluetun")
    M.record("VPN egress recovery time", f"{dt:.1f}s", f"<= {MAX_RECOVERY_S}s", recovered)
    assert recovered, "canary VPN egress did not recover after the kill"
    dr.assert_within(dt, MAX_RECOVERY_S, "VPN egress recovery time")
    assert 0 <= restarts < 10, f"gluetun crash-loop suspected (restarts={restarts})"
