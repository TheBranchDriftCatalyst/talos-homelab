// executor.go - Process execution with WebSocket output streaming
//
// Integrates ec2-agent's process manager for robust subprocess handling
// with real-time output streaming to WebSocket clients.
package main

import (
	"context"
	"encoding/json"
	"log"
	"sync"
	"time"

	"github.com/thebranchdriftcatalyst/ec2-agent/pkg/process"
	"github.com/thebranchdriftcatalyst/ec2-agent/pkg/protocol"
)

// Executor manages worker script execution with output streaming
type Executor struct {
	manager *process.Manager
	hub     *Hub
	mu      sync.RWMutex

	// Track active operations
	activeOps map[string]*Operation
}

// Operation represents a running command
type Operation struct {
	ID        string    `json:"id"`
	Command   string    `json:"command"`
	Target    string    `json:"target"`
	StartTime time.Time `json:"start_time"`
	Done      bool      `json:"done"`
	ExitCode  *int      `json:"exit_code,omitempty"`
}

// CommandOutput is broadcast to WebSocket clients for command output
type CommandOutput struct {
	Type      string    `json:"type"`       // "stdout", "stderr", "result", "error"
	Target    string    `json:"target"`     // e.g., "remote", "local"
	Command   string    `json:"command"`    // e.g., "start", "stop", "status"
	Data      string    `json:"data"`       // Output line or error message
	Timestamp time.Time `json:"timestamp"`
	ExitCode  *int      `json:"exit_code,omitempty"` // For "result" type
}

// NewExecutor creates a new executor with the given worker script
func NewExecutor(workerScript string, hub *Hub) *Executor {
	e := &Executor{
		hub:       hub,
		activeOps: make(map[string]*Operation),
	}

	// Create process manager with output handler that broadcasts to WebSocket
	e.manager = process.New(workerScript, func(msg protocol.OutboundMessage) {
		e.handleOutput(msg)
	})

	return e
}

// handleOutput converts ec2-agent protocol messages to WebSocket broadcasts
func (e *Executor) handleOutput(msg protocol.OutboundMessage) {
	output := CommandOutput{
		Target:    msg.Target,
		Timestamp: msg.Timestamp,
	}

	// Get the command from active operations
	e.mu.RLock()
	if op, ok := e.activeOps[msg.Target]; ok {
		output.Command = op.Command
	}
	e.mu.RUnlock()

	switch msg.Type {
	case protocol.TypeStdout:
		output.Type = "stdout"
		output.Data = msg.Data
		log.Printf("[%s] %s", msg.Target, msg.Data)

	case protocol.TypeStderr:
		output.Type = "stderr"
		output.Data = msg.Data
		log.Printf("[%s] (stderr) %s", msg.Target, msg.Data)

	case protocol.TypeResult:
		output.Type = "result"
		output.ExitCode = msg.ExitCode
		if msg.ExitCode != nil {
			log.Printf("[%s] Command completed with exit code %d", msg.Target, *msg.ExitCode)
		}

		// Mark operation as done
		e.mu.Lock()
		if op, ok := e.activeOps[msg.Target]; ok {
			op.Done = true
			op.ExitCode = msg.ExitCode
		}
		e.mu.Unlock()

	case protocol.TypeError:
		output.Type = "error"
		output.Data = msg.Error
		log.Printf("[%s] Error: %s", msg.Target, msg.Error)

	default:
		return // Skip unknown message types
	}

	// Broadcast to all WebSocket clients
	e.broadcast(output)
}

// broadcast sends output to all WebSocket clients
func (e *Executor) broadcast(output CommandOutput) {
	if e.hub == nil {
		return
	}

	data, err := json.Marshal(output)
	if err != nil {
		return
	}

	select {
	case e.hub.broadcast <- data:
	default:
		// Channel full, skip
	}
}

// Execute runs a command asynchronously and streams output
func (e *Executor) Execute(ctx context.Context, target, command string, args ...string) error {
	// Create operation
	op := &Operation{
		ID:        target + "-" + command,
		Command:   command,
		Target:    target,
		StartTime: time.Now(),
	}

	// Track operation
	e.mu.Lock()
	e.activeOps[target] = op
	e.mu.Unlock()

	// Broadcast start event
	e.broadcast(CommandOutput{
		Type:      "start",
		Target:    target,
		Command:   command,
		Timestamp: time.Now(),
	})

	// Execute in goroutine
	go func() {
		exitCode, err := e.manager.Execute(ctx, target, command, args)
		if err != nil {
			log.Printf("Executor error for %s %s: %v", target, command, err)
			e.broadcast(CommandOutput{
				Type:      "error",
				Target:    target,
				Command:   command,
				Data:      err.Error(),
				Timestamp: time.Now(),
			})
		}

		// Cleanup
		e.mu.Lock()
		if op, ok := e.activeOps[target]; ok {
			op.Done = true
			op.ExitCode = &exitCode
		}
		e.mu.Unlock()
	}()

	return nil
}

// ExecuteSync runs a command synchronously and returns the exit code
func (e *Executor) ExecuteSync(ctx context.Context, target, command string, args ...string) (int, error) {
	// Create operation
	op := &Operation{
		ID:        target + "-" + command,
		Command:   command,
		Target:    target,
		StartTime: time.Now(),
	}

	// Track operation
	e.mu.Lock()
	e.activeOps[target] = op
	e.mu.Unlock()

	defer func() {
		e.mu.Lock()
		delete(e.activeOps, target)
		e.mu.Unlock()
	}()

	// Broadcast start event
	e.broadcast(CommandOutput{
		Type:      "start",
		Target:    target,
		Command:   command,
		Timestamp: time.Now(),
	})

	// Execute synchronously
	exitCode, err := e.manager.Execute(ctx, target, command, args)
	return exitCode, err
}

// Kill terminates a running command
func (e *Executor) Kill(target string) error {
	return e.manager.Kill(target)
}

// IsRunning checks if a command is running for a target
func (e *Executor) IsRunning(target string) bool {
	return e.manager.IsRunning(target)
}

// GetActiveOperations returns currently running operations
func (e *Executor) GetActiveOperations() []Operation {
	e.mu.RLock()
	defer e.mu.RUnlock()

	ops := make([]Operation, 0, len(e.activeOps))
	for _, op := range e.activeOps {
		if !op.Done {
			ops = append(ops, *op)
		}
	}
	return ops
}
