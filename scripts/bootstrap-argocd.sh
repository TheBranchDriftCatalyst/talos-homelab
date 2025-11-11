#!/usr/bin/env bash
set -euo pipefail

# Bootstrap ArgoCD on Talos Kubernetes cluster
# This script installs ArgoCD and configures it for GitOps deployments

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=========================================="
echo "ArgoCD Bootstrap Script"
echo "=========================================="
echo ""

# Check if kubectl is configured
if ! kubectl cluster-info &>/dev/null; then
    echo "❌ kubectl is not configured or cluster is not accessible"
    exit 1
fi

echo "✅ Kubernetes cluster is accessible"
echo ""

# Add ArgoCD Helm repository
echo "📦 Adding ArgoCD Helm repository..."
helm repo add argo https://argoproj.github.io/argo-helm 2>/dev/null || true
helm repo update

# Create argocd namespace
echo "🏗️  Creating argocd namespace..."
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -

# Install ArgoCD
echo "🚀 Installing ArgoCD..."
helm upgrade --install argocd argo/argo-cd \
    -n argocd \
    -f "${PROJECT_ROOT}/infrastructure/base/argocd/values.yaml" \
    --wait \
    --timeout 5m

# Apply IngressRoute
echo "🌐 Applying IngressRoute..."
kubectl apply -f "${PROJECT_ROOT}/infrastructure/base/argocd/ingressroute.yaml"

# Wait for ArgoCD to be ready
echo "⏳ Waiting for ArgoCD pods to be ready..."
kubectl wait --for=condition=ready pod \
    -l app.kubernetes.io/name=argocd-server \
    -n argocd \
    --timeout=300s

# Get initial admin password
echo ""
echo "=========================================="
echo "✅ ArgoCD Installation Complete!"
echo "=========================================="
echo ""
echo "Access ArgoCD:"
echo "  URL: http://argocd.talos00"
echo "  Username: admin"
echo "  Password: $(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d)"
echo ""
echo "Or use port-forward:"
echo "  kubectl port-forward svc/argocd-server -n argocd 8080:80"
echo "  URL: http://localhost:8080"
echo ""
echo "To change the admin password:"
echo "  argocd login argocd.talos00"
echo "  argocd account update-password"
echo ""
echo "NOTE: Delete the initial secret after changing password:"
echo "  kubectl -n argocd delete secret argocd-initial-admin-secret"
echo ""
