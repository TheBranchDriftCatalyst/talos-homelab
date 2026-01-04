package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"sync"
	"sync/atomic"
	"time"

	"github.com/google/uuid"
)

// State represents worker lifecycle states
type State string

const (
	StateUnknown  State = "unknown"
	StateStopped  State = "stopped"
	StateStarting State = "starting"
	StateRunning  State = "running"
	StateStopping State = "stopping"
)

// RoutingMode determines which backend to route to
type RoutingMode string

const (
	RoutingAuto   RoutingMode = "auto"   // Try local first, fallback to remote
	RoutingLocal  RoutingMode = "local"  // Force local only
	RoutingRemote RoutingMode = "remote" // Force remote only
	RoutingMac    RoutingMode = "mac"    // Force Mac dev endpoint (Tilt only)
)

// Scaler manages the EC2 worker lifecycle and proxies requests
type Scaler struct {
	cfg         Config
	localProxy  *httputil.ReverseProxy
	remoteProxy *httputil.ReverseProxy
	macProxy    *httputil.ReverseProxy // Mac dev endpoint (Tilt only)
	hub         *Hub                   // WebSocket hub
	broker      *Broker                // RabbitMQ broker (nil if disabled)
	fleet       *FleetClient           // Fleet API client (nil if disabled)
	executor    *Executor              // Process executor for worker control

	mu           sync.RWMutex
	state        State
	lastActivity time.Time
	startOnce    *sync.Once
	startDone    chan struct{}
	paused       bool        // When true, disable auto-scaling (idle shutdown)
	routingMode  RoutingMode // Current routing mode
	activeTarget string      // Currently active target URL for metrics

	// Metrics (atomic for lock-free reads)
	requests      atomic.Int64
	blocked       atomic.Int64
	starts        atomic.Int64
	localRouted   atomic.Int64
	remoteRouted  atomic.Int64
	macRouted     atomic.Int64
	brokerRouted  atomic.Int64
}

// NewScaler creates a new scaler instance
func NewScaler(cfg Config) *Scaler {
	localTarget, _ := url.Parse(cfg.OllamaURL)

	hub := NewHub()

	s := &Scaler{
		cfg:          cfg,
		hub:          hub,
		executor:     NewExecutor(cfg.WorkerScript, hub),
		state:        StateUnknown,
		lastActivity: time.Now(),
		routingMode:  RoutingAuto,
		activeTarget: cfg.OllamaURL,
	}

	// Local proxy (primary)
	s.localProxy = httputil.NewSingleHostReverseProxy(localTarget)
	s.localProxy.ErrorHandler = s.proxyError

	// Remote proxy (if configured)
	if cfg.RemoteOllamaURL != "" {
		remoteTarget, _ := url.Parse(cfg.RemoteOllamaURL)
		s.remoteProxy = httputil.NewSingleHostReverseProxy(remoteTarget)
		s.remoteProxy.ErrorHandler = s.proxyError
	}

	// Mac proxy (if configured - Tilt dev mode only)
	if cfg.MacOllamaURL != "" {
		macTarget, _ := url.Parse(cfg.MacOllamaURL)
		s.macProxy = httputil.NewSingleHostReverseProxy(macTarget)
		s.macProxy.ErrorHandler = s.proxyError
		log.Printf("   Mac dev endpoint: %s", cfg.MacOllamaURL)
	}

	return s
}

// proxyError handles backend connection failures
func (s *Scaler) proxyError(w http.ResponseWriter, r *http.Request, err error) {
	log.Printf("⚠️  Proxy error: %v", err)
	writeJSON(w, http.StatusBadGateway, map[string]any{
		"error": "backend unavailable",
		"hint":  "worker may be starting up",
	})
}

// Proxy handles all incoming requests
func (s *Scaler) Proxy(w http.ResponseWriter, r *http.Request) {
	s.requests.Add(1)

	// Check if this is an inference request that should go through broker
	if s.shouldUseBroker(r) {
		s.handleBrokerRequest(w, r)
		return
	}

	// Direct proxy mode for non-inference requests or when broker is disabled

	// Get routing mode and determine target
	s.mu.RLock()
	mode := s.routingMode
	s.mu.RUnlock()

	var proxy *httputil.ReverseProxy
	var targetURL string

	switch mode {
	case RoutingMac:
		// Force Mac dev endpoint only (Tilt mode)
		if s.macProxy == nil || !s.checkEndpoint(s.cfg.MacOllamaURL) {
			writeJSON(w, http.StatusServiceUnavailable, map[string]any{
				"error":   "mac worker unavailable",
				"message": "Mac ollama is not responding. Is 'ollama serve' running?",
				"mode":    "mac",
			})
			return
		}
		proxy = s.macProxy
		targetURL = s.cfg.MacOllamaURL
		s.macRouted.Add(1)

	case RoutingLocal:
		// Force local only
		if !s.checkEndpoint(s.cfg.OllamaURL) {
			writeJSON(w, http.StatusServiceUnavailable, map[string]any{
				"error":   "local worker unavailable",
				"message": "Local ollama is not responding",
				"mode":    "local",
			})
			return
		}
		proxy = s.localProxy
		targetURL = s.cfg.OllamaURL
		s.localRouted.Add(1)

	case RoutingRemote:
		// Force remote only
		if s.remoteProxy == nil || !s.checkEndpoint(s.cfg.RemoteOllamaURL) {
			// Try to start EC2 if not ready
			if s.remoteProxy != nil {
				s.blocked.Add(1)
				ctx, cancel := context.WithTimeout(r.Context(), s.cfg.WarmupTimeout)
				defer cancel()
				if err := s.ensureRunning(ctx); err != nil {
					writeJSON(w, http.StatusServiceUnavailable, map[string]any{
						"error":   "remote worker unavailable",
						"message": "EC2 worker is starting. Retry in 2-3 minutes.",
						"mode":    "remote",
					})
					return
				}
			} else {
				writeJSON(w, http.StatusServiceUnavailable, map[string]any{
					"error":   "remote not configured",
					"message": "No remote ollama URL configured",
					"mode":    "remote",
				})
				return
			}
		}
		proxy = s.remoteProxy
		targetURL = s.cfg.RemoteOllamaURL
		s.remoteRouted.Add(1)

	default: // RoutingAuto
		// Try local first, fallback to remote
		if s.checkEndpoint(s.cfg.OllamaURL) {
			proxy = s.localProxy
			targetURL = s.cfg.OllamaURL
			s.localRouted.Add(1)
		} else if s.remoteProxy != nil && s.checkEndpoint(s.cfg.RemoteOllamaURL) {
			proxy = s.remoteProxy
			targetURL = s.cfg.RemoteOllamaURL
			s.remoteRouted.Add(1)
		} else {
			// Neither available, try to start EC2
			s.blocked.Add(1)
			ctx, cancel := context.WithTimeout(r.Context(), s.cfg.WarmupTimeout)
			defer cancel()

			if err := s.ensureRunning(ctx); err != nil {
				writeJSON(w, http.StatusServiceUnavailable, map[string]any{
					"error":   "no workers available",
					"message": "All LLM workers are offline. Retry in 2-3 minutes.",
					"mode":    "auto",
				})
				return
			}
			// After cold start, check which is ready
			if s.checkEndpoint(s.cfg.OllamaURL) {
				proxy = s.localProxy
				targetURL = s.cfg.OllamaURL
				s.localRouted.Add(1)
			} else if s.remoteProxy != nil {
				proxy = s.remoteProxy
				targetURL = s.cfg.RemoteOllamaURL
				s.remoteRouted.Add(1)
			}
		}
	}

	if proxy == nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"error": "no backend available",
		})
		return
	}

	// Update active target for UI
	s.mu.Lock()
	s.activeTarget = targetURL
	s.mu.Unlock()

	// Update activity timestamp
	s.touch()

	// Proxy the request
	proxy.ServeHTTP(w, r)
}

// Health returns 200 if the scaler is running (liveness)
func (s *Scaler) Health(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"status": "ok"})
}

// Ready returns 200 only if worker is ready (readiness)
func (s *Scaler) Ready(w http.ResponseWriter, r *http.Request) {
	if s.isReady() {
		writeJSON(w, http.StatusOK, map[string]any{
			"status": "ready",
			"worker": "running",
		})
	} else {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"status": "not_ready",
			"worker": s.getState(),
		})
	}
}

// Status returns detailed scaler status
func (s *Scaler) Status(w http.ResponseWriter, r *http.Request) {
	s.mu.RLock()
	idle := time.Since(s.lastActivity)
	paused := s.paused
	s.mu.RUnlock()

	// Check local (primary) ollama status
	localReady := s.isReady()
	localState := "stopped"
	if localReady {
		localState = "running"
	}

	// Check remote (EC2/bigboi) ollama status
	remoteReady := false
	remoteState := "stopped"
	if s.cfg.RemoteOllamaURL != "" {
		remoteReady = s.checkEndpoint(s.cfg.RemoteOllamaURL)
		if remoteReady {
			remoteState = "running"
		}
	} else {
		remoteState = "not_configured"
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"worker_state":     s.getState(),
		"worker_ready":     localReady,
		"paused":           paused,
		"idle":             idle.Round(time.Second).String(),
		"idle_timeout":     s.cfg.IdleTimeout.String(),
		"until_shutdown":   (s.cfg.IdleTimeout - idle).Round(time.Second).String(),
		"requests_total":   s.requests.Load(),
		"requests_blocked": s.blocked.Load(),
		"cold_starts":      s.starts.Load(),
		// Dual-backend status
		"local": map[string]any{
			"url":   s.cfg.OllamaURL,
			"state": localState,
			"ready": localReady,
		},
		"remote": map[string]any{
			"url":   s.cfg.RemoteOllamaURL,
			"state": remoteState,
			"ready": remoteReady,
		},
	})
}

// checkEndpoint checks if an ollama endpoint is responding
func (s *Scaler) checkEndpoint(url string) bool {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	req, _ := http.NewRequestWithContext(ctx, "GET", url+"/api/tags", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode == http.StatusOK
}

// ForceStart manually triggers a worker start
func (s *Scaler) ForceStart(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "POST required", http.StatusMethodNotAllowed)
		return
	}

	go s.startWorker()
	writeJSON(w, http.StatusAccepted, map[string]any{
		"status":  "starting",
		"message": "Worker start initiated",
	})
}

// ForceStop manually triggers a worker stop
func (s *Scaler) ForceStop(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "POST required", http.StatusMethodNotAllowed)
		return
	}

	go s.stopWorker()
	writeJSON(w, http.StatusAccepted, map[string]any{
		"status":  "stopping",
		"message": "Worker stop initiated",
	})
}

// Pause disables automatic idle shutdown
func (s *Scaler) Pause(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "POST required", http.StatusMethodNotAllowed)
		return
	}

	s.mu.Lock()
	s.paused = true
	s.mu.Unlock()

	log.Printf("⏸️  Scaler PAUSED - idle shutdown disabled")
	writeJSON(w, http.StatusOK, map[string]any{
		"status":  "paused",
		"message": "Auto-scaling paused. Worker will not auto-shutdown.",
	})
}

// Resume re-enables automatic idle shutdown
func (s *Scaler) Resume(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "POST required", http.StatusMethodNotAllowed)
		return
	}

	s.mu.Lock()
	s.paused = false
	s.lastActivity = time.Now() // Reset idle timer on resume
	s.mu.Unlock()

	log.Printf("▶️  Scaler RESUMED - idle shutdown enabled")
	writeJSON(w, http.StatusOK, map[string]any{
		"status":  "resumed",
		"message": "Auto-scaling resumed. Idle timer reset.",
	})
}

// SetTTL updates the idle timeout
func (s *Scaler) SetTTL(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "POST required", http.StatusMethodNotAllowed)
		return
	}

	ttl := r.URL.Query().Get("ttl")
	if ttl == "" {
		writeJSON(w, http.StatusBadRequest, map[string]any{
			"error": "ttl parameter required (e.g., ?ttl=30m)",
		})
		return
	}

	duration, err := time.ParseDuration(ttl)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{
			"error":   "invalid duration format",
			"example": "15m, 1h, 30m",
		})
		return
	}

	// Minimum 5 minutes, maximum 24 hours
	if duration < 5*time.Minute {
		duration = 5 * time.Minute
	}
	if duration > 24*time.Hour {
		duration = 24 * time.Hour
	}

	s.mu.Lock()
	s.cfg.IdleTimeout = duration
	s.lastActivity = time.Now() // Reset timer on TTL change
	s.mu.Unlock()

	log.Printf("⏱️  Idle timeout changed to %s", duration)
	writeJSON(w, http.StatusOK, map[string]any{
		"status":       "updated",
		"idle_timeout": duration.String(),
		"message":      fmt.Sprintf("Idle timeout set to %s. Timer reset.", duration),
	})
}

// RunIdleWatcher checks for idle timeout and stops the worker
func (s *Scaler) RunIdleWatcher() {
	tick := time.NewTicker(time.Minute)
	defer tick.Stop()

	for range tick.C {
		if !s.isReady() {
			continue
		}

		s.mu.RLock()
		idle := time.Since(s.lastActivity)
		paused := s.paused
		s.mu.RUnlock()

		if paused {
			log.Printf("⏸️  Idle: %s (PAUSED - no auto-shutdown)", idle.Round(time.Second))
			continue
		}

		log.Printf("⏱️  Idle: %s / %s", idle.Round(time.Second), s.cfg.IdleTimeout)

		if idle >= s.cfg.IdleTimeout {
			log.Printf("💤 Idle timeout reached, stopping worker...")
			s.stopWorker()
		}
	}
}

// ServeMetrics exposes Prometheus metrics on a dedicated server
func (s *Scaler) ServeMetrics() {
	mux := http.NewServeMux()
	mux.HandleFunc("/metrics", func(w http.ResponseWriter, r *http.Request) {
		s.mu.RLock()
		idle := time.Since(s.lastActivity).Seconds()
		state := s.state
		s.mu.RUnlock()

		up := 0
		if s.isReady() {
			up = 1
		}

		starting := 0
		if state == StateStarting {
			starting = 1
		}

		// Worker state
		fmt.Fprintf(w, "# HELP llm_scaler_worker_up Worker is running and ready\n")
		fmt.Fprintf(w, "# TYPE llm_scaler_worker_up gauge\n")
		fmt.Fprintf(w, "llm_scaler_worker_up %d\n\n", up)

		fmt.Fprintf(w, "# HELP llm_scaler_worker_starting Worker is currently starting\n")
		fmt.Fprintf(w, "# TYPE llm_scaler_worker_starting gauge\n")
		fmt.Fprintf(w, "llm_scaler_worker_starting %d\n\n", starting)

		// Request metrics
		fmt.Fprintf(w, "# HELP llm_scaler_requests_total Total requests received\n")
		fmt.Fprintf(w, "# TYPE llm_scaler_requests_total counter\n")
		fmt.Fprintf(w, "llm_scaler_requests_total %d\n\n", s.requests.Load())

		fmt.Fprintf(w, "# HELP llm_scaler_requests_blocked Requests that triggered cold start\n")
		fmt.Fprintf(w, "# TYPE llm_scaler_requests_blocked counter\n")
		fmt.Fprintf(w, "llm_scaler_requests_blocked %d\n\n", s.blocked.Load())

		fmt.Fprintf(w, "# HELP llm_scaler_cold_starts_total Cold starts triggered\n")
		fmt.Fprintf(w, "# TYPE llm_scaler_cold_starts_total counter\n")
		fmt.Fprintf(w, "llm_scaler_cold_starts_total %d\n\n", s.starts.Load())

		// Idle metrics
		fmt.Fprintf(w, "# HELP llm_scaler_idle_seconds Seconds since last request\n")
		fmt.Fprintf(w, "# TYPE llm_scaler_idle_seconds gauge\n")
		fmt.Fprintf(w, "llm_scaler_idle_seconds %.0f\n\n", idle)

		fmt.Fprintf(w, "# HELP llm_scaler_idle_timeout_seconds Configured idle timeout\n")
		fmt.Fprintf(w, "# TYPE llm_scaler_idle_timeout_seconds gauge\n")
		fmt.Fprintf(w, "llm_scaler_idle_timeout_seconds %.0f\n\n", s.cfg.IdleTimeout.Seconds())

		fmt.Fprintf(w, "# HELP llm_scaler_warmup_timeout_seconds Configured warmup timeout\n")
		fmt.Fprintf(w, "# TYPE llm_scaler_warmup_timeout_seconds gauge\n")
		fmt.Fprintf(w, "llm_scaler_warmup_timeout_seconds %.0f\n", s.cfg.WarmupTimeout.Seconds())
	})

	log.Printf("   Metrics on %s/metrics", s.cfg.MetricsAddr)
	if err := http.ListenAndServe(s.cfg.MetricsAddr, mux); err != nil {
		log.Printf("Metrics server error: %v", err)
	}
}

// isReady checks if worker is responding
func (s *Scaler) isReady() bool {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	req, _ := http.NewRequestWithContext(ctx, "GET", s.cfg.OllamaURL+"/api/tags", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusOK {
		s.setState(StateRunning)
		return true
	}
	return false
}

// ensureRunning starts the worker if needed and waits for it
func (s *Scaler) ensureRunning(ctx context.Context) error {
	if s.isReady() {
		return nil
	}

	s.mu.Lock()

	// Already starting? Wait for it
	if s.state == StateStarting {
		done := s.startDone
		s.mu.Unlock()

		select {
		case <-done:
			if s.isReady() {
				return nil
			}
			return fmt.Errorf("start completed but worker not ready")
		case <-ctx.Done():
			return ctx.Err()
		}
	}

	// Initiate start
	s.state = StateStarting
	s.startDone = make(chan struct{})
	done := s.startDone
	s.mu.Unlock()

	s.starts.Add(1)
	log.Printf("🔥 Cold start #%d initiated", s.starts.Load())

	// Start worker
	go func() {
		defer close(done)
		if err := s.startWorker(); err != nil {
			log.Printf("❌ Start failed: %v", err)
			s.setState(StateStopped)
		}
	}()

	// Wait for ready
	select {
	case <-done:
		if s.isReady() {
			return nil
		}
		return fmt.Errorf("start completed but worker not ready")
	case <-ctx.Done():
		return ctx.Err()
	}
}

// startWorker executes the worker script with "warm" command
// Output is streamed to WebSocket clients via the executor
func (s *Scaler) startWorker() error {
	log.Printf("▶️  Starting worker...")
	s.setState(StateStarting)

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()

	exitCode, err := s.executor.ExecuteSync(ctx, "remote", "warm")
	if err != nil {
		log.Printf("Start failed: %v", err)
		s.setState(StateUnknown)
		return err
	}

	if exitCode != 0 {
		log.Printf("Start failed with exit code %d", exitCode)
		s.setState(StateUnknown)
		return fmt.Errorf("worker script exited with code %d", exitCode)
	}

	log.Printf("✅ Worker started")
	s.setState(StateRunning)
	s.touch()
	return nil
}

// stopWorker executes the worker script with "stop" command
// Output is streamed to WebSocket clients via the executor
func (s *Scaler) stopWorker() error {
	log.Printf("⏹️  Stopping worker...")
	s.setState(StateStopping)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()

	exitCode, err := s.executor.ExecuteSync(ctx, "remote", "stop")
	if err != nil {
		log.Printf("Stop failed: %v", err)
		s.setState(StateUnknown)
		return err
	}

	if exitCode != 0 {
		log.Printf("Stop failed with exit code %d", exitCode)
		s.setState(StateUnknown)
		return fmt.Errorf("worker script exited with code %d", exitCode)
	}

	log.Printf("✅ Worker stopped")
	s.setState(StateStopped)
	return nil
}

func (s *Scaler) getState() State {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.state
}

func (s *Scaler) setState(state State) {
	s.mu.Lock()
	s.state = state
	s.mu.Unlock()
}

func (s *Scaler) touch() {
	s.mu.Lock()
	s.lastActivity = time.Now()
	s.mu.Unlock()
}

// GetRoutingMode returns the current routing mode
func (s *Scaler) GetRoutingMode() RoutingMode {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.routingMode
}

// SetRoutingMode changes the routing mode
func (s *Scaler) SetRoutingMode(mode RoutingMode) {
	s.mu.Lock()
	s.routingMode = mode
	s.mu.Unlock()
	log.Printf("🔀 Routing mode changed to: %s", mode)
}

// GetActiveTarget returns the currently active backend URL
func (s *Scaler) GetActiveTarget() string {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.activeTarget
}

// GetRoutingStats returns routing statistics
func (s *Scaler) GetRoutingStats() (local, remote, mac int64) {
	return s.localRouted.Load(), s.remoteRouted.Load(), s.macRouted.Load()
}

// HasMacEndpoint returns true if Mac dev endpoint is configured
func (s *Scaler) HasMacEndpoint() bool {
	return s.cfg.MacOllamaURL != ""
}

// GetMacOllamaURL returns the Mac Ollama URL if configured
func (s *Scaler) GetMacOllamaURL() string {
	return s.cfg.MacOllamaURL
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

// shouldUseBroker determines if request should go through RabbitMQ
func (s *Scaler) shouldUseBroker(r *http.Request) bool {
	// Only POST requests to inference endpoints use broker
	if r.Method != http.MethodPost {
		return false
	}

	// Check if broker is available
	if s.broker == nil || !s.broker.IsConnected() {
		return false
	}

	// Only route /api/generate and /api/chat through broker
	path := r.URL.Path
	return path == "/api/generate" || path == "/api/chat"
}

// handleBrokerRequest routes inference requests through RabbitMQ
func (s *Scaler) handleBrokerRequest(w http.ResponseWriter, r *http.Request) {
	start := time.Now()

	// Read request body
	body, err := io.ReadAll(r.Body)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{
			"error": "failed to read request body",
		})
		return
	}
	r.Body.Close()

	// Parse the request to extract model and prompt
	var ollamaReq struct {
		Model   string         `json:"model"`
		Prompt  string         `json:"prompt"`
		Stream  bool           `json:"stream"`
		Options map[string]any `json:"options"`
	}
	if err := json.Unmarshal(body, &ollamaReq); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{
			"error": "invalid JSON request",
		})
		return
	}

	// Check for streaming - not supported through broker yet
	if ollamaReq.Stream {
		log.Printf("📡 Streaming request, falling back to direct proxy")
		// Recreate request body and fall through to direct proxy
		r.Body = io.NopCloser(bytes.NewReader(body))
		s.proxyDirect(w, r)
		return
	}

	// Create inference request
	req := &InferenceRequest{
		ID:        uuid.New().String(),
		Model:     ollamaReq.Model,
		Prompt:    ollamaReq.Prompt,
		Stream:    false,
		Options:   ollamaReq.Options,
		Timestamp: time.Now(),
	}

	log.Printf("📨 Broker: routing %s to model %s", req.ID[:8], req.Model)

	// Set timeout for broker request (5 min max for inference)
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Minute)
	defer cancel()

	// Publish to broker and wait for response
	resp, err := s.broker.Publish(ctx, req)
	if err != nil {
		log.Printf("❌ Broker error: %v, falling back to direct proxy", err)
		// On broker failure, fallback to direct proxy
		r.Body = io.NopCloser(bytes.NewReader(body))
		s.proxyDirect(w, r)
		return
	}

	s.brokerRouted.Add(1)
	s.touch()

	duration := time.Since(start)
	log.Printf("✅ Broker: %s completed in %s (worker: %s)", req.ID[:8], duration.Round(time.Millisecond), resp.WorkerID)

	// Return response in Ollama format
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]any{
		"model":          resp.Model,
		"response":       resp.Response,
		"done":           resp.Done,
		"total_duration": resp.Duration * 1000000, // Convert ms to ns for Ollama compat
	})
}

// proxyDirect handles direct HTTP proxy (fallback or non-broker requests)
func (s *Scaler) proxyDirect(w http.ResponseWriter, r *http.Request) {
	// Get routing mode
	s.mu.RLock()
	mode := s.routingMode
	s.mu.RUnlock()

	var proxy *httputil.ReverseProxy
	var targetURL string

	switch mode {
	case RoutingMac:
		if s.macProxy != nil && s.checkEndpoint(s.cfg.MacOllamaURL) {
			proxy = s.macProxy
			targetURL = s.cfg.MacOllamaURL
			s.macRouted.Add(1)
		}
	case RoutingLocal:
		if s.checkEndpoint(s.cfg.OllamaURL) {
			proxy = s.localProxy
			targetURL = s.cfg.OllamaURL
			s.localRouted.Add(1)
		}
	case RoutingRemote:
		if s.remoteProxy != nil && s.checkEndpoint(s.cfg.RemoteOllamaURL) {
			proxy = s.remoteProxy
			targetURL = s.cfg.RemoteOllamaURL
			s.remoteRouted.Add(1)
		}
	default: // RoutingAuto
		if s.checkEndpoint(s.cfg.OllamaURL) {
			proxy = s.localProxy
			targetURL = s.cfg.OllamaURL
			s.localRouted.Add(1)
		} else if s.remoteProxy != nil && s.checkEndpoint(s.cfg.RemoteOllamaURL) {
			proxy = s.remoteProxy
			targetURL = s.cfg.RemoteOllamaURL
			s.remoteRouted.Add(1)
		}
	}

	if proxy == nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"error": "no backend available",
		})
		return
	}

	s.mu.Lock()
	s.activeTarget = targetURL
	s.mu.Unlock()
	s.touch()

	proxy.ServeHTTP(w, r)
}

// GetBrokerStats returns broker routing statistics
func (s *Scaler) GetBrokerStats() int64 {
	return s.brokerRouted.Load()
}

// IsBrokerConnected checks if broker is connected
func (s *Scaler) IsBrokerConnected() bool {
	return s.broker != nil && s.broker.IsConnected()
}

// FleetStatus returns the current fleet state for the API
func (s *Scaler) FleetStatus(w http.ResponseWriter, r *http.Request) {
	if s.fleet == nil {
		writeJSON(w, http.StatusOK, map[string]any{
			"enabled": false,
			"message": "Fleet API not configured",
		})
		return
	}

	nodes := s.fleet.GetNodes()
	gpuWorkers := s.fleet.GetGPUWorkers()
	bestWorker := s.fleet.GetBestGPUWorker()

	result := map[string]any{
		"enabled":     true,
		"total_nodes": len(nodes),
		"gpu_workers": len(gpuWorkers),
		"nodes":       nodes,
	}

	if bestWorker != nil {
		result["best_worker"] = map[string]any{
			"id":         bestWorker.ID,
			"nebula_ip":  bestWorker.NebulaIP,
			"health":     bestWorker.Health,
			"ollama_url": fmt.Sprintf("http://%s:11434", bestWorker.NebulaIP),
		}
	}

	writeJSON(w, http.StatusOK, result)
}

// GetDynamicRemoteURL returns the remote Ollama URL, preferring fleet API if configured
func (s *Scaler) GetDynamicRemoteURL() string {
	// If fleet is configured and has workers, use dynamic URL
	if s.fleet != nil && s.fleet.IsConfigured() {
		s.fleet.RefreshIfStale(context.Background())
		url := s.fleet.GetOllamaURL()
		if url != "" {
			return url
		}
	}
	// Fall back to static config
	return s.cfg.RemoteOllamaURL
}

// IsFleetConfigured returns true if fleet API is configured
func (s *Scaler) IsFleetConfigured() bool {
	return s.fleet != nil && s.fleet.IsConfigured()
}

// GetFleetWorkerCount returns the number of fleet workers
func (s *Scaler) GetFleetWorkerCount() int {
	if s.fleet == nil {
		return 0
	}
	return len(s.fleet.GetGPUWorkers())
}
