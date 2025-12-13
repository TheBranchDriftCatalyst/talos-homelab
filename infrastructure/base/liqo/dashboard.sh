#!/usr/bin/env bash
# Liqo Multi-Cluster Dashboard - Federation status display
#
# Usage:
#   ./dashboard.sh              # Show full dashboard
#   ./dashboard.sh --summary    # Compact one-line summary
#
# shellcheck disable=SC2016,SC2034

set -euo pipefail

# Get script directory and source common library
DASHBOARD_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${DASHBOARD_SCRIPT_DIR}/../../.." && pwd)"

# shellcheck source=../../../scripts/lib/dashboard-common.sh
source "${PROJECT_ROOT}/scripts/lib/dashboard-common.sh"

# ============================================================================
# Configuration
# ============================================================================
NAMESPACE="liqo"
MODE="full"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --summary | -s)
      MODE="summary"
      shift
      ;;
    --full | -f)
      MODE="full"
      shift
      ;;
    *)
      shift
      ;;
  esac
done

# ============================================================================
# Print ASCII header
# ============================================================================
print_header() {
  echo -e "${CYAN}${BOLD}"
  cat << 'EOF'
██╗     ██╗ ██████╗  ██████╗
██║     ██║██╔═══██╗██╔═══██╗
██║     ██║██║   ██║██║   ██║
██║     ██║██║▄▄ ██║██║   ██║
███████╗██║╚██████╔╝╚██████╔╝
╚══════╝╚═╝ ╚══▀▀═╝  ╚═════╝
       ⚡ Multi-Cluster Federation ⚡
EOF
  echo -e "${RESET}"
  echo ""
}

# ============================================================================
# Fetch liqo data
# ============================================================================
fetch_liqo_data() {
  echo -e "${DIM}Loading liqo data...${RESET}"

  kubectl get pods -n "$NAMESPACE" -o json > "$CACHE_DIR/pods.json" 2> /dev/null &
  kubectl get deployments -n "$NAMESPACE" -o json > "$CACHE_DIR/deployments.json" 2> /dev/null &
  kubectl get foreigncluster -o json > "$CACHE_DIR/foreignclusters.json" 2> /dev/null &
  kubectl get nodes -o json > "$CACHE_DIR/nodes.json" 2> /dev/null &
  kubectl get namespaceoffloading -A -o json > "$CACHE_DIR/namespaceoffloading.json" 2> /dev/null &

  wait
  echo -e "\033[1A\033[2K"
}

# ============================================================================
# Print summary mode
# ============================================================================
print_summary() {
  dashboard_init
  fetch_liqo_data

  local running_pods total_pods foreign_clusters offloaded_ns
  running_pods=$(jq '[.items[] | select(.status.phase == "Running")] | length' "$CACHE_DIR/pods.json" 2> /dev/null || echo "0")
  total_pods=$(jq '.items | length' "$CACHE_DIR/pods.json" 2> /dev/null || echo "0")
  foreign_clusters=$(jq '.items | length' "$CACHE_DIR/foreignclusters.json" 2> /dev/null || echo "0")
  offloaded_ns=$(jq '.items | length' "$CACHE_DIR/namespaceoffloading.json" 2> /dev/null || echo "0")

  local status_icon="${GREEN}✓${RESET}"
  [[ "$running_pods" != "$total_pods" ]] && status_icon="${YELLOW}⚠${RESET}"
  [[ "$running_pods" == "0" ]] && status_icon="${RED}✗${RESET}"

  echo -e "    Liqo: ${status_icon} ${running_pods}/${total_pods} running │ foreign-clusters: ${foreign_clusters} │ offloaded-ns: ${offloaded_ns}"
}

# ============================================================================
# Print control plane section
# ============================================================================
print_control_plane() {
  print_section "CONTROL PLANE"

  local components=("liqo-controller-manager" "liqo-crd-replicator" "liqo-fabric" "liqo-ipam" "liqo-metric-agent" "liqo-proxy" "liqo-webhook")

  for component in "${components[@]}"; do
    local status restarts
    status=$(jq -r ".items[] | select(.metadata.name | startswith(\"$component\")) | .status.phase" "$CACHE_DIR/pods.json" 2> /dev/null | head -1)
    restarts=$(jq -r ".items[] | select(.metadata.name | startswith(\"$component\")) | .status.containerStatuses[0].restartCount // 0" "$CACHE_DIR/pods.json" 2> /dev/null | head -1)

    local status_icon="${GREEN}●${RESET}"
    [[ -z "$status" || "$status" == "null" ]] && status_icon="${DIM}○${RESET}" && status="NotFound"
    [[ "$status" != "Running" && "$status" != "NotFound" ]] && status_icon="${YELLOW}○${RESET}"

    local restart_info=""
    [[ -n "$restarts" && "$restarts" != "0" && "$restarts" != "null" ]] && restart_info=" ${DIM}(${restarts} restarts)${RESET}"

    echo -e "  ${TREE_BRANCH} ${status_icon} ${component}${restart_info}"
  done
  echo ""
}

# ============================================================================
# Print foreign clusters section
# ============================================================================
print_foreign_clusters() {
  print_section "FOREIGN CLUSTERS"

  local cluster_count
  cluster_count=$(jq '.items | length' "$CACHE_DIR/foreignclusters.json" 2> /dev/null || echo "0")

  if [[ "$cluster_count" == "0" ]]; then
    echo -e "  ${DIM}No foreign clusters configured${RESET}"
    echo ""
    return
  fi

  jq -r '.items[] | .metadata.name + "|" + (.status.conditions[]? | select(.type == "NetworkStatus") | .status) + "|" + .spec.clusterID' "$CACHE_DIR/foreignclusters.json" 2> /dev/null | while IFS='|' read -r name network_status cluster_id; do
    local status_icon="${GREEN}●${RESET}"
    [[ "$network_status" != "True" ]] && status_icon="${YELLOW}○${RESET}"
    [[ -z "$network_status" ]] && status_icon="${RED}○${RESET}"

    echo -e "  ${TREE_BRANCH} ${status_icon} ${name}"
    echo -e "  ${TREE_CONT}   ${DIM}cluster-id: ${cluster_id:-unknown}${RESET}"
  done
  echo ""
}

# ============================================================================
# Print virtual nodes section
# ============================================================================
print_virtual_nodes() {
  print_section "VIRTUAL NODES"

  local virtual_nodes
  virtual_nodes=$(jq -r '.items[] | select(.metadata.labels["liqo.io/type"] == "virtual-node") | .metadata.name' "$CACHE_DIR/nodes.json" 2> /dev/null)

  if [[ -z "$virtual_nodes" ]]; then
    echo -e "  ${DIM}No virtual nodes present${RESET}"
  else
    echo "$virtual_nodes" | while read -r node; do
      local ready
      ready=$(jq -r ".items[] | select(.metadata.name == \"$node\") | .status.conditions[] | select(.type == \"Ready\") | .status" "$CACHE_DIR/nodes.json" 2> /dev/null)
      local status_icon="${GREEN}●${RESET}"
      [[ "$ready" != "True" ]] && status_icon="${YELLOW}○${RESET}"
      echo -e "  ${TREE_BRANCH} ${status_icon} ${node}"
    done
  fi
  echo ""
}

# ============================================================================
# Print namespace offloading section
# ============================================================================
print_namespace_offloading() {
  print_section "NAMESPACE OFFLOADING"

  local offload_count
  offload_count=$(jq '.items | length' "$CACHE_DIR/namespaceoffloading.json" 2> /dev/null || echo "0")

  if [[ "$offload_count" == "0" ]]; then
    echo -e "  ${DIM}No namespaces offloaded${RESET}"
    echo ""
    return
  fi

  jq -r '.items[] | .metadata.namespace + "|" + .spec.namespaceMappingStrategy' "$CACHE_DIR/namespaceoffloading.json" 2> /dev/null | while IFS='|' read -r ns strategy; do
    echo -e "  ${TREE_BRANCH} ${CYAN}${ns}${RESET} ${DIM}(${strategy:-default})${RESET}"
  done
  echo ""
}

# ============================================================================
# Print peering health section
# ============================================================================
print_peering_health() {
  print_section "PEERING HEALTH"

  local healthy_count total_count
  healthy_count=$(jq '[.items[] | select(.status.conditions[]? | select(.type == "NetworkStatus" and .status == "True"))] | length' "$CACHE_DIR/foreignclusters.json" 2> /dev/null || echo "0")
  total_count=$(jq '.items | length' "$CACHE_DIR/foreignclusters.json" 2> /dev/null || echo "0")

  if [[ "$total_count" == "0" ]]; then
    echo -e "  ${DIM}No peerings configured${RESET}"
  elif [[ "$healthy_count" == "$total_count" ]]; then
    echo -e "  ${GREEN}✓${RESET} All peerings healthy (${healthy_count}/${total_count})"
  else
    echo -e "  ${YELLOW}⚠${RESET} ${healthy_count}/${total_count} peerings healthy"
  fi
  echo ""
}

# ============================================================================
# Print quick commands
# ============================================================================
print_commands() {
  print_section "QUICK COMMANDS"
  echo -e "  ${CYAN}pods${RESET}          │ kubectl get pods -n $NAMESPACE"
  echo -e "  ${CYAN}clusters${RESET}      │ kubectl get foreigncluster"
  echo -e "  ${CYAN}offload${RESET}       │ kubectl get namespaceoffloading -A"
  echo -e "  ${CYAN}virtual${RESET}       │ kubectl get nodes -l liqo.io/type=virtual-node"
  echo -e "  ${CYAN}logs${RESET}          │ kubectl logs -n $NAMESPACE -l app.kubernetes.io/component=controller-manager -f"
  echo ""
}

# ============================================================================
# Main
# ============================================================================
main() {
  if [[ "$MODE" == "summary" ]]; then
    print_summary
    return 0
  fi

  dashboard_init

  clear
  print_header

  if ! namespace_exists "$NAMESPACE"; then
    echo -e "${RED}✗ Namespace '$NAMESPACE' not found${RESET}"
    echo ""
    exit 1
  fi

  fetch_liqo_data

  print_control_plane
  print_foreign_clusters
  print_virtual_nodes
  print_namespace_offloading
  print_peering_health
  print_commands

  print_cluster_status
  echo ""
}

main "$@"
