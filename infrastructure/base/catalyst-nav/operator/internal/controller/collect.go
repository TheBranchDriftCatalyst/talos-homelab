package controller

// Turning the cluster into a navmodel.Doc.
//
// The model package takes decoded JSON, not typed Kubernetes objects, because that is the
// shape build_nav.py consumes and parity is measured against build_nav.py. So this file is the
// adapter: list IngressRoutes (and CatalystWebSecureIngress claims) through the controller's
// cache, flatten them into the same structure `kubectl get -o json` produces, and hand that to
// navmodel.Build.
//
// Unstructured on purpose. Vendoring Traefik's and Crossplane's Go types would pull two large
// module trees in for four fields apiece, and worse, would pin this operator to a Traefik
// CRD version — IngressRoute's Go type has changed shape across traefik minors while the four
// fields read here (metadata.annotations, spec.routes[].match, .middlewares[].name) have not.

import (
	"context"
	"encoding/json"
	"fmt"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"sigs.k8s.io/controller-runtime/pkg/client"

	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/navmodel"
)

// IngressRouteGVK is traefik.io/v1alpha1 IngressRoute — the entry source today.
var IngressRouteGVK = schema.GroupVersionKind{
	Group: "traefik.io", Version: "v1alpha1", Kind: "IngressRouteList",
}

// WebSecureIngressGVK is net.catalyst.io/v1alpha1 CatalystWebSecureIngress, the Crossplane
// composite most new apps are onboarded through.
//
// WHY WATCH THE CLAIM AS WELL AS THE ROUTE IT COMPOSES. The composite patches
// spec.homepage.{enabled,name,group,icon,weight} onto the IngressRoute it mints, and Kyverno's
// homepage-annotation-derivation policy then adds siteMonitor/href/widget.url. So the route's
// annotations are only complete after two asynchronous passes, and an operator that watched
// only routes would reconcile a half-annotated object and publish an entry with the wrong name
// — then publish it again when the annotations landed. Watching the claim gives the reconciler
// an EAGER, authoritative signal that something nav-relevant changed; the route stays the
// source of the derived values. See infrastructure/base/catalyst-websecure-ingress/.
var WebSecureIngressGVK = schema.GroupVersionKind{
	Group: "net.catalyst.io", Version: "v1alpha1", Kind: "CatalystWebSecureIngressList",
}

// CollectDoc lists every IngressRoute in the cluster and flattens it into the document shape
// navmodel consumes.
func CollectDoc(ctx context.Context, c client.Client) (*navmodel.Doc, error) {
	var list unstructured.UnstructuredList
	list.SetGroupVersionKind(IngressRouteGVK)
	if err := c.List(ctx, &list); err != nil {
		return nil, fmt.Errorf("listing IngressRoutes: %w", err)
	}
	// Round-tripping through JSON rather than hand-walking the unstructured maps: it is the
	// same decode path the parity mode takes, so the two cannot disagree about how a field
	// is read. Hand-walking would be faster and would be a second implementation of the
	// one thing this component must not have two of.
	raw, err := json.Marshal(map[string]any{"items": list.Items})
	if err != nil {
		return nil, fmt.Errorf("re-encoding IngressRoutes: %w", err)
	}
	var doc navmodel.Doc
	if err := json.Unmarshal(raw, &doc); err != nil {
		return nil, fmt.Errorf("decoding IngressRoutes: %w", err)
	}
	return &doc, nil
}
