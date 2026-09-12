"""Rendered-manifest corpus for the ingress-accessibility test layer (Layer 3).

Do NOT glob raw YAML: kustomize patches (e.g. applications/homepage/overlays/*/patch-host.yaml)
parse in isolation as routes with no entryPoints and produce false findings. This module renders
every Flux Kustomization path with `kustomize build` (offline, ~2-3s) and flattens the result into
a route corpus the contracts assert against.

Design notes (see docs + TALOS-a8vo):
  - `kustomize build --load-restrictor LoadRestrictionsNone` — some overlays reference files above
    their own dir.
  - ${VAR} is substituted AFTER the build from the cluster-settings ConfigMap, leaving unknown vars
    intact (visible, not silently blanked).
  - PyYAML safe_load_all crashes on a rendered `- =` literal (yaml value tag); a tolerant Loader
    handles it.
  - A Middleware ref with no explicit namespace defaults to the IngressRoute's own namespace
    (Traefik CRD semantics).
"""
import os
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CLUSTER_DIR = ROOT / "clusters" / "catalyst-cluster"


class _Loader(yaml.SafeLoader):
    pass


# rendered manifests can contain a bare `- =` (yaml value tag) that SafeLoader rejects.
_Loader.add_constructor(
    "tag:yaml.org,2002:value", lambda loader, node: loader.construct_scalar(node)
)


def cluster_vars():
    """data{} of the cluster-settings ConfigMap (CLUSTER_DOMAIN: talos00, etc.)."""
    cm = CLUSTER_DIR / "cluster-settings.yaml"
    if not cm.is_file():
        return {}
    for doc in yaml.load_all(cm.read_text(), Loader=_Loader):
        if doc and doc.get("kind") == "ConfigMap" and doc.get("data"):
            return {str(k): str(v) for k, v in doc["data"].items()}
    return {}


def flux_paths():
    """Every spec.path from the kustomize.toolkit Kustomizations in clusters/catalyst-cluster/."""
    paths = []
    for f in sorted(CLUSTER_DIR.glob("*.yaml")):
        try:
            docs = list(yaml.load_all(f.read_text(), Loader=_Loader))
        except yaml.YAMLError:
            continue
        for d in docs:
            if not d or d.get("kind") != "Kustomization":
                continue
            api = d.get("apiVersion", "")
            if "kustomize.toolkit.fluxcd.io" not in api:
                continue
            p = d.get("spec", {}).get("path")
            if p:
                paths.append(p.lstrip("./"))
    return sorted(set(paths))


def _subst(text, variables):
    """Replace ${VAR} with cluster_vars value; leave unknown vars intact."""

    def repl(m):
        key = m.group(1)
        return variables.get(key, m.group(0))

    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", repl, text)


def render():
    """Render every existing Flux path. Returns (docs, meta).

    docs: list of parsed manifest dicts across the whole tree.
    meta: {'built': [...], 'missing': [...], 'failed': [(path, err)]}
    """
    variables = cluster_vars()
    docs = []
    meta = {"built": [], "missing": [], "failed": []}
    for p in flux_paths():
        d = ROOT / p
        if not d.is_dir():
            meta["missing"].append(p)
            continue
        try:
            out = subprocess.run(
                ["kustomize", "build", "--load-restrictor", "LoadRestrictionsNone", str(d)],
                capture_output=True, text=True, timeout=120,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            meta["failed"].append((p, str(e)))
            continue
        if out.returncode != 0:
            meta["failed"].append((p, out.stderr.strip().splitlines()[-1] if out.stderr else "build failed"))
            continue
        rendered = _subst(out.stdout, variables)
        try:
            for doc in yaml.load_all(rendered, Loader=_Loader):
                if isinstance(doc, dict) and doc.get("kind"):
                    doc.setdefault("_src", p)
                    docs.append(doc)
        except yaml.YAMLError as e:
            meta["failed"].append((p, f"yaml: {e}"))
            continue
        meta["built"].append(p)
    return docs, meta


def ingress_routes(docs):
    """[(src, doc)] for kind in IngressRoute / IngressRouteTCP / IngressRouteUDP."""
    kinds = {"IngressRoute", "IngressRouteTCP", "IngressRouteUDP"}
    return [(d.get("_src", "?"), d) for d in docs if d.get("kind") in kinds]


def middleware_defs(docs):
    """{(namespace, name)} for every rendered kind: Middleware."""
    out = set()
    for d in docs:
        if d.get("kind") == "Middleware":
            ns = d.get("metadata", {}).get("namespace", "default")
            out.add((ns, d["metadata"]["name"]))
    return out


def routes(docs):
    """Flattened per-route view.

    Returns list of dicts: {src, kind, namespace, name, entryPoints, match, priority,
    middlewares [(ns,name)], services [(ns,name,port)]}
    """
    flat = []
    for src, ir in ingress_routes(docs):
        meta = ir.get("metadata", {})
        ns = meta.get("namespace", "default")
        name = meta.get("name", "?")
        spec = ir.get("spec", {})
        eps = spec.get("entryPoints", [])
        annos = meta.get("annotations", {}) or {}
        for rt in spec.get("routes", []):
            mws = []
            for m in rt.get("middlewares", []) or []:
                mws.append((m.get("namespace", ns), m["name"]))
            svcs = []
            for s in rt.get("services", []) or []:
                svcs.append((s.get("namespace", ns), s.get("name", "?"), s.get("port")))
            flat.append({
                "src": src,
                "kind": ir.get("kind"),
                "namespace": ns,
                "name": name,
                "entryPoints": eps,
                "match": rt.get("match", rt.get("hostSNI", "")),
                "priority": rt.get("priority", 0),
                "middlewares": mws,
                "services": svcs,
                "annotations": annos,
            })
    return flat


_HOST_RE = re.compile(r"Host(?:SNI)?\(`([^`]+)`\)")


def hosts_of(match):
    """Extract Host(`x`) / HostSNI(`x`) values from a Traefik match string."""
    return _HOST_RE.findall(match or "")


_PATHPREFIX_RE = re.compile(r"PathPrefix\(`([^`]+)`\)")


def path_prefixes_of(match):
    return _PATHPREFIX_RE.findall(match or "")


if __name__ == "__main__":
    docs, meta = render()
    rs = routes(docs)
    irs = ingress_routes(docs)
    print(f"flux paths: built={len(meta['built'])} missing={meta['missing']} failed={[f[0] for f in meta['failed']]}")
    print(f"rendered docs: {len(docs)}")
    print(f"IngressRoute(+TCP/UDP): {len(irs)}  route-rules: {len(rs)}")
    hosts = sorted({h for r in rs for h in hosts_of(r['match'])})
    print(f"distinct hosts: {len(hosts)}")
