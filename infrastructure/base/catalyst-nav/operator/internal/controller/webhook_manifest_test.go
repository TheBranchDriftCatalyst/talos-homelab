package controller_test

// Keeps the envtest webhook configuration honest against the one the cluster would get.
//
// envtest_test.go installs a ValidatingWebhookConfiguration built in Go. If that drifts from
// operator/webhook.yaml — a different path, a different resource name, Fail relaxed to Ignore —
// the suite would prove the webhook works in a configuration the cluster does not use. That is
// the same shape as the applet-loader bug tests/nav/test_build_nav.py was written for: both
// halves individually correct, the seam between them untested.
//
// Needs no control plane, so unlike the rest of this package it cannot skip.

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	admissionregv1 "k8s.io/api/admissionregistration/v1"
	"sigs.k8s.io/yaml"
)

func TestWebhookConfigMatchesTheShippedManifest(t *testing.T) {
	path := filepath.Join(componentDir(t), "operator", "webhook.yaml")
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("reading %s: %v", path, err)
	}

	var shipped *admissionregv1.ValidatingWebhookConfiguration
	for _, doc := range strings.Split(string(raw), "\n---") {
		if !strings.Contains(doc, "kind: ValidatingWebhookConfiguration") {
			continue
		}
		var cfg admissionregv1.ValidatingWebhookConfiguration
		if err := yaml.Unmarshal([]byte(doc), &cfg); err != nil {
			t.Fatalf("decoding the shipped webhook config: %v", err)
		}
		shipped = &cfg
	}
	if shipped == nil {
		t.Fatal("webhook.yaml contains no ValidatingWebhookConfiguration")
	}
	if len(shipped.Webhooks) != 1 {
		t.Fatalf("shipped config declares %d webhooks, want 1", len(shipped.Webhooks))
	}
	got, want := shipped.Webhooks[0], navEntryWebhookConfig().Webhooks[0]

	// Deliberately NOT a full structural comparison: these are the five fields that decide
	// whether the apiserver calls this handler at all. Comparing whole objects would mean
	// reproducing every default the apiserver fills in, and would fail on cosmetic edits.
	if got.Name != want.Name {
		t.Errorf("webhook name: shipped %q, tested %q", got.Name, want.Name)
	}
	if got.ClientConfig.Service == nil || want.ClientConfig.Service == nil {
		t.Fatal("both configs must route through a Service")
	}
	gp, wp := derefPath(got.ClientConfig.Service.Path), derefPath(want.ClientConfig.Service.Path)
	if gp != wp {
		t.Errorf("webhook PATH differs: shipped %q, tested %q.\n"+
			"A path mismatch means the apiserver calls an unregistered route, so the "+
			"handler is never reached — which no handler-level test can detect.", gp, wp)
	}
	if !reflect.DeepEqual(got.Rules, want.Rules) {
		t.Errorf("RULES differ:\n  shipped %+v\n  tested  %+v\n"+
			"A rule that does not select naventries means the webhook is never invoked.",
			got.Rules, want.Rules)
	}
	if got.FailurePolicy == nil || *got.FailurePolicy != admissionregv1.Fail {
		t.Errorf("shipped failurePolicy = %v, want Fail. Ignore would admit a dangling "+
			"navGroupRef whenever the operator is rolling or unreachable.", got.FailurePolicy)
	}
	if got.SideEffects == nil || *got.SideEffects != admissionregv1.SideEffectClassNone {
		t.Errorf("shipped sideEffects = %v, want None", got.SideEffects)
	}
}

func derefPath(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}
