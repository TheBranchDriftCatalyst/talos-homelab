#!/bin/bash
# Deploy Linkerd service mesh
# GitOps-friendly deployment script
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LINKERD_DIR="$REPO_ROOT/infrastructure/base/linkerd"
CERTS_DIR="$LINKERD_DIR/certs"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() {
  echo -e "${RED}[ERROR]${NC} $1"
  exit 1
}

# Check prerequisites
check_prerequisites() {
  log "Checking prerequisites..."

  command -v helm > /dev/null 2>&1 || error "helm is required but not installed"
  command -v kubectl > /dev/null 2>&1 || error "kubectl is required but not installed"
  command -v step > /dev/null 2>&1 || command -v openssl > /dev/null 2>&1 || error "step or openssl required for cert generation"

  # Check cluster connectivity
  kubectl cluster-info > /dev/null 2>&1 || error "Cannot connect to cluster"

  log "Prerequisites OK"
}

# Setup trust anchor from 1Password via External Secrets
setup_trust_anchor() {
  log "Setting up trust anchor from 1Password..."

  # Ensure linkerd namespace exists with correct labels
  kubectl apply -f "$REPO_ROOT/infrastructure/base/namespaces/linkerd.yaml"

  # Apply ExternalSecret to pull CA from 1Password
  kubectl apply -f "$LINKERD_DIR/external-secret.yaml"

  # Wait for the secret to be synced
  log "Waiting for trust anchor secret to sync from 1Password..."
  for i in {1..30}; do
    if kubectl get secret linkerd-trust-anchor -n linkerd > /dev/null 2>&1; then
      local status
      status=$(kubectl get externalsecret linkerd-trust-anchor -n linkerd -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2> /dev/null || echo "Unknown")
      if [[ "$status" == "True" ]]; then
        log "Trust anchor secret synced successfully"
        return 0
      fi
    fi
    echo -n "."
    sleep 2
  done

  error "Trust anchor secret not found. Please ensure 'linkerd-trust-anchor' exists in 1Password with 'ca.crt' and 'ca.key' fields.

To create the CA certificate, run:
  $0 generate-ca

Then add the contents of ca.crt and ca.key to 1Password item 'linkerd-trust-anchor'"
}

# Generate CA certificate (one-time setup)
# Uses ECDSA P-256 as required by Linkerd
generate_ca() {
  log "Generating Linkerd trust anchor (CA) certificate with ECDSA P-256..."

  mkdir -p "$CERTS_DIR"

  if command -v step > /dev/null 2>&1; then
    log "Using step CLI..."
    step certificate create root.linkerd.cluster.local "$CERTS_DIR/ca.crt" "$CERTS_DIR/ca.key" \
      --profile root-ca \
      --no-password --insecure \
      --not-after 87600h \
      --kty EC --crv P-256 \
      --force
  else
    log "Using openssl with ECDSA P-256..."
    # Generate ECDSA P-256 private key
    openssl ecparam -name prime256v1 -genkey -noout -out "$CERTS_DIR/ca.key"
    # Generate self-signed CA certificate
    openssl req -x509 -new -nodes -key "$CERTS_DIR/ca.key" -sha256 -days 3650 \
      -out "$CERTS_DIR/ca.crt" \
      -subj "/CN=root.linkerd.cluster.local"
  fi

  log ""
  log "CA certificate generated!"
  log ""
  log "Next steps:"
  log "1. Create a new item in 1Password called 'linkerd-trust-anchor'"
  log "2. Add a field 'ca.crt' with contents of: $CERTS_DIR/ca.crt"
  log "3. Add a field 'ca.key' with contents of: $CERTS_DIR/ca.key"
  log ""
  log "Or copy these values:"
  log ""
  log "=== ca.crt ==="
  cat "$CERTS_DIR/ca.crt"
  log ""
  log "=== ca.key ==="
  cat "$CERTS_DIR/ca.key"
  log ""
  log "After adding to 1Password, run: $0 install"
}

# Generate issuer certificate from trust anchor
# Uses ECDSA P-256 to match the CA
generate_issuer() {
  log "Generating issuer certificate from trust anchor (ECDSA P-256)..."

  mkdir -p "$CERTS_DIR"

  # Extract CA from K8s secret (pulled from 1Password)
  kubectl get secret linkerd-trust-anchor -n linkerd -o jsonpath='{.data.ca\.crt}' | base64 -d > "$CERTS_DIR/ca.crt"
  kubectl get secret linkerd-trust-anchor -n linkerd -o jsonpath='{.data.ca\.key}' | base64 -d > "$CERTS_DIR/ca.key"

  if command -v step > /dev/null 2>&1; then
    log "Using step CLI to generate issuer..."
    step certificate create identity.linkerd.cluster.local "$CERTS_DIR/issuer.crt" "$CERTS_DIR/issuer.key" \
      --profile intermediate-ca \
      --ca "$CERTS_DIR/ca.crt" \
      --ca-key "$CERTS_DIR/ca.key" \
      --not-after 8760h \
      --no-password --insecure \
      --kty EC --crv P-256 \
      --force
  else
    log "Using openssl with ECDSA P-256 to generate issuer..."
    # Generate ECDSA P-256 private key for issuer
    openssl ecparam -name prime256v1 -genkey -noout -out "$CERTS_DIR/issuer.key"

    # Generate CSR
    openssl req -new -key "$CERTS_DIR/issuer.key" \
      -out "$CERTS_DIR/issuer.csr" \
      -subj "/CN=identity.linkerd.cluster.local"

    # Create extension file for intermediate CA
    cat > "$CERTS_DIR/issuer.ext" << EOF
basicConstraints = critical, CA:TRUE, pathlen:0
keyUsage = critical, digitalSignature, keyCertSign, cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always
EOF

    openssl x509 -req -in "$CERTS_DIR/issuer.csr" \
      -CA "$CERTS_DIR/ca.crt" -CAkey "$CERTS_DIR/ca.key" \
      -CAcreateserial -out "$CERTS_DIR/issuer.crt" \
      -days 365 -sha256 -extfile "$CERTS_DIR/issuer.ext"

    rm -f "$CERTS_DIR/issuer.csr" "$CERTS_DIR/ca.srl" "$CERTS_DIR/issuer.ext"
  fi

  # Clean up CA key from local (it's in 1Password)
  rm -f "$CERTS_DIR/ca.key"

  log "Issuer certificate generated"
}

# Add Linkerd Helm repo
setup_helm_repo() {
  log "Setting up Linkerd Helm repository..."

  helm repo add linkerd-edge https://helm.linkerd.io/edge 2> /dev/null || true
  helm repo update linkerd-edge
}

# Install Gateway API CRDs (required by Linkerd)
install_gateway_api() {
  log "Installing Gateway API CRDs..."

  kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.1/standard-install.yaml
}

# Install Linkerd CRDs
install_crds() {
  log "Installing Linkerd CRDs..."

  helm upgrade --install linkerd-crds linkerd-edge/linkerd-crds \
    --namespace linkerd \
    --create-namespace \
    --values "$LINKERD_DIR/values-crds.yaml" \
    --wait
}

# Install Linkerd control plane
install_control_plane() {
  log "Installing Linkerd control plane..."

  # Read certificate files
  local trust_anchor
  local issuer_crt
  local issuer_key

  trust_anchor=$(cat "$CERTS_DIR/ca.crt")
  issuer_crt=$(cat "$CERTS_DIR/issuer.crt")
  issuer_key=$(cat "$CERTS_DIR/issuer.key")

  helm upgrade --install linkerd-control-plane linkerd-edge/linkerd-control-plane \
    --namespace linkerd \
    --values "$LINKERD_DIR/values-control-plane.yaml" \
    --set-file identityTrustAnchorsPEM="$CERTS_DIR/ca.crt" \
    --set-file identity.issuer.tls.crtPEM="$CERTS_DIR/issuer.crt" \
    --set-file identity.issuer.tls.keyPEM="$CERTS_DIR/issuer.key" \
    --wait \
    --timeout 5m
}

# Verify installation
verify_installation() {
  log "Verifying Linkerd installation..."

  # Check if linkerd CLI is available
  if command -v linkerd > /dev/null 2>&1; then
    linkerd check || warn "Some Linkerd checks failed (may be expected)"
  else
    # Manual verification
    kubectl wait --for=condition=available --timeout=120s deployment -l app.kubernetes.io/part-of=Linkerd -n linkerd
  fi

  log "Linkerd control plane pods:"
  kubectl get pods -n linkerd
}

# Inject namespace
inject_namespace() {
  local namespace="${1:-}"

  if [[ -z "$namespace" ]]; then
    error "Namespace required for injection"
  fi

  log "Enabling Linkerd injection for namespace: $namespace"

  kubectl annotate namespace "$namespace" linkerd.io/inject=enabled --overwrite

  log "Restarting deployments in $namespace..."
  kubectl rollout restart deployment -n "$namespace" 2> /dev/null || warn "No deployments to restart"
}

# Main
main() {
  local action="${1:-install}"

  case "$action" in
    install)
      check_prerequisites
      setup_trust_anchor
      generate_issuer
      setup_helm_repo
      install_gateway_api
      install_crds
      install_control_plane
      verify_installation
      log "Linkerd installed successfully!"
      log ""
      log "To inject a namespace, run:"
      log "  $0 inject <namespace>"
      ;;
    generate-ca)
      generate_ca
      ;;
    inject)
      inject_namespace "${2:-}"
      ;;
    uninstall)
      log "Uninstalling Linkerd..."
      helm uninstall linkerd-control-plane -n linkerd 2> /dev/null || true
      helm uninstall linkerd-crds -n linkerd 2> /dev/null || true
      kubectl delete externalsecret linkerd-trust-anchor -n linkerd 2> /dev/null || true
      kubectl delete secret linkerd-trust-anchor -n linkerd 2> /dev/null || true
      kubectl delete namespace linkerd 2> /dev/null || true
      rm -rf "$CERTS_DIR"
      log "Linkerd uninstalled"
      ;;
    status)
      kubectl get pods -n linkerd
      if command -v linkerd > /dev/null 2>&1; then
        linkerd check
      fi
      ;;
    *)
      echo "Usage: $0 {install|generate-ca|inject <namespace>|uninstall|status}"
      echo ""
      echo "Commands:"
      echo "  generate-ca         Generate CA certificate (one-time setup)"
      echo "  install             Install Linkerd (requires CA in 1Password)"
      echo "  inject <namespace>  Enable Linkerd injection for a namespace"
      echo "  uninstall           Remove Linkerd from cluster"
      echo "  status              Show Linkerd status"
      exit 1
      ;;
  esac
}

main "$@"
