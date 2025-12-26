#!/usr/bin/env bash
#
# Catalyst Cluster Status Report
# Classification: SCI//EAGLE-12//HOMELAB
#
# Usage: ./scripts/cluster-status.sh [--quick]
#

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Check for quick mode
QUICK_MODE="${1:-}"

header() {
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}                    CATALYST CLUSTER - FULL STATUS REPORT${NC}"
    echo -e "${CYAN}                    Classification: SCI//EAGLE-12//HOMELAB${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "📅 Report Generated: $(date)"
    echo ""
}

section() {
    echo ""
    echo -e "${BLUE}┌─────────────────────────────────────────────────────────────────────────────┐${NC}"
    echo -e "${BLUE}│${NC} ${BOLD}$1${NC}"
    echo -e "${BLUE}└─────────────────────────────────────────────────────────────────────────────┘${NC}"
}

ok() { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
err() { echo -e "  ${RED}✗${NC} $1"; }

# ============================================================================
# NODE STATUS
# ============================================================================
node_status() {
    section "NODE STATUS"
    kubectl get nodes -o wide 2>/dev/null || err "Failed to get nodes"
}

# ============================================================================
# RESOURCE UTILIZATION
# ============================================================================
resource_utilization() {
    section "RESOURCE UTILIZATION"
    if kubectl top nodes 2>/dev/null; then
        echo ""
        # Calculate cluster totals
        local total_cpu total_mem
        total_cpu=$(kubectl top nodes --no-headers 2>/dev/null | awk '{sum += $2} END {print sum}')
        total_mem=$(kubectl top nodes --no-headers 2>/dev/null | awk '{sum += $4} END {print sum}')
        echo -e "  ${BOLD}Cluster Total: ${total_cpu}m CPU, ${total_mem}Mi Memory${NC}"
    else
        warn "Metrics server not available"
    fi
}

# ============================================================================
# FLUX GITOPS STATUS
# ============================================================================
flux_status() {
    section "FLUX GITOPS STATUS"

    # Columns: NAME, REVISION, SUSPENDED, READY, MESSAGE
    # Column 3 = SUSPENDED (True = suspended)
    # Column 4 = READY (True = healthy, False = failed)
    local total ready failed suspended
    total=$(flux get kustomizations --no-header 2>/dev/null | wc -l | tr -d ' ')
    ready=$(flux get kustomizations --no-header 2>/dev/null | awk '$4 == "True" {count++} END {print count+0}')
    failed=$(flux get kustomizations --no-header 2>/dev/null | awk '$4 == "False" {count++} END {print count+0}')
    suspended=$(flux get kustomizations --no-header 2>/dev/null | awk '$3 == "True" {count++} END {print count+0}')

    echo -e "  Total: ${BOLD}$total${NC} | Ready: ${GREEN}$ready${NC} | Failed: ${RED}$failed${NC} | Suspended: ${YELLOW}$suspended${NC}"
    echo ""

    # Show any failing kustomizations (READY column = False)
    local failures
    failures=$(flux get kustomizations --no-header 2>/dev/null | awk '$4 == "False"' || true)
    if [[ -n "$failures" ]]; then
        err "Failing Kustomizations:"
        echo "$failures" | while read -r line; do echo "    $line"; done
    else
        ok "All Flux Kustomizations healthy"
    fi
}

# ============================================================================
# ARGOCD APPLICATIONS
# ============================================================================
argocd_status() {
    section "ARGOCD APPLICATIONS"

    if ! kubectl get applications -n argocd &>/dev/null; then
        warn "ArgoCD not available"
        return
    fi

    kubectl get applications -n argocd -o custom-columns='NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status' 2>/dev/null | \
    while read -r line; do
        if echo "$line" | grep -q "Synced.*Healthy"; then
            echo -e "  ${GREEN}✓${NC} $line"
        elif echo "$line" | grep -q "NAME"; then
            echo "  $line"
        else
            echo -e "  ${RED}✗${NC} $line"
        fi
    done
}

# ============================================================================
# POD HEALTH
# ============================================================================
pod_health() {
    section "POD HEALTH SUMMARY"

    echo "  By Status:"
    kubectl get pods -A --no-headers 2>/dev/null | awk '{print $4}' | sort | uniq -c | sort -rn | \
    while read -r count status; do
        case "$status" in
            Running)   echo -e "    ${GREEN}$count${NC} $status" ;;
            Completed) echo -e "    ${CYAN}$count${NC} $status" ;;
            Pending)   echo -e "    ${YELLOW}$count${NC} $status" ;;
            *)         echo -e "    ${RED}$count${NC} $status" ;;
        esac
    done

    echo ""
    echo "  Problem Pods:"
    local problems
    problems=$(kubectl get pods -A --no-headers 2>/dev/null | grep -Ev "Running|Completed" || true)
    if [[ -n "$problems" ]]; then
        echo "$problems" | head -10 | while read -r line; do
            echo -e "    ${RED}✗${NC} $line"
        done
    else
        ok "All pods healthy"
    fi
}

# ============================================================================
# HELMRELEASE STATUS
# ============================================================================
helmrelease_status() {
    section "HELMRELEASE STATUS"

    # Columns: NAMESPACE, NAME, REVISION, SUSPENDED, READY, MESSAGE
    # Column 4 = SUSPENDED (True = suspended)
    # Column 5 = READY (True = healthy, False = failed)
    local total ready failed
    total=$(flux get helmreleases -A --no-header 2>/dev/null | wc -l | tr -d ' ')
    ready=$(flux get helmreleases -A --no-header 2>/dev/null | awk '$5 == "True" {count++} END {print count+0}')
    failed=$(flux get helmreleases -A --no-header 2>/dev/null | awk '$5 == "False" {count++} END {print count+0}')

    echo -e "  Total: ${BOLD}$total${NC} | Ready: ${GREEN}$ready${NC} | Failed: ${RED}$failed${NC}"

    # Show failures (READY column = False)
    local failures
    failures=$(flux get helmreleases -A --no-header 2>/dev/null | awk '$5 == "False"' || true)
    if [[ -n "$failures" ]]; then
        echo ""
        err "Failing HelmReleases:"
        echo "$failures" | while read -r line; do echo "    $line"; done
    fi
}

# ============================================================================
# VPN GATEWAY STATUS
# ============================================================================
vpn_status() {
    section "VPN GATEWAY STATUS"

    for deploy in qbittorrent securexng; do
        for ns in media vpn-gateway; do
            local result
            result=$(kubectl exec -n "$ns" "deploy/$deploy" -c gluetun -- \
                wget -q -O- http://localhost:8000/v1/publicip/ip 2>/dev/null || true)
            if [[ -n "$result" ]]; then
                local ip country
                ip=$(echo "$result" | jq -r '.public_ip // "unknown"' 2>/dev/null)
                country=$(echo "$result" | jq -r '.country // "unknown"' 2>/dev/null)
                ok "$deploy: VPN $ip ($country)"
                break
            fi
        done 2>/dev/null || warn "$deploy: Not available"
    done
}

# ============================================================================
# STORAGE STATUS
# ============================================================================
storage_status() {
    section "STORAGE STATUS"

    echo "  PVC Summary:"
    kubectl get pvc -A --no-headers 2>/dev/null | awk '{print $3}' | sort | uniq -c | \
    while read -r count status; do
        case "$status" in
            Bound)   echo -e "    ${GREEN}$count${NC} $status" ;;
            Pending) echo -e "    ${YELLOW}$count${NC} $status" ;;
            *)       echo -e "    ${RED}$count${NC} $status" ;;
        esac
    done

    # Check for unbound PVCs
    local unbound
    unbound=$(kubectl get pvc -A --no-headers 2>/dev/null | grep -v Bound || true)
    if [[ -n "$unbound" ]]; then
        echo ""
        warn "Unbound PVCs:"
        echo "$unbound" | while read -r line; do echo "    $line"; done
    fi
}

# ============================================================================
# MONITORING STACK
# ============================================================================
monitoring_status() {
    section "MONITORING STACK"

    echo "  Mimir (metrics):"
    kubectl get pods -n monitoring -l app.kubernetes.io/name=mimir --no-headers 2>/dev/null | \
    while read -r name ready status _; do
        [[ "$status" == "Running" ]] && ok "$name" || err "$name: $status"
    done

    echo ""
    echo "  Grafana:"
    kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana --no-headers 2>/dev/null | \
    while read -r name ready status _; do
        [[ "$status" == "Running" ]] && ok "$name" || err "$name: $status"
    done

    echo ""
    echo "  Loki (logs):"
    kubectl get pods -n monitoring -l app.kubernetes.io/name=loki --no-headers 2>/dev/null | head -3 | \
    while read -r name ready status _; do
        [[ "$status" == "Running" ]] && ok "$name" || err "$name: $status"
    done
}

# ============================================================================
# MEDIA STACK
# ============================================================================
media_status() {
    section "MEDIA STACK"

    kubectl get pods -n media --no-headers 2>/dev/null | \
    while read -r name ready status restarts age; do
        local icon
        [[ "$status" == "Running" ]] && icon="${GREEN}✓${NC}" || icon="${RED}✗${NC}"
        printf "  ${icon} %-42s %s\n" "$name" "$status"
    done
}

# ============================================================================
# POWER CONSUMPTION (Kasa)
# ============================================================================
power_status() {
    section "POWER CONSUMPTION"

    # Query Mimir for power metrics
    local result
    result=$(kubectl run -n monitoring pwr-check-$$ --rm -i --restart=Never --image=curlimages/curl -- \
        curl -s "http://mimir-query-frontend:8080/prometheus/api/v1/query?query=current_consumption:by_device" 2>/dev/null || true)

    if [[ -n "$result" ]] && echo "$result" | jq -e '.data.result[0]' &>/dev/null; then
        echo "$result" | jq -r '.data.result[] | "  \(.metric.alias): \(.value[1])W"' 2>/dev/null | sort -t: -k2 -rn
        echo ""

        # Get total
        local total
        total=$(kubectl run -n monitoring pwr-total-$$ --rm -i --restart=Never --image=curlimages/curl -- \
            curl -s "http://mimir-query-frontend:8080/prometheus/api/v1/query?query=current_consumption:total" 2>/dev/null || true)
        if [[ -n "$total" ]]; then
            local watts
            watts=$(echo "$total" | jq -r '.data.result[0].value[1]' 2>/dev/null)
            echo -e "  ${BOLD}TOTAL: ${watts}W${NC}"
        fi
    else
        warn "Power metrics not available"
    fi
}

# ============================================================================
# RECENT EVENTS
# ============================================================================
recent_events() {
    section "RECENT WARNINGS (last 10)"

    local events
    events=$(kubectl get events -A --field-selector type=Warning --sort-by='.lastTimestamp' 2>/dev/null | tail -10)
    if [[ -n "$events" ]]; then
        echo "$events" | while read -r line; do
            echo -e "  ${YELLOW}⚠${NC} $line"
        done
    else
        ok "No recent warnings"
    fi
}

# ============================================================================
# FOOTER
# ============================================================================
footer() {
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}                              END OF REPORT${NC}"
    echo -e "${CYAN}                    Classification: SCI//EAGLE-12//HOMELAB${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════════════════════${NC}"
}

# ============================================================================
# MAIN
# ============================================================================
main() {
    header
    node_status
    resource_utilization

    if [[ "$QUICK_MODE" != "--quick" ]]; then
        flux_status
        argocd_status
        helmrelease_status
    fi

    pod_health

    if [[ "$QUICK_MODE" != "--quick" ]]; then
        vpn_status
        storage_status
        monitoring_status
        media_status
        power_status
        recent_events
    fi

    footer
}

main "$@"
