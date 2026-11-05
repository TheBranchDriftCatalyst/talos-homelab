// Package visibility narrows a built nav model down to what one identity is allowed to see.
//
// A SECOND PURE PACKAGE, deliberately layered ON TOP of navmodel rather than inside it.
// navmodel's own doc comment states the boundary and why it exists:
//
//	"PHASE 3 IS NOT IMPLEMENTED HERE and must not be: this package knows nothing about
//	 identities, Authentik groups or HTTP. Visibility filtering belongs on top of Build()'s
//	 output, not inside it"
//
// So nothing here touches derivation. Build() keeps producing the one true unfiltered model —
// the thing `catalyst-nav-operator render` diffs byte-for-byte against build_nav.py — and
// Filter() produces a per-identity VIEW of it. The parity gate and this package cannot
// interfere with each other, because the filter is a function of the model and never a
// parameter to it.
//
// Pure, same as navmodel: no client, no HTTP, no clock, no environment. The Identity comes in
// as a value. internal/navserve is the layer that decides what an HTTP request's identity IS,
// and that is exactly where the trust question lives — see its threat model.
package visibility

import (
	"strings"

	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/navmodel"
)

// Identity is the caller, reduced to the only thing the filter asks about: group membership.
//
// Constructed through NewIdentity/Anonymous so the group set is always normalised and the zero
// value is the SAFE one — an Identity{} is a member of nothing, which means a zero value that
// leaked into the filter by mistake shows the public subset rather than everything.
type Identity struct {
	// Username is carried for logs and metrics only. The filter never reads it: per-user
	// visibility is not a thing either CRD can express, and adding it here would invent a
	// surface the schemas do not have.
	Username string

	// Attested records whether the request that produced this identity provably came
	// through the forward-auth proxy. Also not read by the filter — an unattested request
	// is turned into Anonymous() by the server BEFORE it gets here, so by the time the
	// filter sees an Identity with groups, those groups have already been accepted. Kept so
	// the server can label its metrics without re-deriving it.
	Attested bool

	groups map[string]struct{}
}

// NewIdentity normalises a raw group list into an Identity.
//
// Whitespace is trimmed and empties dropped, because the header this comes from is a
// separator-joined string and "a||b" is a real thing to receive. Case is NOT folded:
// Authentik group names are case-sensitive, and folding here would admit a member of "media"
// to a NavGroup restricted to "Media" — which is a widening, and a widening is the one
// direction this code must never guess in.
func NewIdentity(username string, groups []string, attested bool) Identity {
	id := Identity{Username: username, Attested: attested, groups: map[string]struct{}{}}
	for _, g := range groups {
		if g = strings.TrimSpace(g); g != "" {
			id.groups[g] = struct{}{}
		}
	}
	return id
}

// Anonymous is an identity in no groups at all: it sees exactly the items and groups that
// carry no visibility restriction.
//
// THIS IS THE DEGRADED STATE, NOT AN ERROR STATE. Most apps carrying the nav bar are not
// behind forward-auth at all (Plex and Jellyfin are served over plain HTTP; see
// themepark/asset-route.yaml), so a request with no identity headers is the NORMAL case for a
// large part of the cluster, not a failure. Returning the public subset keeps the bar working
// there, and it is also what an unattested request gets — so a client that invents its own
// X-authentik-groups ends up with no more than any LAN browser already has today.
func Anonymous() Identity {
	return Identity{groups: map[string]struct{}{}}
}

// InGroup reports membership.
func (i Identity) InGroup(name string) bool {
	_, ok := i.groups[name]
	return ok
}

// Groups returns the membership set, for logs. Copied: the caller must not be able to widen an
// identity after it has been built.
func (i Identity) Groups() []string {
	out := make([]string, 0, len(i.groups))
	for g := range i.groups {
		out = append(out, g)
	}
	return out
}

// Rule is one object's spec.visibility, reduced to a decision.
//
// Restricted is a SEPARATE FIELD from the allow set rather than being inferred from
// len(Allow) > 0, because the two CRDs define an empty list as "everyone":
//
//	"Omit entirely, or leave authentikGroups empty, for a group visible to everyone"
//
// while an INTERSECTION of two allow-lists can legitimately come out empty and must then mean
// "nobody" (see And). Inferring from length would collapse those two into each other and turn
// the most restrictive possible rule into the most permissive one.
type Rule struct {
	Restricted bool
	Allow      map[string]struct{}
}

// Unrestricted is the rule for an object that stated no visibility: visible to everyone.
func Unrestricted() Rule { return Rule{} }

// NewRule builds a rule from a spec.visibility.authentikGroups list.
//
// A list whose every element is blank counts as UNRESTRICTED, matching the CRD's "leave
// authentikGroups empty" wording: `authentikGroups: [""]` is a malformed way of saying nothing,
// and the apiserver already rejects it (items have minLength: 1), so treating it as "nobody"
// here would only ever punish a path that cannot occur through admission.
func NewRule(groups []string) Rule {
	r := Rule{Allow: map[string]struct{}{}}
	for _, g := range groups {
		if g = strings.TrimSpace(g); g != "" {
			r.Allow[g] = struct{}{}
			r.Restricted = true
		}
	}
	return r
}

// Admits reports whether id may see the thing this rule guards.
//
// Membership in ANY listed group is enough. That is the only reading the CRD supports — it
// calls the field a list of "Authentik group names allowed to see this nav group", not a set of
// requirements — and it is what makes the field usable: the six-group Authentik model this
// cluster runs puts a person in one or two groups, not all of them.
func (r Rule) Admits(id Identity) bool {
	if !r.Restricted {
		return true
	}
	for g := range r.Allow {
		if id.InGroup(g) {
			return true
		}
	}
	return false
}

// And combines two rules guarding the same thing into the rule that admits only identities
// both would admit.
//
// Needed because NavEntry is NAMESPACED: two namespaces can each carry a NavEntry claiming the
// same destination, and nothing in the schema stops them. Taking the first by some ordering
// would silently drop the other one's restriction, which is a fail-OPEN on a collision. The
// intersection fails closed instead, and if the intersection is empty the destination is hidden
// from everybody — a visible, reportable outcome rather than an invisible widening.
func (r Rule) And(o Rule) Rule {
	switch {
	case !r.Restricted:
		return o
	case !o.Restricted:
		return r
	}
	out := Rule{Restricted: true, Allow: map[string]struct{}{}}
	for g := range r.Allow {
		if _, ok := o.Allow[g]; ok {
			out.Allow[g] = struct{}{}
		}
	}
	return out
}

// Index is the visibility rules of the whole cluster, keyed the way Filter needs them.
//
// Built by internal/controller from NavGroup and NavEntry objects — that is where the typed
// Kubernetes API lives — and consumed here. Keeping the two apart is what lets the filter be
// table-tested without a scheme, a client or an envtest control plane.
type Index struct {
	// Groups is keyed by NavGroup metadata.name, which is what navmodel.Group.NavGroupRef
	// carries after internal/controller.Resolve has run.
	//
	// A manifest group whose NavGroupRef is EMPTY — a free-text gethomepage.dev/group that
	// matched no NavGroup — therefore finds no rule and is visible to everyone. That is a
	// fail-open, and it is the right one: the alternative is that a typo in an annotation
	// blanks a whole section of the bar for every user. It is also already reported, not
	// silent — Resolve raises a Degraded/UnresolvedGroupNames condition on the nearly-matched
	// NavGroup for exactly this case. The consequence to understand is that you cannot
	// restrict a section whose name does not resolve: making visibility bite requires the
	// NavGroup to actually match, which is phase 5's job.
	Groups map[string]Rule

	// Entries is keyed by DestinationKey of the entry's href.
	//
	// WHY HREF AND NOT A NAME. Derived entries come from IngressRoutes, which carry no
	// visibility annotation and should not gain one — a per-entry annotation would be a
	// second, un-schema'd place to express the same thing the CRD already expresses. So the
	// carrier for a derived entry's visibility is a NavEntry pointed at the same
	// destination, which is precisely the role naventry-crd.yaml already reserves for the
	// object: "overriding one field of an otherwise-derived entry". The href is the only
	// field both populations share — the derived side has a hostname parsed out of a
	// Traefik match rule and a title derived from an annotation, so matching on the title
	// would make visibility depend on a display string.
	Entries map[string]Rule
}

// ruleForGroup resolves a manifest group's rule.
func (ix Index) ruleForGroup(g navmodel.Group) Rule {
	if g.NavGroupRef == "" {
		return Unrestricted()
	}
	return ix.Groups[g.NavGroupRef]
}

// DestinationKey normalises an href into the key Index.Entries uses.
//
// Scheme-insensitive and trailing-slash-insensitive, because the two sides spell the same
// destination differently and both spellings are legal. Build() emits
// "https://" + host + "/" for every derived entry; a hand-written NavEntry's href only has to
// satisfy the CRD's `^(https?://\S+|/\S*)$`, so "http://grafana.talos00" and
// "https://grafana.talos00/" are both valid ways to name the same app. The host is lowercased
// (DNS is case-insensitive); the PATH is not, because paths are not.
//
// A path-only href ("/foo") keys as "/foo" and can never collide with a derived entry, which
// always has a host — so an in-cluster NavEntry cannot accidentally restrict an app.
func DestinationKey(href string) string {
	s := strings.TrimSpace(href)
	for _, scheme := range []string{"https://", "http://"} {
		if len(s) >= len(scheme) && strings.EqualFold(s[:len(scheme)], scheme) {
			s = s[len(scheme):]
			break
		}
	}
	host, path := s, ""
	if i := strings.IndexByte(s, '/'); i >= 0 {
		host, path = s[:i], s[i:]
	}
	return strings.ToLower(host) + strings.TrimSuffix(path, "/")
}

// hostOf extracts the hostname an item points at, for pruning Manifest.Hosts.
func hostOf(href string) string {
	key := DestinationKey(href)
	if i := strings.IndexByte(key, '/'); i >= 0 {
		key = key[:i]
	}
	return key
}

// Filter returns the view of m that id may see. m is not modified.
//
// THREE RULES, in this order:
//
//  1. A group whose NavGroup denies id is dropped WHOLE, items and all. This is the
//     requirement that a section can disappear rather than merely thin out, and it is why the
//     group check runs before the item loop instead of being folded into it.
//  2. Within a surviving group, each item is checked against its own rule.
//  3. A group left with no items is dropped. Encoding it would render an empty dropdown —
//     a control that opens onto nothing, which tells the user there is something there they
//     cannot have. Dropping it is both better UI and strictly less disclosure.
//
// AND ONE THAT IS EASY TO MISS: Manifest.Hosts is pruned to the surviving hostnames. Its keys
// ARE hostnames, so leaving it whole would leak, through a per-host config block, exactly the
// internal hostnames the group filter just removed from `groups`. Build() already applies the
// same rule to its own output for the same reason ("an annotation on a route that was filtered
// out must not ship config for an app nobody can see"); this is that invariant restated for the
// per-identity case, and TestHostsAreNarrowedToSurvivingEntries is what keeps it true.
//
// Defaults are NOT filtered. They are cluster-wide presentation knobs (animation intensity,
// bar height) plus the applet list, whose srcs are /catalyst/ paths rather than hostnames —
// nothing identifying, and nothing either CRD can attach a visibility to.
//
// Rejections are not carried over: they are operator-facing diagnostics that the encoder never
// emits, and they name objects the caller may not be allowed to know about.
func Filter(m *navmodel.Manifest, ix Index, id Identity) *navmodel.Manifest {
	out := &navmodel.Manifest{Defaults: m.Defaults}
	surviving := map[string]struct{}{}

	for _, g := range m.Groups {
		if !ix.ruleForGroup(g).Admits(id) {
			continue
		}
		kept := make([]navmodel.Item, 0, len(g.Items))
		for _, it := range g.Items {
			if !ix.Entries[DestinationKey(it.Href)].Admits(id) {
				continue
			}
			kept = append(kept, it)
			if h := hostOf(it.Href); h != "" {
				surviving[h] = struct{}{}
			}
		}
		if len(kept) == 0 {
			continue
		}
		out.Groups = append(out.Groups, navmodel.Group{
			Name:        g.Name,
			Items:       kept,
			NavGroupRef: g.NavGroupRef,
		})
	}

	for _, h := range m.Hosts.Keys {
		if _, live := surviving[h]; live {
			out.Hosts.Set(h, m.Hosts.Values[h])
		}
	}
	return out
}
