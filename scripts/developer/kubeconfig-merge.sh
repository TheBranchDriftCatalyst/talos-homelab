#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  Kubeconfig Auto-Merge Utility                                               ║
# ║  Discovers and merges all kubeconfigs from .output/ directory                ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# Source shared library
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"

# ══════════════════════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════════════════════
DEFAULT_KUBECONFIG="${HOME}/.kube/config"

# ══════════════════════════════════════════════════════════════════════════════
# Banner
# ══════════════════════════════════════════════════════════════════════════════
print_banner "
██╗  ██╗██╗   ██╗██████╗ ███████╗ ██████╗ ██████╗ ███╗   ██╗███████╗██╗ ██████╗
██║ ██╔╝██║   ██║██╔══██╗██╔════╝██╔════╝██╔═══██╗████╗  ██║██╔════╝██║██╔════╝
█████╔╝ ██║   ██║██████╔╝█████╗  ██║     ██║   ██║██╔██╗ ██║█████╗  ██║██║  ███╗
██╔═██╗ ██║   ██║██╔══██╗██╔══╝  ██║     ██║   ██║██║╚██╗██║██╔══╝  ██║██║   ██║
██║  ██╗╚██████╔╝██████╔╝███████╗╚██████╗╚██████╔╝██║ ╚████║██║     ██║╚██████╔╝
╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚══════╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═══╝╚═╝     ╚═╝ ╚═════╝
                             ${ICON_LIGHTNING} Auto-Merge Utility ${ICON_LIGHTNING}
" "$YELLOW"

# ══════════════════════════════════════════════════════════════════════════════
# Check Output Directory
# ══════════════════════════════════════════════════════════════════════════════
if [[ ! -d "$OUTPUT_DIR" ]]; then
  error "No $OUTPUT_DIR directory found"
  log_note "Run './scripts/provision.sh' or './scripts/provision-local.sh' first"
  exit 1
fi

# ══════════════════════════════════════════════════════════════════════════════
# Discover Kubeconfigs
# ══════════════════════════════════════════════════════════════════════════════
log_step "1" "Discovering Kubeconfigs in $OUTPUT_DIR"

FOUND_CONFIGS=()
while IFS= read -r -d '' config_path; do
  FOUND_CONFIGS+=("$config_path")
done < <(find "$OUTPUT_DIR" -type f -name "kubeconfig" -print0 2> /dev/null)

if [[ ${#FOUND_CONFIGS[@]} -eq 0 ]]; then
  warn "No kubeconfig files found in $OUTPUT_DIR"
  echo ""
  echo "Expected locations:"
  log_note ".output/kubeconfig         (production cluster)"
  log_note ".output/local/kubeconfig   (local test cluster)"
  log_note ".output/*/kubeconfig       (any other environment)"
  exit 1
fi

success "Found ${#FOUND_CONFIGS[@]} kubeconfig file(s):"
for config in "${FOUND_CONFIGS[@]}"; do
  echo -e "  ${DIM}${ICON_BULLET}${RESET} $config"
done
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Create Backup
# ══════════════════════════════════════════════════════════════════════════════
ensure_dir "${HOME}/.kube"

if [[ -f "$DEFAULT_KUBECONFIG" ]]; then
  log_step "2" "Backing Up Existing Kubeconfig"
  BACKUP_FILE=$(backup_file "$DEFAULT_KUBECONFIG")
  success "Backup: $BACKUP_FILE"
  echo ""
fi

# ══════════════════════════════════════════════════════════════════════════════
# Process Each Kubeconfig
# ══════════════════════════════════════════════════════════════════════════════
log_step "3" "Processing Kubeconfigs"

MERGED_COUNT=0
SKIPPED_COUNT=0

for KUBECONFIG_PATH in "${FOUND_CONFIGS[@]}"; do
  # Derive context name from path
  if [[ "$KUBECONFIG_PATH" == "${OUTPUT_DIR}/kubeconfig" ]]; then
    CONTEXT_NAME="catalyst-cluster"
    CLUSTER_NAME="catalyst-cluster"
    ENV_NAME="production"
  else
    ENV_DIR=$(echo "$KUBECONFIG_PATH" | sed "s|^${OUTPUT_DIR}/||" | sed 's|/kubeconfig$||')
    CONTEXT_NAME="talos-${ENV_DIR}"
    CLUSTER_NAME="talos-${ENV_DIR}"
    ENV_NAME="$ENV_DIR"
  fi

  print_subsection "Processing: $ENV_NAME"
  echo -e "    ${DIM}Path:${RESET}    $KUBECONFIG_PATH"
  echo -e "    ${DIM}Context:${RESET} $CONTEXT_NAME"
  echo -e "    ${DIM}Cluster:${RESET} $CLUSTER_NAME"

  # Check if context already exists
  if [[ -f "$DEFAULT_KUBECONFIG" ]]; then
    if kubectl config get-contexts "$CONTEXT_NAME" &> /dev/null; then
      warn "Context '$CONTEXT_NAME' already exists"
      if confirm "    Remove and re-merge?"; then
        info "Removing existing context..."
        kubectl config delete-context "$CONTEXT_NAME" 2> /dev/null || true
        kubectl config delete-cluster "$CLUSTER_NAME" 2> /dev/null || true
      else
        warn "Skipping"
        echo ""
        ((SKIPPED_COUNT++))
        continue
      fi
    fi
  fi

  # Read original context name
  ORIGINAL_CONTEXT=$(kubectl --kubeconfig="$KUBECONFIG_PATH" config current-context 2> /dev/null || echo "")

  if [[ -z "$ORIGINAL_CONTEXT" ]]; then
    warn "No current context found, using first available"
    ORIGINAL_CONTEXT=$(kubectl --kubeconfig="$KUBECONFIG_PATH" config get-contexts -o name | head -1 || echo "")
  fi

  if [[ -z "$ORIGINAL_CONTEXT" ]]; then
    error "No contexts found in kubeconfig, skipping"
    echo ""
    ((SKIPPED_COUNT++))
    continue
  fi

  # Merge kubeconfig
  if [[ -f "$DEFAULT_KUBECONFIG" ]]; then
    export KUBECONFIG="${KUBECONFIG_PATH}:${DEFAULT_KUBECONFIG}"
  else
    export KUBECONFIG="${KUBECONFIG_PATH}"
  fi

  # Rename context if needed
  if [[ "$ORIGINAL_CONTEXT" != "$CONTEXT_NAME" ]]; then
    kubectl config rename-context "$ORIGINAL_CONTEXT" "$CONTEXT_NAME" 2> /dev/null || true
  fi

  # Update cluster name
  kubectl config set-context "$CONTEXT_NAME" --cluster="$CLUSTER_NAME" 2> /dev/null || true

  # Flatten and write
  kubectl config view --flatten > "${DEFAULT_KUBECONFIG}.tmp"
  mv "${DEFAULT_KUBECONFIG}.tmp" "$DEFAULT_KUBECONFIG"
  chmod 600 "$DEFAULT_KUBECONFIG"

  success "Merged"
  echo ""
  ((MERGED_COUNT++))
done

# Unset KUBECONFIG
unset KUBECONFIG

# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════
print_summary "success"

print_section "MERGE RESULTS"
print_kv "Merged" "$MERGED_COUNT"
print_kv "Skipped" "$SKIPPED_COUNT"
echo ""

# Show available contexts
if [[ -f "$DEFAULT_KUBECONFIG" ]]; then
  print_section "AVAILABLE CONTEXTS"
  kubectl config get-contexts
  echo ""
fi

# Set default context
if [[ $MERGED_COUNT -gt 0 ]]; then
  # Prefer production if available
  if kubectl config get-contexts catalyst-cluster &> /dev/null; then
    DEFAULT_CONTEXT="catalyst-cluster"
  elif kubectl config get-contexts talos-local &> /dev/null; then
    DEFAULT_CONTEXT="talos-local"
  else
    DEFAULT_CONTEXT=$(kubectl config get-contexts -o name | head -1)
  fi

  if [[ -n "$DEFAULT_CONTEXT" ]]; then
    info "Setting current context to: $DEFAULT_CONTEXT"
    kubectl config use-context "$DEFAULT_CONTEXT"
    echo ""
  fi
fi

# Quick Commands
print_section "QUICK COMMANDS"
echo -e "  ${CYAN}kubectl get nodes${RESET}"
echo -e "  ${CYAN}kubectl get pods -A${RESET}"
echo -e "  ${CYAN}kubectl top nodes${RESET}"
echo ""

# Context switching
print_section "CONTEXT SWITCHING"
if command -v kubectx &> /dev/null; then
  echo -e "  ${CYAN}kubectx${RESET}                    ${DIM}# List contexts${RESET}"
  echo -e "  ${CYAN}kubectx catalyst-cluster${RESET}     ${DIM}# Switch to production${RESET}"
  echo -e "  ${CYAN}kubectx talos-local${RESET}        ${DIM}# Switch to local test${RESET}"
  echo -e "  ${CYAN}kubectx -${RESET}                  ${DIM}# Switch to previous${RESET}"
else
  echo -e "  ${CYAN}kubectl config get-contexts${RESET}"
  echo -e "  ${CYAN}kubectl config use-context <context-name>${RESET}"
fi
echo ""

# Namespace switching
if command -v kubens &> /dev/null; then
  print_section "NAMESPACE SWITCHING"
  echo -e "  ${CYAN}kubens${RESET}                     ${DIM}# List namespaces${RESET}"
  echo -e "  ${CYAN}kubens media${RESET}               ${DIM}# Switch to media${RESET}"
  echo -e "  ${CYAN}kubens -${RESET}                   ${DIM}# Switch to previous${RESET}"
  echo ""
fi

# K9s
if command -v k9s &> /dev/null; then
  print_section "K9S TUI"
  echo -e "  ${CYAN}k9s${RESET}                        ${DIM}# Launch interactive manager${RESET}"
  echo -e "  ${CYAN}k9s --context <name>${RESET}       ${DIM}# Launch for specific context${RESET}"
  echo ""
fi

echo -e "${GREEN}${BOLD}${EMOJI_PARTY} Setup complete!${RESET}"
echo ""
