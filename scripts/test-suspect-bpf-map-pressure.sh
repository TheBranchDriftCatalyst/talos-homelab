#!/usr/bin/env bash
#
# test-suspect-bpf-map-pressure.sh
#
# Suspect: Cilium BPF map exhaustion (policy / LB / connection-tracking /
# endpoint maps filling up, causing bpf_update_elem -ENOSPC, silent endpoint
# regeneration failures, networking degradation, and eventually apiserver
# unreachability through Cilium's socket-LB).
#
# Background:
#   * 2026-05-21 incident — talos03 hit "Failed to add PolicyMap key: no space
#     left on device". Bumped bpf.policyMapMax 16384 -> 65536. lbMapMax kept
#     at 65536 in proportion.
#   * 2026-05-29/30 — 10 meltdowns in ~24h. Throttle fix moved the cycle from
#     1hr -> 2hr but didn't eliminate. If a Cilium BPF map is filling between
#     restarts (or insert errors are silently piling up), that's a strong
#     candidate.
#   * See also cilium#34700 (BPF panic class), cilium#41108 (apiserver
#     chicken-and-egg via socket-LB).
#
# What this does:
#   1. For each cilium-agent pod, dumps every BPF map's current/max entries
#      via `cilium-dbg bpf <map> list` (or `metrics list` for pressure).
#   2. Prints a per-node, per-map table with utilization %.
#   3. Highlights warnings (>70%) and criticals (>90%).
#   4. Greps `cilium-dbg metrics list` for the policy/bpf/identity-related
#      gauges and counters and shows their values.
#   5. Greps for any nonzero outcome="fail" BPF op counters.
#
# Exit codes:
#   0 — all maps under 70%, no insert errors observed
#   1 — script error (kubectl unavailable, no cilium pods, etc.)
#   2 — at least one map >=90% OR any nonzero insert-error rate
#   3 — at least one map >=70% but none >=90% AND no insert errors
#
# Usage:
#   ./scripts/test-suspect-bpf-map-pressure.sh                 # all pods
#   ./scripts/test-suspect-bpf-map-pressure.sh talos00         # one node
#   ./scripts/test-suspect-bpf-map-pressure.sh --csv > out.csv # machine readable
#   ./scripts/test-suspect-bpf-map-pressure.sh --watch         # repeat every 60s

set -u # NOT -e: keep going if any single pod is unhealthy

# ----------------------------------------------------------------------
# Style
# ----------------------------------------------------------------------
if [[ -t 1 ]]; then
  RED='\033[0;31m'
  GREEN='\033[0;32m'
  YELLOW='\033[1;33m'
  BLUE='\033[0;34m'
  CYAN='\033[0;36m'
  MAGENTA='\033[0;35m'
  GRAY='\033[0;90m'
  BOLD='\033[1m'
  DIM='\033[2m'
  NC='\033[0m'
else
  RED=''
  GREEN=''
  YELLOW=''
  BLUE=''
  CYAN=''
  MAGENTA=''
  GRAY=''
  BOLD=''
  DIM=''
  NC=''
fi

ts() { date '+%H:%M:%S'; }
info() { printf "${GRAY}[%s]${NC} ${BLUE}i${NC}  %b\n" "$(ts)" "$*" >&2; }
ok() { printf "${GRAY}[%s]${NC} ${GREEN}+${NC}  %b\n" "$(ts)" "$*" >&2; }
warn() { printf "${GRAY}[%s]${NC} ${YELLOW}!${NC}  %b\n" "$(ts)" "$*" >&2; }
err() { printf "${GRAY}[%s]${NC} ${RED}x${NC}  %b\n" "$(ts)" "$*" >&2; }
step() { printf "\n${BOLD}${CYAN}== %s ==${NC}\n" "$*" >&2; }

# ----------------------------------------------------------------------
# Args
# ----------------------------------------------------------------------
CSV=false
WATCH=false
FILTER_NODE=""
for arg in "$@"; do
  case "$arg" in
    --csv) CSV=true ;;
    --watch) WATCH=true ;;
    -h | --help)
      sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    -*)
      err "Unknown flag: $arg"
      exit 1
      ;;
    *) FILTER_NODE="$arg" ;;
  esac
done

command -v kubectl > /dev/null || {
  err "kubectl required"
  exit 1
}

# ----------------------------------------------------------------------
# Detect a working timeout command (same pattern as
# scripts/capture-meltdown-evidence.sh — macOS lacks GNU `timeout` by default).
# ----------------------------------------------------------------------
if command -v gtimeout > /dev/null 2>&1; then
  TIMEOUT_CMD=(gtimeout 30)
elif command -v timeout > /dev/null 2>&1; then
  TIMEOUT_CMD=(timeout 30)
else
  TIMEOUT_CMD=() # no timeout available; just run
fi

# Run cilium-dbg in a pod with a timeout
dbg() {
  local pod=$1
  shift
  if [[ ${#TIMEOUT_CMD[@]} -gt 0 ]]; then
    "${TIMEOUT_CMD[@]}" kubectl exec -n kube-system "$pod" -c cilium-agent -- cilium-dbg "$@" 2> /dev/null
  else
    kubectl exec -n kube-system "$pod" -c cilium-agent -- cilium-dbg "$@" 2> /dev/null
  fi
}

# ----------------------------------------------------------------------
# Discover Cilium pods (best effort — apiserver may be flaky)
# ----------------------------------------------------------------------
step "Discovering cilium-agent pods"

mapfile -t pods_nodes < <(
  kubectl get pod -n kube-system -l k8s-app=cilium \
    -o jsonpath='{range .items[*]}{.metadata.name}{"|"}{.spec.nodeName}{"\n"}{end}' 2> /dev/null
)
if [[ ${#pods_nodes[@]} -eq 0 ]]; then
  err "no cilium pods returned by kubectl. apiserver down? Try again or use ./scripts/capture-meltdown-evidence.sh"
  exit 1
fi

if [[ -n "$FILTER_NODE" ]]; then
  filtered=()
  for pn in "${pods_nodes[@]}"; do
    node="${pn##*|}"
    [[ "$node" == "$FILTER_NODE" ]] && filtered+=("$pn")
  done
  pods_nodes=("${filtered[@]}")
  if [[ ${#pods_nodes[@]} -eq 0 ]]; then
    err "no cilium pod found on node '$FILTER_NODE'"
    exit 1
  fi
fi

info "found ${#pods_nodes[@]} cilium agent(s)"

# ----------------------------------------------------------------------
# Per-pod collection
# ----------------------------------------------------------------------
# Rather than parse each map type's separate `cilium-dbg bpf <type> list`
# (formats vary across versions and some maps are huge), we lean on the
# `cilium_bpf_map_pressure` gauge which Cilium exposes for every named map
# it manages. This is the same source Grafana panels and PrometheusRules
# will use, so test-script verdicts match alert verdicts.
#
# We also grep `cilium-dbg metrics list` for the relevant op counters and
# the policy / identity / endpoint gauges.
# ----------------------------------------------------------------------

WARN_PCT=70
CRIT_PCT=90

# Aggregate state for exit code
worst_pct=0
total_insert_errors=0
total_rows=0

# Header for table
if ! $CSV; then
  printf "\n${BOLD}%-14s %-44s %12s %12s${NC}\n" \
    "NODE" "MAP_NAME" "PRESSURE%" "STATUS"
  printf "${DIM}%-14s %-44s %12s %12s${NC}\n" \
    "----" "--------" "---------" "------"
else
  printf "node,pod,map_name,pressure_pct,status\n"
fi

# Map regex to keep things noisy enough for the suspect but not infinite.
# Cilium exposes pressure for: cilium_policy_v2, cilium_lb4_*, cilium_lb6_*,
# cilium_ct4_*, cilium_ct6_*, cilium_lxc, cilium_ipcache_v2, cilium_metrics,
# cilium_node_map_v2, cilium_nodeport_neigh4/6, cilium_signals, cilium_tunnel_map,
# cilium_encrypt_state, cilium_egress_gw_policy_v4, cilium_fragments_*, etc.
MAP_REGEX='cilium_(policy|lb4|lb6|ct4|ct6|lxc|ipcache|node_map|nodeport_neigh|tunnel_map|encrypt|egress|fragments|signals|metrics)'

run_one_pod() {
  local pod=$1 node=$2

  # --- 1. cilium-dbg metrics list -> grep pressure gauges --------------
  # Output line format:
  #   cilium_bpf_map_pressure{map_name="cilium_policy_v2_01234"} 0.0234
  local metrics
  metrics=$(dbg "$pod" metrics list -o json 2> /dev/null) || {
    warn "$node: cilium-dbg metrics list failed (pod probably restarting)"
    return
  }

  # Parse pressure gauges. Use python for robust JSON handling.
  # On older cilium-dbg versions the JSON shape is an array of {name, labels, value}.
  local parsed
  parsed=$(
    echo "$metrics" | python3 - "$MAP_REGEX" << 'PY' 2> /dev/null
import json, re, sys
regex = re.compile(sys.argv[1])
try:
    data = json.load(sys.stdin)
except Exception as e:
    sys.exit(0)
# Cilium metrics list returns either {"metrics":[...]} or a flat list.
if isinstance(data, dict):
    data = data.get("metrics", [])
for m in data:
    name = m.get("name", "")
    if name != "cilium_bpf_map_pressure":
        continue
    labels = m.get("labels", {}) or {}
    map_name = labels.get("map_name") or labels.get("mapname") or ""
    if not regex.search(map_name):
        continue
    try:
        v = float(m.get("value", 0))
    except Exception:
        continue
    print(f"{map_name}\t{v:.6f}")
PY
  )

  if [[ -z "$parsed" ]]; then
    # Fallback: many older builds only expose the gauge via the Prometheus
    # scrape endpoint, not `cilium-dbg metrics list`. Try the /metrics endpoint
    # over the pod IP from inside the pod itself (curl in agent image; if
    # missing, skip).
    parsed=$(
      kubectl exec -n kube-system "$pod" -c cilium-agent -- \
        sh -c 'curl -s http://127.0.0.1:9962/metrics 2>/dev/null || wget -qO- http://127.0.0.1:9962/metrics 2>/dev/null' 2> /dev/null |
        awk -v re="$MAP_REGEX" '
          /^cilium_bpf_map_pressure\{/ {
            # cilium_bpf_map_pressure{map_name="cilium_policy_v2_42"} 0.123
            match($0, /map_name="[^"]+"/)
            if (RLENGTH < 0) next
            mn = substr($0, RSTART+10, RLENGTH-11)
            if (mn ~ re) {
              printf "%s\t%s\n", mn, $NF
            }
          }
        '
    )
  fi

  if [[ -z "$parsed" ]]; then
    warn "$node: no cilium_bpf_map_pressure samples (cilium-agent may not yet have exported the maps you care about)"
    return
  fi

  while IFS=$'\t' read -r map_name value; do
    [[ -z "$map_name" ]] && continue
    # value is 0.0-1.0
    pct=$(awk -v v="$value" 'BEGIN{ printf "%.2f", v*100 }')
    total_rows=$((total_rows + 1))

    # Track worst (use awk to compare floats, set into a temp file because
    # bash doesn't do floats).
    worst_pct=$(awk -v a="$worst_pct" -v b="$pct" 'BEGIN{ print (a>b) ? a : b }')

    status="${GREEN}OK${NC}"
    raw_status="OK"
    if awk -v v="$pct" 'BEGIN{ exit !(v>=90) }'; then
      status="${RED}${BOLD}CRITICAL${NC}"
      raw_status="CRITICAL"
    elif awk -v v="$pct" 'BEGIN{ exit !(v>=70) }'; then
      status="${YELLOW}WARN${NC}"
      raw_status="WARN"
    fi

    if $CSV; then
      printf "%s,%s,%s,%s,%s\n" "$node" "$pod" "$map_name" "$pct" "$raw_status"
    else
      printf "%-14s %-44s %11s%% " "$node" "$map_name" "$pct"
      printf " %b\n" "$status"
    fi
  done <<< "$parsed"

  # --- 2. policy / identity / endpoint counts -------------------------
  # Diagnostic context: even if pressure is low, if identity count or
  # endpoint count is climbing fast, we'll fill the maps soon.
  local diag
  diag=$(
    echo "$metrics" | python3 - << 'PY' 2> /dev/null
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if isinstance(data, dict):
    data = data.get("metrics", [])
want = {
    "cilium_endpoint",                         # gauge: total endpoints
    "cilium_identity",                         # gauge: total identities
    "cilium_policy",                           # gauge: policies imported
    "cilium_policy_endpoint_enforcement_status",
    "cilium_policy_import_errors_total",       # counter: import failures
    "cilium_policy_change_total",
    "cilium_bpf_map_ops_total",                # counter: success/fail per map
}
for m in data:
    name = m.get("name", "")
    if name not in want:
        continue
    labels = m.get("labels", {}) or {}
    v = m.get("value", 0)
    parts = ",".join(f"{k}={v2}" for k, v2 in sorted(labels.items()))
    print(f"  {name}{{{parts}}} = {v}")
PY
  )
  if ! $CSV && [[ -n "$diag" ]]; then
    printf "${DIM}  diagnostics:${NC}\n%s\n" "$diag" | head -20
  fi

  # --- 3. count nonzero op-error counters -----------------------------
  # Anything with outcome="fail" or outcome="error" and value > 0 is real.
  local errs
  errs=$(
    echo "$metrics" | python3 - << 'PY' 2> /dev/null
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if isinstance(data, dict):
    data = data.get("metrics", [])
total = 0
for m in data:
    if m.get("name") != "cilium_bpf_map_ops_total":
        continue
    labels = m.get("labels", {}) or {}
    outcome = labels.get("outcome") or ""
    if outcome not in ("fail", "error"):
        continue
    try:
        v = float(m.get("value", 0))
    except Exception:
        continue
    if v > 0:
        total += v
print(int(total))
PY
  )
  errs=${errs:-0}
  if [[ "$errs" -gt 0 ]]; then
    err "$node: $errs cilium_bpf_map_ops_total{outcome!=success} sample(s) — INSERT ERRORS"
    total_insert_errors=$((total_insert_errors + errs))
  fi
}

# ----------------------------------------------------------------------
# Iterate
# ----------------------------------------------------------------------
iteration() {
  worst_pct=0
  total_insert_errors=0
  total_rows=0
  for pn in "${pods_nodes[@]}"; do
    pod="${pn%%|*}"
    node="${pn##*|}"
    run_one_pod "$pod" "$node"
  done

  # Summary line
  if ! $CSV; then
    printf "\n${BOLD}== Summary ==${NC}\n"
    printf "  rows                : %s\n" "$total_rows"
    printf "  worst map pressure  : %s%%\n" "$worst_pct"
    printf "  insert error count  : %s\n" "$total_insert_errors"
  fi

  # Verdict
  local code=0
  if [[ "$total_insert_errors" -gt 0 ]]; then
    code=2
  elif awk -v v="$worst_pct" 'BEGIN{ exit !(v>=90) }'; then
    code=2
  elif awk -v v="$worst_pct" 'BEGIN{ exit !(v>=70) }'; then
    code=3
  fi

  if ! $CSV; then
    case $code in
      0) ok "PASS — no BPF map pressure detected, no insert errors" ;;
      2) err "FAIL — at least one map >=90% OR insert errors present (suspect CONFIRMED)" ;;
      3) warn "WARN — at least one map >=70% but under 90% (watch closely)" ;;
    esac
  fi
  return $code
}

if $WATCH; then
  while true; do
    iteration || true
    sleep 60
    printf "\n${DIM}-- refresh --${NC}\n"
  done
else
  iteration
  exit $?
fi
