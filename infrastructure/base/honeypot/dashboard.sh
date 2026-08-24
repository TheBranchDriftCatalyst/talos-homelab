#!/usr/bin/env bash
# Honeypot Dashboard - Cowrie SSH/Telnet honeypot status
#
# Usage:
#   ./dashboard.sh              # Full dashboard
#   ./dashboard.sh --summary    # One-line status
#
# shellcheck disable=SC2016,SC2034

set -euo pipefail

# Get script directory and source common library
DASHBOARD_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${DASHBOARD_SCRIPT_DIR}/../../.." && pwd)"

# shellcheck source=../../../scripts/lib/dashboard-common.sh
source "${PROJECT_ROOT}/scripts/lib/dashboard-common.sh"

# ============================================================================
# Honeypot-specific configuration
# ============================================================================
HONEYPOT_NAMESPACE="honeypot"
DOMAIN="${DOMAIN:-talos00}"

# ============================================================================
# Print ASCII header
# ============================================================================
print_header() {
  echo -e "${CYAN}${BOLD}"
  cat << 'EOF'
 ██████╗ ██████╗ ██╗    ██╗██████╗ ██╗███████╗    ██╗  ██╗ ██████╗ ███╗   ██╗███████╗██╗   ██╗██████╗  ██████╗ ████████╗
██╔════╝██╔═══██╗██║    ██║██╔══██╗██║██╔════╝    ██║  ██║██╔═══██╗████╗  ██║██╔════╝╚██╗ ██╔╝██╔══██╗██╔═══██╗╚══██╔══╝
██║     ██║   ██║██║ █╗ ██║██████╔╝██║█████╗      ███████║██║   ██║██╔██╗ ██║█████╗   ╚████╔╝ ██████╔╝██║   ██║   ██║
██║     ██║   ██║██║███╗██║██╔══██╗██║██╔══╝      ██╔══██║██║   ██║██║╚██╗██║██╔══╝    ╚██╔╝  ██╔═══╝ ██║   ██║   ██║
╚██████╗╚██████╔╝╚███╔███╔╝██║  ██║██║███████╗    ██║  ██║╚██████╔╝██║ ╚████║███████╗   ██║   ██║     ╚██████╔╝   ██║
 ╚═════╝ ╚═════╝  ╚══╝╚══╝ ╚═╝  ╚═╝╚═╝╚══════╝    ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝╚══════╝   ╚═╝   ╚═╝      ╚═════╝    ╚═╝
                                           SSH/Telnet Honeypot
EOF
  echo -e "${RESET}"
  echo ""
}

# ============================================================================
# Fetch honeypot data
# ============================================================================
fetch_honeypot_data() {
  echo -e "${DIM}Loading honeypot data...${RESET}"

  kubectl get pods -n "$HONEYPOT_NAMESPACE" -o json > "$CACHE_DIR/pods.json" 2> /dev/null &
  kubectl get svc -n "$HONEYPOT_NAMESPACE" -o json > "$CACHE_DIR/services.json" 2> /dev/null &
  kubectl get pvc -n "$HONEYPOT_NAMESPACE" -o json > "$CACHE_DIR/pvcs.json" 2> /dev/null &
  kubectl get ciliumnetworkpolicy -n "$HONEYPOT_NAMESPACE" -o json > "$CACHE_DIR/policies.json" 2> /dev/null &
  kubectl get ingressroutetcp -n "$HONEYPOT_NAMESPACE" -o json > "$CACHE_DIR/ingressroutes.json" 2> /dev/null &

  wait
  echo -e "\033[1A\033[2K"
}

# ============================================================================
# Get cowrie stats from logs
# ============================================================================
get_cowrie_stats() {
  local log_output
  log_output=$(kubectl logs -n "$HONEYPOT_NAMESPACE" deploy/cowrie --tail=1000 2> /dev/null || echo "")

  if [[ -n "$log_output" ]]; then
    local total_connections ssh_attempts login_attempts
    total_connections=$(echo "$log_output" | grep -c "New connection" || echo "0")
    login_attempts=$(echo "$log_output" | grep -c "login attempt" || echo "0")

    echo "${total_connections}|${login_attempts}"
  else
    echo "0|0"
  fi
}

# ============================================================================
# Print cowrie service status
# ============================================================================
print_cowrie_status() {
  print_section "COWRIE STATUS"

  local status ready
  status=$(jq -r '.items[] | select(.metadata.labels.app == "cowrie") | .status.phase' "$CACHE_DIR/pods.json" 2> /dev/null | head -1)
  ready=$(jq -r '.items[] | select(.metadata.labels.app == "cowrie") | .status.containerStatuses[0].ready // false' "$CACHE_DIR/pods.json" 2> /dev/null | head -1)

  [[ -z "$status" ]] && status="NotFound"

  local status_indicator
  status_indicator=$(print_status "$status" "$ready")

  local pod_name node_name
  pod_name=$(jq -r '.items[] | select(.metadata.labels.app == "cowrie") | .metadata.name' "$CACHE_DIR/pods.json" 2> /dev/null | head -1)
  node_name=$(jq -r '.items[] | select(.metadata.labels.app == "cowrie") | .spec.nodeName' "$CACHE_DIR/pods.json" 2> /dev/null | head -1)

  echo -e "  ${BOLD}Cowrie Pod${RESET} ${status_indicator}"
  echo -e "    ${DIM}Pod:${RESET}  ${pod_name:-N/A}"
  echo -e "    ${DIM}Node:${RESET} ${node_name:-N/A}"
  echo ""

  # Connection stats
  local stats connections logins
  stats=$(get_cowrie_stats)
  IFS='|' read -r connections logins <<< "$stats"

  echo -e "  ${BOLD}Activity (last 1000 log lines):${RESET}"
  echo -e "    ${CYAN}Connections:${RESET} ${connections}"
  echo -e "    ${YELLOW}Login Attempts:${RESET} ${logins}"
  echo ""
}

# ============================================================================
# Print network policies
# ============================================================================
print_network_policies() {
  print_section "NETWORK POLICIES (CiliumNetworkPolicy)"

  if [[ -f "$CACHE_DIR/policies.json" ]]; then
    local policies
    policies=$(jq -r '.items[] | .metadata.name' "$CACHE_DIR/policies.json" 2> /dev/null)

    if [[ -n "$policies" ]]; then
      while IFS= read -r policy; do
        local valid
        valid=$(jq -r ".items[] | select(.metadata.name == \"$policy\") | .status.isValid // \"unknown\"" "$CACHE_DIR/policies.json" 2> /dev/null)
        local status_icon="${GREEN}●${RESET}"
        [[ "$valid" != "True" && "$valid" != "true" ]] && status_icon="${YELLOW}○${RESET}"
        echo -e "  ${status_icon} ${policy}"
      done <<< "$policies"
    else
      echo -e "  ${DIM}No policies found${RESET}"
    fi
  else
    echo -e "  ${DIM}Unable to fetch policies${RESET}"
  fi
  echo ""
}

# ============================================================================
# Print ingress routes
# ============================================================================
print_ingress_routes() {
  print_section "TCP INGRESS (Traefik)"

  if [[ -f "$CACHE_DIR/ingressroutes.json" ]]; then
    local routes
    routes=$(jq -r '.items[] | .metadata.name + "|" + (.spec.entryPoints[0] // "unknown") + "|" + (.spec.routes[0].services[0].port | tostring)' "$CACHE_DIR/ingressroutes.json" 2> /dev/null)

    if [[ -n "$routes" ]]; then
      while IFS='|' read -r name entrypoint port; do
        echo -e "  ${CYAN}${name}${RESET} ${DIM}→${RESET} entrypoint:${BOLD}${entrypoint}${RESET} port:${BOLD}${port}${RESET}"
      done <<< "$routes"
    else
      echo -e "  ${DIM}No TCP routes found${RESET}"
    fi
  else
    echo -e "  ${DIM}Unable to fetch ingress routes${RESET}"
  fi
  echo ""
}

# ============================================================================
# Print storage status
# ============================================================================
print_storage_status() {
  print_section "STORAGE"

  if [[ -f "$CACHE_DIR/pvcs.json" ]]; then
    local pvcs
    pvcs=$(jq -r '.items[] | .metadata.name + "|" + .status.phase + "|" + .spec.resources.requests.storage + "|" + (.spec.storageClassName // "default")' "$CACHE_DIR/pvcs.json" 2> /dev/null)

    if [[ -n "$pvcs" ]]; then
      while IFS='|' read -r name status size sc; do
        local status_icon="${GREEN}●${RESET}"
        [[ "$status" != "Bound" ]] && status_icon="${YELLOW}○${RESET}"
        echo -e "  ${status_icon} ${name} ${BLUE}(${size})${RESET} ${DIM}[${sc}]${RESET}"
      done <<< "$pvcs"
    else
      echo -e "  ${DIM}No PVCs found${RESET}"
    fi
  else
    echo -e "  ${DIM}Unable to fetch PVCs${RESET}"
  fi
  echo ""
}

# ============================================================================
# Print quick commands
# ============================================================================
print_quick_commands() {
  print_section "QUICK COMMANDS"
  echo -e "  ${CYAN}logs${RESET}        │ kubectl logs -n honeypot deploy/cowrie -f"
  echo -e "  ${CYAN}logs-json${RESET}   │ kubectl logs -n honeypot deploy/cowrie -f | grep -E '^\\{'"
  echo -e "  ${CYAN}test-ssh${RESET}    │ ssh -p 2222 root@192.168.1.54"
  echo -e "  ${CYAN}test-telnet${RESET} │ nc 192.168.1.54 2223"
  echo -e "  ${CYAN}restart${RESET}     │ kubectl rollout restart deploy/cowrie -n honeypot"
  echo -e "  ${CYAN}policies${RESET}    │ kubectl get ciliumnetworkpolicy -n honeypot"
  echo ""
}

# ============================================================================
# Print access info
# ============================================================================
print_access_info() {
  print_section "ACCESS (Internal Only - LAN)"
  echo -e "  ${BOLD}SSH Honeypot:${RESET}    ${CYAN}ssh -p 2222 root@192.168.1.54${RESET}"
  echo -e "  ${BOLD}Telnet Honeypot:${RESET} ${CYAN}nc 192.168.1.54 2223${RESET}"
  echo ""
  echo -e "  ${DIM}Note: Access restricted to 192.168.1.0/24 via CiliumNetworkPolicy${RESET}"
  echo ""
}

# ============================================================================
# Summary mode
# ============================================================================
print_summary() {
  dashboard_init

  local status ready
  status=$(kubectl get pods -n "$HONEYPOT_NAMESPACE" -l app=cowrie -o jsonpath='{.items[0].status.phase}' 2> /dev/null || echo "Unknown")
  ready=$(kubectl get pods -n "$HONEYPOT_NAMESPACE" -l app=cowrie -o jsonpath='{.items[0].status.containerStatuses[0].ready}' 2> /dev/null || echo "false")

  local status_icon="${GREEN}●${RESET}"
  [[ "$status" != "Running" ]] && status_icon="${RED}●${RESET}"
  [[ "$ready" != "true" ]] && status_icon="${YELLOW}●${RESET}"

  echo -e "    Honeypot: ${status_icon} Cowrie ${status} │ SSH:2222 Telnet:2223"
}

# ============================================================================
# Main
# ============================================================================
main() {
  local mode="full"

  while [[ $# -gt 0 ]]; do
    case $1 in
      --summary | -s)
        mode="summary"
        shift
        ;;
      --full | -f)
        mode="full"
        shift
        ;;
      *) shift ;;
    esac
  done

  if [[ "$mode" == "summary" ]]; then
    print_summary
    return 0
  fi

  dashboard_init
  clear
  print_header
  fetch_honeypot_data
  print_cluster_status
  echo ""
  print_cowrie_status
  print_network_policies
  print_ingress_routes
  print_storage_status
  print_access_info
  print_quick_commands
}

main "$@"
