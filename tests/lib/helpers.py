"""Cross-suite test helpers: repo access, kubectl, manifest loading, HTTP probing.

Shared by every Python suite (security-posture, ingress-accessibility, …) so utilities are defined
once. Also surfaced as pytest fixtures in tests/conftest.py. LIVE is env-driven (POSTURE_LIVE=1, set
by the `--live` pytest flag) so the same modules work under `pytest` and standalone.
"""
import ast
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener
import ssl

import yaml

# tests/lib/helpers.py -> parents[2] == repo root (same depth as tests/<suite>/x.py).
ROOT = Path(__file__).resolve().parents[2]
LIVE = os.environ.get("POSTURE_LIVE") == "1"
PROBE_UA = "crowdsec-posture-test"  # so CrowdSec/access-log analysis can filter the audit's own traffic


# ---- manifest loading ----
def document(path):
    return yaml.safe_load((ROOT / path).read_text())


def documents(path):
    return [d for d in yaml.safe_load_all((ROOT / path).read_text()) if d]


def route_middleware_names(route):
    """Set of (namespace, name) middleware refs on an IngressRoute route."""
    return {(m.get("namespace"), m["name"]) for m in route.get("middlewares", [])}


# ---- subprocess / kubectl ----
def run(*args, timeout=45):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    if result.returncode:
        detail = ""
        if len(args) > 1 and str(args[1]).endswith(".py"):
            detail = "\n" + (result.stdout + result.stderr)[-2400:]
        raise AssertionError(f"{args[0]} command failed (exit {result.returncode}); evidence unavailable{detail}")
    return result.stdout


def kube(*args):
    return run("kubectl", "--request-timeout=30s", *args)


def pod_list(namespace, selector):
    pods = json.loads(kube("-n", namespace, "get", "pods", "-l", selector, "-o", "json"))["items"]
    active = [p for p in pods if not p["metadata"].get("deletionTimestamp")]
    if not active:
        raise AssertionError(f"No active pods found for {namespace}/{selector}; evidence unavailable")
    return active


# ---- HTTP probing (read-only; ssl-unverified; no proxy) ----
def http_status(url, headers=None, timeout=15):
    """GET → HTTP status int, or None if unreachable (None is a skip, never a pass)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    hdrs = {"User-Agent": PROBE_UA}
    hdrs.update(headers or {})
    req = Request(url, headers=hdrs)
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ctx))
    try:
        return opener.open(req, timeout=timeout).status
    except Exception as e:  # HTTPError has .code; everything else = unreachable
        return getattr(e, "code", None)


def http_body(url, headers=None, timeout=15):
    """GET → response body text (raises on unreachable; callers guard with skip)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    hdrs = {"User-Agent": PROBE_UA}
    hdrs.update(headers or {})
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ctx))
    return opener.open(Request(url, headers=hdrs), timeout=timeout).read().decode("utf-8", "replace")
