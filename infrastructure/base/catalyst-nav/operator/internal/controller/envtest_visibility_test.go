package controller_test

// Phase 3 end to end against a REAL apiserver, reusing envtest_test.go's harness
// (startEnv/installIngressRouteCRD/reconcileRequest live there).
//
// Kept in its own file rather than appended to envtest_test.go because it is the only envtest
// in the suite that is about SERVING rather than about admission or the CRD schemas, and it is
// the one a reviewer of the visibility work needs to find.

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"sigs.k8s.io/controller-runtime/pkg/client"

	navv1alpha1 "github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/api/v1alpha1"
	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/controller"
	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/navmodel"
	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/navserve"
)

// TestEnvtestPerIdentityEndpointServesFromTheSameBuild wires the whole phase: a real NavGroup
// with a real spec.visibility, two real derived IngressRoutes, one reconcile, then the HTTP
// endpoint answering two different callers.
//
// What only this test can prove — the unit suites each hold one end of it:
//
//   - The ConfigMap keeps the UNFILTERED manifest. The published document is what phase 6's
//     byte audit diffs against build_nav.py, so a visibility object must never reach it. A
//     reconciler that filtered before publishing would pass every navserve and visibility test
//     in the repo.
//   - The endpoint's snapshot and the ConfigMap's annotation carry the SAME revision, which is
//     what makes "the endpoint is serving the published build" checkable rather than assumed.
//   - spec.visibility survives a round trip through the hand-written CRD schema. The Go struct
//     carries no kubebuilder validation markers (navgroup_types.go explains why), so a field
//     renamed on one side and not the other would read back as an empty allow-list — i.e. as
//     "visible to everyone", silently disabling the entire feature with every test still green.
func TestEnvtestPerIdentityEndpointServesFromTheSameBuild(t *testing.T) {
	k8s, _, done := startEnv(t)
	defer done()
	ctx := context.Background()

	if err := k8s.Create(ctx, &corev1.Namespace{
		ObjectMeta: metav1.ObjectMeta{Name: "catalyst-nav"},
	}); err != nil && !apierrors.IsAlreadyExists(err) {
		t.Fatal(err)
	}
	// CollectDoc hard-errors without the IngressRoute CRD, deliberately — see
	// envtest_test.go.
	if err := installIngressRouteCRD(ctx, k8s); err != nil {
		t.Skipf("could not install a minimal IngressRoute CRD: %v", err)
	}

	// Two derived apps in two groups. Only one group will be restricted.
	for _, app := range []struct{ name, host, group string }{
		{"plex", "plex.talos00", "Media"},
		{"grafana", "grafana.talos00", "Observability"},
	} {
		ir := &unstructured.Unstructured{}
		ir.SetGroupVersionKind(schema.GroupVersionKind{
			Group: "traefik.io", Version: "v1alpha1", Kind: "IngressRoute",
		})
		ir.SetName(app.name)
		ir.SetNamespace("default")
		ir.SetAnnotations(map[string]string{
			"gethomepage.dev/enabled": "true",
			"gethomepage.dev/name":    app.name,
			"gethomepage.dev/group":   app.group,
		})
		if err := unstructured.SetNestedSlice(ir.Object, []any{
			map[string]any{
				"match": fmt.Sprintf("Host(`%s`)", app.host),
				"middlewares": []any{
					map[string]any{"name": "catalyst-nav", "namespace": "traefik"},
				},
			},
		}, "spec", "routes"); err != nil {
			t.Fatal(err)
		}
		if err := k8s.Create(ctx, ir); err != nil {
			t.Fatalf("creating the %s IngressRoute: %v", app.name, err)
		}
	}

	// The restriction. Title "Media" is what the derived group carries, so Resolve binds the
	// two and the rule has a ref to key off — without that binding the rule is unreachable
	// and the whole group would stay public (see visibility.Index's comment).
	if err := k8s.Create(ctx, &navv1alpha1.NavGroup{
		ObjectMeta: metav1.ObjectMeta{Name: "media"},
		Spec: navv1alpha1.NavGroupSpec{
			Title: "Media", Order: 10,
			Visibility: &navv1alpha1.Visibility{AuthentikGroups: []string{"catalyst-media"}},
		},
	}); err != nil {
		t.Fatal(err)
	}

	var ng navv1alpha1.NavGroup
	if err := k8s.Get(ctx, client.ObjectKey{Name: "media"}, &ng); err != nil {
		t.Fatal(err)
	}
	if ng.Spec.Visibility == nil || len(ng.Spec.Visibility.AuthentikGroups) != 1 ||
		ng.Spec.Visibility.AuthentikGroups[0] != "catalyst-media" {
		t.Fatalf("spec.visibility did not survive the apiserver round trip: %+v",
			ng.Spec.Visibility)
	}

	snapshots := &navserve.Store{}
	r := &controller.NavReconciler{
		Client: k8s, Namespace: "catalyst-nav", ConfigMapName: "catalyst-nav-manifest",
		Snapshots: snapshots,
		Options:   navmodel.Options{},
	}
	if _, err := r.Reconcile(ctx, reconcileRequest()); err != nil {
		t.Fatalf("reconcile failed: %v", err)
	}

	// ── 1. the ConfigMap is UNFILTERED ──────────────────────────────────────────────────
	var cm corev1.ConfigMap
	if err := k8s.Get(ctx, client.ObjectKey{
		Namespace: "catalyst-nav", Name: "catalyst-nav-manifest",
	}, &cm); err != nil {
		t.Fatalf("manifest ConfigMap was not published: %v", err)
	}
	published := cm.Data[controller.ManifestKey]
	for _, host := range []string{"plex.talos00", "grafana.talos00"} {
		if !strings.Contains(published, host) {
			t.Fatalf("the published ConfigMap is missing %s — a visibility object reached "+
				"the manifest phase 6 audits:\n%s", host, published)
		}
	}

	// ── 2. the endpoint serves the SAME build, filtered ─────────────────────────────────
	snap := snapshots.Snapshot()
	if snap == nil {
		t.Fatal("the reconcile published no snapshot; the endpoint would serve 503 forever")
	}
	if got, want := snap.Revision, cm.Annotations["nav.catalyst.io/manifest-sha256"]; got != want {
		t.Errorf("snapshot revision %q != ConfigMap annotation %q — the endpoint and the "+
			"ConfigMap cannot be shown to describe one build", got, want)
	}

	h := navserve.NewHandler(snapshots, navserve.Config{}, nil)
	body := func(groups string) string {
		t.Helper()
		req := httptest.NewRequest(http.MethodGet, h.Path(), nil)
		if groups != "" {
			req.Header.Set(navserve.DefaultGroupsHeader, groups)
		}
		w := httptest.NewRecorder()
		h.ServeHTTP(w, req)
		if w.Code != http.StatusOK {
			t.Fatalf("groups=%q: status = %d, want 200", groups, w.Code)
		}
		if cc := w.Header().Get("Cache-Control"); cc != "private, no-store" {
			t.Errorf("groups=%q: Cache-Control = %q, want `private, no-store`", groups, cc)
		}
		return w.Body.String()
	}

	outsider := body("catalyst-users")
	member := body("catalyst-media")

	if strings.Contains(outsider, "plex.talos00") {
		t.Errorf("a non-member received the restricted hostname:\n%s", outsider)
	}
	if !strings.Contains(outsider, "grafana.talos00") {
		t.Errorf("a non-member lost the unrestricted group:\n%s", outsider)
	}
	if !strings.Contains(member, "plex.talos00") || !strings.Contains(member, "grafana.talos00") {
		t.Errorf("a member did not receive both groups:\n%s", member)
	}
	// With exactly one restricted group and the caller inside it, the member's view and the
	// published document must be the same bytes. This is the property that makes "the
	// endpoint changes nothing for an authorised user" literal rather than approximate.
	if member != published {
		t.Errorf("a member's view differs from the published manifest\n member    %s\n "+
			"published %s", member, published)
	}
}
