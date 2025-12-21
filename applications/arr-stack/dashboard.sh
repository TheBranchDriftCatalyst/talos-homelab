#!/usr/bin/env bash
# ARR Stack Dashboard - Dynamic cluster status display
# Dynamically queries the cluster for all arr-stack services and their status
#
# Usage:
#   ./dashboard.sh              # Show full dashboard
#   ./dashboard.sh --copy N     # Copy credential N to clipboard
#   ./dashboard.sh --list       # List credentials with copy commands
#
# shellcheck disable=SC2016,SC2034

set -euo pipefail

# Get script directory and source common library
DASHBOARD_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${DASHBOARD_SCRIPT_DIR}/../.." && pwd)"

# shellcheck source=../../scripts/lib/dashboard-common.sh
source "${PROJECT_ROOT}/scripts/lib/dashboard-common.sh"

# ============================================================================
# ARR-specific configuration
# ============================================================================
NAMESPACE="${NAMESPACE:-media}"
COPY_MODE=""
COPY_INDEX=""
LIST_MODE=false

# Parse arguments
SUMMARY_MODE=false
while [[ $# -gt 0 ]]; do
  case $1 in
    --copy | -c)
      COPY_MODE=true
      COPY_INDEX="${2:-}"
      shift 2 || shift
      ;;
    --list | -l)
      LIST_MODE=true
      shift
      ;;
    --summary | -s)
      SUMMARY_MODE=true
      shift
      ;;
    --full | -f)
      SUMMARY_MODE=false
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
 █████  ██████  ██████       ███████ ████████  █████   ██████ ██   ██
██   ██ ██   ██ ██   ██      ██         ██    ██   ██ ██      ██  ██
███████ ██████  ██████  █████ ███████    ██    ███████ ██      █████
██   ██ ██   ██ ██   ██           ██    ██    ██   ██ ██      ██  ██
██   ██ ██   ██ ██   ██      ███████    ██    ██   ██  ██████ ██   ██
                      ⚡ Media Automation Stack ⚡
EOF
  echo -e "${RESET}"
  echo ""
}

# ============================================================================
# ARR-specific helper functions
# ============================================================================

# Get API key for a service from arr-api-keys or arr-stack-secrets
get_api_key() {
  local service=$1
  local key

  # Try arr-api-keys first (uppercase format: SONARR_API_KEY)
  local key_name="${service^^}_API_KEY"
  key=$(get_secret_data "arr-api-keys" "$key_name")
  if [[ -n "$key" ]]; then
    echo "$key"
    return
  fi

  # Try arr-stack-secrets (lowercase format: sonarr-api-key)
  key_name="${service}-api-key"
  key=$(get_secret_data "arr-stack-secrets" "$key_name")
  if [[ -n "$key" ]]; then
    echo "$key"
    return
  fi
}

# Get VPN status from gluetun container
# Returns: ip|country|city|port or empty if unavailable
get_vpn_status() {
  local deploy=${1:-qbittorrent}
  local namespace="${2:-media}"

  # Get public IP info
  local ip_info
  ip_info=$(kubectl exec -n "$namespace" "deploy/$deploy" -c gluetun -- wget -qO- http://localhost:8000/v1/publicip/ip 2>/dev/null)

  if [[ -z "$ip_info" ]]; then
    return
  fi

  local ip country city
  ip=$(echo "$ip_info" | jq -r '.public_ip // empty')
  country=$(echo "$ip_info" | jq -r '.country // empty')
  city=$(echo "$ip_info" | jq -r '.city // empty')

  # Get forwarded port
  local port_info port
  port_info=$(kubectl exec -n "$namespace" "deploy/$deploy" -c gluetun -- wget -qO- http://localhost:8000/v1/openvpn/portforwarded 2>/dev/null)
  port=$(echo "$port_info" | jq -r '.port // empty')

  echo "${ip}|${country}|${city}|${port}"
}

# Print VPN status section
print_vpn_status() {
  local namespace="${1:-media}"

  local vpn_info
  vpn_info=$(get_vpn_status "qbittorrent" "$namespace")

  if [[ -n "$vpn_info" ]]; then
    local ip country city port
    IFS='|' read -r ip country city port <<< "$vpn_info"

    # Country flag emoji
    local flag="🌐"
    case "${country,,}" in
      netherlands) flag="🇳🇱" ;;
      germany) flag="🇩🇪" ;;
      switzerland) flag="🇨🇭" ;;
      sweden) flag="🇸🇪" ;;
      "united states") flag="🇺🇸" ;;
      "united kingdom") flag="🇬🇧" ;;
      japan) flag="🇯🇵" ;;
    esac

    echo -e "  ${BOLD}VPN Status${RESET}"
    echo -e "    ${GREEN}●${RESET} IP: ${CYAN}${ip}${RESET} (${country} ${flag})"
    if [[ -n "$port" ]] && [[ "$port" != "0" ]]; then
      echo -e "    ${GREEN}●${RESET} Forwarded Port: ${CYAN}${port}${RESET} ${DIM}(synced to qBittorrent)${RESET}"
    fi
    echo ""
  fi
}

# Get service credentials - returns "user:pass" or "apikey:KEY" or empty
get_service_credentials() {
  local service=$1

  case "$service" in
    postgresql)
      local pass
      pass=$(get_secret_data "postgresql-secret" "postgres-password")
      if [[ -n "$pass" ]]; then
        echo "postgres:${pass}"
      fi
      ;;
    grafana)
      local user pass
      user=$(get_secret_data "homepage-secrets" "HOMEPAGE_VAR_GRAFANA_USER")
      pass=$(get_secret_data "homepage-secrets" "HOMEPAGE_VAR_GRAFANA_PASS")
      if [[ -n "$user" ]] && [[ -n "$pass" ]]; then
        echo "${user}:${pass}"
      fi
      ;;
    sonarr | radarr | prowlarr | readarr | overseerr | jellyfin | plex)
      local api_key
      api_key=$(get_api_key "$service")
      if [[ -n "$api_key" ]]; then
        # Truncate long API keys for display
        if [[ ${#api_key} -gt 16 ]]; then
          echo "apikey:${api_key:0:12}..."
        else
          echo "apikey:${api_key}"
        fi
      fi
      ;;
    *)
      # No credentials known
      ;;
  esac
}

# ============================================================================
# Print service section with volume mounts
# ============================================================================
print_arr_service() {
  local name=$1
  local description=$2
  local is_last=${3:-false}
  local show_db=${4:-false}

  local status ready ingress_url
  status=$(get_pod_status_by_app "$name")
  ready=$(get_pod_ready_by_app "$name")
  ingress_url=$(get_ingress_url "$name")

  # Handle missing data
  [[ -z "$status" ]] && status="NotFound"

  # Get credentials for this service
  local creds creds_display=""
  creds=$(get_service_credentials "$name")
  if [[ -n "$creds" ]]; then
    creds_display="${YELLOW}${creds}${RESET}"
  fi

  print_service_line "$name" "$status" "$ready" "$ingress_url" "$is_last" "$creds_display"

  # Tree continuation character
  local cont="┃"
  [[ "$is_last" == "true" ]] && cont=" "

  # Get and print volume mounts
  local volumes
  volumes=$(get_volume_mounts "$name")
  if [[ -n "$volumes" ]]; then
    while IFS=: read -r vol_name pvc_name; do
      if [[ -n "$pvc_name" ]]; then
        print_volume_mount "$pvc_name" "  ${cont}    "
      fi
    done <<< "$volumes"
  fi

  # Show database info if requested
  if [[ "$show_db" == "true" ]]; then
    local db_name
    db_name=$(get_secret_data "${name}-secret" "POSTGRES_DB")
    if [[ -n "$db_name" ]]; then
      echo -e "  ${cont}    ${DIM}db: ${db_name}${RESET}"
    fi
  fi

  echo ""
}

# Print a service that might not exist
print_optional_service() {
  local name=$1
  local description=$2
  local is_last=${3:-false}

  if get_deployment_exists "$name"; then
    print_arr_service "$name" "$description" "$is_last"
  else
    local branch="┣━"
    [[ "$is_last" == "true" ]] && branch="┗━"
    echo -e "  ${DIM}${branch} ${name} (not deployed)${RESET}"
    echo ""
  fi
  return 0
}

# ============================================================================
# Print credentials table (full keys for copy/paste)
# ============================================================================
print_credentials_table() {
  local has_creds=false

  # PostgreSQL
  local pg_pass
  pg_pass=$(get_secret_data "postgresql-secret" "postgres-password")
  if [[ -n "$pg_pass" ]]; then
    echo -e "  ${CYAN}postgresql${RESET}  │ postgres:${pg_pass}"
    has_creds=true
  fi

  # API Keys from arr-api-keys / arr-stack-secrets
  local services=("sonarr" "radarr" "prowlarr" "readarr" "overseerr" "sabnzbd")
  for svc in "${services[@]}"; do
    local api_key
    api_key=$(get_api_key "$svc")
    if [[ -n "$api_key" ]]; then
      printf "  ${CYAN}%-11s${RESET} │ apikey:%s\n" "$svc" "$api_key"
      has_creds=true
    fi
  done

  # Plex credentials from dedicated secret
  local plex_token
  plex_token=$(get_secret_data "homepage-plex-credentials" "HOMEPAGE_VAR_PLEX_KEY")
  if [[ -n "$plex_token" ]]; then
    # Truncate for display
    if [[ ${#plex_token} -gt 20 ]]; then
      echo -e "  ${CYAN}plex${RESET}        │ token:${plex_token:0:16}..."
    else
      echo -e "  ${CYAN}plex${RESET}        │ token:${plex_token}"
    fi
    has_creds=true
  fi

  # ArgoCD key if present
  local argocd_key
  argocd_key=$(get_secret_data "homepage-argocd-credentials" "HOMEPAGE_VAR_ARGOCD_KEY")
  if [[ -n "$argocd_key" ]]; then
    echo -e "  ${CYAN}argocd${RESET}      │ apikey:${argocd_key}"
    has_creds=true
  fi

  # Grafana credentials
  local grafana_user grafana_pass
  grafana_user=$(get_secret_data "homepage-grafana-credentials" "HOMEPAGE_VAR_GRAFANA_USER")
  grafana_pass=$(get_secret_data "homepage-grafana-credentials" "HOMEPAGE_VAR_GRAFANA_PASS")
  if [[ -n "$grafana_user" ]] && [[ -n "$grafana_pass" ]]; then
    echo -e "  ${CYAN}grafana${RESET}     │ ${grafana_user}:${grafana_pass}"
    has_creds=true
  fi

  if [[ "$has_creds" == "false" ]]; then
    echo -e "  ${DIM}No credentials found in secrets${RESET}"
  fi
}

# ============================================================================
# Print pod status table
# ============================================================================
print_pod_status() {
  print_section "POD STATUS"
  jq -r '.items[] | [.metadata.name, .status.phase, (.status.containerStatuses[0].restartCount // 0 | tostring), .metadata.creationTimestamp] | @tsv' "$CACHE_DIR/pods.json" 2> /dev/null |
    column -t -s $'\t' | head -15 || echo "  No pods found"
  echo ""
}

# ============================================================================
# Summary mode output
# ============================================================================
print_summary_mode() {
  dashboard_init

  if ! namespace_exists "$NAMESPACE"; then
    echo -e "    ARR Stack: ${RED}✗${RESET} namespace not found"
    return 0
  fi

  fetch_namespace_data "$NAMESPACE"

  local total running
  total=$(jq '.items | length' "$CACHE_DIR/pods.json" 2> /dev/null || echo "0")
  running=$(jq '[.items[] | select(.status.phase == "Running")] | length' "$CACHE_DIR/pods.json" 2> /dev/null || echo "0")

  local status_icon="${GREEN}✓${RESET}"
  [[ "$running" != "$total" ]] && status_icon="${YELLOW}⚠${RESET}"

  echo -e "    ARR Stack: ${status_icon} ${running}/${total} pods │ sonarr/radarr/prowlarr"
}

# ============================================================================
# Node-centric service display
# ============================================================================

# Print a service with inline details (credentials, VPN, volumes)
# Optimized to use cached data only (no kubectl exec calls)
print_node_service() {
  local name=$1
  local is_last=${2:-false}
  local node=$3

  local status ready ingress_url
  status=$(get_pod_status_by_app "$name")
  ready=$(get_pod_ready_by_app "$name")
  ingress_url=$(get_ingress_url "$name")

  [[ -z "$status" ]] && status="NotFound"

  local status_indicator
  status_indicator=$(print_status_indicator "$status" "$ready")

  # Tree characters
  local branch="${TREE_BRANCH}"
  local cont="${TREE_CONT}"
  [[ "$is_last" == "true" ]] && branch="${TREE_LAST}" && cont=" "

  # Get credentials for this service
  local creds=""
  local api_key
  api_key=$(get_api_key "$name")
  if [[ -n "$api_key" ]]; then
    if [[ ${#api_key} -gt 12 ]]; then
      creds="${YELLOW}apikey:${api_key:0:8}...${RESET}"
    else
      creds="${YELLOW}apikey:${api_key}${RESET}"
    fi
  fi

  # Main service line
  local line="  ${BOLD}${branch} ${name}${RESET} ${status_indicator}"
  [[ -n "$ingress_url" ]] && line+=" ${DIM}→${RESET} ${CYAN}${ingress_url}${RESET}"
  [[ -n "$creds" ]] && line+=" ${DIM}│${RESET} ${creds}"
  echo -e "$line"

  # VPN status for qbittorrent (cached via global)
  if [[ "$name" == "qbittorrent" ]] && [[ -n "${VPN_STATUS:-}" ]]; then
    local ip country city port flag="🌐"
    IFS='|' read -r ip country city port <<< "$VPN_STATUS"
    case "${country,,}" in
      netherlands) flag="🇳🇱" ;; germany) flag="🇩🇪" ;; switzerland) flag="🇨🇭" ;;
      sweden) flag="🇸🇪" ;; "united states") flag="🇺🇸" ;; japan) flag="🇯🇵" ;;
    esac
    echo -e "  ${cont}    ${GREEN}⚡${RESET} VPN: ${CYAN}${ip}${RESET} ${flag} ${DIM}Port:${port}${RESET}"
  fi

  # Local volumes (from cached PVC data, no exec)
  local local_vols
  local_vols=$(jq -r ".items[] | select(.metadata.name == \"$name\") | .spec.template.spec.volumes[]? | select(.persistentVolumeClaim != null) | .persistentVolumeClaim.claimName" "$CACHE_DIR/deployments.json" 2>/dev/null)

  if [[ -n "$local_vols" ]]; then
    while read -r pvc; do
      [[ -z "$pvc" ]] && continue
      # Get PVC info from cache
      local pvc_info
      pvc_info=$(jq -r ".items[] | select(.metadata.name == \"$pvc\") | .spec.resources.requests.storage + \"|\" + .spec.storageClassName" "$CACHE_DIR/pvcs.json" 2>/dev/null)
      [[ -z "$pvc_info" ]] && continue

      local size sc
      IFS='|' read -r size sc <<< "$pvc_info"

      # Only show local-path volumes here (shared NFS shown separately)
      if [[ "$sc" == "local-path" ]]; then
        local sc_short
        sc_short=$(shorten_storageclass "$sc")
        echo -e "  ${cont}    ${GREEN}●${RESET} ${DIM}${pvc##*-}${RESET} ${BLUE}(${size})${RESET} ${DIM}[${sc_short}]${RESET}"
      fi
    done <<< "$local_vols"
  fi

  # emptyDir volumes (transcode cache) - just show name, no exec
  local empty_vols
  empty_vols=$(jq -r ".items[] | select(.metadata.name == \"$name\") | .spec.template.spec.volumes[]? | select(.emptyDir != null) | .name + \"|\" + (.emptyDir.sizeLimit // \"node-disk\")" "$CACHE_DIR/deployments.json" 2>/dev/null)
  if [[ -n "$empty_vols" ]]; then
    while IFS='|' read -r vol limit; do
      [[ -z "$vol" ]] && continue
      echo -e "  ${cont}    ${BLUE}◆${RESET} ${DIM}${vol}${RESET} ${CYAN}(${limit})${RESET}"
    done <<< "$empty_vols"
  fi

  echo ""
}

# Print a node section with all its services
print_node_section() {
  local node=$1
  local services=$2
  local disk_info="${3:-}"  # Pre-fetched disk info

  local disk_bar=""
  if [[ -n "$disk_info" ]]; then
    local used avail total percent
    IFS='|' read -r used avail total percent <<< "$disk_info"
    disk_bar=" $(print_usage_bar "${percent%\%}" 15)  ${CYAN}${used}${RESET}/${total}"
  fi

  # Count services
  local svc_count
  svc_count=$(echo "$services" | wc -l | tr -d ' ')

  echo -e "${MAGENTA}${BOLD}▸ NODE: ${node}${RESET} ${DIM}(${svc_count} services)${RESET}${disk_bar}"

  # Print each service
  local i=0
  local total_svcs
  total_svcs=$(echo "$services" | wc -l | tr -d ' ')
  while read -r svc; do
    [[ -z "$svc" ]] && continue
    i=$((i + 1))
    local is_last="false"
    [[ $i -eq $total_svcs ]] && is_last="true"
    print_node_service "$svc" "$is_last" "$node"
  done <<< "$services"
}

# ============================================================================
# Main dashboard
# ============================================================================
main() {
  # Handle summary mode first
  if [[ "$SUMMARY_MODE" == "true" ]]; then
    print_summary_mode
    return 0
  fi

  # Initialize (checks kubectl, kubeconfig, creates cache dir)
  dashboard_init

  clear
  print_header

  # Check if namespace exists
  if ! namespace_exists "$NAMESPACE"; then
    echo -e "${RED}✗ Namespace '$NAMESPACE' not found${RESET}"
    echo ""
    echo -e "${DIM}To deploy arr-stack:${RESET}"
    echo "  task infra:deploy-arr-stack"
    echo ""
    exit 1
  fi

  # Fetch all data upfront
  fetch_namespace_data "$NAMESPACE"
  fetch_cluster_data

  # Pre-fetch VPN status (single kubectl exec call)
  echo -e "${DIM}Checking VPN status...${RESET}"
  VPN_STATUS=$(get_vpn_status "qbittorrent" "$NAMESPACE" 2>/dev/null || true)
  echo -e "\033[1A\033[2K"

  # Legend
  echo -e "${DIM}Legend: ${GREEN}●${RESET}${DIM}=PVC ${BLUE}◆${RESET}${DIM}=Cache ${GREEN}⚡${RESET}${DIM}=VPN${RESET}"
  echo ""

  # Get all nodes and their services
  local nodes
  nodes=$(get_all_nodes)

  # Pre-fetch node disk usage (one exec per node)
  echo -e "${DIM}Fetching node disk usage...${RESET}"
  declare -A NODE_DISK_INFO
  while read -r node; do
    [[ -z "$node" ]] && continue
    NODE_DISK_INFO["$node"]=$(get_node_disk_usage "$node" "$NAMESPACE" 2>/dev/null || true)
  done <<< "$nodes"
  echo -e "\033[1A\033[2K"

  # Print node sections
  for node in $nodes; do
    [[ -z "$node" ]] && continue
    local services
    services=$(get_deployments_on_node "$node")
    [[ -z "$services" ]] && continue
    print_node_section "$node" "$services" "${NODE_DISK_INFO[$node]:-}"
  done

  # Shared Storage Section (NFS/NAS)
  print_section "SHARED STORAGE (NFS/NAS)"

  # Collect all shared PVCs and which services use them
  declare -A shared_pvcs
  while read -r node; do
    [[ -z "$node" ]] && continue
    local services
    services=$(get_deployments_on_node "$node")
    while read -r svc; do
      [[ -z "$svc" ]] && continue
      local shared
      shared=$(get_shared_volumes "$svc")
      while IFS='|' read -r pvc sc; do
        [[ -z "$pvc" ]] && continue
        if [[ -z "${shared_pvcs[$pvc]:-}" ]]; then
          shared_pvcs[$pvc]="$sc:$svc"
        else
          shared_pvcs[$pvc]="${shared_pvcs[$pvc]},$svc"
        fi
      done <<< "$shared"
    done <<< "$services"
  done <<< "$nodes"

  # Print shared PVCs grouped by storage class
  local last_sc=""
  for pvc in $(echo "${!shared_pvcs[@]}" | tr ' ' '\n' | sort); do
    local info="${shared_pvcs[$pvc]}"
    local sc="${info%%:*}"
    local users="${info#*:}"
    local sc_short
    sc_short=$(shorten_storageclass "$sc")

    # Get size
    local size
    size=$(jq -r ".items[] | select(.metadata.name == \"$pvc\") | .spec.resources.requests.storage" "$CACHE_DIR/pvcs.json" 2>/dev/null)

    # Count users
    local user_count
    user_count=$(echo "$users" | tr ',' '\n' | wc -l | tr -d ' ')

    echo -e "  ${GREEN}●${RESET} ${pvc} ${BLUE}(${size})${RESET} ${DIM}[${sc_short}]${RESET} ${DIM}← ${user_count} services${RESET}"
  done
  echo ""

  # Credentials Summary
  print_section "CREDENTIALS"
  print_credentials_table
  echo ""

  # Quick Commands
  print_quick_commands "$NAMESPACE"

  # Cluster status
  print_cluster_status
  echo ""
}

# Run main function
main "$@"
