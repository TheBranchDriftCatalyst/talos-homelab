#!/usr/bin/env python3
"""Layer 3 — Ingress Accessibility: "what is reachable, from where, with what auth".

Offline by default (CI-safe, no cluster): renders the whole Flux tree and asserts ingress
invariants — the standing regression net for the 2026-09 ALPHA audit (TALOS-a8vo) and the prior
pentest (TALOS-lxz5, findings 001-019). Add --live for read-only accessibility probing from
in-cluster + LAN vantages.

Non-destructive envelope (mirrors test_security_posture.py): read-only GETs only; one synthetic
header set per probed host; no POST/PUT/DELETE; no rate-limit/body-cap exercise; probe pods are
--rm; probe UA is `crowdsec-posture-test` so the audit's own traffic is filterable.

  python3 scripts/security/test_ingress_accessibility.py           # offline contracts
  python3 scripts/security/test_ingress_accessibility.py --live    # + in-cluster + LAN probe
"""
import argparse
import os
import ssl
import sys
import unittest
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ingress_corpus as corpus
import ingress_allowlists as al

try:
    import pytest
    pytestmark = pytest.mark.ingress_accessibility  # suite tag
except ImportError:
    pass
LIVE = os.environ.get('POSTURE_LIVE') == '1'

# Admin / infra surfaces that must always be gated (auth or lan-only) on websecure, redirect-only on web.
SENSITIVE_HOSTS = {
    "traefik", "argocd", "grafana", "hubble", "crowdsec", "headlamp", "goldilocks",
    "kube-ops-view", "minio", "s3", "dbgate", "rabbitmq", "guacamole", "qbittorrent",
    "frigate", "homeassistant", "loki", "mimir", "tempo",
}
PUBLIC_SUFFIXES = ("knowledgedump.space", "amberdark.net")
AUTH_MW = {"authentik", "lan-only"}


def _corpus():
    if not hasattr(_corpus, "_c"):
        docs, meta = corpus.render()
        _corpus._c = (docs, meta, corpus.routes(docs), corpus.middleware_defs(docs))
    return _corpus._c


def _mw_names(route):
    return {name for _, name in route["middlewares"]}


# ───────────────────────────── OFFLINE CONTRACTS ─────────────────────────────
class IngressSurface(unittest.TestCase):
    """Offline invariants over the rendered corpus. Always runs (CI-safe, no cluster)."""

    @classmethod
    def setUpClass(cls):
        cls.docs, cls.meta, cls.routes, cls.mws = _corpus()

    # -- corpus integrity: without this, a broken renderer makes every contract pass vacuously --
    def test_corpus_is_complete(self):
        self.assertGreaterEqual(len(self.meta["built"]), 55,
                                f"only {len(self.meta['built'])} flux paths built — renderer broken?")
        irs = corpus.ingress_routes(self.docs)
        self.assertGreaterEqual(len(irs), 120, f"only {len(irs)} IngressRoutes rendered — renderer broken?")
        self.assertEqual(self.meta["failed"], [], f"kustomize build failures: {self.meta['failed']}")

    # A13 — every Flux Kustomization path exists (missing = permanently-failing + invisible to audit)
    def test_flux_kustomization_paths_exist(self):
        # applications/catalyst-llm is a known dead path (TALOS-a8vo P2); assert no NEW ones appear.
        known = {"applications/catalyst-llm"}
        unexpected = [p for p in self.meta["missing"] if p not in known]
        self.assertEqual(unexpected, [], f"Flux paths point at non-existent dirs: {unexpected}")

    # A1 — every middleware ref resolves (a dangling ref makes Traefik DROP the router → silent 404)
    def test_every_middleware_ref_resolves(self):
        dangling = []
        for r in self.routes:
            for ref in r["middlewares"]:
                # cross-provider refs like foo@kubernetescrd or @internal are not CRD Middlewares
                if "@" in ref[1]:
                    continue
                if ref not in self.mws:
                    dangling.append(f"{r['namespace']}/{r['name']} -> {ref[0]}/{ref[1]} ({r['src']})")
        self.assertEqual(dangling, [], "dangling middleware refs (router silently dropped): " + "; ".join(dangling))

    # A2 — every IngressRoute declares entryPoints (omission binds ALL entrypoints incl socks/proxy/bolt)
    def test_no_route_omits_entrypoints(self):
        missing = sorted({f"{r['namespace']}/{r['name']}" for r in self.routes
                          if r["kind"] == "IngressRoute" and not r["entryPoints"]})
        self.assertEqual(missing, [], f"IngressRoutes with no entryPoints (bind to ALL, incl proxy ports): {missing}")

    # A3 — no manifest combines web+websecure (mirrors the Kyverno policy; that admission guard has
    #      failurePolicy:Ignore + can't touch kube-system, so this repo-side check is the backstop).
    def test_no_combined_web_and_websecure(self):
        combined = sorted({f"{r['namespace']}/{r['name']}" for r in self.routes
                           if "web" in r["entryPoints"] and "websecure" in r["entryPoints"]})
        # two legacy redirect-only pairs predate the policy (TALOS-a8vo P2); assert no NEW ones.
        known = {"media-private/amber-legacy-5", "media-private/amber-legacy-private"}
        new = [c for c in combined if c not in known]
        self.assertEqual(new, [], f"NEW combined web+websecure routers (tls:{{}} injection breaks :80): {new}")

    # A4 — /api & /feed carve-outs at priority>0 must be gated OR justified in the allowlist
    def test_priority_api_carveouts_are_gated_or_allowlisted(self):
        offenders = []
        for r in self.routes:
            if r["priority"] <= 0:
                continue
            prefixes = corpus.path_prefixes_of(r["match"])
            if not any(p.startswith("/api") or p.startswith("/feed") for p in prefixes):
                continue
            if _mw_names(r) & AUTH_MW:
                continue
            key = (r["namespace"], r["name"])
            entry = al.API_CARVEOUT_ALLOWLIST.get(key)
            if entry and al.valid(entry):
                continue
            offenders.append(f"{r['namespace']}/{r['name']} match={r['match']!r} ({r['src']})")
        self.assertEqual(offenders, [], "un-gated /api|/feed carve-outs (pentest 005 class): " + "; ".join(offenders))

    # A5 — a header-trusting backend may NEVER hold an un-gated carve-out (allowlist can't override)
    def test_api_carveout_backends_do_not_trust_proxy_headers(self):
        bad = []
        for (ns, name) in al.API_CARVEOUT_ALLOWLIST:
            # host stem == service name in this repo's convention; check the backend name
            if name in al.HEADER_TRUSTING_BACKENDS:
                bad.append(f"{ns}/{name}")
        self.assertEqual(bad, [], f"header-trusting backends must not be carve-out-allowlisted: {bad}")

    # A6 — forward-auth middleware must have an authRequestHeaders allowlist (pentest 010).
    # Landed as expectedFailure: over-tight allowlist silently breaks SSO on ~47 routes; the safe
    # header set must be confirmed against a live outpost before enforcing. See TALOS-a8vo P1.
    @unittest.expectedFailure
    def test_forward_auth_has_auth_request_header_allowlist(self):
        mw = al  # placeholder to keep import
        fa = None
        for d in self.docs:
            if d.get("kind") == "Middleware" and d.get("metadata", {}).get("name") == "authentik" \
               and "forwardAuth" in d.get("spec", {}):
                fa = d["spec"]["forwardAuth"]
                break
        self.assertIsNotNone(fa, "authentik forwardAuth middleware not found in corpus")
        self.assertIn("authRequestHeaders", fa,
                      "forwardAuth has no authRequestHeaders allowlist — every client header forwarded to outpost")

    # A11 — lan-only must not admit the pod CIDR, OR every route relying on it alone is documented.
    def test_lan_only_does_not_admit_pod_cidr_or_is_documented(self):
        lan = None
        for d in self.docs:
            if d.get("kind") == "Middleware" and d.get("metadata", {}).get("name") == "lan-only":
                lan = d["spec"].get("ipAllowList", {}).get("sourceRange", [])
                break
        self.assertIsNotNone(lan, "lan-only middleware not found")
        admits_pod = any(c.strip() in ("10.0.0.0/8",) for c in lan)
        if not admits_pod:
            return  # fixed: pod CIDR excluded
        # still admits pod CIDR → every route relying on lan-only ALONE must be documented as perimeter-only
        undocumented = []
        for r in self.routes:
            names = _mw_names(r)
            if "lan-only" in names and not (names & (AUTH_MW - {"lan-only"})):
                key = (r["namespace"], r["name"])
                # only care about routes with a sensitive /api-ish path
                if any(p.startswith("/api") for p in corpus.path_prefixes_of(r["match"])):
                    if not al.valid(al.LAN_ONLY_PERIMETER_ONLY.get(key)):
                        undocumented.append(f"{r['namespace']}/{r['name']}")
        self.assertEqual(undocumented, [],
                         "lan-only admits pod CIDR (10.0.0.0/8) and these api-routes rely on it alone, "
                         f"undocumented: {undocumented}")

    # A12 — raw TCP proxy entrypoints (socks/httpproxy) must be source-restricted or accepted
    def test_tcp_proxy_routes_are_restricted_or_accepted(self):
        offenders = []
        for src, ir in corpus.ingress_routes(self.docs):
            if ir.get("kind") != "IngressRouteTCP":
                continue
            eps = ir.get("spec", {}).get("entryPoints", [])
            ns = ir.get("metadata", {}).get("namespace", "default")
            name = ir.get("metadata", {}).get("name", "?")
            if any(ep in ("socks", "httpproxy") for ep in eps):
                if not al.valid(al.OPEN_PROXY_ACCEPTED.get((ns, name))):
                    offenders.append(f"{ns}/{name} eps={eps} ({src})")
        self.assertEqual(offenders, [], "open TCP proxy entrypoints (pentest 008 — cluster pivot): " + "; ".join(offenders))


# ───────────────────────────── LIVE PROBE (--live) ─────────────────────────────
_PROBE = f"posture-probe-{uuid.uuid4().hex[:8]}"


def _status(url, headers=None, timeout=15):
    """Read-only GET returning HTTP status (or None if unreachable). ssl unverified, no proxy."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "crowdsec-posture-test"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                         urllib.request.HTTPSHandler(context=ctx))
    try:
        return opener.open(req, timeout=timeout).status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, OSError, ValueError):
        return None


class RunningIngressSurface(unittest.TestCase):
    """--live accessibility probe. Read-only. Skips entirely without --live."""

    def setUp(self):
        if not LIVE:
            self.skipTest("live probe: pass --live")

    # L1 — admin surfaces must never be openly 200 from the LAN vantage
    def test_live_admin_surfaces_not_open(self):
        docs, meta, routes, mws = _corpus()
        domain = corpus.cluster_vars().get("CLUSTER_DOMAIN", "talos00")
        checked = 0
        open_ = []
        for host in sorted(SENSITIVE_HOSTS):
            fqdn = f"{host}.{domain}"
            code = _status(f"https://{fqdn}/", headers={"Host": fqdn, "User-Agent": "crowdsec-posture-test"})
            if code is None:
                continue
            checked += 1
            if code == 200:
                open_.append(f"{fqdn}->{code}")
        self.assertGreater(checked, 0, "no admin surface was reachable — cluster/LAN unavailable?")
        self.assertEqual(open_, [], f"admin surfaces open (expect 401/403/404/redirect): {open_}")

    # L5 — forged identity header is stripped at the edge (positive control, pentest 010)
    def test_live_forged_identity_is_stripped(self):
        domain = corpus.cluster_vars().get("CLUSTER_DOMAIN", "talos00")
        fqdn = f"whoami.{domain}"
        # whoami echoes request headers; the probe token must NOT survive to the backend
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(f"https://{fqdn}/",
                                     headers={"Host": fqdn, "X-Authentik-Username": _PROBE,
                                              "User-Agent": "crowdsec-posture-test"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                             urllib.request.HTTPSHandler(context=ctx))
        try:
            body = opener.open(req, timeout=15).read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError) as e:
            self.skipTest(f"whoami unreachable: {e}")
        self.assertNotIn(_PROBE, body,
                         "forged X-Authentik-Username reached the backend — strip-authentik-headers not applied")


def _load(argv):
    global LIVE
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="run read-only live accessibility probes")
    args, rest = ap.parse_known_args(argv)
    LIVE = args.live
    return [sys.argv[0]] + rest


if __name__ == "__main__":
    sys.argv = _load(sys.argv[1:])
    unittest.main(verbosity=2)
