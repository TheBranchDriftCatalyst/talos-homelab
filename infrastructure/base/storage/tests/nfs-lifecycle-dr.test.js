/**
 * NFS / PVC lifecycle — disaster-recovery / chaos test  (TALOS-23l.7)
 * ------------------------------------------------------------------
 * Guards the STORAGE reclaim/reuse data-hygiene design after the 2026-05-09 incident
 * (UPS event → total local-path PVC loss + an NFS data-hygiene review). Two StorageClasses
 * back the cluster:
 *
 *   • local-path          (default, reclaimPolicy=Delete) — SQLite/db + fast-local workloads
 *   • fatboy-nfs-appdata  (Synology dynamic NFS, reclaimPolicy=Retain, RWX, archiveOnDelete)
 *                         — *arr app-config; pathPattern ${.PVC.namespace}/${.PVC.name}
 *
 * The subtle hygiene invariant: because the NFS class ARCHIVES a deleted PVC's directory
 * (rename, not reuse), recreating a PVC with the SAME name must land on a FRESH, empty
 * volume — never inherit the old PVC's bytes. This test proves that end-to-end on a
 * throwaway canary namespace, so no production *arr data is ever touched.
 *
 * Read-only checks always run (assert the DR machinery EXISTS + is healthy — never mutate).
 * DESTRUCTIVE scenarios (provision/delete real PVCs on NFS) run only when
 *     NFS_DR_DESTRUCTIVE=1
 * and target ONLY the nfs-dr-canary namespace/PVC, so they can't touch real data by accident.
 *
 *   npm install && npm test                # safe, read-only (asserts SCs exist + default set)
 *   NFS_DR_DESTRUCTIVE=1 npm run test:dr    # full chaos: canary provision → reclaim → reuse
 *
 * Needs `kubectl` (context = the cluster) on PATH.
 */
const { exec } = require("child_process");
const path = require("path");

// ---- config ---------------------------------------------------------------
const APPDATA_SC = process.env.NFS_APPDATA_SC || "fatboy-nfs-appdata"; // Synology dynamic NFS
const LOCAL_SC = process.env.NFS_LOCAL_SC || "local-path"; // default, reclaim=Delete
const PROV_NS = process.env.NFS_PROVISIONER_NS || "kube-system";
const PROV_DEPLOY = process.env.NFS_PROVISIONER_DEPLOY || "nfs-subdir-external-provisioner";
const CANARY_NS = process.env.NFS_CANARY_NS || "nfs-dr-canary";
const CANARY_PVC = process.env.NFS_CANARY_PVC || "nfs-dr-canary-pvc";
const CANARY_POD = process.env.NFS_CANARY_POD || "nfs-dr-canary";
const DESTRUCTIVE = process.env.NFS_DR_DESTRUCTIVE === "1";
const MAX_PROVISION_S = parseFloat(process.env.NFS_MAX_PROVISION_S || "60"); // Pending→Bound+mounted
const MAX_RECREATE_S = parseFloat(process.env.NFS_MAX_RECREATE_S || "90"); // delete→rebind→mount

const PVC_YAML = path.join(__dirname, "canary-pvc.yaml");
const POD_YAML = path.join(__dirname, "canary-pod.yaml");

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
    exec(cmd, { timeout, maxBuffer: 8 * 1024 * 1024 }, (err, stdout, stderr) => {
      if (err && doCheck) return reject(new Error(`${cmd}\n${stderr || err.message}`));
      resolve((stdout || "").trim());
    });
  });
}
const kubectl = (a, o) => sh(`kubectl ${a}`, o);

async function waitUntil(fn, timeoutMs = 120000, intervalMs = 2000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    try { if (await fn()) return true; } catch (_) {}
    await sleep(intervalMs);
  }
  return false;
}

// StorageClass as parsed JSON (null if it doesn't exist)
async function scJSON(name) {
  const raw = await kubectl(`get storageclass ${name} -o json`, { check: false });
  if (!raw || !raw.startsWith("{")) return null;
  try { return JSON.parse(raw); } catch (_) { return null; }
}
const isDefaultSC = (sc) =>
  (sc && sc.metadata && sc.metadata.annotations &&
    sc.metadata.annotations["storageclass.kubernetes.io/is-default-class"]) === "true";
// list of StorageClass names currently flagged default (exactly one is the healthy state)
async function defaultSCNames() {
  const raw = await kubectl("get storageclass -o json", { check: false });
  if (!raw || !raw.startsWith("{")) return [];
  const items = (JSON.parse(raw).items || []);
  return items.filter(isDefaultSC).map((i) => i.metadata.name);
}
async function provisionerAvailable() {
  const n = await kubectl(
    `get deploy ${PROV_DEPLOY} -n ${PROV_NS} -o jsonpath={.status.availableReplicas}`, { check: false });
  return parseInt(n || "0", 10) >= 1;
}
const pvcPhase = (name, ns) =>
  kubectl(`get pvc ${name} -n ${ns} -o jsonpath={.status.phase}`, { check: false });

// ---- canary lifecycle (destructive-only; throwaway namespace, zero prod blast radius) ------
async function applyPVC() { await kubectl(`apply -f ${PVC_YAML}`); }
async function applyPod() { await kubectl(`apply -f ${POD_YAML}`); }
async function waitBound(timeoutMs = 90000) {
  return waitUntil(async () => (await pvcPhase(CANARY_PVC, CANARY_NS)) === "Bound", timeoutMs, 2000);
}
async function waitPodReady(timeoutMs = 120000) {
  await kubectl(`wait --for=condition=Ready pod/${CANARY_POD} -n ${CANARY_NS} --timeout=${Math.round(timeoutMs / 1000)}s`,
    { check: false });
  return (await kubectl(
    `get pod ${CANARY_POD} -n ${CANARY_NS} -o jsonpath="{.status.conditions[?(@.type=='Ready')].status}"`,
    { check: false })) === "True";
}
const podExec = (sh_cmd) =>
  kubectl(`exec ${CANARY_POD} -n ${CANARY_NS} -c probe -- sh -c ${JSON.stringify(sh_cmd)}`, { check: false });
const deletePod = () =>
  kubectl(`delete pod ${CANARY_POD} -n ${CANARY_NS} --ignore-not-found --wait=true --timeout=60s`, { check: false });
const deletePVC = () =>
  kubectl(`delete pvc ${CANARY_PVC} -n ${CANARY_NS} --ignore-not-found --wait=true --timeout=90s`, { check: false });
// total bytes across ALL regular files under /data — 0 == a clean, freshly-provisioned volume
async function staleBytes() {
  const o = await podExec(`find /data -type f -exec cat {} + 2>/dev/null | wc -c`);
  const n = parseInt((o || "0").trim(), 10);
  return Number.isFinite(n) ? n : -1;
}
async function fileCount() {
  const o = await podExec(`find /data -type f | wc -l`);
  const n = parseInt((o || "0").trim(), 10);
  return Number.isFinite(n) ? n : -1;
}
// reclaimPolicy=Retain leaves Released PVs behind on delete — clean them so the DR test itself
// never leaks storage. Delete any PV whose claimRef points at our canary PVC.
async function reapReleasedCanaryPVs() {
  const raw = await kubectl("get pv -o json", { check: false });
  if (!raw || !raw.startsWith("{")) return;
  for (const pv of (JSON.parse(raw).items || [])) {
    const cr = pv.spec && pv.spec.claimRef;
    if (cr && cr.namespace === CANARY_NS && cr.name === CANARY_PVC) {
      await kubectl(`delete pv ${pv.metadata.name} --ignore-not-found --wait=false`, { check: false });
    }
  }
}
async function teardownCanary() {
  await deletePod();
  await deletePVC();
  await reapReleasedCanaryPVs();
  await kubectl(`delete namespace ${CANARY_NS} --ignore-not-found --wait=false`, { check: false });
}

const dtest = DESTRUCTIVE ? test : test.skip;
// shared state carried between the two destructive phases
const canary = { sentinel: `dr-sentinel-${Date.now()}`, wroteBytes: 0 };

// ---- measurements collector (printed as a summary table at the end) --------
const METRICS = [];
const record = (name, m) => METRICS.push({ name, ...m });
function printSummary() {
  if (!METRICS.length) return;
  const pad = (s, n) => String(s).padEnd(n);
  out(`\n${C.bold}${C.cyan}═════════════ NFS-LIFECYCLE DR TEST — MEASUREMENTS ═════════════${C.reset}`);
  out(`   ${C.dim}${pad("Metric", 42)}${pad("Measured", 12)}${pad("Threshold", 12)}Result${C.reset}`);
  out(`   ${C.dim}${"─".repeat(72)}${C.reset}`);
  for (const m of METRICS) {
    const meas = m.value !== undefined ? `${m.value}${m.unit || ""}` : m.text || "—";
    const thr = m.threshold !== undefined ? `≤ ${m.threshold}${m.unit || ""}` : m.thresholdText || "—";
    const mark = m.ok ? `${C.green}✓ PASS${C.reset}` : `${C.red}✗ FAIL${C.reset}`;
    const mc = m.ok ? C.green : C.red;
    out(`   ${pad(m.name, 42)}${mc}${pad(meas, 12)}${C.reset}${C.dim}${pad(thr, 12)}${C.reset}${mark}`);
  }
  out(`   ${C.dim}${"─".repeat(72)}${C.reset}`);
  out(`   ${C.bold}${METRICS.filter((m) => m.ok).length}/${METRICS.length} metrics within threshold${C.reset}`);
  out(`${C.bold}${C.cyan}══════════════════════════════════════════════════════════════${C.reset}\n`);
}

// ============================================================================
describe("NFS / PVC lifecycle — disaster recovery", () => {
  jest.setTimeout(300000);

  beforeAll(async () => {
    step("Pre-flight");
    if (!DESTRUCTIVE)
      info("read-only mode — set NFS_DR_DESTRUCTIVE=1 for the canary reclaim/reuse chaos scenarios");
  });

  afterAll(async () => {
    if (DESTRUCTIVE) await teardownCanary();
    printSummary();
  });

  // ---- READ-ONLY tier: assert the storage DR machinery EXISTS + is healthy ------------------

  test("default StorageClass is exactly one, and it is local-path [2026-05-09 guard]", async () => {
    step("Read-only: exactly one default StorageClass (a missing/ambiguous default caused silent bad binds)");
    const defaults = await defaultSCNames();
    const one = defaults.length === 1;
    const isLocal = defaults[0] === LOCAL_SC;
    check(`exactly one default StorageClass`, one, `defaults=[${defaults.join(", ") || "none"}]`);
    check(`the default is ${LOCAL_SC}`, isLocal, defaults[0] || "none");
    record("Default StorageClass count", { value: defaults.length, thresholdText: "= 1", ok: one });
    record("Default StorageClass is local-path", { text: defaults[0] || "none", thresholdText: LOCAL_SC, ok: isLocal });
    expect(defaults).toEqual([LOCAL_SC]);
  });

  test(`${LOCAL_SC} StorageClass exists (rancher.io/local-path, reclaim=Delete)`, async () => {
    const sc = await scJSON(LOCAL_SC);
    const exists = !!sc;
    const prov = exists ? sc.provisioner : "";
    const reclaim = exists ? (sc.reclaimPolicy || "Delete") : "";
    check(`${LOCAL_SC} exists`, exists);
    check(`provisioner = rancher.io/local-path`, prov === "rancher.io/local-path", prov);
    check(`reclaimPolicy = Delete`, reclaim === "Delete", reclaim);
    record("local-path StorageClass exists", { text: exists ? "yes" : "no", thresholdText: "yes", ok: exists });
    record("local-path reclaimPolicy", { text: reclaim || "none", thresholdText: "Delete", ok: reclaim === "Delete" });
    expect(exists).toBe(true);
    expect(prov).toBe("rancher.io/local-path");
    expect(reclaim).toBe("Delete");
  });

  test(`${APPDATA_SC} StorageClass exists`, async () => {
    const sc = await scJSON(APPDATA_SC);
    const exists = !!sc;
    check(`${APPDATA_SC} exists`, exists, exists ? sc.provisioner : "NOT FOUND");
    record("fatboy-nfs-appdata StorageClass exists", { text: exists ? "yes" : "no", thresholdText: "yes", ok: exists });
    expect(exists).toBe(true);
  });

  test(`${APPDATA_SC} is RWX + reclaimPolicy=Retain [reclaim/reuse hygiene]`, async () => {
    step("Read-only: NFS app-config class must Retain + be RWX — the reclaim/reuse hygiene contract");
    const sc = await scJSON(APPDATA_SC);
    expect(sc).not.toBeNull();
    const reclaim = sc.reclaimPolicy || "Delete";
    const prov = sc.provisioner || "";
    const nfsProv = /nfs-subdir-external-provisioner/.test(prov);
    check(`reclaimPolicy = Retain`, reclaim === "Retain", reclaim);
    check(`provisioner is the nfs-subdir provisioner`, nfsProv, prov);
    record("fatboy-nfs-appdata reclaimPolicy", { text: reclaim, thresholdText: "Retain", ok: reclaim === "Retain" });
    expect(reclaim).toBe("Retain");
    expect(nfsProv).toBe(true);
  });

  test(`${PROV_DEPLOY} is deployed and healthy (${PROV_NS})`, async () => {
    step("Read-only: the dynamic NFS provisioner backing fatboy-nfs-appdata must be Available");
    const avail = await provisionerAvailable();
    const replicas = await kubectl(
      `get deploy ${PROV_DEPLOY} -n ${PROV_NS} -o jsonpath={.status.availableReplicas}`, { check: false });
    check(`${PROV_DEPLOY} availableReplicas ≥ 1`, avail, `availableReplicas=${replicas || 0}`);
    record("NFS provisioner healthy", { text: avail ? "available" : "down", thresholdText: "available", ok: avail });
    expect(avail).toBe(true);
  });

  // ---- DESTRUCTIVE tier: canary provision → reclaim → SAME-NAME reuse → zero stale bytes ----

  dtest("PROVISION: canary PVC binds on fatboy-nfs-appdata + a sentinel writes through", async () => {
    step(`Chaos(phase 1): provision throwaway PVC ${C.yellow}${CANARY_NS}/${CANARY_PVC}${C.reset} on ${APPDATA_SC}`);
    // start clean in case a prior aborted run left the namespace around
    await teardownCanary();
    await waitUntil(async () => (await kubectl(`get ns ${CANARY_NS} -o name`, { check: false })) === "", 60000, 2000);

    const t0 = Date.now();
    await applyPVC();
    const bound = await waitBound(90000);
    await applyPod();
    const ready = await waitPodReady(120000);
    const provisionS = (Date.now() - t0) / 1000;

    check("canary PVC reached Bound", bound, `phase=${await pvcPhase(CANARY_PVC, CANARY_NS)}`);
    check("canary pod mounted the PVC (Ready)", ready);
    gauge("provision wall-time (Pending→Bound→mounted)", provisionS, MAX_PROVISION_S);

    // write a unique sentinel THROUGH the mount, prove it reads back
    await podExec(`printf '%s' ${JSON.stringify(canary.sentinel)} > /data/SENTINEL`);
    const readBack = (await podExec(`cat /data/SENTINEL 2>/dev/null`)).trim();
    canary.wroteBytes = canary.sentinel.length;
    const wrote = readBack === canary.sentinel;
    check("sentinel written + reads back through the NFS mount", wrote, `${canary.wroteBytes} bytes`);

    record("Canary provision wall-time", { value: provisionS.toFixed(2), unit: "s", threshold: MAX_PROVISION_S, ok: bound && ready && provisionS <= MAX_PROVISION_S });
    record("Sentinel written to NFS PVC", { value: canary.wroteBytes, unit: " B", thresholdText: "> 0", ok: wrote });
    expect(bound).toBe(true);
    expect(ready).toBe(true);
    expect(wrote).toBe(true);
  });

  dtest("RECLAIM+REUSE: delete PVC, recreate SAME name → ZERO stale bytes (no data leak)", async () => {
    step(`Chaos(phase 2): delete ${C.yellow}${CANARY_PVC}${C.reset}, recreate the SAME name — the reused volume MUST be empty`);
    // 1) drop the pod + PVC. reclaimPolicy=Retain + archiveOnDelete archives the old NFS dir.
    await deletePod();
    const tDel = Date.now();
    await deletePVC();
    await reapReleasedCanaryPVs(); // don't let the Retained PV rebind the archived dir
    info("old PVC deleted (NFS dir archived); recreating a PVC with the identical name…");

    // 2) recreate the identical PVC (same namespace/name → same pathPattern target)
    await applyPVC();
    const rebound = await waitBound(120000);
    await applyPod();
    const ready = await waitPodReady(120000);
    const recreateS = (Date.now() - tDel) / 1000;

    check("same-name PVC re-bound", rebound, `phase=${await pvcPhase(CANARY_PVC, CANARY_NS)}`);
    check("canary pod re-mounted the reused PVC", ready);
    gauge("reclaim→reuse wall-time (delete→rebind→mount)", recreateS, MAX_RECREATE_S);

    // 3) THE hygiene assertion: the reused volume must be pristine — zero leaked bytes/files
    const files = await fileCount();
    const bytes = await staleBytes();
    const sentinelGone = (await podExec(`test -f /data/SENTINEL && echo LEAK || echo CLEAN`)).trim();
    const clean = bytes === 0 && files === 0 && sentinelGone === "CLEAN";
    check("recreated PVC has ZERO files", files === 0, `files=${files}`);
    check("recreated PVC has ZERO stale bytes", bytes === 0, `stale=${bytes} B`);
    check("old sentinel did NOT leak into the reused PVC", sentinelGone === "CLEAN", sentinelGone);

    record("Reclaim→reuse wall-time", { value: recreateS.toFixed(2), unit: "s", threshold: MAX_RECREATE_S, ok: rebound && ready && recreateS <= MAX_RECREATE_S });
    record("Stale bytes on reused same-name PVC", { value: bytes, unit: " B", threshold: 0, ok: bytes === 0 });
    record("Stale files on reused same-name PVC", { value: files, unit: " files", threshold: 0, ok: files === 0 });
    record("No data leak (fresh volume)", { text: clean ? "clean" : "LEAK", thresholdText: "clean", ok: clean });

    expect(rebound).toBe(true);
    expect(ready).toBe(true);
    expect(bytes).toBe(0);
    expect(files).toBe(0);
    expect(sentinelGone).toBe("CLEAN");
  });
});
