"""Cowrie honeypot — security posture assertions  (TALOS-hg7)

This workload is DELIBERATELY BEING EXPOSED TO THE INTERNET. An SSH honeypot's premise is that
attackers reach it and succeed at logging in — so a small set of individually-silent controls is
what stands between "useful sensor" and "attacker's beachhead inside the LAN". This suite makes a
regression of any of them loud.

Every check is READ-ONLY. Nothing here restarts, patches, scales or deletes anything. Checks SKIP
cleanly (never silently pass) when the cluster is unreachable or the honeypot namespace is absent.

Needs `kubectl` on PATH pointed at the cluster.

WHY EACH ASSERTION EXISTS — read before "fixing" a failure by relaxing a test:
  automountServiceAccountToken  A live API token was found mounted into BOTH containers
                                (2026-08-24); Cowrie has no need for the API.
  egress default-deny           THE most important control — stops a compromised honeypot doing
                                lateral movement / scanning / C2 / exfil. Three shapes are
                                sanctioned and nothing else: kube-dns:53; the sample-fetch rule
                                (public 80/443, all private ranges excepted, #5); and the named
                                in-cluster destinations in _SANCTIONED_IN_CLUSTER_EGRESS — each
                                one individually justified there, source AND destination.
  ingress reaches world         The inverse failure: if Cilium silently drops attacker traffic the
                                dashboard reads zero, indistinguishable from "no attacks".
  exposure is declared          Exposure must be DELIBERATE and visible in git. It used to come
                                from a hand-made router forward, so the rule was "nothing in git
                                may expose this". It now comes from the VIP Service declaring its
                                own WAN forward (unifi-port-forward annotation), so the rule is
                                "exactly that one declared Service, and nothing else".
"""
import json
import sys
from pathlib import Path

import pytest

# make `from lib import dr` resolve for this co-located suite regardless of how pytest is invoked
_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pytest.ini").exists())
sys.path.insert(0, str(_ROOT / "tests"))

from lib import dr  # noqa: E402

pytestmark = pytest.mark.security_posture

# ---- config (env-overridable, preserved from the Jest suite) ----
import os

NS = os.environ.get("HONEYPOT_NS", "honeypot")
APP = os.environ.get("HONEYPOT_APP", "cowrie")
SSH_PORT = os.environ.get("HONEYPOT_SSH_PORT", "2222")
TELNET_PORT = os.environ.get("HONEYPOT_TELNET_PORT", "2223")


def _get_json(*args):
    out = dr.kubectl(" ".join(args) + " -o json", check=False)
    try:
        return json.loads(out) if out else None
    except json.JSONDecodeError:
        return None


@pytest.fixture(scope="module")
def state():
    """Load the honeypot Deployment pod-spec + CiliumNetworkPolicies once for the whole suite."""
    dr.require_cluster()
    ns_present = bool(dr.kubectl(f"get ns {NS} -o name", check=False))
    if not ns_present:
        pytest.skip(f"namespace {NS} missing — cannot verify honeypot posture (skipped, not passed)")
    deploy = _get_json("get", "deploy", "-n", NS, "-l", f"app={APP}")
    pod_spec = None
    items = (deploy or {}).get("items", [])
    if items:
        pod_spec = items[0].get("spec", {}).get("template", {}).get("spec")
    cnp = _get_json("get", "ciliumnetworkpolicy", "-n", NS)
    cnps = (cnp or {}).get("items", [])
    return {"pod_spec": pod_spec, "cnps": cnps}


@pytest.fixture
def pod_spec(state):
    ps = state["pod_spec"]
    if ps is None:
        pytest.fail(f"no Deployment matching app={APP} in {NS}")
    return ps


@pytest.fixture
def cnps(state):
    return state["cnps"]


# ── Kubernetes API credential must not be present ──────────────────────────
def test_automount_service_account_token_is_false(pod_spec):
    v = pod_spec.get("automountServiceAccountToken")
    assert v is False, (
        "automountServiceAccountToken must be explicitly false — an attacker escaping the fake "
        f"shell would otherwise hold a live cluster credential (got {v!r})")


def test_no_serviceaccount_token_mounted_into_any_running_container():
    """MUST inspect the LIVE pod, not the Deployment template — the SA token is injected at pod
    creation and does not appear in the template."""
    dr.require_cluster()
    pods = _get_json("get", "pods", "-n", NS, "-l", f"app={APP}")
    items = (pods or {}).get("items", [])
    if not items:
        pytest.fail(f"no running pods matching app={APP} — cannot verify the live mount")
    offenders = []
    for pod in items:
        spec = pod["spec"]
        for c in [*spec.get("containers", []), *spec.get("initContainers", [])]:
            for m in c.get("volumeMounts", []):
                if str(m.get("mountPath", "")).startswith("/var/run/secrets/kubernetes.io/serviceaccount"):
                    offenders.append(f"{pod['metadata']['name']}/{c['name']}")
        for v in spec.get("volumes", []):
            if any(s.get("serviceAccountToken") for s in (v.get("projected") or {}).get("sources", [])):
                offenders.append(f"{pod['metadata']['name']}/volume:{v['name']}")
    assert offenders == [], f"serviceaccount token mounted in running container(s): {offenders}"


# ── Egress lockdown — the control that prevents lateral movement ───────────
def test_default_deny_egress_policy_exists(cnps):
    deny = []
    for p in cnps:
        s = p.get("spec", {})
        sel_empty = not s.get("endpointSelector") or len(s.get("endpointSelector", {})) == 0
        egress_empty_rule = isinstance(s.get("egress"), list) and any(
            len(e) == 0 for e in s["egress"])
        if sel_empty and egress_empty_rule:
            deny.append(p)
    assert len(deny) > 0, "no default-deny-all egress policy present"


# ── Sanctioned egress shapes ───────────────────────────────────────────────
# EXACTLY three shapes are permitted, and nothing else:
#   (1) kube-dns :53.
#   (2) public-only 0.0.0.0/0 on 80/443 with every private range excepted — the sample-fetch rule
#       that lets cowrie capture the payloads attackers wget (#5).
#   (3) a named in-cluster destination listed in _SANCTIONED_IN_CLUSTER_EGRESS below.
# The invariant is NOT "no egress" but "no egress that has not been individually signed off on".
_PRIVATE_PREFIXES = ("10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.2", "172.3",
                     "192.168.", "127.", "169.254.")
_PUBLIC_FETCH_PORTS = {"80", "443"}
_REQUIRED_EXCEPTS = {"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16"}

# Sanctioned IN-CLUSTER egress, keyed on (policy name, SOURCE endpointSelector, DESTINATION
# selector) -> the exact set of ports allowed to that destination.
#
# Keying on the SOURCE as well as the destination is deliberate: it is what stops an entry written
# for the haproxy front from silently sanctioning "cowrie may now reach crowdsec". Any edit to
# either selector changes the key and the rule becomes unsanctioned again — which is the point.
# Widening a cage has to be a reviewed diff to THIS table, not a quiet edit to a policy.
_SANCTIONED_IN_CLUSTER_EGRESS = {
    # haproxy front -> the two honeypots it proxies for. This IS the data path
    # (world -> VIP -> honeypot-lb -> cowrie/beelzebub); without it the trap is dark.
    # Wrong again if: the destination widens past {cowrie, beelzebub}, the ports widen past the
    # two honeypot listeners, or the source stops being the haproxy front.
    ("honeypot-lb", "app=honeypot-lb", "app In(beelzebub,cowrie)"): {"2222", "2223"},

    # haproxy's novelty-bouncer sidecar -> CrowdSec LAPI :8080 (TALOS-hdw8). Read-only decision
    # list; without it the bouncer fails open and is a no-op.
    # SCOPED TO THE honeypot-lb ENDPOINT ONLY. The honeypots themselves must NEVER gain a route
    # into the crowdsec namespace. Wrong again if: this destination ever appears under source
    # app=cowrie or app=beelzebub (that is the regression, not a formatting change), or the port
    # widens past the LAPI.
    ("honeypot-lb", "app=honeypot-lb",
     "k8s-app=crowdsec,k8s:io.kubernetes.pod.namespace=crowdsec,type=lapi"): {"8080"},

    # !!! BEELZEBUB -> CATALYST-LLM (LiteLLM :4000) — A REAL CLUSTER-REACH PATH FROM A
    # !!! COMPROMISED-BY-DESIGN WORKLOAD. Grep "catalyst-llm" in this file when auditing what the
    # !!! honeypot can touch; this is NOT meant to be a silent allowlist entry.
    # It is intentional and load-bearing: beelzebub asks the internal LLM to generate its fake
    # shell responses, which is the whole premise of that honeypot. It is also precisely the pivot
    # an attacker inside beelzebub would go looking for, so it is the one entry here that buys
    # capability rather than just preserving the cage.
    # Wrong again if: the port widens past 4000, the destination widens past the catalyst-llm
    # namespace, or cowrie/honeypot-lb acquire the same reach. Note the destination is a BARE
    # NAMESPACE selector, i.e. any pod in catalyst-llm — narrowing it to the LiteLLM pod labels is
    # the obvious hardening and would only require updating this key.
    ("beelzebub", "app=beelzebub", "k8s:io.kubernetes.pod.namespace=catalyst-llm"): {"4000"},
}

# Ingress/egress rule keys this suite knows how to classify. Anything else (toEntities, toCIDR,
# toServices, toFQDNs, toGroups...) is a shape nobody has reviewed, so it fails loudly rather than
# slipping through an `else` branch.
_KNOWN_EGRESS_KEYS = {"toEndpoints", "toCIDRSet", "toPorts"}


def _sel_key(selector):
    """Canonical, order-independent key for one Cilium endpoint selector.

    Any change to the labels/namespace/matchExpressions of a source or destination changes this
    string, so an allowlist keyed on it cannot be widened by editing a selector in place.
    """
    if not selector:
        return "*"  # empty selector == every endpoint
    parts = [f"{k}={v}" for k, v in sorted((selector.get("matchLabels") or {}).items())]
    for ex in selector.get("matchExpressions") or []:
        vals = ",".join(sorted(str(v) for v in (ex.get("values") or [])))
        parts.append(f"{ex.get('key')} {ex.get('operator')}({vals})")
    return ",".join(sorted(parts)) or "*"


def _dest_key(to_endpoints):
    return "|".join(sorted(_sel_key(t) for t in to_endpoints))


def _rule_ports(rule):
    return {str(x.get("port")) for tp in rule.get("toPorts", []) for x in tp.get("ports", [])}


def _honeypot_manifest_cnps():
    """Every CiliumNetworkPolicy in the honeypot manifests, read OFFLINE from the repo."""
    import yaml
    out = []
    for path in sorted((_ROOT / "infrastructure/base/security/honeypots").glob("*.yaml")):
        with open(path) as fh:
            for doc in yaml.safe_load_all(fh):
                if isinstance(doc, dict) and doc.get("kind") == "CiliumNetworkPolicy":
                    out.append(doc)
    return out


def test_egress_is_dns_public_80_443_or_explicitly_sanctioned():
    """Every permitted egress is kube-dns:53, public-only 80/443 with all private ranges excepted,
    or one of the individually sanctioned in-cluster destinations above.

    The intent is unchanged from when this was written: A HONEYPOT MUST NOT BE ABLE TO PIVOT INTO
    OUR NETWORKS. What changed is that the cage now has three legitimate in-cluster doors (the
    haproxy front reaching its backends, the novelty bouncer reading the CrowdSec LAPI, and
    beelzebub calling the internal LLM), none of which existed when this test was written. They are
    named explicitly rather than waved through with a blanket "in-cluster egress is fine" — a
    blanket exemption would delete this test's value.

    Mutation check: add a port to any rule, point a rule at a new namespace, move a sanctioned
    destination under a different source policy, or drop an `except` CIDR from the sample-fetch
    rule, and this MUST go red.

    OFFLINE by design: reads the CNP manifests directly so CI enforces the egress shape on every PR
    (a live-only check would be skipped in CI, where the regression is most likely to slip in)."""
    cnps = _honeypot_manifest_cnps()
    assert cnps, "no CiliumNetworkPolicy manifest found under infrastructure/base/security/honeypots/"
    violations = []
    for p in cnps:
        name = p["metadata"]["name"]
        src = _sel_key(p.get("spec", {}).get("endpointSelector"))
        for e in p.get("spec", {}).get("egress", []) or []:
            if len(e) == 0:
                continue  # the default-deny rule itself
            unknown = sorted(set(e) - _KNOWN_EGRESS_KEYS)
            if unknown:
                violations.append(
                    f"{name}: egress rule uses unreviewed selector(s) {unknown} — this suite cannot "
                    "prove it stays out of our networks")
                continue
            ports = _rule_ports(e)
            to_eps = e.get("toEndpoints", [])
            cidr_sets = e.get("toCIDRSet", [])

            if to_eps and cidr_sets:
                violations.append(f"{name}: egress rule mixes toEndpoints and toCIDRSet — split it "
                                  "so each destination is classifiable")
                continue

            if to_eps:
                if any(t.get("matchLabels", {}).get("k8s-app") == "kube-dns" for t in to_eps):
                    bad = sorted(ports - {"53"})
                    if bad:
                        violations.append(f"{name}: kube-dns egress on non-DNS port(s) {bad}")
                    continue
                dst = _dest_key(to_eps)
                allowed = _SANCTIONED_IN_CLUSTER_EGRESS.get((name, src, dst))
                if allowed is None:
                    violations.append(
                        f"{name}: UNSANCTIONED in-cluster egress [{src}] -> [{dst}] on {sorted(ports) or 'ALL PORTS'} "
                        "— add it to _SANCTIONED_IN_CLUSTER_EGRESS with a reason, or remove it")
                    continue
                if not ports:
                    violations.append(f"{name}: [{src}] -> [{dst}] has no toPorts, granting ALL ports "
                                      f"(sanctioned: {sorted(allowed)})")
                bad = sorted(ports - allowed)
                if bad:
                    violations.append(f"{name}: [{src}] -> [{dst}] on non-sanctioned port(s) {bad} "
                                      f"(sanctioned: {sorted(allowed)})")
                continue

            if cidr_sets:
                bad = sorted(ports - _PUBLIC_FETCH_PORTS)
                if bad:
                    violations.append(f"{name}: egress on non-sanctioned port(s) {bad}")
                if not ports:
                    violations.append(f"{name}: CIDR egress has no toPorts, granting ALL ports")
                for cset in cidr_sets:
                    cidr = cset.get("cidr", "")
                    excepts = set(cset.get("except", []))
                    if any(cidr.startswith(r) for r in _PRIVATE_PREFIXES):
                        violations.append(f"{name}: egress toCIDR {cidr} is a PRIVATE range")
                        continue
                    if cidr == "0.0.0.0/0":
                        missing = _REQUIRED_EXCEPTS - excepts
                        if missing:
                            violations.append(f"{name}: 0.0.0.0/0 egress MISSING excepts {sorted(missing)} — reaches our networks")
                continue

            violations.append(f"{name}: unclassified egress rule {json.dumps(e)[:140]}")
    assert violations == [], "egress can reach our own networks (pivot risk): " + "; ".join(violations)


def test_no_egress_grants_access_to_apiserver(cnps):
    import re
    api_rules = []
    for p in cnps:
        for e in p.get("spec", {}).get("egress", []) or []:
            if re.search(r'kube-apiserver|toServices|"world"|"all"|"cluster"', json.dumps(e)):
                api_rules.append(p["metadata"]["name"])
    assert api_rules == [], f"egress rule(s) reach the apiserver: {api_rules}"


# ── Container hardening ────────────────────────────────────────────────────
def _containers(pod_spec):
    return pod_spec.get("containers", [])


def _pod_level(pod_spec):
    return pod_spec.get("securityContext", {})


def test_runs_as_non_root(pod_spec):
    bad = []
    for c in _containers(pod_spec):
        sc = {**_pod_level(pod_spec), **(c.get("securityContext") or {})}
        if sc.get("runAsUser") == 0 or (sc.get("runAsUser") is None and sc.get("runAsNonRoot") is not True):
            bad.append(c["name"])
    assert bad == [], f"container(s) may run as root: {bad}"


def test_privilege_escalation_disabled(pod_spec):
    bad = []
    for c in _containers(pod_spec):
        sc = {**_pod_level(pod_spec), **(c.get("securityContext") or {})}
        if sc.get("allowPrivilegeEscalation") is not False:
            bad.append(c["name"])
    assert bad == [], f"allowPrivilegeEscalation not false on: {bad}"


def test_all_capabilities_dropped(pod_spec):
    bad = []
    for c in _containers(pod_spec):
        caps = (c.get("securityContext") or {}).get("capabilities") or {}
        drops = [str(d).upper() for d in caps.get("drop", [])]
        if "ALL" not in drops:
            bad.append(c["name"])
    assert bad == [], f"capabilities not dropped [ALL] on: {bad}"


def test_nothing_privileged_or_host_namespaces(pod_spec):
    priv = [c["name"] for c in _containers(pod_spec) if (c.get("securityContext") or {}).get("privileged") is True]
    assert priv == [], f"privileged container(s): {priv}"
    assert not pod_spec.get("hostNetwork"), "hostNetwork set"
    assert not pod_spec.get("hostPID"), "hostPID set"
    assert not pod_spec.get("hostIPC"), "hostIPC set"


def test_seccomp_runtime_default(pod_spec):
    bad = []
    for c in _containers(pod_spec):
        sc = {**_pod_level(pod_spec), **(c.get("securityContext") or {})}
        t = (sc.get("seccompProfile") or {}).get("type")
        if t not in ("RuntimeDefault", "Localhost"):
            bad.append(c["name"])
    assert bad == [], f"seccompProfile not RuntimeDefault on: {bad}"


# ── Ingress must actually reach the honeypot once exposed ──────────────────
def test_policy_admits_world_on_honeypot_ports(cnps):
    admits_world = False
    for p in cnps:
        for i in p.get("spec", {}).get("ingress", []) or []:
            blob = json.dumps(i)
            ports = [str(x.get("port")) for tp in i.get("toPorts", []) for x in tp.get("ports", [])]
            if SSH_PORT not in ports:
                continue
            if '"world"' in blob or "0.0.0.0/0" in (i.get("fromCIDR") or []):
                admits_world = True
    assert admits_world, (
        f"ingress does not admit world on :{SSH_PORT} — Cilium will silently DROP attacker "
        "traffic and the dashboard reads zero (looks like 'no attacks')")


# kubelet reaches a pod either as the node it runs on (Cilium entity "host") or, on the older
# spelling, from a 10.x node/pod CIDR. Both mean the same thing; the cage must admit one of them.
_NODE_LOCAL_ENTITIES = {"host", "remote-node"}


def _probe_ports():
    """Ports kubelet actually probes, resolved through named ports, from the live Deployments."""
    deploys = _get_json("get", "deploy", "-n", NS)
    out = set()
    for d in (deploys or {}).get("items", []):
        for c in d.get("spec", {}).get("template", {}).get("spec", {}).get("containers", []):
            by_name = {p.get("name"): p.get("containerPort") for p in c.get("ports", []) if p.get("name")}
            for probe in ("livenessProbe", "readinessProbe", "startupProbe"):
                handlers = c.get(probe) or {}
                for h in ("httpGet", "tcpSocket"):
                    port = (handlers.get(h) or {}).get("port")
                    if port is not None:
                        out.add(str(by_name.get(port, port)))
    return out


def test_kubelet_probe_traffic_is_admitted(cnps):
    """Liveness/readiness probes must not be blackholed by the cage.

    Intent unchanged — A PROBE THAT FAILS CLOSED RESTART-LOOPS A HEALTHY HONEYPOT, and a honeypot
    that is down looks exactly like a honeypot nobody is attacking. Only the MECHANISM moved: this
    used to require a `fromCIDR: 10.x` (pod/node CIDR) ingress rule; kubelet probe traffic is now
    expressed as `fromEntities: ["host"]` on the honeypot-lb policy for the dedicated :8404 health
    listener. "host" is the node the pod runs on, which is what kubelet actually is. Either
    spelling satisfies this; admitting NEITHER is the regression.

    Deliberately `any`, not `all`: cowrie's own liveness probe rides Cilium's implicit
    host->endpoint allowance rather than an explicit rule, so requiring every probe port to be
    named in a policy would fail on a configuration that works."""
    admitting = []
    for p in cnps:
        name = p["metadata"]["name"]
        for i in p.get("spec", {}).get("ingress", []) or []:
            ports = {str(x.get("port")) for tp in i.get("toPorts", []) for x in tp.get("ports", [])}
            node_local = set(i.get("fromEntities") or []) & _NODE_LOCAL_ENTITIES
            legacy_cidrs = [str(c) for c in (i.get("fromCIDR") or [])]
            legacy_cidrs += [str(cs.get("cidr", "")) for cs in (i.get("fromCIDRSet") or [])]
            if node_local or any(c.startswith("10.") for c in legacy_cidrs):
                admitting.append((name, ports))
    assert admitting, (
        "no ingress rule admits node-local kubelet probe traffic — neither fromEntities "
        f"{sorted(_NODE_LOCAL_ENTITIES)} nor a 10.x fromCIDR/fromCIDRSet. Probes fail closed and "
        "the honeypot is restart-looped into silence")
    probe_ports = _probe_ports()
    if probe_ports:
        covered = {pt for _, ports in admitting for pt in ports} & probe_ports
        assert covered, (
            f"node-local ingress exists but on none of the ports kubelet probes {sorted(probe_ports)} "
            f"(admitted: {[(n, sorted(pp)) for n, pp in admitting]}) — the probe still fails closed")


# ── Exposure stays deliberate and declared ─────────────────────────────────
# The ONE sanctioned public exposure is the honeypot VIP Service, and ONLY while it declares its
# own WAN forward in git via the UniFi port-forward operator's annotation (which replaced the
# standalone PortForwardRule CRD, itself a replacement for a hand-made router forward).
#
# Why the annotation is load-bearing to this test and not cosmetic: it is the whole reason a
# LoadBalancer in this namespace is allowed at all. With it, going public is a reviewable manifest
# diff. Without it, a LoadBalancer is either exposure by accident or a forward someone configured
# by hand on the router — the exact failure mode this design removed — so a VIP that loses the
# annotation MUST still fail here.
VIP_SVC = os.environ.get("HONEYPOT_VIP_SVC", "honeypot-vip")
PORT_FORWARD_ANNOTATION = "unifi-port-forward.fiskhe.st/mapping"


def test_no_in_cluster_resource_exposes_honeypot_publicly():
    """Exactly one declared exposure, and nothing else.

    Intent unchanged — EXPOSURE MUST BE DELIBERATE AND DECLARED, NEVER INCIDENTAL. Previously that
    meant "nothing in git may expose this" because exposure came from a hand-made router forward.
    Exposure is now declared in the repo on the VIP Service, so the assertion narrows to that one
    named Service carrying its mapping annotation. Every other LoadBalancer/NodePort, any
    external-dns annotation, and any IngressRoute/IngressRouteTCP still fails."""
    dr.require_cluster()
    svcs = _get_json("get", "svc", "-n", NS)
    bad = []
    for s in (svcs or {}).get("items", []):
        name = s["metadata"]["name"]
        typ = s.get("spec", {}).get("type")
        ann = s.get("metadata", {}).get("annotations", {}) or {}
        mapping = str(ann.get(PORT_FORWARD_ANNOTATION, "")).strip()
        if typ in ("LoadBalancer", "NodePort"):
            if not (name == VIP_SVC and typ == "LoadBalancer" and mapping):
                reason = (f"missing/empty {PORT_FORWARD_ANNOTATION} — an undeclared public Service"
                          if name == VIP_SVC
                          else f"only {VIP_SVC} may be public, and only by declaring its WAN forward")
                bad.append(f"{name} ({typ}) — {reason}")
        if any(k.startswith("external-dns.alpha.kubernetes.io") for k in ann):
            bad.append(f"{name} (external-dns annotation — a published DNS name is not part of this design)")
    for kind in ("ingressroutetcp", "ingressroute"):
        r = _get_json("get", kind, "-n", NS)
        for item in (r or {}).get("items", []):
            bad.append(f"{item['metadata']['name']} ({kind})")
    assert bad == [], (
        f"undeclared/incidental exposure of the honeypot (only {VIP_SVC} + "
        f"{PORT_FORWARD_ANNOTATION} is sanctioned): {bad}")


def test_honeypot_ports_published_via_vip_service():
    """The honeypot ports must ACTUALLY be published — now via the VIP Service, not hostPort.

    Same intent as the old hostPort assertion: IF THE PORTS ARE NOT REALLY PUBLISHED, THE TRAP IS
    DARK, and a dark trap is indistinguishable from "no attacks". The mechanism changed — hostPort
    2222/2223 on the cowrie pod was replaced by `honeypot-vip` (LoadBalancer) in front of the
    haproxy front — so this walks the current chain end to end:

        declared WAN forward -> a Service port that exists -> targeting the honeypot SSH port
        -> the VIP holds a LoadBalancer address -> the VIP has a ready backend.

    Break any link (rename a port, retarget it, lose the address, lose the backend) and this goes
    red. externalTrafficPolicy: Local makes the last link real: with no ready local endpoint the
    VIP stops being announced and WAN traffic is blackholed."""
    dr.require_cluster()
    svc = _get_json("get", "svc", VIP_SVC, "-n", NS)
    assert svc, f"Service {VIP_SVC} missing in {NS} — the honeypot is not published at all"
    assert svc.get("spec", {}).get("type") == "LoadBalancer", (
        f"{VIP_SVC} is {svc.get('spec', {}).get('type')!r}, not a LoadBalancer — the VIP is what "
        "publishes the honeypot ports")

    mapping = str((svc["metadata"].get("annotations") or {}).get(PORT_FORWARD_ANNOTATION, "")).strip()
    assert mapping, (
        f"{VIP_SVC} declares no WAN forward ({PORT_FORWARD_ANNOTATION}) — nothing routes the "
        "internet at the honeypot")
    ports_by_name = {p.get("name"): p for p in svc.get("spec", {}).get("ports", [])}
    forwarded_targets = {}
    for pair in mapping.split(","):
        wan, _, port_name = pair.strip().partition(":")
        assert port_name in ports_by_name, (
            f"WAN forward {pair!r} names Service port {port_name!r}, which {VIP_SVC} does not "
            f"define (ports: {sorted(n for n in ports_by_name if n)}) — the forward resolves to nothing")
        forwarded_targets[wan] = str(ports_by_name[port_name].get("targetPort"))
    assert SSH_PORT in forwarded_targets.values(), (
        f"no declared WAN forward reaches the honeypot SSH port {SSH_PORT} "
        f"(forwards {mapping!r} resolve to targetPort(s) {sorted(set(forwarded_targets.values()))})")

    ips = [i.get("ip") for i in (svc.get("status", {}).get("loadBalancer", {}).get("ingress") or [])
           if i.get("ip")]
    assert ips, f"{VIP_SVC} has no LoadBalancer address assigned — the VIP is not announced"

    slices = _get_json("get", "endpointslices", "-n", NS, "-l", f"kubernetes.io/service-name={VIP_SVC}")
    ready = [a for sl in (slices or {}).get("items", [])
             for ep in sl.get("endpoints", []) if (ep.get("conditions") or {}).get("ready")
             for a in ep.get("addresses", [])]
    assert ready, (
        f"{VIP_SVC} ({ips}) has no ready backend — externalTrafficPolicy: Local means the VIP "
        "stops being announced and every attacker connection is blackholed")
