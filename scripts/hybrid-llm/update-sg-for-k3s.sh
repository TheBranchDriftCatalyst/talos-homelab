#!/bin/bash
# Update existing lighthouse security group with k3s ports
#
# Run this if you already have a lighthouse provisioned and need to add
# the k3s API and kubelet ports for GPU workers to join.
#
# Usage:
#   ./scripts/hybrid-llm/update-sg-for-k3s.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
STATE_FILE="$REPO_ROOT/.output/lighthouse-state.json"

AWS_REGION="${AWS_REGION:-us-west-2}"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Get security group ID from state
if [[ ! -f "$STATE_FILE" ]]; then
  log_error "State file not found: $STATE_FILE"
  log_error "Run provision-lighthouse.sh first"
  exit 1
fi

SG_ID=$(jq -r '.security_group_id' "$STATE_FILE")
if [[ -z "$SG_ID" || "$SG_ID" == "null" ]]; then
  log_error "Could not get security group ID from state file"
  exit 1
fi

log_info "Updating security group: $SG_ID"

# Helper to add rule if it doesn't exist
add_rule() {
  local protocol="$1"
  local port="$2"
  local cidr="$3"
  local desc="$4"

  # Check if rule already exists
  existing=$(aws ec2 describe-security-groups \
    --group-ids "$SG_ID" \
    --region "$AWS_REGION" \
    --query "SecurityGroups[0].IpPermissions[?FromPort==\`$port\` && ToPort==\`$port\` && IpProtocol==\`$protocol\`]" \
    --output text 2> /dev/null || echo "")

  if [[ -n "$existing" ]]; then
    log_info "  Rule already exists: $desc (port $port/$protocol)"
  else
    log_info "  Adding rule: $desc (port $port/$protocol from $cidr)"
    aws ec2 authorize-security-group-ingress \
      --group-id "$SG_ID" \
      --protocol "$protocol" \
      --port "$port" \
      --cidr "$cidr" \
      --region "$AWS_REGION" 2> /dev/null || log_warn "  Rule may already exist"
  fi
}

# Add k3s-related rules
log_info "Adding k3s ports for GPU worker connectivity..."

add_rule "tcp" "6443" "10.42.0.0/16" "k3s API server"
add_rule "tcp" "10250" "10.42.0.0/16" "Kubelet API"
add_rule "udp" "8472" "10.42.0.0/16" "Flannel VXLAN"

log_info ""
log_info "Security group updated!"
log_info ""
log_info "Current rules:"
aws ec2 describe-security-groups \
  --group-ids "$SG_ID" \
  --region "$AWS_REGION" \
  --query 'SecurityGroups[0].IpPermissions[*].{Port:FromPort,Protocol:IpProtocol,CIDR:IpRanges[0].CidrIp}' \
  --output table
