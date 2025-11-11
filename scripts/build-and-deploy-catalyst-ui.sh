#!/usr/bin/env bash
set -euo pipefail

# Build and deploy catalyst-ui to the Talos cluster
# This script builds the Docker image, pushes to local registry, and deploys via ArgoCD

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CATALYST_UI_PATH="${HOME}/catalyst-devspace/workspace/catalyst-ui"
REGISTRY_URL="registry.talos00:5000"

echo "==========================================="
echo "Catalyst UI - Build and Deploy"
echo "==========================================="
echo ""

# Check if catalyst-ui directory exists
if [ ! -d "${CATALYST_UI_PATH}" ]; then
    echo "❌ Catalyst UI directory not found at: ${CATALYST_UI_PATH}"
    exit 1
fi

echo "✅ Found catalyst-ui at: ${CATALYST_UI_PATH}"
echo ""

# Ensure local registry is deployed
echo "📦 Ensuring local Docker registry is deployed..."
kubectl apply -f "${PROJECT_ROOT}/infrastructure/base/registry/deployment.yaml"
kubectl wait --for=condition=ready pod -l app=docker-registry -n registry --timeout=120s

# Get the current git commit hash for tagging
GIT_HASH=$(git -C "${CATALYST_UI_PATH}" rev-parse --short HEAD 2>/dev/null || echo "dev")
VERSION=$(git -C "${CATALYST_UI_PATH}" describe --tags --always 2>/dev/null || echo "v0.0.0-${GIT_HASH}")

echo "ℹ️  Version: ${VERSION}"
echo "ℹ️  Git Hash: ${GIT_HASH}"
echo ""

# Build the Docker image
echo "🔨 Building Docker image..."
cd "${CATALYST_UI_PATH}"
docker build -t "catalyst-ui:latest" \
             -t "catalyst-ui:${GIT_HASH}" \
             -t "${REGISTRY_URL}/catalyst-ui:latest" \
             -t "${REGISTRY_URL}/catalyst-ui:${GIT_HASH}" \
             .

echo "✅ Built image with tags: latest and ${GIT_HASH}"
echo ""

# Push to local registry
echo "📤 Pushing image to local registry..."
docker push "${REGISTRY_URL}/catalyst-ui:latest"
docker push "${REGISTRY_URL}/catalyst-ui:${GIT_HASH}"

echo "✅ Pushed to registry at ${REGISTRY_URL}"
echo ""

# Apply the ArgoCD Application
echo "🚀 Deploying ArgoCD Application..."
kubectl apply -f "${PROJECT_ROOT}/infrastructure/base/argocd/applications/catalyst-ui.yaml"

# Wait for ArgoCD to sync
echo "⏳ Waiting for ArgoCD to sync..."
sleep 5

echo ""
echo "==========================================="
echo "✅ Catalyst UI Deploy Complete!"
echo "==========================================="
echo ""
echo "ArgoCD Application created. Check sync status:"
echo "  kubectl get application -n argocd catalyst-ui"
echo ""
echo "Access services:"
echo "  ArgoCD:      http://argocd.talos00"
echo "  Registry:    http://registry.talos00"
echo "  Catalyst UI: http://catalyst.talos00 (once synced)"
echo ""
echo "Update image in deployment:"
echo "  Image: ${REGISTRY_URL}/catalyst-ui:${GIT_HASH}"
echo ""
