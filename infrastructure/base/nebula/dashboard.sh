#!/usr/bin/env bash
# Nebula Mesh VPN Dashboard - Overlay network status display
#
# Usage:
#   ./dashboard.sh              # Show full dashboard
#   ./dashboard.sh --summary    # Compact one-line summary
#
# shellcheck disable=SC1091,SC2016,SC2034

set -euo pipefail

# Get script directory and source common library
DASHBOARD_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${DASHBOARD_SCRIPT_DIR}/../../.." && pwd)"

# shellcheck source=../../../scripts/lib/dashboard-common.sh
source "${PROJECT_ROOT}/scripts/lib/dashboard-common.sh"

# ============================================================================
# Configuration
# ============================================================================
NAMESPACE="nebula-system"
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
███╗   ██╗███████╗██████╗ ██╗   ██╗██╗      █████╗
████╗  ██║██╔════╝██╔══██╗██║   ██║██║     ██╔══██╗
██╔██╗ ██║█████╗  ██████╔╝██║   ██║██║     ███████║
██║╚██╗██║██╔══╝  ██╔══██╗██║   ██║██║     ██╔══██║
██║ ╚████║███████╗██████╔╝╚██████╔╝███████╗██║  ██║
╚═╝  ╚═══╝╚══════╝╚═════╝  ╚═════╝ ╚══════╝╚═╝  ╚═╝
                 ⚡ Mesh VPN Overlay ⚡
EOF
  echo -e "${RESET}"
  echo ""
}

# ============================================================================
# Fetch nebula data
# ============================================================================
fetch_nebula_data() {
  echo -e "${DIM}Loading nebula data...${RESET}"

  kubectl get pods -n "$NAMESPACE" -o json > "$CACHE_DIR/pods.json" 2> /dev/null &
  kubectl get daemonset -n "$NAMESPACE" -o json > "$CACHE_DIR/daemonsets.json" 2> /dev/null &
  kubectl get configmap -n "$NAMESPACE" -o json > "$CACHE_DIR/configmaps.json" 2> /dev/null &
  kubectl get secret -n "$NAMESPACE" -o json > "$CACHE_DIR/secrets.json" 2> /dev/null &
  kubectl get nodes -o json > "$CACHE_DIR/nodes.json" 2> /dev/null &

  wait
  echo -e "\033[1A\033[2K"
}

# ============================================================================
# Get lighthouse IP from configmap
# ============================================================================
get_lighthouse_ip() {
  local config_data
  config_data=$(jq -r '.items[] | select(.metadata.name == "nebula-config") | .data["config.yaml"] // empty' "$CACHE_DIR/configmaps.json" 2> /dev/null)
  if [[ -n "$config_data" ]]; then
    # Extract lighthouse IP from static_host_map (look for 10.42.x.x pattern)
    echo "$config_data" | grep -oE '10\.42\.[0-9]+\.[0-9]+' | head -1
  fi
}

# ============================================================================
# Get overlay network from configmap
# ============================================================================
get_overlay_network() {
  local config_data
  config_data=$(jq -r '.items[] | select(.metadata.name == "nebula-config") | .data["config.yaml"] // empty' "$CACHE_DIR/configmaps.json" 2> /dev/null)
  if [[ -n "$config_data" ]]; then
    # Try to extract network info - look for 10.42.x.x pattern
    echo "$config_data" | grep -oE '10\.42\.[0-9]+\.[0-9]+/[0-9]+' | head -1
  fi
}

# ============================================================================
# Print summary mode
# ============================================================================
print_summary() {
  dashboard_init
  fetch_nebula_data

  local running_pods total_pods lighthouse_ip
  running_pods=$(jq '[.items[] | select(.status.phase == "Running")] | length' "$CACHE_DIR/pods.json" 2> /dev/null || echo "0")
  total_pods=$(jq '.items | length' "$CACHE_DIR/pods.json" 2> /dev/null || echo "0")
  lighthouse_ip=$(get_lighthouse_ip)

  local status_icon="${GREEN}✓${RESET}"
  [[ "$running_pods" != "$total_pods" ]] && status_icon="${YELLOW}⚠${RESET}"
  [[ "$running_pods" == "0" ]] && status_icon="${RED}✗${RESET}"

  local lighthouse_display=""
  [[ -n "$lighthouse_ip" ]] && lighthouse_display=" │ lighthouse: ${lighthouse_ip}"

  echo -e "    Nebula: ${status_icon} ${running_pods}/${total_pods} running${lighthouse_display}"
}

# ============================================================================
# Print mesh nodes section
# ============================================================================
print_mesh_nodes() {
  print_section "MESH NODES"

  # Get DaemonSet status
  local desired ready
  desired=$(jq -r '.items[] | select(.metadata.name | contains("nebula")) | .status.desiredNumberScheduled // 0' "$CACHE_DIR/daemonsets.json" 2> /dev/null | head -1)
  ready=$(jq -r '.items[] | select(.metadata.name | contains("nebula")) | .status.numberReady // 0' "$CACHE_DIR/daemonsets.json" 2> /dev/null | head -1)

  echo -e "  ${DIM}DaemonSet:${RESET} ${ready}/${desired} nodes running"
  echo ""

  # Show per-node status
  jq -r '.items[] | .metadata.name + "|" + .spec.nodeName + "|" + .status.phase + "|" + (.status.containerStatuses[0].restartCount // 0 | tostring)' "$CACHE_DIR/pods.json" 2> /dev/null | while IFS='|' read -r pod_name node_name phase restarts; do
    local status_icon="${GREEN}●${RESET}"
    [[ "$phase" != "Running" ]] && status_icon="${YELLOW}○${RESET}"

    echo -e "  ${TREE_BRANCH} ${status_icon} ${node_name} ${DIM}(${pod_name})${RESET}"
    [[ "$restarts" != "0" ]] && echo -e "  ${TREE_CONT}   ${DIM}restarts: ${restarts}${RESET}"
  done
  echo ""
}

# ============================================================================
# Print lighthouse status
# ============================================================================
print_lighthouse_status() {
  print_section "LIGHTHOUSE"

  local lighthouse_ip
  lighthouse_ip=$(get_lighthouse_ip)

  if [[ -n "$lighthouse_ip" ]]; then
    echo -e "  ${GREEN}●${RESET} Lighthouse IP: ${CYAN}${lighthouse_ip}${RESET}"
  else
    echo -e "  ${YELLOW}○${RESET} ${DIM}Lighthouse IP not found in config${RESET}"
  fi
  echo ""
}

# ============================================================================
# Print overlay network info
# ============================================================================
print_overlay_network() {
  print_section "OVERLAY NETWORK"

  local overlay_net
  overlay_net=$(get_overlay_network)

  if [[ -n "$overlay_net" ]]; then
    echo -e "  ${DIM}Network:${RESET} ${overlay_net}"
  else
    echo -e "  ${DIM}Network:${RESET} 10.42.0.0/16 ${DIM}(default)${RESET}"
  fi

  # Show expected hosts
  echo -e "  ${DIM}Expected hosts:${RESET}"
  echo -e "    ${TREE_BRANCH} 10.42.0.1 - talos00 (control-plane)"
  echo -e "    ${TREE_BRANCH} 10.42.1.1 - talos01 (worker)"
  echo -e "    ${TREE_LAST} 10.42.2.1 - aws-worker (GPU)"
  echo ""
}

# ============================================================================
# Print certificate info
# ============================================================================
print_cert_info() {
  print_section "CERTIFICATES"

  local cert_secret
  cert_secret=$(jq -r '.items[] | select(.metadata.name | contains("nebula-certs") or contains("nebula-secret")) | .metadata.name' "$CACHE_DIR/secrets.json" 2> /dev/null | head -1)

  if [[ -n "$cert_secret" ]]; then
    echo -e "  ${GREEN}●${RESET} Certificate secret: ${cert_secret}"
  else
    echo -e "  ${YELLOW}○${RESET} ${DIM}No certificate secret found${RESET}"
  fi
  echo ""
}

# ============================================================================
# Print quick commands
# ============================================================================
print_commands() {
  print_section "QUICK COMMANDS"
  echo -e "  ${CYAN}pods${RESET}      │ kubectl get pods -n $NAMESPACE"
  echo -e "  ${CYAN}logs${RESET}      │ kubectl logs -n $NAMESPACE -l app=nebula -f"
  echo -e "  ${CYAN}config${RESET}    │ kubectl get configmap -n $NAMESPACE nebula-config -o yaml"
  echo -e "  ${CYAN}restart${RESET}   │ kubectl rollout restart daemonset -n $NAMESPACE"
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

  fetch_nebula_data

  print_mesh_nodes
  print_lighthouse_status
  print_overlay_network
  print_cert_info
  print_commands

  print_cluster_status
  echo ""
}

main "$@"
