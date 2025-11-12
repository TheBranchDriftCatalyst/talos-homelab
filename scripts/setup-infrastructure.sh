#!/bin/bash

# Infrastructure Setup Script
# Installs core infrastructure: Traefik, metrics-server, and test services

set -e

# Change to project root
cd "$(dirname "$0")/.."

KUBECONFIG="${KUBECONFIG:-./.output/kubeconfig}"

echo "🚀 Setting up Core Infrastructure"
echo "===================================="
echo ""
echo "This will install:"
echo "  - Traefik v3 (Ingress Controller)"
echo "  - Metrics Server (Resource monitoring)"
echo "  - whoami (Test service)"
echo "  - Dashboard IngressRoutes"
echo ""

# Step 1: Add Helm repo
echo "1️⃣  Adding Traefik Helm repository..."
helm repo add traefik https://traefik.github.io/charts 2>/dev/null || echo "Repo already exists"
helm repo update
echo "✅ Helm repo updated"
echo ""

# Step 2: Create namespace
echo "2️⃣  Creating traefik namespace..."
if ! kubectl --kubeconfig "$KUBECONFIG" get namespace traefik > /dev/null 2>&1; then
    kubectl --kubeconfig "$KUBECONFIG" create namespace traefik
    kubectl --kubeconfig "$KUBECONFIG" label namespace traefik \
        pod-security.kubernetes.io/enforce=privileged \
        pod-security.kubernetes.io/audit=privileged \
        pod-security.kubernetes.io/warn=privileged
    echo "✅ Namespace created with privileged security labels"
else
    echo "⚠️  Namespace already exists"
fi
echo ""

# Step 3: Install Traefik
echo "3️⃣  Installing Traefik via Helm..."
if helm --kubeconfig "$KUBECONFIG" list -n traefik | grep -q traefik; then
    echo "⚠️  Traefik already installed, upgrading..."
    helm --kubeconfig "$KUBECONFIG" upgrade traefik traefik/traefik \
        --namespace traefik \
        --values kubernetes/traefik-values.yaml \
        2>&1 | grep -v "Warning:"
else
    helm --kubeconfig "$KUBECONFIG" install traefik traefik/traefik \
        --namespace traefik \
        --values kubernetes/traefik-values.yaml \
        2>&1 | grep -v "Warning:"
fi
echo "✅ Traefik installed"
echo ""

# Step 4: Wait for Traefik to be ready
echo "4️⃣  Waiting for Traefik to be ready..."
kubectl --kubeconfig "$KUBECONFIG" wait --namespace traefik \
    --for=condition=ready pod \
    --selector=app.kubernetes.io/name=traefik \
    --timeout=90s
echo "✅ Traefik is ready"
echo ""

# Step 5: Deploy whoami service
echo "5️⃣  Deploying whoami test service..."
kubectl --kubeconfig "$KUBECONFIG" apply -f kubernetes/whoami-ingressroute.yaml
echo "✅ whoami deployed"
echo ""

# Step 6: Deploy dashboard IngressRoute
echo "6️⃣  Deploying Kubernetes Dashboard IngressRoute..."
kubectl --kubeconfig "$KUBECONFIG" apply -f kubernetes/dashboard-ingressroute.yaml
echo "✅ Dashboard IngressRoute deployed"
echo ""

# Step 7: Install metrics-server
echo "7️⃣  Installing metrics-server..."
if kubectl --kubeconfig "$KUBECONFIG" get deployment metrics-server -n kube-system > /dev/null 2>&1; then
    echo "⚠️  Metrics-server already installed"
else
    # Download and apply metrics-server with modified configuration for single-node
    kubectl --kubeconfig "$KUBECONFIG" apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

    # Patch metrics-server to work with self-signed certs (common in homelab)
    kubectl --kubeconfig "$KUBECONFIG" patch deployment metrics-server -n kube-system \
        --type='json' \
        -p='[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--kubelet-insecure-tls"}]' 2>/dev/null || true

    echo "✅ Metrics-server installed"
fi
echo ""

# Step 8: Wait for metrics-server to be ready
echo "8️⃣  Waiting for metrics-server to be ready..."
kubectl --kubeconfig "$KUBECONFIG" wait --namespace kube-system \
    --for=condition=ready pod \
    --selector=k8s-app=metrics-server \
    --timeout=90s || echo "⚠️  Metrics-server may still be starting..."
echo ""

# Step 9: Show status
echo "9️⃣  Deployment Status:"
echo ""
echo "Traefik Pods:"
kubectl --kubeconfig "$KUBECONFIG" get pods -n traefik
echo ""
echo "Metrics Server:"
kubectl --kubeconfig "$KUBECONFIG" get pods -n kube-system -l k8s-app=metrics-server
echo ""
echo "IngressRoutes:"
kubectl --kubeconfig "$KUBECONFIG" get ingressroute -A
echo ""

# Step 10: Test metrics
echo "🔟 Testing metrics availability..."
sleep 5  # Give metrics server a moment to collect data
kubectl --kubeconfig "$KUBECONFIG" top nodes 2>&1 || echo "⏳ Metrics not ready yet (may take 30-60 seconds)"
echo ""

echo "✅ Infrastructure setup complete!"
echo ""
echo "📋 Access Information:"
echo "  - Traefik Dashboard: http://traefik.talos00 (add to /etc/hosts)"
echo "  - whoami Service:    http://whoami.talos00"
echo "  - K8s Dashboard:     http://dashboard.talos00"
echo "  - whoami (IP):       http://192.168.1.54/whoami"
echo ""
echo "💡 Add to /etc/hosts:"
echo "   192.168.1.54  traefik.talos00 whoami.talos00 dashboard.talos00"
echo ""
echo "📊 Metrics Commands:"
echo "   kubectl --kubeconfig ./.output/kubeconfig top nodes"
echo "   kubectl --kubeconfig ./.output/kubeconfig top pods -A"
echo ""
