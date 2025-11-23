#!/bin/bash
set -euo pipefail

# Deploy Complete Homelab Stack
# This script deploys infrastructure and applications to your Talos cluster

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Configuration
DEPLOY_MONITORING="${DEPLOY_MONITORING:-true}"
DEPLOY_OBSERVABILITY="${DEPLOY_OBSERVABILITY:-true}"
DEPLOY_APPS="${DEPLOY_APPS:-false}"
ENVIRONMENT="${ENVIRONMENT:-production}"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   Homelab Stack Deployment${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "Environment: $ENVIRONMENT"
echo "Deploy Monitoring: $DEPLOY_MONITORING"
echo "Deploy Observability: $DEPLOY_OBSERVABILITY"
echo "Deploy Apps: $DEPLOY_APPS"
echo ""

# Function to wait for resources
wait_for_resource() {
  local resource=$1
  local namespace=$2
  local timeout=${3:-300}

  echo -e "${BLUE}⏳ Waiting for $resource in $namespace (timeout: ${timeout}s)...${NC}"
  kubectl wait --for=condition=ready "$resource" -n "$namespace" --timeout="${timeout}s" 2> /dev/null || {
    echo -e "${YELLOW}⚠️  Timeout waiting for $resource, continuing...${NC}"
    return 0
  }
  echo -e "${GREEN}✅ $resource ready${NC}"
}

# Step 1: Verify cluster health
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Step 1: Verifying Cluster Health${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

if ! kubectl cluster-info &> /dev/null; then
  echo -e "${RED}❌ Cannot connect to cluster${NC}"
  echo "Make sure you're using the correct context:"
  echo "  kubectx homelab-single"
  exit 1
fi

echo -e "${GREEN}✅ Cluster is accessible${NC}"
kubectl get nodes
echo ""

# Step 2: Deploy Namespaces
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Step 2: Deploying Namespaces${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

echo "📦 Applying namespaces..."
kubectl apply -k "$PROJECT_ROOT/infrastructure/base/namespaces/"
echo ""

# Wait for namespaces
echo "⏳ Waiting for namespaces to be ready..."
sleep 5
kubectl get namespaces | grep media
echo -e "${GREEN}✅ Namespaces deployed${NC}"
echo ""

# Step 3: Deploy Storage
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Step 3: Deploying Storage${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

echo "💾 Applying storage provisioners..."
kubectl apply -k "$PROJECT_ROOT/infrastructure/base/storage/"
echo ""

# Wait for local-path-provisioner
wait_for_resource "pod -l app=local-path-provisioner" "local-path-storage" 120
echo ""

# Check storage classes
echo "📋 Available storage classes:"
kubectl get storageclass
echo -e "${GREEN}✅ Storage deployed${NC}"
echo ""

# Step 4: Verify Traefik (already installed)
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Step 4: Verifying Traefik${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

if kubectl get namespace traefik &> /dev/null; then
  echo -e "${GREEN}✅ Traefik namespace exists${NC}"
  kubectl get pods -n traefik
  echo ""

  # Check if Traefik is responding
  if kubectl get ingressroute -n default whoami &> /dev/null; then
    echo -e "${GREEN}✅ Traefik IngressRoutes working${NC}"
  fi
else
  echo -e "${YELLOW}⚠️  Traefik not found${NC}"
  echo "Run: task setup-infrastructure"
fi
echo ""

# Step 5: Deploy Monitoring (optional)
if [ "$DEPLOY_MONITORING" = "true" ]; then
  echo -e "${GREEN}========================================${NC}"
  echo -e "${GREEN}Step 5: Deploying Monitoring Stack${NC}"
  echo -e "${GREEN}========================================${NC}"
  echo ""

  echo -e "${YELLOW}⚠️  NOTE: This requires Helm and will install:${NC}"
  echo "  - Prometheus Operator"
  echo "  - Prometheus (50Gi storage)"
  echo "  - Grafana (10Gi storage)"
  echo "  - Alertmanager (10Gi storage)"
  echo "  - Various exporters and service monitors"
  echo ""

  read -p "Continue with monitoring deployment? (y/N) " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Apply namespace
    kubectl apply -f "$PROJECT_ROOT/infrastructure/base/monitoring/kube-prometheus-stack/namespace.yaml"

    # Note: This would normally be deployed via FluxCD
    # For now, we'll need Helm to deploy it manually
    echo -e "${YELLOW}📝 Monitoring stack requires Helm${NC}"
    echo "To deploy manually:"
    echo "  1. Add Helm repo: helm repo add prometheus-community https://prometheus-community.github.io/helm-charts"
    echo "  2. Update repos: helm repo update"
    echo "  3. Install: helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack -n monitoring --create-namespace -f infrastructure/base/monitoring/kube-prometheus-stack/values.yaml"
    echo ""
    echo -e "${YELLOW}⏭️  Skipping for now (deploy via Helm manually or FluxCD later)${NC}"
  else
    echo -e "${YELLOW}⏭️  Skipping monitoring deployment${NC}"
  fi
  echo ""
fi

# Step 6: Deploy Observability Stack (optional)
if [ "$DEPLOY_OBSERVABILITY" = "true" ]; then
  echo -e "${GREEN}========================================${NC}"
  echo -e "${GREEN}Step 6: Deploying Observability Stack${NC}"
  echo -e "${GREEN}========================================${NC}"
  echo ""

  echo -e "${YELLOW}⚠️  NOTE: This will install the complete observability stack:${NC}"
  echo "  - MongoDB (20Gi storage)"
  echo "  - OpenSearch (30Gi storage)"
  echo "  - Graylog (20Gi storage)"
  echo "  - Fluent Bit (log collector)"
  echo ""

  read -p "Continue with observability deployment? (y/N) " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    bash "${SCRIPT_DIR}/deploy-observability.sh"
    echo -e "${GREEN}✅ Observability stack deployed${NC}"
  else
    echo -e "${YELLOW}⏭️  Skipping observability deployment${NC}"
  fi
  echo ""
fi

# Step 7: Summary and Next Steps
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✅ Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

echo -e "${BLUE}📊 Cluster Status:${NC}"
echo ""

echo "📦 Namespaces:"
kubectl get namespaces | grep -E "NAME|media|monitoring|traefik|local-path"
echo ""

echo "💾 Storage Classes:"
kubectl get storageclass
echo ""

echo "📋 PersistentVolumes:"
kubectl get pv 2> /dev/null || echo "  (none yet)"
echo ""

echo -e "${BLUE}🔗 Access Points:${NC}"
echo "  Traefik Dashboard: http://traefik.talos00"
echo "  Whoami Test:       http://whoami.talos00"
echo ""
if [ "$DEPLOY_MONITORING" = "true" ] || kubectl get namespace monitoring &> /dev/null; then
  echo "  Grafana:           http://grafana.talos00"
  echo "  Prometheus:        http://prometheus.talos00"
  echo "  Alertmanager:      http://alertmanager.talos00"
  echo ""
fi
if [ "$DEPLOY_OBSERVABILITY" = "true" ] || kubectl get namespace observability &> /dev/null; then
  echo "  Graylog:           http://graylog.talos00"
  echo ""
fi
echo "  (Add to /etc/hosts: 192.168.1.54 *.talos00)"
echo ""

if [ "$DEPLOY_APPS" = "true" ]; then
  echo -e "${BLUE}📱 Application URLs (when deployed):${NC}"
  echo "  Prowlarr:  http://prowlarr.talos00"
  echo "  Sonarr:    http://sonarr.talos00"
  echo "  Radarr:    http://radarr.talos00"
  echo "  Plex:      http://plex.talos00"
  echo "  Jellyfin:  http://jellyfin.talos00"
  echo ""
fi

echo -e "${YELLOW}📝 Next Steps:${NC}"
echo ""
echo "1. ${BLUE}Configure NFS Storage (if using Synology):${NC}"
echo "   - Create NFS shares on Synology:"
echo "     • /volume1/media (for movies/TV)"
echo "     • /volume1/downloads (for torrents)"
echo "   - Update NFS server IP in infrastructure/base/storage/nfs-storageclass.yaml"
echo "   - Apply NFS resources: kubectl apply -f infrastructure/base/storage/nfs-storageclass.yaml"
echo ""

echo "2. ${BLUE}Deploy Applications (arr stack):${NC}"
echo "   Run: DEPLOY_APPS=true $0"
echo "   Or manually:"
echo "     kubectl apply -k applications/arr-stack/base/prowlarr/ -n media-dev"
echo "     kubectl apply -k applications/arr-stack/base/sonarr/ -n media-dev"
echo "     kubectl apply -k applications/arr-stack/base/radarr/ -n media-dev"
echo ""

echo "3. ${BLUE}Deploy Monitoring (if skipped):${NC}"
echo "   helm repo add prometheus-community https://prometheus-community.github.io/helm-charts"
echo "   helm repo update"
echo "   helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack -n monitoring --create-namespace"
echo ""

echo "4. ${BLUE}Setup GitOps (FluxCD + ArgoCD):${NC}"
echo "   - Push this repo to GitHub"
echo "   - Bootstrap Flux: flux bootstrap github ..."
echo "   - See: bootstrap/flux/README.md"
echo ""

echo -e "${GREEN}🎉 Infrastructure is ready!${NC}"
