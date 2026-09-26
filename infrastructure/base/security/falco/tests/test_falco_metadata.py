"""Falco container-metadata resolution — the gap that hid two blind tripwires.

The honeypot breach rule was blind TWICE in one day (2026-09-18) and nothing but a
human eyeball caught either. There was no test asserting anything about Falco
metadata at all. Both failures would have been caught by the assertions here:

  round 1 (fixed b76d17f6)  k8s.ns.name was null on 299/299 events
  round 2 (fixed 3c08e14c)  container.name resolved to the 12-hex container ID
                            instead of "cowrie"

Round 2 is the instructive one, and it drives the design of this file:

  * container.name was NOT null, so a null-check passes straight over it. The
    assertion has to be "is this a NAME", not "is this set".
  * it was PER NODE — only talos02-gpu was broken, which is the node every honeypot
    pod is pinned to by nodeSelector. Sampling one arbitrary falco pod, or averaging
    across the fleet, would have reported green. So every check here is per-pod and
    fails if ANY node is bad.

The metadata tests read events Falco has already emitted (json_output: true), so
they are read-only. The end-to-end tripwire test actually execs a process in the live
cowrie container and is gated behind --destructive, because it generates a real
CRITICAL — which is itself a useful check of the Discord path.

    pytest infrastructure/base/security/falco/tests/test_falco_metadata.py --live
    pytest ... --live --destructive        # includes the end-to-end tripwire
"""
import json
import os
import re
import sys
import time
from pathlib import Path

import pytest

# make `from lib import dr` resolve regardless of how pytest is invoked
_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pytest.ini").exists())
sys.path.insert(0, str(_ROOT / "tests"))

from lib import dr  # noqa: E402

pytestmark = pytest.mark.integration

NS = os.environ.get("FALCO_NS", "falco")
# How many recent log lines to scan per pod for events carrying container context.
SAMPLE_LINES = int(os.environ.get("FALCO_SAMPLE_LINES", "400"))
DESTRUCTIVE_ENV = "FALCO_DR_DESTRUCTIVE"

HONEYPOT_NS = os.environ.get("HONEYPOT_NS", "honeypot")
BREACH_RULE = "Honeypot Container Breach"
# getent is NOT in honeypot_expected_procs, so it trips the rule; it is also harmless.
# python/python3/python3.13 ARE whitelisted there and cannot be used as the trigger.
TRIPWIRE_CMD = ["getent", "passwd", "root"]
# The event timestamp comes from the NODE's clock and t0 from this machine's, so a
# genuinely fresh event can timestamp slightly BEFORE t0. Measured on this cluster:
# 63ms early. A strict t0 comparison therefore discarded the very event it had just
# caused. 10s absorbs the offset while still rejecting anything actually stale
# (pre-existing breach events here are minutes to hours old).
CLOCK_SKEW_TOLERANCE_S = float(os.environ.get("FALCO_SKEW_TOLERANCE", "10"))

CONTAINER_ID_RE = re.compile(r"^[0-9a-f]{12}$")
# Fail a node only when unresolved metadata is SYSTEMIC, not incidental.
# Round 1 was 299/299 events = 100%. Against that, a short-lived container whose exec
# Falco sees before its container cache catches up is a different animal: measured
# here as 1/400 = 0.25% on talos06, an `esbuild --version` with container.name,
# k8s.ns.name AND image ALL null. 10% sits two orders of magnitude above the observed
# transient rate and an order of magnitude below the real failure, so it catches
# round 1 decisively without going red on build noise. Offenders are always printed,
# so a rising-but-passing rate is still visible.
UNRESOLVED_RATIO_FAIL = float(os.environ.get("FALCO_UNRESOLVED_MAX_RATIO", "0.10"))


def _live():
    """Is --live armed?

    Read from the env rather than the `live` fixture: that fixture is defined in
    tests/conftest.py, which pytest does NOT load for a suite co-located under
    infrastructure/base/. Running this file by path would fail on an unknown fixture.
    POSTURE_LIVE is the same flag conftest sets when --live is passed, so both entry
    points work (`pytest -m integration --live` and running this file directly with
    POSTURE_LIVE=1).
    """
    return os.environ.get("POSTURE_LIVE") == "1"
M = dr.Metrics("Falco metadata")


@pytest.fixture(autouse=True)
def _require_cluster():
    dr.require_cluster()


@pytest.fixture(scope="module", autouse=True)
def _summary():
    yield
    M.summary()


def falco_pods():
    """Every Falco DaemonSet pod with the node it runs on.

    Deliberately returns ALL of them. The round-2 failure was confined to a single
    node, so any test that samples one pod can pass while the node that matters is
    broken.
    """
    # -o json rather than jsonpath: a jsonpath carrying {'\n'} does not survive the
    # shell hop inside dr.kubectl and silently yields an EMPTY list, which would make
    # every per-node assertion below vacuously pass.
    raw = dr.kubectl(f"get pods -n {NS} -l app.kubernetes.io/name=falco -o json",
                     check=False, timeout=60) or ""
    try:
        items = json.loads(raw).get("items", [])
    except Exception:
        return []
    return [(p["metadata"]["name"], p["spec"].get("nodeName", "?")) for p in items]


def event_epoch(ev):
    """Unix seconds for a Falco event, from the event's OWN clock.

    Needed because "is there a breach event in the log" is NOT the same question as
    "did the breach I just caused get detected". Falco gives both `time` (RFC3339
    with nanos) and output_fields["evt.time"] (epoch nanos); prefer the latter.
    Returns 0.0 when neither parses, which callers must treat as "too old to trust".
    """
    of = ev.get("output_fields") or {}
    raw = of.get("evt.time")
    if raw is not None:
        try:
            return int(raw) / 1e9
        except (TypeError, ValueError):
            pass
    t = str(ev.get("time") or "")
    if t:
        try:
            from datetime import datetime, timezone
            return datetime.strptime(t[:26].rstrip("Z"), "%Y-%m-%dT%H:%M:%S.%f").replace(
                tzinfo=timezone.utc).timestamp()
        except Exception:
            pass
    return 0.0


def container_events(pod):
    """Recent Falco events from one pod that carry container context.

    Only events with a container.id are useful here: a rule that fired on host
    activity legitimately has no container name or namespace to resolve, and
    counting those as failures would make this test permanently red.
    """
    raw = dr.kubectl(f"logs -n {NS} {pod} -c falco --tail={SAMPLE_LINES}",
                     check=False, timeout=90) or ""
    events = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        fields = ev.get("output_fields") or {}
        if fields.get("container.id") and fields.get("container.id") != "host":
            events.append(ev)
    return events


# ---- metadata resolution, PER NODE ------------------------------------------------

def test_container_name_is_a_name_not_a_hex_id():
    """THE round-2 check: container.name must be a name, never the 12-hex container ID.

    A null-check cannot catch this — the field was populated, just useless. Failing
    per-node on purpose: aggregating would have hidden that only talos02-gpu (where
    every honeypot pod is pinned) was broken.
    """
    if not _live():
        pytest.skip("needs --live (reads events from running Falco pods)")
    pods = falco_pods()
    assert pods, "no Falco DaemonSet pods found"

    broken, no_data = [], []
    for pod, node in pods:
        evs = container_events(pod)
        if not evs:
            no_data.append(node)
            continue
        bad = [
            (e.get("output_fields", {}).get("container.name"),
             e.get("output_fields", {}).get("container.id"))
            for e in evs
            if CONTAINER_ID_RE.match(str(e.get("output_fields", {}).get("container.name") or ""))
        ]
        if bad:
            broken.append((node, pod, len(bad), len(evs), bad[0]))

    for node, pod, n, total, sample in broken:
        print(f"  {node}: {n}/{total} events have container.name == a 12-hex id, e.g. {sample}")
    if no_data:
        # Not a failure: a quiet node has nothing to resolve. Surfaced so a fleet-wide
        # silence cannot masquerade as a pass.
        print(f"  no container events sampled on: {sorted(no_data)} "
              f"(not a failure, but nothing was verified there)")

    M.record("nodes with hex-id container.name", len(broken), 0, not broken)
    assert not broken, (
        f"container.name is resolving to the container ID on {len(broken)} node(s): "
        f"{[b[0] for b in broken]} — this is the round-2 failure, and a null-check "
        f"would pass straight over it"
    )
    assert len(no_data) < len(pods), (
        "no container-context events on ANY node — nothing was actually verified. "
        "Either Falco is not emitting, or SAMPLE_LINES is too small."
    )


def test_k8s_namespace_resolves():
    """The round-1 check: k8s.ns.name must resolve for container events."""
    if not _live():
        pytest.skip("needs --live (reads events from running Falco pods)")
    pods = falco_pods()
    assert pods, "no Falco DaemonSet pods found"

    broken, no_data = [], []
    for pod, node in pods:
        evs = container_events(pod)
        if not evs:
            no_data.append(node)
            continue
        bad = [e for e in evs
               if not str(e.get("output_fields", {}).get("k8s.ns.name") or "").strip()
               or str(e.get("output_fields", {}).get("k8s.ns.name")).strip() in ("<NA>", "null")]
        if bad:
            ratio = len(bad) / len(evs)
            print(f"  {node}: {len(bad)}/{len(evs)} ({ratio:.1%}) container events have an "
                  f"unresolved k8s.ns.name")
            if ratio > UNRESOLVED_RATIO_FAIL:
                broken.append((node, len(bad), len(evs), ratio))

    if no_data:
        print(f"  no container events sampled on: {sorted(no_data)}")

    M.record("nodes above unresolved-ns threshold", len(broken), 0, not broken)
    assert not broken, (
        f"k8s.ns.name is SYSTEMICALLY unresolved on {len(broken)} node(s): "
        f"{[(b[0], f'{b[3]:.1%}') for b in broken]} — this is the round-1 failure "
        f"(it was null on 299/299 = 100% of events). Threshold is "
        f"{UNRESOLVED_RATIO_FAIL:.0%}; a few percent from short-lived containers is "
        f"expected and does not fail."
    )


# ---- the control itself, end to end ----------------------------------------------

@pytest.mark.destructive
def test_tripwire_fires_end_to_end():
    """Fire the breach rule for real and assert the event arrives.

    This is the only test here that proves the CONTROL rather than its inputs. The
    epic's one lesson was "never verify a detection control by checking an
    intermediate field" — the tripwire was declared fixed three times off field
    checks and was still blind. So: exec a non-whitelisted binary in the live cowrie
    container, then look for the event.

    Generates a real CRITICAL, which is deliberate: it also exercises the Discord
    path. Gated behind --destructive for that reason.
    """
    dr.require_destructive(DESTRUCTIVE_ENV)

    pod = dr.kubectl(
        f"get pods -n {HONEYPOT_NS} -l app=cowrie "
        f"-o jsonpath={{.items[0].metadata.name}}", check=False)
    if not pod:
        pod = (dr.kubectl(f"get pods -n {HONEYPOT_NS} --no-headers", check=False) or "")
        pod = next((l.split()[0] for l in pod.splitlines() if l.startswith("cowrie")), "")
    assert pod, f"no cowrie pod found in ns {HONEYPOT_NS}"

    # Which node cowrie is on decides which Falco pod can possibly see the syscall.
    node = dr.kubectl(f"get pod -n {HONEYPOT_NS} {pod} -o jsonpath={{.spec.nodeName}}",
                      check=False)
    falco_on_node = [p for p, n in falco_pods() if n == node]
    assert falco_on_node, f"no Falco pod on node {node} — the breach could not be seen"
    watcher = falco_on_node[0]

    t0 = time.time()
    dr.kubectl(f"exec -n {HONEYPOT_NS} {pod} -c cowrie -- {' '.join(TRIPWIRE_CMD)}",
               check=False, timeout=45)

    # Poll rather than sleep-once: the event goes syscall -> falco -> stdout.
    # The event MUST be newer than the exec. Matching on rule name alone is a false
    # pass: the honeypot is attacked continuously, so an OLD breach event is almost
    # always sitting in the last SAMPLE_LINES. Verified the hard way -- without this
    # window the test reported "fired in 0s", which is impossible for a real
    # syscall -> falco -> stdout round trip, and it would have passed with the
    # tripwire completely blind. That is the precise failure this file exists to stop.
    hit = None
    for _ in range(20):
        for ev in container_events(watcher):
            f = ev.get("output_fields") or {}
            if BREACH_RULE.lower() not in str(ev.get("rule", "")).lower():
                continue
            if event_epoch(ev) < t0 - CLOCK_SKEW_TOLERANCE_S:
                continue  # pre-existing attack traffic, not our exec
            # Freshness alone is not enough to be sure this is OURS: the honeypot is
            # attacked continuously, so match the distinctive cmdline too. Together
            # they mean the event must be both recent AND the exec we performed.
            cmdline = str(f.get("proc.cmdline") or "")
            if TRIPWIRE_CMD[0] not in cmdline:
                continue
            hit = (ev.get("rule"), f.get("container.name"), f.get("k8s.ns.name"),
                   cmdline or f.get("proc.name"))
            break
        if hit:
            break
        time.sleep(3)

    elapsed = time.time() - t0
    M.record("tripwire fired end to end", bool(hit), True, bool(hit))
    assert hit, (
        f"no '{BREACH_RULE}' event within {elapsed:.0f}s after running "
        f"{' '.join(TRIPWIRE_CMD)} in {HONEYPOT_NS}/{pod} on node {node}. The tripwire "
        f"is BLIND — this is the exact condition that went unnoticed three times. "
        f"(Only events newer than the exec count; a stale breach event does NOT pass.)"
    )

    rule, cname, ns, proc = hit
    print(f"  fired in {elapsed:.0f}s: rule={rule} container={cname} ns={ns} proc={proc}")
    # The metadata has to be usable, not merely present — a breach event naming a
    # 12-hex id is what round 2 looked like.
    assert not CONTAINER_ID_RE.match(str(cname or "")), (
        f"breach event resolved container.name to a hex id ({cname}) — round 2 again"
    )
    assert ns == HONEYPOT_NS, f"breach event ns={ns}, expected {HONEYPOT_NS}"
