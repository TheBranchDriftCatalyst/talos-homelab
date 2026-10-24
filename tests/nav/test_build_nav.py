"""build_nav.py applet discovery.

These specs exist because the applet loader was shipped (M1) and the applet
bundle was shipped and deployed (M2) while NOTHING emitted `applets` into the
manifest -- so the bundle was never injected into a single page, and every
component looked healthy in isolation. The gap was invisible precisely because
each side was individually correct.

The refusal specs matter more than the happy path: `applet-src` is an annotation
on an IngressRoute, so anyone who can annotate a route in any namespace can
propose a <script src> that the nav will inject into ~40 applications. The
client enforces the same rules (APPLET_URL_RULES in catalyst-nav.js); this layer
makes a bad value loud at build time instead of silently dropped in a browser.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "infrastructure/base/themepark/server/nav/build_nav.py"
)


def run(doc):
    """Drive the REAL script as the sidecar does: JSON on stdin, JSON on stdout.

    Deliberately a subprocess rather than an import: the sidecar's contract is
    stdin/stdout/exit-status, and a spec that imported discover_applets() would
    pass even if main() never called it -- which is the exact bug these specs
    are here to catch.
    """
    p = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(doc),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout), p.stderr


def route(name, annotations, ns="dev-overlay"):
    """A route as kubectl actually renders one."""
    return {
        "metadata": {"name": name, "namespace": ns, "annotations": annotations},
        "spec": {"routes": [{"match": "PathPrefix(`/catalyst/x/`)"}]},
    }


APPLET = "/catalyst/applets/dev-overlay/dev-overlay.js"


def test_applet_annotation_reaches_defaults_applets():
    """It must land on defaults.applets specifically.

    resolveConfig() reads DEFAULTS <- manifest.defaults <- manifest.hosts[h],
    and loadApplets() is called with cfg.applets. A top-level "applets" key
    would be valid JSON, would look right in the manifest, and would never be
    read by anything.
    """
    out, _ = run({"items": [route("r", {"catalyst.nav/applet-src": APPLET})]})
    assert out["defaults"]["applets"] == [{"src": APPLET}]


def test_applet_route_needs_no_gethomepage_annotations():
    """The applet has no page to visit, so it is not a nav entry.

    Its route carries no gethomepage.dev/* annotations at all and is skipped by
    the entry loop -- so discovery must be a separate pass. If it were a branch
    inside that loop this returns no applets.
    """
    out, _ = run({"items": [route("r", {"catalyst.nav/applet-src": APPLET})]})
    assert out["groups"] == []
    assert out["defaults"]["applets"] == [{"src": APPLET}]


def test_same_applet_on_both_entrypoints_is_emitted_once():
    """web + websecure are two objects carrying the same annotation.

    A duplicate would make the nav inject two <script> tags; the client
    deduplicates by src too, but shipping the duplicate would mean the manifest
    no longer describes what is intended.
    """
    out, _ = run({"items": [
        route("r-websecure", {"catalyst.nav/applet-src": APPLET}),
        route("r-web", {"catalyst.nav/applet-src": APPLET}),
    ]})
    assert out["defaults"]["applets"] == [{"src": APPLET}]


def test_no_applets_means_no_key_at_all():
    """An empty list must not be emitted.

    DEFAULTS.applets is already [] in the client, so an empty array here is pure
    noise in a file served to every app on every page load.
    """
    out, _ = run({"items": []})
    assert "applets" not in (out.get("defaults") or {})


@pytest.mark.parametrize("src,why", [
    ("//evil.example/x.js", "protocol-relative"),
    ("https://evil.example/x.js", "absolute or schemed"),
    ("javascript:alert(1)", "absolute or schemed"),
    ("data:text/javascript,alert(1)", "absolute or schemed"),
    # No literal ".." in this one on purpose: with both present the ".." rule
    # fires first and the percent rule would never be exercised at all.
    ("/catalyst/%2e%2e%2fx.js", "percent-encoded"),
    ("/catalyst/../../x.js", "contains .."),
    ("/catalyst/\\evil.example/x.js", "contains a backslash"),
    ("/assets/x.js", "outside /catalyst/"),
    ("", "not a non-empty string"),
])
def test_hostile_applet_src_is_refused_with_a_reason(src, why):
    """Each refusal names the attack it closes, and says so on stderr.

    Silence here would be the worst outcome: the operator annotated a route and
    got no applet and no explanation.
    """
    out, err = run({"items": [route("r", {"catalyst.nav/applet-src": src})]})
    assert "applets" not in (out.get("defaults") or {})
    assert why in err


def test_one_bad_applet_does_not_suppress_a_good_one():
    """A hostile annotation in some other namespace must not disarm discovery."""
    out, err = run({"items": [
        route("evil", {"catalyst.nav/applet-src": "https://evil.example/x.js"}, ns="other"),
        route("good", {"catalyst.nav/applet-src": APPLET}),
    ]})
    assert out["defaults"]["applets"] == [{"src": APPLET}]
    assert "absolute or schemed" in err


def test_applets_are_sorted_for_a_byte_stable_manifest():
    """The sidecar rewrites this file every 300s.

    Dict/iteration order would change the bytes without the cluster changing,
    which makes any future "has the nav changed?" check worthless.
    """
    a = "/catalyst/applets/aaa/a.js"
    z = "/catalyst/applets/zzz/z.js"
    out1, _ = run({"items": [route("r1", {"catalyst.nav/applet-src": z}),
                             route("r2", {"catalyst.nav/applet-src": a})]})
    out2, _ = run({"items": [route("r1", {"catalyst.nav/applet-src": a}),
                             route("r2", {"catalyst.nav/applet-src": z})]})
    assert out1["defaults"]["applets"] == out2["defaults"]["applets"]
    assert [e["src"] for e in out1["defaults"]["applets"]] == [a, z]


def test_existing_nav_entries_still_work():
    """A control. Applet discovery must not disturb the thing that already worked."""
    out, _ = run({"items": [{
        "metadata": {"name": "grafana", "namespace": "monitoring", "annotations": {
            "gethomepage.dev/enabled": "true",
            "gethomepage.dev/name": "Grafana",
            "gethomepage.dev/group": "Observability",
            "gethomepage.dev/href": "http://grafana.talos00",
        }},
        "spec": {"routes": [{
            "match": "Host(`grafana.talos00`)",
            "middlewares": [{"name": "catalyst-nav", "namespace": "traefik"}],
        }]},
    }]})
    names = [i["name"] for g in out["groups"] for i in g["items"]]
    assert "Grafana" in names


# ── the injected / themed classifier ─────────────────────────────────────────
# Untested until now, and it is load-bearing in a way that fails SILENTLY: a
# wrongly-classified app gets a dimmed nav entry promising a restyled
# destination that in fact keeps its own look. Nothing errors, nothing logs.
#
# It is also the specific regression an injected-applet composite could cause.
# `themed` is computed over middleware NAMES, so a middleware called
# catalyst-inject-<applet> — which starts with "catalyst-" and contains no
# "nav" — would flip every route carrying it to themed. That is exactly why the
# CatalystInjectedApplet composite mints no middleware at all, and these specs
# are what make that constraint enforceable rather than a comment.

def entry(middlewares, host="app.talos00", name="App"):
    """A nav-eligible route carrying the given middleware names."""
    return {
        "metadata": {"name": name.lower(), "namespace": "default", "annotations": {
            "gethomepage.dev/enabled": "true",
            "gethomepage.dev/name": name,
            "gethomepage.dev/group": "Group",
            "gethomepage.dev/href": f"http://{host}",
        }},
        "spec": {"routes": [{
            "match": f"Host(`{host}`)",
            "middlewares": [{"name": n, "namespace": "traefik"} for n in middlewares],
        }]},
    }


def only_item(out):
    items = [i for g in out["groups"] for i in g["items"]]
    assert len(items) == 1, items
    return items[0]


def test_nav_only_middleware_is_not_themed():
    """catalyst-nav adds the bar and leaves the app's own styling alone."""
    out, _ = run({"items": [entry(["catalyst-nav"])]})
    assert only_item(out)["themed"] is False


def test_per_app_full_theme_is_themed():
    out, _ = run({"items": [entry(["catalyst-sonarr"])]})
    assert only_item(out)["themed"] is True


def test_merged_nav_injector_is_not_themed():
    """catalyst-nav-rum-grafana merges the bar with a RUM tag in ONE rewriteBody,
    because chaining two is a silent no-op. Testing the exact string
    "catalyst-nav" instead of a substring would dim every such merged app."""
    out, _ = run({"items": [entry(["catalyst-nav-rum-grafana"])]})
    assert only_item(out)["themed"] is False


def test_a_hypothetical_catalyst_inject_middleware_would_wrongly_theme():
    """THE REGRESSION THIS GUARDS. If anything ever mints a middleware named
    catalyst-inject-<applet>, every route carrying it is classified as fully
    restyled. This spec asserts the misclassification so the consequence is
    visible and deliberate rather than discovered in the bar — and so a future
    fix to the classifier has a failing test to flip."""
    out, _ = run({"items": [entry(["catalyst-nav", "catalyst-inject-devoverlay"])]})
    assert only_item(out)["themed"] is True, (
        "if this now reports False the classifier was fixed — invert this spec"
    )


def test_shared_middlewares_alone_do_not_make_an_app_injected():
    """compress/accept-encoding/asset-cache ride along inside every chain, so
    counting them would make `injected` tautologically true."""
    out, _ = run({"items": [entry(["catalyst-compress", "catalyst-asset-cache"])]})
    assert out["groups"] == []


def test_an_app_with_no_catalyst_middleware_is_not_in_the_bar():
    out, _ = run({"items": [entry(["authentik"])]})
    assert out["groups"] == []
