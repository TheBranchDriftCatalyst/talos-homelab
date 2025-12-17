#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

NAMESPACE="${NAMESPACE:-media-dev}"
TIMEOUT="${TIMEOUT:-300s}"

echo "=================================================="
echo "Deploying Tdarr to namespace: ${NAMESPACE}"
echo "=================================================="

# Check cluster health
echo ""
echo "Checking cluster health..."
if ! kubectl cluster-info &> /dev/null; then
  echo "ERROR: Cannot connect to Kubernetes cluster"
  echo "Run: task kubeconfig-merge"
  exit 1
fi

# Create namespace if it doesn't exist
echo ""
echo "Ensuring namespace exists..."
kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

# Apply shared storage (if needed)
echo ""
echo "Ensuring shared storage exists..."
if kubectl get pvc -n "${NAMESPACE}" media-shared &> /dev/null; then
  echo "  ✓ Shared media PVC already exists"
else
  echo "  Creating shared media PVC..."
  kubectl apply -f "${PROJECT_ROOT}/applications/arr-stack/overlays/dev/storage.yaml"
fi

# Deploy Tdarr
echo ""
echo "Deploying Tdarr..."
kubectl apply -k "${PROJECT_ROOT}/applications/arr-stack/base/tdarr/" -n "${NAMESPACE}"

# Wait for deployment to be ready
echo ""
echo "Waiting for Tdarr to be ready (timeout: ${TIMEOUT})..."
if kubectl wait --for=condition=available deployment/tdarr -n "${NAMESPACE}" --timeout="${TIMEOUT}"; then
  echo "  ✓ Tdarr deployment is ready"
else
  echo "  ✗ Tdarr deployment failed to become ready"
  echo ""
  echo "Checking pod status..."
  kubectl get pods -n "${NAMESPACE}" -l app=tdarr
  echo ""
  echo "Recent events:"
  kubectl get events -n "${NAMESPACE}" --sort-by='.lastTimestamp' | tail -10
  exit 1
fi

# Display access information
echo ""
echo "=================================================="
echo "Tdarr deployed successfully!"
echo "=================================================="
echo ""
echo "Access Tdarr:"
echo "  URL: http://tdarr.talos00"
echo "  (Make sure 'tdarr.talos00' is in your /etc/hosts file)"
echo ""
echo "Check status:"
echo "  kubectl get pods -n ${NAMESPACE} -l app=tdarr"
echo "  kubectl logs -n ${NAMESPACE} -l app=tdarr --tail=50 -f"
echo ""
echo "Service endpoints:"
echo "  Web UI:    http://tdarr.talos00 (port 8265)"
echo "  Server:    tdarr.${NAMESPACE}.svc.cluster.local:8266"
echo ""
