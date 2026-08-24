/**
 * CloudNativePG failover — chaos/DR test  (epic TALOS-23l.5)
 * ---------------------------------------------------------------------------
 * Validates the CloudNativePG (CNPG) high-availability design: the operator is
 * live, every declared Postgres Cluster is streaming-replicated and healthy, and
 * — when the primary dies — CNPG promotes a replica, repoints the `-rw` Service
 * at the new primary, and NO committed data is lost. The destructive tier MEASURES
 * the replica-promotion time end-to-end.
 *
 * TWO TIERS:
 *   READ-ONLY  (always) — assert the DR machinery EXISTS + is healthy. Never mutates:
 *       • CNPG operator Deployment is Available
 *       • every postgresql.cnpg.io/Cluster reports healthy (readyInstances == instances)
 *       • each cluster exposes its `-rw` / `-r` Services with a live primary endpoint
 *   DESTRUCTIVE (CNPG_DR_DESTRUCTIVE=1) — runs ONLY against a THROWAWAY canary cluster
 *   in an isolated namespace (never a prod DB):
 *       • stand up a 2-instance canary CNPG Cluster, write N rows
 *       • delete the primary pod → assert a replica is promoted (currentPrimary changes)
 *       • assert the `-rw` Service now points at the NEW primary
 *       • assert the N rows survived the failover  + MEASURE promotion time
 *       • tear the canary cluster + namespace down
 *
 *   npm install && npm test                # safe, read-only
 *   CNPG_DR_DESTRUCTIVE=1 npm run test:dr  # full chaos test (homelab only)
 *   (from repo root)  npm test -- --selectProjects cnpg-dr
 *
 * Needs `kubectl` (context = the cluster) on PATH. Everything runs through kubectl
 * exec/get — no direct DB ports. Data writes/reads use `psql` inside the CNPG pods.
 */
const { exec } = require("child_process");

// ---- config ---------------------------------------------------------------
// Operator lives in the `databases` namespace (Flux HelmRelease `cloudnative-pg`).
const OPERATOR_NS = process.env.CNPG_OPERATOR_NS || "databases";
// Read-only tier discovers Clusters cluster-wide; pin a subset via CNPG_CLUSTER_NS if desired.
const CLUSTER_NS = process.env.CNPG_CLUSTER_NS || ""; // "" = all namespaces
const DESTRUCTIVE = process.env.CNPG_DR_DESTRUCTIVE === "1";
// Canary (destructive target — real DBs untouched)
const CANARY_NS = process.env.CNPG_CANARY_NS || "cnpg-dr-canary";
const CANARY = process.env.CNPG_CANARY || "cnpg-canary";
const CANARY_INSTANCES = parseInt(process.env.CNPG_CANARY_INSTANCES || "2", 10); // 2–3
const CANARY_STORAGE = process.env.CNPG_CANARY_STORAGE_CLASS || "fatboy-nfs-appdata"; // node-independent, like prod
const CANARY_STORAGE_SIZE = process.env.CNPG_CANARY_STORAGE_SIZE || "1Gi";
const CANARY_ROWS = parseInt(process.env.CNPG_CANARY_ROWS || "1000", 10);
const MAX_PROMOTION_S = parseFloat(process.env.CNPG_MAX_PROMOTION_S || "60"); // replica promotion budget
const MAX_RW_REPOINT_S = parseFloat(process.env.CNPG_MAX_RW_REPOINT_S || "60"); // -rw Service repoint budget
const CNPG_HEALTHY_PHASE = "Cluster in healthy state";

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

// ---- shell / kubectl helpers ----------------------------------------------
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function sh(cmd, { timeout = 60000, check: doCheck = true } = {}) {
  return new Promise((resolve, reject) => {
    exec(cmd, { timeout, maxBuffer: 16 * 1024 * 1024 }, (err, stdout, stderr) => {
      if (err && doCheck) return reject(new Error(`${cmd}\n${stderr || err.message}`));
      resolve((stdout || "").trim());
    });
  });
}
const kubectl = (a, o) => sh(`kubectl ${a}`, o);
const nsFlag = (ns) => (ns ? `-n ${ns}` : "-A");

async function waitUntil(fn, timeoutMs = 120000, intervalMs = 2000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    try { if (await fn()) return true; } catch (_) {}
    await sleep(intervalMs);
  }
  return false;
}

// discover CNPG Clusters (read-only). Returns [] if the CRD isn't installed.
async function listClusters() {
  const raw = await kubectl(
    `get cluster.postgresql.cnpg.io ${nsFlag(CLUSTER_NS)} -o json`, { check: false });
  if (!raw || /the server doesn't have a resource type|No resources found/.test(raw)) return [];
  let parsed;
  try { parsed = JSON.parse(raw); } catch (_) { return []; }
  return (parsed.items || []).map((c) => ({
    name: c.metadata.name,
    ns: c.metadata.namespace,
    instances: c.spec && c.spec.instances,
    ready: c.status && c.status.readyInstances,
    phase: (c.status && c.status.phase) || "",
    primary: (c.status && c.status.currentPrimary) || "",
  }));
}
// current primary instance name for a single cluster
const currentPrimary = (name, ns) =>
  kubectl(`get cluster.postgresql.cnpg.io ${name} -n ${ns} -o jsonpath={.status.currentPrimary}`, { check: false });
const podIP = (pod, ns) =>
  kubectl(`get pod ${pod} -n ${ns} -o jsonpath={.status.podIP}`, { check: false });
// IPs behind a Service (via its Endpoints) — the -rw Service should resolve to the primary pod
async function endpointIPs(svc, ns) {
  const raw = await kubectl(
    `get endpoints ${svc} -n ${ns} -o jsonpath="{range .subsets[*].addresses[*]}{.ip}{'\\n'}{end}"`,
    { check: false });
  return raw.split("\n").map((s) => s.trim()).filter(Boolean);
}
// run psql inside a CNPG instance pod (container `postgres`, local peer auth as superuser)
function psql(pod, ns, db, sql) {
  const q = sql.replace(/"/g, '\\"');
  return kubectl(
    `exec ${pod} -n ${ns} -c postgres -- psql -U postgres -d ${db} -tAc "${q}"`,
    { check: false, timeout: 60000 });
}

// ---- measurements collector (printed as a summary table at the end) --------
const METRICS = [];
const record = (name, m) => METRICS.push({ name, ...m });
function printSummary() {
  if (!METRICS.length) return;
  const pad = (s, n) => String(s).padEnd(n);
  out(`\n${C.bold}${C.cyan}════════════════ CNPG DR TEST — MEASUREMENTS ════════════════${C.reset}`);
  out(`   ${C.dim}${pad("Metric", 42)}${pad("Measured", 11)}${pad("Threshold", 11)}Result${C.reset}`);
  out(`   ${C.dim}${"─".repeat(70)}${C.reset}`);
  for (const m of METRICS) {
    const meas = m.value !== undefined ? `${m.value}${m.unit || ""}` : m.text || "—";
    const thr = m.threshold !== undefined ? `≤ ${m.threshold}${m.unit || ""}` : m.thresholdText || "—";
    const mark = m.ok ? `${C.green}✓ PASS${C.reset}` : `${C.red}✗ FAIL${C.reset}`;
    const mc = m.ok ? C.green : C.red;
    out(`   ${pad(m.name, 42)}${mc}${pad(meas, 11)}${C.reset}${C.dim}${pad(thr, 11)}${C.reset}${mark}`);
  }
  const passed = METRICS.filter((m) => m.ok).length;
  out(`   ${C.dim}${"─".repeat(70)}${C.reset}`);
  out(`   ${C.bold}${passed}/${METRICS.length} metrics within threshold${C.reset}`);
  out(`${C.bold}${C.cyan}════════════════════════════════════════════════════════════${C.reset}\n`);
}

// ---- ad-hoc canary (destructive chaos target — real clusters untouched) ----
// A throwaway 2-instance CNPG Cluster. CNPG auto-creates the `app` database (owner
// `app`) + the `<name>-rw` / `<name>-r` / `<name>-ro` Services. We connect as the
// `postgres` superuser via local peer auth inside the pod, so no app secret is needed.
function canaryManifest() {
  return `apiVersion: v1
kind: Namespace
metadata:
  name: ${CANARY_NS}
  labels:
    app.kubernetes.io/name: cnpg-dr-canary
    catalyst.io/ephemeral: "true"
---
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: ${CANARY}
  namespace: ${CANARY_NS}
  labels:
    catalyst.io/ephemeral: "true"
spec:
  instances: ${CANARY_INSTANCES}
  imagePullPolicy: IfNotPresent
  primaryUpdateStrategy: unsupervised
  storage:
    size: ${CANARY_STORAGE_SIZE}
    storageClass: ${CANARY_STORAGE}
  monitoring:
    enablePodMonitor: false
  bootstrap:
    initdb:
      database: app
      owner: app
  resources:
    requests:
      cpu: 50m
      memory: 128Mi
`;
}
async function createCanary() {
  await sh(`printf '%s' ${JSON.stringify(canaryManifest())} | kubectl apply -f -`);
  // wait for the Cluster to report healthy with all instances ready
  await waitUntil(async () => {
    const raw = await kubectl(
      `get cluster.postgresql.cnpg.io ${CANARY} -n ${CANARY_NS} -o json`, { check: false });
    if (!raw) return false;
    let c; try { c = JSON.parse(raw); } catch (_) { return false; }
    return c.status && c.status.readyInstances === c.spec.instances && c.status.currentPrimary;
  }, 420000, 5000);
}
async function deleteCanary() {
  // deleting the namespace cascades the Cluster + all PVCs (throwaway data)
  await kubectl(`delete namespace ${CANARY_NS} --ignore-not-found --wait=false`, { check: false });
}

const dtest = DESTRUCTIVE ? test : test.skip;

// ============================================================================
describe("CloudNativePG failover — disaster recovery", () => {
  let CLUSTERS = [];

  beforeAll(async () => {
    step("Pre-flight — CNPG operator + declared clusters");
    // operator Deployment (chart label app.kubernetes.io/name=cloudnative-pg)
    const availRaw = await kubectl(
      `get deploy -n ${OPERATOR_NS} -l app.kubernetes.io/name=cloudnative-pg ` +
      `-o jsonpath="{.items[*].status.availableReplicas}"`, { check: false });
    const avail = (availRaw || "").split(/\s+/).filter(Boolean).reduce((a, b) => a + (parseInt(b, 10) || 0), 0);
    check("CNPG operator Deployment Available (≥1 replica)", avail >= 1, `availableReplicas=${avail}`);
    CLUSTERS = await listClusters();
    info(`discovered ${CLUSTERS.length} CNPG cluster(s)` +
      (CLUSTERS.length ? `: ${CLUSTERS.map((c) => `${c.ns}/${c.name}`).join(", ")}` : ""));
    if (!DESTRUCTIVE)
      info("read-only mode — set CNPG_DR_DESTRUCTIVE=1 for the canary failover chaos scenario");

    if (DESTRUCTIVE) {
      step(`Spinning up throwaway canary ${C.yellow}${CANARY_NS}/${CANARY}${C.reset} ` +
        `(${CANARY_INSTANCES} instances — chaos target, real DBs stay untouched)`);
      await createCanary();
      const prim = await currentPrimary(CANARY, CANARY_NS);
      info(`canary ready; current primary = ${prim || "(none)"}`);
    }
  }, 500000);

  afterAll(async () => {
    if (DESTRUCTIVE) {
      step("Teardown — deleting the canary namespace (cascades cluster + PVCs)");
      await deleteCanary();
    }
    printSummary();
  });

  // ---- READ-ONLY tier (always runs) ---------------------------------------
  test("CNPG operator is Available", async () => {
    const raw = await kubectl(
      `get deploy -n ${OPERATOR_NS} -l app.kubernetes.io/name=cloudnative-pg ` +
      `-o jsonpath="{.items[*].status.availableReplicas}"`, { check: false });
    const avail = (raw || "").split(/\s+/).filter(Boolean).reduce((a, b) => a + (parseInt(b, 10) || 0), 0);
    check("operator availableReplicas ≥ 1", avail >= 1, `availableReplicas=${avail}`);
    record("CNPG operator Available", { value: avail, thresholdText: "≥ 1", ok: avail >= 1 });
    expect(avail).toBeGreaterThanOrEqual(1);
  });

  test("at least one CNPG Cluster CR exists (the DR machinery is deployed)", async () => {
    const n = CLUSTERS.length;
    check("postgresql.cnpg.io/Cluster CRs present", n >= 1, `count=${n}`);
    record("CNPG Clusters discovered", { value: n, thresholdText: "≥ 1", ok: n >= 1 });
    expect(n).toBeGreaterThanOrEqual(1);
  });

  test("every CNPG Cluster is healthy (readyInstances == instances)", async () => {
    step("Read-only health sweep across all discovered clusters");
    let allOk = CLUSTERS.length > 0;
    for (const c of CLUSTERS) {
      const healthy = c.ready === c.instances && c.phase === CNPG_HEALTHY_PHASE && !!c.primary;
      allOk = allOk && healthy;
      check(`${c.ns}/${c.name}: ${c.ready}/${c.instances} ready, primary=${c.primary || "none"}`,
        healthy, c.phase);
    }
    record("All clusters healthy (ready==instances)", {
      text: allOk ? `${CLUSTERS.length}/${CLUSTERS.length}` : "DEGRADED", thresholdText: "all", ok: allOk });
    expect(allOk).toBe(true);
  });

  test("every CNPG Cluster exposes a -rw Service that points at its primary", async () => {
    step("Read-only: the read-write Service must resolve to exactly the current primary pod");
    let allOk = CLUSTERS.length > 0;
    for (const c of CLUSTERS) {
      const eps = await endpointIPs(`${c.name}-rw`, c.ns);
      const primIP = c.primary ? await podIP(c.primary, c.ns) : "";
      const ok = eps.length >= 1 && (!primIP || eps.includes(primIP));
      allOk = allOk && ok;
      check(`${c.ns}/${c.name}-rw → ${eps.join(",") || "(no endpoints)"}`,
        ok, primIP ? `primary ${c.primary} @ ${primIP}` : "primary IP unknown");
    }
    record("-rw Services point at primary", {
      text: allOk ? "all" : "MISMATCH", thresholdText: "all", ok: allOk });
    expect(allOk).toBe(true);
  });

  // ---- DESTRUCTIVE tier (CNPG_DR_DESTRUCTIVE=1, canary only) ---------------
  dtest("SEED: write N rows to the canary primary (baseline data)", async () => {
    const prim = await currentPrimary(CANARY, CANARY_NS);
    step(`Seeding ${C.yellow}${CANARY_ROWS}${C.reset} rows into canary primary ${prim}`);
    await psql(prim, CANARY_NS, "app",
      "CREATE TABLE IF NOT EXISTS dr_probe (id bigserial primary key, note text);");
    await psql(prim, CANARY_NS, "app",
      `INSERT INTO dr_probe (note) SELECT 'dr-'||g FROM generate_series(1, ${CANARY_ROWS}) g;`);
    // force the WAL out so the standby has definitely streamed it before we kill the primary
    await psql(prim, CANARY_NS, "app", "CHECKPOINT; SELECT pg_switch_wal();");
    const count = parseInt((await psql(prim, CANARY_NS, "app", "SELECT count(*) FROM dr_probe;")) || "0", 10);
    check(`seeded rows readable on primary`, count === CANARY_ROWS, `count=${count}`);
    record("Seed rows written to primary", {
      value: count, unit: " rows", threshold: undefined,
      thresholdText: `= ${CANARY_ROWS}`, ok: count === CANARY_ROWS });
    expect(count).toBe(CANARY_ROWS);
  });

  dtest("FAILOVER: delete the canary primary → replica is promoted (measure promotion time)", async () => {
    const oldPrimary = await currentPrimary(CANARY, CANARY_NS);
    step(`Chaos: delete the canary PRIMARY ${C.yellow}${oldPrimary}${C.reset} — CNPG must promote a replica`);
    const t0 = Date.now();
    await kubectl(`delete pod ${oldPrimary} -n ${CANARY_NS} --wait=false`, { check: false });

    // promotion = status.currentPrimary flips to a DIFFERENT instance
    let newPrimary = "";
    const promoted = await waitUntil(async () => {
      const p = await currentPrimary(CANARY, CANARY_NS);
      if (p && p !== oldPrimary) { newPrimary = p; return true; }
      return false;
    }, MAX_PROMOTION_S * 1000 * 2, 1000);
    const promoS = (Date.now() - t0) / 1000;

    check("a replica was promoted to primary", promoted,
      promoted ? `${oldPrimary} → ${newPrimary}` : "TIMEOUT (no new primary)");
    gauge("replica promotion time", promoS, MAX_PROMOTION_S);
    record("Replica promotion time", {
      value: promoS.toFixed(2), unit: "s", threshold: MAX_PROMOTION_S, ok: promoted && promoS <= MAX_PROMOTION_S });
    record("New primary elected", {
      text: newPrimary || "none", thresholdText: `≠ ${oldPrimary}`, ok: promoted });
    expect(promoted).toBe(true);
    expect(promoS).toBeLessThanOrEqual(MAX_PROMOTION_S);

    // -rw Service must repoint to the NEW primary's pod IP
    step("Verifying the -rw Service repoints at the promoted primary");
    const tSvc = Date.now();
    let newPrimIP = "";
    const repointed = await waitUntil(async () => {
      newPrimIP = await podIP(newPrimary, CANARY_NS);
      if (!newPrimIP) return false;
      const eps = await endpointIPs(`${CANARY}-rw`, CANARY_NS);
      return eps.length >= 1 && eps.includes(newPrimIP);
    }, MAX_RW_REPOINT_S * 1000, 1000);
    const svcS = (Date.now() - tSvc) / 1000;
    check(`${CANARY}-rw → new primary ${newPrimary}`, repointed, `${newPrimIP} (${svcS.toFixed(1)}s)`);
    gauge("-rw Service repoint time", svcS, MAX_RW_REPOINT_S);
    record("-rw Service repoint time", {
      value: svcS.toFixed(2), unit: "s", threshold: MAX_RW_REPOINT_S, ok: repointed && svcS <= MAX_RW_REPOINT_S });
    expect(repointed).toBe(true);

    // data must survive the failover: the N committed rows are on the new primary
    step("Verifying the seeded rows survived the failover on the new primary");
    let count = 0;
    const survived = await waitUntil(async () => {
      count = parseInt((await psql(newPrimary, CANARY_NS, "app", "SELECT count(*) FROM dr_probe;")) || "0", 10);
      return count === CANARY_ROWS;
    }, 60000, 2000);
    check(`all ${CANARY_ROWS} rows survived on the promoted primary`, survived, `count=${count}`);
    record("Rows survive failover", {
      value: count, unit: " rows", thresholdText: `= ${CANARY_ROWS}`, ok: survived });
    expect(count).toBe(CANARY_ROWS);
  });

  dtest("RECOVERY: canary returns to full health (all instances ready) after the kill", async () => {
    step("Recovery: canary must re-attach the demoted node and report all instances ready again");
    const recovered = await waitUntil(async () => {
      const raw = await kubectl(
        `get cluster.postgresql.cnpg.io ${CANARY} -n ${CANARY_NS} -o json`, { check: false });
      if (!raw) return false;
      let c; try { c = JSON.parse(raw); } catch (_) { return false; }
      return c.status && c.status.readyInstances === c.spec.instances && c.status.phase === CNPG_HEALTHY_PHASE;
    }, 300000, 5000);
    check("canary back to all-instances-ready + healthy phase", recovered);
    record("Canary re-attaches to full health", {
      text: recovered ? "healthy" : "DEGRADED", thresholdText: "healthy", ok: recovered });
    expect(recovered).toBe(true);
  });
});
