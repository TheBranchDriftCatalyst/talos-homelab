#!/bin/bash
# Store Nebula certificates in AWS Secrets Manager
# These will be used by GPU worker instances

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== Storing Nebula Certs in AWS Secrets Manager ===${NC}"

# Configuration
NEBULA_CA_DIR="${NEBULA_CA_DIR:-$HOME/.nebula-ca}"
REGION="${AWS_REGION:-us-west-2}"

# Check certs exist
for cert in ca.crt aws-gpu-worker.crt aws-gpu-worker.key; do
  if [[ ! -f "${NEBULA_CA_DIR}/${cert}" ]]; then
    echo -e "${RED}Error: ${NEBULA_CA_DIR}/${cert} not found${NC}"
    exit 1
  fi
done

echo "Reading certificates from: ${NEBULA_CA_DIR}"

# Function to create or update secret
store_secret() {
  local name="$1"
  local value="$2"

  # Check if secret exists
  if aws secretsmanager describe-secret --secret-id "$name" 2>/dev/null; then
    echo "Updating secret: ${name}"
    aws secretsmanager put-secret-value \
      --secret-id "$name" \
      --secret-string "$value" \
      --output text > /dev/null
  else
    echo "Creating secret: ${name}"
    aws secretsmanager create-secret \
      --name "$name" \
      --description "Nebula certificate for hybrid-llm" \
      --secret-string "$value" \
      --tags Key=Project,Value=hybrid-llm \
      --output text > /dev/null
  fi
}

# Store secrets
store_secret "nebula/ca-crt" "$(cat ${NEBULA_CA_DIR}/ca.crt)"
store_secret "nebula/aws-gpu-crt" "$(cat ${NEBULA_CA_DIR}/aws-gpu-worker.crt)"
store_secret "nebula/aws-gpu-key" "$(cat ${NEBULA_CA_DIR}/aws-gpu-worker.key)"

echo ""
echo -e "${GREEN}=== Secrets Stored ===${NC}"
echo "Secrets created:"
echo "  - nebula/ca-crt"
echo "  - nebula/aws-gpu-crt"
echo "  - nebula/aws-gpu-key"
echo ""
echo "GPU worker instances will fetch these on bootstrap."
