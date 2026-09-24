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

PER-APP BAR BEHAVIOUR is carried the same way, on the app's own route, so it
lives next to the annotations that already describe that app rather than in a
list of app names somewhere in the theme:

    catalyst.nav/mode           overlay | push | off
    catalyst.nav/reveal-at      px; overlay: how close to the top reveals it
    catalyst.nav/hide-past      px; overlay: how far down re-hides it
    catalyst.nav/height         px; bar height, also drives --catalyst-nav-h
    catalyst.nav/scroll-reveal  true | false
    catalyst.nav/intensity      0..n; amplitude of every animation in the
                                theme's layer 45. 1 is full, 0 is flat.
    catalyst.nav/fx             true | false; false removes the injected
                                atmosphere layers and stops all animation

These land in the manifest under `hosts`, keyed by hostname, and the script
resolves DEFAULTS <- defaults <- hosts[location.hostname]. Cluster-wide
defaults come from the NAV_DEFAULTS env var as a JSON object using the same
camelCase keys the script reads, e.g. NAV_DEFAULTS='{"revealAt":4}'.

An app with no catalyst.nav/* annotations contributes nothing to `hosts`, so
the common case costs zero bytes in the manifest.
"""
import json
import os
import re
import sys

HOST_RE = re.compile(r"Host\(`([^`]+)`\)")
A = "gethomepage.dev/"
NAV = "catalyst.nav/"


def _as_bool(v):
    return str(v).strip().lower() in ("true", "1", "yes", "on")


def _as_intensity(v):
    """0..n animation amplitude. Rejects negatives, NaN and inf.

    A negative value would not merely look wrong -- layer 45 multiplies
    translate distances by it, so every animation would run backwards, and
    `inf` would produce a transform the compositor cannot resolve.
    """
    n = float(v)
    if n != n or n in (float("inf"), float("-inf")) or n < 0:
        return None
    return n


# annotation suffix -> (manifest key, parser). ONE table: it validates the
# annotations, names the manifest keys, and documents the surface. The script's
# DEFAULTS object declares the same seven keys and nothing else, so anything
# not listed here can never reach it.
CONFIG_KEYS = {
    "mode": ("mode", lambda v: v if v in ("overlay", "push", "off") else None),
    "reveal-at": ("revealAt", int),
    "hide-past": ("hidePast", int),
    "height": ("height", int),
    "scroll-reveal": ("scrollReveal", _as_bool),
    "intensity": ("intensity", _as_intensity),
    "fx": ("fx", _as_bool),
}


def nav_config(ann):
    """Extract catalyst.nav/* into the manifest's camelCase config shape.

    A malformed value is DROPPED, never allowed to propagate: this JSON is
    consumed inside fourteen third-party apps, and a bad int there would throw
    in the host page rather than here where it is merely logged.
    """
    cfg = {}
    for suffix, (key, parse) in CONFIG_KEYS.items():
        raw = ann.get(NAV + suffix)
        if raw is None:
            continue
        try:
            val = parse(raw)
        except (TypeError, ValueError):
            val = None
        if val is None:
            print(f"[nav] ignoring {NAV}{suffix}={raw!r}", file=sys.stderr)
            continue
        cfg[key] = val
    return cfg


def env_defaults():
    """Cluster-wide defaults from NAV_DEFAULTS, filtered through the same table."""
    raw = os.environ.get("NAV_DEFAULTS", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        print(f"[nav] NAV_DEFAULTS is not valid JSON, ignoring: {raw!r}", file=sys.stderr)
        return {}
    if not isinstance(parsed, dict):
        print("[nav] NAV_DEFAULTS must be a JSON object, ignoring", file=sys.stderr)
        return {}
    allowed = {key for key, _ in CONFIG_KEYS.values()}
    return {k: v for k, v in parsed.items() if k in allowed}


def main() -> int:
    doc = json.load(sys.stdin)
    entries = {}
    host_cfg = {}

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

        # Collected AFTER the dedup check, so the surviving route for a host is
        # the one whose catalyst.nav/* annotations apply.
        cfg = nav_config(ann)
        if cfg:
            host_cfg[host] = cfg

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

    out = {"groups": groups}
    defaults = env_defaults()
    if defaults:
        out["defaults"] = defaults
    # Only hosts that actually made it into the nav — an annotation on a route
    # that was filtered out must not ship config for an app nobody can see.
    live = {h: c for h, c in host_cfg.items() if h in entries}
    if live:
        out["hosts"] = live

    json.dump(out, sys.stdout, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
