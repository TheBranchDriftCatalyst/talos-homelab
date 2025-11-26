package main

import (
	"context"
	"encoding/json"
	"flag"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/talos-fix/catalyst-dns-sync/internal/config"
	"github.com/talos-fix/catalyst-dns-sync/internal/controller"
	"github.com/talos-fix/catalyst-dns-sync/internal/dns"

	networkingv1 "k8s.io/api/networking/v1"
	"k8s.io/apimachinery/pkg/runtime"
	utilruntime "k8s.io/apimachinery/pkg/util/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/healthz"
	"sigs.k8s.io/controller-runtime/pkg/log/zap"
	metricsserver "sigs.k8s.io/controller-runtime/pkg/metrics/server"
)

var (
	scheme   = runtime.NewScheme()
	setupLog = ctrl.Log.WithName("setup")
)

func init() {
	utilruntime.Must(clientgoscheme.AddToScheme(scheme))
	utilruntime.Must(networkingv1.AddToScheme(scheme))
}

func main() {
	var devMode bool
	flag.BoolVar(&devMode, "dev-mode", false, "Enable dev mode (update /etc/hosts instead of DNS)")
	flag.Parse()

	// Load configuration
	cfg := config.LoadFromEnv()
	if devMode {
		cfg.DevMode = true
	}

	// Setup logger
	var logger *slog.Logger
	if cfg.LogFormat == "json" {
		logger = slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
			Level: parseLogLevel(cfg.LogLevel),
		}))
	} else {
		logger = slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{
			Level: parseLogLevel(cfg.LogLevel),
		}))
	}

	slog.SetDefault(logger)

	logger.Info("Starting catalyst-dns-sync",
		"devMode", cfg.DevMode,
		"zone", cfg.DNSZone,
		"ipAddress", cfg.DNSIPAddress,
	)

	if cfg.DevMode {
		logger.Info("Running in DEV MODE - will update /etc/hosts")
	} else {
		logger.Info("Running in PRODUCTION MODE - will update Technitium DNS",
			"serverURL", cfg.DNSServerURL,
		)
	}

	// Setup controller-runtime logging
	ctrl.SetLogger(zap.New(zap.UseDevMode(cfg.DevMode)))

	// Create manager
	mgr, err := ctrl.NewManager(ctrl.GetConfigOrDie(), ctrl.Options{
		Scheme: scheme,
		Metrics: metricsserver.Options{
			BindAddress: cfg.MetricsBindAddress,
		},
		HealthProbeBindAddress: cfg.HealthProbeAddress,
		LeaderElection:         false, // Single instance
	})
	if err != nil {
		logger.Error("Unable to create manager", "error", err)
		os.Exit(1)
	}

	// Create DNS client
	var dnsClient dns.DNSClient
	if cfg.DevMode {
		dnsClient = dns.NewHostsFileClient(cfg, logger)
	} else {
		dnsClient = dns.NewTechnitiumClient(cfg, logger)
	}

	// Create and setup controller
	dnsController := controller.NewDNSSyncController(
		mgr.GetClient(),
		dnsClient,
		cfg,
		logger,
		scheme,
	)

	if err := dnsController.SetupWithManager(mgr); err != nil {
		logger.Error("Unable to setup controller", "error", err)
		os.Exit(1)
	}

	// Add health checks
	if err := mgr.AddHealthzCheck("healthz", healthz.Ping); err != nil {
		logger.Error("Unable to set up health check", "error", err)
		os.Exit(1)
	}

	// Custom readiness check that verifies DNS connectivity
	if err := mgr.AddReadyzCheck("readyz", func(req *http.Request) error {
		ctx, cancel := context.WithTimeout(req.Context(), 5*time.Second)
		defer cancel()
		if !dnsClient.IsHealthy(ctx) {
			return &healthError{msg: "DNS not healthy"}
		}
		return nil
	}); err != nil {
		logger.Error("Unable to set up ready check", "error", err)
		os.Exit(1)
	}

	// Start HTTP server for custom health endpoints with JSON responses
	go startHealthServer(cfg, dnsClient, logger)

	// Perform initial full sync
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	go func() {
		// Wait for cache to sync
		time.Sleep(5 * time.Second)
		logger.Info("Performing initial full sync")
		if err := dnsController.FullSync(ctx); err != nil {
			logger.Error("Initial full sync failed", "error", err)
		}
	}()

	// Handle graceful shutdown
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	go func() {
		sig := <-sigCh
		logger.Info("Received shutdown signal", "signal", sig)
		cancel()
	}()

	// Start manager
	logger.Info("Starting manager")
	if err := mgr.Start(ctx); err != nil {
		logger.Error("Manager exited with error", "error", err)
		os.Exit(1)
	}

	logger.Info("Shutdown complete")
}

type healthError struct {
	msg string
}

func (e *healthError) Error() string {
	return e.msg
}

func parseLogLevel(level string) slog.Level {
	switch level {
	case "debug":
		return slog.LevelDebug
	case "info":
		return slog.LevelInfo
	case "warn":
		return slog.LevelWarn
	case "error":
		return slog.LevelError
	default:
		return slog.LevelInfo
	}
}

// startHealthServer starts HTTP server for JSON health endpoints
func startHealthServer(cfg *config.Config, dnsClient dns.DNSClient, logger *slog.Logger) {
	mux := http.NewServeMux()

	// JSON health endpoint
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
	})

	// JSON readiness endpoint with component checks
	mux.HandleFunc("/readyz", func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
		defer cancel()

		checks := map[string]string{
			"kubernetes": "ok",
		}

		dnsStatus := "ok"
		if !dnsClient.IsHealthy(ctx) {
			dnsStatus = "error"
		}
		checks["dns"] = dnsStatus

		response := map[string]interface{}{
			"status": "ok",
			"checks": checks,
		}

		if dnsStatus != "ok" {
			response["status"] = "degraded"
			w.WriteHeader(http.StatusServiceUnavailable)
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(response)
	})

	// Prometheus metrics (additional endpoint, controller-runtime also serves at :8080/metrics)
	mux.Handle("/metrics", promhttp.Handler())

	// Start server on a different port to not conflict with controller-runtime
	addr := ":8082"
	logger.Info("Starting health server", "addr", addr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		logger.Error("Health server failed", "error", err)
	}
}
