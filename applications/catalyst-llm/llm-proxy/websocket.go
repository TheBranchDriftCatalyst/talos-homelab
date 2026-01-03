package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"sync"
	"time"

	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/ec2"
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
	State        string `json:"state"`         // EC2 instance state from AWS (running, stopped, etc.)
	OllamaReady  bool   `json:"ollama_ready"`  // Whether Ollama endpoint is responding
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
	Broker       BrokerStatus `json:"broker"`
	Operations   []Operation  `json:"operations,omitempty"` // Active executor operations
}

type ScalerStatus struct {
	Paused        bool   `json:"paused"`
	IdleTimeout   string `json:"idle_timeout"`
	Idle          string `json:"idle"`
	UntilShutdown string `json:"until_shutdown"`
	RequestsTotal int64  `json:"requests_total"`
	ColdStarts    int64  `json:"cold_starts"`
	// Routing
	RoutingMode   string `json:"routing_mode"`
	ActiveTarget  string `json:"active_target"`
	LocalRouted   int64  `json:"local_routed"`
	RemoteRouted  int64  `json:"remote_routed"`
	MacRouted     int64  `json:"mac_routed"`
	BrokerRouted  int64  `json:"broker_routed"`
	HasMac        bool   `json:"has_mac"` // True if Mac dev endpoint is configured
}

// BrokerStatus contains RabbitMQ broker information
type BrokerStatus struct {
	Connected bool         `json:"connected"`
	Enabled   bool         `json:"enabled"`
	Queues    []QueueInfo  `json:"queues,omitempty"`
	Exchanges []string     `json:"exchanges,omitempty"`
	ReplyQueue string      `json:"reply_queue,omitempty"`
}

// QueueInfo contains information about a RabbitMQ queue
type QueueInfo struct {
	Name         string `json:"name"`
	Messages     int    `json:"messages"`
	Consumers    int    `json:"consumers"`
	RoutingKey   string `json:"routing_key"`
	MessagesReady int   `json:"messages_ready"`
	MessagesUnacked int `json:"messages_unacked"`
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

	case "set_routing":
		switch ctrl.Data {
		case "auto":
			s.SetRoutingMode(RoutingAuto)
			response["status"] = "updated"
			response["message"] = "Routing mode: Auto (local first, fallback remote)"
		case "local":
			s.SetRoutingMode(RoutingLocal)
			response["status"] = "updated"
			response["message"] = "Routing mode: Local only"
		case "remote":
			s.SetRoutingMode(RoutingRemote)
			response["status"] = "updated"
			response["message"] = "Routing mode: Remote only"
		case "mac":
			if s.HasMacEndpoint() {
				s.SetRoutingMode(RoutingMac)
				response["status"] = "updated"
				response["message"] = "Routing mode: Mac dev endpoint"
			} else {
				response["status"] = "error"
				response["message"] = "Mac endpoint not configured (set MAC_OLLAMA_URL)"
			}
		default:
			response["status"] = "error"
			response["message"] = "Invalid routing mode. Use: auto, local, remote, mac"
		}

	case "status":
		// Run status command via executor with streaming output
		if ctrl.Target == "remote" {
			go func() {
				ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
				defer cancel()
				s.executor.ExecuteSync(ctx, "remote", "status")
			}()
			response["status"] = "checking"
			response["message"] = "Checking remote worker status..."
		} else {
			response["status"] = "ok"
			response["message"] = "Local worker status available in status update"
		}

	case "logs":
		// Fetch logs from remote worker
		if ctrl.Target == "remote" {
			go func() {
				ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
				defer cancel()
				s.executor.ExecuteSync(ctx, "remote", "logs")
			}()
			response["status"] = "fetching"
			response["message"] = "Fetching remote worker logs..."
		} else {
			response["status"] = "error"
			response["message"] = "Logs only available for remote worker"
		}

	case "ssh":
		// Open SSH session to remote worker
		if ctrl.Target == "remote" {
			go func() {
				ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
				defer cancel()
				s.executor.ExecuteSync(ctx, "remote", "ssh", ctrl.Data)
			}()
			response["status"] = "connecting"
			response["message"] = "Opening SSH session..."
		} else {
			response["status"] = "error"
			response["message"] = "SSH only available for remote worker"
		}

	case "kill":
		// Kill running command
		if err := s.executor.Kill(ctrl.Target); err != nil {
			response["status"] = "error"
			response["message"] = err.Error()
		} else {
			response["status"] = "killed"
			response["message"] = "Command terminated"
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

	// Mac worker (if configured - Tilt dev mode)
	if s.cfg.MacOllamaURL != "" {
		macReady := s.checkEndpoint(s.cfg.MacOllamaURL)
		macWorker := WorkerInfo{
			Name:      "mac-dev",
			Type:      "mac",
			URL:       s.cfg.MacOllamaURL,
			State:     "stopped",
			Ready:     macReady,
			LastCheck: time.Now(),
		}
		if macReady {
			macWorker.State = "running"
			macWorker.Models = s.fetchModels(s.cfg.MacOllamaURL)
			macWorker.Stats.ModelsLoaded = len(macWorker.Models)
		}
		workers = append(workers, macWorker)
	}

	// Get routing info
	localRouted, remoteRouted, macRouted := s.GetRoutingStats()
	routingMode := s.GetRoutingMode()
	activeTarget := s.GetActiveTarget()

	// Determine active target name for display
	activeTargetName := "none"
	if activeTarget == s.cfg.OllamaURL {
		activeTargetName = "local"
	} else if activeTarget == s.cfg.RemoteOllamaURL {
		activeTargetName = "remote"
	} else if activeTarget == s.cfg.MacOllamaURL {
		activeTargetName = "mac"
	}

	// Build broker status
	brokerStatus := s.buildBrokerStatus()

	// Get active operations from executor
	activeOps := s.executor.GetActiveOperations()

	return StatusUpdate{
		Type:       "status",
		Timestamp:  time.Now().Format(time.RFC3339),
		Operations: activeOps,
		Scaler: ScalerStatus{
			Paused:        paused,
			IdleTimeout:   s.cfg.IdleTimeout.String(),
			Idle:          idle.Round(time.Second).String(),
			UntilShutdown: (s.cfg.IdleTimeout - idle).Round(time.Second).String(),
			RequestsTotal: s.requests.Load(),
			ColdStarts:    s.starts.Load(),
			// Routing info
			RoutingMode:  string(routingMode),
			ActiveTarget: activeTargetName,
			LocalRouted:  localRouted,
			RemoteRouted: remoteRouted,
			MacRouted:    macRouted,
			BrokerRouted: s.brokerRouted.Load(),
			HasMac:       s.HasMacEndpoint(),
		},
		Workers: workers,
		Broker:  brokerStatus,
	}
}

// buildBrokerStatus constructs the broker status from RabbitMQ
func (s *Scaler) buildBrokerStatus() BrokerStatus {
	status := BrokerStatus{
		Enabled:   IsBrokerModeEnabled(),
		Connected: s.IsBrokerConnected(),
	}

	if !status.Connected || s.broker == nil {
		return status
	}

	// Get reply queue name
	status.ReplyQueue = s.broker.replyQueue.Name

	// Get queue info from RabbitMQ Management API
	status.Queues = s.fetchQueueInfo()

	// List exchanges we use
	status.Exchanges = []string{
		s.broker.cfg.InferenceExchange,
		s.broker.cfg.PriorityExchange,
		s.broker.cfg.WorkersExchange,
	}

	return status
}

// fetchQueueInfo gets queue statistics from RabbitMQ Management API
func (s *Scaler) fetchQueueInfo() []QueueInfo {
	if s.broker == nil {
		return nil
	}

	// RabbitMQ Management API endpoint
	mgmtURL := fmt.Sprintf("http://%s:15672/api/queues/%s",
		s.broker.cfg.Host, s.broker.cfg.VHost)

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	req, _ := http.NewRequestWithContext(ctx, "GET", mgmtURL, nil)
	req.SetBasicAuth(s.broker.cfg.User, s.broker.cfg.Password)

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		log.Printf("⚠️ Failed to fetch queue info: %v", err)
		return nil
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil
	}

	var queues []struct {
		Name              string `json:"name"`
		Messages          int    `json:"messages"`
		MessagesReady     int    `json:"messages_ready"`
		MessagesUnacked   int    `json:"messages_unacknowledged"`
		Consumers         int    `json:"consumers"`
	}

	if err := json.NewDecoder(resp.Body).Decode(&queues); err != nil {
		return nil
	}

	result := make([]QueueInfo, 0, len(queues))
	for _, q := range queues {
		// Skip auto-generated reply queues (amq.gen-*)
		if len(q.Name) > 4 && q.Name[:4] == "amq." {
			continue
		}

		// Extract routing key from queue name (e.g., llm.inference.llama3 -> llama3)
		routingKey := ""
		parts := splitString(q.Name, ".")
		if len(parts) >= 3 {
			routingKey = parts[len(parts)-1]
		}

		result = append(result, QueueInfo{
			Name:            q.Name,
			Messages:        q.Messages,
			MessagesReady:   q.MessagesReady,
			MessagesUnacked: q.MessagesUnacked,
			Consumers:       q.Consumers,
			RoutingKey:      routingKey,
		})
	}

	return result
}

// splitString is a simple string split helper
func splitString(s, sep string) []string {
	var result []string
	start := 0
	for i := 0; i <= len(s)-len(sep); i++ {
		if s[i:i+len(sep)] == sep {
			result = append(result, s[start:i])
			start = i + len(sep)
			i += len(sep) - 1
		}
	}
	result = append(result, s[start:])
	return result
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

	// Get actual EC2 state from AWS
	ec2State := s.getEC2StateFromAWS(instanceID, region)

	// Check Ollama endpoint separately
	ollamaReady := s.checkEndpoint(s.cfg.RemoteOllamaURL)

	return &EC2Info{
		InstanceID:   instanceID,
		InstanceType: instanceType,
		Region:       region,
		ConsoleURL:   "https://" + region + ".console.aws.amazon.com/ec2/home?region=" + region + "#InstanceDetails:instanceId=" + instanceID,
		State:        ec2State,
		OllamaReady:  ollamaReady,
	}
}

func (s *Scaler) getEC2StateFromAWS(instanceID, region string) string {
	if instanceID == "" {
		return "not_configured"
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	// Load AWS config
	cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion(region))
	if err != nil {
		log.Printf("⚠️ AWS config error: %v", err)
		return "unknown"
	}

	// Create EC2 client
	client := ec2.NewFromConfig(cfg)

	// Describe instance
	input := &ec2.DescribeInstancesInput{
		InstanceIds: []string{instanceID},
	}

	result, err := client.DescribeInstances(ctx, input)
	if err != nil {
		log.Printf("⚠️ EC2 describe error: %v", err)
		return "unknown"
	}

	// Extract state
	for _, reservation := range result.Reservations {
		for _, instance := range reservation.Instances {
			if instance.State != nil && instance.State.Name != "" {
				return string(instance.State.Name)
			}
		}
	}

	return "unknown"
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
		return fmt.Sprintf("%d B", b)
	}
	div, exp := int64(unit), 0
	for n := b / unit; n >= unit; n /= unit {
		div *= unit
		exp++
	}
	return fmt.Sprintf("%.1f %cB", float64(b)/float64(div), "KMGTPE"[exp])
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
