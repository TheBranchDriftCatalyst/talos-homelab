#!/bin/bash
# Mock worker script for testing carrierarr
# Simulates the behavior of llm-worker.sh

set -euo pipefail

COMMAND="${1:-help}"
shift || true

# Simulate state
STATE_FILE="/tmp/mock-worker-state.json"

log_info() { echo "[INFO] $1"; }
log_warn() { echo "[WARN] $1" >&2; }
log_error() { echo "[ERROR] $1" >&2; }

get_state() {
  if [[ -f "$STATE_FILE" ]]; then
    jq -r --arg key "$1" '.[$key] // "unknown"' "$STATE_FILE" 2>/dev/null || echo "unknown"
  else
    echo "unknown"
  fi
}

save_state() {
  if [[ -f "$STATE_FILE" ]]; then
    jq --arg key "$1" --arg value "$2" '.[$key] = $value' "$STATE_FILE" > "${STATE_FILE}.tmp"
    mv "${STATE_FILE}.tmp" "$STATE_FILE"
  else
    echo "{\"$1\": \"$2\"}" > "$STATE_FILE"
  fi
}

case "$COMMAND" in
  start)
    log_info "Starting mock worker..."
    save_state "status" "starting"

    for i in {1..5}; do
      log_info "Initializing... ($i/5)"
      sleep 1
    done

    save_state "status" "running"
    log_info "Mock worker is now running!"
    log_info "Instance ID: i-mock123456789"
    log_info "Public IP: 1.2.3.4"
    log_info "Private IP: 10.0.0.100"
    ;;

  stop)
    log_info "Stopping mock worker..."
    save_state "status" "stopping"

    for i in {1..3}; do
      log_info "Shutting down... ($i/3)"
      sleep 1
    done

    save_state "status" "stopped"
    log_info "Mock worker stopped"
    ;;

  status)
    status=$(get_state "status")
    log_info "Mock worker status: $status"

    case "$status" in
      running)
        echo "Instance: i-mock123456789"
        echo "Type: g4dn.xlarge"
        echo "Public IP: 1.2.3.4"
        echo "Private IP: 10.0.0.100"
        echo "Uptime: 2h 30m"
        ;;
      stopped)
        echo "Instance: i-mock123456789 (stopped)"
        ;;
      *)
        echo "Instance: not provisioned"
        ;;
    esac
    ;;

  logs)
    log_info "Fetching logs..."
    echo "=== Mock Worker Logs ==="
    echo "[2024-01-02 10:00:00] Worker started"
    echo "[2024-01-02 10:00:05] Ollama initialized"
    echo "[2024-01-02 10:00:10] Model llama3.2 loaded"
    echo "[2024-01-02 10:01:00] Received inference request"
    echo "[2024-01-02 10:01:02] Response sent (1.5s)"
    echo "=== End of Logs ==="
    ;;

  provision)
    log_info "Provisioning new mock worker..."
    save_state "status" "provisioning"

    for i in {1..5}; do
      log_info "Creating resources... ($i/5)"
      sleep 1
    done

    save_state "status" "stopped"
    save_state "instance_id" "i-mock$(date +%s)"
    log_info "Mock worker provisioned!"
    ;;

  terminate)
    log_warn "Terminating mock worker..."
    save_state "status" "terminating"
    sleep 2
    rm -f "$STATE_FILE"
    log_info "Mock worker terminated"
    ;;

  stream)
    # Continuous output for testing streaming
    log_info "Starting continuous stream..."
    for i in {1..30}; do
      echo "stdout: Stream message $i"
      echo "stderr: Debug info $i" >&2
      sleep 1
    done
    log_info "Stream complete"
    ;;

  error)
    log_error "Simulating an error condition"
    echo "Something went wrong!" >&2
    exit 1
    ;;

  help|*)
    echo "Mock Worker Control Script"
    echo ""
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  start       Start the mock worker"
    echo "  stop        Stop the mock worker"
    echo "  status      Get worker status"
    echo "  logs        View mock logs"
    echo "  provision   Provision a new worker"
    echo "  terminate   Terminate the worker"
    echo "  stream      Continuous output test"
    echo "  error       Simulate an error"
    ;;
esac
