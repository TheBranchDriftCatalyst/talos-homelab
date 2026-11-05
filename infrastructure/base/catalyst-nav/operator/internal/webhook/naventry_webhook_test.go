package webhook

// Unit-level proof that the validator refuses a dangling navGroupRef.
//
// These drive Handle() directly with a fake client. The ENVTEST suite
// (internal/controller/envtest_test.go) proves the same thing end-to-end through a real
// apiserver with the real phase-1 CRDs installed and the real webhook wired up — this file is
// the fast, always-runnable version, and it exists because the envtest suite needs downloaded
// control-plane binaries and will skip without them. A gap this important should not be
// coverable only by the suite that can skip.

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	admissionv1 "k8s.io/api/admission/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
	"sigs.k8s.io/controller-runtime/pkg/webhook/admission"

	navv1alpha1 "github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/api/v1alpha1"
)

func scheme(t *testing.T) *runtime.Scheme {
	t.Helper()
	s := runtime.NewScheme()
	if err := navv1alpha1.AddToScheme(s); err != nil {
		t.Fatal(err)
	}
	return s
}

func navGroup(name, title string) *navv1alpha1.NavGroup {
	return &navv1alpha1.NavGroup{
		ObjectMeta: metav1.ObjectMeta{Name: name},
		Spec:       navv1alpha1.NavGroupSpec{Title: title, Order: 60},
	}
}

func entryReq(t *testing.T, op admissionv1.Operation, ref string) admission.Request {
	t.Helper()
	e := navv1alpha1.NavEntry{
		ObjectMeta: metav1.ObjectMeta{Name: "bookmark", Namespace: "library"},
		Spec: navv1alpha1.NavEntrySpec{
			Title:       "Some Bookmark",
			Href:        "https://example.invalid/",
			NavGroupRef: ref,
		},
	}
	raw, err := json.Marshal(&e)
	if err != nil {
		t.Fatal(err)
	}
	return admission.Request{AdmissionRequest: admissionv1.AdmissionRequest{
		Operation: op,
		Object:    runtime.RawExtension{Raw: raw},
	}}
}

func validatorWith(t *testing.T, objs ...runtime.Object) *NavEntryValidator {
	t.Helper()
	c := fake.NewClientBuilder().WithScheme(scheme(t)).WithRuntimeObjects(objs...).Build()
	return &NavEntryValidator{Client: c, APIReader: c}
}

// TestDanglingNavGroupRefIsRejected is THE test this whole component exists for.
func TestDanglingNavGroupRefIsRejected(t *testing.T) {
	v := validatorWith(t, navGroup("observability", "Observability"))

	resp := v.Handle(context.Background(), entryReq(t, admissionv1.Create, "obsevrability"))
	if resp.Allowed {
		t.Fatal("a typo'd navGroupRef was ADMITTED -- this is the exact silent failure " +
			"the CRD was supposed to close, and the webhook is the only thing that can")
	}
	msg := resp.Result.Message
	// The denial must name the offending value, or the operator has to guess which of
	// several fields is wrong.
	if !strings.Contains(msg, "obsevrability") {
		t.Errorf("denial does not quote the bad ref: %q", msg)
	}
	// ...and must list what IS available, so the fix is one line rather than a lookup.
	if !strings.Contains(msg, "observability") {
		t.Errorf("denial does not name the existing NavGroups: %q", msg)
	}
}

func TestExistingNavGroupRefIsAdmitted(t *testing.T) {
	v := validatorWith(t, navGroup("observability", "Observability"))
	resp := v.Handle(context.Background(), entryReq(t, admissionv1.Create, "observability"))
	if !resp.Allowed {
		t.Fatalf("a valid ref was rejected: %s", resp.Result.Message)
	}
}

// TestRefIsMatchedOnNameNotTitle pins which string navGroupRef takes.
//
// The CRD says metadata.name. The RESOLVER accepts either name or title, because the derived
// annotations carry titles — but admission must be strict, or "Observability" and
// "observability" both become valid spellings of one ref and the field has two meanings.
func TestRefIsMatchedOnNameNotTitle(t *testing.T) {
	v := validatorWith(t, navGroup("observability", "Observability"))
	resp := v.Handle(context.Background(), entryReq(t, admissionv1.Create, "Observability"))
	if resp.Allowed {
		t.Fatal("spec.title was accepted as a navGroupRef; the field is metadata.name")
	}
	if !strings.Contains(resp.Result.Message, "metadata.name") {
		t.Errorf("denial does not explain which string to use: %q", resp.Result.Message)
	}
}

func TestUpdateIsValidatedToo(t *testing.T) {
	// An entry can be edited into a dangling state just as easily as created in one.
	v := validatorWith(t, navGroup("observability", "Observability"))
	resp := v.Handle(context.Background(), entryReq(t, admissionv1.Update, "gone"))
	if resp.Allowed {
		t.Fatal("UPDATE to a dangling ref was admitted")
	}
}

func TestDeleteIsAlwaysAllowed(t *testing.T) {
	// A DELETE request carries no object, and removing an entry is always safe. If this
	// denied, a NavEntry whose group had been deleted could never be cleaned up.
	v := validatorWith(t)
	req := admission.Request{AdmissionRequest: admissionv1.AdmissionRequest{
		Operation: admissionv1.Delete,
	}}
	if resp := v.Handle(context.Background(), req); !resp.Allowed {
		t.Fatalf("DELETE was denied: %s", resp.Result.Message)
	}
}

func TestEmptyRefIsRejected(t *testing.T) {
	// The CRD's minLength: 1 normally catches this first; the handler must not depend on
	// the CRD being installed with the schema it was reviewed with.
	v := validatorWith(t, navGroup("observability", "Observability"))
	resp := v.Handle(context.Background(), entryReq(t, admissionv1.Create, ""))
	if resp.Allowed {
		t.Fatal("an empty navGroupRef was admitted")
	}
}

func TestGarbageObjectIsABadRequestNotADenial(t *testing.T) {
	// Distinguishing 400 from a denial matters: a denial says "your value is wrong", a 400
	// says "I could not read your object at all", and conflating them sends the operator
	// looking at the wrong field.
	v := validatorWith(t)
	req := admission.Request{AdmissionRequest: admissionv1.AdmissionRequest{
		Operation: admissionv1.Create,
		Object:    runtime.RawExtension{Raw: []byte(`{"spec":`)},
	}}
	resp := v.Handle(context.Background(), req)
	if resp.Allowed {
		t.Fatal("undecodable object was admitted")
	}
	if resp.Result.Code != 400 {
		t.Errorf("code = %d, want 400 for an undecodable object", resp.Result.Code)
	}
}

func TestMissingObjectIsABadRequest(t *testing.T) {
	v := validatorWith(t)
	req := admission.Request{AdmissionRequest: admissionv1.AdmissionRequest{
		Operation: admissionv1.Create,
	}}
	resp := v.Handle(context.Background(), req)
	if resp.Allowed {
		t.Fatal("an empty object was admitted")
	}
	if resp.Result.Code != 400 {
		t.Errorf("code = %d, want 400", resp.Result.Code)
	}
}

// TestCacheMissIsConfirmedAgainstTheAPIReader guards the same-apply race.
//
// A NavGroup and a NavEntry committed in one kustomize directory arrive together. If the
// informer has not yet seen the group, a cache-only check rejects valid YAML — intermittently,
// which is the worst way for it to fail. The validator must confirm a miss against the
// apiserver before denying.
func TestCacheMissIsConfirmedAgainstTheAPIReader(t *testing.T) {
	cacheOnly := fake.NewClientBuilder().WithScheme(scheme(t)).Build()
	live := fake.NewClientBuilder().WithScheme(scheme(t)).
		WithRuntimeObjects(navGroup("observability", "Observability")).Build()

	v := &NavEntryValidator{Client: cacheOnly, APIReader: live}
	resp := v.Handle(context.Background(), entryReq(t, admissionv1.Create, "observability"))
	if !resp.Allowed {
		t.Fatalf("a group present in the apiserver but not yet in the cache was rejected: %s\n"+
			"This breaks `kubectl apply -k` on a directory creating both objects.",
			resp.Result.Message)
	}

	// And the fallback must not rubber-stamp: a ref absent from BOTH is still denied.
	resp = v.Handle(context.Background(), entryReq(t, admissionv1.Create, "nope"))
	if resp.Allowed {
		t.Fatal("the APIReader fallback admitted a ref that exists nowhere")
	}
}
