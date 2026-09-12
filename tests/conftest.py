"""Shared pytest configuration + fixtures for the consolidated test system.

Suites are pytest markers (security_posture, ingress_accessibility, disaster_recovery) — run one with
`pytest -m <suite>` anywhere in the tree. Shared utils/auth/corpus live here as fixtures so suites
don't duplicate them. `--live` opts into read-only running-cluster probes (off by default = CI-safe).
"""
import os
import sys
from pathlib import Path

import pytest

# make `import lib.helpers` work from any suite dir
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import helpers  # noqa: E402


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", default=False,
                     help="run read-only live probes against the running cluster/LAN")
    parser.addoption("--destructive", action="store_true", default=False,
                     help="arm destructive Disaster-Recovery chaos scenarios (mutates the live "
                          "cluster on throwaway canaries); off by default = CI-safe")


def pytest_configure(config):
    # register suite markers (the 'tag' mechanism) so `pytest -m <suite>` is first-class + strict
    config.addinivalue_line("markers", "security_posture: Security Posture suite — each fixed finding stays fixed")
    config.addinivalue_line("markers", "ingress_accessibility: Ingress Accessibility suite — what is reachable, from where, with what auth")
    config.addinivalue_line("markers", "disaster_recovery: Disaster Recovery suite — recovery machinery + fault injection")
    config.addinivalue_line("markers", "live: requires --live (running cluster/LAN)")
    config.addinivalue_line("markers", "destructive: destructive DR chaos — only runs with --destructive (or the per-suite <SUITE>_DR_DESTRUCTIVE=1)")
    # propagate --live to the env flag the suites + helpers read
    if config.getoption("--live"):
        os.environ["POSTURE_LIVE"] = "1"
        helpers.LIVE = True
    # propagate --destructive to the env flag the DR suites read (mirrors --live). The DR suites
    # skip destructive scenarios unless armed here OR via their per-suite <SUITE>_DR_DESTRUCTIVE=1.
    if config.getoption("--destructive"):
        os.environ["DR_DESTRUCTIVE"] = "1"


# ---- shared fixtures (utils / auth / corpus) ----
@pytest.fixture(scope="session")
def repo_root():
    return helpers.ROOT


@pytest.fixture(scope="session")
def live(request):
    """True when --live was passed; tests can `if not live: pytest.skip(...)`."""
    return request.config.getoption("--live")


@pytest.fixture(scope="session")
def destructive(request):
    """True when --destructive was passed; DR tests gate chaos on this (or a per-suite env var)."""
    return request.config.getoption("--destructive")


@pytest.fixture(scope="session")
def kube():
    """kubectl runner (raises with evidence on failure)."""
    return helpers.kube


@pytest.fixture(scope="session")
def http_get():
    """Read-only HTTP probe: (status, body-getter). ssl-unverified, no proxy, posture UA."""
    return helpers.http_status


@pytest.fixture(scope="session")
def rendered_corpus():
    """The rendered Flux ingress corpus (kustomize build over every path). Session-cached."""
    sys.path.insert(0, str(helpers.ROOT / "tests" / "ingress-accessibility"))
    import ingress_corpus as corpus
    docs, meta = corpus.render()
    return {"docs": docs, "meta": meta, "routes": corpus.routes(docs),
            "middlewares": corpus.middleware_defs(docs), "corpus": corpus}


# ───────────────────────── suite-aware terminal reporter ─────────────────────────
_SUITES = ("security_posture", "ingress_accessibility", "disaster_recovery")
_LABEL = {"security_posture": "Security Posture", "ingress_accessibility": "Ingress Accessibility",
          "disaster_recovery": "Disaster Recovery", "_other": "Other / integration"}
_C = {"reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m", "green": "\033[32m",
      "red": "\033[31m", "yellow": "\033[33m", "cyan": "\033[36m"}


def _suite_of(item):
    names = {m.name for m in item.iter_markers()}
    for s in _SUITES:
        if s in names:
            return s
    return "_other"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    rep._suite = _suite_of(item)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    tr = terminalreporter
    stats = {}

    def bucket(s):
        return stats.setdefault(s, {"passed": 0, "failed": 0, "skipped": 0, "xfailed": 0, "time": 0.0})

    for status, reports in tr.stats.items():
        for rep in reports:
            when = getattr(rep, "when", None)
            if when == "call" or (status == "skipped" and when == "setup"):
                key = {"passed": "passed", "failed": "failed", "error": "failed",
                       "skipped": "skipped", "xfailed": "xfailed", "xpassed": "passed"}.get(status)
                if key:
                    b = bucket(getattr(rep, "_suite", "_other"))
                    b[key] += 1
                    b["time"] += getattr(rep, "duration", 0.0) or 0.0
    if not stats:
        return
    c, w = _C, tr.write_line
    w("")
    w(f"{c['bold']}{c['cyan']}╭─ Test System · results by suite ───────────────────────────────╮{c['reset']}")
    order = [s for s in _SUITES if s in stats] + [s for s in stats if s not in _SUITES]
    for s in order:
        d = stats[s]
        parts = [f"{c['green']}{d['passed']}✓{c['reset']}"]
        if d["failed"]:
            parts.append(f"{c['red']}{d['failed']}✗{c['reset']}")
        if d["xfailed"]:
            parts.append(f"{c['yellow']}{d['xfailed']}⊘{c['reset']}")
        if d["skipped"]:
            parts.append(f"{c['dim']}{d['skipped']}–{c['reset']}")
        mark = f"{c['red']}FAIL{c['reset']}" if d["failed"] else f"{c['green']}PASS{c['reset']}"
        w(f"{c['bold']}│{c['reset']} {mark}  {c['bold']}{_LABEL.get(s, s):<22}{c['reset']} "
          f"{' '.join(parts):<28} {c['dim']}{d['time']:.1f}s{c['reset']}")
    w(f"{c['bold']}{c['cyan']}╰────────────────────────────────────────────────────────────────╯{c['reset']}")
    w(f"{c['dim']}  suites = pytest markers · run one: pytest -m security_posture | -m ingress_accessibility{c['reset']}")
