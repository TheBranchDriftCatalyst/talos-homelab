#!/bin/bash
# Nebula Certificate Generator
# Generates CA and node certificates for the Nebula mesh VPN
#
# Usage: ./scripts/hybrid-llm/nebula-certs.sh [command]
#
# Commands:
#   init        - Generate CA certificate (run once)
#   lighthouse  - Generate lighthouse certificate
#   node        - Generate node certificate (interactive)
#   list        - List all generated certificates
#   clean       - Remove all generated certificates
#
# Output: .output/nebula/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUTPUT_DIR="$REPO_ROOT/.output/nebula"

# Nebula mesh configuration
MESH_NAME="talos-homelab-mesh"
LIGHTHOUSE_NAME="lighthouse"
LIGHTHOUSE_IP="10.42.0.1/24"
CA_EXPIRY="8760h"  # 1 year
CERT_EXPIRY="8760h"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log() { echo -e "${GREEN}[nebula-certs]${NC} $1"; }
warn() { echo -e "${YELLOW}[nebula-certs]${NC} $1"; }
error() { echo -e "${RED}[nebula-certs]${NC} $1" >&2; }

# Check for nebula-cert binary
check_nebula_cert() {
    if ! command -v nebula-cert &> /dev/null; then
        error "nebula-cert not found. Install with: brew install nebula"
        exit 1
    fi
}

# Initialize output directory
init_output_dir() {
    mkdir -p "$OUTPUT_DIR"
    chmod 700 "$OUTPUT_DIR"
}

# Generate CA certificate
cmd_init() {
    check_nebula_cert
    init_output_dir

    if [[ -f "$OUTPUT_DIR/ca.crt" ]]; then
        warn "CA certificate already exists at $OUTPUT_DIR/ca.crt"
        read -p "Regenerate? This will invalidate all existing node certs (y/N): " confirm
        if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
            log "Keeping existing CA"
            return 0
        fi
        # Backup old CA
        mv "$OUTPUT_DIR/ca.crt" "$OUTPUT_DIR/ca.crt.bak.$(date +%s)"
        mv "$OUTPUT_DIR/ca.key" "$OUTPUT_DIR/ca.key.bak.$(date +%s)"
    fi

    log "Generating CA certificate for mesh: $MESH_NAME"
    nebula-cert ca \
        -name "$MESH_NAME" \
        -duration "$CA_EXPIRY" \
        -out-crt "$OUTPUT_DIR/ca.crt" \
        -out-key "$OUTPUT_DIR/ca.key"

    chmod 600 "$OUTPUT_DIR/ca.key"
    chmod 644 "$OUTPUT_DIR/ca.crt"

    log "CA certificate generated:"
    echo "  - $OUTPUT_DIR/ca.crt (public - can be distributed)"
    echo "  - $OUTPUT_DIR/ca.key (PRIVATE - keep secure!)"
}

# Generate lighthouse certificate
cmd_lighthouse() {
    check_nebula_cert
    init_output_dir

    if [[ ! -f "$OUTPUT_DIR/ca.crt" ]]; then
        error "CA certificate not found. Run 'init' first."
        exit 1
    fi

    local cert_dir="$OUTPUT_DIR/lighthouse"
    mkdir -p "$cert_dir"

    if [[ -f "$cert_dir/host.crt" ]]; then
        warn "Lighthouse certificate already exists"
        read -p "Regenerate? (y/N): " confirm
        if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
            log "Keeping existing lighthouse cert"
            return 0
        fi
    fi

    log "Generating lighthouse certificate ($LIGHTHOUSE_IP)"
    nebula-cert sign \
        -ca-crt "$OUTPUT_DIR/ca.crt" \
        -ca-key "$OUTPUT_DIR/ca.key" \
        -name "$LIGHTHOUSE_NAME" \
        -ip "$LIGHTHOUSE_IP" \
        -groups "lighthouse,infrastructure" \
        -duration "$CERT_EXPIRY" \
        -out-crt "$cert_dir/host.crt" \
        -out-key "$cert_dir/host.key"

    chmod 600 "$cert_dir/host.key"
    chmod 644 "$cert_dir/host.crt"

    log "Lighthouse certificate generated:"
    echo "  - $cert_dir/host.crt"
    echo "  - $cert_dir/host.key"
    echo ""
    echo -e "${CYAN}To generate EC2 userdata:${NC}"
    echo "  ./scripts/hybrid-llm/lighthouse-userdata.sh > /tmp/userdata.sh"
}

# Generate a generic node certificate
cmd_node() {
    check_nebula_cert
    init_output_dir

    if [[ ! -f "$OUTPUT_DIR/ca.crt" ]]; then
        error "CA certificate not found. Run 'init' first."
        exit 1
    fi

    read -p "Node name: " node_name
    read -p "Node IP (e.g., 10.42.0.10/24): " node_ip
    read -p "Groups (comma-separated, e.g., kubernetes,homelab): " groups

    local cert_dir="$OUTPUT_DIR/nodes/$node_name"
    mkdir -p "$cert_dir"

    if [[ -f "$cert_dir/host.crt" ]]; then
        warn "Certificate for '$node_name' already exists"
        read -p "Regenerate? (y/N): " confirm
        if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
            log "Keeping existing cert"
            return 0
        fi
    fi

    log "Generating certificate for node: $node_name ($node_ip)"
    nebula-cert sign \
        -ca-crt "$OUTPUT_DIR/ca.crt" \
        -ca-key "$OUTPUT_DIR/ca.key" \
        -name "$node_name" \
        -ip "$node_ip" \
        -groups "$groups" \
        -duration "$CERT_EXPIRY" \
        -out-crt "$cert_dir/host.crt" \
        -out-key "$cert_dir/host.key"

    chmod 600 "$cert_dir/host.key"
    chmod 644 "$cert_dir/host.crt"

    log "Node certificate generated:"
    echo "  - $cert_dir/host.crt"
    echo "  - $cert_dir/host.key"
}

# List all certificates
cmd_list() {
    init_output_dir

    echo -e "${CYAN}=== Nebula Certificates ===${NC}"
    echo ""

    if [[ -f "$OUTPUT_DIR/ca.crt" ]]; then
        echo -e "${GREEN}CA Certificate:${NC}"
        nebula-cert print -path "$OUTPUT_DIR/ca.crt" 2>/dev/null | head -10
        echo ""
    else
        echo -e "${YELLOW}No CA certificate found${NC}"
        echo ""
    fi

    if [[ -f "$OUTPUT_DIR/lighthouse/host.crt" ]]; then
        echo -e "${GREEN}Lighthouse Certificate:${NC}"
        nebula-cert print -path "$OUTPUT_DIR/lighthouse/host.crt" 2>/dev/null | head -10
        echo ""
    fi

    if [[ -d "$OUTPUT_DIR/nodes" ]]; then
        for node_dir in "$OUTPUT_DIR/nodes"/*/; do
            if [[ -f "$node_dir/host.crt" ]]; then
                node_name=$(basename "$node_dir")
                echo -e "${GREEN}Node: $node_name${NC}"
                nebula-cert print -path "$node_dir/host.crt" 2>/dev/null | head -10
                echo ""
            fi
        done
    fi
}

# Clean all certificates
cmd_clean() {
    if [[ ! -d "$OUTPUT_DIR" ]]; then
        log "No certificates to clean"
        return 0
    fi

    warn "This will delete ALL Nebula certificates in $OUTPUT_DIR"
    read -p "Are you sure? (y/N): " confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        log "Cancelled"
        return 0
    fi

    rm -rf "$OUTPUT_DIR"
    log "Cleaned all certificates"
}

# Show usage
usage() {
    echo "Nebula Certificate Generator"
    echo ""
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  init        Generate CA certificate (run once)"
    echo "  lighthouse  Generate lighthouse certificate and userdata"
    echo "  node        Generate node certificate (interactive)"
    echo "  list        List all generated certificates"
    echo "  clean       Remove all generated certificates"
    echo ""
    echo "Output directory: $OUTPUT_DIR"
}

# Main
case "${1:-}" in
    init)
        cmd_init
        ;;
    lighthouse)
        cmd_lighthouse
        ;;
    node)
        cmd_node
        ;;
    list)
        cmd_list
        ;;
    clean)
        cmd_clean
        ;;
    *)
        usage
        exit 1
        ;;
esac
