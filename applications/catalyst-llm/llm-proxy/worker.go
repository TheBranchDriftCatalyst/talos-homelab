// worker.go - RabbitMQ consumer for Ollama inference workers
//
// This runs as a sidecar alongside Ollama, consuming inference requests
// from RabbitMQ and forwarding them to the local Ollama instance.
//
// Usage:
//   LLM_WORKER_MODE=true ./llm-proxy
//
// Architecture:
//   RabbitMQ Queue → Worker Consumer → Ollama API → Reply Queue
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	amqp "github.com/rabbitmq/amqp091-go"
)

// WorkerConfig holds worker configuration
type WorkerConfig struct {
	WorkerID    string
	OllamaURL   string
	Models      []string // Models this worker handles
	Concurrency int      // Max concurrent requests
}

// Worker consumes inference requests from RabbitMQ
type Worker struct {
	cfg        WorkerConfig
	brokerCfg  BrokerConfig
	conn       *amqp.Connection
	channel    *amqp.Channel
	httpClient *http.Client
	shutdown   chan struct{}
}

// NewWorker creates a new worker instance
func NewWorker(cfg WorkerConfig, brokerCfg BrokerConfig) *Worker {
	return &Worker{
		cfg:       cfg,
		brokerCfg: brokerCfg,
		httpClient: &http.Client{
			Timeout: 10 * time.Minute, // Long timeout for inference
		},
		shutdown: make(chan struct{}),
	}
}

// Run starts the worker consumer
func (w *Worker) Run(ctx context.Context) error {
	// Connect to RabbitMQ
	url := fmt.Sprintf("amqp://%s:%s@%s:%s/%s",
		w.brokerCfg.User, w.brokerCfg.Password,
		w.brokerCfg.Host, w.brokerCfg.Port, w.brokerCfg.VHost)

	var err error
	w.conn, err = amqp.Dial(url)
	if err != nil {
		return fmt.Errorf("failed to connect to RabbitMQ: %w", err)
	}
	defer w.conn.Close()

	w.channel, err = w.conn.Channel()
	if err != nil {
		return fmt.Errorf("failed to open channel: %w", err)
	}
	defer w.channel.Close()

	// Set QoS for fair dispatch
	err = w.channel.Qos(w.cfg.Concurrency, 0, false)
	if err != nil {
		return fmt.Errorf("failed to set QoS: %w", err)
	}

	log.Printf("🔧 Worker %s starting, Ollama: %s", w.cfg.WorkerID, w.cfg.OllamaURL)
	log.Printf("   Models: %v", w.cfg.Models)
	log.Printf("   Concurrency: %d", w.cfg.Concurrency)

	// Build list of queues to consume
	var queues []string
	for _, model := range w.cfg.Models {
		queues = append(queues, fmt.Sprintf("llm.inference.%s", modelToQueueName(model)))
	}
	queues = append(queues, "llm.inference.default")

	// Set up each queue sequentially (channel ops not thread-safe)
	for i, queueName := range queues {
		consumerTag := fmt.Sprintf("%s-%d", w.cfg.WorkerID, i)
		go w.consumeQueue(ctx, queueName, consumerTag)
		// Small delay to let channel stabilize
		time.Sleep(100 * time.Millisecond)
	}

	// Start heartbeat
	go w.heartbeatLoop(ctx)

	// Wait for shutdown
	<-ctx.Done()
	close(w.shutdown)
	log.Printf("🛑 Worker %s shutting down", w.cfg.WorkerID)
	return nil
}

// consumeQueue consumes messages from a specific queue
func (w *Worker) consumeQueue(ctx context.Context, queueName, consumerTag string) {
	// Create a dedicated channel for this queue (channels are not thread-safe)
	ch, err := w.conn.Channel()
	if err != nil {
		log.Printf("⚠️ Failed to create channel for %s: %v", queueName, err)
		return
	}
	defer ch.Close()

	// Declare queue (idempotent)
	queue, err := ch.QueueDeclare(
		queueName, // Name
		true,      // Durable
		false,     // Auto-delete
		false,     // Exclusive
		false,     // No-wait
		amqp.Table{
			"x-dead-letter-exchange": "llm.dlx",
		},
	)
	if err != nil {
		log.Printf("⚠️ Failed to declare queue %s: %v", queueName, err)
		return
	}

	// Bind to inference exchange
	err = ch.QueueBind(
		queue.Name,
		"#", // Routing key (catch all for this queue)
		"llm.inference",
		false,
		nil,
	)
	if err != nil {
		log.Printf("⚠️ Failed to bind queue %s: %v", queueName, err)
		return
	}

	msgs, err := ch.Consume(
		queue.Name,  // Queue
		consumerTag, // Consumer tag (unique per queue)
		false,       // Auto-ack (false = manual ack)
		false,       // Exclusive
		false,       // No-local
		false,       // No-wait
		nil,         // Args
	)
	if err != nil {
		log.Printf("⚠️ Failed to consume from %s: %v", queueName, err)
		return
	}

	log.Printf("📥 Consuming from queue: %s", queueName)

	for {
		select {
		case msg, ok := <-msgs:
			if !ok {
				log.Printf("Queue %s channel closed", queueName)
				return
			}
			w.handleMessage(ctx, msg)
		case <-w.shutdown:
			return
		case <-ctx.Done():
			return
		}
	}
}

// handleMessage processes a single inference request
func (w *Worker) handleMessage(ctx context.Context, msg amqp.Delivery) {
	start := time.Now()

	var req InferenceRequest
	if err := json.Unmarshal(msg.Body, &req); err != nil {
		log.Printf("⚠️ Invalid message: %v", err)
		msg.Nack(false, false) // Don't requeue malformed messages
		return
	}

	log.Printf("📨 Processing request %s for model %s", req.ID, req.Model)

	// Forward to Ollama
	resp, err := w.forwardToOllama(ctx, &req)
	if err != nil {
		log.Printf("❌ Ollama error for %s: %v", req.ID, err)
		resp = &InferenceResponse{
			ID:        req.ID,
			Model:     req.Model,
			Error:     err.Error(),
			WorkerID:  w.cfg.WorkerID,
			Timestamp: time.Now(),
			Duration:  time.Since(start).Milliseconds(),
		}
	} else {
		resp.ID = req.ID
		resp.WorkerID = w.cfg.WorkerID
		resp.Timestamp = time.Now()
		resp.Duration = time.Since(start).Milliseconds()
	}

	// Publish response to reply queue
	if req.ReplyTo != "" {
		if err := w.publishResponse(ctx, req.ReplyTo, resp); err != nil {
			log.Printf("❌ Failed to publish response: %v", err)
			msg.Nack(false, true) // Requeue
			return
		}
	}

	// Acknowledge message
	msg.Ack(false)
	log.Printf("✅ Completed %s in %dms", req.ID, resp.Duration)
}

// forwardToOllama sends the request to the local Ollama instance
func (w *Worker) forwardToOllama(ctx context.Context, req *InferenceRequest) (*InferenceResponse, error) {
	// Build Ollama request
	ollamaReq := map[string]any{
		"model":  req.Model,
		"prompt": req.Prompt,
		"stream": false, // Non-streaming for simplicity in broker mode
	}
	if req.Options != nil {
		ollamaReq["options"] = req.Options
	}

	body, err := json.Marshal(ollamaReq)
	if err != nil {
		return nil, err
	}

	httpReq, err := http.NewRequestWithContext(ctx, "POST",
		w.cfg.OllamaURL+"/api/generate", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	httpReq.Header.Set("Content-Type", "application/json")

	httpResp, err := w.httpClient.Do(httpReq)
	if err != nil {
		return nil, err
	}
	defer httpResp.Body.Close()

	if httpResp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(httpResp.Body)
		return nil, fmt.Errorf("ollama returned %d: %s", httpResp.StatusCode, string(body))
	}

	var ollamaResp struct {
		Model    string `json:"model"`
		Response string `json:"response"`
		Done     bool   `json:"done"`
	}

	if err := json.NewDecoder(httpResp.Body).Decode(&ollamaResp); err != nil {
		return nil, err
	}

	return &InferenceResponse{
		Model:    ollamaResp.Model,
		Response: ollamaResp.Response,
		Done:     ollamaResp.Done,
	}, nil
}

// publishResponse sends the response back to the reply queue
func (w *Worker) publishResponse(ctx context.Context, replyTo string, resp *InferenceResponse) error {
	body, err := json.Marshal(resp)
	if err != nil {
		return err
	}

	return w.channel.PublishWithContext(ctx,
		"",      // Default exchange
		replyTo, // Routing key = reply queue name
		false,   // Mandatory
		false,   // Immediate
		amqp.Publishing{
			ContentType:   "application/json",
			CorrelationId: resp.ID,
			Body:          body,
			Timestamp:     time.Now(),
		},
	)
}

// heartbeatLoop sends periodic heartbeats
func (w *Worker) heartbeatLoop(ctx context.Context) {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			hb := &WorkerHeartbeat{
				WorkerID:  w.cfg.WorkerID,
				Models:    w.cfg.Models,
				Status:    "ready",
				Timestamp: time.Now(),
			}
			body, _ := json.Marshal(hb)
			w.channel.PublishWithContext(ctx,
				"llm.workers", // Fanout exchange
				"",            // Routing key ignored
				false, false,
				amqp.Publishing{
					ContentType: "application/json",
					Body:        body,
				},
			)
		case <-w.shutdown:
			return
		case <-ctx.Done():
			return
		}
	}
}

// modelToQueueName converts model name to queue name
func modelToQueueName(model string) string {
	// Extract base name (before : or /)
	name := strings.Split(model, ":")[0]
	name = strings.Split(name, "/")[0]
	return strings.ToLower(name)
}

// LoadWorkerConfig loads worker configuration from environment
func LoadWorkerConfig() WorkerConfig {
	models := strings.Split(env("LLM_WORKER_MODELS", "llama3,mistral,qwen"), ",")
	for i := range models {
		models[i] = strings.TrimSpace(models[i])
	}

	concurrency := 1
	if c := env("LLM_WORKER_CONCURRENCY", ""); c != "" {
		fmt.Sscanf(c, "%d", &concurrency)
	}

	hostname, _ := os.Hostname()

	return WorkerConfig{
		WorkerID:    env("LLM_WORKER_ID", hostname),
		OllamaURL:   env("LLM_WORKER_OLLAMA_URL", "http://localhost:11434"),
		Models:      models,
		Concurrency: concurrency,
	}
}

// IsWorkerMode checks if running in worker mode
func IsWorkerMode() bool {
	return env("LLM_WORKER_MODE", "false") == "true"
}

// RunWorker starts the worker if in worker mode
func RunWorker() {
	if !IsWorkerMode() {
		return
	}

	cfg := LoadWorkerConfig()
	brokerCfg := LoadBrokerConfig()

	worker := NewWorker(cfg, brokerCfg)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Handle shutdown signals
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	go func() {
		<-sigCh
		log.Println("Received shutdown signal")
		cancel()
	}()

	if err := worker.Run(ctx); err != nil {
		log.Fatalf("Worker error: %v", err)
	}
}
