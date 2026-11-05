package navmodel

// Ported from tests/nav/test_build_nav.py, which is the behavioural spec for the nav model.
//
// WHAT CHANGED IN THE PORT, and why it is not a weakening: the Python specs drive the real
// script as a SUBPROCESS, and say so ("deliberately a subprocess rather than an import: the
// sidecar's contract is stdin/stdout/exit-status, and a spec that imported discover_applets()
// would pass even if main() never called it -- which is the exact bug these specs are here to
// catch"). That reasoning is about build_nav.py's shape, not about testing in general: the
// script had one entry point and no seam, so an import-level test could pass while the entry
// point ignored the function.
//
// Here the seam is Build(), which IS the entry point — the reconciler, the webhook and the
// `render` subcommand all go through it and have no other path to a manifest. The
// never-called-by-main failure mode is therefore closed by construction rather than by
// subprocess isolation. It is also still covered end-to-end: TestRenderMatchesBuildNavPy in
// cmd/catalyst-nav-operator runs the compiled binary against the real build_nav.py over a
// corpus of this cluster's actual IngressRoutes and compares bytes, which is a strictly
// stronger version of what the subprocess harness was buying.

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

// ── harness ──────────────────────────────────────────────────────────────────────────────

// run decodes a document the way the sidecar receives it and builds the model, returning the
// manifest plus whatever would have gone to stderr. Mirrors the Python `run()` helper.
func run(t *testing.T, doc string, opts ...func(*Options)) (*Manifest, string) {
	t.Helper()
	var d Doc
	if err := json.Unmarshal([]byte(doc), &d); err != nil {
		t.Fatalf("fixture is not valid JSON: %v", err)
	}
	var log bytes.Buffer
	o := Options{Log: &log}
	for _, f := range opts {
		f(&o)
	}
	return Build(&d, o), log.String()
}

// routeDoc mirrors the Python `route()` helper: a route as kubectl actually renders one,
// carrying only the given annotations and a PathPrefix match.
func routeDoc(entries ...string) string {
	return `{"items":[` + strings.Join(entries, ",") + `]}`
}

func appletRoute(name, src, ns string) string {
	return `{"metadata":{"name":"` + name + `","namespace":"` + ns + `","annotations":` +
		`{"catalyst.nav/applet-src":` + jsonStr(src) + `}},` +
		`"spec":{"routes":[{"match":"PathPrefix(` + "`/catalyst/x/`" + `)"}]}}`
}

// entryRoute mirrors the Python `entry()` helper: a nav-eligible route carrying the given
// middleware names.
func entryRoute(host, name string, middlewares ...string) string {
	mws := make([]string, 0, len(middlewares))
	for _, m := range middlewares {
		mws = append(mws, `{"name":"`+m+`","namespace":"traefik"}`)
	}
	return `{"metadata":{"name":"` + strings.ToLower(name) + `","namespace":"default","annotations":{` +
		`"gethomepage.dev/enabled":"true",` +
		`"gethomepage.dev/name":"` + name + `",` +
		`"gethomepage.dev/group":"Group",` +
		`"gethomepage.dev/href":"http://` + host + `"}},` +
		`"spec":{"routes":[{"match":"Host(` + "`" + host + "`" + `)","middlewares":[` +
		strings.Join(mws, ",") + `]}]}}`
}

func jsonStr(s string) string {
	b, _ := json.Marshal(s)
	return string(b)
}

// onlyItem asserts exactly one entry made it into the bar and returns it.
func onlyItem(t *testing.T, m *Manifest) Item {
	t.Helper()
	var items []Item
	for _, g := range m.Groups {
		items = append(items, g.Items...)
	}
	if len(items) != 1 {
		t.Fatalf("want exactly 1 item, got %d: %+v", len(items), items)
	}
	return items[0]
}

func applets(m *Manifest) []Applet {
	v, ok := m.Defaults.Get("applets")
	if !ok {
		return nil
	}
	a, _ := v.([]Applet)
	return a
}

const appletSrc = "/catalyst/applets/dev-overlay/dev-overlay.js"

// ── applet discovery ─────────────────────────────────────────────────────────────────────
// These specs exist because the applet loader was shipped (M1) and the applet bundle was
// shipped and deployed (M2) while NOTHING emitted `applets` into the manifest -- so the bundle
// was never injected into a single page, and every component looked healthy in isolation. The
// gap was invisible precisely because each side was individually correct.

func TestAppletAnnotationReachesDefaultsApplets(t *testing.T) {
	// It must land on defaults.applets specifically. resolveConfig() reads
	// DEFAULTS <- manifest.defaults <- manifest.hosts[h], and loadApplets() is called with
	// cfg.applets. A top-level "applets" key would be valid JSON, would look right in the
	// manifest, and would never be read by anything.
	m, _ := run(t, routeDoc(appletRoute("r", appletSrc, "dev-overlay")))
	got := applets(m)
	if len(got) != 1 || got[0].Src != appletSrc {
		t.Fatalf("defaults.applets = %+v, want one entry %q", got, appletSrc)
	}
	// Pin the placement in the BYTES too, which is what the Python spec's dict indexing
	// was really asserting.
	if !bytes.Contains(Encode(m), []byte(`"defaults":{"applets":[{"src":"`+appletSrc+`"}]}`)) {
		t.Fatalf("applets not under defaults in encoded manifest: %s", Encode(m))
	}
}

func TestAppletRouteNeedsNoGethomepageAnnotations(t *testing.T) {
	// The applet has no page to visit, so it is not a nav entry. Its route carries no
	// gethomepage.dev/* annotations at all and is skipped by the entry loop -- so discovery
	// must be a separate pass. If it were a branch inside that loop this returns no applets.
	m, _ := run(t, routeDoc(appletRoute("r", appletSrc, "dev-overlay")))
	if len(m.Groups) != 0 {
		t.Fatalf("groups = %+v, want empty", m.Groups)
	}
	if len(applets(m)) != 1 {
		t.Fatalf("applets = %+v, want one", applets(m))
	}
}

func TestSameAppletOnBothEntrypointsIsEmittedOnce(t *testing.T) {
	// web + websecure are two objects carrying the same annotation. A duplicate would make
	// the nav inject two <script> tags; the client deduplicates by src too, but shipping the
	// duplicate would mean the manifest no longer describes what is intended.
	m, _ := run(t, routeDoc(
		appletRoute("r-websecure", appletSrc, "dev-overlay"),
		appletRoute("r-web", appletSrc, "dev-overlay"),
	))
	if got := applets(m); len(got) != 1 {
		t.Fatalf("applets = %+v, want exactly one", got)
	}
}

func TestNoAppletsMeansNoKeyAtAll(t *testing.T) {
	// An empty list must not be emitted. DEFAULTS.applets is already [] in the client, so an
	// empty array here is pure noise in a file served to every app on every page load.
	m, _ := run(t, `{"items":[]}`)
	if _, present := m.Defaults.Get("applets"); present {
		t.Fatal("applets key present with no applets")
	}
	if got := string(Encode(m)); got != `{"groups":[]}` {
		t.Fatalf("encoded = %s, want {\"groups\":[]}", got)
	}
}

func TestHostileAppletSrcIsRefusedWithAReason(t *testing.T) {
	// Each refusal names the attack it closes, and says so on the log. Silence here would be
	// the worst outcome: the operator annotated a route and got no applet and no explanation.
	//
	// These matter more than the happy path: applet-src is an annotation on an IngressRoute,
	// so anyone who can annotate a route in any namespace can propose a <script src> that
	// the nav will inject into ~40 applications.
	cases := []struct{ src, why string }{
		{"//evil.example/x.js", "protocol-relative"},
		{"https://evil.example/x.js", "absolute or schemed"},
		{"javascript:alert(1)", "absolute or schemed"},
		{"data:text/javascript,alert(1)", "absolute or schemed"},
		// No literal ".." in this one on purpose: with both present the ".." rule fires
		// first and the percent rule would never be exercised at all.
		{"/catalyst/%2e%2e%2fx.js", "percent-encoded"},
		{"/catalyst/../../x.js", "contains .."},
		{`/catalyst/\evil.example/x.js`, "contains a backslash"},
		{"/assets/x.js", "outside /catalyst/"},
		{"", "not a non-empty string"},
	}
	for _, tc := range cases {
		t.Run(tc.why+"/"+tc.src, func(t *testing.T) {
			m, log := run(t, routeDoc(appletRoute("r", tc.src, "dev-overlay")))
			if _, present := m.Defaults.Get("applets"); present {
				t.Fatalf("hostile src %q reached the manifest", tc.src)
			}
			if !strings.Contains(log, tc.why) {
				t.Fatalf("log = %q, want it to name %q", log, tc.why)
			}
		})
	}
}

func TestOneBadAppletDoesNotSuppressAGoodOne(t *testing.T) {
	// A hostile annotation in some other namespace must not disarm discovery.
	m, log := run(t, routeDoc(
		appletRoute("evil", "https://evil.example/x.js", "other"),
		appletRoute("good", appletSrc, "dev-overlay"),
	))
	got := applets(m)
	if len(got) != 1 || got[0].Src != appletSrc {
		t.Fatalf("applets = %+v, want just the good one", got)
	}
	if !strings.Contains(log, "absolute or schemed") {
		t.Fatalf("log = %q, want the refusal reason", log)
	}
}

func TestAppletsAreSortedForAByteStableManifest(t *testing.T) {
	// The sidecar rewrites this file every 300s. Map/iteration order would change the bytes
	// without the cluster changing, which makes any future "has the nav changed?" check
	// worthless.
	a := "/catalyst/applets/aaa/a.js"
	z := "/catalyst/applets/zzz/z.js"
	m1, _ := run(t, routeDoc(appletRoute("r1", z, "dev-overlay"), appletRoute("r2", a, "dev-overlay")))
	m2, _ := run(t, routeDoc(appletRoute("r1", a, "dev-overlay"), appletRoute("r2", z, "dev-overlay")))
	if !bytes.Equal(Encode(m1), Encode(m2)) {
		t.Fatalf("input order changed the bytes:\n%s\n%s", Encode(m1), Encode(m2))
	}
	got := applets(m1)
	if len(got) != 2 || got[0].Src != a || got[1].Src != z {
		t.Fatalf("applets = %+v, want sorted [%s %s]", got, a, z)
	}
}

func TestExistingNavEntriesStillWork(t *testing.T) {
	// A control. Applet discovery must not disturb the thing that already worked.
	m, _ := run(t, `{"items":[{
		"metadata":{"name":"grafana","namespace":"monitoring","annotations":{
			"gethomepage.dev/enabled":"true",
			"gethomepage.dev/name":"Grafana",
			"gethomepage.dev/group":"Observability",
			"gethomepage.dev/href":"http://grafana.talos00"}},
		"spec":{"routes":[{
			"match":"Host(`+"`grafana.talos00`"+`)",
			"middlewares":[{"name":"catalyst-nav","namespace":"traefik"}]}]}}]}`)
	var names []string
	for _, g := range m.Groups {
		for _, i := range g.Items {
			names = append(names, i.Name)
		}
	}
	if len(names) != 1 || names[0] != "Grafana" {
		t.Fatalf("names = %v, want [Grafana]", names)
	}
}

// ── the injected / themed classifier ─────────────────────────────────────────────────────
// Load-bearing in a way that fails SILENTLY: a wrongly-classified app gets a dimmed nav entry
// promising a restyled destination that in fact keeps its own look. Nothing errors, nothing
// logs.

func TestNavOnlyMiddlewareIsNotThemed(t *testing.T) {
	// catalyst-nav adds the bar and leaves the app's own styling alone.
	m, _ := run(t, routeDoc(entryRoute("app.talos00", "App", "catalyst-nav")))
	if onlyItem(t, m).Themed {
		t.Fatal("catalyst-nav classified as a full theme")
	}
}

func TestPerAppFullThemeIsThemed(t *testing.T) {
	m, _ := run(t, routeDoc(entryRoute("app.talos00", "App", "catalyst-sonarr")))
	if !onlyItem(t, m).Themed {
		t.Fatal("catalyst-sonarr not classified as a full theme")
	}
}

func TestMergedNavInjectorIsNotThemed(t *testing.T) {
	// catalyst-nav-rum-grafana merges the bar with a RUM tag in ONE rewriteBody, because
	// chaining two is a silent no-op. Testing the exact string "catalyst-nav" instead of a
	// substring would dim every such merged app.
	m, _ := run(t, routeDoc(entryRoute("app.talos00", "App", "catalyst-nav-rum-grafana")))
	if onlyItem(t, m).Themed {
		t.Fatal("merged nav injector classified as a full theme")
	}
}

func TestAHypotheticalCatalystInjectMiddlewareWouldWronglyTheme(t *testing.T) {
	// THE REGRESSION THIS GUARDS. If anything ever mints a middleware named
	// catalyst-inject-<applet>, every route carrying it is classified as fully restyled.
	// This spec asserts the MISCLASSIFICATION so the consequence is visible and deliberate
	// rather than discovered in the bar -- and so a future fix to the classifier has a
	// failing test to flip.
	m, _ := run(t, routeDoc(entryRoute("app.talos00", "App", "catalyst-nav", "catalyst-inject-devoverlay")))
	if !onlyItem(t, m).Themed {
		t.Fatal("if this now reports false the classifier was fixed -- invert this spec")
	}
}

func TestSharedMiddlewaresAloneDoNotMakeAnAppInjected(t *testing.T) {
	// compress/accept-encoding/asset-cache ride along inside every chain, so counting them
	// would make `injected` tautologically true.
	m, _ := run(t, routeDoc(entryRoute("app.talos00", "App", "catalyst-compress", "catalyst-asset-cache")))
	if len(m.Groups) != 0 {
		t.Fatalf("groups = %+v, want empty", m.Groups)
	}
}

func TestAnAppWithNoCatalystMiddlewareIsNotInTheBar(t *testing.T) {
	m, _ := run(t, routeDoc(entryRoute("app.talos00", "App", "authentik")))
	if len(m.Groups) != 0 {
		t.Fatalf("groups = %+v, want empty", m.Groups)
	}
}

// ── behaviour the Python specs never covered ─────────────────────────────────────────────
// Everything below is NEW coverage of build_nav.py behaviour that tests/nav/test_build_nav.py
// left unpinned. It is all derived by reading the script, and every case here was verified
// against the real build_nav.py by TestRenderMatchesBuildNavPy's differential corpus -- so
// these assert the Python behaviour, not this port's opinion of it.

func TestScopeAllAdmitsUninjectedApps(t *testing.T) {
	// NAV_SCOPE=all is the documented escape hatch from the derived filter.
	m, _ := run(t, routeDoc(entryRoute("app.talos00", "App", "authentik")),
		func(o *Options) { o.ScopeAll = true })
	if onlyItem(t, m).Themed {
		t.Fatal("an uninjected app must still be unthemed under NAV_SCOPE=all")
	}
}

func TestPrivateHostnamesAreSkipped(t *testing.T) {
	// Reachable, but not somewhere a nav should send people by default.
	m, _ := run(t, routeDoc(entryRoute("app.priv.talos00", "App", "catalyst-nav")))
	if len(m.Groups) != 0 {
		t.Fatalf("groups = %+v, want empty for a .priv. host", m.Groups)
	}
	if len(m.Rejections) != 1 || m.Rejections[0].Reason != "PrivateHostname" {
		t.Fatalf("rejections = %+v, want one PrivateHostname", m.Rejections)
	}
}

func TestPlainRouteIsPreferredOverPathPrefix(t *testing.T) {
	// The asset route added for the theme also matches Host(); picking it would be harmless
	// but is less obviously the app's front door.
	doc := `{"items":[{"metadata":{"name":"app","namespace":"default","annotations":{
		"gethomepage.dev/enabled":"true","gethomepage.dev/name":"App"}},
		"spec":{"routes":[
			{"match":"Host(` + "`assets.talos00`" + `) && PathPrefix(` + "`/catalyst/`" + `)",
			 "middlewares":[{"name":"catalyst-nav","namespace":"traefik"}]},
			{"match":"Host(` + "`app.talos00`" + `)",
			 "middlewares":[{"name":"catalyst-nav","namespace":"traefik"}]}]}}]}`
	if got := onlyItem(t, mustBuild(t, doc)).Href; got != "//app.talos00/" {
		t.Fatalf("href = %q, want the plain route's host", got)
	}
}

func TestPathPrefixHostIsUsedWhenItIsTheOnlyOne(t *testing.T) {
	// The second pass exists for exactly this: prefer plain, but do not drop the app.
	doc := `{"items":[{"metadata":{"name":"app","namespace":"default","annotations":{
		"gethomepage.dev/enabled":"true","gethomepage.dev/name":"App"}},
		"spec":{"routes":[{"match":"Host(` + "`only.talos00`" + `) && PathPrefix(` + "`/x/`" + `)",
			"middlewares":[{"name":"catalyst-nav","namespace":"traefik"}]}]}}]}`
	if got := onlyItem(t, mustBuild(t, doc)).Href; got != "//only.talos00/" {
		t.Fatalf("href = %q, want the PathPrefix route's host as a fallback", got)
	}
}

func TestDedupKeepsTheThemedRoute(t *testing.T) {
	// Several IngressRoutes can advertise the same host (an http redirect companion
	// alongside the real one). The themed one wins regardless of document order.
	themedFirst := routeDoc(
		entryRoute("app.talos00", "App", "catalyst-sonarr"),
		entryRoute("app.talos00", "App", "catalyst-nav"),
	)
	themedSecond := routeDoc(
		entryRoute("app.talos00", "App", "catalyst-nav"),
		entryRoute("app.talos00", "App", "catalyst-sonarr"),
	)
	for name, doc := range map[string]string{"themed-first": themedFirst, "themed-second": themedSecond} {
		t.Run(name, func(t *testing.T) {
			if !onlyItem(t, mustBuild(t, doc)).Themed {
				t.Fatal("dedup dropped the themed route")
			}
		})
	}
}

func TestHostConfigIsCollectedFromTheSurvivingRoute(t *testing.T) {
	// "Collected AFTER the dedup decision" — the losing route's annotations must not apply.
	doc := routeDoc(
		withAnn(entryRoute("app.talos00", "App", "catalyst-sonarr"), `"catalyst.nav/height":"80"`),
		withAnn(entryRoute("app.talos00", "App", "catalyst-nav"), `"catalyst.nav/height":"40"`),
	)
	m := mustBuild(t, doc)
	cfg := m.Hosts.Values["app.talos00"]
	if v, _ := cfg.Get("height"); v != 80 {
		t.Fatalf("height = %v, want 80 (the themed/surviving route's value)", v)
	}
}

func TestStaleHostConfigFromALosingRouteSurvives(t *testing.T) {
	// A LATENT BUG IN build_nav.py, pinned so the port's fidelity is provable and so a
	// future fix has a failing test to flip.
	//
	// `if cfg: host_cfg[host] = cfg` assigns only when the surviving route has annotations
	// of its own. An unthemed route carrying catalyst.nav/* that is then overwritten by a
	// themed route WITHOUT them leaves the loser's config in host_cfg, shipping under the
	// winner's hostname. Reproduced deliberately: fixing it here would put a non-empty diff
	// in phase 6's audit for a reason unrelated to the migration.
	doc := routeDoc(
		withAnn(entryRoute("app.talos00", "App", "catalyst-nav"), `"catalyst.nav/height":"40"`),
		entryRoute("app.talos00", "App", "catalyst-sonarr"),
	)
	m := mustBuild(t, doc)
	cfg, present := m.Hosts.Values["app.talos00"]
	if !present {
		t.Fatal("stale config was dropped -- build_nav.py keeps it; if the script was " +
			"fixed, invert this spec and the comment in derive.go")
	}
	if v, _ := cfg.Get("height"); v != 40 {
		t.Fatalf("height = %v, want the losing route's 40", v)
	}
}

func TestHostConfigForAFilteredOutHostIsNotShipped(t *testing.T) {
	// "An annotation on a route that was filtered out must not ship config for an app nobody
	// can see." The route below is uninjected, so it never becomes an entry.
	doc := routeDoc(withAnn(entryRoute("app.talos00", "App", "authentik"), `"catalyst.nav/height":"40"`))
	m := mustBuild(t, doc)
	if len(m.Hosts.Keys) != 0 {
		t.Fatalf("hosts = %+v, want empty", m.Hosts.Keys)
	}
	if got := string(Encode(m)); strings.Contains(got, "hosts") {
		t.Fatalf("encoded = %s, want no hosts key", got)
	}
}

func TestMalformedConfigValuesAreDroppedWithALog(t *testing.T) {
	cases := []struct {
		ann, key string
	}{
		{`"catalyst.nav/mode":"sideways"`, "mode"},
		{`"catalyst.nav/height":"tall"`, "height"},
		{`"catalyst.nav/height":"40.5"`, "height"},
		{`"catalyst.nav/reveal-at":""`, "revealAt"},
		{`"catalyst.nav/intensity":"-1"`, "intensity"},
		{`"catalyst.nav/intensity":"inf"`, "intensity"},
		{`"catalyst.nav/intensity":"nan"`, "intensity"},
	}
	for _, tc := range cases {
		t.Run(tc.ann, func(t *testing.T) {
			doc := routeDoc(withAnn(entryRoute("app.talos00", "App", "catalyst-nav"), tc.ann))
			m := mustBuild(t, doc)
			if cfg, ok := m.Hosts.Values["app.talos00"]; ok {
				if _, bad := cfg.Get(tc.key); bad {
					t.Fatalf("%s reached the manifest", tc.ann)
				}
			}
		})
	}
}

func TestMalformedBooleanBecomesFalseRatherThanBeingDropped(t *testing.T) {
	// _as_bool is a membership test, not a parser: it never returns None, so a junk value
	// ships as false. Pinned because it is the one CONFIG_KEYS row that does NOT drop.
	doc := routeDoc(withAnn(entryRoute("app.talos00", "App", "catalyst-nav"), `"catalyst.nav/fx":"maybe"`))
	m := mustBuild(t, doc)
	cfg := m.Hosts.Values["app.talos00"]
	v, present := cfg.Get("fx")
	if !present || v != false {
		t.Fatalf("fx = %v (present=%v), want false", v, present)
	}
}

func TestBoolTruthySpellings(t *testing.T) {
	for _, raw := range []string{"true", "TRUE", " yes ", "1", "on", "On"} {
		doc := routeDoc(withAnn(entryRoute("app.talos00", "App", "catalyst-nav"),
			`"catalyst.nav/fx":`+jsonStr(raw)))
		cfg := mustBuild(t, doc).Hosts.Values["app.talos00"]
		if v, _ := cfg.Get("fx"); v != true {
			t.Fatalf("fx for %q = %v, want true", raw, v)
		}
	}
}

func TestConfigKeyOrderFollowsTheTableNotTheAlphabet(t *testing.T) {
	// The manifest's byte layout depends on CONFIG_KEYS order. Alphabetical would be
	// fx,height,hidePast,intensity,mode,revealAt,scrollReveal -- a different file.
	doc := routeDoc(withAnn(entryRoute("app.talos00", "App", "catalyst-nav"),
		`"catalyst.nav/fx":"true","catalyst.nav/mode":"push","catalyst.nav/height":"60",`+
			`"catalyst.nav/intensity":"1","catalyst.nav/reveal-at":"4",`+
			`"catalyst.nav/hide-past":"200","catalyst.nav/scroll-reveal":"true"`))
	want := `"hosts":{"app.talos00":{"mode":"push","revealAt":4,"hidePast":200,` +
		`"height":60,"scrollReveal":true,"intensity":1.0,"fx":true}}`
	if got := string(Encode(mustBuild(t, doc))); !strings.Contains(got, want) {
		t.Fatalf("encoded = %s\nwant it to contain %s", got, want)
	}
}

func TestIntensityOneRendersAsAFloat(t *testing.T) {
	// Python's float() then repr() makes `intensity: 1` ship as 1.0. One byte, and it fails
	// the whole phase-6 byte comparison.
	doc := routeDoc(withAnn(entryRoute("app.talos00", "App", "catalyst-nav"), `"catalyst.nav/intensity":"1"`))
	if got := string(Encode(mustBuild(t, doc))); !strings.Contains(got, `"intensity":1.0`) {
		t.Fatalf("encoded = %s, want intensity 1.0 not 1", got)
	}
}

func TestNameFallsBackToMetadataNameTitled(t *testing.T) {
	// `meta.get("name", host.split(".")[0]).title()`. Python's str.title() uppercases after
	// every non-letter, so a hyphenated object name gets BOTH halves capitalised.
	doc := `{"items":[{"metadata":{"name":"grafana-main","namespace":"monitoring","annotations":{
		"gethomepage.dev/enabled":"true"}},
		"spec":{"routes":[{"match":"Host(` + "`g.talos00`" + `)",
			"middlewares":[{"name":"catalyst-nav","namespace":"traefik"}]}]}}]}`
	if got := onlyItem(t, mustBuild(t, doc)).Name; got != "Grafana-Main" {
		t.Fatalf("name = %q, want %q", got, "Grafana-Main")
	}
}

func TestNameFallsBackToHostWhenMetadataNameIsAbsent(t *testing.T) {
	// The dict-default arm, reachable only when metadata.name is missing entirely.
	doc := `{"items":[{"metadata":{"namespace":"monitoring","annotations":{
		"gethomepage.dev/enabled":"true"}},
		"spec":{"routes":[{"match":"Host(` + "`grafana.talos00`" + `)",
			"middlewares":[{"name":"catalyst-nav","namespace":"traefik"}]}]}}]}`
	if got := onlyItem(t, mustBuild(t, doc)).Name; got != "Grafana" {
		t.Fatalf("name = %q, want %q", got, "Grafana")
	}
}

func TestGroupDefaultsToOther(t *testing.T) {
	doc := `{"items":[{"metadata":{"name":"app","namespace":"default","annotations":{
		"gethomepage.dev/enabled":"true","gethomepage.dev/name":"App"}},
		"spec":{"routes":[{"match":"Host(` + "`app.talos00`" + `)",
			"middlewares":[{"name":"catalyst-nav","namespace":"traefik"}]}]}}]}`
	m := mustBuild(t, doc)
	if len(m.Groups) != 1 || m.Groups[0].Name != "Other" {
		t.Fatalf("groups = %+v, want one group named Other", m.Groups)
	}
}

func TestWeightDefaultsTo50AndMalformedWeightIsReported(t *testing.T) {
	doc := routeDoc(withAnn(entryRoute("app.talos00", "App", "catalyst-nav"),
		`"gethomepage.dev/weight":"heavy"`))
	m := mustBuild(t, doc)
	if got := onlyItem(t, m).Weight; got != 50 {
		t.Fatalf("weight = %d, want the 50 default", got)
	}
	// The feedback channel build_nav.py lacks: a bad annotation becomes a condition
	// instead of a line in a sidecar log nobody reads.
	if len(m.Rejections) != 1 || m.Rejections[0].Reason != "MalformedWeight" {
		t.Fatalf("rejections = %+v, want one MalformedWeight", m.Rejections)
	}
}

func TestWeightAcceptsPythonIntSpellings(t *testing.T) {
	// int(" 50 ") is 50 in Python; strconv.Atoi rejects it. int("1_0") is 10.
	for raw, want := range map[string]int{" 70 ": 70, "+30": 30, "-10": -10, "1_0": 10} {
		doc := routeDoc(withAnn(entryRoute("app.talos00", "App", "catalyst-nav"),
			`"gethomepage.dev/weight":`+jsonStr(raw)))
		if got := onlyItem(t, mustBuild(t, doc)).Weight; got != want {
			t.Fatalf("weight for %q = %d, want %d", raw, got, want)
		}
	}
}

func TestItemsSortByWeightThenLowercasedName(t *testing.T) {
	doc := routeDoc(
		entryRoute("b.talos00", "zeta", "catalyst-nav"),
		entryRoute("a.talos00", "Alpha", "catalyst-nav"),
		withAnn(entryRoute("c.talos00", "First", "catalyst-nav"), `"gethomepage.dev/weight":"10"`),
	)
	m := mustBuild(t, doc)
	var names []string
	for _, i := range m.Groups[0].Items {
		names = append(names, i.Name)
	}
	want := []string{"First", "Alpha", "zeta"}
	if strings.Join(names, ",") != strings.Join(want, ",") {
		t.Fatalf("order = %v, want %v", names, want)
	}
}

func TestThemedGroupsSortBeforeUnthemedThenAlphabetically(t *testing.T) {
	// "Groups with themed apps first (that is where you actually navigate), then the rest
	// alphabetically."
	doc := routeDoc(
		withGroup(entryRoute("a.talos00", "A", "catalyst-nav"), "Zebra"),
		withGroup(entryRoute("b.talos00", "B", "catalyst-nav"), "Alpha"),
		withGroup(entryRoute("c.talos00", "C", "catalyst-sonarr"), "Themed"),
	)
	m := mustBuild(t, doc)
	var got []string
	for _, g := range m.Groups {
		got = append(got, g.Name)
	}
	want := "Themed,Alpha,Zebra"
	if strings.Join(got, ",") != want {
		t.Fatalf("group order = %v, want %s", got, want)
	}
}

func TestEnabledMustBeExactlyTrue(t *testing.T) {
	for _, v := range []string{"True", "yes", "1", ""} {
		doc := routeDoc(strings.Replace(
			entryRoute("app.talos00", "App", "catalyst-nav"),
			`"gethomepage.dev/enabled":"true"`, `"gethomepage.dev/enabled":`+jsonStr(v), 1))
		if m := mustBuild(t, doc); len(m.Groups) != 0 {
			t.Fatalf("enabled=%q admitted the route; only the exact string \"true\" opts in", v)
		}
	}
}

func TestRouteWithNoHostMatchIsRejectedWithAReason(t *testing.T) {
	doc := `{"items":[{"metadata":{"name":"app","namespace":"default","annotations":{
		"gethomepage.dev/enabled":"true","gethomepage.dev/name":"App"}},
		"spec":{"routes":[{"match":"PathPrefix(` + "`/x/`" + `)",
			"middlewares":[{"name":"catalyst-nav","namespace":"traefik"}]}]}}]}`
	m := mustBuild(t, doc)
	if len(m.Groups) != 0 {
		t.Fatalf("groups = %+v, want empty", m.Groups)
	}
	if len(m.Rejections) != 1 || m.Rejections[0].Reason != "NoHostMatch" {
		t.Fatalf("rejections = %+v, want one NoHostMatch", m.Rejections)
	}
}

// ── NAV_DEFAULTS ─────────────────────────────────────────────────────────────────────────

func TestNavDefaultsFiltersToTheConfigKeyTable(t *testing.T) {
	cfg := ParseNavDefaultsEnv(`{"revealAt":4,"notAKey":"x","fx":false}`, nil)
	if cfg.Len() != 2 {
		t.Fatalf("keys = %v, want revealAt and fx only", cfg.Keys)
	}
	if strings.Join(cfg.Keys, ",") != "revealAt,fx" {
		t.Fatalf("keys = %v, want source order revealAt,fx", cfg.Keys)
	}
}

func TestNavDefaultsPreservesSourceOrderInTheBytes(t *testing.T) {
	// Python dicts keep the order keys appeared in the JSON text, and json.dump writes them
	// back in that order. Go maps would alphabetise.
	m := &Manifest{Defaults: ParseNavDefaultsEnv(`{"fx":true,"revealAt":4}`, nil)}
	if got := string(Encode(m)); !strings.Contains(got, `"defaults":{"fx":true,"revealAt":4}`) {
		t.Fatalf("encoded = %s, want fx before revealAt", got)
	}
}

func TestNavDefaultsRejectsNonObjectsAndJunk(t *testing.T) {
	cases := []struct{ raw, wantLog string }{
		{`[1,2]`, "must be a JSON object"},
		{`"nope"`, "must be a JSON object"},
		{`{nope}`, "not valid JSON"},
		{`{"revealAt":4} trailing`, "not valid JSON"},
	}
	for _, tc := range cases {
		t.Run(tc.raw, func(t *testing.T) {
			var log bytes.Buffer
			cfg := ParseNavDefaultsEnv(tc.raw, &log)
			if cfg.Len() != 0 {
				t.Fatalf("cfg = %v, want empty", cfg.Keys)
			}
			if !strings.Contains(log.String(), tc.wantLog) {
				t.Fatalf("log = %q, want %q", log.String(), tc.wantLog)
			}
		})
	}
}

func TestNavDefaultsEmptyIsNoKeyAtAll(t *testing.T) {
	m := &Manifest{Defaults: ParseNavDefaultsEnv("   ", nil)}
	if got := string(Encode(m)); got != `{"groups":[]}` {
		t.Fatalf("encoded = %s, want no defaults key", got)
	}
}

func TestAppletsAppendAfterNavDefaultsKeys(t *testing.T) {
	// env_defaults() first, then `defaults["applets"] = applets` — so applets is last.
	var d Doc
	if err := json.Unmarshal([]byte(routeDoc(appletRoute("r", appletSrc, "dev-overlay"))), &d); err != nil {
		t.Fatal(err)
	}
	m := Build(&d, Options{Defaults: ParseNavDefaultsEnv(`{"revealAt":4}`, nil)})
	if strings.Join(m.Defaults.Keys, ",") != "revealAt,applets" {
		t.Fatalf("keys = %v, want revealAt then applets", m.Defaults.Keys)
	}
}

func TestBuildDoesNotMutateItsOptions(t *testing.T) {
	// Options is passed by value but OrderedConfig holds a slice and a map; appending
	// "applets" in place would leak into the caller and make a second Build disagree.
	// The reconciler calls Build on every event with one long-lived Options.
	var d Doc
	if err := json.Unmarshal([]byte(routeDoc(appletRoute("r", appletSrc, "dev-overlay"))), &d); err != nil {
		t.Fatal(err)
	}
	opts := Options{Defaults: ParseNavDefaultsEnv(`{"revealAt":4}`, nil)}
	first := Encode(Build(&d, opts))
	second := Encode(Build(&d, opts))
	if !bytes.Equal(first, second) {
		t.Fatalf("Build mutated Options:\n%s\n%s", first, second)
	}
	if opts.Defaults.Len() != 1 {
		t.Fatalf("caller's Defaults grew to %v", opts.Defaults.Keys)
	}
}

// ── Python-semantics helpers ─────────────────────────────────────────────────────────────

func TestPyTitleMatchesPythonStrTitle(t *testing.T) {
	// Verified against python3 -c 'print(repr(s.title()))' for each input.
	cases := map[string]string{
		"grafana":       "Grafana",
		"grafana-main":  "Grafana-Main",
		"kube_ops_view": "Kube_Ops_View",
		"ARGOCD":        "Argocd",
		"a1b":           "A1B",
		"":              "",
		"x.y":           "X.Y",
	}
	for in, want := range cases {
		if got := pyTitle(in); got != want {
			t.Errorf("pyTitle(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestPyFloatRendersIntegralValuesWithAFraction(t *testing.T) {
	cases := map[float64]string{1: "1.0", 0: "0.0", 0.5: "0.5", 1.25: "1.25", 100: "100.0"}
	for in, want := range cases {
		if got := pyFloat(in); got != want {
			t.Errorf("pyFloat(%v) = %q, want %q", in, got, want)
		}
	}
}

func TestPyIntRejectsWhatPythonRejects(t *testing.T) {
	for _, bad := range []string{"", " ", "50.0", "5a", "_1", "1_", "1__0", "0x10", "1e3"} {
		if n, ok := pyInt(bad); ok {
			t.Errorf("pyInt(%q) = %d, want rejection", bad, n)
		}
	}
}

// ── helpers ──────────────────────────────────────────────────────────────────────────────

func mustBuild(t *testing.T, doc string, opts ...func(*Options)) *Manifest {
	t.Helper()
	m, _ := run(t, doc, opts...)
	return m
}

// withAnn splices extra annotations into a fixture built by entryRoute.
func withAnn(routeJSON, extra string) string {
	const anchor = `"gethomepage.dev/enabled":"true",`
	return strings.Replace(routeJSON, anchor, anchor+extra+",", 1)
}

func withGroup(routeJSON, group string) string {
	return strings.Replace(routeJSON, `"gethomepage.dev/group":"Group"`,
		`"gethomepage.dev/group":`+jsonStr(group), 1)
}
