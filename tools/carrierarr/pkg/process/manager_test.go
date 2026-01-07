package process

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/thebranchdriftcatalyst/carrierarr/pkg/protocol"
)

func TestManager_Execute(t *testing.T) {
	// Create a temporary test script
	tmpDir := t.TempDir()
	scriptPath := filepath.Join(tmpDir, "test-worker.sh")

	script := `#!/bin/bash
case "$1" in
  echo)
    echo "stdout: hello"
    echo "stderr: world" >&2
    ;;
  exit-zero)
    echo "success"
    exit 0
    ;;
  exit-one)
    echo "failure" >&2
    exit 1
    ;;
  slow)
    echo "starting"
    sleep 2
    echo "done"
    ;;
  *)
    echo "unknown command: $1"
    exit 1
    ;;
esac
`
	if err := os.WriteFile(scriptPath, []byte(script), 0755); err != nil {
		t.Fatalf("Failed to create test script: %v", err)
	}

	tests := []struct {
		name         string
		command      string
		wantExitCode int
		wantStdout   []string
		wantStderr   []string
	}{
		{
			name:         "echo command",
			command:      "echo",
			wantExitCode: 0,
			wantStdout:   []string{"stdout: hello"},
			wantStderr:   []string{"stderr: world"},
		},
		{
			name:         "exit zero",
			command:      "exit-zero",
			wantExitCode: 0,
			wantStdout:   []string{"success"},
		},
		{
			name:         "exit one",
			command:      "exit-one",
			wantExitCode: 1,
			wantStderr:   []string{"failure"},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var stdout, stderr []string
			var mu sync.Mutex

			handler := func(msg protocol.OutboundMessage) {
				mu.Lock()
				defer mu.Unlock()
				switch msg.Type {
				case protocol.TypeStdout:
					stdout = append(stdout, msg.Data)
				case protocol.TypeStderr:
					stderr = append(stderr, msg.Data)
				}
			}

			mgr := New(scriptPath, handler)
			ctx := context.Background()

			exitCode, err := mgr.Execute(ctx, "test", tt.command, nil)
			if err != nil && tt.wantExitCode == 0 {
				t.Fatalf("Execute() error = %v", err)
			}

			if exitCode != tt.wantExitCode {
				t.Errorf("exitCode = %d, want %d", exitCode, tt.wantExitCode)
			}

			mu.Lock()
			defer mu.Unlock()

			for _, want := range tt.wantStdout {
				found := false
				for _, got := range stdout {
					if strings.Contains(got, want) {
						found = true
						break
					}
				}
				if !found {
					t.Errorf("stdout missing %q, got %v", want, stdout)
				}
			}

			for _, want := range tt.wantStderr {
				found := false
				for _, got := range stderr {
					if strings.Contains(got, want) {
						found = true
						break
					}
				}
				if !found {
					t.Errorf("stderr missing %q, got %v", want, stderr)
				}
			}
		})
	}
}

func TestManager_Kill(t *testing.T) {
	// Create a long-running test script
	tmpDir := t.TempDir()
	scriptPath := filepath.Join(tmpDir, "slow-worker.sh")

	script := `#!/bin/bash
echo "starting"
sleep 30
echo "done"
`
	if err := os.WriteFile(scriptPath, []byte(script), 0755); err != nil {
		t.Fatalf("Failed to create test script: %v", err)
	}

	mgr := New(scriptPath, nil)
	ctx := context.Background()

	// Start the process in a goroutine
	done := make(chan struct{})
	go func() {
		mgr.Execute(ctx, "slow-test", "run", nil)
		close(done)
	}()

	// Wait for process to start
	time.Sleep(100 * time.Millisecond)

	// Verify it's running
	if !mgr.IsRunning("slow-test") {
		t.Error("Process should be running")
	}

	// Kill it
	if err := mgr.Kill("slow-test"); err != nil {
		t.Errorf("Kill() error = %v", err)
	}

	// Wait for it to finish
	select {
	case <-done:
		// OK
	case <-time.After(5 * time.Second):
		t.Error("Process did not terminate after kill")
	}

	// Verify it's not running
	if mgr.IsRunning("slow-test") {
		t.Error("Process should not be running after kill")
	}
}

func TestManager_RunningProcesses(t *testing.T) {
	tmpDir := t.TempDir()
	scriptPath := filepath.Join(tmpDir, "worker.sh")

	script := `#!/bin/bash
sleep 5
`
	if err := os.WriteFile(scriptPath, []byte(script), 0755); err != nil {
		t.Fatalf("Failed to create test script: %v", err)
	}

	mgr := New(scriptPath, nil)
	ctx := context.Background()

	// Start multiple processes
	go mgr.Execute(ctx, "worker-1", "run", nil)
	go mgr.Execute(ctx, "worker-2", "run", nil)

	// Wait for them to start
	time.Sleep(100 * time.Millisecond)

	running := mgr.RunningProcesses()
	if len(running) != 2 {
		t.Errorf("RunningProcesses() = %d, want 2", len(running))
	}

	// Kill them
	mgr.Kill("worker-1")
	mgr.Kill("worker-2")
}
