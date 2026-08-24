/**
 * MinIO tenant — disaster-recovery / chaos test  (TALOS-23l.2)
 * -------------------------------------------------------------
 * Validates the operator-managed MinIO Tenant that is the cluster's S3 backend
 * (Loki / Mimir / Tempo + Velero). It is a SINGLE server (pools[0].servers=1)
 * on a ReadWriteOnce PVC backed by the Synology NFS storage class
 * (fatboy-nfs-appdata). The DR claim under test: because the data lives on NFS,
 * killing the one MinIO pod loses NO objects — the pod reschedules, re-mounts the
 * same RWO PVC, and every object is byte-identical afterward.
 *
 * TWO TIERS:
 *   READ-ONLY  (always run) — assert the DR machinery EXISTS + is healthy:
 *     tenant pod Ready, NFS-backed PVC bound, S3 service present, root-cred secret
 *     present, the core consumer buckets exist, and a canary object round-trips
 *     byte-identical through the S3 API. The canary only ever touches a THROWAWAY
 *     bucket (minio-dr-canary) and is deleted afterwards — production buckets
 *     (mimir/loki/tempo/velero/cnpg-backups/…) are never written or read.
 *   DESTRUCTIVE (MINIO_DR_DESTRUCTIVE=1) — write a canary object, DELETE the live
 *     MinIO tenant pod, wait for it to come back Ready, then prove the canary
 *     object is still readable + byte-identical (NFS persistence) and MEASURE the
 *     S3 recovery wall-time. Still confined to the throwaway bucket.
 *
 *   (from repo root)  npm test                                    # this + others, read-only
 *   (this suite only) npm test -- --selectProjects minio-dr       # read-only
 *                     MINIO_DR_DESTRUCTIVE=1 npm run test:dr       # full chaos (homelab only)
 *
 * Needs `kubectl` (context = the cluster) on PATH. All S3 I/O runs through an
 * ephemeral in-cluster `minio/mc` pod (the tenant is ClusterIP-only); root creds
 * come from the minio-root-credentials Secret.
 */
const { exec } = require("child_process");

// ---- config ---------------------------------------------------------------
const NS = process.env.MINIO_NS || "minio";
const S3_SVC = process.env.MINIO_S3_SVC || "minio"; // operator-created ClusterIP (port 80 -> 9000)
const ENDPOINT = process.env.MINIO_ENDPOINT || `http://${S3_SVC}.${NS}.svc.cluster.local`;
const ROOT_SECRET = process.env.MINIO_ROOT_SECRET || "minio-root-credentials"; // AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
const TENANT_SELECTOR = process.env.MINIO_TENANT_LABEL || "v1.min.io/tenant=minio";
const CORE_BUCKETS = (process.env.MINIO_CORE_BUCKETS || "mimir,loki,tempo,velero,cnpg-backups")
  .split(",").map((s) => s.trim()).filter(Boolean);
const CANARY_BUCKET = process.env.MINIO_CANARY_BUCKET || "minio-dr-canary"; // THROWAWAY — never a real bucket
const MC_IMAGE = process.env.MINIO_MC_IMAGE || "minio/mc:latest";
const DESTRUCTIVE = process.env.MINIO_DR_DESTRUCTIVE === "1";
const MAX_RECOVERY_S = parseFloat(process.env.MINIO_MAX_RECOVERY_S || "180"); // pod reschedule + NFS remount + minio start

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
  out(`\n${C.bold}${C.cyan}═══════════════ MinIO DR TEST — MEASUREMENTS ═══════════════${C.reset}`);
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
// POSIX single-quote a value so secrets/scripts survive the host shell untouched.
const shq = (s) => `'${String(s).replace(/'/g, `'\\''`)}'`;

async function waitUntil(fn, timeoutMs = 180000, intervalMs = 3000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    try { if (await fn()) return true; } catch (_) {}
    await sleep(intervalMs);
  }
  return false;
}

// tenant pods (the single MinIO server, plus any future pool members)
async function tenantPods() {
  const jp = "jsonpath={range .items[*]}{.metadata.name}|{.status.phase}|{.status.podIP}|" +
    "{range .status.conditions[?(@.type=='Ready')]}{.status}{end}{'\\n'}{end}";
  const o = await kubectl(`get pods -n ${NS} -l ${TENANT_SELECTOR} -o "${jp}"`, { check: false });
  return o.split("\n").filter(Boolean).map((l) => {
    const [name, phase, ip, ready] = l.split("|");
    return { name, phase, ip, ready: ready === "True" };
  });
}
const tenantPodReady = async () => (await tenantPods()).some((p) => p.ready);

// root creds straight from the ExternalSecret-materialised Secret
async function rootCreds() {
  const b64 = (k) => kubectl(`get secret ${ROOT_SECRET} -n ${NS} -o jsonpath={.data.${k}}`, { check: false });
  const dec = (s) => Buffer.from(s || "", "base64").toString();
  return { access: dec(await b64("AWS_ACCESS_KEY_ID")), secret: dec(await b64("AWS_SECRET_ACCESS_KEY")) };
}

// Run an mc script inside a throwaway in-cluster pod. Creds are injected as env
// (AK/SK) and never URL-encoded — `mc alias set` takes them positionally. The
// script runs after the alias `local` is configured against the tenant.
async function mcRun(script, { timeout = 120000 } = {}) {
  const { access, secret } = await rootCreds();
  if (!access || !secret) throw new Error(`could not read ${ROOT_SECRET} (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY)`);
  const name = `minio-dr-mc-${Date.now()}`;
  const inner = `set -e\n` +
    `mc alias set local ${ENDPOINT} "$AK" "$SK" --api S3v4 >/dev/null 2>&1 || { echo __MC_ALIAS_FAIL__; exit 40; }\n` +
    script;
  const cmd =
    `run ${name} -n ${NS} --rm -i --restart=Never --image=${MC_IMAGE} ` +
    `--env=AK=${shq(access)} --env=SK=${shq(secret)} --command -- sh -c ${shq(inner)}`;
  return kubectl(cmd, { timeout, check: false });
}

// Deterministic canary payload — asserted byte-for-byte on read-back.
const canaryContent = (tag) => `minio-dr-canary|${tag}|${"0123456789abcdef".repeat(8)}`;
const CANARY_OBJ = "canary.txt";

// Round-trip a canary object entirely within the throwaway bucket, then clean up.
// Returns the exact bytes mc read back so the caller can assert byte-identity.
async function canaryRoundTrip(content) {
  const o = await mcRun(
    `mc mb --ignore-existing local/${CANARY_BUCKET} >/dev/null 2>&1\n` +
    `printf '%s' ${shqInner(content)} | mc pipe local/${CANARY_BUCKET}/${CANARY_OBJ}\n` +
    `echo __BEGIN__\n` +
    `mc cat local/${CANARY_BUCKET}/${CANARY_OBJ}\n` +
    `echo\n` +
    `echo __END__\n` +
    `mc rm --force local/${CANARY_BUCKET}/${CANARY_OBJ} >/dev/null 2>&1 || true\n` +
    `mc rb --force local/${CANARY_BUCKET} >/dev/null 2>&1 || true\n`);
  return extract(o);
}
// nested single-quote for the pod-side sh -c (already single-quoted once by shq)
const shqInner = (s) => `'${String(s).replace(/'/g, `'\\''`)}'`;
function extract(o) {
  const m = o.match(/__BEGIN__\n([\s\S]*?)\n__END__/);
  return m ? m[1] : "";
}

const dtest = DESTRUCTIVE ? test : test.skip;

// ============================================================================
describe("MinIO tenant — disaster recovery", () => {
  jest.setTimeout(600000);

  beforeAll(async () => {
    step("Pre-flight");
    const pods = await tenantPods();
    const ready = pods.filter((p) => p.ready).length;
    check(`tenant pod(s) Ready (${TENANT_SELECTOR})`, ready >= 1, pods.map((p) => `${p.name}:${p.ready ? "Ready" : p.phase}`).join(" "));
    if (!DESTRUCTIVE) info("read-only mode — set MINIO_DR_DESTRUCTIVE=1 for the pod-kill chaos scenario");
  }, 120000);

  afterAll(printSummary);

  // -------- READ-ONLY TIER (always) --------
  test("tenant server pod is Ready", async () => {
    const pods = await tenantPods();
    const ready = pods.filter((p) => p.ready);
    check("at least one MinIO server pod Ready", ready.length >= 1, ready.map((p) => p.name).join(", ") || "none");
    record("Tenant server pod Ready", { text: `${ready.length}/${pods.length}`, thresholdText: "≥ 1", ok: ready.length >= 1 });
    expect(ready.length).toBeGreaterThanOrEqual(1);
  });

  test("data PVC is Bound on the NFS storage class (RWO persistence backbone)", async () => {
    const jp = "jsonpath={range .items[*]}{.metadata.name}|{.status.phase}|{.spec.storageClassName}|{.spec.accessModes[0]}{'\\n'}{end}";
    const o = await kubectl(`get pvc -n ${NS} -o "${jp}"`, { check: false });
    const pvcs = o.split("\n").filter(Boolean).map((l) => { const [name, phase, sc, mode] = l.split("|"); return { name, phase, sc, mode }; });
    // the tenant's volumeClaimTemplate is named `data`; match its per-pod PVCs (data-minio-pool-0-0…)
    // MinIO operator names per-pod PVCs data<N>-<tenant>-pool-<n>-<n> (e.g. data0-minio-pool-0-0),
    // so match on the tenant pool substring rather than a bare `data-` prefix.
    const dataPvcs = pvcs.filter((p) => p.name.includes("minio-pool"));
    const bound = dataPvcs.filter((p) => p.phase === "Bound");
    const rwoNfs = bound.filter((p) => p.mode === "ReadWriteOnce" && /nfs/i.test(p.sc || ""));
    check("tenant data PVC(s) Bound", bound.length >= 1, dataPvcs.map((p) => `${p.name}:${p.phase}`).join(" ") || "none found");
    check("PVC is ReadWriteOnce on an NFS class", rwoNfs.length >= 1, rwoNfs.map((p) => `${p.name} (${p.sc})`).join(" ") || "check MINIO storageClass");
    record("Data PVC Bound (NFS RWO)", { text: bound.length ? `${bound.length} bound` : "none", thresholdText: "≥ 1", ok: bound.length >= 1 });
    expect(bound.length).toBeGreaterThanOrEqual(1);
  });

  test("S3 ClusterIP service exists", async () => {
    const ip = await kubectl(`get svc ${S3_SVC} -n ${NS} -o jsonpath={.spec.clusterIP}`, { check: false });
    check(`service ${S3_SVC} present`, !!ip && ip !== "None", `clusterIP=${ip || "none"}`);
    record("S3 service present", { text: ip || "none", thresholdText: "exists", ok: !!ip && ip !== "None" });
    expect(!!ip && ip !== "None").toBe(true);
  });

  test("root-credentials secret exists with S3 keys", async () => {
    const { access, secret } = await rootCreds();
    const ok = !!access && !!secret;
    check(`${ROOT_SECRET} has AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY`, ok, ok ? `access=${access.slice(0, 3)}…` : "MISSING");
    record("Root-cred secret populated", { text: ok ? "yes" : "no", thresholdText: "yes", ok });
    expect(ok).toBe(true);
  });

  test("core consumer buckets exist (Loki/Mimir/Tempo/Velero backend)", async () => {
    step("Enumerating core buckets via mc");
    const probe = CORE_BUCKETS
      .map((b) => `if mc ls local/${b} >/dev/null 2>&1; then echo "${b} OK"; else echo "${b} MISSING"; fi`).join("\n");
    const o = await mcRun(probe, { timeout: 120000 });
    const present = {};
    for (const b of CORE_BUCKETS) present[b] = new RegExp(`^${b} OK$`, "m").test(o);
    let allOk = CORE_BUCKETS.length > 0;
    for (const b of CORE_BUCKETS) { const ok = present[b]; allOk = allOk && ok; check(`bucket ${b}`, ok, ok ? "" : "MISSING"); }
    record("Core buckets exist", { text: `${Object.values(present).filter(Boolean).length}/${CORE_BUCKETS.length}`, thresholdText: `${CORE_BUCKETS.length}`, ok: allOk });
    expect(allOk).toBe(true);
  });

  test("canary object round-trips byte-identical through S3 (throwaway bucket)", async () => {
    step(`Canary round-trip in throwaway bucket ${C.yellow}${CANARY_BUCKET}${C.reset} (production buckets untouched)`);
    const content = canaryContent(`ro-${Date.now()}`);
    const got = await canaryRoundTrip(content);
    const identical = got === content;
    check("GET bytes === PUT bytes", identical, identical ? `${content.length} bytes match` : `PUT ${content.length}B / GET ${got.length}B`);
    record("Canary write→GET byte-identical", { text: identical ? "identical" : "MISMATCH", thresholdText: "identical", ok: identical });
    expect(got).toBe(content);
  });

  // -------- DESTRUCTIVE TIER (MINIO_DR_DESTRUCTIVE=1) --------
  dtest("PERSISTENCE + RECOVERY: kill the MinIO pod → object survives on NFS + measure recovery", async () => {
    // 1) write a durable canary into the throwaway bucket (NOT cleaned up until after recovery)
    const content = canaryContent(`dr-${Date.now()}`);
    step("Chaos setup: writing a durable canary object into the throwaway bucket");
    const wrote = await mcRun(
      `mc mb --ignore-existing local/${CANARY_BUCKET} >/dev/null 2>&1\n` +
      `printf '%s' ${shqInner(content)} | mc pipe local/${CANARY_BUCKET}/${CANARY_OBJ}\n` +
      `mc stat local/${CANARY_BUCKET}/${CANARY_OBJ} >/dev/null 2>&1 && echo __WROTE_OK__ || echo __WROTE_FAIL__\n`);
    check("canary object staged pre-kill", wrote.includes("__WROTE_OK__"), wrote.includes("__WROTE_OK__") ? `${content.length} bytes` : "write failed");
    expect(wrote).toContain("__WROTE_OK__");

    // 2) delete the live tenant pod
    const before = (await tenantPods()).find((p) => p.ready) || (await tenantPods())[0];
    step(`Chaos: delete the MinIO server pod ${C.yellow}${before.name}${C.reset} (single server — full S3 outage until it returns)`);
    const t0 = Date.now();
    await kubectl(`delete pod ${before.name} -n ${NS} --wait=false`, { check: false });

    // 3) wait for a tenant pod to be Ready again (pod reschedules + re-mounts the SAME RWO NFS PVC)
    info("waiting for the tenant pod to reschedule + re-mount the NFS PVC…");
    const podBack = await waitUntil(tenantPodReady, MAX_RECOVERY_S * 1000, 3000);
    const podReadyDt = (Date.now() - t0) / 1000;
    check("tenant pod Ready again after kill", podBack, podBack ? `${podReadyDt.toFixed(1)}s` : "TIMEOUT");

    // 4) wait until the S3 API actually serves the canary again, and it is byte-identical
    let got = "", s3Dt = 0;
    const s3Back = await waitUntil(async () => {
      const o = await mcRun(
        `echo __BEGIN__\n` +
        `mc cat local/${CANARY_BUCKET}/${CANARY_OBJ} 2>/dev/null\n` +
        `echo\n` +
        `echo __END__\n`, { timeout: 90000 });
      got = extract(o);
      if (got === content) { s3Dt = (Date.now() - t0) / 1000; return true; }
      return false;
    }, MAX_RECOVERY_S * 1000, 4000);
    const identical = got === content;

    check("canary object survived the pod kill (NFS persistence)", identical, identical ? "byte-identical" : `GET ${got.length}B ≠ PUT ${content.length}B`);
    gauge("S3 recovery wall-time (kill → object readable)", s3Back ? s3Dt : MAX_RECOVERY_S + 1, MAX_RECOVERY_S);

    // 5) cleanup — remove the throwaway bucket + object
    await mcRun(
      `mc rm --force local/${CANARY_BUCKET}/${CANARY_OBJ} >/dev/null 2>&1 || true\n` +
      `mc rb --force local/${CANARY_BUCKET} >/dev/null 2>&1 || true\n`, { timeout: 90000 }).catch(() => {});

    record("Pod-Ready recovery wall-time", { value: podReadyDt.toFixed(1), unit: "s", threshold: MAX_RECOVERY_S, ok: podBack });
    record("S3 recovery wall-time (kill→read)", { value: (s3Back ? s3Dt : MAX_RECOVERY_S + 1).toFixed(1), unit: "s", threshold: MAX_RECOVERY_S, ok: s3Back && s3Dt <= MAX_RECOVERY_S });
    record("Object survived pod kill (NFS)", { text: identical ? "byte-identical" : "LOST/CORRUPT", thresholdText: "byte-identical", ok: identical });

    expect(podBack).toBe(true);
    expect(s3Back).toBe(true);
    expect(got).toBe(content);
  });
});
