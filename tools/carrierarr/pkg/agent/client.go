package agent

import (
	"context"
	"fmt"
	"io"
	"log"
	"os"
	"sync"
	"time"

	pb "github.com/thebranchdriftcatalyst/ec2-agent/pkg/proto"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/keepalive"
)

// Client handles communication with the control plane
type Client struct {
	mu sync.RWMutex

	// Connection
	conn   *grpc.ClientConn
	client pb.AgentControlClient
	stream grpc.BidiStreamingClient[pb.AgentMessage, pb.ControlMessage]

	// Identity
	nodeID     string
	nodeType   pb.NodeType
	instanceID string
	nebulaIP   string
	publicIP   string
	region     string
	az         string

	// Configuration
	ControlPlaneAddr  string
	HeartbeatInterval time.Duration
	StatusInterval    time.Duration
	ReconnectDelay    time.Duration

	// Components
	statusCollector *StatusCollector
	executor        *Executor

	// Callbacks
	OnConnected    func()
	OnDisconnected func()
	OnCommand      func(*pb.Command)

	// State
	connected bool
	stopChan  chan struct{}
}

// NewClient creates a new agent client
func NewClient(controlPlaneAddr string, nodeType pb.NodeType) *Client {
	nodeID, _ := os.Hostname()

	return &Client{
		ControlPlaneAddr:  controlPlaneAddr,
		nodeID:            nodeID,
		nodeType:          nodeType,
		HeartbeatInterval: 30 * time.Second,
		StatusInterval:    30 * time.Second,
		ReconnectDelay:    5 * time.Second,
		stopChan:          make(chan struct{}),
	}
}

// SetIdentity sets the node identity information
func (c *Client) SetIdentity(instanceID, nebulaIP, publicIP, region, az string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.instanceID = instanceID
	c.nebulaIP = nebulaIP
	c.publicIP = publicIP
	c.region = region
	c.az = az
}

// SetStatusCollector sets the status collector
func (c *Client) SetStatusCollector(sc *StatusCollector) {
	c.statusCollector = sc
}

// SetExecutor sets the command executor
func (c *Client) SetExecutor(ex *Executor) {
	c.executor = ex
}

// Connect establishes connection to control plane
func (c *Client) Connect(ctx context.Context) error {
	log.Printf("[client] Connecting to control plane at %s", c.ControlPlaneAddr)

	var err error
	c.conn, err = grpc.NewClient(
		c.ControlPlaneAddr,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithKeepaliveParams(keepalive.ClientParameters{
			Time:                30 * time.Second,
			Timeout:             10 * time.Second,
			PermitWithoutStream: true,
		}),
	)
	if err != nil {
		return fmt.Errorf("failed to connect: %w", err)
	}

	c.client = pb.NewAgentControlClient(c.conn)

	// Register with control plane
	if err := c.register(ctx); err != nil {
		c.conn.Close()
		return fmt.Errorf("registration failed: %w", err)
	}

	// Establish bidirectional stream
	if err := c.establishStream(ctx); err != nil {
		c.conn.Close()
		return fmt.Errorf("stream establishment failed: %w", err)
	}

	c.mu.Lock()
	c.connected = true
	c.mu.Unlock()

	if c.OnConnected != nil {
		go c.OnConnected()
	}

	log.Printf("[client] Connected and registered as %s", c.nodeID)
	return nil
}

func (c *Client) register(ctx context.Context) error {
	c.mu.RLock()
	req := &pb.RegisterRequest{
		NodeId:     c.nodeID,
		NodeType:   c.nodeType,
		InstanceId: c.instanceID,
		NebulaIp:   c.nebulaIP,
		PublicIp:   c.publicIP,
		Region:     c.region,
		AvailabilityZone: c.az,
		Labels:     make(map[string]string),
	}

	// Add capabilities for GPU workers
	if c.nodeType == pb.NodeType_NODE_TYPE_GPU_WORKER {
		req.Capabilities = &pb.NodeCapabilities{
			HasGpu:   true,
			GpuCount: 1, // Will be updated from status
			GpuModel: "unknown",
		}
	}
	c.mu.RUnlock()

	resp, err := c.client.Register(ctx, req)
	if err != nil {
		return err
	}

	if !resp.Accepted {
		return fmt.Errorf("registration rejected: %s", resp.Message)
	}

	// Update intervals from server
	if resp.HeartbeatIntervalSec > 0 {
		c.HeartbeatInterval = time.Duration(resp.HeartbeatIntervalSec) * time.Second
	}
	if resp.StatusIntervalSec > 0 {
		c.StatusInterval = time.Duration(resp.StatusIntervalSec) * time.Second
	}

	log.Printf("[client] Registered: %s (heartbeat=%v, status=%v)",
		resp.Message, c.HeartbeatInterval, c.StatusInterval)
	return nil
}

func (c *Client) establishStream(ctx context.Context) error {
	var err error
	c.stream, err = c.client.Connect(ctx)
	if err != nil {
		return err
	}

	// Start goroutine to receive commands
	go c.receiveLoop()

	return nil
}

func (c *Client) receiveLoop() {
	for {
		msg, err := c.stream.Recv()
		if err == io.EOF {
			log.Printf("[client] Stream closed by server")
			break
		}
		if err != nil {
			log.Printf("[client] Stream error: %v", err)
			break
		}

		switch payload := msg.Payload.(type) {
		case *pb.ControlMessage_Command:
			log.Printf("[client] Received command: %s (%s)",
				payload.Command.CommandId, payload.Command.Type)
			c.handleCommand(payload.Command)

		case *pb.ControlMessage_Config:
			log.Printf("[client] Received config update")
			// Handle config updates
		}
	}

	c.mu.Lock()
	c.connected = false
	c.mu.Unlock()

	if c.OnDisconnected != nil {
		go c.OnDisconnected()
	}
}

func (c *Client) handleCommand(cmd *pb.Command) {
	if c.OnCommand != nil {
		c.OnCommand(cmd)
	}

	if c.executor == nil {
		log.Printf("[client] No executor configured, ignoring command")
		return
	}

	// Execute command in background
	go func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
		defer cancel()

		result := c.executor.Execute(ctx, cmd)

		// Send result back
		if err := c.SendCommandResult(result); err != nil {
			log.Printf("[client] Failed to send command result: %v", err)
		}
	}()
}

// SendStatus sends current status to control plane
func (c *Client) SendStatus(status *pb.NodeStatus) error {
	c.mu.RLock()
	stream := c.stream
	c.mu.RUnlock()

	if stream == nil {
		return fmt.Errorf("not connected")
	}

	return stream.Send(&pb.AgentMessage{
		Payload: &pb.AgentMessage_Status{
			Status: status,
		},
	})
}

// SendCommandResult sends command result to control plane
func (c *Client) SendCommandResult(result *pb.CommandResult) error {
	c.mu.RLock()
	stream := c.stream
	c.mu.RUnlock()

	if stream == nil {
		return fmt.Errorf("not connected")
	}

	return stream.Send(&pb.AgentMessage{
		Payload: &pb.AgentMessage_CommandResult{
			CommandResult: result,
		},
	})
}

// SendLog sends a log message to control plane
func (c *Client) SendLog(level pb.LogLevel, message string) error {
	c.mu.RLock()
	stream := c.stream
	c.mu.RUnlock()

	if stream == nil {
		return fmt.Errorf("not connected")
	}

	return stream.Send(&pb.AgentMessage{
		Payload: &pb.AgentMessage_Log{
			Log: &pb.LogEntry{
				Level:   level,
				Message: message,
			},
		},
	})
}

// Run starts the agent main loop
func (c *Client) Run(ctx context.Context) error {
	// Initial connection
	if err := c.Connect(ctx); err != nil {
		return err
	}

	// Start background tasks
	go c.statusLoop(ctx)
	go c.heartbeatLoop(ctx)

	// Wait for stop signal or context cancellation
	select {
	case <-ctx.Done():
		log.Printf("[client] Context cancelled, shutting down")
	case <-c.stopChan:
		log.Printf("[client] Stop requested, shutting down")
	}

	return c.Close()
}

// RunWithReconnect runs the agent with automatic reconnection
func (c *Client) RunWithReconnect(ctx context.Context) {
	for {
		select {
		case <-ctx.Done():
			return
		default:
		}

		err := c.Run(ctx)
		if err != nil {
			log.Printf("[client] Connection error: %v, reconnecting in %v", err, c.ReconnectDelay)
		}

		select {
		case <-ctx.Done():
			return
		case <-time.After(c.ReconnectDelay):
			// Reconnect
		}
	}
}

func (c *Client) statusLoop(ctx context.Context) {
	ticker := time.NewTicker(c.StatusInterval)
	defer ticker.Stop()

	// Send initial status
	c.sendCurrentStatus()

	for {
		select {
		case <-ctx.Done():
			return
		case <-c.stopChan:
			return
		case <-ticker.C:
			c.sendCurrentStatus()
		}
	}
}

func (c *Client) sendCurrentStatus() {
	if c.statusCollector == nil {
		return
	}

	c.mu.RLock()
	connected := c.connected
	c.mu.RUnlock()

	if !connected {
		return
	}

	status := c.statusCollector.Collect()
	if err := c.SendStatus(status); err != nil {
		log.Printf("[client] Failed to send status: %v", err)
	}
}

func (c *Client) heartbeatLoop(ctx context.Context) {
	ticker := time.NewTicker(c.HeartbeatInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-c.stopChan:
			return
		case <-ticker.C:
			c.sendHeartbeat(ctx)
		}
	}
}

func (c *Client) sendHeartbeat(ctx context.Context) {
	c.mu.RLock()
	connected := c.connected
	nodeID := c.nodeID
	c.mu.RUnlock()

	if !connected {
		return
	}

	_, err := c.client.Heartbeat(ctx, &pb.HeartbeatRequest{
		NodeId: nodeID,
	})
	if err != nil {
		log.Printf("[client] Heartbeat failed: %v", err)
	}
}

// IsConnected returns current connection state
func (c *Client) IsConnected() bool {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.connected
}

// Stop signals the client to stop
func (c *Client) Stop() {
	close(c.stopChan)
}

// Close closes the connection
func (c *Client) Close() error {
	c.mu.Lock()
	defer c.mu.Unlock()

	c.connected = false

	if c.stream != nil {
		c.stream.CloseSend()
	}

	if c.conn != nil {
		return c.conn.Close()
	}

	return nil
}
