#!/usr/bin/env bash
# Infrastructure Dashboard - Dynamic cluster status display
# Dynamically queries the cluster for all infrastructure services and their status
#
# Usage:
#   ./dashboard.sh              # Show full dashboard
#
# shellcheck disable=SC2016,SC2034

set -euo pipefail

# Get script directory and source common library
DASHBOARD_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${DASHBOARD_SCRIPT_DIR}/.." && pwd)"

# shellcheck source=../scripts/lib/dashboard-common.sh
source "${PROJECT_ROOT}/scripts/lib/dashboard-common.sh"

# ============================================================================
# Infrastructure-specific configuration
# ============================================================================
INFRA_NAMESPACES=("monitoring" "observability" "traefik" "argocd" "registry" "external-secrets" "flux-system")

# ============================================================================
# Print ASCII header
# ============================================================================
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

# ============================================================================
# Fetch all infrastructure namespace data
# ============================================================================
fetch_infra_data() {
  echo -e "${DIM}Loading infrastructure data...${RESET}"

  # Fetch cluster-wide data
  kubectl get nodes -o json > "$CACHE_DIR/nodes.json" 2> /dev/null &
  kubectl get sc -o json > "$CACHE_DIR/storageclasses.json" 2> /dev/null &
  kubectl get pv -o json > "$CACHE_DIR/pvs.json" 2> /dev/null &
  kubectl get pvc -A -o json > "$CACHE_DIR/all-pvcs.json" 2> /dev/null &

  # Fetch per-namespace data
  for ns in "${INFRA_NAMESPACES[@]}"; do
    if namespace_exists "$ns"; then
      kubectl get pods -n "$ns" -o json > "$CACHE_DIR/${ns}-pods.json" 2> /dev/null &
      kubectl get svc -n "$ns" -o json > "$CACHE_DIR/${ns}-services.json" 2> /dev/null &
      kubectl get deployments -n "$ns" -o json > "$CACHE_DIR/${ns}-deployments.json" 2> /dev/null &
      kubectl get pvc -n "$ns" -o json > "$CACHE_DIR/${ns}-pvcs.json" 2> /dev/null &
      kubectl get secrets -n "$ns" -o json > "$CACHE_DIR/${ns}-secrets.json" 2> /dev/null &
    fi
  done

  wait

  # Clear the loading message
  echo -e "\033[1A\033[2K"
}

# ============================================================================
# Infrastructure credential helpers
# ============================================================================

# Get secret data (base64 decoded)
get_infra_secret() {
  local namespace=$1
  local secret_name=$2
  local key=$3
  local value
  value=$(jq -r ".items[] | select(.metadata.name == \"$secret_name\") | .data[\"$key\"] // empty" "$CACHE_DIR/${namespace}-secrets.json" 2> /dev/null)
  if [[ -n "$value" ]]; then
    echo "$value" | base64 -d 2> /dev/null
  fi
}

# Get credentials for infrastructure services
get_infra_credentials() {
  local service=$1
  local namespace=$2

  case "$service" in
    grafana)
      # Grafana creds from kube-prometheus-stack
      local pass
      pass=$(get_infra_secret "$namespace" "kube-prometheus-stack-grafana" "admin-password")
      if [[ -n "$pass" ]]; then
        echo "admin:${pass}"
      fi
      ;;
    argocd-server)
      # ArgoCD initial admin password
      local pass
      pass=$(get_infra_secret "$namespace" "argocd-initial-admin-secret" "password")
      if [[ -n "$pass" ]]; then
        echo "admin:${pass}"
      fi
      ;;
    graylog)
      # Graylog default credentials (from helm values)
      echo "admin:admin"
      ;;
    nexus)
      # Nexus admin password is generated on first startup
      echo "admin:(kubectl exec -n registry deploy/nexus -- cat /nexus-data/admin.password)"
      ;;
    opensearch)
      local pass
      pass=$(get_infra_secret "$namespace" "opensearch-admin-credentials" "password")
      if [[ -n "$pass" ]]; then
        echo "admin:${pass}"
      fi
      ;;
    mongodb)
      local user pass
      user=$(get_infra_secret "$namespace" "mongodb-secret" "MONGO_INITDB_ROOT_USERNAME")
      pass=$(get_infra_secret "$namespace" "mongodb-secret" "MONGO_INITDB_ROOT_PASSWORD")
      if [[ -n "$user" ]] && [[ -n "$pass" ]]; then
        echo "${user}:${pass}"
      fi
      ;;
    *)
      # No credentials known
      ;;
  esac
}

# Get volume mounts for a deployment by label
get_infra_volume_mounts() {
  local namespace=$1
  local label_key=$2
  local label_value=$3

  # Find deployment name by label first
  local deploy_name
  deploy_name=$(jq -r ".items[] | select(.spec.selector.matchLabels[\"$label_key\"] == \"$label_value\" or .metadata.labels[\"$label_key\"] == \"$label_value\") | .metadata.name" "$CACHE_DIR/${namespace}-deployments.json" 2> /dev/null | head -1)

  if [[ -n "$deploy_name" ]]; then
    jq -r ".items[] | select(.metadata.name == \"$deploy_name\") | .spec.template.spec.volumes[]? | select(.persistentVolumeClaim != null) | .name + \":\" + .persistentVolumeClaim.claimName" "$CACHE_DIR/${namespace}-deployments.json" 2> /dev/null
  fi
}

# Get PVC info from namespace cache
get_infra_pvc_info() {
  local namespace=$1
  local pvc_name=$2
  jq -r ".items[] | select(.metadata.name == \"$pvc_name\") | .status.phase + \"|\" + .spec.resources.requests.storage + \"|\" + (.spec.storageClassName // \"default\")" "$CACHE_DIR/${namespace}-pvcs.json" 2> /dev/null
}

# Print volume mount with status
print_infra_volume_mount() {
  local namespace=$1
  local pvc_name=$2
  local indent=$3

  local pvc_info
  pvc_info=$(get_infra_pvc_info "$namespace" "$pvc_name")

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

  # Shorten storage class names
  local sc_short="$sc"
  case "$sc" in
    fatboy-nfs-appdata) sc_short="nfs:appdata" ;;
    truenas-nfs) sc_short="truenas" ;;
    synology-nfs) sc_short="synology" ;;
    local-path) sc_short="local" ;;
  esac

  echo -e "${indent}${status_color}${status_icon}${RESET} ${DIM}${pvc_name}${RESET} ${BLUE}(${capacity})${RESET} ${DIM}[${sc_short}]${RESET}"
}

# ============================================================================
# Print infrastructure service
# ============================================================================
print_infra_service() {
  local name=$1
  local namespace=$2
  local label_key=$3
  local label_value=$4
  local url=$5
  local is_last=${6:-false}

  local status ready
  status=$(jq -r ".items[] | select(.metadata.labels[\"$label_key\"] == \"$label_value\") | .status.phase" "$CACHE_DIR/${namespace}-pods.json" 2> /dev/null | head -1)
  ready=$(jq -r ".items[] | select(.metadata.labels[\"$label_key\"] == \"$label_value\") | .status.containerStatuses[0].ready // false" "$CACHE_DIR/${namespace}-pods.json" 2> /dev/null | head -1)

  # Handle missing data
  [[ -z "$status" ]] && status="NotFound"

  # Get credentials for this service
  local creds creds_display=""
  creds=$(get_infra_credentials "$name" "$namespace")
  if [[ -n "$creds" ]]; then
    creds_display="${YELLOW}${creds}${RESET}"
  fi

  print_service_line "$name" "$status" "$ready" "$url" "$is_last" "$creds_display"

  # Tree continuation character
  local cont="┃"
  [[ "$is_last" == "true" ]] && cont=" "

  # Get and print volume mounts
  local volumes
  volumes=$(get_infra_volume_mounts "$namespace" "$label_key" "$label_value")
  if [[ -n "$volumes" ]]; then
    while IFS=: read -r vol_name pvc_name; do
      if [[ -n "$pvc_name" ]]; then
        print_infra_volume_mount "$namespace" "$pvc_name" "  ${cont}    "
      fi
    done <<< "$volumes"
  fi
}

# ============================================================================
# Print storage section
# ============================================================================
print_storage_section() {
  print_section "STORAGE"
  echo ""

  # Storage Classes
  echo -e "  ${BOLD}Storage Classes:${RESET}"
  if [[ -f "$CACHE_DIR/storageclasses.json" ]]; then
    jq -r '.items[] | .metadata.name + "|" + .provisioner + "|" + (if .metadata.annotations["storageclass.kubernetes.io/is-default-class"] == "true" then "default" else "" end)' "$CACHE_DIR/storageclasses.json" 2> /dev/null | while IFS='|' read -r name provisioner default; do
      local default_marker=""
      [[ "$default" == "default" ]] && default_marker=" ${GREEN}(default)${RESET}"
      echo -e "    ${DIM}•${RESET} ${name}${default_marker} ${DIM}→ ${provisioner}${RESET}"
    done
  fi
  echo ""

  # PVCs by namespace
  echo -e "  ${BOLD}PersistentVolumeClaims:${RESET}"
  if [[ -f "$CACHE_DIR/all-pvcs.json" ]]; then
    local pvc_namespaces
    pvc_namespaces=$(jq -r '[.items[].metadata.namespace] | unique | .[]' "$CACHE_DIR/all-pvcs.json" 2> /dev/null | sort)

    if [[ -n "$pvc_namespaces" ]]; then
      for ns in $pvc_namespaces; do
        local pvc_count
        pvc_count=$(jq "[.items[] | select(.metadata.namespace == \"$ns\")] | length" "$CACHE_DIR/all-pvcs.json" 2> /dev/null)
        local bound_count
        bound_count=$(jq "[.items[] | select(.metadata.namespace == \"$ns\" and .status.phase == \"Bound\")] | length" "$CACHE_DIR/all-pvcs.json" 2> /dev/null)

        local status_color=$GREEN
        [[ "$bound_count" != "$pvc_count" ]] && status_color=$YELLOW

        echo -e "    ${CYAN}${ns}:${RESET} ${status_color}${bound_count}/${pvc_count} Bound${RESET}"
      done
    else
      echo -e "    ${DIM}No PVCs found${RESET}"
    fi
  fi
  echo ""
}

# ============================================================================
# Print Flux status
# ============================================================================
print_flux_status() {
  print_section "GITOPS (FLUX)"

  if ! command -v flux &> /dev/null; then
    echo -e "  ${DIM}flux CLI not installed${RESET}"
    echo ""
    return
  fi

  local flux_suspended flux_ready
  # Flux output columns: NAME, REVISION, SUSPENDED, READY, MESSAGE
  flux_suspended=$(flux get kustomization flux-system 2> /dev/null | tail -n 1 | awk '{print $3}')
  flux_ready=$(flux get kustomization flux-system 2> /dev/null | tail -n 1 | awk '{print $4}')

  if [[ "$flux_ready" == "True" ]]; then
    echo -e "  ${GREEN}✓${RESET} Flux is ready and reconciling"
  elif [[ "$flux_suspended" == "True" ]]; then
    echo -e "  ${YELLOW}⚠${RESET} Flux is suspended"
  elif [[ -n "$flux_ready" ]]; then
    echo -e "  ${YELLOW}⚠${RESET} Flux is not ready (status: $flux_ready)"
  else
    echo -e "  ${RED}✗${RESET} Flux status unknown or not installed"
  fi
  echo ""

  echo -e "  ${DIM}Kustomizations:${RESET}"
  # Flux output columns: NAME, REVISION, SUSPENDED, READY, MESSAGE
  flux get kustomization 2> /dev/null | tail -n +2 | while IFS= read -r line; do
    local name ready
    name=$(echo "$line" | awk '{print $1}')
    ready=$(echo "$line" | awk '{print $4}')
    local status_icon="✓"
    local status_color=$GREEN
    if [[ "$ready" != "True" ]]; then
      status_icon="⚠"
      status_color=$YELLOW
    fi
    echo -e "    ${status_color}${status_icon}${RESET} ${name}"
  done
  echo ""
}

# ============================================================================
# Print service URLs section
# ============================================================================
print_service_urls() {
  print_section "SERVICE URLS (via Traefik)"
  echo -e "  ${DIM}Requires /etc/hosts entries for *.${DOMAIN}${RESET}"
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

  echo -e "  ${BOLD}Artifact Repository:${RESET}"
  echo -e "    Nexus UI:      http://nexus.$DOMAIN"
  echo -e "    Docker:        http://registry.$DOMAIN"
  echo -e "    Docker Proxy:  http://docker-proxy.$DOMAIN"
  echo -e "    npm:           http://npm.$DOMAIN"
  echo ""
}

# ============================================================================
# Print credentials section
# ============================================================================
print_credentials() {
  print_section "CREDENTIALS (user:password)"
  local has_creds=false

  # Grafana
  local grafana_creds
  grafana_creds=$(get_infra_credentials "grafana" "monitoring")
  if [[ -n "$grafana_creds" ]]; then
    printf "  ${CYAN}%-14s${RESET} │ ${YELLOW}%s${RESET}\n" "Grafana" "$grafana_creds"
    has_creds=true
  else
    printf "  ${CYAN}%-14s${RESET} │ ${DIM}admin:prom-operator (default)${RESET}\n" "Grafana"
    has_creds=true
  fi

  # ArgoCD
  local argocd_creds
  argocd_creds=$(get_infra_credentials "argocd-server" "argocd")
  if [[ -n "$argocd_creds" ]]; then
    printf "  ${CYAN}%-14s${RESET} │ ${YELLOW}%s${RESET}\n" "ArgoCD" "$argocd_creds"
    has_creds=true
  else
    printf "  ${CYAN}%-14s${RESET} │ ${DIM}(run: kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d)${RESET}\n" "ArgoCD"
    has_creds=true
  fi

  # Graylog
  printf "  ${CYAN}%-14s${RESET} │ ${YELLOW}admin:admin${RESET}\n" "Graylog"
  has_creds=true

  # OpenSearch
  local opensearch_creds
  opensearch_creds=$(get_infra_credentials "opensearch" "observability")
  if [[ -n "$opensearch_creds" ]]; then
    printf "  ${CYAN}%-14s${RESET} │ ${YELLOW}%s${RESET}\n" "OpenSearch" "$opensearch_creds"
    has_creds=true
  fi

  # MongoDB
  local mongodb_creds
  mongodb_creds=$(get_infra_credentials "mongodb" "observability")
  if [[ -n "$mongodb_creds" ]]; then
    printf "  ${CYAN}%-14s${RESET} │ ${YELLOW}%s${RESET}\n" "MongoDB" "$mongodb_creds"
    has_creds=true
  fi

  # Nexus
  printf "  ${CYAN}%-14s${RESET} │ ${DIM}admin:(kubectl exec -n registry deploy/nexus -- cat /nexus-data/admin.password)${RESET}\n" "Nexus"
  has_creds=true

  if [[ "$has_creds" == "false" ]]; then
    echo -e "  ${DIM}No credentials found in secrets${RESET}"
  fi
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

  # Fetch all infrastructure data
  fetch_infra_data

  # Cluster status
  print_cluster_status
  echo ""

  # Monitoring Stack
  print_section "MONITORING"
  print_infra_service "prometheus" "monitoring" "app.kubernetes.io/name" "prometheus" "http://prometheus.$DOMAIN"
  print_infra_service "grafana" "monitoring" "app.kubernetes.io/name" "grafana" "http://grafana.$DOMAIN"
  print_infra_service "alertmanager" "monitoring" "app.kubernetes.io/name" "alertmanager" "http://alertmanager.$DOMAIN" true
  echo ""

  # Observability Stack
  print_section "OBSERVABILITY"
  print_infra_service "graylog" "observability" "app.kubernetes.io/name" "graylog" "http://graylog.$DOMAIN"
  print_infra_service "opensearch" "observability" "app.kubernetes.io/name" "opensearch" ""
  print_infra_service "mongodb" "observability" "app.kubernetes.io/name" "mongodb" ""
  print_infra_service "fluent-bit" "observability" "app.kubernetes.io/name" "fluent-bit" "" true
  echo ""

  # Networking
  print_section "NETWORKING"
  print_infra_service "traefik" "traefik" "app.kubernetes.io/name" "traefik" "http://traefik.$DOMAIN/dashboard/"
  print_infra_service "argocd-server" "argocd" "app.kubernetes.io/name" "argocd-server" "http://argocd.$DOMAIN" true
  echo ""

  # Registry - detect if Nexus or old docker-registry
  print_section "ARTIFACT REPOSITORY"
  local nexus_status
  nexus_status=$(jq -r '.items[] | select(.metadata.labels["app"] == "nexus") | .status.phase' "$CACHE_DIR/registry-pods.json" 2> /dev/null | head -1)

  if [[ -n "$nexus_status" ]]; then
    # Nexus is deployed
    print_infra_service "nexus" "registry" "app" "nexus" "http://nexus.$DOMAIN"
    echo -e "  ┣━ ${DIM}Docker Registry:${RESET}  ${CYAN}http://registry.$DOMAIN${RESET}"
    echo -e "  ┣━ ${DIM}Docker Proxy:${RESET}     ${CYAN}http://docker-proxy.$DOMAIN${RESET}"
    echo -e "  ┗━ ${DIM}npm Registry:${RESET}     ${CYAN}http://npm.$DOMAIN${RESET}"
  else
    # Old docker-registry still in use
    print_infra_service "docker-registry" "registry" "app" "docker-registry" "http://registry.$DOMAIN" true
    echo -e "  ${DIM}    (Upgrade to Nexus: kubectl apply -f infrastructure/base/registry/deployment.yaml)${RESET}"
  fi
  echo ""

  # External Secrets
  print_section "SECRETS MANAGEMENT"
  print_infra_service "external-secrets" "external-secrets" "app.kubernetes.io/name" "external-secrets" "" true
  echo ""

  # Storage
  print_storage_section

  # Flux Status
  print_flux_status

  # Quick Commands
  print_section "QUICK COMMANDS"
  echo -e "  ${CYAN}deploy${RESET}      │ ./scripts/deploy-stack.sh"
  echo -e "  ${CYAN}tilt${RESET}        │ cd infrastructure && tilt up"
  echo -e "  ${CYAN}flux-status${RESET} │ flux get all"
  echo -e "  ${CYAN}pv-status${RESET}   │ kubectl get pv,pvc -A"
  echo -e "  ${CYAN}logs${RESET}        │ kubectl logs -n <ns> <pod> -f"
  echo ""

  # Service URLs
  print_service_urls

  # Credentials
  print_credentials
}

# Run main function
main "$@"
