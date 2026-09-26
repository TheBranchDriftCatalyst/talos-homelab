#!/usr/bin/env python3
"""Ingress exposure inventory — the reviewable basis for TALOS-a8vo.4.

WHY THIS EXISTS
a8vo.4's fix is to invert the Traefik entrypoint default from allow-all to lan-only
and exempt the genuinely-public routes. That is a one-line change with an enormous
blast radius: get the exemption list wrong and every public route dies, including
the Authentik outpost callbacks that gate everything else. So the exemption list has
to be derived, reviewable and re-derivable -- not assembled by hand once.

DETERMINISM
Renders the repo's Flux tree (never the live cluster) via ingress_corpus, sorts every
collection, and stamps the git SHA rather than a wall-clock time. Same commit in =>
byte-identical report out, so two runs can be diffed to see what a change did to the
exposure surface.

WHAT IT ADDS OVER THE EXISTING TEST LAYER
test_ingress_accessibility.py matches middleware names FLATLY (AUTH_MW = {"authentik",
"lan-only"}). 17 of the 53 middlewares in this repo are `chain`s, so a route protected
only via a chain reads as unguarded and a chain that contains no protection reads as
guarded. This expands chains recursively before classifying.

USAGE
    python3 tests/ingress-accessibility/generate_exposure_inventory.py
    ... --json out.json --markdown out.md      # explicit paths
    ... --stdout                               # print the report
"""
import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import ingress_corpus as corpus  # noqa: E402

try:
    import ingress_allowlists as allowlists
except Exception:  # the report still works without the registry
    allowlists = None

# Entrypoints reachable from outside the LAN. The a8vo.4 finding is that Traefik routes
# on the Host header REGARDLESS of entrypoint, and :80/:443 are WAN-forwarded -- so a
# route on these is Host-spoofable from the internet unless it carries an IP restriction.
WAN_ENTRYPOINTS = {"web", "websecure"}
# Deliberately LAN-scoped listeners (different ports, not WAN-forwarded).
LAN_ENTRYPOINTS = {"weblan", "websecurelan"}

# Middleware spec keys that constitute real protection, vs ones that only shape traffic.
PROTECTION_KINDS = {"forwardAuth": "sso", "ipAllowList": "ip-allowlist", "basicAuth": "basic-auth",
                    "digestAuth": "digest-auth"}
# A route whose ONLY middleware is a redirect is not "unguarded" in a meaningful sense:
# it never reaches a backend. Tracked separately so it cannot inflate the risk count.
REDIRECT_KINDS = {"redirectScheme", "redirectRegex"}

PATH_RE = re.compile(r"Path(?:Prefix|Regexp)?\(`([^`]+)`\)")
PUBLIC_TLD_RE = re.compile(r"\.[a-z]{2,}$", re.I)


def git_sha():
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=15).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def git_dirty():
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"],
                             capture_output=True, text=True, timeout=20).stdout
        return bool(out.strip())
    except Exception:
        return False


def build_middleware_index(docs):
    """{(ns, name): spec} for every Middleware in the corpus."""
    idx = {}
    for d in docs:
        if d.get("kind") == "Middleware":
            m = d.get("metadata", {})
            idx[(m.get("namespace", "default"), m.get("name"))] = d.get("spec", {}) or {}
    return idx


def expand(ref, idx, seen=None):
    """Recursively flatten a middleware ref into concrete (ns, name, spec-key) leaves.

    Chains are the whole reason this function exists -- see module docstring. Returns
    (leaves, missing, cyclic) where `missing` refs are load-bearing: Traefik DROPS a
    router whose middleware does not resolve, which presents as a silent 404 on a
    perfectly healthy backend. That is exactly how boomtime was down for five days.
    """
    seen = seen or set()
    if ref in seen:
        return [], [], [ref]
    seen = seen | {ref}
    spec = idx.get(ref)
    if spec is None:
        return [], [ref], []
    if "chain" in spec:
        leaves, missing, cyclic = [], [], []
        for m in spec["chain"].get("middlewares", []) or []:
            child = (m.get("namespace", ref[0]), m.get("name"))
            lv, ms, cy = expand(child, idx, seen)
            leaves += lv
            missing += ms
            cyclic += cy
        return leaves, missing, cyclic
    return [(ref[0], ref[1], k) for k in sorted(spec)], [], []


def accepted_for(ns, name):
    """Any documented exception covering this route, with its ticket."""
    if not allowlists:
        return []
    found = []
    for reg in ("NO_MIDDLEWARE_ALLOWLIST", "PUBLIC_CHAIN_ALLOWLIST", "API_CARVEOUT_ALLOWLIST",
                "LAN_ONLY_PERIMETER_ONLY", "OPEN_PROXY_ACCEPTED"):
        table = getattr(allowlists, reg, None) or {}
        for key, val in table.items():
            k = key[:2] if isinstance(key, tuple) and len(key) >= 2 else key
            if k == (ns, name):
                found.append({
                    "registry": reg,
                    "reason": getattr(val, "reason", str(val)),
                    "ticket": getattr(val, "ticket", ""),
                    "since": getattr(val, "since", getattr(val, "date", "")),
                })
    return sorted(found, key=lambda f: (f["registry"], f["reason"]))


def classify(route, idx):
    """One route -> a full exposure record."""
    ns, name = route["namespace"], route["name"]
    eps = sorted(route.get("entryPoints") or [])
    hosts = sorted(set(corpus.hosts_of(route.get("match", ""))))
    paths = sorted(set(PATH_RE.findall(route.get("match") or "")))

    leaves, missing, cyclic = [], [], []
    for ref in route.get("middlewares") or []:
        lv, ms, cy = expand(tuple(ref), idx)
        leaves += lv
        missing += ms
        cyclic += cy

    kinds = sorted({k for _, _, k in leaves})
    protections = sorted({PROTECTION_KINDS[k] for k in kinds if k in PROTECTION_KINDS})
    redirect_only = bool(kinds) and all(k in REDIRECT_KINDS for k in kinds)

    # Host-spoofable: on a WAN entrypoint, not IP-restricted, and actually serves content.
    on_wan = bool(set(eps) & WAN_ENTRYPOINTS)
    ip_restricted = "ip-allowlist" in protections
    authed = "sso" in protections or "basic-auth" in protections or "digest-auth" in protections
    wan_exposed = on_wan and not ip_restricted and not redirect_only

    # .talos00 hosts are LAN-intent by naming but are STILL Host-spoofable from the WAN;
    # that mismatch is the core of a8vo.4, so record intent separately from reachability.
    lan_intent = bool(hosts) and all(h.endswith(".talos00") for h in hosts)
    public_dns = sorted(h for h in hosts if not h.endswith(".talos00") and PUBLIC_TLD_RE.search(h))

    if missing:
        verdict = "BROKEN-ROUTER"       # Traefik drops it; silent 404
    elif redirect_only:
        verdict = "redirect-only"
    elif not protections:
        verdict = "UNGUARDED"
    elif ip_restricted and not authed:
        verdict = "lan-only"            # perimeter only; pod CIDR residue applies
    elif authed:
        verdict = "authenticated"
    else:
        verdict = "other-middleware"

    return {
        "namespace": ns, "name": name, "kind": route.get("kind"),
        "src": route.get("src"), "entryPoints": eps, "hosts": hosts, "paths": paths,
        "priority": route.get("priority", 0),
        "services": sorted(f"{s[0]}/{s[1]}:{s[2]}" for s in (route.get("services") or [])),
        "middlewares_declared": sorted(f"{r[0]}/{r[1]}" for r in (route.get("middlewares") or [])),
        "middleware_leaves": sorted({f"{a}/{b}:{c}" for a, b, c in leaves}),
        "missing_middlewares": sorted(set(f"{a}/{b}" for a, b in missing)),
        "cyclic_middlewares": sorted(set(f"{a}/{b}" for a, b in cyclic)),
        "protections": protections,
        "verdict": verdict,
        "wan_exposed": wan_exposed,
        "lan_intent_host": lan_intent,
        "public_dns_hosts": public_dns,
        "lan_only_alone": ip_restricted and not authed,
        "api_carveout": any(p.startswith("/api") for p in paths),
        "accepted": accepted_for(ns, name),
    }


def build(records):
    """Aggregates the report needs. Everything sorted for byte-stable output."""
    by_verdict = Counter(r["verdict"] for r in records)
    wan = [r for r in records if r["wan_exposed"]]
    undoc_wan = [r for r in wan if not r["accepted"] and r["verdict"] == "UNGUARDED"]
    return {
        "by_verdict": dict(sorted(by_verdict.items())),
        "wan_exposed": wan,
        "undocumented_unguarded_wan": undoc_wan,
        "broken_routers": [r for r in records if r["verdict"] == "BROKEN-ROUTER"],
        "lan_only_alone": [r for r in records if r["lan_only_alone"]],
        "api_carveouts": [r for r in records if r["api_carveout"] and not r["protections"]],
        "public_dns": sorted({h for r in records for h in r["public_dns_hosts"]}),
        "header_trusting_exposed": [
            r for r in records
            if allowlists and any(
                svc.split("/")[1].split(":")[0] in getattr(allowlists, "HEADER_TRUSTING_BACKENDS", set())
                for svc in r["services"]) and r["api_carveout"] and not r["protections"]],
    }


def markdown(records, agg, meta, sha, dirty):
    L = []
    A = L.append
    total = len(records)
    wan = agg["wan_exposed"]
    undoc = agg["undocumented_unguarded_wan"]

    A("# Ingress Exposure Inventory")
    A("")
    A(f"**Source:** repo Flux tree at `{sha}`" + ("  ⚠️ **working tree dirty**" if dirty else "") +
      f" · **Routes:** {total} · **Middlewares:** {meta.get('mw_count', '?')}")
    A("")
    A("Regenerate with `task test:ingress-inventory`. Deterministic: renders the repo (never the "
      "live cluster), sorts every collection, and stamps the commit rather than a timestamp — so "
      "two reports can be diffed to see what a change did to the exposure surface.")
    A("")

    # ---- headline ----
    A("## The number that matters")
    A("")
    A(f"**{len(undoc)}** routes are Host-spoofable from the WAN with **no protection and no "
      f"documented exception.** These are the ones the a8vo.4 fix has to either lock down or "
      f"explicitly exempt.")
    A("")
    A("| Verdict | Routes | Meaning |")
    A("|---|---:|---|")
    meanings = {
        "UNGUARDED": "no auth, no IP restriction — reaches a backend",
        "authenticated": "SSO / basic-auth in the chain",
        "lan-only": "IP allowlist only (perimeter; see pod-CIDR caveat)",
        "redirect-only": "never reaches a backend (http→https)",
        "BROKEN-ROUTER": "**middleware ref does not resolve — Traefik DROPS the router**",
        "other-middleware": "middleware present but none of it is protection",
    }
    for v, n in agg["by_verdict"].items():
        A(f"| `{v}` | {n} | {meanings.get(v, '')} |")
    A("")
    A(f"Of all {total} routes, **{len(wan)}** sit on a WAN entrypoint without an IP restriction. "
      f"Traefik matches on the `Host` header regardless of entrypoint and `:80`/`:443` are "
      f"WAN-forwarded, so a `.talos00` name is **not** a boundary — it is a naming convention.")
    A("")

    # ---- the deliverable ----
    A("## Exemption decision table")
    A("")
    A("The actual deliverable: every WAN-exposed unguarded route, with what it serves. Mark each "
      "**KEEP PUBLIC** or **LOCK DOWN** before the entrypoint default is inverted.")
    A("")
    A("| ns/name | hosts | paths | service | decision |")
    A("|---|---|---|---|---|")
    for r in sorted(undoc, key=lambda x: (x["namespace"], x["name"], x["hosts"])):
        hosts = "<br>".join(f"`{h}`" for h in r["hosts"]) or "_(no Host predicate)_"
        paths = ", ".join(f"`{p}`" for p in r["paths"]) or "—"
        svc = ", ".join(f"`{s}`" for s in r["services"]) or "—"
        A(f"| `{r['namespace']}/{r['name']}` | {hosts} | {paths} | {svc} | ☐ |")
    A("")

    # ---- risk flags ----
    A("## Risk flags")
    A("")
    if agg["broken_routers"]:
        A("### 🔴 Broken routers — Traefik drops these (silent 404 on a healthy backend)")
        A("")
        for r in agg["broken_routers"]:
            A(f"- `{r['namespace']}/{r['name']}` → unresolved: "
              f"{', '.join('`'+m+'`' for m in r['missing_middlewares'])}")
        A("")
    else:
        A("- ✅ No broken routers: every middleware reference resolves.")
    if agg["api_carveouts"]:
        A("")
        A("### ⚠️ Unprotected `/api` carve-outs")
        A("")
        A("A high-priority `/api` route with no auth serves the API to anyone who can reach the "
          "host — the TALOS-lxz5 class.")
        A("")
        for r in agg["api_carveouts"]:
            A(f"- `{r['namespace']}/{r['name']}` priority={r['priority']} "
              f"paths={', '.join(r['paths'])}")
    if agg["header_trusting_exposed"]:
        A("")
        A("### 🔴 Header-trusting backend behind an unprotected carve-out")
        A("")
        A("These map a proxy header to a user identity, so an un-gated carve-out is an "
          "authentication bypass, not just exposure.")
        A("")
        for r in agg["header_trusting_exposed"]:
            A(f"- `{r['namespace']}/{r['name']}` → {', '.join(r['services'])}")
    if agg["lan_only_alone"]:
        A("")
        A(f"### ⚠️ Relying on `lan-only` alone ({len(agg['lan_only_alone'])} routes)")
        A("")
        A("`lan-only` admits `10.0.0.0/8`, which contains the pod CIDR `10.244.0.0/16`. Off-LAN "
          "is blocked; **east-west is not**. Any pod in the cluster can reach these.")
        A("")
        for r in sorted(agg["lan_only_alone"], key=lambda x: (x["namespace"], x["name"]))[:25]:
            note = " _(documented)_" if r["accepted"] else ""
            A(f"- `{r['namespace']}/{r['name']}`{note}")
    A("")

    # ---- documented exceptions ----
    documented = sorted((r for r in records if r["accepted"]),
                        key=lambda x: (x["namespace"], x["name"]))
    A(f"## Documented exceptions ({len(documented)})")
    A("")
    A("Already justified in `ingress_allowlists.py`. These are candidates for **KEEP PUBLIC** — "
      "the reason and ticket are the audit trail.")
    A("")
    if documented:
        A("| ns/name | registry | ticket | reason |")
        A("|---|---|---|---|")
        for r in documented:
            for a in r["accepted"]:
                A(f"| `{r['namespace']}/{r['name']}` | {a['registry']} | `{a['ticket']}` | "
                  f"{a['reason'][:90]} |")
    else:
        A("_none_")
    A("")

    # ---- public DNS ----
    A("## Hosts on public DNS")
    A("")
    A("Names that are not `.talos00`. Each one is a name an outsider can resolve and therefore "
      "spoof a `Host` header for.")
    A("")
    A(", ".join(f"`{h}`" for h in agg["public_dns"]) or "_none_")
    A("")

    # ---- honesty ----
    A("## Coverage caveats")
    A("")
    A("Read these before treating the counts as complete.")
    A("")
    A("- **Flux-managed only.** This renders the repo's Flux tree. Routes managed by ArgoCD from "
      "sister repos (e.g. `arr-stack-private`) are **not** included — a live cluster count will "
      "be higher. `ingress_allowlists.DRIFT_ALLOWLIST` is the intended home for that delta.")
    if meta.get("missing"):
        A(f"- **{len(meta['missing'])} Flux path(s) referenced but absent** from the working tree: "
          f"{', '.join('`'+m+'`' for m in sorted(meta['missing'])[:6])}")
    if meta.get("failed"):
        A(f"- **{len(meta['failed'])} path(s) failed to render** and contribute no routes: "
          f"{', '.join('`'+str(f)+'`' for f in sorted(map(str, meta['failed']))[:6])}")
    A("- **Reachability is inferred from manifests, not probed.** It says what the config permits; "
      "it cannot prove what the WAN actually reaches. Confirming that needs an off-LAN vantage "
      "point, which is also why the a8vo.4 fix cannot be verified from the LAN.")
    A("- `lan-only` is treated as protection for WAN purposes and flagged separately for "
      "east-west, because it genuinely blocks off-LAN while genuinely admitting every pod.")
    A("")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Generate the ingress exposure inventory.")
    ap.add_argument("--json", default=str(ROOT / ".output" / "ingress-exposure-inventory.json"))
    ap.add_argument("--markdown", default=str(ROOT / ".output" / "ingress-exposure-inventory.md"))
    ap.add_argument("--stdout", action="store_true", help="print the markdown instead of writing")
    args = ap.parse_args()

    docs, meta = corpus.render()
    idx = build_middleware_index(docs)
    raw = corpus.routes(docs)
    records = sorted((classify(r, idx) for r in raw),
                     key=lambda r: (r["namespace"], r["name"], r["hosts"], r["paths"]))
    agg = build(records)
    meta = dict(meta or {})
    meta["mw_count"] = len(idx)
    sha, dirty = git_sha(), git_dirty()
    md = markdown(records, agg, meta, sha, dirty)

    if args.stdout:
        print(md)
    else:
        for path, payload in ((args.markdown, md),
                              (args.json, json.dumps(
                                  {"commit": sha, "dirty": dirty,
                                   "summary": agg["by_verdict"],
                                   "counts": {k: len(v) for k, v in agg.items()
                                              if isinstance(v, list)},
                                   "routes": records}, indent=2, sort_keys=True) + "\n")):
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(payload)
            print(f"  wrote {p.relative_to(ROOT) if str(p).startswith(str(ROOT)) else p}")

    print(f"  routes={len(records)} wan_exposed={len(agg['wan_exposed'])} "
          f"undocumented_unguarded_wan={len(agg['undocumented_unguarded_wan'])} "
          f"broken_routers={len(agg['broken_routers'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
