#!/bin/bash
# Cold Start Timing Test for LLM Worker
# Measures time from stop -> start -> first query response via Nebula mesh
#
# Usage:
#   ./cold-start-timing.sh [--model MODEL] [--skip-stop]
#
# Examples:
#   ./cold-start-timing.sh                    # Full cycle with llama3.2
#   ./cold-start-timing.sh --model mistral    # Use different model
#   ./cold-start-timing.sh --skip-stop        # Start from stopped state (no stop phase)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Configuration
MODEL="${TEST_MODEL:-llama3.2}"
TEST_PROMPT="${TEST_PROMPT:-Say hello in one sentence}"
NEBULA_IP="10.42.2.1"
OLLAMA_PORT="11434"
SKIP_STOP=false

# Parse args
while [[ $# -gt 0 ]]; do
  case $1 in
    --model)
      MODEL="$2"
      shift 2
      ;;
    --skip-stop)
      SKIP_STOP=true
      shift
      ;;
    *) shift ;;
  esac
done

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_phase() { echo -e "\n${CYAN}=== $1 ===${NC}"; }
timestamp() { date '+%H:%M:%S'; }

# Get worker status via kubectl
get_worker_status() {
  kubectl exec -n catalyst-llm deploy/llm-proxy -- /app/llm-worker.sh status 2> /dev/null | grep "State:" | awk '{print $2}' | sed 's/\x1b\[[0-9;]*m//g'
}

# Start worker via kubectl
start_worker() {
  kubectl exec -n catalyst-llm deploy/llm-proxy -- /app/llm-worker.sh start 2>&1
}

# Stop worker via kubectl
stop_worker() {
  kubectl exec -n catalyst-llm deploy/llm-proxy -- /app/llm-worker.sh stop 2>&1
}

# Check if Ollama is reachable via Nebula from inside cluster
check_ollama_via_nebula() {
  kubectl exec -n catalyst-llm deploy/llm-proxy -- curl -s --connect-timeout 3 "http://${NEBULA_IP}:${OLLAMA_PORT}/api/tags" 2> /dev/null | grep -q "models"
}

# Run query via Nebula mesh from inside cluster
run_query_via_nebula() {
  local model=$1
  local prompt=$2
  kubectl exec -n catalyst-llm deploy/llm-proxy -- curl -s --max-time 120 \
    "http://${NEBULA_IP}:${OLLAMA_PORT}/api/generate" \
    -d "{\"model\":\"$model\",\"prompt\":\"$prompt\",\"stream\":false}" 2> /dev/null
}

# Wait for Ollama to be ready via Nebula
wait_for_ollama() {
  local timeout=${1:-180}
  local start=$(date +%s)

  while true; do
    if check_ollama_via_nebula; then
      return 0
    fi

    local elapsed=$(($(date +%s) - start))
    if [[ $elapsed -ge $timeout ]]; then
      return 1
    fi
    echo -n "."
    sleep 3
  done
}

main() {
  echo "========================================="
  echo "  LLM Worker Cold Start Timing Test"
  echo "========================================="
  echo ""
  echo "Model:         $MODEL"
  echo "Test prompt:   $TEST_PROMPT"
  echo "Nebula IP:     $NEBULA_IP"
  echo ""

  # Check current status
  local current_status=$(get_worker_status)
  log_info "Current worker status: $current_status"

  local stop_time="N/A"
  local start_time="N/A"
  local ssh_time="N/A"
  local ollama_time="N/A"
  local mesh_time="N/A"
  local query1_time="N/A"
  local query2_time="N/A"
  local total_time="N/A"

  # Phase 1: Stop (if not skipping and currently running)
  if [[ "$SKIP_STOP" == "false" ]] && [[ "$current_status" == *"Running"* ]]; then
    log_phase "PHASE 1: Stopping Worker"
    local stop_start=$(date +%s.%N)

    stop_worker | grep -E "(INFO|Stopping|stopped)" || true

    local stop_end=$(date +%s.%N)
    stop_time=$(echo "$stop_end - $stop_start" | bc)
    log_success "[$(timestamp)] Worker stopped in ${stop_time}s"
  elif [[ "$SKIP_STOP" == "true" ]]; then
    log_info "Skipping stop phase (--skip-stop)"
  else
    log_info "Worker already stopped"
  fi

  # Phase 2: Start
  log_phase "PHASE 2: Starting Worker"
  local start_begin=$(date +%s.%N)

  # Start in background
  start_worker &
  local start_pid=$!

  # Poll for instance running
  log_info "[$(timestamp)] Waiting for EC2 instance..."
  local instance_running=false
  for i in {1..60}; do
    local status=$(get_worker_status 2> /dev/null || echo "unknown")
    if [[ "$status" == *"Running"* ]]; then
      instance_running=true
      break
    fi
    sleep 2
  done

  if [[ "$instance_running" == "false" ]]; then
    log_error "Instance failed to start"
    kill $start_pid 2> /dev/null || true
    exit 1
  fi

  local instance_ready=$(date +%s.%N)
  start_time=$(echo "$instance_ready - $start_begin" | bc)
  log_success "[$(timestamp)] Instance running (${start_time}s)"

  # Phase 3: Wait for Ollama via Nebula
  log_phase "PHASE 3: Waiting for Ollama API via Nebula"
  log_info "[$(timestamp)] Polling http://${NEBULA_IP}:${OLLAMA_PORT}..."

  if wait_for_ollama 180; then
    echo ""
    local ollama_ready=$(date +%s.%N)
    ollama_time=$(echo "$ollama_ready - $start_begin" | bc)
    log_success "[$(timestamp)] Ollama ready via Nebula (${ollama_time}s)"
  else
    echo ""
    log_error "Ollama timeout via Nebula"
    kill $start_pid 2> /dev/null || true
    exit 1
  fi

  # Phase 4: First query (cold model load)
  log_phase "PHASE 4: First Query (Cold Model Load)"
  log_info "[$(timestamp)] Running: $TEST_PROMPT"
  local query1_start=$(date +%s.%N)

  local response=$(run_query_via_nebula "$MODEL" "$TEST_PROMPT")
  local response_text=$(echo "$response" | jq -r '.response // "error"' 2> /dev/null | head -c 100)

  local query1_end=$(date +%s.%N)
  query1_time=$(echo "$query1_end - $query1_start" | bc)
  total_time=$(echo "$query1_end - $start_begin" | bc)

  log_success "[$(timestamp)] First query completed (${query1_time}s)"
  echo -e "Response: ${GREEN}${response_text}...${NC}"

  # Phase 5: Second query (warm model)
  log_phase "PHASE 5: Second Query (Warm Model)"
  local query2_start=$(date +%s.%N)

  local response2=$(run_query_via_nebula "$MODEL" "What is 2+2?")
  local response2_text=$(echo "$response2" | jq -r '.response // "error"' 2> /dev/null | head -c 100)

  local query2_end=$(date +%s.%N)
  query2_time=$(echo "$query2_end - $query2_start" | bc)

  log_success "[$(timestamp)] Second query completed (${query2_time}s)"
  echo -e "Response: ${GREEN}${response2_text}...${NC}"

  # Cleanup background process
  kill $start_pid 2> /dev/null || true

  # Summary
  echo ""
  echo "========================================="
  echo "           TIMING SUMMARY"
  echo "========================================="
  printf "%-25s %s\n" "Stop worker:" "${stop_time}s"
  printf "%-25s %s\n" "Instance startup:" "${start_time}s"
  printf "%-25s %s\n" "Ollama ready (via Nebula):" "${ollama_time}s"
  printf "%-25s %s\n" "First query (cold):" "${query1_time}s"
  printf "%-25s %s\n" "Second query (warm):" "${query2_time}s"
  echo "-----------------------------------------"
  printf "%-25s ${GREEN}%s${NC}\n" "TOTAL (start->response):" "${total_time}s"
  echo "========================================="

  # Save results
  local results_dir="$SCRIPT_DIR/.output"
  mkdir -p "$results_dir"
  local results_file="$results_dir/cold-start-$(date +%Y%m%d-%H%M%S).json"

  cat > "$results_file" << EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "model": "$MODEL",
  "nebula_ip": "$NEBULA_IP",
  "timings": {
    "stop_s": ${stop_time//N\/A/null},
    "instance_startup_s": ${start_time//N\/A/null},
    "ollama_ready_s": ${ollama_time//N\/A/null},
    "first_query_s": ${query1_time//N\/A/null},
    "second_query_s": ${query2_time//N\/A/null},
    "total_s": ${total_time//N\/A/null}
  }
}
EOF
  echo ""
  log_info "Results saved to: $results_file"
}

main "$@"
