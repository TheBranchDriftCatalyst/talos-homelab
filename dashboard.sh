#!/usr/bin/env bash
# Root Orchestrator Dashboard - Unified cluster status view
#
# Usage:
#   ./dashboard.sh              # Inline summary mode (default)
#   ./dashboard.sh --interactive  # Interactive menu mode
#   ./dashboard.sh --help        # Show usage
#
# shellcheck disable=SC2016,SC2034

set -euo pipefail

# Get script directory and source common library
DASHBOARD_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${DASHBOARD_SCRIPT_DIR}"

# shellcheck source=scripts/lib/dashboard-common.sh
source "${PROJECT_ROOT}/scripts/lib/dashboard-common.sh"

# ============================================================================
# Configuration
# ============================================================================
MODE="inline"

# Domain dashboards configuration
# Format: "name|namespace|path|description"
declare -a DOMAINS=(
  "infrastructure|flux-system|infrastructure/dashboard.sh|Platform Infrastructure"
  "arr-stack|media|applications/arr-stack/dashboard.sh|Media Automation Stack"
  "catalyst-llm|catalyst-llm|applications/catalyst-llm/dashboard.sh|LLM Hybrid Cloud"
  "nebula|nebula-system|infrastructure/base/nebula/dashboard.sh|Mesh VPN Overlay"
  "liqo|liqo|infrastructure/base/liqo/dashboard.sh|Multi-Cluster Federation"
  "intel-gpu|node-feature-discovery|infrastructure/base/intel-gpu/dashboard.sh|GPU Acceleration"
)

# ============================================================================
# Usage
# ============================================================================
print_usage() {
  echo "Usage: $0 [OPTIONS]"
  echo ""
  echo "Unified cluster dashboard with multiple viewing modes."
  echo ""
  echo "Options:"
  echo "  (no args)       Inline summary mode - compact status from all domains"
  echo "  --interactive   Interactive menu mode - select domains to explore"
  echo "  --help          Show this help message"
  echo ""
  echo "Available domains:"
  for domain in "${DOMAINS[@]}"; do
    IFS='|' read -r name namespace path desc <<< "$domain"
    printf "  %-14s %s\n" "$name" "$desc"
  done
  echo ""
}

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --interactive | -i)
      MODE="interactive"
      shift
      ;;
    --help | -h)
      print_usage
      exit 0
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
 ██████╗ █████╗ ████████╗ █████╗ ██╗  ██╗   ██╗███████╗████████╗
██╔════╝██╔══██╗╚══██╔══╝██╔══██╗██║  ╚██╗ ██╔╝██╔════╝╚══██╔══╝
██║     ███████║   ██║   ███████║██║   ╚████╔╝ ███████╗   ██║
██║     ██╔══██║   ██║   ██╔══██║██║    ╚██╔╝  ╚════██║   ██║
╚██████╗██║  ██║   ██║   ██║  ██║███████╗██║   ███████║   ██║
 ╚═════╝╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝   ╚══════╝   ╚═╝
              ⚡ Talos Homelab Cluster Dashboard ⚡
EOF
  echo -e "${RESET}"
  echo ""
}

# ============================================================================
# Get available domains (namespace exists and dashboard script exists)
# ============================================================================
get_available_domains() {
  local available=()
  for domain in "${DOMAINS[@]}"; do
    IFS='|' read -r name namespace path desc <<< "$domain"
    if namespace_exists "$namespace" && [[ -x "${PROJECT_ROOT}/${path}" ]]; then
      available+=("$domain")
    fi
  done
  echo "${available[@]}"
}

# ============================================================================
# Inline Summary Mode
# ============================================================================
run_inline_mode() {
  clear
  print_header

  print_section "CLUSTER OVERVIEW"

  # Quick cluster health
  local node_count ready_nodes
  node_count=$(kubectl get nodes --no-headers 2> /dev/null | wc -l | tr -d ' ')
  ready_nodes=$(kubectl get nodes --no-headers 2> /dev/null | grep -c " Ready" || echo "0")

  if [[ "$ready_nodes" == "$node_count" ]]; then
    echo -e "  ${GREEN}✓${RESET} Cluster: ${ready_nodes}/${node_count} nodes ready"
  else
    echo -e "  ${YELLOW}⚠${RESET} Cluster: ${ready_nodes}/${node_count} nodes ready"
  fi

  local total_pods running_pods
  total_pods=$(kubectl get pods -A --no-headers 2> /dev/null | wc -l | tr -d ' ')
  running_pods=$(kubectl get pods -A --no-headers 2> /dev/null | grep -c "Running" || echo "0")
  echo -e "  ${DIM}Pods: ${running_pods}/${total_pods} running${RESET}"
  echo ""

  print_section "DOMAIN STATUS"

  for domain in "${DOMAINS[@]}"; do
    IFS='|' read -r name namespace path desc <<< "$domain"

    if ! namespace_exists "$namespace"; then
      echo -e "  ${DIM}○ ${name}: namespace not found${RESET}"
      continue
    fi

    if [[ ! -x "${PROJECT_ROOT}/${path}" ]]; then
      echo -e "  ${YELLOW}○${RESET} ${name}: ${DIM}dashboard not found${RESET}"
      continue
    fi

    # Run the sub-dashboard in summary mode
    "${PROJECT_ROOT}/${path}" --summary 2> /dev/null || echo -e "  ${RED}✗${RESET} ${name}: ${DIM}error${RESET}"
  done

  echo ""

  # Flux status
  print_section "GITOPS STATUS"
  if command -v flux &> /dev/null; then
    local flux_ready flux_total
    flux_total=$(flux get kustomization --no-header 2> /dev/null | wc -l | tr -d ' ')
    flux_ready=$(flux get kustomization --no-header 2> /dev/null | grep -c "True" || echo "0")

    if [[ "$flux_ready" == "$flux_total" ]]; then
      echo -e "  ${GREEN}✓${RESET} Flux: ${flux_ready}/${flux_total} kustomizations ready"
    else
      echo -e "  ${YELLOW}⚠${RESET} Flux: ${flux_ready}/${flux_total} kustomizations ready"
    fi
  else
    echo -e "  ${DIM}flux CLI not installed${RESET}"
  fi

  # ArgoCD status
  if namespace_exists "argocd"; then
    local argocd_apps
    argocd_apps=$(kubectl get applications -n argocd --no-headers 2> /dev/null | wc -l | tr -d ' ')
    local synced_apps
    synced_apps=$(kubectl get applications -n argocd --no-headers 2> /dev/null | grep -c "Synced" || echo "0")
    echo -e "  ${DIM}ArgoCD: ${synced_apps}/${argocd_apps} apps synced${RESET}"
  fi
  echo ""

  # Quick commands
  print_section "QUICK ACTIONS"
  echo -e "  ${CYAN}./dashboard.sh --interactive${RESET}  │ Interactive domain explorer"
  echo -e "  ${CYAN}task health${RESET}                   │ Full cluster health check"
  echo -e "  ${CYAN}flux get all${RESET}                  │ GitOps status"
  echo -e "  ${CYAN}k9s${RESET}                           │ Terminal UI"
  echo ""

  echo -e "${DIM}Last updated: $(date '+%Y-%m-%d %H:%M:%S')${RESET}"
  echo ""
}

# ============================================================================
# Interactive Menu Mode
# ============================================================================
run_interactive_mode() {
  while true; do
    clear
    print_header

    print_section "SELECT DOMAIN"

    local available_domains=()
    local idx=1

    for domain in "${DOMAINS[@]}"; do
      IFS='|' read -r name namespace path desc <<< "$domain"

      if namespace_exists "$namespace" && [[ -x "${PROJECT_ROOT}/${path}" ]]; then
        available_domains+=("$domain")
        echo -e "  ${CYAN}${idx})${RESET} ${BOLD}${name}${RESET} - ${desc}"
        ((idx++))
      else
        echo -e "  ${DIM}-)${RESET} ${DIM}${name} - ${desc} (unavailable)${RESET}"
      fi
    done

    echo ""
    echo -e "  ${CYAN}0)${RESET} Exit"
    echo ""

    read -rp "  Select domain [0-$((idx - 1))]: " choice

    case "$choice" in
      0)
        echo ""
        echo -e "${DIM}Goodbye!${RESET}"
        exit 0
        ;;
      [1-9]*)
        if [[ "$choice" -ge 1 && "$choice" -lt "$idx" ]]; then
          local selected="${available_domains[$((choice - 1))]}"
          IFS='|' read -r name namespace path desc <<< "$selected"

          clear
          "${PROJECT_ROOT}/${path}" --full

          echo ""
          read -rp "  Press Enter to return to menu..." _
        else
          echo -e "  ${RED}Invalid selection${RESET}"
          sleep 1
        fi
        ;;
      *)
        echo -e "  ${RED}Invalid selection${RESET}"
        sleep 1
        ;;
    esac
  done
}

# ============================================================================
# Main
# ============================================================================
main() {
  dashboard_init

  case "$MODE" in
    inline)
      run_inline_mode
      ;;
    interactive)
      run_interactive_mode
      ;;
  esac
}

main "$@"
