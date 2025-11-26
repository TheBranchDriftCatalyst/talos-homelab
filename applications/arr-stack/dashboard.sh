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

# Color codes
RESET='\033[0m'
BOLD='\033[1m'
DIM='\033[2m'
CYAN='\033[96m'
GREEN='\033[92m'
YELLOW='\033[93m'
RED='\033[91m'
MAGENTA='\033[95m'
BLUE='\033[94m'

# Configuration
NAMESPACE="${NAMESPACE:-media-prod}"
KUBECONFIG_PATH="${KUBECONFIG:-./.output/kubeconfig}"
DOMAIN="${DOMAIN:-talos00}"
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

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
  echo "kubectl not found. Please install kubectl."
  exit 1
fi

# Check if kubeconfig exists
if [[ ! -f "$KUBECONFIG_PATH" ]] && [[ -z "${KUBECONFIG:-}" ]]; then
  echo "Kubeconfig not found at $KUBECONFIG_PATH"
  echo "Run: task kubeconfig"
  exit 1
fi

# Use local kubeconfig if KUBECONFIG env var not set
if [[ -z "${KUBECONFIG:-}" ]]; then
  export KUBECONFIG="$KUBECONFIG_PATH"
fi

# Temp files for cached data
CACHE_DIR=$(mktemp -d)
trap 'rm -rf "$CACHE_DIR"' EXIT

# ============================================================================
# Bulk data fetching - do all kubectl calls upfront
# ============================================================================
fetch_all_data() {
  echo -e "${DIM}Loading cluster data...${RESET}"

  # Fetch all data in parallel
  kubectl get deployments -n "$NAMESPACE" -o json > "$CACHE_DIR/deployments.json" 2> /dev/null &
  kubectl get pods -n "$NAMESPACE" -o json > "$CACHE_DIR/pods.json" 2> /dev/null &
  kubectl get pvc -n "$NAMESPACE" -o json > "$CACHE_DIR/pvcs.json" 2> /dev/null &
  kubectl get svc -n "$NAMESPACE" -o json > "$CACHE_DIR/services.json" 2> /dev/null &
  kubectl get ingressroute -n "$NAMESPACE" -o json > "$CACHE_DIR/ingressroutes.json" 2> /dev/null &
  kubectl get secrets -n "$NAMESPACE" -o json > "$CACHE_DIR/secrets.json" 2> /dev/null &
  kubectl get nodes -o json > "$CACHE_DIR/nodes.json" 2> /dev/null &

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

# Get deployment info from cache
get_deployment_exists() {
  local app=$1
  jq -e ".items[] | select(.metadata.name == \"$app\")" "$CACHE_DIR/deployments.json" &> /dev/null
}

# Get pod status from cache
get_pod_status() {
  local app=$1
  jq -r ".items[] | select(.metadata.labels.app == \"$app\") | .status.phase" "$CACHE_DIR/pods.json" 2> /dev/null | head -1
}

# Get pod ready status from cache
get_pod_ready() {
  local app=$1
  jq -r ".items[] | select(.metadata.labels.app == \"$app\") | .status.containerStatuses[0].ready // false" "$CACHE_DIR/pods.json" 2> /dev/null | head -1
}

# Get service info from cache
get_service_info() {
  local service=$1
  local result
  result=$(jq -r ".items[] | select(.metadata.name == \"$service\") | .spec.clusterIP + \":\" + (.spec.ports[0].port | tostring)" "$CACHE_DIR/services.json" 2> /dev/null)
  echo "${result:-not-found}"
}

# Get ingress URL from cache
get_ingress_url() {
  local service=$1
  local host
  host=$(jq -r ".items[] | select(.metadata.name | contains(\"$service\")) | .spec.routes[0].match" "$CACHE_DIR/ingressroutes.json" 2> /dev/null |
    sed -n 's/.*Host(`\([^`]*\)`).*/\1/p' | head -1)

  if [[ -n "$host" ]]; then
    echo "http://$host"
  else
    echo "http://$service.$DOMAIN"
  fi
}

# Get volume mounts for a deployment from cache
get_volume_mounts() {
  local app=$1
  jq -r ".items[] | select(.metadata.name == \"$app\") | .spec.template.spec.volumes[]? | select(.persistentVolumeClaim != null) | .name + \":\" + .persistentVolumeClaim.claimName" "$CACHE_DIR/deployments.json" 2> /dev/null
}

# Get PVC info from cache
get_pvc_info() {
  local pvc_name=$1
  jq -r ".items[] | select(.metadata.name == \"$pvc_name\") | .status.phase + \"|\" + .spec.resources.requests.storage + \"|\" + (.spec.storageClassName // \"default\")" "$CACHE_DIR/pvcs.json" 2> /dev/null
}

# Get secret data from cache
get_secret_data() {
  local secret_name=$1
  local key=$2
  local value
  value=$(jq -r ".items[] | select(.metadata.name == \"$secret_name\") | .data[\"$key\"] // empty" "$CACHE_DIR/secrets.json" 2> /dev/null)
  if [[ -n "$value" ]]; then
    echo "$value" | base64 -d 2> /dev/null
  fi
}

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

# Check cluster health from cache
cluster_healthy() {
  jq -e '.items | length > 0' "$CACHE_DIR/nodes.json" &> /dev/null
}

# ============================================================================
# Display functions
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

# Print volume mount with status indicator
print_volume_mount() {
  local pvc_name=$1
  local indent=$2

  local pvc_info
  pvc_info=$(get_pvc_info "$pvc_name")

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

# Print ASCII header
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

# Print service section with volume mounts
print_service() {
  local name=$1
  local description=$2
  local is_last=${3:-false}
  local show_db=${4:-false}

  local status
  status=$(get_pod_status "$name")
  local ready
  ready=$(get_pod_ready "$name")
  local ingress_url
  ingress_url=$(get_ingress_url "$name")

  # Status indicator
  local status_icon="⚠"
  local status_color=$YELLOW
  if [[ "$status" == "Running" ]] && [[ "$ready" == "true" ]]; then
    status_icon="✓"
    status_color=$GREEN
  elif [[ -z "$status" ]] || [[ "$status" == "null" ]]; then
    status_icon="✗"
    status_color=$RED
    status="NotFound"
  fi

  # Tree characters based on position
  local branch="┣━"
  local cont="┃"
  if [[ "$is_last" == "true" ]]; then
    branch="┗━"
    cont=" "
  fi

  # Get credentials for this service
  local creds
  creds=$(get_service_credentials "$name")
  local creds_display=""
  if [[ -n "$creds" ]]; then
    creds_display=" ${DIM}│${RESET} ${YELLOW}${creds}${RESET}"
  fi

  echo -e "  ${BOLD}${branch} ${name}${RESET} ${status_color}[${status_icon}]${RESET} ${DIM}→${RESET} ${ingress_url}${creds_display}"

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
    print_service "$name" "$description" "$is_last"
  else
    local branch="┣━"
    if [[ "$is_last" == "true" ]]; then
      branch="┗━"
    fi
    echo -e "  ${DIM}${branch} ${name} (not deployed)${RESET}"
    echo ""
  fi
  return 0
}

# Print credentials table (full keys for copy/paste)
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
# Main dashboard
# ============================================================================
main() {
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
  fetch_all_data

  # Legend
  echo -e "${DIM}Volume Status: ${GREEN}●${RESET}${DIM}=Bound ${YELLOW}○${RESET}${DIM}=Pending ${RED}✗${RESET}${DIM}=NotFound${RESET}"
  echo ""

  echo -e "${MAGENTA}▸ INDEXER & MANAGEMENT${RESET}"
  print_service "prowlarr" "Indexer Manager" true

  echo -e "${MAGENTA}▸ MEDIA AUTOMATION${RESET}"
  print_service "sonarr" "TV Shows"
  print_service "radarr" "Movies"
  print_optional_service "readarr" "Books"
  print_service "overseerr" "Request Management" true

  echo -e "${MAGENTA}▸ MEDIA SERVERS${RESET}"
  print_service "plex" "Plex Media Server"
  if get_deployment_exists "tdarr"; then
    print_service "jellyfin" "Jellyfin Media Server"
    print_service "tdarr" "Transcoding Service" true
  else
    print_service "jellyfin" "Jellyfin Media Server" true
  fi

  echo -e "${MAGENTA}▸ INFRASTRUCTURE${RESET}"
  print_service "postgresql" "PostgreSQL Database" false true
  print_optional_service "homepage" "Dashboard" true

  echo -e "${MAGENTA}▸ MONITORING${RESET}"
  print_optional_service "exportarr" "Metrics Exporter" true
  echo ""

  # Storage Summary from cached data
  echo -e "${MAGENTA}▸ STORAGE SUMMARY${RESET}"
  echo -e "  ${DIM}Namespace:${RESET} $NAMESPACE"

  local bound_count pending_count total_count
  bound_count=$(jq '[.items[] | select(.status.phase == "Bound")] | length' "$CACHE_DIR/pvcs.json" 2> /dev/null || echo "0")
  pending_count=$(jq '[.items[] | select(.status.phase == "Pending")] | length' "$CACHE_DIR/pvcs.json" 2> /dev/null || echo "0")
  total_count=$(jq '.items | length' "$CACHE_DIR/pvcs.json" 2> /dev/null || echo "0")

  echo -e "  ${DIM}PVCs:${RESET} ${GREEN}${bound_count} Bound${RESET} ${YELLOW}${pending_count} Pending${RESET} ${DIM}(${total_count} total)${RESET}"

  # Show storage classes in use
  local storage_classes
  storage_classes=$(jq -r '[.items[].spec.storageClassName] | unique | join(" ")' "$CACHE_DIR/pvcs.json" 2> /dev/null)
  if [[ -n "$storage_classes" ]]; then
    echo -e "  ${DIM}Storage Classes:${RESET} ${storage_classes}"
  fi
  echo ""

  # Credentials Summary
  echo -e "${MAGENTA}▸ CREDENTIALS${RESET}"
  print_credentials_table
  echo ""

  # Quick Commands
  echo -e "${MAGENTA}▸ QUICK COMMANDS${RESET}"
  echo -e "  ${CYAN}pods${RESET}    │ kubectl get pods -n $NAMESPACE"
  echo -e "  ${CYAN}pvcs${RESET}    │ kubectl get pvc -n $NAMESPACE"
  echo -e "  ${CYAN}logs${RESET}    │ kubectl logs -n $NAMESPACE deploy/<name> -f"
  echo -e "  ${CYAN}shell${RESET}   │ kubectl exec -n $NAMESPACE -it deploy/<name> -- /bin/bash"
  echo -e "  ${CYAN}restart${RESET} │ kubectl rollout restart deploy/<name> -n $NAMESPACE"
  echo ""

  # Cluster status from cache
  if cluster_healthy; then
    echo -e "${GREEN}✓ Cluster is running${RESET}"
  else
    echo -e "${RED}✗ Cluster is not accessible${RESET}"
  fi
  echo ""

  # Pod status table from cached data
  echo -e "${MAGENTA}▸ POD STATUS${RESET}"
  jq -r '.items[] | [.metadata.name, .status.phase, (.status.containerStatuses[0].restartCount // 0 | tostring), .metadata.creationTimestamp] | @tsv' "$CACHE_DIR/pods.json" 2> /dev/null |
    column -t -s $'\t' | head -15 || echo "  No pods found"
  echo ""
}

# Run main function
main "$@"
