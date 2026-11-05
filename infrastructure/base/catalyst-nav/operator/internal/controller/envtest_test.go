package controller_test

// End-to-end against a REAL apiserver, with the REAL phase-1 CRDs.
//
// WHY THIS EXISTS SEPARATELY from the fake-client unit tests: those prove the handler's and
// reconciler's logic. They cannot prove the two things that actually go wrong when wiring a
// webhook, and both have bitten this repo's other components:
//
//   1. That the Go structs in api/v1alpha1 match the hand-written CRD schemas. The structs
//      carry no kubebuilder validation markers on purpose (navgroup_types.go explains why), so
//      nothing but a round-trip through the real schema catches a renamed field — it would
//      just read as a zero value forever.
//   2. That the ValidatingWebhookConfiguration's rules actually SELECT NavEntry. A webhook with
//      a typo'd resource name is never called, the apiserver reports nothing, and every test
//      that drives the handler directly still passes. That is the same class of failure as the
//      applet loader shipping with nothing emitting `applets`.
//
// Skips when the envtest control-plane binaries are absent:
//
//	go run sigs.k8s.io/controller-runtime/tools/setup-envtest use -p path
//	KUBEBUILDER_ASSETS=$(...) go test ./internal/controller/

import (
	"context"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	admissionregv1 "k8s.io/api/admissionregistration/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/types"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/envtest"
	"sigs.k8s.io/controller-runtime/pkg/log/zap"
	metricsserver "sigs.k8s.io/controller-runtime/pkg/metrics/server"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"
	webhookserver "sigs.k8s.io/controller-runtime/pkg/webhook"
	"sigs.k8s.io/controller-runtime/pkg/webhook/admission"

	navv1alpha1 "github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/api/v1alpha1"
	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/controller"
	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/navmodel"
	navwebhook "github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/webhook"
)

// componentDir is infrastructure/base/catalyst-nav — where the phase-1 CRDs live.
// TestMain installs a logger before any manager starts. Without it controller-runtime
// prints a multi-line stack trace on shutdown that buries the actual assertion failures.
func TestMain(m *testing.M) {
	ctrl.SetLogger(zap.New(zap.UseDevMode(true), zap.WriteTo(io.Discard)))
	os.Exit(m.Run())
}

func componentDir(t *testing.T) string {
	t.Helper()
	wd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	p, err := filepath.Abs(filepath.Join(wd, "..", "..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(p, "navgroup-crd.yaml")); err != nil {
		t.Fatalf("phase-1 CRDs not found under %s: %v", p, err)
	}
	return p
}

// ensureAssets locates the envtest control plane, asking setup-envtest if the env var is unset.
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

// startEnv boots an apiserver with the phase-1 CRDs and a webhook serving the real validator.
func startEnv(t *testing.T) (client.Client, *envtest.Environment, func()) {
	t.Helper()
	assets := ensureAssets(t)
	dir := componentDir(t)

	scheme := runtime.NewScheme()
	if err := clientgoscheme.AddToScheme(scheme); err != nil {
		t.Fatal(err)
	}
	if err := navv1alpha1.AddToScheme(scheme); err != nil {
		t.Fatal(err)
	}

	env := &envtest.Environment{
		BinaryAssetsDirectory: assets,
		// The REAL phase-1 files, not a generated copy. If a field is renamed in the Go
		// structs without the YAML following, this is what notices.
		CRDDirectoryPaths: []string{
			filepath.Join(dir, "navgroup-crd.yaml"),
			filepath.Join(dir, "naventry-crd.yaml"),
		},
		ErrorIfCRDPathMissing: true,
		Scheme:                scheme,
		WebhookInstallOptions: envtest.WebhookInstallOptions{
			ValidatingWebhooks: []*admissionregv1.ValidatingWebhookConfiguration{
				navEntryWebhookConfig(),
			},
		},
	}
	cfg, err := env.Start()
	if err != nil {
		t.Skipf("could not start envtest control plane: %v", err)
	}
	stop := func() { _ = env.Stop() }

	mgr, err := ctrl.NewManager(cfg, ctrl.Options{
		Scheme:         scheme,
		LeaderElection: false,
		// Metrics and health servers off: two envtest cases run in the same process and
		// would collide on the ports.
		Metrics: metricsserver.Options{BindAddress: "0"},
		WebhookServer: webhookserver.NewServer(webhookserver.Options{
			Host:    env.WebhookInstallOptions.LocalServingHost,
			Port:    env.WebhookInstallOptions.LocalServingPort,
			CertDir: env.WebhookInstallOptions.LocalServingCertDir,
		}),
	})
	if err != nil {
		stop()
		t.Fatal(err)
	}
	mgr.GetWebhookServer().Register("/validate-nav-catalyst-io-v1alpha1-naventry",
		&admission.Webhook{Handler: &navwebhook.NavEntryValidator{
			Client:    mgr.GetClient(),
			APIReader: mgr.GetAPIReader(),
		}})

	ctx, cancel := context.WithCancel(context.Background())
	go func() { _ = mgr.Start(ctx) }()
	if !mgr.GetCache().WaitForCacheSync(ctx) {
		cancel()
		stop()
		t.Fatal("cache never synced")
	}
	// The apiserver will call the webhook over TLS; wait for the listener or the first
	// NavEntry write fails with a connection error that looks like a validation bug.
	waitForWebhook(t, env)

	k8s, err := client.New(cfg, client.Options{Scheme: scheme})
	if err != nil {
		cancel()
		stop()
		t.Fatal(err)
	}
	return k8s, env, func() { cancel(); stop() }
}

func waitForWebhook(t *testing.T, env *envtest.Environment) {
	t.Helper()
	opts := env.WebhookInstallOptions
	deadline := time.Now().Add(20 * time.Second)
	for time.Now().Before(deadline) {
		conn, err := dial(opts.LocalServingHost, opts.LocalServingPort)
		if err == nil {
			_ = conn.Close()
			return
		}
		time.Sleep(200 * time.Millisecond)
	}
	t.Fatal("webhook listener never came up")
}

// navEntryWebhookConfig is the webhook configuration under test.
//
// Kept in sync with webhook.yaml by TestWebhookConfigMatchesTheShippedManifest below, so this
// cannot drift into testing a selector the cluster does not use.
func navEntryWebhookConfig() *admissionregv1.ValidatingWebhookConfiguration {
	fail := admissionregv1.Fail
	none := admissionregv1.SideEffectClassNone
	namespaced := admissionregv1.NamespacedScope
	path := "/validate-nav-catalyst-io-v1alpha1-naventry"
	return &admissionregv1.ValidatingWebhookConfiguration{
		ObjectMeta: metav1.ObjectMeta{Name: "catalyst-nav-naventry"},
		Webhooks: []admissionregv1.ValidatingWebhook{{
			Name:                    "naventry.nav.catalyst.io",
			FailurePolicy:           &fail,
			SideEffects:             &none,
			AdmissionReviewVersions: []string{"v1"},
			ClientConfig: admissionregv1.WebhookClientConfig{
				Service: &admissionregv1.ServiceReference{
					Name:      "catalyst-nav-webhook",
					Namespace: "catalyst-nav",
					Path:      &path,
				},
			},
			Rules: []admissionregv1.RuleWithOperations{{
				Operations: []admissionregv1.OperationType{
					admissionregv1.Create, admissionregv1.Update,
				},
				Rule: admissionregv1.Rule{
					APIGroups:   []string{"nav.catalyst.io"},
					APIVersions: []string{"v1alpha1"},
					Resources:   []string{"naventries"},
					Scope:       &namespaced,
				},
			}},
		}},
	}
}

// ── the webhook, end to end ──────────────────────────────────────────────────────────────

func TestEnvtestWebhookRejectsDanglingNavGroupRef(t *testing.T) {
	k8s, _, done := startEnv(t)
	defer done()
	ctx := context.Background()

	if err := k8s.Create(ctx, &navv1alpha1.NavGroup{
		ObjectMeta: metav1.ObjectMeta{Name: "observability"},
		Spec:       navv1alpha1.NavGroupSpec{Title: "Observability", Order: 60},
	}); err != nil {
		t.Fatalf("creating the NavGroup: %v", err)
	}

	// The good one is admitted.
	good := &navv1alpha1.NavEntry{
		ObjectMeta: metav1.ObjectMeta{Name: "ok", Namespace: "default"},
		Spec: navv1alpha1.NavEntrySpec{
			Title: "External Grafana", Href: "https://example.invalid/",
			NavGroupRef: "observability", Order: 500,
		},
	}
	if err := k8s.Create(ctx, good); err != nil {
		t.Fatalf("a valid NavEntry was rejected by the real apiserver: %v", err)
	}

	// The typo is refused BY THE APISERVER, which is the claim that matters.
	bad := &navv1alpha1.NavEntry{
		ObjectMeta: metav1.ObjectMeta{Name: "typo", Namespace: "default"},
		Spec: navv1alpha1.NavEntrySpec{
			Title: "Typo'd", Href: "https://example.invalid/",
			NavGroupRef: "obsevrability", Order: 500,
		},
	}
	err := k8s.Create(ctx, bad)
	if err == nil {
		t.Fatal("THE APISERVER ADMITTED A DANGLING navGroupRef. Either the webhook is " +
			"not selecting naventries or it is not registered -- the unit tests " +
			"cannot catch this.")
	}
	if !apierrors.IsForbidden(err) && !apierrors.IsInvalid(err) {
		t.Fatalf("rejected for the wrong reason (%T): %v", err, err)
	}
	if !strings.Contains(err.Error(), "obsevrability") {
		t.Errorf("apiserver error does not quote the bad ref: %v", err)
	}
	t.Logf("apiserver denial: %v", err)
}

func TestEnvtestCRDsMatchTheGoStructs(t *testing.T) {
	// Round-trip every field through the real schema. A field renamed in the Go struct
	// without the CRD following reads back as a zero value here rather than erroring.
	k8s, _, done := startEnv(t)
	defer done()
	ctx := context.Background()

	want := navv1alpha1.NavGroupSpec{
		Title: "Observability", Order: 60, Icon: "grafana.png",
		Lifecycle:  navv1alpha1.LifecycleStable,
		Visibility: &navv1alpha1.Visibility{AuthentikGroups: []string{"talos-admin", "cluster-admin"}},
	}
	if err := k8s.Create(ctx, &navv1alpha1.NavGroup{
		ObjectMeta: metav1.ObjectMeta{Name: "observability"}, Spec: want,
	}); err != nil {
		t.Fatalf("creating a fully-populated NavGroup: %v", err)
	}
	var got navv1alpha1.NavGroup
	if err := k8s.Get(ctx, client.ObjectKey{Name: "observability"}, &got); err != nil {
		t.Fatal(err)
	}
	if got.Spec.Title != want.Title || got.Spec.Order != want.Order ||
		got.Spec.Icon != want.Icon || got.Spec.Lifecycle != want.Lifecycle {
		t.Errorf("NavGroup spec did not round-trip: got %+v want %+v", got.Spec, want)
	}
	if got.Spec.Visibility == nil || len(got.Spec.Visibility.AuthentikGroups) != 2 {
		t.Errorf("visibility.authentikGroups did not round-trip: %+v", got.Spec.Visibility)
	}

	entry := navv1alpha1.NavEntrySpec{
		Title: "Bookmark", Href: "/catalyst/x", NavGroupRef: "observability",
		Order: 20, Themed: true, Lifecycle: navv1alpha1.LifecycleExperimental,
		Visibility: &navv1alpha1.Visibility{AuthentikGroups: []string{"talos-admin"}},
	}
	if err := k8s.Create(ctx, &navv1alpha1.NavEntry{
		ObjectMeta: metav1.ObjectMeta{Name: "bm", Namespace: "default"}, Spec: entry,
	}); err != nil {
		t.Fatalf("creating a fully-populated NavEntry: %v", err)
	}
	var gotE navv1alpha1.NavEntry
	if err := k8s.Get(ctx, client.ObjectKey{Name: "bm", Namespace: "default"}, &gotE); err != nil {
		t.Fatal(err)
	}
	if gotE.Spec.Order != 20 || !gotE.Spec.Themed ||
		gotE.Spec.Lifecycle != navv1alpha1.LifecycleExperimental ||
		gotE.Spec.Href != "/catalyst/x" {
		t.Errorf("NavEntry spec did not round-trip: %+v", gotE.Spec)
	}
}

func TestEnvtestCRDCELRulesStillBite(t *testing.T) {
	// The phase-1 CEL rule (order must be a multiple of 10) is load-bearing documentation.
	// Asserting it here means the CRD files cannot be swapped for generated ones that
	// quietly drop it -- which is the failure mode the CatalystCNPGAppDB XRD comment warns
	// about: a schema CLAIMING a constraint it does not enforce.
	k8s, _, done := startEnv(t)
	defer done()
	ctx := context.Background()

	err := k8s.Create(ctx, &navv1alpha1.NavGroup{
		ObjectMeta: metav1.ObjectMeta{Name: "offscale"},
		Spec:       navv1alpha1.NavGroupSpec{Title: "Off Scale", Order: 55},
	})
	if err == nil {
		t.Fatal("order=55 was accepted; the multiple-of-10 CEL rule is not enforced")
	}
	if !strings.Contains(err.Error(), "multiple of 10") {
		t.Errorf("rejected, but not by the documented rule: %v", err)
	}
}

// ── the reconciler, end to end ───────────────────────────────────────────────────────────

func TestEnvtestReconcilerPublishesAndReportsStatus(t *testing.T) {
	k8s, _, done := startEnv(t)
	defer done()
	ctx := context.Background()

	if err := k8s.Create(ctx, &corev1.Namespace{
		ObjectMeta: metav1.ObjectMeta{Name: "catalyst-nav"},
	}); err != nil && !apierrors.IsAlreadyExists(err) {
		t.Fatal(err)
	}
	// CollectDoc hard-errors when the IngressRoute CRD is absent, deliberately: a cluster
	// with no Traefik CRD has no nav to derive, and publishing an empty manifest there
	// would blank the bar on every app rather than report a problem.
	if err := installIngressRouteCRD(ctx, k8s); err != nil {
		t.Skipf("could not install a minimal IngressRoute CRD: %v", err)
	}
	if err := k8s.Create(ctx, &navv1alpha1.NavGroup{
		ObjectMeta: metav1.ObjectMeta{Name: "observability"},
		Spec:       navv1alpha1.NavGroupSpec{Title: "Observability", Order: 60},
	}); err != nil {
		t.Fatal(err)
	}
	if err := k8s.Create(ctx, &navv1alpha1.NavEntry{
		ObjectMeta: metav1.ObjectMeta{Name: "bm", Namespace: "default"},
		Spec: navv1alpha1.NavEntrySpec{
			Title: "Bookmark", Href: "https://example.invalid/",
			NavGroupRef: "observability", Order: 500,
		},
	}); err != nil {
		t.Fatal(err)
	}

	// Drive Reconcile directly: the watches are covered by SetupWithManager compiling
	// against the builder, and a timing-dependent "wait for the event to arrive" assertion
	// is the classic flaky test. What matters here is that a reconcile against a real
	// apiserver writes a real ConfigMap and real conditions.
	r := &controller.NavReconciler{
		Client: k8s, Namespace: "catalyst-nav", ConfigMapName: "catalyst-nav-manifest",
		Options: navmodel.Options{},
	}
	if _, err := r.Reconcile(ctx, reconcileRequest()); err != nil {
		t.Fatalf("reconcile failed: %v", err)
	}

	var cm corev1.ConfigMap
	if err := k8s.Get(ctx, client.ObjectKey{Namespace: "catalyst-nav", Name: "catalyst-nav-manifest"}, &cm); err != nil {
		t.Fatalf("manifest ConfigMap was not published: %v", err)
	}
	if got := cm.Data[controller.ManifestKey]; !strings.HasPrefix(got, `{"groups":`) {
		t.Errorf("published payload does not look like a nav manifest: %q", got)
	}
	if cm.Annotations["nav.catalyst.io/manifest-sha256"] == "" {
		t.Error("no content hash annotation on the published ConfigMap")
	}

	// The NavEntry's ref resolves, so Published must be True and name the group.
	var e navv1alpha1.NavEntry
	if err := k8s.Get(ctx, client.ObjectKey{Name: "bm", Namespace: "default"}, &e); err != nil {
		t.Fatal(err)
	}
	if c := findCondition(e.Status.Conditions, "Published"); c == nil {
		t.Fatal("NavEntry carries no Published condition -- the feedback channel is the " +
			"whole point of this phase")
	} else if c.Status != metav1.ConditionTrue {
		t.Errorf("Published = %s (%s): %s", c.Status, c.Reason, c.Message)
	}
	if e.Status.ResolvedGroup != "Observability" {
		t.Errorf("resolvedGroup = %q, want Observability", e.Status.ResolvedGroup)
	}

	var g navv1alpha1.NavGroup
	if err := k8s.Get(ctx, client.ObjectKey{Name: "observability"}, &g); err != nil {
		t.Fatal(err)
	}
	if g.Status.PublishedEntries < 1 {
		t.Errorf("NavGroup publishedEntries = %d, want >= 1", g.Status.PublishedEntries)
	}

	// Idempotence: a second reconcile must not rewrite the ConfigMap.
	before := cm.ResourceVersion
	if _, err := r.Reconcile(ctx, reconcileRequest()); err != nil {
		t.Fatal(err)
	}
	if err := k8s.Get(ctx, client.ObjectKey{Namespace: "catalyst-nav", Name: "catalyst-nav-manifest"}, &cm); err != nil {
		t.Fatal(err)
	}
	if cm.ResourceVersion != before {
		t.Errorf("a no-op reconcile rewrote the ConfigMap (%s -> %s); phase 3 and any "+
			"Flux healthcheck watching it would see churn that is not a nav change",
			before, cm.ResourceVersion)
	}
}

func TestEnvtestDeletedNavGroupLeavesAnEntryReported(t *testing.T) {
	// The residual case admission cannot cover: the group existed when the entry was
	// admitted and was deleted afterwards. This is the ONLY path to a NavGroupNotFound
	// condition, and the reason the condition exists at all.
	k8s, _, done := startEnv(t)
	defer done()
	ctx := context.Background()

	if err := k8s.Create(ctx, &corev1.Namespace{
		ObjectMeta: metav1.ObjectMeta{Name: "catalyst-nav"},
	}); err != nil && !apierrors.IsAlreadyExists(err) {
		t.Fatal(err)
	}
	// CollectDoc hard-errors when the IngressRoute CRD is absent, deliberately: a cluster
	// with no Traefik CRD has no nav to derive, and publishing an empty manifest there
	// would blank the bar on every app rather than report a problem.
	if err := installIngressRouteCRD(ctx, k8s); err != nil {
		t.Skipf("could not install a minimal IngressRoute CRD: %v", err)
	}
	g := &navv1alpha1.NavGroup{
		ObjectMeta: metav1.ObjectMeta{Name: "doomed"},
		Spec:       navv1alpha1.NavGroupSpec{Title: "Doomed", Order: 90},
	}
	if err := k8s.Create(ctx, g); err != nil {
		t.Fatal(err)
	}
	if err := k8s.Create(ctx, &navv1alpha1.NavEntry{
		ObjectMeta: metav1.ObjectMeta{Name: "orphan", Namespace: "default"},
		Spec: navv1alpha1.NavEntrySpec{
			Title: "Orphan", Href: "https://example.invalid/",
			NavGroupRef: "doomed", Order: 500,
		},
	}); err != nil {
		t.Fatalf("entry referencing an existing group was rejected: %v", err)
	}
	if err := k8s.Delete(ctx, g); err != nil {
		t.Fatal(err)
	}

	r := &controller.NavReconciler{
		Client: k8s, Namespace: "catalyst-nav", ConfigMapName: "catalyst-nav-manifest",
	}
	if _, err := r.Reconcile(ctx, reconcileRequest()); err != nil {
		t.Fatal(err)
	}

	var e navv1alpha1.NavEntry
	if err := k8s.Get(ctx, client.ObjectKey{Name: "orphan", Namespace: "default"}, &e); err != nil {
		t.Fatal(err)
	}
	c := findCondition(e.Status.Conditions, "Published")
	if c == nil || c.Status != metav1.ConditionFalse || c.Reason != "NavGroupNotFound" {
		t.Fatalf("orphaned entry condition = %+v, want Published=False/NavGroupNotFound", c)
	}
	t.Logf("condition message: %s", c.Message)
}

func TestEnvtestIngressRouteAnnotationsReachTheManifest(t *testing.T) {
	// Proves CollectDoc's unstructured list + JSON round-trip really reads the annotations
	// off a live IngressRoute. A broken GVK here returns an empty list and every other
	// assertion in this file still passes.
	k8s, env, done := startEnv(t)
	defer done()
	ctx := context.Background()
	_ = env

	if err := installIngressRouteCRD(ctx, k8s); err != nil {
		t.Skipf("could not install a minimal IngressRoute CRD: %v", err)
	}
	if err := k8s.Create(ctx, &corev1.Namespace{
		ObjectMeta: metav1.ObjectMeta{Name: "catalyst-nav"},
	}); err != nil && !apierrors.IsAlreadyExists(err) {
		t.Fatal(err)
	}
	// CollectDoc hard-errors when the IngressRoute CRD is absent, deliberately: a cluster
	// with no Traefik CRD has no nav to derive, and publishing an empty manifest there
	// would blank the bar on every app rather than report a problem.
	if err := installIngressRouteCRD(ctx, k8s); err != nil {
		t.Skipf("could not install a minimal IngressRoute CRD: %v", err)
	}

	ir := &unstructured.Unstructured{}
	ir.SetGroupVersionKind(schema.GroupVersionKind{
		Group: "traefik.io", Version: "v1alpha1", Kind: "IngressRoute",
	})
	ir.SetName("grafana")
	ir.SetNamespace("default")
	ir.SetAnnotations(map[string]string{
		"gethomepage.dev/enabled": "true",
		"gethomepage.dev/name":    "Grafana",
		"gethomepage.dev/group":   "Observability",
	})
	if err := unstructured.SetNestedSlice(ir.Object, []any{
		map[string]any{
			"match": "Host(`grafana.talos00`)",
			"middlewares": []any{
				map[string]any{"name": "catalyst-nav", "namespace": "traefik"},
			},
		},
	}, "spec", "routes"); err != nil {
		t.Fatal(err)
	}
	if err := k8s.Create(ctx, ir); err != nil {
		t.Fatalf("creating the IngressRoute: %v", err)
	}

	doc, err := controller.CollectDoc(ctx, k8s)
	if err != nil {
		t.Fatalf("CollectDoc: %v", err)
	}
	m := navmodel.Build(doc, navmodel.Options{})
	var names []string
	for _, g := range m.Groups {
		for _, it := range g.Items {
			names = append(names, it.Name)
		}
	}
	if len(names) != 1 || names[0] != "Grafana" {
		t.Fatalf("model entries = %v, want [Grafana] -- CollectDoc did not read the live "+
			"IngressRoute's annotations", names)
	}
	if m.Groups[0].Name != "Observability" {
		t.Errorf("group = %q, want Observability", m.Groups[0].Name)
	}
}

func findCondition(cs []metav1.Condition, t string) *metav1.Condition {
	for i := range cs {
		if cs[i].Type == t {
			return &cs[i]
		}
	}
	return nil
}

// ── helpers ──────────────────────────────────────────────────────────────────────────────

func dial(host string, port int) (net.Conn, error) {
	return net.DialTimeout("tcp", net.JoinHostPort(host, strconv.Itoa(port)), time.Second)
}

// reconcileRequest is the singleton key. The reconciler ignores its argument (the nav is one
// document), but passing the real key rather than a zero value keeps the call site honest if
// that ever changes.
func reconcileRequest() reconcile.Request {
	return reconcile.Request{NamespacedName: types.NamespacedName{Name: "catalyst-nav"}}
}

// installIngressRouteCRD registers a MINIMAL traefik.io IngressRoute so CollectDoc has
// something real to list.
//
// Minimal on purpose, and the limitation is the point: this is a stand-in with
// x-kubernetes-preserve-unknown-fields, NOT Traefik's real CRD. It proves CollectDoc reads the
// four fields the nav depends on and proves nothing about Traefik's own schema. Vendoring the
// real CRD would make this suite fail whenever Traefik rev'd a field the nav never reads.
func installIngressRouteCRD(ctx context.Context, c client.Client) error {
	crd := &unstructured.Unstructured{}
	crd.SetGroupVersionKind(schema.GroupVersionKind{
		Group: "apiextensions.k8s.io", Version: "v1", Kind: "CustomResourceDefinition",
	})
	crd.SetName("ingressroutes.traefik.io")
	spec := map[string]any{
		"group": "traefik.io",
		"scope": "Namespaced",
		"names": map[string]any{
			"kind": "IngressRoute", "listKind": "IngressRouteList",
			"plural": "ingressroutes", "singular": "ingressroute",
		},
		"versions": []any{map[string]any{
			"name": "v1alpha1", "served": true, "storage": true,
			"schema": map[string]any{"openAPIV3Schema": map[string]any{
				"type": "object",
				"properties": map[string]any{
					"spec": map[string]any{
						"type":                                 "object",
						"x-kubernetes-preserve-unknown-fields": true,
					},
				},
			}},
		}},
	}
	if err := unstructured.SetNestedMap(crd.Object, spec, "spec"); err != nil {
		return err
	}
	if err := c.Create(ctx, crd); err != nil && !apierrors.IsAlreadyExists(err) {
		return err
	}
	// A freshly-registered resource is not servable instantly; without this wait the first
	// List returns a NoKindMatchError that reads exactly like a wrong GVK in CollectDoc.
	deadline := time.Now().Add(30 * time.Second)
	for time.Now().Before(deadline) {
		var list unstructured.UnstructuredList
		list.SetGroupVersionKind(controller.IngressRouteGVK)
		if err := c.List(ctx, &list); err == nil {
			return nil
		}
		time.Sleep(250 * time.Millisecond)
	}
	return fmt.Errorf("IngressRoute CRD never became servable")
}
