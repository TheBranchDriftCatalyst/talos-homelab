// Package navserve is the authenticated, per-identity manifest endpoint — phase 3 of the
// catalyst-nav strangler fig.
//
// WHAT PROBLEM THIS SOLVES. The manifest today is a static catalyst-nav.json written by a
// sidecar and served by nginx under /catalyst/, with no authentication of any kind. It
// enumerates every internal hostname in the cluster, and on 2026-09-26 it was confirmed
// readable from the public internet — infrastructure/base/themepark/asset-route.yaml carries
// the whole writeup and the two controls (HostRegexp + lan-only) added afterwards. Those
// controls make the file LAN-only. They cannot make it per-identity, because a file has no
// idea who is asking. This endpoint can.
//
// ── THREAT MODEL ─────────────────────────────────────────────────────────────────────────────
//
// The identity in a response comes from request headers, and request headers are client input.
// Here is exactly what is and is not trustworthy, and what each control actually buys.
//
// WHO SETS THE HEADERS LEGITIMATELY. infrastructure/base/authentik/middleware.yaml:13-24
// declares X-authentik-username / -groups / -uid / -email / -jwt in the forward-auth
// middleware's authResponseHeaders. Traefik calls the Authentik outpost, the outpost answers
// with those headers, and Traefik copies them onto the request it forwards to the backend —
// REPLACING whatever the client sent under those names. So a request that genuinely traversed
// the forward-auth middleware carries groups Authentik vouched for.
//
// THE ATTACK. A client that reaches this endpoint WITHOUT traversing that middleware — an
// in-cluster pod talking to the Service directly, a compromised workload, anything that can
// open a TCP connection to the pod IP — sets X-authentik-groups to whatever it likes and is
// indistinguishable, at this layer, from the proxy. There is no header a plain HTTP handler can
// inspect to tell the two apart. Claiming otherwise would be the lie; so the defence is
// layered, and the layers are in descending order of how much they actually do:
//
//  1. NETWORK (primary, and the one that is load-bearing). CiliumNetworkPolicy in
//     operator/cilium-network-policy.yaml default-denies ingress to this namespace and permits
//     the manifest port only fromEndpoints in the `traefik` namespace. An arbitrary pod
//     therefore cannot reach the port at all, spoofed headers or not. This is the same control
//     the asset route leans on (lan-only), one layer further in, and it is the reason the
//     header-level checks below are defence in depth rather than the defence.
//
//  2. PROXY ATTESTATION (optional, off until phase 4 wires it). If AttestationSecret is set,
//     a request must carry that exact value in AttestationHeader or its identity headers are
//     DISCARDED and it is served as Anonymous. The secret is injected by a Traefik
//     customRequestHeaders middleware, which a client cannot forge without reading the
//     cluster's Secret. Left unconfigured by default because wiring the middleware is phase
//     4's job and a half-wired secret would silently anonymise every real user.
//
//  3. FAIL-CLOSED DEFAULT (always on, and the reason a spoof is not a catastrophe). There is
//     no code path IN THIS HANDLER that serves the UNFILTERED manifest. Every response is
//     filtered through an identity, and the identity for a request with no usable headers is
//     visibility.Anonymous() — a member of nothing, which sees only entries and groups that
//     declared no visibility at all. A spoofer therefore cannot gain by OMITTING headers, and
//     the most they gain by ADDING them is the restricted sections — never more than the
//     public manifest already hands to every LAN browser today. The exposure strictly shrinks
//     relative to the thing being replaced.
//
// THE UNFILTERED MANIFEST IS SERVED, BUT NOT FROM HERE. public.go answers the public path on
// its own listener (port 8083, its own Service, its own route with NO forward-auth) because
// the 21 themed hosts without forward-auth depend on it. An earlier revision of this comment
// said flatly that "there is no code path that serves the UNFILTERED manifest"; that was true
// of the whole operator then and is true only of THIS HANDLER now. The boundary to reason
// about is therefore per-listener: the identity endpoint has no unfiltered path, the public
// endpoint has no filtered one, and the public endpoint reads no request headers at all so
// there is nothing on it to spoof. See public.go for why its exposure is unchanged from the
// static file it replaced.
//
// WHAT IS DELIBERATELY NOT DONE. X-authentik-jwt is a signed assertion and verifying it
// against Authentik's JWKS would give a cryptographic trust root instead of a network one.
// That is the correct long-term answer and it is not this phase: it needs egress to Authentik
// (currently denied by the operator's own network policy), a JWKS cache with rotation, and a
// decision about what to do when Authentik is down — on a cosmetic nav bar, where the answer
// must be "render the public subset", so the fail-closed default above does the work anyway.
// Filed as the follow-up, not pretended away.
//
// ── CACHING ──────────────────────────────────────────────────────────────────────────────────
//
// THE TRAP THIS ENDPOINT EXISTS TO AVOID. infrastructure/base/themepark/middlewares.yaml
// defines catalyst-asset-cache, which stamps
//
//	Cache-Control: public, max-age=300, stale-while-revalidate=3600
//
// onto everything served under the /catalyst/ path prefix, via customResponseHeaders — which
// OVERWRITE whatever the backend set. A per-identity body behind that is one user's nav served
// to the next user for five minutes. Two structural choices keep it impossible:
//
//   - The default path is OUTSIDE /catalyst/. `PathPrefix(`/catalyst/`)` cannot match
//     /catalyst-nav/..., so the manifest route cannot pick up the asset-cache middleware by
//     being adjacent to the assets. The static CSS/JS/fonts stay exactly where they are,
//     public and cacheable, untouched.
//   - Every response — success, 404, 405, 503 — carries `Cache-Control: private, no-store`
//     before anything else is written. Written FIRST, on every path, because the one that
//     gets forgotten is always the error path, and a cached 503 blanks the bar for everyone
//     behind that cache.
//
// Vary names BOTH halves of the chain, which is subtler than it looks. Between Traefik and
// this pod the body varies by the injected group header. Between the browser and Traefik those
// headers do not exist yet — there the body varies by the SESSION COOKIE, since that is what
// the outpost turns into groups. A cache at either hop has to be told the right thing, so both
// are listed.
//
// ── DEGRADING ────────────────────────────────────────────────────────────────────────────────
//
// catalyst-nav.js is explicit that the bar "is cosmetic: it must never surface an error into a
// third-party app", and it retries a failed manifest fetch three times then goes quiet. So
// every failure here is an ordinary HTTP status with an empty-ish body and no detail, never a
// stack trace and never an HTML error page: the client renders no bar and the host application
// is untouched.
package navserve

import (
	"context"
	"crypto/subtle"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/prometheus/client_golang/prometheus"

	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/navmodel"
	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/visibility"
)

// Defaults for Config. Exported so the Deployment's env defaults and the tests cannot drift
// from each other silently.
const (
	// DefaultPath is deliberately NOT under /catalyst/. See the caching section above: the
	// asset-cache middleware is attached by path prefix, so staying outside that prefix is
	// what makes a public cache on this response structurally impossible rather than merely
	// discouraged. Phase 4 routes this prefix to the operator's Service; no IngressRoute
	// exists yet.
	DefaultPath = "/catalyst-nav/v1/manifest.json"

	// DefaultGroupsHeader / DefaultUsernameHeader are the names Authentik's outpost sets and
	// infrastructure/base/authentik/middleware.yaml propagates.
	DefaultGroupsHeader   = "X-authentik-groups"
	DefaultUsernameHeader = "X-authentik-username"

	// DefaultGroupSeparator is what Authentik's proxy provider joins group names with.
	//
	// NOT also splitting on "," even though some deployments configure it that way: a
	// comma is a legal character in an Authentik group name, so splitting on it
	// speculatively could shatter one real group into two names that match nothing. Getting
	// the separator wrong fails CLOSED — the whole joined string is read as a single group
	// name, matches no allow-list, and the user sees the public subset — which is a
	// cosmetic degradation, whereas an over-eager split is a correctness bug in the
	// direction of confusion. Override with NAV_GROUP_SEPARATOR if the outpost differs.
	DefaultGroupSeparator = "|"

	// DefaultAttestationHeader carries the shared secret from the Traefik middleware phase 4
	// adds. Non-Authentik name on purpose: it is OUR control, not something the outpost
	// knows about, and naming it X-authentik-* would imply the outpost vouches for it.
	DefaultAttestationHeader = "X-Catalyst-Nav-Proxy"
)

// Config is the server's knobs. The zero value is usable: Handler fills every empty field
// with the Default* above.
type Config struct {
	Path              string
	GroupsHeader      string
	UsernameHeader    string
	GroupSeparator    string
	AttestationHeader string

	// AttestationSecret empty means attestation is NOT required — control 2 in the threat
	// model is off and the network policy is doing the work alone. Set it only together with
	// the Traefik middleware that injects it, or every real user is anonymised.
	AttestationSecret string
}

func (c Config) withDefaults() Config {
	if c.Path == "" {
		c.Path = DefaultPath
	}
	if c.GroupsHeader == "" {
		c.GroupsHeader = DefaultGroupsHeader
	}
	if c.UsernameHeader == "" {
		c.UsernameHeader = DefaultUsernameHeader
	}
	if c.GroupSeparator == "" {
		c.GroupSeparator = DefaultGroupSeparator
	}
	if c.AttestationHeader == "" {
		c.AttestationHeader = DefaultAttestationHeader
	}
	return c
}

// Source is what the handler reads its model from. An interface so a test can hand over a
// fixed Snapshot without a manager, a cache or a cluster.
type Source interface {
	Snapshot() *Snapshot
}

// Handler serves the per-identity manifest.
type Handler struct {
	cfg    Config
	src    Source
	vary   string
	served *prometheus.CounterVec
}

// NewHandler wires a Source to a Config. reg may be nil, which disables metrics — the right
// default for tests, which would otherwise fight over a global registry.
func NewHandler(src Source, cfg Config, reg prometheus.Registerer) *Handler {
	cfg = cfg.withDefaults()
	h := &Handler{
		cfg: cfg,
		src: src,
		// Cookie FIRST because it is the one that matters at the outer hop, where the
		// group headers do not exist yet. See the caching section in the package comment.
		vary: strings.Join([]string{"Cookie", cfg.GroupsHeader, cfg.AttestationHeader}, ", "),
	}
	if reg != nil {
		h.served = prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "catalyst_nav_manifest_requests_total",
			Help: "Per-identity nav manifest requests by outcome. " +
				"outcome=unattested counts requests whose identity headers were " +
				"discarded for failing proxy attestation — a non-zero rate there " +
				"means something is talking to this endpoint off the proxy path.",
		}, []string{"outcome"})
		reg.MustRegister(h.served)
	}
	return h
}

// Path is where this handler answers, after defaulting. Used by the Server to mount it and by
// the tests so the path cannot drift between them.
func (h *Handler) Path() string { return h.cfg.Path }

func (h *Handler) count(outcome string) {
	if h.served != nil {
		h.served.WithLabelValues(outcome).Inc()
	}
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	// BEFORE the routing and method checks, not after: a 404 or 405 that slips out without
	// these headers is as cacheable as a 200, and it is the path nobody looks at.
	h.writeUncacheable(w)

	if r.URL.Path != h.cfg.Path {
		h.count("not_found")
		w.WriteHeader(http.StatusNotFound)
		return
	}
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		h.count("method_not_allowed")
		w.Header().Set("Allow", "GET, HEAD")
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}

	snap := h.src.Snapshot()
	if snap == nil || snap.Manifest == nil {
		// Before the first reconcile. 503 rather than an empty manifest: an empty
		// manifest is a VALID document that would make the client build a bar with
		// nothing in it and stop retrying, whereas a 503 is what its three-try backoff
		// exists for. Same reasoning discover.sh gives for never publishing an empty
		// nav on a failed refresh.
		h.count("no_snapshot")
		w.Header().Set("Retry-After", "2")
		w.WriteHeader(http.StatusServiceUnavailable)
		return
	}

	id, attested := h.identity(r)
	body := navmodel.Encode(visibility.Filter(snap.Manifest, snap.Index, id))

	switch {
	case !attested:
		h.count("unattested")
	case len(id.Groups()) == 0:
		h.count("anonymous")
	default:
		h.count("identified")
	}

	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Length", strconv.Itoa(len(body)))
	// Provenance only — see Snapshot.Revision for why this is not an ETag.
	w.Header().Set("X-Catalyst-Nav-Revision", snap.Revision)
	if !snap.BuiltAt.IsZero() {
		w.Header().Set("X-Catalyst-Nav-Built-At", snap.BuiltAt.UTC().Format(time.RFC3339))
	}
	w.WriteHeader(http.StatusOK)
	if r.Method == http.MethodHead {
		return
	}
	_, _ = w.Write(body)
}

// writeUncacheable stamps the headers that keep a per-identity body out of every cache.
//
// `private, no-store` exactly, and nothing softer. no-store forbids storing the response at
// all, which is the only directive strong enough here — max-age=0 or must-revalidate would
// still permit a shared cache to HOLD one user's nav and merely require it to revalidate
// before reuse, and a revalidation that returns 304 to the wrong user is the same bug.
// `private` is belt to that brace: it bars a shared cache even from a response that somehow
// lost no-store downstream.
//
// Pragma and Expires are set for the same reason catalyst-asset-cache blanks them: nginx sends
// both, they are legacy but still honoured, and either one left over from an upstream hop
// would override the modern header.
func (h *Handler) writeUncacheable(w http.ResponseWriter) {
	hdr := w.Header()
	hdr.Set("Cache-Control", "private, no-store")
	hdr.Set("Pragma", "no-cache")
	hdr.Set("Expires", "0")
	hdr.Set("Vary", h.vary)
	// The body is JSON built by our own encoder, but it is served to ~40 third-party apps;
	// nosniff costs a header and removes content-type confusion as a question.
	hdr.Set("X-Content-Type-Options", "nosniff")
}

// identity derives the caller from the request, and reports whether the derivation was
// attested.
//
// The attestation check comes FIRST and is total: a failed check does not produce a partial
// identity, an error, or a 401 — it produces Anonymous(), which is the public subset. See
// control 3 in the threat model for why that is the safe failure and not a shrug.
func (h *Handler) identity(r *http.Request) (visibility.Identity, bool) {
	if h.cfg.AttestationSecret != "" {
		got := r.Header.Get(h.cfg.AttestationHeader)
		// Constant-time: the comparison is against a secret, and a byte-at-a-time
		// compare on a header an attacker controls is a byte-at-a-time oracle for it.
		if subtle.ConstantTimeCompare([]byte(got), []byte(h.cfg.AttestationSecret)) != 1 {
			return visibility.Anonymous(), false
		}
	}
	// Header.Values, not Header.Get: a repeated header is legal, and taking only the first
	// would silently drop groups. Every value is split and the results unioned.
	var groups []string
	for _, v := range r.Header.Values(h.cfg.GroupsHeader) {
		groups = append(groups, strings.Split(v, h.cfg.GroupSeparator)...)
	}
	return visibility.NewIdentity(r.Header.Get(h.cfg.UsernameHeader), groups, true), true
}

// Server runs the handler on its own listener.
//
// Start's signature is exactly sigs.k8s.io/controller-runtime's manager.Runnable —
// `Start(context.Context) error` — so the manager owns this listener's lifecycle (graceful
// shutdown on the same signal that stops the controller) while this package imports nothing
// from controller-runtime. That matters for the tests: a handler test needs neither a manager
// nor a scheme.
type Server struct {
	Addr    string
	Handler http.Handler
}

// Start listens until ctx is cancelled, then drains.
func (s *Server) Start(ctx context.Context) error {
	mux := http.NewServeMux()
	mux.Handle("/", s.Handler)
	srv := &http.Server{
		Addr:    s.Addr,
		Handler: mux,
		// Modest timeouts: the handler does no I/O beyond an atomic load, so anything
		// slow is a stuck client holding a goroutine.
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      15 * time.Second,
		IdleTimeout:       60 * time.Second,
	}
	errCh := make(chan error, 1)
	go func() {
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			errCh <- err
			return
		}
		errCh <- nil
	}()
	select {
	case err := <-errCh:
		return err
	case <-ctx.Done():
		return srv.Close()
	}
}
