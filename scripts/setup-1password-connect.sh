#!/usr/bin/env bash
# shellcheck disable=SC2034,SC2162
set -euo pipefail

# Setup 1Password Connect for External Secrets Operator
# This script helps you configure the required secrets for 1Password Connect
#
# Usage:
#   ./setup-1password-connect.sh           # Interactive mode
#   ./setup-1password-connect.sh --auto    # Auto mode (uses env vars and local files)
#
# Auto mode requires:
#   - OP_CONNECT_TOKEN environment variable
#   - ./1password-credentials.json file (or OP_CREDENTIALS_FILE env var)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
NAMESPACE="external-secrets"
AUTO_MODE=false
FORCE_RECREATE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --auto|-a)
      AUTO_MODE=true
      shift
      ;;
    --force|-f)
      FORCE_RECREATE=true
      shift
      ;;
    --help|-h)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --auto, -a     Auto mode: use OP_CONNECT_TOKEN env var and ./1password-credentials.json"
      echo "  --force, -f    Force recreate secrets even if they exist"
      echo "  --help, -h     Show this help message"
      echo ""
      echo "Environment variables (for auto mode):"
      echo "  OP_CONNECT_TOKEN      1Password Connect API token"
      echo "  OP_CREDENTIALS_FILE   Path to 1password-credentials.json (default: ./1password-credentials.json)"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

echo "=========================================="
echo "1Password Connect Setup for ESO"
echo "=========================================="
echo ""

# Check prerequisites
if ! command -v kubectl &> /dev/null; then
  echo "❌ kubectl not installed"
  exit 1
fi

echo "✅ kubectl installed"

# Check if namespace exists
if ! kubectl get namespace "${NAMESPACE}" &> /dev/null; then
  echo "Creating namespace: ${NAMESPACE}"
  kubectl create namespace "${NAMESPACE}"
fi

# Auto mode logic
if [ "$AUTO_MODE" = true ]; then
  echo "🤖 Running in AUTO mode"
  echo ""

  # Check for OP_CONNECT_TOKEN
  if [ -z "${OP_CONNECT_TOKEN:-}" ]; then
    echo "❌ OP_CONNECT_TOKEN environment variable not set"
    echo "   Set it with: export OP_CONNECT_TOKEN='your-token-here'"
    exit 1
  fi
  echo "✅ OP_CONNECT_TOKEN found in environment"

  # Check for credentials file
  CREDS_FILE="${OP_CREDENTIALS_FILE:-${PROJECT_DIR}/1password-credentials.json}"
  if [ ! -f "${CREDS_FILE}" ]; then
    echo "❌ Credentials file not found: ${CREDS_FILE}"
    echo "   Set OP_CREDENTIALS_FILE or place 1password-credentials.json in project root"
    exit 1
  fi
  echo "✅ Credentials file found: ${CREDS_FILE}"
  echo ""

  # Handle existing secrets
  SKIP_CREDS=false
  SKIP_TOKEN=false

  if kubectl get secret onepassword-connect-secret -n "${NAMESPACE}" &> /dev/null; then
    if [ "$FORCE_RECREATE" = true ]; then
      echo "🔄 Recreating onepassword-connect-secret (--force)"
      kubectl delete secret onepassword-connect-secret -n "${NAMESPACE}"
    else
      echo "⏭️  Secret 'onepassword-connect-secret' already exists (use --force to recreate)"
      SKIP_CREDS=true
    fi
  fi

  if kubectl get secret onepassword-connect-token -n "${NAMESPACE}" &> /dev/null; then
    if [ "$FORCE_RECREATE" = true ]; then
      echo "🔄 Recreating onepassword-connect-token (--force)"
      kubectl delete secret onepassword-connect-token -n "${NAMESPACE}"
    else
      echo "⏭️  Secret 'onepassword-connect-token' already exists (use --force to recreate)"
      SKIP_TOKEN=true
    fi
  fi

  # Create credentials secret
  if [ "${SKIP_CREDS}" != "true" ]; then
    echo ""
    echo "Creating secret: onepassword-connect-secret"
    echo "Base64 encoding credentials file for 1Password Connect..."

    # Create temporary base64-encoded file
    cat "${CREDS_FILE}" | base64 | tr -d '\n' > /tmp/op-creds-b64.txt

    kubectl create secret generic onepassword-connect-secret \
      -n "${NAMESPACE}" \
      --from-file=1password-credentials.json=/tmp/op-creds-b64.txt

    rm /tmp/op-creds-b64.txt
    echo "✅ Created onepassword-connect-secret"
  fi

  # Create token secret
  if [ "${SKIP_TOKEN}" != "true" ]; then
    echo ""
    echo "Creating secret: onepassword-connect-token"
    kubectl create secret generic onepassword-connect-token \
      -n "${NAMESPACE}" \
      --from-literal=token="${OP_CONNECT_TOKEN}"
    echo "✅ Created onepassword-connect-token"
  fi

  # Restart onepassword-connect if it exists
  if kubectl get deployment onepassword-connect -n "${NAMESPACE}" &> /dev/null; then
    echo ""
    echo "🔄 Restarting onepassword-connect deployment..."
    kubectl rollout restart deployment/onepassword-connect -n "${NAMESPACE}" 2>/dev/null || true
  fi

  echo ""
  echo "=========================================="
  echo "✅ Auto Setup Complete!"
  echo "=========================================="

  # Quick status check
  echo ""
  echo "Checking pod status..."
  sleep 3
  kubectl get pods -n "${NAMESPACE}" -l app.kubernetes.io/name=onepassword-connect 2>/dev/null || echo "onepassword-connect not yet deployed"

  exit 0
fi

# Interactive mode (original behavior)
echo ""
echo "This script will help you create the required secrets for 1Password Connect."
echo ""
echo "You will need:"
echo "  1. 1password-credentials.json (from 1Password Connect Server setup)"
echo "  2. 1Password Connect API token"
echo ""
echo "Get these from: https://my.1password.com/developer-tools/infrastructure-secrets/connect"
echo ""
echo "TIP: Run with --auto to use OP_CONNECT_TOKEN env var and ./1password-credentials.json"
echo ""

# Check if secrets already exist
SKIP_CREDS=false
SKIP_TOKEN=false

if kubectl get secret onepassword-connect-secret -n "${NAMESPACE}" &> /dev/null; then
  echo "⚠️  Secret 'onepassword-connect-secret' already exists"
  read -p "Do you want to recreate it? (y/N): " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    kubectl delete secret onepassword-connect-secret -n "${NAMESPACE}"
  else
    echo "Skipping onepassword-connect-secret creation"
    SKIP_CREDS=true
  fi
fi

if kubectl get secret onepassword-connect-token -n "${NAMESPACE}" &> /dev/null; then
  echo "⚠️  Secret 'onepassword-connect-token' already exists"
  read -p "Do you want to recreate it? (y/N): " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    kubectl delete secret onepassword-connect-token -n "${NAMESPACE}"
  else
    echo "Skipping onepassword-connect-token creation"
    SKIP_TOKEN=true
  fi
fi

# Create credentials secret
if [ "${SKIP_CREDS}" != "true" ]; then
  echo ""
  echo "=========================================="
  echo "Step 1: 1Password Credentials File"
  echo "=========================================="
  echo ""
  read -p "Enter path to 1password-credentials.json: " CREDS_FILE

  if [ ! -f "${CREDS_FILE}" ]; then
    echo "❌ File not found: ${CREDS_FILE}"
    exit 1
  fi

  echo "Creating secret: onepassword-connect-secret"
  echo "Base64 encoding credentials file for 1Password Connect..."
  echo "(1Password Connect expects OP_SESSION to be base64-encoded JSON)"

  # Create temporary base64-encoded file
  # Kubernetes auto-decodes secrets when mounting as env vars, so we need to pre-encode
  cat "${CREDS_FILE}" | base64 | tr -d '\n' > /tmp/op-creds-b64.txt

  kubectl create secret generic onepassword-connect-secret \
    -n "${NAMESPACE}" \
    --from-file=1password-credentials.json=/tmp/op-creds-b64.txt

  # Clean up temporary file
  rm /tmp/op-creds-b64.txt

  echo "✅ Created onepassword-connect-secret (base64-encoded)"
fi

# Create token secret
if [ "${SKIP_TOKEN}" != "true" ]; then
  echo ""
  echo "=========================================="
  echo "Step 2: 1Password Connect Token"
  echo "=========================================="
  echo ""
  echo "Enter your 1Password Connect API token."
  echo "This token is used by External Secrets Operator to authenticate to 1Password Connect."
  echo ""
  read -sp "1Password Connect Token: " OP_TOKEN
  echo ""

  if [ -z "${OP_TOKEN}" ]; then
    echo "❌ Token cannot be empty"
    exit 1
  fi

  echo "Creating secret: onepassword-connect-token"
  kubectl create secret generic onepassword-connect-token \
    -n "${NAMESPACE}" \
    --from-literal=token="${OP_TOKEN}"

  echo "✅ Created onepassword-connect-token"
fi

echo ""
echo "=========================================="
echo "✅ Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Update the vault ID in infrastructure/base/external-secrets/secretstores/onepassword-secretstore.yaml"
echo "  2. Uncomment the onepassword-connect and secretstores in infrastructure/base/external-secrets/kustomization.yaml"
echo "  3. Deploy via Flux: flux reconcile kustomization external-secrets"
echo "  4. Verify: kubectl get pods -n external-secrets"
echo ""
echo "Test your setup by creating an ExternalSecret resource."
echo "See: infrastructure/base/external-secrets/secretstores/example-externalsecret.yaml"
echo ""
