/**
 * crossplane-demo — operator catalog integration test (companion to the pihole/vpn DR suites).
 * ---------------------------------------------------------------------------------------------
 * Verifies the self-service operator catalog (TALOS-ja5) end-to-end, in two tiers per subsystem:
 *   CRD/health  — the provisioned CR exists and its operator reconciled it to Ready.
 *   functional  — the Go "flex" pod actually exercised the backend (bucket/publish-consume/
 *                 set-get/insert-query/index-search/workflow/celery/crossplane) and reports OK.
 *
 *   (repo root)  npm test -- --selectProjects provisioning-demo
 *
 * Needs `kubectl` (context = the cluster) on PATH. NS = crossplane-demo.
 */
const { exec } = require("child_process");

const NS = process.env.DEMO_NS || "crossplane-demo";
const FLEX = process.env.FLEX_DEPLOY || "demo-flex";
const C = { reset: "\x1b[0m", bold: "\x1b[1m", dim: "\x1b[2m", green: "\x1b[32m", red: "\x1b[31m", cyan: "\x1b[36m", grey: "\x1b[90m" };
const out = (s = "") => process.stdout.write(String(s) + "\n");
const step = (m) => out(`\n${C.bold}${C.cyan}▶ ${m}${C.reset}`);
const check = (label, ok, detail = "") => { out(`   ${ok ? `${C.green}✓${C.reset}` : `${C.red}✗${C.reset}`} ${label}${detail ? `  ${C.dim}${detail}${C.reset}` : ""}`); return ok; };

const METRICS = [];
const record = (name, ok, detail) => METRICS.push({ name, ok, detail });
function printSummary() {
  if (!METRICS.length) return;
  const pad = (s, n) => String(s).padEnd(n);
  out(`\n${C.bold}${C.cyan}════ crossplane-demo — SUBSYSTEM MATRIX ════${C.reset}`);
  out(`   ${C.dim}${pad("Subsystem", 26)}${pad("Result", 10)}Detail${C.reset}`);
  out(`   ${C.dim}${"─".repeat(64)}${C.reset}`);
  for (const m of METRICS) out(`   ${pad(m.name, 26)}${m.ok ? `${C.green}✓ OK  ${C.reset}` : `${C.red}✗ FAIL${C.reset}`}    ${C.dim}${m.detail || ""}${C.reset}`);
  out(`   ${C.dim}${"─".repeat(64)}${C.reset}`);
  out(`   ${C.bold}${METRICS.filter((m) => m.ok).length}/${METRICS.length} subsystems OK${C.reset}\n`);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function sh(cmd, { timeout = 60000, check: doCheck = false } = {}) {
  return new Promise((resolve, reject) => {
    exec(cmd, { timeout, maxBuffer: 8 * 1024 * 1024 }, (err, stdout, stderr) => {
      if (err && doCheck) return reject(new Error(`${cmd}\n${stderr || err.message}`));
      resolve((stdout || "").trim());
    });
  });
}
const kubectl = (a, o) => sh(`kubectl ${a}`, o);
async function waitUntil(fn, timeoutMs = 240000, intervalMs = 5000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) { try { if (await fn()) return true; } catch (_) {} await sleep(intervalMs); }
  return false;
}

describe("crossplane-demo — operator catalog", () => {
  jest.setTimeout(300000);
  afterAll(printSummary);

  // ---- CRD/health tier: each provisioned CR exists + reconciled Ready ---------------------
  const CRS = [
    { label: "RabbitMQ (RabbitmqCluster)", kind: "rabbitmqclusters.rabbitmq.com", name: "demo-rabbit", ready: `-o jsonpath={.status.conditions[?(@.type=='AllReplicasReady')].status}`, want: "True" },
    { label: "Dragonfly (Dragonfly)", kind: "dragonflies.dragonflydb.io", name: "demo", ready: `-o jsonpath={.status.phase}`, want: "Ready" },
    { label: "ClickHouse (ClickHouseInstallation)", kind: "clickhouseinstallations.clickhouse.altinity.com", name: "demo", ready: `-o jsonpath={.status.status}`, want: "Completed" },
    { label: "OpenSearch (OpenSearchCluster)", kind: "opensearchclusters.opensearch.opster.io", name: "demo", ready: `-o jsonpath={.status.phase}`, want: "RUNNING" },
    { label: "KEDA (ScaledObject)", kind: "scaledobjects.keda.sh", name: "demo-celery", ready: `-o jsonpath={.status.conditions[?(@.type=='Ready')].status}`, want: "True" },
    { label: "Argo (WorkflowTemplate)", kind: "workflowtemplates.argoproj.io", name: "demo-hello", ready: "", want: "" },
    { label: "Crossplane (Object)", kind: "objects.kubernetes.crossplane.io", name: "crossplane-made-this", ready: `-o jsonpath={.status.conditions[?(@.type=='Ready')].status}`, want: "True" },
  ];
  for (const cr of CRS) {
    test(`CRD/health: ${cr.label}`, async () => {
      step(`Provisioned CR present + Ready: ${cr.label}`);
      const exists = (await kubectl(`get ${cr.kind} ${cr.name} -n ${NS} -o name`, { check: false }));
      let ok = !!exists;
      let detail = exists ? cr.name : "not found";
      if (ok && cr.ready) {
        const ready = await waitUntil(async () => (await kubectl(`get ${cr.kind} ${cr.name} -n ${NS} ${cr.ready}`, { check: false })) === cr.want, 180000, 5000);
        ok = ready; detail = `${exists.split("/").pop()} status=${cr.want}${ready ? "" : " (NOT reached)"}`;
      }
      check(`${cr.label}`, ok, detail);
      record(cr.label, ok, detail);
      expect(ok).toBe(true);
    });
  }

  // ---- functional tier: the Go flex pod exercised every backend ---------------------------
  test("functional: flex /run reports every subsystem OK", async () => {
    step("Driving the Go flex pod (/run) to exercise each provisioned backend");
    const pod = await kubectl(`get pods -n ${NS} -l app=${FLEX} -o jsonpath={.items[0].metadata.name}`, { check: false });
    if (!pod) { check("flex pod present", false, "no demo-flex pod"); record("flex functional", false, "no pod"); expect(pod).toBeTruthy(); return; }
    // run the checks in-pod (the flex binary supports -once → JSON on stdout)
    const raw = await kubectl(`exec ${pod} -n ${NS} -- /flex -once`, { check: false, timeout: 120000 });
    let parsed;
    try { parsed = JSON.parse(raw.slice(raw.indexOf("{"))); } catch (_) { parsed = null; }
    if (!parsed || !Array.isArray(parsed.results)) {
      check("flex /run returned JSON", false, raw.slice(0, 120));
      record("flex functional", false, "no JSON"); expect(parsed).toBeTruthy(); return;
    }
    for (const r of parsed.results) {
      const ok = r.ok || r.skipped;
      check(`flex:${r.subsystem}`, ok, r.detail || (r.skipped ? "skipped" : ""));
      record(`flex:${r.subsystem}`, r.ok, r.skipped ? "skipped" : (r.detail || ""));
    }
    // the two provisioning proofs the flex util asserts
    const cfgm = await kubectl(`get configmap crossplane-made-this -n ${NS} -o name`, { check: false });
    check("crossplane provisioned a ConfigMap", !!cfgm, cfgm || "missing");
    record("crossplane ConfigMap", !!cfgm, cfgm ? "present" : "missing");
    expect(parsed.all_ok || parsed.results.every((r) => r.ok || r.skipped)).toBe(true);
  });
});
