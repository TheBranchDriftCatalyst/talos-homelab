#!/usr/bin/env bash
# Tdarr Worker Cache Dashboard
# Shows cache/transcode storage status for all Tdarr workers
#
# Usage:
#   ./tdarr-dashboard.sh          # Full dashboard
#   ./tdarr-dashboard.sh --json   # JSON output
#   ./tdarr-dashboard.sh --watch  # Auto-refresh every 10s
#
set -euo pipefail

NAMESPACE="tdarr"
WATCH_MODE=false
JSON_MODE=false

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

# Parse args
for arg in "$@"; do
    case $arg in
        --watch|-w) WATCH_MODE=true ;;
        --json|-j) JSON_MODE=true ;;
        --help|-h)
            echo "Usage: $0 [--watch] [--json]"
            echo "  --watch, -w  Auto-refresh every 10s"
            echo "  --json, -j   Output as JSON"
            exit 0
            ;;
    esac
done

# Draw a progress bar
draw_bar() {
    local percent=$1
    local width=${2:-30}
    local filled=$((percent * width / 100))
    local empty=$((width - filled))

    # Color based on usage
    local color="$GREEN"
    if [[ $percent -ge 80 ]]; then
        color="$RED"
    elif [[ $percent -ge 60 ]]; then
        color="$YELLOW"
    fi

    printf "${color}"
    printf '█%.0s' $(seq 1 $filled 2>/dev/null) || true
    printf "${DIM}"
    printf '░%.0s' $(seq 1 $empty 2>/dev/null) || true
    printf "${NC}"
}

# Get worker cache info
get_worker_cache() {
    local pod=$1
    local node
    node=$(kubectl get pod -n "$NAMESPACE" "$pod" -o jsonpath='{.spec.nodeName}')

    # Get volume type
    local vol_type
    vol_type=$(kubectl get pod -n "$NAMESPACE" "$pod" -o jsonpath='{.spec.volumes[?(@.name=="transcode-cache")].emptyDir}' 2>/dev/null)
    if [[ -n "$vol_type" ]]; then
        vol_type="emptyDir"
    else
        vol_type="hostPath"
    fi

    # Get disk usage from pod
    local df_output
    df_output=$(kubectl exec -n "$NAMESPACE" "$pod" -- df -h /temp 2>/dev/null | tail -1 || echo "")

    if [[ -z "$df_output" ]]; then
        echo "$pod|$node|$vol_type|N/A|N/A|N/A|0"
        return
    fi

    # Parse df output: Filesystem Size Used Avail Use% Mounted
    local total used avail percent
    total=$(echo "$df_output" | awk '{print $2}')
    used=$(echo "$df_output" | awk '{print $3}')
    avail=$(echo "$df_output" | awk '{print $4}')
    percent=$(echo "$df_output" | awk '{print $5}' | tr -d '%')

    echo "$pod|$node|$vol_type|$total|$used|$avail|$percent"
}

# Generate JSON output
output_json() {
    local workers=("$@")
    echo "["
    local first=true
    for info in "${workers[@]}"; do
        IFS='|' read -r pod node vol_type total used avail percent <<< "$info"
        if $first; then
            first=false
        else
            echo ","
        fi
        cat <<EOF
  {
    "pod": "$pod",
    "node": "$node",
    "volumeType": "$vol_type",
    "total": "$total",
    "used": "$used",
    "available": "$avail",
    "percentUsed": $percent
  }
EOF
    done
    echo ""
    echo "]"
}

# Display dashboard
display_dashboard() {
    clear 2>/dev/null || true

    echo ""
    echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${CYAN}║                      TDARR WORKER CACHE DASHBOARD                        ║${NC}"
    echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════════════════════════════╝${NC}"
    echo ""

    # Get server status
    local server_pod
    server_pod=$(kubectl get pods -n "$NAMESPACE" -l app=tdarr-server -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
    if [[ -n "$server_pod" ]]; then
        local server_status
        server_status=$(kubectl get pod -n "$NAMESPACE" "$server_pod" -o jsonpath='{.status.phase}')
        echo -e "  ${BOLD}Server:${NC} $server_pod ${GREEN}($server_status)${NC}"
    fi

    # Get worker pods
    local worker_pods
    mapfile -t worker_pods < <(kubectl get pods -n "$NAMESPACE" -l app=tdarr-worker -o jsonpath='{.items[*].metadata.name}' | tr ' ' '\n')

    echo -e "  ${BOLD}Workers:${NC} ${#worker_pods[@]} active"
    echo ""

    # Header
    echo -e "${DIM}  ┌─────────────────┬─────────────┬───────────┬─────────┬─────────┬─────────┬────────────────────────────────┐${NC}"
    printf "  │ ${BOLD}%-15s${NC} │ ${BOLD}%-11s${NC} │ ${BOLD}%-9s${NC} │ ${BOLD}%-7s${NC} │ ${BOLD}%-7s${NC} │ ${BOLD}%-7s${NC} │ ${BOLD}%-30s${NC} │\n" \
        "Worker" "Node" "Type" "Total" "Used" "Free" "Usage"
    echo -e "${DIM}  ├─────────────────┼─────────────┼───────────┼─────────┼─────────┼─────────┼────────────────────────────────┤${NC}"

    # Collect worker info
    local worker_info=()
    for pod in "${worker_pods[@]}"; do
        local info
        info=$(get_worker_cache "$pod")
        worker_info+=("$info")
    done

    # Display each worker
    for info in "${worker_info[@]}"; do
        IFS='|' read -r pod node vol_type total used avail percent <<< "$info"

        # Shorten pod name for display
        local short_pod="${pod#tdarr-worker-}"

        # Color volume type
        local vol_color="$GREEN"
        [[ "$vol_type" == "emptyDir" ]] && vol_color="$YELLOW"

        printf "  │ %-15s │ %-11s │ ${vol_color}%-9s${NC} │ %7s │ %7s │ %7s │ " \
            "$short_pod" "$node" "$vol_type" "$total" "$used" "$avail"

        if [[ "$percent" != "0" && "$percent" != "N/A" ]]; then
            draw_bar "$percent" 24
            printf " %3s%%" "$percent"
        else
            printf "${DIM}%-30s${NC}" "N/A"
        fi
        echo " │"
    done

    echo -e "${DIM}  └─────────────────┴─────────────┴───────────┴─────────┴─────────┴─────────┴────────────────────────────────┘${NC}"

    # Summary
    echo ""
    local total_used=0
    local total_avail=0
    for info in "${worker_info[@]}"; do
        IFS='|' read -r _ _ _ _ used avail _ <<< "$info"
        # Convert to GB for rough totals (handles G, T suffixes)
        if [[ "$used" =~ ^[0-9]+G$ ]]; then
            total_used=$((total_used + ${used%G}))
        elif [[ "$used" =~ ^[0-9]+T$ ]]; then
            total_used=$((total_used + ${used%T} * 1024))
        fi
        if [[ "$avail" =~ ^[0-9.]+G$ ]]; then
            total_avail=$((total_avail + ${avail%G}))
        elif [[ "$avail" =~ ^[0-9.]+T$ ]]; then
            # Handle decimal TB like 1.8T
            local tb_val="${avail%T}"
            total_avail=$((total_avail + ${tb_val%.*} * 1024))
        fi
    done

    echo -e "  ${BOLD}Summary:${NC}"
    echo -e "    Cache Used:  ${YELLOW}~${total_used}G${NC} across all workers"
    echo -e "    Cache Free:  ${GREEN}~${total_avail}G${NC} available"
    echo ""

    # Legend
    echo -e "  ${DIM}Legend: ${YELLOW}emptyDir${NC}${DIM} = backed by node EPHEMERAL partition (NVMe), ${GREEN}hostPath${NC}${DIM} = direct mount${NC}"
    echo -e "  ${DIM}        Bar colors: ${GREEN}█${NC}${DIM} <60%, ${YELLOW}█${NC}${DIM} 60-80%, ${RED}█${NC}${DIM} >80%${NC}"
    echo -e "  ${DIM}        All workers have 300Gi sizeLimit, but actual capacity varies by node NVMe${NC}"
    echo ""

    if $WATCH_MODE; then
        echo -e "  ${DIM}Auto-refreshing every 10s... Press Ctrl+C to exit${NC}"
    fi
}

# Main
main() {
    # Get worker pods
    local worker_pods
    mapfile -t worker_pods < <(kubectl get pods -n "$NAMESPACE" -l app=tdarr-worker -o jsonpath='{.items[*].metadata.name}' | tr ' ' '\n')

    if [[ ${#worker_pods[@]} -eq 0 ]]; then
        echo "No Tdarr workers found in namespace $NAMESPACE"
        exit 1
    fi

    # Collect worker info
    local worker_info=()
    for pod in "${worker_pods[@]}"; do
        worker_info+=("$(get_worker_cache "$pod")")
    done

    if $JSON_MODE; then
        output_json "${worker_info[@]}"
        exit 0
    fi

    if $WATCH_MODE; then
        while true; do
            display_dashboard
            sleep 10
        done
    else
        display_dashboard
    fi
}

main "$@"
