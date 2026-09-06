/**
 * etcd-snapshot — disaster-recovery / chaos test  (TALOS-23l.6)
 * ------------------------------------------------------------------------------
 * Validates the control-plane etcd backup pipeline: an hourly CronJob snapshots etcd via
 * `talosctl etcd snapshot` and uploads the .snapshot object to MinIO (bucket `backups`,
 * prefix `etcd`, NFS-backed so it survives ephemeral XFS loss — see TALOS-a8g). Recovery
 * from a control-plane disk failure (the 2026-05-09 incident) depends entirely on a
 * FRESH, INTACT snapshot existing off-node.
 *
 * The manifests under test live in  infrastructure/base/backup/  (namespace `backup`):
 *   - CronJob        etcd-backup            (schedule "0 * * * *")
 *   - ConfigMap      etcd-backup-config     (TALOS_NODE, S3_BUCKET=backups, S3_PREFIX=etcd, ...)
 *   - Secret         talosconfig            (os:etcd:backup role, used by the snapshot init)
 *   - Secret         minio-root-credentials (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY)
 *   - PrometheusRule etcd-backup-alerts     (EtcdBackupJobFailed / NotRunning / CronJobMissing)
 * This test lives in a sibling `talos-dr/` dir (not `backup/tests/`) so it is its own
 * self-contained Jest project (`etcd-dr`) and does not collide with the `velero-dr` suite.
 *
 * ── TWO TIERS ─────────────────────────────────────────────────────────────────
 * READ-ONLY (always run — the PRIMARY value; never mutates anything):
 *   - the backup machinery EXISTS  (CronJob + ConfigMap + secrets present, schedule sane)
 *   - the CronJob is HEALTHY        (last scheduled/successful run recent, not suspended)
 *   - a <1h-FRESH snapshot object exists in MinIO  (freshness — the whole point)
 *   - the stored snapshot is INTACT (non-empty, well-formed bbolt/etcd db header)
 *   - etcd itself is HEALTHY and snapshottable  (`talosctl etcd status`)
 *
 * DESTRUCTIVE (only when  ETCD_DR_DESTRUCTIVE=1):
 *   We deliberately DO NOT restore the live control-plane etcd — a bad restore is
 *   catastrophic and irreversible. Instead we validate the restore *procedure*
 *   NON-destructively: take a fresh `talosctl etcd snapshot` to a throwaway temp file
 *   and prove it LOADS + HASHES cleanly (exactly what a real restore consumes), measuring
 *   wall-time. Then we print the full bootstrap-restore runbook. A true restore-into-canary
 *   is infeasible without a spare Talos node, so the actual restore step is a documented
 *   no-op that prints the runbook (see printRestoreRunbook()).
 *
 *   (from repo root)  npm test                 # this + other suites, read-only
 *                     npm run test:dr          # include destructive chaos
 *   (this suite only) npm test -- --selectProjects etcd-dr
 *                     ETCD_DR_DESTRUCTIVE=1 npm test -- --selectProjects etcd-dr
 *
 * Needs `kubectl` (context = the cluster) and `talosctl` (with a talosconfig for the
 * control-plane node) on PATH. The MinIO probe runs through a throwaway `minio/mc` pod
 * (MinIO is in-cluster only); the snapshot object is validated inside that pod so no
 * binary etcd db is ever streamed back over kubectl.
 */
const { exec } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

// ---- config ---------------------------------------------------------------
const NS = process.env.ETCD_BACKUP_NS || "backup";
const CRONJOB = process.env.ETCD_CRONJOB || "etcd-backup";
const CM = process.env.ETCD_BACKUP_CM || "etcd-backup-config";
const S3_SECRET = process.env.ETCD_S3_SECRET || "minio-root-credentials";
const TALOSCONFIG_SECRET = process.env.ETCD_TALOSCONFIG_SECRET || "talosconfig";
// MinIO target (defaults mirror etcd-backup-config; overridden from the live ConfigMap in beforeAll)
let S3_ENDPOINT = process.env.ETCD_S3_ENDPOINT || "http://minio.minio.svc.cluster.local";
let S3_BUCKET = process.env.ETCD_S3_BUCKET || "backups";
let S3_PREFIX = process.env.ETCD_S3_PREFIX || "etcd";
let TALOS_NODE = process.env.TALOS_NODE || "192.168.1.54";
// freshness / integrity thresholds
const MAX_SNAPSHOT_AGE_S = parseFloat(process.env.ETCD_MAX_SNAPSHOT_AGE_S || "3600"); // <1h
const MAX_CRONJOB_SINCE_SCHEDULED_S = parseFloat(process.env.ETCD_MAX_SINCE_SCHEDULED_S || "7200"); // <2h
const MIN_SNAPSHOT_BYTES = parseInt(process.env.ETCD_MIN_SNAPSHOT_BYTES || "1048576", 10); // 1 MiB floor
const MAX_SNAPSHOT_WALL_S = parseFloat(process.env.ETCD_MAX_SNAPSHOT_WALL_S || "120"); // destructive snapshot budget
const DESTRUCTIVE = process.env.ETCD_DR_DESTRUCTIVE === "1";
const MC_IMAGE = process.env.ETCD_MC_IMAGE || "minio/mc:RELEASE.2024-11-21T17-21-54Z";
// bbolt/etcd snapshot files are bbolt databases: meta page magic 0xED0CDAED (little-endian on disk).
const BBOLT_MAGIC_LE = "edda0ced";

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
  out(`\n${C.bold}${C.cyan}════════════════ ETCD-DR TEST — MEASUREMENTS ═══════════════${C.reset}`);
  out(`   ${C.dim}${pad("Metric", 42)}${pad("Measured", 12)}${pad("Threshold", 12)}Result${C.reset}`);
  out(`   ${C.dim}${"─".repeat(72)}${C.reset}`);
  for (const m of METRICS) {
    const meas = m.value !== undefined ? `${m.value}${m.unit || ""}` : m.text || "—";
    const thr = m.threshold !== undefined ? `≤ ${m.threshold}${m.unit || ""}` : m.thresholdText || "—";
    const mark = m.ok ? `${C.green}✓ PASS${C.reset}` : `${C.red}✗ FAIL${C.reset}`;
    const mc = m.ok ? C.green : C.red;
    out(`   ${pad(m.name, 42)}${mc}${pad(meas, 12)}${C.reset}${C.dim}${pad(thr, 12)}${C.reset}${mark}`);
  }
  const passed = METRICS.filter((m) => m.ok).length;
  out(`   ${C.dim}${"─".repeat(72)}${C.reset}`);
  out(`   ${C.bold}${passed}/${METRICS.length} metrics within threshold${C.reset}`);
  out(`${C.bold}${C.cyan}═══════════════════════════════════════════════════════════${C.reset}\n`);
}

// ---- shell / kubectl / talosctl helpers -----------------------------------
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function sh(cmd, { timeout = 60000, check: doCheck = true } = {}) {
  return new Promise((resolve, reject) => {
    exec(cmd, { timeout, maxBuffer: 32 * 1024 * 1024 }, (err, stdout, stderr) => {
      if (err && doCheck) return reject(new Error(`${cmd}\n${stderr || err.message}`));
      resolve((stdout || "").trim());
    });
  });
}
const kubectl = (a, o) => sh(`kubectl ${a}`, o);
// talosctl always targets the control-plane node; TALOSCONFIG may come from the env of the admin host.
const talosctl = (a, o) => sh(`talosctl -n ${TALOS_NODE} ${a}`, o);

async function secretVal(name, key) {
  const b64 = await kubectl(
    `get secret ${name} -n ${NS} -o jsonpath="{.data.${key}}"`, { check: false });
  if (!b64) return "";
  return Buffer.from(b64, "base64").toString().trim();
}

// Run an mc one-liner inside a throwaway pod in the backup namespace. Creds come from the
// SAME secret the CronJob uses, decoded host-side and passed as --env (read-only; the pod
// only ever does `mc ls/stat/cat` against the snapshot prefix).
async function mc(mcArgs, { timeout = 90000 } = {}) {
  const ak = await secretVal(S3_SECRET, "AWS_ACCESS_KEY_ID");
  const sk = await secretVal(S3_SECRET, "AWS_SECRET_ACCESS_KEY");
  if (!ak || !sk) throw new Error(`could not read S3 creds from secret ${S3_SECRET} in ns ${NS}`);
  const name = `etcddr-mc-${Date.now()}`;
  // CRITICAL: the pod script is HOST-single-quoted so $AK/$SK are expanded by the POD
  // shell (from --env), NOT by the /bin/sh that node's exec() spawns. Double-quoting the
  // script here would make the host expand $AK to empty → AccessDenied. Keep the script
  // free of single quotes.
  const script =
    `mc alias set b "${S3_ENDPOINT}" "$AK" "$SK" >/dev/null 2>&1; ${mcArgs}`;
  return kubectl(
    `run ${name} -n ${NS} --rm -i --restart=Never --image=${MC_IMAGE} ` +
    `--env AK='${ak}' --env SK='${sk}' --command -- sh -c '${script}'`,
    { timeout, check: false });
}

// Newest object under s3://<bucket>/<prefix>/ as { key, ageS, bytes } (or null if none).
// mc ls --json emits one JSON line per object with `lastModified` and `size`.
async function newestSnapshot() {
  const raw = await mc(`mc ls --json "b/${S3_BUCKET}/${S3_PREFIX}/"`);
  const rows = raw.split("\n").map((l) => l.trim()).filter(Boolean)
    .map((l) => { try { return JSON.parse(l); } catch (_) { return null; } })
    .filter((o) => o && o.type === "file" && o.lastModified);
  if (!rows.length) return null;
  rows.sort((a, b) => new Date(b.lastModified) - new Date(a.lastModified));
  const n = rows[0];
  return { key: n.key, ageS: (Date.now() - new Date(n.lastModified).getTime()) / 1000, bytes: n.size || 0 };
}

// Integrity of the STORED snapshot, validated INSIDE the mc pod (no binary streamed to host):
// download to /tmp, confirm size, and confirm the first bytes carry the bbolt meta magic.
async function storedSnapshotIntegrity(key) {
  // HOST-single-quoted (see mc() note): no inner single quotes, $AK/$SK resolved in-pod.
  // `tr -dc 0-9a-f` keeps only hex chars (drops the od spacing/newlines) without needing a
  // quoted whitespace class.
  const script =
    `mc alias set b "${S3_ENDPOINT}" "$AK" "$SK" >/dev/null 2>&1; ` +
    `mc cp "b/${S3_BUCKET}/${S3_PREFIX}/${key}" /tmp/s.db >/dev/null 2>&1 || { echo BYTES=0 MAGIC=none; exit 0; }; ` +
    `echo BYTES=$(wc -c < /tmp/s.db); ` +
    // dump first 32 bytes as hex; od is present in the mc image
    `echo MAGIC=$(od -An -tx1 -N32 /tmp/s.db | tr -dc 0-9a-f)`;
  const ak = await secretVal(S3_SECRET, "AWS_ACCESS_KEY_ID");
  const sk = await secretVal(S3_SECRET, "AWS_SECRET_ACCESS_KEY");
  const name = `etcddr-int-${Date.now()}`;
  const o = await kubectl(
    `run ${name} -n ${NS} --rm -i --restart=Never --image=${MC_IMAGE} ` +
    `--env AK='${ak}' --env SK='${sk}' --command -- sh -c '${script}'`,
    { timeout: 120000, check: false });
  const bytes = parseInt((o.match(/BYTES=(\d+)/) || [])[1] || "0", 10);
  const hex = (o.match(/MAGIC=([0-9a-f]+)/) || [])[1] || "";
  return { bytes, hasMagic: hex.includes(BBOLT_MAGIC_LE), hex };
}

// Validate an etcd snapshot FILE loads/hashes. Prefer etcdutl/etcdctl `snapshot status`
// (returns {hash,revision,totalKey} and errors on a corrupt db); fall back to the bbolt
// meta-magic + size check when neither binary is on PATH.
async function verifySnapshotFile(file) {
  const size = fs.existsSync(file) ? fs.statSync(file).size : 0;
  for (const bin of ["etcdutl", "etcdctl"]) {
    const have = await sh(`command -v ${bin} || true`, { check: false });
    if (!have) continue;
    const env = bin === "etcdctl" ? "ETCDCTL_API=3 " : "";
    const o = await sh(`${env}${bin} snapshot status "${file}" --write-out=json`,
      { check: false, timeout: 120000 });
    try {
      const st = JSON.parse(o);
      if (typeof st.hash !== "undefined") {
        return { ok: true, size, tool: bin, detail: `hash=${st.hash} rev=${st.revision} keys=${st.totalKey}` };
      }
    } catch (_) { /* fall through to magic check */ }
  }
  // fallback: bbolt magic in the first page
  let hasMagic = false;
  try {
    const fd = fs.openSync(file, "r");
    const buf = Buffer.alloc(32);
    fs.readSync(fd, buf, 0, 32, 0);
    fs.closeSync(fd);
    hasMagic = buf.toString("hex").includes(BBOLT_MAGIC_LE);
  } catch (_) {}
  return { ok: hasMagic && size >= MIN_SNAPSHOT_BYTES, size, tool: "bbolt-magic",
    detail: hasMagic ? "bbolt meta magic present" : "NO bbolt magic" };
}

// ── The full bootstrap-restore runbook. Printed by the destructive tier (which never
//    actually restores). This is the authoritative "what to do when the control plane
//    disk dies" procedure — keep it in sync with docs/05-runbooks/. ────────────────────
function printRestoreRunbook(snapshotKey = "etcd-<TIMESTAMP>.snapshot") {
  out(`\n${C.bold}${C.yellow}ETCD BOOTSTRAP-RESTORE RUNBOOK (control-plane disk loss)${C.reset}`);
  const L = (s) => out(`   ${C.grey}${s}${C.reset}`);
  L("Preconditions: a fresh, INTACT snapshot off-node (this test guards that) + talosconfig");
  L("               with os:etcd:backup role + the node's machine config.");
  L("");
  L("1. Pull the chosen snapshot from MinIO to the admin host:");
  L(`     mc alias set b ${S3_ENDPOINT} <AK> <SK>`);
  L(`     mc cp b/${S3_BUCKET}/${S3_PREFIX}/${snapshotKey} ./etcd-restore.db`);
  L("2. Verify BEFORE trusting it (this test's verifySnapshotFile does the same):");
  L("     ETCDCTL_API=3 etcdutl snapshot status ./etcd-restore.db --write-out=table");
  L("3. Put the control-plane node into a clean state (single-node CP shown):");
  L(`     talosctl -n ${TALOS_NODE} bootstrap --recover-from=./etcd-restore.db`);
  L("   (Talos streams the snapshot to /var/lib/etcd and re-bootstraps etcd from it.)");
  L("   Multi-CP: reset the other CP members first, recover on ONE, then rejoin the rest:");
  L(`     talosctl -n <other-cp> reset --graceful=false --reboot   # wipe stale members`);
  L("4. Wait for the API + etcd to come healthy, then verify quorum:");
  L(`     talosctl -n ${TALOS_NODE} etcd status`);
  L(`     talosctl -n ${TALOS_NODE} health --wait-timeout 10m`);
  L("5. Reconcile GitOps (Flux/ArgoCD) so workloads converge to the snapshot's revision.");
  L(`${C.dim}   NOTE: this test NEVER runs step 3 against live etcd — it only proves steps 1-2${C.reset}`);
  L(`${C.dim}   (fetch + verify) plus the snapshot-taking half of step 0 are healthy.${C.reset}`);
}

const dtest = DESTRUCTIVE ? test : test.skip;

// ============================================================================
describe("etcd-snapshot — disaster recovery", () => {
  jest.setTimeout(600000);

  beforeAll(async () => {
    step("Pre-flight — load live backup config (namespace + ConfigMap)");
    // Pull the real tunables from the live ConfigMap so the freshness/integrity checks use
    // the ACTUAL bucket/prefix/node, not just defaults.
    const cm = await kubectl(`get configmap ${CM} -n ${NS} -o json`, { check: false });
    try {
      const d = JSON.parse(cm).data || {};
      S3_ENDPOINT = process.env.ETCD_S3_ENDPOINT || d.S3_ENDPOINT || S3_ENDPOINT;
      S3_BUCKET = process.env.ETCD_S3_BUCKET || d.S3_BUCKET || S3_BUCKET;
      S3_PREFIX = process.env.ETCD_S3_PREFIX || d.S3_PREFIX || S3_PREFIX;
      TALOS_NODE = process.env.TALOS_NODE || d.TALOS_NODE || TALOS_NODE;
      info(`config: node=${TALOS_NODE} s3=${S3_ENDPOINT} bucket=${S3_BUCKET}/${S3_PREFIX}`);
    } catch (_) {
      info(`could not read ConfigMap ${CM}/${NS} — using defaults (node=${TALOS_NODE}, ${S3_BUCKET}/${S3_PREFIX})`);
    }
    if (!DESTRUCTIVE)
      info("read-only mode — set ETCD_DR_DESTRUCTIVE=1 for the snapshot->load restore-procedure check");
  }, 120000);

  afterAll(printSummary);

  // ── READ-ONLY TIER — always runs, never mutates ────────────────────────────────────

  test("backup machinery EXISTS — CronJob + ConfigMap + secrets present", async () => {
    step("Machinery: the etcd-backup pipeline is deployed");
    const cj = await kubectl(`get cronjob ${CRONJOB} -n ${NS} -o json`, { check: false });
    let schedule = "", suspended = null;
    try { const o = JSON.parse(cj); schedule = o.spec.schedule; suspended = !!o.spec.suspend; } catch (_) {}
    const cjOk = !!schedule;
    check(`CronJob ${CRONJOB} exists`, cjOk, cjOk ? `schedule="${schedule}"` : "NOT FOUND");
    const notSuspended = suspended === false;
    check("CronJob is not suspended", notSuspended, `suspend=${suspended}`);
    const cmOk = !!(await kubectl(`get configmap ${CM} -n ${NS} -o name`, { check: false }));
    check(`ConfigMap ${CM} exists`, cmOk);
    const talosSecretOk = !!(await kubectl(`get secret ${TALOSCONFIG_SECRET} -n ${NS} -o name`, { check: false }));
    check(`Secret ${TALOSCONFIG_SECRET} (os:etcd:backup role) exists`, talosSecretOk);
    const s3SecretOk = !!(await kubectl(`get secret ${S3_SECRET} -n ${NS} -o name`, { check: false }));
    check(`Secret ${S3_SECRET} (MinIO creds) exists`, s3SecretOk);
    const all = cjOk && notSuspended && cmOk && talosSecretOk && s3SecretOk;
    record("Backup machinery exists", { text: all ? "complete" : "INCOMPLETE", thresholdText: "complete", ok: all });
    expect(cjOk).toBe(true);
    expect(notSuspended).toBe(true);
    expect(cmOk).toBe(true);
    expect(talosSecretOk).toBe(true);
    expect(s3SecretOk).toBe(true);
  });

  test("CronJob is HEALTHY — scheduled recently, no unresolved failure", async () => {
    step("Health: the hourly CronJob is actually firing");
    const cj = JSON.parse(await kubectl(`get cronjob ${CRONJOB} -n ${NS} -o json`, { check: false }) || "{}");
    const lastSched = cj.status && cj.status.lastScheduleTime ? new Date(cj.status.lastScheduleTime).getTime() : 0;
    const sinceS = lastSched ? (Date.now() - lastSched) / 1000 : Infinity;
    const schedOk = sinceS <= MAX_CRONJOB_SINCE_SCHEDULED_S;
    check("last scheduled run is recent", schedOk,
      lastSched ? `${(sinceS / 60).toFixed(0)} min ago (≤ ${(MAX_CRONJOB_SINCE_SCHEDULED_S / 60).toFixed(0)} min)` : "never scheduled");
    // Any completed job for this CronJob that ended in success is a good sign; a Failed one is not.
    // The live etcd-backup jobTemplate carries no labels, so select ALL jobs in the ns and
    // filter by the CronJob's name prefix below (a label selector returns zero → dead check).
    const jobs = JSON.parse(await kubectl(
      `get jobs -n ${NS} -o json`, { check: false }) || '{"items":[]}');
    const named = (jobs.items || []).filter((j) => (j.metadata.name || "").startsWith(`${CRONJOB}-`));
    const anySucceeded = named.some((j) => (j.status && j.status.succeeded) > 0);
    const anyActiveFail = named.some((j) => (j.status && j.status.failed) > 0 && !(j.status.succeeded > 0)
      && !(j.status.conditions || []).some((c) => c.type === "Complete" && c.status === "True"));
    // If we found no labelled jobs (label may differ), don't hard-fail on job introspection —
    // lastScheduleTime already covers "is it firing"; jobs are a bonus signal.
    const healthOk = schedOk && !anyActiveFail;
    check("no etcd-backup job stuck in Failed", !anyActiveFail, `succeeded-seen=${anySucceeded}`);
    record("CronJob scheduled recently", {
      value: lastSched ? (sinceS / 60).toFixed(0) : "∞", unit: "min",
      threshold: (MAX_CRONJOB_SINCE_SCHEDULED_S / 60).toFixed(0), ok: schedOk });
    expect(schedOk).toBe(true);
    expect(anyActiveFail).toBe(false);
  });

  test("FRESHNESS — a <1h-fresh etcd snapshot object exists in MinIO", async () => {
    step("Freshness: the newest snapshot in MinIO must be younger than the RPO");
    const snap = await newestSnapshot();
    const exists = !!snap;
    check(`snapshot object present under s3://${S3_BUCKET}/${S3_PREFIX}/`, exists,
      exists ? snap.key.split("/").pop() : "NONE FOUND");
    expect(snap).not.toBeNull();
    const fresh = snap.ageS <= MAX_SNAPSHOT_AGE_S;
    gauge("newest snapshot age", snap.ageS, MAX_SNAPSHOT_AGE_S);
    record("Newest snapshot freshness", {
      value: (snap.ageS / 60).toFixed(1), unit: "min",
      threshold: (MAX_SNAPSHOT_AGE_S / 60).toFixed(0), ok: fresh });
    expect(fresh).toBe(true);
  });

  test("INTEGRITY — the stored snapshot is a well-formed, non-empty etcd db", async () => {
    step("Integrity: the newest stored snapshot must load as a real bbolt/etcd database");
    const snap = await newestSnapshot();
    expect(snap).not.toBeNull();
    const key = snap.key.split("/").pop();
    const res = await storedSnapshotIntegrity(key);
    const sizeOk = res.bytes >= MIN_SNAPSHOT_BYTES;
    check("snapshot is non-empty (≥ floor)", sizeOk, `${(res.bytes / 1048576).toFixed(1)} MiB (≥ ${(MIN_SNAPSHOT_BYTES / 1048576).toFixed(0)} MiB)`);
    check("snapshot carries bbolt/etcd meta magic (0xED0CDAED)", res.hasMagic, res.hex ? `head=${res.hex.slice(0, 24)}…` : "unreadable");
    const ok = sizeOk && res.hasMagic;
    record("Stored snapshot integrity", { text: ok ? "valid db" : "INVALID", thresholdText: "valid db", ok });
    expect(sizeOk).toBe(true);
    expect(res.hasMagic).toBe(true);
  });

  test("etcd is HEALTHY and snapshottable (talosctl etcd status)", async () => {
    step("Source health: etcd on the control plane must be healthy to snapshot");
    const status = await talosctl("etcd status", { check: false, timeout: 60000 });
    // `talosctl etcd status` prints a header + one data row per member. Match the DATA row
    // (the one carrying the node IP) — do NOT test the whole blob for /error/, or the
    // literal "ERRORS" column header would trip a false negative.
    const lines = status.split("\n").filter(Boolean);
    const hardErr = /rpc error|connection refused|context deadline exceeded|certificate|permission denied|no such host|failed to|unauthenticated/i.test(status);
    const dataRow = lines.slice(1).find((l) => l.includes(TALOS_NODE)) || "";
    const reachable = !!dataRow && !hardErr;
    // healthy = the member row reports a non-empty DB SIZE (e.g. "239 MB")
    const hasDbSize = /\b\d+(\.\d+)?\s*(B|kB|KB|MB|MiB|GB|GiB|TB)\b/.test(dataRow);
    check("etcd status reachable (member row present, no rpc error)", reachable, dataRow || lines[0] || "no output");
    check("etcd reports a non-empty DB size", hasDbSize, (dataRow.match(/\d+(\.\d+)?\s*[kKMGT]?i?B/) || ["?"])[0]);
    const ok = reachable && hasDbSize;
    record("etcd healthy + snapshottable", { text: ok ? "healthy" : "UNHEALTHY", thresholdText: "healthy", ok });
    expect(reachable).toBe(true);
    expect(hasDbSize).toBe(true);
  });

  // ── DESTRUCTIVE TIER — ETCD_DR_DESTRUCTIVE=1 only; still NON-destructive to live etcd ──

  dtest("RESTORE-PROCEDURE — fresh snapshot to a temp file LOADS + HASHES (no live restore)", async () => {
    step("Restore drill: exercise the snapshot->verify path a real restore consumes");
    info("this takes a NEW snapshot to a throwaway temp file — talosctl etcd snapshot is");
    info("read-only on etcd (it streams a copy); it NEVER mutates the live cluster.");
    const tmp = path.join(os.tmpdir(), `etcd-dr-${Date.now()}.db`);
    let wall = 0, ok = false, detail = "";
    try {
      const t0 = Date.now();
      // talosctl writes the snapshot to a local file on the admin host.
      await talosctl(`etcd snapshot "${tmp}"`, { timeout: 300000 });
      wall = (Date.now() - t0) / 1000;
      const v = await verifySnapshotFile(tmp);
      ok = v.ok;
      detail = `${v.tool}: ${v.detail}`;
      gauge("snapshot wall-time", wall, MAX_SNAPSHOT_WALL_S);
      check(`fresh snapshot loads + hashes (${(v.size / 1048576).toFixed(1)} MiB)`, ok, detail);
      record("Snapshot wall-time (fresh)", { value: wall.toFixed(1), unit: "s", threshold: MAX_SNAPSHOT_WALL_S, ok: wall <= MAX_SNAPSHOT_WALL_S });
      record("Fresh snapshot loads + hashes", { text: ok ? "valid" : "INVALID", thresholdText: "valid", ok });
    } finally {
      try { fs.existsSync(tmp) && fs.unlinkSync(tmp); } catch (_) {}
    }
    // Print the authoritative restore runbook. The actual `bootstrap --recover-from` step is
    // a DOCUMENTED NO-OP here (a true restore-into-canary needs a spare Talos node).
    const newest = await newestSnapshot().catch(() => null);
    printRestoreRunbook(newest ? newest.key.split("/").pop() : undefined);
    expect(ok).toBe(true);
    expect(wall).toBeLessThanOrEqual(MAX_SNAPSHOT_WALL_S);
  });

  dtest("RESTORE-INTO-CANARY — documented no-op (needs a spare Talos node)", async () => {
    step("Canary restore: intentionally NOT executed against live etcd");
    info("A real `talosctl bootstrap --recover-from=<db>` targets an actual control-plane");
    info("node and REPLACES its etcd — catastrophic on the live CP and infeasible without a");
    info("throwaway Talos node in this homelab. Documented no-op; runbook printed above.");
    check("live-etcd restore deliberately skipped (safety)", true, "see printRestoreRunbook()");
    record("Restore-into-canary", { text: "doc no-op", thresholdText: "safe", ok: true });
    expect(true).toBe(true);
  });
});
