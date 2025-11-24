#!/usr/bin/env bash
# List all secrets from 1Password Connect API
# This script runs an ephemeral pod to query vaults and items

set -euo pipefail

# Configuration
NAMESPACE="${NAMESPACE:-external-secrets}"
VAULT_NAME="${VAULT_NAME:-catalyst-eso}"

# Colors
CYAN='\033[0;36m'
GREEN='\033[0;32m'
RED='\033[0;31m'
RESET='\033[0m'

echo -e "${CYAN}🔍 1Password Connect - List All Secrets${RESET}"
echo ""

# Check prerequisites
if ! command -v kubectl &> /dev/null; then
  echo -e "${RED}✗ kubectl not found${RESET}"
  exit 1
fi

# Check cluster connectivity
if ! kubectl cluster-info &> /dev/null; then
  echo -e "${RED}✗ Not connected to Kubernetes cluster${RESET}"
  exit 1
fi

# Get the token from the secret
echo -e "${CYAN}→ Retrieving 1Password Connect token...${RESET}"
OP_TOKEN=$(kubectl get secret onepassword-connect-token -n "${NAMESPACE}" -o jsonpath='{.data.token}' 2> /dev/null | base64 -d)

if [ -z "${OP_TOKEN}" ]; then
  echo -e "${RED}✗ Could not retrieve 1Password Connect token${RESET}"
  echo "  Make sure the secret 'onepassword-connect-token' exists in namespace '${NAMESPACE}'"
  exit 1
fi

echo -e "${CYAN}→ Querying 1Password Connect API...${RESET}"
echo ""

# Run ephemeral pod with curl and jq to query the API
kubectl run test-1p-list-secrets --rm -i --restart=Never --image=alpine:latest -n "${NAMESPACE}" \
  --env="OP_CONNECT_TOKEN=${OP_TOKEN}" \
  --env="VAULT_NAME=${VAULT_NAME}" \
  --env="NAMESPACE=${NAMESPACE}" \
  -- sh -c '
apk add --no-cache curl jq > /dev/null 2>&1

TOKEN="${OP_CONNECT_TOKEN}"
CONNECT_HOST="http://onepassword-connect.${NAMESPACE}.svc.cluster.local:8080"
VAULT_NAME="${VAULT_NAME}"

echo "=================================================="
echo "🔍 1Password Connect API - Vault Contents"
echo "=================================================="
echo ""

# Check health
if ! curl -sf "${CONNECT_HOST}/health" > /dev/null 2>&1; then
    echo "✗ 1Password Connect API is not reachable"
    exit 1
fi
echo "✓ Connect API: ${CONNECT_HOST}"
echo ""

# List all vaults
echo "📁 Available Vaults:"
echo "--------------------------------------------------"
VAULTS=$(curl -s -H "Authorization: Bearer ${TOKEN}" "${CONNECT_HOST}/v1/vaults")
echo "${VAULTS}" | jq -r ".[] | \"  📦 \(.name) (ID: \(.id))\""
echo ""

# Get vault ID
VAULT_ID=$(echo "${VAULTS}" | jq -r ".[] | select(.name == \"${VAULT_NAME}\") | .id")

if [ -z "${VAULT_ID}" ]; then
    echo "⚠️  Vault \"${VAULT_NAME}\" not found"
    echo "Available vaults listed above"
    exit 1
fi

echo "🔍 Items in \"${VAULT_NAME}\" vault:"
echo "--------------------------------------------------"
ITEMS=$(curl -s -H "Authorization: Bearer ${TOKEN}" "${CONNECT_HOST}/v1/vaults/${VAULT_ID}/items")
ITEM_COUNT=$(echo "${ITEMS}" | jq -r ". | length")
echo "${ITEMS}" | jq -r ".[] | \"  📄 \(.title) (ID: \(.id))\""
echo ""
echo "Total items: ${ITEM_COUNT}"
echo ""

echo "🔓 Secret Values:"
echo "--------------------------------------------------"
for ITEM_ID in $(echo "${ITEMS}" | jq -r ".[].id"); do
    ITEM_DETAILS=$(curl -s -H "Authorization: Bearer ${TOKEN}" "${CONNECT_HOST}/v1/vaults/${VAULT_ID}/items/${ITEM_ID}")
    ITEM_TITLE=$(echo "${ITEM_DETAILS}" | jq -r ".title")
    echo ""
    echo "📌 ${ITEM_TITLE}:"
    
    # Extract all fields with their values
    FIELDS=$(echo "${ITEM_DETAILS}" | jq -r ".fields[]? | select(.value != null and .value != \"\") | \"  \(.label // .id): \(.value)\"")
    
    if [ -z "${FIELDS}" ]; then
        echo "  (no fields with values)"
    else
        echo "${FIELDS}"
    fi
done

echo ""
echo "=================================================="
echo "✅ Complete"
echo "=================================================="
' 2>&1 | grep -v "would violate PodSecurity" | grep -v "All commands and output" | grep -v "If you don't see a command prompt"

echo ""
echo -e "${GREEN}✓ Done${RESET}"
