#!/usr/bin/env bash
# Common dashboard library - shared functions for all dashboard scripts
# Source this file from dashboard scripts:
#   source "$(dirname "${BASH_SOURCE[0]}")/../scripts/lib/dashboard-common.sh"
#
# shellcheck disable=SC2016,SC2034

# ============================================================================
# Color codes
# ============================================================================
RESET='\033[0m'
BOLD='\033[1m'
DIM='\033[2m'
CYAN='\033[96m'
GREEN='\033[92m'
YELLOW='\033[93m'
RED='\033[91m'
MAGENTA='\033[95m'
BLUE='\033[94m'

# ============================================================================
# Configuration
# ============================================================================
DOMAIN="${DOMAIN:-talos00}"

# Find project root
_find_project_root() {
  local dir="$1"
  while [[ "$dir" != "/" ]]; do
    if [[ -f "$dir/Taskfile.yaml" ]] && [[ -d "$dir/infrastructure" ]]; then
      echo "$dir"
      return
    fi
    dir="$(dirname "$dir")"
  done
  echo ""
}

DASHBOARD_SCRIPT_DIR="${DASHBOARD_SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
PROJECT_ROOT="${PROJECT_ROOT:-$(_find_project_root "$DASHBOARD_SCRIPT_DIR")}"

# Kubeconfig search order: KUBECONFIG env, project .output, ~/.kube/config
_find_kubeconfig() {
  if [[ -n "${KUBECONFIG:-}" ]] && [[ -f "$KUBECONFIG" ]]; then
    echo "$KUBECONFIG"
  elif [[ -n "$PROJECT_ROOT" ]] && [[ -f "${PROJECT_ROOT}/.output/kubeconfig" ]]; then
    echo "${PROJECT_ROOT}/.output/kubeconfig"
  elif [[ -f "${HOME}/.kube/config" ]]; then
    echo "${HOME}/.kube/config"
  else
    echo ""
  fi
}

# ============================================================================
# Initialization
# ============================================================================
dashboard_init() {
  # Check if kubectl is available
  if ! command -v kubectl &> /dev/null; then
    echo "kubectl not found. Please install kubectl."
    exit 1
  fi

  # Check if jq is available
  if ! command -v jq &> /dev/null; then
    echo "jq not found. Please install jq."
    exit 1
  fi

  # Find and set kubeconfig
  local kubeconfig_path
  kubeconfig_path=$(_find_kubeconfig)

  if [[ -z "$kubeconfig_path" ]]; then
    echo "Kubeconfig not found. Searched:"
    echo "  - \$KUBECONFIG env var"
    [[ -n "$PROJECT_ROOT" ]] && echo "  - ${PROJECT_ROOT}/.output/kubeconfig"
    echo "  - ${HOME}/.kube/config"
    echo "Run: task kubeconfig"
    exit 1
  fi

  export KUBECONFIG="$kubeconfig_path"

  # Create temp cache directory
  CACHE_DIR=$(mktemp -d)
  trap 'rm -rf "$CACHE_DIR"' EXIT
}

# ============================================================================
# Bulk data fetching - do all kubectl calls upfront
# ============================================================================
fetch_cluster_data() {
  echo -e "${DIM}Loading cluster data...${RESET}"

  # Fetch cluster-wide data in parallel
  kubectl get nodes -o json > "$CACHE_DIR/nodes.json" 2> /dev/null &
  kubectl get sc -o json > "$CACHE_DIR/storageclasses.json" 2> /dev/null &
  kubectl get pv -o json > "$CACHE_DIR/pvs.json" 2> /dev/null &

  wait

  # Clear the loading message
  echo -e "\033[1A\033[2K"
}

fetch_namespace_data() {
  local namespace=$1
  local prefix="${2:-}" # optional prefix for cache files

  echo -e "${DIM}Loading ${namespace} data...${RESET}"

  # Fetch namespace data in parallel
  kubectl get deployments -n "$namespace" -o json > "$CACHE_DIR/${prefix}deployments.json" 2> /dev/null &
  kubectl get pods -n "$namespace" -o json > "$CACHE_DIR/${prefix}pods.json" 2> /dev/null &
  kubectl get pvc -n "$namespace" -o json > "$CACHE_DIR/${prefix}pvcs.json" 2> /dev/null &
  kubectl get svc -n "$namespace" -o json > "$CACHE_DIR/${prefix}services.json" 2> /dev/null &
  kubectl get secrets -n "$namespace" -o json > "$CACHE_DIR/${prefix}secrets.json" 2> /dev/null &

  # IngressRoutes (Traefik CRD - may not exist)
  kubectl get ingressroute -n "$namespace" -o json > "$CACHE_DIR/${prefix}ingressroutes.json" 2> /dev/null &

  wait

  # Clear the loading message
  echo -e "\033[1A\033[2K"
}

# ============================================================================
# Helper functions using cached data
# ============================================================================

# Check if namespace exists
namespace_exists() {
  kubectl get namespace "$1" &> /dev/null
}

# Check cluster health from cache
cluster_healthy() {
  [[ -f "$CACHE_DIR/nodes.json" ]] && jq -e '.items | length > 0' "$CACHE_DIR/nodes.json" &> /dev/null
}

# Get deployment exists from cache
get_deployment_exists() {
  local app=$1
  local prefix="${2:-}"
  jq -e ".items[] | select(.metadata.name == \"$app\")" "$CACHE_DIR/${prefix}deployments.json" &> /dev/null
}

# Get pod status from cache
get_pod_status() {
  local label_key=$1
  local label_value=$2
  local prefix="${3:-}"

  jq -r ".items[] | select(.metadata.labels[\"$label_key\"] == \"$label_value\") | .status.phase" "$CACHE_DIR/${prefix}pods.json" 2> /dev/null | head -1
}

# Get pod status by app label (convenience function)
get_pod_status_by_app() {
  local app=$1
  local prefix="${2:-}"
  get_pod_status "app" "$app" "$prefix"
}

# Get pod status by k8s app name label
get_pod_status_by_name() {
  local app=$1
  local prefix="${2:-}"
  get_pod_status "app.kubernetes.io/name" "$app" "$prefix"
}

# Get pod ready status from cache
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

# Get service info from cache
get_service_info() {
  local service=$1
  local prefix="${2:-}"
  local result
  result=$(jq -r ".items[] | select(.metadata.name == \"$service\") | .spec.clusterIP + \":\" + (.spec.ports[0].port | tostring)" "$CACHE_DIR/${prefix}services.json" 2> /dev/null)
  echo "${result:-not-found}"
}

# Get ingress URL from cache (Traefik IngressRoute)
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

# Get volume mounts for a deployment from cache
get_volume_mounts() {
  local app=$1
  local prefix="${2:-}"
  jq -r ".items[] | select(.metadata.name == \"$app\") | .spec.template.spec.volumes[]? | select(.persistentVolumeClaim != null) | .name + \":\" + .persistentVolumeClaim.claimName" "$CACHE_DIR/${prefix}deployments.json" 2> /dev/null
}

# Get PVC info from cache
get_pvc_info() {
  local pvc_name=$1
  local prefix="${2:-}"
  jq -r ".items[] | select(.metadata.name == \"$pvc_name\") | .status.phase + \"|\" + .spec.resources.requests.storage + \"|\" + (.spec.storageClassName // \"default\")" "$CACHE_DIR/${prefix}pvcs.json" 2> /dev/null
}

# Get secret data from cache
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

# ============================================================================
# Display helper functions
# ============================================================================

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

# Print status indicator
print_status_indicator() {
  local status=$1
  local ready=$2

  if [[ "$status" == "Running" ]] && [[ "$ready" == "true" ]]; then
    echo -e "${GREEN}[✓]${RESET}"
  elif [[ -z "$status" ]] || [[ "$status" == "null" ]] || [[ "$status" == "NotFound" ]]; then
    echo -e "${RED}[✗]${RESET}"
  else
    echo -e "${YELLOW}[⚠]${RESET}"
  fi
}

# Print volume mount with status indicator
print_volume_mount() {
  local pvc_name=$1
  local indent=$2
  local prefix="${3:-}"

  local pvc_info
  pvc_info=$(get_pvc_info "$pvc_name" "$prefix")

  if [[ -z "$pvc_info" ]]; then
    echo -e "${indent}${RED}✗${RESET} ${DIM}${pvc_name}${RESET} ${RED}[NotFound]${RESET}"
    return
  fi

  local status capacity sc
  IFS='|' read -r status capacity sc <<< "$pvc_info"

  # Status indicator
  local status_icon="⚠"
  local status_color=$YELLOW
  if [[ "$status" == "Bound" ]]; then
    status_icon="●"
    status_color=$GREEN
  elif [[ "$status" == "Pending" ]]; then
    status_icon="○"
    status_color=$YELLOW
  fi

  local sc_short
  sc_short=$(shorten_storageclass "$sc")

  echo -e "${indent}${status_color}${status_icon}${RESET} ${DIM}${pvc_name}${RESET} ${BLUE}(${capacity})${RESET} ${DIM}[${sc_short}]${RESET}"
}

# Print service with status (generic version)
# Usage: print_service_line "name" "status" "ready" "url" "is_last" ["extra_info"]
print_service_line() {
  local name=$1
  local status=$2
  local ready=$3
  local url=$4
  local is_last=${5:-false}
  local extra=${6:-}

  # Status indicator
  local status_indicator
  status_indicator=$(print_status_indicator "$status" "$ready")

  # Tree characters
  local branch="┣━"
  if [[ "$is_last" == "true" ]]; then
    branch="┗━"
  fi

  local line="  ${BOLD}${branch} ${name}${RESET} ${status_indicator}"

  if [[ -n "$url" ]]; then
    line+=" ${DIM}→${RESET} ${CYAN}${url}${RESET}"
  fi

  if [[ -n "$extra" ]]; then
    line+=" ${DIM}│${RESET} ${extra}"
  fi

  echo -e "$line"
}

# Print section header
print_section() {
  local title=$1
  echo -e "${MAGENTA}▸ ${title}${RESET}"
}

# Print a sub-item (indented line under a service)
print_sub_item() {
  local text=$1
  local is_last=${2:-false}
  local cont="┃"
  if [[ "$is_last" == "true" ]]; then
    cont=" "
  fi
  echo -e "  ${cont}  ${DIM}${text}${RESET}"
}

# Print storage summary
print_storage_summary() {
  local prefix="${1:-}"

  print_section "STORAGE SUMMARY"

  if [[ -f "$CACHE_DIR/${prefix}pvcs.json" ]]; then
    local bound_count pending_count total_count
    bound_count=$(jq '[.items[] | select(.status.phase == "Bound")] | length' "$CACHE_DIR/${prefix}pvcs.json" 2> /dev/null || echo "0")
    pending_count=$(jq '[.items[] | select(.status.phase == "Pending")] | length' "$CACHE_DIR/${prefix}pvcs.json" 2> /dev/null || echo "0")
    total_count=$(jq '.items | length' "$CACHE_DIR/${prefix}pvcs.json" 2> /dev/null || echo "0")

    echo -e "  ${DIM}PVCs:${RESET} ${GREEN}${bound_count} Bound${RESET} ${YELLOW}${pending_count} Pending${RESET} ${DIM}(${total_count} total)${RESET}"

    # Show storage classes in use
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

# Print cluster status
print_cluster_status() {
  if cluster_healthy; then
    echo -e "${GREEN}✓ Cluster is running${RESET}"
  else
    echo -e "${RED}✗ Cluster is not accessible${RESET}"
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
