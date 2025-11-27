#!/bin/bash

# Cluster Audit Report Generator
# Generates a comprehensive Markdown audit report

set -e

# Change to project root
cd "$(dirname "$0")/.."

KUBECONFIG="${KUBECONFIG:-./.output/kubeconfig}"
TALOSCONFIG="./configs/talosconfig"
OUTPUT_DIR="./.output/audit"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
REPORT_FILE="$OUTPUT_DIR/cluster-audit-$TIMESTAMP.md"

# Create output directory
mkdir -p "$OUTPUT_DIR"

echo "🔍 Talos Cluster Audit Report Generator"
echo "========================================"
echo ""
echo "Output directory: $OUTPUT_DIR"
echo "Timestamp: $TIMESTAMP"
echo ""

# Helper function to check health status
check_health() {
  if talosctl --talosconfig "$TALOSCONFIG" --nodes "$TALOS_NODE" health --server=false 2>&1 | grep -q "waiting for"; then
    if talosctl --talosconfig "$TALOSCONFIG" --nodes "$TALOS_NODE" health --server=false 2>&1 | tail -1 | grep -q "OK"; then
      echo "HEALTHY"
    else
      echo "UNHEALTHY"
    fi
  else
    echo "UNKNOWN"
  fi
}

# Gather data
TALOS_VERSION=$(talosctl --talosconfig "$TALOSCONFIG" --nodes "$TALOS_NODE" version 2> /dev/null | grep 'Tag:' | head -1 | awk '{print $2}')
K8S_VERSION=$(kubectl --kubeconfig "$KUBECONFIG" version --short 2> /dev/null | grep Server | awk '{print $3}' || kubectl --kubeconfig "$KUBECONFIG" get nodes -o jsonpath='{.items[0].status.nodeInfo.kubeletVersion}')
TOTAL_PODS=$(kubectl --kubeconfig "$KUBECONFIG" get pods -A --no-headers 2> /dev/null | wc -l | tr -d ' ')
RUNNING_PODS=$(kubectl --kubeconfig "$KUBECONFIG" get pods -A --no-headers 2> /dev/null | grep -c Running || echo 0)
PENDING_PODS=$(kubectl --kubeconfig "$KUBECONFIG" get pods -A --no-headers 2> /dev/null | grep -c Pending || echo 0)
FAILED_PODS=$(kubectl --kubeconfig "$KUBECONFIG" get pods -A --no-headers 2> /dev/null | grep -cE '(Error|CrashLoop|Failed)' || echo 0)
TOTAL_NAMESPACES=$(kubectl --kubeconfig "$KUBECONFIG" get namespaces --no-headers 2> /dev/null | wc -l | tr -d ' ')
TOTAL_DEPLOYMENTS=$(kubectl --kubeconfig "$KUBECONFIG" get deployments -A --no-headers 2> /dev/null | wc -l | tr -d ' ')
TOTAL_SERVICES=$(kubectl --kubeconfig "$KUBECONFIG" get svc -A --no-headers 2> /dev/null | wc -l | tr -d ' ')
TOTAL_CRDS=$(kubectl --kubeconfig "$KUBECONFIG" get crd --no-headers 2> /dev/null | wc -l | tr -d ' ')
TRAEFIK_CRDS=$(kubectl --kubeconfig "$KUBECONFIG" get crd --no-headers 2> /dev/null | grep -c traefik || echo 0)
HELM_RELEASES=$(helm list -A --kubeconfig "$KUBECONFIG" --no-headers 2> /dev/null | wc -l | tr -d ' ')
HEALTH_STATUS=$(check_health)

# Generate Markdown report
{
  cat << 'EOF'
# 🔍 Talos Cluster Audit Report

EOF
  echo "**Generated:** $(date '+%B %d, %Y at %H:%M:%S %Z')"
  echo "**Cluster:** homelab-single"
  echo "**Node IP:** $TALOS_NODE"
  echo ""
  echo "---"
  echo ""
  echo "## 📊 Executive Summary"
  echo ""

  if [ "$HEALTH_STATUS" = "HEALTHY" ]; then
    echo "✅ **Status:** HEALTHY & OPERATIONAL"
  else
    echo "⚠️ **Status:** $HEALTH_STATUS"
  fi

  echo ""
  echo "| Metric | Value |"
  echo "|--------|-------|"
  echo "| **Talos Version** | $TALOS_VERSION |"
  echo "| **Kubernetes Version** | $K8S_VERSION |"
  echo "| **Total Pods** | $RUNNING_PODS/$TOTAL_PODS Running |"
  echo "| **Namespaces** | $TOTAL_NAMESPACES |"
  echo "| **Services** | $TOTAL_SERVICES |"
  echo "| **Deployments** | $TOTAL_DEPLOYMENTS |"
  echo "| **Helm Releases** | $HELM_RELEASES |"
  echo "| **Custom CRDs** | $TOTAL_CRDS ($TRAEFIK_CRDS Traefik) |"
  echo ""
  echo "---"
  echo ""
  echo "## 🏗️ Infrastructure"
  echo ""
  echo "### Talos Version Information"
  echo ""
  echo '```'
  talosctl --talosconfig "$TALOSCONFIG" --nodes "$TALOS_NODE" version 2> /dev/null
  echo '```'
  echo ""
  echo "### Kubernetes Nodes"
  echo ""
  echo '```'
  kubectl --kubeconfig "$KUBECONFIG" get nodes -o wide 2> /dev/null
  echo '```'
  echo ""
  echo "**Node Taints:**"
  echo '```'
  kubectl --kubeconfig "$KUBECONFIG" get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints 2> /dev/null
  echo '```'
  echo ""
  echo "---"
  echo ""
  echo "## 💚 Health Status"
  echo ""
  echo '```'
  talosctl --talosconfig "$TALOSCONFIG" --nodes "$TALOS_NODE" health --server=false 2>&1 || true
  echo '```'
  echo ""
  echo "---"
  echo ""
  echo "## ⚙️ System Services"
  echo ""
  echo '```'
  talosctl --talosconfig "$TALOSCONFIG" --nodes "$TALOS_NODE" services 2> /dev/null
  echo '```'
  echo ""
  echo "---"
  echo ""
  echo "## 🏷️ Namespaces"
  echo ""
  echo '```'
  kubectl --kubeconfig "$KUBECONFIG" get namespaces 2> /dev/null
  echo '```'
  echo ""
  echo "---"
  echo ""
  echo "## 🐳 Pods"
  echo ""
  echo "### Summary"
  echo ""
  echo "| Status | Count |"
  echo "|--------|-------|"
  echo "| ✅ Running | $RUNNING_PODS |"
  echo "| ⏳ Pending | $PENDING_PODS |"
  echo "| ❌ Failed | $FAILED_PODS |"
  echo "| **Total** | **$TOTAL_PODS** |"
  echo ""
  echo "### All Pods"
  echo ""
  echo '```'
  kubectl --kubeconfig "$KUBECONFIG" get pods -A -o wide 2> /dev/null
  echo '```'
  echo ""
  echo "---"
  echo ""
  echo "## 📦 Workloads"
  echo ""
  echo "### Deployments"
  echo ""
  echo '```'
  kubectl --kubeconfig "$KUBECONFIG" get deployments -A 2> /dev/null
  echo '```'
  echo ""
  echo "### DaemonSets"
  echo ""
  echo '```'
  kubectl --kubeconfig "$KUBECONFIG" get daemonsets -A 2> /dev/null
  echo '```'
  echo ""
  echo "---"
  echo ""
  echo "## 🌐 Network Services"
  echo ""
  echo "### Services"
  echo ""
  echo '```'
  kubectl --kubeconfig "$KUBECONFIG" get svc -A 2> /dev/null
  echo '```'
  echo ""
  echo "### IngressRoutes"
  echo ""
  echo '```'
  kubectl --kubeconfig "$KUBECONFIG" get ingressroute -A 2> /dev/null || echo "No IngressRoutes found"
  echo '```'
  echo ""
  echo "---"
  echo ""
  echo "## 📋 Configuration"
  echo ""
  echo "### ConfigMaps by Namespace"
  echo ""
  echo '```'
  kubectl --kubeconfig "$KUBECONFIG" get configmaps -A --no-headers 2> /dev/null | awk '{print $1}' | sort | uniq -c
  echo '```'
  echo ""
  echo "### Secrets by Namespace"
  echo ""
  echo '```'
  kubectl --kubeconfig "$KUBECONFIG" get secrets -A --no-headers 2> /dev/null | awk '{print $1}' | sort | uniq -c
  echo '```'
  echo ""
  echo "---"
  echo ""
  echo "## 💾 Storage"
  echo ""
  echo "### Persistent Volumes & Claims"
  echo ""
  echo '```'
  kubectl --kubeconfig "$KUBECONFIG" get pv,pvc -A 2> /dev/null || echo "No PVs or PVCs"
  echo '```'
  echo ""
  echo "### Storage Classes"
  echo ""
  echo '```'
  kubectl --kubeconfig "$KUBECONFIG" get storageclasses 2> /dev/null || echo "No StorageClasses"
  echo '```'
  echo ""
  echo "---"
  echo ""
  echo "## 📦 Helm Releases"
  echo ""
  echo '```'
  helm list -A --kubeconfig "$KUBECONFIG" 2> /dev/null
  echo '```'
  echo ""
  echo "---"
  echo ""
  echo "## 🔧 Custom Resource Definitions"
  echo ""
  echo "**Total CRDs:** $TOTAL_CRDS"
  echo ""
  echo "**Traefik CRDs:** $TRAEFIK_CRDS"
  echo ""
  if [ "$TRAEFIK_CRDS" -gt 0 ]; then
    echo '```'
    kubectl --kubeconfig "$KUBECONFIG" get crd 2> /dev/null | grep traefik
    echo '```'
  fi
  echo ""
  echo "---"
  echo ""
  echo "## 🗄️ etcd Status"
  echo ""
  echo '```'
  talosctl --talosconfig "$TALOSCONFIG" --nodes "$TALOS_NODE" etcd status 2>&1
  echo '```'
  echo ""
  echo "---"
  echo ""
  echo "## 📊 Resource Usage"
  echo ""
  echo "### Node Metrics"
  echo ""
  echo '```'
  kubectl --kubeconfig "$KUBECONFIG" top nodes 2>&1 || echo "⚠️ Metrics server not installed"
  echo '```'
  echo ""
  echo "### Pod Metrics (Top 20)"
  echo ""
  echo '```'
  kubectl --kubeconfig "$KUBECONFIG" top pods -A 2>&1 | head -20 || echo "⚠️ Metrics server not installed"
  echo '```'
  echo ""
  echo "---"
  echo ""
  echo "## 📝 Recent Events (Last 20)"
  echo ""
  echo '```'
  kubectl --kubeconfig "$KUBECONFIG" get events -A --sort-by='.lastTimestamp' 2> /dev/null | tail -20 || echo "No recent events"
  echo '```'
  echo ""
  echo "---"
  echo ""
  echo "## ℹ️ Cluster Info"
  echo ""
  echo '```'
  kubectl --kubeconfig "$KUBECONFIG" cluster-info 2> /dev/null
  echo '```'
  echo ""
  echo "---"
  echo ""
  echo "## 🎯 Quick Access Commands"
  echo ""
  echo '```bash'
  echo "# Cluster health"
  echo "talosctl --talosconfig ./configs/talosconfig --nodes $TALOS_NODE health"
  echo ""
  echo "# View pods"
  echo "kubectl --kubeconfig ./.output/kubeconfig get pods -A"
  echo ""
  echo "# Traefik dashboard"
  echo "curl http://192.168.1.54/whoami"
  echo ""
  echo "# Dashboard token"
  echo "./scripts/dashboard-token.sh"
  echo '```'
  echo ""
  echo "---"
  echo ""
  echo "_Report generated on $(date)_"

} > "$REPORT_FILE"

echo "✅ Markdown report generated: $REPORT_FILE"
echo ""
echo "📄 View report:"
echo "   cat $REPORT_FILE"
echo ""
echo "🎉 Audit complete!"
