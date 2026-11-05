package controller

// Specs for the CRD → rule adapter, plus the end-to-end run over the committed cluster corpus.
//
// The corpus tests are the ones that matter most here. internal/visibility proves the filter's
// algebra on a hand-built three-group fixture; these prove the same filter does the right thing
// to the REAL manifest, including the guarantee the whole phase rests on — that a caller with
// no restrictions receives byte-for-byte what the sidecar serves today.

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	navv1alpha1 "github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/api/v1alpha1"
	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/navmodel"
	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/visibility"
)

func visibleTo(groups ...string) *navv1alpha1.Visibility {
	return &navv1alpha1.Visibility{AuthentikGroups: groups}
}

func navGroup(name, title string, v *navv1alpha1.Visibility) navv1alpha1.NavGroup {
	return navv1alpha1.NavGroup{
		ObjectMeta: metav1.ObjectMeta{Name: name, Generation: 1},
		Spec:       navv1alpha1.NavGroupSpec{Title: title, Order: 50, Visibility: v},
	}
}

func navEntry(ns, name, href string, v *navv1alpha1.Visibility) navv1alpha1.NavEntry {
	return navv1alpha1.NavEntry{
		ObjectMeta: metav1.ObjectMeta{Namespace: ns, Name: name, Generation: 1},
		Spec: navv1alpha1.NavEntrySpec{
			Title: name, Href: href, NavGroupRef: "media", Visibility: v,
		},
	}
}

// ── the adapter ─────────────────────────────────────────────────────────────────────────────

func TestNavGroupVisibilityBecomesAGroupRuleKeyedByObjectName(t *testing.T) {
	// Keyed by metadata.name because that is what Resolve stamps onto Group.NavGroupRef.
	// Keying by title would break the moment a group is renamed in the UI.
	ix := BuildVisibilityIndex([]navv1alpha1.NavGroup{
		navGroup("media", "Media", visibleTo("catalyst-media")),
	}, nil)

	r, ok := ix.Groups["media"]
	if !ok {
		t.Fatalf("no rule under the object name; keys = %v", keysOf(ix.Groups))
	}
	if r.Admits(visibility.Anonymous()) {
		t.Error("the rule admits an identity in no groups")
	}
	if !r.Admits(visibility.NewIdentity("dj", []string{"catalyst-media"}, true)) {
		t.Error("the rule denies a member")
	}
}

func TestSilentVisibilityContributesNoRule(t *testing.T) {
	// Both the nil pointer and the empty list mean "everyone". Inserting a permissive rule
	// for them would be harmless alone but would WIDEN a colliding restrictive rule, since
	// collisions intersect — so they must contribute nothing at all.
	ix := BuildVisibilityIndex(
		[]navv1alpha1.NavGroup{
			navGroup("media", "Media", nil),
			navGroup("infra", "Infrastructure", visibleTo()),
			navGroup("home", "Home", &navv1alpha1.Visibility{}),
		},
		[]navv1alpha1.NavEntry{
			navEntry("a", "one", "https://x.talos00/", nil),
			navEntry("b", "two", "https://y.talos00/", visibleTo()),
		},
	)
	if len(ix.Groups) != 0 || len(ix.Entries) != 0 {
		t.Fatalf("groups = %v, entries = %v; want both empty",
			keysOf(ix.Groups), keysOf(ix.Entries))
	}
}

func TestNavEntryCarriesVisibilityForTheDerivedEntryAtTheSameHref(t *testing.T) {
	// This is the mechanism for per-entry visibility on a DERIVED entry: an IngressRoute has
	// no visibility annotation and deliberately never gains one, so a NavEntry pointed at
	// the same destination is the carrier — the "override one field of an otherwise-derived
	// entry" role naventry-crd.yaml already reserves.
	ix := BuildVisibilityIndex(nil, []navv1alpha1.NavEntry{
		// Spelled differently from the derived href on purpose: no scheme match, no
		// trailing slash, mixed case. All three are legal under the CRD's pattern.
		navEntry("media", "plex-visibility", "http://PLEX.talos00", visibleTo("catalyst-media")),
	})

	m := &navmodel.Manifest{Groups: []navmodel.Group{{Name: "Media", Items: []navmodel.Item{
		{Name: "Plex", Href: "https://plex.talos00/"},
		{Name: "Jellyfin", Href: "https://jellyfin.talos00/"},
	}}}}

	out := visibility.Filter(m, ix, visibility.Anonymous())
	if len(out.Groups) != 1 || len(out.Groups[0].Items) != 1 ||
		out.Groups[0].Items[0].Name != "Jellyfin" {
		t.Fatalf("filtered manifest = %s, want Plex removed and Jellyfin kept",
			navmodel.Encode(out))
	}
}

func TestCollidingNavEntriesIntersectRatherThanOneWinning(t *testing.T) {
	// NavEntry is namespaced, so two namespaces can each claim one destination and nothing
	// in the schema stops them. Letting either win silently drops the other's restriction,
	// which is a fail-OPEN on a collision.
	ix := BuildVisibilityIndex(nil, []navv1alpha1.NavEntry{
		navEntry("a", "one", "https://plex.talos00/", visibleTo("catalyst-media", "catalyst-admins")),
		navEntry("b", "two", "https://plex.talos00/", visibleTo("catalyst-admins")),
	})
	r := ix.Entries[visibility.DestinationKey("https://plex.talos00/")]

	if r.Admits(visibility.NewIdentity("", []string{"catalyst-media"}, true)) {
		t.Error("an identity only ONE of the two colliding entries admits was admitted")
	}
	if !r.Admits(visibility.NewIdentity("", []string{"catalyst-admins"}, true)) {
		t.Error("an identity both colliding entries admit was denied")
	}
}

// ── over the real cluster corpus ────────────────────────────────────────────────────────────

// corpusModel builds and resolves the manifest from the committed capture of the live
// cluster's IngressRoutes — the same input the parity gate diffs against build_nav.py.
func corpusModel(t *testing.T, groups []navv1alpha1.NavGroup) *navmodel.Manifest {
	t.Helper()
	path := filepath.Join("..", "..", "testdata", "cluster-ingressroutes.json")
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("corpus missing (%v); regenerate with testdata/extract-corpus.sh", err)
	}
	var doc navmodel.Doc
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatalf("decoding the corpus: %v", err)
	}
	m := navmodel.Build(&doc, navmodel.Options{})
	Resolve(m, groups, nil)
	return m
}

func TestUnrestrictedIdentityGetsTheUnfilteredBytes(t *testing.T) {
	// THE GUARANTEE PHASE 3 RESTS ON. No NavGroup in this cluster carries visibility today,
	// so every identity — including the least privileged one there is — must receive exactly
	// the document the themepark sidecar is serving right now. If this ever fails, deploying
	// the endpoint becomes a user-visible nav change, and the strangler fig's whole premise
	// (each phase changes nothing that ships until the phase that does) is broken.
	m := corpusModel(t, nil)
	want := string(navmodel.Encode(m))

	got := string(navmodel.Encode(visibility.Filter(m, visibility.Index{}, visibility.Anonymous())))
	if got != want {
		t.Fatalf("filtering with no visibility objects changed the manifest\n want %s\n got  %s",
			want, got)
	}
	// Sanity: the corpus is not empty, or the assertion above is vacuous.
	if len(m.Groups) < 5 {
		t.Fatalf("corpus produced only %d groups; the comparison proves nothing", len(m.Groups))
	}
}

func TestRestrictingTheMediaNavGroupHidesFifteenRealAppsFromANonMember(t *testing.T) {
	// The concrete thing this phase buys, measured on the real corpus: "Media" is the
	// largest group in the cluster and a non-member must not learn that any of it exists.
	groups := []navv1alpha1.NavGroup{navGroup("media", "Media", visibleTo("catalyst-media"))}
	m := corpusModel(t, groups)
	ix := BuildVisibilityIndex(groups, nil)

	var mediaItems int
	for _, g := range m.Groups {
		if g.Name == "Media" {
			mediaItems = len(g.Items)
		}
	}
	if mediaItems == 0 {
		t.Fatal("the corpus has no Media group; this test is measuring nothing")
	}

	outsider := visibility.Filter(m, ix, visibility.NewIdentity("guest", []string{"catalyst-users"}, true))
	for _, g := range outsider.Groups {
		if g.Name == "Media" {
			t.Fatal("the Media group survived for a non-member")
		}
	}
	// Every other group must be untouched — this is a filter, not a kill switch.
	if len(outsider.Groups) != len(m.Groups)-1 {
		t.Errorf("groups = %d, want %d (only Media removed)", len(outsider.Groups), len(m.Groups)-1)
	}

	member := visibility.Filter(m, ix, visibility.NewIdentity("dj", []string{"catalyst-media"}, true))
	if len(member.Groups) != len(m.Groups) {
		t.Errorf("member groups = %d, want all %d", len(member.Groups), len(m.Groups))
	}

	// And the hostnames are actually gone from the bytes, not merely from the group list.
	body := string(navmodel.Encode(outsider))
	for _, host := range []string{"plex.", "jellyfin.", "stackarr.talos00"} {
		if strings.Contains(body, host) {
			t.Errorf("a Media hostname (%s) leaked into a non-member's manifest", host)
		}
	}
}

func TestPerHostConfigDoesNotOutliveItsEntryOnTheRealCorpus(t *testing.T) {
	// Manifest.hosts is keyed by hostname, so it is a second, less obvious channel for the
	// same disclosure as `groups`.
	//
	// THE HOST CONFIG HERE IS INJECTED, and that is not laziness. No IngressRoute in the
	// committed capture carries a catalyst.nav/* annotation, so the corpus manifest ships no
	// `hosts` block at all — meaning the obvious version of this test ("filter the corpus,
	// assert no Media host survives in hosts") iterates over an empty list and passes no
	// matter what the filter does. Verified by mutation: deleting the pruning loop entirely
	// left that version green. So the config is added to the built model on purpose, with
	// the real corpus's real hostnames, which is what gives the assertion teeth.
	groups := []navv1alpha1.NavGroup{navGroup("media", "Media", visibleTo("catalyst-media"))}
	m := corpusModel(t, groups)
	ix := BuildVisibilityIndex(groups, nil)

	mediaHosts := map[string]bool{}
	var keep string
	for _, g := range m.Groups {
		for _, it := range g.Items {
			h := hostFromHref(it.Href)
			if g.Name == "Media" {
				mediaHosts[h] = true
				m.Hosts.Set(h, cfgWith("mode", "overlay"))
			} else if keep == "" {
				keep = h
				m.Hosts.Set(h, cfgWith("height", 48))
			}
		}
	}
	if len(mediaHosts) == 0 || keep == "" {
		t.Fatal("the corpus has no Media group or no other group; this test measures nothing")
	}

	out := visibility.Filter(m, ix, visibility.Anonymous())
	for _, h := range out.Hosts.Keys {
		if mediaHosts[h] {
			t.Errorf("host config for %q survived its filtered-out entry", h)
		}
	}
	// ...and the surviving entry's config is still there, or "pruning" would just mean
	// "dropping hosts", which would break every app's per-host nav config.
	if _, ok := out.Hosts.Values[keep]; !ok {
		t.Errorf("host config for the still-visible %q was pruned too", keep)
	}
	if strings.Contains(string(navmodel.Encode(out)), `"mode":"overlay"`) {
		t.Error("a filtered-out host's config block reached the encoded manifest")
	}
}

func cfgWith(k string, v any) navmodel.OrderedConfig {
	var c navmodel.OrderedConfig
	c.Set(k, v)
	return c
}

func hostFromHref(href string) string {
	key := visibility.DestinationKey(href)
	if i := strings.IndexByte(key, '/'); i >= 0 {
		return key[:i]
	}
	return key
}

func keysOf[V any](m map[string]V) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}
