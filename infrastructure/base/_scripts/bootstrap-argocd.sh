#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  Bootstrap ArgoCD                                                            ║
# ║  GitOps Controller Installation and Configuration                            ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# Source shared library
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../../scripts/lib/common.sh"

# ══════════════════════════════════════════════════════════════════════════════
# Banner
# ══════════════════════════════════════════════════════════════════════════════
print_banner "
 █████╗ ██████╗  ██████╗  ██████╗  ██████╗██████╗
██╔══██╗██╔══██╗██╔════╝ ██╔═══██╗██╔════╝██╔══██╗
███████║██████╔╝██║  ███╗██║   ██║██║     ██║  ██║
██╔══██║██╔══██╗██║   ██║██║   ██║██║     ██║  ██║
██║  ██║██║  ██║╚██████╔╝╚██████╔╝╚██████╗██████╔╝
╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝  ╚═════╝  ╚═════╝╚═════╝
                    ${ICON_LIGHTNING} GitOps Controller ${ICON_LIGHTNING}
" "$BLUE"

# ══════════════════════════════════════════════════════════════════════════════
# Prerequisites
# ══════════════════════════════════════════════════════════════════════════════
require_cmds kubectl helm || exit 1
require_cluster || exit 1

# ══════════════════════════════════════════════════════════════════════════════
# Step 1: Add Helm Repository
# ══════════════════════════════════════════════════════════════════════════════
log_step "1" "Adding ArgoCD Helm Repository"

helm_repo_add "argo" "https://argoproj.github.io/argo-helm"
info "Updating repositories..."
helm repo update
success "Helm repository ready"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 2: Create Namespace
# ══════════════════════════════════════════════════════════════════════════════
log_step "2" "Creating argocd Namespace"

kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
success "Namespace ready"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 3: Install ArgoCD
# ══════════════════════════════════════════════════════════════════════════════
log_step "3" "Installing ArgoCD via Helm"

helm upgrade --install argocd argo/argo-cd \
  -n argocd \
  -f "${PROJECT_ROOT}/infrastructure/base/argocd/values.yaml" \
  --wait \
  --timeout 5m
success "ArgoCD installed"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 4: Apply IngressRoute
# ══════════════════════════════════════════════════════════════════════════════
log_step "4" "Applying IngressRoute"

if [[ -f "${PROJECT_ROOT}/infrastructure/base/argocd/ingressroute.yaml" ]]; then
  kubectl apply -f "${PROJECT_ROOT}/infrastructure/base/argocd/ingressroute.yaml"
  success "IngressRoute applied"
else
  warn "IngressRoute file not found, skipping"
fi
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 5: Wait for ArgoCD
# ══════════════════════════════════════════════════════════════════════════════
log_step "5" "Waiting for ArgoCD Pods"

wait_for_resource "pod -l app.kubernetes.io/name=argocd-server" "argocd" 300
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Get Admin Password
# ══════════════════════════════════════════════════════════════════════════════
ARGOCD_PASSWORD=$(get_secret "argocd" "argocd-initial-admin-secret" "password")

# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════
print_summary "success"

print_urls \
  "ArgoCD|http://argocd.${DOMAIN}"

print_credentials \
  "ArgoCD|admin:${ARGOCD_PASSWORD}"

print_section "PORT-FORWARD ACCESS"
echo -e "  ${CYAN}kubectl port-forward svc/argocd-server -n argocd 8080:80${RESET}"
echo -e "  ${DIM}Then access: http://localhost:8080${RESET}"
echo ""

print_section "CHANGE PASSWORD"
echo -e "  ${CYAN}argocd login argocd.${DOMAIN}${RESET}"
echo -e "  ${CYAN}argocd account update-password${RESET}"
echo ""

warn "Delete the initial secret after changing password:"
echo -e "  ${CYAN}kubectl -n argocd delete secret argocd-initial-admin-secret${RESET}"
echo ""

echo -e "${GREEN}${BOLD}${EMOJI_PARTY} ArgoCD is ready!${RESET}"
echo ""
