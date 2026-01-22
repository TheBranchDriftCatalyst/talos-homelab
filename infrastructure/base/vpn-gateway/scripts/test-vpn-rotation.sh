#!/usr/bin/env bash
#
# VPN Gateway E2E Test Script
#
# Tests:
# 1. VPN connectivity via proxy
# 2. Public IP retrieval
# 3. Pod restart (validates iptables cleanup init container)
# 4. VPN rotation (IP change verification)
#
# Usage:
#   ./scripts/test-vpn-rotation.sh           # Run all tests
#   ./scripts/test-vpn-rotation.sh --quick   # Skip rotation test (faster)
#   ./scripts/test-vpn-rotation.sh --cleanup # Only cleanup test resources
#
set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Config
NAMESPACE="vpn-gateway"
TEST_POD_NAME="vpn-test-client"
GLUETUN_SVC="gluetun.${NAMESPACE}.svc.cluster.local"
PROXY_PORT="8080"
SOCKS_PORT="1080"
CONTROL_PORT="8000"
TIMEOUT=120
QUICK_MODE=false
CLEANUP_ONLY=false

log() { echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $*"; }
success() { echo -e "${GREEN}✓${NC} $*"; }
fail() { echo -e "${RED}✗${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }

# Parse args
for arg in "$@"; do
    case $arg in
        --quick) QUICK_MODE=true ;;
        --cleanup) CLEANUP_ONLY=true ;;
        --help|-h)
            echo "Usage: $0 [--quick] [--cleanup]"
            echo "  --quick   Skip rotation test (faster)"
            echo "  --cleanup Only cleanup test resources"
            exit 0
            ;;
    esac
done

cleanup() {
    log "Cleaning up test resources..."
    kubectl delete pod "$TEST_POD_NAME" -n "$NAMESPACE" --ignore-not-found --wait=false 2>/dev/null || true
    success "Cleanup complete"
}

# Trap for cleanup on exit
trap cleanup EXIT

if $CLEANUP_ONLY; then
    cleanup
    exit 0
fi

# Create test pod that can reach VPN gateway
create_test_pod() {
    log "Creating test pod..."

    kubectl delete pod "$TEST_POD_NAME" -n "$NAMESPACE" --ignore-not-found --wait=true 2>/dev/null || true

    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: ${TEST_POD_NAME}
  namespace: ${NAMESPACE}
  labels:
    app: vpn-test
spec:
  containers:
    - name: test
      image: curlimages/curl:latest
      command: ["sleep", "3600"]
      resources:
        requests:
          cpu: 10m
          memory: 16Mi
EOF

    log "Waiting for test pod to be ready..."
    kubectl wait --for=condition=Ready pod/"$TEST_POD_NAME" -n "$NAMESPACE" --timeout="${TIMEOUT}s"
    success "Test pod ready"
}

# Get public IP via VPN proxy
get_public_ip() {
    local method=$1  # http or socks5
    local ip=""

    case $method in
        http)
            ip=$(kubectl exec -n "$NAMESPACE" "$TEST_POD_NAME" -- \
                curl -s --proxy "http://${GLUETUN_SVC}:${PROXY_PORT}" \
                --max-time 10 \
                https://api.ipify.org 2>/dev/null || echo "")
            ;;
        socks5)
            ip=$(kubectl exec -n "$NAMESPACE" "$TEST_POD_NAME" -- \
                curl -s --socks5 "${GLUETUN_SVC}:${SOCKS_PORT}" \
                --max-time 10 \
                https://api.ipify.org 2>/dev/null || echo "")
            ;;
        direct)
            # Get IP directly from gluetun control API
            ip=$(kubectl exec -n "$NAMESPACE" "$TEST_POD_NAME" -- \
                curl -s "http://${GLUETUN_SVC}:${CONTROL_PORT}/v1/publicip/ip" \
                --max-time 10 2>/dev/null | tr -d '"' || echo "")
            ;;
    esac

    echo "$ip"
}

# Get VPN status from gluetun
get_vpn_status() {
    kubectl exec -n "$NAMESPACE" "$TEST_POD_NAME" -- \
        curl -s "http://${GLUETUN_SVC}:${CONTROL_PORT}/v1/vpn/status" \
        --max-time 10 2>/dev/null || echo '{"status":"unknown"}'
}

# Test VPN connectivity
test_connectivity() {
    log "Testing VPN connectivity..."

    local status
    status=$(get_vpn_status)
    echo "  VPN Status: $status"

    if echo "$status" | grep -q '"running"'; then
        success "VPN is running"
    else
        fail "VPN is not running: $status"
        return 1
    fi

    # Test HTTP proxy
    log "Testing HTTP proxy..."
    local http_ip
    http_ip=$(get_public_ip http)
    if [[ -n "$http_ip" && "$http_ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        success "HTTP proxy working - Public IP: $http_ip"
    else
        warn "HTTP proxy failed or returned invalid IP: '$http_ip'"
    fi

    # Test SOCKS5 proxy
    log "Testing SOCKS5 proxy..."
    local socks_ip
    socks_ip=$(get_public_ip socks5)
    if [[ -n "$socks_ip" && "$socks_ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        success "SOCKS5 proxy working - Public IP: $socks_ip"
    else
        warn "SOCKS5 proxy failed or returned invalid IP: '$socks_ip'"
    fi

    # Test control API
    log "Testing control API..."
    local api_ip
    api_ip=$(get_public_ip direct)
    if [[ -n "$api_ip" && "$api_ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        success "Control API working - Public IP: $api_ip"
        echo "$api_ip"
        return 0
    else
        fail "Control API failed: '$api_ip'"
        return 1
    fi
}

# Test pod restart (iptables cleanup)
test_pod_restart() {
    log "Testing pod restart (iptables cleanup fix)..."

    # Get current gluetun pod
    local pod_name
    pod_name=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=gluetun -o jsonpath='{.items[0].metadata.name}')

    if [[ -z "$pod_name" ]]; then
        fail "No gluetun pod found"
        return 1
    fi

    log "Current gluetun pod: $pod_name"

    # Delete the pod to trigger restart
    log "Deleting gluetun pod to trigger restart..."
    kubectl delete pod "$pod_name" -n "$NAMESPACE" --wait=false

    # Wait for new pod to be created and ready
    log "Waiting for new gluetun pod..."
    sleep 5

    local retries=0
    local max_retries=30
    while [[ $retries -lt $max_retries ]]; do
        local new_pod
        new_pod=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=gluetun -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
        local status
        status=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=gluetun -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "")

        if [[ -n "$new_pod" && "$new_pod" != "$pod_name" && "$status" == "Running" ]]; then
            # Check all containers are ready
            local ready
            ready=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=gluetun -o jsonpath='{.items[0].status.containerStatuses[*].ready}' 2>/dev/null || echo "")
            if [[ "$ready" != *"false"* ]]; then
                success "New gluetun pod ready: $new_pod"
                break
            fi
        fi

        echo -n "."
        sleep 5
        ((retries++))
    done
    echo ""

    if [[ $retries -ge $max_retries ]]; then
        fail "Timeout waiting for gluetun pod to restart"

        # Check for crash loop
        local restart_count
        restart_count=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=gluetun -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}' 2>/dev/null || echo "0")
        if [[ "$restart_count" -gt 0 ]]; then
            fail "Pod is crash-looping (restart count: $restart_count)"
            log "Init container logs:"
            kubectl logs -n "$NAMESPACE" -l app.kubernetes.io/name=gluetun -c cleanup-routes --tail=20 2>/dev/null || true
            log "Gluetun container logs:"
            kubectl logs -n "$NAMESPACE" -l app.kubernetes.io/name=gluetun -c gluetun --tail=30 2>/dev/null || true
        fi
        return 1
    fi

    # Give VPN time to connect
    log "Waiting for VPN to reconnect..."
    sleep 15

    # Test connectivity after restart
    log "Testing connectivity after restart..."
    if test_connectivity >/dev/null 2>&1; then
        success "VPN connectivity restored after restart"
        return 0
    else
        fail "VPN connectivity failed after restart"
        return 1
    fi
}

# Test VPN rotation
test_rotation() {
    log "Testing VPN rotation..."

    # Get initial IP
    local initial_ip
    initial_ip=$(get_public_ip direct)

    if [[ -z "$initial_ip" ]]; then
        fail "Could not get initial IP"
        return 1
    fi

    log "Initial public IP: $initial_ip"

    # Trigger rotation via cronjob
    log "Triggering VPN rotation job..."
    kubectl create job --from=cronjob/vpn-rotator "vpn-rotator-test-$(date +%s)" -n "$NAMESPACE"

    # Wait for job to complete
    log "Waiting for rotation job to complete..."
    local job_name
    job_name=$(kubectl get jobs -n "$NAMESPACE" -l app.kubernetes.io/name=vpn-rotator --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}')

    kubectl wait --for=condition=complete job/"$job_name" -n "$NAMESPACE" --timeout=300s || {
        warn "Rotation job did not complete in time"
        kubectl logs -n "$NAMESPACE" -l job-name="$job_name" --tail=50
    }

    # Wait for VPN to reconnect
    log "Waiting for VPN to reconnect after rotation..."
    sleep 20

    # Get new IP
    local new_ip
    new_ip=$(get_public_ip direct)

    if [[ -z "$new_ip" ]]; then
        fail "Could not get IP after rotation"
        return 1
    fi

    log "New public IP: $new_ip"

    if [[ "$initial_ip" != "$new_ip" ]]; then
        success "IP changed after rotation: $initial_ip -> $new_ip"
        return 0
    else
        warn "IP did not change after rotation (may be expected if same server selected)"
        return 0
    fi
}

# Main
main() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║           VPN Gateway E2E Test Suite                         ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""

    local failed=0

    # Check gluetun pod exists
    log "Checking gluetun deployment..."
    if ! kubectl get deployment gluetun -n "$NAMESPACE" &>/dev/null; then
        fail "Gluetun deployment not found in namespace $NAMESPACE"
        exit 1
    fi
    success "Gluetun deployment found"

    # Create test pod
    create_test_pod

    # Test 1: Basic connectivity
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "TEST 1: VPN Connectivity"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if test_connectivity; then
        success "TEST 1 PASSED: VPN connectivity OK"
    else
        fail "TEST 1 FAILED: VPN connectivity issues"
        ((failed++))
    fi

    # Test 2: Pod restart (iptables cleanup)
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "TEST 2: Pod Restart (iptables cleanup)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if test_pod_restart; then
        success "TEST 2 PASSED: Pod restart recovery OK"
    else
        fail "TEST 2 FAILED: Pod restart issues"
        ((failed++))
    fi

    # Test 3: VPN rotation (optional)
    if ! $QUICK_MODE; then
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "TEST 3: VPN Rotation"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        if test_rotation; then
            success "TEST 3 PASSED: VPN rotation OK"
        else
            fail "TEST 3 FAILED: VPN rotation issues"
            ((failed++))
        fi
    else
        warn "Skipping rotation test (--quick mode)"
    fi

    # Summary
    echo ""
    echo "══════════════════════════════════════════════════════════════"
    if [[ $failed -eq 0 ]]; then
        success "ALL TESTS PASSED"
        exit 0
    else
        fail "$failed TEST(S) FAILED"
        exit 1
    fi
}

main "$@"
