// Package fleet provides RabbitMQ consumer for agent state
package fleet

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"sync"
	"time"

	amqp "github.com/rabbitmq/amqp091-go"
)

// RabbitMQConfig holds RabbitMQ connection settings
type RabbitMQConfig struct {
	URL                   string
	VHost                 string
	RegistrationQueue     string
	HeartbeatQueue        string
	ReconnectDelay        time.Duration
	StaleThreshold        time.Duration // Time after which node is marked stale
	DeadThreshold         time.Duration // Time after which node is marked dead
	AutoTerminateOnDead   bool          // If true, send SHUTDOWN command when node is dead
}

// DefaultRabbitMQConfig returns sensible defaults
func DefaultRabbitMQConfig() RabbitMQConfig {
	return RabbitMQConfig{
		URL:                   "amqp://panda:turbopookipanda@rabbitmq.catalyst-llm.svc.cluster.local:5672/agents",
		VHost:                 "agents",
		RegistrationQueue:     "registration.control-plane",
		HeartbeatQueue:        "heartbeat.control-plane",
		ReconnectDelay:        5 * time.Second,
		StaleThreshold:        2 * time.Minute,
		DeadThreshold:         5 * time.Minute,
		AutoTerminateOnDead:   false, // Safe default
	}
}

// RegistrationMessage received from workers
type RegistrationMessage struct {
	Action       string                 `json:"action"` // "register" or "deregister"
	NodeID       string                 `json:"node_id"`
	NodeType     string                 `json:"node_type"`
	NebulaIP     string                 `json:"nebula_ip"`
	PublicIP     string                 `json:"public_ip"`
	Region       string                 `json:"region"`
	AZ           string                 `json:"az"`
	Capabilities map[string]interface{} `json:"capabilities"`
	Timestamp    time.Time              `json:"timestamp"`
}

// HeartbeatMessage received from workers
type HeartbeatMessage struct {
	NodeID    string                 `json:"node_id"`
	Status    string                 `json:"status"` // "healthy", "degraded", "unhealthy"
	Services  map[string]bool        `json:"services"`
	Resources map[string]interface{} `json:"resources"`
	Timestamp time.Time              `json:"timestamp"`
}

// RabbitMQConsumer consumes agent state from RabbitMQ
type RabbitMQConsumer struct {
	config   RabbitMQConfig
	manager  *Manager
	conn     *amqp.Connection
	channel  *amqp.Channel
	mu       sync.RWMutex
	stopChan chan struct{}
	wg       sync.WaitGroup
}

// NewRabbitMQConsumer creates a new RabbitMQ consumer
func NewRabbitMQConsumer(config RabbitMQConfig, manager *Manager) *RabbitMQConsumer {
	return &RabbitMQConsumer{
		config:   config,
		manager:  manager,
		stopChan: make(chan struct{}),
	}
}

// Connect establishes connection to RabbitMQ with retry
func (c *RabbitMQConsumer) Connect(ctx context.Context) error {
	return c.connectWithRetry(ctx)
}

func (c *RabbitMQConsumer) connectWithRetry(ctx context.Context) error {
	for attempt := 1; ; attempt++ {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		err := c.connect()
		if err == nil {
			log.Printf("[RabbitMQ Consumer] Connected successfully on attempt %d", attempt)
			return nil
		}

		backoff := c.config.ReconnectDelay * time.Duration(min(attempt, 6))
		log.Printf("[RabbitMQ Consumer] Connection attempt %d failed: %v. Retrying in %v...", attempt, err, backoff)

		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(backoff):
		}
	}
}

func (c *RabbitMQConsumer) connect() error {
	c.mu.Lock()
	defer c.mu.Unlock()

	conn, err := amqp.Dial(c.config.URL)
	if err != nil {
		return fmt.Errorf("failed to connect to RabbitMQ: %w", err)
	}

	ch, err := conn.Channel()
	if err != nil {
		conn.Close()
		return fmt.Errorf("failed to open channel: %w", err)
	}

	// Set QoS - process one message at a time
	if err := ch.Qos(1, 0, false); err != nil {
		ch.Close()
		conn.Close()
		return fmt.Errorf("failed to set QoS: %w", err)
	}

	c.conn = conn
	c.channel = ch

	// Setup connection close handler for reconnection
	go c.handleReconnect()

	return nil
}

func (c *RabbitMQConsumer) handleReconnect() {
	closeErr := <-c.conn.NotifyClose(make(chan *amqp.Error))
	if closeErr != nil {
		log.Printf("[RabbitMQ Consumer] Connection closed: %v. Attempting reconnect...", closeErr)

		ctx := context.Background()
		if err := c.connectWithRetry(ctx); err != nil {
			log.Printf("[RabbitMQ Consumer] Failed to reconnect: %v", err)
			return
		}

		// Restart consumers after reconnect
		go c.consumeRegistrations(ctx)
		go c.consumeHeartbeats(ctx)
	}
}

// Start begins consuming messages from RabbitMQ
func (c *RabbitMQConsumer) Start(ctx context.Context) error {
	c.wg.Add(3)

	// Start registration consumer
	go c.consumeRegistrations(ctx)

	// Start heartbeat consumer
	go c.consumeHeartbeats(ctx)

	// Start TTL checker
	go c.runTTLChecker(ctx)

	return nil
}

func (c *RabbitMQConsumer) consumeRegistrations(ctx context.Context) {
	defer c.wg.Done()

	c.mu.RLock()
	ch := c.channel
	c.mu.RUnlock()

	if ch == nil {
		log.Printf("[RabbitMQ Consumer] Channel not available for registration consumer")
		return
	}

	msgs, err := ch.Consume(
		c.config.RegistrationQueue,
		"control-plane-registration",
		false, // auto-ack
		false, // exclusive
		false, // no-local
		false, // no-wait
		nil,
	)
	if err != nil {
		log.Printf("[RabbitMQ Consumer] Failed to start registration consumer: %v", err)
		return
	}

	log.Printf("[RabbitMQ Consumer] Started registration consumer")

	for {
		select {
		case <-ctx.Done():
			return
		case <-c.stopChan:
			return
		case msg, ok := <-msgs:
			if !ok {
				log.Printf("[RabbitMQ Consumer] Registration channel closed")
				return
			}

			var regMsg RegistrationMessage
			if err := json.Unmarshal(msg.Body, &regMsg); err != nil {
				log.Printf("[RabbitMQ Consumer] Failed to unmarshal registration: %v", err)
				msg.Nack(false, false)
				continue
			}

			c.handleRegistration(regMsg)
			msg.Ack(false)
		}
	}
}

func (c *RabbitMQConsumer) handleRegistration(msg RegistrationMessage) {
	switch msg.Action {
	case "register":
		log.Printf("[RabbitMQ Consumer] Node registered: %s (%s) at %s", msg.NodeID, msg.NodeType, msg.NebulaIP)

		// Check if node already exists
		existing := c.manager.GetNode(msg.NodeID)
		if existing != nil {
			// Update existing node
			existing.NebulaIP = msg.NebulaIP
			existing.PublicIP = msg.PublicIP
			existing.Region = msg.Region
			existing.AZ = msg.AZ
			existing.SetConnected(true)
		} else {
			// Create new node
			node := NewNodeFromRabbitMQ(msg.NodeID, msg.NodeType)
			node.NebulaIP = msg.NebulaIP
			node.PublicIP = msg.PublicIP
			node.Region = msg.Region
			node.AZ = msg.AZ
			node.SetConnected(true)

			// Set capabilities as labels
			if gpu, ok := msg.Capabilities["gpu"].(bool); ok && gpu {
				node.Labels["gpu"] = "true"
			}

			c.manager.RegisterNode(node)
		}

	case "deregister":
		log.Printf("[RabbitMQ Consumer] Node deregistered: %s", msg.NodeID)
		c.manager.Disconnect(msg.NodeID)
	}
}

func (c *RabbitMQConsumer) consumeHeartbeats(ctx context.Context) {
	defer c.wg.Done()

	c.mu.RLock()
	ch := c.channel
	c.mu.RUnlock()

	if ch == nil {
		log.Printf("[RabbitMQ Consumer] Channel not available for heartbeat consumer")
		return
	}

	msgs, err := ch.Consume(
		c.config.HeartbeatQueue,
		"control-plane-heartbeat",
		false, // auto-ack
		false, // exclusive
		false, // no-local
		false, // no-wait
		nil,
	)
	if err != nil {
		log.Printf("[RabbitMQ Consumer] Failed to start heartbeat consumer: %v", err)
		return
	}

	log.Printf("[RabbitMQ Consumer] Started heartbeat consumer")

	for {
		select {
		case <-ctx.Done():
			return
		case <-c.stopChan:
			return
		case msg, ok := <-msgs:
			if !ok {
				log.Printf("[RabbitMQ Consumer] Heartbeat channel closed")
				return
			}

			var hbMsg HeartbeatMessage
			if err := json.Unmarshal(msg.Body, &hbMsg); err != nil {
				log.Printf("[RabbitMQ Consumer] Failed to unmarshal heartbeat: %v", err)
				msg.Nack(false, false)
				continue
			}

			c.handleHeartbeat(hbMsg)
			msg.Ack(false)
		}
	}
}

func (c *RabbitMQConsumer) handleHeartbeat(msg HeartbeatMessage) {
	node := c.manager.GetNode(msg.NodeID)
	if node == nil {
		// Unknown node - might have registered via gRPC
		log.Printf("[RabbitMQ Consumer] Heartbeat from unknown node: %s", msg.NodeID)
		return
	}

	// Update last seen
	node.Heartbeat()

	// Update health status from heartbeat
	node.mu.Lock()
	node.HealthStatus = msg.Status

	// Store resources for API access
	if node.Metadata == nil {
		node.Metadata = make(map[string]interface{})
	}
	node.Metadata["services"] = msg.Services
	node.Metadata["resources"] = msg.Resources
	node.mu.Unlock()
}

func (c *RabbitMQConsumer) runTTLChecker(ctx context.Context) {
	defer c.wg.Done()

	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-c.stopChan:
			return
		case <-ticker.C:
			c.checkNodeTTLs()
		}
	}
}

func (c *RabbitMQConsumer) checkNodeTTLs() {
	now := time.Now()

	c.manager.mu.RLock()
	nodes := make([]*Node, 0, len(c.manager.nodes))
	for _, node := range c.manager.nodes {
		nodes = append(nodes, node)
	}
	c.manager.mu.RUnlock()

	for _, node := range nodes {
		node.mu.RLock()
		lastSeen := node.LastSeen
		connected := node.Connected
		healthStatus := node.HealthStatus
		node.mu.RUnlock()

		if !connected {
			continue // Already disconnected
		}

		timeSinceLastSeen := now.Sub(lastSeen)

		if timeSinceLastSeen > c.config.DeadThreshold {
			// Node is dead
			log.Printf("[TTL] Node %s is DEAD (no heartbeat for %v)", node.ID, timeSinceLastSeen)
			c.manager.Disconnect(node.ID)

			if c.config.AutoTerminateOnDead {
				log.Printf("[TTL] Auto-terminating node %s", node.ID)
				// Send shutdown command via gRPC if node has active stream
				// The manager will handle this
				c.manager.SendShutdownCommand(node.ID, "TTL expired - auto terminate")
			}
		} else if timeSinceLastSeen > c.config.StaleThreshold {
			// Node is stale
			if healthStatus != "stale" {
				log.Printf("[TTL] Node %s is STALE (no heartbeat for %v)", node.ID, timeSinceLastSeen)
				node.mu.Lock()
				node.HealthStatus = "stale"
				node.mu.Unlock()
			}
		}
	}
}

// Stop gracefully stops the consumer
func (c *RabbitMQConsumer) Stop() error {
	close(c.stopChan)
	c.wg.Wait()

	c.mu.Lock()
	defer c.mu.Unlock()

	if c.channel != nil {
		c.channel.Close()
	}
	if c.conn != nil {
		c.conn.Close()
	}

	return nil
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
