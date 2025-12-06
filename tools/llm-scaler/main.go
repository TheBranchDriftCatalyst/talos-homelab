// LLM Scaler - Transparent reverse proxy with scale-to-zero for EC2 workers
//
// Features:
//   - Automatic worker spin-up on first request
//   - Automatic spin-down after configurable idle timeout
//   - Request queuing during cold start
//   - Prometheus metrics
//   - Health endpoints for K8s probes
package main

import (
	"log"
	"net/http"
	"os"
	"time"
)

func main() {
	cfg := loadConfig()

	log.Printf("🚀 LLM Scaler starting")
	log.Printf("   Proxy: %s -> %s", cfg.ListenAddr, cfg.OllamaURL)
	log.Printf("   Idle timeout: %s", cfg.IdleTimeout)
	log.Printf("   Warmup timeout: %s", cfg.WarmupTimeout)
	log.Printf("   Dashboard: http://localhost%s/_/ui", cfg.ListenAddr)

	scaler := NewScaler(cfg)
	go scaler.RunIdleWatcher()
	go scaler.ServeMetrics()

	mux := http.NewServeMux()
	mux.HandleFunc("/health", scaler.Health)
	mux.HandleFunc("/ready", scaler.Ready)
	mux.HandleFunc("/_/status", scaler.Status)
	mux.HandleFunc("/_/start", scaler.ForceStart)
	mux.HandleFunc("/_/stop", scaler.ForceStop)
	mux.HandleFunc("/_/pause", scaler.Pause)
	mux.HandleFunc("/_/resume", scaler.Resume)
	mux.HandleFunc("/_/ui", scaler.UI)
	mux.HandleFunc("/", scaler.Proxy)

	log.Printf("   Listening on %s", cfg.ListenAddr)
	log.Fatal(http.ListenAndServe(cfg.ListenAddr, mux))
}

// Config for the scaler
type Config struct {
	ListenAddr    string
	MetricsAddr   string
	OllamaURL     string
	IdleTimeout   time.Duration
	WarmupTimeout time.Duration
	WorkerScript  string
}

func loadConfig() Config {
	return Config{
		ListenAddr:    env("LISTEN_ADDR", ":8080"),
		MetricsAddr:   env("METRICS_ADDR", ":9090"),
		OllamaURL:     env("OLLAMA_URL", "http://10.42.2.1:11434"),
		IdleTimeout:   duration("IDLE_TIMEOUT", 40*time.Minute),
		WarmupTimeout: duration("WARMUP_TIMEOUT", 5*time.Minute),
		WorkerScript:  env("WORKER_SCRIPT", "/app/llm-worker.sh"),
	}
}

func env(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func duration(key string, fallback time.Duration) time.Duration {
	if v := os.Getenv(key); v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			return d
		}
	}
	return fallback
}
