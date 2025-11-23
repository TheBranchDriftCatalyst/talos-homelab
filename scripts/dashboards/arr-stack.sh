#!/usr/bin/env bash
# ARR Stack Dashboard - Dynamic cluster status display
# Dynamically queries the cluster for all arr-stack services and their status
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

# Configuration
NAMESPACE="${NAMESPACE:-media-dev}"
KUBECONFIG_PATH="${KUBECONFIG:-./.output/kubeconfig}"
DOMAIN="${DOMAIN:-talos00}"

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
  echo "❌ kubectl not found. Please install kubectl."
  exit 1
fi

# Check if kubeconfig exists
if [[ ! -f "$KUBECONFIG_PATH" ]] && [[ -z "${KUBECONFIG:-}" ]]; then
  echo "❌ Kubeconfig not found at $KUBECONFIG_PATH"
  echo "Run: task kubeconfig"
  exit 1
fi

# Use local kubeconfig if KUBECONFIG env var not set
if [[ -z "${KUBECONFIG:-}" ]]; then
  export KUBECONFIG="$KUBECONFIG_PATH"
fi

# Helper function to check if namespace exists
namespace_exists() {
  kubectl get namespace "$1" &> /dev/null
}

# Helper function to get service info
get_service_info() {
  local service=$1
  local namespace=$2

  if kubectl get svc "$service" -n "$namespace" &> /dev/null; then
    local cluster_ip
    cluster_ip=$(kubectl get svc "$service" -n "$namespace" -o jsonpath='{.spec.clusterIP}' 2> /dev/null || echo "N/A")
    local port
    port=$(kubectl get svc "$service" -n "$namespace" -o jsonpath='{.spec.ports[0].port}' 2> /dev/null || echo "N/A")
    echo "$cluster_ip:$port"
  else
    echo "not-found"
  fi
}

# Helper function to get ingress URL
get_ingress_url() {
  local service=$1
  local namespace=$2

  # Check for IngressRoute (Traefik)
  if kubectl get ingressroute -n "$namespace" 2> /dev/null | grep -q "$service"; then
    local host
    host=$(kubectl get ingressroute -n "$namespace" -o json 2> /dev/null |
      jq -r ".items[] | select(.metadata.name | contains(\"$service\")) | .spec.routes[0].match" |
      grep -oP 'Host\(\`\K[^\`]+' | head -1 || echo "")
    if [[ -n "$host" ]]; then
      echo "http://$host"
      return
    fi
  fi

  # Fallback to expected pattern
  echo "http://$service.$DOMAIN"
}

# Helper function to get pod status
get_pod_status() {
  local app=$1
  local namespace=$2

  if kubectl get pods -n "$namespace" -l "app=$app" &> /dev/null 2>&1; then
    kubectl get pods -n "$namespace" -l "app=$app" -o jsonpath='{.items[0].status.phase}' 2> /dev/null || echo "NotFound"
  else
    echo "NotFound"
  fi
}

# Helper function to get pod ready status
get_pod_ready() {
  local app=$1
  local namespace=$2

  if kubectl get pods -n "$namespace" -l "app=$app" &> /dev/null 2>&1; then
    local ready
    ready=$(kubectl get pods -n "$namespace" -l "app=$app" -o jsonpath='{.items[0].status.containerStatuses[0].ready}' 2> /dev/null || echo "false")
    echo "$ready"
  else
    echo "false"
  fi
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

# Print service section
print_service() {
  local name=$1
  local namespace=$2
  local description=$3
  local check_db=${4:-false}

  local svc_info
  svc_info=$(get_service_info "$name" "$namespace")
  local ingress_url
  ingress_url=$(get_ingress_url "$name" "$namespace")
  local status
  status=$(get_pod_status "$name" "$namespace")
  local ready
  ready=$(get_pod_ready "$name" "$namespace")

  # Status indicator
  local status_icon="⚠"
  local status_color=$YELLOW
  if [[ "$status" == "Running" ]] && [[ "$ready" == "true" ]]; then
    status_icon="✓"
    status_color=$GREEN
  elif [[ "$status" == "NotFound" ]]; then
    status_icon="✗"
    status_color=$RED
  fi

  echo -e "  ${BOLD}┣━ ${name}${RESET} ${DIM}→${RESET} ${GREEN}${svc_info}${RESET} ${status_color}[${status_icon}]${RESET}"
  echo -e "  ┃  ${DIM}Web UI:${RESET}   $ingress_url"
  if [[ "$svc_info" != "not-found" ]]; then
    echo -e "  ┃  ${DIM}Internal:${RESET} ${name}.${namespace}.svc:$(echo "$svc_info" | cut -d: -f2)"
  fi

  if [[ "$check_db" == "true" ]]; then
    # Try to get DB credentials from secret
    local db_user db_pass db_name
    if kubectl get secret "${name}-secret" -n "$namespace" &> /dev/null; then
      db_user=$(kubectl get secret "${name}-secret" -n "$namespace" -o jsonpath='{.data.POSTGRES_USER}' 2> /dev/null | base64 -d || echo "postgres")
      db_pass=$(kubectl get secret "${name}-secret" -n "$namespace" -o jsonpath='{.data.POSTGRES_PASSWORD}' 2> /dev/null | base64 -d || echo "****")
      db_name=$(kubectl get secret "${name}-secret" -n "$namespace" -o jsonpath='{.data.POSTGRES_DB}' 2> /dev/null | base64 -d || echo "mediadb")
      echo -e "  ┃  ${DIM}DB String:${RESET} postgresql://${db_user}:****@${name}.${namespace}.svc:5432/${db_name}"
    fi
  fi

  echo ""
}

# Print last service (with different box character)
print_last_service() {
  local name=$1
  local namespace=$2
  local description=$3

  local svc_info
  svc_info=$(get_service_info "$name" "$namespace")
  local ingress_url
  ingress_url=$(get_ingress_url "$name" "$namespace")
  local status
  status=$(get_pod_status "$name" "$namespace")
  local ready
  ready=$(get_pod_ready "$name" "$namespace")

  # Status indicator
  local status_icon="⚠"
  local status_color=$YELLOW
  if [[ "$status" == "Running" ]] && [[ "$ready" == "true" ]]; then
    status_icon="✓"
    status_color=$GREEN
  elif [[ "$status" == "NotFound" ]]; then
    status_icon="✗"
    status_color=$RED
  fi

  echo -e "  ${BOLD}┗━ ${name}${RESET} ${DIM}→${RESET} ${GREEN}${svc_info}${RESET} ${status_color}[${status_icon}]${RESET}"
  echo -e "     ${DIM}Web UI:${RESET}   $ingress_url"
  if [[ "$svc_info" != "not-found" ]]; then
    echo -e "     ${DIM}Internal:${RESET} ${name}.${namespace}.svc:$(echo "$svc_info" | cut -d: -f2)"
  fi
  echo ""
}

# Main dashboard
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

  echo -e "${MAGENTA}▸ INDEXER & MANAGEMENT${RESET}"
  print_service "prowlarr" "$NAMESPACE" "Indexer Manager"

  echo -e "${MAGENTA}▸ MEDIA AUTOMATION${RESET}"
  print_service "sonarr" "$NAMESPACE" "TV Shows"
  print_service "radarr" "$NAMESPACE" "Movies"
  print_service "readarr" "$NAMESPACE" "Books"
  print_last_service "overseerr" "$NAMESPACE" "Request Management"

  echo -e "${MAGENTA}▸ MEDIA SERVERS${RESET}"
  print_service "plex" "$NAMESPACE" "Plex Media Server"
  print_service "jellyfin" "$NAMESPACE" "Jellyfin Media Server"

  # Check if tdarr exists
  if kubectl get deployment tdarr -n "$NAMESPACE" &> /dev/null; then
    print_last_service "tdarr" "$NAMESPACE" "Transcoding Service"
  else
    echo -e "  ${DIM}┗━ tdarr (not deployed)${RESET}"
    echo ""
  fi

  echo -e "${MAGENTA}▸ INFRASTRUCTURE${RESET}"
  print_service "postgresql" "$NAMESPACE" "PostgreSQL Database" true

  # Check if homepage exists
  if kubectl get deployment homepage -n "$NAMESPACE" &> /dev/null; then
    print_last_service "homepage" "$NAMESPACE" "Dashboard"
  else
    echo -e "  ${DIM}┗━ homepage (not deployed)${RESET}"
    echo ""
  fi

  echo -e "${MAGENTA}▸ MONITORING${RESET}"
  if kubectl get deployment exportarr -n "$NAMESPACE" &> /dev/null; then
    local exportarr_svc
    exportarr_svc=$(get_service_info "exportarr" "$NAMESPACE")
    echo -e "  ${BOLD}┗━ exportarr${RESET} ${DIM}→${RESET} ${GREEN}${exportarr_svc}${RESET}"
    echo -e "     ${DIM}Metrics:${RESET}  http://exportarr.${NAMESPACE}.svc:9707/metrics"
  else
    echo -e "  ${DIM}┗━ exportarr (not deployed)${RESET}"
  fi
  echo ""

  echo -e "${MAGENTA}▸ STORAGE${RESET}"
  echo -e "  ${DIM}Namespace:${RESET} $NAMESPACE"

  # Get PVC info
  local pvc_count
  pvc_count=$(kubectl get pvc -n "$NAMESPACE" 2> /dev/null | grep -c "Bound" || echo "0")
  local pvc_total
  pvc_total=$(kubectl get pvc -n "$NAMESPACE" 2> /dev/null | tail -n +2 | wc -l | tr -d ' ' || echo "0")

  if [[ "$pvc_total" -gt 0 ]]; then
    echo -e "  ${DIM}PVCs:${RESET}      $pvc_count/$pvc_total Bound"

    # Show storage usage if available
    if kubectl get pvc -n "$NAMESPACE" &> /dev/null; then
      kubectl get pvc -n "$NAMESPACE" -o custom-columns=NAME:.metadata.name,SIZE:.spec.resources.requests.storage,STATUS:.status.phase 2> /dev/null | tail -n +2 | while IFS= read -r line; do
        echo -e "  ${DIM}  • $line${RESET}"
      done
    fi
  else
    echo -e "  ${DIM}PVCs:${RESET}      None"
  fi
  echo ""

  echo -e "${MAGENTA}▸ QUICK COMMANDS${RESET}"
  echo -e "  ${CYAN}pods${RESET}    │ kubectl get pods -n $NAMESPACE"
  echo -e "  ${CYAN}logs${RESET}    │ kubectl logs -n $NAMESPACE <pod> -f"
  echo -e "  ${CYAN}shell${RESET}   │ kubectl exec -n $NAMESPACE -it <pod> -- /bin/bash"
  echo -e "  ${CYAN}restart${RESET} │ kubectl rollout restart deploy/<name> -n $NAMESPACE"
  echo -e "  ${CYAN}events${RESET}  │ kubectl get events -n $NAMESPACE --sort-by='.lastTimestamp'"
  echo ""

  echo -e "${MAGENTA}▸ GETTING STARTED${RESET}"
  echo -e "  ${DIM}Deploy stack:${RESET}     task infra:deploy-arr-stack"
  echo -e "  ${DIM}Port forward:${RESET}     kubectl port-forward -n $NAMESPACE svc/<service> <port>:<port>"
  echo -e "  ${DIM}Access via web:${RESET}   Add to /etc/hosts: <node-ip> <service>.$DOMAIN"
  echo ""

  # Cluster status
  local cluster_status
  if kubectl get nodes &> /dev/null; then
    cluster_status="${GREEN}✓ Cluster is running${RESET}"
  else
    cluster_status="${RED}✗ Cluster is not accessible${RESET}"
  fi

  echo -e "$cluster_status"
  echo ""

  # Pod status table
  echo -e "${MAGENTA}▸ POD STATUS${RESET}"
  if kubectl get pods -n "$NAMESPACE" &> /dev/null 2>&1; then
    kubectl get pods -n "$NAMESPACE" -o wide 2> /dev/null || echo "  No pods found"
  else
    echo "  No pods in namespace $NAMESPACE"
  fi
  echo ""
}

# Run main function
main "$@"
