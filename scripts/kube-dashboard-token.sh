#!/bin/bash

# Get tokens for all cluster dashboards and UIs
# TODO: meeds to get other stuff as well

set -e

# Change to project root
cd "$(dirname "$0")/.."

KUBECONFIG="${KUBECONFIG:-./.output/kubeconfig}"

# Ensure output directory exists
mkdir -p .output

echo "================================================================================"
echo "                         CLUSTER DASHBOARD TOKENS"
echo "================================================================================"
echo ""

# ------------------------------------------------------------------------------
# Kubernetes Dashboard
# ------------------------------------------------------------------------------
echo "1. KUBERNETES DASHBOARD"
echo "   URL: http://localhost:8001/api/v1/namespaces/kubernetes-dashboard/services/https:kubernetes-dashboard:/proxy/"
echo "   Start proxy: task dashboard-proxy"
echo ""

K8S_TOKEN=$(kubectl --kubeconfig "$KUBECONFIG" -n kubernetes-dashboard create token admin-user --duration=8760h 2> /dev/null || echo "")
if [ -n "$K8S_TOKEN" ]; then
  echo "   Token:"
  echo "   ────────────────────────────────────────────────────────────────────────────"
  echo "   $K8S_TOKEN"
  echo "   ────────────────────────────────────────────────────────────────────────────"
  echo "$K8S_TOKEN" > .output/dashboard-token.txt
else
  echo "   ⚠️  Token not available (kubernetes-dashboard not installed?)"
fi
echo ""

# ------------------------------------------------------------------------------
# Headlamp
# ------------------------------------------------------------------------------
echo "2. HEADLAMP"
echo "   URL: http://headlamp.talos00"
echo ""

HEADLAMP_TOKEN=$(kubectl --kubeconfig "$KUBECONFIG" -n infra-testing create token headlamp --duration=8760h 2> /dev/null || echo "")
if [ -n "$HEADLAMP_TOKEN" ]; then
  echo "   Token:"
  echo "   ────────────────────────────────────────────────────────────────────────────"
  echo "   $HEADLAMP_TOKEN"
  echo "   ────────────────────────────────────────────────────────────────────────────"
  echo "$HEADLAMP_TOKEN" > .output/headlamp-token.txt
else
  echo "   ⚠️  Token not available (headlamp not installed?)"
fi
echo ""

# ------------------------------------------------------------------------------
# ArgoCD
# ------------------------------------------------------------------------------
echo "3. ARGOCD"
echo "   URL: http://argocd.talos00"
echo "   Username: admin"
echo ""

ARGOCD_PASS=$(kubectl --kubeconfig "$KUBECONFIG" -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" 2> /dev/null | base64 -d || echo "")
if [ -n "$ARGOCD_PASS" ]; then
  echo "   Password:"
  echo "   ────────────────────────────────────────────────────────────────────────────"
  echo "   $ARGOCD_PASS"
  echo "   ────────────────────────────────────────────────────────────────────────────"
  echo "$ARGOCD_PASS" > .output/argocd-password.txt
else
  echo "   ⚠️  Password not available (argocd not installed?)"
fi
echo ""

# ------------------------------------------------------------------------------
# Grafana
# ------------------------------------------------------------------------------
echo "4. GRAFANA"
echo "   URL: http://grafana.talos00"
echo "   Username: admin"
echo "   Password: prom-operator"
echo ""

# ------------------------------------------------------------------------------
# Graylog
# ------------------------------------------------------------------------------
echo "5. GRAYLOG"
echo "   URL: http://graylog.talos00"
echo "   Username: admin"
echo "   Password: admin"
echo ""

# ------------------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------------------
echo "================================================================================"
echo "                              SAVED FILES"
echo "================================================================================"
echo ""
echo "   .output/dashboard-token.txt  - Kubernetes Dashboard token"
echo "   .output/headlamp-token.txt   - Headlamp token"
echo "   .output/argocd-password.txt  - ArgoCD admin password"
echo ""
