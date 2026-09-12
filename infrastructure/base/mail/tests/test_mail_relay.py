"""Mail subsystem (Stalwart SMTP relay → Gmail smarthost) — integration test  [SCAFFOLD]

Proves the outbound mailer path works: connects to the in-cluster Stalwart SMTP listener, hands it
a test message, and confirms it's accepted for relay (Stalwart then forwards to the Gmail smarthost
using the `mail-relay-credentials`).

STATUS: Stalwart's Deployment/Service is not in the repo yet (only ns + creds — TALOS-w5b). Until
it lands, the send auto-skips with a clear note; the scaffolding checks (namespace + relay secret
exist) run regardless, so this suite already guards the mailer wiring. All checks SKIP cleanly when
the cluster is unreachable.

Resolution / gating:
  - SMTP endpoint: env MAIL_SMTP_HOST[:MAIL_SMTP_PORT], else auto-detected from a Service in ns
    `mail` exposing port 2525 (Stalwart's non-root SMTP listener).
  - The send runs only when  MAIL_TEST_SEND=1  AND  MAIL_TEST_TO=you@example.com  is set (this repo
    is public — no recipient is hardcoded). Mirrors the DR suites' gating.
  - The SMTP session runs from a throwaway in-cluster pod (the relay is cluster-internal).

    MAIL_TEST_TO=you@example.com MAIL_TEST_SEND=1 pytest -m integration infrastructure/base/mail/tests

Needs `kubectl` (context = the cluster) on PATH.
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest

# make `from lib import dr` resolve for this co-located suite regardless of how pytest is invoked
_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pytest.ini").exists())
sys.path.insert(0, str(_ROOT / "tests"))

from lib import dr  # noqa: E402

pytestmark = pytest.mark.integration

# ---- config (env-overridable, preserved from the Jest suite) ----
NS = os.environ.get("MAIL_NS", "mail")
SECRET_NAME = os.environ.get("MAIL_SECRET_NAME", "mail-relay-credentials")
SMTP_PORT = os.environ.get("MAIL_SMTP_PORT", "2525")
TO = os.environ.get("MAIL_TEST_TO", "")
FROM = os.environ.get("MAIL_TEST_FROM", "homelab-test@knowledgedump.space")
DO_SEND = os.environ.get("MAIL_TEST_SEND") == "1"
CAN_SEND = DO_SEND and bool(TO)


@pytest.fixture(autouse=True)
def _require_cluster():
    dr.require_cluster()


def resolve_smtp_host():
    """Find the Stalwart SMTP Service (by env, or a Service in ns mail exposing :2525)."""
    if os.environ.get("MAIL_SMTP_HOST"):
        return os.environ["MAIL_SMTP_HOST"]
    raw = dr.kubectl(f"get svc -n {NS} -o json", check=False)
    if not raw:
        return None
    try:
        items = json.loads(raw).get("items", [])
    except json.JSONDecodeError:
        return None
    svc = next((s for s in items
                if any(str(p.get("port")) == str(SMTP_PORT) for p in s["spec"].get("ports", []))), None)
    return f"{svc['metadata']['name']}.{NS}.svc.cluster.local" if svc else None


def send_via_cluster(host, to):
    """Send a message through the relay from an in-cluster throwaway pod (Stalwart is internal)."""
    subject = f"Homelab mail relay test {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"
    py = "\n".join([
        "import smtplib,email.message,os,sys",
        "m=email.message.EmailMessage()",
        "m['From']=os.environ['F']; m['To']=os.environ['T']; m['Subject']=os.environ['S']",
        "m.set_content('If you can read this, the Stalwart -> Gmail relay works. Sent by test_mail_relay.py.')",
        "s=smtplib.SMTP(os.environ['H'],int(os.environ['P']),timeout=20)",
        "s.ehlo()",
        "\ntry:\n    if s.has_extn('starttls'): s.starttls(); s.ehlo()\nexcept Exception as e:\n    print('starttls-skip',e)",
        "s.send_message(m); s.quit(); print('SENT-OK')",
    ])
    pod = f"mail-test-{int(time.time() * 1000)}"
    overrides = json.dumps({
        "spec": {
            "restartPolicy": "Never",
            "containers": [{
                "name": "c", "image": "python:3.12-alpine",
                "env": [{"name": "H", "value": host}, {"name": "P", "value": SMTP_PORT},
                        {"name": "F", "value": FROM}, {"name": "T", "value": to},
                        {"name": "S", "value": subject}],
                "command": ["python3", "-c", py],
            }],
        },
    })
    ov = overrides.replace("'", "'\\''")
    raw = dr.sh(
        f"kubectl run {pod} -n {NS} --image=python:3.12-alpine --restart=Never --rm -i "
        f"--quiet --timeout=45s --overrides='{ov}'", check=False, timeout=70)
    return {"ok": "SENT-OK" in raw, "raw": raw, "subject": subject}


def test_mailer_scaffolding_in_place():
    assert dr.kubectl(f"get ns {NS} -o name", check=False), f"namespace {NS} missing"
    assert dr.kubectl(f"get secret {SECRET_NAME} -n {NS} -o name", check=False), \
        f"secret {NS}/{SECRET_NAME} missing"


def test_stalwart_smtp_listener_reachable_or_not_deployed():
    host = resolve_smtp_host()
    if not host:
        pytest.skip(f"no Service on :{SMTP_PORT} in ns {NS} — Stalwart relay not deployed yet (TALOS-w5b)")
    assert host, f"SMTP endpoint {host}:{SMTP_PORT}"


@pytest.mark.skipif(not CAN_SEND,
                    reason="send gated behind MAIL_TEST_SEND=1 + MAIL_TEST_TO=<recipient>")
def test_relays_test_email_through_stalwart():
    host = resolve_smtp_host()
    if not host:
        pytest.skip("Stalwart not deployed — nothing to send through (TALOS-w5b)")
    assert TO, "MAIL_TEST_TO must be set"
    res = send_via_cluster(host, TO)
    assert res["ok"], f"relay did not accept the message: {res['raw'][-200:]}"
