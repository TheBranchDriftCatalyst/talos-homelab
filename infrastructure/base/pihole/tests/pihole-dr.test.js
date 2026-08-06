/**
 * Pi-hole HA disaster-recovery / chaos test  (TALOS-0nt.2)
 * ---------------------------------------------------------
 * Validates the StatefulSet + single-VIP (DNS+web, eTP:Local) + nebula-sync design and
 * MEASURES DNS failover downtime with a high-frequency background probe against the VIP.
 *
 * Read-only checks always run. DESTRUCTIVE scenarios (they delete pods) run only when
 *     PIHOLE_DR_DESTRUCTIVE=1
 * so this can never disrupt DNS by accident.
 *
 *   npm install && npm test                 # safe, read-only
 *   PIHOLE_DR_DESTRUCTIVE=1 npm run test:dr  # full chaos test (homelab only)
 *
 * Needs `kubectl` (context = the cluster) and `dig` on PATH.
 */
const { exec } = require("child_process");

// ---- config ---------------------------------------------------------------
const VIP = process.env.PIHOLE_VIP || "192.168.1.240";
const NS = process.env.PIHOLE_NS || "pihole";
const LEASE = process.env.PIHOLE_LEASE || "cilium-l2announce-pihole-pihole";
const PROBE_DOMAIN = process.env.PIHOLE_PROBE_DOMAIN || "cloudflare.com";
const SYNC_INTERVAL = parseInt(process.env.PIHOLE_SYNC_INTERVAL || "300", 10);
const DESTRUCTIVE = process.env.PIHOLE_DR_DESTRUCTIVE === "1";
const MAX_FAILOVER_S = parseFloat(process.env.PIHOLE_MAX_FAILOVER_S || "30");
const MAX_NOIMPACT_S = parseFloat(process.env.PIHOLE_MAX_NOIMPACT_S || "2");

// ---- pretty output --------------------------------------------------------
const C = {
  reset: "\x1b[0m", bold: "\x1b[1m", dim: "\x1b[2m",
  green: "\x1b[32m", red: "\x1b[31m", yellow: "\x1b[33m", cyan: "\x1b[36m", grey: "\x1b[90m",
};
const step = (m) => console.log(`\n${C.bold}${C.cyan}▶ ${m}${C.reset}`);
const info = (m) => console.log(`   ${C.grey}${m}${C.reset}`);
function check(label, ok, detail = "") {
  const mark = ok ? `${C.green}✓${C.reset}` : `${C.red}✗${C.reset}`;
  const d = detail ? `  ${C.dim}${detail}${C.reset}` : "";
  console.log(`   ${mark} ${label}${d}`);
  return ok;
}
function gauge(label, value, threshold, unit = "s") {
  const ok = value <= threshold;
  const col = ok ? C.green : C.red;
  check(label, ok, `${col}${value.toFixed(2)}${unit}${C.reset} ${C.dim}(≤ ${threshold}${unit})${C.reset}`);
  return ok;
}

// ---- shell / kubectl helpers (async so the probe keeps sampling) -----------
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function sh(cmd, { timeout = 60000, check: doCheck = true } = {}) {
  return new Promise((resolve, reject) => {
    exec(cmd, { timeout, maxBuffer: 8 * 1024 * 1024 }, (err, stdout, stderr) => {
      if (err && doCheck) return reject(new Error(`${cmd}\n${stderr || err.message}`));
      resolve((stdout || "").trim());
    });
  });
}
const kubectl = (a, o) => sh(`kubectl ${a}`, o);

async function dnsOk(timeoutS = 1) {
  const out = await sh(`dig +short +time=${timeoutS} +tries=1 @${VIP} ${PROBE_DOMAIN}`,
    { timeout: (timeoutS + 2) * 1000, check: false });
  return /\d+\.\d+\.\d+\.\d+/.test(out);
}
const leaseHolder = () =>
  kubectl(`get lease ${LEASE} -n kube-system -o jsonpath={.spec.holderIdentity}`, { check: false });
async function leaseCount() {
  const out = await kubectl("get leases -n kube-system -o name");
  return out.split("\n").filter((l) => l.includes("l2announce-pihole")).length;
}
async function pods() {
  const jp = "jsonpath={range .items[*]}{.metadata.name}|{.spec.nodeName}|{.status.podIP}|{.status.phase}{'\\n'}{end}";
  const out = await kubectl(`get pods -n ${NS} -l app=pihole -o "${jp}"`);
  return out.split("\n").filter(Boolean).map((l) => {
    const [name, node, ip, phase] = l.split("|");
    return { name, node, ip, phase };
  });
}
async function activePod() {
  const node = await leaseHolder();
  if (!node) return null;
  return (await pods()).find((p) => p.node === node) || null;
}
async function waitUntil(fn, timeoutMs = 120000, intervalMs = 1500) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    try { if (await fn()) return true; } catch (_) {}
    await sleep(intervalMs);
  }
  return false;
}

// ---- background DNS probe -------------------------------------------------
function startProbe(intervalMs = 200) {
  const samples = []; // { t, ok }
  let running = true;
  (async () => {
    while (running) {
      const t = Date.now();
      const ok = await dnsOk();
      samples.push({ t, ok });
      await sleep(intervalMs);
    }
  })();
  return {
    stop: () => { running = false; },
    worstDowntime() { // longest contiguous FAIL streak, seconds
      let worst = 0, start = null;
      for (const s of samples) {
        if (!s.ok && start === null) start = s.t;
        else if (s.ok && start !== null) { worst = Math.max(worst, s.t - start); start = null; }
      }
      if (start !== null) worst = Math.max(worst, samples[samples.length - 1].t - start);
      return worst / 1000;
    },
    availability() {
      return samples.length ? samples.filter((s) => s.ok).length / samples.length : 0;
    },
  };
}

const dtest = DESTRUCTIVE ? test : test.skip;

// ============================================================================
describe("Pi-hole HA — disaster recovery", () => {
  beforeAll(async () => {
    step("Pre-flight");
    const ready = await kubectl(`get statefulset pihole -n ${NS} -o jsonpath={.status.readyReplicas}`);
    check("StatefulSet pihole 5/5 ready", ready === "5", `readyReplicas=${ready}`);
    expect(ready).toBe("5");
    if (!DESTRUCTIVE)
      info("read-only mode — set PIHOLE_DR_DESTRUCTIVE=1 for the chaos scenarios");
  });

  test("DNS resolves via the VIP", async () => {
    const ok = await dnsOk();
    check(`dig @${VIP} ${PROBE_DOMAIN}`, ok);
    expect(ok).toBe(true);
  });

  test("single active — exactly one L2 lease (no split-brain)", async () => {
    const n = await leaseCount();
    const act = await activePod();
    check("one l2announce-pihole lease", n === 1, `count=${n}`);
    check("active pod resolvable from lease", !!act, act ? `${act.name} @ ${act.node}` : "none");
    expect(n).toBe(1);
    expect(act).not.toBeNull();
  });

  test("pihole.talos00 resolves to the VIP", async () => {
    const out = await sh(`dig +short +time=2 +tries=1 @${VIP} pihole.talos00`, { check: false });
    check("pihole.talos00 → VIP", out.includes(VIP), out.trim());
    expect(out).toContain(VIP);
  });

  dtest("FAILOVER: delete the active pod → measure DNS downtime", async () => {
    const before = await activePod();
    step(`Chaos: delete active primary ${C.yellow}${before.name}${C.reset} (node ${before.node})`);
    const probe = startProbe();
    await sleep(1200);
    await kubectl(`delete pod ${before.name} -n ${NS} --wait=false`);
    info("waiting for the L2 lease + VIP to hand off to another pod…");
    const failedOver = await waitUntil(async () => {
      const a = await activePod();
      return a && a.name !== before.name && (await dnsOk());
    }, 120000);
    await sleep(4000);
    probe.stop();
    const dt = probe.worstDowntime();
    const now = await activePod();
    check("failover completed", failedOver, now ? `new primary ${now.name}` : "TIMEOUT");
    gauge("DNS downtime", dt, MAX_FAILOVER_S);
    check("no split-brain after failover", (await leaseCount()) === 1);
    info(`overall DNS availability during test: ${(probe.availability() * 100).toFixed(1)}%`);
    expect(failedOver).toBe(true);
    expect(dt).toBeLessThanOrEqual(MAX_FAILOVER_S);
    expect(await leaseCount()).toBe(1);
  });

  dtest("ISOLATION: delete a standby → DNS must not blip", async () => {
    const act = await activePod();
    const standby = (await pods()).find((p) => p.name !== act.name);
    step(`Chaos: delete standby ${C.yellow}${standby.name}${C.reset} (active stays ${act.name})`);
    const probe = startProbe();
    await sleep(1000);
    await kubectl(`delete pod ${standby.name} -n ${NS} --wait=false`);
    await sleep(15000);
    probe.stop();
    gauge("DNS downtime", probe.worstDowntime(), MAX_NOIMPACT_S);
    expect(probe.worstDowntime()).toBeLessThanOrEqual(MAX_NOIMPACT_S);
  });

  dtest("ISOLATION: kill nebula-sync → zero DNS impact + self-heal", async () => {
    const p = await kubectl(
      `get pods -n ${NS} -l app.kubernetes.io/component=config-sync -o jsonpath={.items[0].metadata.name}`);
    step(`Chaos: delete sync worker ${C.yellow}${p}${C.reset}`);
    const probe = startProbe();
    await sleep(1000);
    await kubectl(`delete pod ${p} -n ${NS} --wait=false`);
    await sleep(10000);
    probe.stop();
    gauge("DNS downtime (sync worker is independent)", probe.worstDowntime(), MAX_NOIMPACT_S);
    const healed = await waitUntil(async () =>
      (await kubectl(`get deploy nebula-sync -n ${NS} -o jsonpath={.status.availableReplicas}`)) === "1",
      90000);
    check("nebula-sync self-healed", healed);
    expect(probe.worstDowntime()).toBeLessThanOrEqual(MAX_NOIMPACT_S);
    expect(healed).toBe(true);
  });

  dtest("PERSISTENCE: restart the active pod → stats survive (local-path PVC)", async () => {
    const act = await activePod();
    const before = await queriesToday(act.ip);
    step(`Chaos: restart active ${C.yellow}${act.name}${C.reset} (had ${before} queries today)`);
    await kubectl(`delete pod ${act.name} -n ${NS} --wait=false`);
    await waitUntil(async () =>
      (await kubectl(`get pod ${act.name} -n ${NS} -o jsonpath={.status.containerStatuses[0].ready}`,
        { check: false })) === "true", 180000);
    await sleep(5000);
    const ip = (await pods()).find((p) => p.name === act.name)?.ip;
    const after = await queriesToday(ip);
    check("stats survived restart", after !== null && after >= before * 0.5,
      `before=${before} after=${after}`);
    expect(after).not.toBeNull();
    expect(after).toBeGreaterThanOrEqual(Math.floor(before * 0.5));
  });
});

// pihole_dns_queries_today via the pod's own v6 API (rough persistence signal)
async function queriesToday(ip) {
  if (!ip) return null;
  const name = `drq-${Date.now()}`;
  const out = await kubectl(
    `run ${name} -n ${NS} --rm -i --restart=Never --image=curlimages/curl:8.10.1 --command -- ` +
    `sh -c "curl -s http://${ip}/api/stats/summary || true"`, { timeout: 60000, check: false });
  const m = out.match(/"total"\s*:\s*(\d+)/);
  return m ? parseInt(m[1], 10) : 0;
}
