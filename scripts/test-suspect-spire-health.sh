#!/usr/bin/env bash
#
# test-suspect-spire-health.sh
#
# Investigates SPIRE socket/identity issues as a potential contributor to
# the cilium-agent meltdown cascade observed on the single-CP Talos cluster.
#
# HYPOTHESIS
# ----------
# SPIRE has been broken for 20+ days (spire-server StatefulSet has been
# stuck at 0/1 Ready). cilium-agent uses SPIRE for mTLS service mesh
# authentication. When the SPIRE admin socket is unavailable, cilium logs
# warnings every ~10s but keeps running:
#
#   "SPIRE Delegate API Client failed to init watcher, retrying
#    error=\"SPIRE admin socket (/run/spire/sockets/admin.sock) does not exist\""
#
# Counter-evidence: cilium has been running with broken SPIRE for 20 days
# without ALWAYS causing meltdowns. So SPIRE alone is not deterministic.
# BUT — under apiserver pressure or network jitter, the mesh-auth controller
# could deadlock waiting for SPIRE I/O that never completes, blocking
# reconciliation and slowing /healthz responses.
#
# This script:
#   1. Inventories SPIRE namespace state
#   2. Checks why spire-server is 0/1 (probably PVC binding or cert issue)
#   3. Checks spire-agent DaemonSet coverage (1 pod per node?)
#   4. Inspects /run/spire/sockets/ inside a cilium-agent pod
#   5. Pulls mesh-auth controller state from cilium-dbg status
#   6. Checks cilium auth/mutual metrics
#   7. Queries Loki for SPIRE warning frequency over the last 1h
#
# Usage:
#   ./scripts/test-suspect-spire-health.sh
#
# Resilient to cluster intermittency — every command tolerates failure
# and continues.

set -u # NOT -e: we want to keep going even if individual commands fail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

pass() {
  printf "${GREEN}[PASS]${NC} %s\n" "$*"
  PASS=$((PASS + 1))
}
fail() {
  printf "${RED}[FAIL]${NC} %s\n" "$*"
  FAIL=$((FAIL + 1))
}
warn() {
  printf "${YELLOW}[WARN]${NC} %s\n" "$*"
  WARN=$((WARN + 1))
}
info() { printf "${BLUE}[INFO]${NC} %s\n" "$*"; }
section() { printf "\n${CYAN}=== %s ===${NC}\n" "$*"; }

# Resilient kubectl wrapper — short timeout so a degraded apiserver
# doesn't hang the script.
k() {
  kubectl --request-timeout=15s "$@" 2>&1
}

EXPECTED_NODE_COUNT=5

section "Pre-flight: cluster reachability"
if ! k version --short > /dev/null 2>&1; then
  warn "kubectl version failed — cluster may be degraded, continuing best-effort"
fi
node_count=$(k get nodes --no-headers 2> /dev/null | wc -l | tr -d ' ')
info "kube nodes reported: $node_count (expected $EXPECTED_NODE_COUNT)"

# --------------------------------------------------------------------
# 1. SPIRE namespace inventory
# --------------------------------------------------------------------
section "1. SPIRE namespace state (cilium-spire)"
k get all -n cilium-spire 2>&1 | head -40 || warn "cannot list cilium-spire namespace"

# --------------------------------------------------------------------
# 2. spire-server status
# --------------------------------------------------------------------
section "2. spire-server StatefulSet status"

ss_ready=$(k get statefulset -n cilium-spire spire-server \
  -o jsonpath='{.status.readyReplicas}' 2> /dev/null)
ss_desired=$(k get statefulset -n cilium-spire spire-server \
  -o jsonpath='{.spec.replicas}' 2> /dev/null)
info "spire-server StatefulSet: readyReplicas=${ss_ready:-?}/${ss_desired:-?}"

if [ "${ss_ready:-0}" = "${ss_desired:-1}" ] && [ "${ss_ready:-0}" -ge 1 ] 2> /dev/null; then
  pass "spire-server StatefulSet is fully Ready"
else
  fail "spire-server StatefulSet is degraded (${ss_ready:-0}/${ss_desired:-1})"
fi

echo
info "spire-server pod state:"
k get pod -n cilium-spire -l app=spire-server -o wide 2>&1

echo
info "spire-server pod describe (last 30 lines — events at bottom):"
ss_pod=$(k get pod -n cilium-spire -l app=spire-server \
  -o jsonpath='{.items[0].metadata.name}' 2> /dev/null)
if [ -n "$ss_pod" ]; then
  k describe pod -n cilium-spire "$ss_pod" 2>&1 | tail -40
else
  fail "no spire-server pod found"
fi

echo
info "spire-server pod logs (last 50 lines):"
if [ -n "$ss_pod" ]; then
  k logs -n cilium-spire "$ss_pod" --tail=50 2>&1
fi

echo
info "spire-server PVC status (common 0/1 cause: PVC pending):"
k get pvc -n cilium-spire 2>&1

# --------------------------------------------------------------------
# 3. spire-agent DaemonSet coverage
# --------------------------------------------------------------------
section "3. spire-agent DaemonSet coverage"

ds_ready=$(k get ds -n cilium-spire spire-agent \
  -o jsonpath='{.status.numberReady}' 2> /dev/null)
ds_desired=$(k get ds -n cilium-spire spire-agent \
  -o jsonpath='{.status.desiredNumberScheduled}' 2> /dev/null)
info "spire-agent DaemonSet: ready=${ds_ready:-?}/${ds_desired:-?}"

if [ "${ds_ready:-0}" = "${ds_desired:-0}" ] && [ "${ds_ready:-0}" -ge 1 ] 2> /dev/null; then
  pass "spire-agent DaemonSet has full coverage"
else
  fail "spire-agent DaemonSet incomplete (${ds_ready:-0}/${ds_desired:-0})"
fi

echo
info "spire-agent pods per node:"
k get pod -n cilium-spire -l app=spire-agent -o wide 2>&1

echo
info "spire-agent recent logs (any one pod, last 30 lines):"
agent_pod=$(k get pod -n cilium-spire -l app=spire-agent \
  -o jsonpath='{.items[0].metadata.name}' 2> /dev/null)
if [ -n "$agent_pod" ]; then
  k logs -n cilium-spire "$agent_pod" --tail=30 2>&1
fi

# --------------------------------------------------------------------
# 4. SPIRE admin socket from inside a cilium-agent pod
# --------------------------------------------------------------------
section "4. SPIRE admin socket visibility from cilium-agent"

cilium_pod=$(k get pod -n kube-system -l k8s-app=cilium \
  -o jsonpath='{.items[0].metadata.name}' 2> /dev/null)

if [ -z "$cilium_pod" ]; then
  fail "no cilium-agent pod found"
else
  info "Inspecting cilium-agent pod: $cilium_pod"
  echo
  info "ls /run/spire/sockets/ (expect admin.sock + agent.sock):"
  socket_listing=$(k exec -n kube-system "$cilium_pod" -- ls -la /run/spire/sockets/ 2>&1)
  echo "$socket_listing"

  if echo "$socket_listing" | grep -q "admin.sock"; then
    pass "SPIRE admin.sock present in cilium-agent pod"
  else
    fail "SPIRE admin.sock MISSING in cilium-agent pod (matches the recurring warning)"
  fi

  if echo "$socket_listing" | grep -q "agent.sock"; then
    pass "SPIRE agent.sock present in cilium-agent pod"
  else
    fail "SPIRE agent.sock MISSING in cilium-agent pod"
  fi
fi

# --------------------------------------------------------------------
# 5. cilium-agent mesh-auth controller state
# --------------------------------------------------------------------
section "5. cilium mesh-auth controller state"
if [ -n "$cilium_pod" ]; then
  info "cilium-dbg status (auth / spire / mesh lines only):"
  k exec -n kube-system "$cilium_pod" -- cilium-dbg status --verbose 2>&1 |
    grep -iE "mesh-auth|auth|spire|mutual" |
    head -40 || warn "no matching status lines"

  echo
  info "controllers with auth/spire/mesh in name:"
  k exec -n kube-system "$cilium_pod" -- cilium-dbg status --all-controllers 2>&1 |
    grep -iE "auth|spire|mesh" |
    head -20 || warn "no matching controller lines"
fi

# --------------------------------------------------------------------
# 6. cilium-agent metrics — auth / mutual
# --------------------------------------------------------------------
section "6. cilium-agent auth/mutual metrics"
if [ -n "$cilium_pod" ]; then
  info "metrics matching auth|spire|mutual:"
  k exec -n kube-system "$cilium_pod" -- cilium-dbg metrics list 2>&1 |
    grep -iE "auth|spire|mutual" |
    head -40 || warn "no auth/spire/mutual metrics exposed"
fi

# --------------------------------------------------------------------
# 7. Loki frequency of the SPIRE init-watcher warning
# --------------------------------------------------------------------
section "7. Loki — SPIRE warning frequency over last 1h"

loki_url="http://loki-gateway.monitoring.svc.cluster.local/loki/api/v1/query"

# Use a kubectl run debug pod to query Loki — keeps the script self-contained.
loki_query='sum(count_over_time({namespace="kube-system",app="cilium"} |~ "SPIRE.*failed to init" [1h]))'

info "Loki query: $loki_query"
info "(querying via in-cluster service)"

# Use a temporary curl pod (debian/curl image is small + reliable).
loki_result=$(k run loki-spire-probe \
  --rm -i --restart=Never --image=curlimages/curl:8.10.1 \
  --quiet \
  --request-timeout=30s \
  -- sh -c "curl -s -G '$loki_url' --data-urlencode 'query=$loki_query' --max-time 15" 2>&1)

echo "$loki_result"
echo

# Extract the result count if jq-friendly
count=$(echo "$loki_result" | grep -oE '"value":\[[0-9.]+,"[0-9.]+"' |
  grep -oE '"[0-9.]+"$' | tr -d '"' | head -1)
if [ -n "$count" ]; then
  info "SPIRE init-watcher warning count over last 1h: $count"
  # Roughly: 10s interval = 360/h per pod. With 5 pods that's ~1800/h.
  if [ "${count%.*}" -gt 1000 ] 2> /dev/null; then
    fail "chronic SPIRE flapping (>1000 warnings/h) — confirms socket is consistently absent"
  elif [ "${count%.*}" -gt 100 ] 2> /dev/null; then
    warn "elevated SPIRE warning rate ($count/h) — socket intermittently absent"
  else
    pass "SPIRE warning rate is low ($count/h)"
  fi
else
  warn "could not extract count from Loki response (Loki may be unreachable)"
fi

# --------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------
section "Summary"
printf "  ${GREEN}PASS:${NC} %d   ${RED}FAIL:${NC} %d   ${YELLOW}WARN:${NC} %d\n" "$PASS" "$FAIL" "$WARN"
echo

if [ "$FAIL" -gt 0 ]; then
  printf "${RED}SPIRE health checks FAILED — suspect is supported by evidence.${NC}\n"
  echo "Likely contributor to the meltdowns IF the chronic SPIRE absence"
  echo "occasionally causes cilium-agent mesh-auth I/O to block during"
  echo "high-latency periods. See markdown summary for recommended fix."
  exit 1
elif [ "$WARN" -gt 0 ]; then
  printf "${YELLOW}SPIRE health checks PASSED with warnings — partial suspect signal.${NC}\n"
  exit 0
else
  printf "${GREEN}SPIRE health checks all PASSED — this suspect is largely cleared.${NC}\n"
  exit 0
fi
