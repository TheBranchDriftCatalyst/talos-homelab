#!/usr/bin/env bash
# Linkerd Service Mesh Dashboard - Control plane and mesh status
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
NAMESPACE="linkerd"
VIZ_NAMESPACE="linkerd-viz"
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
██╗     ██╗███╗   ██╗██╗  ██╗███████╗██████╗ ██████╗
██║     ██║████╗  ██║██║ ██╔╝██╔════╝██╔══██╗██╔══██╗
██║     ██║██╔██╗ ██║█████╔╝ █████╗  ██████╔╝██║  ██║
██║     ██║██║╚██╗██║██╔═██╗ ██╔══╝  ██╔══██╗██║  ██║
███████╗██║██║ ╚████║██║  ██╗███████╗██║  ██║██████╔╝
╚══════╝╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═════╝
                 ⚡ Service Mesh ⚡
EOF
  echo -e "${RESET}"
  echo ""
}

# ============================================================================
# Fetch linkerd data
# ============================================================================
fetch_linkerd_data() {
  echo -e "${DIM}Loading linkerd data...${RESET}"

  kubectl get pods -n "$NAMESPACE" -o json > "$CACHE_DIR/pods.json" 2> /dev/null &
  kubectl get pods -n "$VIZ_NAMESPACE" -o json > "$CACHE_DIR/viz-pods.json" 2> /dev/null &
  kubectl get deployments -n "$NAMESPACE" -o json > "$CACHE_DIR/deployments.json" 2> /dev/null &
  kubectl get deployments -n "$VIZ_NAMESPACE" -o json > "$CACHE_DIR/viz-deployments.json" 2> /dev/null &
  kubectl get namespaces -o json > "$CACHE_DIR/namespaces.json" 2> /dev/null &

  wait
  echo -e "\033[1A\033[2K"
}

# ============================================================================
# Print summary mode
# ============================================================================
print_summary() {
  dashboard_init
  fetch_linkerd_data

  local cp_running cp_total viz_running viz_total meshed_ns
  cp_running=$(jq '[.items[] | select(.status.phase == "Running")] | length' "$CACHE_DIR/pods.json" 2> /dev/null || echo "0")
  cp_total=$(jq '.items | length' "$CACHE_DIR/pods.json" 2> /dev/null || echo "0")
  viz_running=$(jq '[.items[] | select(.status.phase == "Running")] | length' "$CACHE_DIR/viz-pods.json" 2> /dev/null || echo "0")
  viz_total=$(jq '.items | length' "$CACHE_DIR/viz-pods.json" 2> /dev/null || echo "0")
  meshed_ns=$(jq '[.items[] | select(.metadata.annotations["linkerd.io/inject"] == "enabled")] | length' "$CACHE_DIR/namespaces.json" 2> /dev/null || echo "0")

  local status_icon="${GREEN}✓${RESET}"
  [[ "$cp_running" != "$cp_total" ]] && status_icon="${YELLOW}⚠${RESET}"
  [[ "$cp_running" == "0" ]] && status_icon="${RED}✗${RESET}"

  echo -e "    Linkerd: ${status_icon} cp: ${cp_running}/${cp_total} │ viz: ${viz_running}/${viz_total} │ meshed-ns: ${meshed_ns}"
}

# ============================================================================
# Print control plane section
# ============================================================================
print_control_plane() {
  print_section "CONTROL PLANE (${NAMESPACE})"

  local components=("linkerd-destination" "linkerd-identity" "linkerd-proxy-injector")

  for component in "${components[@]}"; do
    local status restarts
    status=$(jq -r ".items[] | select(.metadata.name | startswith(\"$component\")) | .status.phase" "$CACHE_DIR/pods.json" 2> /dev/null | head -1)
    restarts=$(jq -r ".items[] | select(.metadata.name | startswith(\"$component\")) | .status.containerStatuses[0].restartCount // 0" "$CACHE_DIR/pods.json" 2> /dev/null | head -1)

    local status_icon="${GREEN}●${RESET}"
    [[ -z "$status" || "$status" == "null" ]] && status_icon="${DIM}○${RESET}" && status="NotFound"
    [[ "$status" != "Running" && "$status" != "NotFound" ]] && status_icon="${YELLOW}○${RESET}"

    local restart_info=""
    [[ -n "$restarts" && "$restarts" != "0" && "$restarts" != "null" ]] && restart_info=" ${DIM}(${restarts} restarts)${RESET}"

    # Clean component name for display
    local display_name="${component#linkerd-}"
    echo -e "  ${TREE_BRANCH} ${status_icon} ${display_name}${restart_info}"
  done
  echo ""
}

# ============================================================================
# Print viz extension section
# ============================================================================
print_viz_extension() {
  print_section "VIZ EXTENSION (${VIZ_NAMESPACE})"

  if ! namespace_exists "$VIZ_NAMESPACE"; then
    echo -e "  ${DIM}Viz extension not installed${RESET}"
    echo ""
    return
  fi

  local components=("web" "metrics-api" "tap" "tap-injector")

  for component in "${components[@]}"; do
    local status restarts
    status=$(jq -r ".items[] | select(.metadata.name | contains(\"$component\")) | .status.phase" "$CACHE_DIR/viz-pods.json" 2> /dev/null | head -1)
    restarts=$(jq -r ".items[] | select(.metadata.name | contains(\"$component\")) | .status.containerStatuses[0].restartCount // 0" "$CACHE_DIR/viz-pods.json" 2> /dev/null | head -1)

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
# Print meshed namespaces section
# ============================================================================
print_meshed_namespaces() {
  print_section "MESHED NAMESPACES"

  local meshed_ns
  meshed_ns=$(jq -r '.items[] | select(.metadata.annotations["linkerd.io/inject"] == "enabled") | .metadata.name' "$CACHE_DIR/namespaces.json" 2> /dev/null)

  if [[ -z "$meshed_ns" ]]; then
    echo -e "  ${DIM}No namespaces with automatic injection${RESET}"
  else
    local count
    count=$(echo "$meshed_ns" | wc -l | tr -d ' ')
    echo -e "  ${DIM}${count} namespace(s) with injection enabled:${RESET}"
    echo "$meshed_ns" | while read -r ns; do
      echo -e "  ${TREE_BRANCH} ${CYAN}${ns}${RESET}"
    done
  fi
  echo ""
}

# ============================================================================
# Print health check section
# ============================================================================
print_health_check() {
  print_section "HEALTH CHECK"

  if ! command -v linkerd &> /dev/null; then
    echo -e "  ${DIM}linkerd CLI not installed - install for health checks${RESET}"
    echo ""
    return
  fi

  echo -e "  ${DIM}Running linkerd check...${RESET}"
  local check_result
  check_result=$(linkerd check --pre 2>&1 | tail -5 || true)

  if echo "$check_result" | grep -q "Status check results are"; then
    local status
    status=$(echo "$check_result" | grep "Status check" | head -1)
    if echo "$status" | grep -qi "√"; then
      echo -e "  ${GREEN}✓${RESET} All checks passed"
    else
      echo -e "  ${YELLOW}⚠${RESET} Some checks have warnings"
    fi
  else
    echo -e "  ${DIM}Run 'linkerd check' for full health status${RESET}"
  fi
  echo ""
}

# ============================================================================
# Print quick commands
# ============================================================================
print_commands() {
  print_section "QUICK COMMANDS"
  echo -e "  ${CYAN}pods${RESET}       │ kubectl get pods -n $NAMESPACE"
  echo -e "  ${CYAN}viz${RESET}        │ kubectl get pods -n $VIZ_NAMESPACE"
  echo -e "  ${CYAN}check${RESET}      │ linkerd check"
  echo -e "  ${CYAN}dashboard${RESET}  │ linkerd viz dashboard &"
  echo -e "  ${CYAN}top${RESET}        │ linkerd viz top deploy/<name> -n <ns>"
  echo -e "  ${CYAN}edges${RESET}      │ linkerd viz edges deploy -n <ns>"
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

  fetch_linkerd_data

  print_control_plane
  print_viz_extension
  print_meshed_namespaces
  print_health_check
  print_commands

  print_cluster_status
  echo ""
}

main "$@"
