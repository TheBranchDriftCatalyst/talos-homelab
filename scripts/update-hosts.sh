#!/bin/bash
# Update /etc/hosts with Kubernetes Ingress hostnames
# Idempotent script that manages a fenced block for DNS entries

set -e

# Parse arguments
DRY_RUN=false
if [[ "$1" == "--dry-run" ]]; then
    DRY_RUN=true
fi

KUBECONFIG="${KUBECONFIG:-./.output/kubeconfig}"
NODE_IP="${TALOS_NODE:-192.168.1.54}"
DNS_ZONE="${DNS_ZONE:-talos00}"

# Markers for our managed block in /etc/hosts
START_MARKER="# BEGIN CATALYST-DNS-SYNC MANAGED BLOCK"
END_MARKER="# END CATALYST-DNS-SYNC MANAGED BLOCK"

echo "🔧 Updating /etc/hosts with Kubernetes Ingress hostnames"
echo "=========================================================="
echo "  Node IP: $NODE_IP"
echo "  Zone: $DNS_ZONE"
echo ""

# Create temporary file for new entries
TEMP_ENTRIES=$(mktemp)
trap "rm -f $TEMP_ENTRIES" EXIT

# Function to extract hostnames from Ingress resources
extract_ingress_hostnames() {
    kubectl --kubeconfig "$KUBECONFIG" get ingress --all-namespaces -o json 2>/dev/null | \
        jq -r '.items[].spec.rules[]?.host // empty' | \
        grep -E "\.$DNS_ZONE$|^$DNS_ZONE$" | \
        sort -u
}

# Function to extract hostnames from IngressRoute resources
extract_ingressroute_hostnames() {
    kubectl --kubeconfig "$KUBECONFIG" get ingressroute --all-namespaces -o json 2>/dev/null | \
        jq -r '.items[].spec.routes[]?.match // empty' | \
        sed -n 's/.*Host(`\([^`]*\)`).*/\1/p' | \
        grep -E "\.$DNS_ZONE$|^$DNS_ZONE$" | \
        sort -u || true
}

# Gather all hostnames
echo "1️⃣  Discovering Ingress hostnames from cluster..."
{
    extract_ingress_hostnames
    extract_ingressroute_hostnames
} | sort -u > "$TEMP_ENTRIES.raw"

# Generate the managed block content
echo "$START_MARKER" > "$TEMP_ENTRIES"
echo "# Auto-generated on $(date)" >> "$TEMP_ENTRIES"
echo "# Managed by catalyst-dns-sync - DO NOT EDIT MANUALLY" >> "$TEMP_ENTRIES"
echo "#" >> "$TEMP_ENTRIES"

if [ -s "$TEMP_ENTRIES.raw" ]; then
    COUNT=0
    while IFS= read -r hostname; do
        echo "$NODE_IP  $hostname" >> "$TEMP_ENTRIES"
        COUNT=$((COUNT + 1))
    done < "$TEMP_ENTRIES.raw"
    echo "" >> "$TEMP_ENTRIES"
    echo "# Total entries: $COUNT" >> "$TEMP_ENTRIES"
    echo "✅ Found $COUNT hostnames to add"
else
    echo "# No Ingress resources found" >> "$TEMP_ENTRIES"
    echo "⚠️  No hostnames found in cluster"
fi

echo "$END_MARKER" >> "$TEMP_ENTRIES"

if [ "$DRY_RUN" = true ]; then
    echo ""
    echo "🔍 DRY RUN MODE - No changes will be made to /etc/hosts"
    echo ""
    echo "📝 Would add the following entries:"
    echo "===================="
    cat "$TEMP_ENTRIES"
    echo ""
    echo "💡 Run without --dry-run to apply these changes"
    echo ""
    exit 0
fi

# Create backup of /etc/hosts
echo ""
echo "2️⃣  Creating backup of /etc/hosts..."
sudo cp /etc/hosts /etc/hosts.backup.$(date +%Y%m%d-%H%M%S)
echo "✅ Backup created: /etc/hosts.backup.$(date +%Y%m%d-%H%M%S)"

# Remove old managed block if it exists
echo ""
echo "3️⃣  Updating /etc/hosts..."
TEMP_HOSTS=$(mktemp)

if grep -q "$START_MARKER" /etc/hosts 2>/dev/null; then
    # Remove existing managed block
    sudo awk "/$START_MARKER/,/$END_MARKER/{next} {print}" /etc/hosts > "$TEMP_HOSTS"
    echo "   Removed old managed block"
else
    # No existing block, just copy current hosts
    sudo cat /etc/hosts > "$TEMP_HOSTS"
fi

# Append new managed block
cat "$TEMP_ENTRIES" >> "$TEMP_HOSTS"

# Write back to /etc/hosts
sudo cp "$TEMP_HOSTS" /etc/hosts
rm -f "$TEMP_HOSTS"

echo "✅ /etc/hosts updated successfully"

# Show what was added
echo ""
echo "📝 Added entries:"
echo "===================="
cat "$TEMP_ENTRIES"

echo ""
echo "🎉 Done! Your /etc/hosts now includes all Kubernetes Ingress hostnames."
echo ""
echo "💡 Tips:"
echo "  - Run this script again anytime to refresh entries"
echo "  - Entries are idempotent - safe to run multiple times"
echo "  - Original backup saved to /etc/hosts.backup.*"
echo "  - Deploy DNS server to avoid manual /etc/hosts updates: ./scripts/setup-dns.sh"
echo ""
