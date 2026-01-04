// Fleet client for querying the ec2-agents control-plane API
// Provides dynamic GPU worker discovery and lifecycle management
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"sync"
	"time"
)

// FleetNode represents a worker node from the fleet API
type FleetNode struct {
	ID           string    `json:"id"`
	Type         string    `json:"type"`
	InstanceID   string    `json:"instance_id"`
	NebulaIP     string    `json:"nebula_ip"`
	PublicIP     string    `json:"public_ip"`
	Connected    bool      `json:"connected"`
	LastSeen     time.Time `json:"last_seen"`
	StreamActive bool      `json:"stream_active"`
	Health       string    `json:"health,omitempty"`
	HealthStatus string    `json:"health_status,omitempty"` // From RabbitMQ heartbeats
	UptimeSeconds int64    `json:"uptime_seconds,omitempty"`
	GPUCount     int       `json:"gpu_count,omitempty"`
}

// FleetClient manages communication with the ec2-agents control-plane
type FleetClient struct {
	baseURL     string
	httpClient  *http.Client
	mu          sync.RWMutex
	nodes       []FleetNode
	lastRefresh time.Time
	refreshInterval time.Duration
}

// NewFleetClient creates a new fleet client
func NewFleetClient(baseURL string) *FleetClient {
	return &FleetClient{
		baseURL:         baseURL,
		httpClient:      &http.Client{Timeout: 10 * time.Second},
		nodes:           make([]FleetNode, 0),
		refreshInterval: 30 * time.Second,
	}
}

// GetGPUWorkers returns all healthy GPU workers
func (c *FleetClient) GetGPUWorkers() []FleetNode {
	c.mu.RLock()
	defer c.mu.RUnlock()

	var workers []FleetNode
	for _, node := range c.nodes {
		if node.Type == "NODE_TYPE_GPU_WORKER" && node.Connected {
			workers = append(workers, node)
		}
	}
	return workers
}

// GetBestGPUWorker returns the best available GPU worker (prefer healthy, then by GPU count)
func (c *FleetClient) GetBestGPUWorker() *FleetNode {
	workers := c.GetGPUWorkers()
	if len(workers) == 0 {
		return nil
	}

	// Simple selection: prefer healthy workers, then highest GPU count
	var best *FleetNode
	for i := range workers {
		w := &workers[i]
		if best == nil {
			best = w
			continue
		}

		// Prefer healthy over unhealthy
		if w.Health == "HEALTH_STATE_HEALTHY" && best.Health != "HEALTH_STATE_HEALTHY" {
			best = w
		} else if w.GPUCount > best.GPUCount {
			best = w
		}
	}
	return best
}

// GetOllamaURL returns the Ollama URL for the best GPU worker (nebula_ip:11434)
func (c *FleetClient) GetOllamaURL() string {
	worker := c.GetBestGPUWorker()
	if worker == nil {
		return ""
	}
	return fmt.Sprintf("http://%s:11434", worker.NebulaIP)
}

// Refresh fetches the latest node list from the fleet API
func (c *FleetClient) Refresh(ctx context.Context) error {
	url := c.baseURL + "/api/v1/nodes"
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("failed to fetch nodes: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("fleet API returned status %d", resp.StatusCode)
	}

	var nodes []FleetNode
	if err := json.NewDecoder(resp.Body).Decode(&nodes); err != nil {
		return fmt.Errorf("failed to decode nodes: %w", err)
	}

	c.mu.Lock()
	c.nodes = nodes
	c.lastRefresh = time.Now()
	c.mu.Unlock()

	return nil
}

// RefreshIfStale refreshes the node list if it's older than the refresh interval
func (c *FleetClient) RefreshIfStale(ctx context.Context) {
	c.mu.RLock()
	stale := time.Since(c.lastRefresh) > c.refreshInterval
	c.mu.RUnlock()

	if stale {
		if err := c.Refresh(ctx); err != nil {
			log.Printf("⚠️  Fleet refresh failed: %v", err)
		}
	}
}

// SendShutdownCommand sends a shutdown command to a specific node via the fleet API
func (c *FleetClient) SendShutdownCommand(ctx context.Context, nodeID, reason string) error {
	url := c.baseURL + "/api/v1/command"
	payload := map[string]any{
		"node_id": nodeID,
		"type":    "SHUTDOWN",
		"args":    map[string]string{"reason": reason},
	}

	body, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("failed to marshal command: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, "POST", url, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("failed to send command: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusAccepted {
		return fmt.Errorf("command failed with status %d", resp.StatusCode)
	}

	return nil
}

// RunRefreshLoop starts a background goroutine that periodically refreshes node state
func (c *FleetClient) RunRefreshLoop(ctx context.Context) {
	ticker := time.NewTicker(c.refreshInterval)
	defer ticker.Stop()

	// Initial refresh
	if err := c.Refresh(ctx); err != nil {
		log.Printf("⚠️  Initial fleet refresh failed: %v", err)
	}

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if err := c.Refresh(ctx); err != nil {
				log.Printf("⚠️  Fleet refresh failed: %v", err)
			}
		}
	}
}

// IsConfigured returns true if fleet API is configured
func (c *FleetClient) IsConfigured() bool {
	return c.baseURL != ""
}

// NodeCount returns the number of known nodes
func (c *FleetClient) NodeCount() int {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return len(c.nodes)
}

// GetNodes returns a copy of all known nodes
func (c *FleetClient) GetNodes() []FleetNode {
	c.mu.RLock()
	defer c.mu.RUnlock()

	nodes := make([]FleetNode, len(c.nodes))
	copy(nodes, c.nodes)
	return nodes
}
