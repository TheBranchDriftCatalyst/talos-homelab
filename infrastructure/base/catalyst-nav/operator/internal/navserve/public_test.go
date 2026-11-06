package navserve

// The public endpoint's contract, which is a MIGRATION contract: it must serve what the
// deleted sidecar served. Three properties carry that, and each one has a specific way of
// failing silently, which is why each is asserted rather than reasoned about:
//
//   1. UNFILTERED — identical bytes to navmodel.Encode of the whole manifest, no matter what
//      the caller presents. Filtering here would empty the bar on the 21 hosts with no
//      forward-auth, and it would do it only once some NavGroup declared spec.visibility, i.e.
//      long after the change that caused it.
//   2. CACHEABLE — `public, max-age=...` on the 200 and `no-store` on the errors. Getting this
//      backwards is invisible in a browser and shows up as either operator CPU (uncacheable
//      200) or a bar that stays blank for five minutes after a blip (cacheable 503).
//   3. HEADER-BLIND — the response does not change when identity headers are supplied. This is
//      the structural claim public.go makes, so it gets a test rather than a comment.

import (
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"
	"time"

	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/navmodel"
	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/visibility"
)

// publicFixture builds a manifest with a RESTRICTED group, so "unfiltered" is a claim with
// teeth: if the handler ever grew a filter, this group is what would vanish.
func publicFixture(t *testing.T) (*Store, []byte) {
	t.Helper()
	m := &navmodel.Manifest{
		Groups: []navmodel.Group{
			{Name: "Public", Items: []navmodel.Item{
				{Name: "Grafana", Weight: 10, Href: "https://grafana.talos00/", Themed: true},
			}},
			{Name: "Admin", NavGroupRef: "admin", Items: []navmodel.Item{
				{Name: "ArgoCD", Weight: 20, Href: "https://argocd.talos00/", Themed: true},
			}},
		},
	}
	// An index that restricts the "admin" group to an Authentik group nobody in these tests
	// is a member of. visibility.Filter would drop it; this handler must not.
	idx := visibility.Index{Groups: map[string]visibility.Rule{
		"admin": visibility.NewRule([]string{"talos-admins"}),
	}}
	store := &Store{}
	store.Publish(&Snapshot{
		Manifest: m,
		Index:    idx,
		Revision: "deadbeefcafe",
		BuiltAt:  time.Unix(1762400000, 0),
	})
	return store, navmodel.Encode(m)
}

func getPublic(t *testing.T, h http.Handler, path string, hdr map[string]string) *httptest.ResponseRecorder {
	t.Helper()
	r := httptest.NewRequest(http.MethodGet, path, nil)
	for k, v := range hdr {
		r.Header.Set(k, v)
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	return w
}

// TestPublicServesTheUnfilteredManifest is the migration's core assertion: these bytes are the
// ConfigMap's bytes, which the frozen parity gate proves are build_nav.py's bytes.
func TestPublicServesTheUnfilteredManifest(t *testing.T) {
	store, want := publicFixture(t)
	h := NewPublicHandler(store, PublicConfig{}, nil)

	w := getPublic(t, h, DefaultPublicPath, nil)
	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", w.Code)
	}
	if got := w.Body.String(); got != string(want) {
		t.Errorf("body differs from navmodel.Encode\n  got: %s\n want: %s", got, want)
	}
	// The restricted group MUST be present. This is the assertion that fails if a filter
	// is ever introduced here.
	if body := w.Body.String(); !contains(body, `"name":"Admin"`) {
		t.Errorf("the restricted group is missing -- the public endpoint is filtering: %s", body)
	}

	// AND THE FIXTURE MUST BE DISCRIMINATING. Asserting "Admin is present" proves nothing
	// if Admin would survive a filter anyway — the test would pass against a handler that
	// filtered on every request. So assert the contrast directly: the same manifest and
	// index, run through visibility.Filter as the identity endpoint does, DROPS this group.
	// That is what makes the assertion above a real guard rather than a restatement.
	snap := store.Snapshot()
	filtered := navmodel.Encode(visibility.Filter(snap.Manifest, snap.Index, visibility.Anonymous()))
	if contains(string(filtered), `"name":"Admin"`) {
		t.Fatal("the fixture's restricted group survives visibility.Filter, so this test " +
			"cannot distinguish a filtering handler from a non-filtering one")
	}
	if string(filtered) == string(want) {
		t.Fatal("filtered and unfiltered bytes are identical; the fixture proves nothing")
	}
	if got := w.Header().Get("Content-Type"); got != "application/json" {
		t.Errorf("Content-Type = %q", got)
	}
	if got, err := strconv.Atoi(w.Header().Get("Content-Length")); err != nil || got != len(want) {
		t.Errorf("Content-Length = %q, want %d", w.Header().Get("Content-Length"), len(want))
	}
}

// TestPublicIsIdenticalForEveryIdentity is the header-blindness proof. A spoofable header can
// only be a vulnerability if something reads it; this asserts nothing does.
func TestPublicIsIdenticalForEveryIdentity(t *testing.T) {
	store, want := publicFixture(t)
	h := NewPublicHandler(store, PublicConfig{}, nil)

	for name, hdr := range map[string]map[string]string{
		"anonymous":          nil,
		"claims admin group": {DefaultGroupsHeader: "talos-admins"},
		"claims many groups": {DefaultGroupsHeader: "talos-admins|talos-media|wheel"},
		"claims a username":  {DefaultUsernameHeader: "root"},
		"forged attestation": {DefaultAttestationHeader: "whatever"},
		"bogus cookie":       {"Cookie": "authentik_session=forged"},
	} {
		t.Run(name, func(t *testing.T) {
			w := getPublic(t, h, DefaultPublicPath, hdr)
			if w.Code != http.StatusOK {
				t.Fatalf("status = %d, want 200", w.Code)
			}
			if got := w.Body.String(); got != string(want) {
				t.Errorf("body varied with request headers -- the public endpoint "+
					"is reading identity\n  got: %s\n want: %s", got, want)
			}
		})
	}
}

// TestPublicResponseIsCacheable pins the caching asymmetry: cacheable success, uncacheable
// errors. Both halves matter and they fail in opposite, equally quiet ways.
func TestPublicResponseIsCacheable(t *testing.T) {
	store, _ := publicFixture(t)
	h := NewPublicHandler(store, PublicConfig{}, nil)

	w := getPublic(t, h, DefaultPublicPath, nil)
	if got := w.Header().Get("Cache-Control"); got != DefaultPublicCacheControl {
		t.Errorf("200 Cache-Control = %q, want %q", got, DefaultPublicCacheControl)
	}
	// Vary must NOT name Cookie or a group header: the body does not vary by them, and
	// saying it does fragments every shared cache by session.
	if got := w.Header().Get("Vary"); got != "Accept-Encoding" {
		t.Errorf("Vary = %q, want exactly Accept-Encoding", got)
	}
	if got := w.Header().Get("ETag"); got != `"deadbeefcafe"` {
		t.Errorf("ETag = %q", got)
	}
	if got := w.Header().Get("X-Content-Type-Options"); got != "nosniff" {
		t.Errorf("X-Content-Type-Options = %q", got)
	}

	// A 404 must not be cacheable.
	w404 := getPublic(t, h, "/catalyst/resources/nope.json", nil)
	if w404.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", w404.Code)
	}
	if got := w404.Header().Get("Cache-Control"); got != "private, no-store" {
		t.Errorf("404 Cache-Control = %q, want private, no-store", got)
	}
}

// TestPublicBeforeFirstReconcile503s guards the client's retry path. An empty manifest here
// would be a valid document, so catalyst-nav.js would render an empty bar and stop retrying.
func TestPublicBeforeFirstReconcile503s(t *testing.T) {
	h := NewPublicHandler(&Store{}, PublicConfig{}, nil)
	w := getPublic(t, h, DefaultPublicPath, nil)
	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503", w.Code)
	}
	if got := w.Header().Get("Cache-Control"); got != "private, no-store" {
		t.Errorf("503 Cache-Control = %q -- a cached 503 blanks the bar for everyone", got)
	}
	if got := w.Header().Get("Retry-After"); got == "" {
		t.Error("503 carries no Retry-After")
	}
	if w.Body.Len() != 0 {
		t.Errorf("503 has a body (%q); the client must not be able to parse it", w.Body.String())
	}
}

// TestPublicPathIsTheSidecarPath pins the one string that 57 injectors depend on.
func TestPublicPathIsTheSidecarPath(t *testing.T) {
	// The literal the deleted sidecar's nginx served and catalyst-nav.js still requests as
	// MANIFEST_STATIC. If this changes, every catalyst-inject-* middleware in
	// infrastructure/base/themepark/middlewares.yaml must change in the same commit.
	const sidecarPath = "/catalyst/resources/catalyst-nav.json"
	if DefaultPublicPath != sidecarPath {
		t.Fatalf("DefaultPublicPath = %q, want %q", DefaultPublicPath, sidecarPath)
	}
	if got := NewPublicHandler(&Store{}, PublicConfig{}, nil).Path(); got != sidecarPath {
		t.Fatalf("Path() = %q, want %q", got, sidecarPath)
	}
}

func TestPublicConditionalRequest(t *testing.T) {
	store, want := publicFixture(t)
	h := NewPublicHandler(store, PublicConfig{}, nil)

	for name, tc := range map[string]struct {
		inm      string
		wantCode int
	}{
		"matching etag":      {`"deadbeefcafe"`, http.StatusNotModified},
		"weak matching etag": {`W/"deadbeefcafe"`, http.StatusNotModified},
		"wildcard":           {`*`, http.StatusNotModified},
		"in a list":          {`"other", "deadbeefcafe"`, http.StatusNotModified},
		"stale etag":         {`"0000"`, http.StatusOK},
		"empty":              {``, http.StatusOK},
		// A prefix of the real revision must NOT match, or a truncating proxy would
		// pin a stale manifest.
		"prefix of the etag": {`"deadbeef"`, http.StatusOK},
	} {
		t.Run(name, func(t *testing.T) {
			hdr := map[string]string{}
			if tc.inm != "" {
				hdr["If-None-Match"] = tc.inm
			}
			w := getPublic(t, h, DefaultPublicPath, hdr)
			if w.Code != tc.wantCode {
				t.Fatalf("status = %d, want %d", w.Code, tc.wantCode)
			}
			if tc.wantCode == http.StatusOK && w.Body.String() != string(want) {
				t.Errorf("200 body differs from the manifest")
			}
			if tc.wantCode == http.StatusNotModified && w.Body.Len() != 0 {
				t.Errorf("304 carries a body: %q", w.Body.String())
			}
		})
	}
}

func TestPublicRejectsWrites(t *testing.T) {
	store, _ := publicFixture(t)
	h := NewPublicHandler(store, PublicConfig{}, nil)
	for _, m := range []string{http.MethodPost, http.MethodPut, http.MethodDelete, http.MethodPatch} {
		r := httptest.NewRequest(m, DefaultPublicPath, nil)
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		if w.Code != http.StatusMethodNotAllowed {
			t.Errorf("%s: status = %d, want 405", m, w.Code)
		}
		if got := w.Header().Get("Allow"); got != "GET, HEAD" {
			t.Errorf("%s: Allow = %q", m, got)
		}
	}
}

func TestPublicHeadHasNoBody(t *testing.T) {
	store, want := publicFixture(t)
	h := NewPublicHandler(store, PublicConfig{}, nil)
	r := httptest.NewRequest(http.MethodHead, DefaultPublicPath, nil)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", w.Code)
	}
	if w.Body.Len() != 0 {
		t.Errorf("HEAD returned a body")
	}
	// Content-Length still describes the body a GET would return.
	if got := w.Header().Get("Content-Length"); got != strconv.Itoa(len(want)) {
		t.Errorf("Content-Length = %q, want %d", got, len(want))
	}
}

func contains(haystack, needle string) bool {
	for i := 0; i+len(needle) <= len(haystack); i++ {
		if haystack[i:i+len(needle)] == needle {
			return true
		}
	}
	return false
}
