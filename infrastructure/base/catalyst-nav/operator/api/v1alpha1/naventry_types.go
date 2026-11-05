package v1alpha1

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// NavEntrySpec is one explicit navbar listing: an override of a derived entry, or an entry for
// a destination that has no IngressRoute of its own to derive from.
//
// Override/inject ONLY — see naventry-crd.yaml's header. The common path is derivation, and an
// urge to make NavEntry the normal way of adding an app's listing is a sign the derivation
// path is missing something.
type NavEntrySpec struct {
	// Title is the display name in the navbar.
	Title string `json:"title"`

	// Href is an absolute URL (http:// or https://) for anything outside this cluster, or an
	// absolute path beginning with "/" for an in-cluster destination.
	Href string `json:"href"`

	// NavGroupRef is the metadata.name of the target NavGroup (cluster-scoped, so no
	// namespace).
	//
	// THE WEBHOOK IS WHAT MAKES THIS FIELD MEAN ANYTHING. The CRD schema types it as a bare
	// string and says so: "NOT validated against actually-existing NavGroup objects — an
	// OpenAPI schema has no way to look at other objects". internal/webhook closes exactly
	// that gap, and it is the main justification for the whole CRD effort — without it a
	// typo here fails as silently as a typo'd gethomepage.dev/group, which is how this
	// cluster ended up with both "Monitoring" and "Observability".
	NavGroupRef string `json:"navGroupRef"`

	// Order is the position within the target group, same multiples-of-10 scale as
	// NavGroup.spec.order. The CRD defaults it to 500.
	// +optional
	Order int32 `json:"order,omitempty"`

	// Themed mirrors the flag build_nav.py derives from middleware names: whether the
	// destination gets the full Catalyst visual treatment (rendered undimmed) versus an
	// unthemed destination that is dimmed so it is obvious you are leaving the styled set.
	// A hand-written NavEntry has no middleware to derive this from, so it is stated.
	// +optional
	Themed bool `json:"themed,omitempty"`

	// +optional
	Lifecycle Lifecycle `json:"lifecycle,omitempty"`

	// +optional
	Visibility *Visibility `json:"visibility,omitempty"`
}

// NavEntryStatus reports whether this entry reached the manifest.
type NavEntryStatus struct {
	// Conditions carries Published: True when the entry is in the published model, False
	// with a reason when it is not.
	//
	// The webhook rejects a dangling navGroupRef at admission, so the ONLY way a
	// NavGroupNotFound condition appears here is a group deleted after the entry was
	// accepted — which admission cannot prevent and which is therefore precisely what this
	// condition is for. Writing one before the webhook existed would have been the common
	// case; now it is the residual case.
	// +optional
	Conditions []metav1.Condition `json:"conditions,omitempty"`

	// ResolvedGroup is the title of the NavGroup this entry rendered under, for an operator
	// reading `kubectl get naventries -o wide` rather than chasing the ref by hand.
	// +optional
	ResolvedGroup string `json:"resolvedGroup,omitempty"`

	// +optional
	ObservedGeneration int64 `json:"observedGeneration,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status

// NavEntry is one explicit navbar listing. Namespaced: it belongs to whichever app's manifests
// it rides along with, so it moves and deletes with that app.
type NavEntry struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   NavEntrySpec   `json:"spec,omitempty"`
	Status NavEntryStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// NavEntryList is a list of NavEntry.
type NavEntryList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []NavEntry `json:"items"`
}

func init() {
	SchemeBuilder.Register(&NavEntry{}, &NavEntryList{})
}
