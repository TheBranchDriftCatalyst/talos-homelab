#!/usr/bin/env bash
# Catalyst LLM Dashboard - Hybrid cloud LLM inference status
# Shows local K8s services and remote AWS worker status via Nebula mesh
#
# Usage:
#   ./dashboard.sh              # Show full dashboard
#   ./dashboard.sh --test       # Test Ollama API connectivity
#
# shellcheck disable=SC2016,SC2034

set -euo pipefail

# Get script directory and source common library
DASHBOARD_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${DASHBOARD_SCRIPT_DIR}/../../.." && pwd)"

# shellcheck source=../../../scripts/lib/dashboard-common.sh
source "${PROJECT_ROOT}/scripts/lib/dashboard-common.sh"

# ============================================================================
# Catalyst LLM Configuration
# ============================================================================
LLM_NAMESPACE="catalyst-llm"
NEBULA_WORKER_IP="10.42.2.1"
OLLAMA_PORT="11434"
OLLAMA_LOCAL_URL="http://ollama.talos00"
OLLAMA_API_URL="http://llm.talos00"

# ============================================================================
# Print ASCII header
# ============================================================================
print_header() {
  echo -e "${CYAN}${BOLD}"
  cat << 'EOF'
 ██████╗ █████╗ ████████╗ █████╗ ██╗  ██╗   ██╗███████╗████████╗    ██╗     ██╗     ███╗   ███╗
██╔════╝██╔══██╗╚══██╔══╝██╔══██╗██║  ╚██╗ ██╔╝██╔════╝╚══██╔══╝    ██║     ██║     ████╗ ████║
██║     ███████║   ██║   ███████║██║   ╚████╔╝ ███████╗   ██║       ██║     ██║     ██╔████╔██║
██║     ██╔══██║   ██║   ██╔══██║██║    ╚██╔╝  ╚════██║   ██║       ██║     ██║     ██║╚██╔╝██║
╚██████╗██║  ██║   ██║   ██║  ██║███████╗██║   ███████║   ██║       ███████╗███████╗██║ ╚═╝ ██║
 ╚═════╝╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝   ╚══════╝   ╚═╝       ╚══════╝╚══════╝╚═╝     ╚═╝
                          Hybrid Cloud LLM Inference Platform
EOF
  echo -e "${RESET}"
  echo ""
}

# ============================================================================
# Fetch LLM stack data
# ============================================================================
fetch_llm_data() {
  echo -e "${DIM}Loading LLM stack data...${RESET}"

  # Check if namespace exists
  if ! namespace_exists "$LLM_NAMESPACE"; then
    echo -e "\033[1A\033[2K"
    echo -e "${YELLOW}Namespace '$LLM_NAMESPACE' not found${RESET}"
    return 1
  fi

  # Fetch K8s data in parallel
  kubectl get svc -n "$LLM_NAMESPACE" -o json > "$CACHE_DIR/services.json" 2>/dev/null &
  kubectl get endpoints -n "$LLM_NAMESPACE" -o json > "$CACHE_DIR/endpoints.json" 2>/dev/null &
  kubectl get pods -n "$LLM_NAMESPACE" -o json > "$CACHE_DIR/pods.json" 2>/dev/null &
  kubectl get pvc -n "$LLM_NAMESPACE" -o json > "$CACHE_DIR/pvcs.json" 2>/dev/null &
  kubectl get ingressroute -n "$LLM_NAMESPACE" -o json > "$CACHE_DIR/ingressroutes.json" 2>/dev/null &

  wait

  # Clear loading message
  echo -e "\033[1A\033[2K"
}

# ============================================================================
# Test Nebula mesh connectivity to AWS worker
# ============================================================================
test_nebula_connectivity() {
  local timeout_sec=3

  # Test if we can reach the Nebula worker IP
  if timeout "$timeout_sec" nc -z "$NEBULA_WORKER_IP" "$OLLAMA_PORT" 2>/dev/null; then
    echo "connected"
  else
    echo "unreachable"
  fi
}

# ============================================================================
# Test Ollama API and get status
# ============================================================================
test_ollama_api() {
  local endpoint="${1:-$NEBULA_WORKER_IP:$OLLAMA_PORT}"
  local timeout_sec=5

  # Test basic API connectivity
  local response
  response=$(timeout "$timeout_sec" curl -s "http://$endpoint/api/tags" 2>/dev/null) || true

  if [[ -n "$response" ]] && echo "$response" | jq -e '.models' &>/dev/null; then
    echo "healthy"
  else
    echo "unhealthy"
  fi
}

# ============================================================================
# Get Ollama models
# ============================================================================
get_ollama_models() {
  local endpoint="${1:-$NEBULA_WORKER_IP:$OLLAMA_PORT}"
  local timeout_sec=5

  local response
  response=$(timeout "$timeout_sec" curl -s "http://$endpoint/api/tags" 2>/dev/null) || true

  if [[ -n "$response" ]]; then
    echo "$response" | jq -r '.models[]? | .name + "|" + .size' 2>/dev/null
  fi
}

# ============================================================================
# Get running Ollama processes
# ============================================================================
get_running_models() {
  local endpoint="${1:-$NEBULA_WORKER_IP:$OLLAMA_PORT}"
  local timeout_sec=5

  local response
  response=$(timeout "$timeout_sec" curl -s "http://$endpoint/api/ps" 2>/dev/null) || true

  if [[ -n "$response" ]]; then
    echo "$response" | jq -r '.models[]? | .name' 2>/dev/null
  fi
}

# ============================================================================
# Print service line
# ============================================================================
print_llm_service() {
  local name=$1
  local status=$2
  local url=$3
  local is_last=${4:-false}
  local extra=${5:-}

  local status_icon="${ICON_FAILURE}"
  local status_color=$RED

  case "$status" in
    connected|healthy|Running|configured)
      status_icon="${ICON_SUCCESS}"
      status_color=$GREEN
      ;;
    pending|unknown|no-endpoints)
      status_icon="${ICON_PENDING}"
      status_color=$YELLOW
      ;;
    unreachable|unhealthy)
      status_icon="${ICON_FAILURE}"
      status_color=$RED
      ;;
  esac

  local branch="${TREE_BRANCH}"
  [[ "$is_last" == "true" ]] && branch="${TREE_LAST}"

  local line="  ${BOLD}${branch} ${name}${RESET} ${status_color}[${status}]${RESET}"

  if [[ -n "$url" ]]; then
    line+=" ${DIM}${ICON_ARROW}${RESET} ${CYAN}${url}${RESET}"
  fi

  if [[ -n "$extra" ]]; then
    line+=" ${DIM}│${RESET} ${extra}"
  fi

  echo -e "$line"
}

# ============================================================================
# Print K8s services status
# ============================================================================
print_k8s_services() {
  print_section "KUBERNETES SERVICES"

  if [[ ! -f "$CACHE_DIR/services.json" ]]; then
    echo -e "  ${DIM}No services data available${RESET}"
    echo ""
    return
  fi

  # Get services
  local services
  services=$(jq -r '.items[] | .metadata.name + "|" + .spec.type + "|" + (.spec.ports[0].port | tostring)' "$CACHE_DIR/services.json" 2>/dev/null)

  if [[ -z "$services" ]]; then
    echo -e "  ${DIM}No services found${RESET}"
    echo ""
    return
  fi

  local count=0
  local total
  total=$(echo "$services" | wc -l | tr -d ' ')

  while IFS='|' read -r name type port; do
    count=$((count + 1))
    local is_last="false"
    [[ "$count" == "$total" ]] && is_last="true"

    # Check endpoint status
    local endpoint_status="unknown"
    local endpoint_ip
    endpoint_ip=$(jq -r ".items[] | select(.metadata.name == \"$name\") | .subsets[0].addresses[0].ip // empty" "$CACHE_DIR/endpoints.json" 2>/dev/null)

    if [[ -n "$endpoint_ip" ]]; then
      endpoint_status="configured"
    else
      endpoint_status="no-endpoints"
    fi

    local extra="${DIM}${type}:${port}${RESET}"
    [[ -n "$endpoint_ip" ]] && extra+=" ${DIM}→ ${endpoint_ip}${RESET}"

    print_llm_service "$name" "$endpoint_status" "" "$is_last" "$extra"
  done <<< "$services"

  echo ""
}

# ============================================================================
# Print Nebula mesh status
# ============================================================================
print_nebula_status() {
  print_section "NEBULA MESH (AWS WORKER)"

  echo -e "  ${DIM}Worker IP:${RESET} ${CYAN}${NEBULA_WORKER_IP}${RESET}"
  echo ""

  # Test connectivity
  echo -e "  ${DIM}Testing connectivity...${RESET}"
  local nebula_status
  nebula_status=$(test_nebula_connectivity)
  echo -e "\033[1A\033[2K"

  if [[ "$nebula_status" == "connected" ]]; then
    echo -e "  ${GREEN}${ICON_SUCCESS} Nebula tunnel: Connected${RESET}"

    # Test Ollama API
    local ollama_status
    ollama_status=$(test_ollama_api)

    if [[ "$ollama_status" == "healthy" ]]; then
      echo -e "  ${GREEN}${ICON_SUCCESS} Ollama API: Healthy${RESET}"
    else
      echo -e "  ${RED}${ICON_FAILURE} Ollama API: Unhealthy${RESET}"
    fi
  else
    echo -e "  ${RED}${ICON_FAILURE} Nebula tunnel: Unreachable${RESET}"
    echo -e "  ${DIM}  Check: Is the AWS worker running? Is Nebula daemon active?${RESET}"
  fi

  echo ""
}

# ============================================================================
# Print available models
# ============================================================================
print_models() {
  print_section "AVAILABLE MODELS"

  local models
  models=$(get_ollama_models)

  if [[ -z "$models" ]]; then
    echo -e "  ${DIM}No models found or Ollama unreachable${RESET}"
    echo ""
    return
  fi

  while IFS='|' read -r name size; do
    # Convert size to human readable
    local size_hr=""
    if [[ -n "$size" ]]; then
      size_hr=$(numfmt --to=iec-i --suffix=B "$size" 2>/dev/null || echo "${size}B")
    fi
    echo -e "  ${CYAN}•${RESET} ${name} ${DIM}(${size_hr})${RESET}"
  done <<< "$models"

  echo ""

  # Show running models
  local running
  running=$(get_running_models)
  if [[ -n "$running" ]]; then
    echo -e "  ${BOLD}Currently loaded:${RESET}"
    while read -r model; do
      echo -e "    ${GREEN}▶${RESET} ${model}"
    done <<< "$running"
    echo ""
  fi
}

# ============================================================================
# Print ingress routes
# ============================================================================
print_ingress() {
  print_section "INGRESS ROUTES"

  if [[ ! -f "$CACHE_DIR/ingressroutes.json" ]]; then
    echo -e "  ${DIM}No ingress data available${RESET}"
    echo ""
    return
  fi

  local routes
  routes=$(jq -r '.items[] | .metadata.name + "|" + .spec.routes[0].match' "$CACHE_DIR/ingressroutes.json" 2>/dev/null)

  if [[ -z "$routes" ]]; then
    echo -e "  ${DIM}No ingress routes found${RESET}"
    echo ""
    return
  fi

  while IFS='|' read -r name match; do
    local host
    host=$(echo "$match" | sed -n 's/.*Host(`\([^`]*\)`).*/\1/p')
    echo -e "  ${DIM}•${RESET} ${CYAN}http://${host}${RESET} ${DIM}(${name})${RESET}"
  done <<< "$routes"

  echo ""
}

# ============================================================================
# Print quick commands
# ============================================================================
print_llm_commands() {
  print_section "QUICK COMMANDS"
  echo -e "  ${CYAN}test${RESET}     │ curl -s http://llm.talos00/api/tags | jq"
  echo -e "  ${CYAN}chat${RESET}     │ curl http://llm.talos00/api/chat -d '{\"model\":\"llama3.2\",\"messages\":[{\"role\":\"user\",\"content\":\"hello\"}]}'"
  echo -e "  ${CYAN}models${RESET}   │ curl -s http://llm.talos00/api/tags | jq '.models[].name'"
  echo -e "  ${CYAN}pull${RESET}     │ curl http://llm.talos00/api/pull -d '{\"name\":\"llama3.2\"}'"
  echo -e "  ${CYAN}worker${RESET}   │ ssh -i ~/.ssh/catalyst-llm ubuntu@<aws-ip>"
  echo ""
}

# ============================================================================
# Print service URLs
# ============================================================================
print_service_urls() {
  print_section "SERVICE URLS"
  echo -e "  ${DIM}Requires /etc/hosts: 192.168.1.54 *.talos00${RESET}"
  echo ""
  echo -e "  ${BOLD}Frontend UIs:${RESET}"
  echo -e "    ${CYAN}http://chat.talos00${RESET}           ${DIM}│${RESET} Open-WebUI (ChatGPT-like interface)"
  echo -e "    ${CYAN}http://sillytavern.talos00${RESET}    ${DIM}│${RESET} SillyTavern (character chat)"
  echo -e "    ${CYAN}http://searxng.talos00${RESET}        ${DIM}│${RESET} SearXNG (privacy search)"
  echo -e "    ${CYAN}http://llm-scaler.talos00/_/ui${RESET} ${DIM}│${RESET} Scaler Dashboard (pause/resume)"
  echo ""
  echo -e "  ${BOLD}API Endpoints:${RESET}"
  echo -e "    ${CYAN}http://llm.talos00${RESET}            ${DIM}│${RESET} Ollama API (via scaler)"
  echo -e "    ${CYAN}http://ollama.talos00${RESET}         ${DIM}│${RESET} Ollama API (via scaler)"
  echo -e "    ${CYAN}http://ollama-direct.talos00${RESET}  ${DIM}│${RESET} Ollama API (bypasses scaler)"
  echo -e "    ${CYAN}http://${NEBULA_WORKER_IP}:${OLLAMA_PORT}${RESET}      ${DIM}│${RESET} Ollama (Nebula direct)"
  echo ""
}

# ============================================================================
# Quick API test mode
# ============================================================================
run_api_test() {
  echo -e "${CYAN}${BOLD}Testing Catalyst LLM API...${RESET}"
  echo ""

  echo -e "${DIM}1. Testing Nebula connectivity to ${NEBULA_WORKER_IP}:${OLLAMA_PORT}...${RESET}"
  if timeout 3 nc -z "$NEBULA_WORKER_IP" "$OLLAMA_PORT" 2>/dev/null; then
    echo -e "   ${GREEN}${ICON_SUCCESS} Connected${RESET}"
  else
    echo -e "   ${RED}${ICON_FAILURE} Unreachable${RESET}"
    exit 1
  fi

  echo ""
  echo -e "${DIM}2. Testing Ollama API...${RESET}"
  local response
  response=$(curl -s "http://${NEBULA_WORKER_IP}:${OLLAMA_PORT}/api/tags" 2>/dev/null) || true

  if [[ -n "$response" ]] && echo "$response" | jq -e '.models' &>/dev/null; then
    echo -e "   ${GREEN}${ICON_SUCCESS} API responding${RESET}"
    echo ""
    echo -e "${DIM}3. Available models:${RESET}"
    echo "$response" | jq -r '.models[] | "   • " + .name'
  else
    echo -e "   ${RED}${ICON_FAILURE} API not responding${RESET}"
    exit 1
  fi

  echo ""
  echo -e "${GREEN}${BOLD}All tests passed!${RESET}"
}

# ============================================================================
# Main dashboard
# ============================================================================
main() {
  # Handle flags
  if [[ "${1:-}" == "--test" ]]; then
    run_api_test
    exit 0
  fi

  # Initialize
  dashboard_init

  clear
  print_header

  # Fetch data
  fetch_cluster_data || true
  fetch_llm_data || true

  # Cluster status
  print_cluster_status
  echo ""

  # K8s services
  print_k8s_services

  # Nebula/AWS worker status
  print_nebula_status

  # Models
  print_models

  # Ingress routes
  print_ingress

  # Service URLs
  print_service_urls

  # Quick commands
  print_llm_commands
}

# Run main function
main "$@"
