#!/bin/bash
# Export AWS credentials from Kubernetes secret to .envrc
# This script fetches AWS creds from the cluster and adds them to .envrc idempotently
#
# Usage: ./scripts/hybrid-llm/export-aws-creds.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENVRC_FILE="$REPO_ROOT/.envrc"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Fetching AWS credentials from cluster...${NC}"

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}Error: kubectl not found${NC}"
    exit 1
fi

# Check if secret exists
if ! kubectl get secret aws-credentials -n hybrid-llm &> /dev/null; then
    echo -e "${RED}Error: Secret 'aws-credentials' not found in namespace 'hybrid-llm'${NC}"
    echo -e "${YELLOW}Make sure the ExternalSecret has synced from 1Password.${NC}"
    echo ""
    echo "To check status:"
    echo "  kubectl get externalsecret aws-credentials -n hybrid-llm"
    echo ""
    echo "To create the 1Password item:"
    echo "  1. Go to 1Password vault 'catalyst-eso'"
    echo "  2. Create a new item named 'aws_access_key'"
    echo "  3. Add fields: 'access_key_id' and 'secret_access_key'"
    exit 1
fi

# Fetch credentials
AWS_ACCESS_KEY_ID=$(kubectl get secret aws-credentials -n hybrid-llm -o jsonpath='{.data.access_key_id}' | base64 -d)
AWS_SECRET_ACCESS_KEY=$(kubectl get secret aws-credentials -n hybrid-llm -o jsonpath='{.data.secret_access_key}' | base64 -d)

if [[ -z "$AWS_ACCESS_KEY_ID" || -z "$AWS_SECRET_ACCESS_KEY" ]]; then
    echo -e "${RED}Error: Could not fetch AWS credentials from secret${NC}"
    exit 1
fi

echo -e "${GREEN}Successfully fetched AWS credentials${NC}"

# Create .envrc if it doesn't exist
if [[ ! -f "$ENVRC_FILE" ]]; then
    echo "# Environment variables for talos-homelab" > "$ENVRC_FILE"
    echo "" >> "$ENVRC_FILE"
fi

# Function to update or add a variable in .envrc
update_envrc_var() {
    local var_name="$1"
    local var_value="$2"

    if grep -q "^export ${var_name}=" "$ENVRC_FILE"; then
        # Variable exists, update it
        if [[ "$(uname)" == "Darwin" ]]; then
            sed -i '' "s|^export ${var_name}=.*|export ${var_name}=\"${var_value}\"|" "$ENVRC_FILE"
        else
            sed -i "s|^export ${var_name}=.*|export ${var_name}=\"${var_value}\"|" "$ENVRC_FILE"
        fi
        echo -e "  Updated ${var_name}"
    else
        # Variable doesn't exist, add it
        echo "export ${var_name}=\"${var_value}\"" >> "$ENVRC_FILE"
        echo -e "  Added ${var_name}"
    fi
}

echo -e "${YELLOW}Updating .envrc...${NC}"

# Update AWS credentials
update_envrc_var "AWS_ACCESS_KEY_ID" "$AWS_ACCESS_KEY_ID"
update_envrc_var "AWS_SECRET_ACCESS_KEY" "$AWS_SECRET_ACCESS_KEY"

# Also add region if not present
if ! grep -q "^export AWS_DEFAULT_REGION=" "$ENVRC_FILE"; then
    update_envrc_var "AWS_DEFAULT_REGION" "us-west-2"
fi

echo -e "${GREEN}Done! AWS credentials written to .envrc${NC}"
echo ""
echo -e "${YELLOW}Run 'direnv allow' to load the environment variables${NC}"
