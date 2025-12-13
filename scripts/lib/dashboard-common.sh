#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  Dashboard Common Library                                                    ║
# ║  Extended utilities for dashboard scripts (extends common.sh)                ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
#
# Source this file from dashboard scripts:
#   source "$(dirname "${BASH_SOURCE[0]}")/../scripts/lib/dashboard-common.sh"
#
# This library extends common.sh with dashboard-specific functionality:
#   - Cached kubectl data fetching (parallel)
#   - Pod/deployment status helpers
#   - Volume and PVC information
#   - Service URL resolution
#   - Credential extraction
#
# shellcheck disable=SC2016,SC2034

# Get the directory of this script
_DASHBOARD_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source the base common library
source "${_DASHBOARD_LIB_DIR}/common.sh"

# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD INITIALIZATION
# ══════════════════════════════════════════════════════════════════════════════

# Initialize dashboard environment
# Creates cache directory and validates prerequisites
dashboard_init() {
  # Check prerequisites
  require_cmd "kubectl" "kubectl is required for dashboards"
  require_cmd "jq" "jq is required for JSON parsing"

  # Find and set kubeconfig
  local kubeconfig_path
  kubeconfig_path=$(_find_kubeconfig)

  if [[ -z "$kubeconfig_path" ]]; then
    error "Kubeconfig not found. Searched:"
    log_note "\$KUBECONFIG env var"
    [[ -n "$PROJECT_ROOT" ]] && log_note "${PROJECT_ROOT}/.output/kubeconfig"
    log_note "${HOME}/.kube/config"
    log_note "Run: task kubeconfig-merge"
    exit 1
  fi

  export KUBECONFIG="$kubeconfig_path"

  # Create temp cache directory
  CACHE_DIR=$(mktemp -d)
  register_cleanup "rm -rf $CACHE_DIR"
  setup_cleanup_trap
}

# ══════════════════════════════════════════════════════════════════════════════
# BULK DATA FETCHING (Parallel for Performance)
# ══════════════════════════════════════════════════════════════════════════════

# Fetch cluster-wide data (nodes, storage classes, PVs)
fetch_cluster_data() {
  echo -e "${DIM}Loading cluster data...${RESET}"

  # Fetch in parallel
  kubectl get nodes -o json > "$CACHE_DIR/nodes.json" 2> /dev/null &
  kubectl get sc -o json > "$CACHE_DIR/storageclasses.json" 2> /dev/null &
  kubectl get pv -o json > "$CACHE_DIR/pvs.json" 2> /dev/null &

  wait

  # Clear loading message
  echo -e "\033[1A\033[2K"
}

# Fetch namespace-specific data
# Usage: fetch_namespace_data "media" ["prefix"]
fetch_namespace_data() {
  local namespace=$1
  local prefix="${2:-}"

  echo -e "${DIM}Loading ${namespace} data...${RESET}"

  # Fetch in parallel
  kubectl get deployments -n "$namespace" -o json > "$CACHE_DIR/${prefix}deployments.json" 2> /dev/null &
  kubectl get pods -n "$namespace" -o json > "$CACHE_DIR/${prefix}pods.json" 2> /dev/null &
  kubectl get pvc -n "$namespace" -o json > "$CACHE_DIR/${prefix}pvcs.json" 2> /dev/null &
  kubectl get svc -n "$namespace" -o json > "$CACHE_DIR/${prefix}services.json" 2> /dev/null &
  kubectl get secrets -n "$namespace" -o json > "$CACHE_DIR/${prefix}secrets.json" 2> /dev/null &
  kubectl get ingressroute -n "$namespace" -o json > "$CACHE_DIR/${prefix}ingressroutes.json" 2> /dev/null &

  wait

  # Clear loading message
  echo -e "\033[1A\033[2K"
}

# ══════════════════════════════════════════════════════════════════════════════
# NAMESPACE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

# Check if namespace exists
namespace_exists() {
  kubectl get namespace "$1" &> /dev/null
}

# Check cluster health from cache
cluster_healthy() {
  [[ -f "$CACHE_DIR/nodes.json" ]] && jq -e '.items | length > 0' "$CACHE_DIR/nodes.json" &> /dev/null
}

# ══════════════════════════════════════════════════════════════════════════════
# DEPLOYMENT HELPERS
# ══════════════════════════════════════════════════════════════════════════════

# Check if deployment exists
get_deployment_exists() {
  local app=$1
  local prefix="${2:-}"
  jq -e ".items[] | select(.metadata.name == \"$app\")" "$CACHE_DIR/${prefix}deployments.json" &> /dev/null
}

# Get volume mounts for a deployment
get_volume_mounts() {
  local app=$1
  local prefix="${2:-}"
  jq -r ".items[] | select(.metadata.name == \"$app\") | .spec.template.spec.volumes[]? | select(.persistentVolumeClaim != null) | .name + \":\" + .persistentVolumeClaim.claimName" "$CACHE_DIR/${prefix}deployments.json" 2> /dev/null
}

# ══════════════════════════════════════════════════════════════════════════════
# POD STATUS HELPERS
# ══════════════════════════════════════════════════════════════════════════════

# Get pod status by label
# Usage: get_pod_status "app" "nginx" ["prefix"]
get_pod_status() {
  local label_key=$1
  local label_value=$2
  local prefix="${3:-}"

  jq -r ".items[] | select(.metadata.labels[\"$label_key\"] == \"$label_value\") | .status.phase" "$CACHE_DIR/${prefix}pods.json" 2> /dev/null | head -1
}

# Convenience wrappers
get_pod_status_by_app() {
  local app=$1
  local prefix="${2:-}"
  get_pod_status "app" "$app" "$prefix"
}

get_pod_status_by_name() {
  local app=$1
  local prefix="${2:-}"
  get_pod_status "app.kubernetes.io/name" "$app" "$prefix"
}

# Get pod ready status
get_pod_ready() {
  local label_key=$1
  local label_value=$2
  local prefix="${3:-}"

  jq -r ".items[] | select(.metadata.labels[\"$label_key\"] == \"$label_value\") | .status.containerStatuses[0].ready // false" "$CACHE_DIR/${prefix}pods.json" 2> /dev/null | head -1
}

get_pod_ready_by_app() {
  local app=$1
  local prefix="${2:-}"
  get_pod_ready "app" "$app" "$prefix"
}

get_pod_ready_by_name() {
  local app=$1
  local prefix="${2:-}"
  get_pod_ready "app.kubernetes.io/name" "$app" "$prefix"
}

# ══════════════════════════════════════════════════════════════════════════════
# SERVICE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

# Get service info (ClusterIP:Port)
get_service_info() {
  local service=$1
  local prefix="${2:-}"
  local result
  result=$(jq -r ".items[] | select(.metadata.name == \"$service\") | .spec.clusterIP + \":\" + (.spec.ports[0].port | tostring)" "$CACHE_DIR/${prefix}services.json" 2> /dev/null)
  echo "${result:-not-found}"
}

# Get ingress URL (from Traefik IngressRoute)
get_ingress_url() {
  local service=$1
  local prefix="${2:-}"
  local host

  if [[ -f "$CACHE_DIR/${prefix}ingressroutes.json" ]]; then
    host=$(jq -r ".items[] | select(.metadata.name | contains(\"$service\")) | .spec.routes[0].match" "$CACHE_DIR/${prefix}ingressroutes.json" 2> /dev/null |
      sed -n 's/.*Host(`\([^`]*\)`).*/\1/p' | head -1)
  fi

  if [[ -n "$host" ]]; then
    echo "http://$host"
  else
    echo "http://$service.$DOMAIN"
  fi
}

# ══════════════════════════════════════════════════════════════════════════════
# PVC HELPERS
# ══════════════════════════════════════════════════════════════════════════════

# Get PVC info (phase|capacity|storageClass)
get_pvc_info() {
  local pvc_name=$1
  local prefix="${2:-}"
  jq -r ".items[] | select(.metadata.name == \"$pvc_name\") | .status.phase + \"|\" + .spec.resources.requests.storage + \"|\" + (.spec.storageClassName // \"default\")" "$CACHE_DIR/${prefix}pvcs.json" 2> /dev/null
}

# Shorten storage class name for display
shorten_storageclass() {
  local sc=$1
  case "$sc" in
    fatboy-nfs-appdata) echo "nfs:appdata" ;;
    truenas-nfs) echo "truenas" ;;
    synology-nfs) echo "synology" ;;
    local-path) echo "local" ;;
    *) echo "$sc" ;;
  esac
}

# ══════════════════════════════════════════════════════════════════════════════
# SECRET HELPERS
# ══════════════════════════════════════════════════════════════════════════════

# Get secret data from cache (base64 decoded)
get_secret_data() {
  local secret_name=$1
  local key=$2
  local prefix="${3:-}"
  local value
  value=$(jq -r ".items[] | select(.metadata.name == \"$secret_name\") | .data[\"$key\"] // empty" "$CACHE_DIR/${prefix}secrets.json" 2> /dev/null)
  if [[ -n "$value" ]]; then
    echo "$value" | base64 -d 2> /dev/null
  fi
}

# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD DISPLAY HELPERS
# ══════════════════════════════════════════════════════════════════════════════

# Print status indicator (uses base print_status)
print_status_indicator() {
  local status=$1
  local ready=$2
  print_status "$status" "$ready"
}

# Print volume mount with status
print_volume_mount() {
  local pvc_name=$1
  local indent=$2
  local prefix="${3:-}"

  local pvc_info
  pvc_info=$(get_pvc_info "$pvc_name" "$prefix")

  if [[ -z "$pvc_info" ]]; then
    echo -e "${indent}${RED}${ICON_FAILURE}${RESET} ${DIM}${pvc_name}${RESET} ${RED}[NotFound]${RESET}"
    return
  fi

  local status capacity sc
  IFS='|' read -r status capacity sc <<< "$pvc_info"

  # Status indicator
  local status_icon="${ICON_WARNING}"
  local status_color=$YELLOW
  if [[ "$status" == "Bound" ]]; then
    status_icon="${ICON_RUNNING}"
    status_color=$GREEN
  elif [[ "$status" == "Pending" ]]; then
    status_icon="${ICON_PENDING}"
    status_color=$YELLOW
  fi

  local sc_short
  sc_short=$(shorten_storageclass "$sc")

  echo -e "${indent}${status_color}${status_icon}${RESET} ${DIM}${pvc_name}${RESET} ${BLUE}(${capacity})${RESET} ${DIM}[${sc_short}]${RESET}"
}

# Print service line with status (tree-style)
# Usage: print_service_line "name" "status" "ready" "url" "is_last" ["extra"]
print_service_line() {
  local name=$1
  local status=$2
  local ready=$3
  local url=$4
  local is_last=${5:-false}
  local extra=${6:-}

  local status_indicator
  status_indicator=$(print_status_indicator "$status" "$ready")

  # Tree characters
  local branch="${TREE_BRANCH}"
  [[ "$is_last" == "true" ]] && branch="${TREE_LAST}"

  local line="  ${BOLD}${branch} ${name}${RESET} ${status_indicator}"

  if [[ -n "$url" ]]; then
    line+=" ${DIM}${ICON_ARROW}${RESET} ${CYAN}${url}${RESET}"
  fi

  if [[ -n "$extra" ]]; then
    line+=" ${DIM}│${RESET} ${extra}"
  fi

  echo -e "$line"
}

# Print a sub-item under a tree line
print_sub_item() {
  local text=$1
  local is_last=${2:-false}
  local cont="${TREE_CONT}"
  [[ "$is_last" == "true" ]] && cont=" "
  echo -e "  ${cont}  ${DIM}${text}${RESET}"
}

# Print storage summary from cache
print_storage_summary() {
  local prefix="${1:-}"

  print_section "STORAGE SUMMARY"

  if [[ -f "$CACHE_DIR/${prefix}pvcs.json" ]]; then
    local bound_count pending_count total_count
    bound_count=$(jq '[.items[] | select(.status.phase == "Bound")] | length' "$CACHE_DIR/${prefix}pvcs.json" 2> /dev/null || echo "0")
    pending_count=$(jq '[.items[] | select(.status.phase == "Pending")] | length' "$CACHE_DIR/${prefix}pvcs.json" 2> /dev/null || echo "0")
    total_count=$(jq '.items | length' "$CACHE_DIR/${prefix}pvcs.json" 2> /dev/null || echo "0")

    echo -e "  ${DIM}PVCs:${RESET} ${GREEN}${bound_count} Bound${RESET} ${YELLOW}${pending_count} Pending${RESET} ${DIM}(${total_count} total)${RESET}"

    # Storage classes in use
    local storage_classes
    storage_classes=$(jq -r '[.items[].spec.storageClassName] | unique | join(" ")' "$CACHE_DIR/${prefix}pvcs.json" 2> /dev/null)
    if [[ -n "$storage_classes" ]] && [[ "$storage_classes" != "null" ]]; then
      echo -e "  ${DIM}Storage Classes:${RESET} ${storage_classes}"
    fi
  else
    echo -e "  ${DIM}No PVC data available${RESET}"
  fi
  echo ""
}

# Print cluster status line
print_cluster_status() {
  if cluster_healthy; then
    echo -e "${GREEN}${ICON_SUCCESS} Cluster is running${RESET}"
  else
    echo -e "${RED}${ICON_FAILURE} Cluster is not accessible${RESET}"
  fi
}

# Print quick commands section
print_quick_commands() {
  local namespace="${1:-default}"

  print_section "QUICK COMMANDS"
  echo -e "  ${CYAN}pods${RESET}    │ kubectl get pods -n $namespace"
  echo -e "  ${CYAN}pvcs${RESET}    │ kubectl get pvc -n $namespace"
  echo -e "  ${CYAN}logs${RESET}    │ kubectl logs -n $namespace deploy/<name> -f"
  echo -e "  ${CYAN}shell${RESET}   │ kubectl exec -n $namespace -it deploy/<name> -- /bin/bash"
  echo -e "  ${CYAN}restart${RESET} │ kubectl rollout restart deploy/<name> -n $namespace"
  echo ""
}
