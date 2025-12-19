#!/usr/bin/env bash
#
# network-layer-tests.sh - Comprehensive network layer validation for Talos homelab
#
# Tests:
#   - Cilium status and health
#   - SPIRE/mTLS authentication
#   - Inter-node communication (with and without mTLS)
#   - Nebula overlay status
#   - Grafana dashboards availability
#
# Usage: ./scripts/network-layer-tests.sh [--verbose]

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

VERBOSE=${1:-""}
FAILED=0
PASSED=0

log_test() {
    echo -e "${BLUE}[TEST]${NC} $1"
}

log_pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
    ((PASSED++))
}

log_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    ((FAILED++))
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

section() {
    echo ""
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
}

# ============================================================================
# CILIUM TESTS
# ============================================================================

test_cilium_pods() {
    log_test "Cilium pods running on all nodes"
    local cilium_pods
    cilium_pods=$(kubectl get pods -n kube-system -l k8s-app=cilium --no-headers 2>/dev/null | wc -l)
    local node_count
    node_count=$(kubectl get nodes --no-headers 2>/dev/null | wc -l)

    if [[ "$cilium_pods" -eq "$node_count" && "$cilium_pods" -gt 0 ]]; then
        log_pass "Cilium running on all $node_count nodes"
    else
        log_fail "Cilium pods: $cilium_pods, Nodes: $node_count"
    fi
}

test_cilium_health() {
    log_test "Cilium cluster health"
    local cilium_pod
    cilium_pod=$(kubectl get pods -n kube-system -l k8s-app=cilium -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)

    if [[ -z "$cilium_pod" ]]; then
        log_fail "No Cilium pod found"
        return
    fi

    local health
    health=$(kubectl exec -n kube-system "$cilium_pod" -- cilium-dbg status 2>/dev/null | grep "Cluster health" || echo "")

    if echo "$health" | grep -q "reachable"; then
        local reachable
        reachable=$(echo "$health" | grep -oP '\d+/\d+ reachable')
        log_pass "Cilium cluster health: $reachable"
    else
        log_fail "Cilium cluster health check failed"
    fi
}

test_cilium_connectivity() {
    log_test "Cilium node connectivity"
    local cilium_pod
    cilium_pod=$(kubectl get pods -n kube-system -l k8s-app=cilium -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)

    local status
    status=$(kubectl exec -n kube-system "$cilium_pod" -- cilium-dbg status 2>/dev/null | grep "Cilium:" || echo "")

    if echo "$status" | grep -q "Ok"; then
        log_pass "Cilium status: Ok"
    else
        log_fail "Cilium status not Ok"
    fi
}

# ============================================================================
# SPIRE/mTLS TESTS
# ============================================================================

test_spire_server() {
    log_test "SPIRE server running"
    local server_ready
    server_ready=$(kubectl get pods -n cilium-spire -l app=spire-server -o jsonpath='{.items[0].status.containerStatuses[*].ready}' 2>/dev/null | tr ' ' '\n' | grep -c "true" || echo "0")

    if [[ "$server_ready" -ge 1 ]]; then
        log_pass "SPIRE server running (containers ready: $server_ready)"
    else
        log_fail "SPIRE server not ready"
    fi
}

test_spire_agents() {
    log_test "SPIRE agents on all nodes"
    local agent_count
    agent_count=$(kubectl get pods -n cilium-spire -l app=spire-agent --no-headers 2>/dev/null | grep -c "Running" || echo "0")
    local node_count
    node_count=$(kubectl get nodes --no-headers 2>/dev/null | wc -l)

    if [[ "$agent_count" -eq "$node_count" && "$agent_count" -gt 0 ]]; then
        log_pass "SPIRE agents running on all $node_count nodes"
    else
        log_fail "SPIRE agents: $agent_count, Nodes: $node_count"
    fi
}

test_spire_identities() {
    log_test "SPIRE issuing identities"
    local identity_log
    identity_log=$(kubectl logs -n cilium-spire -l app=spire-agent --tail=50 2>/dev/null | grep -c "Fetched X.509 SVID" || echo "0")

    if [[ "$identity_log" -gt 0 ]]; then
        log_pass "SPIRE is actively issuing X.509 SVIDs"
    else
        log_warn "No recent SVID issuance in logs (may be normal if idle)"
    fi
}

test_mtls_auth_table() {
    log_test "mTLS authentication table"
    local cilium_pod
    cilium_pod=$(kubectl get pods -n kube-system -l k8s-app=cilium -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)

    local auth_entries
    auth_entries=$(kubectl exec -n kube-system "$cilium_pod" -- cilium-dbg bpf auth list 2>/dev/null | grep -c "spire" || echo "0")

    if [[ "$auth_entries" -gt 0 ]]; then
        log_pass "mTLS auth table has $auth_entries authenticated pairs"
    else
        log_warn "No mTLS authenticated pairs (may be normal if no mTLS policies active)"
    fi
}

# ============================================================================
# INTER-NODE COMMUNICATION TESTS
# ============================================================================

test_internode_non_mtls() {
    log_test "Inter-node communication (non-mTLS)"

    # Create test pod on talos01, test connectivity to service on talos00
    local test_pod="network-test-$$"

    cat <<EOF | kubectl apply -f - >/dev/null 2>&1
apiVersion: v1
kind: Pod
metadata:
  name: $test_pod
  namespace: default
spec:
  nodeSelector:
    kubernetes.io/hostname: talos01
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    seccompProfile:
      type: RuntimeDefault
  containers:
  - name: curl
    image: curlimages/curl
    command: ["sleep", "60"]
    securityContext:
      allowPrivilegeEscalation: false
      capabilities:
        drop: ["ALL"]
  restartPolicy: Never
EOF

    # Wait for pod
    if ! kubectl wait --for=condition=ready "pod/$test_pod" -n default --timeout=30s >/dev/null 2>&1; then
        kubectl delete pod "$test_pod" -n default --ignore-not-found >/dev/null 2>&1
        log_fail "Could not create test pod"
        return
    fi

    # Test cross-node connectivity to CoreDNS
    local result
    result=$(kubectl exec -n default "$test_pod" -- curl -s --max-time 5 http://kube-dns.kube-system.svc:9153/metrics 2>/dev/null | head -1 || echo "FAIL")

    kubectl delete pod "$test_pod" -n default --ignore-not-found >/dev/null 2>&1

    if echo "$result" | grep -q "HELP\|TYPE"; then
        log_pass "Cross-node non-mTLS connectivity working"
    else
        log_fail "Cross-node non-mTLS connectivity failed"
    fi
}

test_internode_mtls() {
    log_test "Inter-node communication (mTLS)"

    # Check if grpc-go service exists
    if ! kubectl get svc grpc-go -n scratch >/dev/null 2>&1; then
        log_warn "grpc-go service not found in scratch namespace - skipping mTLS test"
        return
    fi

    local test_pod="mtls-test-$$"

    cat <<EOF | kubectl apply -f - >/dev/null 2>&1
apiVersion: v1
kind: Pod
metadata:
  name: $test_pod
  namespace: scratch
  labels:
    app: mtls-test
spec:
  nodeSelector:
    kubernetes.io/hostname: talos01
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    seccompProfile:
      type: RuntimeDefault
  containers:
  - name: curl
    image: curlimages/curl
    command: ["sleep", "60"]
    securityContext:
      allowPrivilegeEscalation: false
      capabilities:
        drop: ["ALL"]
  restartPolicy: Never
EOF

    # Wait for pod
    if ! kubectl wait --for=condition=ready "pod/$test_pod" -n scratch --timeout=30s >/dev/null 2>&1; then
        kubectl delete pod "$test_pod" -n scratch --ignore-not-found >/dev/null 2>&1
        log_fail "Could not create mTLS test pod"
        return
    fi

    # Test mTLS connectivity to grpc-go
    local result
    result=$(kubectl exec -n scratch "$test_pod" -- curl -s --max-time 10 http://grpc-go:9090/health 2>/dev/null || echo "FAIL")

    kubectl delete pod "$test_pod" -n scratch --ignore-not-found >/dev/null 2>&1

    if [[ "$result" == "OK" ]]; then
        log_pass "Cross-node mTLS connectivity working"
    else
        log_fail "Cross-node mTLS connectivity failed (result: $result)"
    fi
}

# ============================================================================
# NEBULA TESTS
# ============================================================================

test_nebula_status() {
    log_test "Nebula overlay network"

    if ! kubectl get ns nebula-system >/dev/null 2>&1; then
        log_warn "Nebula namespace not found - Nebula not deployed"
        return
    fi

    local ds_desired
    ds_desired=$(kubectl get ds nebula -n nebula-system -o jsonpath='{.status.desiredNumberScheduled}' 2>/dev/null || echo "0")
    local ds_ready
    ds_ready=$(kubectl get ds nebula -n nebula-system -o jsonpath='{.status.numberReady}' 2>/dev/null || echo "0")

    if [[ "$ds_desired" -eq 0 ]]; then
        log_warn "Nebula DaemonSet disabled (0 desired pods) - intentionally disabled via nodeSelector"
    elif [[ "$ds_ready" -eq "$ds_desired" && "$ds_ready" -gt 0 ]]; then
        log_pass "Nebula running on $ds_ready/$ds_desired nodes"
    else
        log_fail "Nebula: $ds_ready/$ds_desired nodes ready"
    fi
}

# ============================================================================
# GRAFANA DASHBOARD TESTS
# ============================================================================

test_cilium_dashboards() {
    log_test "Cilium Grafana dashboards"

    local dashboards
    dashboards=$(kubectl get grafanadashboard -n monitoring 2>/dev/null | grep -c "cilium" || echo "0")

    if [[ "$dashboards" -ge 4 ]]; then
        log_pass "$dashboards Cilium dashboards configured"
        if [[ -n "$VERBOSE" ]]; then
            kubectl get grafanadashboard -n monitoring 2>/dev/null | grep cilium | awk '{print "         - " $1}'
        fi
    elif [[ "$dashboards" -gt 0 ]]; then
        log_warn "Only $dashboards Cilium dashboards found (expected 4+)"
    else
        log_fail "No Cilium dashboards found"
    fi
}

test_grafana_running() {
    log_test "Grafana service running"

    local grafana_ready
    grafana_ready=$(kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana-deployment --no-headers 2>/dev/null | grep -c "Running" || echo "0")

    if [[ "$grafana_ready" -gt 0 ]]; then
        log_pass "Grafana is running"
    else
        # Try alternative label
        grafana_ready=$(kubectl get pods -n monitoring 2>/dev/null | grep -c "grafana-deployment.*Running" || echo "0")
        if [[ "$grafana_ready" -gt 0 ]]; then
            log_pass "Grafana is running"
        else
            log_fail "Grafana not running"
        fi
    fi
}

# ============================================================================
# MAIN
# ============================================================================

main() {
    echo -e "${BLUE}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║          Network Layer Validation - Talos Homelab            ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"

    section "Cilium CNI"
    test_cilium_pods
    test_cilium_health
    test_cilium_connectivity

    section "SPIRE / mTLS"
    test_spire_server
    test_spire_agents
    test_spire_identities
    test_mtls_auth_table

    section "Inter-Node Communication"
    test_internode_non_mtls
    test_internode_mtls

    section "Nebula Overlay"
    test_nebula_status

    section "Grafana Dashboards"
    test_grafana_running
    test_cilium_dashboards

    # Summary
    echo ""
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  SUMMARY${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${GREEN}Passed:${NC} $PASSED"
    echo -e "  ${RED}Failed:${NC} $FAILED"
    echo ""

    if [[ "$FAILED" -gt 0 ]]; then
        echo -e "${RED}Some tests failed. Review output above.${NC}"
        exit 1
    else
        echo -e "${GREEN}All tests passed!${NC}"
        exit 0
    fi
}

main "$@"
