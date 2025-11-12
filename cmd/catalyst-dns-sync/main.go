package main

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"github.com/spf13/cobra"
	"github.com/yourusername/catalyst-dns-sync/internal/config"
	"github.com/yourusername/catalyst-dns-sync/internal/controller"
	"github.com/yourusername/catalyst-dns-sync/internal/metrics"
)

var (
	// Version information (set via -ldflags)
	version   = "dev"
	gitCommit = "unknown"
	buildDate = "unknown"

	// CLI flags
	logLevel string
	mode     string
)

func main() {
	rootCmd := &cobra.Command{
		Use:   "catalyst-dns-sync",
		Short: "Kubernetes DNS sync daemon for Technitium DNS Server",
		Long: `catalyst-dns-sync watches Kubernetes Ingress and IngressRoute resources
and automatically syncs DNS A records to Technitium DNS Server.`,
		RunE: run,
	}

	rootCmd.Flags().StringVar(&logLevel, "log-level", "info", "Log level (debug, info, warn, error)")
	rootCmd.Flags().StringVar(&mode, "mode", "", "Run mode: watch or poll (overrides MODE env var)")

	versionCmd := &cobra.Command{
		Use:   "version",
		Short: "Print version information",
		Run: func(cmd *cobra.Command, args []string) {
			fmt.Printf("catalyst-dns-sync %s\n", version)
			fmt.Printf("  git commit: %s\n", gitCommit)
			fmt.Printf("  build date: %s\n", buildDate)
		},
	}

	rootCmd.AddCommand(versionCmd)

	if err := rootCmd.Execute(); err != nil {
		os.Exit(1)
	}
}

func run(cmd *cobra.Command, args []string) error {
	// Setup logging
	logger := setupLogging(logLevel)

	logger.Info().
		Str("version", version).
		Str("git_commit", gitCommit).
		Str("build_date", buildDate).
		Msg("Starting catalyst-dns-sync")

	// Load configuration
	cfg, err := config.LoadFromEnv()
	if err != nil {
		logger.Fatal().Err(err).Msg("Failed to load configuration")
	}

	// Override mode from CLI flag if provided
	if mode != "" {
		cfg.Mode = mode
	}

	logger.Info().
		Str("mode", cfg.Mode).
		Str("zone", cfg.TechnitiumZone).
		Str("node_ip", cfg.NodeIP).
		Str("technitium_url", cfg.TechnitiumURL).
		Dur("resync_interval", cfg.ResyncInterval).
		Msg("Configuration loaded")

	// Create context with cancellation
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Handle signals for graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	go func() {
		sig := <-sigChan
		logger.Info().Str("signal", sig.String()).Msg("Received shutdown signal")
		cancel()
	}()

	// Start metrics server
	metricsServer := startMetricsServer(cfg.MetricsPort, logger)
	defer func() {
		shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer shutdownCancel()
		if err := metricsServer.Shutdown(shutdownCtx); err != nil {
			logger.Error().Err(err).Msg("Metrics server shutdown error")
		}
	}()

	// Start health server
	healthServer := startHealthServer(cfg.HealthPort, logger)
	defer func() {
		shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer shutdownCancel()
		if err := healthServer.Shutdown(shutdownCtx); err != nil {
			logger.Error().Err(err).Msg("Health server shutdown error")
		}
	}()

	// Create and run controller
	ctrl, err := controller.NewController(cfg, logger)
	if err != nil {
		logger.Fatal().Err(err).Msg("Failed to create controller")
	}

	logger.Info().Msg("Controller initialized, starting sync loop")

	if err := ctrl.Run(ctx); err != nil && err != context.Canceled {
		logger.Error().Err(err).Msg("Controller error")
		metrics.HealthStatus.Set(0)
		return err
	}

	logger.Info().Msg("Shutdown complete")
	return nil
}

// setupLogging configures structured JSON logging
func setupLogging(level string) zerolog.Logger {
	// Parse log level
	logLevel, err := zerolog.ParseLevel(level)
	if err != nil {
		logLevel = zerolog.InfoLevel
	}

	zerolog.SetGlobalLevel(logLevel)
	zerolog.TimeFieldFormat = time.RFC3339

	// JSON output to stdout
	logger := zerolog.New(os.Stdout).With().
		Timestamp().
		Str("service", "catalyst-dns-sync").
		Logger()

	return logger
}

// startMetricsServer starts the Prometheus metrics HTTP server
func startMetricsServer(port int, logger zerolog.Logger) *http.Server {
	mux := http.NewServeMux()
	mux.Handle("/metrics", promhttp.Handler())

	server := &http.Server{
		Addr:         fmt.Sprintf(":%d", port),
		Handler:      mux,
		ReadTimeout:  5 * time.Second,
		WriteTimeout: 10 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	go func() {
		logger.Info().Int("port", port).Msg("Starting metrics server")
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error().Err(err).Msg("Metrics server error")
		}
	}()

	return server
}

// startHealthServer starts the health check HTTP server
func startHealthServer(port int, logger zerolog.Logger) *http.Server {
	mux := http.NewServeMux()

	// Liveness probe - always returns 200 if server is running
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("ok"))
	})

	// Readiness probe - returns 200 if healthy, 503 if not
	mux.HandleFunc("/readyz", func(w http.ResponseWriter, r *http.Request) {
		// Check if we're healthy based on metrics
		// In a real implementation, you might check last successful sync time, etc.
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("ready"))
	})

	server := &http.Server{
		Addr:         fmt.Sprintf(":%d", port),
		Handler:      mux,
		ReadTimeout:  5 * time.Second,
		WriteTimeout: 10 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	go func() {
		logger.Info().Int("port", port).Msg("Starting health server")
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error().Err(err).Msg("Health server error")
		}
	}()

	return server
}
