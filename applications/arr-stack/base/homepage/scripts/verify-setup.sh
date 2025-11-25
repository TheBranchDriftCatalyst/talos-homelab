#!/bin/bash
# Script to verify the Homepage ExternalSecret and deployment setup

set -e

NAMESPACE="media-dev"
EXTERNALSECRET="homepage-secrets"
SECRET="homepage-secrets"
DEPLOYMENT="homepage"

echo "🔍 Verifying Homepage Setup..."
echo ""

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print status
print_status() {
    local status=$1
    local message=$2
    if [ "$status" = "ok" ]; then
        echo -e "${GREEN}✅${NC} $message"
    elif [ "$status" = "warn" ]; then
        echo -e "${YELLOW}⚠️${NC}  $message"
    else
        echo -e "${RED}❌${NC} $message"
    fi
}

# Check namespace exists
echo "Checking namespace..."
if kubectl get namespace "$NAMESPACE" &> /dev/null; then
    print_status "ok" "Namespace '$NAMESPACE' exists"
else
    print_status "error" "Namespace '$NAMESPACE' not found"
    exit 1
fi

echo ""

# Check ExternalSecret exists
echo "Checking ExternalSecret..."
if kubectl get externalsecret "$EXTERNALSECRET" -n "$NAMESPACE" &> /dev/null; then
    print_status "ok" "ExternalSecret '$EXTERNALSECRET' exists"

    # Check ExternalSecret status
    STATUS=$(kubectl get externalsecret "$EXTERNALSECRET" -n "$NAMESPACE" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')
    if [ "$STATUS" = "True" ]; then
        print_status "ok" "ExternalSecret is Ready"
    else
        print_status "error" "ExternalSecret is not Ready"
        echo ""
        echo "ExternalSecret status:"
        kubectl get externalsecret "$EXTERNALSECRET" -n "$NAMESPACE" -o jsonpath='{.status.conditions[?(@.type=="Ready")].message}'
        echo ""
        echo ""
        echo "Full status:"
        kubectl describe externalsecret "$EXTERNALSECRET" -n "$NAMESPACE"
        exit 1
    fi
else
    print_status "error" "ExternalSecret '$EXTERNALSECRET' not found"
    echo ""
    echo "Create it with:"
    echo "  kubectl apply -k applications/arr-stack/base/homepage/"
    exit 1
fi

echo ""

# Check Secret exists
echo "Checking Secret..."
if kubectl get secret "$SECRET" -n "$NAMESPACE" &> /dev/null; then
    print_status "ok" "Secret '$SECRET' exists"

    # Check secret has expected keys
    EXPECTED_KEYS=(
        "HOMEPAGE_VAR_SONARR_KEY"
        "HOMEPAGE_VAR_RADARR_KEY"
        "HOMEPAGE_VAR_READARR_KEY"
        "HOMEPAGE_VAR_PROWLARR_KEY"
        "HOMEPAGE_VAR_PLEX_KEY"
        "HOMEPAGE_VAR_JELLYFIN_KEY"
        "HOMEPAGE_VAR_OVERSEERR_KEY"
        "HOMEPAGE_VAR_ARGOCD_KEY"
        "HOMEPAGE_VAR_GRAFANA_USER"
        "HOMEPAGE_VAR_GRAFANA_PASS"
    )

    MISSING_KEYS=()
    for key in "${EXPECTED_KEYS[@]}"; do
        if kubectl get secret "$SECRET" -n "$NAMESPACE" -o jsonpath="{.data.$key}" &> /dev/null; then
            if [ -z "$(kubectl get secret "$SECRET" -n "$NAMESPACE" -o jsonpath="{.data.$key}")" ]; then
                MISSING_KEYS+=("$key")
            fi
        else
            MISSING_KEYS+=("$key")
        fi
    done

    if [ ${#MISSING_KEYS[@]} -eq 0 ]; then
        print_status "ok" "All expected secret keys present (${#EXPECTED_KEYS[@]})"
    else
        print_status "warn" "Missing ${#MISSING_KEYS[@]} secret keys: ${MISSING_KEYS[*]}"
        echo ""
        echo "These fields are missing from the 1Password item 'arr-stack-credentials'"
    fi
else
    print_status "error" "Secret '$SECRET' not found (ExternalSecret should create it)"
    exit 1
fi

echo ""

# Check Deployment exists
echo "Checking Deployment..."
if kubectl get deployment "$DEPLOYMENT" -n "$NAMESPACE" &> /dev/null; then
    print_status "ok" "Deployment '$DEPLOYMENT' exists"

    # Check if deployment is ready
    READY=$(kubectl get deployment "$DEPLOYMENT" -n "$NAMESPACE" -o jsonpath='{.status.conditions[?(@.type=="Available")].status}')
    if [ "$READY" = "True" ]; then
        print_status "ok" "Deployment is Available"
    else
        print_status "error" "Deployment is not Available"
        echo ""
        echo "Deployment status:"
        kubectl get deployment "$DEPLOYMENT" -n "$NAMESPACE"
        echo ""
        echo "Pod status:"
        kubectl get pods -n "$NAMESPACE" -l app=homepage
    fi

    # Check if deployment uses the secret
    USES_SECRET=$(kubectl get deployment "$DEPLOYMENT" -n "$NAMESPACE" -o jsonpath='{.spec.template.spec.containers[0].envFrom[*].secretRef.name}' | grep -c "$SECRET" || true)
    if [ "$USES_SECRET" -gt 0 ]; then
        print_status "ok" "Deployment configured to use secret"
    else
        print_status "warn" "Deployment not configured to use secret (check envFrom)"
    fi
else
    print_status "error" "Deployment '$DEPLOYMENT' not found"
    echo ""
    echo "Deploy it with:"
    echo "  kubectl apply -k applications/arr-stack/base/homepage/"
    exit 1
fi

echo ""

# Check ConfigMaps
echo "Checking ConfigMaps..."
if kubectl get configmap homepage-config -n "$NAMESPACE" &> /dev/null; then
    print_status "ok" "ConfigMap 'homepage-config' exists"
else
    print_status "error" "ConfigMap 'homepage-config' not found"
fi

if kubectl get configmap homepage-services -n "$NAMESPACE" &> /dev/null; then
    print_status "ok" "ConfigMap 'homepage-services' exists"
else
    print_status "error" "ConfigMap 'homepage-services' not found"
fi

echo ""

# Check Service
echo "Checking Service..."
if kubectl get service "$DEPLOYMENT" -n "$NAMESPACE" &> /dev/null; then
    print_status "ok" "Service '$DEPLOYMENT' exists"
    PORT=$(kubectl get service "$DEPLOYMENT" -n "$NAMESPACE" -o jsonpath='{.spec.ports[0].port}')
    print_status "ok" "Service port: $PORT"
else
    print_status "error" "Service '$DEPLOYMENT' not found"
fi

echo ""

# Check IngressRoute
echo "Checking IngressRoute..."
if kubectl get ingressroute "$DEPLOYMENT" -n "$NAMESPACE" &> /dev/null; then
    print_status "ok" "IngressRoute '$DEPLOYMENT' exists"
    HOST=$(kubectl get ingressroute "$DEPLOYMENT" -n "$NAMESPACE" -o jsonpath='{.spec.routes[0].match}' | sed 's/Host(`\(.*\)`)/\1/')
    print_status "ok" "Accessible at: http://$HOST"
else
    print_status "warn" "IngressRoute '$DEPLOYMENT' not found (optional)"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Get pod logs if available
if kubectl get pods -n "$NAMESPACE" -l app=homepage &> /dev/null; then
    POD=$(kubectl get pods -n "$NAMESPACE" -l app=homepage -o jsonpath='{.items[0].metadata.name}')
    if [ -n "$POD" ]; then
        echo "Recent logs from pod '$POD':"
        echo ""
        kubectl logs -n "$NAMESPACE" "$POD" --tail=20
    fi
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
print_status "ok" "Setup verification complete!"
echo ""
echo "If everything is green, you can access Homepage at:"
echo "  http://homepage.talos00"
