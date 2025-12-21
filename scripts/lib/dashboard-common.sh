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

# Get the node a pod is running on
# Usage: get_pod_node "app-name" ["prefix"]
get_pod_node() {
  local app=$1
  local prefix="${2:-}"
  jq -r ".items[] | select(.metadata.labels.app == \"$app\" or .metadata.labels[\"app.kubernetes.io/name\"] == \"$app\") | .spec.nodeName // empty" "$CACHE_DIR/${prefix}pods.json" 2>/dev/null | head -1
}

# Get all unique nodes with running pods
get_all_nodes() {
  local prefix="${1:-}"
  jq -r '.items[] | select(.status.phase == "Running") | .spec.nodeName' "$CACHE_DIR/${prefix}pods.json" 2>/dev/null | sort -u
}

# Get all deployments running on a specific node
# Returns: deployment names, one per line
get_deployments_on_node() {
  local node=$1
  local prefix="${2:-}"
  jq -r ".items[] | select(.spec.nodeName == \"$node\" and .status.phase == \"Running\") | .metadata.labels.app // .metadata.labels[\"app.kubernetes.io/name\"] // empty" "$CACHE_DIR/${prefix}pods.json" 2>/dev/null | sort -u | grep -v '^$'
}

# Check if a volume is shared (NFS/NAS) vs local
is_shared_volume() {
  local storage_class=$1
  case "$storage_class" in
    fatboy-nfs-appdata|truenas-nfs|synology-nfs) return 0 ;;
    *) return 1 ;;
  esac
}

# Get local volumes for a deployment (local-path only)
get_local_volumes() {
  local app=$1
  local prefix="${2:-}"
  jq -r ".items[] | select(.metadata.name == \"$app\") | .spec.template.spec.volumes[]? | select(.persistentVolumeClaim != null) | .persistentVolumeClaim.claimName" "$CACHE_DIR/${prefix}deployments.json" 2>/dev/null | while read -r pvc; do
    local sc
    sc=$(jq -r ".items[] | select(.metadata.name == \"$pvc\") | .spec.storageClassName // \"default\"" "$CACHE_DIR/${prefix}pvcs.json" 2>/dev/null)
    if [[ "$sc" == "local-path" ]]; then
      echo "$pvc"
    fi
  done
}

# Get shared volumes for a deployment (NFS/NAS)
get_shared_volumes() {
  local app=$1
  local prefix="${2:-}"
  jq -r ".items[] | select(.metadata.name == \"$app\") | .spec.template.spec.volumes[]? | select(.persistentVolumeClaim != null) | .persistentVolumeClaim.claimName" "$CACHE_DIR/${prefix}deployments.json" 2>/dev/null | while read -r pvc; do
    local sc
    sc=$(jq -r ".items[] | select(.metadata.name == \"$pvc\") | .spec.storageClassName // \"default\"" "$CACHE_DIR/${prefix}pvcs.json" 2>/dev/null)
    if is_shared_volume "$sc"; then
      echo "$pvc|$sc"
    fi
  done
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

# Get node disk usage for local-path storage
# Returns: used|available|total|percent for the node's /var partition
get_node_disk_usage() {
  local node=$1
  local namespace="${2:-default}"

  # Find a pod running on this node to exec df
  local pod_name
  pod_name=$(kubectl get pods -n "$namespace" -o json 2>/dev/null | \
    jq -r ".items[] | select(.spec.nodeName == \"$node\" and .status.phase == \"Running\") | .metadata.name" | head -1)

  if [[ -z "$pod_name" ]]; then
    return 1
  fi

  # Run df and parse output for /var or root filesystem
  local df_output
  df_output=$(kubectl exec -n "$namespace" "$pod_name" -- df -h / 2>/dev/null | tail -1)

  if [[ -n "$df_output" ]]; then
    # Parse: Filesystem Size Used Avail Use% Mounted
    local size used avail percent
    read -r _ size used avail percent _ <<< "$df_output"
    echo "${used}|${avail}|${size}|${percent}"
  fi
}

# Cache node disk usage to avoid repeated execs
declare -A NODE_DISK_CACHE

fetch_node_disk_usage() {
  local namespace="${1:-media}"

  # Get unique nodes with local-path PVCs
  local nodes
  nodes=$(jq -r '.items[] | select(.spec.storageClassName == "local-path") | .metadata.annotations["volume.kubernetes.io/selected-node"] // empty' "$CACHE_DIR/pvcs.json" 2>/dev/null | sort -u)

  for node in $nodes; do
    if [[ -n "$node" ]]; then
      local usage
      usage=$(get_node_disk_usage "$node" "$namespace")
      if [[ -n "$usage" ]]; then
        NODE_DISK_CACHE["$node"]="$usage"
      fi
    fi
  done
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

# Print a visual progress bar for disk usage
# Usage: print_usage_bar percent width
print_usage_bar() {
  local percent=$1
  local width=${2:-20}

  # Remove % suffix if present
  percent="${percent%\%}"

  # Calculate filled/empty segments
  local filled=$((percent * width / 100))
  local empty=$((width - filled))

  # Color based on usage
  local color=$GREEN
  if [[ $percent -ge 90 ]]; then
    color=$RED
  elif [[ $percent -ge 70 ]]; then
    color=$YELLOW
  fi

  # Build the bar
  local bar=""
  for ((i=0; i<filled; i++)); do bar+="█"; done
  for ((i=0; i<empty; i++)); do bar+="░"; done

  echo -e "${color}${bar}${RESET} ${percent}%"
}

# Print node local storage usage summary
print_node_storage_summary() {
  local namespace="${1:-media}"
  local prefix="${2:-}"

  print_section "NODE LOCAL STORAGE"

  # Get unique nodes with local-path PVCs
  local nodes
  nodes=$(jq -r '.items[] | select(.spec.storageClassName == "local-path") | .metadata.annotations["volume.kubernetes.io/selected-node"] // empty' "$CACHE_DIR/${prefix}pvcs.json" 2>/dev/null | sort -u)

  if [[ -z "$nodes" ]]; then
    echo -e "  ${DIM}No local-path PVCs found${RESET}"
    echo ""
    return
  fi

  for node in $nodes; do
    if [[ -z "$node" ]]; then continue; fi

    # Get disk usage for this node
    local usage
    usage=$(get_node_disk_usage "$node" "$namespace")

    if [[ -n "$usage" ]]; then
      local used avail total percent
      IFS='|' read -r used avail total percent <<< "$usage"

      # Count PVCs on this node
      local pvc_count
      pvc_count=$(jq -r "[.items[] | select(.spec.storageClassName == \"local-path\" and .metadata.annotations[\"volume.kubernetes.io/selected-node\"] == \"$node\")] | length" "$CACHE_DIR/${prefix}pvcs.json" 2>/dev/null || echo "0")

      echo -e "  ${BOLD}${node}${RESET} ${DIM}(${pvc_count} PVCs)${RESET}"
      echo -e "    $(print_usage_bar "${percent%\%}" 25)  ${CYAN}${used}${RESET}/${total} used, ${GREEN}${avail}${RESET} free"
    else
      echo -e "  ${BOLD}${node}${RESET} ${DIM}(usage unavailable)${RESET}"
    fi
  done
  echo ""
}

# ══════════════════════════════════════════════════════════════════════════════
# PVC USAGE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

# Cache for PVC usage data (pvc_name -> used|total|percent)
declare -A PVC_USAGE_CACHE

# Get PVC usage by exec'ing df inside a pod that has it mounted
# Returns: used|total|percent or empty if unavailable
get_pvc_usage() {
  local pvc_name=$1
  local namespace="${2:-media}"
  local prefix="${3:-}"

  # Check cache first
  if [[ -n "${PVC_USAGE_CACHE[$pvc_name]:-}" ]]; then
    echo "${PVC_USAGE_CACHE[$pvc_name]}"
    return
  fi

  # Find a pod that has this PVC mounted
  local pod_info
  pod_info=$(jq -r ".items[] | select(.status.phase == \"Running\") | select(.spec.volumes[]?.persistentVolumeClaim?.claimName == \"$pvc_name\") | .metadata.name + \"|\" + (.spec.volumes[] | select(.persistentVolumeClaim?.claimName == \"$pvc_name\") | .name)" "$CACHE_DIR/${prefix}pods.json" 2>/dev/null | head -1)

  if [[ -z "$pod_info" ]]; then
    return
  fi

  local pod_name vol_name
  IFS='|' read -r pod_name vol_name <<< "$pod_info"

  # Find the mount path for this volume
  local mount_path
  mount_path=$(jq -r ".items[] | select(.metadata.name == \"$pod_name\") | .spec.containers[0].volumeMounts[]? | select(.name == \"$vol_name\") | .mountPath" "$CACHE_DIR/${prefix}pods.json" 2>/dev/null | head -1)

  if [[ -z "$mount_path" ]]; then
    return
  fi

  # Run df inside the pod
  local df_output
  df_output=$(kubectl exec -n "$namespace" "$pod_name" -- df -h "$mount_path" 2>/dev/null | tail -1)

  if [[ -n "$df_output" ]]; then
    local size used avail percent
    read -r _ size used avail percent _ <<< "$df_output"
    PVC_USAGE_CACHE[$pvc_name]="${used}|${size}|${percent%\%}"
    echo "${used}|${size}|${percent%\%}"
  fi
}

# Fetch PVC usage for all PVCs in namespace (parallel for speed)
fetch_pvc_usage() {
  local namespace="${1:-media}"
  local prefix="${2:-}"

  # Get list of bound PVCs
  local pvcs
  pvcs=$(jq -r '.items[] | select(.status.phase == "Bound") | .metadata.name' "$CACHE_DIR/${prefix}pvcs.json" 2>/dev/null)

  # Fetch usage for each (could parallelize but kubectl exec is slow anyway)
  for pvc in $pvcs; do
    get_pvc_usage "$pvc" "$namespace" "$prefix" >/dev/null 2>&1 &
  done
  wait
}

# Cache for emptyDir usage data
declare -A EMPTYDIR_USAGE_CACHE

# Get emptyDir volume usage by exec'ing df inside the pod
# Usage: get_emptydir_usage "deployment-name" "volume-name" "namespace"
# Returns: used|total|percent or empty if unavailable
get_emptydir_usage() {
  local deploy_name=$1
  local vol_name=$2
  local namespace="${3:-media}"

  local cache_key="${deploy_name}:${vol_name}"

  # Check cache first
  if [[ -n "${EMPTYDIR_USAGE_CACHE[$cache_key]:-}" ]]; then
    echo "${EMPTYDIR_USAGE_CACHE[$cache_key]}"
    return
  fi

  # Find the pod for this deployment
  local pod_name
  pod_name=$(kubectl get pods -n "$namespace" -l "app=$deploy_name" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)

  if [[ -z "$pod_name" ]]; then
    # Try with app.kubernetes.io/name label
    pod_name=$(kubectl get pods -n "$namespace" -l "app.kubernetes.io/name=$deploy_name" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
  fi

  if [[ -z "$pod_name" ]]; then
    return
  fi

  # Find the mount path for this volume
  local mount_path
  mount_path=$(kubectl get pod -n "$namespace" "$pod_name" -o jsonpath="{.spec.containers[0].volumeMounts[?(@.name==\"$vol_name\")].mountPath}" 2>/dev/null)

  if [[ -z "$mount_path" ]]; then
    return
  fi

  # Run df inside the pod
  local df_output
  df_output=$(kubectl exec -n "$namespace" "$pod_name" -- df -h "$mount_path" 2>/dev/null | tail -1)

  if [[ -n "$df_output" ]]; then
    local size used avail percent
    read -r _ size used avail percent _ <<< "$df_output"
    EMPTYDIR_USAGE_CACHE[$cache_key]="${used}|${size}|${percent%\%}"
    echo "${used}|${size}|${percent%\%}"
  fi
}

# Print a compact usage bar with size info
# Usage: print_compact_usage_bar used total percent [width]
print_compact_usage_bar() {
  local used=$1
  local total=$2
  local percent=$3
  local width=${4:-12}

  # Calculate filled segments
  local filled=$((percent * width / 100))
  local empty=$((width - filled))

  # Color based on usage
  local color=$GREEN
  if [[ $percent -ge 90 ]]; then
    color=$RED
  elif [[ $percent -ge 70 ]]; then
    color=$YELLOW
  fi

  # Build the bar
  local bar=""
  for ((i=0; i<filled; i++)); do bar+="█"; done
  for ((i=0; i<empty; i++)); do bar+="░"; done

  echo -e "${color}${bar}${RESET} ${used}/${total}"
}

# Print detailed infrastructure storage by category (from cluster) with usage bars
print_infrastructure_storage() {
  local namespace="${1:-media}"
  local prefix="${2:-}"

  print_section "INFRASTRUCTURE STORAGE"

  if [[ ! -f "$CACHE_DIR/${prefix}pvcs.json" ]]; then
    echo -e "  ${DIM}No PVC data available${RESET}"
    echo ""
    return
  fi

  # Group PVCs by service pattern and display with sizes
  local categories=(
    "Indexer:prowlarr"
    "Media Automation:sonarr radarr readarr overseerr"
    "Media Servers:plex jellyfin"
    "Transcoding:tdarr"
    "Media Management:kometa posterizarr posterr tautulli"
    "Downloads:sabnzbd qbittorrent"
    "Infrastructure:postgresql homepage"
  )

  for category_def in "${categories[@]}"; do
    local category_name="${category_def%%:*}"
    local services="${category_def#*:}"
    local found=false
    local category_output=""

    for service in $services; do
      # Find all PVCs matching this service
      local pvcs
      pvcs=$(jq -r ".items[] | select(.metadata.name | contains(\"$service\")) | .metadata.name + \"|\" + .spec.resources.requests.storage + \"|\" + .status.phase" "$CACHE_DIR/${prefix}pvcs.json" 2> /dev/null)

      if [[ -n "$pvcs" ]]; then
        found=true
        while IFS='|' read -r pvc_name size status; do
          local status_icon="${GREEN}●${RESET}"
          [[ "$status" != "Bound" ]] && status_icon="${YELLOW}○${RESET}"

          # Try to get actual usage
          local usage
          usage=$(get_pvc_usage "$pvc_name" "$namespace" "$prefix")

          if [[ -n "$usage" ]]; then
            local used total percent
            IFS='|' read -r used total percent <<< "$usage"
            local bar
            bar=$(print_compact_usage_bar "$used" "$total" "$percent" 10)
            category_output+="    ${status_icon} ${pvc_name}: ${bar}\n"
          else
            category_output+="    ${status_icon} ${pvc_name}: ${CYAN}${size}${RESET} ${DIM}(usage n/a)${RESET}\n"
          fi
        done <<< "$pvcs"
      fi
    done

    if [[ "$found" == "true" ]]; then
      echo -e "  ${BOLD}${category_name}${RESET}"
      echo -e "$category_output"
    fi
  done

  # Show transcode cache (emptyDir) info from deployments with usage bars
  echo -e "  ${BOLD}Transcode Cache (emptyDir)${RESET}"
  if [[ -f "$CACHE_DIR/${prefix}deployments.json" ]]; then
    # Get emptyDir volumes with their deployments and limits (use | as delimiter since names don't have it)
    local cache_info
    cache_info=$(jq -r '.items[] | select(.metadata.name | test("tdarr|plex|jellyfin")) | .metadata.name as $dep | .spec.template.spec.volumes[]? | select(.emptyDir != null) | [$dep, .name, (.emptyDir.sizeLimit // "unlimited")] | join("|")' "$CACHE_DIR/${prefix}deployments.json" 2> /dev/null | sort -u)

    if [[ -n "$cache_info" ]]; then
      while IFS='|' read -r deploy_name vol_name size_limit; do
        [[ -z "$deploy_name" ]] && continue
        # Try to get actual usage by exec'ing into the pod
        local usage
        usage=$(get_emptydir_usage "$deploy_name" "$vol_name" "$namespace")

        if [[ -n "$usage" ]]; then
          local used total percent
          IFS='|' read -r used total percent <<< "$usage"
          local bar
          bar=$(print_compact_usage_bar "$used" "$total" "$percent" 10)
          echo -e "    ${BLUE}◆${RESET} ${deploy_name}/${vol_name}: ${bar}"
        else
          echo -e "    ${BLUE}◆${RESET} ${deploy_name}/${vol_name}: ${CYAN}${size_limit}${RESET} ${DIM}(node-local)${RESET}"
        fi
      done <<< "$cache_info"
    else
      echo -e "    ${DIM}No emptyDir volumes found${RESET}"
    fi
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

# ══════════════════════════════════════════════════════════════════════════════
# DUAL COLUMN LAYOUT HELPERS
# ══════════════════════════════════════════════════════════════════════════════

# Minimum width for dual-column mode
DUAL_COLUMN_MIN_WIDTH=${DUAL_COLUMN_MIN_WIDTH:-140}

# Get terminal width
get_terminal_width() {
  if [[ -n "${COLUMNS:-}" ]]; then
    echo "$COLUMNS"
  elif command -v tput &>/dev/null; then
    tput cols 2>/dev/null || echo "80"
  else
    echo "80"
  fi
}

# Check if terminal is wide enough for dual columns
is_dual_column_mode() {
  local width
  width=$(get_terminal_width)
  [[ $width -ge $DUAL_COLUMN_MIN_WIDTH ]]
}

# Collect output into an array for columnar display
# Usage: start_column_buffer
#        ... output commands ...
#        end_column_buffer
# Then use COLUMN_BUFFER array
declare -a COLUMN_BUFFER_LEFT
declare -a COLUMN_BUFFER_RIGHT

start_column_buffer() {
  COLUMN_BUFFER_LEFT=()
  COLUMN_BUFFER_RIGHT=()
}

# Add a line to the left column buffer
add_to_left_column() {
  COLUMN_BUFFER_LEFT+=("$1")
}

# Add a line to the right column buffer
add_to_right_column() {
  COLUMN_BUFFER_RIGHT+=("$1")
}

# Strip ANSI codes for width calculation
strip_ansi() {
  echo -e "$1" | sed 's/\x1b\[[0-9;]*m//g'
}

# Calculate visible width of a string (excluding ANSI codes)
visible_width() {
  local stripped
  stripped=$(strip_ansi "$1")
  echo "${#stripped}"
}

# Pad a string to a given visible width
pad_to_width() {
  local str=$1
  local target_width=$2
  local current_width
  current_width=$(visible_width "$str")
  local padding=$((target_width - current_width))

  echo -n "$str"
  if [[ $padding -gt 0 ]]; then
    printf '%*s' "$padding" ''
  fi
}

# Print the column buffers side by side
# Usage: print_columns [separator] [left_width]
print_columns() {
  local separator="${1:-  │  }"
  local term_width
  term_width=$(get_terminal_width)
  local sep_width
  sep_width=$(visible_width "$separator")
  local left_width=$(( (term_width - sep_width) / 2 ))

  local left_len=${#COLUMN_BUFFER_LEFT[@]}
  local right_len=${#COLUMN_BUFFER_RIGHT[@]}
  local max_len=$((left_len > right_len ? left_len : right_len))

  for ((i=0; i<max_len; i++)); do
    local left_line="${COLUMN_BUFFER_LEFT[$i]:-}"
    local right_line="${COLUMN_BUFFER_RIGHT[$i]:-}"

    # Pad left column to fixed width and add right column
    echo -e "$(pad_to_width "$left_line" "$left_width")${separator}${right_line}"
  done
}

# Print two sections side by side if terminal is wide enough
# Usage: print_dual_sections "LEFT TITLE" left_content_func "RIGHT TITLE" right_content_func
print_dual_sections() {
  local left_title=$1
  local left_func=$2
  local right_title=$3
  local right_func=$4

  if is_dual_column_mode; then
    start_column_buffer

    # Capture left output
    add_to_left_column "$(print_section "$left_title" | head -1)"
    while IFS= read -r line; do
      add_to_left_column "$line"
    done < <($left_func 2>/dev/null)
    add_to_left_column ""

    # Capture right output
    add_to_right_column "$(print_section "$right_title" | head -1)"
    while IFS= read -r line; do
      add_to_right_column "$line"
    done < <($right_func 2>/dev/null)
    add_to_right_column ""

    print_columns "  │  "
  else
    # Single column mode - print sequentially
    print_section "$left_title"
    $left_func
    echo ""
    print_section "$right_title"
    $right_func
    echo ""
  fi
}

# Print quick commands section
print_quick_commands() {
  local namespace="${1:-default}"

  print_section "QUICK COMMANDS"
  print_quick_commands_content "$namespace"
  echo ""
}

# Print quick commands content only (for dual-column mode)
print_quick_commands_content() {
  local namespace="${1:-default}"
  echo -e "  ${CYAN}pods${RESET}    │ kubectl get pods -n $namespace"
  echo -e "  ${CYAN}pvcs${RESET}    │ kubectl get pvc -n $namespace"
  echo -e "  ${CYAN}logs${RESET}    │ kubectl logs -n $namespace deploy/<name> -f"
  echo -e "  ${CYAN}shell${RESET}   │ kubectl exec -n $namespace -it deploy/<name> -- /bin/bash"
  echo -e "  ${CYAN}restart${RESET} │ kubectl rollout restart deploy/<name> -n $namespace"
}

# Print node storage content only (for dual-column mode)
print_node_storage_content() {
  local namespace="${1:-media}"
  local prefix="${2:-}"

  # Get unique nodes with local-path PVCs
  local nodes
  nodes=$(jq -r '.items[] | select(.spec.storageClassName == "local-path") | .metadata.annotations["volume.kubernetes.io/selected-node"] // empty' "$CACHE_DIR/${prefix}pvcs.json" 2>/dev/null | sort -u)

  if [[ -z "$nodes" ]]; then
    echo -e "  ${DIM}No local-path PVCs found${RESET}"
    return
  fi

  for node in $nodes; do
    if [[ -z "$node" ]]; then continue; fi

    # Get disk usage for this node
    local usage
    usage=$(get_node_disk_usage "$node" "$namespace")

    if [[ -n "$usage" ]]; then
      local used avail total percent
      IFS='|' read -r used avail total percent <<< "$usage"

      # Count PVCs on this node
      local pvc_count
      pvc_count=$(jq -r "[.items[] | select(.spec.storageClassName == \"local-path\" and .metadata.annotations[\"volume.kubernetes.io/selected-node\"] == \"$node\")] | length" "$CACHE_DIR/${prefix}pvcs.json" 2>/dev/null || echo "0")

      echo -e "  ${BOLD}${node}${RESET} ${DIM}(${pvc_count} PVCs)${RESET}"
      echo -e "    $(print_usage_bar "${percent%\%}" 20)  ${CYAN}${used}${RESET}/${total}"
    else
      echo -e "  ${BOLD}${node}${RESET} ${DIM}(usage unavailable)${RESET}"
    fi
  done
}

# Print infrastructure storage content only (for dual-column mode)
print_infrastructure_storage_content() {
  local namespace="${1:-media}"
  local prefix="${2:-}"

  if [[ ! -f "$CACHE_DIR/${prefix}pvcs.json" ]]; then
    echo -e "  ${DIM}No PVC data available${RESET}"
    return
  fi

  # Group PVCs by service pattern and display with sizes
  local categories=(
    "Indexer:prowlarr"
    "Media Automation:sonarr radarr readarr overseerr"
    "Media Servers:plex jellyfin"
    "Transcoding:tdarr"
    "Media Mgmt:kometa posterizarr posterr tautulli"
    "Downloads:sabnzbd qbittorrent"
    "Infra:postgresql homepage"
  )

  for category_def in "${categories[@]}"; do
    local category_name="${category_def%%:*}"
    local services="${category_def#*:}"
    local found=false
    local category_output=""

    for service in $services; do
      # Find all PVCs matching this service
      local pvcs
      pvcs=$(jq -r ".items[] | select(.metadata.name | contains(\"$service\")) | .metadata.name + \"|\" + .spec.resources.requests.storage + \"|\" + .status.phase" "$CACHE_DIR/${prefix}pvcs.json" 2> /dev/null)

      if [[ -n "$pvcs" ]]; then
        found=true
        while IFS='|' read -r pvc_name size status; do
          local status_icon="${GREEN}●${RESET}"
          [[ "$status" != "Bound" ]] && status_icon="${YELLOW}○${RESET}"

          # Try to get actual usage
          local usage
          usage=$(get_pvc_usage "$pvc_name" "$namespace" "$prefix")

          if [[ -n "$usage" ]]; then
            local used total percent
            IFS='|' read -r used total percent <<< "$usage"
            local bar
            bar=$(print_compact_usage_bar "$used" "$total" "$percent" 8)
            category_output+="  ${status_icon} ${pvc_name##*-}: ${bar}\n"
          else
            category_output+="  ${status_icon} ${pvc_name##*-}: ${CYAN}${size}${RESET}\n"
          fi
        done <<< "$pvcs"
      fi
    done

    if [[ "$found" == "true" ]]; then
      echo -e "  ${BOLD}${category_name}${RESET}"
      echo -e "$category_output"
    fi
  done
}
