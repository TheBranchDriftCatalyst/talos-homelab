#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  Cluster Audit Report Generator                                              ║
# ║  Comprehensive Markdown audit report for Talos cluster                       ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# Source shared library
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"

# ══════════════════════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════════════════════
AUDIT_DIR="${OUTPUT_DIR}/audit"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
REPORT_FILE="${AUDIT_DIR}/cluster-audit-${TIMESTAMP}.md"

# ══════════════════════════════════════════════════════════════════════════════
# Banner
# ══════════════════════════════════════════════════════════════════════════════
print_banner "
 █████╗ ██╗   ██╗██████╗ ██╗████████╗
██╔══██╗██║   ██║██╔══██╗██║╚══██╔══╝
███████║██║   ██║██║  ██║██║   ██║
██╔══██║██║   ██║██║  ██║██║   ██║
██║  ██║╚██████╔╝██████╔╝██║   ██║
╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚═╝   ╚═╝
          ${ICON_LIGHTNING} Cluster Audit Report ${ICON_LIGHTNING}
" "$YELLOW"

print_section "CONFIGURATION"
print_kv "Output" "$AUDIT_DIR"
print_kv "Timestamp" "$TIMESTAMP"
echo ""

# Create output directory
ensure_dir "$AUDIT_DIR"

# ══════════════════════════════════════════════════════════════════════════════
# Helper Functions
# ══════════════════════════════════════════════════════════════════════════════
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

# ══════════════════════════════════════════════════════════════════════════════
# Gather Data
# ══════════════════════════════════════════════════════════════════════════════
log_step "1" "Gathering Cluster Data"

info "Collecting version information..."
TALOS_VERSION=$(talosctl --talosconfig "$TALOSCONFIG" --nodes "$TALOS_NODE" version 2>/dev/null | grep 'Tag:' | head -1 | awk '{print $2}')
K8S_VERSION=$(kubectl version --short 2>/dev/null | grep Server | awk '{print $3}' || kubectl get nodes -o jsonpath='{.items[0].status.nodeInfo.kubeletVersion}' 2>/dev/null)

info "Collecting pod statistics..."
TOTAL_PODS=$(kubectl get pods -A --no-headers 2>/dev/null | wc -l | tr -d ' ')
RUNNING_PODS=$(kubectl get pods -A --no-headers 2>/dev/null | grep -c Running || echo 0)
PENDING_PODS=$(kubectl get pods -A --no-headers 2>/dev/null | grep -c Pending || echo 0)
FAILED_PODS=$(kubectl get pods -A --no-headers 2>/dev/null | grep -cE '(Error|CrashLoop|Failed)' || echo 0)

info "Collecting resource counts..."
TOTAL_NAMESPACES=$(kubectl get namespaces --no-headers 2>/dev/null | wc -l | tr -d ' ')
TOTAL_DEPLOYMENTS=$(kubectl get deployments -A --no-headers 2>/dev/null | wc -l | tr -d ' ')
TOTAL_SERVICES=$(kubectl get svc -A --no-headers 2>/dev/null | wc -l | tr -d ' ')
TOTAL_CRDS=$(kubectl get crd --no-headers 2>/dev/null | wc -l | tr -d ' ')
TRAEFIK_CRDS=$(kubectl get crd --no-headers 2>/dev/null | grep -c traefik || echo 0)
HELM_RELEASES=$(helm list -A --no-headers 2>/dev/null | wc -l | tr -d ' ')

info "Checking health status..."
HEALTH_STATUS=$(check_health)

success "Data collection complete"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Generate Report
# ══════════════════════════════════════════════════════════════════════════════
log_step "2" "Generating Markdown Report"

{
  cat << 'EOF'
# 🔍 Talos Cluster Audit Report

EOF
  echo "**Generated:** $(date '+%B %d, %Y at %H:%M:%S %Z')"
  echo "**Cluster:** ${CLUSTER_NAME}"
  echo "**Node IP:** ${TALOS_NODE}"
  echo ""
  echo "---"
  echo ""
  echo "## 📊 Executive Summary"
  echo ""

  if [[ "$HEALTH_STATUS" == "HEALTHY" ]]; then
    echo "✅ **Status:** HEALTHY & OPERATIONAL"
  else
    echo "⚠️ **Status:** ${HEALTH_STATUS}"
  fi

  echo ""
  echo "| Metric | Value |"
  echo "|--------|-------|"
  echo "| **Talos Version** | ${TALOS_VERSION} |"
  echo "| **Kubernetes Version** | ${K8S_VERSION} |"
  echo "| **Total Pods** | ${RUNNING_PODS}/${TOTAL_PODS} Running |"
  echo "| **Namespaces** | ${TOTAL_NAMESPACES} |"
  echo "| **Services** | ${TOTAL_SERVICES} |"
  echo "| **Deployments** | ${TOTAL_DEPLOYMENTS} |"
  echo "| **Helm Releases** | ${HELM_RELEASES} |"
  echo "| **Custom CRDs** | ${TOTAL_CRDS} (${TRAEFIK_CRDS} Traefik) |"
  echo ""
  echo "---"
  echo ""
  echo "## 🏗️ Infrastructure"
  echo ""
  echo "### Talos Version Information"
  echo ""
  echo '```'
  talosctl --talosconfig "$TALOSCONFIG" --nodes "$TALOS_NODE" version 2>/dev/null
  echo '```'
  echo ""
  echo "### Kubernetes Nodes"
  echo ""
  echo '```'
  kubectl get nodes -o wide 2>/dev/null
  echo '```'
  echo ""
  echo "**Node Taints:**"
  echo '```'
  kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints 2>/dev/null
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
  talosctl --talosconfig "$TALOSCONFIG" --nodes "$TALOS_NODE" services 2>/dev/null
  echo '```'
  echo ""
  echo "---"
  echo ""
  echo "## 🏷️ Namespaces"
  echo ""
  echo '```'
  kubectl get namespaces 2>/dev/null
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
  echo "| ✅ Running | ${RUNNING_PODS} |"
  echo "| ⏳ Pending | ${PENDING_PODS} |"
  echo "| ❌ Failed | ${FAILED_PODS} |"
  echo "| **Total** | **${TOTAL_PODS}** |"
  echo ""
  echo "### All Pods"
  echo ""
  echo '```'
  kubectl get pods -A -o wide 2>/dev/null
  echo '```'
  echo ""
  echo "---"
  echo ""
  echo "## 📦 Workloads"
  echo ""
  echo "### Deployments"
  echo ""
  echo '```'
  kubectl get deployments -A 2>/dev/null
  echo '```'
  echo ""
  echo "### DaemonSets"
  echo ""
  echo '```'
  kubectl get daemonsets -A 2>/dev/null
  echo '```'
  echo ""
  echo "---"
  echo ""
  echo "## 🌐 Network Services"
  echo ""
  echo "### Services"
  echo ""
  echo '```'
  kubectl get svc -A 2>/dev/null
  echo '```'
  echo ""
  echo "### IngressRoutes"
  echo ""
  echo '```'
  kubectl get ingressroute -A 2>/dev/null || echo "No IngressRoutes found"
  echo '```'
  echo ""
  echo "---"
  echo ""
  echo "## 💾 Storage"
  echo ""
  echo "### Persistent Volumes & Claims"
  echo ""
  echo '```'
  kubectl get pv,pvc -A 2>/dev/null || echo "No PVs or PVCs"
  echo '```'
  echo ""
  echo "### Storage Classes"
  echo ""
  echo '```'
  kubectl get storageclasses 2>/dev/null || echo "No StorageClasses"
  echo '```'
  echo ""
  echo "---"
  echo ""
  echo "## 📦 Helm Releases"
  echo ""
  echo '```'
  helm list -A 2>/dev/null
  echo '```'
  echo ""
  echo "---"
  echo ""
  echo "## 🔧 Custom Resource Definitions"
  echo ""
  echo "**Total CRDs:** ${TOTAL_CRDS}"
  echo ""
  echo "**Traefik CRDs:** ${TRAEFIK_CRDS}"
  echo ""
  if [[ "$TRAEFIK_CRDS" -gt 0 ]]; then
    echo '```'
    kubectl get crd 2>/dev/null | grep traefik
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
  kubectl top nodes 2>&1 || echo "⚠️ Metrics server not installed"
  echo '```'
  echo ""
  echo "### Pod Metrics (Top 20)"
  echo ""
  echo '```'
  kubectl top pods -A 2>&1 | head -20 || echo "⚠️ Metrics server not installed"
  echo '```'
  echo ""
  echo "---"
  echo ""
  echo "## 📝 Recent Events (Last 20)"
  echo ""
  echo '```'
  kubectl get events -A --sort-by='.lastTimestamp' 2>/dev/null | tail -20 || echo "No recent events"
  echo '```'
  echo ""
  echo "---"
  echo ""
  echo "_Report generated on $(date)_"

} > "$REPORT_FILE"

success "Report generated"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════
print_summary "success"

print_section "REPORT DETAILS"
print_kv "File" "$REPORT_FILE"
print_kv "Size" "$(du -h "$REPORT_FILE" | cut -f1)"
echo ""

print_section "VIEW REPORT"
echo -e "  ${CYAN}cat ${REPORT_FILE}${RESET}"
echo -e "  ${CYAN}open ${REPORT_FILE}${RESET}  ${DIM}# macOS${RESET}"
echo ""

echo -e "${GREEN}${BOLD}${EMOJI_PARTY} Audit complete!${RESET}"
echo ""
