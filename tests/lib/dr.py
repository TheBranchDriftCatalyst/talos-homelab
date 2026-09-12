"""Shared Disaster-Recovery test helpers (pytest suite = disaster_recovery).

Ports the common machinery the per-component ``*-dr`` suites relied on under Jest to
Python, so each co-located ``test_<c>_dr.py`` stays small and every suite shares one
implementation of:

  * ``sh`` / ``kubectl`` — a shell + kubectl runner that (like the Jest ``sh({check:false})``
    pattern) tolerates failure without raising, so DR probes can poll a not-yet-ready cluster.
  * ``wait_until`` — the poll-until-true loop the Jest suites used everywhere.
  * ``Probe`` — a background availability sampler (DNS/HTTP/OIDC) that measures the worst
    contiguous downtime + availability during a failover, mirroring the Jest ``startProbe``.
  * ``Metrics`` — a small measurement recorder that prints a per-suite summary.
  * the two skip gates every DR test shares:
      - ``require_cluster()`` — SKIP (never error) when the cluster is unreachable, so the
        suite is CI-safe / collectable without a homelab.
      - ``require_destructive()`` — SKIP unless armed via ``--destructive`` (conftest sets
        ``DR_DESTRUCTIVE=1``) OR the per-suite ``<SUITE>_DR_DESTRUCTIVE=1`` env var, preserved
        faithfully from the Jest suites.

Imported by every DR suite via ``from lib import dr`` (tests/ is on sys.path — added by
tests/conftest.py and, defensively, by each suite's own bootstrap).
"""
import os
import subprocess
import threading
import time

import pytest

from lib import helpers

ROOT = helpers.ROOT


# ---- shell / kubectl (check=False tolerates failure, mirroring the Jest sh({check:false})) ----
def sh(cmd, timeout=60, check=True):
    """Run a shell command STRING; return stripped stdout.

    check=False → never raises (returns whatever stdout we got, possibly ""), so callers can
    poll a resource that does not exist yet. Shell semantics are preserved (pipes/quoting) to
    keep the ported command strings byte-identical to the Jest originals.
    """
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout, cwd=ROOT)
    except subprocess.TimeoutExpired as e:
        if check:
            raise AssertionError(f"command timed out after {timeout}s: {cmd}")
        out = e.stdout
        return (out.decode() if isinstance(out, bytes) else out or "").strip()
    if r.returncode and check:
        raise AssertionError(
            f"command failed (exit {r.returncode}): {cmd}\n{(r.stderr or r.stdout)[-2000:]}")
    return (r.stdout or "").strip()


def kubectl(args, timeout=60, check=False):
    """kubectl runner. Defaults to check=False (the DR suites poll heavily)."""
    return sh("kubectl " + args, timeout=timeout, check=check)


def wait_until(fn, timeout_s=120, interval_s=1.5):
    """Poll fn() until truthy or the deadline; swallow exceptions (a not-ready resource)."""
    end = time.time() + timeout_s
    while time.time() < end:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(interval_s)
    return False


# ---- cluster reachability gate: SKIP (not fail) when there is no cluster ----
_CLUSTER_OK = None


def cluster_reachable():
    """True if kubectl can talk to the API server. Cached for the session."""
    global _CLUSTER_OK
    if _CLUSTER_OK is None:
        try:
            r = subprocess.run("kubectl --request-timeout=8s api-versions",
                               shell=True, capture_output=True, text=True, timeout=20, cwd=ROOT)
            _CLUSTER_OK = r.returncode == 0 and bool((r.stdout or "").strip())
        except Exception:
            _CLUSTER_OK = False
    return _CLUSTER_OK


def require_cluster():
    """Skip the current test when the cluster is unreachable (CI-safe / offline collection)."""
    if not cluster_reachable():
        pytest.skip("cluster unreachable (kubectl api-versions failed) — DR checks need a live cluster")


# ---- destructive arming gate (unified --destructive + per-suite env override) ----
def armed(env_var):
    """True when destructive chaos is armed: --destructive (DR_DESTRUCTIVE=1) OR <SUITE>_DR_DESTRUCTIVE=1."""
    return os.environ.get("DR_DESTRUCTIVE") == "1" or os.environ.get(env_var) == "1"


def require_destructive(env_var):
    """Skip a destructive scenario unless armed. Preserves the per-suite env var from Jest."""
    if not armed(env_var):
        pytest.skip(f"destructive DR scenario — arm with --destructive (or {env_var}=1)")


# ---- timing assertion helper (the Jest `gauge(...) + expect(dt).toBeLessThanOrEqual(...)`) ----
def assert_within(value, threshold, label, unit="s"):
    assert value <= threshold, f"{label}: {value:.2f}{unit} exceeds threshold {threshold}{unit}"


# ---- background availability probe (mirror of the Jest startProbe) ----
class Probe:
    """Sample a boolean health function in a background thread; report worst downtime + availability."""

    def __init__(self, sample_fn, interval_s=0.25):
        self._fn = sample_fn
        self._interval = interval_s
        self._samples = []  # list[(t, ok)]
        self._running = True
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def _loop(self):
        while self._running:
            t = time.time()
            try:
                ok = bool(self._fn())
            except Exception:
                ok = False
            self._samples.append((t, ok))
            time.sleep(self._interval)

    def stop(self):
        self._running = False
        self._t.join(timeout=5)

    def worst_downtime(self):
        """Longest contiguous FAIL streak, in seconds."""
        worst = 0.0
        start = None
        for t, ok in self._samples:
            if not ok and start is None:
                start = t
            elif ok and start is not None:
                worst = max(worst, t - start)
                start = None
        if start is not None and self._samples:
            worst = max(worst, self._samples[-1][0] - start)
        return worst

    def availability(self):
        return (sum(1 for _, ok in self._samples if ok) / len(self._samples)) if self._samples else 0.0

    def sampled(self):
        return len(self._samples)


# ---- measurement recorder (prints a per-suite summary; assertions are the real gate) ----
class Metrics:
    def __init__(self, title):
        self.title = title
        self.rows = []

    def record(self, name, measured, threshold, ok):
        self.rows.append((name, str(measured), str(threshold), bool(ok)))

    def summary(self):
        if not self.rows:
            return
        print(f"\n== {self.title} — measurements ==")
        for name, meas, thr, ok in self.rows:
            print(f"  [{'PASS' if ok else 'FAIL'}] {name:<46} {meas:<14} (threshold {thr})")
        passed = sum(1 for *_, ok in self.rows if ok)
        print(f"  {passed}/{len(self.rows)} metrics within threshold")
