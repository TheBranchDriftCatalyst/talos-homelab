/**
 * Authentik SSO — disaster-recovery / chaos test  (TALOS-23l.4)
 * -------------------------------------------------------------
 * Authentik is a CLUSTER-WIDE AUTH SPOF: a SINGLE-replica authentik-server backed by a CNPG
 * postgres (authentik-postgres) and a Dragonfly redis (authentik-cache). Every OIDC/forward-auth
 * app in the fleet (grafana, minio, forgejo, litellm, immich, the *arr stack, boomtime, …) rides
 * on it. When the server PVC was lost on 2026-05-09 every SSO login broke. This suite validates the
 * DR machinery EXISTS + is healthy, and MEASURES OIDC downtime when the single server pod is killed.
 *
 * Read-only checks always run (they ONLY observe — never mutate). DESTRUCTIVE scenarios (they delete
 * the authentik-server pod) run only when
 *     AUTHENTIK_DR_DESTRUCTIVE=1
 * so this can never disrupt cluster-wide SSO by accident. The destructive tier NEVER touches the
 * postgres cluster or its PVC — only the stateless server pod (which the Deployment recreates) and a
 * throwaway in-namespace probe pod. Postgres/redis/PVC are strictly off-limits.
 *
 *   npm install && npm test                     # safe, read-only
 *   AUTHENTIK_DR_DESTRUCTIVE=1 npm run test:dr   # full chaos test (homelab only)
 *
 * Needs `kubectl` (context = the cluster) on PATH. The OIDC endpoint is in-cluster only, so every
 * HTTP probe runs THROUGH a pod (throwaway one-shot curl for read-only; a persistent throwaway probe
 * pod exec'd in a tight loop for the destructive downtime measurement).
 */
const { exec } = require("child_process");

// ---- config ---------------------------------------------------------------
const NS = process.env.AUTHENTIK_NS || "authentik";
const SERVER_DEPLOY = process.env.AUTHENTIK_SERVER_DEPLOY || "authentik-server";
const WORKER_DEPLOY = process.env.AUTHENTIK_WORKER_DEPLOY || "authentik-worker";
const SERVER_SVC = process.env.AUTHENTIK_SERVER_SVC || "authentik-server";
const SERVER_LABEL = process.env.AUTHENTIK_SERVER_LABEL || "app.kubernetes.io/component=server";
const PG_CLUSTER = process.env.AUTHENTIK_PG_CLUSTER || "authentik-postgres";
// In-cluster OIDC discovery (well-known) endpoint. Authentik serves per-application discovery at
// /application/o/<slug>/.well-known/openid-configuration (confirmed by minio/forgejo consumers).
// `litellm` is a stable, long-lived provider slug; override via env for a different app.
const OIDC_HOST = process.env.AUTHENTIK_OIDC_HOST || `${SERVER_SVC}.${NS}.svc.cluster.local`;
const OIDC_SLUG = process.env.AUTHENTIK_OIDC_SLUG || "litellm";
const WELLKNOWN_PATH =
  process.env.AUTHENTIK_WELLKNOWN_PATH ||
  `/application/o/${OIDC_SLUG}/.well-known/openid-configuration`;
const WELLKNOWN_URL = `http://${OIDC_HOST}${WELLKNOWN_PATH}`;
const CURL_IMAGE = process.env.AUTHENTIK_CURL_IMAGE || "curlimages/curl:8.10.1";
const PROBE_POD = process.env.AUTHENTIK_PROBE_POD || "authentik-dr-probe";
const DESTRUCTIVE = process.env.AUTHENTIK_DR_DESTRUCTIVE === "1";
// single-replica server → a kill is a FULL cold start; thresholds are generous (we MEASURE the
// SPOF's recovery, we don't pretend it fails over fast). Downtime ≈ recovery for one replica.
const MAX_RECOVERY_S = parseFloat(process.env.AUTHENTIK_MAX_RECOVERY_S || "180");
const MAX_DOWNTIME_S = parseFloat(process.env.AUTHENTIK_MAX_DOWNTIME_S || "180");

// ---- pretty output --------------------------------------------------------
const C = {
  reset: "\x1b[0m", bold: "\x1b[1m", dim: "\x1b[2m",
  green: "\x1b[32m", red: "\x1b[31m", yellow: "\x1b[33m", cyan: "\x1b[36m", grey: "\x1b[90m",
};
// write straight to stdout so Jest doesn't wrap every line with "console.log / at log (...)"
const out = (s = "") => process.stdout.write(String(s) + "\n");
const step = (m) => out(`\n${C.bold}${C.cyan}▶ ${m}${C.reset}`);
const info = (m) => out(`   ${C.grey}${m}${C.reset}`);
function check(label, ok, detail = "") {
  const mark = ok ? `${C.green}✓${C.reset}` : `${C.red}✗${C.reset}`;
  const d = detail ? `  ${C.dim}${detail}${C.reset}` : "";
  out(`   ${mark} ${label}${d}`);
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

async function waitUntil(fn, timeoutMs = 120000, intervalMs = 1500) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    try { if (await fn()) return true; } catch (_) {}
    await sleep(intervalMs);
  }
  return false;
}

// readyReplicas for a Deployment (defaults to 0 when unset/absent).
async function readyReplicas(deploy) {
  const r = await kubectl(
    `get deploy ${deploy} -n ${NS} -o jsonpath={.status.readyReplicas}`, { check: false });
  return parseInt(r || "0", 10);
}
async function specReplicas(deploy) {
  const r = await kubectl(
    `get deploy ${deploy} -n ${NS} -o jsonpath={.spec.replicas}`, { check: false });
  return parseInt(r || "0", 10);
}
// active server pod name (label-selected; the Deployment's single replica).
async function serverPod() {
  return kubectl(
    `get pods -n ${NS} -l ${SERVER_LABEL} -o jsonpath={.items[0].metadata.name}`, { check: false });
}

// ---- OIDC well-known probe (in-cluster only → goes THROUGH a pod) ----------
// read-only: one-shot throwaway curl pod (never persists; never touches app data).
async function oidcCodeOneShot(tries = 3) {
  for (let i = 0; i < tries; i++) {
    const code = await kubectl(
      `run adr-${Date.now()} -n ${NS} --rm -i --restart=Never --image=${CURL_IMAGE} --command -- ` +
      `curl -s -o /dev/null -w "%{http_code}" --max-time 8 ${WELLKNOWN_URL}`,
      { check: false, timeout: 70000 });
    // take the TRAILING 3-digit group: curl writes http_code last, and `kubectl run -i` attach can
    // prepend stray bytes (observed "200200"), which a \b…\b match mis-reads as no-code.
    const m = (code || "").match(/(\d{3})(?!\d)/);
    if (m) return m[1];
    await sleep(1500);
  }
  return "000";
}
const isOk = (code) => /^2\d\d$/.test(String(code));

// ---- persistent throwaway probe pod (destructive tier ONLY) ----------------
// a sleeping curl pod we exec into on a tight loop, so downtime is measured at ~1s resolution.
// It is a CANARY: no app data, deleted in afterAll, and it only ever GETs the public well-known.
async function createProbe() {
  await kubectl(
    `run ${PROBE_POD} -n ${NS} --restart=Never --image=${CURL_IMAGE} --command -- sleep 3600`,
    { check: false });
  await kubectl(`wait --for=condition=Ready pod/${PROBE_POD} -n ${NS} --timeout=120s`, { check: false });
}
const deleteProbe = () =>
  kubectl(`delete pod ${PROBE_POD} -n ${NS} --ignore-not-found --wait=false`, { check: false });
async function probeCode() {
  const code = await kubectl(
    `exec ${PROBE_POD} -n ${NS} -- curl -s -o /dev/null -w "%{http_code}" --max-time 3 ${WELLKNOWN_URL}`,
    { check: false, timeout: 15000 });
  const m = (code || "").match(/(\d{3})(?!\d)/); // trailing http_code (see oidcCodeOneShot note)
  return m ? m[1] : "000";
}

// ---- background OIDC probe (via the persistent probe pod) -------------------
function startProbe(intervalMs = 500) {
  const samples = []; // { t, ok }
  let running = true;
  (async () => {
    while (running) {
      const t = Date.now();
      const ok = isOk(await probeCode());
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

// ---- measurements collector (printed as a summary table at the end) --------
const METRICS = [];
const record = (name, m) => METRICS.push({ name, ...m });
function printSummary() {
  if (!METRICS.length) return;
  const pad = (s, n) => String(s).padEnd(n);
  out(`\n${C.bold}${C.cyan}════════════════ AUTHENTIK DR TEST — MEASUREMENTS ════════════════${C.reset}`);
  out(`   ${C.dim}${pad("Metric", 42)}${pad("Measured", 11)}${pad("Threshold", 11)}Result${C.reset}`);
  out(`   ${C.dim}${"─".repeat(72)}${C.reset}`);
  for (const m of METRICS) {
    const meas = m.value !== undefined ? `${m.value}${m.unit || ""}` : m.text || "—";
    const thr = m.threshold !== undefined ? `≤ ${m.threshold}${m.unit || ""}` : m.thresholdText || "—";
    const mark = m.ok ? `${C.green}✓ PASS${C.reset}` : `${C.red}✗ FAIL${C.reset}`;
    const mc = m.ok ? C.green : C.red;
    out(`   ${pad(m.name, 42)}${mc}${pad(meas, 11)}${C.reset}${C.dim}${pad(thr, 11)}${C.reset}${mark}`);
  }
  const passed = METRICS.filter((m) => m.ok).length;
  out(`   ${C.dim}${"─".repeat(72)}${C.reset}`);
  out(`   ${C.bold}${passed}/${METRICS.length} metrics within threshold${C.reset}`);
  out(`${C.bold}${C.cyan}═════════════════════════════════════════════════════════════════${C.reset}\n`);
}

// ============================================================================
describe("Authentik SSO — disaster recovery", () => {
  jest.setTimeout(300000);

  beforeAll(async () => {
    step("Pre-flight");
    const ready = await readyReplicas(SERVER_DEPLOY);
    check(`Deployment ${SERVER_DEPLOY} ready`, ready >= 1, `readyReplicas=${ready}`);
    if (!DESTRUCTIVE) {
      info("read-only mode — set AUTHENTIK_DR_DESTRUCTIVE=1 for the chaos scenarios");
      return;
    }
    step("Spinning up the throwaway OIDC probe pod (chaos measurement — real services untouched)");
    await createProbe();
    info(`probe ${PROBE_POD} ready; initial well-known code ${await probeCode()}`);
  }, 200000);

  afterAll(async () => { if (DESTRUCTIVE) await deleteProbe(); printSummary(); });

  // ---- READ-ONLY tier: assert the DR machinery EXISTS + is healthy ---------

  test("authentik-server is Ready (single-replica auth SPOF)", async () => {
    const ready = await readyReplicas(SERVER_DEPLOY);
    const replicas = await specReplicas(SERVER_DEPLOY);
    check(`${SERVER_DEPLOY} ready ${ready}/${replicas}`, ready >= 1);
    info(`server is a SINGLE replica (${replicas}) — cluster-wide SSO SPOF; this suite measures its recovery`);
    record("authentik-server Ready", { text: `${ready}/${replicas}`, thresholdText: "≥ 1", ok: ready >= 1 });
    expect(ready).toBeGreaterThanOrEqual(1);
  });

  test("authentik-worker is Ready (blueprint/OIDC reconciler)", async () => {
    const ready = await readyReplicas(WORKER_DEPLOY);
    check(`${WORKER_DEPLOY} ready`, ready >= 1, `readyReplicas=${ready}`);
    record("authentik-worker Ready", { text: ready >= 1 ? "yes" : "no", thresholdText: "yes", ok: ready >= 1 });
    expect(ready).toBeGreaterThanOrEqual(1);
  });

  test("OIDC well-known / token endpoint returns 200 (in-cluster)", async () => {
    step("Read-only OIDC health: curl the well-known discovery THROUGH a throwaway pod");
    const code = await oidcCodeOneShot();
    check(`GET ${WELLKNOWN_PATH} → ${code}`, isOk(code), WELLKNOWN_URL);
    record("OIDC well-known endpoint 200", { text: code, thresholdText: "2xx", ok: isOk(code) });
    expect(isOk(code)).toBe(true);
  });

  test("CNPG authentik-postgres is healthy (HA, node-independent)", async () => {
    const phase = await kubectl(
      `get cluster ${PG_CLUSTER} -n ${NS} -o jsonpath={.status.phase}`, { check: false });
    const readyInst = parseInt(await kubectl(
      `get cluster ${PG_CLUSTER} -n ${NS} -o jsonpath={.status.readyInstances}`, { check: false }) || "0", 10);
    const instances = parseInt(await kubectl(
      `get cluster ${PG_CLUSTER} -n ${NS} -o jsonpath={.spec.instances}`, { check: false }) || "0", 10);
    const healthy = /healthy/i.test(phase) && instances > 0 && readyInst === instances;
    check(`${PG_CLUSTER} phase`, /healthy/i.test(phase), phase || "(none)");
    check(`${PG_CLUSTER} instances all ready`, instances > 0 && readyInst === instances, `${readyInst}/${instances}`);
    record("CNPG authentik-postgres healthy", { text: `${readyInst}/${instances}`, thresholdText: "all ready", ok: healthy });
    expect(healthy).toBe(true);
  });

  // ---- DESTRUCTIVE tier: kill the single server pod, MEASURE OIDC downtime --

  dtest("CHAOS: delete authentik-server pod → OIDC recovers to 200 + measure downtime", async () => {
    const before = await serverPod();
    step(`Chaos: delete the single authentik-server pod ${C.yellow}${before}${C.reset} (postgres/PVC untouched)`);
    const probe = startProbe();
    await sleep(1500); // establish a healthy baseline in the samples
    await kubectl(`delete pod ${before} -n ${NS} --wait=false`);
    info("waiting for the OIDC well-known endpoint to answer 200 again (server cold start)…");
    const t0 = Date.now();
    const recovered = await waitUntil(async () => isOk(await probeCode()), MAX_RECOVERY_S * 1000, 1000);
    const recoveryS = (Date.now() - t0) / 1000;
    await sleep(3000); // let the probe capture the tail of the recovery
    probe.stop();
    const dt = probe.worstDowntime();
    const now = await serverPod();
    const stillOne = (await specReplicas(SERVER_DEPLOY)) === 1;
    check("OIDC endpoint recovered to 200 after server kill", recovered, now ? `serving pod ${now}` : "TIMEOUT");
    gauge("OIDC recovery time (well-known → 200)", recoveryS, MAX_RECOVERY_S);
    gauge("OIDC downtime (worst contiguous outage)", dt, MAX_DOWNTIME_S);
    check("server still single-replica (Deployment recreated it, no scale change)", stillOne);
    info(`OIDC availability during the kill window: ${(probe.availability() * 100).toFixed(1)}%`);
    record("OIDC recovery time (server kill)", {
      value: recoveryS.toFixed(2), unit: "s", threshold: MAX_RECOVERY_S, ok: recovered && recoveryS <= MAX_RECOVERY_S });
    record("OIDC worst downtime (server kill)", {
      value: dt.toFixed(2), unit: "s", threshold: MAX_DOWNTIME_S, ok: recovered && dt <= MAX_DOWNTIME_S });
    record("OIDC availability during kill", {
      value: (probe.availability() * 100).toFixed(1), unit: "%", thresholdText: "—", ok: recovered });
    expect(recovered).toBe(true);
    expect(recoveryS).toBeLessThanOrEqual(MAX_RECOVERY_S);
  });
});
