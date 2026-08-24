#!/usr/bin/env bash
#
# Trust Homelab CA - Add homelab-ca root certificate to OS trust store
#
# Extracts the homelab-ca root CA certificate from the cluster and adds it
# to the local trust store so browser warnings are eliminated for *.talos00 services.
#
# Usage: ./scripts/trust-homelab-ca.sh [--check]
#
# Options:
#   --check   Only check if the CA is already trusted, don't install
#
# NOTE: Linux support (update-ca-certificates) is not yet implemented.
#       Currently only macOS (security add-trusted-cert) is supported.
#       When adding Linux support, detect the OS and use:
#         - Debian/Ubuntu: cp cert to /usr/local/share/ca-certificates/ && update-ca-certificates
#         - RHEL/Fedora:   cp cert to /etc/pki/ca-trust/source/anchors/ && update-ca-trust
#

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

ok() { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
err() { echo -e "  ${RED}✗${NC} $1"; }

CA_SECRET_NAME="homelab-ca-secret"
CA_SECRET_NAMESPACE="cert-manager"
CA_CERT_LABEL="Homelab CA"
TEMP_CERT=""

cleanup() {
  if [[ -n "$TEMP_CERT" && -f "$TEMP_CERT" ]]; then
    rm -f "$TEMP_CERT"
  fi
}
trap cleanup EXIT

check_dependencies() {
  if ! command -v kubectl &> /dev/null; then
    err "kubectl not found. Install it or run: task deps:install"
    exit 1
  fi

  if [[ "$(uname -s)" != "Darwin" ]]; then
    # NOTE: Add Linux support here in the future.
    # Detect distro and use the appropriate ca-certificates update mechanism.
    err "This script currently only supports macOS."
    err "Linux support (update-ca-certificates / update-ca-trust) is planned but not yet implemented."
    exit 1
  fi
}

extract_ca_cert() {
  echo -e "${BOLD}Extracting CA certificate from cluster...${NC}"

  TEMP_CERT="$(mktemp /tmp/homelab-ca-XXXXXX.crt)"

  if ! kubectl get secret "$CA_SECRET_NAME" -n "$CA_SECRET_NAMESPACE" &> /dev/null; then
    err "Secret '$CA_SECRET_NAME' not found in namespace '$CA_SECRET_NAMESPACE'"
    err "Make sure cert-manager is running and the homelab-ca issuer is configured."
    exit 1
  fi

  kubectl get secret "$CA_SECRET_NAME" -n "$CA_SECRET_NAMESPACE" \
    -o jsonpath='{.data.ca\.crt}' | base64 -d > "$TEMP_CERT"

  if [[ ! -s "$TEMP_CERT" ]]; then
    # Fall back to tls.crt if ca.crt is empty (self-signed CA stores cert in tls.crt)
    kubectl get secret "$CA_SECRET_NAME" -n "$CA_SECRET_NAMESPACE" \
      -o jsonpath='{.data.tls\.crt}' | base64 -d > "$TEMP_CERT"
  fi

  if [[ ! -s "$TEMP_CERT" ]]; then
    err "Failed to extract certificate data from secret."
    exit 1
  fi

  ok "CA certificate extracted ($(wc -c < "$TEMP_CERT" | tr -d ' ') bytes)"
}

is_already_trusted() {
  # Check if a cert with this label is already in the system keychain
  security find-certificate -c "$CA_CERT_LABEL" /Library/Keychains/System.keychain &> /dev/null 2>&1
}

check_trust() {
  echo -e "${BOLD}Checking trust status...${NC}"

  if is_already_trusted; then
    ok "'$CA_CERT_LABEL' is already trusted in the system keychain."
    return 0
  else
    warn "'$CA_CERT_LABEL' is NOT in the system keychain."
    return 1
  fi
}

add_to_keychain() {
  echo -e "${BOLD}Adding CA certificate to macOS system keychain...${NC}"
  echo "  You may be prompted for your password (sudo required)."
  echo ""

  if is_already_trusted; then
    warn "Certificate already exists in keychain. Removing old entry first..."
    sudo security delete-certificate -c "$CA_CERT_LABEL" /Library/Keychains/System.keychain 2> /dev/null || true
  fi

  sudo security add-trusted-cert \
    -d \
    -r trustRoot \
    -k /Library/Keychains/System.keychain \
    "$TEMP_CERT"

  ok "CA certificate added to system keychain as trusted root."
  echo ""
  echo -e "  ${BOLD}All *.talos00 services using homelab-ca certs will now be trusted.${NC}"
  echo "  You may need to restart your browser for changes to take effect."
}

main() {
  local mode="${1:-}"

  check_dependencies

  if [[ "$mode" == "--check" ]]; then
    check_trust
    exit $?
  fi

  extract_ca_cert
  add_to_keychain
}

main "$@"
