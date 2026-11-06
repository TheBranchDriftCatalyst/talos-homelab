package controller

// The reconciler.
//
// ONE RECONCILER FOR THE WHOLE NAV, not one per kind. The nav manifest is a cluster singleton:
// every IngressRoute, NavGroup and NavEntry contributes to one document, and the position of
// any entry depends on every other entry (groups sort by whether ANY member is themed; items
// sort against their siblings). A per-object reconciler would therefore have to rebuild the
// whole model on each call anyway, and would additionally have to decide what a "NavGroup
// reconcile" means for an object whose output is a slice of a shared document. So all four
// watches funnel into one fixed request key and the reconcile is idempotent and total.
//
// That makes this a levelled, not an edge-triggered, controller — which is also what makes it
// correct in the face of the two asynchronous mutators upstream of it (the Crossplane
// composite and Kyverno's annotation derivation). It never asks "what changed?", only "what
// should the manifest be now?".
//
// WHAT IT DOES NOT DO: serve anything itself. It publishes into a ConfigMap and hands
// internal/navserve a Snapshot, which two HTTP handlers read. An earlier revision of this
// comment said the themepark sidecar "keeps writing and serving its own catalyst-nav.json,
// untouched"; THAT SIDECAR IS DELETED and this reconcile is the only thing that derives the
// nav model anywhere in the cluster.
//
// ONE BUILD PER RECONCILE FEEDS ALL THREE CONSUMERS, which is what makes them unable to
// disagree:
//
//	the ConfigMap            catalyst-nav-manifest, for humans and for diffing
//	the public endpoint      serves Snapshot.Bytes verbatim — literally the same []byte
//	                         written to the ConfigMap, not a second Encode of the same model
//	the per-identity endpoint filters this model through the visibility Index, per request,
//	                         because its body differs by caller and cannot be precomputed
//
// See internal/navserve/snapshot.go.

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"sort"
	"strings"
	"time"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/builder"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller"
	"sigs.k8s.io/controller-runtime/pkg/handler"
	"sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/manager"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"

	navv1alpha1 "github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/api/v1alpha1"
	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/navmodel"
	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/navserve"
)

// ManifestKey is the ConfigMap key the published manifest lands under. Named to match the file
// the themepark sidecar serves, so a `diff` between the two needs no translation step.
const ManifestKey = "catalyst-nav.json"

// conditionPublished is the condition type both kinds carry.
const (
	conditionPublished = "Published"
	conditionDegraded  = "Degraded"
)

// singletonRequest is the one key every watch maps to. The name is not a real object; it exists
// so the workqueue coalesces a burst of IngressRoute events into one rebuild.
var singletonRequest = reconcile.Request{
	NamespacedName: types.NamespacedName{Name: "catalyst-nav"},
}

// NavReconciler rebuilds and publishes the nav model.
type NavReconciler struct {
	Client client.Client

	// Namespace and ConfigMapName locate the published manifest.
	Namespace     string
	ConfigMapName string

	// Options are the model knobs (NAV_SCOPE / NAV_DEFAULTS equivalents), held once rather
	// than re-read from the environment per reconcile.
	Options navmodel.Options

	// Snapshots receives the resolved model plus its visibility rules for the per-identity
	// endpoint to read. Nil is allowed and means "do not serve" — which is what the render
	// parity mode and most of the unit tests want, and it keeps the endpoint from being a
	// thing you have to opt OUT of in a test that is about something else.
	Snapshots *navserve.Store
}

// Reconcile rebuilds the whole model and reports the outcome on every contributing object.
func (r *NavReconciler) Reconcile(ctx context.Context, _ reconcile.Request) (reconcile.Result, error) {
	lg := log.FromContext(ctx)

	doc, err := CollectDoc(ctx, r.Client)
	if err != nil {
		// Returning the error requeues with backoff. Publishing an EMPTY manifest here
		// instead would blank the bar on every app the moment the apiserver hiccupped —
		// which is the same reasoning discover.sh spells out for not using `set -e`:
		// "Failures here are logged and retried; the previous manifest keeps being
		// served."
		return reconcile.Result{}, err
	}

	var groups navv1alpha1.NavGroupList
	if err := r.Client.List(ctx, &groups); err != nil {
		return reconcile.Result{}, fmt.Errorf("listing NavGroups: %w", err)
	}
	var entries navv1alpha1.NavEntryList
	if err := r.Client.List(ctx, &entries); err != nil {
		return reconcile.Result{}, fmt.Errorf("listing NavEntries: %w", err)
	}

	model := navmodel.Build(doc, r.Options)
	// Resolve MUST run before the snapshot is published: it is what stamps NavGroupRef onto
	// each manifest group, and the visibility filter keys group rules by that ref. Publish a
	// model that has not been resolved and every group looks unrestricted — a silent,
	// total fail-open on group visibility.
	res := Resolve(model, groups.Items, entries.Items)

	encoded, revision, err := r.publish(ctx, model)
	if err != nil {
		return reconcile.Result{}, err
	}
	if r.Snapshots != nil {
		r.Snapshots.Publish(&navserve.Snapshot{
			Manifest: model,
			Index:    BuildVisibilityIndex(groups.Items, entries.Items),
			Bytes:    encoded,
			Revision: revision,
			BuiltAt:  time.Now(),
		})
	}
	if err := r.writeStatuses(ctx, res, groups.Items, entries.Items); err != nil {
		return reconcile.Result{}, err
	}

	lg.Info("published nav manifest",
		"groups", len(model.Groups),
		"entries", countItems(model),
		"navGroups", len(groups.Items),
		"navEntries", len(entries.Items),
		"rejections", len(model.Rejections),
		"unresolvedGroupNames", len(res.UnresolvedGroupNames))
	return reconcile.Result{}, nil
}

// publish writes the manifest into the ConfigMap, creating it if absent.
//
// Compared before writing: an unconditional Update on every reconcile would bump
// resourceVersion on every unrelated IngressRoute event, and anything watching the ConfigMap
// (phase 3's server, a future Flux healthcheck) would see churn that does not reflect a nav
// change. build_nav.py has the same property for the same reason — see its sorted/byte-stable
// comments.
// It returns BOTH the encoded bytes and the revision (their sha256), so the caller can put the
// exact same bytes on the snapshot the endpoints serve. Returning them rather than
// re-encoding and re-hashing is the point, and it is a stronger guarantee than it looks:
//
//   - the ConfigMap's value and the PUBLIC endpoint's response body are now one []byte, not
//     two calls to one function. "They cannot disagree" stops being a property of
//     navmodel.Encode being deterministic and becomes a property of there only being one
//     copy. That is the whole claim this migration rests on, so it is worth not re-deriving.
//   - it takes an encode off the public endpoint's hot path, which since the build_nav.py
//     sidecar was deleted is every themed pageview in the cluster rather than the handful of
//     opted-in apps the per-identity endpoint sees.
//
// The per-identity endpoint still encodes per request, necessarily: its body is the filtered
// model and differs by caller, so there is nothing to precompute.
func (r *NavReconciler) publish(ctx context.Context, m *navmodel.Manifest) ([]byte, string, error) {
	encoded := navmodel.Encode(m)
	payload := string(encoded)
	sum := sha256.Sum256(encoded)
	revision := hex.EncodeToString(sum[:])

	var cm corev1.ConfigMap
	key := client.ObjectKey{Namespace: r.Namespace, Name: r.ConfigMapName}
	err := r.Client.Get(ctx, key, &cm)
	switch {
	case apierrors.IsNotFound(err):
		cm = corev1.ConfigMap{
			ObjectMeta: metav1.ObjectMeta{
				Namespace: r.Namespace,
				Name:      r.ConfigMapName,
				Labels: map[string]string{
					"app.kubernetes.io/name":    "catalyst-nav",
					"app.kubernetes.io/part-of": "catalyst",
				},
			},
			Data: map[string]string{ManifestKey: payload},
		}
		cm.Annotations = map[string]string{"nav.catalyst.io/manifest-sha256": revision}
		return encoded, revision, r.Client.Create(ctx, &cm)
	case err != nil:
		return nil, "", fmt.Errorf("reading published ConfigMap: %w", err)
	}

	if cm.Data[ManifestKey] == payload {
		return encoded, revision, nil
	}
	if cm.Data == nil {
		cm.Data = map[string]string{}
	}
	cm.Data[ManifestKey] = payload
	if cm.Annotations == nil {
		cm.Annotations = map[string]string{}
	}
	cm.Annotations["nav.catalyst.io/manifest-sha256"] = revision
	return encoded, revision, r.Client.Update(ctx, &cm)
}

// writeStatuses stamps conditions onto every NavGroup and NavEntry.
func (r *NavReconciler) writeStatuses(
	ctx context.Context,
	res *Resolution,
	groups []navv1alpha1.NavGroup,
	entries []navv1alpha1.NavEntry,
) error {
	for i := range groups {
		g := &groups[i]
		want := res.GroupStatus(g)
		if !statusChangedGroup(g, want) {
			continue
		}
		g.Status = want
		if err := r.Client.Status().Update(ctx, g); err != nil && !apierrors.IsConflict(err) {
			return fmt.Errorf("updating NavGroup/%s status: %w", g.Name, err)
		}
	}
	for i := range entries {
		e := &entries[i]
		want := res.EntryStatus(e)
		if !statusChangedEntry(e, want) {
			continue
		}
		e.Status = want
		if err := r.Client.Status().Update(ctx, e); err != nil && !apierrors.IsConflict(err) {
			return fmt.Errorf("updating NavEntry/%s/%s status: %w", e.Namespace, e.Name, err)
		}
	}
	return nil
}

// SetupWithManager registers the four watches, all funnelling into the singleton key.
//
// WATCHES, NOT A POLL. The thing being replaced is a `while :; do kubectl get ...; sleep 300;
// done` supervision loop, so a 300-second worst-case staleness and a full cluster LIST every
// five minutes forever are the two properties this phase is meant to remove. An informer-backed
// watch reacts in milliseconds and the LIST happens once, at cache start.
func (r *NavReconciler) SetupWithManager(mgr manager.Manager) error {
	toSingleton := handler.EnqueueRequestsFromMapFunc(
		func(context.Context, client.Object) []reconcile.Request {
			return []reconcile.Request{singletonRequest}
		})

	ingressRoutes := &unstructured.UnstructuredList{}
	ingressRoutes.SetGroupVersionKind(IngressRouteGVK)
	claims := &unstructured.UnstructuredList{}
	claims.SetGroupVersionKind(WebSecureIngressGVK)

	return builder.ControllerManagedBy(mgr).
		Named("catalyst-nav").
		// MaxConcurrentReconciles stays at 1: the reconcile writes one ConfigMap and
		// every object's status, so two in flight would race each other's status
		// updates for no throughput gain on a singleton.
		WithOptions(controller.Options{MaxConcurrentReconciles: 1}).
		Watches(&navv1alpha1.NavGroup{}, toSingleton).
		Watches(&navv1alpha1.NavEntry{}, toSingleton).
		Watches(unstructuredFor(IngressRouteGVK), toSingleton).
		Watches(unstructuredFor(WebSecureIngressGVK), toSingleton).
		Complete(r)
}

// unstructuredFor builds the single-object form of a list GVK for a watch.
func unstructuredFor(listGVK schema.GroupVersionKind) *unstructured.Unstructured {
	u := &unstructured.Unstructured{}
	u.SetGroupVersionKind(listGVK.GroupVersion().WithKind(strings.TrimSuffix(listGVK.Kind, "List")))
	return u
}

func countItems(m *navmodel.Manifest) int {
	n := 0
	for _, g := range m.Groups {
		n += len(g.Items)
	}
	return n
}

// statusChangedGroup/statusChangedEntry suppress no-op status writes. Without them every
// IngressRoute event in the cluster would issue one status PATCH per NavGroup and NavEntry,
// which on this cluster's ~200 routes is a steady stream of writes that change nothing and
// make `kubectl get --watch` on either kind useless.
func statusChangedGroup(g *navv1alpha1.NavGroup, want navv1alpha1.NavGroupStatus) bool {
	if g.Status.PublishedEntries != want.PublishedEntries ||
		g.Status.ObservedGeneration != want.ObservedGeneration {
		return true
	}
	return conditionsDiffer(g.Status.Conditions, want.Conditions)
}

func statusChangedEntry(e *navv1alpha1.NavEntry, want navv1alpha1.NavEntryStatus) bool {
	if e.Status.ResolvedGroup != want.ResolvedGroup ||
		e.Status.ObservedGeneration != want.ObservedGeneration {
		return true
	}
	return conditionsDiffer(e.Status.Conditions, want.Conditions)
}

// conditionsDiffer compares on the fields that carry meaning, deliberately ignoring
// LastTransitionTime: it is set to Now() when building the wanted conditions, so comparing it
// would make every status differ from every other and defeat the suppression entirely.
func conditionsDiffer(have, want []metav1.Condition) bool {
	if len(have) != len(want) {
		return true
	}
	index := map[string]metav1.Condition{}
	for _, c := range have {
		index[c.Type] = c
	}
	for _, w := range want {
		h, ok := index[w.Type]
		if !ok || h.Status != w.Status || h.Reason != w.Reason || h.Message != w.Message ||
			h.ObservedGeneration != w.ObservedGeneration {
			return true
		}
	}
	return false
}

// sortedKeys is used by the resolver's messages so a condition's text is stable across
// reconciles — an unstable message would rewrite status forever.
func sortedKeys[V any](m map[string]V) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}
