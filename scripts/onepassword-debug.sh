#!/usr/bin/env bash
# 1Password SecretStore Debug Script
# Tests connectivity and queries secrets from 1Password Connect via External Secrets Operator

set -euo pipefail

# Color codes
RESET='\033[0m'
BOLD='\033[1m'
GREEN='\033[92m'
YELLOW='\033[93m'
RED='\033[91m'
CYAN='\033[96m'
DIM='\033[2m'

# Configuration
NAMESPACE="${NAMESPACE:-external-secrets}"
SECRET_STORE_NAME="${SECRET_STORE_NAME:-onepassword}"
CLUSTER_SECRET_STORE_NAME="${CLUSTER_SECRET_STORE_NAME:-onepassword}"
ONEPASSWORD_CONNECT_SVC="${ONEPASSWORD_CONNECT_SVC:-onepassword-connect}"

echo -e "${CYAN}${BOLD}"
cat << 'EOF'
 ██████  ███████      ██████  ███████ ██████  ██    ██  ██████
██  ████ ██          ██    ██ ██      ██   ██ ██    ██ ██
██ ██ ██ █████ █████ ██    ██ █████   ██████  ██    ██ ██   ███
████  ██ ██          ██    ██ ██      ██   ██ ██    ██ ██    ██
 ██████  ███████      ██████  ███████ ██████   ██████   ██████
           External Secrets + 1Password Debug Tool
EOF
echo -e "${RESET}"
echo ""

# Helper functions
check_success() {
  if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${RESET} $1"
  else
    echo -e "${RED}✗${RESET} $1"
    return 1
  fi
}

print_header() {
  echo -e "${CYAN}${BOLD}▸ $1${RESET}"
}

print_info() {
  echo -e "  ${DIM}$1${RESET}"
}

print_value() {
  echo -e "  ${GREEN}$1${RESET}"
}

# Check prerequisites
print_header "CHECKING PREREQUISITES"

if ! command -v kubectl &> /dev/null; then
  echo -e "${RED}✗ kubectl not found${RESET}"
  exit 1
fi
check_success "kubectl installed"

if ! command -v jq &> /dev/null; then
  echo -e "${YELLOW}⚠ jq not found (optional, but recommended)${RESET}"
  echo -e "  ${DIM}Install with: brew install jq${RESET}"
fi

echo ""

# Check cluster connectivity
print_header "CLUSTER CONNECTIVITY"

if kubectl cluster-info &> /dev/null; then
  check_success "Connected to Kubernetes cluster"
  CONTEXT=$(kubectl config current-context)
  print_info "Context: $CONTEXT"
else
  echo -e "${RED}✗ Cannot connect to cluster${RESET}"
  exit 1
fi

echo ""

# Check namespace
print_header "NAMESPACE CHECK"

if kubectl get namespace "$NAMESPACE" &> /dev/null; then
  check_success "Namespace '$NAMESPACE' exists"
else
  echo -e "${RED}✗ Namespace '$NAMESPACE' not found${RESET}"
  echo -e "  ${DIM}Create with: kubectl create namespace $NAMESPACE${RESET}"
  exit 1
fi

echo ""

# Check External Secrets Operator
print_header "EXTERNAL SECRETS OPERATOR"

if kubectl get deployment -n "$NAMESPACE" external-secrets &> /dev/null 2>&1; then
  check_success "ESO deployment found"

  # Check if running
  READY=$(kubectl get deployment -n "$NAMESPACE" external-secrets -o jsonpath='{.status.readyReplicas}' 2> /dev/null || echo "0")
  DESIRED=$(kubectl get deployment -n "$NAMESPACE" external-secrets -o jsonpath='{.spec.replicas}' 2> /dev/null || echo "0")

  if [ "$READY" = "$DESIRED" ] && [ "$READY" != "0" ]; then
    check_success "ESO is running ($READY/$DESIRED replicas ready)"
  else
    echo -e "${YELLOW}⚠ ESO not ready yet ($READY/$DESIRED replicas)${RESET}"
  fi

  # Show version
  VERSION=$(kubectl get deployment -n "$NAMESPACE" external-secrets -o jsonpath='{.spec.template.spec.containers[0].image}' | cut -d: -f2)
  print_info "Version: $VERSION"
else
  echo -e "${RED}✗ ESO deployment not found${RESET}"
  echo -e "  ${DIM}Deploy with: tilt up${RESET}"
  exit 1
fi

# Check CRDs
print_info "Checking CRDs..."
CRDS=(
  "secretstores.external-secrets.io"
  "clustersecretstores.external-secrets.io"
  "externalsecrets.external-secrets.io"
)

for crd in "${CRDS[@]}"; do
  if kubectl get crd "$crd" &> /dev/null; then
    echo -e "  ${GREEN}✓${RESET} $crd"
  else
    echo -e "  ${RED}✗${RESET} $crd"
  fi
done

echo ""

# Check 1Password Connect
print_header "1PASSWORD CONNECT"

if kubectl get deployment -n "$NAMESPACE" "$ONEPASSWORD_CONNECT_SVC" &> /dev/null 2>&1; then
  check_success "1Password Connect deployment found"

  # Check if running
  READY=$(kubectl get deployment -n "$NAMESPACE" "$ONEPASSWORD_CONNECT_SVC" -o jsonpath='{.status.readyReplicas}' 2> /dev/null || echo "0")
  DESIRED=$(kubectl get deployment -n "$NAMESPACE" "$ONEPASSWORD_CONNECT_SVC" -o jsonpath='{.spec.replicas}' 2> /dev/null || echo "0")

  if [ "$READY" = "$DESIRED" ] && [ "$READY" != "0" ]; then
    check_success "1Password Connect is running ($READY/$DESIRED replicas ready)"
  else
    echo -e "${YELLOW}⚠ 1Password Connect not ready ($READY/$DESIRED replicas)${RESET}"
  fi
else
  echo -e "${YELLOW}⚠ 1Password Connect not deployed${RESET}"
  echo -e "  ${DIM}Deploy with: kubectl apply -k infrastructure/base/external-secrets/onepassword-connect${RESET}"
  echo -e "  ${DIM}Setup first: ./scripts/setup-1password-connect.sh${RESET}"
fi

# Check secrets
print_info "Checking required secrets..."
SECRETS=(
  "onepassword-connect-secret"
  "onepassword-connect-token"
)

for secret in "${SECRETS[@]}"; do
  if kubectl get secret -n "$NAMESPACE" "$secret" &> /dev/null 2>&1; then
    echo -e "  ${GREEN}✓${RESET} $secret"
  else
    echo -e "  ${YELLOW}⚠${RESET} $secret (not found)"
  fi
done

# Check service
if kubectl get service -n "$NAMESPACE" "$ONEPASSWORD_CONNECT_SVC" &> /dev/null 2>&1; then
  SVC_IP=$(kubectl get service -n "$NAMESPACE" "$ONEPASSWORD_CONNECT_SVC" -o jsonpath='{.spec.clusterIP}')
  SVC_PORT=$(kubectl get service -n "$NAMESPACE" "$ONEPASSWORD_CONNECT_SVC" -o jsonpath='{.spec.ports[0].port}')
  print_info "Service: $SVC_IP:$SVC_PORT"
fi

echo ""

# Check SecretStores
print_header "SECRET STORES"

# Check SecretStore
if kubectl get secretstore -n "$NAMESPACE" "$SECRET_STORE_NAME" &> /dev/null 2>&1; then
  check_success "SecretStore '$SECRET_STORE_NAME' found"

  # Get status
  if command -v jq &> /dev/null; then
    STATUS=$(kubectl get secretstore -n "$NAMESPACE" "$SECRET_STORE_NAME" -o json | jq -r '.status.conditions[0].status // "Unknown"')
    REASON=$(kubectl get secretstore -n "$NAMESPACE" "$SECRET_STORE_NAME" -o json | jq -r '.status.conditions[0].reason // "Unknown"')
    MESSAGE=$(kubectl get secretstore -n "$NAMESPACE" "$SECRET_STORE_NAME" -o json | jq -r '.status.conditions[0].message // "No message"')

    if [ "$STATUS" = "True" ]; then
      check_success "SecretStore status: Ready"
    else
      echo -e "  ${YELLOW}⚠${RESET} Status: $STATUS"
      print_info "Reason: $REASON"
      print_info "Message: $MESSAGE"
    fi
  fi
else
  echo -e "${YELLOW}⚠ SecretStore '$SECRET_STORE_NAME' not found${RESET}"
  echo -e "  ${DIM}Create with: kubectl apply -k infrastructure/base/external-secrets/secretstores${RESET}"
fi

# Check ClusterSecretStore
if kubectl get clustersecretstore "$CLUSTER_SECRET_STORE_NAME" &> /dev/null 2>&1; then
  check_success "ClusterSecretStore '$CLUSTER_SECRET_STORE_NAME' found"

  # Get status
  if command -v jq &> /dev/null; then
    STATUS=$(kubectl get clustersecretstore "$CLUSTER_SECRET_STORE_NAME" -o json | jq -r '.status.conditions[0].status // "Unknown"')
    REASON=$(kubectl get clustersecretstore "$CLUSTER_SECRET_STORE_NAME" -o json | jq -r '.status.conditions[0].reason // "Unknown"')

    if [ "$STATUS" = "True" ]; then
      check_success "ClusterSecretStore status: Ready"
    else
      echo -e "  ${YELLOW}⚠${RESET} Status: $STATUS"
      print_info "Reason: $REASON"
    fi
  fi
else
  echo -e "${YELLOW}⚠ ClusterSecretStore '$CLUSTER_SECRET_STORE_NAME' not found${RESET}"
fi

echo ""

# Check ExternalSecrets
print_header "EXTERNAL SECRETS"

EXTERNAL_SECRETS=$(kubectl get externalsecrets -n "$NAMESPACE" -o name 2> /dev/null | wc -l | tr -d ' ')

if [ "$EXTERNAL_SECRETS" -gt 0 ]; then
  echo -e "${GREEN}✓${RESET} Found $EXTERNAL_SECRETS ExternalSecret(s)"

  kubectl get externalsecrets -n "$NAMESPACE" -o custom-columns=NAME:.metadata.name,STORE:.spec.secretStoreRef.name,STATUS:.status.conditions[0].reason,SYNCED:.status.syncedResourceVersion 2> /dev/null | while IFS= read -r line; do
    print_info "$line"
  done
else
  echo -e "${YELLOW}⚠ No ExternalSecrets found${RESET}"
  echo -e "  ${DIM}Create a test ExternalSecret to validate SecretStore${RESET}"
fi

echo ""

# Test connectivity (if 1Password Connect is running)
print_header "CONNECTIVITY TEST"

if kubectl get deployment -n "$NAMESPACE" "$ONEPASSWORD_CONNECT_SVC" &> /dev/null 2>&1; then
  READY=$(kubectl get deployment -n "$NAMESPACE" "$ONEPASSWORD_CONNECT_SVC" -o jsonpath='{.status.readyReplicas}' 2> /dev/null || echo "0")

  if [ "$READY" != "0" ]; then
    print_info "Testing connection to 1Password Connect..."

    # Port forward in background
    kubectl port-forward -n "$NAMESPACE" "svc/$ONEPASSWORD_CONNECT_SVC" 8080:8080 > /dev/null 2>&1 &
    PF_PID=$!
    sleep 2

    # Test health endpoint
    if curl -s -f http://localhost:8080/health > /dev/null 2>&1; then
      check_success "1Password Connect API is reachable"
    else
      echo -e "${YELLOW}⚠ Cannot reach 1Password Connect API${RESET}"
    fi

    # Cleanup port forward
    kill $PF_PID 2> /dev/null || true
  else
    echo -e "${YELLOW}⚠ 1Password Connect not running, skipping connectivity test${RESET}"
  fi
else
  echo -e "${YELLOW}⚠ 1Password Connect not deployed, skipping connectivity test${RESET}"
fi

echo ""

# Show ESO logs (last 10 lines)
print_header "RECENT ESO LOGS"

kubectl logs -n "$NAMESPACE" -l app.kubernetes.io/name=external-secrets --tail=10 2> /dev/null || echo -e "${YELLOW}⚠ No logs available${RESET}"

echo ""

# Summary and recommendations
print_header "SUMMARY & RECOMMENDATIONS"

echo ""
if kubectl get deployment -n "$NAMESPACE" external-secrets &> /dev/null 2>&1; then
  if kubectl get secretstore -n "$NAMESPACE" "$SECRET_STORE_NAME" &> /dev/null 2>&1; then
    echo -e "${GREEN}✓ External Secrets Operator is deployed and SecretStore exists${RESET}"
    echo ""
    echo -e "${CYAN}Next steps:${RESET}"
    echo -e "  1. Create a test ExternalSecret:"
    echo -e "     ${DIM}kubectl apply -f infrastructure/base/external-secrets/secretstores/example-externalsecret.yaml${RESET}"
    echo -e "  2. Check if secret was created:"
    echo -e "     ${DIM}kubectl get secret -n $NAMESPACE example-secret${RESET}"
    echo -e "  3. View ExternalSecret status:"
    echo -e "     ${DIM}kubectl describe externalsecret -n $NAMESPACE example-secret${RESET}"
  else
    echo -e "${YELLOW}⚠ ESO is deployed but SecretStore not configured${RESET}"
    echo ""
    echo -e "${CYAN}Next steps:${RESET}"
    echo -e "  1. Setup 1Password Connect:"
    echo -e "     ${DIM}./scripts/setup-1password-connect.sh${RESET}"
    echo -e "  2. Deploy SecretStores:"
    echo -e "     ${DIM}kubectl apply -k infrastructure/base/external-secrets/secretstores${RESET}"
  fi
else
  echo -e "${RED}✗ External Secrets Operator not deployed${RESET}"
  echo ""
  echo -e "${CYAN}Next steps:${RESET}"
  echo -e "  1. Start Tilt to deploy ESO:"
  echo -e "     ${DIM}tilt up${RESET}"
fi

echo ""
