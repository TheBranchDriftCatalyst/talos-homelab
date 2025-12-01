#!/bin/bash
# Simple Grafana dashboard provisioning script
# Usage: ./scripts/provision-grafana-dashboard.sh <dashboard-id>

set -e

DASHBOARD_ID="${1}"
NAMESPACE="monitoring"
GRAFANA_POD=$(kubectl get pod -n $NAMESPACE -l app.kubernetes.io/name=grafana -o jsonpath='{.items[0].metadata.name}')
GRAFANA_PASSWORD=$(kubectl get secret -n $NAMESPACE kube-prometheus-stack-grafana -o jsonpath='{.data.admin-password}' | base64 -d)

if [ -z "$DASHBOARD_ID" ]; then
  echo "Usage: $0 <dashboard-id>"
  echo "Example: $0 14588  (VPA Recommendations dashboard)"
  exit 1
fi

echo "Provisioning dashboard ID: $DASHBOARD_ID"
echo "Grafana pod: $GRAFANA_POD"

# Download dashboard JSON and save locally
echo "Downloading dashboard $DASHBOARD_ID from Grafana.com..."
DASHBOARD_JSON=$(curl -s "https://grafana.com/api/dashboards/$DASHBOARD_ID/revisions/latest/download")

# Create import payload
IMPORT_PAYLOAD=$(cat <<EOF
{
  "dashboard": $DASHBOARD_JSON,
  "overwrite": true,
  "inputs": [{
    "name": "DS_PROMETHEUS",
    "type": "datasource",
    "pluginId": "prometheus",
    "value": "Prometheus"
  }],
  "folderId": 0
}
EOF
)

# Import via kubectl exec
echo "Importing dashboard to Grafana..."
RESULT=$(kubectl exec -n $NAMESPACE $GRAFANA_POD -- sh -c "
  curl -s -X POST http://admin:$GRAFANA_PASSWORD@localhost:3000/api/dashboards/import \
    -H 'Content-Type: application/json' \
    -d '$IMPORT_PAYLOAD'
")

if echo "$RESULT" | grep -q '"uid"'; then
  echo "Success! Dashboard imported."
  echo "$RESULT"
else
  echo "Error importing dashboard:"
  echo "$RESULT"
  exit 1
fi

echo ""
echo "Dashboard provisioned successfully!"
echo "Access it at: http://grafana.talos00"
