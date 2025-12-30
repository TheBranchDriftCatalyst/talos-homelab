#!/usr/bin/env bash
#
# Grafana Dashboard Sync Script
# Bidirectional sync between Grafana UI and JSON files
#
# Usage:
#   ./grafana-sync.sh pull              # Export dashboards from Grafana to JSON files
#   ./grafana-sync.sh push              # Apply JSON files to cluster
#   ./grafana-sync.sh pull --dashboard tdarr-transcoding  # Pull specific dashboard
#   ./grafana-sync.sh list              # List dashboards in Grafana
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DASHBOARD_DIR="$(dirname "$SCRIPT_DIR")"
JSON_DIR="$DASHBOARD_DIR/json"
RESOURCES_DIR="$DASHBOARD_DIR/resources"

# Grafana connection settings
GRAFANA_URL="${GRAFANA_URL:-http://grafana.talos00}"
GRAFANA_USER="${GRAFANA_USER:-admin}"
GRAFANA_PASSWORD="${GRAFANA_PASSWORD:-}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log() { echo -e "$1"; }
info() { log "${CYAN}$1${NC}"; }
success() { log "${GREEN}$1${NC}"; }
warn() { log "${YELLOW}$1${NC}"; }
error() { log "${RED}$1${NC}"; }

# Get Grafana password from Kubernetes secret if not set
get_grafana_password() {
    if [[ -z "$GRAFANA_PASSWORD" ]]; then
        GRAFANA_PASSWORD=$(kubectl get secret -n monitoring grafana-admin-credentials \
            -o jsonpath='{.data.GF_SECURITY_ADMIN_PASSWORD}' 2>/dev/null | base64 -d) || true
    fi

    if [[ -z "$GRAFANA_PASSWORD" ]]; then
        error "Grafana password not found. Set GRAFANA_PASSWORD or ensure grafana-admin-credentials secret exists."
        exit 1
    fi
}

# Make authenticated API call to Grafana
grafana_api() {
    local endpoint="$1"
    local method="${2:-GET}"
    local data="${3:-}"

    local curl_args=(
        -s
        -X "$method"
        -H "Content-Type: application/json"
        -u "${GRAFANA_USER}:${GRAFANA_PASSWORD}"
    )

    if [[ -n "$data" ]]; then
        curl_args+=(-d "$data")
    fi

    curl "${curl_args[@]}" "${GRAFANA_URL}${endpoint}"
}

# List all dashboards in Grafana
list_dashboards() {
    info "Fetching dashboards from ${GRAFANA_URL}..."

    local response
    response=$(grafana_api "/api/search?type=dash-db")

    if [[ -z "$response" ]] || [[ "$response" == "null" ]]; then
        error "Failed to fetch dashboards"
        exit 1
    fi

    echo ""
    printf "${CYAN}%-40s %-20s %-15s${NC}\n" "TITLE" "UID" "FOLDER"
    printf "%-40s %-20s %-15s\n" "----------------------------------------" "--------------------" "---------------"

    echo "$response" | jq -r '.[] | "\(.title)\t\(.uid)\t\(.folderTitle // "General")"' | while IFS=$'\t' read -r title uid folder; do
        printf "%-40s %-20s %-15s\n" "${title:0:40}" "$uid" "${folder:0:15}"
    done
}

# Pull dashboard from Grafana API and save to JSON file
pull_dashboard() {
    local uid="$1"
    local filename="$2"

    info "Pulling dashboard: $uid -> $filename"

    local response
    response=$(grafana_api "/api/dashboards/uid/$uid")

    if [[ -z "$response" ]] || echo "$response" | jq -e '.message' &>/dev/null; then
        error "  Failed to fetch dashboard $uid: $(echo "$response" | jq -r '.message // "Unknown error"')"
        return 1
    fi

    # Extract just the dashboard JSON (not the meta wrapper)
    local dashboard_json
    dashboard_json=$(echo "$response" | jq '.dashboard')

    # Clean up dashboard JSON for storage
    # - Remove id (will be assigned by Grafana)
    # - Keep uid for identification
    # - Reset version to 1
    dashboard_json=$(echo "$dashboard_json" | jq 'del(.id) | .version = 1')

    # Save to file
    echo "$dashboard_json" | jq '.' > "$JSON_DIR/$filename"

    success "  Saved: $JSON_DIR/$filename"
}

# Pull all custom dashboards from Grafana
pull_all() {
    info "=== Pulling dashboards from Grafana ==="
    echo ""

    # Map of dashboard UIDs to filenames (based on our resources)
    declare -A DASHBOARD_MAP

    # Read UIDs from existing JSON files
    for json_file in "$JSON_DIR"/*.json; do
        if [[ -f "$json_file" ]]; then
            local uid
            uid=$(jq -r '.uid // empty' "$json_file" 2>/dev/null)
            if [[ -n "$uid" ]]; then
                DASHBOARD_MAP["$uid"]="$(basename "$json_file")"
            fi
        fi
    done

    if [[ ${#DASHBOARD_MAP[@]} -eq 0 ]]; then
        warn "No existing dashboards found in $JSON_DIR"
        warn "Run 'list' to see available dashboards, then pull individually"
        exit 0
    fi

    local success_count=0
    local fail_count=0

    for uid in "${!DASHBOARD_MAP[@]}"; do
        local filename="${DASHBOARD_MAP[$uid]}"
        if pull_dashboard "$uid" "$filename"; then
            ((success_count++))
        else
            ((fail_count++))
        fi
    done

    echo ""
    success "=== Pull complete: $success_count succeeded, $fail_count failed ==="
}

# Pull specific dashboard by name/uid
pull_single() {
    local target="$1"

    # Check if it's a filename in our json dir
    if [[ -f "$JSON_DIR/${target}.json" ]]; then
        local uid
        uid=$(jq -r '.uid // empty' "$JSON_DIR/${target}.json")
        if [[ -n "$uid" ]]; then
            pull_dashboard "$uid" "${target}.json"
            return
        fi
    fi

    # Try as UID directly
    info "Pulling dashboard with UID: $target"

    local response
    response=$(grafana_api "/api/dashboards/uid/$target")

    if echo "$response" | jq -e '.message' &>/dev/null; then
        error "Dashboard not found: $target"
        exit 1
    fi

    local title
    title=$(echo "$response" | jq -r '.dashboard.title')
    local filename="${target}.json"

    pull_dashboard "$target" "$filename"

    # Check if we need to create a GrafanaDashboard CR
    if [[ ! -f "$RESOURCES_DIR/${target}.yaml" ]]; then
        warn "Note: No GrafanaDashboard CR exists for $target"
        warn "You may need to create $RESOURCES_DIR/${target}.yaml"
    fi
}

# Push dashboards to cluster via kustomize
push_dashboards() {
    info "=== Pushing dashboards to cluster ==="
    echo ""

    # Validate kustomization first
    info "Validating kustomization..."
    if ! kustomize build "$DASHBOARD_DIR" > /dev/null 2>&1; then
        error "Kustomization validation failed!"
        kustomize build "$DASHBOARD_DIR"
        exit 1
    fi
    success "Kustomization valid"

    # Apply to cluster
    info "Applying to cluster..."
    kubectl apply -k "$DASHBOARD_DIR"

    echo ""
    success "=== Push complete ==="
    info "Dashboards will sync to Grafana via the operator"
}

# Show status of dashboards
status() {
    info "=== Dashboard Status ==="
    echo ""

    info "Local JSON files:"
    for json_file in "$JSON_DIR"/*.json; do
        if [[ -f "$json_file" ]]; then
            local name uid
            name=$(basename "$json_file" .json)
            uid=$(jq -r '.uid // "no-uid"' "$json_file")
            log "  ${GREEN}$name${NC} (uid: $uid)"
        fi
    done

    echo ""
    info "GrafanaDashboard CRs in cluster:"
    kubectl get grafanadashboards -n monitoring -o custom-columns=NAME:.metadata.name,FOLDER:.spec.folder,SYNCED:.status.contentTimestamp 2>/dev/null || warn "  Unable to fetch"
}

# Main entry point
main() {
    local command="${1:-help}"
    shift || true

    case "$command" in
        pull)
            get_grafana_password
            if [[ -n "${1:-}" ]] && [[ "$1" == "--dashboard" ]] && [[ -n "${2:-}" ]]; then
                pull_single "$2"
            else
                pull_all
            fi
            ;;
        push)
            push_dashboards
            ;;
        list)
            get_grafana_password
            list_dashboards
            ;;
        status)
            status
            ;;
        help|--help|-h)
            cat <<EOF
Grafana Dashboard Sync Script

Bidirectional sync between Grafana UI edits and JSON files in git.

Usage:
  $0 <command> [options]

Commands:
  pull                      Export all custom dashboards from Grafana to JSON files
  pull --dashboard <name>   Export specific dashboard by name or UID
  push                      Apply JSON files to cluster via kustomize
  list                      List all dashboards in Grafana
  status                    Show sync status

Environment Variables:
  GRAFANA_URL       Grafana URL (default: http://grafana.talos00)
  GRAFANA_USER      Grafana username (default: admin)
  GRAFANA_PASSWORD  Grafana password (auto-fetched from k8s secret if not set)

Examples:
  # Pull all dashboards from Grafana UI to local JSON files
  $0 pull

  # Pull specific dashboard
  $0 pull --dashboard tdarr-transcoding

  # Apply local changes to cluster
  $0 push

  # See what's in Grafana
  $0 list

Workflow:
  1. Edit dashboard in Grafana UI
  2. Run '$0 pull' to export changes to JSON
  3. Commit JSON changes to git
  4. Changes auto-apply via GitOps (or run '$0 push')

  OR

  1. Edit JSON file directly
  2. Run '$0 push' to apply
  3. Grafana Operator syncs to Grafana
EOF
            ;;
        *)
            error "Unknown command: $command"
            echo "Run '$0 help' for usage"
            exit 1
            ;;
    esac
}

main "$@"
