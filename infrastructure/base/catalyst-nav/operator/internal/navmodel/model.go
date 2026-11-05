// Package navmodel builds the Catalyst nav manifest from a set of IngressRoutes, plus (phase
// 2+) NavGroup/NavEntry objects. It is a PURE package: no Kubernetes client, no API types, no
// I/O. Input is plain decoded JSON; output is a Manifest and its bytes.
//
// That boundary is the point. build_nav.py is a 355-line script wired to stdin/stdout inside a
// supervision loop, so the only way to exercise its model was to shell out to it — which is
// exactly what tests/nav/test_build_nav.py has to do, and why it documents "deliberately a
// subprocess rather than an import". Keeping the model free of the cluster means the
// reconciler, the one-shot `render` parity mode, and phase 3's per-identity manifest endpoint
// all build the SAME model three different ways, and the table tests reach it directly.
//
// PHASE 3 IS NOT IMPLEMENTED HERE and must not be: this package knows nothing about
// identities, Authentik groups or HTTP. Visibility filtering belongs on top of Build()'s
// output, not inside it — see Manifest's comment.
package navmodel

import "encoding/json"

// Item is one app's entry in the bar.
type Item struct {
	Name   string
	Weight int
	Href   string
	Themed bool

	// Group is carried through Build and dropped by the encoder, mirroring build_nav.py's
	// `{k: v for k, v in i.items() if k != "group"}` — the group name is already the key
	// one level up, so repeating it per item would be redundant bytes in a file served on
	// every page load of ~40 apps.
	Group string

	// Source records where this entry came from so a controller can write a status
	// condition against the right object. Unused by the encoder — it never reaches the
	// manifest, and it is the reason Build's result is not simply the JSON bytes.
	Source Source
}

// Source identifies the object that produced an Item or a rejection.
type Source struct {
	Kind      string // "IngressRoute" | "NavEntry"
	Namespace string
	Name      string
}

// Group is one dropdown.
type Group struct {
	Name  string
	Items []Item

	// NavGroupRef is the metadata.name of the NavGroup this dropdown resolved to, or "" when
	// the group came from a free-text gethomepage.dev/group with no matching NavGroup. Empty
	// here is precisely the condition the webhook exists to prevent for NavEntry and that
	// phase 5 has to clear for annotations — see Rejection.
	NavGroupRef string
}

// Manifest is the model. Build returns it; Encode renders it.
//
// Phase 3 note: an authenticated per-identity endpoint filters a Manifest by the viewer's
// Authentik groups. That filter needs NavGroup.spec.visibility, which is why Group carries
// NavGroupRef rather than only the display string — but the filter itself is NOT here, and
// adding it to Build would make the parity mode's output depend on an identity it does not
// have.
type Manifest struct {
	Groups   []Group
	Defaults OrderedConfig
	Hosts    OrderedHosts

	// Rejections is everything Build refused, with a reason. build_nav.py's equivalent is a
	// line on stderr inside a sidecar nobody reads — which is the feedback gap phase 2
	// exists to close. These become status.conditions.
	Rejections []Rejection
}

// Rejection is one thing that did not make it into the manifest, and why.
type Rejection struct {
	Source  Source
	Reason  string // a CamelCase condition reason, e.g. "NavGroupNotFound"
	Message string // human-readable, names the offending value
}

// OrderedConfig is a string-keyed map that remembers insertion order.
//
// Needed because the manifest's byte layout has to match Python dict order (see encode.go).
// Deliberately not a []struct{K,V}: lookup-by-key is used on every annotation, and callers
// read it as a map.
type OrderedConfig struct {
	Keys   []string
	Values map[string]any
}

// Set inserts or overwrites. An overwrite keeps the key's ORIGINAL position, which is what
// Python dicts do and therefore what the bytes depend on.
func (o *OrderedConfig) Set(k string, v any) {
	if o.Values == nil {
		o.Values = map[string]any{}
	}
	if _, seen := o.Values[k]; !seen {
		o.Keys = append(o.Keys, k)
	}
	o.Values[k] = v
}

func (o *OrderedConfig) Len() int { return len(o.Keys) }

// Get reports the value and whether the key is present.
func (o *OrderedConfig) Get(k string) (any, bool) {
	v, ok := o.Values[k]
	return v, ok
}

// OrderedHosts maps hostname -> per-host config, in first-seen order.
type OrderedHosts struct {
	Keys   []string
	Values map[string]OrderedConfig
}

func (o *OrderedHosts) Set(k string, v OrderedConfig) {
	if o.Values == nil {
		o.Values = map[string]OrderedConfig{}
	}
	if _, seen := o.Values[k]; !seen {
		o.Keys = append(o.Keys, k)
	}
	o.Values[k] = v
}

// Applet is one dockable bundle advertised by a catalyst.nav/applet-src annotation.
type Applet struct {
	Src string
}

// Doc is the shape of `kubectl get ingressroutes -A -o json`, decoded only as far as this
// package reads it. Untyped `any` for annotation values on purpose: the input is whatever the
// apiserver emitted, and build_nav.py's tolerance for a wrong type (it catches TypeError
// alongside ValueError) is behaviour the port has to keep.
type Doc struct {
	Items []Object `json:"items"`
}

// Object is one IngressRoute.
type Object struct {
	Metadata Metadata `json:"metadata"`
	Spec     Spec     `json:"spec"`
}

type Metadata struct {
	Name        string            `json:"name"`
	Namespace   string            `json:"namespace"`
	Annotations map[string]string `json:"annotations"`

	// nameAbsent distinguishes a missing metadata.name from an empty one, because
	// build_nav.py's `meta.get("name", host.split(".")[0])` falls back ONLY when the key is
	// absent — an explicit empty string is used as-is and titles to "".
	nameAbsent bool
}

// UnmarshalJSON records whether metadata.name was present at all.
func (m *Metadata) UnmarshalJSON(b []byte) error {
	var raw struct {
		Name        *string           `json:"name"`
		Namespace   string            `json:"namespace"`
		Annotations map[string]string `json:"annotations"`
	}
	if err := json.Unmarshal(b, &raw); err != nil {
		return err
	}
	m.Namespace = raw.Namespace
	m.Annotations = raw.Annotations
	if raw.Name == nil {
		m.nameAbsent = true
		m.Name = ""
	} else {
		m.Name = *raw.Name
	}
	return nil
}

type Spec struct {
	Routes []Route `json:"routes"`
}

type Route struct {
	Match       string       `json:"match"`
	Middlewares []Middleware `json:"middlewares"`
}

type Middleware struct {
	Name      string `json:"name"`
	Namespace string `json:"namespace"`
}
