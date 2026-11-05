#!/usr/bin/env bash
# Regenerate testdata/cluster-ingressroutes.json — the corpus the parity gate runs on.
#
# TWO SOURCES, and the difference between them matters.
#
#   --from-repo (default)  Every IngressRoute object committed under infrastructure/ and
#                          applications/. Reproducible, reviewable in a diff, and safe to run
#                          from a laptop with no cluster. This is what is committed.
#
#   --from-cluster         `kubectl get ingressroutes.traefik.io -A -o json`, i.e. exactly what
#                          discover.sh feeds build_nav.py. This is the AUTHORITATIVE corpus for
#                          phase 6's sign-off and the repo corpus is not a substitute for it.
#
# Why the repo corpus is not enough on its own: routes minted by a HelmRelease or by the
# catalyst-websecure-ingress Composition exist only in the cluster, never as YAML here, and the
# live set is larger than what this script can see from git. Phase 6 must diff against
# --from-cluster. The committed corpus is a regression net for the port, not the gate.
#
# Annotation note: gethomepage.dev/siteMonitor, /href and /widget.url are injected by the
# Kyverno homepage-annotation-derivation policy and so are absent from the repo corpus. That is
# harmless HERE because build_nav.py reads none of them — it reads enabled/name/group/weight
# and synthesises href as //<host>/ from the Host() rule. If the nav ever starts reading a
# Kyverno-derived annotation, the repo corpus stops being representative and this comment is
# the warning that it has.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
out="$here/cluster-ingressroutes.json"
mode=${1:---from-repo}

case "$mode" in
  --from-cluster)
    # Read-only. Still a cluster read, so it is NOT the default: a unit test must never
    # depend on a reachable apiserver.
    kubectl get ingressroutes.traefik.io -A -o json > "$out"
    ;;
  --from-repo)
    repo=$(cd "$here/../../../../.." && pwd)
    python3 - "$repo" "$out" << 'PY'
import json, os, sys

root, out = sys.argv[1], sys.argv[2]
items, seen = [], set()
for base in ("infrastructure", "applications"):
    for dirpath, _, files in os.walk(os.path.join(root, base)):
        for fn in sorted(files):
            if not fn.endswith((".yaml", ".yml")):
                continue
            try:
                import yaml
                docs = list(yaml.safe_load_all(open(os.path.join(dirpath, fn), encoding="utf-8")))
            except Exception:
                continue
            for d in docs:
                if not isinstance(d, dict) or d.get("kind") != "IngressRoute":
                    continue
                md = d.get("metadata")
                if not isinstance(md, dict):
                    continue
                name = md.get("name")
                # Crossplane composition templates carry patch placeholders, not names.
                if not isinstance(name, str) or not name or "{" in name:
                    continue
                key = (md.get("namespace") or "default", name)
                if key in seen:
                    continue
                seen.add(key)
                items.append(d)

# Sorted by (namespace, name) so a regenerated corpus diffs cleanly instead of reshuffling
# with the filesystem walk order.
items.sort(key=lambda d: (d["metadata"].get("namespace") or "default", d["metadata"]["name"]))
with open(out, "w", encoding="utf-8") as fh:
    json.dump({"apiVersion": "v1", "kind": "List", "items": items}, fh, indent=1, sort_keys=True)
    fh.write("\n")
sys.stderr.write("%d IngressRoute objects -> %s\n" % (len(items), out))
PY
    ;;
  *)
    echo "usage: $0 [--from-repo|--from-cluster]" >&2
    exit 2
    ;;
esac
