// Package v1alpha1 contains the Go types for nav.catalyst.io/v1alpha1.
//
// +kubebuilder:object:generate=true
// +groupName=nav.catalyst.io
package v1alpha1

import (
	"k8s.io/apimachinery/pkg/runtime/schema"
	"sigs.k8s.io/controller-runtime/pkg/scheme"
)

// GroupVersion is nav.catalyst.io/v1alpha1, matching the CRDs in this component.
var GroupVersion = schema.GroupVersion{Group: "nav.catalyst.io", Version: "v1alpha1"}

// SchemeBuilder registers these types into a runtime.Scheme.
var SchemeBuilder = &scheme.Builder{GroupVersion: GroupVersion}

// AddToScheme adds these types to a Scheme.
var AddToScheme = SchemeBuilder.AddToScheme
