package fleet

import (
	"context"
	"log"
	"sync"
	"time"

	pb "github.com/thebranchdriftcatalyst/ec2-agent/pkg/proto"
)

// Manager manages the fleet of connected worker agents
type Manager struct {
	mu    sync.RWMutex
	nodes map[string]*Node

	// Configuration
	HeartbeatInterval time.Duration
	StatusInterval    time.Duration
	StaleTimeout      time.Duration

	// Event callbacks
	OnNodeConnected    func(*Node)
	OnNodeDisconnected func(*Node)
	OnNodeStatusUpdate func(*Node, *pb.NodeStatus)
}

// NewManager creates a new fleet manager
func NewManager() *Manager {
	return &Manager{
		nodes:             make(map[string]*Node),
		HeartbeatInterval: 30 * time.Second,
		StatusInterval:    30 * time.Second,
		StaleTimeout:      2 * time.Minute,
	}
}

// Register registers a new node or updates existing (from gRPC)
func (m *Manager) Register(req *pb.RegisterRequest) (*Node, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	nodeID := req.NodeId
	if nodeID == "" {
		nodeID = req.InstanceId
	}

	existing, exists := m.nodes[nodeID]
	if exists {
		// Update existing node
		existing.SetConnected(true)
		existing.InstanceID = req.InstanceId
		existing.NebulaIP = req.NebulaIp
		existing.PublicIP = req.PublicIp
		existing.Labels = req.Labels
		existing.Capabilities = req.Capabilities
		log.Printf("[fleet] Node reconnected: %s (%s)", nodeID, req.NodeType)
		return existing, nil
	}

	// Create new node
	node := NewNode(req)
	node.ID = nodeID
	m.nodes[nodeID] = node

	log.Printf("[fleet] Node registered: %s (%s) at %s", nodeID, req.NodeType, req.NebulaIp)

	if m.OnNodeConnected != nil {
		go m.OnNodeConnected(node)
	}

	return node, nil
}

// RegisterNode registers a node directly (from RabbitMQ)
func (m *Manager) RegisterNode(node *Node) {
	m.mu.Lock()
	defer m.mu.Unlock()

	existing, exists := m.nodes[node.ID]
	if exists {
		// Update existing node - preserve connection state
		existing.NebulaIP = node.NebulaIP
		existing.PublicIP = node.PublicIP
		existing.Region = node.Region
		existing.AZ = node.AZ
		existing.SetConnected(true)
		log.Printf("[fleet] Node updated via RabbitMQ: %s", node.ID)
		return
	}

	m.nodes[node.ID] = node
	log.Printf("[fleet] Node registered via RabbitMQ: %s (%v) at %s", node.ID, node.Type, node.NebulaIP)

	if m.OnNodeConnected != nil {
		go m.OnNodeConnected(node)
	}
}

// Unregister removes a node from the fleet
func (m *Manager) Unregister(nodeID string) {
	m.mu.Lock()
	node, exists := m.nodes[nodeID]
	if exists {
		node.SetConnected(false)
		delete(m.nodes, nodeID)
	}
	m.mu.Unlock()

	if exists && m.OnNodeDisconnected != nil {
		go m.OnNodeDisconnected(node)
	}

	log.Printf("[fleet] Node unregistered: %s", nodeID)
}

// Disconnect marks a node as disconnected but keeps it in the fleet
func (m *Manager) Disconnect(nodeID string) {
	m.mu.RLock()
	node, exists := m.nodes[nodeID]
	m.mu.RUnlock()

	if exists {
		node.SetConnected(false)
		node.SetStreamActive(false)
		log.Printf("[fleet] Node disconnected: %s", nodeID)
		if m.OnNodeDisconnected != nil {
			go m.OnNodeDisconnected(node)
		}
	}
}

// GetNode returns a node by ID
func (m *Manager) GetNode(nodeID string) *Node {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.nodes[nodeID]
}

// UpdateStatus updates a node's status
func (m *Manager) UpdateStatus(nodeID string, status *pb.NodeStatus) {
	m.mu.RLock()
	node, exists := m.nodes[nodeID]
	m.mu.RUnlock()

	if exists {
		node.UpdateStatus(status)
		if m.OnNodeStatusUpdate != nil {
			go m.OnNodeStatusUpdate(node, status)
		}
	}
}

// Heartbeat updates the last seen time for a node
func (m *Manager) Heartbeat(nodeID string) {
	m.mu.RLock()
	node, exists := m.nodes[nodeID]
	m.mu.RUnlock()

	if exists {
		node.Touch()
	}
}

// GetFleetStatus returns status of all nodes
func (m *Manager) GetFleetStatus(filter *pb.FleetStatusRequest) *pb.FleetStatusResponse {
	m.mu.RLock()
	defer m.mu.RUnlock()

	var nodes []*pb.NodeSummary
	summary := &pb.FleetSummary{}

	for _, node := range m.nodes {
		// Apply filters
		if filter != nil {
			if filter.NodeType != pb.NodeType_NODE_TYPE_UNSPECIFIED && node.Type != filter.NodeType {
				continue
			}
			if filter.Health != pb.HealthState_HEALTH_STATE_UNSPECIFIED {
				if node.Status == nil || node.Status.Health != filter.Health {
					continue
				}
			}
		}

		nodes = append(nodes, node.ToSummary())

		// Update summary
		summary.TotalNodes++
		if node.IsHealthy() {
			summary.HealthyNodes++
		} else if node.Connected {
			summary.UnhealthyNodes++
		}
		if node.Type == pb.NodeType_NODE_TYPE_GPU_WORKER {
			summary.GpuNodes++
			if node.Capabilities != nil {
				summary.TotalGpus += node.Capabilities.GpuCount
			}
		}
	}

	return &pb.FleetStatusResponse{
		Nodes:   nodes,
		Summary: summary,
	}
}

// SendCommand sends a command to a specific node
func (m *Manager) SendCommand(nodeID string, cmd *pb.Command) bool {
	m.mu.RLock()
	node, exists := m.nodes[nodeID]
	m.mu.RUnlock()

	if !exists || !node.Connected {
		return false
	}

	return node.SendCommand(&pb.ControlMessage{
		Payload: &pb.ControlMessage_Command{
			Command: cmd,
		},
	})
}

// BroadcastCommand sends a command to all connected nodes
func (m *Manager) BroadcastCommand(cmd *pb.Command, nodeType pb.NodeType) int {
	m.mu.RLock()
	defer m.mu.RUnlock()

	sent := 0
	for _, node := range m.nodes {
		if !node.Connected {
			continue
		}
		if nodeType != pb.NodeType_NODE_TYPE_UNSPECIFIED && node.Type != nodeType {
			continue
		}
		if node.SendCommand(&pb.ControlMessage{
			Payload: &pb.ControlMessage_Command{
				Command: cmd,
			},
		}) {
			sent++
		}
	}
	return sent
}

// SendShutdownCommand sends a shutdown command to a specific node via gRPC
func (m *Manager) SendShutdownCommand(nodeID string, reason string) bool {
	m.mu.RLock()
	node, exists := m.nodes[nodeID]
	m.mu.RUnlock()

	if !exists {
		log.Printf("[fleet] Cannot send shutdown to unknown node: %s", nodeID)
		return false
	}

	if !node.StreamActive {
		log.Printf("[fleet] Cannot send shutdown to node %s: no active gRPC stream", nodeID)
		return false
	}

	cmd := &pb.Command{
		CommandId: "auto-shutdown-" + nodeID,
		Type:      pb.CommandType_COMMAND_TYPE_SHUTDOWN,
		Args:      map[string]string{"reason": reason},
	}

	success := node.SendCommand(&pb.ControlMessage{
		Payload: &pb.ControlMessage_Command{
			Command: cmd,
		},
	})

	if success {
		log.Printf("[fleet] Sent shutdown command to node %s: %s", nodeID, reason)
	} else {
		log.Printf("[fleet] Failed to send shutdown to node %s: channel full or inactive", nodeID)
	}

	return success
}

// ListNodes returns all nodes (for debugging/admin)
func (m *Manager) ListNodes() []*Node {
	m.mu.RLock()
	defer m.mu.RUnlock()

	nodes := make([]*Node, 0, len(m.nodes))
	for _, node := range m.nodes {
		nodes = append(nodes, node)
	}
	return nodes
}

// ConnectedCount returns the number of connected nodes
func (m *Manager) ConnectedCount() int {
	m.mu.RLock()
	defer m.mu.RUnlock()

	count := 0
	for _, node := range m.nodes {
		if node.Connected {
			count++
		}
	}
	return count
}

// StartCleanup starts a goroutine to clean up stale nodes
func (m *Manager) StartCleanup(ctx context.Context) {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			m.cleanupStaleNodes()
		}
	}
}

func (m *Manager) cleanupStaleNodes() {
	m.mu.Lock()
	defer m.mu.Unlock()

	now := time.Now()
	for nodeID, node := range m.nodes {
		if node.Connected && now.Sub(node.LastSeen) > m.StaleTimeout {
			log.Printf("[fleet] Node stale, marking disconnected: %s (last seen: %v ago)",
				nodeID, now.Sub(node.LastSeen))
			node.SetConnected(false)
			node.SetStreamActive(false)
			if m.OnNodeDisconnected != nil {
				go m.OnNodeDisconnected(node)
			}
		}
	}
}
