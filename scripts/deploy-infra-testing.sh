#!/usr/bin/env bash
set -euo pipefail

# Deploy Infrastructure Testing Tools Stack
# This script deploys UI and monitoring tools to the infra-testing namespace

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
  echo -e "${BLUE}ℹ${NC} $*"
}

log_success() {
  echo -e "${GREEN}✓${NC} $*"
}

log_warning() {
  echo -e "${YELLOW}⚠${NC} $*"
}

log_error() {
  echo -e "${RED}✗${NC} $*"
}

# Check if cluster is accessible
check_cluster() {
  log_info "Checking cluster connectivity..."
  if ! kubectl cluster-info &> /dev/null; then
    log_error "Cannot connect to cluster. Please check your kubeconfig."
    exit 1
  fi
  log_success "Cluster is accessible"
}

# Wait for pods to be ready
wait_for_pods() {
  local namespace=$1
  local label=$2
  local timeout=${3:-300}

  log_info "Waiting for pods with label ${label} in namespace ${namespace}..."
  if kubectl wait --for=condition=ready pod \
    -l "${label}" \
    -n "${namespace}" \
    --timeout="${timeout}s" 2> /dev/null; then
    log_success "Pods are ready"
    return 0
  else
    log_warning "Some pods may not be ready yet"
    return 0
  fi
}

# Deploy namespace
deploy_namespace() {
  log_info "Deploying infra-testing namespace..."
  kubectl apply -k "${PROJECT_ROOT}/infrastructure/base/infra-testing/namespace/"
  log_success "Namespace deployed"
}

# Deploy VPA and Goldilocks
deploy_goldilocks() {
  log_info "Deploying Goldilocks (with VPA)..."
  kubectl apply -k "${PROJECT_ROOT}/infrastructure/base/infra-testing/goldilocks/"
  wait_for_pods "kube-system" "app=vpa-recommender" 120
  wait_for_pods "infra-testing" "app=goldilocks,component=controller" 120
  wait_for_pods "infra-testing" "app=goldilocks,component=dashboard" 120
  log_success "Goldilocks deployed"
}

# Deploy Headlamp
deploy_headlamp() {
  log_info "Deploying Headlamp..."
  kubectl apply -k "${PROJECT_ROOT}/infrastructure/base/infra-testing/headlamp/"
  wait_for_pods "infra-testing" "app=headlamp" 120
  log_success "Headlamp deployed"
}

# Deploy Kubeview
deploy_kubeview() {
  log_info "Deploying Kubeview..."
  kubectl apply -k "${PROJECT_ROOT}/infrastructure/base/infra-testing/kubeview/"
  wait_for_pods "infra-testing" "app=kubeview" 120
  log_success "Kubeview deployed"
}

# Deploy Kube-ops-view
deploy_kube_ops_view() {
  log_info "Deploying Kube-ops-view..."
  kubectl apply -k "${PROJECT_ROOT}/infrastructure/base/infra-testing/kube-ops-view/"
  wait_for_pods "infra-testing" "app=kube-ops-view" 120
  log_success "Kube-ops-view deployed"
}

# Main deployment
main() {
  echo "========================================"
  echo "Infrastructure Testing Tools Deployment"
  echo "========================================"
  echo ""

  check_cluster

  deploy_namespace

  # Deploy all tools
  deploy_goldilocks
  deploy_headlamp
  deploy_kubeview
  deploy_kube_ops_view

  echo ""
  echo "========================================"
  log_success "All infrastructure testing tools deployed!"
  echo "========================================"
  echo ""

  log_info "Access the tools at:"
  echo ""
  echo "  Headlamp:         http://headlamp.talos00"
  echo "  Kubeview:         http://kubeview.talos00"
  echo "  Kube-ops-view:    http://kube-ops-view.talos00"
  echo "  Goldilocks:       http://goldilocks.talos00"
  echo ""

  log_warning "Make sure to add these entries to /etc/hosts:"
  echo "  192.168.1.54  headlamp.talos00 kubeview.talos00 kube-ops-view.talos00 goldilocks.talos00"
  echo ""

  log_info "To enable Goldilocks recommendations for a namespace, label it:"
  echo "  kubectl label namespace <namespace> goldilocks.fairwinds.com/enabled=true"
  echo ""
}

main "$@"
