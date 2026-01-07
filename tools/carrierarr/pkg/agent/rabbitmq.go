// Package agent provides RabbitMQ publisher for worker registration and heartbeats
package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"sync"
	"time"

	amqp "github.com/rabbitmq/amqp091-go"
	pb "github.com/thebranchdriftcatalyst/carrierarr/pkg/proto"
)

// RabbitMQConfig holds RabbitMQ connection settings
type RabbitMQConfig struct {
	URL                  string
	VHost                string
	RegistrationExchange string
	HeartbeatExchange    string
	HeartbeatInterval    time.Duration
	ReconnectDelay       time.Duration
}

// DefaultRabbitMQConfig returns sensible defaults
func DefaultRabbitMQConfig() RabbitMQConfig {
	return RabbitMQConfig{
		URL:                  "amqp://panda:turbopookipanda@rabbitmq.catalyst-llm.svc.cluster.local:5672/agents",
		VHost:                "agents",
		RegistrationExchange: "agents.registration",
		HeartbeatExchange:    "agents.heartbeat",
		HeartbeatInterval:    30 * time.Second,
		ReconnectDelay:       5 * time.Second,
	}
}

// RegistrationMessage is published when a worker registers or deregisters
type RegistrationMessage struct {
	Action      string                 `json:"action"` // "register" or "deregister"
	NodeID      string                 `json:"node_id"`
	NodeType    string                 `json:"node_type"`
	NebulaIP    string                 `json:"nebula_ip"`
	PublicIP    string                 `json:"public_ip"`
	Region      string                 `json:"region"`
	AZ          string                 `json:"az"`
	Capabilities map[string]interface{} `json:"capabilities"`
	Timestamp   time.Time              `json:"timestamp"`
}

// HeartbeatMessage is published periodically to indicate worker health
type HeartbeatMessage struct {
	NodeID    string                 `json:"node_id"`
	Status    string                 `json:"status"` // "healthy", "degraded", "unhealthy"
	Services  map[string]bool        `json:"services"`
	Resources map[string]interface{} `json:"resources"`
	Timestamp time.Time              `json:"timestamp"`
}

// RabbitMQPublisher publishes worker state to RabbitMQ
type RabbitMQPublisher struct {
	config     RabbitMQConfig
	conn       *amqp.Connection
	channel    *amqp.Channel
	nodeID     string
	nodeType   string
	nebulaIP   string
	publicIP   string
	region     string
	az         string
	mu         sync.RWMutex
	connected  bool
	statusFunc func() *pb.NodeStatus // function to get current status
	stopChan   chan struct{}
	wg         sync.WaitGroup
}

// NewRabbitMQPublisher creates a new RabbitMQ publisher
func NewRabbitMQPublisher(config RabbitMQConfig, nodeID, nodeType, nebulaIP, publicIP, region, az string) *RabbitMQPublisher {
	return &RabbitMQPublisher{
		config:   config,
		nodeID:   nodeID,
		nodeType: nodeType,
		nebulaIP: nebulaIP,
		publicIP: publicIP,
		region:   region,
		az:       az,
		stopChan: make(chan struct{}),
	}
}

// SetStatusFunc sets the function used to get current node status for heartbeats
func (p *RabbitMQPublisher) SetStatusFunc(fn func() *pb.NodeStatus) {
	p.statusFunc = fn
}

// Connect establishes connection to RabbitMQ with retry
func (p *RabbitMQPublisher) Connect(ctx context.Context) error {
	return p.connectWithRetry(ctx)
}

func (p *RabbitMQPublisher) connectWithRetry(ctx context.Context) error {
	for attempt := 1; ; attempt++ {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		err := p.connect()
		if err == nil {
			log.Printf("[RabbitMQ] Connected successfully on attempt %d", attempt)
			return nil
		}

		backoff := p.config.ReconnectDelay * time.Duration(min(attempt, 6))
		log.Printf("[RabbitMQ] Connection attempt %d failed: %v. Retrying in %v...", attempt, err, backoff)

		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(backoff):
		}
	}
}

func (p *RabbitMQPublisher) connect() error {
	p.mu.Lock()
	defer p.mu.Unlock()

	conn, err := amqp.Dial(p.config.URL)
	if err != nil {
		return fmt.Errorf("failed to connect to RabbitMQ: %w", err)
	}

	ch, err := conn.Channel()
	if err != nil {
		conn.Close()
		return fmt.Errorf("failed to open channel: %w", err)
	}

	p.conn = conn
	p.channel = ch
	p.connected = true

	// Setup connection close handler for reconnection
	go p.handleReconnect()

	return nil
}

func (p *RabbitMQPublisher) handleReconnect() {
	closeErr := <-p.conn.NotifyClose(make(chan *amqp.Error))
	if closeErr != nil {
		log.Printf("[RabbitMQ] Connection closed: %v. Attempting reconnect...", closeErr)
		p.mu.Lock()
		p.connected = false
		p.mu.Unlock()

		ctx := context.Background()
		if err := p.connectWithRetry(ctx); err != nil {
			log.Printf("[RabbitMQ] Failed to reconnect: %v", err)
		}
	}
}

// Register publishes a registration message
func (p *RabbitMQPublisher) Register(ctx context.Context) error {
	msg := RegistrationMessage{
		Action:   "register",
		NodeID:   p.nodeID,
		NodeType: p.nodeType,
		NebulaIP: p.nebulaIP,
		PublicIP: p.publicIP,
		Region:   p.region,
		AZ:       p.az,
		Capabilities: map[string]interface{}{
			"gpu": p.nodeType == "gpu-worker",
		},
		Timestamp: time.Now().UTC(),
	}

	return p.publish(ctx, p.config.RegistrationExchange, "register", msg)
}

// Deregister publishes a deregistration message
func (p *RabbitMQPublisher) Deregister(ctx context.Context) error {
	msg := RegistrationMessage{
		Action:    "deregister",
		NodeID:    p.nodeID,
		NodeType:  p.nodeType,
		Timestamp: time.Now().UTC(),
	}

	return p.publish(ctx, p.config.RegistrationExchange, "deregister", msg)
}

// SendHeartbeat publishes a heartbeat message
func (p *RabbitMQPublisher) SendHeartbeat(ctx context.Context) error {
	status := "healthy"
	services := make(map[string]bool)
	resources := make(map[string]interface{})

	// Get current status if function is set
	if p.statusFunc != nil {
		result := p.statusFunc()
		if result != nil {
			// Map protobuf health state to string
			switch result.Health {
			case pb.HealthState_HEALTH_STATE_HEALTHY:
				status = "healthy"
			case pb.HealthState_HEALTH_STATE_DEGRADED:
				status = "degraded"
			case pb.HealthState_HEALTH_STATE_UNHEALTHY:
				status = "unhealthy"
			default:
				status = "unknown"
			}

			// Map service statuses
			if result.Nebula != nil {
				services["nebula"] = result.Nebula.State == pb.ServiceState_SERVICE_STATE_RUNNING
			}
			if result.K3S != nil {
				services["k3s"] = result.K3S.State == pb.ServiceState_SERVICE_STATE_RUNNING
			}
			if result.Ollama != nil {
				services["ollama"] = result.Ollama.State == pb.ServiceState_SERVICE_STATE_RUNNING
			}
			if result.Liqo != nil {
				services["liqo"] = result.Liqo.State == pb.ServiceState_SERVICE_STATE_RUNNING
			}

			// Map resource usage
			if result.Resources != nil {
				resources["memory_total_mb"] = result.Resources.MemoryTotalMb
				resources["memory_used_mb"] = result.Resources.MemoryUsedMb
				resources["cpu_percent"] = result.Resources.CpuPercent
			}

			// Map GPU status
			if len(result.Gpus) > 0 {
				gpuInfo := make([]map[string]interface{}, len(result.Gpus))
				for i, gpu := range result.Gpus {
					gpuInfo[i] = map[string]interface{}{
						"index":        gpu.Index,
						"name":         gpu.Name,
						"memory_used":  gpu.MemoryUsedMb,
						"memory_total": gpu.MemoryTotalMb,
						"utilization":  gpu.UtilizationPercent,
						"temperature":  gpu.TemperatureC,
					}
				}
				resources["gpus"] = gpuInfo
			}

			// Map loaded models
			if len(result.LoadedModels) > 0 {
				modelNames := make([]string, len(result.LoadedModels))
				for i, model := range result.LoadedModels {
					modelNames[i] = model.Name
				}
				resources["models_loaded"] = modelNames
			}
		}
	}

	msg := HeartbeatMessage{
		NodeID:    p.nodeID,
		Status:    status,
		Services:  services,
		Resources: resources,
		Timestamp: time.Now().UTC(),
	}

	return p.publish(ctx, p.config.HeartbeatExchange, "", msg)
}

func (p *RabbitMQPublisher) publish(ctx context.Context, exchange, routingKey string, msg interface{}) error {
	p.mu.RLock()
	if !p.connected {
		p.mu.RUnlock()
		return fmt.Errorf("not connected to RabbitMQ")
	}
	ch := p.channel
	p.mu.RUnlock()

	body, err := json.Marshal(msg)
	if err != nil {
		return fmt.Errorf("failed to marshal message: %w", err)
	}

	err = ch.PublishWithContext(ctx, exchange, routingKey, false, false, amqp.Publishing{
		ContentType:  "application/json",
		DeliveryMode: amqp.Persistent,
		Timestamp:    time.Now(),
		Body:         body,
	})
	if err != nil {
		return fmt.Errorf("failed to publish message: %w", err)
	}

	return nil
}

// StartHeartbeatLoop starts the periodic heartbeat publisher
func (p *RabbitMQPublisher) StartHeartbeatLoop(ctx context.Context) {
	p.wg.Add(1)
	go func() {
		defer p.wg.Done()
		ticker := time.NewTicker(p.config.HeartbeatInterval)
		defer ticker.Stop()

		for {
			select {
			case <-ctx.Done():
				return
			case <-p.stopChan:
				return
			case <-ticker.C:
				if err := p.SendHeartbeat(ctx); err != nil {
					log.Printf("[RabbitMQ] Failed to send heartbeat: %v", err)
				}
			}
		}
	}()
}

// Stop gracefully stops the publisher
func (p *RabbitMQPublisher) Stop(ctx context.Context) error {
	close(p.stopChan)
	p.wg.Wait()

	// Send deregistration
	if err := p.Deregister(ctx); err != nil {
		log.Printf("[RabbitMQ] Failed to deregister: %v", err)
	}

	p.mu.Lock()
	defer p.mu.Unlock()

	if p.channel != nil {
		p.channel.Close()
	}
	if p.conn != nil {
		p.conn.Close()
	}
	p.connected = false

	return nil
}

// IsConnected returns the current connection status
func (p *RabbitMQPublisher) IsConnected() bool {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.connected
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
