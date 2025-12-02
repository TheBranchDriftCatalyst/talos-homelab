#!/usr/bin/env bash
#
# update-hosts.sh - Idempotently update /etc/hosts with Traefik IngressRoute hostnames
#
# This script fetches all IngressRoute hosts from the cluster and updates
# /etc/hosts with a fenced block containing the host mappings.
#
# Usage:
#   ./scripts/update-hosts.sh           # Update /etc/hosts (requires sudo)
#   ./scripts/update-hosts.sh --dry-run # Show what would be added without modifying
#   ./scripts/update-hosts.sh --print   # Just print the hosts block to stdout
#

set -euo pipefail

# Configuration
CLUSTER_IP="${TALOS_NODE:-192.168.1.54}"
FENCE_START="# >>> TALOS-HOMELAB HOSTS - DO NOT EDIT MANUALLY >>>"
FENCE_END="# <<< TALOS-HOMELAB HOSTS <<<"
HOSTS_FILE="/etc/hosts"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}ℹ${NC} $*"; }
log_success() { echo -e "${GREEN}✓${NC} $*"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $*"; }
log_error() { echo -e "${RED}✗${NC} $*" >&2; }

# Parse arguments
DRY_RUN=false
PRINT_ONLY=false

for arg in "$@"; do
    case $arg in
        --dry-run|-n)
            DRY_RUN=true
            ;;
        --print|-p)
            PRINT_ONLY=true
            ;;
        --help|-h)
            echo "Usage: $0 [--dry-run|--print]"
            echo ""
            echo "Options:"
            echo "  --dry-run, -n  Show what would be changed without modifying /etc/hosts"
            echo "  --print, -p    Just print the hosts block to stdout"
            echo "  --help, -h     Show this help message"
            echo ""
            echo "Environment:"
            echo "  TALOS_NODE     Cluster IP address (default: 192.168.1.54)"
            exit 0
            ;;
    esac
done

# Check for kubectl
if ! command -v kubectl &> /dev/null; then
    log_error "kubectl is required but not installed"
    exit 1
fi

# Check cluster connectivity
if ! kubectl cluster-info &> /dev/null; then
    log_error "Cannot connect to Kubernetes cluster. Check your kubeconfig."
    exit 1
fi

# Fetch all IngressRoute hosts from the cluster
log_info "Fetching IngressRoute hostnames from cluster..."

# Get hosts from Traefik IngressRoutes (traefik.io/v1alpha1 and traefik.containo.us/v1alpha1)
# Extract Host(`hostname`) patterns using jq and sed (macOS compatible)
HOSTS=$(kubectl get ingressroutes.traefik.io --all-namespaces -o json 2>/dev/null | \
    jq -r '.items[].spec.routes[].match // empty' 2>/dev/null | \
    sed -n 's/.*Host(`\([^`]*\)`).*/\1/p' | \
    sort -u || true)

# Also check for traefik.containo.us API version (older)
HOSTS_OLD=$(kubectl get ingressroutes.traefik.containo.us --all-namespaces -o json 2>/dev/null | \
    jq -r '.items[].spec.routes[].match // empty' 2>/dev/null | \
    sed -n 's/.*Host(`\([^`]*\)`).*/\1/p' | \
    sort -u 2>/dev/null || true)

# Also get standard Kubernetes Ingress hosts
HOSTS_INGRESS=$(kubectl get ingress --all-namespaces -o json 2>/dev/null | \
    jq -r '.items[].spec.rules[].host // empty' 2>/dev/null | \
    sort -u || true)

# Combine all hosts
ALL_HOSTS=$(echo -e "${HOSTS}\n${HOSTS_OLD}\n${HOSTS_INGRESS}" | grep -v '^$' | sort -u)

if [[ -z "$ALL_HOSTS" ]]; then
    log_warn "No IngressRoute or Ingress hosts found in the cluster"
    exit 0
fi

# Count hosts
HOST_COUNT=$(echo "$ALL_HOSTS" | wc -l | tr -d ' ')
log_info "Found ${HOST_COUNT} unique hostnames"

# Generate the hosts block
generate_hosts_block() {
    echo "$FENCE_START"
    echo "# Generated: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "# Cluster IP: $CLUSTER_IP"
    echo "# Hostnames: $HOST_COUNT"
    echo "#"
    while IFS= read -r host; do
        if [[ -n "$host" ]]; then
            printf "%-16s %s\n" "$CLUSTER_IP" "$host"
        fi
    done <<< "$ALL_HOSTS"
    echo "$FENCE_END"
}

HOSTS_BLOCK=$(generate_hosts_block)

# Print only mode
if [[ "$PRINT_ONLY" == true ]]; then
    echo "$HOSTS_BLOCK"
    exit 0
fi

# Show what will be added
echo ""
echo "Hosts block to be added/updated:"
echo "─────────────────────────────────"
echo "$HOSTS_BLOCK"
echo "─────────────────────────────────"
echo ""

# Dry run mode
if [[ "$DRY_RUN" == true ]]; then
    log_info "Dry run mode - no changes made"

    if grep -q "$FENCE_START" "$HOSTS_FILE" 2>/dev/null; then
        log_info "Existing fenced block found in $HOSTS_FILE - would be replaced"
    else
        log_info "No existing block found - would be appended to $HOSTS_FILE"
    fi
    exit 0
fi

# Check if we need sudo
if [[ ! -w "$HOSTS_FILE" ]]; then
    log_info "Root privileges required to modify $HOSTS_FILE"
    SUDO="sudo"
else
    SUDO=""
fi

# Create a temporary file with the new content
TEMP_FILE=$(mktemp)
trap "rm -f $TEMP_FILE" EXIT

# Remove existing fenced block and add new one
if grep -q "$FENCE_START" "$HOSTS_FILE" 2>/dev/null; then
    log_info "Replacing existing hosts block..."
    # Remove lines between fence markers (inclusive)
    $SUDO sed "/$FENCE_START/,/$FENCE_END/d" "$HOSTS_FILE" > "$TEMP_FILE"
else
    log_info "Adding new hosts block..."
    cat "$HOSTS_FILE" > "$TEMP_FILE"
fi

# Append the new hosts block
echo "" >> "$TEMP_FILE"
echo "$HOSTS_BLOCK" >> "$TEMP_FILE"

# Update /etc/hosts
$SUDO cp "$TEMP_FILE" "$HOSTS_FILE"

log_success "Successfully updated $HOSTS_FILE with ${HOST_COUNT} hostnames"
echo ""
echo "You can now access your services at:"
while IFS= read -r host; do
    if [[ -n "$host" ]]; then
        echo "  http://${host}"
    fi
done <<< "$ALL_HOSTS"
