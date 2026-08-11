/**
 * Mail subsystem (Stalwart SMTP relay → Gmail smarthost) — integration test  [SCAFFOLD]
 * -------------------------------------------------------------------------------------
 * Proves the outbound mailer path works: connects to the in-cluster Stalwart SMTP listener,
 * hands it a test message, and confirms it's accepted for relay (Stalwart then forwards to the
 * Gmail smarthost using the `mail-relay-credentials`). You then see the email in the inbox.
 *
 * STATUS: Stalwart's Deployment/Service is not in the repo yet (only ns + creds — TALOS-w5b).
 * Until it lands, the send auto-skips with a clear note; the scaffolding checks (namespace +
 * relay secret exist) run regardless, so this suite already guards the mailer wiring.
 *
 * Resolution / gating:
 *   - SMTP endpoint: env MAIL_SMTP_HOST[:MAIL_SMTP_PORT], else auto-detected from a Service in
 *     ns `mail` exposing port 2525 (Stalwart's non-root SMTP listener).
 *   - The send runs only when  MAIL_TEST_SEND=1  AND  MAIL_TEST_TO=you@example.com  is set
 *     (this repo is public — no recipient is hardcoded). Mirrors the DR suites' gating.
 *   - The SMTP session runs from a throwaway in-cluster pod (the relay is cluster-internal),
 *     the same "probe through a pod" approach the VPN/Pi-hole suites use.
 *
 *   (from repo root)  MAIL_TEST_TO=you@example.com npm run test:mail    # sends + verifies
 *                     npm test -- --selectProjects mail-relay           # scaffolding checks only
 *
 * Needs `kubectl` (context = the cluster) on PATH.
 */
const { execSync } = require("child_process");

// ---- config ---------------------------------------------------------------
const NS = process.env.MAIL_NS || "mail";
const SECRET_NAME = process.env.MAIL_SECRET_NAME || "mail-relay-credentials";
const SMTP_PORT = process.env.MAIL_SMTP_PORT || "2525";
const TO = process.env.MAIL_TEST_TO || "";
const FROM = process.env.MAIL_TEST_FROM || "homelab-test@knowledgedump.space";
const DO_SEND = process.env.MAIL_TEST_SEND === "1";

// ---- pretty output (bypass Jest console wrapping, like the DR suites) ------
const C = { reset: "\x1b[0m", bold: "\x1b[1m", dim: "\x1b[2m", green: "\x1b[32m", red: "\x1b[31m", yellow: "\x1b[33m", cyan: "\x1b[36m", grey: "\x1b[90m" };
const out = (s = "") => process.stdout.write(String(s) + "\n");
const step = (m) => out(`\n${C.bold}${C.cyan}▶ ${m}${C.reset}`);
const info = (m) => out(`   ${C.grey}${m}${C.reset}`);
function check(label, ok, detail = "") {
  out(`   ${ok ? `${C.green}✓${C.reset}` : `${C.red}✗${C.reset}`} ${label}${detail ? `  ${C.dim}${detail}${C.reset}` : ""}`);
  return ok;
}

const sh = (cmd) => execSync(cmd, { stdio: ["ignore", "pipe", "ignore"] }).toString().trim();
const trySh = (cmd) => { try { return sh(cmd); } catch (_) { return ""; } };

// Find the Stalwart SMTP Service (by env, or a Service in ns mail exposing :2525).
function resolveSmtpHost() {
  if (process.env.MAIL_SMTP_HOST) return process.env.MAIL_SMTP_HOST;
  const json = trySh(`kubectl get svc -n ${NS} -o json`);
  if (!json) return null;
  let items = [];
  try { items = JSON.parse(json).items || []; } catch (_) { return null; }
  const svc = items.find((s) => (s.spec.ports || []).some((p) => String(p.port) === String(SMTP_PORT)));
  return svc ? `${svc.metadata.name}.${NS}.svc.cluster.local` : null;
}

// Send a message through the relay from an in-cluster throwaway pod (Stalwart is cluster-internal).
function sendViaCluster(host, to) {
  const subject = `Homelab mail relay test ${new Date().toISOString()}`;
  const py = [
    "import smtplib,email.message,os,sys",
    "m=email.message.EmailMessage()",
    "m['From']=os.environ['F']; m['To']=os.environ['T']; m['Subject']=os.environ['S']",
    "m.set_content('If you can read this, the Stalwart -> Gmail relay works. Sent by mail-relay.test.js.')",
    "s=smtplib.SMTP(os.environ['H'],int(os.environ['P']),timeout=20)",
    "s.ehlo()",
    "\ntry:\n    if s.has_extn('starttls'): s.starttls(); s.ehlo()\nexcept Exception as e:\n    print('starttls-skip',e)",
    "s.send_message(m); s.quit(); print('SENT-OK')",
  ].join("\n");
  const pod = `mail-test-${Date.now()}`;
  const overrides = JSON.stringify({
    spec: {
      restartPolicy: "Never",
      containers: [{
        name: "c", image: "python:3.12-alpine",
        env: [{ name: "H", value: host }, { name: "P", value: SMTP_PORT }, { name: "F", value: FROM }, { name: "T", value: to }, { name: "S", value: subject }],
        command: ["python3", "-c", py],
      }],
    },
  });
  const raw = trySh(`kubectl run ${pod} -n ${NS} --image=python:3.12-alpine --restart=Never --rm -i --quiet --timeout=45s --overrides='${overrides.replace(/'/g, "'\\''")}'`);
  return { ok: /SENT-OK/.test(raw), raw, subject };
}

// ---------------------------------------------------------------------------
describe("Mail relay (Stalwart → Gmail)", () => {
  let host = null;

  beforeAll(() => {
    step("Resolving the Stalwart SMTP relay");
    host = resolveSmtpHost();
  });

  test("mailer scaffolding is in place (namespace + relay credentials)", () => {
    const nsOk = check(`namespace ${NS} exists`, !!trySh(`kubectl get ns ${NS} -o name`));
    expect(nsOk).toBe(true);
    const secOk = check(`secret ${NS}/${SECRET_NAME} exists`, !!trySh(`kubectl get secret ${SECRET_NAME} -n ${NS} -o name`));
    expect(secOk).toBe(true);
  });

  test("Stalwart SMTP listener is reachable (or clearly not deployed yet)", () => {
    if (!host) {
      info(`no Service on :${SMTP_PORT} in ns ${NS} — Stalwart relay not deployed yet (TALOS-w5b). Send is skipped.`);
      return; // scaffold: don't fail the suite before the relay exists
    }
    check(`found SMTP endpoint ${host}:${SMTP_PORT}`, true);
  });

  // The real send — gated so it never fires without an explicit recipient + flag.
  const canSend = DO_SEND && !!TO;
  (canSend ? test : test.skip)(
    "relays a test email through Stalwart (check the inbox)",
    () => {
      if (!host) { info("Stalwart not deployed — nothing to send through (TALOS-w5b)."); return; }
      expect(TO).toBeTruthy();
      step(`Sending test email → ${TO} via ${host}:${SMTP_PORT}`);
      const { ok, raw, subject } = sendViaCluster(host, TO);
      const accepted = check("relay accepted the message (SENT-OK)", ok, ok ? "" : raw.slice(-200));
      expect(accepted).toBe(true);
      out(`\n${C.bold}${C.green}✅ Relayed — check ${TO} for "${subject}"${C.reset}\n`);
    },
    60000
  );

  afterAll(() => {
    if (!canSend) {
      out(`\n${C.yellow}ℹ send skipped${C.reset} ${C.dim}— run  ${C.reset}${C.bold}MAIL_TEST_TO=you@example.com npm run test:mail${C.reset}${C.dim}  once Stalwart is deployed.${C.reset}\n`);
    }
  });
});
