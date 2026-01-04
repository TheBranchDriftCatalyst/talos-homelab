// LLM Proxy - Intelligent reverse proxy for LLM inference routing
//
// Features:
//   - Multi-backend routing (local, remote, Mac dev)
//   - Automatic worker spin-up on first request
//   - Automatic spin-down after configurable idle timeout
//   - RabbitMQ broker mode for decoupled scaling
//   - Prometheus metrics
//   - Health endpoints for K8s probes
//   - Real-time WebSocket dashboard
package main

import (
	"log"
	"net/http"
	"os"
	"time"
)

func main() {
	// Check if running in worker mode (sidecar alongside Ollama)
	if IsWorkerMode() {
		log.Printf("🔧 Starting in WORKER mode")
		RunWorker()
		return
	}

	cfg := loadConfig()

	log.Printf("🚀 LLM Proxy starting")
	log.Printf("   Proxy: %s -> %s", cfg.ListenAddr, cfg.OllamaURL)
	log.Printf("   Idle timeout: %s", cfg.IdleTimeout)
	log.Printf("   Warmup timeout: %s", cfg.WarmupTimeout)
	log.Printf("   Dashboard: http://localhost%s/_/ui", cfg.ListenAddr)

	// Check if broker mode is enabled
	var broker *Broker
	if IsBrokerModeEnabled() {
		log.Printf("   Broker mode: ENABLED")
		brokerCfg := LoadBrokerConfig()
		var err error
		broker, err = NewBroker(brokerCfg)
		if err != nil {
			log.Printf("⚠️  Failed to connect to RabbitMQ, falling back to direct proxy: %v", err)
		} else {
			log.Printf("   RabbitMQ: %s:%s/%s", brokerCfg.Host, brokerCfg.Port, brokerCfg.VHost)
			defer broker.Close()
		}
	} else {
		log.Printf("   Broker mode: DISABLED (direct proxy)")
	}

	scaler := NewScaler(cfg)
	scaler.broker = broker // Attach broker to scaler
	go scaler.hub.Run()
	go scaler.RunIdleWatcher()
	go scaler.RunStatusBroadcaster()
	go scaler.ServeMetrics()

	// Ingress discovery for dynamic tabs
	ingressDiscovery, err := NewIngressDiscovery()
	if err != nil {
		log.Printf("   Ingress discovery: disabled (not in cluster)")
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/health", scaler.Health)
	mux.HandleFunc("/ready", scaler.Ready)
	mux.HandleFunc("/_/status", scaler.Status)
	mux.HandleFunc("/_/start", scaler.ForceStart)
	mux.HandleFunc("/_/stop", scaler.ForceStop)
	mux.HandleFunc("/_/pause", scaler.Pause)
	mux.HandleFunc("/_/resume", scaler.Resume)
	mux.HandleFunc("/_/ttl", scaler.SetTTL)
	mux.HandleFunc("/_/ws", scaler.WebSocket)

	// Dynamic tabs from IngressRoutes
	if ingressDiscovery != nil {
		mux.HandleFunc("/_/tabs", ingressDiscovery.TabsHandler)
	} else {
		mux.HandleFunc("/_/tabs", TabsHandlerFallback)
	}

	// Serve React UI from static files if available, otherwise use embedded HTML
	uiDir := env("UI_DIR", "/app/ui/dist")
	if _, err := os.Stat(uiDir); err == nil {
		log.Printf("   UI: Serving from %s", uiDir)
		fs := http.FileServer(http.Dir(uiDir))
		mux.Handle("/_/ui/", http.StripPrefix("/_/ui/", fs))
		mux.HandleFunc("/_/ui", func(w http.ResponseWriter, r *http.Request) {
			http.ServeFile(w, r, uiDir+"/index.html")
		})
	} else {
		log.Printf("   UI: Using embedded HTML (no %s)", uiDir)
		mux.HandleFunc("/_/ui", scaler.UI)
	}

	mux.HandleFunc("/", scaler.Proxy)

	log.Printf("   Listening on %s", cfg.ListenAddr)
	log.Fatal(http.ListenAndServe(cfg.ListenAddr, mux))
}

// Config for the scaler
type Config struct {
	ListenAddr      string
	MetricsAddr     string
	OllamaURL       string        // Primary (local) ollama
	RemoteOllamaURL string        // Remote (EC2) ollama - for status display
	MacOllamaURL    string        // Mac dev ollama (Tilt only)
	IdleTimeout     time.Duration
	WarmupTimeout   time.Duration
	WorkerScript    string
	StateFile       string
	AWSRegion       string
}

func loadConfig() Config {
	return Config{
		ListenAddr:      env("LISTEN_ADDR", ":8080"),
		MetricsAddr:     env("METRICS_ADDR", ":9090"),
		OllamaURL:       env("OLLAMA_URL", "http://10.42.2.1:11434"),
		RemoteOllamaURL: env("REMOTE_OLLAMA_URL", ""),
		MacOllamaURL:    env("MAC_OLLAMA_URL", ""), // Set by Tiltfile for dev mode
		IdleTimeout:     duration("IDLE_TIMEOUT", 40*time.Minute),
		WarmupTimeout:   duration("WARMUP_TIMEOUT", 5*time.Minute),
		WorkerScript:    env("WORKER_SCRIPT", "/app/llm-worker.sh"),
		StateFile:       env("STATE_FILE", "/app/.output/worker-state.json"),
		AWSRegion:       env("AWS_REGION", "us-west-2"),
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
