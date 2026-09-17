"""VPN rotation soak — repeated REAL rotations against the throwaway canary, measuring
how long the tunnel is actually DOWN each time.

WHY A SOAK AND NOT A SINGLE PASS/FAIL: three separate rotator bugs were found in one
day (2026-09-17), all presenting as the same symptom (Job BackoffLimitExceeded, or an
app stalled behind a dead tunnel):

  1. validation gated on gluetun /v1/publicip/ip, which returns EMPTY on this cluster,
     so every rotation false-failed and cooled down a healthy server     (TALOS-1gp)
  2. the validation budget was 5x3s=15s -- shorter than a real tunnel rebuild, so a
     fast pod passed and a slow one "failed"                             (8fc2c9ca)
  3. gluetun can WEDGE in status="stopping" after a settings PUT and never rebuild
     the tunnel at all, needing a pod delete to recover                  (TALOS-z16b)

A single rotation test catches none of these reliably: #2 and #3 are timing- and
luck-dependent, and #1 looked like a server-side problem. What separates them is the
DOWNTIME DISTRIBUTION over many rotations -- a healthy rotation dips for seconds, a
wedge never returns. So this measures per-cycle downtime instead of asserting a bool.

Chaos lands ONLY on the ad-hoc canary pod, whose se-be-1/se-in-1 keys are unused by
the real pods (no ProtonVPN duplicate-connection conflict). Real VPN traffic is
untouched.

    task test:vpn-rotation                      # or:
    pytest infrastructure/base/vpn-gateway/tests/test_vpn_rotation_soak.py --destructive
    VPN_SOAK_CYCLES=20 pytest ... --destructive # longer soak
"""
import base64
import json
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

NS = os.environ.get("VPN_NS", "vpn-gateway")
CANARY = "vpn-canary"
CANARY_YAML = str(Path(__file__).resolve().parent / "canary-pod.yaml")
DESTRUCTIVE_ENV = "VPN_DR_DESTRUCTIVE"

SOAK_CYCLES = int(os.environ.get("VPN_SOAK_CYCLES", "5"))
# Per-rotation downtime we are willing to accept. Generous: the goal is to catch
# wedges and regressions, not to police a few seconds of reconnect.
MAX_ROTATION_DOWNTIME_S = float(os.environ.get("VPN_MAX_ROTATION_S", "90"))
# Past this, the tunnel is not slow -- it is wedged (bug 3 above sat here indefinitely).
WEDGE_AFTER_S = float(os.environ.get("VPN_WEDGE_AFTER_S", "180"))
POLL_S = 2.0

# The canary cycles between the two keys no real pod uses. se-nl-1 (gateway,
# qBittorrent) and se-de-1 (securexng, secure-chrome) are deliberately excluded --
# reusing a live key risks ProtonVPN refusing the duplicate connection and would make
# a harness failure indistinguishable from a real one.
TARGETS = [("se-be-1", "Belgium"), ("se-in-1", "India")]

IPV4 = re.compile(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})")
M = dr.Metrics("VPN rotation soak")


@pytest.fixture(autouse=True)
def _require_cluster():
    dr.require_cluster()


def _armed():
    return dr.armed(DESTRUCTIVE_ENV)


# ---- canary plumbing -------------------------------------------------------------

def _ctl(path, timeout=15):
    """Read the canary's own gluetun control API from the probe sidecar (shares the
    tunnel netns), so no extra pod is spawned per poll."""
    out = dr.kubectl(
        f'exec {CANARY} -n {NS} -c gluetun -- sh -c '
        f'"wget -qO- --timeout=5 http://localhost:8000{path} 2>/dev/null || true"',
        check=False, timeout=timeout)
    try:
        return json.loads(out)
    except Exception:
        return None


def status():
    return (_ctl("/v1/vpn/status") or {}).get("status", "unreachable")


def egress_ip(tries=2):
    """EXTERNAL connectivity through the tunnel. This is the property that matters --
    status=running only reports what gluetun believes about itself, and bug 3 showed
    those can disagree."""
    # http:// on purpose -- the probe sidecar is busybox, whose wget has no TLS support.
    # Mirrors canary_egress_ip() in test_vpn_dr.py rather than inventing a second probe.
    for _ in range(tries):
        out = dr.kubectl(
            f'exec {CANARY} -n {NS} -c probe -- sh -c '
            f'"wget -qO- --timeout=4 http://api.ipify.org 2>/dev/null || true"',
            check=False, timeout=25) or ""
        m = IPV4.search(out)
        if m:
            return m.group(1)
    return ""


def healthy():
    return status() == "running" and bool(egress_ip())


def public_country(tries=6, delay=5):
    """Country of the current exit, per gluetun's OWN geo lookup.

    /v1/publicip/ip is EMPTY until the IP getter completes -- that lag is the whole
    reason validation must not gate on it (TALOS-1gp) -- so this polls rather than
    reading once. Used only to confirm a rotation landed in the requested country;
    never to decide whether the tunnel is up.
    """
    for _ in range(tries):
        d = _ctl("/v1/publicip/ip") or {}
        if d.get("country"):
            return d["country"]
        time.sleep(delay)
    return ""


def gluetun_tail(n=14):
    return dr.kubectl(f"logs -n {NS} {CANARY} -c gluetun --tail={n}", check=False, timeout=30) or ""


def rotate(key, country):
    """Send the SAME payload the real rotator sends -- including "names": [].

    Kept deliberately in sync with rotate_pod() in rotation/configmap-script.yaml. An
    earlier copy of this helper omitted "names", which is the very field whose absence
    caused the qBittorrent outage; a soak using the stale payload would exercise a code
    path nobody actually runs. test_rotator_payload_clears_names guards the pairing."""
    b64 = dr.kubectl(
        f"get secret protonvpn-credentials -n {NS} -o jsonpath={{.data.{key}}}", check=False)
    wg = base64.b64decode(b64 or "").decode().strip()
    body = json.dumps({
        "wireguard": {"private_key": wg},
        "provider": {"server_selection": {"countries": [country], "names": []}},
    })
    # via a file inside the pod so the private key never lands in a shell command line
    out = dr.kubectl(
        f"exec -n {NS} {CANARY} -c gluetun -- sh -c "
        f"\"printf '%s' '{body}' > /tmp/rot.json && "
        f"wget -qO- --timeout=20 --method=PUT --body-file=/tmp/rot.json "
        f"--header='Content-Type: application/json' "
        f"http://127.0.0.1:8000/v1/vpn/settings\"", check=False, timeout=50)
    return out


def create_canary():
    dr.kubectl(f"apply -f {CANARY_YAML}", check=False, timeout=60)
    dr.kubectl(f"wait --for=condition=Ready pod/{CANARY} -n {NS} --timeout=150s",
               check=False, timeout=170)
    dr.wait_until(healthy, timeout_s=180, interval_s=4)


def delete_canary():
    dr.kubectl(f"delete pod {CANARY} -n {NS} --ignore-not-found --wait=false", check=False)


@pytest.fixture(scope="module", autouse=True)
def _canary_lifecycle():
    created = False
    if _armed() and dr.cluster_reachable():
        create_canary()
        created = True
    yield
    if created:
        delete_canary()
    M.summary()


# ---- READ-ONLY tier (always runs) ------------------------------------------------

def test_rotator_payload_clears_names():
    """Regression guard for the original outage: rotate_pod() MUST clear `names`
    whenever it changes `countries`.

    Server names are country-specific, so a pinned SERVER_NAMES becomes unsatisfiable
    the instant the country moves -- qBittorrent pinned NL#316,... and a rotation to
    India produced "country India AND names NL#... AND port_forward_only", which
    matches no server. gluetun then retried every 30s until its liveness probe killed
    the container, 37 restarts deep. Cheap static check; no cluster mutation."""
    script = (Path(__file__).resolve().parents[1] / "rotation" / "configmap-script.yaml").read_text()
    payload = re.search(r"payload = json\.dumps\((\{.*?\})\)\.encode\(\)", script, re.S)
    assert payload, "could not locate the rotation payload in configmap-script.yaml"
    body = payload.group(1)
    assert '"countries"' in body, "payload no longer sets countries -- did the shape change?"
    ok = '"names": []' in body
    M.record("rotate payload clears names", ok, True, ok)
    assert ok, (
        "rotate_pod() sets countries without clearing names. Any pod pinning "
        "SERVER_NAMES will get an unsatisfiable filter on the next country change."
    )


def test_rotator_does_not_gate_on_public_ip():
    """Regression guard for TALOS-1gp: validation must NOT fail on an empty
    /v1/publicip/ip. That endpoint returns "" on this cluster even when the tunnel is
    fully healthy, so gating on it false-failed every rotation, poisoned the persisted
    failed_servers map, and exited the Job 1 every 35 minutes."""
    script = (Path(__file__).resolve().parents[1] / "rotation" / "configmap-script.yaml").read_text()
    ok = "no public IP yet" not in script
    M.record("validation not gated on public IP", ok, True, ok)
    assert ok, "validate_vpn_connection() is failing on empty public_ip again (TALOS-1gp)"


# ---- DESTRUCTIVE tier (armed only) -----------------------------------------------

@pytest.mark.destructive
@pytest.mark.skip(reason=(
    "KNOWN-UNSOUND: verifies the landed country via /v1/publicip/ip, which is empty "
    "exactly in the post-rotation window this polls -- so it reports '?' and then "
    "mis-scores healthy rotations as NO-SWITCH. Parse gluetun's '[ip getter] Public IP "
    "address is X (Country, ...)' log line instead. Also needs >2 spare ProtonVPN keys "
    "so the canary can always target a country it is not already in. "
    "The two read-only guards above are sound and DO run."))
def test_rotation_soak_downtime():
    """Rotate the canary SOAK_CYCLES times, measuring real external-connectivity
    downtime per rotation and dumping gluetun logs on any wedge."""
    dr.require_destructive(DESTRUCTIVE_ENV)

    assert healthy(), f"canary unhealthy before soak: status={status()}"
    base = egress_ip()
    print(f"\n  baseline egress={base} status={status()}  cycles={SOAK_CYCLES}")

    downtimes, wedges, no_switch = [], [], []
    for i in range(SOAK_CYCLES):
        # Target must differ from the CURRENT country. A fixed alternating list does
        # not guarantee that: the canary boots in Belgium (SERVER_COUNTRIES in
        # canary-pod.yaml) and a list starting at Belgium asks gluetun to move where
        # it already is -- largely a no-op, so nothing changes and the cycle merely
        # looks stuck. Observed directly: cycles 1 and 3 both requested Belgium while
        # already in Belgium; 1 "failed" and 3 passed only because gluetun happened
        # to pick a different Belgian server.
        here = public_country()
        key, country = next((k, c) for k, c in TARGETS if c.lower() != (here or "").lower())
        before = egress_ip()
        print(f"\n  --- cycle {i+1}/{SOAK_CYCLES}: {here or '?'} -> {country} ({key}), from ip {before or '?'}")

        t0 = time.time()
        rotate(key, country)

        # Recovery means: gluetun reports running AND its own geolocation says we are
        # in the country we asked for. "Exit IP changed" is NOT sufficient -- two
        # servers in one country have different exit IPs, so an intra-country hop
        # satisfies it while the rotation has not actually honoured the request. A
        # 6-cycle run scored 6/6 green that way while every exit stayed in
        # 146.70.142.0/24 (ProtonVPN Mumbai), including the cycles asking for Belgium.
        recovered, wedged, seen, now_ip, landed = None, False, set(), "", ""
        while True:
            el = time.time() - t0
            st = status()
            seen.add(st)
            if st == "running":
                now_ip = egress_ip(tries=1)
                landed = (_ctl("/v1/publicip/ip") or {}).get("country", "") or ""
                if landed and landed.lower() == country.lower():
                    recovered = el
                    break
            if el > WEDGE_AFTER_S:
                wedged = True
                break
            time.sleep(POLL_S)

        # Distinguish the two timeout modes. They look identical in a pass/fail
        # summary and have completely different causes:
        #   WEDGED    - gluetun never returned to "running" (the TALOS-z16b deadlock;
        #               observed sitting in "stopping" for 2+ min needing a pod delete)
        #   NO-SWITCH - gluetun says "running" the whole time but never landed in the
        #               requested country
        # Conflating them previously reported 3 "wedges" that were all status=running.
        if wedged:
            final = status()
            if final == "running":
                no_switch.append((i + 1, country, public_country() or "?"))
                print(f"      !! NO-SWITCH >{WEDGE_AFTER_S:.0f}s  still running but never "
                      f"reached {country} (in {public_country() or '?'})  states={sorted(seen)}")
            else:
                wedges.append(i + 1)
                print(f"      *** WEDGED >{WEDGE_AFTER_S:.0f}s  status={final} states={sorted(seen)}")
            for line in gluetun_tail().splitlines():
                print(f"        {line[:150]}")
            # a wedged tunnel never self-heals (TALOS-z16b) -- recover so later cycles
            # still measure something meaningful rather than cascading failures
            delete_canary()
            create_canary()
        else:
            downtimes.append(recovered)
            print(f"      recovered in {recovered:.1f}s  egress {before or '?'} -> {now_ip}"
                  f"  country={landed or '?'}  states={sorted(seen)}")
        time.sleep(5)

    if downtimes:
        worst = max(downtimes)
        avg = sum(downtimes) / len(downtimes)
        print(f"\n  downtime: min {min(downtimes):.1f}s  avg {avg:.1f}s  max {worst:.1f}s "
              f"over {len(downtimes)} clean rotations")
        M.record("worst rotation downtime", f"{worst:.1f}s",
                 f"{MAX_ROTATION_DOWNTIME_S}s", worst <= MAX_ROTATION_DOWNTIME_S)

    M.record("rotations wedged", len(wedges), 0, not wedges)
    M.record("rotations that never switched country", len(no_switch), 0, not no_switch)
    assert not wedges, (
        f"gluetun wedged on cycle(s) {wedges} of {SOAK_CYCLES} -- tunnel never rebuilt "
        f"after the settings PUT and needed a pod delete (TALOS-z16b)"
    )
    assert not no_switch, (
        f"rotation(s) never reached the requested country within {WEDGE_AFTER_S:.0f}s: "
        f"{no_switch} -- gluetun stayed 'running' but the country filter did not take "
        f"effect, so the exit never honoured the request"
    )
    assert downtimes, "no rotation completed"
    assert max(downtimes) <= MAX_ROTATION_DOWNTIME_S, (
        f"worst rotation downtime {max(downtimes):.1f}s exceeds {MAX_ROTATION_DOWNTIME_S}s"
    )
