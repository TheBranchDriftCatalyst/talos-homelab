#!/bin/bash
# =============================================================================
# AWS GPU Cluster Orchestration Script
# =============================================================================
# Complete automation for provisioning the AWS k3s + Liqo cluster and
# establishing peering with the homelab Talos cluster.
#
# This script:
#   1. Tears down existing lighthouse (if any)
#   2. Provisions new lighthouse with Nebula + k3s + Liqo
#   3. Waits for cloud-init to complete
#   4. Fetches credentials (k3s token, Liqo peering info)
#   5. Creates secrets in homelab cluster
#   6. Establishes Liqo peering
#   7. Verifies the peering is working
#
# Usage:
#   ./scripts/hybrid-llm/orchestrate-aws-cluster.sh
#   ./scripts/hybrid-llm/orchestrate-aws-cluster.sh --skip-teardown
#   ./scripts/hybrid-llm/orchestrate-aws-cluster.sh --dry-run
#
# Prerequisites:
#   - AWS CLI configured
#   - kubectl configured for homelab cluster
#   - nebula-cert installed
#   - Nebula CA generated (~/.nebula-ca/ca.crt)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Configuration
AWS_REGION="${AWS_REGION:-us-west-2}"
LIGHTHOUSE_INSTANCE_TYPE="${LIGHTHOUSE_INSTANCE_TYPE:-t3.small}"
OUTPUT_DIR="$REPO_ROOT/.output"
SSH_KEY="$OUTPUT_DIR/ssh/hybrid-llm-key.pem"
STATE_FILE="$OUTPUT_DIR/lighthouse-state.json"
SECRETS_DIR="$OUTPUT_DIR/aws-cluster-secrets"

# Homelab cluster context (for kubectl)
HOMELAB_CONTEXT="${HOMELAB_CONTEXT:-talos-homelab}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log_step() {
  echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${CYAN}▶ $1${NC}"
  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}
log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_debug() { [[ "${DEBUG:-false}" == "true" ]] && echo -e "[DEBUG] $1" || true; }

# Parse arguments
DRY_RUN=false
SKIP_TEARDOWN=false
SKIP_PEERING=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --skip-teardown)
      SKIP_TEARDOWN=true
      shift
      ;;
    --skip-peering)
      SKIP_PEERING=true
      shift
      ;;
    --debug)
      DEBUG=true
      shift
      ;;
    -h | --help)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --dry-run        Show what would be done without making changes"
      echo "  --skip-teardown  Don't teardown existing lighthouse"
      echo "  --skip-peering   Provision only, skip Liqo peering setup"
      echo "  --debug          Enable debug output"
      echo "  -h, --help       Show this help message"
      exit 0
      ;;
    *)
      log_error "Unknown option: $1"
      exit 1
      ;;
  esac
done

# =============================================================================
# Helper Functions
# =============================================================================

ssh_lighthouse() {
  local lighthouse_ip="$1"
  shift
  ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -o BatchMode=yes \
    -i "$SSH_KEY" "ec2-user@$lighthouse_ip" "$@"
}

wait_for_ssh() {
  local ip="$1"
  local max_attempts="${2:-30}"

  log_info "Waiting for SSH access to $ip..."
  for i in $(seq 1 "$max_attempts"); do
    if ssh_lighthouse "$ip" "echo 'SSH OK'" 2> /dev/null; then
      log_info "SSH is available"
      return 0
    fi
    echo -n "."
    sleep 10
  done
  echo ""
  log_error "SSH not available after $max_attempts attempts"
  return 1
}

wait_for_cloud_init() {
  local ip="$1"
  local max_attempts="${2:-60}"

  log_info "Waiting for cloud-init to complete (this may take 5-10 minutes)..."
  for i in $(seq 1 "$max_attempts"); do
    status=$(ssh_lighthouse "$ip" "sudo cloud-init status" 2> /dev/null || echo "unknown")
    if echo "$status" | grep -q "done"; then
      log_info "Cloud-init completed successfully"
      return 0
    elif echo "$status" | grep -q "error"; then
      log_error "Cloud-init failed!"
      ssh_lighthouse "$ip" "sudo cat /var/log/lighthouse-bootstrap.log | tail -50" 2> /dev/null || true
      return 1
    fi
    printf "\r  Progress: attempt %d/%d - status: %s" "$i" "$max_attempts" "$status"
    sleep 10
  done
  echo ""
  log_warn "Cloud-init timeout - checking status..."
  ssh_lighthouse "$ip" "sudo cloud-init status --long" 2> /dev/null || true
  return 1
}

wait_for_k3s() {
  local ip="$1"
  local max_attempts="${2:-30}"

  log_info "Waiting for k3s to be ready..."
  for i in $(seq 1 "$max_attempts"); do
    if ssh_lighthouse "$ip" "sudo kubectl get nodes 2>/dev/null | grep -q Ready"; then
      log_info "k3s is ready"
      return 0
    fi
    echo -n "."
    sleep 5
  done
  echo ""
  log_error "k3s not ready after $max_attempts attempts"
  return 1
}

wait_for_liqo() {
  local ip="$1"
  local max_attempts="${2:-30}"

  log_info "Waiting for Liqo pods to be ready..."
  for i in $(seq 1 "$max_attempts"); do
    ready=$(ssh_lighthouse "$ip" "sudo kubectl get pods -n liqo-system --no-headers 2>/dev/null | grep -c Running" || echo "0")
    total=$(ssh_lighthouse "$ip" "sudo kubectl get pods -n liqo-system --no-headers 2>/dev/null | wc -l" || echo "0")

    if [[ "$ready" -gt 0 && "$ready" == "$total" ]]; then
      log_info "Liqo is ready ($ready/$total pods running)"
      return 0
    fi
    printf "\r  Progress: %s/%s pods ready" "$ready" "$total"
    sleep 10
  done
  echo ""
  log_warn "Some Liqo pods may not be ready"
  return 0 # Don't fail, Liqo might still work
}

# =============================================================================
# Step 1: Teardown existing lighthouse
# =============================================================================

step_teardown() {
  log_step "Step 1: Teardown Existing Lighthouse"

  if [[ "$SKIP_TEARDOWN" == "true" ]]; then
    log_info "Skipping teardown (--skip-teardown)"
    return 0
  fi

  if [[ ! -f "$STATE_FILE" ]]; then
    log_info "No existing lighthouse found (no state file)"
    return 0
  fi

  local instance_id=$(jq -r '.instance_id // empty' "$STATE_FILE")
  if [[ -z "$instance_id" ]]; then
    log_info "No instance ID in state file"
    return 0
  fi

  log_info "Found existing lighthouse: $instance_id"

  if [[ "$DRY_RUN" == "true" ]]; then
    log_info "[DRY-RUN] Would teardown lighthouse"
    return 0
  fi

  "$SCRIPT_DIR/provision-lighthouse.sh" --teardown
  log_info "Teardown complete"
}

# =============================================================================
# Step 2: Provision new lighthouse
# =============================================================================

step_provision() {
  log_step "Step 2: Provision New Lighthouse (Nebula + k3s + Liqo)"

  if [[ "$DRY_RUN" == "true" ]]; then
    log_info "[DRY-RUN] Would provision lighthouse with:"
    log_info "  Instance type: $LIGHTHOUSE_INSTANCE_TYPE"
    log_info "  Region: $AWS_REGION"
    return 0
  fi

  LIGHTHOUSE_INSTANCE_TYPE="$LIGHTHOUSE_INSTANCE_TYPE" \
    AWS_REGION="$AWS_REGION" \
    "$SCRIPT_DIR/provision-lighthouse.sh"

  log_info "Lighthouse provisioned"
}

# =============================================================================
# Step 3: Wait for services to be ready
# =============================================================================

step_wait_for_services() {
  log_step "Step 3: Wait for Services to Initialize"

  if [[ "$DRY_RUN" == "true" ]]; then
    log_info "[DRY-RUN] Would wait for cloud-init, k3s, and Liqo"
    return 0
  fi

  local lighthouse_ip=$(jq -r '.elastic_ip' "$STATE_FILE")

  wait_for_ssh "$lighthouse_ip"
  wait_for_cloud_init "$lighthouse_ip"
  wait_for_k3s "$lighthouse_ip"
  wait_for_liqo "$lighthouse_ip"

  log_info "All services are ready"
}

# =============================================================================
# Step 4: Fetch credentials and create secrets
# =============================================================================

step_fetch_credentials() {
  log_step "Step 4: Fetch Credentials from AWS Cluster"

  if [[ "$DRY_RUN" == "true" ]]; then
    log_info "[DRY-RUN] Would fetch k3s token, kubeconfig, and Liqo peering info"
    return 0
  fi

  local lighthouse_ip=$(jq -r '.elastic_ip' "$STATE_FILE")
  mkdir -p "$SECRETS_DIR"
  chmod 700 "$SECRETS_DIR"

  # Fetch k3s token
  log_info "Fetching k3s node token..."
  ssh_lighthouse "$lighthouse_ip" "sudo cat /var/lib/rancher/k3s/server/node-token" > "$SECRETS_DIR/k3s-token"
  chmod 600 "$SECRETS_DIR/k3s-token"
  # Also save to standard location for worker provisioning
  cp "$SECRETS_DIR/k3s-token" "$OUTPUT_DIR/k3s-token"

  # Fetch kubeconfig (modify server URL to use Nebula mesh IP)
  log_info "Fetching kubeconfig..."
  ssh_lighthouse "$lighthouse_ip" "sudo cat /etc/rancher/k3s/k3s.yaml" |
    sed "s|server: https://127.0.0.1:6443|server: https://10.42.0.1:6443|g" > "$SECRETS_DIR/kubeconfig"
  chmod 600 "$SECRETS_DIR/kubeconfig"

  # Fetch Liqo cluster ID and auth token
  log_info "Fetching Liqo cluster info..."

  # Get cluster ID
  local cluster_id=$(ssh_lighthouse "$lighthouse_ip" \
    "sudo kubectl get configmap -n liqo-system liqo-clusterid-configmap -o jsonpath='{.data.CLUSTER_ID}'" 2> /dev/null || echo "")
  echo "$cluster_id" > "$SECRETS_DIR/liqo-cluster-id"

  # Get auth token (for out-of-band peering)
  local auth_token=$(ssh_lighthouse "$lighthouse_ip" \
    "sudo kubectl get secret -n liqo-system liqo-auth-token -o jsonpath='{.data.token}' 2>/dev/null | base64 -d" 2> /dev/null || echo "")
  echo "$auth_token" > "$SECRETS_DIR/liqo-auth-token"
  chmod 600 "$SECRETS_DIR/liqo-auth-token"

  # Get the peering endpoint (auth service URL)
  local auth_url="https://10.42.0.1:5443" # Default Liqo auth port via Nebula
  echo "$auth_url" > "$SECRETS_DIR/liqo-auth-url"

  # Generate liqoctl peer command
  log_info "Generating Liqo peer command..."
  ssh_lighthouse "$lighthouse_ip" \
    "sudo /usr/local/bin/liqoctl generate peer-command --only-command 2>/dev/null" > "$SECRETS_DIR/liqo-peer-command.txt" || true

  log_info "Credentials saved to: $SECRETS_DIR/"
  ls -la "$SECRETS_DIR/"
}

# =============================================================================
# Step 5: Create secrets in homelab cluster
# =============================================================================

step_create_homelab_secrets() {
  log_step "Step 5: Create Secrets in Homelab Cluster"

  if [[ "$DRY_RUN" == "true" ]]; then
    log_info "[DRY-RUN] Would create secrets in homelab cluster"
    return 0
  fi

  # Check if we can access homelab cluster
  if ! kubectl --context="$HOMELAB_CONTEXT" get nodes &> /dev/null; then
    log_warn "Cannot access homelab cluster with context '$HOMELAB_CONTEXT'"
    log_warn "Skipping homelab secret creation. You can manually create secrets later."
    log_info "Secrets are available in: $SECRETS_DIR/"
    return 0
  fi

  local lighthouse_ip=$(jq -r '.elastic_ip' "$STATE_FILE")
  local cluster_id=$(cat "$SECRETS_DIR/liqo-cluster-id")
  local auth_token=$(cat "$SECRETS_DIR/liqo-auth-token" 2> /dev/null || echo "")

  log_info "Creating/updating secrets in homelab cluster..."

  # Ensure liqo-system namespace exists
  kubectl --context="$HOMELAB_CONTEXT" create namespace liqo-system 2> /dev/null || true

  # Create secret with AWS cluster credentials
  kubectl --context="$HOMELAB_CONTEXT" create secret generic aws-gpu-cluster-credentials \
    --namespace=liqo-system \
    --from-file=kubeconfig="$SECRETS_DIR/kubeconfig" \
    --from-file=k3s-token="$SECRETS_DIR/k3s-token" \
    --from-literal=cluster-id="$cluster_id" \
    --from-literal=auth-token="$auth_token" \
    --from-literal=lighthouse-ip="$lighthouse_ip" \
    --from-literal=lighthouse-mesh-ip="10.42.0.1" \
    --dry-run=client -o yaml |
    kubectl --context="$HOMELAB_CONTEXT" apply -f -

  log_info "Secret 'aws-gpu-cluster-credentials' created in liqo-system namespace"

  # Create ConfigMap with peering info (non-sensitive)
  kubectl --context="$HOMELAB_CONTEXT" create configmap aws-gpu-cluster-info \
    --namespace=liqo-system \
    --from-literal=cluster-name="aws-gpu-cluster" \
    --from-literal=cluster-id="$cluster_id" \
    --from-literal=api-server="https://10.42.0.1:6443" \
    --from-literal=auth-url="https://10.42.0.1:5443" \
    --dry-run=client -o yaml |
    kubectl --context="$HOMELAB_CONTEXT" apply -f -

  log_info "ConfigMap 'aws-gpu-cluster-info' created in liqo-system namespace"
}

# =============================================================================
# Step 6: Establish Liqo peering
# =============================================================================

step_establish_peering() {
  log_step "Step 6: Establish Liqo Peering"

  if [[ "$SKIP_PEERING" == "true" ]]; then
    log_info "Skipping peering setup (--skip-peering)"
    return 0
  fi

  if [[ "$DRY_RUN" == "true" ]]; then
    log_info "[DRY-RUN] Would establish Liqo peering between homelab and AWS"
    return 0
  fi

  # Check if liqoctl is available locally
  if ! command -v liqoctl &> /dev/null; then
    log_error "liqoctl not installed locally"
    log_info "Install with: brew install liqoctl"
    log_info ""
    log_info "To establish peering manually, run:"
    log_info "  liqoctl peer \\"
    log_info "    --remote-kubeconfig $SECRETS_DIR/kubeconfig \\"
    log_info "    --namespace liqo \\"
    log_info "    --remote-namespace liqo-system \\"
    log_info "    --networking-disabled"
    return 1
  fi

  # Verify we can access the homelab Liqo namespace
  if ! kubectl get namespace liqo &> /dev/null; then
    log_error "Cannot access homelab 'liqo' namespace"
    log_info "Ensure you're connected to the homelab cluster and Liqo is installed"
    return 1
  fi

  # Verify we can access AWS cluster via the kubeconfig
  log_info "Verifying AWS cluster connectivity..."
  if ! KUBECONFIG="$SECRETS_DIR/kubeconfig" kubectl get nodes --request-timeout=10s &> /dev/null; then
    log_error "Cannot connect to AWS cluster via kubeconfig"
    log_info "Check Nebula mesh connectivity: ping 10.42.0.1"
    return 1
  fi

  log_info "Establishing Liqo peering..."
  log_info "  Homelab Liqo namespace: liqo"
  log_info "  AWS Liqo namespace:     liqo-system"
  log_info "  Networking:             disabled (using Nebula)"

  # CRITICAL: Use the correct peering command with namespace flags
  # - Homelab has Liqo in 'liqo' namespace (Flux-managed HelmRelease)
  # - AWS has Liqo in 'liqo-system' namespace (installed via liqoctl/helm)
  # - We disable Liqo networking because we use Nebula mesh for cross-cluster traffic
  liqoctl peer \
    --remote-kubeconfig "$SECRETS_DIR/kubeconfig" \
    --namespace liqo \
    --remote-namespace liqo-system \
    --networking-disabled 2>&1 || {
    local exit_code=$?
    if [[ $exit_code -ne 0 ]]; then
      log_warn "liqoctl peering command returned non-zero exit code: $exit_code"
      log_info "This may be expected if peering already exists"
    fi
  }

  # Wait for peering to establish
  log_info "Waiting for peering to establish..."
  sleep 10

  # Verify virtual node appears
  log_info "Checking for virtual node..."
  local max_attempts=12
  for i in $(seq 1 "$max_attempts"); do
    if kubectl get nodes -l liqo.io/type=virtual-node --no-headers 2> /dev/null | grep -q .; then
      log_info "✅ Virtual node created successfully!"
      kubectl get nodes -l liqo.io/type=virtual-node
      return 0
    fi
    printf "\r  Waiting for virtual node... (%d/%d)" "$i" "$max_attempts"
    sleep 5
  done
  echo ""

  log_warn "Virtual node not yet visible - peering may still be initializing"
  log_info "Check with: kubectl get nodes -l liqo.io/type=virtual-node"
  log_info "Or: liqoctl info"
}

# =============================================================================
# Step 7: Verify everything is working
# =============================================================================

step_verify() {
  log_step "Step 7: Verify Setup"

  if [[ "$DRY_RUN" == "true" ]]; then
    log_info "[DRY-RUN] Would verify setup"
    return 0
  fi

  local lighthouse_ip=$(jq -r '.elastic_ip' "$STATE_FILE")

  echo ""
  log_info "=== AWS Cluster Status ==="
  ssh_lighthouse "$lighthouse_ip" "sudo kubectl get nodes -o wide" 2> /dev/null || log_warn "Could not get nodes"

  echo ""
  log_info "=== Liqo Status (AWS) ==="
  ssh_lighthouse "$lighthouse_ip" "sudo kubectl get pods -n liqo-system --no-headers | head -10" 2> /dev/null || log_warn "Could not get Liqo pods"

  echo ""
  log_info "=== Homelab Cluster Status ==="
  kubectl get nodes -o wide 2> /dev/null || log_warn "Could not get homelab nodes"

  echo ""
  log_info "=== Virtual Nodes (Liqo) ==="
  if kubectl get nodes -l liqo.io/type=virtual-node --no-headers 2> /dev/null | grep -q .; then
    kubectl get nodes -l liqo.io/type=virtual-node
    log_info "✅ Virtual node is present - peering is working!"
  else
    log_warn "No virtual nodes found yet"
    log_info "Peering may still be initializing. Check with: liqoctl info"
  fi

  echo ""
  log_info "=== Liqo Peering Status ==="
  liqoctl info 2> /dev/null | head -30 || log_warn "Could not get Liqo info"

  echo ""
  log_info "=== Test Pod Offloading ==="
  log_info "To verify pod offloading works, create a test pod:"
  echo ""
  echo "kubectl apply -f - <<EOF"
  echo "apiVersion: v1"
  echo "kind: Pod"
  echo "metadata:"
  echo "  name: test-offload-aws"
  echo "  namespace: default"
  echo "spec:"
  echo "  nodeSelector:"
  echo "    liqo.io/type: virtual-node"
  echo "  tolerations:"
  echo "  - key: \"virtual-node.liqo.io/not-allowed\""
  echo "    operator: \"Exists\""
  echo "    effect: \"NoExecute\"  # MUST be NoExecute, not NoSchedule"
  echo "  containers:"
  echo "  - name: test"
  echo "    image: busybox"
  echo "    command: [\"sh\", \"-c\", \"echo 'Running on AWS via Liqo!' && hostname && sleep 600\"]"
  echo "EOF"
}

# =============================================================================
# Summary
# =============================================================================

print_summary() {
  local lighthouse_ip=$(jq -r '.elastic_ip' "$STATE_FILE" 2> /dev/null || echo "unknown")
  local instance_id=$(jq -r '.instance_id' "$STATE_FILE" 2> /dev/null || echo "unknown")
  local cluster_id=$(cat "$SECRETS_DIR/liqo-cluster-id" 2> /dev/null || echo "unknown")

  log_step "Setup Complete!"

  echo ""
  echo "┌─────────────────────────────────────────────────────────────────┐"
  echo "│                    AWS GPU CLUSTER READY                        │"
  echo "├─────────────────────────────────────────────────────────────────┤"
  echo "│                                                                 │"
  echo "│  Lighthouse:                                                    │"
  echo "│    Instance ID:  $instance_id"
  echo "│    Public IP:    $lighthouse_ip"
  echo "│    Nebula IP:    10.42.0.1"
  echo "│                                                                 │"
  echo "│  k3s Cluster:                                                   │"
  echo "│    API Server:   https://10.42.0.1:6443                         │"
  echo "│    Cluster:      aws-gpu-cluster                                │"
  echo "│                                                                 │"
  echo "│  Liqo Federation:                                               │"
  echo "│    Cluster ID:   $cluster_id"
  echo "│    Homelab NS:   liqo                                           │"
  echo "│    AWS NS:       liqo-system                                    │"
  echo "│    Networking:   Disabled (using Nebula)                        │"
  echo "│                                                                 │"
  echo "│  Credentials:    $SECRETS_DIR/"
  echo "│                                                                 │"
  echo "├─────────────────────────────────────────────────────────────────┤"
  echo "│  SSH Access:                                                    │"
  echo "│    ssh -i $SSH_KEY ec2-user@$lighthouse_ip"
  echo "│                                                                 │"
  echo "│  Kubectl (AWS):                                                 │"
  echo "│    KUBECONFIG=$SECRETS_DIR/kubeconfig kubectl get nodes"
  echo "│                                                                 │"
  echo "├─────────────────────────────────────────────────────────────────┤"
  echo "│  Re-establish Peering (if needed):                              │"
  echo "│    liqoctl peer \\                                               │"
  echo "│      --remote-kubeconfig $SECRETS_DIR/kubeconfig \\              │"
  echo "│      --namespace liqo \\                                         │"
  echo "│      --remote-namespace liqo-system \\                           │"
  echo "│      --networking-disabled                                      │"
  echo "│                                                                 │"
  echo "├─────────────────────────────────────────────────────────────────┤"
  echo "│  Verification:                                                  │"
  echo "│    liqoctl info                  # Check peering status         │"
  echo "│    kubectl get nodes             # Should show virtual node     │"
  echo "│                                                                 │"
  echo "└─────────────────────────────────────────────────────────────────┘"
  echo ""
}

# =============================================================================
# Main
# =============================================================================

main() {
  echo ""
  echo "╔═══════════════════════════════════════════════════════════════════╗"
  echo "║         AWS GPU CLUSTER ORCHESTRATION                             ║"
  echo "║         Nebula + k3s + Liqo Federation                            ║"
  echo "╚═══════════════════════════════════════════════════════════════════╝"
  echo ""

  if [[ "$DRY_RUN" == "true" ]]; then
    log_warn "DRY RUN MODE - No changes will be made"
  fi

  step_teardown
  step_provision
  step_wait_for_services
  step_fetch_credentials
  step_create_homelab_secrets
  step_establish_peering
  step_verify
  print_summary
}

main "$@"
