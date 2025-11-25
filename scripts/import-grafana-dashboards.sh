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
GRAFANA_PASS="${GRAFANA_PASS:-admin}"  # Change if you've updated the password

DASHBOARDS=(
  "315"    # Kubernetes Cluster Monitoring
  "17347"  # Traefik Official Kubernetes Dashboard
  "1860"   # Node Exporter Full
  "9628"   # PostgreSQL Database
)

echo "Importing Grafana dashboards..."
echo "================================"

for dashboard_id in "${DASHBOARDS[@]}"; do
  echo ""
  echo "Importing dashboard ID: $dashboard_id"

  # Download dashboard JSON
  dashboard_json=$(curl -sf "https://grafana.com/api/dashboards/${dashboard_id}/revisions/latest/download")

  if [ -z "$dashboard_json" ]; then
    echo "  ✗ Failed to download dashboard $dashboard_id"
    continue
  fi

  # Create import payload
  import_payload=$(jq -n \
    --argjson dashboard "$dashboard_json" \
    '{
      dashboard: $dashboard,
      overwrite: true,
      inputs: [{
        name: "DS_PROMETHEUS",
        type: "datasource",
        pluginId: "prometheus",
        value: "Prometheus"
      }],
      folderId: 0
    }')

  # Import via API
  response=$(curl -sf -X POST \
    -H "Content-Type: application/json" \
    -u "${GRAFANA_USER}:${GRAFANA_PASS}" \
    -d "$import_payload" \
    "${GRAFANA_URL}/api/dashboards/import" 2>&1)

  if echo "$response" | jq -e '.status == "success"' > /dev/null 2>&1; then
    dashboard_uid=$(echo "$response" | jq -r '.uid')
    echo "  ✓ Successfully imported dashboard $dashboard_id (UID: $dashboard_uid)"
  else
    echo "  ✗ Failed to import dashboard $dashboard_id"
    echo "  Response: $response"
  fi
done

echo ""
echo "================================"
echo "Dashboard import completed!"
echo "Access Grafana at: $GRAFANA_URL"
