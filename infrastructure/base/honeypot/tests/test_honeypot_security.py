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
                                lateral movement / scanning / C2 / exfil. kube-dns:53 is the only
                                intended exception; the sample-fetch rule (public 80/443,
#                                all private ranges excepted) is the second sanctioned shape (#5).
  ingress reaches world         The inverse failure: if Cilium silently drops attacker traffic the
                                dashboard reads zero, indistinguishable from "no attacks".
  not-yet-exposed               Nothing in git should make this reachable before the operator
                                forwards the port themselves.
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


# Sanctioned egress shapes: (1) kube-dns:53; (2) public-only 0.0.0.0/0 on 80/443 with ALL private
# ranges excepted — the sample-fetch rule that lets cowrie capture the payloads attackers wget
# (#5). The invariant is NOT "no egress" but "egress that can never reach anything of ours".
_PRIVATE_PREFIXES = ("10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.2", "172.3",
                     "192.168.", "127.", "169.254.")
_SANCTIONED_PORTS = {"53", "80", "443"}
_REQUIRED_EXCEPTS = {"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16"}


def test_egress_is_dns_or_public_only_80_443():
    """Every permitted egress is kube-dns:53 OR public-only 80/443 with every private range excepted.
    Mutation check: drop an `except` CIDR from the sample-fetch rule (or add 10.0.0.0/8 to the allowed
    set) and this MUST go red — otherwise the honeypot can reach the LAN/API. (ported from the peer's
    egress-isolation test when honeypot tests moved Jest->pytest).

    OFFLINE by design: reads the CNP manifest directly so CI enforces the egress shape on every PR
    (a live-only check would be skipped in CI, where the regression is most likely to slip in)."""
    import glob
    import yaml
    cnps = []
    for path in glob.glob("infrastructure/base/honeypot/*.yaml"):
        with open(path) as fh:
            for doc in yaml.safe_load_all(fh):
                if isinstance(doc, dict) and doc.get("kind") == "CiliumNetworkPolicy":
                    cnps.append(doc)
    assert cnps, "no CiliumNetworkPolicy manifest found under infrastructure/base/honeypot/"
    violations = []
    for p in cnps:
        name = p["metadata"]["name"]
        for e in p.get("spec", {}).get("egress", []) or []:
            if len(e) == 0:
                continue  # the default-deny rule itself
            to_dns = any(t.get("matchLabels", {}).get("k8s-app") == "kube-dns"
                         for t in e.get("toEndpoints", []))
            if to_dns:
                continue
            cidr_sets = e.get("toCIDRSet", [])
            ports = [str(x.get("port")) for tp in e.get("toPorts", []) for x in tp.get("ports", [])]
            bad = [pt for pt in ports if pt not in _SANCTIONED_PORTS]
            if bad:
                violations.append(f"{name}: egress on non-sanctioned port(s) {bad}")
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
            if not cidr_sets and not to_dns:
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


def test_kubelet_probe_traffic_from_pod_cidr_permitted(cnps):
    pod_cidr = any(
        any(c.startswith("10.") for c in (i.get("fromCIDR") or []))
        for p in cnps for i in p.get("spec", {}).get("ingress", []) or [])
    assert pod_cidr, "pod-CIDR ingress not retained (liveness probes would break)"


# ── Exposure stays operator-controlled ─────────────────────────────────────
def test_no_in_cluster_resource_exposes_honeypot_publicly():
    dr.require_cluster()
    svcs = _get_json("get", "svc", "-n", NS)
    bad = []
    for s in (svcs or {}).get("items", []):
        if s.get("spec", {}).get("type") in ("LoadBalancer", "NodePort"):
            bad.append(f"{s['metadata']['name']} ({s['spec']['type']})")
        ann = s.get("metadata", {}).get("annotations", {}) or {}
        if any(k.startswith("external-dns.alpha.kubernetes.io") for k in ann):
            bad.append(f"{s['metadata']['name']} (external-dns annotation)")
    for kind in ("ingressroutetcp", "ingressroute"):
        r = _get_json("get", kind, "-n", NS)
        for item in (r or {}).get("items", []):
            bad.append(f"{item['metadata']['name']} ({kind})")
    assert bad == [], f"in-cluster resource(s) expose the honeypot (must come from router forward): {bad}"


def test_honeypot_ports_published_via_hostport(pod_spec):
    hp = [str(p.get("hostPort")) for c in pod_spec.get("containers", [])
          for p in c.get("ports", []) if p.get("hostPort")]
    assert SSH_PORT in hp, f"hostPort {SSH_PORT} not present (hostPorts: {hp or 'none'})"
