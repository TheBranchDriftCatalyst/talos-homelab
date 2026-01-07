package agent

import (
	"bytes"
	"context"
	"fmt"
	"log"
	"os"
	"os/exec"
	"strings"
	"time"

	pb "github.com/thebranchdriftcatalyst/carrierarr/pkg/proto"
)

// Executor handles command execution on the worker
type Executor struct {
	// Callbacks for streaming output
	OnStdout func(string)
	OnStderr func(string)
}

// NewExecutor creates a new command executor
func NewExecutor() *Executor {
	return &Executor{}
}

// Execute runs a command and returns the result
func (e *Executor) Execute(ctx context.Context, cmd *pb.Command) *pb.CommandResult {
	startTime := time.Now()

	result := &pb.CommandResult{
		CommandId: cmd.CommandId,
	}

	var err error
	switch cmd.Type {
	case pb.CommandType_COMMAND_TYPE_SHUTDOWN:
		err = e.doShutdown(ctx, cmd.Args)
	case pb.CommandType_COMMAND_TYPE_REBOOT:
		err = e.doReboot(ctx)
	case pb.CommandType_COMMAND_TYPE_DRAIN:
		err = e.doDrain(ctx, cmd.Args)
	case pb.CommandType_COMMAND_TYPE_PULL_MODEL:
		result.Stdout, result.Stderr, result.ExitCode, err = e.doPullModel(ctx, cmd.Args)
	case pb.CommandType_COMMAND_TYPE_UNLOAD_MODEL:
		err = e.doUnloadModel(ctx, cmd.Args)
	case pb.CommandType_COMMAND_TYPE_EXEC:
		result.Stdout, result.Stderr, result.ExitCode, err = e.doExec(ctx, cmd.Args, cmd.TimeoutSeconds)
	case pb.CommandType_COMMAND_TYPE_RESTART_SERVICE:
		err = e.doRestartService(ctx, cmd.Args)
	default:
		err = fmt.Errorf("unknown command type: %v", cmd.Type)
	}

	result.DurationMs = time.Since(startTime).Milliseconds()
	if err != nil {
		result.Success = false
		result.Error = err.Error()
	} else {
		result.Success = true
	}

	log.Printf("[executor] Command %s (%s) completed: success=%v duration=%dms",
		cmd.CommandId, cmd.Type, result.Success, result.DurationMs)

	return result
}

func (e *Executor) doShutdown(ctx context.Context, args map[string]string) error {
	log.Printf("[executor] Initiating shutdown...")

	// Graceful stop of services
	exec.Command("systemctl", "stop", "ollama").Run()
	exec.Command("systemctl", "stop", "k3s-agent").Run()

	// Get delay from args (default 1 minute)
	delay := "1"
	if d, ok := args["delay"]; ok {
		delay = d
	}

	// Schedule shutdown
	cmd := exec.CommandContext(ctx, "shutdown", "-h", "+"+delay)
	return cmd.Run()
}

func (e *Executor) doReboot(ctx context.Context) error {
	log.Printf("[executor] Initiating reboot...")
	cmd := exec.CommandContext(ctx, "shutdown", "-r", "+1")
	return cmd.Run()
}

func (e *Executor) doDrain(ctx context.Context, args map[string]string) error {
	log.Printf("[executor] Draining node...")

	// Get node name
	hostname, _ := os.Hostname()

	// Drain the node
	cmd := exec.CommandContext(ctx, "kubectl", "drain", hostname,
		"--ignore-daemonsets", "--delete-emptydir-data", "--force")
	if output, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("drain failed: %s: %w", string(output), err)
	}

	// Then shutdown
	return e.doShutdown(ctx, args)
}

func (e *Executor) doPullModel(ctx context.Context, args map[string]string) (string, string, int32, error) {
	model, ok := args["model"]
	if !ok {
		return "", "", 1, fmt.Errorf("model argument required")
	}

	log.Printf("[executor] Pulling model: %s", model)

	cmd := exec.CommandContext(ctx, "ollama", "pull", model)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	err := cmd.Run()
	exitCode := int32(0)
	if exitErr, ok := err.(*exec.ExitError); ok {
		exitCode = int32(exitErr.ExitCode())
	}

	return stdout.String(), stderr.String(), exitCode, err
}

func (e *Executor) doUnloadModel(ctx context.Context, args map[string]string) error {
	// Ollama doesn't have a direct unload command
	// The model will be unloaded after idle timeout
	// We can force it by stopping and starting ollama
	log.Printf("[executor] Unloading models (restarting ollama)...")

	if err := exec.CommandContext(ctx, "systemctl", "restart", "ollama").Run(); err != nil {
		return fmt.Errorf("failed to restart ollama: %w", err)
	}

	return nil
}

func (e *Executor) doExec(ctx context.Context, args map[string]string, timeoutSec int32) (string, string, int32, error) {
	cmdStr, ok := args["cmd"]
	if !ok {
		return "", "", 1, fmt.Errorf("cmd argument required")
	}

	log.Printf("[executor] Executing: %s", cmdStr)

	// Apply timeout
	if timeoutSec > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, time.Duration(timeoutSec)*time.Second)
		defer cancel()
	}

	// Split command (simple split, doesn't handle quotes)
	parts := strings.Fields(cmdStr)
	if len(parts) == 0 {
		return "", "", 1, fmt.Errorf("empty command")
	}

	cmd := exec.CommandContext(ctx, parts[0], parts[1:]...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	err := cmd.Run()
	exitCode := int32(0)
	if exitErr, ok := err.(*exec.ExitError); ok {
		exitCode = int32(exitErr.ExitCode())
	} else if ctx.Err() == context.DeadlineExceeded {
		return stdout.String(), stderr.String(), 124, fmt.Errorf("command timed out")
	}

	return stdout.String(), stderr.String(), exitCode, nil
}

func (e *Executor) doRestartService(ctx context.Context, args map[string]string) error {
	service, ok := args["service"]
	if !ok {
		return fmt.Errorf("service argument required")
	}

	// Whitelist of allowed services
	allowed := map[string]bool{
		"ollama":    true,
		"nebula":    true,
		"k3s":       true,
		"k3s-agent": true,
	}

	if !allowed[service] {
		return fmt.Errorf("service %s is not in allowed list", service)
	}

	log.Printf("[executor] Restarting service: %s", service)
	cmd := exec.CommandContext(ctx, "systemctl", "restart", service)
	if output, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("restart failed: %s: %w", string(output), err)
	}

	return nil
}
