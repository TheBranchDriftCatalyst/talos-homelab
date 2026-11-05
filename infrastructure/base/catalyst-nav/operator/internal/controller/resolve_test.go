package controller

// The resolver is the half of phase 2 that is NOT a port, so it gets its own specs. Its whole
// job is to answer "does this group name refer to anything?" — the question the annotation
// pipeline could never ask — without changing a single byte of what the manifest ships.

import (
	"strings"
	"testing"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	navv1alpha1 "github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/api/v1alpha1"
	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/navmodel"
)

func group(name, title string, order int32) navv1alpha1.NavGroup {
	return navv1alpha1.NavGroup{
		ObjectMeta: metav1.ObjectMeta{Name: name, Generation: 1},
		Spec:       navv1alpha1.NavGroupSpec{Title: title, Order: order},
	}
}

func entry(ns, name, ref string) navv1alpha1.NavEntry {
	return navv1alpha1.NavEntry{
		ObjectMeta: metav1.ObjectMeta{Namespace: ns, Name: name, Generation: 1},
		Spec: navv1alpha1.NavEntrySpec{
			Title: name, Href: "https://example.invalid/", NavGroupRef: ref,
		},
	}
}

// model builds a manifest with one item per named group, as the derived pipeline would.
func model(groupNames ...string) *navmodel.Manifest {
	m := &navmodel.Manifest{}
	for _, g := range groupNames {
		m.Groups = append(m.Groups, navmodel.Group{
			Name:  g,
			Items: []navmodel.Item{{Name: "App", Weight: 50, Href: "//a/", Group: g}},
		})
	}
	return m
}

func TestDerivedGroupResolvesByTitle(t *testing.T) {
	// The derived path carries the human TITLE (gethomepage.dev/group: "Observability"), so
	// title matching is what makes the taxonomy useful before any annotation is migrated.
	m := model("Observability")
	res := Resolve(m, []navv1alpha1.NavGroup{group("observability", "Observability", 60)}, nil)
	if got := res.EntriesPerGroup["observability"]; got != 1 {
		t.Fatalf("entriesPerGroup = %d, want 1", got)
	}
	if m.Groups[0].NavGroupRef != "observability" {
		t.Errorf("binding not recorded on the model: %q", m.Groups[0].NavGroupRef)
	}
	if len(res.UnresolvedGroupNames) != 0 {
		t.Errorf("unexpected unresolved: %v", res.UnresolvedGroupNames)
	}
}

func TestDerivedGroupResolvesByObjectName(t *testing.T) {
	m := model("observability")
	res := Resolve(m, []navv1alpha1.NavGroup{group("observability", "Observability", 60)}, nil)
	if got := res.EntriesPerGroup["observability"]; got != 1 {
		t.Fatalf("entriesPerGroup = %d, want 1", got)
	}
}

func TestTitleMatchIsCaseInsensitive(t *testing.T) {
	m := model("OBSERVABILITY")
	res := Resolve(m, []navv1alpha1.NavGroup{group("observability", "Observability", 60)}, nil)
	if got := res.EntriesPerGroup["observability"]; got != 1 {
		t.Fatalf("entriesPerGroup = %d, want 1 (case must not matter for titles)", got)
	}
}

// TestTheLiveMonitoringObservabilityForkIsReported is the concrete thing this phase buys.
func TestTheLiveMonitoringObservabilityForkIsReported(t *testing.T) {
	// The live cluster carries both. The taxonomy declares only Observability, so
	// "Monitoring" and "Analytics" must come back as unresolved — that list IS phase 5's
	// worklist.
	m := model("Observability", "Monitoring", "Analytics")
	groups := []navv1alpha1.NavGroup{group("observability", "Observability", 60)}
	res := Resolve(m, groups, nil)

	if _, ok := res.UnresolvedGroupNames["Monitoring"]; !ok {
		t.Error(`"Monitoring" was not reported as unresolved`)
	}
	if _, ok := res.UnresolvedGroupNames["Analytics"]; !ok {
		t.Error(`"Analytics" was not reported as unresolved`)
	}
	if _, ok := res.UnresolvedGroupNames["Observability"]; ok {
		t.Error(`"Observability" was reported unresolved despite having a NavGroup`)
	}
}

// TestUnresolvedGroupsStillRenderUnchanged is the contract that makes phase 2 safe to deploy.
func TestUnresolvedGroupsStillRenderUnchanged(t *testing.T) {
	// Resolution must NOT drop an entry whose group matched nothing. Dropping it would make
	// deploying this operator a user-visible nav change, and phase 2's whole promise is that
	// it changes nothing that ships.
	m := model("Observability", "Monitoring")
	before := string(navmodel.Encode(m))
	Resolve(m, []navv1alpha1.NavGroup{group("observability", "Observability", 60)}, nil)
	if after := string(navmodel.Encode(m)); after != before {
		t.Fatalf("Resolve changed the published manifest:\n before %s\n after  %s", before, after)
	}
}

func TestNavEntryResolvesAndCountsTowardItsGroup(t *testing.T) {
	groups := []navv1alpha1.NavGroup{group("observability", "Observability", 60)}
	entries := []navv1alpha1.NavEntry{entry("default", "bm", "observability")}
	res := Resolve(model(), groups, entries)

	if got := res.EntryResolved["default/bm"]; got != "Observability" {
		t.Fatalf("entryResolved = %q, want Observability", got)
	}
	if got := res.EntriesPerGroup["observability"]; got != 1 {
		t.Fatalf("entriesPerGroup = %d, want the NavEntry counted", got)
	}
}

func TestGroupStatusReportsEmptyGroupsWithoutCallingItAFailure(t *testing.T) {
	// Six of the eight taxonomy groups were empty the day they were created. A False
	// Published with reason NoEntries states the fact; a Degraded would train the reader to
	// ignore the condition.
	g := group("library", "Library", 40)
	st := Resolve(model(), []navv1alpha1.NavGroup{g}, nil).GroupStatus(&g)

	if st.PublishedEntries != 0 {
		t.Errorf("publishedEntries = %d, want 0", st.PublishedEntries)
	}
	c := condition(st.Conditions, "Published")
	if c == nil || c.Status != metav1.ConditionFalse || c.Reason != "NoEntries" {
		t.Fatalf("Published condition = %+v, want False/NoEntries", c)
	}
	if condition(st.Conditions, "Degraded") != nil {
		t.Error("an empty group must not be Degraded")
	}
	if st.ObservedGeneration != g.Generation {
		t.Errorf("observedGeneration = %d, want %d", st.ObservedGeneration, g.Generation)
	}
}

func TestGroupStatusSurfacesNearMissNames(t *testing.T) {
	// "Infra" shares no whole word with "Infrastructure" but is a substring of it — the
	// case the heuristic is actually for.
	m := model("Infra")
	g := group("infrastructure", "Infrastructure", 50)
	st := Resolve(m, []navv1alpha1.NavGroup{g}, nil).GroupStatus(&g)

	c := condition(st.Conditions, "Degraded")
	if c == nil {
		t.Fatal("no Degraded condition reporting the near-miss group name")
	}
	if !strings.Contains(c.Message, "Infra") || c.Reason != "UnresolvedGroupNames" {
		t.Fatalf("Degraded condition = %+v, want it to name \"Infra\"", c)
	}
}

func TestNearMissHeuristicDoesNotClaimToRelateSynonyms(t *testing.T) {
	// The honest limitation, asserted so the comment in resolve.go cannot rot into a claim
	// the code does not make: nothing automatic can relate "Monitoring" to "Observability".
	// The unresolved names are reported in FULL on the log line; this condition is a
	// convenience for the cases it does catch.
	m := model("Monitoring")
	g := group("observability", "Observability", 60)
	res := Resolve(m, []navv1alpha1.NavGroup{g}, nil)
	st := res.GroupStatus(&g)

	if c := condition(st.Conditions, "Degraded"); c != nil {
		t.Fatalf("the heuristic claimed to relate Monitoring to Observability: %q", c.Message)
	}
	// ...but it must still be in the resolution, or the information is lost entirely.
	if _, ok := res.UnresolvedGroupNames["Monitoring"]; !ok {
		t.Fatal("Monitoring is neither reported as a near-miss NOR as unresolved -- " +
			"the information has been dropped on the floor")
	}
}

func TestEntryStatusReportsADanglingRefAsNavGroupNotFound(t *testing.T) {
	e := entry("default", "orphan", "doomed")
	st := Resolve(model(), nil, []navv1alpha1.NavEntry{e}).EntryStatus(&e)

	c := condition(st.Conditions, "Published")
	if c == nil || c.Status != metav1.ConditionFalse || c.Reason != "NavGroupNotFound" {
		t.Fatalf("condition = %+v, want False/NavGroupNotFound", c)
	}
	if !strings.Contains(c.Message, "doomed") {
		t.Errorf("message does not quote the bad ref: %q", c.Message)
	}
	if st.ResolvedGroup != "" {
		t.Errorf("resolvedGroup = %q, want empty", st.ResolvedGroup)
	}
}

func TestRejectionsAreIndexedBySourceObject(t *testing.T) {
	// A rejection has to reach the object that caused it, or it is just another log line.
	m := &navmodel.Manifest{Rejections: []navmodel.Rejection{{
		Source:  navmodel.Source{Kind: "IngressRoute", Namespace: "media", Name: "plex"},
		Reason:  "PrivateHostname",
		Message: "plex.priv.talos00 is excluded",
	}}}
	res := Resolve(m, nil, nil)
	got := res.RejectionsBySource["IngressRoute/media/plex"]
	if len(got) != 1 || got[0].Reason != "PrivateHostname" {
		t.Fatalf("rejectionsBySource = %+v", res.RejectionsBySource)
	}
}

func TestStatusMessagesAreStableAcrossResolves(t *testing.T) {
	// An unstable message rewrites status on every reconcile forever, which is why the
	// unresolved-name lists are sorted. Two resolves over the same input must agree.
	m1 := model("Infra", "Infrastructure Extra", "Observability")
	m2 := model("Infrastructure Extra", "Infra", "Observability")
	g := group("infrastructure", "Infrastructure", 50)

	a := Resolve(m1, []navv1alpha1.NavGroup{g}, nil).GroupStatus(&g)
	b := Resolve(m2, []navv1alpha1.NavGroup{g}, nil).GroupStatus(&g)

	ca, cb := condition(a.Conditions, "Degraded"), condition(b.Conditions, "Degraded")
	if ca == nil || cb == nil {
		t.Fatal("expected a Degraded condition from both")
	}
	if ca.Message != cb.Message {
		t.Fatalf("message depends on input order:\n %q\n %q", ca.Message, cb.Message)
	}
}

func condition(cs []metav1.Condition, t string) *metav1.Condition {
	for i := range cs {
		if cs[i].Type == t {
			return &cs[i]
		}
	}
	return nil
}
