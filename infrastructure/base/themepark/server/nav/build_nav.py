#!/usr/bin/env python3
"""Turn a cluster's IngressRoutes into the Catalyst nav manifest.

Reads `kubectl get ingressroutes -A -o json` on stdin, writes JSON on stdout.

Every field is derived from annotations that already exist in this cluster:

    gethomepage.dev/enabled   opt-in; anything else is ignored entirely
    gethomepage.dev/name      display label
    gethomepage.dev/group     dropdown it belongs to
    gethomepage.dev/weight    sort order within the group
    gethomepage.dev/icon      reserved; not rendered yet

The host comes from the route's own Host(`...`) rule, and "themed" is true when
any route on that object references a middleware named theme-*. Nothing is
hardcoded, so the nav tracks the cluster automatically.
"""
import json
import os
import re
import sys

HOST_RE = re.compile(r"Host\(`([^`]+)`\)")
A = "gethomepage.dev/"


def main() -> int:
    doc = json.load(sys.stdin)
    entries = {}

    # Scope. Default lists only apps that actually carry Catalyst injection —
    # a DERIVED filter, not a list. Add the middleware to an app and it joins
    # the bar on the next refresh with nothing to edit here.
    # Set NAV_SCOPE=all to advertise every gethomepage.dev-enabled route.
    only_injected = os.environ.get("NAV_SCOPE", "themed").lower() != "all"

    for item in doc.get("items", []):
        meta = item.get("metadata", {})
        ann = meta.get("annotations") or {}
        if ann.get(A + "enabled") != "true":
            continue

        spec = item.get("spec", {})
        routes = spec.get("routes", []) or []

        # Two distinct questions, and conflating them emptied the nav once
        # already when middlewares were renamed:
        #
        #   injected — does this app carry ANY catalyst injection? That decides
        #              whether it belongs in the bar at all.
        #   themed   — does it carry a per-app FULL theme (catalyst-<slug>), as
        #              opposed to catalyst-nav which adds the bar and leaves the
        #              app's own styling alone? That decides whether the entry is
        #              dimmed, so it is visible up front that the destination
        #              will not look like where you came from.
        #
        # SHARED is excluded from both: those ride along inside every chain, so
        # counting them would make the test tautological.
        #
        # The prefix here and the names in middlewares.yaml must move together.
        SHARED = {"catalyst-compress", "catalyst-accept-encoding",
                  "catalyst-asset-cache"}
        names = {
            (mw.get("name") or "")
            for r in routes
            for mw in (r.get("middlewares") or [])
        } - SHARED
        injected = any(n.startswith("catalyst") for n in names)
        themed = any(n.startswith("catalyst-") and n != "catalyst-nav" for n in names)

        # Prefer a host from a plain route over one carrying a PathPrefix: the
        # asset route we add for the theme also matches Host(), and picking it
        # would be harmless but is less obviously the app's front door.
        host = None
        for prefer_plain in (True, False):
            for r in routes:
                match = r.get("match", "")
                if prefer_plain and "PathPrefix" in match:
                    continue
                m = HOST_RE.search(match)
                if m:
                    host = m.group(1)
                    break
            if host:
                break
        if not host:
            continue

        if only_injected and not injected:
            continue

        # Private/internal hostnames are reachable but not somewhere a nav
        # should send people by default.
        if ".priv." in host:
            continue

        name = ann.get(A + "name") or meta.get("name", host.split(".")[0]).title()
        group = ann.get(A + "group") or "Other"
        try:
            weight = int(ann.get(A + "weight") or 50)
        except ValueError:
            weight = 50

        # Deduplicate: several IngressRoutes can advertise the same host (an
        # http redirect companion alongside the real one). Keep the themed one.
        prev = entries.get(host)
        if prev and prev["themed"] and not themed:
            continue

        entries[host] = {
            "name": name,
            "group": group,
            "weight": weight,
            "href": f"//{host}/",
            "themed": themed,
        }

    grouped = {}
    for e in entries.values():
        grouped.setdefault(e["group"], []).append(e)

    groups = []
    for gname, items in grouped.items():
        items.sort(key=lambda x: (x["weight"], x["name"].lower()))
        # A group is themed if anything in it is; drives ordering below.
        groups.append({
            "name": gname,
            "items": [
                {k: v for k, v in i.items() if k != "group"} for i in items
            ],
        })

    # Groups with themed apps first (that is where you actually navigate),
    # then the rest alphabetically. Stable and derived, not a curated order.
    groups.sort(key=lambda g: (
        0 if any(i["themed"] for i in g["items"]) else 1,
        g["name"].lower(),
    ))

    json.dump({"groups": groups}, sys.stdout, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
