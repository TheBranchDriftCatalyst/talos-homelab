// Package monitor provides AWS resource monitoring for EC2 and Fargate
package monitor

import (
	"context"
	"log"
	"sync"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/ecs"
	"github.com/aws/aws-sdk-go-v2/service/ecs/types"
	"github.com/thebranchdriftcatalyst/carrierarr/pkg/protocol"
)

// FargateMonitor watches ECS Fargate tasks and reports status changes
type FargateMonitor struct {
	client   *ecs.Client
	interval time.Duration
	cluster  string
	services []string

	// Callback for status updates
	OnStatusUpdate func([]protocol.WorkerStatus)

	// Current known status
	status map[string]protocol.WorkerStatus
	mu     sync.RWMutex

	stopCh chan struct{}
}

// FargateConfig configures the Fargate monitor
type FargateConfig struct {
	Client   *ecs.Client
	Interval time.Duration
	Cluster  string   // ECS cluster name or ARN
	Services []string // Optional: filter by service names
}

// NewFargateMonitor creates a new Fargate task monitor
func NewFargateMonitor(cfg FargateConfig) *FargateMonitor {
	if cfg.Interval == 0 {
		cfg.Interval = 30 * time.Second
	}

	return &FargateMonitor{
		client:   cfg.Client,
		interval: cfg.Interval,
		cluster:  cfg.Cluster,
		services: cfg.Services,
		status:   make(map[string]protocol.WorkerStatus),
		stopCh:   make(chan struct{}),
	}
}

// Start begins monitoring Fargate tasks
func (m *FargateMonitor) Start(ctx context.Context) {
	log.Printf("[FargateMonitor] Starting with interval: %s, cluster: %s", m.interval, m.cluster)

	// Initial poll
	m.poll(ctx)

	ticker := time.NewTicker(m.interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			log.Printf("[FargateMonitor] Context cancelled, stopping")
			return
		case <-m.stopCh:
			log.Printf("[FargateMonitor] Stop requested")
			return
		case <-ticker.C:
			m.poll(ctx)
		}
	}
}

// Stop stops the monitor
func (m *FargateMonitor) Stop() {
	close(m.stopCh)
}

// poll fetches current Fargate task status
func (m *FargateMonitor) poll(ctx context.Context) {
	// List tasks in the cluster
	listInput := &ecs.ListTasksInput{
		Cluster: aws.String(m.cluster),
	}

	listResult, err := m.client.ListTasks(ctx, listInput)
	if err != nil {
		log.Printf("[FargateMonitor] Failed to list tasks: %v", err)
		return
	}

	if len(listResult.TaskArns) == 0 {
		return
	}

	// Describe the tasks
	descInput := &ecs.DescribeTasksInput{
		Cluster: aws.String(m.cluster),
		Tasks:   listResult.TaskArns,
	}

	descResult, err := m.client.DescribeTasks(ctx, descInput)
	if err != nil {
		log.Printf("[FargateMonitor] Failed to describe tasks: %v", err)
		return
	}

	workers := make([]protocol.WorkerStatus, 0)

	for _, task := range descResult.Tasks {
		status := m.taskToStatus(task)
		workers = append(workers, status)

		// Track status
		m.mu.Lock()
		m.status[status.ID] = status
		m.mu.Unlock()
	}

	// Notify callback
	if m.OnStatusUpdate != nil && len(workers) > 0 {
		m.OnStatusUpdate(workers)
	}
}

// taskToStatus converts ECS task to WorkerStatus
func (m *FargateMonitor) taskToStatus(task types.Task) protocol.WorkerStatus {
	taskArn := aws.ToString(task.TaskArn)

	status := protocol.WorkerStatus{
		ID:       taskArn,
		Provider: "fargate",
		State:    aws.ToString(task.LastStatus),
		Tags:     make(map[string]string),
	}

	// Extract task definition name as "name"
	if task.TaskDefinitionArn != nil {
		status.Name = extractTaskDefName(aws.ToString(task.TaskDefinitionArn))
	}

	// Get private IP from network attachments
	for _, attachment := range task.Attachments {
		if aws.ToString(attachment.Type) == "ElasticNetworkInterface" {
			for _, detail := range attachment.Details {
				if aws.ToString(detail.Name) == "privateIPv4Address" {
					status.PrivateIP = aws.ToString(detail.Value)
				}
			}
		}
	}

	// Extract container info
	if len(task.Containers) > 0 {
		container := task.Containers[0]
		if container.NetworkInterfaces != nil && len(container.NetworkInterfaces) > 0 {
			ni := container.NetworkInterfaces[0]
			if ni.PrivateIpv4Address != nil {
				status.PrivateIP = aws.ToString(ni.PrivateIpv4Address)
			}
		}
	}

	// Launch type as instance type equivalent
	status.InstanceType = string(task.LaunchType)

	// CPU and memory
	if task.Cpu != nil && task.Memory != nil {
		status.InstanceType = *task.Cpu + " vCPU / " + *task.Memory + " MB"
	}

	// Started time
	if task.StartedAt != nil {
		status.LaunchTime = task.StartedAt
	}

	// Tags
	for _, tag := range task.Tags {
		status.Tags[aws.ToString(tag.Key)] = aws.ToString(tag.Value)
	}

	// Health status
	if task.HealthStatus != "" {
		status.HealthCheck = string(task.HealthStatus)
	}

	return status
}

// extractTaskDefName gets the task definition name from ARN
func extractTaskDefName(arn string) string {
	// ARN format: arn:aws:ecs:region:account:task-definition/name:revision
	// We want just the name
	for i := len(arn) - 1; i >= 0; i-- {
		if arn[i] == '/' {
			name := arn[i+1:]
			// Remove revision
			for j := 0; j < len(name); j++ {
				if name[j] == ':' {
					return name[:j]
				}
			}
			return name
		}
	}
	return arn
}

// GetStatus returns current status of all monitored tasks
func (m *FargateMonitor) GetStatus() []protocol.WorkerStatus {
	m.mu.RLock()
	defer m.mu.RUnlock()

	workers := make([]protocol.WorkerStatus, 0, len(m.status))
	for _, s := range m.status {
		workers = append(workers, s)
	}
	return workers
}

// GetTaskStatus returns status of a specific task
func (m *FargateMonitor) GetTaskStatus(taskArn string) (protocol.WorkerStatus, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	status, ok := m.status[taskArn]
	return status, ok
}
