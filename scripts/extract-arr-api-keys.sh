#!/usr/bin/env bash
set -euo pipefail

# Script to extract API keys from *arr applications and update Exportarr deployments
# Run this after you've completed the initial setup of Prowlarr, Sonarr, and Radarr

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=========================================="
echo "Extracting *arr API Keys"
echo "=========================================="
echo ""

# Function to extract API key from config.xml
extract_api_key() {
    local app=$1
    local pod=$(kubectl get pod -n media-dev -l app=$app -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)

    if [ -z "$pod" ]; then
        echo "  ❌ No pod found for $app"
        return 1
    fi

    local apikey=$(kubectl exec -n media-dev $pod -- cat /config/config.xml 2>/dev/null | grep "<ApiKey>" | sed 's/.*<ApiKey>\(.*\)<\/ApiKey>/\1/' | tr -d ' \n\r')

    if [ -z "$apikey" ]; then
        echo "  ⚠️  $app: Not configured yet (access http://$app.talos00 to complete setup)"
        return 1
    else
        echo "  ✅ $app: $apikey"
        echo "$apikey"
        return 0
    fi
}

# Extract API keys
echo "Extracting API keys from running pods..."
echo ""

PROWLARR_KEY=$(extract_api_key "prowlarr" || echo "")
SONARR_KEY=$(extract_api_key "sonarr" || echo "")
RADARR_KEY=$(extract_api_key "radarr" || echo "")
READARR_KEY=$(extract_api_key "readarr" || echo "")

echo ""

# Check if we got all keys
MISSING=0
[ -z "$PROWLARR_KEY" ] && MISSING=1
[ -z "$SONARR_KEY" ] && MISSING=1
[ -z "$RADARR_KEY" ] && MISSING=1

if [ $MISSING -eq 1 ]; then
    echo "=========================================="
    echo "⚠️  Some API keys are missing"
    echo "=========================================="
    echo ""
    echo "Please complete the initial setup for all *arr applications:"
    echo "  1. Access each app's web interface:"
    echo "     - Prowlarr: http://prowlarr.talos00"
    echo "     - Sonarr:   http://sonarr.talos00"
    echo "     - Radarr:   http://radarr.talos00"
    echo "     - Readarr:  http://readarr.talos00 (if working)"
    echo ""
    echo "  2. Complete the initial setup wizard for each"
    echo "  3. Run this script again"
    echo ""
    exit 1
fi

echo "=========================================="
echo "✅ All API keys extracted successfully"
echo "=========================================="
echo ""

# Create Secret with API keys
echo "Creating/updating arr-api-keys Secret..."

kubectl create secret generic arr-api-keys \
    --from-literal=prowlarr-api-key="$PROWLARR_KEY" \
    --from-literal=sonarr-api-key="$SONARR_KEY" \
    --from-literal=radarr-api-key="$RADARR_KEY" \
    ${READARR_KEY:+--from-literal=readarr-api-key="$READARR_KEY"} \
    --namespace=media-dev \
    --dry-run=client -o yaml | kubectl apply -f -

echo "✅ Secret created/updated"
echo ""

# Update Exportarr deployments to use the Secret
echo "Updating Exportarr deployments to use Secret..."

# Patch each deployment
for app in prowlarr sonarr radarr readarr; do
    if kubectl get deployment -n media-dev exportarr-$app &>/dev/null; then
        echo "  Updating exportarr-$app..."
        kubectl set env deployment/exportarr-$app -n media-dev \
            APIKEY="" \
            --from=secret/arr-api-keys \
            --keys=${app}-api-key \
            --prefix=API 2>/dev/null || true

        # Direct patch approach
        kubectl patch deployment exportarr-$app -n media-dev --type=json -p='[
            {
                "op": "replace",
                "path": "/spec/template/spec/containers/0/env",
                "value": [
                    {"name": "URL", "value": "http://'$app':'$([ "$app" = "prowlarr" ] && echo "9696" || [ "$app" = "sonarr" ] && echo "8989" || [ "$app" = "radarr" ] && echo "7878" || echo "8787")'"},
                    {"name": "PORT", "value": "9707"},
                    {"name": "APIKEY", "valueFrom": {"secretKeyRef": {"name": "arr-api-keys", "key": "'$app'-api-key"}}}
                ]
            }
        ]' 2>/dev/null || echo "    ⚠️  Failed to patch $app (may not exist)"
    fi
done

echo ""
echo "=========================================="
echo "✅ Exportarr Configuration Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Wait for Exportarr pods to restart and become healthy"
echo "  2. Check metrics are being scraped:"
echo "     kubectl port-forward -n media-dev svc/exportarr-sonarr 9707:9707"
echo "     curl http://localhost:9707/metrics"
echo ""
echo "  3. View in Prometheus:"
echo "     http://prometheus.talos00/targets"
echo ""
