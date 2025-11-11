#!/bin/bash

# Kubeconfig Unmerge Script
# Removes the homelab-single context from ~/.kube/config

set -e

# Change to project root
cd "$(dirname "$0")/.."

DEFAULT_KUBECONFIG="${HOME}/.kube/config"
CONTEXT_NAME="${CONTEXT_NAME:-homelab-single}"
CLUSTER_NAME="${CLUSTER_NAME:-homelab-single}"

echo "🗑️  Kubeconfig Unmerge Utility"
echo "=============================="
echo ""
echo "Context to remove: $CONTEXT_NAME"
echo "Cluster to remove: $CLUSTER_NAME"
echo ""

# Check if config exists
if [ ! -f "$DEFAULT_KUBECONFIG" ]; then
    echo "❌ No kubeconfig found at $DEFAULT_KUBECONFIG"
    exit 0
fi

# Check if context exists
if ! kubectl config get-contexts "$CONTEXT_NAME" &>/dev/null; then
    echo "ℹ️  Context '$CONTEXT_NAME' not found in ~/.kube/config"
    echo "Nothing to remove."
    exit 0
fi

# Backup existing config
echo "📦 Backing up existing kubeconfig..."
cp "$DEFAULT_KUBECONFIG" "${DEFAULT_KUBECONFIG}.backup.$(date +%Y%m%d-%H%M%S)"
echo "✅ Backup created"
echo ""

# Show what will be removed
echo "📋 Current contexts:"
kubectl config get-contexts
echo ""

# Confirm removal
read -p "Remove '$CONTEXT_NAME' context? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Unmerge cancelled."
    exit 0
fi

echo ""
echo "🗑️  Removing context..."

# Get the user associated with this context (for informational purposes)
USER_NAME=$(kubectl config view -o jsonpath="{.contexts[?(@.name=='$CONTEXT_NAME')].context.user}" 2>/dev/null || echo "")

# Delete context
kubectl config delete-context "$CONTEXT_NAME" 2>/dev/null || echo "Context already removed"

# Delete cluster
kubectl config delete-cluster "$CLUSTER_NAME" 2>/dev/null || echo "Cluster already removed"

# Optionally delete user (ask first since it might be shared)
if [ -n "$USER_NAME" ]; then
    echo ""
    read -p "Also remove user '$USER_NAME'? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        kubectl config delete-user "$USER_NAME" 2>/dev/null || echo "User already removed"
    else
        echo "ℹ️  Keeping user '$USER_NAME' (may be used by other contexts)"
    fi
fi

echo ""
echo "✅ Context removed successfully!"
echo ""

# Show remaining contexts
REMAINING=$(kubectl config get-contexts --no-headers 2>/dev/null | wc -l | tr -d ' ')
if [ "$REMAINING" -gt 0 ]; then
    echo "📋 Remaining contexts:"
    kubectl config get-contexts
    echo ""

    # If there's a current context, show it
    CURRENT=$(kubectl config current-context 2>/dev/null || echo "")
    if [ -n "$CURRENT" ]; then
        echo "Current context: $CURRENT"
    else
        echo "⚠️  No current context set. Use 'kubectx <name>' to set one."
    fi
else
    echo "ℹ️  No contexts remaining in ~/.kube/config"
fi

echo ""
echo "💡 To re-merge, run: task kubeconfig-merge"
echo ""
