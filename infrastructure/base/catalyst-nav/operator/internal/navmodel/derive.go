package navmodel

// The build_nav.py port. Read that script alongside this file; every non-obvious branch here
// exists because it exists there, and the comment says which incident put it there.
//
// THE CONTRACT THIS FILE OWES: phase 6 deletes build_nav.py only after a byte-comparison of
// this output against the sidecar's. So "cleaner" is not a licence to change behaviour — the
// one latent bug found during the port (staleHostConfig, below) is reproduced deliberately
// rather than fixed, because fixing it here would make the audit diff non-empty for a reason
// unrelated to the migration.

import (
	"fmt"
	"io"
	"regexp"
	"sort"
	"strings"
)

const (
	// annPrefix is build_nav.py's `A`.
	annPrefix = "gethomepage.dev/"
	// navPrefix is build_nav.py's `NAV`.
	navPrefix = "catalyst.nav/"
)

var hostRE = regexp.MustCompile("Host\\(`([^`]+)`\\)")

// sharedMiddlewares is build_nav.py's SHARED. These ride along inside every chain, so
// counting them would make `injected` tautologically true for every route in the cluster.
//
// The prefix tests below and the names in infrastructure/base/themepark/middlewares.yaml must
// move together.
var sharedMiddlewares = map[string]struct{}{
	"catalyst-compress":        {},
	"catalyst-accept-encoding": {},
	"catalyst-asset-cache":     {},
}

// configKey is one row of build_nav.py's CONFIG_KEYS table: the manifest key plus the parser
// that validates the annotation. A parser returning ok=false means DROP — never propagate.
//
// ONE table, same as the script: it validates the annotations, names the manifest keys, and
// documents the surface. Anything not listed here can never reach the manifest.
type configKey struct {
	suffix string // annotation suffix under catalyst.nav/
	key    string // manifest key (camelCase)
	parse  func(string) (any, bool)
}

// configKeys is declared as a SLICE, not a map, because its order is the order the keys appear
// in each host's config object and therefore part of the manifest bytes. A Go map would
// reorder them to alphabetical and the parity diff would fail on every app that sets more than
// one of these.
var configKeys = []configKey{
	{"mode", "mode", func(v string) (any, bool) {
		switch v {
		case "overlay", "push", "off":
			return v, true
		}
		return nil, false
	}},
	{"reveal-at", "revealAt", parseInt},
	{"hide-past", "hidePast", parseInt},
	{"height", "height", parseInt},
	// _as_bool NEVER fails: str(v).strip().lower() in (...) is a membership test, so a
	// malformed value yields False rather than being dropped. `scroll-reveal: yes-please`
	// therefore ships `"scrollReveal":false`, not nothing. Reproduced, not corrected.
	{"scroll-reveal", "scrollReveal", parseBool},
	{"intensity", "intensity", parseIntensity},
	{"fx", "fx", parseBool},
}

func parseInt(v string) (any, bool) {
	n, ok := pyInt(v)
	if !ok {
		return nil, false
	}
	return n, true
}

func parseBool(v string) (any, bool) {
	switch strings.ToLower(strings.TrimSpace(v)) {
	case "true", "1", "yes", "on":
		return true, true
	}
	return false, true
}

// parseIntensity is _as_intensity: a 0..n animation amplitude.
//
// A negative value would not merely look wrong — the theme's layer 45 multiplies translate
// distances by it, so every animation would run backwards — and inf produces a transform the
// compositor cannot resolve.
func parseIntensity(v string) (any, bool) {
	f, ok := pyFloat64(v)
	if !ok || !isFiniteNonNegative(f) {
		return nil, false
	}
	return f, true
}

// appletSrcRule mirrors APPLET_URL_RULES in catalyst-nav.js. Duplicated on purpose: the client
// rule is the one that actually protects the ~40 host pages, and this one keeps a bad
// annotation from ever reaching them. If you widen one, widen both.
type appletSrcRule struct {
	why string
	bad func(string) bool
}

var schemedRE = regexp.MustCompile(`^[a-zA-Z][a-zA-Z0-9+.\-]*:`)

var appletSrcRules = []appletSrcRule{
	{"not a non-empty string", func(s string) bool { return s == "" }},
	{"protocol-relative", func(s string) bool { return strings.HasPrefix(s, "//") }},
	{"absolute or schemed", func(s string) bool { return schemedRE.MatchString(s) }},
	{"contains a backslash", func(s string) bool { return strings.Contains(s, `\`) }},
	{"contains ..", func(s string) bool { return strings.Contains(s, "..") }},
	{"percent-encoded", func(s string) bool { return strings.Contains(s, "%") }},
	// The prefix is the whole trust story: /catalyst/ is the one path gated by
	// HostRegexp + lan-only, so a bundle served from anywhere else is not subject to the
	// controls that keep the applet off the public hostnames.
	{"outside /catalyst/", func(s string) bool { return !strings.HasPrefix(s, "/catalyst/") }},
}

// AppletSrcRefusal reports why src is unacceptable, or "" if it is fine.
func AppletSrcRefusal(src string) string {
	for _, r := range appletSrcRules {
		if r.bad(src) {
			return r.why
		}
	}
	return ""
}

// Options are the environment knobs build_nav.py reads, lifted into parameters so the model is
// testable without mutating os.Environ and so the reconciler can hold them as config.
type Options struct {
	// ScopeAll is NAV_SCOPE=all: advertise every gethomepage.dev-enabled route rather than
	// only those carrying Catalyst injection. Default (false) is the DERIVED filter — add
	// the middleware to an app and it joins the bar, with nothing to edit anywhere.
	ScopeAll bool

	// Defaults is NAV_DEFAULTS, already parsed and already filtered to the CONFIG_KEYS key
	// set. Order is the order it will be emitted in. Use ParseNavDefaults to build it.
	Defaults OrderedConfig

	// Log receives the refusal lines build_nav.py writes to stderr. Nil discards them —
	// which is the right default for the reconciler, whose equivalent output is a status
	// condition, and the wrong default for the render parity mode, which must reproduce
	// the sidecar's stderr too.
	Log io.Writer
}

func (o *Options) logf(format string, args ...any) {
	if o.Log == nil {
		return
	}
	fmt.Fprintf(o.Log, format+"\n", args...)
}

// ParseNavDefaults filters a decoded NAV_DEFAULTS object down to the CONFIG_KEYS key set,
// preserving the order the keys appeared in.
//
// Filtered by KEY ONLY, exactly as env_defaults() does — a value of the wrong type for its key
// is passed straight through. That is not an oversight being copied blindly: NAV_DEFAULTS is
// set by whoever edits the Deployment, not by an app team annotating a route, so it is a
// trusted input in a way annotations are not, and the client's resolveConfig() is the layer
// that has to cope either way.
func ParseNavDefaults(order []string, values map[string]any) OrderedConfig {
	allowed := map[string]struct{}{}
	for _, ck := range configKeys {
		allowed[ck.key] = struct{}{}
	}
	var out OrderedConfig
	for _, k := range order {
		if _, ok := allowed[k]; !ok {
			continue
		}
		out.Set(k, values[k])
	}
	return out
}

// navConfig extracts catalyst.nav/* into the manifest's camelCase config shape.
//
// A malformed value is DROPPED, never allowed to propagate: this JSON is consumed inside
// fourteen third-party apps, and a bad int there would throw in the host page rather than here
// where it is merely logged.
func navConfig(ann map[string]string, opts *Options) OrderedConfig {
	var cfg OrderedConfig
	for _, ck := range configKeys {
		raw, present := ann[navPrefix+ck.suffix]
		if !present {
			continue
		}
		val, ok := ck.parse(raw)
		if !ok {
			opts.logf("[nav] ignoring %s%s=%s", navPrefix, ck.suffix, pyRepr(raw))
			continue
		}
		cfg.Set(ck.key, val)
	}
	return cfg
}

// discoverApplets collects {src} entries from catalyst.nav/applet-src annotations.
//
// A SEPARATE PASS over the same document, not a branch inside the entry loop, and
// tests/nav/test_build_nav.py pins that: the applet's route carries no gethomepage.dev/*
// annotations at all (dev-overlay has no page to visit), so the entry loop skips it before any
// branch inside that loop could run.
//
// Sorted by src so the manifest is byte-stable across refreshes — an unstable manifest would
// change the file every 300 seconds and make any future "did the nav change?" check useless.
func discoverApplets(doc *Doc, opts *Options) []Applet {
	found := map[string]struct{}{}
	var srcs []string
	for _, item := range doc.Items {
		src, present := item.Metadata.Annotations[navPrefix+"applet-src"]
		if !present {
			continue
		}
		if why := AppletSrcRefusal(src); why != "" {
			opts.logf("[nav] refusing %sapplet-src=%s: %s", navPrefix, pyRepr(src), why)
			continue
		}
		// Deduplicated by src: the same applet is routed on both `web` and `websecure`,
		// so its annotation legitimately appears twice.
		if _, dup := found[src]; dup {
			continue
		}
		found[src] = struct{}{}
		srcs = append(srcs, src)
		if name := item.Metadata.Annotations[navPrefix+"applet-name"]; name != "" {
			opts.logf("[nav] applet %s -> %s", name, src)
		}
	}
	sort.Strings(srcs)
	out := make([]Applet, 0, len(srcs))
	for _, s := range srcs {
		out = append(out, Applet{Src: s})
	}
	return out
}

// classify answers the two distinct questions build_nav.py asks about a route's middlewares.
// Conflating them emptied the nav once already when middlewares were renamed:
//
//	injected — does this app carry ANY catalyst injection? That decides whether it belongs
//	           in the bar at all.
//	themed   — does it carry a per-app FULL theme (catalyst-<slug>), as opposed to
//	           catalyst-nav which adds the bar and leaves the app's own styling alone? That
//	           decides whether the entry is dimmed, so it is visible up front that the
//	           destination will not look like where you came from.
//
// SHARED is excluded from both.
func classify(routes []Route) (injected, themed bool) {
	names := map[string]struct{}{}
	for _, r := range routes {
		for _, mw := range r.Middlewares {
			if _, shared := sharedMiddlewares[mw.Name]; shared {
				continue
			}
			names[mw.Name] = struct{}{}
		}
	}
	for n := range names {
		if strings.HasPrefix(n, "catalyst") {
			injected = true
		}
		// "nav" in the name means nav-only, by convention: catalyst-nav itself, and any
		// merged injector that adds the bar alongside something else
		// (catalyst-nav-rum-grafana, where the bar and the RUM tag share one rewriteBody
		// because chaining two is a silent failure). Testing the exact string
		// "catalyst-nav" instead would classify every such merged middleware as a FULL
		// theme and dim its entry, promising a restyled destination that keeps its own
		// look.
		if strings.HasPrefix(n, "catalyst-") && !strings.Contains(n, "nav") {
			themed = true
		}
	}
	return injected, themed
}

// hostFor extracts the app's front door from the route match rules.
//
// Prefer a host from a plain route over one carrying a PathPrefix: the asset route added for
// the theme also matches Host(), and picking it would be harmless but is less obviously the
// app's front door.
func hostFor(routes []Route) string {
	for _, preferPlain := range []bool{true, false} {
		for _, r := range routes {
			if preferPlain && strings.Contains(r.Match, "PathPrefix") {
				continue
			}
			if m := hostRE.FindStringSubmatch(r.Match); m != nil {
				return m[1]
			}
		}
	}
	return ""
}

// Build derives the nav model from a decoded `kubectl get ingressroutes -A -o json`.
//
// Pure: no clients, no environment reads, no clock. Everything variable is in Options.
func Build(doc *Doc, opts Options) *Manifest {
	type entry struct {
		item  Item
		order int
	}
	entries := map[string]*entry{}
	var entryOrder []string // insertion order of `entries`, which Python gets from dict

	var hostCfg OrderedHosts
	m := &Manifest{}

	for _, item := range doc.Items {
		ann := item.Metadata.Annotations
		if ann[annPrefix+"enabled"] != "true" {
			continue
		}
		routes := item.Spec.Routes
		src := Source{Kind: "IngressRoute", Namespace: item.Metadata.Namespace, Name: item.Metadata.Name}

		injected, themed := classify(routes)

		host := hostFor(routes)
		if host == "" {
			m.Rejections = append(m.Rejections, Rejection{
				Source: src, Reason: "NoHostMatch",
				Message: "gethomepage.dev/enabled=true but no route carries a Host(`...`) rule, so there is no destination to link to",
			})
			continue
		}

		if !opts.ScopeAll && !injected {
			m.Rejections = append(m.Rejections, Rejection{
				Source: src, Reason: "NotInjected",
				Message: fmt.Sprintf("%s carries no catalyst-* middleware, so it is outside the default NAV_SCOPE=themed set", host),
			})
			continue
		}

		// Private/internal hostnames are reachable but not somewhere a nav should send
		// people by default.
		if strings.Contains(host, ".priv.") {
			m.Rejections = append(m.Rejections, Rejection{
				Source: src, Reason: "PrivateHostname",
				Message: fmt.Sprintf("%s is a .priv. hostname, excluded from the nav by design", host),
			})
			continue
		}

		name := ann[annPrefix+"name"]
		if name == "" {
			// `meta.get("name", host.split(".")[0]).title()` — the fallback applies
			// only when metadata.name is ABSENT, and .title() applies to whichever of
			// the two was returned.
			if item.Metadata.nameAbsent {
				name = pyTitle(strings.SplitN(host, ".", 2)[0])
			} else {
				name = pyTitle(item.Metadata.Name)
			}
		}
		group := ann[annPrefix+"group"]
		if group == "" {
			group = "Other"
		}
		weight := 50
		if raw, ok := ann[annPrefix+"weight"]; ok && raw != "" {
			if n, good := pyInt(raw); good {
				weight = n
			} else {
				m.Rejections = append(m.Rejections, Rejection{
					Source: src, Reason: "MalformedWeight",
					Message: fmt.Sprintf("gethomepage.dev/weight=%s is not an integer; defaulted to 50", pyRepr(raw)),
				})
			}
		}

		// Deduplicate: several IngressRoutes can advertise the same host (an http
		// redirect companion alongside the real one). Keep the themed one.
		if prev, seen := entries[host]; seen && prev.item.Themed && !themed {
			continue
		}

		// Collected AFTER the dedup check, so the surviving route for a host is the one
		// whose catalyst.nav/* annotations apply.
		//
		// staleHostConfig: a LATENT BUG, reproduced on purpose. `if cfg: host_cfg[host] =
		// cfg` only assigns when the surviving route has annotations of its own — so when
		// an unthemed route with catalyst.nav/* annotations is overwritten by a themed
		// route WITHOUT them, the loser's config stays in host_cfg and ships under the
		// winner's hostname. Fixing it here would put a non-empty diff in phase 6's audit
		// for a reason that has nothing to do with the migration; file it as its own
		// change against build_nav.py first, then change both.
		if cfg := navConfig(ann, &opts); cfg.Len() > 0 {
			hostCfg.Set(host, cfg)
		}

		if _, seen := entries[host]; !seen {
			entryOrder = append(entryOrder, host)
		}
		entries[host] = &entry{item: Item{
			Name:   name,
			Weight: weight,
			Href:   "//" + host + "/",
			Themed: themed,
			Group:  group,
			Source: src,
		}}
	}

	// Group in first-appearance order, then sort. Python's grouped dict preserves insertion
	// order and list.sort is stable, so first-appearance order is what breaks ties.
	grouped := map[string][]Item{}
	var groupOrder []string
	for _, h := range entryOrder {
		e := entries[h]
		if _, seen := grouped[e.item.Group]; !seen {
			groupOrder = append(groupOrder, e.item.Group)
		}
		grouped[e.item.Group] = append(grouped[e.item.Group], e.item)
	}

	groups := make([]Group, 0, len(groupOrder))
	for _, gname := range groupOrder {
		items := grouped[gname]
		sort.SliceStable(items, func(i, j int) bool {
			if items[i].Weight != items[j].Weight {
				return items[i].Weight < items[j].Weight
			}
			return strings.ToLower(items[i].Name) < strings.ToLower(items[j].Name)
		})
		groups = append(groups, Group{Name: gname, Items: items})
	}

	// Groups with themed apps first (that is where you actually navigate), then the rest
	// alphabetically. Stable and derived, not a curated order.
	sort.SliceStable(groups, func(i, j int) bool {
		ri, rj := themedRank(groups[i]), themedRank(groups[j])
		if ri != rj {
			return ri < rj
		}
		return strings.ToLower(groups[i].Name) < strings.ToLower(groups[j].Name)
	})
	m.Groups = groups

	defaults := opts.Defaults
	// defaults, not per-host: an applet docks into every app carrying the bar, which is the
	// point of it. The per-host override path still exists — hosts.<h>.applets resolves
	// last — so one app can opt out or carry an extra bundle without this becoming a
	// curated list.
	if applets := discoverApplets(doc, &opts); len(applets) > 0 {
		// Copy before mutating: Options is passed by value but OrderedConfig holds a
		// slice and a map, so appending in place would leak into the caller's copy and
		// make two Build calls on one Options disagree.
		next := OrderedConfig{Keys: append([]string(nil), defaults.Keys...), Values: map[string]any{}}
		for k, v := range defaults.Values {
			next.Values[k] = v
		}
		next.Set("applets", applets)
		defaults = next
	}
	m.Defaults = defaults

	// Only hosts that actually made it into the nav — an annotation on a route that was
	// filtered out must not ship config for an app nobody can see.
	for _, h := range hostCfg.Keys {
		if _, live := entries[h]; live {
			m.Hosts.Set(h, hostCfg.Values[h])
		}
	}

	return m
}

func themedRank(g Group) int {
	for _, i := range g.Items {
		if i.Themed {
			return 0
		}
	}
	return 1
}
