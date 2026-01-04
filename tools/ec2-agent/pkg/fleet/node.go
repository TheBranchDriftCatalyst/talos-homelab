package fleet

import (
	"sync"
	"time"

	pb "github.com/thebranchdriftcatalyst/ec2-agent/pkg/proto"
)

// Node represents a connected worker agent
type Node struct {
	mu sync.RWMutex

	// Identity
	ID           string
	Type         pb.NodeType
	InstanceID   string
	NebulaIP     string
	PublicIP     string
	Region       string
	AZ           string
	Labels       map[string]string
	Capabilities *pb.NodeCapabilities

	// Connection state
	Connected    bool
	ConnectedAt  time.Time
	LastSeen     time.Time
	StreamActive bool

	// Status (latest from agent)
	Status *pb.NodeStatus

	// Stream for sending commands (set when Connect stream is active)
	commandChan chan *pb.ControlMessage
}

// NewNode creates a new node from registration request
func NewNode(req *pb.RegisterRequest) *Node {
	return &Node{
		ID:           req.NodeId,
		Type:         req.NodeType,
		InstanceID:   req.InstanceId,
		NebulaIP:     req.NebulaIp,
		PublicIP:     req.PublicIp,
		Region:       req.Region,
		AZ:           req.AvailabilityZone,
		Labels:       req.Labels,
		Capabilities: req.Capabilities,
		Connected:    true,
		ConnectedAt:  time.Now(),
		LastSeen:     time.Now(),
		commandChan:  make(chan *pb.ControlMessage, 10),
	}
}

// UpdateStatus updates the node's status
func (n *Node) UpdateStatus(status *pb.NodeStatus) {
	n.mu.Lock()
	defer n.mu.Unlock()
	n.Status = status
	n.LastSeen = time.Now()
}

// SetConnected updates connection state
func (n *Node) SetConnected(connected bool) {
	n.mu.Lock()
	defer n.mu.Unlock()
	n.Connected = connected
	if connected {
		n.ConnectedAt = time.Now()
	}
	n.LastSeen = time.Now()
}

// SetStreamActive marks whether the bidirectional stream is active
func (n *Node) SetStreamActive(active bool) {
	n.mu.Lock()
	defer n.mu.Unlock()
	n.StreamActive = active
	if !active {
		// Close command channel when stream ends
		close(n.commandChan)
		n.commandChan = make(chan *pb.ControlMessage, 10)
	}
}

// SendCommand sends a command to this node via the stream
func (n *Node) SendCommand(cmd *pb.ControlMessage) bool {
	n.mu.RLock()
	defer n.mu.RUnlock()
	if !n.StreamActive {
		return false
	}
	select {
	case n.commandChan <- cmd:
		return true
	default:
		return false // Channel full
	}
}

// CommandChan returns the channel for receiving commands to send
func (n *Node) CommandChan() <-chan *pb.ControlMessage {
	n.mu.RLock()
	defer n.mu.RUnlock()
	return n.commandChan
}

// Touch updates last seen time
func (n *Node) Touch() {
	n.mu.Lock()
	defer n.mu.Unlock()
	n.LastSeen = time.Now()
}

// IsHealthy returns true if the node is connected and reporting healthy
func (n *Node) IsHealthy() bool {
	n.mu.RLock()
	defer n.mu.RUnlock()
	if !n.Connected {
		return false
	}
	if n.Status == nil {
		return false
	}
	return n.Status.Health == pb.HealthState_HEALTH_STATE_HEALTHY
}

// ToSummary converts node to a summary for API responses
func (n *Node) ToSummary() *pb.NodeSummary {
	n.mu.RLock()
	defer n.mu.RUnlock()

	summary := &pb.NodeSummary{
		NodeId:     n.ID,
		NodeType:   n.Type,
		NebulaIp:   n.NebulaIP,
		InstanceId: n.InstanceID,
		Connected:  n.Connected,
	}

	if n.Status != nil {
		summary.Health = n.Status.Health
		summary.UptimeSeconds = n.Status.UptimeSeconds
		summary.IdleSeconds = n.Status.IdleSeconds
		if n.Status.Resources != nil {
			summary.CpuPercent = n.Status.Resources.CpuPercent
			if n.Status.Resources.MemoryTotalMb > 0 {
				summary.MemoryPercent = float64(n.Status.Resources.MemoryUsedMb) / float64(n.Status.Resources.MemoryTotalMb) * 100
			}
		}
		summary.GpuCount = int32(len(n.Status.Gpus))
		summary.LoadedModels = int32(len(n.Status.LoadedModels))
	}

	return summary
}
