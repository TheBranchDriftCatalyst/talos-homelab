// Package protocol defines the WebSocket message types for carrierarr
package protocol

import (
	"encoding/json"
	"time"
)

// MessageType represents the type of WebSocket message
type MessageType string

const (
	// Inbound message types (client -> server)
	TypeCommand   MessageType = "command"
	TypeSubscribe MessageType = "subscribe"
	TypePing      MessageType = "ping"

	// Outbound message types (server -> client)
	TypeStdout MessageType = "stdout"
	TypeStderr MessageType = "stderr"
	TypeStatus MessageType = "status"
	TypeResult MessageType = "result"
	TypeError  MessageType = "error"
	TypePong   MessageType = "pong"
)

// InboundMessage represents a message from client to server
type InboundMessage struct {
	Type    MessageType `json:"type"`
	Command string      `json:"command,omitempty"` // For TypeCommand: start, stop, status, etc.
	Args    []string    `json:"args,omitempty"`    // Optional command arguments
	Target  string      `json:"target,omitempty"`  // Target worker/instance ID
}

// OutboundMessage represents a message from server to client
type OutboundMessage struct {
	Type      MessageType `json:"type"`
	Data      string      `json:"data,omitempty"`
	Timestamp time.Time   `json:"timestamp"`
	Target    string      `json:"target,omitempty"`    // Which worker this relates to
	ExitCode  *int        `json:"exit_code,omitempty"` // For TypeResult
	Error     string      `json:"error,omitempty"`     // For TypeError
}

// WorkerStatus represents the current state of a worker
type WorkerStatus struct {
	ID            string            `json:"id"`
	Name          string            `json:"name"`
	Provider      string            `json:"provider"` // "ec2" or "fargate"
	State         string            `json:"state"`    // running, stopped, pending, etc.
	PublicIP      string            `json:"public_ip,omitempty"`
	PrivateIP     string            `json:"private_ip,omitempty"`
	InstanceType  string            `json:"instance_type,omitempty"`
	LaunchTime    *time.Time        `json:"launch_time,omitempty"`
	Tags          map[string]string `json:"tags,omitempty"`
	HealthCheck   string            `json:"health_check,omitempty"` // healthy, unhealthy, unknown
	LastHeartbeat *time.Time        `json:"last_heartbeat,omitempty"`
}

// StatusUpdate wraps worker status for WebSocket broadcast
type StatusUpdate struct {
	Workers   []WorkerStatus `json:"workers"`
	Timestamp time.Time      `json:"timestamp"`
}

// NewStdoutMessage creates a stdout message
func NewStdoutMessage(target, data string) OutboundMessage {
	return OutboundMessage{
		Type:      TypeStdout,
		Target:    target,
		Data:      data,
		Timestamp: time.Now(),
	}
}

// NewStderrMessage creates a stderr message
func NewStderrMessage(target, data string) OutboundMessage {
	return OutboundMessage{
		Type:      TypeStderr,
		Target:    target,
		Data:      data,
		Timestamp: time.Now(),
	}
}

// NewResultMessage creates a command result message
func NewResultMessage(target string, exitCode int) OutboundMessage {
	return OutboundMessage{
		Type:      TypeResult,
		Target:    target,
		ExitCode:  &exitCode,
		Timestamp: time.Now(),
	}
}

// NewErrorMessage creates an error message
func NewErrorMessage(target, err string) OutboundMessage {
	return OutboundMessage{
		Type:      TypeError,
		Target:    target,
		Error:     err,
		Timestamp: time.Now(),
	}
}

// NewStatusMessage creates a status update message
func NewStatusMessage(workers []WorkerStatus) OutboundMessage {
	data, _ := json.Marshal(StatusUpdate{
		Workers:   workers,
		Timestamp: time.Now(),
	})
	return OutboundMessage{
		Type:      TypeStatus,
		Data:      string(data),
		Timestamp: time.Now(),
	}
}

// ParseInbound parses an inbound WebSocket message
func ParseInbound(data []byte) (*InboundMessage, error) {
	var msg InboundMessage
	if err := json.Unmarshal(data, &msg); err != nil {
		return nil, err
	}
	return &msg, nil
}

// ToJSON serializes an outbound message to JSON
func (m *OutboundMessage) ToJSON() []byte {
	data, _ := json.Marshal(m)
	return data
}
