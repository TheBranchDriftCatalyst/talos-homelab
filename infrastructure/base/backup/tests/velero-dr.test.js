/**
 * Velero backup / disaster-recovery chaos test  (TALOS-23l.1)
 * ------------------------------------------------------------
 * Validates the Velero DR machinery (MinIO S3 backend, BackupStorageLocation, node-agent Kopia
 * fs-backup, automated Schedules) and PROVES a real backup→restore round-trip recovers data with
 * zero loss — by writing a file with a known sha256, backing it up, DELETING the whole namespace,
 * restoring, and asserting the restored sha256 matches. Restore wall-time is measured.
 *
 * Read-only checks ALWAYS run (they only assert the DR machinery EXISTS + is healthy — never
 * mutate a thing). The DESTRUCTIVE round-trip runs ONLY when
 *     VELERO_DR_DESTRUCTIVE=1
 * and it operates exclusively on a throwaway CANARY namespace (velero-dr-canary), so it can never
 * touch real backups or app data.
 *
 *   (from repo root)  npm test                                    # this + other suites, read-only
 *                     npm test -- --selectProjects velero-dr      # this suite only, read-only
 *   (this dir)        npm install && npm test                     # safe, read-only
 *                     VELERO_DR_DESTRUCTIVE=1 npm run test:dr      # full backup/restore round-trip
 *
 * Needs `kubectl` (context = the cluster where Velero runs) on PATH. Everything is driven through
 * kubectl + Velero CRs (Backup/Restore/BackupStorageLocation) — no `velero` CLI dependency.
 *
 * Velero lives in the `backup` namespace (infrastructure/base/backup/velero.yaml), NOT a
 * `velero/` dir — the manifest names are the source of truth for the read-only assertions:
 *   deploy=velero  BSL=default (MinIO)  schedules=daily-all,weekly-full,critical-data-daily
 */
const { exec } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

// ---- config ---------------------------------------------------------------
const NS = process.env.VELERO_NS || "backup"; // Velero's own namespace
const BSL = process.env.VELERO_BSL || "default"; // BackupStorageLocation (MinIO backend)
const CANARY_NS = process.env.VELERO_CANARY_NS || "velero-dr-canary";
const CANARY_FILE = "/data/canary.bin";
const DESTRUCTIVE = process.env.VELERO_DR_DESTRUCTIVE === "1";
const BACKUP_RECENCY_H = parseFloat(process.env.VELERO_BACKUP_RECENCY_H || "24"); // "recent" = < 24h
const MAX_BACKUP_S = parseFloat(process.env.VELERO_MAX_BACKUP_S || "300");
const MAX_RESTORE_S = parseFloat(process.env.VELERO_MAX_RESTORE_S || "300");
const CANARY_YAML = path.join(__dirname, "canary.yaml");

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

// ---- measurements collector (printed as a summary table at the end) --------
const METRICS = [];
const record = (name, m) => METRICS.push({ name, ...m });
function printSummary() {
  if (!METRICS.length) return;
  const pad = (s, n) => String(s).padEnd(n);
  out(`\n${C.bold}${C.cyan}════════════════ VELERO DR TEST — MEASUREMENTS ═════════════${C.reset}`);
  out(`   ${C.dim}${pad("Metric", 42)}${pad("Measured", 10)}${pad("Threshold", 10)}Result${C.reset}`);
  out(`   ${C.dim}${"─".repeat(70)}${C.reset}`);
  for (const m of METRICS) {
    const meas = m.value !== undefined ? `${m.value}${m.unit || ""}` : m.text || "—";
    const thr = m.threshold !== undefined ? `≤ ${m.threshold}${m.unit || ""}` : m.thresholdText || "—";
    const mark = m.ok ? `${C.green}✓ PASS${C.reset}` : `${C.red}✗ FAIL${C.reset}`;
    const mc = m.ok ? C.green : C.red;
    out(`   ${pad(m.name, 42)}${mc}${pad(meas, 10)}${C.reset}${C.dim}${pad(thr, 10)}${C.reset}${mark}`);
  }
  const passed = METRICS.filter((m) => m.ok).length;
  out(`   ${C.dim}${"─".repeat(70)}${C.reset}`);
  out(`   ${C.bold}${passed}/${METRICS.length} metrics within threshold${C.reset}`);
  out(`${C.bold}${C.cyan}═══════════════════════════════════════════════════════════${C.reset}\n`);
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
const jstr = (s) => JSON.stringify(s || "{}");

async function waitUntil(fn, timeoutMs = 300000, intervalMs = 3000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    try { if (await fn()) return true; } catch (_) {}
    await sleep(intervalMs);
  }
  return false;
}

// apply an in-memory manifest via a temp file (kubectl apply -f -)
async function applyManifest(name, yaml) {
  const f = path.join(os.tmpdir(), `velero-dr-${name}-${Date.now()}.yaml`);
  fs.writeFileSync(f, yaml);
  try { await kubectl(`apply -f ${f}`); } finally { fs.unlinkSync(f); }
}

// Velero CR phase readers (return "" when the CRD/resource is absent so callers can decide)
const bslPhase = () =>
  kubectl(`get backupstoragelocation ${BSL} -n ${NS} -o jsonpath={.status.phase}`, { check: false });
const backupPhase = (n) =>
  kubectl(`get backup.velero.io ${n} -n ${NS} -o jsonpath={.status.phase}`, { check: false });
const restorePhase = (n) =>
  kubectl(`get restore.velero.io ${n} -n ${NS} -o jsonpath={.status.phase}`, { check: false });

// most recent SUCCESSFUL backup age in hours (null = none / CRD absent)
async function recentSuccessfulBackupAgeH() {
  const raw = await kubectl(`get backups.velero.io -n ${NS} -o json`, { check: false });
  let doc; try { doc = JSON.parse(raw || "{}"); } catch { return null; }
  const items = doc.items || [];
  let newest = null; // { name, ageH }
  for (const b of items) {
    if ((b.status || {}).phase !== "Completed") continue;
    const ts = (b.status || {}).completionTimestamp || (b.status || {}).startTimestamp;
    if (!ts) continue;
    const ageH = (Date.now() - new Date(ts).getTime()) / 3600000;
    if (!newest || ageH < newest.ageH) newest = { name: b.metadata.name, ageH };
  }
  return newest;
}

// ---- canary write/read (busybox sha256sum in the pod that mounts the PVC) ---
async function canaryPod() {
  return kubectl(`get pods -n ${CANARY_NS} -l app=velero-canary -o jsonpath={.items[0].metadata.name}`,
    { check: false });
}
async function writeCanaryData() {
  const pod = await canaryPod();
  // 4 MiB of random data → a stable known sha256 we can compare after the round-trip
  await kubectl(`exec ${pod} -n ${CANARY_NS} -- sh -c "dd if=/dev/urandom of=${CANARY_FILE} bs=1024 count=4096 2>/dev/null; sync"`);
  return readCanarySha();
}
async function readCanarySha() {
  const pod = await canaryPod();
  if (!pod) return "";
  const o = await kubectl(`exec ${pod} -n ${CANARY_NS} -- sh -c "sha256sum ${CANARY_FILE} 2>/dev/null || true"`,
    { check: false });
  const m = o.match(/([0-9a-f]{64})/);
  return m ? m[1] : "";
}

async function createCanary() {
  await applyManifest("canary", fs.readFileSync(CANARY_YAML, "utf8"));
  await kubectl(`rollout status deploy/velero-canary -n ${CANARY_NS} --timeout=120s`, { check: false });
  await waitUntil(async () => !!(await canaryPod()) &&
    (await kubectl(`get deploy velero-canary -n ${CANARY_NS} -o jsonpath={.status.availableReplicas}`, { check: false })) === "1",
    120000, 3000);
}
const deleteCanary = () =>
  kubectl(`delete ns ${CANARY_NS} --ignore-not-found --wait=false`, { check: false });

// create a Velero Backup CR scoped to the canary namespace (Kopia fs-backup, MinIO BSL)
async function createBackup(name) {
  const yaml = `apiVersion: velero.io/v1
kind: Backup
metadata:
  name: ${name}
  namespace: ${NS}
  labels:
    velero-dr.talos00/throwaway: "true"
spec:
  includedNamespaces: ["${CANARY_NS}"]
  storageLocation: ${BSL}
  defaultVolumesToFsBackup: true
  snapshotVolumes: false
  ttl: 1h0m0s`;
  await applyManifest("backup", yaml);
}
// create a Velero Restore CR from a completed backup
async function createRestore(name, backupName) {
  const yaml = `apiVersion: velero.io/v1
kind: Restore
metadata:
  name: ${name}
  namespace: ${NS}
  labels:
    velero-dr.talos00/throwaway: "true"
spec:
  backupName: ${backupName}
  includedNamespaces: ["${CANARY_NS}"]
  existingResourcePolicy: update`;
  await applyManifest("restore", yaml);
}

const dtest = DESTRUCTIVE ? test : test.skip;

// ============================================================================
describe("Velero — disaster recovery", () => {
  jest.setTimeout(600000);

  afterAll(async () => {
    if (DESTRUCTIVE) {
      // best-effort teardown of every throwaway artifact this suite created
      await deleteCanary();
      await kubectl(`delete backup.velero.io,restore.velero.io -n ${NS} -l velero-dr.talos00/throwaway=true --ignore-not-found`, { check: false });
    }
    printSummary();
  });

  // ---------------- READ-ONLY tier (always runs; never mutates) -------------
  test("velero deployment is healthy (>=1 available replica)", async () => {
    step("Read-only: DR machinery must EXIST and be healthy");
    const avail = await kubectl(`get deploy velero -n ${NS} -o jsonpath={.status.availableReplicas}`, { check: false });
    const ok = parseInt(avail || "0", 10) >= 1;
    check("deploy/velero available", ok, `availableReplicas=${avail || "0"}`);
    record("Velero deployment healthy", { text: ok ? "yes" : "no", thresholdText: "yes", ok });
    if (!DESTRUCTIVE) info("read-only mode — set VELERO_DR_DESTRUCTIVE=1 for the backup/restore round-trip");
    expect(ok).toBe(true);
  });

  test("node-agent DaemonSet is fully rolled out (Kopia fs-backup path)", async () => {
    // fs-backup of local-path PVCs runs through the node-agent DaemonSet; if it's not ready,
    // PVC backups silently no-op. Assert desired == ready.
    const raw = await kubectl(`get daemonset node-agent -n ${NS} -o json`, { check: false });
    let ds; try { ds = JSON.parse(raw || "{}"); } catch { ds = {}; }
    const desired = (ds.status || {}).desiredNumberScheduled;
    const ready = (ds.status || {}).numberReady;
    const ok = desired !== undefined && desired > 0 && ready === desired;
    check("node-agent desired == ready", ok, `ready=${ready}/${desired}`);
    record("node-agent DaemonSet ready", { text: ok ? `${ready}/${desired}` : `${ready}/${desired}`, thresholdText: "all", ok });
    expect(ok).toBe(true);
  });

  test(`BackupStorageLocation '${BSL}' is Available (MinIO backend)`, async () => {
    const phase = await bslPhase();
    const ok = phase === "Available";
    check(`BSL ${BSL} phase = Available`, ok, `phase=${phase || "(none)"}`);
    // surface the backend so a failure is diagnosable at a glance
    const bucket = await kubectl(`get backupstoragelocation ${BSL} -n ${NS} -o jsonpath={.spec.objectStorage.bucket}`, { check: false });
    const provider = await kubectl(`get backupstoragelocation ${BSL} -n ${NS} -o jsonpath={.spec.provider}`, { check: false });
    info(`backend: provider=${provider || "?"} bucket=${bucket || "?"}`);
    record("BackupStorageLocation Available", { text: phase || "none", thresholdText: "Available", ok });
    expect(phase).toBe("Available");
  });

  test("at least one backup Schedule exists", async () => {
    const raw = await kubectl(`get schedules.velero.io -n ${NS} -o json`, { check: false });
    let doc; try { doc = JSON.parse(raw || "{}"); } catch { doc = {}; }
    const names = (doc.items || []).map((s) => s.metadata.name);
    const ok = names.length >= 1;
    check("Schedule count >= 1", ok, names.length ? names.join(", ") : "(none)");
    record("Backup Schedule(s) present", { value: names.length, thresholdText: ">= 1", ok });
    expect(names.length).toBeGreaterThanOrEqual(1);
  });

  test(`a recent successful Backup exists (< ${BACKUP_RECENCY_H}h)`, async () => {
    const newest = await recentSuccessfulBackupAgeH();
    const ok = !!newest && newest.ageH <= BACKUP_RECENCY_H;
    check(
      `most recent Completed backup < ${BACKUP_RECENCY_H}h`,
      ok,
      newest ? `${newest.name} — ${newest.ageH.toFixed(1)}h ago` : "no Completed backups found",
    );
    record("Recent successful backup", {
      value: newest ? newest.ageH.toFixed(1) : "none",
      unit: newest ? "h" : "",
      threshold: BACKUP_RECENCY_H,
      ok,
    });
    expect(ok).toBe(true);
  });

  // ---------------- DESTRUCTIVE tier (VELERO_DR_DESTRUCTIVE=1 only) ----------
  // Full backup→delete→restore round-trip against a THROWAWAY canary namespace. Never touches
  // real backups (own label/name) or real app data (own namespace).
  dtest("ROUND-TRIP: backup → delete namespace → restore → sha256 matches (no data loss)", async () => {
    step(`Chaos: real DR round-trip on throwaway namespace ${C.yellow}${CANARY_NS}${C.reset}`);

    info("1/6 provisioning the canary (namespace + local-path PVC + pod)…");
    await createCanary();

    info("2/6 writing 4 MiB of random data + recording its sha256…");
    const shaBefore = await writeCanaryData();
    check("canary data written with a known sha256", /^[0-9a-f]{64}$/.test(shaBefore), shaBefore || "(no sha)");
    expect(shaBefore).toMatch(/^[0-9a-f]{64}$/);

    // --- BACKUP -------------------------------------------------------------
    const backupName = `velero-dr-canary-${Date.now()}`;
    info(`3/6 velero Backup ${backupName} (Kopia fs-backup → MinIO)…`);
    const tB = Date.now();
    await createBackup(backupName);
    const backedUp = await waitUntil(async () => {
      const p = await backupPhase(backupName);
      if (p === "Completed") return true;
      if (p && p !== "InProgress" && p !== "New") throw new Error(`backup phase=${p}`);
      return false;
    }, MAX_BACKUP_S * 1000 + 60000, 4000);
    const backupS = (Date.now() - tB) / 1000;
    const bPhase = await backupPhase(backupName);
    check("backup reached Completed", backedUp && bPhase === "Completed", `phase=${bPhase} in ${backupS.toFixed(1)}s`);
    gauge("backup wall-time", backupS, MAX_BACKUP_S);
    record("Backup wall-time", { value: backupS.toFixed(1), unit: "s", threshold: MAX_BACKUP_S, ok: backedUp });
    expect(bPhase).toBe("Completed");

    // --- DISASTER: nuke the whole namespace (PVC data is gone with it) -------
    info(`4/6 DISASTER — deleting namespace ${CANARY_NS} (local-path data destroyed)…`);
    await kubectl(`delete ns ${CANARY_NS} --wait=true --timeout=120s`, { check: false });
    const gone = await waitUntil(async () =>
      (await kubectl(`get ns ${CANARY_NS} --ignore-not-found -o name`, { check: false })) === "", 150000, 3000);
    check("canary namespace fully deleted", gone);
    expect(gone).toBe(true);

    // --- RESTORE ------------------------------------------------------------
    const restoreName = `velero-dr-restore-${Date.now()}`;
    info(`5/6 velero Restore ${restoreName} from ${backupName} — measuring wall-time…`);
    const tR = Date.now();
    await createRestore(restoreName, backupName);
    const restored = await waitUntil(async () => {
      const p = await restorePhase(restoreName);
      if (p === "Completed") return true;
      if (p && p !== "InProgress" && p !== "New") throw new Error(`restore phase=${p}`);
      return false;
    }, MAX_RESTORE_S * 1000 + 60000, 4000);
    const restoreS = (Date.now() - tR) / 1000;
    const rPhase = await restorePhase(restoreName);
    check("restore reached Completed", restored && rPhase === "Completed", `phase=${rPhase} in ${restoreS.toFixed(1)}s`);
    gauge("restore wall-time (downtime → data back)", restoreS, MAX_RESTORE_S);

    // --- VERIFY: restored pod's file sha256 must equal the pre-disaster sha --
    info("6/6 verifying restored data integrity (sha256)…");
    await waitUntil(async () => !!(await canaryPod()) &&
      (await kubectl(`get deploy velero-canary -n ${CANARY_NS} -o jsonpath={.status.availableReplicas}`, { check: false })) === "1",
      180000, 4000);
    let shaAfter = "";
    await waitUntil(async () => { shaAfter = await readCanarySha(); return /^[0-9a-f]{64}$/.test(shaAfter); }, 60000, 4000);
    const noLoss = !!shaBefore && shaAfter === shaBefore;
    check("restored sha256 == original (ZERO data loss)", noLoss, `${(shaBefore || "").slice(0, 12)}… → ${(shaAfter || "none").slice(0, 12)}…`);

    record("Restore wall-time", { value: restoreS.toFixed(1), unit: "s", threshold: MAX_RESTORE_S, ok: restored });
    record("Data integrity after restore (sha256)", { text: noLoss ? "match" : "MISMATCH", thresholdText: "match", ok: noLoss });

    expect(rPhase).toBe("Completed");
    expect(shaAfter).toBe(shaBefore);
  });
});
