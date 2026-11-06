package navserve

// THE PUBLIC MANIFEST ENDPOINT — the operator becoming the SOLE producer of the nav manifest.
//
// ── WHAT THIS REPLACES, AND WHY A SECOND HANDLER WAS NEEDED AT ALL ───────────────────────────
//
// Until this existed there were two implementations of one derivation: build_nav.py in a
// sidecar beside the theme server, and navmodel in this operator. They were kept honest by a
// byte-for-byte parity gate, which is a good gate and still a standing cost — every change to
// the nav model had to be made twice, in two languages, and the only thing stopping them
// drifting was a manual task nobody's CI runs. The sidecar is deleted and this is what takes
// over its output.
//
// It could NOT be taken over by Handler, the per-identity endpoint in server.go. That handler
// is built on two invariants this one must break:
//
//   - `private, no-store` on EVERY response, so a per-identity body can never enter a cache.
//     The public manifest is the opposite: one body for everybody, fetched as a subresource by
//     ~57 apps on every page load, and the thing it replaces was served by nginx behind
//     `public, max-age=300`. Serving it uncacheable would turn one cached asset into a
//     per-pageview request against a single-replica operator.
//   - "There is no code path that serves the UNFILTERED manifest" — server.go's words, and
//     they were true when written. This file makes them false, so server.go's package comment
//     has been corrected rather than left to mislead. The honest statement of the boundary is
//     now: the IDENTITY endpoint has no unfiltered path, and the PUBLIC endpoint has no
//     filtered one; they are different listeners on different ports behind different routes.
//
// ── IS SERVING THE UNFILTERED MANIFEST SAFE? ─────────────────────────────────────────────────
//
// It is exactly as safe as what it replaces, and not one bit safer — which is the whole claim,
// so it is worth being precise rather than reassuring.
//
// These bytes are byte-identical to the static catalyst-nav.json that nginx served at
// /catalyst/resources/catalyst-nav.json, to every LAN browser, with no authentication, from
// the day the nav shipped. The manifest enumerates every internal *.talos00 hostname; in
// 2026-09-26 it was confirmed readable from the public internet, and the two controls added
// afterwards — HostRegexp(`^[a-z0-9-]+\.talos00$`) and lan-only — are what make it LAN-only.
// THOSE CONTROLS ARE THE BOUNDARY, they live on the IngressRoute, and this handler inherits
// them unchanged because the route that reaches it carries both. Nothing about the exposure
// moves: same path, same host gate, same IP gate, same bytes.
//
// What DOES improve is incidental and worth recording: the sidecar also published the manifest
// at /resources/catalyst-nav.json on the theme server's own document root (outside /catalyst/
// entirely, which is why both gates above missed it and a third lan-only had to be bolted onto
// the themepark IngressRoute). With the sidecar gone nothing writes into that document root
// and that path is a 404. One fewer copy, one fewer place to gate.
//
// The 21 themed hosts that cannot use the per-identity endpoint — no forward-auth at all
// (grafana, plex, jellyfin, komga, kavita, minio, homeassistant, linkwarden, argocd…), or on
// bare `authentik` rather than `authentik-lan`, or served over plain HTTP where a Secure
// session cookie is never sent — depend on this path and on it being unfiltered. Filtering it
// through visibility.Anonymous() instead would be a different and WORSE answer: it changes the
// bytes (failing the migration's own gate), and on the day a NavGroup first declares
// spec.visibility it would silently empty the bar on a fifth of the cluster.
//
// ── NO IDENTITY, STRUCTURALLY ────────────────────────────────────────────────────────────────
//
// This handler never reads a request header. Not "does not currently" — there is no
// visibility.Identity in scope, no call to Filter, and no Config field that could introduce
// one. A spoofed X-authentik-groups against this port is not a weaker control than the
// identity endpoint's, it is NOT A CONTROL AT ALL, because nothing here consults it. That is
// the correct shape for a body that is identical for every caller: the way to be immune to
// header spoofing is to have no code that believes a header.
//
// Correspondingly, Vary names ONLY Accept-Encoding. Listing Cookie here — as the identity
// handler must — would fragment a shared cache by session for a body that never varies, which
// is a cache-efficiency bug dressed as caution.

import (
	"net/http"
	"strconv"
	"time"

	"github.com/prometheus/client_golang/prometheus"

	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/navmodel"
)

const (
	// DefaultPublicPath is the path the deleted sidecar's file was served at, preserved
	// EXACTLY. 57 themed hosts have this URL baked into the <script> tag Traefik injects
	// (catalyst-nav.js's MANIFEST_STATIC), so changing it would mean editing every injector
	// in infrastructure/base/themepark/middlewares.yaml in the same commit. Keeping the path
	// is what makes this cutover invisible to every client that did not opt in.
	DefaultPublicPath = "/catalyst/resources/catalyst-nav.json"

	// DefaultPublicCacheControl matches what the catalyst-asset-cache Traefik middleware
	// stamps on everything under /catalyst/, which is what nginx's copy of this file was
	// served behind.
	//
	// SET BY THE BACKEND ANYWAY, even though that middleware's customResponseHeaders will
	// OVERWRITE it. Belt and braces in the one direction that matters: if the route is ever
	// rewritten without the middleware, the body stays cacheable because the origin said so,
	// rather than silently becoming a per-pageview fetch that shows up as operator CPU and
	// not as an error.
	DefaultPublicCacheControl = "public, max-age=300, stale-while-revalidate=3600"
)

// PublicConfig is the public handler's knobs. The zero value is usable.
type PublicConfig struct {
	Path         string
	CacheControl string
}

func (c PublicConfig) withDefaults() PublicConfig {
	if c.Path == "" {
		c.Path = DefaultPublicPath
	}
	if c.CacheControl == "" {
		c.CacheControl = DefaultPublicCacheControl
	}
	return c
}

// PublicHandler serves the unfiltered nav manifest.
type PublicHandler struct {
	cfg    PublicConfig
	src    Source
	served *prometheus.CounterVec
}

// NewPublicHandler wires a Source to a PublicConfig. reg may be nil, which disables metrics.
//
// Takes the SAME Source as the identity handler on purpose. Both read one Snapshot published
// once per reconcile, so the public bytes, the per-identity bytes and the ConfigMap's bytes
// all descend from a single build and cannot disagree about what the cluster looks like. A
// second source — re-listing IngressRoutes here, say — would reintroduce exactly the
// two-producers-one-derivation problem this endpoint exists to end.
func NewPublicHandler(src Source, cfg PublicConfig, reg prometheus.Registerer) *PublicHandler {
	h := &PublicHandler{cfg: cfg.withDefaults(), src: src}
	if reg != nil {
		h.served = prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "catalyst_nav_public_manifest_requests_total",
			Help: "Public (unfiltered, cacheable) nav manifest requests by outcome. " +
				"outcome=no_snapshot counts requests that arrived before the first " +
				"reconcile completed; a sustained rate there means the operator is " +
				"not reconciling and ~57 apps are rendering no nav bar.",
		}, []string{"outcome"})
		reg.MustRegister(h.served)
	}
	return h
}

// Path is where this handler answers, after defaulting.
func (h *PublicHandler) Path() string { return h.cfg.Path }

func (h *PublicHandler) count(outcome string) {
	if h.served != nil {
		h.served.WithLabelValues(outcome).Inc()
	}
}

func (h *PublicHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != h.cfg.Path {
		h.count("not_found")
		// no-store on the ERROR paths, deliberately asymmetric with the 200 below. A
		// cached 404 or 503 blanks the bar for everyone behind that cache for the full
		// max-age, and these are the responses nobody looks at. Only the success path
		// is worth caching, and only the success path is cacheable.
		w.Header().Set("Cache-Control", "private, no-store")
		w.WriteHeader(http.StatusNotFound)
		return
	}
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		h.count("method_not_allowed")
		w.Header().Set("Cache-Control", "private, no-store")
		w.Header().Set("Allow", "GET, HEAD")
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}

	snap := h.src.Snapshot()
	if snap == nil || snap.Manifest == nil {
		// Before the first reconcile. 503, not an empty manifest: an empty manifest is a
		// VALID document that would make catalyst-nav.js build a bar with nothing in it
		// and STOP retrying, whereas a 503 is what its three-try backoff exists for. The
		// deleted discover.sh made the same choice — it never published an empty nav on a
		// failed refresh, it kept serving the previous one.
		h.count("no_snapshot")
		w.Header().Set("Cache-Control", "private, no-store")
		w.Header().Set("Retry-After", "2")
		w.WriteHeader(http.StatusServiceUnavailable)
		return
	}

	// UNFILTERED, and literally the bytes the reconciler put in the ConfigMap — not a second
	// call to the same encoder. See Snapshot.Bytes.
	//
	// The fallback re-encodes rather than serving an empty body, for a caller that built a
	// Snapshot without Bytes (every test that predates the field, and anything constructing
	// one by hand). Silently serving `nil` would render an empty bar cluster-wide and look
	// like a nav with nothing in it, which is the one failure mode this endpoint's 503 path
	// exists to avoid.
	body := snap.Bytes
	if body == nil {
		body = navmodel.Encode(snap.Manifest)
	}

	hdr := w.Header()
	hdr.Set("Content-Type", "application/json")
	hdr.Set("Content-Length", strconv.Itoa(len(body)))
	hdr.Set("Cache-Control", h.cfg.CacheControl)
	// Accept-Encoding ONLY. The body does not vary by cookie, by group, or by anything
	// else a caller can present -- see the package comment.
	hdr.Set("Vary", "Accept-Encoding")
	// The body is JSON built by our own encoder, but it is served to ~57 third-party apps;
	// nosniff costs a header and removes content-type confusion as a question.
	hdr.Set("X-Content-Type-Options", "nosniff")
	// A REAL ETag here, unlike the identity endpoint's deliberately-not-an-ETag revision
	// header. An ETag is a cache validator, and a validator is only dangerous on a body
	// that differs between callers; this body is identical for everyone, and Revision is
	// literally the sha256 of these exact bytes, which is what a strong ETag is supposed to
	// be. It lets a 300s-cached asset revalidate into a 304 instead of re-sending ~5KB.
	hdr.Set("ETag", `"`+snap.Revision+`"`)
	hdr.Set("X-Catalyst-Nav-Revision", snap.Revision)
	if !snap.BuiltAt.IsZero() {
		hdr.Set("X-Catalyst-Nav-Built-At", snap.BuiltAt.UTC().Format(time.RFC3339))
	}

	// Conditional request support, so the ETag above is not decorative. Checked AFTER the
	// headers are set, because a 304 must carry the same validators as the 200 it stands in
	// for.
	if match := r.Header.Get("If-None-Match"); match != "" && etagMatches(match, snap.Revision) {
		h.count("not_modified")
		hdr.Del("Content-Length")
		hdr.Del("Content-Type")
		w.WriteHeader(http.StatusNotModified)
		return
	}

	h.count("ok")
	w.WriteHeader(http.StatusOK)
	if r.Method == http.MethodHead {
		return
	}
	_, _ = w.Write(body)
}

// etagMatches reports whether an If-None-Match header names our current revision.
//
// Handles the `*` wildcard and a comma-separated list, and tolerates the `W/` weak prefix a
// proxy may add — a mismatch here is not a correctness bug (it just re-sends the body) but a
// FALSE match would serve a 304 for content that changed, so the comparison is on the quoted
// revision and nothing looser.
func etagMatches(header, revision string) bool {
	want := `"` + revision + `"`
	for len(header) > 0 {
		// Split on the next comma by hand rather than strings.Split, to avoid allocating
		// on a hot path that runs on every themed pageview.
		var tok string
		if i := indexByte(header, ','); i >= 0 {
			tok, header = header[:i], header[i+1:]
		} else {
			tok, header = header, ""
		}
		tok = trimSpace(tok)
		if tok == "*" || tok == want {
			return true
		}
		if len(tok) > 2 && tok[0] == 'W' && tok[1] == '/' && tok[2:] == want {
			return true
		}
	}
	return false
}

func indexByte(s string, b byte) int {
	for i := 0; i < len(s); i++ {
		if s[i] == b {
			return i
		}
	}
	return -1
}

func trimSpace(s string) string {
	for len(s) > 0 && (s[0] == ' ' || s[0] == '\t') {
		s = s[1:]
	}
	for len(s) > 0 && (s[len(s)-1] == ' ' || s[len(s)-1] == '\t') {
		s = s[:len(s)-1]
	}
	return s
}
