#!/bin/bash
# Deploy Linkerd Viz extension for observability
# This provides Grafana dashboards, Prometheus scraping, and CLI commands
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LINKERD_DIR="$REPO_ROOT/infrastructure/base/linkerd"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# Check prerequisites
check_prerequisites() {
    log "Checking prerequisites..."

    command -v helm >/dev/null 2>&1 || error "helm is required"
    command -v kubectl >/dev/null 2>&1 || error "kubectl is required"

    # Check if Linkerd is installed
    kubectl get namespace linkerd >/dev/null 2>&1 || error "Linkerd not installed. Run ./scripts/deploy-linkerd.sh first"
    kubectl get deployment -n linkerd linkerd-destination >/dev/null 2>&1 || error "Linkerd control plane not installed"

    log "Prerequisites OK"
}

# Create namespace with PSS labels (Linkerd requires NET_ADMIN capability)
create_namespace() {
    log "Creating linkerd-viz namespace with privileged PSS..."

    kubectl apply -f - <<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: linkerd-viz
  labels:
    kubernetes.io/metadata.name: linkerd-viz
    linkerd.io/extension: viz
    pod-security.kubernetes.io/enforce: privileged
    pod-security.kubernetes.io/audit: privileged
    pod-security.kubernetes.io/warn: privileged
EOF

    log "Namespace created with privileged PSS"
}

# Install Linkerd Viz
install_viz() {
    log "Installing Linkerd Viz extension..."

    # Add Helm repo if not present
    helm repo add linkerd-edge https://helm.linkerd.io/edge 2>/dev/null || true
    helm repo update linkerd-edge

    # Install with external Prometheus
    # Our existing Prometheus at monitoring/prometheus-kube-prometheus-stack-prometheus
    PROMETHEUS_URL="http://prometheus-kube-prometheus-stack-prometheus.monitoring.svc.cluster.local:9090"

    helm upgrade --install linkerd-viz linkerd-edge/linkerd-viz \
        --namespace linkerd-viz \
        --set prometheus.enabled=false \
        --set prometheusUrl="$PROMETHEUS_URL" \
        --set dashboard.enforcedHostRegexp=".*" \
        --set grafana.enabled=false \
        --set tap.enabled=true \
        --set tapInjector.enabled=true \
        --set metricsAPI.enabled=true \
        --wait \
        --timeout 5m

    log "Linkerd Viz installed"
}

# Create PodMonitor for Linkerd proxies
create_podmonitor() {
    log "Creating PodMonitor for Linkerd proxy metrics..."

    kubectl apply -f - <<EOF
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: linkerd-proxy
  namespace: monitoring
  labels:
    prometheus: kube-prometheus
spec:
  namespaceSelector:
    any: true
  selector:
    matchExpressions:
      - key: linkerd.io/proxy-deployment
        operator: Exists
  podMetricsEndpoints:
    - port: linkerd-admin
      relabelings:
        - sourceLabels: [__meta_kubernetes_pod_container_name]
          action: keep
          regex: linkerd-proxy
        - sourceLabels: [__meta_kubernetes_namespace]
          action: replace
          targetLabel: namespace
        - sourceLabels: [__meta_kubernetes_pod_name]
          action: replace
          targetLabel: pod
        - sourceLabels: [__meta_kubernetes_pod_label_linkerd_io_proxy_deployment]
          action: replace
          targetLabel: deployment
EOF

    log "PodMonitor created"
}

# Create ServiceMonitor for Linkerd control plane
create_servicemonitor() {
    log "Creating ServiceMonitor for Linkerd control plane..."

    kubectl apply -f - <<EOF
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: linkerd-control-plane
  namespace: monitoring
  labels:
    prometheus: kube-prometheus
spec:
  namespaceSelector:
    matchNames:
      - linkerd
  selector:
    matchLabels:
      linkerd.io/control-plane-component: ""
  endpoints:
    - port: admin-http
      interval: 30s
EOF

    log "ServiceMonitor created"
}

# Verify installation
verify_installation() {
    log "Verifying Linkerd Viz installation..."

    kubectl wait --for=condition=available --timeout=120s deployment -l linkerd.io/extension=viz -n linkerd-viz 2>/dev/null || warn "Some Viz components not ready"

    log "Linkerd Viz pods:"
    kubectl get pods -n linkerd-viz

    if command -v linkerd >/dev/null 2>&1; then
        linkerd viz check || warn "Some Linkerd Viz checks failed"
    fi
}

# Enable dashboard import
enable_dashboards() {
    log "To import Linkerd Grafana dashboards, run:"
    log "  ./scripts/import-grafana-dashboards.sh"
    log ""
    log "Or import manually from grafana.com:"
    log "  - 15474: Linkerd Top Line"
    log "  - 15475: Linkerd Deployment"
    log "  - 15481: Linkerd Route"
    log "  - 15484: Linkerd DaemonSet"
    log "  - 14274: Linkerd Service"
}

# Main
main() {
    local action="${1:-install}"

    case "$action" in
        install)
            check_prerequisites
            create_namespace
            install_viz
            create_podmonitor
            create_servicemonitor
            verify_installation
            enable_dashboards
            log ""
            log "Linkerd Viz installed successfully!"
            log ""
            log "Access the dashboard with:"
            log "  linkerd viz dashboard"
            ;;
        uninstall)
            log "Uninstalling Linkerd Viz..."
            helm uninstall linkerd-viz -n linkerd-viz 2>/dev/null || true
            kubectl delete namespace linkerd-viz 2>/dev/null || true
            kubectl delete podmonitor linkerd-proxy -n monitoring 2>/dev/null || true
            kubectl delete servicemonitor linkerd-control-plane -n monitoring 2>/dev/null || true
            log "Linkerd Viz uninstalled"
            ;;
        status)
            kubectl get pods -n linkerd-viz
            if command -v linkerd >/dev/null 2>&1; then
                linkerd viz check
            fi
            ;;
        *)
            echo "Usage: $0 {install|uninstall|status}"
            exit 1
            ;;
    esac
}

main "$@"
