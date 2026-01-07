package protocol

import (
	"encoding/json"
	"testing"
	"time"
)

func TestParseInbound(t *testing.T) {
	tests := []struct {
		name    string
		input   string
		want    *InboundMessage
		wantErr bool
	}{
		{
			name:  "command message",
			input: `{"type":"command","command":"start","target":"worker-1"}`,
			want: &InboundMessage{
				Type:    TypeCommand,
				Command: "start",
				Target:  "worker-1",
			},
		},
		{
			name:  "command with args",
			input: `{"type":"command","command":"start","args":["--spot","--instance-type","g4dn.xlarge"]}`,
			want: &InboundMessage{
				Type:    TypeCommand,
				Command: "start",
				Args:    []string{"--spot", "--instance-type", "g4dn.xlarge"},
			},
		},
		{
			name:  "subscribe message",
			input: `{"type":"subscribe","target":"*"}`,
			want: &InboundMessage{
				Type:   TypeSubscribe,
				Target: "*",
			},
		},
		{
			name:  "ping message",
			input: `{"type":"ping"}`,
			want: &InboundMessage{
				Type: TypePing,
			},
		},
		{
			name:    "invalid json",
			input:   `{not valid json}`,
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := ParseInbound([]byte(tt.input))
			if (err != nil) != tt.wantErr {
				t.Errorf("ParseInbound() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if tt.wantErr {
				return
			}
			if got.Type != tt.want.Type {
				t.Errorf("Type = %v, want %v", got.Type, tt.want.Type)
			}
			if got.Command != tt.want.Command {
				t.Errorf("Command = %v, want %v", got.Command, tt.want.Command)
			}
			if got.Target != tt.want.Target {
				t.Errorf("Target = %v, want %v", got.Target, tt.want.Target)
			}
		})
	}
}

func TestNewStdoutMessage(t *testing.T) {
	msg := NewStdoutMessage("worker-1", "Hello, World!")

	if msg.Type != TypeStdout {
		t.Errorf("Type = %v, want %v", msg.Type, TypeStdout)
	}
	if msg.Target != "worker-1" {
		t.Errorf("Target = %v, want worker-1", msg.Target)
	}
	if msg.Data != "Hello, World!" {
		t.Errorf("Data = %v, want Hello, World!", msg.Data)
	}
	if msg.Timestamp.IsZero() {
		t.Error("Timestamp should not be zero")
	}
}

func TestNewStderrMessage(t *testing.T) {
	msg := NewStderrMessage("worker-1", "Error occurred")

	if msg.Type != TypeStderr {
		t.Errorf("Type = %v, want %v", msg.Type, TypeStderr)
	}
	if msg.Data != "Error occurred" {
		t.Errorf("Data = %v, want Error occurred", msg.Data)
	}
}

func TestNewResultMessage(t *testing.T) {
	msg := NewResultMessage("worker-1", 0)

	if msg.Type != TypeResult {
		t.Errorf("Type = %v, want %v", msg.Type, TypeResult)
	}
	if msg.ExitCode == nil || *msg.ExitCode != 0 {
		t.Errorf("ExitCode = %v, want 0", msg.ExitCode)
	}

	// Test non-zero exit code
	msg2 := NewResultMessage("worker-1", 1)
	if msg2.ExitCode == nil || *msg2.ExitCode != 1 {
		t.Errorf("ExitCode = %v, want 1", msg2.ExitCode)
	}
}

func TestNewErrorMessage(t *testing.T) {
	msg := NewErrorMessage("worker-1", "Something went wrong")

	if msg.Type != TypeError {
		t.Errorf("Type = %v, want %v", msg.Type, TypeError)
	}
	if msg.Error != "Something went wrong" {
		t.Errorf("Error = %v, want Something went wrong", msg.Error)
	}
}

func TestNewStatusMessage(t *testing.T) {
	now := time.Now()
	workers := []WorkerStatus{
		{
			ID:       "i-12345",
			Name:     "llm-worker",
			Provider: "ec2",
			State:    "running",
		},
	}

	msg := NewStatusMessage(workers)

	if msg.Type != TypeStatus {
		t.Errorf("Type = %v, want %v", msg.Type, TypeStatus)
	}

	// Parse the data
	var status StatusUpdate
	if err := json.Unmarshal([]byte(msg.Data), &status); err != nil {
		t.Fatalf("Failed to parse status data: %v", err)
	}

	if len(status.Workers) != 1 {
		t.Errorf("Workers count = %d, want 1", len(status.Workers))
	}
	if status.Workers[0].ID != "i-12345" {
		t.Errorf("Worker ID = %v, want i-12345", status.Workers[0].ID)
	}
	if status.Timestamp.Before(now) {
		t.Error("Timestamp should be after test start")
	}
}

func TestOutboundMessageToJSON(t *testing.T) {
	msg := NewStdoutMessage("worker-1", "test output")
	data := msg.ToJSON()

	var parsed OutboundMessage
	if err := json.Unmarshal(data, &parsed); err != nil {
		t.Fatalf("Failed to parse JSON: %v", err)
	}

	if parsed.Type != TypeStdout {
		t.Errorf("Type = %v, want %v", parsed.Type, TypeStdout)
	}
	if parsed.Data != "test output" {
		t.Errorf("Data = %v, want test output", parsed.Data)
	}
}
