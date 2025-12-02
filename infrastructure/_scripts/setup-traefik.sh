#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  Setup Traefik Infrastructure                                                ║
# ║  Ingress Controller, Metrics Server, and Test Services                       ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# Source shared library
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../../scripts/lib/common.sh"

# ══════════════════════════════════════════════════════════════════════════════
# Banner
# ══════════════════════════════════════════════════════════════════════════════
print_banner "
████████╗██████╗  █████╗ ███████╗███████╗██╗██╗  ██╗
╚══██╔══╝██╔══██╗██╔══██╗██╔════╝██╔════╝██║██║ ██╔╝
   ██║   ██████╔╝███████║█████╗  █████╗  ██║█████╔╝
   ██║   ██╔══██╗██╔══██║██╔══╝  ██╔══╝  ██║██╔═██╗
   ██║   ██║  ██║██║  ██║███████╗██║     ██║██║  ██╗
   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═╝     ╚═╝╚═╝  ╚═╝
                  ${ICON_LIGHTNING} Ingress Controller ${ICON_LIGHTNING}
" "$CYAN"

print_section "COMPONENTS TO INSTALL"
echo ""
print_kv "Traefik" "v3 (Ingress Controller)"
print_kv "Metrics Server" "Resource monitoring"
print_kv "whoami" "Test service"
print_kv "Dashboard" "IngressRoutes"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Prerequisites
# ══════════════════════════════════════════════════════════════════════════════
require_cmds kubectl helm || exit 1
require_cluster || exit 1

# ══════════════════════════════════════════════════════════════════════════════
# Step 1: Add Helm Repository
# ══════════════════════════════════════════════════════════════════════════════
log_step "1" "Adding Traefik Helm Repository"

helm_repo_add "traefik" "https://traefik.github.io/charts"
helm repo update
success "Helm repository ready"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 2: Create Namespace
# ══════════════════════════════════════════════════════════════════════════════
log_step "2" "Creating traefik Namespace"

if ! kubectl get namespace traefik &>/dev/null; then
  kubectl create namespace traefik
  kubectl label namespace traefik \
    pod-security.kubernetes.io/enforce=privileged \
    pod-security.kubernetes.io/audit=privileged \
    pod-security.kubernetes.io/warn=privileged
  success "Namespace created with privileged security labels"
else
  warn "Namespace already exists"
fi
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 3: Install Traefik
# ══════════════════════════════════════════════════════════════════════════════
log_step "3" "Installing Traefik via Helm"

TRAEFIK_VALUES="${PROJECT_ROOT}/infrastructure/base/traefik/values.yaml"
if [[ ! -f "$TRAEFIK_VALUES" ]]; then
  # Fallback to old location
  TRAEFIK_VALUES="${PROJECT_ROOT}/kubernetes/traefik-values.yaml"
fi

if helm list -n traefik | grep -q traefik; then
  info "Traefik already installed, upgrading..."
  helm upgrade traefik traefik/traefik \
    --namespace traefik \
    --values "$TRAEFIK_VALUES" \
    2>&1 | grep -v "Warning:" || true
else
  helm install traefik traefik/traefik \
    --namespace traefik \
    --values "$TRAEFIK_VALUES" \
    2>&1 | grep -v "Warning:" || true
fi
success "Traefik installed"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 4: Wait for Traefik
# ══════════════════════════════════════════════════════════════════════════════
log_step "4" "Waiting for Traefik to be Ready"

wait_for_resource "pod -l app.kubernetes.io/name=traefik" "traefik" 90
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 5: Deploy Test Services
# ══════════════════════════════════════════════════════════════════════════════
log_step "5" "Deploying whoami Test Service"

WHOAMI_FILE="${PROJECT_ROOT}/infrastructure/base/traefik/whoami-ingressroute.yaml"
if [[ ! -f "$WHOAMI_FILE" ]]; then
  WHOAMI_FILE="${PROJECT_ROOT}/kubernetes/whoami-ingressroute.yaml"
fi

if [[ -f "$WHOAMI_FILE" ]]; then
  kubectl apply -f "$WHOAMI_FILE"
  success "whoami deployed"
else
  warn "whoami manifest not found, skipping"
fi
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 6: Deploy Dashboard IngressRoute
# ══════════════════════════════════════════════════════════════════════════════
log_step "6" "Deploying Dashboard IngressRoute"

DASHBOARD_FILE="${PROJECT_ROOT}/infrastructure/base/traefik/dashboard-ingressroute.yaml"
if [[ ! -f "$DASHBOARD_FILE" ]]; then
  DASHBOARD_FILE="${PROJECT_ROOT}/kubernetes/dashboard-ingressroute.yaml"
fi

if [[ -f "$DASHBOARD_FILE" ]]; then
  kubectl apply -f "$DASHBOARD_FILE"
  success "Dashboard IngressRoute deployed"
else
  warn "Dashboard manifest not found, skipping"
fi
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 7: Install Metrics Server
# ══════════════════════════════════════════════════════════════════════════════
log_step "7" "Installing Metrics Server"

if kubectl get deployment metrics-server -n kube-system &>/dev/null; then
  warn "Metrics server already installed"
else
  kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

  # Patch for self-signed certs (homelab)
  kubectl patch deployment metrics-server -n kube-system \
    --type='json' \
    -p='[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--kubelet-insecure-tls"}]' 2>/dev/null || true

  success "Metrics server installed"
fi
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 8: Wait for Metrics Server
# ══════════════════════════════════════════════════════════════════════════════
log_step "8" "Waiting for Metrics Server"

wait_for_resource "pod -l k8s-app=metrics-server" "kube-system" 90 || true
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 9: Show Status
# ══════════════════════════════════════════════════════════════════════════════
log_step "9" "Deployment Status"

print_subsection "Traefik Pods:"
kubectl get pods -n traefik
echo ""

print_subsection "Metrics Server:"
kubectl get pods -n kube-system -l k8s-app=metrics-server
echo ""

print_subsection "IngressRoutes:"
kubectl get ingressroute -A
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 10: Test Metrics
# ══════════════════════════════════════════════════════════════════════════════
log_step "10" "Testing Metrics Availability"

info "Waiting for metrics collection..."
sleep 5
kubectl top nodes 2>&1 || warn "Metrics not ready yet (may take 30-60 seconds)"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════
print_summary "success"

print_urls \
  "Traefik Dashboard|http://traefik.${DOMAIN}" \
  "whoami Service|http://whoami.${DOMAIN}" \
  "K8s Dashboard|http://dashboard.${DOMAIN}" \
  "whoami (IP)|http://${TALOS_NODE}/whoami"

print_section "ADD TO /etc/hosts"
echo -e "  ${CYAN}${TALOS_NODE}  traefik.${DOMAIN} whoami.${DOMAIN} dashboard.${DOMAIN}${RESET}"
echo ""

print_section "METRICS COMMANDS"
echo -e "  ${CYAN}kubectl top nodes${RESET}"
echo -e "  ${CYAN}kubectl top pods -A${RESET}"
echo ""

echo -e "${GREEN}${BOLD}${EMOJI_PARTY} Infrastructure setup complete!${RESET}"
echo ""
