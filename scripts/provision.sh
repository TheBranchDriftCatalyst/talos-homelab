#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  Talos Single-Node Cluster Provisioning                                      ║
# ║  Fresh cluster setup with configuration and bootstrap                        ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# Source shared library
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"

# ══════════════════════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════════════════════
CONTROLPLANE_CONFIG="${PROJECT_ROOT}/configs/controlplane.yaml"
AUTO_MERGE_KUBECONFIG="${AUTO_MERGE_KUBECONFIG:-true}"
MAX_RETRIES=10

# ══════════════════════════════════════════════════════════════════════════════
# Banner
# ══════════════════════════════════════════════════════════════════════════════
print_banner "
██████╗ ██████╗  ██████╗ ██╗   ██╗██╗███████╗██╗ ██████╗ ███╗   ██╗
██╔══██╗██╔══██╗██╔═══██╗██║   ██║██║██╔════╝██║██╔═══██╗████╗  ██║
██████╔╝██████╔╝██║   ██║██║   ██║██║███████╗██║██║   ██║██╔██╗ ██║
██╔═══╝ ██╔══██╗██║   ██║╚██╗ ██╔╝██║╚════██║██║██║   ██║██║╚██╗██║
██║     ██║  ██║╚██████╔╝ ╚████╔╝ ██║███████║██║╚██████╔╝██║ ╚████║
╚═╝     ╚═╝  ╚═╝ ╚═════╝   ╚═══╝  ╚═╝╚══════╝╚═╝ ╚═════╝ ╚═╝  ╚═══╝
                   ${ICON_LIGHTNING} Talos Cluster Bootstrap ${ICON_LIGHTNING}
" "$MAGENTA"

# Ensure output directory exists
ensure_dir "$OUTPUT_DIR"

print_section "PROVISIONING CONFIGURATION"
echo ""
print_kv "Node IP" "$TALOS_NODE"
print_kv "Cluster" "$CLUSTER_NAME"
print_kv "Talosconfig" "$TALOSCONFIG"
print_kv "Controlplane" "$CONTROLPLANE_CONFIG"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 1: Check Network Connectivity
# ══════════════════════════════════════════════════════════════════════════════
log_step "1" "Checking Network Connectivity"

if ! ping -c 2 "$TALOS_NODE" >/dev/null 2>&1; then
  error "Node $TALOS_NODE is not reachable"
  exit 1
fi
success "Node is reachable at $TALOS_NODE"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 2: Apply Configuration
# ══════════════════════════════════════════════════════════════════════════════
log_step "2" "Applying Configuration (insecure mode for first boot)"

if [[ ! -f "$CONTROLPLANE_CONFIG" ]]; then
  error "Control plane config not found: $CONTROLPLANE_CONFIG"
  log_note "Run: task gen-config"
  exit 1
fi

if ! talosctl apply-config --insecure --nodes "$TALOS_NODE" --file "$CONTROLPLANE_CONFIG"; then
  error "Failed to apply configuration"
  exit 1
fi
success "Configuration applied"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 3: Wait for Node Reboot
# ══════════════════════════════════════════════════════════════════════════════
log_step "3" "Waiting for Node Reboot"

info "Waiting 90 seconds for node to reboot and apply configuration..."
for i in {1..18}; do
  printf "\r${DIM}Progress: %d/90s${RESET}" $((i * 5))
  sleep 5
done
printf "\r%60s\r" ""
success "Wait complete"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 4: Configure Talosconfig
# ══════════════════════════════════════════════════════════════════════════════
log_step "4" "Configuring talosconfig"

talosctl config endpoint "$TALOS_NODE" --talosconfig "$TALOSCONFIG"
talosctl config node "$TALOS_NODE" --talosconfig "$TALOSCONFIG"
success "Talosconfig configured"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 5: Test Connection
# ══════════════════════════════════════════════════════════════════════════════
log_step "5" "Testing Connection to Node"

RETRY=0
while [[ $RETRY -lt $MAX_RETRIES ]]; do
  if talosctl --talosconfig "$TALOSCONFIG" --nodes "$TALOS_NODE" version >/dev/null 2>&1; then
    success "Connection successful!"
    talosctl --talosconfig "$TALOSCONFIG" --nodes "$TALOS_NODE" version
    break
  fi
  RETRY=$((RETRY + 1))
  warn "Attempt $RETRY/$MAX_RETRIES - waiting for node..."
  sleep 10
done

if [[ $RETRY -eq $MAX_RETRIES ]]; then
  error "Failed to connect to node after $MAX_RETRIES attempts"
  exit 1
fi
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 6: Bootstrap etcd
# ══════════════════════════════════════════════════════════════════════════════
log_step "6" "Bootstrapping etcd Cluster"

if ! talosctl --talosconfig "$TALOSCONFIG" --nodes "$TALOS_NODE" bootstrap; then
  error "Failed to bootstrap cluster"
  exit 1
fi
success "Cluster bootstrapped"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 7: Wait for Kubernetes
# ══════════════════════════════════════════════════════════════════════════════
log_step "7" "Waiting for Kubernetes to Start"

info "Waiting 30 seconds for Kubernetes components..."
for i in {1..6}; do
  printf "\r${DIM}Progress: %d/30s${RESET}" $((i * 5))
  sleep 5
done
printf "\r%60s\r" ""
success "Wait complete"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 8: Download Kubeconfig
# ══════════════════════════════════════════════════════════════════════════════
log_step "8" "Downloading Kubeconfig"

if talosctl --talosconfig "$TALOSCONFIG" --nodes "$TALOS_NODE" kubeconfig "$OUTPUT_DIR"; then
  success "Kubeconfig downloaded to ${OUTPUT_DIR}/kubeconfig"
else
  warn "Failed to download kubeconfig (Kubernetes may still be starting)"
fi
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 8.5: Remove Control-Plane Taint
# ══════════════════════════════════════════════════════════════════════════════
log_step "8.5" "Removing Control-Plane Taint (single-node cluster)"

sleep 10  # Give k8s a moment to settle
export KUBECONFIG="${OUTPUT_DIR}/kubeconfig"
NODE_NAME=$(kubectl get nodes -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")

if [[ -n "$NODE_NAME" ]]; then
  if kubectl taint nodes "$NODE_NAME" node-role.kubernetes.io/control-plane:NoSchedule- 2>/dev/null; then
    success "Control-plane taint removed from $NODE_NAME"
  else
    warn "Taint already removed or not present"
  fi
else
  warn "Could not get node name, skipping taint removal"
fi
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 9: Check Cluster Health
# ══════════════════════════════════════════════════════════════════════════════
log_step "9" "Checking Cluster Health"

talosctl --talosconfig "$TALOSCONFIG" --nodes "$TALOS_NODE" health --server=false || true
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Step 10: List Services
# ══════════════════════════════════════════════════════════════════════════════
log_step "10" "Listing Services"

talosctl --talosconfig "$TALOSCONFIG" --nodes "$TALOS_NODE" services
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════
print_summary "success"

# Optionally merge kubeconfig
if [[ "${AUTO_MERGE_KUBECONFIG}" == "true" ]]; then
  info "Auto-merging kubeconfig to ~/.kube/config..."
  "${SCRIPT_DIR}/kubeconfig-merge.sh"
  echo ""

  print_next_steps \
    "kubectl get nodes  ${DIM}# No --kubeconfig needed!${RESET}" \
    "task dashboard     ${DIM}# Open Talos dashboard${RESET}" \
    "task health        ${DIM}# Check cluster health${RESET}" \
    "task setup-infrastructure  ${DIM}# Install Traefik and metrics-server${RESET}"
else
  print_next_steps \
    "task kubeconfig-merge  ${DIM}# Merge config to ~/.kube/config${RESET}" \
    "kubectl --kubeconfig ${OUTPUT_DIR}/kubeconfig get nodes" \
    "task dashboard     ${DIM}# Open Talos dashboard${RESET}" \
    "task health        ${DIM}# Check cluster health${RESET}"
fi

echo -e "${GREEN}${BOLD}${EMOJI_PARTY} Your cluster is ready!${RESET}"
echo ""
