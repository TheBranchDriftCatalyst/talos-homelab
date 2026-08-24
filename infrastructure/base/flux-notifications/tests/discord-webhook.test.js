/**
 * Discord notification webhook — integration test
 * ------------------------------------------------
 * Proves the shared `discord-webhook` channel actually works end-to-end: it resolves the webhook
 * URL, POSTs a real formatted message, and (via `?wait=true`) reads back the message Discord
 * created to confirm it landed. Flux alerts, Alertmanager, ArgoCD, and CrowdSec all post here, so
 * this is the canary for that whole notification path. A DIAGNOSTICS block (webhook id/name,
 * channel + guild, resolved config vars, last-send result) always prints at the end.
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
// Optional: a bot token that's a member of the server resolves the human #channel + server names
// (a webhook token alone only exposes the IDs). Falls back to IDs when unset / bot lacks access.
const BOT_TOKEN = (process.env.DISCORD_BOT_TOKEN || "").trim();

// ---- pretty output (bypass Jest's console wrapping, like the DR suites) ----
const C = { reset: "\x1b[0m", bold: "\x1b[1m", dim: "\x1b[2m", green: "\x1b[32m", red: "\x1b[31m", yellow: "\x1b[33m", cyan: "\x1b[36m", grey: "\x1b[90m" };
const out = (s = "") => process.stdout.write(String(s) + "\n");
const step = (m) => out(`\n${C.bold}${C.cyan}▶ ${m}${C.reset}`);
const info = (m) => out(`   ${C.grey}${m}${C.reset}`);
function check(label, ok, detail = "") {
  out(`   ${ok ? `${C.green}✓${C.reset}` : `${C.red}✗${C.reset}`} ${label}${detail ? `  ${C.dim}${detail}${C.reset}` : ""}`);
  return ok;
}

// ---- diagnostics collector (printed at the end) ---------------------------
const DIAG = {
  urlSource: "—",
  webhookId: "—",
  webhookName: "—",
  channelId: "—",
  channelName: "—",
  guildId: "—",
  guildName: "—",
  tokenMask: "—",
  sendEnabled: DO_SEND,
  sendStatus: "—",
  messageId: "—",
  sentAt: "—",
};

// ---- webhook URL resolution ----------------------------------------------
function resolveWebhookUrl() {
  if (process.env.DISCORD_WEBHOOK_URL) {
    DIAG.urlSource = "env DISCORD_WEBHOOK_URL";
    info("URL source: env DISCORD_WEBHOOK_URL");
    return process.env.DISCORD_WEBHOOK_URL.trim();
  }
  try {
    const b64 = execSync(
      `kubectl get secret ${SECRET_NAME} -n ${SECRET_NS} -o jsonpath='{.data.${SECRET_KEY}}'`,
      { stdio: ["ignore", "pipe", "ignore"] }
    ).toString().trim().replace(/^'|'$/g, "");
    if (!b64) return null;
    DIAG.urlSource = `secret ${SECRET_NS}/${SECRET_NAME} .${SECRET_KEY}`;
    info(`URL source: ${DIAG.urlSource}`);
    return Buffer.from(b64, "base64").toString("utf8").trim();
  } catch (_) {
    return null;
  }
}

// Extract the webhook id + a masked token from the URL (…/webhooks/<id>/<token>) — never log the token.
function dissectUrl(url) {
  try {
    const segs = new URL(url).pathname.split("/").filter(Boolean); // [api, webhooks, <id>, <token>]
    const id = segs[segs.indexOf("webhooks") + 1] || "—";
    const token = segs[segs.indexOf("webhooks") + 2] || "";
    DIAG.webhookId = id;
    DIAG.tokenMask = token ? `${token.slice(0, 3)}…redacted (${token.length} chars)` : "—";
  } catch (_) {}
}

// ---- minimal HTTPS helpers (zero-dep, like the rest of the repo) -----------
function request(method, url, payload) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const body = payload ? JSON.stringify(payload) : null;
    const headers = body ? { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) } : {};
    const req = https.request({ method, hostname: u.hostname, path: u.pathname + u.search, headers }, (res) => {
      let data = "";
      res.on("data", (c) => (data += c));
      res.on("end", () => resolve({ status: res.statusCode, body: data }));
    });
    req.on("error", reject);
    req.setTimeout(10000, () => req.destroy(new Error(`Discord ${method} timed out (10s)`)));
    if (body) req.write(body);
    req.end();
  });
}
const getJson = (url) => request("GET", url);
const postJson = (url, payload) => request("POST", url, payload);

// Resolve a channel/guild NAME via the bot API (needs DISCORD_BOT_TOKEN in that server).
function discordName(apiPath) {
  return new Promise((resolve) => {
    const req = https.request(
      { method: "GET", hostname: "discord.com", path: `/api/v10/${apiPath}`, headers: { Authorization: `Bot ${BOT_TOKEN}` } },
      (res) => {
        let data = "";
        res.on("data", (c) => (data += c));
        res.on("end", () => {
          if (res.statusCode === 200) { try { return resolve(JSON.parse(data).name || "—"); } catch (_) {} }
          resolve(res.statusCode === 401 || res.statusCode === 403 ? `(bot lacks access — ${res.statusCode})` : `(${res.statusCode})`);
        });
      }
    );
    req.on("error", () => resolve("—"));
    req.setTimeout(8000, () => req.destroy());
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

function printDiagnostics() {
  const pad = (s, n) => String(s).padEnd(n);
  out(`\n${C.bold}${C.cyan}════════════════ DISCORD WEBHOOK — DIAGNOSTICS ════════════════${C.reset}`);
  const row = (k, v) => out(`   ${C.dim}${pad(k, 24)}${C.reset}${v}`);
  row("URL source", DIAG.urlSource);
  row("Webhook ID", DIAG.webhookId);
  row("Webhook name", DIAG.webhookName);
  const namedChan = DIAG.channelName !== "—" && !DIAG.channelName.startsWith("(");
  const namedGuild = DIAG.guildName !== "—" && !DIAG.guildName.startsWith("(");
  row("Channel", namedChan ? `#${DIAG.channelName}  ${C.dim}(${DIAG.channelId})${C.reset}` : `${DIAG.channelId}  ${C.dim}${DIAG.channelName !== "—" ? DIAG.channelName : "(set DISCORD_BOT_TOKEN for the #name)"}${C.reset}`);
  row("Server / space", namedGuild ? `${DIAG.guildName}  ${C.dim}(${DIAG.guildId})${C.reset}` : `${DIAG.guildId}  ${C.dim}${DIAG.guildName !== "—" ? DIAG.guildName : "(set DISCORD_BOT_TOKEN for the name)"}${C.reset}`);
  row("Token", DIAG.tokenMask);
  out(`   ${C.dim}${"─".repeat(58)}${C.reset}`);
  out(`   ${C.dim}config vars${C.reset}`);
  row("  DISCORD_SECRET_NS", SECRET_NS);
  row("  DISCORD_SECRET_NAME", SECRET_NAME);
  row("  DISCORD_SECRET_KEY", SECRET_KEY);
  row("  CLUSTER_DOMAIN", CLUSTER);
  row("  DISCORD_WEBHOOK_TEST", `${DO_SEND ? "1 (send enabled)" : "unset (send skipped)"}`);
  out(`   ${C.dim}${"─".repeat(58)}${C.reset}`);
  out(`   ${C.dim}last send${C.reset}`);
  row("  HTTP status", DIAG.sendStatus);
  row("  Message ID", DIAG.messageId);
  row("  Sent at", DIAG.sentAt);
  out(`${C.bold}${C.cyan}═══════════════════════════════════════════════════════════════${C.reset}\n`);
}

// ---------------------------------------------------------------------------
describe("Discord notification webhook", () => {
  let url = null;

  beforeAll(async () => {
    step("Resolving the Discord webhook URL");
    url = resolveWebhookUrl();
    if (url) {
      dissectUrl(url);
      // GET the webhook itself → channel/guild/name for the diagnostics block (no message posted).
      try {
        const meta = await getJson(url);
        if (meta.status === 200) {
          const m = JSON.parse(meta.body);
          DIAG.webhookName = m.name || "—";
          DIAG.channelId = m.channel_id || "—";
          DIAG.guildId = m.guild_id || "—";
          // Enrich IDs → human names when a bot token is available (webhook tokens can't).
          if (BOT_TOKEN) {
            if (m.channel_id) DIAG.channelName = await discordName(`channels/${m.channel_id}`);
            if (m.guild_id) DIAG.guildName = await discordName(`guilds/${m.guild_id}`);
          }
        }
      } catch (_) {}
    }
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
      DIAG.sendStatus = res.status;
      DIAG.sentAt = msg.embeds[0].timestamp;

      const ok200 = check("HTTP 200 (message accepted + created)", res.status === 200, `status=${res.status}`);
      expect(res.status).toBe(200);

      let created = {};
      try { created = JSON.parse(res.body); } catch (_) {}
      DIAG.messageId = created.id || "—";
      if (created.channel_id) DIAG.channelId = created.channel_id;
      check("Discord returned a message id", !!created.id, created.id ? `id=${created.id}` : "");
      expect(created.id).toBeTruthy();

      const echoedTitle = created.embeds?.[0]?.title;
      check("echoed embed matches what we sent", echoedTitle === msg.embeds[0].title, echoedTitle || "(none)");
      expect(echoedTitle).toBe(msg.embeds[0].title);

      out(`\n${C.bold}${C.green}✅ Sent — check your Discord channel for "${msg.embeds[0].title}"${C.reset}`);
      out(`   ${C.dim}message id ${created.id} · channel ${created.channel_id || "?"}${C.reset}`);
      void ok200;
    },
    20000
  );

  afterAll(() => {
    printDiagnostics();
    if (!DO_SEND) {
      out(`${C.yellow}ℹ send skipped${C.reset} ${C.dim}— run  ${C.reset}${C.bold}npm run test:discord${C.reset}${C.dim}  to actually post a message.${C.reset}\n`);
    }
  });
});
