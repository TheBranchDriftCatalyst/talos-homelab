#!/bin/bash

# Talos Single-Node Cluster Provisioning Script
# This script provisions a fresh Talos node with the configuration in this directory

set -e

# Change to project root
cd "$(dirname "$0")/.."

TALOS_NODE="${TALOS_NODE:-192.168.1.54}"
TALOSCONFIG="./configs/talosconfig"
CONTROLPLANE_CONFIG="./configs/controlplane.yaml"
KUBECONFIG="./.output/kubeconfig"
CLUSTER_NAME="${CLUSTER_NAME:-homelab-single}"

# Ensure output directory exists
mkdir -p .output

echo "🚀 Starting Talos provisioning for node: $TALOS_NODE"
echo ""

# Step 1: Check if node is reachable
echo "1️⃣  Checking network connectivity..."
if ! ping -c 2 "$TALOS_NODE" > /dev/null 2>&1; then
  echo "❌ Node $TALOS_NODE is not reachable"
  exit 1
fi
echo "✅ Node is reachable"
echo ""

# Step 2: Apply configuration with insecure mode (for maintenance mode)
echo "2️⃣  Applying configuration to node (insecure mode for first boot)..."
if ! talosctl apply-config --insecure --nodes "$TALOS_NODE" --file "$CONTROLPLANE_CONFIG"; then
  echo "❌ Failed to apply configuration"
  exit 1
fi
echo "✅ Configuration applied"
echo ""

# Step 3: Wait for node to reboot and apply config
echo "3️⃣  Waiting 90 seconds for node to reboot and apply configuration..."
sleep 90
echo ""

# Step 4: Configure talosconfig endpoints
echo "4️⃣  Configuring talosconfig..."
talosctl config endpoint "$TALOS_NODE" --talosconfig "$TALOSCONFIG"
talosctl config node "$TALOS_NODE" --talosconfig "$TALOSCONFIG"
echo "✅ Talosconfig configured"
echo ""

# Step 5: Test connection
echo "5️⃣  Testing connection to node..."
MAX_RETRIES=10
RETRY=0
while [ $RETRY -lt $MAX_RETRIES ]; do
  if talosctl --talosconfig "$TALOSCONFIG" --nodes "$TALOS_NODE" version > /dev/null 2>&1; then
    echo "✅ Connection successful!"
    talosctl --talosconfig "$TALOSCONFIG" --nodes "$TALOS_NODE" version
    break
  fi
  RETRY=$((RETRY + 1))
  echo "⏳ Attempt $RETRY/$MAX_RETRIES - waiting for node..."
  sleep 10
done

if [ $RETRY -eq $MAX_RETRIES ]; then
  echo "❌ Failed to connect to node after $MAX_RETRIES attempts"
  exit 1
fi
echo ""

# Step 6: Bootstrap etcd
echo "6️⃣  Bootstrapping etcd cluster..."
if ! talosctl --talosconfig "$TALOSCONFIG" --nodes "$TALOS_NODE" bootstrap; then
  echo "❌ Failed to bootstrap cluster"
  exit 1
fi
echo "✅ Cluster bootstrapped"
echo ""

# Step 7: Wait for Kubernetes to start
echo "7️⃣  Waiting 30 seconds for Kubernetes to start..."
sleep 30
echo ""

# Step 8: Download kubeconfig
echo "8️⃣  Downloading kubeconfig..."
if ! talosctl --talosconfig "$TALOSCONFIG" --nodes "$TALOS_NODE" kubeconfig .output; then
  echo "⚠️  Failed to download kubeconfig (this is normal if Kubernetes is still starting)"
else
  echo "✅ Kubeconfig downloaded to $KUBECONFIG"
fi
echo ""

# Step 8.5: Remove control-plane taint for single-node cluster
echo "8.5️⃣  Removing control-plane taint (single-node cluster)..."
sleep 10 # Give k8s a moment to settle
NODE_NAME=$(kubectl --kubeconfig "$KUBECONFIG" get nodes -o jsonpath='{.items[0].metadata.name}' 2> /dev/null || echo "")
if [ -n "$NODE_NAME" ]; then
  if kubectl --kubeconfig "$KUBECONFIG" taint nodes "$NODE_NAME" node-role.kubernetes.io/control-plane:NoSchedule- 2> /dev/null; then
    echo "✅ Control-plane taint removed from $NODE_NAME"
  else
    echo "⚠️  Taint already removed or not present"
  fi
else
  echo "⚠️  Could not get node name, skipping taint removal"
fi
echo ""

# Step 9: Check cluster health
echo "9️⃣  Checking cluster health..."
talosctl --talosconfig "$TALOSCONFIG" --nodes "$TALOS_NODE" health --server=false || true
echo ""

# Step 10: Show services
echo "🔟 Listing services..."
talosctl --talosconfig "$TALOSCONFIG" --nodes "$TALOS_NODE" services
echo ""

echo "✅ Provisioning complete!"
echo ""

# Optionally merge kubeconfig
if [ "${AUTO_MERGE_KUBECONFIG:-true}" = "true" ]; then
  echo "🔀 Auto-merging kubeconfig to ~/.kube/config..."
  ./scripts/kubeconfig-merge.sh
  echo ""
  echo "Next steps:"
  echo "  - Run 'kubectl get nodes' to check nodes (no --kubeconfig needed!)"
  echo "  - Run 'task dashboard' to open the Talos dashboard"
  echo "  - Run 'task health' to check cluster health"
  echo "  - Run 'task setup-infrastructure' to install Traefik and metrics-server"
else
  echo "Next steps:"
  echo "  - Run 'task kubeconfig-merge' to merge config to ~/.kube/config"
  echo "  - Or use: kubectl --kubeconfig ./.output/kubeconfig get nodes"
  echo "  - Run 'task dashboard' to open the Talos dashboard"
  echo "  - Run 'task health' to check cluster health"
  echo "  - Run 'task setup-infrastructure' to install Traefik and metrics-server"
fi
echo ""
echo "Your cluster is ready! 🎉"
