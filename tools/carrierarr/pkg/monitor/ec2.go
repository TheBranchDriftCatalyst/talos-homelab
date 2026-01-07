// Package monitor provides AWS resource monitoring for EC2 and Fargate
package monitor

import (
	"context"
	"log"
	"sync"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/ec2"
	"github.com/aws/aws-sdk-go-v2/service/ec2/types"
	"github.com/thebranchdriftcatalyst/ec2-agent/pkg/protocol"
)

// EC2Monitor watches EC2 instances and reports status changes
type EC2Monitor struct {
	client   *ec2.Client
	interval time.Duration
	filters  []types.Filter

	// Callback for status updates
	OnStatusUpdate func([]protocol.WorkerStatus)

	// Current known status
	status map[string]protocol.WorkerStatus
	mu     sync.RWMutex

	stopCh chan struct{}
}

// EC2Config configures the EC2 monitor
type EC2Config struct {
	Client   *ec2.Client
	Interval time.Duration
	Tags     map[string]string // Filter instances by tags
}

// NewEC2Monitor creates a new EC2 instance monitor
func NewEC2Monitor(cfg EC2Config) *EC2Monitor {
	if cfg.Interval == 0 {
		cfg.Interval = 30 * time.Second
	}

	// Build filters from tags
	filters := make([]types.Filter, 0)
	for key, value := range cfg.Tags {
		filters = append(filters, types.Filter{
			Name:   aws.String("tag:" + key),
			Values: []string{value},
		})
	}

	return &EC2Monitor{
		client:   cfg.Client,
		interval: cfg.Interval,
		filters:  filters,
		status:   make(map[string]protocol.WorkerStatus),
		stopCh:   make(chan struct{}),
	}
}

// Start begins monitoring EC2 instances
func (m *EC2Monitor) Start(ctx context.Context) {
	log.Printf("[EC2Monitor] Starting with interval: %s", m.interval)

	// Initial poll
	m.poll(ctx)

	ticker := time.NewTicker(m.interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			log.Printf("[EC2Monitor] Context cancelled, stopping")
			return
		case <-m.stopCh:
			log.Printf("[EC2Monitor] Stop requested")
			return
		case <-ticker.C:
			m.poll(ctx)
		}
	}
}

// Stop stops the monitor
func (m *EC2Monitor) Stop() {
	close(m.stopCh)
}

// poll fetches current EC2 instance status
func (m *EC2Monitor) poll(ctx context.Context) {
	input := &ec2.DescribeInstancesInput{}
	if len(m.filters) > 0 {
		input.Filters = m.filters
	}

	result, err := m.client.DescribeInstances(ctx, input)
	if err != nil {
		log.Printf("[EC2Monitor] Failed to describe instances: %v", err)
		return
	}

	workers := make([]protocol.WorkerStatus, 0)

	for _, reservation := range result.Reservations {
		for _, instance := range reservation.Instances {
			status := m.instanceToStatus(instance)
			workers = append(workers, status)

			// Track status
			m.mu.Lock()
			m.status[status.ID] = status
			m.mu.Unlock()
		}
	}

	// Notify callback
	if m.OnStatusUpdate != nil && len(workers) > 0 {
		m.OnStatusUpdate(workers)
	}
}

// instanceToStatus converts EC2 instance to WorkerStatus
func (m *EC2Monitor) instanceToStatus(instance types.Instance) protocol.WorkerStatus {
	status := protocol.WorkerStatus{
		ID:       aws.ToString(instance.InstanceId),
		Provider: "ec2",
		State:    string(instance.State.Name),
		Tags:     make(map[string]string),
	}

	// Extract name from tags
	for _, tag := range instance.Tags {
		key := aws.ToString(tag.Key)
		value := aws.ToString(tag.Value)
		status.Tags[key] = value
		if key == "Name" {
			status.Name = value
		}
	}

	if instance.PublicIpAddress != nil {
		status.PublicIP = aws.ToString(instance.PublicIpAddress)
	}
	if instance.PrivateIpAddress != nil {
		status.PrivateIP = aws.ToString(instance.PrivateIpAddress)
	}
	if instance.InstanceType != "" {
		status.InstanceType = string(instance.InstanceType)
	}
	if instance.LaunchTime != nil {
		status.LaunchTime = instance.LaunchTime
	}

	return status
}

// GetStatus returns current status of all monitored instances
func (m *EC2Monitor) GetStatus() []protocol.WorkerStatus {
	m.mu.RLock()
	defer m.mu.RUnlock()

	workers := make([]protocol.WorkerStatus, 0, len(m.status))
	for _, s := range m.status {
		workers = append(workers, s)
	}
	return workers
}

// GetInstanceStatus returns status of a specific instance
func (m *EC2Monitor) GetInstanceStatus(instanceID string) (protocol.WorkerStatus, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	status, ok := m.status[instanceID]
	return status, ok
}
