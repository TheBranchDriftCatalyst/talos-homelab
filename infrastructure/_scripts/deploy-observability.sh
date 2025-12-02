#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  Deploy Observability Stack                                                  ║
# ║  MongoDB, OpenSearch, Graylog, Fluent Bit + Monitoring                       ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# Source shared library
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../../scripts/lib/common.sh"

# ══════════════════════════════════════════════════════════════════════════════
# Banner
# ══════════════════════════════════════════════════════════════════════════════
print_banner "
 ██████╗ ██████╗ ███████╗███████╗██████╗ ██╗   ██╗ █████╗ ██████╗ ██╗██╗     ██╗████████╗██╗   ██╗
██╔═══██╗██╔══██╗██╔════╝██╔════╝██╔══██╗██║   ██║██╔══██╗██╔══██╗██║██║     ██║╚══██╔══╝╚██╗ ██╔╝
██║   ██║██████╔╝███████╗█████╗  ██████╔╝██║   ██║███████║██████╔╝██║██║     ██║   ██║    ╚████╔╝
██║   ██║██╔══██╗╚════██║██╔══╝  ██╔══██╗╚██╗ ██╔╝██╔══██║██╔══██╗██║██║     ██║   ██║     ╚██╔╝
╚██████╔╝██████╔╝███████║███████╗██║  ██║ ╚████╔╝ ██║  ██║██████╔╝██║███████╗██║   ██║      ██║
 ╚═════╝ ╚═════╝ ╚══════╝╚══════╝╚═╝  ╚═╝  ╚═══╝  ╚═╝  ╚═╝╚═════╝ ╚═╝╚══════╝╚═╝   ╚═╝      ╚═╝
                              ${ICON_LIGHTNING} Logging & Metrics Stack ${ICON_LIGHTNING}
" "$GREEN"

# ══════════════════════════════════════════════════════════════════════════════
# Prerequisites
# ══════════════════════════════════════════════════════════════════════════════
require_cmds kubectl helm || exit 1
require_cluster || exit 1

# ══════════════════════════════════════════════════════════════════════════════
# Step 1: Add Helm Repositories
# ══════════════════════════════════════════════════════════════════════════════
log_step "1" "Adding Helm Repositories"

helm_repo_add "prometheus-community" "https://prometheus-community.github.io/helm-charts"
helm_repo_add "grafana" "https://grafana.github.io/helm-charts"
helm_repo_add "bitnami" "https://charts.bitnami.com/bitnami"
helm_repo_add "opensearch" "https://opensearch-project.github.io/helm-charts"
helm_repo_add "fluent" "https://fluent.github.io/helm-charts"

info "Updating Helm repositories..."
helm repo update
success "Helm repositories ready"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 2: Create Namespaces
# ══════════════════════════════════════════════════════════════════════════════
log_step "2" "Creating Namespaces"

kubectl apply -f "${PROJECT_ROOT}/infrastructure/base/namespaces/monitoring.yaml"
kubectl apply -f "${PROJECT_ROOT}/infrastructure/base/namespaces/observability.yaml"
success "Namespaces created"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 3: Deploy MongoDB
# ══════════════════════════════════════════════════════════════════════════════
log_step "3" "Deploying MongoDB (Graylog backend)"

helm_install "mongodb" "bitnami/mongodb" "observability" \
  "${PROJECT_ROOT}/infrastructure/base/observability/mongodb/values.yaml" \
  "10m"
success "MongoDB deployed"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 4: Deploy OpenSearch
# ══════════════════════════════════════════════════════════════════════════════
log_step "4" "Deploying OpenSearch (Log storage)"

helm_install "opensearch" "opensearch/opensearch" "observability" \
  "${PROJECT_ROOT}/infrastructure/base/observability/opensearch/values.yaml" \
  "10m"
success "OpenSearch deployed"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 5: Deploy Graylog
# ══════════════════════════════════════════════════════════════════════════════
log_step "5" "Deploying Graylog (Log management)"

kubectl apply -f "${PROJECT_ROOT}/infrastructure/base/observability/graylog/deployment.yaml"
success "Graylog deployed"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 6: Deploy kube-prometheus-stack
# ══════════════════════════════════════════════════════════════════════════════
log_step "6" "Deploying kube-prometheus-stack (Prometheus, Grafana, Alertmanager)"

helm_install "kube-prometheus-stack" "prometheus-community/kube-prometheus-stack" "monitoring" \
  "${PROJECT_ROOT}/infrastructure/base/monitoring/kube-prometheus-stack/values.yaml" \
  "10m"
success "Prometheus stack deployed"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 7: Deploy Fluent Bit
# ══════════════════════════════════════════════════════════════════════════════
log_step "7" "Deploying Fluent Bit (Log collector)"

helm_install "fluent-bit" "fluent/fluent-bit" "observability" \
  "${PROJECT_ROOT}/infrastructure/base/observability/fluent-bit/values.yaml" \
  "5m"
success "Fluent Bit deployed"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 8: Apply IngressRoutes
# ══════════════════════════════════════════════════════════════════════════════
log_step "8" "Applying IngressRoutes"

if [[ -f "${PROJECT_ROOT}/infrastructure/base/observability/ingressroutes.yaml" ]]; then
  kubectl apply -f "${PROJECT_ROOT}/infrastructure/base/observability/ingressroutes.yaml"
  success "IngressRoutes applied"
else
  warn "IngressRoutes file not found, skipping"
fi
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════
print_summary "success"

print_urls \
  "Grafana|http://grafana.${DOMAIN}" \
  "Prometheus|http://prometheus.${DOMAIN}" \
  "Alertmanager|http://alertmanager.${DOMAIN}" \
  "Graylog|http://graylog.${DOMAIN}"

print_credentials \
  "Grafana|admin:prom-operator" \
  "Graylog|admin:admin"

print_next_steps \
  "Configure API keys in Exportarr deployments" \
  "Set up Graylog inputs and streams" \
  "Import Grafana dashboards: ${SCRIPT_DIR}/import-grafana-dashboards.sh"

echo -e "${GREEN}${BOLD}${EMOJI_PARTY} Observability stack is ready!${RESET}"
echo ""
