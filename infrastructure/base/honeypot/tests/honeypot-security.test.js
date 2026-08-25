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
 *   egress default-deny            THE most important control here. It is what stops a
 *                                  compromised honeypot doing lateral movement, outbound
 *                                  scanning, C2, exfil, or becoming someone's DDoS node.
 *                                  kube-dns:53 is the only intended exception.
 *                                  ⚠️ If you are adding an egress rule, stop and think about
 *                                  what you are handing to a machine you invited attackers into.
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

  test("the ONLY egress permitted is kube-dns:53", () => {
    requireCluster();
    const allowed = [];
    for (const p of cnps) {
      for (const e of p.spec?.egress || []) {
        if (Object.keys(e).length === 0) continue; // the default-deny rule itself
        const toDNS = (e.toEndpoints || []).some(
          (t) => t.matchLabels && t.matchLabels["k8s-app"] === "kube-dns"
        );
        if (toDNS) continue;
        allowed.push(`${p.metadata.name}: ${JSON.stringify(e).slice(0, 120)}`);
      }
    }
    for (const a of allowed) warn(a);
    check("no egress beyond kube-dns", allowed.length === 0,
      allowed.length ? "⚠️ a public honeypot with outbound reach is a pivot point" : "");
    expect(allowed).toEqual([]);
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
