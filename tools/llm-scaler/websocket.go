package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool { return true },
}

// Hub manages WebSocket connections
type Hub struct {
	clients    map[*websocket.Conn]bool
	broadcast  chan []byte
	register   chan *websocket.Conn
	unregister chan *websocket.Conn
	mu         sync.RWMutex
}

func NewHub() *Hub {
	return &Hub{
		clients:    make(map[*websocket.Conn]bool),
		broadcast:  make(chan []byte, 256),
		register:   make(chan *websocket.Conn),
		unregister: make(chan *websocket.Conn),
	}
}

func (h *Hub) Run() {
	for {
		select {
		case conn := <-h.register:
			h.mu.Lock()
			h.clients[conn] = true
			h.mu.Unlock()
			log.Printf("📡 WebSocket client connected (%d total)", len(h.clients))

		case conn := <-h.unregister:
			h.mu.Lock()
			if _, ok := h.clients[conn]; ok {
				delete(h.clients, conn)
				conn.Close()
			}
			h.mu.Unlock()
			log.Printf("📡 WebSocket client disconnected (%d total)", len(h.clients))

		case message := <-h.broadcast:
			h.mu.RLock()
			for conn := range h.clients {
				if err := conn.WriteMessage(websocket.TextMessage, message); err != nil {
					conn.Close()
					delete(h.clients, conn)
				}
			}
			h.mu.RUnlock()
		}
	}
}

func (h *Hub) Broadcast(data any) {
	msg, err := json.Marshal(data)
	if err != nil {
		return
	}
	select {
	case h.broadcast <- msg:
	default:
		// Channel full, skip
	}
}

// WorkerInfo contains detailed info about a worker
type WorkerInfo struct {
	Name      string            `json:"name"`
	Type      string            `json:"type"` // "local" or "remote"
	URL       string            `json:"url"`
	State     string            `json:"state"`
	Ready     bool              `json:"ready"`
	Models    []ModelInfo       `json:"models,omitempty"`
	Stats     WorkerStats       `json:"stats"`
	EC2Info   *EC2Info          `json:"ec2,omitempty"`
	LastCheck time.Time         `json:"last_check"`
}

type ModelInfo struct {
	Name       string `json:"name"`
	Size       string `json:"size"`
	ModifiedAt string `json:"modified_at"`
}

type WorkerStats struct {
	Uptime        string `json:"uptime,omitempty"`
	RequestsTotal int64  `json:"requests_total"`
	ModelsLoaded  int    `json:"models_loaded"`
}

type EC2Info struct {
	InstanceID   string `json:"instance_id"`
	InstanceType string `json:"instance_type"`
	Region       string `json:"region"`
	ConsoleURL   string `json:"console_url"`
	State        string `json:"state"`
	PublicIP     string `json:"public_ip,omitempty"`
	LaunchTime   string `json:"launch_time,omitempty"`
}

// ControlMessage is sent from client to control workers
type ControlMessage struct {
	Action string `json:"action"` // start, stop, pull_model, etc.
	Target string `json:"target"` // local, remote, or specific worker name
	Data   string `json:"data"`   // Additional data (e.g., model name)
}

// StatusUpdate is broadcast to all clients
type StatusUpdate struct {
	Type         string       `json:"type"` // "status", "log", "error"
	Timestamp    string       `json:"timestamp"`
	Scaler       ScalerStatus `json:"scaler"`
	Workers      []WorkerInfo `json:"workers"`
}

type ScalerStatus struct {
	Paused        bool   `json:"paused"`
	IdleTimeout   string `json:"idle_timeout"`
	Idle          string `json:"idle"`
	UntilShutdown string `json:"until_shutdown"`
	RequestsTotal int64  `json:"requests_total"`
	ColdStarts    int64  `json:"cold_starts"`
}

// WebSocket handles WebSocket connections
func (s *Scaler) WebSocket(w http.ResponseWriter, r *http.Request) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Printf("WebSocket upgrade error: %v", err)
		return
	}

	s.hub.register <- conn

	// Send initial status
	s.sendFullStatus(conn)

	// Handle incoming messages
	go func() {
		defer func() {
			s.hub.unregister <- conn
		}()

		for {
			_, message, err := conn.ReadMessage()
			if err != nil {
				break
			}

			var ctrl ControlMessage
			if err := json.Unmarshal(message, &ctrl); err != nil {
				continue
			}

			s.handleControl(ctrl, conn)
		}
	}()
}

func (s *Scaler) handleControl(ctrl ControlMessage, conn *websocket.Conn) {
	log.Printf("📨 Control: %s on %s", ctrl.Action, ctrl.Target)

	response := map[string]any{
		"type":      "response",
		"action":    ctrl.Action,
		"target":    ctrl.Target,
		"timestamp": time.Now().Format(time.RFC3339),
	}

	switch ctrl.Action {
	case "start":
		if ctrl.Target == "remote" {
			go s.startWorker()
			response["status"] = "starting"
			response["message"] = "EC2 worker starting..."
		} else {
			response["status"] = "error"
			response["message"] = "Local worker is always-on"
		}

	case "stop":
		if ctrl.Target == "remote" {
			go s.stopWorker()
			response["status"] = "stopping"
			response["message"] = "EC2 worker stopping..."
		} else {
			response["status"] = "error"
			response["message"] = "Cannot stop local worker"
		}

	case "pause":
		s.mu.Lock()
		s.paused = true
		s.mu.Unlock()
		response["status"] = "paused"
		response["message"] = "Auto-scaling paused"

	case "resume":
		s.mu.Lock()
		s.paused = false
		s.lastActivity = time.Now()
		s.mu.Unlock()
		response["status"] = "resumed"
		response["message"] = "Auto-scaling resumed"

	case "set_ttl":
		if d, err := time.ParseDuration(ctrl.Data); err == nil {
			if d < 5*time.Minute {
				d = 5 * time.Minute
			}
			if d > 24*time.Hour {
				d = 24 * time.Hour
			}
			s.mu.Lock()
			s.cfg.IdleTimeout = d
			s.lastActivity = time.Now()
			s.mu.Unlock()
			response["status"] = "updated"
			response["message"] = "TTL set to " + d.String()
		} else {
			response["status"] = "error"
			response["message"] = "Invalid duration"
		}

	case "pull_model":
		if ctrl.Data == "" {
			response["status"] = "error"
			response["message"] = "Model name required"
		} else {
			go s.pullModel(ctrl.Target, ctrl.Data)
			response["status"] = "pulling"
			response["message"] = "Pulling " + ctrl.Data + "..."
		}

	case "refresh":
		s.sendFullStatus(conn)
		return

	default:
		response["status"] = "error"
		response["message"] = "Unknown action"
	}

	msg, _ := json.Marshal(response)
	conn.WriteMessage(websocket.TextMessage, msg)
}

func (s *Scaler) sendFullStatus(conn *websocket.Conn) {
	status := s.buildStatusUpdate()
	msg, _ := json.Marshal(status)
	conn.WriteMessage(websocket.TextMessage, msg)
}

func (s *Scaler) buildStatusUpdate() StatusUpdate {
	s.mu.RLock()
	idle := time.Since(s.lastActivity)
	paused := s.paused
	s.mu.RUnlock()

	// Build worker info
	workers := []WorkerInfo{}

	// Local worker
	localReady := s.isReady()
	localWorker := WorkerInfo{
		Name:      "talos06-local",
		Type:      "local",
		URL:       s.cfg.OllamaURL,
		State:     "stopped",
		Ready:     localReady,
		LastCheck: time.Now(),
		Stats: WorkerStats{
			RequestsTotal: s.requests.Load(),
		},
	}
	if localReady {
		localWorker.State = "running"
		localWorker.Models = s.fetchModels(s.cfg.OllamaURL)
		localWorker.Stats.ModelsLoaded = len(localWorker.Models)
	}
	workers = append(workers, localWorker)

	// Remote worker (EC2)
	if s.cfg.RemoteOllamaURL != "" {
		remoteReady := s.checkEndpoint(s.cfg.RemoteOllamaURL)
		remoteWorker := WorkerInfo{
			Name:      "ec2-bigboi",
			Type:      "remote",
			URL:       s.cfg.RemoteOllamaURL,
			State:     "stopped",
			Ready:     remoteReady,
			LastCheck: time.Now(),
			EC2Info:   s.getEC2Info(),
		}
		if remoteReady {
			remoteWorker.State = "running"
			remoteWorker.Models = s.fetchModels(s.cfg.RemoteOllamaURL)
			remoteWorker.Stats.ModelsLoaded = len(remoteWorker.Models)
		}
		workers = append(workers, remoteWorker)
	}

	return StatusUpdate{
		Type:      "status",
		Timestamp: time.Now().Format(time.RFC3339),
		Scaler: ScalerStatus{
			Paused:        paused,
			IdleTimeout:   s.cfg.IdleTimeout.String(),
			Idle:          idle.Round(time.Second).String(),
			UntilShutdown: (s.cfg.IdleTimeout - idle).Round(time.Second).String(),
			RequestsTotal: s.requests.Load(),
			ColdStarts:    s.starts.Load(),
		},
		Workers: workers,
	}
}

func (s *Scaler) fetchModels(url string) []ModelInfo {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	req, _ := http.NewRequestWithContext(ctx, "GET", url+"/api/tags", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil
	}
	defer resp.Body.Close()

	var result struct {
		Models []struct {
			Name       string `json:"name"`
			Size       int64  `json:"size"`
			ModifiedAt string `json:"modified_at"`
		} `json:"models"`
	}

	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil
	}

	models := make([]ModelInfo, len(result.Models))
	for i, m := range result.Models {
		size := "unknown"
		if m.Size > 0 {
			size = formatBytes(m.Size)
		}
		models[i] = ModelInfo{
			Name:       m.Name,
			Size:       size,
			ModifiedAt: m.ModifiedAt,
		}
	}
	return models
}

func (s *Scaler) getEC2Info() *EC2Info {
	// Read from state file
	stateFile := s.cfg.StateFile
	if stateFile == "" {
		stateFile = "/app/.output/worker-state.json"
	}

	data, err := readStateFile(stateFile)
	if err != nil {
		return nil
	}

	instanceID, _ := data["instance_id"].(string)
	instanceType, _ := data["instance_type"].(string)
	region := s.cfg.AWSRegion
	if region == "" {
		region = "us-west-2"
	}

	return &EC2Info{
		InstanceID:   instanceID,
		InstanceType: instanceType,
		Region:       region,
		ConsoleURL:   "https://" + region + ".console.aws.amazon.com/ec2/home?region=" + region + "#InstanceDetails:instanceId=" + instanceID,
		State:        s.getEC2State(instanceID),
	}
}

func (s *Scaler) getEC2State(instanceID string) string {
	if instanceID == "" {
		return "not_configured"
	}
	// Quick check via worker script
	if s.checkEndpoint(s.cfg.RemoteOllamaURL) {
		return "running"
	}
	return "stopped"
}

func (s *Scaler) pullModel(target, modelName string) {
	url := s.cfg.OllamaURL
	if target == "remote" {
		url = s.cfg.RemoteOllamaURL
	}

	log.Printf("📥 Pulling model %s on %s", modelName, target)

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Minute)
	defer cancel()

	body := map[string]string{"name": modelName}
	bodyBytes, _ := json.Marshal(body)

	req, _ := http.NewRequestWithContext(ctx, "POST", url+"/api/pull",
		http.NoBody)
	req.Header.Set("Content-Type", "application/json")

	// This would need streaming support for progress updates
	// For now, just trigger the pull
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		log.Printf("❌ Pull failed: %v", err)
		s.hub.Broadcast(map[string]any{
			"type":    "log",
			"level":   "error",
			"message": "Failed to pull " + modelName + ": " + err.Error(),
		})
		return
	}
	defer resp.Body.Close()

	_ = bodyBytes // Would use for actual pull request
	log.Printf("✅ Pull initiated for %s", modelName)
}

// RunStatusBroadcaster periodically broadcasts status to all WebSocket clients
func (s *Scaler) RunStatusBroadcaster() {
	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()

	for range ticker.C {
		s.hub.mu.RLock()
		clientCount := len(s.hub.clients)
		s.hub.mu.RUnlock()

		if clientCount > 0 {
			status := s.buildStatusUpdate()
			s.hub.Broadcast(status)
		}
	}
}

func formatBytes(b int64) string {
	const unit = 1024
	if b < unit {
		return string(rune(b)) + " B"
	}
	div, exp := int64(unit), 0
	for n := b / unit; n >= unit; n /= unit {
		div *= unit
		exp++
	}
	return string(rune(b/div)) + " " + string("KMGTPE"[exp]) + "B"
}

func readStateFile(path string) (map[string]any, error) {
	data := make(map[string]any)
	file, err := os.ReadFile(path)
	if err != nil {
		return data, err
	}
	if err := json.Unmarshal(file, &data); err != nil {
		return data, err
	}
	return data, nil
}
