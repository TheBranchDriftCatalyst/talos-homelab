package xrdschema_test

// Admission specs for the CatalystWebSecureIngress XRD's phase-5 `nav` block, run against a
// REAL apiserver.
//
// WHY THESE EXIST, AND WHY THEY ARE NOT UNIT TESTS. Every constraint phase 5 adds is enforced
// by the API server and by nothing else: an OpenAPI enum, four numeric bounds, a regex, and
// six CEL rules. There is no Go code to unit-test, and a YAML-reading test could only assert
// that the rule TEXT is present — which is exactly the failure this repo has already recorded
// once, in catalyst-cnpg-appdb/xrd.yaml, whose comment claimed the schema "REFUSES 1" with no
// such rule behind it. A schema comment is not evidence. A rejection is.
//
// Two things here can only be learned from a real apiserver:
//
//  1. Whether the CEL rules are ADMISSIBLE at all. The apiserver refuses a CRD whose CEL cost
//     ESTIMATE exceeds its budget, and the estimate is computed from maxItems/maxLength — so
//     rule 5 and rule 6, which walk spec.middlewares, are only installable because that array
//     and its strings are bounded. Nothing short of installing the CRD proves it.
//  2. Whether the rules actually reject what they claim to. CEL has no compiler to lean on
//     here; a rule that reads correctly and evaluates to `true` always is indistinguishable
//     from a working one until something that should fail is sent.
//
// WHY IT LIVES IN THE NAV OPERATOR'S MODULE. This is the only Go module in the repo, and it
// already carries the envtest wiring (internal/controller/envtest_test.go) and the rest of the
// catalyst-nav migration. The XRD it reads is in a sibling component directory, read from disk
// as the real file, never a copy.
//
// Skips cleanly when the envtest control-plane binaries are absent — same contract as
// internal/controller:
//
//	KUBEBUILDER_ASSETS=$(go run sigs.k8s.io/controller-runtime/tools/setup-envtest use -p path) \
//	  GOWORK=off go test ./internal/xrdschema/

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	corev1 "k8s.io/api/core/v1"
	apiextv1 "k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/envtest"
	"sigs.k8s.io/yaml"
)

const (
	testNamespace = "xrd-schema-test"
	apiVersion    = "net.catalyst.io/v1alpha1"
	kind          = "CatalystWebSecureIngress"
)

// ---- locating and converting the real XRD -----------------------------------------------

// baseDir is infrastructure/base — four levels up from internal/xrdschema.
func baseDir(t *testing.T) string {
	t.Helper()
	wd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	p, err := filepath.Abs(filepath.Join(wd, "..", "..", "..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(p, "catalyst-websecure-ingress", "xrd.yaml")); err != nil {
		t.Fatalf("catalyst-websecure-ingress/xrd.yaml not found under %s: %v", p, err)
	}
	return p
}

// xrd is the slice of a CompositeResourceDefinition this test needs. Deliberately not the
// Crossplane Go type: vendoring crossplane-runtime for four fields would drag a large module
// tree in, and the fields read here (group, names, versions[].schema) have been stable across
// every Crossplane release this cluster has run.
type xrd struct {
	Spec struct {
		Group string `json:"group"`
		Names struct {
			Kind     string `json:"kind"`
			Plural   string `json:"plural"`
			Singular string `json:"singular"`
		} `json:"names"`
		Versions []struct {
			Name   string `json:"name"`
			Served bool   `json:"served"`
			Schema struct {
				OpenAPIV3Schema apiextv1.JSONSchemaProps `json:"openAPIV3Schema"`
			} `json:"schema"`
		} `json:"versions"`
	} `json:"spec"`
}

// crdFromXRD builds the CustomResourceDefinition the XRD's v1alpha1 version describes.
//
// This reproduces the part of Crossplane's XRD->CRD generation the schema depends on: the
// composite's `spec`/`status` schema is copied VERBATIM into the CRD, and Crossplane adds its
// own machinery fields (spec.crossplane, status.conditions) alongside. Only the verbatim half
// matters for these specs, and the copy is literal — the JSONSchemaProps decoded from the file
// is the same value handed to the apiserver, so there is no second interpretation of the schema
// to get wrong. That Crossplane itself preserves x-kubernetes-validations through this
// conversion was confirmed out of band with `crossplane xrd convert` on Crossplane v2.3.4, the
// version this cluster runs.
func crdFromXRD(t *testing.T) *apiextv1.CustomResourceDefinition {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(baseDir(t), "catalyst-websecure-ingress", "xrd.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	var x xrd
	if err := yaml.Unmarshal(raw, &x); err != nil {
		t.Fatalf("decoding xrd.yaml: %v", err)
	}
	if len(x.Spec.Versions) != 1 {
		t.Fatalf("expected exactly one XRD version, got %d — this test hardcodes versions[0] "+
			"as storage, which stops being right the moment a second version is served",
			len(x.Spec.Versions))
	}
	v := x.Spec.Versions[0]
	singular := x.Spec.Names.Singular
	if singular == "" {
		singular = strings.ToLower(x.Spec.Names.Kind)
	}
	return &apiextv1.CustomResourceDefinition{
		ObjectMeta: metav1.ObjectMeta{Name: x.Spec.Names.Plural + "." + x.Spec.Group},
		Spec: apiextv1.CustomResourceDefinitionSpec{
			Group: x.Spec.Group,
			Scope: apiextv1.NamespaceScoped,
			Names: apiextv1.CustomResourceDefinitionNames{
				Kind:     x.Spec.Names.Kind,
				ListKind: x.Spec.Names.Kind + "List",
				Plural:   x.Spec.Names.Plural,
				Singular: singular,
			},
			Versions: []apiextv1.CustomResourceDefinitionVersion{{
				Name:    v.Name,
				Served:  v.Served,
				Storage: true,
				Schema:  &apiextv1.CustomResourceValidation{OpenAPIV3Schema: v.Schema.OpenAPIV3Schema.DeepCopy()},
			}},
		},
	}
}

// ---- control plane ----------------------------------------------------------------------

func ensureAssets(t *testing.T) string {
	t.Helper()
	if p := os.Getenv("KUBEBUILDER_ASSETS"); p != "" {
		return p
	}
	cmd := exec.Command("go", "run", "sigs.k8s.io/controller-runtime/tools/setup-envtest", "use", "-p", "path")
	cmd.Env = append(os.Environ(), "GOWORK=off")
	out, err := cmd.Output()
	if err != nil {
		t.Skipf("envtest assets unavailable (%v); run setup-envtest and set KUBEBUILDER_ASSETS", err)
	}
	return strings.TrimSpace(string(out))
}

// startEnv installs the CRD generated from the real XRD. A failure HERE is the
// cost-estimate/structural-schema verdict, which is why it is a Fatal and not a Skip.
func startEnv(t *testing.T) (client.Client, func()) {
	t.Helper()
	assets := ensureAssets(t)

	scheme := runtime.NewScheme()
	if err := clientgoscheme.AddToScheme(scheme); err != nil {
		t.Fatal(err)
	}

	env := &envtest.Environment{
		BinaryAssetsDirectory: assets,
		CRDs:                  []*apiextv1.CustomResourceDefinition{crdFromXRD(t)},
	}
	cfg, err := env.Start()
	if err != nil {
		// Distinguishable on purpose: "could not start" is an environment problem,
		// but the CRD install happens inside Start(), so a rejected schema (bad
		// structural schema, CEL over budget) lands here too and must not be skipped.
		if strings.Contains(err.Error(), "catalystwebsecureingresses") ||
			strings.Contains(err.Error(), "x-kubernetes-validations") ||
			strings.Contains(err.Error(), "estimated cost") {
			t.Fatalf("the XRD's schema was REFUSED by the apiserver: %v", err)
		}
		t.Skipf("could not start envtest control plane: %v", err)
	}
	stop := func() { _ = env.Stop() }

	k8s, err := client.New(cfg, client.Options{Scheme: scheme})
	if err != nil {
		stop()
		t.Fatal(err)
	}
	ns := &corev1.Namespace{ObjectMeta: metav1.ObjectMeta{Name: testNamespace}}
	if err := k8s.Create(context.Background(), ns); err != nil {
		stop()
		t.Fatal(err)
	}
	return k8s, stop
}

// ---- helpers ----------------------------------------------------------------------------

// navMiddlewares is the chain kubeview and system-graph both carry: injected (so the nav
// advertises the app at all) but nav-only (so themed is false).
func navMiddlewares() []any {
	return []any{
		map[string]any{"name": "authentik", "namespace": "authentik"},
		map[string]any{"name": "catalyst-nav", "namespace": "traefik"},
	}
}

func fullThemeMiddlewares() []any {
	return []any{
		map[string]any{"name": "authentik", "namespace": "authentik"},
		map[string]any{"name": "catalyst-plex", "namespace": "traefik"},
	}
}

// baseSpec is a minimal admissible claim: host, backend, an injected chain and a homepage
// block. Each case mutates its own copy.
func baseSpec() map[string]any {
	return map[string]any{
		"host": "probe.talos00",
		"backend": map[string]any{
			"service":  "probe",
			"port":     int64(80),
			"selector": map[string]any{"app": "probe"},
		},
		"middlewares": navMiddlewares(),
		"homepage": map[string]any{
			"name": "Probe",
			"icon": "probe.png",
		},
	}
}

// objectName turns a case name into a legal RFC 1123 subdomain.
func objectName(s string) string {
	var b strings.Builder
	b.WriteString("probe-")
	for _, r := range strings.ToLower(s) {
		switch {
		case r >= 'a' && r <= 'z', r >= '0' && r <= '9':
			b.WriteRune(r)
		default:
			b.WriteRune('-')
		}
	}
	return strings.Trim(b.String(), "-")
}

func create(t *testing.T, k8s client.Client, name string, spec map[string]any) error {
	t.Helper()
	u := &unstructured.Unstructured{Object: map[string]any{
		"apiVersion": apiVersion,
		"kind":       kind,
		"metadata":   map[string]any{"name": name, "namespace": testNamespace},
		"spec":       spec,
	}}
	err := k8s.Create(context.Background(), u)
	if err == nil {
		t.Cleanup(func() { _ = k8s.Delete(context.Background(), u) })
	}
	return err
}

// ---- the specs --------------------------------------------------------------------------

// TestNavBlockAdmission is the rejection evidence for every constraint spec.nav claims to
// enforce. Each `wantErr` is a substring of the message an operator actually sees.
func TestNavBlockAdmission(t *testing.T) {
	k8s, stop := startEnv(t)
	defer stop()

	withNav := func(nav map[string]any, mutate ...func(map[string]any)) map[string]any {
		s := baseSpec()
		s["nav"] = nav
		for _, m := range mutate {
			m(s)
		}
		return s
	}

	cases := []struct {
		name    string
		spec    map[string]any
		wantErr string // "" means it must be ACCEPTED
	}{
		// ---- the enum: a free-text group is no longer expressible -------------------
		{
			name: "group accepts a taxonomy NavGroup name",
			spec: withNav(map[string]any{"themed": false, "group": "infrastructure", "order": int64(30)}),
		},
		{
			// THE live typo-fork value. "Monitoring" is one of the two names the cluster
			// carries for one concept today; this is the admission that would have
			// prevented it.
			name:    "group rejects the free-text title Monitoring",
			spec:    withNav(map[string]any{"themed": false, "group": "Monitoring"}),
			wantErr: "Unsupported value",
		},
		{
			name:    "group rejects a lowercased non-taxonomy name",
			spec:    withNav(map[string]any{"themed": false, "group": "monitoring"}),
			wantErr: "Unsupported value",
		},
		{
			name:    "group rejects the display title of a real group",
			spec:    withNav(map[string]any{"themed": false, "group": "Observability"}),
			wantErr: "Unsupported value",
		},
		{
			// The silent-duplicate case NavGroup's own schema calls out: a trailing
			// space is invisible in review and forks the taxonomy.
			name:    "group rejects a trailing space on a real name",
			spec:    withNav(map[string]any{"themed": false, "group": "observability "}),
			wantErr: "Unsupported value",
		},

		// ---- order: the taxonomy's documented scale, enforced -----------------------
		{
			name: "order accepts a multiple of 10",
			spec: withNav(map[string]any{"themed": false, "group": "media", "order": int64(40)}),
		},
		{
			// system-graph's live gethomepage.dev/weight is 35. The runbook has to say
			// so because the scale refuses it rather than silently rounding.
			name:    "order rejects 35, the live system-graph weight",
			spec:    withNav(map[string]any{"themed": false, "group": "media", "order": int64(35)}),
			wantErr: "multiple of 10",
		},
		{
			name:    "order rejects below the scale",
			spec:    withNav(map[string]any{"themed": false, "group": "media", "order": int64(5)}),
			wantErr: "greater than or equal to 10",
		},
		{
			name:    "order rejects above the scale",
			spec:    withNav(map[string]any{"themed": false, "group": "media", "order": int64(1000)}),
			wantErr: "less than or equal to 990",
		},

		// ---- themed: the substring convention, now a checked contract ---------------
		{
			name: "themed true is accepted with a full-theme middleware",
			spec: withNav(
				map[string]any{"themed": true, "group": "media", "order": int64(10)},
				func(s map[string]any) { s["middlewares"] = fullThemeMiddlewares() },
			),
		},
		{
			// The claim says the destination is fully themed; the chain says nav-only.
			// Under phase 6 the declaration wins, so this would promise a restyled page
			// and deliver the app's own look. Refused instead.
			name:    "themed true is rejected when only catalyst-nav is present",
			spec:    withNav(map[string]any{"themed": true, "group": "media", "order": int64(10)}),
			wantErr: "disagrees with spec.middlewares",
		},
		{
			name: "themed false is rejected when a full theme IS present",
			spec: withNav(
				map[string]any{"themed": false, "group": "media", "order": int64(10)},
				func(s map[string]any) { s["middlewares"] = fullThemeMiddlewares() },
			),
			wantErr: "disagrees with spec.middlewares",
		},
		{
			// The shared trio rides along in every chain; counting it would make every
			// app "themed". build_nav.py subtracts it, and so must this rule.
			name: "the shared compress middleware does not count as a theme",
			spec: withNav(
				map[string]any{"themed": false, "group": "media", "order": int64(10)},
				func(s map[string]any) {
					s["middlewares"] = []any{
						map[string]any{"name": "catalyst-compress", "namespace": "traefik"},
						map[string]any{"name": "catalyst-nav", "namespace": "traefik"},
					}
				},
			),
		},
		{
			name:    "themed is required inside the nav block",
			spec:    withNav(map[string]any{"group": "media", "order": int64(10)}),
			wantErr: "themed",
		},

		// ---- injection: a declared entry that could never render --------------------
		{
			name: "nav is rejected with no catalyst middleware at all",
			spec: withNav(
				map[string]any{"themed": false, "group": "media", "order": int64(10)},
				func(s map[string]any) {
					s["middlewares"] = []any{map[string]any{"name": "authentik", "namespace": "authentik"}}
				},
			),
			wantErr: "requires at least one catalyst* middleware",
		},
		{
			name: "nav is rejected when the only catalyst middleware is a shared one",
			spec: withNav(
				map[string]any{"themed": false, "group": "media", "order": int64(10)},
				func(s map[string]any) {
					s["middlewares"] = []any{
						map[string]any{"name": "catalyst-asset-cache", "namespace": "traefik"},
					}
				},
			),
			wantErr: "requires at least one catalyst* middleware",
		},

		// ---- the two paths do not overlap -------------------------------------------
		{
			name: "nav is rejected without a homepage block",
			spec: withNav(
				map[string]any{"themed": false, "group": "media", "order": int64(10)},
				func(s map[string]any) { delete(s, "homepage") },
			),
			wantErr: "requires spec.homepage",
		},
		{
			name: "nav.group and homepage.group are mutually exclusive",
			spec: withNav(
				map[string]any{"themed": false, "group": "media", "order": int64(10)},
				func(s map[string]any) {
					s["homepage"] = map[string]any{"name": "Probe", "group": "Media"}
				},
			),
			wantErr: "mutually exclusive",
		},
		{
			name: "nav.order and homepage.weight are mutually exclusive",
			spec: withNav(
				map[string]any{"themed": false, "group": "media", "order": int64(10)},
				func(s map[string]any) {
					s["homepage"] = map[string]any{"name": "Probe", "weight": int64(30)}
				},
			),
			wantErr: "mutually exclusive",
		},

		// ---- visibility: the comma-joined encoding is kept lossless -----------------
		{
			name: "visibility accepts a list of group names",
			spec: withNav(map[string]any{
				"themed":     false,
				"group":      "infrastructure",
				"order":      int64(30),
				"visibility": map[string]any{"authentikGroups": []any{"talos-admin", "cluster-admin"}},
			}),
		},
		{
			// The composition joins this list with commas into ONE annotation value, so
			// a comma inside a name would silently become two groups.
			name: "visibility rejects a name containing a comma",
			spec: withNav(map[string]any{
				"themed":     false,
				"group":      "infrastructure",
				"order":      int64(30),
				"visibility": map[string]any{"authentikGroups": []any{"talos-admin,cluster-admin"}},
			}),
			wantErr: "should match",
		},
		{
			name: "visibility rejects an empty list",
			spec: withNav(map[string]any{
				"themed":     false,
				"group":      "infrastructure",
				"order":      int64(30),
				"visibility": map[string]any{"authentikGroups": []any{}},
			}),
			wantErr: "should have at least 1 items",
		},
		{
			name: "visibility rejects a block with no authentikGroups",
			spec: withNav(map[string]any{
				"themed":     false,
				"group":      "infrastructure",
				"order":      int64(30),
				"visibility": map[string]any{},
			}),
			wantErr: "authentikGroups",
		},
		{
			name: "visibility rejects a duplicate group name",
			spec: withNav(map[string]any{
				"themed":     false,
				"group":      "infrastructure",
				"order":      int64(30),
				"visibility": map[string]any{"authentikGroups": []any{"talos-admin", "talos-admin"}},
			}),
			wantErr: "Duplicate value",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			// objectName, not the raw case name: a name the apiserver rejects as a
			// bad RFC 1123 subdomain produces an error that CONTAINS the schema
			// complaints as well, so a case could pass on an error it never meant
			// to provoke.
			err := create(t, k8s, objectName(tc.name), tc.spec)
			switch {
			case tc.wantErr == "" && err != nil:
				t.Fatalf("expected the claim to be ADMITTED, got: %v", err)
			case tc.wantErr != "" && err == nil:
				t.Fatalf("expected a rejection containing %q, but the claim was ADMITTED — "+
					"the constraint this case documents is not actually enforced", tc.wantErr)
			case tc.wantErr != "" && !strings.Contains(err.Error(), tc.wantErr):
				t.Fatalf("rejected, but for the wrong reason.\n  want substring: %s\n  got: %v", tc.wantErr, err)
			}
		})
	}
}

// TestPrePhase5ClaimsStillAdmit is the backward-compatibility spec, and it uses the REAL
// manifest rather than a reconstruction.
//
// WHAT WOULD BREAK WITHOUT IT. Phase 5 adds six CEL rules to the same `spec` the two live
// claims are validated against, plus maxItems/maxLength on spec.middlewares. Any one of them
// written without the `!has(self.nav) ||` guard would reject every claim in the cluster on the
// next reconcile — and because Crossplane validates the composite, the symptom would not be a
// failed git push but a live claim stuck with the old spec and a new one that cannot be
// written. There is no gradual version of that failure.
func TestPrePhase5ClaimsStillAdmit(t *testing.T) {
	k8s, stop := startEnv(t)
	defer stop()

	// The kubeview claim, exactly as Flux applies it. The namespace is overridden because
	// envtest has no infra-control.
	raw, err := os.ReadFile(filepath.Join(baseDir(t), "infra-control", "kubeview", "websecure-ingress.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	var claim map[string]any
	if err := yaml.Unmarshal(raw, &claim); err != nil {
		t.Fatal(err)
	}
	u := &unstructured.Unstructured{Object: claim}
	u.SetNamespace(testNamespace)
	if got := u.GetKind(); got != kind {
		t.Fatalf("expected the fixture to be a %s, got %s — this test is reading the wrong file", kind, got)
	}

	// Sanity: the fixture must still be a PRE-phase-5 claim, or it proves nothing about
	// backward compatibility. If kubeview is migrated, this assertion is the reminder to
	// repoint this test at a claim that has not been.
	spec, _, _ := unstructured.NestedMap(u.Object, "spec")
	if _, migrated := spec["nav"]; migrated {
		t.Fatalf("the kubeview claim now carries spec.nav, so it no longer exercises the " +
			"pre-phase-5 path; point this spec at an un-migrated claim")
	}
	if _, ok := spec["homepage"].(map[string]any)["group"]; !ok {
		t.Fatalf("the kubeview claim no longer sets spec.homepage.group, which is the field " +
			"the mutual-exclusion rules could wrongly reject; this spec has stopped testing it")
	}

	if err := k8s.Create(context.Background(), u); err != nil {
		t.Fatalf("the live, un-migrated kubeview claim was REJECTED by the phase-5 schema: %v", err)
	}
	t.Cleanup(func() { _ = k8s.Delete(context.Background(), u) })
}
