// Package process manages subprocess execution with stdout/stderr streaming
package process

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"log"
	"os"
	"os/exec"
	"sync"
	"time"

	"github.com/thebranchdriftcatalyst/carrierarr/pkg/protocol"
)

// OutputHandler is called for each line of output
type OutputHandler func(msg protocol.OutboundMessage)

// Manager handles process execution and output streaming
type Manager struct {
	// WorkerScript is the path to the worker control script
	WorkerScript string

	// OutputHandler receives stdout/stderr messages
	OutputHandler OutputHandler

	// Running processes by target ID
	processes map[string]*runningProcess
	mu        sync.RWMutex
}

type runningProcess struct {
	cmd      *exec.Cmd
	cancel   context.CancelFunc
	target   string
	started  time.Time
	finished bool
}

// New creates a new process manager
func New(workerScript string, handler OutputHandler) *Manager {
	return &Manager{
		WorkerScript:  workerScript,
		OutputHandler: handler,
		processes:     make(map[string]*runningProcess),
	}
}

// Execute runs a command and streams output
func (m *Manager) Execute(ctx context.Context, target, command string, args []string) (int, error) {
	// Build the full command
	fullArgs := append([]string{command}, args...)

	log.Printf("[Process] Executing: %s %v (target: %s)", m.WorkerScript, fullArgs, target)

	// Create command with context
	cmdCtx, cancel := context.WithCancel(ctx)
	cmd := exec.CommandContext(cmdCtx, m.WorkerScript, fullArgs...)

	// Set up environment
	cmd.Env = append(os.Environ(),
		fmt.Sprintf("EC2_AGENT_TARGET=%s", target),
	)

	// Get stdout and stderr pipes
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		cancel()
		return -1, fmt.Errorf("failed to get stdout pipe: %w", err)
	}

	stderr, err := cmd.StderrPipe()
	if err != nil {
		cancel()
		return -1, fmt.Errorf("failed to get stderr pipe: %w", err)
	}

	// Track process
	proc := &runningProcess{
		cmd:     cmd,
		cancel:  cancel,
		target:  target,
		started: time.Now(),
	}

	m.mu.Lock()
	m.processes[target] = proc
	m.mu.Unlock()

	defer func() {
		m.mu.Lock()
		proc.finished = true
		delete(m.processes, target)
		m.mu.Unlock()
	}()

	// Start command
	if err := cmd.Start(); err != nil {
		cancel()
		return -1, fmt.Errorf("failed to start command: %w", err)
	}

	// Stream output in goroutines
	var wg sync.WaitGroup
	wg.Add(2)

	go func() {
		defer wg.Done()
		m.streamOutput(stdout, target, protocol.TypeStdout)
	}()

	go func() {
		defer wg.Done()
		m.streamOutput(stderr, target, protocol.TypeStderr)
	}()

	// Wait for output streaming to complete
	wg.Wait()

	// Wait for command to finish
	err = cmd.Wait()
	exitCode := 0
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			exitCode = exitErr.ExitCode()
		} else {
			return -1, fmt.Errorf("command failed: %w", err)
		}
	}

	// Send result message
	if m.OutputHandler != nil {
		m.OutputHandler(protocol.NewResultMessage(target, exitCode))
	}

	log.Printf("[Process] Command finished: %s %v (exit: %d, duration: %s)",
		m.WorkerScript, fullArgs, exitCode, time.Since(proc.started))

	return exitCode, nil
}

// streamOutput reads from a pipe and sends to handler
func (m *Manager) streamOutput(r io.Reader, target string, msgType protocol.MessageType) {
	scanner := bufio.NewScanner(r)
	// Increase buffer size for long lines
	buf := make([]byte, 64*1024)
	scanner.Buffer(buf, 1024*1024)

	for scanner.Scan() {
		line := scanner.Text()
		if m.OutputHandler != nil {
			var msg protocol.OutboundMessage
			if msgType == protocol.TypeStdout {
				msg = protocol.NewStdoutMessage(target, line)
			} else {
				msg = protocol.NewStderrMessage(target, line)
			}
			m.OutputHandler(msg)
		}
	}

	if err := scanner.Err(); err != nil {
		log.Printf("[Process] Scanner error for %s: %v", target, err)
	}
}

// Kill terminates a running process
func (m *Manager) Kill(target string) error {
	m.mu.RLock()
	proc, ok := m.processes[target]
	m.mu.RUnlock()

	if !ok {
		return fmt.Errorf("no running process for target: %s", target)
	}

	log.Printf("[Process] Killing process for target: %s", target)
	proc.cancel()
	return nil
}

// IsRunning checks if a process is running for a target
func (m *Manager) IsRunning(target string) bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	proc, ok := m.processes[target]
	return ok && !proc.finished
}

// RunningProcesses returns list of running process targets
func (m *Manager) RunningProcesses() []string {
	m.mu.RLock()
	defer m.mu.RUnlock()

	targets := make([]string, 0, len(m.processes))
	for target, proc := range m.processes {
		if !proc.finished {
			targets = append(targets, target)
		}
	}
	return targets
}
