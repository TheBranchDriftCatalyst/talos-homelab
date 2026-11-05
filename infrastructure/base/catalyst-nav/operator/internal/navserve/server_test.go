package navserve

// Specs for the endpoint. Two of these are the reason the package exists and are called out in
// the phase brief: a per-identity response must never be cacheable, and two identities in
// sequence must never be able to receive each other's body. Both are written so that softening
// the implementation — not just deleting it — turns them red.

import (
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/navmodel"
	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/visibility"
)

type fixedSource struct{ snap *Snapshot }

func (f fixedSource) Snapshot() *Snapshot { return f.snap }

// twoTenants builds a model with one group per tenant, each restricted to that tenant's
// Authentik group, plus one public group everybody sees.
func twoTenants() *Snapshot {
	m := &navmodel.Manifest{
		Groups: []navmodel.Group{
			{Name: "Media", NavGroupRef: "media", Items: []navmodel.Item{
				{Name: "Plex", Weight: 10, Href: "https://plex.talos00/", Themed: true},
			}},
			{Name: "Infrastructure", NavGroupRef: "infrastructure", Items: []navmodel.Item{
				{Name: "Argocd", Weight: 50, Href: "https://argocd.talos00/", Themed: true},
			}},
			{Name: "Home & Tools", NavGroupRef: "home", Items: []navmodel.Item{
				{Name: "Homepage", Weight: 50, Href: "https://home.talos00/", Themed: true},
			}},
		},
	}
	return &Snapshot{
		Manifest: m,
		Index: visibility.Index{
			Groups: map[string]visibility.Rule{
				"media":          visibility.NewRule([]string{"catalyst-media"}),
				"infrastructure": visibility.NewRule([]string{"catalyst-infra"}),
				// "home" deliberately carries no rule: the public baseline.
			},
		},
		Revision: "deadbeef",
		BuiltAt:  time.Unix(1_800_000_000, 0),
	}
}

func handler(src Source, cfg Config) *Handler {
	// reg nil: the metrics are registered against controller-runtime's global registry in
	// main, and a test that registered them too would fight every other test in the
	// process for the collector name.
	return NewHandler(src, cfg, nil)
}

// get issues a request with the given group header value ("" = header absent).
func get(t *testing.T, h *Handler, groups string, extra map[string]string) *httptest.ResponseRecorder {
	t.Helper()
	r := httptest.NewRequest(http.MethodGet, h.Path(), nil)
	if groups != "" {
		r.Header.Set(DefaultGroupsHeader, groups)
	}
	for k, v := range extra {
		r.Header.Set(k, v)
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	return w
}

// ── THE CACHE TEST ──────────────────────────────────────────────────────────────────────────

// reporter is the part of *testing.T's surface that assertUncacheable needs, so the assertion can be
// aimed at a fake and checked.
type reporter interface {
	Helper()
	Errorf(format string, args ...any)
	Fatalf(format string, args ...any)
}

// failRecorder records that the assertion fired without aborting the goroutine. Fatalf does
// NOT stop execution here, unlike the real thing — harmless, because the only input that
// reaches a Fatalf is a missing Cache-Control and the self-check supplies one.
type failRecorder struct{ failed bool }

func (r *failRecorder) Helper()               {}
func (r *failRecorder) Errorf(string, ...any) { r.failed = true }
func (r *failRecorder) Fatalf(string, ...any) { r.failed = true }

// assertUncacheable fails if anything about the response would let a cache — shared or
// private — hand this body to a second request.
//
// Written as a property rather than a string comparison on purpose: `Cache-Control:
// private, max-age=0, must-revalidate` would pass a naive "does it mention private" check
// while still permitting a shared cache to STORE one user's nav and revalidate it for the
// next, and a 304 to the wrong user is the same bug as a 200 to the wrong user.
//
// Takes a `reporter` rather than *testing.T so TestTheCacheAssertionCanFail can point it at a
// recorder and prove the guard rejects the asset-cache header. Pointing it at a zero-valued
// testing.T instead would be relying on undefined behaviour in the testing package to test our
// own test.
func assertUncacheable(t reporter, w *httptest.ResponseRecorder, what string) {
	t.Helper()
	cc := strings.ToLower(w.Header().Get("Cache-Control"))
	if cc == "" {
		t.Fatalf("%s: no Cache-Control at all — the response is heuristically cacheable", what)
	}
	if !strings.Contains(cc, "no-store") {
		t.Errorf("%s: Cache-Control %q does not forbid storage (no-store)", what, cc)
	}
	if !strings.Contains(cc, "private") {
		t.Errorf("%s: Cache-Control %q does not bar shared caches (private)", what, cc)
	}
	for _, banned := range []string{"public", "s-maxage", "stale-while-revalidate", "immutable"} {
		if strings.Contains(cc, banned) {
			t.Errorf("%s: Cache-Control %q contains %q, which permits reuse", what, cc, banned)
		}
	}
	// A positive max-age alongside no-store is contradictory, and an intermediary that
	// honours the wrong half of it is a cross-identity leak.
	for _, part := range strings.Split(cc, ",") {
		part = strings.TrimSpace(part)
		if v, ok := strings.CutPrefix(part, "max-age="); ok {
			if n, err := strconv.Atoi(v); err != nil || n > 0 {
				t.Errorf("%s: Cache-Control carries %q", what, part)
			}
		}
	}

	// The legacy pair, for the reason catalyst-asset-cache blanks them: nginx sends both and
	// either one surviving an upstream hop overrides Cache-Control.
	if p := strings.ToLower(w.Header().Get("Pragma")); p != "no-cache" {
		t.Errorf("%s: Pragma = %q, want no-cache", what, p)
	}
	if e := w.Header().Get("Expires"); e != "0" {
		t.Errorf("%s: Expires = %q, want 0", what, e)
	}

	// Vary must name BOTH hops. Between Traefik and this pod the body varies by the
	// injected group header; between the browser and Traefik those headers do not exist
	// yet and the body varies by the session cookie the outpost resolves into groups.
	vary := strings.ToLower(w.Header().Get("Vary"))
	for _, needed := range []string{"cookie", strings.ToLower(DefaultGroupsHeader)} {
		if !strings.Contains(vary, needed) {
			t.Errorf("%s: Vary %q does not name %q", what, vary, needed)
		}
	}

	// A cache validator on a per-identity body invites a 304 that reuses the wrong body.
	for _, validator := range []string{"ETag", "Last-Modified"} {
		if v := w.Header().Get(validator); v != "" {
			t.Errorf("%s: %s = %q — a validator on a per-identity response permits "+
				"revalidated reuse", what, validator, v)
		}
	}
}

func TestEveryResponseIsUncacheable(t *testing.T) {
	h := handler(fixedSource{twoTenants()}, Config{})

	assertUncacheable(t, get(t, h, "catalyst-media", nil), "200 identified")
	assertUncacheable(t, get(t, h, "", nil), "200 anonymous")

	// The error paths, which are the ones that get forgotten. A cached 503 blanks the bar
	// for everyone behind that cache until it expires.
	assertUncacheable(t, get(t, handler(fixedSource{nil}, Config{}), "", nil), "503 no snapshot")

	r := httptest.NewRequest(http.MethodGet, "/catalyst/resources/catalyst-nav.json", nil)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	assertUncacheable(t, w, "404 wrong path")

	r = httptest.NewRequest(http.MethodPost, h.Path(), nil)
	w = httptest.NewRecorder()
	h.ServeHTTP(w, r)
	assertUncacheable(t, w, "405 wrong method")

	r = httptest.NewRequest(http.MethodHead, h.Path(), nil)
	w = httptest.NewRecorder()
	h.ServeHTTP(w, r)
	assertUncacheable(t, w, "200 HEAD")
}

func TestTheCacheAssertionCanFail(t *testing.T) {
	// The guard above is only worth having if it rejects the thing it exists to reject.
	// `public, max-age=300, stale-while-revalidate=3600` is verbatim what
	// infrastructure/base/themepark/middlewares.yaml stamps on /catalyst/.
	rec := httptest.NewRecorder()
	rec.Header().Set("Cache-Control", "public, max-age=300, stale-while-revalidate=3600")
	rec.Header().Set("Vary", "Cookie, X-authentik-groups")
	rec.Header().Set("Pragma", "no-cache")
	rec.Header().Set("Expires", "0")

	sub := &failRecorder{}
	assertUncacheable(sub, rec, "the asset-cache header")
	if !sub.failed {
		t.Fatal("assertUncacheable accepted the catalyst-asset-cache header — it proves nothing")
	}
}

func TestThePathIsOutsideTheAssetCachePrefix(t *testing.T) {
	// The structural half of the cache defence: catalyst-asset-cache is attached by
	// PathPrefix(`/catalyst/`), so a default path inside that prefix would pick up
	// `public, max-age=300` from the middleware no matter what this handler sets.
	if strings.HasPrefix(DefaultPath, "/catalyst/") {
		t.Fatalf("DefaultPath %q is inside the /catalyst/ asset-cache prefix", DefaultPath)
	}
	if !strings.HasPrefix(DefaultPath, "/") {
		t.Fatalf("DefaultPath %q is not absolute", DefaultPath)
	}
}

// ── THE CROSS-IDENTITY TEST ─────────────────────────────────────────────────────────────────

func TestTwoIdentitiesInSequenceCannotReceiveEachOthersBody(t *testing.T) {
	// One handler, one snapshot, four requests alternating between two identities. Each
	// must see its own restricted section and the public one, and never the other's.
	h := handler(fixedSource{twoTenants()}, Config{})

	mediaA := get(t, h, "catalyst-media", nil).Body.String()
	infraB := get(t, h, "catalyst-infra", nil).Body.String()
	mediaA2 := get(t, h, "catalyst-media", nil).Body.String()
	infraB2 := get(t, h, "catalyst-infra", nil).Body.String()

	if mediaA != mediaA2 {
		t.Errorf("identity A's body changed after B's request:\n %s\n %s", mediaA, mediaA2)
	}
	if infraB != infraB2 {
		t.Errorf("identity B's body changed after A's request:\n %s\n %s", infraB, infraB2)
	}
	if mediaA == infraB {
		t.Fatal("two different identities received the same body")
	}

	if !strings.Contains(mediaA, "plex.talos00") {
		t.Errorf("A did not get its own group: %s", mediaA)
	}
	if strings.Contains(mediaA, "argocd.talos00") {
		t.Errorf("A received B's restricted hostname: %s", mediaA)
	}
	if !strings.Contains(infraB, "argocd.talos00") {
		t.Errorf("B did not get its own group: %s", infraB)
	}
	if strings.Contains(infraB, "plex.talos00") {
		t.Errorf("B received A's restricted hostname: %s", infraB)
	}
	// Both must still see the unrestricted group — filtering is per-rule, not all-or-nothing.
	for name, body := range map[string]string{"A": mediaA, "B": infraB} {
		if !strings.Contains(body, "home.talos00") {
			t.Errorf("%s lost the public group: %s", name, body)
		}
	}
}

func TestAnonymousSeesOnlyTheUnrestrictedGroups(t *testing.T) {
	h := handler(fixedSource{twoTenants()}, Config{})
	body := get(t, h, "", nil).Body.String()

	if strings.Contains(body, "plex.talos00") || strings.Contains(body, "argocd.talos00") {
		t.Fatalf("an identity-less request received restricted hostnames: %s", body)
	}
	if !strings.Contains(body, "home.talos00") {
		t.Fatalf("the public group was withheld from an anonymous caller: %s", body)
	}
}

func TestThereIsNoCodePathThatServesTheUnfilteredManifest(t *testing.T) {
	// The fail-closed property: no header combination, including none at all and including
	// a deliberately absurd one, yields both restricted sections. If a future "admin"
	// shortcut is added, this is the test that has to be argued with.
	h := handler(fixedSource{twoTenants()}, Config{})
	for _, hdrs := range []map[string]string{
		nil,
		{DefaultGroupsHeader: ""},
		{DefaultUsernameHeader: "akadmin"},
		{"X-authentik-uid": "root", "X-authentik-jwt": "whatever"},
		{"Authorization": "Bearer anything"},
	} {
		body := get(t, h, "", hdrs).Body.String()
		if strings.Contains(body, "plex.talos00") && strings.Contains(body, "argocd.talos00") {
			t.Fatalf("headers %v produced the unfiltered manifest: %s", hdrs, body)
		}
	}
}

// ── group header parsing ────────────────────────────────────────────────────────────────────

func TestGroupsAreSplitOnTheAuthentikSeparator(t *testing.T) {
	h := handler(fixedSource{twoTenants()}, Config{})
	body := get(t, h, "unrelated|catalyst-media|another", nil).Body.String()
	if !strings.Contains(body, "plex.talos00") {
		t.Fatalf("a pipe-joined membership was not parsed: %s", body)
	}
}

func TestRepeatedGroupHeadersAreAllRead(t *testing.T) {
	// A repeated header is legal; Header.Get would silently take only the first and drop a
	// user's membership, which presents as "my section vanished sometimes".
	r := httptest.NewRequest(http.MethodGet, DefaultPath, nil)
	r.Header.Add(DefaultGroupsHeader, "unrelated")
	r.Header.Add(DefaultGroupsHeader, "catalyst-media")
	w := httptest.NewRecorder()
	handler(fixedSource{twoTenants()}, Config{}).ServeHTTP(w, r)

	if !strings.Contains(w.Body.String(), "plex.talos00") {
		t.Fatalf("the second header value was dropped: %s", w.Body.String())
	}
}

func TestAWrongSeparatorFailsClosedRatherThanWidening(t *testing.T) {
	// If the outpost is configured to join with "," and we split on "|", the whole string
	// reads as one group name, matches nothing, and the caller sees the public subset. That
	// is a cosmetic degradation. The failure that must NOT happen is the reverse — a
	// speculative comma split shattering a legitimate group name that contains a comma.
	h := handler(fixedSource{twoTenants()}, Config{})
	body := get(t, h, "catalyst-media,catalyst-infra", nil).Body.String()
	if strings.Contains(body, "plex.talos00") || strings.Contains(body, "argocd.talos00") {
		t.Fatalf("a comma-joined header widened access: %s", body)
	}

	// ...and a deployment that knows its separator can say so.
	h = handler(fixedSource{twoTenants()}, Config{GroupSeparator: ","})
	if body := get(t, h, "catalyst-media,x", nil).Body.String(); !strings.Contains(body, "plex.talos00") {
		t.Fatalf("GroupSeparator was not honoured: %s", body)
	}
}

// ── proxy attestation ───────────────────────────────────────────────────────────────────────

func TestUnattestedGroupHeadersAreDiscarded(t *testing.T) {
	// Control 2 in the threat model. With a secret configured, a caller that reaches the
	// endpoint off the proxy path — the in-cluster spoof — gets the public subset no matter
	// what groups it claims.
	h := handler(fixedSource{twoTenants()}, Config{AttestationSecret: "s3cret"})

	for _, hdrs := range []map[string]string{
		nil,
		{DefaultAttestationHeader: ""},
		{DefaultAttestationHeader: "wrong"},
		{DefaultAttestationHeader: "s3cre"},   // prefix
		{DefaultAttestationHeader: "s3cretx"}, // extension
	} {
		w := get(t, h, "catalyst-media|catalyst-infra", hdrs)
		if w.Code != http.StatusOK {
			t.Errorf("attestation %v: status = %d, want 200 (degrade, never error)", hdrs, w.Code)
		}
		if body := w.Body.String(); strings.Contains(body, "plex.talos00") {
			t.Errorf("attestation %v: spoofed groups were honoured: %s", hdrs, body)
		}
	}

	// The real proxy still works.
	w := get(t, h, "catalyst-media", map[string]string{DefaultAttestationHeader: "s3cret"})
	if !strings.Contains(w.Body.String(), "plex.talos00") {
		t.Fatalf("an attested request was anonymised: %s", w.Body.String())
	}
}

func TestAttestationOffMeansHeadersAreTakenAtFaceValue(t *testing.T) {
	// Stated as a test because it is the shipped default and the honest reading of it: with
	// no secret configured the ONLY thing standing between a pod and a spoofed identity is
	// the CiliumNetworkPolicy. If this test ever needs changing, the network policy has
	// stopped being the primary control and the threat model needs rewriting.
	h := handler(fixedSource{twoTenants()}, Config{})
	if !strings.Contains(get(t, h, "catalyst-media", nil).Body.String(), "plex.talos00") {
		t.Fatal("groups were discarded with no attestation configured; the default changed")
	}
}

// ── degrading, methods, routing ─────────────────────────────────────────────────────────────

func TestNoSnapshotIs503AndNotAnEmptyManifest(t *testing.T) {
	// Before the first reconcile. An empty manifest is a VALID document: the client would
	// build an empty bar and stop retrying. A 503 is what its three-try backoff is for.
	w := get(t, handler(fixedSource{nil}, Config{}), "", nil)
	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503", w.Code)
	}
	if w.Body.Len() != 0 {
		t.Errorf("body = %q, want empty — never a detail page inside a third-party app",
			w.Body.String())
	}
	if w.Header().Get("Retry-After") == "" {
		t.Error("no Retry-After on a 503")
	}
}

func TestFailureBodiesCarryNoDetail(t *testing.T) {
	// The bar "must never surface an error into a third-party app" (catalyst-nav.js). An
	// error page rendered inside ~40 apps would be worse than no bar.
	h := handler(fixedSource{twoTenants()}, Config{})

	r := httptest.NewRequest(http.MethodPost, h.Path(), nil)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	if w.Code != http.StatusMethodNotAllowed {
		t.Fatalf("status = %d, want 405", w.Code)
	}
	if w.Header().Get("Allow") != "GET, HEAD" {
		t.Errorf("Allow = %q", w.Header().Get("Allow"))
	}
	if w.Body.Len() != 0 {
		t.Errorf("405 body = %q, want empty", w.Body.String())
	}
}

func TestOnlyTheConfiguredPathAnswers(t *testing.T) {
	h := handler(fixedSource{twoTenants()}, Config{})
	for _, path := range []string{
		"/",
		"/catalyst/resources/catalyst-nav.json",
		DefaultPath + "/extra",
		strings.TrimSuffix(DefaultPath, ".json"),
	} {
		r := httptest.NewRequest(http.MethodGet, path, nil)
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		if w.Code != http.StatusNotFound {
			t.Errorf("GET %s: status = %d, want 404", path, w.Code)
		}
	}
}

func TestHeadReturnsTheHeadersAndNoBody(t *testing.T) {
	r := httptest.NewRequest(http.MethodHead, DefaultPath, nil)
	r.Header.Set(DefaultGroupsHeader, "catalyst-media")
	w := httptest.NewRecorder()
	handler(fixedSource{twoTenants()}, Config{}).ServeHTTP(w, r)

	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", w.Code)
	}
	if w.Body.Len() != 0 {
		t.Errorf("HEAD returned a body: %q", w.Body.String())
	}
	// Content-Length must still describe the body a GET would return, or a client cannot
	// use HEAD to size the fetch.
	if cl := w.Header().Get("Content-Length"); cl == "" || cl == "0" {
		t.Errorf("Content-Length = %q on HEAD", cl)
	}
}

func TestContentTypeAndLengthMatchTheBody(t *testing.T) {
	w := get(t, handler(fixedSource{twoTenants()}, Config{}), "catalyst-media", nil)
	if ct := w.Header().Get("Content-Type"); ct != "application/json" {
		t.Errorf("Content-Type = %q", ct)
	}
	if got, want := w.Header().Get("Content-Length"), strconv.Itoa(w.Body.Len()); got != want {
		t.Errorf("Content-Length = %q, body is %s bytes", got, want)
	}
	if w.Header().Get("X-Content-Type-Options") != "nosniff" {
		t.Error("no nosniff on a JSON document served into ~40 third-party apps")
	}
}

func TestRevisionIsReportedForDiffingAgainstTheConfigMap(t *testing.T) {
	w := get(t, handler(fixedSource{twoTenants()}, Config{}), "", nil)
	if got := w.Header().Get("X-Catalyst-Nav-Revision"); got != "deadbeef" {
		t.Errorf("X-Catalyst-Nav-Revision = %q, want the snapshot's revision", got)
	}
}

func TestGarbageHeadersDoNotProduceA500(t *testing.T) {
	h := handler(fixedSource{twoTenants()}, Config{})
	for _, v := range []string{
		"|||", " | | ", strings.Repeat("a|", 4096), "\x00weird", "catalyst-media|",
	} {
		w := get(t, h, v, nil)
		if w.Code != http.StatusOK {
			t.Errorf("groups %q: status = %d, want 200", v, w.Code)
		}
	}
}
