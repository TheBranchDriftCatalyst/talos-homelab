#!/usr/bin/env bash
set -euo pipefail

# Script to deploy the complete observability stack from scratch
# This includes: Prometheus, Grafana, Alertmanager, MongoDB, OpenSearch, Graylog, Fluent Bit

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=================================================="
echo "Deploying Observability Stack"
echo "=================================================="

# Add Helm repositories
echo ""
echo "Adding Helm repositories..."
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo add opensearch https://opensearch-project.github.io/helm-charts
helm repo add fluent https://fluent.github.io/helm-charts
helm repo update

# Create namespaces
echo ""
echo "Creating namespaces..."
kubectl apply -f "${PROJECT_ROOT}/infrastructure/base/namespaces/monitoring.yaml"
kubectl apply -f "${PROJECT_ROOT}/infrastructure/base/namespaces/observability.yaml"

# Deploy MongoDB for Graylog
echo ""
echo "Deploying MongoDB..."
helm upgrade --install mongodb bitnami/mongodb \
  --namespace observability \
  --create-namespace \
  --values "${PROJECT_ROOT}/infrastructure/base/observability/mongodb/values.yaml" \
  --wait \
  --timeout 10m

# Deploy OpenSearch for Graylog
echo ""
echo "Deploying OpenSearch..."
helm upgrade --install opensearch opensearch/opensearch \
  --namespace observability \
  --values "${PROJECT_ROOT}/infrastructure/base/observability/opensearch/values.yaml" \
  --wait \
  --timeout 10m

# Deploy Graylog
echo ""
echo "Deploying Graylog..."
kubectl apply -f "${PROJECT_ROOT}/infrastructure/base/observability/graylog/deployment.yaml"

# Deploy kube-prometheus-stack (Prometheus, Grafana, Alertmanager)
echo ""
echo "Deploying kube-prometheus-stack (Prometheus, Grafana, Alertmanager)..."
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --values "${PROJECT_ROOT}/infrastructure/base/monitoring/kube-prometheus-stack/values.yaml" \
  --wait \
  --timeout 10m

# Deploy Fluent Bit for log collection
echo ""
echo "Deploying Fluent Bit..."
helm upgrade --install fluent-bit fluent/fluent-bit \
  --namespace observability \
  --values "${PROJECT_ROOT}/infrastructure/base/observability/fluent-bit/values.yaml" \
  --wait \
  --timeout 5m

# Apply IngressRoutes
echo ""
echo "Applying IngressRoutes..."
kubectl apply -f "${PROJECT_ROOT}/infrastructure/base/observability/ingressroutes.yaml"

echo ""
echo "=================================================="
echo "Observability Stack Deployment Complete!"
echo "=================================================="
echo ""
echo "Access URLs (add these to your /etc/hosts):"
echo "  Grafana:      http://grafana.talos00"
echo "  Prometheus:   http://prometheus.talos00"
echo "  Alertmanager: http://alertmanager.talos00"
echo "  Graylog:      http://graylog.talos00"
echo ""
echo "Default Credentials:"
echo "  Grafana:  admin / prom-operator"
echo "  Graylog:  admin / admin"
echo ""
echo "Next steps:"
echo "  1. Configure API keys in Exportarr deployments"
echo "  2. Set up Graylog inputs and streams"
echo "  3. Import Grafana dashboards"
echo ""
