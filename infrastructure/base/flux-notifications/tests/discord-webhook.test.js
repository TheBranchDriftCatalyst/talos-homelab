/**
 * Discord notification webhook — integration test
 * ------------------------------------------------
 * Proves the shared `discord-webhook` channel actually works end-to-end: it resolves the webhook
 * URL, POSTs a real formatted message, and (via `?wait=true`) reads back the message Discord
 * created to confirm it landed. Flux alerts, Alertmanager, ArgoCD, and CrowdSec all post here, so
 * this is the canary for that whole notification path.
 *
 * The URL is resolved from (in order):
 *   1. env  DISCORD_WEBHOOK_URL
 *   2. the live secret  discord-webhook  (ns flux-system, key `address`)  via kubectl
 *
 * The read-only check (URL resolves + is a valid Discord webhook) ALWAYS runs. The actual SEND is
 * gated behind  DISCORD_WEBHOOK_TEST=1  so `npm run test:all` never spams the channel by accident —
 * exactly like the DR suites gate their destructive scenarios.
 *
 *   (from repo root)  npm run test:discord      # ← resolves + SENDS + verifies (you'll see a msg)
 *                     npm test -- --selectProjects discord-webhook   # read-only unless the flag is set
 *
 * Needs `kubectl` (context = the cluster) on PATH unless DISCORD_WEBHOOK_URL is exported.
 */
const https = require("https");
const { execSync } = require("child_process");

// ---- config ---------------------------------------------------------------
const SECRET_NS = process.env.DISCORD_SECRET_NS || "flux-system";
const SECRET_NAME = process.env.DISCORD_SECRET_NAME || "discord-webhook";
const SECRET_KEY = process.env.DISCORD_SECRET_KEY || "address";
const DO_SEND = process.env.DISCORD_WEBHOOK_TEST === "1";
const CLUSTER = process.env.CLUSTER_DOMAIN || "talos00";

// ---- pretty output (bypass Jest's console wrapping, like the DR suites) ----
const C = { reset: "\x1b[0m", bold: "\x1b[1m", dim: "\x1b[2m", green: "\x1b[32m", red: "\x1b[31m", yellow: "\x1b[33m", cyan: "\x1b[36m", grey: "\x1b[90m", blurple: "\x1b[38;5;103m" };
const out = (s = "") => process.stdout.write(String(s) + "\n");
const step = (m) => out(`\n${C.bold}${C.cyan}▶ ${m}${C.reset}`);
const info = (m) => out(`   ${C.grey}${m}${C.reset}`);
function check(label, ok, detail = "") {
  out(`   ${ok ? `${C.green}✓${C.reset}` : `${C.red}✗${C.reset}`} ${label}${detail ? `  ${C.dim}${detail}${C.reset}` : ""}`);
  return ok;
}

// ---- webhook URL resolution ----------------------------------------------
function resolveWebhookUrl() {
  if (process.env.DISCORD_WEBHOOK_URL) {
    info("URL source: env DISCORD_WEBHOOK_URL");
    return process.env.DISCORD_WEBHOOK_URL.trim();
  }
  try {
    const b64 = execSync(
      `kubectl get secret ${SECRET_NAME} -n ${SECRET_NS} -o jsonpath='{.data.${SECRET_KEY}}'`,
      { stdio: ["ignore", "pipe", "ignore"] }
    ).toString().trim().replace(/^'|'$/g, "");
    if (!b64) return null;
    info(`URL source: secret ${SECRET_NS}/${SECRET_NAME} .${SECRET_KEY}`);
    return Buffer.from(b64, "base64").toString("utf8").trim();
  } catch (_) {
    return null;
  }
}

// ---- minimal HTTPS POST (zero-dep, like the rest of the repo) --------------
function postJson(url, payload) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const body = JSON.stringify(payload);
    const req = https.request(
      { method: "POST", hostname: u.hostname, path: u.pathname + u.search, headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) } },
      (res) => {
        let data = "";
        res.on("data", (c) => (data += c));
        res.on("end", () => resolve({ status: res.statusCode, body: data }));
      }
    );
    req.on("error", reject);
    req.setTimeout(10000, () => req.destroy(new Error("Discord POST timed out (10s)")));
    req.write(body);
    req.end();
  });
}

// A recognizable, self-explanatory message so it "makes sense" when you see it in the channel.
function buildMessage() {
  return {
    username: "Homelab Test Bot",
    embeds: [
      {
        title: "🧪 Discord webhook integration test",
        description:
          "If you can read this, the **`discord-webhook`** channel is wired correctly — " +
          "Flux, Alertmanager, ArgoCD, and CrowdSec all post here.",
        color: 0x5865f2, // Discord blurple
        fields: [
          { name: "Source", value: "`jest · discord-webhook.test.js`", inline: true },
          { name: "Cluster", value: `\`${CLUSTER}\``, inline: true },
          { name: "Secret", value: `\`${SECRET_NS}/${SECRET_NAME}\` → \`.${SECRET_KEY}\``, inline: false },
        ],
        footer: { text: "talos-homelab · integration test" },
        timestamp: new Date().toISOString(),
      },
    ],
  };
}

// ---------------------------------------------------------------------------
describe("Discord notification webhook", () => {
  let url = null;

  beforeAll(() => {
    step("Resolving the Discord webhook URL");
    url = resolveWebhookUrl();
  });

  test("webhook URL resolves and is a valid Discord webhook", () => {
    const resolved = check("webhook URL resolved", !!url, url ? "(hidden)" : "set DISCORD_WEBHOOK_URL or ensure kubectl can read the secret");
    expect(resolved).toBe(true);
    const validShape = /^https:\/\/(discord|discordapp)\.com\/api\/webhooks\/\d+\/[\w-]+/.test(url);
    check("URL is a discord.com/api/webhooks/… endpoint", validShape);
    expect(validShape).toBe(true);
  });

  // The real send — gated so test:all never spams the channel.
  (DO_SEND ? test : test.skip)(
    "POSTs a message and Discord echoes it back (round-trip)",
    async () => {
      expect(url).toBeTruthy();
      const msg = buildMessage();

      step("Posting to Discord (?wait=true so Discord returns the created message)");
      info(`embed title: "${msg.embeds[0].title}"`);
      // ?wait=true → Discord responds 200 + the created message JSON (instead of a fire-and-forget 204)
      const sep = url.includes("?") ? "&" : "?";
      const res = await postJson(`${url}${sep}wait=true`, msg);

      const ok200 = check("HTTP 200 (message accepted + created)", res.status === 200, `status=${res.status}`);
      expect(res.status).toBe(200);

      let created = {};
      try { created = JSON.parse(res.body); } catch (_) {}
      check("Discord returned a message id", !!created.id, created.id ? `id=${created.id}` : "");
      expect(created.id).toBeTruthy();

      const echoedTitle = created.embeds?.[0]?.title;
      check("echoed embed matches what we sent", echoedTitle === msg.embeds[0].title, echoedTitle || "(none)");
      expect(echoedTitle).toBe(msg.embeds[0].title);

      out(`\n${C.bold}${C.green}✅ Sent — check your Discord channel for "${msg.embeds[0].title}"${C.reset}`);
      out(`   ${C.dim}message id ${created.id} · channel ${created.channel_id || "?"}${C.reset}\n`);
      void ok200;
    },
    20000
  );

  afterAll(() => {
    if (!DO_SEND) {
      out(`\n${C.yellow}ℹ send skipped${C.reset} ${C.dim}— run  ${C.reset}${C.bold}npm run test:discord${C.reset}${C.dim}  to actually post a message.${C.reset}\n`);
    }
  });
});
