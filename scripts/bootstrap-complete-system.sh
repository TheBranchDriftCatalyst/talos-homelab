#!/usr/bin/env bash
set -euo pipefail

# Complete Talos Kubernetes Homelab Bootstrap
# Rebuilds the entire system from scratch

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=========================================="
echo "Talos Kubernetes Homelab - Complete Bootstrap"
echo "=========================================="
echo ""

# Step 1: Infrastructure
echo "📦 Step 1/5: Deploying Infrastructure..."
"${SCRIPT_DIR}/setup-infrastructure.sh"

# Step 2: Monitoring
echo ""
echo "📊 Step 2/5: Deploying Monitoring Stack..."
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
    -n monitoring \
    --create-namespace \
    -f "${PROJECT_ROOT}/infrastructure/base/monitoring/kube-prometheus-stack/values.yaml" \
    --wait

kubectl apply -f "${PROJECT_ROOT}/infrastructure/base/monitoring/kube-prometheus-stack/ingressroute.yaml"

# Step 3: Observability
echo ""
echo "📝 Step 3/5: Deploying Observability Stack..."
"${SCRIPT_DIR}/deploy-observability.sh"

# Step 4: Media Stack
echo ""
echo "🎬 Step 4/5: Deploying Media Stack..."
kubectl apply -k "${PROJECT_ROOT}/applications/arr-stack/overlays/dev/"

# Step 5: ArgoCD
echo ""
echo "🚀 Step 5/5: Installing ArgoCD..."
"${SCRIPT_DIR}/bootstrap-argocd.sh"

# Step 6: Bastion
echo ""
echo "🔧 Step 6/6: Deploying Bastion Container..."
kubectl apply -f "${PROJECT_ROOT}/infrastructure/base/bastion/deployment.yaml"

echo ""
echo "=========================================="
echo "✅ Complete System Bootstrap Finished!"
echo "=========================================="
echo ""
echo "Next Steps:"
echo "  1. Access ArgoCD: http://argocd.talos00"
echo "  2. Configure *arr apps and extract API keys:"
echo "     ${SCRIPT_DIR}/extract-arr-api-keys.sh"
echo "  3. View system status:"
echo "     kubectl get pods -A"
echo ""
