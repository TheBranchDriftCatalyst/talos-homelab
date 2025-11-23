#!/bin/bash
set -euo pipefail

# Provision Local Talos Cluster (Docker-based)
# This script creates a local single-node Talos cluster for testing

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="$PROJECT_ROOT/.output/local"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   Talos Local Cluster Provisioning${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check prerequisites
echo -e "${GREEN}Step 1: Checking prerequisites...${NC}"

if ! command -v talosctl &> /dev/null; then
  echo -e "${RED}❌ talosctl not found. Please install it first:${NC}"
  echo "   brew install siderolabs/tap/talosctl"
  exit 1
fi

if ! command -v kubectl &> /dev/null; then
  echo -e "${RED}❌ kubectl not found. Please install it first:${NC}"
  echo "   brew install kubectl"
  exit 1
fi

if ! command -v docker &> /dev/null; then
  echo -e "${RED}❌ docker not found. Please install Docker Desktop first${NC}"
  exit 1
fi

if ! docker info &> /dev/null; then
  echo -e "${RED}❌ Docker is not running. Please start Docker Desktop${NC}"
  exit 1
fi

echo -e "${GREEN}✅ All prerequisites satisfied${NC}"
echo ""

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Cluster configuration
CLUSTER_NAME="talos-local"
CONTROLPLANE_IP="127.0.0.1"
CONTROLPLANE_PORT="6443"

echo -e "${GREEN}Step 2: Creating Talos cluster configuration...${NC}"

# Generate cluster configuration
talosctl gen config "$CLUSTER_NAME" "https://${CONTROLPLANE_IP}:${CONTROLPLANE_PORT}" \
  --output "$OUTPUT_DIR" \
  --with-examples=false \
  --with-docs=false \
  --force

echo -e "${GREEN}✅ Cluster configuration generated${NC}"
echo ""

echo -e "${GREEN}Step 3: Creating local Talos cluster...${NC}"

# Create the cluster
talosctl cluster create \
  --name "$CLUSTER_NAME" \
  --controlplanes 1 \
  --workers 0 \
  --config-patch @"${PROJECT_ROOT}/talos/controlplane.yaml" \
  --wait=true \
  --wait-timeout=10m \
  --talosconfig "$OUTPUT_DIR/talosconfig"

echo -e "${GREEN}✅ Cluster created${NC}"
echo ""

echo -e "${GREEN}Step 4: Waiting for cluster to be ready...${NC}"

# Wait for Kubernetes API
talosctl --talosconfig "$OUTPUT_DIR/talosconfig" \
  --nodes "$CONTROLPLANE_IP" \
  health --wait-timeout 10m

echo -e "${GREEN}✅ Cluster is healthy${NC}"
echo ""

echo -e "${GREEN}Step 5: Extracting kubeconfig...${NC}"

# Get kubeconfig
talosctl --talosconfig "$OUTPUT_DIR/talosconfig" \
  kubeconfig "$OUTPUT_DIR/kubeconfig" \
  --force \
  --nodes "$CONTROLPLANE_IP"

# Set KUBECONFIG for this script
export KUBECONFIG="$OUTPUT_DIR/kubeconfig"

# Wait for nodes to be ready
echo "Waiting for nodes to be ready..."
kubectl wait --for=condition=ready nodes --all --timeout=5m

echo -e "${GREEN}✅ Kubeconfig extracted${NC}"
echo ""

# Patch metrics-server for local development
echo -e "${GREEN}Step 6: Installing core components...${NC}"

# Install metrics-server
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl patch deployment metrics-server -n kube-system \
  --type='json' \
  -p='[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--kubelet-insecure-tls"}]'

echo -e "${GREEN}✅ Core components installed${NC}"
echo ""

# Install Traefik
echo -e "${GREEN}Step 7: Installing Traefik...${NC}"

# Add Traefik Helm repo
helm repo add traefik https://traefik.github.io/charts || true
helm repo update

# Install Traefik (modified for local cluster - no hostPort)
helm upgrade --install traefik traefik/traefik \
  --namespace traefik \
  --create-namespace \
  --set deployment.kind=Deployment \
  --set service.type=LoadBalancer \
  --set ports.web.exposedPort=80 \
  --set ports.websecure.exposedPort=443 \
  --set ingressRoute.dashboard.enabled=true \
  --set ingressRoute.dashboard.matchRule='Host(`traefik.localhost`)' \
  --set logs.general.level=INFO \
  --set logs.access.enabled=true \
  --set providers.kubernetesCRD.enabled=true \
  --set providers.kubernetesCRD.allowCrossNamespace=true \
  --wait

echo -e "${GREEN}✅ Traefik installed${NC}"
echo ""

# Create test whoami service
echo -e "${GREEN}Step 8: Creating test service (whoami)...${NC}"

kubectl create namespace whoami --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -n whoami -f - << EOF
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: whoami
spec:
  replicas: 1
  selector:
    matchLabels:
      app: whoami
  template:
    metadata:
      labels:
        app: whoami
    spec:
      containers:
      - name: whoami
        image: traefik/whoami
        ports:
        - containerPort: 80
---
apiVersion: v1
kind: Service
metadata:
  name: whoami
spec:
  ports:
  - port: 80
    targetPort: 80
  selector:
    app: whoami
---
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: whoami
spec:
  entryPoints:
    - web
  routes:
    - match: Host(\`whoami.localhost\`)
      kind: Rule
      services:
        - name: whoami
          port: 80
EOF

echo -e "${GREEN}✅ Test service created${NC}"
echo ""

# Auto-merge kubeconfig
if [ "${AUTO_MERGE_KUBECONFIG:-true}" = "true" ]; then
  echo -e "${BLUE}🔀 Auto-merging kubeconfig to ~/.kube/config...${NC}"

  # Set context name
  kubectl config rename-context admin@"$CLUSTER_NAME" "$CLUSTER_NAME" --kubeconfig="$OUTPUT_DIR/kubeconfig" || true

  # Merge
  if [ -f ~/.kube/config ]; then
    cp ~/.kube/config ~/.kube/config.backup.$(date +%Y%m%d_%H%M%S)
    KUBECONFIG="$OUTPUT_DIR/kubeconfig:$HOME/.kube/config" kubectl config view --flatten > ~/.kube/config.tmp
    mv ~/.kube/config.tmp ~/.kube/config
    chmod 600 ~/.kube/config
    echo -e "${GREEN}✅ Kubeconfig merged to ~/.kube/config${NC}"
  else
    mkdir -p ~/.kube
    cp "$OUTPUT_DIR/kubeconfig" ~/.kube/config
    chmod 600 ~/.kube/config
    echo -e "${GREEN}✅ Kubeconfig copied to ~/.kube/config${NC}"
  fi

  kubectl config use-context "$CLUSTER_NAME"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   ✅ Local Cluster Provisioned!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${YELLOW}Cluster Information:${NC}"
echo -e "  Name: $CLUSTER_NAME"
echo -e "  Kubeconfig: $OUTPUT_DIR/kubeconfig"
echo -e "  Talosconfig: $OUTPUT_DIR/talosconfig"
echo -e "  Control Plane: https://${CONTROLPLANE_IP}:${CONTROLPLANE_PORT}"
echo ""
echo -e "${YELLOW}Access Services:${NC}"
echo -e "  Traefik Dashboard: http://traefik.localhost"
echo -e "  Whoami Test: http://whoami.localhost"
echo ""
echo -e "${YELLOW}Useful Commands:${NC}"
echo -e "  kubectl --kubeconfig $OUTPUT_DIR/kubeconfig get nodes"
echo -e "  talosctl --talosconfig $OUTPUT_DIR/talosconfig --nodes $CONTROLPLANE_IP dashboard"
echo -e "  kubectl config use-context $CLUSTER_NAME"
echo ""
echo -e "${YELLOW}Cleanup:${NC}"
echo -e "  talosctl cluster destroy --name $CLUSTER_NAME"
echo ""
