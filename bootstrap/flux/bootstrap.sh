#!/usr/bin/env bash
set -euo pipefail

# Bootstrap FluxCD for infrastructure management
# FluxCD manages: namespaces, storage, monitoring, observability
# ArgoCD manages: applications (arr-stack)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "=========================================="
echo "FluxCD Bootstrap for Infrastructure"
echo "=========================================="
echo ""

# Check prerequisites
if ! command -v flux &> /dev/null; then
  echo "❌ Flux CLI not installed"
  echo "Install with: brew install fluxcd/tap/flux"
  exit 1
fi

echo "✅ Flux CLI installed"
echo ""

# Check if Git repo is configured
if [ -z "${GITHUB_USER:-}" ] || [ -z "${GITHUB_REPO:-}" ]; then
  echo "⚠️  Environment variables not set:"
  echo "   export GITHUB_USER=your-github-username"
  echo "   export GITHUB_REPO=talos-fix"
  echo ""
  read -p "Enter GitHub username: " GITHUB_USER
  read -p "Enter GitHub repo name [talos-fix]: " GITHUB_REPO
  GITHUB_REPO=${GITHUB_REPO:-talos-fix}
  export GITHUB_USER GITHUB_REPO
fi

echo "Repository: ${GITHUB_USER}/${GITHUB_REPO}"
echo ""

# Bootstrap Flux
echo "🚀 Bootstrapping FluxCD..."
flux bootstrap github \
  --owner="${GITHUB_USER}" \
  --repository="${GITHUB_REPO}" \
  --branch=main \
  --path=clusters/catalyst-cluster \
  --personal \
  --read-write-key

echo ""
echo "=========================================="
echo "✅ FluxCD Bootstrap Complete!"
echo "=========================================="
echo ""
echo "FluxCD is now managing:"
echo "  - Namespaces (media-dev, media-prod)"
echo "  - Storage (local-path-provisioner)"
echo "  - Monitoring (kube-prometheus-stack)"
echo "  - Observability (Graylog, OpenSearch, MongoDB, Fluent Bit)"
echo ""
echo "Verify Flux status:"
echo "  flux get all"
echo "  flux get kustomizations"
echo ""
echo "ArgoCD continues to manage applications (arr-stack)"
echo ""
