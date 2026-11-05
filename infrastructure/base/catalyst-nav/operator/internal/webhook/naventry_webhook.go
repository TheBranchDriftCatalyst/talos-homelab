// Package webhook holds the validating admission webhook for NavEntry.
//
// THIS IS THE JUSTIFICATION FOR THE WHOLE CRD EFFORT, so it is not optional and it is not a
// nice-to-have on top of the types.
//
// Phase 1 left spec.navGroupRef as a bare string, and naventry-crd.yaml is explicit that this
// was a deferral, not a solution:
//
//	"NOT validated against actually-existing NavGroup objects — an OpenAPI schema has no way
//	 to look at other objects, and wiring that up would need an admission webhook, which is
//	 out of scope for this phase. A typo here fails the same way a typo'd
//	 gethomepage.dev/group fails today: the entry silently has nowhere to render. Closing that
//	 gap is explicitly deferred, not solved, by this CRD."
//
// Without this webhook the CRDs buy almost nothing over the annotations they replace. The live
// cluster carries both "Monitoring" and "Observability" as separate groups precisely because
// nothing could look at a free-text group name and say "that refers to nothing" — and a typo'd
// navGroupRef fails in exactly the same silent way. `kubectl get navgroups` showing two rows
// instead of two invisible strings is an improvement in VISIBILITY; refusing the write is the
// improvement in CORRECTNESS, and only one of the two actually prevents the next fork.
//
// WHY A WEBHOOK AND NOT CEL. x-kubernetes-validations runs against the object under admission
// and the apiserver's own request context; it cannot read other objects. There is no CEL
// expression, however clever, that can check a cross-object reference. (A future
// ValidatingAdmissionPolicy with a paramRef could, but paramRef binds ONE parameter object, not
// "any NavGroup with this name", so it does not cover this either.)
package webhook

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"

	admissionv1 "k8s.io/api/admission/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/util/validation/field"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/webhook/admission"

	navv1alpha1 "github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/api/v1alpha1"
)

// NavEntryValidator refuses a NavEntry whose navGroupRef names no NavGroup.
type NavEntryValidator struct {
	// Client must be able to GET cluster-scoped NavGroups.
	//
	// Reads go through the manager's CACHE, not a live apiserver call. That is the correct
	// trade here but it has a real failure mode worth naming: a NavGroup created in the same
	// apply as the NavEntry that references it can be rejected if the informer has not seen
	// it yet. The fallback below converts exactly that case into a retryable 503 rather than
	// a flat rejection, because "your YAML is wrong" and "I have not caught up" must not
	// look the same to the person running kubectl apply -k.
	Client client.Client

	// APIReader bypasses the cache. Consulted only to double-check a miss.
	APIReader client.Reader
}

// Handle implements admission.Handler.
func (v *NavEntryValidator) Handle(ctx context.Context, req admission.Request) admission.Response {
	// DELETE carries no object to validate, and a NavEntry is always safe to remove.
	//
	// Deleting the NavGROUP an entry points at is the asymmetric case, and it is handled by
	// the reconciler's NavGroupNotFound condition rather than refused here: blocking a
	// NavGroup delete because some namespace still references it would make the taxonomy
	// un-editable by whoever owns it, for reasons living in someone else's namespace.
	if req.Operation == admissionv1.Delete {
		return admission.Allowed("")
	}

	entry := &navv1alpha1.NavEntry{}
	if len(req.Object.Raw) == 0 {
		return admission.Errored(http.StatusBadRequest,
			fmt.Errorf("admission request carries no object"))
	}
	// encoding/json rather than an injected admission.Decoder: a decoder that was never
	// wired in is nil, and the resulting panic inside the webhook server reaches the
	// apiserver as a connection failure, which failurePolicy: Fail then reports as "all
	// NavEntry writes blocked" with nothing in the logs naming the cause. NavEntry is a
	// plain JSON struct, so there is nothing a scheme-aware decoder would add.
	if err := json.Unmarshal(req.Object.Raw, entry); err != nil {
		return admission.Errored(http.StatusBadRequest,
			fmt.Errorf("decoding NavEntry: %w", err))
	}

	ref := entry.Spec.NavGroupRef
	path := field.NewPath("spec", "navGroupRef")

	// The CRD already enforces minLength: 1, so an empty ref cannot reach here through a
	// normal apply. Checked anyway: this handler must not depend on the CRD being installed
	// with the exact schema it was reviewed with, and an empty ref would otherwise be
	// looked up as the empty name and produce a confusing NotFound.
	if ref == "" {
		return admission.Denied(fmt.Sprintf(
			"%s must name a NavGroup; it is empty", path))
	}

	found, err := v.navGroupExists(ctx, ref)
	if err != nil {
		// Fail CLOSED but RETRYABLE. The ValidatingWebhookConfiguration sets
		// failurePolicy: Fail, so an unavailable webhook already blocks NavEntry
		// writes; returning 503 here makes kubectl retry rather than report a
		// validation failure the user cannot act on.
		return admission.Errored(http.StatusServiceUnavailable,
			fmt.Errorf("cannot verify navGroupRef %q right now: %w", ref, err))
	}
	if !found {
		known, listErr := v.knownGroups(ctx)
		msg := fmt.Sprintf(
			"%s = %q names no NavGroup. A NavEntry whose group does not exist has "+
				"nowhere to render, which is the silent failure this CRD exists to "+
				"replace — so it is refused at admission rather than accepted and "+
				"dropped.", path, ref)
		if listErr == nil && len(known) > 0 {
			msg += fmt.Sprintf(" Existing NavGroups: %v.", known)
		}
		msg += " navGroupRef takes a NavGroup's metadata.name (e.g. \"observability\")," +
			" not its spec.title."
		return admission.Denied(msg)
	}

	return admission.Allowed("")
}

// navGroupExists checks the cache, then confirms a miss against the apiserver.
//
// The double read is the whole point: a cache miss is ambiguous (absent, or not yet synced) and
// a rejection on the strength of an unsynced cache would break `kubectl apply -k` on a
// directory that creates a NavGroup and a NavEntry together — a completely reasonable thing to
// commit, and one that would fail intermittently and unreproducibly.
func (v *NavEntryValidator) navGroupExists(ctx context.Context, name string) (bool, error) {
	var g navv1alpha1.NavGroup
	err := v.Client.Get(ctx, client.ObjectKey{Name: name}, &g)
	if err == nil {
		return true, nil
	}
	if !apierrors.IsNotFound(err) {
		return false, err
	}
	if v.APIReader == nil {
		return false, nil
	}
	err = v.APIReader.Get(ctx, client.ObjectKey{Name: name}, &g)
	if err == nil {
		return true, nil
	}
	if apierrors.IsNotFound(err) {
		return false, nil
	}
	return false, err
}

// knownGroups lists existing NavGroup names so a rejection can show the operator what IS
// available. A denial that only says "wrong" makes the reader go and look it up; naming the
// eight real options turns a typo into a one-line fix.
func (v *NavEntryValidator) knownGroups(ctx context.Context) ([]string, error) {
	var list navv1alpha1.NavGroupList
	if err := v.Client.List(ctx, &list); err != nil {
		return nil, err
	}
	out := make([]string, 0, len(list.Items))
	for i := range list.Items {
		out = append(out, list.Items[i].Name)
	}
	return out, nil
}

var _ admission.Handler = &NavEntryValidator{}
