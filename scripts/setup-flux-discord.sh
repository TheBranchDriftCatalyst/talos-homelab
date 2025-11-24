#!/usr/bin/env bash
# Setup Flux notifications to Discord
set -euo pipefail

# Colors
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
RESET='\033[0m'

echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${CYAN}  Flux Discord Notifications Setup${RESET}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""

# Check if webhook URL is provided
if [ $# -eq 0 ]; then
    echo -e "${YELLOW}Usage: $0 <discord-webhook-url>${RESET}"
    echo ""
    echo "To get a Discord webhook URL:"
    echo "  1. Go to your Discord server"
    echo "  2. Server Settings → Integrations → Webhooks"
    echo "  3. Create New Webhook or copy existing one"
    echo "  4. Copy the Webhook URL"
    echo ""
    echo "Example:"
    echo "  $0 https://discord.com/api/webhooks/123456789/abcdef..."
    exit 1
fi

WEBHOOK_URL="$1"

# Validate webhook URL
if [[ ! "$WEBHOOK_URL" =~ ^https://discord.com/api/webhooks/ ]]; then
    echo -e "${RED}✗ Invalid Discord webhook URL${RESET}"
    echo "  URL should start with: https://discord.com/api/webhooks/"
    exit 1
fi

echo -e "${CYAN}→ Creating Discord webhook secret...${RESET}"

# Create or update the secret
kubectl create secret generic discord-webhook \
    --from-literal=address="${WEBHOOK_URL}" \
    --namespace=flux-system \
    --dry-run=client -o yaml | kubectl apply -f -

echo -e "${GREEN}✓ Secret created${RESET}"
echo ""

echo -e "${CYAN}→ Applying Flux notification configuration...${RESET}"

# Apply the notification resources
kubectl apply -k infrastructure/base/flux-notifications/

echo -e "${GREEN}✓ Flux notifications configured${RESET}"
echo ""

echo -e "${CYAN}→ Verifying configuration...${RESET}"

# Wait a moment for resources to be created
sleep 3

# Check provider
if kubectl get provider discord -n flux-system &>/dev/null; then
    PROVIDER_STATUS=$(kubectl get provider discord -n flux-system -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')
    if [ "$PROVIDER_STATUS" = "True" ]; then
        echo -e "${GREEN}✓ Discord provider is ready${RESET}"
    else
        echo -e "${YELLOW}⚠ Discord provider status: ${PROVIDER_STATUS}${RESET}"
        echo "  Check logs: kubectl logs -n flux-system -l app=notification-controller"
    fi
else
    echo -e "${RED}✗ Discord provider not found${RESET}"
fi

# Check alerts
ALERT_COUNT=$(kubectl get alerts -n flux-system --no-headers 2>/dev/null | wc -l | tr -d ' ')
echo -e "${GREEN}✓ ${ALERT_COUNT} alerts configured${RESET}"

echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${GREEN}✓ Setup complete!${RESET}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
echo "You should now receive Discord notifications for:"
echo "  • GitRepository changes"
echo "  • Kustomization updates"
echo "  • HelmRelease deployments"
echo "  • Critical errors"
echo ""
echo "To test, trigger a Flux reconciliation:"
echo "  flux reconcile kustomization flux-system"
echo ""
echo "To view notification logs:"
echo "  kubectl logs -n flux-system -l app=notification-controller -f"
