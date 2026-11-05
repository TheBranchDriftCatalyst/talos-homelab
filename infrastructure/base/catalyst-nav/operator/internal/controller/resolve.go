package controller

// Resolution: binding the derived nav model to the NavGroup taxonomy, and turning the result
// into status facts.
//
// THIS IS THE HALF OF PHASE 2 THAT IS NOT A PORT. navmodel reproduces build_nav.py exactly;
// this file adds the thing the annotation pipeline never had — an answer to "does this group
// name refer to anything?".
//
// It deliberately does NOT rewrite the manifest. A derived entry whose gethomepage.dev/group
// resolves to no NavGroup still renders under its free-text name, exactly as today, and is
// merely REPORTED as unresolved. Dropping it instead would make deploying this operator a
// user-visible nav change, and phase 2's whole contract is that it changes nothing that ships.
// The reports are the deliverable: they are phase 5's worklist, and they are what makes the
// live "Monitoring" vs "Observability" fork a row in `kubectl get navgroups` output rather
// than a thing someone has to notice.

import (
	"fmt"
	"sort"
	"strings"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	navv1alpha1 "github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/api/v1alpha1"
	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/navmodel"
)

// Resolution is everything the status writers need, computed once.
type Resolution struct {
	// EntriesPerGroup counts derived entries that resolved into each NavGroup, by
	// metadata.name.
	EntriesPerGroup map[string]int32

	// UnresolvedGroupNames maps a free-text gethomepage.dev/group value that matched no
	// NavGroup to the entry names carrying it. This is the typo-fork detector.
	UnresolvedGroupNames map[string][]string

	// EntryResolved maps namespace/name of a NavEntry to the title of the NavGroup it
	// resolved to. Absent means it did not resolve.
	EntryResolved map[string]string

	// RejectionsBySource maps "Kind/namespace/name" to the reasons that object was refused.
	RejectionsBySource map[string][]navmodel.Rejection
}

// Resolve matches the derived model and the NavEntry objects against the NavGroup taxonomy.
//
// Matching is by metadata.name first, then by spec.title case-insensitively. Both, because the
// two populations spell a group differently by design: a NavEntry names the OBJECT
// ("observability"), while a derived gethomepage.dev/group carries the human TITLE
// ("Observability") — those are the strings each side already has, and requiring either to
// adopt the other's spelling would mean editing ~40 annotations before this operator could
// report anything useful, which is phase 5's job and not a prerequisite for phase 2.
func Resolve(
	m *navmodel.Manifest,
	groups []navv1alpha1.NavGroup,
	entries []navv1alpha1.NavEntry,
) *Resolution {
	byName := map[string]*navv1alpha1.NavGroup{}
	byTitle := map[string]*navv1alpha1.NavGroup{}
	for i := range groups {
		g := &groups[i]
		byName[g.Name] = g
		byTitle[strings.ToLower(g.Spec.Title)] = g
	}
	lookup := func(ref string) *navv1alpha1.NavGroup {
		if g, ok := byName[ref]; ok {
			return g
		}
		if g, ok := byTitle[strings.ToLower(ref)]; ok {
			return g
		}
		return nil
	}

	res := &Resolution{
		EntriesPerGroup:      map[string]int32{},
		UnresolvedGroupNames: map[string][]string{},
		EntryResolved:        map[string]string{},
		RejectionsBySource:   map[string][]navmodel.Rejection{},
	}

	for i := range m.Groups {
		g := &m.Groups[i]
		target := lookup(g.Name)
		if target == nil {
			for _, it := range g.Items {
				res.UnresolvedGroupNames[g.Name] = append(res.UnresolvedGroupNames[g.Name], it.Name)
			}
			continue
		}
		// Record the binding on the model so a later phase (and phase 3's visibility
		// filter) can read it without redoing the match.
		g.NavGroupRef = target.Name
		res.EntriesPerGroup[target.Name] += int32(len(g.Items))
	}
	for k := range res.UnresolvedGroupNames {
		sort.Strings(res.UnresolvedGroupNames[k])
	}

	for i := range entries {
		e := &entries[i]
		key := e.Namespace + "/" + e.Name
		if target := lookup(e.Spec.NavGroupRef); target != nil {
			res.EntryResolved[key] = target.Spec.Title
			res.EntriesPerGroup[target.Name]++
		}
	}

	for _, rj := range m.Rejections {
		k := rj.Source.Kind + "/" + rj.Source.Namespace + "/" + rj.Source.Name
		res.RejectionsBySource[k] = append(res.RejectionsBySource[k], rj)
	}

	return res
}

// GroupStatus is the status this NavGroup should carry.
func (r *Resolution) GroupStatus(g *navv1alpha1.NavGroup) navv1alpha1.NavGroupStatus {
	now := metav1.Now()
	n := r.EntriesPerGroup[g.Name]

	published := metav1.Condition{
		Type:               conditionPublished,
		ObservedGeneration: g.Generation,
		LastTransitionTime: now,
	}
	if n > 0 {
		published.Status = metav1.ConditionTrue
		published.Reason = "Published"
		published.Message = fmt.Sprintf("%d entries resolve into this group", n)
	} else {
		// NOT an error. A reviewed taxonomy legitimately contains a group nothing has
		// been migrated into yet — six of the eight were empty the day they were
		// created. Saying so plainly beats a False/Degraded that an operator learns to
		// ignore.
		published.Status = metav1.ConditionFalse
		published.Reason = "NoEntries"
		published.Message = "no entry currently resolves into this group; it will not render"
	}

	status := navv1alpha1.NavGroupStatus{
		PublishedEntries:   n,
		ObservedGeneration: g.Generation,
		Conditions:         []metav1.Condition{published},
	}

	// The taxonomy-drift report, attached to the group whose title was NEARLY matched.
	// Attached here rather than to a cluster-wide object because this is where someone
	// fixing the drift is already looking: `kubectl describe navgroup observability` is the
	// command that should tell you nine apps are still annotated "Monitoring".
	if near := r.nearMisses(g); len(near) > 0 {
		status.Conditions = append(status.Conditions, metav1.Condition{
			Type:               conditionDegraded,
			Status:             metav1.ConditionTrue,
			Reason:             "UnresolvedGroupNames",
			ObservedGeneration: g.Generation,
			LastTransitionTime: now,
			Message: fmt.Sprintf(
				"free-text gethomepage.dev/group values matching no NavGroup: %s. "+
					"These render under their own name today; migrating them is the "+
					"point of this taxonomy", strings.Join(near, ", ")),
		})
	}
	return status
}

// nearMisses reports unresolved group names plausibly intended for this group.
//
// A deliberately crude heuristic — shared word, or one is a substring of the other. It will not
// relate "Monitoring" to "Observability", and NOTHING automatic can: the phase-1 CRD comment
// makes exactly this point ("a regex can't know two words mean the same thing"). So the
// unresolved names are ALSO reported in full on the controller's log line and are not
// discoverable only through this heuristic. The heuristic is a convenience for the cases it
// does catch ("Observability " with trailing space, "Infra" vs "Infrastructure"), not the
// mechanism.
func (r *Resolution) nearMisses(g *navv1alpha1.NavGroup) []string {
	title := strings.ToLower(g.Spec.Title)
	titleWords := map[string]struct{}{}
	for _, w := range strings.FieldsFunc(title, isNotLetter) {
		if len(w) > 3 {
			titleWords[w] = struct{}{}
		}
	}
	var out []string
	for _, name := range sortedKeys(r.UnresolvedGroupNames) {
		ln := strings.ToLower(name)
		related := strings.Contains(ln, title) || strings.Contains(title, ln)
		if !related {
			for _, w := range strings.FieldsFunc(ln, isNotLetter) {
				if _, ok := titleWords[w]; ok && len(w) > 3 {
					related = true
					break
				}
			}
		}
		if related {
			out = append(out, fmt.Sprintf("%q (%d entries)", name, len(r.UnresolvedGroupNames[name])))
		}
	}
	return out
}

func isNotLetter(r rune) bool {
	return !(r >= 'a' && r <= 'z') && !(r >= 'A' && r <= 'Z')
}

// EntryStatus is the status this NavEntry should carry.
func (r *Resolution) EntryStatus(e *navv1alpha1.NavEntry) navv1alpha1.NavEntryStatus {
	now := metav1.Now()
	status := navv1alpha1.NavEntryStatus{ObservedGeneration: e.Generation}

	title, ok := r.EntryResolved[e.Namespace+"/"+e.Name]
	if ok {
		status.ResolvedGroup = title
		status.Conditions = []metav1.Condition{{
			Type:               conditionPublished,
			Status:             metav1.ConditionTrue,
			Reason:             "Published",
			ObservedGeneration: e.Generation,
			LastTransitionTime: now,
			Message:            fmt.Sprintf("published under NavGroup %q", title),
		}}
		return status
	}

	// Reachable only when a NavGroup was DELETED after this entry was admitted — the
	// webhook refuses a dangling navGroupRef at creation. That residual case is exactly
	// what a status condition is for and what admission cannot cover.
	status.Conditions = []metav1.Condition{{
		Type:               conditionPublished,
		Status:             metav1.ConditionFalse,
		Reason:             "NavGroupNotFound",
		ObservedGeneration: e.Generation,
		LastTransitionTime: now,
		Message: fmt.Sprintf(
			"navGroupRef %q names no NavGroup, so this entry has nowhere to render. "+
				"Admission rejects a dangling ref, so the group was most likely "+
				"deleted after this entry was created", e.Spec.NavGroupRef),
	}}
	return status
}
