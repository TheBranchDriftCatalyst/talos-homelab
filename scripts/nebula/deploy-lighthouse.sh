#!/usr/bin/env bash
# Deploy Nebula Lighthouse to Kubernetes
# Creates secret from local certs, then applies kustomization

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CERT_DIR="$REPO_ROOT/configs/nebula-certs"
MANIFEST_DIR="$REPO_ROOT/infrastructure/base/nebula"

echo "=== Nebula Lighthouse Deployment ==="
echo ""

# Check certs exist
for cert in ca.crt lighthouse.crt lighthouse.key; do
  if [[ ! -f "$CERT_DIR/$cert" ]]; then
    echo "ERROR: Missing certificate: $CERT_DIR/$cert"
    echo ""
    echo "Generate certs first:"
    echo "  cd $CERT_DIR"
    echo "  nebula-cert ca -name 'talos-homelab-mesh'"
    echo "  nebula-cert sign -name 'lighthouse' -ip '10.100.0.1/24' -groups 'lighthouse,homelab'"
    exit 1
  fi
done

echo "✓ Certificates found"

# Create namespace if not exists
echo "Creating namespace..."
kubectl apply -f "$MANIFEST_DIR/namespace.yaml"

# Create secret from certs
echo "Creating secret from certificates..."
kubectl create secret generic nebula-lighthouse-certs \
  --from-file=ca.crt="$CERT_DIR/ca.crt" \
  --from-file=lighthouse.crt="$CERT_DIR/lighthouse.crt" \
  --from-file=lighthouse.key="$CERT_DIR/lighthouse.key" \
  -n nebula \
  --dry-run=client -o yaml | kubectl apply -f -

echo "✓ Secret created"

# Apply kustomization
echo "Applying kustomization..."
kubectl apply -k "$MANIFEST_DIR"

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Check status:"
echo "  kubectl get pods -n nebula"
echo "  kubectl logs -n nebula -l app=nebula-lighthouse"
echo ""
echo "Router configuration required:"
echo "  Forward UDP 4242 to control-plane IP (192.168.1.54)"
echo ""
echo "Cloudflare DDNS should point to your home IP for external workers."
