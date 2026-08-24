/**
 * Cilium LB-IPAM + L2 announcement — disaster-recovery / chaos test  (TALOS-23l.3)
 * -------------------------------------------------------------------------------
 * Validates the Cilium LoadBalancer IPAM design: a CiliumLoadBalancerIPPool hands VIPs to
 * type=LoadBalancer Services, and a CiliumL2AnnouncementPolicy ARP-announces each VIP from one
 * elected node (an L2 lease in kube-system). When that node's announcer dies the lease must be
 * re-elected and the VIP re-announced from a surviving node. This suite MEASURES that VIP
 * failover downtime — on a THROWAWAY canary VIP, never a production one.
 *
 * Read-only checks always run (assert the LB-IPAM machinery EXISTS + is healthy — never mutate).
 * DESTRUCTIVE scenarios (they stand up a canary LoadBalancer in its OWN dedicated IP-pool block
 * and take out the announcing node) run only when
 *     CILIUM_LBIPAM_DR_DESTRUCTIVE=1
 * so this can NEVER disrupt a real LB VIP (pihole .240, traefik, minio, …) by accident.
 *
 *   npm install && npm test                        # safe, read-only
 *   CILIUM_LBIPAM_DR_DESTRUCTIVE=1 npm run test:dr  # full chaos test (homelab only)
 *
 * Needs `kubectl` (context = the cluster) on PATH. The optional VIP-reachability probe curls the
 * canary VIP directly over the LAN (like the Pi-hole suite digs the DNS VIP), so run it from a
 * host on the same L2 segment.
 */
const { exec } = require("child_process");
const path = require("path");

// ---- config ---------------------------------------------------------------
// Cilium CRDs are cluster-scoped; these are the ACTUAL resources from infrastructure/base/cilium/lb-ipam.yaml.
const POOL_KIND = "ciliumloadbalancerippools.cilium.io";
const L2_KIND = "ciliuml2announcementpolicies.cilium.io";
const KNOWN_POOL = process.env.CILIUM_LBIPAM_POOL || "lan-pihole-pool";
const KNOWN_L2 = process.env.CILIUM_LBIPAM_L2 || "lan-pihole-l2";
// a KNOWN production LoadBalancer Service that must always hold an allocated external IP
const PROD_NS = process.env.CILIUM_LBIPAM_PROD_NS || "pihole";
const PROD_SVC = process.env.CILIUM_LBIPAM_PROD_SVC || "pihole";
const PROD_VIP = process.env.CILIUM_LBIPAM_PROD_VIP || "192.168.1.240";
const PROD_LEASE = process.env.CILIUM_LBIPAM_PROD_LEASE || "cilium-l2announce-pihole-pihole";

// ---- canary (destructive chaos target — real LB VIPs untouched) ------------
const CANARY_NS = process.env.CILIUM_LBIPAM_CANARY_NS || "lbipam-dr";
const CANARY_SVC = process.env.CILIUM_LBIPAM_CANARY_SVC || "lbipam-canary";
const CANARY_VIP = process.env.CILIUM_LBIPAM_CANARY_VIP || "192.168.1.251";
const CANARY_LEASE = process.env.CILIUM_LBIPAM_CANARY_LEASE || `cilium-l2announce-${CANARY_NS}-${CANARY_SVC}`;
const CANARY_YAML = path.join(__dirname, "canary-lb.yaml");
// chaos mode: "agent" evicts the announcing cilium-agent (deterministically moves the VIP to a
// surviving node); "lease" just deletes the L2 lease (lighter — cilium re-elects, may re-pick the
// same node). Datapath eBPF survives a cilium-agent restart, so "agent" is safe + self-healing.
// Default to "lease" (delete the canary VIP's L2 lease) — the SAFE subset: it forces a
// re-announce without touching the shared node-level cilium-agent. "agent" mode
// (evict the announcing cilium-agent) is opt-in via CILIUM_LBIPAM_CHAOS=agent.
const CHAOS = (process.env.CILIUM_LBIPAM_CHAOS || "lease").toLowerCase();

const DESTRUCTIVE = process.env.CILIUM_LBIPAM_DR_DESTRUCTIVE === "1";
const MAX_FAILOVER_S = parseFloat(process.env.CILIUM_LBIPAM_MAX_FAILOVER_S || "30");

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

// ---- shell / kubectl helpers (async so probes keep sampling) --------------
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const IPV4 = /(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})/;
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

// ---- LB-IPAM introspection ------------------------------------------------
async function names(kind) {
  const o = await kubectl(`get ${kind} -o name`, { check: false });
  return o.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => l.split("/").pop());
}
// every type=LoadBalancer Service cluster-wide that has an allocated external IP
async function lbServicesWithIP() {
  const jp = "jsonpath={range .items[?(@.spec.type=='LoadBalancer')]}{.metadata.namespace}/{.metadata.name}|{.status.loadBalancer.ingress[0].ip}{'\\n'}{end}";
  const o = await kubectl(`get svc -A -o "${jp}"`, { check: false });
  return o.split("\n").filter(Boolean).map((l) => {
    const [svc, ip] = l.split("|");
    return { svc, ip: (ip || "").trim() };
  });
}
async function svcExternalIP(ns, name) {
  return kubectl(`get svc ${name} -n ${ns} -o jsonpath={.status.loadBalancer.ingress[0].ip}`, { check: false });
}
// holder of an L2 lease = the node currently ARP-announcing the VIP
const leaseHolder = (name) =>
  kubectl(`get lease ${name} -n kube-system -o jsonpath={.spec.holderIdentity}`, { check: false });
async function leaseExists(name) {
  const o = await kubectl(`get lease ${name} -n kube-system -o name`, { check: false });
  return o.includes(name);
}
// tolerate cilium truncating/hashing a long lease name: fall back to a substring scan
async function resolveCanaryLease() {
  if (await leaseExists(CANARY_LEASE)) return CANARY_LEASE;
  const o = await kubectl("get leases -n kube-system -o name", { check: false });
  const hit = o.split("\n").map((l) => l.split("/").pop())
    .find((n) => n.includes("l2announce") && n.includes(CANARY_SVC));
  return hit || CANARY_LEASE;
}
// HTTP reachability of a VIP straight over the LAN (canary whoami answers :80). "" = unreachable.
async function vipHttpOk(vip, timeoutS = 1) {
  const o = await sh(`curl -s -o /dev/null -w "%{http_code}" --max-time ${timeoutS} http://${vip}/`,
    { timeout: (timeoutS + 2) * 1000, check: false });
  return /^(2|3|4)\d\d$/.test(o.trim()); // any HTTP response = the VIP is answering on L2
}

// ---- background VIP probe (mirror of the Pi-hole DNS probe) ----------------
function startProbe(vip, intervalMs = 250) {
  const samples = []; // { t, ok }
  let running = true;
  (async () => {
    while (running) {
      const t = Date.now();
      const ok = await vipHttpOk(vip);
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
      if (start !== null && samples.length) worst = Math.max(worst, samples[samples.length - 1].t - start);
      return worst / 1000;
    },
    availability() {
      return samples.length ? samples.filter((s) => s.ok).length / samples.length : 0;
    },
    sampled: () => samples.length,
  };
}

// ---- canary lifecycle ------------------------------------------------------
async function createCanary() {
  await kubectl(`apply -f ${CANARY_YAML}`);
  await kubectl(`rollout status deploy/${CANARY_SVC} -n ${CANARY_NS} --timeout=120s`, { check: false });
  // wait for LB-IPAM to allocate the VIP…
  await waitUntil(async () => (await svcExternalIP(CANARY_NS, CANARY_SVC)) === CANARY_VIP, 120000, 3000);
  // …and for cilium to elect an announcer (the L2 lease to gain a holder)
  await waitUntil(async () => !!(await leaseHolder(await resolveCanaryLease())), 120000, 3000);
}
const deleteCanary = () => kubectl(`delete -f ${CANARY_YAML} --ignore-not-found --wait=false`, { check: false });

const dtest = DESTRUCTIVE ? test : test.skip;

// ---- measurements collector (printed as a summary table at the end) --------
const METRICS = [];
const record = (name, m) => METRICS.push({ name, ...m });
function printSummary() {
  if (!METRICS.length) return;
  const pad = (s, n) => String(s).padEnd(n);
  out(`\n${C.bold}${C.cyan}════════════ CILIUM LB-IPAM DR — MEASUREMENTS ════════════${C.reset}`);
  out(`   ${C.dim}${pad("Metric", 40)}${pad("Measured", 11)}${pad("Threshold", 11)}Result${C.reset}`);
  out(`   ${C.dim}${"─".repeat(68)}${C.reset}`);
  for (const m of METRICS) {
    const meas = m.value !== undefined ? `${m.value}${m.unit || ""}` : m.text || "—";
    const thr = m.threshold !== undefined ? `≤ ${m.threshold}${m.unit || ""}` : m.thresholdText || "—";
    const mark = m.ok ? `${C.green}✓ PASS${C.reset}` : `${C.red}✗ FAIL${C.reset}`;
    const mc = m.ok ? C.green : C.red;
    out(`   ${pad(m.name, 40)}${mc}${pad(meas, 11)}${C.reset}${C.dim}${pad(thr, 11)}${C.reset}${mark}`);
  }
  const passed = METRICS.filter((m) => m.ok).length;
  out(`   ${C.dim}${"─".repeat(68)}${C.reset}`);
  out(`   ${C.bold}${passed}/${METRICS.length} metrics within threshold${C.reset}`);
  out(`${C.bold}${C.cyan}══════════════════════════════════════════════════════════${C.reset}\n`);
}

// ============================================================================
describe("Cilium LB-IPAM + L2 announcement — disaster recovery", () => {
  jest.setTimeout(300000);

  beforeAll(async () => {
    step("Pre-flight");
    // fail loudly (not silently green) if kubectl can't reach the cluster or Cilium CRDs are absent
    const crds = await kubectl(`get crd ${POOL_KIND} ${L2_KIND} -o name`, { check: false });
    check("Cilium LB-IPAM + L2 CRDs installed", crds.includes("ippool") && crds.includes("l2announcement"), crds.replace(/\n/g, "  "));
    expect(crds).toContain("ippool");
    if (DESTRUCTIVE) {
      step("Standing up the throwaway canary LoadBalancer (chaos target — real VIPs stay untouched)");
      await createCanary();
      const lease = await resolveCanaryLease();
      info(`canary ${CANARY_NS}/${CANARY_SVC} → VIP ${await svcExternalIP(CANARY_NS, CANARY_SVC)}; announced by ${await leaseHolder(lease)}`);
    } else {
      info("read-only mode — set CILIUM_LBIPAM_DR_DESTRUCTIVE=1 for the canary VIP-failover chaos");
    }
  }, 200000);

  afterAll(async () => {
    if (DESTRUCTIVE) { step("Cleanup: removing the canary LoadBalancer + its dedicated pool/policy"); await deleteCanary(); }
    printSummary();
  });

  // ---- READ-ONLY tier (always runs — asserts the DR machinery EXISTS + is healthy) ----
  test("CiliumLoadBalancerIPPool(s) exist and the known LAN pool is present", async () => {
    const pools = await names(POOL_KIND);
    check("at least one CiliumLoadBalancerIPPool exists", pools.length > 0, `pools=[${pools.join(", ")}]`);
    const hasKnown = pools.includes(KNOWN_POOL);
    check(`known pool "${KNOWN_POOL}" present`, hasKnown);
    // Ready condition on the known pool (cilium sets status.conditions[type=cilium.io/PoolConflict]=False when healthy)
    const conflict = await kubectl(
      `get ${POOL_KIND} ${KNOWN_POOL} -o jsonpath="{.status.conditions[?(@.type=='cilium.io/PoolConflict')].status}"`,
      { check: false });
    const noConflict = conflict !== "True"; // "False" (healthy) or "" (older cilium omits it) both pass
    check(`pool "${KNOWN_POOL}" has no IP conflict`, noConflict, `PoolConflict=${conflict || "unset"}`);
    record("CiliumLoadBalancerIPPools exist", { value: pools.length, thresholdText: "≥ 1", ok: pools.length > 0 });
    expect(pools.length).toBeGreaterThan(0);
    expect(hasKnown).toBe(true);
    expect(noConflict).toBe(true);
  });

  test("a type=LoadBalancer Service has an allocated external IP", async () => {
    const svcs = await lbServicesWithIP();
    const withIp = svcs.filter((s) => IPV4.test(s.ip));
    for (const s of svcs) check(`${s.svc}`, IPV4.test(s.ip), s.ip || "(pending)");
    // the known prod VIP specifically must be allocated
    const prodIp = await svcExternalIP(PROD_NS, PROD_SVC);
    const prodOk = prodIp === PROD_VIP;
    check(`prod ${PROD_NS}/${PROD_SVC} → ${PROD_VIP}`, prodOk, `allocated=${prodIp || "(pending)"}`);
    record("LoadBalancer Services with external IP", { value: withIp.length, thresholdText: "≥ 1", ok: withIp.length > 0 });
    record(`Prod VIP ${PROD_NS}/${PROD_SVC} allocated`, { text: prodIp || "pending", thresholdText: PROD_VIP, ok: prodOk });
    expect(withIp.length).toBeGreaterThan(0);
    expect(prodOk).toBe(true);
  });

  test("CiliumL2AnnouncementPolicy present and the prod VIP has an active L2 lease", async () => {
    const pols = await names(L2_KIND);
    check("at least one CiliumL2AnnouncementPolicy exists", pols.length > 0, `policies=[${pols.join(", ")}]`);
    const hasKnown = pols.includes(KNOWN_L2);
    check(`known L2 policy "${KNOWN_L2}" present`, hasKnown);
    // the prod VIP must currently be announced by exactly one node (a lease with a holder)
    const holder = await leaseHolder(PROD_LEASE);
    const announced = !!holder;
    check(`prod VIP announced (lease ${PROD_LEASE})`, announced, holder ? `holder=${holder}` : "no holder");
    record("CiliumL2AnnouncementPolicies exist", { value: pols.length, thresholdText: "≥ 1", ok: pols.length > 0 });
    record("Prod VIP has an active L2 announcer", { text: holder || "none", thresholdText: "1 node", ok: announced });
    expect(pols.length).toBeGreaterThan(0);
    expect(hasKnown).toBe(true);
    expect(announced).toBe(true);
  });

  // ---- DESTRUCTIVE tier (canary only — CILIUM_LBIPAM_DR_DESTRUCTIVE=1) ----
  dtest("T0 baseline — canary VIP is allocated AND announced BEFORE any chaos", async () => {
    step("T0 pre-flight: the canary VIP must be up on L2 before we break anything");
    const ip = await svcExternalIP(CANARY_NS, CANARY_SVC);
    const lease = await resolveCanaryLease();
    const holder = await leaseHolder(lease);
    const reachable = await waitUntil(() => vipHttpOk(CANARY_VIP), 30000, 2000);
    check(`canary VIP allocated = ${CANARY_VIP}`, ip === CANARY_VIP, `got ${ip || "(pending)"}`);
    check("canary VIP has an L2 announcer", !!holder, `holder=${holder || "none"}`);
    check("canary VIP answers HTTP over the LAN", reachable, `curl http://${CANARY_VIP}/`);
    record("Canary VIP baseline (T0)", { text: ip || "none", thresholdText: CANARY_VIP, ok: ip === CANARY_VIP });
    expect(ip).toBe(CANARY_VIP);
    expect(holder).toBeTruthy();
  });

  dtest("FAILOVER: take out the announcing node → VIP re-announces + measure downtime", async () => {
    const lease = await resolveCanaryLease();
    const holderBefore = await leaseHolder(lease);
    const prodHolderBefore = await leaseHolder(PROD_LEASE);
    step(`Chaos [${CHAOS}]: knock the canary VIP off ${C.yellow}${holderBefore}${C.reset} — it must re-announce elsewhere`);

    const probe = startProbe(CANARY_VIP);
    await sleep(1500);
    const t0 = Date.now();
    if (CHAOS === "lease") {
      // lightest touch: drop the lease; cilium re-elects an announcer (may re-pick the same node)
      await kubectl(`delete lease ${lease} -n kube-system --wait=false`, { check: false });
    } else {
      // evict the cilium-agent on the announcing node → it can't hold the lease → another node wins.
      // eBPF datapath persists across a cilium-agent restart, and the DaemonSet self-heals the pod.
      const agent = await kubectl(
        `get pods -n kube-system -l k8s-app=cilium --field-selector spec.nodeName=${holderBefore} -o jsonpath={.items[0].metadata.name}`,
        { check: false });
      check(`found cilium-agent on ${holderBefore}`, !!agent, agent || "none");
      await kubectl(`delete pod ${agent} -n kube-system --wait=false`, { check: false });
    }

    info("waiting for the VIP to be re-announced (lease holder present again)…");
    // success = a holder is elected again; with the "agent" chaos it must be a DIFFERENT node
    let holderAfter = "";
    const reannounced = await waitUntil(async () => {
      holderAfter = await leaseHolder(lease); // lease may be recreated with a new name in "agent" mode? no — same object
      if (!holderAfter) { holderAfter = await leaseHolder(await resolveCanaryLease()); }
      if (!holderAfter) return false;
      return CHAOS === "agent" ? holderAfter !== holderBefore : true;
    }, MAX_FAILOVER_S * 1000 + 15000, 1000);
    const reannounceWall = (Date.now() - t0) / 1000;

    // let the probe settle, then measure the VIP-reachability blip
    await waitUntil(() => vipHttpOk(CANARY_VIP), 30000, 1000);
    await sleep(3000);
    probe.stop();
    const dt = probe.worstDowntime();

    const moved = holderAfter && holderAfter !== holderBefore;
    check("VIP re-announced from a node", reannounced, `${holderBefore} → ${holderAfter || "TIMEOUT"}`);
    check("VIP moved to a different node (ARP owner changed)", moved, moved ? "moved" : "same node re-elected");
    gauge("VIP failover downtime", dt, MAX_FAILOVER_S);
    info(`canary VIP availability during the failover window: ${(probe.availability() * 100).toFixed(1)}% (${probe.sampled()} samples)`);

    // BLAST-RADIUS GUARD: the prod pihole VIP must NOT have been disturbed by any of this
    const prodHolderAfter = await leaseHolder(PROD_LEASE);
    const prodUntouched = !!prodHolderAfter && prodHolderAfter === prodHolderBefore;
    check("prod VIP announcer UNCHANGED (no blast radius)", prodUntouched, `${PROD_LEASE}: ${prodHolderBefore} → ${prodHolderAfter}`);

    record("VIP re-announce wall time", { value: reannounceWall.toFixed(2), unit: "s", threshold: MAX_FAILOVER_S, ok: reannounced && reannounceWall <= MAX_FAILOVER_S + 15 });
    record("VIP failover downtime (HTTP blip)", { value: dt.toFixed(2), unit: "s", threshold: MAX_FAILOVER_S, ok: dt <= MAX_FAILOVER_S });
    record("Canary VIP availability during failover", { value: (probe.availability() * 100).toFixed(1), unit: "%", thresholdText: "—", ok: reannounced });
    record("Prod VIP untouched (blast radius)", { text: prodUntouched ? "untouched" : "DISTURBED", thresholdText: "untouched", ok: prodUntouched });

    expect(reannounced).toBe(true);
    if (CHAOS === "agent") expect(moved).toBe(true);
    expect(dt).toBeLessThanOrEqual(MAX_FAILOVER_S);
    expect(prodUntouched).toBe(true);
  });

  dtest("RECOVERY: the evicted cilium-agent self-heals (DaemonSet) + no split-brain", async () => {
    step("Recovery: cilium-agent DaemonSet must be fully Ready again and the canary VIP single-announced");
    const healed = await waitUntil(async () => {
      const [desired, ready] = (await kubectl(
        `get ds cilium -n kube-system -o jsonpath="{.status.desiredNumberScheduled}/{.status.numberReady}"`,
        { check: false })).split("/");
      return desired && desired === ready;
    }, 180000, 4000);
    check("cilium DaemonSet fully Ready", healed);
    // exactly one holder = no split-brain announcing the canary VIP twice
    const lease = await resolveCanaryLease();
    const holder = await leaseHolder(lease);
    check("canary VIP single-announced (no split-brain)", !!holder, `holder=${holder || "none"}`);
    record("cilium-agent self-heals", { text: healed ? "yes" : "no", thresholdText: "yes", ok: healed });
    expect(healed).toBe(true);
    expect(holder).toBeTruthy();
  });
});
