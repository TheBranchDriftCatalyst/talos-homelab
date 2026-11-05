package v1alpha1

// Go types for the CRDs in infrastructure/base/catalyst-nav/{navgroup,naventry}-crd.yaml.
//
// THE YAML IS THE SOURCE OF TRUTH, not these structs. The CRDs were written and reviewed in
// phase 1 with the CEL rules, patterns and prose descriptions that carry the argument for each
// field; regenerating them from kubebuilder markers here would throw all of that away and
// replace it with terser, worse schemas. So these types carry NO kubebuilder validation
// markers — only the markers controller-gen needs for DeepCopy and for the client's scheme.
//
// What that costs: the two can drift. What keeps them honest is that every field below is
// exercised against the real CRDs by the envtest suite, which installs the phase-1 YAML and
// round-trips these structs through the apiserver — so a field renamed in one and not the
// other fails a test rather than silently reading zero.

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// Lifecycle mirrors the CRDs' `lifecycle` enum.
//
// The enum itself is enforced by the CRD schema, not here — see navgroup-crd.yaml's comment
// about the CatalystCNPGAppDB XRD that CLAIMED a constraint it did not enforce. A Go string
// type is documentation; the apiserver is the enforcement.
type Lifecycle string

const (
	// LifecycleStable: generally-available, expected to keep working.
	LifecycleStable Lifecycle = "stable"
	// LifecycleExperimental: may move, rename or disappear without the usual notice.
	LifecycleExperimental Lifecycle = "experimental"
)

// Visibility is the shared shape of spec.visibility on both kinds.
type Visibility struct {
	// AuthentikGroups lists the Authentik group names allowed to see this item. Empty or
	// absent means visible to everyone.
	//
	// NOT consumed by this phase. Phase 3's per-identity endpoint filters on it; phase 2
	// only carries it through the model so that filter has something to read. Getting a
	// name wrong fails safe — a nonexistent Authentik group matches nobody.
	// +optional
	AuthentikGroups []string `json:"authentikGroups,omitempty"`
}

// NavGroupSpec is one entry in the navbar's top-level taxonomy.
type NavGroupSpec struct {
	// Title is the display label in the dropdown header.
	Title string `json:"title"`

	// Order is where this group sits relative to every other group; lower sorts first.
	// Multiples of 10 from 10 to 990, enforced by CEL in the CRD.
	Order int32 `json:"order"`

	// Icon is a dashboard-icons filename (e.g. "grafana.png"), not a URL.
	// +optional
	Icon string `json:"icon,omitempty"`

	// +optional
	Lifecycle Lifecycle `json:"lifecycle,omitempty"`

	// +optional
	Visibility *Visibility `json:"visibility,omitempty"`
}

// NavGroupStatus reports what the controller published into this group and what it refused.
//
// This is the feedback channel the annotation pipeline never had: today a bad
// gethomepage.dev/group is a line on a sidecar's stderr, inside a pod whose logs nobody reads,
// and the only symptom is an app missing from the bar. These conditions make the same facts
// `kubectl describe`-able.
type NavGroupStatus struct {
	// Conditions carries Published (did this group render, with how many entries) and
	// Degraded (were any candidate entries refused, and why).
	// +optional
	Conditions []metav1.Condition `json:"conditions,omitempty"`

	// PublishedEntries is how many entries currently resolve into this group.
	// +optional
	PublishedEntries int32 `json:"publishedEntries,omitempty"`

	// ObservedGeneration is the spec generation these conditions describe.
	// +optional
	ObservedGeneration int64 `json:"observedGeneration,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:resource:scope=Cluster

// NavGroup is one dropdown group in the Catalyst navbar. Cluster-scoped: a navbar group is
// cluster-wide taxonomy, not a thing any one app namespace owns.
type NavGroup struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   NavGroupSpec   `json:"spec,omitempty"`
	Status NavGroupStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// NavGroupList is a list of NavGroup.
type NavGroupList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []NavGroup `json:"items"`
}

func init() {
	SchemeBuilder.Register(&NavGroup{}, &NavGroupList{})
}
