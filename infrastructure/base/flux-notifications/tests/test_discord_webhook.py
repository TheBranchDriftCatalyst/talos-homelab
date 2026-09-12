"""Discord notification webhook — integration test

Proves the shared `discord-webhook` channel actually works end-to-end: it resolves the webhook
URL, POSTs a real formatted message, and (via `?wait=true`) reads back the message Discord created
to confirm it landed. Flux alerts, Alertmanager, ArgoCD, and CrowdSec all post here, so this is the
canary for that whole notification path.

The URL is resolved from (in order):
  1. env  DISCORD_WEBHOOK_URL
  2. the live secret  discord-webhook  (ns flux-system, key `address`)  via kubectl

The read-only check (URL resolves + is a valid Discord webhook) always runs — it SKIPS cleanly
when the URL can only come from kubectl and the cluster is unreachable. The actual SEND is gated
behind  DISCORD_WEBHOOK_TEST=1  so a normal run never spams the channel by accident — exactly like
the DR suites gate their destructive scenarios.

    DISCORD_WEBHOOK_TEST=1 pytest -m integration infrastructure/base/flux-notifications/tests

Needs `kubectl` (context = the cluster) on PATH unless DISCORD_WEBHOOK_URL is exported.
"""
import base64
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

# make `from lib import dr` resolve for this co-located suite regardless of how pytest is invoked
_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pytest.ini").exists())
sys.path.insert(0, str(_ROOT / "tests"))

from lib import dr  # noqa: E402

pytestmark = pytest.mark.integration

# ---- config (env-overridable, preserved from the Jest suite) ----
SECRET_NS = os.environ.get("DISCORD_SECRET_NS", "flux-system")
SECRET_NAME = os.environ.get("DISCORD_SECRET_NAME", "discord-webhook")
SECRET_KEY = os.environ.get("DISCORD_SECRET_KEY", "address")
DO_SEND = os.environ.get("DISCORD_WEBHOOK_TEST") == "1"
CLUSTER = os.environ.get("CLUSTER_DOMAIN", "talos00")


def _request(method, url, payload=None, timeout=10):
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if body else {}
    req = Request(url, data=body, headers=headers, method=method)
    try:
        resp = urlopen(req, timeout=timeout)
        return {"status": resp.status, "body": resp.read().decode("utf-8", "replace")}
    except Exception as e:  # HTTPError carries .code + a readable body
        code = getattr(e, "code", None)
        b = ""
        try:
            b = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        return {"status": code, "body": b}


def resolve_webhook_url():
    """(url, source) — env first, else the live secret via kubectl."""
    if os.environ.get("DISCORD_WEBHOOK_URL"):
        return os.environ["DISCORD_WEBHOOK_URL"].strip(), "env DISCORD_WEBHOOK_URL"
    b64 = dr.kubectl(
        f"get secret {SECRET_NAME} -n {SECRET_NS} -o jsonpath='{{.data.{SECRET_KEY}}}'",
        check=False).strip().strip("'")
    if not b64:
        return None, None
    return base64.b64decode(b64).decode("utf-8").strip(), f"secret {SECRET_NS}/{SECRET_NAME} .{SECRET_KEY}"


def _using_kubectl_source():
    return not os.environ.get("DISCORD_WEBHOOK_URL")


def build_message():
    return {
        "username": "Homelab Test Bot",
        "embeds": [{
            "title": "🧪 Discord webhook integration test",
            "description": ("If you can read this, the **`discord-webhook`** channel is wired "
                            "correctly — Flux, Alertmanager, ArgoCD, and CrowdSec all post here."),
            "color": 0x5865F2,
            "fields": [
                {"name": "Source", "value": "`pytest · test_discord_webhook.py`", "inline": True},
                {"name": "Cluster", "value": f"`{CLUSTER}`", "inline": True},
                {"name": "Secret", "value": f"`{SECRET_NS}/{SECRET_NAME}` → `.{SECRET_KEY}`", "inline": False},
            ],
            "footer": {"text": "talos-homelab · integration test"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
    }


def test_webhook_url_resolves_and_is_valid():
    # If the URL can only come from kubectl and there's no cluster, SKIP (never silently pass).
    if _using_kubectl_source() and not dr.cluster_reachable():
        pytest.skip("no DISCORD_WEBHOOK_URL and cluster unreachable — cannot resolve the webhook secret")
    url, _ = resolve_webhook_url()
    assert url, "webhook URL did not resolve (set DISCORD_WEBHOOK_URL or ensure kubectl can read the secret)"
    valid_shape = bool(re.match(r"^https://(discord|discordapp)\.com/api/webhooks/\d+/[\w-]+", url))
    assert valid_shape, "URL is not a discord.com/api/webhooks/… endpoint"


@pytest.mark.skipif(not DO_SEND, reason="send gated behind DISCORD_WEBHOOK_TEST=1")
def test_posts_message_and_discord_echoes_it_back():
    if _using_kubectl_source() and not dr.cluster_reachable():
        pytest.skip("no DISCORD_WEBHOOK_URL and cluster unreachable — cannot resolve the webhook secret")
    url, _ = resolve_webhook_url()
    assert url, "webhook URL did not resolve"
    msg = build_message()
    # ?wait=true → Discord responds 200 + the created message JSON (instead of a fire-and-forget 204)
    sep = "&" if "?" in url else "?"
    res = _request("POST", f"{url}{sep}wait=true", msg)
    assert res["status"] == 200, f"Discord POST returned status={res['status']}"
    created = {}
    try:
        created = json.loads(res["body"])
    except json.JSONDecodeError:
        pass
    assert created.get("id"), "Discord did not return a message id"
    echoed_title = (created.get("embeds") or [{}])[0].get("title")
    assert echoed_title == msg["embeds"][0]["title"], f"echoed embed mismatch: {echoed_title}"
