/**
 * VPN gateway/rotator — chaos/DR test  (companion to the Pi-hole DR suite)
 * -----------------------------------------------------------------------
 * Validates the gluetun + ProtonVPN rotator system: exit traffic goes through the VPN
 * (never the home WAN), rotation changes the exit IP WITHOUT restarting the consuming app
 * pods, the kill-switch holds when the tunnel drops (no leak), and it recovers.
 *
 * Read-only checks always run. DESTRUCTIVE scenarios (kill containers / force a rotation)
 * run only when   VPN_DR_DESTRUCTIVE=1   so they can't disrupt egress by accident.
 *
 *   (from repo root)  npm test                 # this + other suites, read-only
 *                     npm run test:dr          # include destructive chaos
 *   (this suite only) npm test -- --selectProjects vpn-dr
 *
 * Needs `kubectl` (context = the cluster) on PATH. Probes run through pods (the proxy is
 * in-cluster only). Exit-IP truth = actual egress (gluetun's control-API public_ip is empty).
 */
const { exec } = require("child_process");

// ---- config ---------------------------------------------------------------
const NS = process.env.VPN_NS || "vpn-gateway";
const PROXY = process.env.VPN_PROXY || "http://gluetun.vpn-gateway.svc.cluster.local:8080";
const HOME_WAN = process.env.VPN_HOME_WAN || "108.64.138.156"; // a home-WAN egress = LEAK
const DESTRUCTIVE = process.env.VPN_DR_DESTRUCTIVE === "1";
const MAX_ROTATION_DOWNTIME_S = parseFloat(process.env.VPN_MAX_ROTATION_S || "20");
const MAX_RECOVERY_S = parseFloat(process.env.VPN_MAX_RECOVERY_S || "90");
// exit surfaces (per-pod sidecars). gluetun-exporter (busybox) shares the pod netns + has wget.
const SIDECAR = { deploy: "securexng", probeContainer: "gluetun-exporter", vpnContainer: "gluetun" };

// ---- pretty output --------------------------------------------------------
const C = { reset: "\x1b[0m", bold: "\x1b[1m", dim: "\x1b[2m", green: "\x1b[32m", red: "\x1b[31m", yellow: "\x1b[33m", cyan: "\x1b[36m", grey: "\x1b[90m" };
const out = (s = "") => process.stdout.write(String(s) + "\n"); // bypass Jest console wrapping
const step = (m) => out(`\n${C.bold}${C.cyan}▶ ${m}${C.reset}`);
const info = (m) => out(`   ${C.grey}${m}${C.reset}`);
function check(label, ok, detail = "") {
  out(`   ${ok ? `${C.green}✓${C.reset}` : `${C.red}✗${C.reset}`} ${label}${detail ? `  ${C.dim}${detail}${C.reset}` : ""}`);
  return ok;
}
function gauge(label, value, threshold, unit = "s") {
  const ok = value <= threshold;
  check(label, ok, `${ok ? C.green : C.red}${value.toFixed(2)}${unit}${C.reset} ${C.dim}(≤ ${threshold}${unit})${C.reset}`);
  return ok;
}

// ---- measurements collector ----------------------------------------------
const METRICS = [];
const record = (name, m) => METRICS.push({ name, ...m });
function printSummary() {
  if (!METRICS.length) return;
  const pad = (s, n) => String(s).padEnd(n);
  out(`\n${C.bold}${C.cyan}════════════════ VPN DR TEST — MEASUREMENTS ════════════════${C.reset}`);
  out(`   ${C.dim}${pad("Metric", 42)}${pad("Measured", 10)}${pad("Threshold", 10)}Result${C.reset}`);
  out(`   ${C.dim}${"─".repeat(70)}${C.reset}`);
  for (const m of METRICS) {
    const meas = m.value !== undefined ? `${m.value}${m.unit || ""}` : m.text || "—";
    const thr = m.threshold !== undefined ? `≤ ${m.threshold}${m.unit || ""}` : m.thresholdText || "—";
    const mark = m.ok ? `${C.green}✓ PASS${C.reset}` : `${C.red}✗ FAIL${C.reset}`;
    out(`   ${pad(m.name, 42)}${m.ok ? C.green : C.red}${pad(meas, 10)}${C.reset}${C.dim}${pad(thr, 10)}${C.reset}${mark}`);
  }
  out(`   ${C.dim}${"─".repeat(70)}${C.reset}`);
  out(`   ${C.bold}${METRICS.filter((m) => m.ok).length}/${METRICS.length} metrics within threshold${C.reset}`);
  out(`${C.bold}${C.cyan}═══════════════════════════════════════════════════════════${C.reset}\n`);
}

// ---- shell / kubectl helpers ----------------------------------------------
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
const isPublicIPv4 = (ip) => /^\d+\.\d+\.\d+\.\d+$/.test(ip) && !/^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|127\.)/.test(ip);

async function waitUntil(fn, timeoutMs = 120000, intervalMs = 2000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) { try { if (await fn()) return true; } catch (_) {} await sleep(intervalMs); }
  return false;
}
async function firstPod(deploy) {
  return kubectl(`get pods -n ${NS} -l app=${deploy} -o jsonpath={.items[0].metadata.name}`, { check: false })
    .then((n) => n || kubectl(`get pods -n ${NS} -o name | grep ${deploy} | head -1 | cut -d/ -f2`, { check: false }));
}
async function restartCount(pod, container) {
  const n = await kubectl(`get pod ${pod} -n ${NS} -o jsonpath="{.status.containerStatuses[?(@.name=='${container}')].restartCount}"`, { check: false });
  return parseInt(n || "-1", 10);
}
async function podReady(pod) {
  return (await kubectl(`get pod ${pod} -n ${NS} -o jsonpath="{.status.conditions[?(@.type=='Ready')].status}"`, { check: false })) === "True";
}
// exit IP as seen THROUGH the shared HTTP proxy (throwaway curl pod — proxy is in-cluster only).
// Retries: VPN egress (routed via NL) can be slow/intermittent, so a single tight probe flakes.
async function proxyExitIP(tries = 3) {
  for (let i = 0; i < tries; i++) {
    const o = await kubectl(
      `run vpndr-${Date.now()} -n ${NS} --rm -i --restart=Never --image=curlimages/curl:8.10.1 --command -- ` +
      `curl -s --max-time 15 -x ${PROXY} https://api.ipify.org`, { check: false, timeout: 70000 });
    const m = o.match(IPV4); if (m) return m[1];
    await sleep(1500);
  }
  return "";
}
// exit IP from a pod's OWN netns (busybox wget in the exporter sidecar; http = busybox has no TLS)
async function podEgressIP(pod, container) {
  const o = await kubectl(`exec ${pod} -n ${NS} -c ${container} -- sh -c "wget -qO- --timeout=3 http://api.ipify.org 2>/dev/null || true"`, { check: false, timeout: 20000 });
  const m = o.match(IPV4); return m ? m[1] : "";
}
async function vpnRunning(pod) {
  const o = await kubectl(`exec ${pod} -n ${NS} -c gluetun -- sh -c "wget -qO- --timeout=5 http://localhost:8000/v1/vpn/status 2>/dev/null || true"`, { check: false, timeout: 20000 });
  return /running/.test(o);
}

// ---- ad-hoc canary (destructive chaos target — real services untouched) ----
const path = require("path");
const CANARY = "vpn-canary";
const CANARY_YAML = path.join(__dirname, "canary-pod.yaml");
// egress IP from the canary's OWN netns (busybox probe container; http = busybox has no TLS)
async function canaryEgressIP() {
  const o = await kubectl(`exec ${CANARY} -n ${NS} -c probe -- sh -c "wget -qO- --timeout=4 http://api.ipify.org 2>/dev/null || true"`, { check: false, timeout: 25000 });
  const m = o.match(IPV4); return m ? m[1] : "";
}
async function canaryTunnelUp() {
  const o = await kubectl(`exec ${CANARY} -n ${NS} -c gluetun -- sh -c "wget -qO- --timeout=5 http://localhost:8000/v1/vpn/status 2>/dev/null || true"`, { check: false, timeout: 20000 });
  return /running/.test(o);
}
async function createCanary() {
  await kubectl(`apply -f ${CANARY_YAML}`);
  await kubectl(`wait --for=condition=Ready pod/${CANARY} -n ${NS} --timeout=120s`, { check: false });
  await waitUntil(canaryTunnelUp, 120000, 4000);
  await waitUntil(async () => { const ip = await canaryEgressIP(); return isPublicIPv4(ip) && ip !== HOME_WAN; }, 120000, 4000);
}
const deleteCanary = () => kubectl(`delete pod ${CANARY} -n ${NS} --ignore-not-found --wait=false`, { check: false });
// rotate the canary to a different ProtonVPN country via ITS OWN control API (as the real rotator
// does). Belgium→India: both keys unused by real pods, so no duplicate-connection conflict.
async function rotateCanary() {
  const inKey = Buffer.from(await kubectl(`get secret protonvpn-credentials -n ${NS} -o jsonpath={.data.se-in-1}`, { check: false }), "base64").toString().trim();
  const ip = await kubectl(`get pod ${CANARY} -n ${NS} -o jsonpath={.status.podIP}`);
  const body = JSON.stringify({ wireguard: { private_key: inKey }, provider: { server_selection: { countries: ["India"] } } });
  await kubectl(`run rot-${Date.now()} -n ${NS} --rm -i --restart=Never --image=curlimages/curl:8.10.1 --command -- curl -s -X PUT --max-time 15 --data '${body}' http://${ip}:8000/v1/vpn/settings`, { check: false, timeout: 45000 });
}

const dtest = DESTRUCTIVE ? test : test.skip;

// ============================================================================
describe("VPN gateway — disaster recovery", () => {
  jest.setTimeout(300000);
  beforeAll(async () => {
    if (!DESTRUCTIVE) { step("read-only mode — set VPN_DR_DESTRUCTIVE=1 for chaos scenarios"); return; }
    step("Spinning up the ad-hoc VPN canary (chaos target — real services stay untouched)");
    await createCanary();
    info(`canary ${CANARY} ready; exit IP ${await canaryEgressIP()}`);
  }, 200000);
  afterAll(async () => { if (DESTRUCTIVE) await deleteCanary(); printSummary(); });

  test("gateway tunnel is up (gluetun control API)", async () => {
    step("Pre-flight");
    const pod = await firstPod("gluetun");
    const up = await vpnRunning(pod);
    check("gluetun VPN status = running", up, pod);
    record("Gateway tunnel up", { text: up ? "yes" : "no", thresholdText: "yes", ok: up });
    expect(up).toBe(true);
  });

  test("proxy egress is a VPN IP, NOT the home WAN (leak check)", async () => {
    const ip = await proxyExitIP();
    const ok = isPublicIPv4(ip) && ip !== HOME_WAN;
    check(`proxy exit IP = ${ip || "(none)"}`, ok, ip === HOME_WAN ? "!!! HOME WAN — LEAK" : `≠ home ${HOME_WAN}`);
    record("Proxy exit IP is VPN (not home WAN)", { text: ip || "none", thresholdText: `≠ ${HOME_WAN}`, ok });
    expect(ip).not.toBe(HOME_WAN);
    expect(isPublicIPv4(ip)).toBe(true);
  });

  test("secure-chrome is excluded from rotation (config invariant)", async () => {
    const rot = await kubectl(`get deploy secure-chrome -n ${NS} -o jsonpath="{.spec.template.metadata.labels.vpn-gateway\\.io/rotation}"`, { check: false });
    check("secure-chrome rotation label = disabled", rot === "disabled", `rotation=${rot}`);
    record("secure-chrome excluded from rotation", { text: rot, thresholdText: "disabled", ok: rot === "disabled" });
    expect(rot).toBe("disabled");
  });

  // --- stale-route (table 51820) regression guards [TALOS-4qwy] -----------------------------
  // History: stale WireGuard rules persist across an in-pod gluetun restart -> `ip rule add ...
  // file exists` -> crashloop (README: 257+ restarts). Fix = cleanup init (pod-create) + preStop
  // (graceful exit). We can't inject the ungraceful-crash path from kubectl (SIGTERM cleans up
  // gracefully; SIGKILL to PID 1 is kernel-blocked), so we guard the two observable invariants:
  // the cleanup must EXIST, and the crashloop symptom must be ABSENT.
  test("every gluetun pod carries the stale-route cleanup (init + preStop) [TALOS-4qwy]", async () => {
    step("Regression guard: table-51820 cleanup must exist on every gluetun workload");
    const deps = JSON.parse((await kubectl(`get deploy -n ${NS} -o json`, { check: false })) || '{"items":[]}');
    const gluetunDeps = deps.items.filter((d) => (d.spec.template.spec.containers || []).some((c) => c.name === "gluetun"));
    let allOk = gluetunDeps.length > 0;
    for (const d of gluetunDeps) {
      const spec = d.spec.template.spec;
      const initOk = (spec.initContainers || []).some((c) => JSON.stringify(c.command || "").includes("51820"));
      const g = spec.containers.find((c) => c.name === "gluetun");
      const preStopOk = !!(g.lifecycle && g.lifecycle.preStop);
      const ok = initOk && preStopOk;
      allOk = allOk && ok;
      check(`${d.metadata.name}: cleanup-init=${initOk} preStop=${preStopOk}`, ok);
    }
    record("gluetun pods have stale-route cleanup", { text: allOk ? `all ${gluetunDeps.length}` : "MISSING", thresholdText: "all", ok: allOk });
    expect(allOk).toBe(true);
  });

  test("no gluetun pod is crash-looping (stale-route symptom) [TALOS-4qwy]", async () => {
    step("Regression symptom: bounded gluetun restart rate (a table-51820 crashloop spikes it)");
    const MAX_RATE = parseFloat(process.env.VPN_MAX_RESTART_RATE || "5"); // restarts/day
    const pods = JSON.parse((await kubectl(`get pods -n ${NS} -o json`, { check: false })) || '{"items":[]}');
    let worst = 0, allOk = true, seen = 0;
    for (const p of pods.items) {
      const cs = (p.status.containerStatuses || []).find((c) => c.name === "gluetun");
      if (!cs) continue;
      seen++;
      const start = p.status.startTime ? new Date(p.status.startTime).getTime() : Date.now();
      const ageDays = Math.max((Date.now() - start) / 86400000, 1 / 24); // floor at 1h
      const rate = cs.restartCount / ageDays;
      const ok = rate < MAX_RATE;
      allOk = allOk && ok;
      worst = Math.max(worst, rate);
      check(`${p.metadata.name}: ${cs.restartCount} restarts / ${ageDays.toFixed(1)}d = ${rate.toFixed(2)}/day`, ok);
    }
    record("gluetun restart rate (worst pod)", { value: worst.toFixed(2), unit: "/day", threshold: MAX_RATE, ok: allOk });
    expect(seen).toBeGreaterThan(0);
    expect(allOk).toBe(true);
  });

  dtest("T0 baseline — canary egress is a VPN exit IP BEFORE any chaos", async () => {
    step("T0 pre-flight: canary must already be tunnelled out a VPN exit before we break anything");
    // retry the read — a single busybox wget over VPN egress can transiently time out even
    // though beforeAll already confirmed the tunnel is up.
    let ip = "";
    await waitUntil(async () => { const x = await canaryEgressIP(); if (isPublicIPv4(x) && x !== HOME_WAN) { ip = x; return true; } return false; }, 30000, 3000);
    const tunnelUp = await canaryTunnelUp();
    const vpnOk = isPublicIPv4(ip) && ip !== HOME_WAN;
    check("canary tunnel is up (control API = running)", tunnelUp);
    check("canary egress is a public VPN IP (not home WAN)", vpnOk, `${ip || "none"} ≠ ${HOME_WAN}`);
    record("Canary baseline egress (T0)", { text: ip || "none", thresholdText: `≠ ${HOME_WAN}`, ok: vpnOk });
    expect(tunnelUp).toBe(true);
    expect(vpnOk).toBe(true);
  });

  dtest("ROTATION does not disrupt the canary app container (exit IP changes, no restart)", async () => {
    const before = await canaryEgressIP();
    const rcBefore = await restartCount(CANARY, "probe");
    step(`Chaos: rotate the canary (was exit ${C.yellow}${before}${C.reset}); its 'app' container must NOT restart`);
    await rotateCanary();
    info("waiting for the new tunnel + exit IP…");
    // capture the confirmed IP INSIDE the wait — re-reading afterward can catch the tunnel
    // mid-flap (new server still stabilizing) and read empty.
    let after = "";
    await waitUntil(async () => { const ip = await canaryEgressIP(); if (isPublicIPv4(ip) && ip !== HOME_WAN) { after = ip; return true; } return false; }, 120000, 4000);
    const rcAfter = await restartCount(CANARY, "probe");
    const vpnOk = isPublicIPv4(after) && after !== HOME_WAN;
    const noRestart = rcAfter === rcBefore;
    check("exit IP still a VPN IP after rotation", vpnOk, `${before} → ${after}`);
    check("exit IP actually changed (rotated)", after !== before, after !== before ? "changed" : "same server");
    check("app container NOT restarted by rotation", noRestart, `restarts ${rcBefore} → ${rcAfter}`);
    record("Rotation keeps a VPN exit", { text: after || "none", thresholdText: `≠ ${HOME_WAN}`, ok: vpnOk });
    record("Rotation does NOT restart the app", { value: rcAfter - rcBefore, unit: " restarts", threshold: 0, ok: noRestart });
    expect(vpnOk).toBe(true);
    expect(noRestart).toBe(true);
  });

  dtest("KILL-SWITCH holds on the canary — no home-WAN leak when the tunnel drops", async () => {
    step("Chaos: kill the canary gluetun tunnel; app egress must NEVER be the home WAN");
    // kill gluetun PID 1 → container exits + restarts; the pod netns (kill-switch iptables) persists
    await kubectl(`exec ${CANARY} -n ${NS} -c gluetun -- sh -c "kill 1"`, { check: false });
    let leaked = false, samples = 0;
    for (let i = 0; i < 12; i++) {
      const ip = await canaryEgressIP(); // "" = blocked (good)
      samples++;
      if (ip === HOME_WAN) { leaked = true; info(`  ${C.red}LEAK: egress = ${ip}${C.reset}`); break; }
      await sleep(1000);
    }
    check("no home-WAN leak during tunnel outage", !leaked, `${samples} samples, leak=${leaked}`);
    record("Kill-switch: no home-WAN leak", { text: leaked ? "LEAK" : "held", thresholdText: "held", ok: !leaked });
    expect(leaked).toBe(false);
  });

  dtest("RECOVERY — canary VPN egress restored after the kill", async () => {
    step("Recovery: waiting for the canary tunnel + VPN exit IP to come back…");
    const t0 = Date.now();
    const recovered = await waitUntil(async () => {
      const ip = await canaryEgressIP();
      return isPublicIPv4(ip) && ip !== HOME_WAN;
    }, MAX_RECOVERY_S * 1000, 3000);
    const dt = (Date.now() - t0) / 1000;
    const restarts = await restartCount(CANARY, "gluetun");
    gauge("VPN egress recovery time", dt, MAX_RECOVERY_S);
    check("no crash-loop (restarts bounded)", restarts >= 0 && restarts < 10, `gluetun restarts=${restarts}`);
    record("VPN egress recovery time", { value: dt.toFixed(1), unit: "s", threshold: MAX_RECOVERY_S, ok: recovered });
    expect(recovered).toBe(true);
  });
});
