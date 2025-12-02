#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  Deploy Complete Homelab Stack                                               ║
# ║  Infrastructure & Applications Deployment for Talos Kubernetes               ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# Source shared library (relative to infrastructure/base/_scripts/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../../scripts/lib/common.sh"

# ══════════════════════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════════════════════
DEPLOY_MONITORING="${DEPLOY_MONITORING:-true}"
DEPLOY_OBSERVABILITY="${DEPLOY_OBSERVABILITY:-true}"
DEPLOY_APPS="${DEPLOY_APPS:-false}"
ENVIRONMENT="${ENVIRONMENT:-production}"
DRY_RUN="${DRY_RUN:-false}"

# ══════════════════════════════════════════════════════════════════════════════
# Banner
# ══════════════════════════════════════════════════════════════════════════════
print_banner "
██████╗ ███████╗██████╗ ██╗      ██████╗ ██╗   ██╗    ███████╗████████╗ █████╗  ██████╗██╗  ██╗
██╔══██╗██╔════╝██╔══██╗██║     ██╔═══██╗╚██╗ ██╔╝    ██╔════╝╚══██╔══╝██╔══██╗██╔════╝██║ ██╔╝
██║  ██║█████╗  ██████╔╝██║     ██║   ██║ ╚████╔╝     ███████╗   ██║   ███████║██║     █████╔╝
██║  ██║██╔══╝  ██╔═══╝ ██║     ██║   ██║  ╚██╔╝      ╚════██║   ██║   ██╔══██║██║     ██╔═██╗
██████╔╝███████╗██║     ███████╗╚██████╔╝   ██║       ███████║   ██║   ██║  ██║╚██████╗██║  ██╗
╚═════╝ ╚══════╝╚═╝     ╚══════╝ ╚═════╝    ╚═╝       ╚══════╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝
                          ${ICON_LIGHTNING} Homelab Infrastructure Deployment ${ICON_LIGHTNING}
" "$CYAN"

# ══════════════════════════════════════════════════════════════════════════════
# Configuration Summary
# ══════════════════════════════════════════════════════════════════════════════
print_section "DEPLOYMENT CONFIGURATION"
echo ""
print_kv "Environment" "$ENVIRONMENT"
print_kv "Monitoring" "$DEPLOY_MONITORING"
print_kv "Observability" "$DEPLOY_OBSERVABILITY"
print_kv "Apps" "$DEPLOY_APPS"
print_kv "Dry Run" "$DRY_RUN"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 1: Verify Cluster Health
# ══════════════════════════════════════════════════════════════════════════════
log_step "1" "Verifying Cluster Health"

require_cmds kubectl helm || exit 1
require_cluster || exit 1

success "Cluster is accessible"
kubectl get nodes
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 2: Deploy Namespaces
# ══════════════════════════════════════════════════════════════════════════════
log_step "2" "Deploying Namespaces"

info "Applying namespaces..."
if [[ "$DRY_RUN" == "true" ]]; then
  kubectl apply -k "$PROJECT_ROOT/infrastructure/base/namespaces/" --dry-run=client
else
  kubectl apply -k "$PROJECT_ROOT/infrastructure/base/namespaces/"
fi

log_note "Waiting for namespaces to be ready..."
sleep 5
kubectl get namespaces | grep -E "NAME|media|monitoring|observability"
success "Namespaces deployed"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 3: Deploy Storage
# ══════════════════════════════════════════════════════════════════════════════
log_step "3" "Deploying Storage"

info "Applying storage provisioners..."
if [[ "$DRY_RUN" == "true" ]]; then
  kubectl apply -k "$PROJECT_ROOT/infrastructure/base/storage/" --dry-run=client
else
  kubectl apply -k "$PROJECT_ROOT/infrastructure/base/storage/"
fi

wait_for_resource "pod -l app=local-path-provisioner" "local-path-storage" 120 || true

print_subsection "Available Storage Classes:"
kubectl get storageclass
success "Storage deployed"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 4: Verify Traefik
# ══════════════════════════════════════════════════════════════════════════════
log_step "4" "Verifying Traefik"

if kubectl get namespace traefik &>/dev/null; then
  success "Traefik namespace exists"
  kubectl get pods -n traefik
  echo ""

  if kubectl get ingressroute -n default whoami &>/dev/null; then
    success "Traefik IngressRoutes working"
  fi
else
  warn "Traefik not found"
  log_note "Run: ${SCRIPT_DIR}/setup-traefik.sh"
fi
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 5: Deploy Monitoring (optional)
# ══════════════════════════════════════════════════════════════════════════════
if [[ "$DEPLOY_MONITORING" == "true" ]]; then
  log_step "5" "Deploying Monitoring Stack"

  warn "This requires Helm and will install:"
  log_note "- Prometheus Operator"
  log_note "- Prometheus (50Gi storage)"
  log_note "- Grafana (10Gi storage)"
  log_note "- Alertmanager (10Gi storage)"
  log_note "- Various exporters and service monitors"
  echo ""

  if confirm "Continue with monitoring deployment?"; then
    kubectl apply -f "$PROJECT_ROOT/infrastructure/base/monitoring/kube-prometheus-stack/namespace.yaml"

    info "Monitoring stack requires Helm"
    log_note "To deploy manually:"
    log_note "  1. helm repo add prometheus-community https://prometheus-community.github.io/helm-charts"
    log_note "  2. helm repo update"
    log_note "  3. helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack -n monitoring --create-namespace -f infrastructure/base/monitoring/kube-prometheus-stack/values.yaml"
    echo ""
    warn "Skipping for now (deploy via Helm manually or FluxCD later)"
  else
    warn "Skipping monitoring deployment"
  fi
  echo ""
fi

# ══════════════════════════════════════════════════════════════════════════════
# Step 6: Deploy Observability Stack (optional)
# ══════════════════════════════════════════════════════════════════════════════
if [[ "$DEPLOY_OBSERVABILITY" == "true" ]]; then
  log_step "6" "Deploying Observability Stack"

  warn "This will install the complete observability stack:"
  log_note "- MongoDB (20Gi storage)"
  log_note "- OpenSearch (30Gi storage)"
  log_note "- Graylog (20Gi storage)"
  log_note "- Fluent Bit (log collector)"
  echo ""

  if confirm "Continue with observability deployment?"; then
    bash "${SCRIPT_DIR}/deploy-observability.sh"
    success "Observability stack deployed"
  else
    warn "Skipping observability deployment"
  fi
  echo ""
fi

# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════
print_summary "success"

print_section "CLUSTER STATUS"
echo ""

print_subsection "Namespaces:"
kubectl get namespaces | grep -E "NAME|media|monitoring|traefik|local-path"
echo ""

print_subsection "Storage Classes:"
kubectl get storageclass
echo ""

print_subsection "PersistentVolumes:"
kubectl get pv 2>/dev/null || echo "  (none yet)"
echo ""

# URLs
print_urls \
  "Traefik|http://traefik.${DOMAIN}" \
  "Whoami|http://whoami.${DOMAIN}"

if [[ "$DEPLOY_MONITORING" == "true" ]] || kubectl get namespace monitoring &>/dev/null 2>&1; then
  print_urls \
    "Grafana|http://grafana.${DOMAIN}" \
    "Prometheus|http://prometheus.${DOMAIN}" \
    "Alertmanager|http://alertmanager.${DOMAIN}"
fi

if [[ "$DEPLOY_OBSERVABILITY" == "true" ]] || kubectl get namespace observability &>/dev/null 2>&1; then
  print_urls \
    "Graylog|http://graylog.${DOMAIN}"
fi

log_note "Add to /etc/hosts: ${TALOS_NODE} *.${DOMAIN}"
echo ""

if [[ "$DEPLOY_APPS" == "true" ]]; then
  print_section "APPLICATION URLS (when deployed)"
  print_urls \
    "Prowlarr|http://prowlarr.${DOMAIN}" \
    "Sonarr|http://sonarr.${DOMAIN}" \
    "Radarr|http://radarr.${DOMAIN}" \
    "Plex|http://plex.${DOMAIN}" \
    "Jellyfin|http://jellyfin.${DOMAIN}"
fi

# Next Steps
print_next_steps \
  "${BLUE}Configure NFS Storage:${RESET} Update NFS server IP in infrastructure/base/storage/nfs-storageclass.yaml" \
  "${BLUE}Deploy Applications:${RESET} DEPLOY_APPS=true $0" \
  "${BLUE}Deploy Monitoring:${RESET} See helm commands above" \
  "${BLUE}Setup GitOps:${RESET} See bootstrap/flux/README.md"

echo -e "${GREEN}${BOLD}${EMOJI_PARTY} Infrastructure is ready!${RESET}"
echo ""
