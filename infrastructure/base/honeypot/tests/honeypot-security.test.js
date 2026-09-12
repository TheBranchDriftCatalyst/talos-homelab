/**
 * Cowrie honeypot — security posture assertions  (TALOS-hg7)
 * ----------------------------------------------------------
 * This workload is DELIBERATELY BEING EXPOSED TO THE INTERNET. That is a considered decision,
 * not an accident. An SSH honeypot's entire premise is that attackers reach it and succeed at
 * logging in — so the thing standing between "useful sensor" and "attacker's beachhead inside
 * the LAN" is a small set of controls that are individually easy to regress and individually
 * silent when they do.
 *
 * This suite exists to make that regression loud.
 *
 * Every check is READ-ONLY. Nothing here restarts, patches, scales or deletes anything.
 *
 *   npm test -- --selectProjects honeypot-security
 *
 * Needs `kubectl` on PATH pointed at the cluster.
 *
 * ─────────────────────────────────────────────────────────────────────────────────────────
 * WHY EACH ASSERTION EXISTS — read this before "fixing" a failure by relaxing a test.
 *
 *   automountServiceAccountToken   A Kubernetes API token was found mounted into BOTH
 *                                  containers (2026-08-24). The `default` SA in this namespace
 *                                  carries 30 permission rows including cluster-scoped reads of
 *                                  kubevirt resources and `selfsubjectrulesreviews: create` —
 *                                  which hands an attacker a supported way to enumerate exactly
 *                                  what their stolen credential can do. Cowrie has no need for
 *                                  the API. Neither does a sidecar that tails a file.
 *
 *   egress is TIGHT, not zero    THE most important control here. It is what stops a
 *                                  compromised honeypot doing LATERAL MOVEMENT into the LAN,
 *                                  reaching our own services, or hitting the cluster API.
 *                                  Two exceptions are intended and ONLY two:
 *                                    - kube-dns:53 (name resolution)
 *                                    - 80/443 to the PUBLIC internet, with every RFC1918
 *                                      range + link-local EXCLUDED, so cowrie can fetch the
 *                                      malware samples an attacker wgets (TALOS honeypot
 *                                      sample capture) but can never reach anything of ours.
 *                                  The load-bearing invariant is the EXCLUSION, not the
 *                                  absence of egress. A rule that reaches a private range,
 *                                  the pod CIDR, the API, or a port other than 53/80/443 is
 *                                  a regression and these tests fail on it.
 *                                  ⚠️ Widening this (new port, a private range slipping back
 *                                  into the allowed set, toEntities:world without excepts) is
 *                                  handing reach to a machine you invited attackers into.
 *
 *   ingress reaches world          The inverse failure: if Cilium silently drops attacker
 *                                  traffic the dashboard reads zero, which is indistinguishable
 *                                  from "no attacks". The policy comment claimed external access
 *                                  while the rule listed only LAN CIDRs — that exact mismatch is
 *                                  what this catches.
 *
 *   not-yet-exposed                Until the operator forwards the port themselves, nothing in
 *                                  git should make this reachable. Guards against a
 *                                  well-meaning LoadBalancer/NodePort/IngressRoute landing
 *                                  early and exposing it before the hardening is verified.
 * ─────────────────────────────────────────────────────────────────────────────────────────
 */
const { execFile } = require("child_process");

// ---- config ---------------------------------------------------------------
const NS = process.env.HONEYPOT_NS || "honeypot";
const APP = process.env.HONEYPOT_APP || "cowrie";
const SSH_PORT = process.env.HONEYPOT_SSH_PORT || "2222";
const TELNET_PORT = process.env.HONEYPOT_TELNET_PORT || "2223";

// ---- pretty output --------------------------------------------------------
const C = {
  reset: "\x1b[0m", bold: "\x1b[1m", dim: "\x1b[2m",
  green: "\x1b[32m", red: "\x1b[31m", yellow: "\x1b[33m", cyan: "\x1b[36m", grey: "\x1b[90m",
};
const out = (s = "") => process.stdout.write(String(s) + "\n");
const step = (m) => out(`\n${C.bold}${C.cyan}▶ ${m}${C.reset}`);
const info = (m) => out(`   ${C.grey}${m}${C.reset}`);
const warn = (m) => out(`   ${C.yellow}⚠ ${m}${C.reset}`);
function check(label, ok, detail = "") {
  const mark = ok ? `${C.green}✓${C.reset}` : `${C.red}✗${C.reset}`;
  out(`   ${mark} ${label}${detail ? `  ${C.dim}${detail}${C.reset}` : ""}`);
  return ok;
}

// ---- kubectl helper -------------------------------------------------------
function kubectl(args) {
  return new Promise((resolve) => {
    execFile("kubectl", args, { timeout: 45000, maxBuffer: 32 * 1024 * 1024 }, (err, stdout, stderr) => {
      resolve({ ok: !err, stdout: (stdout || "").trim(), stderr: (stderr || "").trim() });
    });
  });
}
async function getJSON(args) {
  const r = await kubectl([...args, "-o", "json"]);
  if (!r.ok) return null;
  try { return JSON.parse(r.stdout); } catch { return null; }
}

// ---- shared state ---------------------------------------------------------
let deploy = null;
let podSpec = null;
let cnps = [];
let reachable = true;

beforeAll(async () => {
  const probe = await kubectl(["get", "ns", NS, "--no-headers"]);
  reachable = probe.ok;
  if (!reachable) {
    warn(`cluster not reachable (or namespace ${NS} missing) — checks will be skipped, not silently passed`);
    return;
  }
  deploy = await getJSON(["get", "deploy", "-n", NS, "-l", `app=${APP}`]);
  podSpec = deploy?.items?.[0]?.spec?.template?.spec ?? null;
  const c = await getJSON(["get", "ciliumnetworkpolicy", "-n", NS]);
  cnps = c?.items ?? [];
});

// A failure to reach the cluster must not read as a pass. Every test asserts this first.
function requireCluster() {
  if (!reachable) throw new Error(`cluster unreachable or namespace ${NS} missing — cannot verify posture`);
  if (!podSpec) throw new Error(`no Deployment matching app=${APP} in ${NS}`);
}

// ═══════════════════════════════════════════════════════════════════════════
describe("Kubernetes API credential must not be present", () => {
  test("automountServiceAccountToken is explicitly false", () => {
    requireCluster();
    step("Service-account token");
    const v = podSpec.automountServiceAccountToken;
    info(`serviceAccountName=${podSpec.serviceAccountName || "default"}  automount=${v === undefined ? "UNSET (defaults to true)" : v}`);
    const ok = v === false;
    check("automountServiceAccountToken === false", ok,
      ok ? "" : "an attacker escaping the fake shell would hold a live cluster credential");
    expect(v).toBe(false);
  });

  /**
   * ⚠️ THIS MUST INSPECT THE LIVE POD, NOT THE DEPLOYMENT TEMPLATE.
   *
   * The serviceaccount token is injected by the API server at POD CREATION — it does not
   * appear in the Deployment's pod template at all. An earlier version of this test read the
   * template and PASSED while a token was demonstrably mounted in both running containers.
   * That is the precise failure mode this whole suite exists to catch: a check that reports
   * healthy while the thing it claims to verify is false.
   */
  test("no serviceaccount token is mounted into ANY running container", async () => {
    requireCluster();
    const pods = await getJSON(["get", "pods", "-n", NS, "-l", `app=${APP}`]);
    const items = pods?.items || [];
    if (items.length === 0) throw new Error(`no running pods matching app=${APP} — cannot verify the live mount`);

    const offenders = [];
    for (const pod of items) {
      const all = [...(pod.spec.containers || []), ...(pod.spec.initContainers || [])];
      for (const c of all) {
        for (const m of c.volumeMounts || []) {
          if (m.mountPath && m.mountPath.startsWith("/var/run/secrets/kubernetes.io/serviceaccount")) {
            offenders.push(`${pod.metadata.name}/${c.name}`);
          }
        }
      }
      // The projected volume itself, even if nothing mounts it.
      for (const v of pod.spec.volumes || []) {
        const isSAToken = (v.projected?.sources || []).some((s) => s.serviceAccountToken);
        if (isSAToken) offenders.push(`${pod.metadata.name}/volume:${v.name}`);
      }
    }
    info(`inspected ${items.length} live pod(s)`);
    check("zero serviceaccount mounts in running containers", offenders.length === 0, offenders.join(", "));
    expect(offenders).toEqual([]);
  });
});

// ═══════════════════════════════════════════════════════════════════════════
describe("Egress lockdown — the control that prevents lateral movement", () => {
  test("a default-deny egress policy exists", () => {
    requireCluster();
    step("Egress posture");
    const deny = cnps.filter((p) => {
      const s = p.spec || {};
      const selEmpty = !s.endpointSelector || Object.keys(s.endpointSelector).length === 0;
      const egressEmptyRule = Array.isArray(s.egress) && s.egress.some((e) => Object.keys(e).length === 0);
      return selEmpty && egressEmptyRule;
    });
    check("default-deny-all egress policy present", deny.length > 0, deny.map((d) => d.metadata.name).join(", "));
    expect(deny.length).toBeGreaterThan(0);
  });

  // Egress is intentionally NON-ZERO: cowrie must fetch the payloads attackers wget, or
  // downloads/ stays empty and no samples are ever captured. The invariant is therefore
  // not "no egress" but "egress that can never reach anything of ours". Each permitted
  // rule is classified and anything outside the two sanctioned shapes fails.
  //
  // ⚠️ Mutation check for this test: delete any `except` CIDR from the sample-fetch rule,
  // or add "10.0.0.0/8" to the allowed set, and this MUST go red. If it stays green the
  // test has stopped protecting the LAN.
  const PRIVATE_RANGES = ["10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.2", "172.30.", "172.31.", "192.168.", "169.254.", "127."];
  const SANCTIONED_PORTS = new Set(["53", "80", "443"]);

  test("every permitted egress rule is either kube-dns:53 or public-only 80/443", () => {
    requireCluster();
    const violations = [];
    for (const p of cnps) {
      for (const e of p.spec?.egress || []) {
        if (Object.keys(e).length === 0) continue; // the default-deny rule itself

        // Shape 1: kube-dns.
        const toDNS = (e.toEndpoints || []).some((t) => t.matchLabels && t.matchLabels["k8s-app"] === "kube-dns");
        if (toDNS) continue;

        // Shape 2: CIDR-set egress. Must be public-only (0.0.0.0/0 WITH private excepts)
        // and restricted to sanctioned ports.
        const cidrSets = e.toCIDRSet || [];
        const ports = (e.toPorts || []).flatMap((tp) => (tp.ports || []).map((x) => String(x.port)));
        const badPort = ports.filter((pt) => !SANCTIONED_PORTS.has(pt));
        if (badPort.length) violations.push(`${p.metadata.name}: egress on non-sanctioned port(s) ${badPort.join(",")}`);

        for (const set of cidrSets) {
          const cidr = set.cidr || "";
          const excepts = set.except || [];
          // A CIDR that is itself private is a direct LAN/API reach — never allowed.
          if (PRIVATE_RANGES.some((r) => cidr.startsWith(r))) {
            violations.push(`${p.metadata.name}: egress toCIDR ${cidr} is a PRIVATE range`);
            continue;
          }
          // 0.0.0.0/0 is only safe if every private range is excepted out of it.
          if (cidr === "0.0.0.0/0") {
            const required = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16"];
            const missing = required.filter((req) => !excepts.includes(req));
            if (missing.length) violations.push(`${p.metadata.name}: 0.0.0.0/0 egress is MISSING excepts ${missing.join(", ")} — reaches our own networks`);
          }
        }

        // Anything that is neither DNS nor a bounded CIDR-set rule (e.g. toEntities:world,
        // toEndpoints to arbitrary namespaces, toServices) is unclassified and denied here.
        if (!cidrSets.length && !toDNS) {
          violations.push(`${p.metadata.name}: unclassified egress rule ${JSON.stringify(e).slice(0, 140)}`);
        }
      }
    }
    for (const v of violations) warn(v);
    check("all egress is DNS or public-only 80/443 with private ranges excluded", violations.length === 0,
      violations.length ? "⚠️ an egress rule can reach our own networks — pivot risk" : "DNS + public sample-fetch only");
    expect(violations).toEqual([]);
  });

  test("the sample-fetch egress rule exists and excludes every private range", () => {
    requireCluster();
    // The positive assertion: sample capture depends on this rule being PRESENT. If it is
    // silently dropped, downloads/ goes empty again and this catches the regression the
    // same way the ingress test catches silently-dropped attacker traffic.
    let found = null;
    for (const p of cnps) {
      for (const e of p.spec?.egress || []) {
        const set = (e.toCIDRSet || []).find((c) => c.cidr === "0.0.0.0/0");
        const ports = (e.toPorts || []).flatMap((tp) => (tp.ports || []).map((x) => String(x.port)));
        if (set && (ports.includes("80") || ports.includes("443"))) found = { policy: p.metadata.name, set, ports };
      }
    }
    check("sample-fetch egress (public 80/443) present", !!found,
      found ? `${found.policy} ports ${found.ports.join("/")}` : "cowrie cannot fetch samples — downloads/ will stay empty");
    expect(found).not.toBeNull();
    for (const req of ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16"]) {
      check(`excludes ${req}`, found.set.except.includes(req));
      expect(found.set.except).toContain(req);
    }
  });

  test("no egress rule grants access to the Kubernetes API server", () => {
    requireCluster();
    const apiRules = [];
    for (const p of cnps) {
      for (const e of p.spec?.egress || []) {
        const blob = JSON.stringify(e);
        if (/kube-apiserver|toServices|"world"|"all"|"cluster"/.test(blob)) apiRules.push(p.metadata.name);
      }
    }
    check("zero apiserver-reaching egress rules", apiRules.length === 0, apiRules.join(", "));
    // Defence in depth: even with the token gone, nothing here should be able to reach the API.
    expect(apiRules).toEqual([]);
  });
});

// ═══════════════════════════════════════════════════════════════════════════
describe("Container hardening", () => {
  const podLevel = () => podSpec.securityContext || {};
  const containers = () => podSpec.containers || [];

  test("runs as a non-root user", () => {
    requireCluster();
    step("Container security context");
    const bad = containers().filter((c) => {
      const sc = { ...podLevel(), ...(c.securityContext || {}) };
      return sc.runAsUser === 0 || (sc.runAsUser === undefined && sc.runAsNonRoot !== true);
    });
    check("every container non-root", bad.length === 0, bad.map((c) => c.name).join(", "));
    expect(bad.map((c) => c.name)).toEqual([]);
  });

  test("privilege escalation is disabled", () => {
    requireCluster();
    const bad = containers().filter((c) => {
      const sc = { ...podLevel(), ...(c.securityContext || {}) };
      return sc.allowPrivilegeEscalation !== false;
    });
    check("allowPrivilegeEscalation false everywhere", bad.length === 0, bad.map((c) => c.name).join(", "));
    expect(bad.map((c) => c.name)).toEqual([]);
  });

  test("all Linux capabilities are dropped", () => {
    requireCluster();
    const bad = containers().filter((c) => {
      const caps = (c.securityContext || {}).capabilities || {};
      const drops = (caps.drop || []).map((d) => String(d).toUpperCase());
      return !drops.includes("ALL");
    });
    check("capabilities drop: [ALL]", bad.length === 0, bad.map((c) => c.name).join(", "));
    expect(bad.map((c) => c.name)).toEqual([]);
  });

  test("nothing runs privileged or with host namespaces", () => {
    requireCluster();
    const priv = containers().filter((c) => (c.securityContext || {}).privileged === true);
    check("no privileged containers", priv.length === 0, priv.map((c) => c.name).join(", "));
    // hostPort is expected and intentional here; hostNetwork/hostPID/hostIPC are NOT — they
    // would put an attacker directly on the node's namespaces.
    check("no hostNetwork / hostPID / hostIPC", !podSpec.hostNetwork && !podSpec.hostPID && !podSpec.hostIPC);
    expect(priv).toEqual([]);
    expect(!!podSpec.hostNetwork).toBe(false);
    expect(!!podSpec.hostPID).toBe(false);
    expect(!!podSpec.hostIPC).toBe(false);
  });

  test("seccomp is set to RuntimeDefault", () => {
    requireCluster();
    const bad = containers().filter((c) => {
      const sc = { ...podLevel(), ...(c.securityContext || {}) };
      const t = (sc.seccompProfile || {}).type;
      return t !== "RuntimeDefault" && t !== "Localhost";
    });
    check("seccompProfile RuntimeDefault", bad.length === 0, bad.map((c) => c.name).join(", "));
    expect(bad.map((c) => c.name)).toEqual([]);
  });
});

// ═══════════════════════════════════════════════════════════════════════════
describe("Ingress must actually reach the honeypot once exposed", () => {
  test("policy admits traffic from outside the LAN on the honeypot ports", () => {
    requireCluster();
    step("Ingress reachability");
    let admitsWorld = false;
    const seen = [];
    for (const p of cnps) {
      for (const i of p.spec?.ingress || []) {
        const blob = JSON.stringify(i);
        const ports = (i.toPorts || []).flatMap((tp) => (tp.ports || []).map((x) => String(x.port)));
        if (!ports.includes(SSH_PORT)) continue;
        seen.push(`${p.metadata.name}: ${(i.fromCIDR || i.fromEntities || []).join(",") || "?"}`);
        // Either fromEntities:[world] (idiomatic Cilium) or an explicit 0.0.0.0/0.
        if (/"world"/.test(blob) || (i.fromCIDR || []).includes("0.0.0.0/0")) admitsWorld = true;
      }
    }
    for (const s of seen) info(s);
    check(`ingress admits world on :${SSH_PORT}`, admitsWorld,
      admitsWorld ? "" : "Cilium will silently DROP attacker traffic — dashboard will read zero and look like 'no attacks'");
    expect(admitsWorld).toBe(true);
  });

  test("kubelet probe traffic from the pod CIDR is still permitted", () => {
    requireCluster();
    const podCidr = cnps.some((p) =>
      (p.spec?.ingress || []).some((i) => (i.fromCIDR || []).some((c) => c.startsWith("10.")))
    );
    check("pod-CIDR ingress retained (liveness probes)", podCidr);
    expect(podCidr).toBe(true);
  });
});

// ═══════════════════════════════════════════════════════════════════════════
describe("Sample capture — persistence and safe archival", () => {
  /**
   * The honeypot now KEEPS what it captures. var/lib/cowrie holds downloads/ (real malware
   * samples, named by SHA-256) and tty/ (replayable sessions) — binary artifacts no log
   * pipeline carries. These were on an emptyDir and lost on every restart. The invariant
   * here: the capture volume is durable, and the copy that reaches SHARED storage does so
   * safely (read-only source, non-executable destination).
   */
  test("cowrie var/lib is a PersistentVolumeClaim, not an emptyDir", () => {
    requireCluster();
    step("Sample persistence");
    const vols = podSpec.volumes || [];
    const varlib = vols.find((v) => v.name === "cowrie-var-lib");
    info(`cowrie-var-lib -> ${varlib ? Object.keys(varlib).filter((k) => k !== "name")[0] : "MISSING"}`);
    check("cowrie-var-lib is a PVC", !!varlib?.persistentVolumeClaim,
      varlib?.emptyDir ? "still an emptyDir — captured samples and tty logs are lost on every restart" : "");
    expect(varlib?.persistentVolumeClaim).toBeTruthy();
  });

  test("an off-node archive CronJob exists and mounts the capture volume READ-ONLY", async () => {
    requireCluster();
    const cj = await getJSON(["get", "cronjob", "-n", NS]);
    const jobs = cj?.items || [];
    const archive = jobs.find((j) => /archive|backup/i.test(j.metadata.name));
    check("archive CronJob present", !!archive, archive ? archive.metadata.name : "no CronJob backs the samples off-node");
    expect(archive).toBeTruthy();

    const jspec = archive.spec.jobTemplate.spec.template.spec;
    // The source (honeypot volume) must be mounted read-only — the job must not be able to
    // write back into a volume an attacker can influence.
    const srcVol = (jspec.volumes || []).find((v) => v.persistentVolumeClaim?.claimName === "cowrie-var-lib");
    check("archive mounts cowrie-var-lib read-only", srcVol?.persistentVolumeClaim?.readOnly === true,
      "the job writing back into the honeypot volume would break the separation of privilege");
    expect(srcVol?.persistentVolumeClaim?.readOnly).toBe(true);

    // The archive job must itself hold no cluster credential.
    check("archive job has no service-account token", jspec.automountServiceAccountToken === false);
    expect(jspec.automountServiceAccountToken).toBe(false);

    // And it must be pinned to the same node as the RWO capture volume, or it silently
    // fails to mount and backs nothing up.
    const nodePin = jspec.nodeSelector?.["kubernetes.io/hostname"];
    const cowriePin = podSpec.nodeSelector?.["kubernetes.io/hostname"];
    check("archive job pinned to the cowrie node", !!nodePin && nodePin === cowriePin,
      `job=${nodePin} cowrie=${cowriePin} — a mismatch means the RWO volume never mounts`);
    expect(nodePin).toBe(cowriePin);
  });

  test("the archive StorageClass is mounted noexec/nosuid/nodev", async () => {
    requireCluster();
    // Samples are live malware. Whatever the archive PVC binds to must refuse execution.
    const pvcs = await getJSON(["get", "pvc", "-n", NS]);
    const archivePvc = (pvcs?.items || []).find((c) => /archive/i.test(c.metadata.name));
    if (!archivePvc) throw new Error("no archive PVC found — cannot verify mount hardening");
    const scName = archivePvc.spec.storageClassName;
    const sc = await getJSON(["get", "storageclass", scName]);
    const opts = sc?.mountOptions || [];
    info(`archive StorageClass ${scName} mountOptions: ${opts.join(",") || "none"}`);
    for (const req of ["noexec", "nosuid", "nodev"]) {
      check(`mountOption ${req}`, opts.includes(req),
        req === "noexec" ? "malware could be executed straight off the archive volume" : "");
      expect(opts).toContain(req);
    }
  });
});

// ═══════════════════════════════════════════════════════════════════════════
describe("Exposure stays operator-controlled", () => {
  /**
   * The operator forwards WAN:22 → node:2222 on the router themselves, deliberately. Nothing
   * in git should make this internet-reachable ahead of that — this test fails loudly if a
   * LoadBalancer, NodePort or ingress route lands early.
   */
  test("no in-cluster resource exposes the honeypot publicly", async () => {
    requireCluster();
    step("Exposure surface");
    const svcs = await getJSON(["get", "svc", "-n", NS]);
    const bad = [];
    for (const s of svcs?.items || []) {
      if (s.spec?.type === "LoadBalancer" || s.spec?.type === "NodePort") {
        bad.push(`${s.metadata.name} (${s.spec.type})`);
      }
      const ann = s.metadata?.annotations || {};
      if (Object.keys(ann).some((k) => k.startsWith("external-dns.alpha.kubernetes.io"))) {
        bad.push(`${s.metadata.name} (external-dns annotation)`);
      }
    }
    for (const kind of ["ingressroutetcp", "ingressroute"]) {
      const r = await getJSON(["get", kind, "-n", NS]);
      for (const item of r?.items || []) bad.push(`${item.metadata.name} (${kind})`);
    }
    for (const b of bad) warn(b);
    check("no LoadBalancer / NodePort / IngressRoute / external-dns", bad.length === 0,
      bad.length ? "exposure must come from the router forward, not from git" : "hostPort only, as intended");
    expect(bad).toEqual([]);
  });

  test("the honeypot ports are published via hostPort", async () => {
    requireCluster();
    const hp = (podSpec.containers || []).flatMap((c) => (c.ports || []).map((p) => p.hostPort)).filter(Boolean);
    info(`hostPorts: ${hp.join(", ") || "none"}`);
    check(`hostPort ${SSH_PORT} present`, hp.map(String).includes(SSH_PORT));
    expect(hp.map(String)).toContain(SSH_PORT);
  });
});
