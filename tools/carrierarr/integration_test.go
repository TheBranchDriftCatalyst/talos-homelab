// +build integration

package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/gorilla/websocket"
	"github.com/thebranchdriftcatalyst/ec2-agent/pkg/hub"
	"github.com/thebranchdriftcatalyst/ec2-agent/pkg/process"
	"github.com/thebranchdriftcatalyst/ec2-agent/pkg/protocol"
)

// TestIntegration_WebSocketFlow tests the complete WebSocket flow
func TestIntegration_WebSocketFlow(t *testing.T) {
	// Create test script
	tmpDir := t.TempDir()
	scriptPath := filepath.Join(tmpDir, "test-worker.sh")

	script := `#!/bin/bash
case "$1" in
  status)
    echo "Worker status: running"
    echo "Instance: i-test12345"
    ;;
  start)
    echo "Starting worker..."
    sleep 1
    echo "Worker started!"
    ;;
  stream)
    for i in 1 2 3; do
      echo "Message $i"
      echo "Debug $i" >&2
      sleep 0.1
    done
    ;;
  *)
    echo "Unknown: $1" >&2
    exit 1
    ;;
esac
`
	if err := os.WriteFile(scriptPath, []byte(script), 0755); err != nil {
		t.Fatalf("Failed to create test script: %v", err)
	}

	// Create hub
	h := hub.New()
	go h.Run()

	// Create process manager
	procMgr := process.New(scriptPath, func(msg protocol.OutboundMessage) {
		h.Broadcast <- msg
	})

	// Create test server
	upgrader := websocket.Upgrader{
		CheckOrigin: func(r *http.Request) bool { return true },
	}

	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			t.Logf("Upgrade error: %v", err)
			return
		}
		defer conn.Close()

		client := h.NewClient(conn)
		client.Subscribe("*")

		go client.WritePump()
		client.ReadPump()
	})

	server := httptest.NewServer(handler)
	defer server.Close()

	// Handle inbound messages
	go func() {
		for msg := range h.Inbound {
			if msg.Message.Type == protocol.TypeCommand {
				target := msg.Message.Target
				if target == "" {
					target = "default"
				}
				go procMgr.Execute(context.Background(), target, msg.Message.Command, msg.Message.Args)
			}
		}
	}()

	// Connect WebSocket client
	wsURL := "ws" + strings.TrimPrefix(server.URL, "http") + "/"
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatalf("Failed to connect: %v", err)
	}
	defer conn.Close()

	// Collect messages
	var received []protocol.OutboundMessage
	var mu sync.Mutex
	done := make(chan struct{})

	go func() {
		for {
			_, data, err := conn.ReadMessage()
			if err != nil {
				close(done)
				return
			}
			// Handle batched messages
			for _, msgStr := range strings.Split(string(data), "\n") {
				if msgStr == "" {
					continue
				}
				var msg protocol.OutboundMessage
				if err := json.Unmarshal([]byte(msgStr), &msg); err != nil {
					continue
				}
				mu.Lock()
				received = append(received, msg)
				mu.Unlock()
			}
		}
	}()

	// Send status command
	cmd := protocol.InboundMessage{
		Type:    protocol.TypeCommand,
		Command: "status",
		Target:  "test-worker",
	}
	cmdData, _ := json.Marshal(cmd)
	if err := conn.WriteMessage(websocket.TextMessage, cmdData); err != nil {
		t.Fatalf("Failed to send command: %v", err)
	}

	// Wait for response
	time.Sleep(500 * time.Millisecond)

	mu.Lock()
	defer mu.Unlock()

	// Verify we got output
	if len(received) == 0 {
		t.Error("Expected to receive messages")
	}

	// Check for stdout messages
	hasStdout := false
	for _, msg := range received {
		if msg.Type == protocol.TypeStdout {
			hasStdout = true
			t.Logf("Received stdout: %s", msg.Data)
		}
	}

	if !hasStdout {
		t.Error("Expected stdout messages")
	}
}

// TestIntegration_HTTPEndpoints tests the HTTP API
func TestIntegration_HTTPEndpoints(t *testing.T) {
	h := hub.New()
	go h.Run()

	// Health endpoint
	healthHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"status":  "healthy",
			"clients": h.ClientCount(),
		})
	})

	// Status endpoint
	statusHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"workers":   []protocol.WorkerStatus{},
			"timestamp": time.Now(),
		})
	})

	mux := http.NewServeMux()
	mux.Handle("/health", healthHandler)
	mux.Handle("/api/status", statusHandler)

	server := httptest.NewServer(mux)
	defer server.Close()

	// Test health endpoint
	resp, err := http.Get(server.URL + "/health")
	if err != nil {
		t.Fatalf("Health request failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("Health status = %d, want 200", resp.StatusCode)
	}

	var health map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&health); err != nil {
		t.Fatalf("Failed to decode health response: %v", err)
	}

	if health["status"] != "healthy" {
		t.Errorf("Health status = %v, want healthy", health["status"])
	}

	// Test status endpoint
	resp2, err := http.Get(server.URL + "/api/status")
	if err != nil {
		t.Fatalf("Status request failed: %v", err)
	}
	defer resp2.Body.Close()

	if resp2.StatusCode != http.StatusOK {
		t.Errorf("Status status = %d, want 200", resp2.StatusCode)
	}
}
