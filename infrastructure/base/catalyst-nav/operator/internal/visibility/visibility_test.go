package visibility

// Specs for the filter. Every one of these mutates the thing it is about and asserts the
// filter notices — a visibility test that passes whether or not the filter runs is worse than
// no test, because it certifies the one property that must never silently regress.

import (
	"strings"
	"testing"

	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/navmodel"
)

// fixture builds a two-group model shaped like the real one: derived items with absolute
// https hrefs, a resolved NavGroupRef on each group, and per-host config in Hosts.
func fixture() *navmodel.Manifest {
	m := &navmodel.Manifest{
		Groups: []navmodel.Group{
			{
				Name:        "Media",
				NavGroupRef: "media",
				Items: []navmodel.Item{
					{Name: "Plex", Weight: 10, Href: "https://plex.talos00/", Themed: true},
					{Name: "Jellyfin", Weight: 20, Href: "https://jellyfin.talos00/", Themed: true},
				},
			},
			{
				Name:        "Infrastructure",
				NavGroupRef: "infrastructure",
				Items: []navmodel.Item{
					{Name: "Argocd", Weight: 50, Href: "https://argocd.talos00/", Themed: true},
				},
			},
		},
	}
	m.Hosts.Set("plex.talos00", cfg("mode", "overlay"))
	m.Hosts.Set("argocd.talos00", cfg("height", 48))
	return m
}

func cfg(k string, v any) navmodel.OrderedConfig {
	var c navmodel.OrderedConfig
	c.Set(k, v)
	return c
}

func restricted(groups ...string) Rule { return NewRule(groups) }

func groupNames(m *navmodel.Manifest) []string {
	out := make([]string, 0, len(m.Groups))
	for _, g := range m.Groups {
		out = append(out, g.Name)
	}
	return out
}

func itemNames(g navmodel.Group) []string {
	out := make([]string, 0, len(g.Items))
	for _, i := range g.Items {
		out = append(out, i.Name)
	}
	return out
}

// ── the no-visibility case: the default is "everyone" ────────────────────────────────────────

func TestAbsentVisibilityIsVisibleToEveryone(t *testing.T) {
	// An empty Index is the state of the cluster today: zero NavGroups carry visibility.
	// Anonymous() — the least privileged identity there is — must still see everything.
	m := fixture()
	got := Filter(m, Index{}, Anonymous())

	if len(got.Groups) != 2 {
		t.Fatalf("groups = %v, want both", groupNames(got))
	}
	if string(navmodel.Encode(got)) != string(navmodel.Encode(m)) {
		t.Fatalf("an empty index changed the bytes:\n before %s\n after  %s",
			navmodel.Encode(m), navmodel.Encode(got))
	}
}

func TestEmptyAuthentikGroupsIsVisibleToEveryone(t *testing.T) {
	// Both CRDs say so in as many words: "Omit entirely, or leave authentikGroups empty,
	// for a group visible to everyone". An empty list must NOT read as "nobody".
	ix := Index{Groups: map[string]Rule{"media": NewRule(nil)}}
	if got := Filter(fixture(), ix, Anonymous()); len(got.Groups) != 2 {
		t.Fatalf("groups = %v, want both — an empty allow-list hid a group", groupNames(got))
	}

	ix = Index{Groups: map[string]Rule{"media": NewRule([]string{"", "   "})}}
	if got := Filter(fixture(), ix, Anonymous()); len(got.Groups) != 2 {
		t.Fatalf("groups = %v, want both — a blank-only allow-list hid a group", groupNames(got))
	}
}

// ── group filtering: a whole section disappears ──────────────────────────────────────────────

func TestDeniedGroupDisappearsWholeWithItsItems(t *testing.T) {
	ix := Index{Groups: map[string]Rule{"media": restricted("catalyst-media")}}

	outsider := Filter(fixture(), ix, NewIdentity("guest", []string{"catalyst-users"}, true))
	if names := groupNames(outsider); len(names) != 1 || names[0] != "Infrastructure" {
		t.Fatalf("groups = %v, want only Infrastructure", names)
	}
	// Not merely thinned: the member items must be gone from the document entirely.
	if body := string(navmodel.Encode(outsider)); strings.Contains(body, "plex.talos00") ||
		strings.Contains(body, "jellyfin.talos00") {
		t.Fatalf("a denied group's hostnames survived in the body: %s", body)
	}

	member := Filter(fixture(), ix, NewIdentity("dj", []string{"catalyst-media"}, true))
	if names := groupNames(member); len(names) != 2 {
		t.Fatalf("member groups = %v, want both", names)
	}
}

func TestMembershipInAnyListedGroupIsEnough(t *testing.T) {
	ix := Index{Groups: map[string]Rule{"media": restricted("catalyst-media", "catalyst-admins")}}
	id := NewIdentity("dj", []string{"catalyst-admins", "unrelated"}, true)
	if len(Filter(fixture(), ix, id).Groups) != 2 {
		t.Fatal("a member of the second listed group was denied; the rule is ANY, not ALL")
	}
}

func TestGroupNamesAreCaseSensitive(t *testing.T) {
	// Folding case here would ADMIT a non-member, and a widening is the one direction this
	// code must never guess in. Authentik group names are case-sensitive.
	ix := Index{Groups: map[string]Rule{"media": restricted("catalyst-media")}}
	id := NewIdentity("dj", []string{"Catalyst-Media"}, true)
	if names := groupNames(Filter(fixture(), ix, id)); len(names) != 1 {
		t.Fatalf("groups = %v: a case-mismatched group name was admitted", names)
	}
}

func TestAGroupWithNoNavGroupRefCannotBeRestricted(t *testing.T) {
	// The documented fail-open: a free-text gethomepage.dev/group that matched no NavGroup
	// has no ref to key a rule by, so it stays visible. Asserted so the comment in Index
	// cannot rot into a claim the code does not make — and so that anyone who later decides
	// this should fail CLOSED has to delete a test that says why it does not.
	m := fixture()
	m.Groups[0].NavGroupRef = "" // as if "Media" matched no NavGroup
	ix := Index{Groups: map[string]Rule{"media": restricted("catalyst-media")}}

	if names := groupNames(Filter(m, ix, Anonymous())); len(names) != 2 {
		t.Fatalf("groups = %v, want both: an unresolved group was filtered by a rule it "+
			"cannot be matched to", names)
	}
}

// ── entry filtering ─────────────────────────────────────────────────────────────────────────

func TestDeniedEntryIsRemovedButItsGroupSurvives(t *testing.T) {
	ix := Index{Entries: map[string]Rule{
		DestinationKey("https://plex.talos00/"): restricted("catalyst-media"),
	}}
	got := Filter(fixture(), ix, Anonymous())

	if names := groupNames(got); len(names) != 2 {
		t.Fatalf("groups = %v, want both — the group still has a visible member", names)
	}
	if names := itemNames(got.Groups[0]); len(names) != 1 || names[0] != "Jellyfin" {
		t.Fatalf("Media items = %v, want only Jellyfin", names)
	}
	if strings.Contains(string(navmodel.Encode(got)), "plex.talos00") {
		t.Fatal("the denied entry's hostname survived in the body")
	}
}

func TestEntryKeyIsSchemeAndTrailingSlashInsensitive(t *testing.T) {
	// Build() emits "https://host/"; a hand-written NavEntry only has to satisfy the CRD's
	// ^(https?://\S+|/\S*)$, so every spelling below is a legal way to name the same app.
	for _, href := range []string{
		"https://plex.talos00/",
		"https://plex.talos00",
		"http://plex.talos00/",
		"HTTPS://PLEX.TALOS00/",
	} {
		ix := Index{Entries: map[string]Rule{
			DestinationKey(href): restricted("catalyst-media"),
		}}
		got := Filter(fixture(), ix, Anonymous())
		if names := itemNames(got.Groups[0]); len(names) != 1 {
			t.Errorf("href %q did not match the derived entry: Media items = %v", href, names)
		}
	}
}

func TestPathOnlyEntryCannotRestrictAHostedApp(t *testing.T) {
	// A NavEntry may carry a path-only href ("/foo"). Its key has no host, so it must be
	// unable to collide with a derived entry — otherwise an in-cluster bookmark could hide
	// an app by accident.
	ix := Index{Entries: map[string]Rule{
		DestinationKey("/plex.talos00/"): restricted("nobody-at-all"),
	}}
	if got := Filter(fixture(), ix, Anonymous()); len(got.Groups[0].Items) != 2 {
		t.Fatalf("Media items = %v, want both", itemNames(got.Groups[0]))
	}
}

// ── the empty-group case ────────────────────────────────────────────────────────────────────

func TestAGroupLeftWithNoItemsIsOmittedEntirely(t *testing.T) {
	// Not an empty dropdown. A control that opens onto nothing advertises that there is
	// something there you cannot have, and it is strictly more disclosure than omitting it.
	ix := Index{Entries: map[string]Rule{
		DestinationKey("https://plex.talos00/"):     restricted("catalyst-media"),
		DestinationKey("https://jellyfin.talos00/"): restricted("catalyst-media"),
	}}
	got := Filter(fixture(), ix, Anonymous())

	if names := groupNames(got); len(names) != 1 || names[0] != "Infrastructure" {
		t.Fatalf("groups = %v, want only Infrastructure", names)
	}
	if body := string(navmodel.Encode(got)); strings.Contains(body, `"Media"`) {
		t.Fatalf("an emptied group was still encoded: %s", body)
	}
}

func TestEveryGroupDeniedYieldsAValidEmptyManifest(t *testing.T) {
	// The extreme case has to produce a document the client can parse and build nothing
	// from, not a malformed one — the bar is cosmetic and must degrade, never throw.
	ix := Index{Groups: map[string]Rule{
		"media":          restricted("nobody"),
		"infrastructure": restricted("nobody"),
	}}
	got := Filter(fixture(), ix, Anonymous())
	if body := string(navmodel.Encode(got)); body != `{"groups":[]}` {
		t.Fatalf("encoded = %s, want an empty but well-formed manifest", body)
	}
}

// ── the leak that is easy to miss ───────────────────────────────────────────────────────────

func TestHostsAreNarrowedToSurvivingEntries(t *testing.T) {
	// Manifest.Hosts is keyed BY HOSTNAME. Filtering `groups` while leaving `hosts` whole
	// would hand back, in a per-host config block, exactly the internal hostnames the group
	// filter just removed — which is the disclosure this entire phase exists to close.
	ix := Index{Groups: map[string]Rule{"media": restricted("catalyst-media")}}
	got := Filter(fixture(), ix, Anonymous())

	if len(got.Hosts.Keys) != 1 || got.Hosts.Keys[0] != "argocd.talos00" {
		t.Fatalf("hosts = %v, want only argocd.talos00", got.Hosts.Keys)
	}
	if body := string(navmodel.Encode(got)); strings.Contains(body, "plex.talos00") {
		t.Fatalf("a filtered host leaked through `hosts`: %s", body)
	}
}

// ── purity ──────────────────────────────────────────────────────────────────────────────────

func TestFilterDoesNotMutateTheSnapshot(t *testing.T) {
	// The snapshot is shared by every concurrent request. A filter that trimmed it in place
	// would serve the first caller's view to everyone after them — the exact cross-identity
	// leak, moved from the HTTP cache into process memory.
	m := fixture()
	before := string(navmodel.Encode(m))

	ix := Index{Groups: map[string]Rule{"media": restricted("catalyst-media")}}
	_ = Filter(m, ix, Anonymous())
	_ = Filter(m, ix, NewIdentity("dj", []string{"catalyst-media"}, true))

	if after := string(navmodel.Encode(m)); after != before {
		t.Fatalf("Filter mutated its input:\n before %s\n after  %s", before, after)
	}
}

func TestTwoIdentitiesFilterIndependently(t *testing.T) {
	ix := Index{Groups: map[string]Rule{"media": restricted("catalyst-media")}}
	m := fixture()

	a := string(navmodel.Encode(Filter(m, ix, NewIdentity("dj", []string{"catalyst-media"}, true))))
	b := string(navmodel.Encode(Filter(m, ix, Anonymous())))
	// Re-run A to prove B did not poison the shared state.
	a2 := string(navmodel.Encode(Filter(m, ix, NewIdentity("dj", []string{"catalyst-media"}, true))))

	if a == b {
		t.Fatal("a member and a non-member got the same document")
	}
	if a != a2 {
		t.Fatalf("the member's view changed after a non-member's request:\n %s\n %s", a, a2)
	}
}

// ── Rule algebra ────────────────────────────────────────────────────────────────────────────

func TestAndIntersectsSoACollisionFailsClosed(t *testing.T) {
	// NavEntry is namespaced: two namespaces can each claim one destination. Picking one
	// would drop the other's restriction, which widens. And() narrows.
	a := restricted("catalyst-media", "catalyst-admins")
	b := restricted("catalyst-admins")
	both := a.And(b)

	if !both.Admits(NewIdentity("", []string{"catalyst-admins"}, true)) {
		t.Error("an identity both rules admit was denied")
	}
	if both.Admits(NewIdentity("", []string{"catalyst-media"}, true)) {
		t.Error("an identity only ONE rule admits was admitted; the collision failed open")
	}
}

func TestAndWithADisjointRuleHidesFromEveryone(t *testing.T) {
	// The empty intersection must mean "nobody", not "everyone" — which is the whole reason
	// Rule carries Restricted separately from len(Allow).
	nobody := restricted("a").And(restricted("b"))
	if !nobody.Restricted {
		t.Fatal("an empty intersection lost its Restricted flag and became public")
	}
	if nobody.Admits(NewIdentity("", []string{"a"}, true)) || nobody.Admits(Anonymous()) {
		t.Fatal("an empty intersection admitted somebody")
	}
}

func TestAndWithAnUnrestrictedRuleKeepsTheRestriction(t *testing.T) {
	r := restricted("catalyst-media")
	for _, combined := range []Rule{r.And(Unrestricted()), Unrestricted().And(r)} {
		if combined.Admits(Anonymous()) {
			t.Error("combining with an unrestricted rule dissolved the restriction")
		}
	}
}

// ── Identity hygiene ────────────────────────────────────────────────────────────────────────

func TestZeroIdentityIsAMemberOfNothing(t *testing.T) {
	// A zero value that leaked past a constructor must be the SAFE one, not a wildcard.
	var zero Identity
	if restricted("catalyst-media").Admits(zero) {
		t.Fatal("Identity{} was admitted to a restricted group")
	}
}

func TestBlankGroupsInTheHeaderAreDropped(t *testing.T) {
	// "a||b" is a real thing to receive from a separator-joined header. An empty string must
	// not become a group name that could match a malformed allow-list.
	id := NewIdentity("dj", []string{"a", "", "  ", "b"}, true)
	if n := len(id.Groups()); n != 2 {
		t.Fatalf("groups = %v, want 2", id.Groups())
	}
	if id.InGroup("") {
		t.Fatal("the empty string became a group")
	}
}

func TestGroupsAreCopiedOut(t *testing.T) {
	// An identity must not be wideable after construction.
	id := NewIdentity("dj", []string{"a"}, true)
	got := id.Groups()
	got[0] = "catalyst-admins"
	if id.InGroup("catalyst-admins") {
		t.Fatal("mutating the returned slice widened the identity")
	}
}

// ── the harness itself can fail ─────────────────────────────────────────────────────────────

func TestFilterIsActuallyRunning(t *testing.T) {
	// Guard against the whole suite above passing because every assertion happens to hold
	// on an unfiltered document. One rule that denies everything must change the output.
	m := fixture()
	ix := Index{Groups: map[string]Rule{"media": restricted("nobody")}}
	if string(navmodel.Encode(Filter(m, ix, Anonymous()))) == string(navmodel.Encode(m)) {
		t.Fatal("a deny-all rule produced the unfiltered document; the filter is a no-op")
	}
}
