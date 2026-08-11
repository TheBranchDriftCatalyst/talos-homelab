/**
 * Traefik ingress — disaster-recovery / chaos test  (TALOS-23l.8)
 * ----------------------------------------------------------------
 * Traefik runs as a single-replica-per-node DaemonSet binding hostPort 80/443, so on any
 * given node the whole-cluster ingress path is a SPOF: one pod down = that node's :80/:443
 * is dark until the DaemonSet reschedules and rebinds the hostPort. This suite proves the DR
 * machinery EXISTS + is healthy, then (destructive) kills the serving Traefik pod behind a
 * high-frequency probe against a BENIGN whoami route and MEASURES the ingress downtime.
 *
 * Read-only checks always run (they only observe — never mutate). DESTRUCTIVE scenarios
 * (they delete the serving Traefik pod) run only when
 *     TRAEFIK_DR_DESTRUCTIVE=1
 * so this can never black-hole ingress by accident. The chaos ONLY ever probes the throwaway
 * whoami test route and ONLY ever deletes self-healing Traefik infra pods — no real app route
 * and no persistent data is ever touched.
 *
 *   npm install && npm test                  # safe, read-only
 *   TRAEFIK_DR_DESTRUCTIVE=1 npm run test:dr  # full chaos test (homelab only)
 *
 * Needs `kubectl` (context = the Talos cluster) on PATH. The high-frequency probe hits the
 * node hostPort (curl from the host); the read-only route check ALSO probes in-cluster via a
 * throwaway curl pod against the Traefik ClusterIP service (works even off-LAN).
 */
const { exec } = require("child_process");

// ---- config ---------------------------------------------------------------
const TRAEFIK_NS = process.env.TRAEFIK_NS || "traefik";
const TRAEFIK_DS = process.env.TRAEFIK_DS || "traefik";
const TRAEFIK_POD_LABEL = process.env.TRAEFIK_POD_LABEL || "app=traefik";
// in-cluster ClusterIP service (web entrypoint) — used for the robust in-cluster route probe
const TRAEFIK_SVC = process.env.TRAEFIK_SVC || "traefik.traefik.svc.cluster.local";
// the BENIGN test route (no auth, no bot-wrangler) — infrastructure/base/whoami/ingressroute.yaml
const WHOAMI_NS = process.env.WHOAMI_NS || "default";
const WHOAMI_ROUTE = process.env.WHOAMI_ROUTE || "whoami-http-noauth";
const WHOAMI_DEPLOY = process.env.WHOAMI_DEPLOY || "whoami";
const WHOAMI_HOST = process.env.WHOAMI_HOST || "whoami.talos00";
// node whose hostPort:80 we probe + whose Traefik pod we kill (talos00 control plane by default)
const NODE_IP = process.env.TRAEFIK_NODE_IP || "192.168.1.54";
const DESTRUCTIVE = process.env.TRAEFIK_DR_DESTRUCTIVE === "1";
const MAX_RECOVERY_S = parseFloat(process.env.TRAEFIK_MAX_RECOVERY_S || "45");

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

// HTTP status of the benign whoami route via the node hostPort (curl from the host). Fast enough
// for a high-frequency background probe; 200 = whoami answered through Traefik.
async function routeStatusFromHost(timeoutS = 1) {
  const code = await sh(
    `curl -s -o /dev/null -w "%{http_code}" --max-time ${timeoutS} -H "Host: ${WHOAMI_HOST}" http://${NODE_IP}`,
    { timeout: (timeoutS + 2) * 1000, check: false });
  return parseInt(code || "0", 10);
}
const routeOkFromHost = async (timeoutS = 1) => (await routeStatusFromHost(timeoutS)) === 200;

// HTTP status of the benign whoami route from INSIDE the cluster (throwaway curl pod → Traefik
// ClusterIP svc). Robust even when the host can't reach the node hostPort (off-LAN CI). Retries:
// the very first probe pod can miss (cold DNS / pod not yet networked) and read empty → HTTP 0.
async function routeStatusInCluster(timeoutS = 5, tries = 3) {
  let last = 0;
  for (let i = 0; i < tries; i++) {
    const o = await kubectl(
      `run tfdr-${Date.now()} -n ${WHOAMI_NS} --rm -i --restart=Never --image=curlimages/curl:8.10.1 --command -- ` +
      `curl -s -o /dev/null -w "%{http_code}" --max-time ${timeoutS} -H "Host: ${WHOAMI_HOST}" http://${TRAEFIK_SVC}`,
      { timeout: 70000, check: false });
    // curl's %{http_code} is the FIRST thing on stdout; kubectl's `pod "x" deleted` notice is
    // appended right after (no newline) → e.g. "200pod ... deleted". Anchor to the leading digits.
    const m = (o || "").match(/^(\d{3})/);
    last = m ? parseInt(m[1], 10) : 0;
    if (last === 200) return last;
    await sleep(1500);
  }
  return last;
}

// map the probed node IP → node name → the Traefik pod scheduled there (the "serving" pod).
async function nodeNameForIP(ip) {
  const jp = `jsonpath={range .items[*]}{.metadata.name}|{.status.addresses[?(@.type=="InternalIP")].address}{'\\n'}{end}`;
  const o = await kubectl(`get nodes -o "${jp}"`, { check: false });
  const row = o.split("\n").map((l) => l.split("|")).find(([, addr]) => (addr || "").trim() === ip);
  return row ? row[0] : null;
}
async function traefikPods() {
  const jp = "jsonpath={range .items[*]}{.metadata.name}|{.spec.nodeName}|{.status.phase}{'\\n'}{end}";
  const o = await kubectl(`get pods -n ${TRAEFIK_NS} -l ${TRAEFIK_POD_LABEL} -o "${jp}"`, { check: false });
  return o.split("\n").filter(Boolean).map((l) => {
    const [name, node, phase] = l.split("|");
    return { name, node, phase };
  });
}
async function servingPod() {
  const node = await nodeNameForIP(NODE_IP);
  const pods = await traefikPods();
  if (node) {
    const onNode = pods.find((p) => p.node === node);
    if (onNode) return onNode;
  }
  return pods[0] || null; // single-node cluster (or IP unmatched): the only Traefik pod is the server
}
async function dsReady() {
  const desired = await kubectl(`get ds ${TRAEFIK_DS} -n ${TRAEFIK_NS} -o jsonpath={.status.desiredNumberScheduled}`, { check: false });
  const ready = await kubectl(`get ds ${TRAEFIK_DS} -n ${TRAEFIK_NS} -o jsonpath={.status.numberReady}`, { check: false });
  return { desired: parseInt(desired || "0", 10), ready: parseInt(ready || "0", 10) };
}
async function waitUntil(fn, timeoutMs = 120000, intervalMs = 1000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    try { if (await fn()) return true; } catch (_) {}
    await sleep(intervalMs);
  }
  return false;
}

// ---- background ingress probe (high-frequency, against the node hostPort) --
function startProbe(intervalMs = 200) {
  const samples = []; // { t, ok }
  let running = true;
  (async () => {
    while (running) {
      const t = Date.now();
      const ok = await routeOkFromHost();
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
    sampleCount() { return samples.length; },
  };
}

const dtest = DESTRUCTIVE ? test : test.skip;

// ---- measurements collector (printed as a summary table at the end) --------
const METRICS = [];
const record = (name, m) => METRICS.push({ name, ...m });
function printSummary() {
  if (!METRICS.length) return;
  const pad = (s, n) => String(s).padEnd(n);
  out(`\n${C.bold}${C.cyan}════════════════ TRAEFIK DR TEST — MEASUREMENTS ════════════════${C.reset}`);
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
  out(`${C.bold}${C.cyan}═══════════════════════════════════════════════════════════════${C.reset}\n`);
}

// ============================================================================
describe("Traefik ingress — disaster recovery", () => {
  jest.setTimeout(300000);

  beforeAll(async () => {
    step("Pre-flight");
    const { desired, ready } = await dsReady();
    check(`DaemonSet ${TRAEFIK_DS} all pods Ready`, desired > 0 && ready === desired, `ready=${ready}/${desired}`);
    if (!DESTRUCTIVE)
      info("read-only mode — set TRAEFIK_DR_DESTRUCTIVE=1 for the chaos scenarios");
  });

  beforeEach(async () => {
    // each scenario starts from a fully-Ready DaemonSet (previous chaos may still be recovering)
    if (!DESTRUCTIVE) return;
    await waitUntil(async () => {
      const { desired, ready } = await dsReady();
      return desired > 0 && ready === desired;
    }, 180000, 3000);
  });

  afterAll(printSummary);

  // -- READ-ONLY tier: the DR machinery EXISTS + is healthy (never mutates) ----------------

  test("Traefik DaemonSet exists and every pod is Ready", async () => {
    const { desired, ready } = await dsReady();
    const pods = await traefikPods();
    check(`DaemonSet ${TRAEFIK_DS} scheduled`, desired > 0, `desiredNumberScheduled=${desired}`);
    check("all scheduled pods Ready", ready === desired && desired > 0, `numberReady=${ready}/${desired}`);
    check("pods observed", pods.length > 0, pods.map((p) => `${p.name}@${p.node}`).join(", "));
    record("Traefik DaemonSet pods Ready", { text: `${ready}/${desired}`, thresholdText: "all", ok: desired > 0 && ready === desired });
    expect(desired).toBeGreaterThan(0);
    expect(ready).toBe(desired);
  });

  test("benign whoami route + backend exist (the DR probe target)", async () => {
    const routeExists = (await kubectl(
      `get ingressroute ${WHOAMI_ROUTE} -n ${WHOAMI_NS} -o jsonpath={.metadata.name}`, { check: false })) === WHOAMI_ROUTE;
    const backendReady = (await kubectl(
      `get deploy ${WHOAMI_DEPLOY} -n ${WHOAMI_NS} -o jsonpath={.status.readyReplicas}`, { check: false })) === "1";
    check(`IngressRoute ${WHOAMI_NS}/${WHOAMI_ROUTE} exists`, routeExists);
    check(`whoami backend Ready`, backendReady);
    record("Benign whoami DR target present", { text: routeExists && backendReady ? "yes" : "no", thresholdText: "yes", ok: routeExists && backendReady });
    expect(routeExists).toBe(true);
    expect(backendReady).toBe(true);
  });

  test("benign whoami route serves 200 in-cluster (via Traefik ClusterIP svc)", async () => {
    const code = await routeStatusInCluster();
    check(`in-cluster GET http://${TRAEFIK_SVC} (Host: ${WHOAMI_HOST}) → 200`, code === 200, `HTTP ${code}`);
    record("Route 200 in-cluster (baseline)", { text: `HTTP ${code}`, thresholdText: "200", ok: code === 200 });
    expect(code).toBe(200);
  });

  test("benign whoami route serves 200 via node hostPort (SPOF surface)", async () => {
    const code = await routeStatusFromHost(3);
    check(`GET http://${NODE_IP} (Host: ${WHOAMI_HOST}) → 200`, code === 200, `HTTP ${code}`);
    record("Route 200 via node hostPort", { text: `HTTP ${code}`, thresholdText: "200", ok: code === 200 });
    expect(code).toBe(200);
  });

  test("a Traefik pod is scheduled on the probed node (hostPort binder identified)", async () => {
    const pod = await servingPod();
    const node = await nodeNameForIP(NODE_IP);
    check(`serving Traefik pod for ${NODE_IP}`, !!pod, pod ? `${pod.name} @ ${pod.node}` : "none");
    record("Serving hostPort pod identified", { text: pod ? pod.name : "none", thresholdText: "found", ok: !!pod });
    expect(pod).not.toBeNull();
    if (node) expect(pod.node).toBe(node);
  });

  // -- DESTRUCTIVE tier: TRAEFIK_DR_DESTRUCTIVE=1 (kills the serving Traefik pod) ----------

  dtest("FAILOVER: kill the serving Traefik pod → measure ingress downtime + recovery", async () => {
    const before = await servingPod();
    step(`Chaos: delete serving Traefik pod ${C.yellow}${before.name}${C.reset} (node ${before.node}) — hostPort:80 goes dark`);
    const probe = startProbe(200);
    await sleep(1500); // establish a healthy baseline before the kill
    await kubectl(`delete pod ${before.name} -n ${TRAEFIK_NS} --wait=false`);
    info("waiting for the whoami route to answer 200 again (DaemonSet reschedule + hostPort rebind)…");
    const recovered = await waitUntil(async () => await routeOkFromHost(), MAX_RECOVERY_S * 1000, 1000);
    await sleep(4000); // let the probe capture the tail of the recovery
    probe.stop();
    const dt = probe.worstDowntime();
    const nowReady = await dsReady();
    const noSPOFdrift = nowReady.desired > 0; // DaemonSet still owns every node
    check("ingress recovered after serving-pod kill", recovered, recovered ? "route → 200" : "TIMEOUT");
    gauge("ingress downtime (hostPort dark window)", dt, MAX_RECOVERY_S);
    check("DaemonSet still scheduled on every node", noSPOFdrift, `desired=${nowReady.desired} ready=${nowReady.ready}`);
    info(`route availability during the kill window: ${(probe.availability() * 100).toFixed(1)}% over ${probe.sampleCount()} samples`);
    record("Ingress downtime (serving-pod kill)", { value: dt.toFixed(2), unit: "s", threshold: MAX_RECOVERY_S, ok: recovered && dt <= MAX_RECOVERY_S });
    record("Ingress availability during kill", { value: (probe.availability() * 100).toFixed(1), unit: "%", thresholdText: "—", ok: recovered });
    record("DaemonSet recovers to full schedule", { text: recovered ? "yes" : "no", thresholdText: "yes", ok: recovered });
    expect(recovered).toBe(true);
    expect(dt).toBeLessThanOrEqual(MAX_RECOVERY_S);
    expect(noSPOFdrift).toBe(true);
  });
});
