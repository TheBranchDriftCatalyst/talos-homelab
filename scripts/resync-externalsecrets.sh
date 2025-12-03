#!/usr/bin/env bash
# Force resync all ExternalSecrets
#
# Usage: ./scripts/resync-1password-secrets.sh [--onepassword-only]
#
# Options:
#   --onepassword-only   Only resync ExternalSecrets using 1Password store

set -euo pipefail

TIMESTAMP=$(date +%s)
ONEPASSWORD_ONLY=false

if [[ "${1:-}" == "--onepassword-only" ]]; then
    ONEPASSWORD_ONLY=true
fi

if [[ "$ONEPASSWORD_ONLY" == "true" ]]; then
    echo "Finding ExternalSecrets using 1Password..."
    SECRETS=$(kubectl get externalsecrets -A -o json | jq -r '.items[] | select(.spec.secretStoreRef.name == "onepassword") | "\(.metadata.namespace)/\(.metadata.name)"')
else
    echo "Finding all ExternalSecrets..."
    SECRETS=$(kubectl get externalsecrets -A -o json | jq -r '.items[] | "\(.metadata.namespace)/\(.metadata.name)"')
fi

if [[ -z "$SECRETS" ]]; then
    echo "No ExternalSecrets found"
    exit 0
fi

echo ""
echo "Forcing resync on:"
echo "$SECRETS" | while read -r secret; do
    echo "  - $secret"
done
echo ""

# Annotate each ExternalSecret to force resync
echo "$SECRETS" | while read -r secret; do
    NAMESPACE=$(echo "$secret" | cut -d'/' -f1)
    NAME=$(echo "$secret" | cut -d'/' -f2)

    echo "Resyncing $NAMESPACE/$NAME..."
    kubectl annotate externalsecret "$NAME" -n "$NAMESPACE" force-sync="$TIMESTAMP" --overwrite
done

echo ""
echo "Done! All ExternalSecrets have been resynced."
echo ""
echo "To verify sync status:"
echo "  kubectl get externalsecrets -A"
