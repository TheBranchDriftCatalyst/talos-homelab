#!/bin/bash
# DNS Infrastructure Setup Script
# Deploys Technitium DNS Server and catalyst-dns-sync daemon

set -e

cd "$(dirname "$0")/.."

KUBECONFIG="${KUBECONFIG:-./.output/kubeconfig}"
TECHNITIUM_PASSWORD="${TECHNITIUM_PASSWORD:-admin}"
NODE_IP="${TALOS_NODE:-192.168.1.54}"
DNS_ZONE="${DNS_ZONE:-talos00}"
REGISTRY="${REGISTRY:-localhost:5000}"

echo "🌐 DNS Infrastructure Setup"
echo "===================================="
echo "  Technitium DNS Server"
echo "  catalyst-dns-sync Daemon"
echo ""
echo "Configuration:"
echo "  - Zone: $DNS_ZONE"
echo "  - Node IP: $NODE_IP"
echo "  - Registry: $REGISTRY"
echo ""

# Step 1: Create namespace
echo "1️⃣  Creating dns namespace..."
kubectl --kubeconfig "$KUBECONFIG" apply -f infrastructure/base/dns/namespace.yaml

# Step 2: Deploy Technitium DNS Server
echo ""
echo "2️⃣  Deploying Technitium DNS Server..."
kubectl --kubeconfig "$KUBECONFIG" apply -k infrastructure/base/dns/technitium/

# Step 3: Wait for Technitium to be ready
echo ""
echo "3️⃣  Waiting for Technitium DNS to be ready..."
kubectl --kubeconfig "$KUBECONFIG" wait --namespace dns \
    --for=condition=ready pod \
    --selector=app=technitium-dns \
    --timeout=180s

# Step 4: Configure Technitium
echo ""
echo "4️⃣  Configuring Technitium DNS Server..."
if [ -f "./scripts/configure-technitium.sh" ]; then
    ./scripts/configure-technitium.sh
else
    echo "⚠️  Manual configuration required:"
    echo "    1. Access Web UI: http://dns.$DNS_ZONE"
    echo "    2. Login with password: $TECHNITIUM_PASSWORD"
    echo "    3. Create zone: $DNS_ZONE"
    echo "    4. Verify zone is active"
    echo ""
    read -p "Press Enter when configuration is complete..."
fi

# Step 5: Build and push catalyst-dns-sync image
echo ""
echo "5️⃣  Building catalyst-dns-sync Docker image..."
docker build \
    --build-arg VERSION=$(git describe --tags --always --dirty 2>/dev/null || echo "dev") \
    --build-arg GIT_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "unknown") \
    --build-arg BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ") \
    -t $REGISTRY/catalyst-dns-sync:latest \
    .

echo ""
echo "6️⃣  Pushing image to registry..."
docker push $REGISTRY/catalyst-dns-sync:latest

# Step 6: Deploy catalyst-dns-sync
echo ""
echo "7️⃣  Deploying catalyst-dns-sync daemon..."
kubectl --kubeconfig "$KUBECONFIG" apply -k applications/catalyst-dns-sync/base/

# Step 7: Wait for daemon to be ready
echo ""
echo "8️⃣  Waiting for catalyst-dns-sync to be ready..."
kubectl --kubeconfig "$KUBECONFIG" wait --namespace dns \
    --for=condition=ready pod \
    --selector=app=catalyst-dns-sync \
    --timeout=120s

# Step 8: Show status
echo ""
echo "✅ DNS infrastructure deployed successfully!"
echo ""
echo "📊 Status:"
kubectl --kubeconfig "$KUBECONFIG" -n dns get pods

echo ""
echo "🔗 Access Points:"
echo "  - Technitium Web UI: http://dns.$DNS_ZONE"
echo "  - Metrics: kubectl --kubeconfig $KUBECONFIG -n dns port-forward deployment/catalyst-dns-sync 9090:9090"
echo "  - Logs: kubectl --kubeconfig $KUBECONFIG -n dns logs -f deployment/catalyst-dns-sync"
echo ""
echo "📝 Next Steps:"
echo "  1. Configure your network/devices to use $NODE_IP as DNS server"
echo "  2. Test DNS resolution: dig @$NODE_IP test.$DNS_ZONE"
echo "  3. Deploy an Ingress and watch DNS records auto-create!"
echo ""
echo "🎉 Setup complete!"
