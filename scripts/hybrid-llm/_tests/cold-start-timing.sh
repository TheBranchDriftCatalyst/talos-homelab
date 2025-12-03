#!/bin/bash
# Cold Start Timing Test for LLM Worker
# Measures time from stop → start → first query response
#
# Usage:
#   ./scripts/hybrid-llm/_tests/cold-start-timing.sh
#
# Prerequisites:
#   - Worker instance provisioned (run llm-worker.sh provision first)
#   - Model already pulled (llama3.2 by default)
#   - AWS CLI configured
#   - SSH key at .output/ssh/hybrid-llm-key.pem

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
LLM_WORKER="$REPO_ROOT/scripts/hybrid-llm/llm-worker.sh"
SSH_KEY="$REPO_ROOT/.output/ssh/hybrid-llm-key.pem"
STATE_FILE="$REPO_ROOT/.output/worker-state.json"

# Configuration
AWS_REGION="${AWS_REGION:-us-west-2}"
MODEL="${TEST_MODEL:-llama3.2}"
TEST_PROMPT="${TEST_PROMPT:-Say hello in one sentence}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
timestamp() { date '+%H:%M:%S'; }

# Get instance info from state file
get_instance_id() {
    jq -r '.instance_id // empty' "$STATE_FILE" 2>/dev/null
}

get_public_ip() {
    local instance_id=$(get_instance_id)
    aws ec2 describe-instances \
        --instance-ids "$instance_id" \
        --query 'Reservations[0].Instances[0].PublicIpAddress' \
        --output text \
        --region "$AWS_REGION" 2>/dev/null
}

wait_for_ssh() {
    local ip=$1
    local timeout=${2:-120}
    local start=$(date +%s)

    while true; do
        if ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=3 -o BatchMode=yes \
            ec2-user@"$ip" "echo ok" 2>/dev/null | grep -q "ok"; then
            return 0
        fi

        local elapsed=$(($(date +%s) - start))
        if [[ $elapsed -ge $timeout ]]; then
            return 1
        fi
        sleep 2
    done
}

wait_for_ollama() {
    local ip=$1
    local timeout=${2:-120}
    local start=$(date +%s)

    while true; do
        if ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=3 \
            ec2-user@"$ip" "curl -s http://localhost:11434/api/tags" 2>/dev/null | grep -q "models"; then
            return 0
        fi

        local elapsed=$(($(date +%s) - start))
        if [[ $elapsed -ge $timeout ]]; then
            return 1
        fi
        sleep 2
    done
}

wait_for_mesh() {
    local ip=$1
    local timeout=${2:-60}
    local start=$(date +%s)

    while true; do
        if ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=3 \
            ec2-user@"$ip" "ping -c 1 10.42.1.1" 2>/dev/null | grep -q "1 received"; then
            return 0
        fi

        local elapsed=$(($(date +%s) - start))
        if [[ $elapsed -ge $timeout ]]; then
            return 1
        fi
        sleep 2
    done
}

run_query() {
    local ip=$1
    local model=$2
    local prompt=$3

    ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ec2-user@"$ip" \
        "curl -s http://localhost:11434/api/generate -d '{\"model\":\"$model\",\"prompt\":\"$prompt\",\"stream\":false}'" 2>/dev/null
}

main() {
    echo "========================================="
    echo "  LLM Worker Cold Start Timing Test"
    echo "========================================="
    echo ""

    # Get instance info
    local instance_id=$(get_instance_id)
    local instance_type=$(jq -r '.instance_type // "unknown"' "$STATE_FILE" 2>/dev/null)

    if [[ -z "$instance_id" ]]; then
        log_error "No worker instance found. Run 'llm-worker.sh provision' first."
        exit 1
    fi

    echo "Instance:     $instance_id ($instance_type)"
    echo "Model:        $MODEL"
    echo "Test prompt:  $TEST_PROMPT"
    echo ""

    # Phase 1: Stop the worker
    log_info "[$(timestamp)] Stopping worker..."
    local stop_start=$(date +%s.%N)

    "$LLM_WORKER" stop 2>&1 | grep -E "(INFO|ERROR)" || true

    local stop_end=$(date +%s.%N)
    local stop_time=$(echo "$stop_end - $stop_start" | bc)
    log_success "[$(timestamp)] Worker stopped (${stop_time}s)"
    echo ""

    # Phase 2: Start the worker
    log_info "[$(timestamp)] Starting worker..."
    local start_begin=$(date +%s.%N)

    "$LLM_WORKER" start 2>&1 &
    local start_pid=$!

    # Wait for instance to get a public IP
    sleep 10
    local public_ip=""
    for i in {1..30}; do
        public_ip=$(get_public_ip)
        if [[ -n "$public_ip" && "$public_ip" != "None" ]]; then
            break
        fi
        sleep 2
    done

    if [[ -z "$public_ip" || "$public_ip" == "None" ]]; then
        log_error "Failed to get public IP"
        kill $start_pid 2>/dev/null
        exit 1
    fi

    local instance_ready=$(date +%s.%N)
    local instance_time=$(echo "$instance_ready - $start_begin" | bc)
    log_success "[$(timestamp)] Instance running (${instance_time}s) - IP: $public_ip"

    # Phase 3: Wait for SSH
    log_info "[$(timestamp)] Waiting for SSH..."
    if wait_for_ssh "$public_ip" 120; then
        local ssh_ready=$(date +%s.%N)
        local ssh_time=$(echo "$ssh_ready - $start_begin" | bc)
        log_success "[$(timestamp)] SSH ready (${ssh_time}s)"
    else
        log_error "SSH timeout"
        kill $start_pid 2>/dev/null
        exit 1
    fi

    # Phase 4: Wait for Ollama API
    log_info "[$(timestamp)] Waiting for Ollama API..."
    if wait_for_ollama "$public_ip" 120; then
        local ollama_ready=$(date +%s.%N)
        local ollama_time=$(echo "$ollama_ready - $start_begin" | bc)
        log_success "[$(timestamp)] Ollama API ready (${ollama_time}s)"
    else
        log_error "Ollama timeout"
        kill $start_pid 2>/dev/null
        exit 1
    fi

    # Phase 5: Wait for Nebula mesh
    log_info "[$(timestamp)] Waiting for Nebula mesh..."
    if wait_for_mesh "$public_ip" 60; then
        local mesh_ready=$(date +%s.%N)
        local mesh_time=$(echo "$mesh_ready - $start_begin" | bc)
        log_success "[$(timestamp)] Nebula mesh ready (${mesh_time}s)"
    else
        log_warn "[$(timestamp)] Nebula mesh not connected (may still work via public IP)"
        mesh_time="N/A"
    fi

    # Phase 6: First query (model loading)
    echo ""
    log_info "[$(timestamp)] Running first query (cold model load)..."
    local query_start=$(date +%s.%N)

    local response=$(run_query "$public_ip" "$MODEL" "$TEST_PROMPT")
    local response_text=$(echo "$response" | jq -r '.response' 2>/dev/null | head -c 100)

    local query_end=$(date +%s.%N)
    local query_time=$(echo "$query_end - $query_start" | bc)
    local total_time=$(echo "$query_end - $start_begin" | bc)

    log_success "[$(timestamp)] First query completed (${query_time}s)"
    echo "Response: ${response_text}..."

    # Phase 7: Second query (warm model)
    echo ""
    log_info "[$(timestamp)] Running second query (warm model)..."
    local query2_start=$(date +%s.%N)

    local response2=$(run_query "$public_ip" "$MODEL" "What is 2+2?")
    local response2_text=$(echo "$response2" | jq -r '.response' 2>/dev/null | head -c 100)

    local query2_end=$(date +%s.%N)
    local query2_time=$(echo "$query2_end - $query2_start" | bc)

    log_success "[$(timestamp)] Second query completed (${query2_time}s)"
    echo "Response: ${response2_text}..."

    # Cleanup
    kill $start_pid 2>/dev/null || true

    # Summary
    echo ""
    echo "========================================="
    echo "           TIMING SUMMARY"
    echo "========================================="
    echo "Instance startup:         ${instance_time}s"
    echo "SSH ready:                ${ssh_time}s"
    echo "Ollama API ready:         ${ollama_time}s"
    echo "Nebula mesh ready:        ${mesh_time}s"
    echo "First query (cold):       ${query_time}s"
    echo "Second query (warm):      ${query2_time}s"
    echo "-----------------------------------------"
    echo "TOTAL (start → response): ${total_time}s"
    echo "========================================="

    # Save results to file
    local results_file="$REPO_ROOT/.output/cold-start-timing-$(date +%Y%m%d-%H%M%S).json"
    cat > "$results_file" << EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "instance_id": "$instance_id",
  "instance_type": "$instance_type",
  "model": "$MODEL",
  "timings": {
    "instance_startup_s": $instance_time,
    "ssh_ready_s": $ssh_time,
    "ollama_ready_s": $ollama_time,
    "mesh_ready_s": ${mesh_time//N\/A/null},
    "first_query_s": $query_time,
    "second_query_s": $query2_time,
    "total_s": $total_time
  }
}
EOF
    echo ""
    log_info "Results saved to: $results_file"
}

main "$@"
