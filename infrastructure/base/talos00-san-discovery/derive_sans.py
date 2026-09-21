#!/usr/bin/env python3
"""Derive the talos00 certificate's SAN list from the cluster's own IngressRoutes.

Reads `kubectl get ingressroutes -A -o json` on stdin, prints a compact JSON
array on stdout, ready to be substituted into Certificate.spec.dnsNames.

WHY THIS EXISTS: a `*.talos00` wildcard is unusable on Apple platforms. macOS
and iOS reject a wildcard whose parent is a single label — the same rule that
forbids `*.com` — so Safari and Chrome on those devices report "Host name
mismatch" for every single-label host under it, no matter how thoroughly the CA
is trusted. Explicit SANs are the only fix, and hardcoding 65 hostnames would
rot immediately. So they are discovered.

The wildcard is KEPT alongside the explicit names: it still works for
non-Apple clients and covers any host that appears between refreshes.
"""
import json
import re
import sys

HOST_RE = re.compile(r"Host\(`([^`]+)`\)")
# Always present, independent of what is deployed.
ALWAYS = ["*.talos00", "talos00"]


def main() -> int:
    doc = json.load(sys.stdin)
    hosts = set()

    for item in doc.get("items", []):
        for route in (item.get("spec", {}).get("routes") or []):
            for host in HOST_RE.findall(route.get("match", "")):
                # Unresolved Flux placeholders can appear if we ever read from
                # git rather than the API; never put one in a certificate.
                if "${" in host or "*" in host:
                    continue
                # ONLY direct children of talos00 (sonarr.talos00), never
                # deeper names (apps.homepage.talos00, auth.priv.talos00).
                #
                # Deeper names already have dedicated wildcards
                # (*.homepage.talos00, *.priv.talos00, *.teak.talos00) and those
                # are LEGAL on Apple, because their parent is two labels. Only
                # `*.talos00` is rejected. Claiming those names here as well
                # would mean two certificates matching the same SNI host for no
                # benefit, so this stays strictly in its own lane.
                if host.endswith(".talos00") and host.count(".") == 1:
                    hosts.add(host)

    names = ALWAYS + sorted(hosts - set(ALWAYS))

    # Sorted and deduplicated so the output is STABLE. An unstable list would
    # rewrite the ConfigMap on every run, and every rewrite reissues the
    # certificate — churn that would eventually look like an outage.
    json.dump(names, sys.stdout, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
