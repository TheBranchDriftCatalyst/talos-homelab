// broker.go - RabbitMQ message broker for LLM request routing
//
// Architecture:
//   Client → LLM Proxy → RabbitMQ → Worker Consumers
//                           ↑
//                     Reply Queue
//
// Request Flow:
//   1. HTTP request arrives at proxy
//   2. Proxy publishes to llm.inference exchange with routing key
//   3. Worker consumes from model-specific queue
//   4. Worker processes and publishes response to reply queue
//   5. Proxy returns response to client
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"sync"
	"time"

	amqp "github.com/rabbitmq/amqp091-go"
)

// BrokerConfig holds RabbitMQ connection settings
type BrokerConfig struct {
	Host     string
	Port     string
	VHost    string
	User     string
	Password string
	// Exchange names
	InferenceExchange string
	PriorityExchange  string
	WorkersExchange   string
}

// Broker manages RabbitMQ connections and message routing
type Broker struct {
	cfg        BrokerConfig
	conn       *amqp.Connection
	channel    *amqp.Channel
	replyQueue amqp.Queue

	// Pending requests waiting for responses
	mu       sync.RWMutex
	pending  map[string]chan *InferenceResponse
	shutdown chan struct{}
}

// InferenceRequest represents an LLM inference request
type InferenceRequest struct {
	ID        string            `json:"id"`         // Correlation ID
	Model     string            `json:"model"`      // Target model name
	Prompt    string            `json:"prompt"`     // Input prompt
	Stream    bool              `json:"stream"`     // Streaming response
	Options   map[string]any    `json:"options"`    // Model options
	Priority  int               `json:"priority"`   // 0-10, higher = more urgent
	ReplyTo   string            `json:"reply_to"`   // Reply queue name
	Timestamp time.Time         `json:"timestamp"`  // Request timestamp
	Headers   map[string]string `json:"headers"`    // Custom routing headers
}

// InferenceResponse represents an LLM inference response
type InferenceResponse struct {
	ID        string    `json:"id"`         // Correlation ID (matches request)
	Model     string    `json:"model"`      // Model that processed
	Response  string    `json:"response"`   // Generated text
	Done      bool      `json:"done"`       // Stream complete
	Error     string    `json:"error"`      // Error message if failed
	WorkerID  string    `json:"worker_id"`  // Worker that processed
	Timestamp time.Time `json:"timestamp"`  // Response timestamp
	Duration  int64     `json:"duration"`   // Processing time in ms
}

// WorkerHeartbeat represents a worker status update
type WorkerHeartbeat struct {
	WorkerID   string    `json:"worker_id"`
	Models     []string  `json:"models"`      // Available models
	Status     string    `json:"status"`      // ready, busy, draining
	QueueDepth int       `json:"queue_depth"` // Pending requests
	GPUMemory  int64     `json:"gpu_memory"`  // Available VRAM in bytes
	Timestamp  time.Time `json:"timestamp"`
}

// NewBroker creates a new RabbitMQ broker instance
func NewBroker(cfg BrokerConfig) (*Broker, error) {
	b := &Broker{
		cfg:      cfg,
		pending:  make(map[string]chan *InferenceResponse),
		shutdown: make(chan struct{}),
	}

	if err := b.connect(); err != nil {
		return nil, err
	}

	return b, nil
}

// connect establishes connection to RabbitMQ
func (b *Broker) connect() error {
	url := fmt.Sprintf("amqp://%s:%s@%s:%s/%s",
		b.cfg.User, b.cfg.Password,
		b.cfg.Host, b.cfg.Port, b.cfg.VHost)

	var err error
	b.conn, err = amqp.Dial(url)
	if err != nil {
		return fmt.Errorf("failed to connect to RabbitMQ: %w", err)
	}

	b.channel, err = b.conn.Channel()
	if err != nil {
		return fmt.Errorf("failed to open channel: %w", err)
	}

	// Declare exclusive reply queue for this proxy instance
	b.replyQueue, err = b.channel.QueueDeclare(
		"",    // Auto-generated name
		false, // Non-durable
		true,  // Auto-delete
		true,  // Exclusive
		false, // No-wait
		nil,   // Args
	)
	if err != nil {
		return fmt.Errorf("failed to declare reply queue: %w", err)
	}

	log.Printf("📨 Broker connected, reply queue: %s", b.replyQueue.Name)

	// Start consuming replies
	go b.consumeReplies()

	return nil
}

// consumeReplies listens for responses and dispatches to waiting requests
func (b *Broker) consumeReplies() {
	msgs, err := b.channel.Consume(
		b.replyQueue.Name, // Queue
		"",                // Consumer tag
		true,              // Auto-ack
		true,              // Exclusive
		false,             // No-local
		false,             // No-wait
		nil,               // Args
	)
	if err != nil {
		log.Printf("❌ Failed to consume replies: %v", err)
		return
	}

	for {
		select {
		case msg, ok := <-msgs:
			if !ok {
				log.Printf("Reply channel closed")
				return
			}
			b.handleReply(msg)
		case <-b.shutdown:
			return
		}
	}
}

// handleReply processes a response message
func (b *Broker) handleReply(msg amqp.Delivery) {
	var resp InferenceResponse
	if err := json.Unmarshal(msg.Body, &resp); err != nil {
		log.Printf("⚠️ Invalid reply message: %v", err)
		return
	}

	b.mu.RLock()
	ch, ok := b.pending[resp.ID]
	b.mu.RUnlock()

	if ok {
		select {
		case ch <- &resp:
		default:
			log.Printf("⚠️ Reply channel full for %s", resp.ID)
		}
	} else {
		log.Printf("⚠️ No pending request for correlation ID: %s", resp.ID)
	}
}

// Publish sends an inference request to the broker
func (b *Broker) Publish(ctx context.Context, req *InferenceRequest) (*InferenceResponse, error) {
	// Create response channel
	respCh := make(chan *InferenceResponse, 1)

	b.mu.Lock()
	b.pending[req.ID] = respCh
	b.mu.Unlock()

	defer func() {
		b.mu.Lock()
		delete(b.pending, req.ID)
		b.mu.Unlock()
	}()

	// Determine routing key based on model
	routingKey := determineRoutingKey(req.Model)

	// Set reply queue
	req.ReplyTo = b.replyQueue.Name

	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal request: %w", err)
	}

	// Determine exchange based on priority
	// Priority 0 = not set (use default), 1-4 = low, 5 = normal, 6-10 = high
	exchange := b.cfg.InferenceExchange
	if req.Priority > 5 {
		exchange = b.cfg.PriorityExchange
		routingKey = "high"
	} else if req.Priority > 0 && req.Priority < 5 {
		// Only use priority exchange if priority was explicitly set
		exchange = b.cfg.PriorityExchange
		routingKey = "low"
	}
	// Priority 0 or 5 uses the default inference exchange

	err = b.channel.PublishWithContext(ctx,
		exchange,   // Exchange
		routingKey, // Routing key
		false,      // Mandatory
		false,      // Immediate
		amqp.Publishing{
			ContentType:   "application/json",
			CorrelationId: req.ID,
			ReplyTo:       b.replyQueue.Name,
			Body:          body,
			Timestamp:     time.Now(),
			Expiration:    "300000", // 5 minute TTL
		},
	)
	if err != nil {
		return nil, fmt.Errorf("failed to publish: %w", err)
	}

	// Wait for response
	select {
	case resp := <-respCh:
		if resp.Error != "" {
			return resp, fmt.Errorf("worker error: %s", resp.Error)
		}
		return resp, nil
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

// PublishHeartbeat sends a worker heartbeat
func (b *Broker) PublishHeartbeat(ctx context.Context, hb *WorkerHeartbeat) error {
	body, err := json.Marshal(hb)
	if err != nil {
		return err
	}

	return b.channel.PublishWithContext(ctx,
		b.cfg.WorkersExchange, // Exchange
		"",                    // Routing key (fanout ignores)
		false,                 // Mandatory
		false,                 // Immediate
		amqp.Publishing{
			ContentType: "application/json",
			Body:        body,
			Timestamp:   time.Now(),
		},
	)
}

// Close cleanly shuts down the broker connection
func (b *Broker) Close() error {
	close(b.shutdown)

	if b.channel != nil {
		b.channel.Close()
	}
	if b.conn != nil {
		return b.conn.Close()
	}
	return nil
}

// IsConnected checks if broker is connected
func (b *Broker) IsConnected() bool {
	return b.conn != nil && !b.conn.IsClosed()
}

// determineRoutingKey maps model names to routing keys
// Returns just the base model family name for clean routing
func determineRoutingKey(model string) string {
	switch {
	case containsAny(model, "llama3", "llama-3", "llama3.2", "llama3.1"):
		return "llama3"
	case containsAny(model, "mistral"):
		return "mistral"
	case containsAny(model, "qwen"):
		return "qwen"
	case containsAny(model, "dolphin"):
		return "dolphin"
	default:
		return "default" // Unknown models go to default queue
	}
}

func containsAny(s string, substrs ...string) bool {
	for _, sub := range substrs {
		if len(s) >= len(sub) {
			for i := 0; i <= len(s)-len(sub); i++ {
				if s[i:i+len(sub)] == sub {
					return true
				}
			}
		}
	}
	return false
}

// LoadBrokerConfig loads broker configuration from environment
func LoadBrokerConfig() BrokerConfig {
	return BrokerConfig{
		Host:              env("RABBITMQ_HOST", "rabbitmq.catalyst-llm.svc.cluster.local"),
		Port:              env("RABBITMQ_PORT", "5672"),
		VHost:             env("RABBITMQ_VHOST", "llm"),
		User:              env("RABBITMQ_USER", "llmproxy"),
		Password:          env("RABBITMQ_PASSWORD", ""),
		InferenceExchange: env("RABBITMQ_INFERENCE_EXCHANGE", "llm.inference"),
		PriorityExchange:  env("RABBITMQ_PRIORITY_EXCHANGE", "llm.priority"),
		WorkersExchange:   env("RABBITMQ_WORKERS_EXCHANGE", "llm.workers"),
	}
}

// IsBrokerModeEnabled checks if broker mode is enabled
func IsBrokerModeEnabled() bool {
	return env("BROKER_MODE", "false") == "true"
}
