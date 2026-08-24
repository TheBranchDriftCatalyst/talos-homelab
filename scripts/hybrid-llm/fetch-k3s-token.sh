#!/bin/bash
# Fetch k3s token from lighthouse for GPU worker to join
#
# Usage:
#   ./scripts/hybrid-llm/fetch-k3s-token.sh
#   ./scripts/hybrid-llm/fetch-k3s-token.sh --save  # Save to .output/k3s-token

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUTPUT_DIR="$REPO_ROOT/.output"
SSH_KEY="$OUTPUT_DIR/ssh/hybrid-llm-key.pem"
STATE_FILE="$OUTPUT_DIR/lighthouse-state.json"
TOKEN_FILE="$OUTPUT_DIR/k3s-token"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Parse arguments
SAVE_TOKEN=false
if [[ "${1:-}" == "--save" ]]; then
  SAVE_TOKEN=true
fi

# Get lighthouse IP
if [[ ! -f "$STATE_FILE" ]]; then
  log_error "Lighthouse state file not found: $STATE_FILE"
  log_error "Run provision-lighthouse.sh first"
  exit 1
fi

LIGHTHOUSE_IP=$(jq -r '.elastic_ip' "$STATE_FILE")
if [[ -z "$LIGHTHOUSE_IP" || "$LIGHTHOUSE_IP" == "null" ]]; then
  log_error "Could not get lighthouse IP from state file"
  exit 1
fi

# Check SSH key
if [[ ! -f "$SSH_KEY" ]]; then
  log_error "SSH key not found: $SSH_KEY"
  exit 1
fi

log_info "Fetching k3s token from lighthouse at $LIGHTHOUSE_IP..."

# Fetch token via SSH
TOKEN=$(ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 \
  -i "$SSH_KEY" "ec2-user@$LIGHTHOUSE_IP" \
  "sudo cat /var/lib/rancher/k3s/server/node-token" 2> /dev/null)

if [[ -z "$TOKEN" ]]; then
  log_error "Failed to fetch token. Is k3s running on the lighthouse?"
  log_warn "SSH to lighthouse and check: sudo systemctl status k3s"
  exit 1
fi

if [[ "$SAVE_TOKEN" == "true" ]]; then
  echo "$TOKEN" > "$TOKEN_FILE"
  chmod 600 "$TOKEN_FILE"
  log_info "Token saved to: $TOKEN_FILE"
else
  echo "$TOKEN"
fi

log_info "Token fetched successfully"
log_info ""
log_info "To generate worker userdata:"
log_info "  K3S_TOKEN='$TOKEN' ./scripts/hybrid-llm/worker-userdata.sh > /tmp/worker-userdata.sh"
