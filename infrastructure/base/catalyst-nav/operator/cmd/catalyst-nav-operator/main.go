// catalyst-nav-operator reconciles the Catalyst navbar model from the cluster.
//
// Two modes, because phase 6's audit needs one of them and the cluster needs the other:
//
//	catalyst-nav-operator            run the controller + webhook (the Deployment's command)
//	catalyst-nav-operator render     stdin/stdout, byte-identical to build_nav.py
//
// See internal/render for why the parity mode reads a document on stdin instead of talking to
// the apiserver itself.
package main

import (
	"fmt"
	"os"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/cache"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/healthz"
	"sigs.k8s.io/controller-runtime/pkg/log/zap"
	"sigs.k8s.io/controller-runtime/pkg/metrics"
	metricsserver "sigs.k8s.io/controller-runtime/pkg/metrics/server"
	webhookserver "sigs.k8s.io/controller-runtime/pkg/webhook"
	"sigs.k8s.io/controller-runtime/pkg/webhook/admission"

	navv1alpha1 "github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/api/v1alpha1"
	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/controller"
	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/navmodel"
	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/navserve"
	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/render"
	navwebhook "github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/webhook"
)

func main() {
	if len(os.Args) > 1 && os.Args[1] == "render" {
		if err := render.Run(os.Stdin, os.Stdout, os.Stderr, render.EnvFromOS()); err != nil {
			fmt.Fprintf(os.Stderr, "[nav] %v\n", err)
			os.Exit(1)
		}
		return
	}
	if len(os.Args) > 1 {
		fmt.Fprintf(os.Stderr, "usage: %s [render]\n", os.Args[0])
		os.Exit(2)
	}
	if err := runManager(); err != nil {
		fmt.Fprintf(os.Stderr, "[nav] fatal: %v\n", err)
		os.Exit(1)
	}
}

func runManager() error {
	ctrl.SetLogger(zap.New(zap.UseDevMode(false)))
	lg := ctrl.Log.WithName("setup")

	scheme := runtime.NewScheme()
	if err := clientgoscheme.AddToScheme(scheme); err != nil {
		return err
	}
	if err := navv1alpha1.AddToScheme(scheme); err != nil {
		return err
	}

	ns := envOr("POD_NAMESPACE", "catalyst-nav")
	cmName := envOr("NAV_CONFIGMAP", "catalyst-nav-manifest")

	mgr, err := ctrl.NewManager(ctrl.GetConfigOrDie(), ctrl.Options{
		Scheme: scheme,
		Metrics: metricsserver.Options{
			// Alloy scrapes by pod annotation in this cluster (see
			// infrastructure/base/monitoring/v2-otel/alloy), so this is plain HTTP on
			// the pod IP rather than the kube-rbac-proxy arrangement kubebuilder
			// scaffolds. No ServiceMonitor is needed.
			BindAddress: ":8080",
		},
		HealthProbeBindAddress: ":8081",
		WebhookServer: webhookserver.NewServer(webhookserver.Options{
			Port:    9443,
			CertDir: envOr("WEBHOOK_CERT_DIR", "/tmp/k8s-webhook-server/serving-certs"),
		}),
		Cache: cache.Options{
			// Cache ConfigMaps only in our own namespace. Without this the informer
			// would watch and hold EVERY ConfigMap in the cluster in memory to manage
			// the one it writes — on this cluster that is the whole Grafana dashboard
			// set, which is tens of megabytes of JSON for no reason.
			ByObject: map[client.Object]cache.ByObject{
				&corev1.ConfigMap{}: {
					Namespaces: map[string]cache.Config{ns: {}},
				},
			},
		},
		// No LeaderElection. The reconcile is idempotent and writes one ConfigMap plus
		// statuses, and the Deployment is replicas: 1 with strategy Recreate, so a lease
		// would add a failure mode (a stuck lease delays startup by its duration) to
		// protect against a concurrency that cannot occur. Revisit if this ever scales
		// out — which it should not: the model is a singleton.
		LeaderElection: false,
	})
	if err != nil {
		return fmt.Errorf("building manager: %w", err)
	}

	// The per-identity manifest endpoint (phase 3). The reconciler publishes into this store
	// and the handler reads from it, so there is exactly one build per reconcile and the
	// endpoint cannot disagree with the ConfigMap. Nothing routes to it yet — phase 4 adds
	// the IngressRoute, and it must NOT carry the catalyst-asset-cache middleware; see
	// internal/navserve's package comment.
	snapshots := &navserve.Store{}
	manifestHandler := navserve.NewHandler(snapshots, navserve.Config{
		Path:              envOr("NAV_MANIFEST_PATH", navserve.DefaultPath),
		GroupsHeader:      envOr("NAV_GROUPS_HEADER", navserve.DefaultGroupsHeader),
		UsernameHeader:    envOr("NAV_USERNAME_HEADER", navserve.DefaultUsernameHeader),
		GroupSeparator:    envOr("NAV_GROUP_SEPARATOR", navserve.DefaultGroupSeparator),
		AttestationHeader: envOr("NAV_PROXY_HEADER", navserve.DefaultAttestationHeader),
		// Empty by default: attestation stays OFF until phase 4 also deploys the
		// Traefik middleware that injects the secret. Setting it here alone would
		// anonymise every real user, which is a silent cosmetic regression rather than
		// a visible failure — exactly the kind this component exists to avoid.
		AttestationSecret: os.Getenv("NAV_PROXY_SECRET"),
	}, metrics.Registry)
	// Same registry Alloy already scrapes on :8080, so the request counters land beside the
	// controller-runtime ones with no new scrape target.
	if err := mgr.Add(&navserve.Server{
		Addr:    envOr("NAV_MANIFEST_ADDR", ":8082"),
		Handler: manifestHandler,
	}); err != nil {
		return fmt.Errorf("wiring the manifest endpoint: %w", err)
	}

	navReconciler := &controller.NavReconciler{
		Client:        mgr.GetClient(),
		Namespace:     ns,
		ConfigMapName: cmName,
		Snapshots:     snapshots,
		Options: navmodel.Options{
			ScopeAll: envOr("NAV_SCOPE", "themed") == "all",
			Defaults: navmodel.ParseNavDefaultsEnv(os.Getenv("NAV_DEFAULTS"), os.Stderr),
			// Log stays nil: the reconciler's feedback channel is status.conditions,
			// not stderr. Writing the refusal lines here as well would recreate the
			// exact thing phase 2 is replacing — diagnostics in a log nobody reads.
		},
	}
	if err := navReconciler.SetupWithManager(mgr); err != nil {
		return fmt.Errorf("wiring the nav controller: %w", err)
	}

	mgr.GetWebhookServer().Register("/validate-nav-catalyst-io-v1alpha1-naventry",
		&admission.Webhook{Handler: &navwebhook.NavEntryValidator{
			Client:    mgr.GetClient(),
			APIReader: mgr.GetAPIReader(),
		}})

	if err := mgr.AddHealthzCheck("ping", healthz.Ping); err != nil {
		return err
	}
	// Readiness is gated on the webhook's listener, not on Ping. The
	// ValidatingWebhookConfiguration is failurePolicy: Fail, so a pod that reports Ready
	// before its TLS listener is up makes the Service route NavEntry admission to a closed
	// port — every NavEntry write in the cluster fails until it catches up.
	if err := mgr.AddReadyzCheck("webhook", mgr.GetWebhookServer().StartedChecker()); err != nil {
		return err
	}

	lg.Info("starting", "namespace", ns, "configMap", cmName)
	return mgr.Start(ctrl.SetupSignalHandler())
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
