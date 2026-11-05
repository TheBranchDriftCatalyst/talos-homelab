package controller

// Turning NavGroup/NavEntry objects into the rules internal/visibility filters with.
//
// This file is the ONLY place the typed CRDs and the visibility filter meet, and it is here
// rather than in internal/visibility for the same reason collect.go is here rather than in
// navmodel: the filter has to be table-testable without a scheme, a client or an envtest
// control plane, so it takes plain rules and knows nothing about api/v1alpha1.

import (
	navv1alpha1 "github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/api/v1alpha1"
	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/visibility"
)

// BuildVisibilityIndex reads spec.visibility off both kinds.
//
// GROUPS are keyed by metadata.name, which is what Resolve stamps onto
// navmodel.Group.NavGroupRef. Cluster-scoped, so the key cannot collide.
//
// ENTRIES are keyed by destination, and this is the part worth reading twice. A derived entry
// comes from an IngressRoute, which carries no visibility annotation and deliberately does not
// gain one — a `catalyst.nav/visibility-groups` annotation would be a second, un-schema'd way
// to say the thing the CRD already says, and the entire argument for these CRDs
// (navgroup-crd.yaml's header) is that a bare annotation string has no spellchecker and forks.
// So the carrier for a derived entry's visibility is a NavEntry pointed at the same href, which
// is the role naventry-crd.yaml already reserves for the object:
//
//	"overriding one field of an otherwise-derived entry (a later phase's reconciler is
//	 expected to let a NavEntry win over the derived value for the same destination)"
//
// This is that reconciler, for exactly one field: visibility. It does NOT yet let a NavEntry
// override title/order/themed, and it does NOT inject NavEntry-only destinations into the
// served manifest — both are phase 5. Scoping phase 3 to filtering alone is what keeps the
// guarantee that an unrestricted identity receives byte-for-byte the manifest the sidecar
// serves today, which is a property a test can hold onto (see
// TestUnrestrictedIdentityGetsTheUnfilteredBytes).
//
// A NavEntry with no visibility, or an empty authentikGroups, contributes NO rule rather than
// an unrestricted one. Same outcome for a lone entry, but it matters on a collision: two
// namespaces may each claim the same destination, and Rule.And intersects them, so inserting a
// permissive rule for the silent one would widen the restrictive one's grant.
func BuildVisibilityIndex(
	groups []navv1alpha1.NavGroup,
	entries []navv1alpha1.NavEntry,
) visibility.Index {
	ix := visibility.Index{
		Groups:  map[string]visibility.Rule{},
		Entries: map[string]visibility.Rule{},
	}

	for i := range groups {
		g := &groups[i]
		if r := ruleFor(g.Spec.Visibility); r.Restricted {
			ix.Groups[g.Name] = r
		}
	}

	for i := range entries {
		e := &entries[i]
		r := ruleFor(e.Spec.Visibility)
		if !r.Restricted {
			continue
		}
		key := visibility.DestinationKey(e.Spec.Href)
		if prev, dup := ix.Entries[key]; dup {
			// Fail closed on a collision — see Rule.And.
			r = prev.And(r)
		}
		ix.Entries[key] = r
	}

	return ix
}

// ruleFor reads one spec.visibility. A nil pointer and an empty list are the same thing: both
// mean "visible to everyone", which both CRDs state in their own words ("Omit entirely, or
// leave authentikGroups empty, for a group visible to everyone").
func ruleFor(v *navv1alpha1.Visibility) visibility.Rule {
	if v == nil {
		return visibility.Unrestricted()
	}
	return visibility.NewRule(v.AuthentikGroups)
}
