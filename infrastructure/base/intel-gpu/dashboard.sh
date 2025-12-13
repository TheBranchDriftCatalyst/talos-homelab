#!/usr/bin/env bash
# Intel GPU Dashboard - NFD and GPU device plugin status
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
NFD_NAMESPACE="node-feature-discovery"
GPU_NAMESPACE="intel-device-plugins"
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
██╗███╗   ██╗████████╗███████╗██╗          ██████╗ ██████╗ ██╗   ██╗
██║████╗  ██║╚══██╔══╝██╔════╝██║         ██╔════╝ ██╔══██╗██║   ██║
██║██╔██╗ ██║   ██║   █████╗  ██║         ██║  ███╗██████╔╝██║   ██║
██║██║╚██╗██║   ██║   ██╔══╝  ██║         ██║   ██║██╔═══╝ ██║   ██║
██║██║ ╚████║   ██║   ███████╗███████╗    ╚██████╔╝██║     ╚██████╔╝
╚═╝╚═╝  ╚═══╝   ╚═╝   ╚══════╝╚══════╝     ╚═════╝ ╚═╝      ╚═════╝
                    ⚡ GPU Acceleration ⚡
EOF
  echo -e "${RESET}"
  echo ""
}

# ============================================================================
# Fetch GPU data
# ============================================================================
fetch_gpu_data() {
  echo -e "${DIM}Loading GPU data...${RESET}"

  kubectl get pods -n "$NFD_NAMESPACE" -o json > "$CACHE_DIR/nfd-pods.json" 2> /dev/null &
  kubectl get pods -n "$GPU_NAMESPACE" -o json > "$CACHE_DIR/gpu-pods.json" 2> /dev/null &
  kubectl get daemonset -n "$NFD_NAMESPACE" -o json > "$CACHE_DIR/nfd-daemonsets.json" 2> /dev/null &
  kubectl get daemonset -n "$GPU_NAMESPACE" -o json > "$CACHE_DIR/gpu-daemonsets.json" 2> /dev/null &
  kubectl get deployments -n "$NFD_NAMESPACE" -o json > "$CACHE_DIR/nfd-deployments.json" 2> /dev/null &
  kubectl get nodes -o json > "$CACHE_DIR/nodes.json" 2> /dev/null &
  kubectl get pods -A -o json > "$CACHE_DIR/all-pods.json" 2> /dev/null &

  wait
  echo -e "\033[1A\033[2K"
}

# ============================================================================
# Print summary mode
# ============================================================================
print_summary() {
  dashboard_init
  fetch_gpu_data

  local nfd_running nfd_total gpu_nodes
  nfd_running=$(jq '[.items[] | select(.status.phase == "Running")] | length' "$CACHE_DIR/nfd-pods.json" 2> /dev/null || echo "0")
  nfd_total=$(jq '.items | length' "$CACHE_DIR/nfd-pods.json" 2> /dev/null || echo "0")
  gpu_nodes=$(jq '[.items[] | select(.metadata.labels["intel.feature.node.kubernetes.io/gpu"] == "true")] | length' "$CACHE_DIR/nodes.json" 2> /dev/null || echo "0")

  local status_icon="${GREEN}✓${RESET}"
  [[ "$nfd_running" != "$nfd_total" ]] && status_icon="${YELLOW}⚠${RESET}"
  [[ "$nfd_running" == "0" ]] && status_icon="${RED}✗${RESET}"

  echo -e "    Intel GPU: ${status_icon} NFD: ${nfd_running}/${nfd_total} │ GPU nodes: ${gpu_nodes}"
}

# ============================================================================
# Print NFD status section
# ============================================================================
print_nfd_status() {
  print_section "NODE FEATURE DISCOVERY (${NFD_NAMESPACE})"

  if ! namespace_exists "$NFD_NAMESPACE"; then
    echo -e "  ${YELLOW}○${RESET} ${DIM}NFD namespace not found${RESET}"
    echo ""
    return
  fi

  # Master deployment
  local master_status
  master_status=$(jq -r '.items[] | select(.metadata.name | contains("master")) | .status.phase' "$CACHE_DIR/nfd-pods.json" 2> /dev/null | head -1)
  local master_icon="${GREEN}●${RESET}"
  [[ -z "$master_status" || "$master_status" != "Running" ]] && master_icon="${YELLOW}○${RESET}"
  echo -e "  ${TREE_BRANCH} ${master_icon} nfd-master ${DIM}(${master_status:-NotFound})${RESET}"

  # Worker DaemonSet
  local worker_desired worker_ready
  worker_desired=$(jq -r '.items[] | select(.metadata.name | contains("worker")) | .status.desiredNumberScheduled // 0' "$CACHE_DIR/nfd-daemonsets.json" 2> /dev/null | head -1)
  worker_ready=$(jq -r '.items[] | select(.metadata.name | contains("worker")) | .status.numberReady // 0' "$CACHE_DIR/nfd-daemonsets.json" 2> /dev/null | head -1)

  local worker_icon="${GREEN}●${RESET}"
  [[ "$worker_ready" != "$worker_desired" ]] && worker_icon="${YELLOW}○${RESET}"
  echo -e "  ${TREE_LAST} ${worker_icon} nfd-worker ${DIM}(${worker_ready}/${worker_desired} nodes)${RESET}"
  echo ""
}

# ============================================================================
# Print GPU node labels section
# ============================================================================
print_gpu_labels() {
  print_section "GPU NODE LABELS"

  local gpu_nodes
  gpu_nodes=$(jq -r '.items[] | select(.metadata.labels["intel.feature.node.kubernetes.io/gpu"] == "true") | .metadata.name' "$CACHE_DIR/nodes.json" 2> /dev/null)

  if [[ -z "$gpu_nodes" ]]; then
    echo -e "  ${DIM}No nodes with Intel GPU label detected${RESET}"
    echo -e "  ${DIM}Expected label: intel.feature.node.kubernetes.io/gpu=true${RESET}"
  else
    echo "$gpu_nodes" | while read -r node; do
      local gpu_count
      gpu_count=$(jq -r ".items[] | select(.metadata.name == \"$node\") | .status.allocatable[\"gpu.intel.com/i915\"] // \"0\"" "$CACHE_DIR/nodes.json" 2> /dev/null)
      echo -e "  ${TREE_BRANCH} ${GREEN}●${RESET} ${node} ${DIM}(allocatable: ${gpu_count} GPU)${RESET}"
    done
  fi
  echo ""
}

# ============================================================================
# Print GPU device plugin section
# ============================================================================
print_gpu_plugin() {
  print_section "GPU DEVICE PLUGIN (${GPU_NAMESPACE})"

  if ! namespace_exists "$GPU_NAMESPACE"; then
    echo -e "  ${YELLOW}○${RESET} ${DIM}GPU plugin namespace not found${RESET}"
    echo ""
    return
  fi

  local plugin_pods
  plugin_pods=$(jq -r '.items[] | .metadata.name + "|" + .spec.nodeName + "|" + .status.phase' "$CACHE_DIR/gpu-pods.json" 2> /dev/null)

  if [[ -z "$plugin_pods" ]]; then
    echo -e "  ${DIM}No GPU plugin pods found${RESET}"
    echo -e "  ${DIM}(Waiting for NFD to label GPU nodes)${RESET}"
  else
    echo "$plugin_pods" | while IFS='|' read -r pod_name node_name phase; do
      local status_icon="${GREEN}●${RESET}"
      [[ "$phase" != "Running" ]] && status_icon="${YELLOW}○${RESET}"
      echo -e "  ${TREE_BRANCH} ${status_icon} ${pod_name} ${DIM}on ${node_name}${RESET}"
    done
  fi
  echo ""
}

# ============================================================================
# Print allocatable resources section
# ============================================================================
print_allocatable() {
  print_section "ALLOCATABLE GPU RESOURCES"

  local has_gpu=false
  jq -r '.items[] | .metadata.name + "|" + (.status.allocatable["gpu.intel.com/i915"] // "none")' "$CACHE_DIR/nodes.json" 2> /dev/null | while IFS='|' read -r node_name gpu_count; do
    if [[ "$gpu_count" != "none" && "$gpu_count" != "0" ]]; then
      echo -e "  ${TREE_BRANCH} ${node_name}: ${GREEN}${gpu_count}${RESET} gpu.intel.com/i915"
      has_gpu=true
    fi
  done

  if [[ "$has_gpu" == "false" ]]; then
    echo -e "  ${DIM}No GPU resources detected in any node${RESET}"
  fi
  echo ""
}

# ============================================================================
# Print GPU workloads section
# ============================================================================
print_gpu_workloads() {
  print_section "GPU WORKLOADS"

  local gpu_pods
  gpu_pods=$(jq -r '.items[] | select(.spec.containers[].resources.requests["gpu.intel.com/i915"] != null or .spec.containers[].resources.limits["gpu.intel.com/i915"] != null) | .metadata.namespace + "/" + .metadata.name' "$CACHE_DIR/all-pods.json" 2> /dev/null)

  if [[ -z "$gpu_pods" ]]; then
    echo -e "  ${DIM}No pods requesting GPU resources${RESET}"
  else
    local count
    count=$(echo "$gpu_pods" | wc -l | tr -d ' ')
    echo -e "  ${DIM}${count} pod(s) using GPU:${RESET}"
    echo "$gpu_pods" | while read -r pod; do
      echo -e "  ${TREE_BRANCH} ${CYAN}${pod}${RESET}"
    done
  fi
  echo ""
}

# ============================================================================
# Print quick commands
# ============================================================================
print_commands() {
  print_section "QUICK COMMANDS"
  echo -e "  ${CYAN}nfd-pods${RESET}    │ kubectl get pods -n $NFD_NAMESPACE"
  echo -e "  ${CYAN}gpu-pods${RESET}    │ kubectl get pods -n $GPU_NAMESPACE"
  echo -e "  ${CYAN}labels${RESET}      │ kubectl get nodes -l intel.feature.node.kubernetes.io/gpu=true"
  echo -e "  ${CYAN}resources${RESET}   │ kubectl describe node <node> | grep -A5 'Allocatable'"
  echo -e "  ${CYAN}test-gpu${RESET}    │ kubectl run gpu-test --rm -it --image=intel/intel-gpu-tools -- intel_gpu_top"
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

  fetch_gpu_data

  print_nfd_status
  print_gpu_labels
  print_gpu_plugin
  print_allocatable
  print_gpu_workloads
  print_commands

  print_cluster_status
  echo ""
}

main "$@"
