#!/usr/bin/env bash
# Arr-Stack Deployment Script
# Orchestrates deployment to production via Flux GitOps
#
# Usage:
#   ./deploy.sh                    # Interactive deployment
#   ./deploy.sh --auto-confirm     # Skip confirmation prompts
#   ./deploy.sh --skip-validation  # Skip manifest validation
#   ./deploy.sh --dry-run          # Show what would be deployed

set -euo pipefail

# Color codes
RESET='\033[0m'
BOLD='\033[1m'
GREEN='\033[92m'
YELLOW='\033[93m'
RED='\033[91m'
CYAN='\033[96m'

# Configuration
NAMESPACE="media-prod"
OVERLAY="overlays/prod"
AUTO_CONFIRM="${AUTO_CONFIRM:-false}"
SKIP_VALIDATION="${SKIP_VALIDATION:-false}"
DRY_RUN="${DRY_RUN:-false}"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --auto-confirm | -y)
      AUTO_CONFIRM=true
      shift
      ;;
    --skip-validation)
      SKIP_VALIDATION=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --help | -h)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --auto-confirm, -y     Skip confirmation prompts"
      echo "  --skip-validation      Skip manifest validation"
      echo "  --dry-run              Show what would be deployed without making changes"
      echo "  --help, -h             Show this help message"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      echo "Use --help for usage information"
      exit 1
      ;;
  esac
done

# Helper functions
log_info() {
  echo -e "${CYAN}ℹ${RESET} $1"
}

log_success() {
  echo -e "${GREEN}✓${RESET} $1"
}

log_warning() {
  echo -e "${YELLOW}⚠${RESET} $1"
}

log_error() {
  echo -e "${RED}✗${RESET} $1"
}

log_step() {
  echo -e "\n${BOLD}${CYAN}▸ $1${RESET}\n"
}

confirm() {
  if [[ "$AUTO_CONFIRM" == "true" ]]; then
    return 0
  fi

  local prompt="$1"
  read -p "$(echo -e "${YELLOW}?${RESET} $prompt (y/N): ")" -n 1 -r
  echo
  [[ $REPLY =~ ^[Yy]$ ]]
}

# Main deployment workflow
main() {
  echo -e "${BOLD}${CYAN}"
  cat << 'EOF'
╔═══════════════════════════════════════╗
║   Arr-Stack Deployment Orchestrator   ║
╚═══════════════════════════════════════╝
EOF
  echo -e "${RESET}"

  log_info "Target Namespace: ${BOLD}$NAMESPACE${RESET}"
  log_info "Overlay: ${BOLD}$OVERLAY${RESET}"
  log_info "Dry Run: ${BOLD}$DRY_RUN${RESET}"
  echo ""

  # Step 1: Check git status
  log_step "1/7: Checking Git Status"

  if [[ -n $(git status --porcelain) ]]; then
    log_info "Uncommitted changes detected:"
    git status --short
    echo ""

    if ! confirm "Continue with uncommitted changes?"; then
      log_error "Deployment cancelled"
      exit 1
    fi
  else
    log_success "Working directory is clean"
  fi

  # Step 2: Validate manifests
  if [[ "$SKIP_VALIDATION" != "true" ]]; then
    log_step "2/7: Validating Manifests"

    log_info "Running kustomize build..."
    if kustomize build "$OVERLAY" > /tmp/arr-stack-manifests.yaml; then
      log_success "Kustomize build successful"
    else
      log_error "Kustomize build failed"
      exit 1
    fi

    log_info "Running kubectl dry-run..."
    if kubectl apply --dry-run=client -f /tmp/arr-stack-manifests.yaml > /dev/null 2>&1; then
      log_success "Kubectl validation passed"
    else
      log_error "Kubectl validation failed"
      kubectl apply --dry-run=client -f /tmp/arr-stack-manifests.yaml
      exit 1
    fi

    rm /tmp/arr-stack-manifests.yaml
  else
    log_warning "Skipping validation (--skip-validation)"
  fi

  # Step 3: Show what will be deployed
  log_step "3/7: Deployment Preview"

  log_info "Resources to be deployed:"
  kustomize build "$OVERLAY" | grep -E "^kind:|^  name:" | paste - - | sed 's/kind: /  • /' | sed 's/  name: / → /'
  echo ""

  if [[ "$DRY_RUN" == "true" ]]; then
    log_warning "Dry run mode - stopping before git operations"
    log_success "Dry run complete!"
    exit 0
  fi

  # Step 4: Confirm deployment
  if ! confirm "Deploy arr-stack to production?"; then
    log_error "Deployment cancelled"
    exit 1
  fi

  # Step 5: Git operations
  log_step "4/7: Git Operations"

  if [[ -n $(git status --porcelain) ]]; then
    log_info "Staging changes..."
    git add applications/arr-stack/

    log_info "Creating commit..."
    git commit -m "deploy: Update arr-stack production deployment

Deployed via deploy.sh script

🤖 Generated with Claude Code
Co-Authored-By: Claude <noreply@anthropic.com>"

    log_success "Changes committed"
  else
    log_warning "No changes to commit"
  fi

  # Step 6: Push to GitHub
  log_step "5/7: Pushing to GitHub"

  log_info "Pushing to origin/main..."
  if git push origin main; then
    log_success "Pushed to GitHub"
  else
    log_error "Failed to push to GitHub"
    exit 1
  fi

  # Step 7: Trigger Flux reconciliation
  log_step "6/7: Flux Reconciliation"

  log_info "Reconciling Flux source..."
  flux reconcile source git flux-system

  log_info "Reconciling Flux kustomization..."
  flux reconcile kustomization flux-system

  log_success "Flux reconciliation triggered"

  # Step 8: Wait and verify
  log_step "7/7: Verifying Deployment"

  log_info "Waiting for pods to be ready (timeout: 5m)..."
  if kubectl wait --for=condition=ready pod \
    -l app.kubernetes.io/part-of=arr-stack \
    -n "$NAMESPACE" \
    --timeout=300s 2> /dev/null; then
    log_success "All pods are ready!"
  else
    log_warning "Some pods may not be ready yet - check status manually"
  fi

  # Success
  echo ""
  echo -e "${BOLD}${GREEN}✓ Deployment Complete!${RESET}"
  echo ""
  log_info "Check deployment status:"
  echo "  • Dashboard: ${CYAN}./dashboard.sh${RESET}"
  echo "  • Pods: ${CYAN}kubectl get pods -n $NAMESPACE${RESET}"
  echo "  • Flux: ${CYAN}flux get kustomizations${RESET}"
  echo ""
}

# Run main function
main "$@"
