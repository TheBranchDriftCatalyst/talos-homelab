#!/usr/bin/env bash
set -euo pipefail

# Import Grafana dashboards via API
#
# Usage:
#   # Option 1: Access via hostname (requires /etc/hosts entry or DNS)
#   ./scripts/import-grafana-dashboards.sh
#
#   # Option 2: Use port-forward (run in another terminal first)
#   kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80
#   GRAFANA_URL=http://localhost:3000 ./scripts/import-grafana-dashboards.sh

GRAFANA_URL="${GRAFANA_URL:-http://grafana.talos00}"
GRAFANA_USER="${GRAFANA_USER:-admin}"
GRAFANA_PASS="${GRAFANA_PASS:-admin}" # Change if you've updated the password

# Auto-detect Prometheus datasource UID from Grafana
echo "Detecting Prometheus datasource UID..."
PROMETHEUS_UID=$(curl -s -u "${GRAFANA_USER}:${GRAFANA_PASS}" "${GRAFANA_URL}/api/datasources" 2>/dev/null | \
  jq -r '.[] | select(.type == "prometheus") | .uid' 2>/dev/null | head -1)

if [ -z "$PROMETHEUS_UID" ]; then
  echo "Warning: Could not detect Prometheus UID, using default 'prometheus'"
  PROMETHEUS_UID="prometheus"
fi
echo "Using Prometheus datasource UID: $PROMETHEUS_UID"

# Dashboard IDs organized by category
# See docs/GRAFANA-DASHBOARDS.md for full documentation

# Core Kubernetes Dashboards
K8S_DASHBOARDS=(
  "315"    # Kubernetes Cluster Monitoring (classic)
  "15661"  # K8S Dashboard (comprehensive 2025)
  "15760"  # Kubernetes / Views / Pods
  "14623"  # Kubernetes Monitoring Overview
  "13646"  # Kubernetes PVC Dashboard
  "11454"  # Kubernetes Volumes Dashboard
)

# Infrastructure Dashboards
INFRA_DASHBOARDS=(
  "1860"   # Node Exporter Full
  "9628"   # PostgreSQL Database
)

# Traefik Ingress Dashboards
TRAEFIK_DASHBOARDS=(
  "17347"  # Traefik Official Kubernetes Dashboard
  "4475"   # Traefik v2 - alternative view
)

# ArgoCD GitOps Dashboards
ARGOCD_DASHBOARDS=(
  "14584"  # ArgoCD - Application Overview
  "19993"  # ArgoCD Operational Dashboard
)

# Linkerd Service Mesh Dashboards (requires linkerd-viz or external scrape)
LINKERD_DASHBOARDS=(
  "15474"  # Linkerd Top Line (overview)
  "15475"  # Linkerd Deployment
  "15481"  # Linkerd Route
  "15484"  # Linkerd DaemonSet
  "14274"  # Linkerd Service
)

# Combined list
DASHBOARDS=(
  "${K8S_DASHBOARDS[@]}"
  "${INFRA_DASHBOARDS[@]}"
  "${TRAEFIK_DASHBOARDS[@]}"
  "${ARGOCD_DASHBOARDS[@]}"
  # Note: Linkerd dashboards require linkerd-viz extension or prometheus scrape config
  # Uncomment after running: ./scripts/deploy-linkerd-viz.sh
  # "${LINKERD_DASHBOARDS[@]}"
)

echo "Importing Grafana dashboards..."
echo "================================"

for dashboard_id in "${DASHBOARDS[@]}"; do
  echo ""
  echo "Importing dashboard ID: $dashboard_id"

  # Download dashboard JSON
  dashboard_json=$(curl -s "https://grafana.com/api/dashboards/${dashboard_id}/revisions/latest/download" 2>/dev/null)

  if [ -z "$dashboard_json" ] || ! echo "$dashboard_json" | jq -e . >/dev/null 2>&1; then
    echo "  ✗ Failed to download dashboard $dashboard_id"
    continue
  fi

  # Replace datasource variables with actual datasource reference
  # This fixes the ${DS_PROMETHEUS} interpolation issue
  dashboard_json=$(echo "$dashboard_json" | jq --arg uid "$PROMETHEUS_UID" '
    # Replace templated datasource references with direct prometheus reference
    walk(if type == "object" and .datasource? then
      if (.datasource | type) == "object" and .datasource.uid? == "${DS_PROMETHEUS}" then
        .datasource = {"type": "prometheus", "uid": $uid}
      elif (.datasource | type) == "string" and .datasource == "${DS_PROMETHEUS}" then
        .datasource = {"type": "prometheus", "uid": $uid}
      elif (.datasource | type) == "string" and (.datasource | test("^\\$\\{")) then
        .datasource = {"type": "prometheus", "uid": $uid}
      else .
      end
    else . end)
  ')

  # Create import payload with multiple datasource input mappings
  # Handle various datasource variable names used by different dashboards
  import_payload=$(jq -n \
    --argjson dashboard "$dashboard_json" \
    --arg uid "$PROMETHEUS_UID" \
    '{
      dashboard: $dashboard,
      overwrite: true,
      inputs: [
        { name: "DS_PROMETHEUS", type: "datasource", pluginId: "prometheus", value: $uid },
        { name: "VAR_DATASOURCE", type: "datasource", pluginId: "prometheus", value: $uid },
        { name: "datasource", type: "datasource", pluginId: "prometheus", value: $uid },
        { name: "DS_OPENSHIFT_PROMETHEUS", type: "datasource", pluginId: "prometheus", value: $uid },
        { name: "DS__VICTORIAMETRICS-PROD-ALL", type: "datasource", pluginId: "prometheus", value: $uid },
        { name: "DS_VICTORIAMETRICS", type: "datasource", pluginId: "prometheus", value: $uid }
      ],
      folderId: 0
    }')

  # Import via API
  response=$(curl -s -X POST \
    -H "Content-Type: application/json" \
    -u "${GRAFANA_USER}:${GRAFANA_PASS}" \
    -d "$import_payload" \
    "${GRAFANA_URL}/api/dashboards/import" 2>/dev/null)

  if echo "$response" | jq -e '.imported == true' > /dev/null 2>&1; then
    dashboard_uid=$(echo "$response" | jq -r '.uid')
    dashboard_title=$(echo "$response" | jq -r '.title')
    echo "  ✓ Imported: $dashboard_title (UID: $dashboard_uid)"
  else
    error_msg=$(echo "$response" | jq -r '.message // "Unknown error"' 2>/dev/null || echo "$response")
    echo "  ✗ Failed to import dashboard $dashboard_id: $error_msg"
  fi
done

echo ""
echo "================================"
echo "Dashboard import completed!"
echo "Access Grafana at: $GRAFANA_URL"
