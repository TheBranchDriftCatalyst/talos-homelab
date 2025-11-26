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
NAMESPACE="${NAMESPACE:-media-prod}"
COPY_MODE=""
COPY_INDEX=""
LIST_MODE=false

# Parse arguments
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

# Get API key for a service from homepage-secrets
get_api_key() {
  local service=$1
  local key_name="HOMEPAGE_VAR_${service^^}_KEY"
  get_secret_data "homepage-secrets" "$key_name"
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

  # API Keys from homepage-secrets
  local services=("sonarr" "radarr" "prowlarr" "readarr" "overseerr" "jellyfin" "plex")
  for svc in "${services[@]}"; do
    local api_key
    api_key=$(get_api_key "$svc")
    if [[ -n "$api_key" ]]; then
      printf "  ${CYAN}%-11s${RESET} │ apikey:%s\n" "$svc" "$api_key"
      has_creds=true
    fi
  done

  # ArgoCD key if present
  local argocd_key
  argocd_key=$(get_secret_data "homepage-secrets" "HOMEPAGE_VAR_ARGOCD_KEY")
  if [[ -n "$argocd_key" ]]; then
    echo -e "  ${CYAN}argocd${RESET}      │ apikey:${argocd_key}"
    has_creds=true
  fi

  # Grafana credentials
  local grafana_user grafana_pass
  grafana_user=$(get_secret_data "homepage-secrets" "HOMEPAGE_VAR_GRAFANA_USER")
  grafana_pass=$(get_secret_data "homepage-secrets" "HOMEPAGE_VAR_GRAFANA_PASS")
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
# Main dashboard
# ============================================================================
main() {
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

  # Legend
  echo -e "${DIM}Volume Status: ${GREEN}●${RESET}${DIM}=Bound ${YELLOW}○${RESET}${DIM}=Pending ${RED}✗${RESET}${DIM}=NotFound${RESET}"
  echo ""

  print_section "INDEXER & MANAGEMENT"
  print_arr_service "prowlarr" "Indexer Manager" true

  print_section "MEDIA AUTOMATION"
  print_arr_service "sonarr" "TV Shows"
  print_arr_service "radarr" "Movies"
  print_optional_service "readarr" "Books"
  print_arr_service "overseerr" "Request Management" true

  print_section "MEDIA SERVERS"
  print_arr_service "plex" "Plex Media Server"
  if get_deployment_exists "tdarr"; then
    print_arr_service "jellyfin" "Jellyfin Media Server"
    print_arr_service "tdarr" "Transcoding Service" true
  else
    print_arr_service "jellyfin" "Jellyfin Media Server" true
  fi

  print_section "INFRASTRUCTURE"
  print_arr_service "postgresql" "PostgreSQL Database" false true
  print_optional_service "homepage" "Dashboard" true

  print_section "MONITORING"
  print_optional_service "exportarr" "Metrics Exporter" true
  echo ""

  # Storage Summary
  print_storage_summary

  # Credentials Summary
  print_section "CREDENTIALS"
  print_credentials_table
  echo ""

  # Quick Commands
  print_quick_commands "$NAMESPACE"

  # Cluster status
  print_cluster_status
  echo ""

  # Pod status table
  print_pod_status
}

# Run main function
main "$@"
