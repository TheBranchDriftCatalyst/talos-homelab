#!/bin/bash

# Get the Kubernetes Dashboard admin token

set -e

# Change to project root
cd "$(dirname "$0")/.."

KUBECONFIG="${KUBECONFIG:-./.output/kubeconfig}"

# Ensure output directory exists
mkdir -p .output

echo "🔐 Kubernetes Dashboard Access"
echo "================================"
echo ""

# Create a token for the admin-user
echo "📋 Getting admin-user token..."
TOKEN=$(kubectl --kubeconfig "$KUBECONFIG" -n kubernetes-dashboard create token admin-user --duration=8760h 2> /dev/null)

if [ -z "$TOKEN" ]; then
  echo "❌ Failed to get token"
  exit 1
fi

echo "✅ Token retrieved!"
echo ""
echo "🔗 To access the dashboard:"
echo "   1. Run: task dashboard-proxy"
echo "      (or: kubectl --kubeconfig $KUBECONFIG proxy)"
echo "   2. Open: http://localhost:8001/api/v1/namespaces/kubernetes-dashboard/services/https:kubernetes-dashboard:/proxy/"
echo "   3. Use this token to login:"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "$TOKEN"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "💾 Token saved to: .output/dashboard-token.txt"
echo "$TOKEN" > .output/dashboard-token.txt
echo ""
