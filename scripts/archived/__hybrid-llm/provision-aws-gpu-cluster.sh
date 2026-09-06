#!/bin/bash
# =============================================================================
# Quick Start: Provision AWS GPU Cluster
# =============================================================================
# Single command to set up the complete AWS GPU cluster with Liqo federation
#
# Usage:
#   ./scripts/hybrid-llm/provision-aws-gpu-cluster.sh
#
# What this does:
#   1. Teardowns any existing lighthouse
#   2. Provisions new lighthouse with Nebula + k3s + Liqo
#   3. Waits for all services to be ready
#   4. Fetches credentials and creates secrets in homelab
#   5. Establishes Liqo peering
#
# Prerequisites:
#   - AWS CLI configured (aws configure)
#   - kubectl configured for homelab cluster
#   - nebula-cert installed (brew install nebula)
#
# Environment variables (optional):
#   LIGHTHOUSE_INSTANCE_TYPE  - Instance type (default: t3.small)
#   AWS_REGION               - AWS region (default: us-west-2)
#   HOMELAB_CONTEXT          - kubectl context (default: talos-homelab)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Default configuration
export LIGHTHOUSE_INSTANCE_TYPE="${LIGHTHOUSE_INSTANCE_TYPE:-t3.small}"
export AWS_REGION="${AWS_REGION:-us-west-2}"
export HOMELAB_CONTEXT="${HOMELAB_CONTEXT:-talos-homelab}"

echo ""
echo "╔═══════════════════════════════════════════════════════════════════╗"
echo "║   AWS GPU Cluster Quick Provisioning                              ║"
echo "╠═══════════════════════════════════════════════════════════════════╣"
echo "║   Lighthouse:  $LIGHTHOUSE_INSTANCE_TYPE (Nebula + k3s + Liqo)              ║"
echo "║   GPU Worker:  g4dn.4xlarge (16 vCPU, 64GB, T4 GPU)              ║"
echo "║   Region:      $AWS_REGION                                        ║"
echo "╚═══════════════════════════════════════════════════════════════════╝"
echo ""

# Check prerequisites
check_prereqs() {
  local missing=0

  if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found - install with: brew install awscli"
    missing=1
  else
    echo "✅ AWS CLI"
  fi

  if ! command -v kubectl &> /dev/null; then
    echo "❌ kubectl not found - install with: brew install kubectl"
    missing=1
  else
    echo "✅ kubectl"
  fi

  if ! command -v jq &> /dev/null; then
    echo "❌ jq not found - install with: brew install jq"
    missing=1
  else
    echo "✅ jq"
  fi

  if ! command -v nebula-cert &> /dev/null; then
    echo "❌ nebula-cert not found - install with: brew install nebula"
    missing=1
  else
    echo "✅ nebula-cert"
  fi

  # Check AWS credentials
  if ! aws sts get-caller-identity &> /dev/null; then
    echo "❌ AWS credentials not configured - run: aws configure"
    missing=1
  else
    echo "✅ AWS credentials"
  fi

  # Check for Nebula CA
  if [[ ! -f "$HOME/.nebula-ca/ca.crt" ]]; then
    echo ""
    echo "⚠️  Nebula CA not found at ~/.nebula-ca/ca.crt"
    echo "   First-time setup will generate it automatically."
  else
    echo "✅ Nebula CA"
  fi

  echo ""

  if [[ $missing -eq 1 ]]; then
    echo "Please install missing prerequisites and try again."
    exit 1
  fi
}

check_prereqs

# Run the orchestration
exec "$SCRIPT_DIR/orchestrate-aws-cluster.sh" "$@"
