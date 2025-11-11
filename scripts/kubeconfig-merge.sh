#!/bin/bash

# Kubeconfig Merge Script
# Automatically discovers and merges all kubeconfigs from .output/ directory

set -e

# Change to project root
cd "$(dirname "$0")/.."

DEFAULT_KUBECONFIG="${HOME}/.kube/config"
OUTPUT_DIR=".output"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}🔧 Kubeconfig Auto-Merge Utility${NC}"
echo -e "${BLUE}================================${NC}"
echo ""

# Check if .output directory exists
if [ ! -d "$OUTPUT_DIR" ]; then
    echo -e "${RED}❌ No $OUTPUT_DIR directory found${NC}"
    echo "Run './scripts/provision.sh' or './scripts/provision-local.sh' first"
    exit 1
fi

# Discover all kubeconfig files in .output/
echo -e "${BLUE}🔍 Discovering kubeconfigs in $OUTPUT_DIR...${NC}"
echo ""

# Find all files named 'kubeconfig' recursively
FOUND_CONFIGS=()
while IFS= read -r -d '' config_path; do
    FOUND_CONFIGS+=("$config_path")
done < <(find "$OUTPUT_DIR" -type f -name "kubeconfig" -print0 2>/dev/null)

if [ ${#FOUND_CONFIGS[@]} -eq 0 ]; then
    echo -e "${YELLOW}⚠️  No kubeconfig files found in $OUTPUT_DIR${NC}"
    echo ""
    echo "Expected locations:"
    echo "  .output/kubeconfig         (production cluster)"
    echo "  .output/local/kubeconfig   (local test cluster)"
    echo "  .output/*/kubeconfig       (any other environment)"
    exit 1
fi

echo -e "${GREEN}Found ${#FOUND_CONFIGS[@]} kubeconfig file(s):${NC}"
for config in "${FOUND_CONFIGS[@]}"; do
    echo "  - $config"
done
echo ""

# Create ~/.kube directory if it doesn't exist
mkdir -p "${HOME}/.kube"

# Backup existing config if it exists
if [ -f "$DEFAULT_KUBECONFIG" ]; then
    BACKUP_FILE="${DEFAULT_KUBECONFIG}.backup.$(date +%Y%m%d-%H%M%S)"
    echo -e "${BLUE}📦 Backing up existing kubeconfig...${NC}"
    cp "$DEFAULT_KUBECONFIG" "$BACKUP_FILE"
    echo -e "${GREEN}✅ Backup created: $BACKUP_FILE${NC}"
    echo ""
fi

# Process each discovered kubeconfig
MERGED_COUNT=0
SKIPPED_COUNT=0

for KUBECONFIG_PATH in "${FOUND_CONFIGS[@]}"; do
    # Derive context name from path
    # .output/kubeconfig -> homelab-single
    # .output/local/kubeconfig -> talos-local
    # .output/staging/kubeconfig -> talos-staging
    # etc.

    if [[ "$KUBECONFIG_PATH" == ".output/kubeconfig" ]]; then
        # Root level is production
        CONTEXT_NAME="homelab-single"
        CLUSTER_NAME="homelab-single"
        ENV_NAME="production"
    else
        # Extract directory name between .output/ and /kubeconfig
        ENV_DIR=$(echo "$KUBECONFIG_PATH" | sed 's|^.output/||' | sed 's|/kubeconfig$||')
        CONTEXT_NAME="talos-${ENV_DIR}"
        CLUSTER_NAME="talos-${ENV_DIR}"
        ENV_NAME="$ENV_DIR"
    fi

    echo -e "${BLUE}📋 Processing: $ENV_NAME${NC}"
    echo "   Path: $KUBECONFIG_PATH"
    echo "   Context: $CONTEXT_NAME"
    echo "   Cluster: $CLUSTER_NAME"

    # Check if context already exists
    if [ -f "$DEFAULT_KUBECONFIG" ]; then
        if kubectl config get-contexts "$CONTEXT_NAME" &>/dev/null; then
            echo -e "${YELLOW}   ⚠️  Context '$CONTEXT_NAME' already exists${NC}"
            read -p "   Remove and re-merge? (y/N) " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                echo "   🗑️  Removing existing context..."
                kubectl config delete-context "$CONTEXT_NAME" 2>/dev/null || true
                kubectl config delete-cluster "$CLUSTER_NAME" 2>/dev/null || true
            else
                echo -e "${YELLOW}   ⏭️  Skipping${NC}"
                echo ""
                ((SKIPPED_COUNT++))
                continue
            fi
        fi
    fi

    # Read original context name from the kubeconfig
    ORIGINAL_CONTEXT=$(kubectl --kubeconfig="$KUBECONFIG_PATH" config current-context 2>/dev/null || echo "")

    if [ -z "$ORIGINAL_CONTEXT" ]; then
        echo -e "${YELLOW}   ⚠️  No current context found, using first available${NC}"
        ORIGINAL_CONTEXT=$(kubectl --kubeconfig="$KUBECONFIG_PATH" config get-contexts -o name | head -1 || echo "")
    fi

    if [ -z "$ORIGINAL_CONTEXT" ]; then
        echo -e "${RED}   ❌ No contexts found in kubeconfig, skipping${NC}"
        echo ""
        ((SKIPPED_COUNT++))
        continue
    fi

    # Build KUBECONFIG env var for merging
    if [ -f "$DEFAULT_KUBECONFIG" ]; then
        export KUBECONFIG="${KUBECONFIG_PATH}:${DEFAULT_KUBECONFIG}"
    else
        export KUBECONFIG="${KUBECONFIG_PATH}"
    fi

    # Rename context if needed
    if [ "$ORIGINAL_CONTEXT" != "$CONTEXT_NAME" ]; then
        kubectl config rename-context "$ORIGINAL_CONTEXT" "$CONTEXT_NAME" 2>/dev/null || true
    fi

    # Update cluster name for clarity
    kubectl config set-context "$CONTEXT_NAME" --cluster="$CLUSTER_NAME" 2>/dev/null || true

    # Flatten and write
    kubectl config view --flatten > "${DEFAULT_KUBECONFIG}.tmp"
    mv "${DEFAULT_KUBECONFIG}.tmp" "$DEFAULT_KUBECONFIG"
    chmod 600 "$DEFAULT_KUBECONFIG"

    echo -e "${GREEN}   ✅ Merged${NC}"
    echo ""
    ((MERGED_COUNT++))
done

# Unset KUBECONFIG to use the default
unset KUBECONFIG

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✅ Merge Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${BLUE}📊 Summary:${NC}"
echo "   Merged: $MERGED_COUNT"
echo "   Skipped: $SKIPPED_COUNT"
echo ""

# Show available contexts
if [ -f "$DEFAULT_KUBECONFIG" ]; then
    echo -e "${BLUE}📋 Available contexts:${NC}"
    kubectl config get-contexts
    echo ""
fi

# Try to set a sensible default context
if [ $MERGED_COUNT -gt 0 ]; then
    # Prefer production if available, otherwise use the first merged
    if kubectl config get-contexts homelab-single &>/dev/null; then
        DEFAULT_CONTEXT="homelab-single"
    elif kubectl config get-contexts talos-local &>/dev/null; then
        DEFAULT_CONTEXT="talos-local"
    else
        DEFAULT_CONTEXT=$(kubectl config get-contexts -o name | head -1)
    fi

    if [ -n "$DEFAULT_CONTEXT" ]; then
        echo -e "${BLUE}🎯 Setting current context to: $DEFAULT_CONTEXT${NC}"
        kubectl config use-context "$DEFAULT_CONTEXT"
        echo ""
    fi
fi

echo -e "${GREEN}✅ Setup complete!${NC}"
echo ""
echo -e "${BLUE}🎯 Quick commands (no --kubeconfig needed!):${NC}"
echo "  kubectl get nodes"
echo "  kubectl get pods -A"
echo "  kubectl top nodes"
echo ""
echo -e "${BLUE}🔀 Context switching:${NC}"
if command -v kubectx &> /dev/null; then
    echo "  kubectx                    # List contexts"
    echo "  kubectx homelab-single     # Switch to production"
    echo "  kubectx talos-local        # Switch to local test"
    echo "  kubectx -                  # Switch to previous context"
else
    echo "  kubectl config get-contexts"
    echo "  kubectl config use-context <context-name>"
fi
echo ""
if command -v kubens &> /dev/null; then
    echo -e "${BLUE}📦 Namespace switching:${NC}"
    echo "  kubens                     # List namespaces"
    echo "  kubens media-dev           # Switch to dev namespace"
    echo "  kubens media-prod          # Switch to prod namespace"
    echo "  kubens -                   # Switch to previous namespace"
    echo ""
fi
if command -v k9s &> /dev/null; then
    echo -e "${BLUE}👾 K9s TUI:${NC}"
    echo "  k9s                        # Launch interactive cluster manager"
    echo "  k9s --context <name>       # Launch for specific context"
    echo ""
fi
