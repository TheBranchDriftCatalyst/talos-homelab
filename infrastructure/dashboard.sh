#!/usr/bin/env bash
# Infrastructure Dashboard - Dynamic cluster status display
# Dynamically queries the cluster for all infrastructure services and their status
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
KUBECONFIG_PATH="${KUBECONFIG:-../.output/kubeconfig}"
DOMAIN="${DOMAIN:-talos00}"

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

# Helper function to get pod status
get_pod_status() {
  local label=$1
  local namespace=$2

  if kubectl get pods -n "$namespace" -l "$label" &> /dev/null 2>&1; then
    kubectl get pods -n "$namespace" -l "$label" -o jsonpath='{.items[0].status.phase}' 2> /dev/null || echo "NotFound"
  else
    echo "NotFound"
  fi
}

# Helper function to get pod ready status
get_pod_ready() {
  local label=$1
  local namespace=$2

  if kubectl get pods -n "$namespace" -l "$label" &> /dev/null 2>&1; then
    local ready
    ready=$(kubectl get pods -n "$namespace" -l "$label" -o jsonpath='{.items[0].status.containerStatuses[0].ready}' 2> /dev/null || echo "false")
    echo "$ready"
  else
    echo "false"
  fi
}

# Print ASCII header
print_header() {
  echo -e "${CYAN}${BOLD}"
  cat << 'EOF'
██╗███╗   ██╗███████╗██████╗  █████╗ ███████╗████████╗██████╗ ██╗   ██╗ ██████╗████████╗██╗   ██╗██████╗ ███████╗
██║████╗  ██║██╔════╝██╔══██╗██╔══██╗██╔════╝╚══██╔══╝██╔══██╗██║   ██║██╔════╝╚══██╔══╝██║   ██║██╔══██╗██╔════╝
██║██╔██╗ ██║█████╗  ██████╔╝███████║███████╗   ██║   ██████╔╝██║   ██║██║        ██║   ██║   ██║██████╔╝█████╗
██║██║╚██╗██║██╔══╝  ██╔══██╗██╔══██║╚════██║   ██║   ██╔══██╗██║   ██║██║        ██║   ██║   ██║██╔══██╗██╔══╝
██║██║ ╚████║██║     ██║  ██║██║  ██║███████║   ██║   ██║  ██║╚██████╔╝╚██████╗   ██║   ╚██████╔╝██║  ██║███████╗
╚═╝╚═╝  ╚═══╝╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝  ╚═════╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝╚══════╝
                                    Platform Infrastructure Stack
EOF
  echo -e "${RESET}"
  echo ""
}

# Print service with status
print_service() {
  local name=$1
  local namespace=$2
  local label=$3
  local url=$4
  local last=${5:-false}

  local status
  status=$(get_pod_status "$label" "$namespace")
  local ready
  ready=$(get_pod_ready "$label" "$namespace")

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

  local prefix="┣━"
  local indent="┃ "
  if [[ "$last" == "true" ]]; then
    prefix="┗━"
    indent="  "
  fi

  echo -e "  ${BOLD}${prefix} ${name}${RESET} ${status_color}[${status_icon}]${RESET}"
  if [[ -n "$url" ]]; then
    echo -e "  ${indent} ${DIM}URL:${RESET} ${CYAN}${url}${RESET}"
  fi
}

# Print storage section
print_storage() {
  echo -e "${MAGENTA}▸ STORAGE${RESET}"
  echo ""

  # Storage Classes
  echo -e "  ${BOLD}Storage Classes:${RESET}"
  kubectl get sc 2> /dev/null | tail -n +2 | while IFS= read -r line; do
    local name
    name=$(echo "$line" | awk '{print $1}')
    local provisioner
    provisioner=$(echo "$line" | awk '{print $2}')
    local default
    default=$(echo "$line" | grep -q "(default)" && echo " ${GREEN}(default)${RESET}" || echo "")
    echo -e "    ${DIM}•${RESET} ${name}${default} ${DIM}→ ${provisioner}${RESET}"
  done
  echo ""

  # PersistentVolumes
  echo -e "  ${BOLD}PersistentVolumes:${RESET}"
  local pv_count
  pv_count=$(kubectl get pv 2> /dev/null | grep -c "Available\|Bound" || echo "0")
  if [[ "$pv_count" -gt 0 ]]; then
    kubectl get pv 2> /dev/null | tail -n +2 | while IFS= read -r line; do
      local name
      name=$(echo "$line" | awk '{print $1}')
      local capacity
      capacity=$(echo "$line" | awk '{print $2}')
      local status
      status=$(echo "$line" | awk '{print $5}')
      local status_color=$GREEN
      [[ "$status" != "Bound" ]] && status_color=$YELLOW
      echo -e "    ${DIM}•${RESET} ${name} ${DIM}(${capacity})${RESET} ${status_color}[${status}]${RESET}"
    done
  else
    echo -e "    ${DIM}No PVs found${RESET}"
  fi
  echo ""

  # PersistentVolumeClaims by namespace
  echo -e "  ${BOLD}PersistentVolumeClaims:${RESET}"
  local pvc_namespaces
  pvc_namespaces=$(kubectl get pvc -A 2> /dev/null | tail -n +2 | awk '{print $1}' | sort -u)
  if [[ -n "$pvc_namespaces" ]]; then
    for ns in $pvc_namespaces; do
      echo -e "    ${CYAN}$ns:${RESET}"
      kubectl get pvc -n "$ns" 2> /dev/null | tail -n +2 | while IFS= read -r line; do
        local name
        name=$(echo "$line" | awk '{print $1}')
        local status
        status=$(echo "$line" | awk '{print $2}')
        local capacity
        capacity=$(echo "$line" | awk '{print $4}')
        local status_color=$GREEN
        [[ "$status" != "Bound" ]] && status_color=$YELLOW
        echo -e "      ${DIM}•${RESET} ${name} ${DIM}(${capacity})${RESET} ${status_color}[${status}]${RESET}"
      done
    done
  else
    echo -e "    ${DIM}No PVCs found${RESET}"
  fi
  echo ""
}

# Main dashboard
main() {
  clear
  print_header

  # Cluster status
  local cluster_status
  if kubectl get nodes &> /dev/null; then
    cluster_status="${GREEN}✓ Cluster is running${RESET}"
  else
    cluster_status="${RED}✗ Cluster is not accessible${RESET}"
  fi
  echo -e "$cluster_status"
  echo ""

  # Monitoring Stack
  echo -e "${MAGENTA}▸ MONITORING${RESET}"
  print_service "prometheus" "monitoring" "app.kubernetes.io/name=prometheus" "http://prometheus.$DOMAIN"
  print_service "grafana" "monitoring" "app.kubernetes.io/name=grafana" "http://grafana.$DOMAIN"
  print_service "alertmanager" "monitoring" "app.kubernetes.io/name=alertmanager" "http://alertmanager.$DOMAIN" true
  echo ""

  # Observability Stack
  echo -e "${MAGENTA}▸ OBSERVABILITY${RESET}"
  print_service "graylog" "observability" "app=graylog" "http://graylog.$DOMAIN"
  print_service "opensearch" "observability" "app=opensearch" ""
  print_service "mongodb" "observability" "app=mongodb" ""
  print_service "fluent-bit" "observability" "app.kubernetes.io/name=fluent-bit" "" true
  echo ""

  # Networking
  echo -e "${MAGENTA}▸ NETWORKING${RESET}"
  print_service "traefik" "traefik" "app.kubernetes.io/name=traefik" "http://traefik.$DOMAIN/dashboard/"
  print_service "argocd-server" "argocd" "app.kubernetes.io/name=argocd-server" "http://argocd.$DOMAIN" true
  echo ""

  # Registry
  echo -e "${MAGENTA}▸ REGISTRY${RESET}"
  print_service "docker-registry" "registry" "app=docker-registry" "http://registry.$DOMAIN" true
  echo ""

  # External Secrets
  echo -e "${MAGENTA}▸ SECRETS MANAGEMENT${RESET}"
  print_service "external-secrets" "external-secrets" "app.kubernetes.io/name=external-secrets" "" true
  echo ""

  # Storage
  print_storage

  # Flux Status
  echo -e "${MAGENTA}▸ GITOPS (FLUX)${RESET}"
  if command -v flux &> /dev/null; then
    local flux_status
    flux_status=$(flux get kustomization flux-system 2> /dev/null | tail -n 1 | awk '{print $2}')
    local flux_ready
    flux_ready=$(flux get kustomization flux-system 2> /dev/null | tail -n 1 | awk '{print $3}')
    if [[ "$flux_ready" == "True" ]]; then
      echo -e "  ${GREEN}✓${RESET} Flux is ready and reconciling"
    elif [[ "$flux_status" == "True" ]]; then
      echo -e "  ${YELLOW}⚠${RESET} Flux is suspended"
    else
      echo -e "  ${RED}✗${RESET} Flux status unknown"
    fi
    echo ""
    echo -e "  ${DIM}Kustomizations:${RESET}"
    flux get kustomization 2> /dev/null | tail -n +2 | while IFS= read -r line; do
      local name
      name=$(echo "$line" | awk '{print $1}')
      local ready
      ready=$(echo "$line" | awk '{print $3}')
      local status_icon="✓"
      local status_color=$GREEN
      if [[ "$ready" != "True" ]]; then
        status_icon="⚠"
        status_color=$YELLOW
      fi
      echo -e "    ${status_color}${status_icon}${RESET} ${name}"
    done
  else
    echo -e "  ${DIM}flux CLI not installed${RESET}"
  fi
  echo ""

  # Quick Commands
  echo -e "${MAGENTA}▸ QUICK COMMANDS${RESET}"
  echo -e "  ${CYAN}deploy${RESET}      │ ./scripts/deploy-stack.sh"
  echo -e "  ${CYAN}tilt${RESET}        │ cd infrastructure && tilt up"
  echo -e "  ${CYAN}flux-status${RESET} │ flux get all"
  echo -e "  ${CYAN}pv-status${RESET}   │ kubectl get pv,pvc -A"
  echo -e "  ${CYAN}logs${RESET}        │ kubectl logs -n <ns> <pod> -f"
  echo ""

  # Service URLs
  echo -e "${MAGENTA}▸ SERVICE URLS (via Traefik)${RESET}"
  echo -e "  ${DIM}Requires /etc/hosts entries for *.$DOMAIN${RESET}"
  echo ""
  echo -e "  ${BOLD}Monitoring:${RESET}"
  echo -e "    Grafana:       http://grafana.$DOMAIN"
  echo -e "    Prometheus:    http://prometheus.$DOMAIN"
  echo -e "    Alertmanager:  http://alertmanager.$DOMAIN"
  echo ""
  echo -e "  ${BOLD}Observability:${RESET}"
  echo -e "    Graylog:       http://graylog.$DOMAIN"
  echo ""
  echo -e "  ${BOLD}GitOps:${RESET}"
  echo -e "    ArgoCD:        http://argocd.$DOMAIN"
  echo ""
  echo -e "  ${BOLD}Registry:${RESET}"
  echo -e "    Docker:        http://registry.$DOMAIN"
  echo ""

  # Credentials
  echo -e "${MAGENTA}▸ DEFAULT CREDENTIALS${RESET}"
  echo -e "  ${DIM}Grafana:${RESET}  admin / prom-operator"
  echo -e "  ${DIM}Graylog:${RESET}  admin / admin"
  echo -e "  ${DIM}ArgoCD:${RESET}   admin / kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d"
  echo ""
}

# Run main function
main "$@"
