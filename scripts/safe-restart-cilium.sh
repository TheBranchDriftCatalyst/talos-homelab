#!/usr/bin/env bash
#
# Safe Cilium DaemonSet restart — one node at a time, with health gates.
#
# Why: `kubectl rollout restart ds cilium` is technically rolling, but in
# practice multiple agents go down concurrently because of fast termination +
# slow startup. On 2026-05-21 this combined with a broken admission webhook
# (opentelemetry-operator with failurePolicy=Fail and no Ready endpoints) to
# cause a 40-minute control-plane outage. See:
#   docs/06-troubleshooting/2026-05-21-cilium-cascading-meltdown.md
#
# This script restarts agents one at a time, waits for each new pod to be
# Running AND for `cilium-dbg status` to return OK before moving on. Also
# pre-flights admission webhook health (same check as upgrade-talos.py /
# shutdown-cluster.sh).
#
# Usage:
#   ./scripts/safe-restart-cilium.sh             # interactive
#   ./scripts/safe-restart-cilium.sh --yes       # skip confirmation
#   ./scripts/safe-restart-cilium.sh --dry-run   # show plan only

set -euo pipefail

NODE_READY_TIMEOUT="${NODE_READY_TIMEOUT:-180}"
SETTLE_BETWEEN_NODES="${SETTLE_BETWEEN_NODES:-15}"

ASSUME_YES=false
DRY_RUN=false
for arg in "$@"; do
  case "$arg" in
    --yes | -y) ASSUME_YES=true ;;
    --dry-run | -n) DRY_RUN=true ;;
    -h | --help)
      sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown arg: $arg" >&2
      exit 2
      ;;
  esac
done

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

ts() { date '+%H:%M:%S'; }
info() { printf "${GRAY}[%s]${NC} ${BLUE}ℹ${NC}  %b\n" "$(ts)" "$*"; }
ok() { printf "${GRAY}[%s]${NC} ${GREEN}✓${NC}  %b\n" "$(ts)" "$*"; }
warn() { printf "${GRAY}[%s]${NC} ${YELLOW}⚠${NC}  %b\n" "$(ts)" "$*"; }
err() { printf "${GRAY}[%s]${NC} ${RED}✗${NC}  %b\n" "$(ts)" "$*" >&2; }
step() { printf "\n${BOLD}${CYAN}┏━━ %s ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n" "$*"; }

run() {
  if $DRY_RUN; then
    printf "  ${DIM}[dry-run]${NC} %s\n" "$*"
  else
    "$@"
  fi
}

printf "${MAGENTA}"
cat << 'EOF'
   ____  _____   _____ _______       _____ _______
  |  _ \|  __ \ / ____|__   __|/\   |  __ \__   __|
  | |_) | |__) | (___    | |  /  \  | |__) | | |
  |  _ <|  _  / \___ \   | | / /\ \ |  _  /  | |
  | |_) | | \ \ ____) |  | |/ ____ \| | \ \  | |
  |____/|_|  \_\_____/   |_/_/    \_\_|  \_\ |_|

  catalyst-cluster · safe cilium daemonset restart
EOF
printf "${NC}\n"

# ----------------------------------------------------------------------
# Pre-flight: webhook health
# ----------------------------------------------------------------------
step "Pre-flight: admission webhook health"

command -v kubectl > /dev/null || {
  err "kubectl required"
  exit 1
}

broken=()
for kind in mutatingwebhookconfigurations validatingwebhookconfigurations; do
  while IFS=$'\t' read -r svc_ns svc_name fail_policy; do
    [[ -z "$svc_ns" || -z "$svc_name" ]] && continue
    ips=$(kubectl get endpoints -n "$svc_ns" "$svc_name" \
      -o jsonpath='{.subsets[*].addresses[*].ip}' 2> /dev/null || true)
    if [[ -z "$ips" ]]; then
      broken+=("$svc_ns/$svc_name (failurePolicy=$fail_policy)")
    fi
  done < <(kubectl get "$kind" -o jsonpath='{range .items[*].webhooks[*]}{.clientConfig.service.namespace}{"\t"}{.clientConfig.service.name}{"\t"}{.failurePolicy}{"\n"}{end}' 2> /dev/null | sort -u)
done

if [[ ${#broken[@]} -gt 0 ]]; then
  err "broken admission webhook backends detected:"
  for b in "${broken[@]}"; do err "  $b"; done
  err "Fix or delete these BEFORE restarting Cilium. A Cilium pod restart"
  err "needs to call apiserver, which calls these webhooks. Broken webhooks"
  err "with failurePolicy=Fail cause cluster-wide pod admission stalls."
  $ASSUME_YES || exit 1
  warn "--yes set — proceeding despite broken webhooks (NOT recommended)"
fi
ok "all admission webhook backends have Ready endpoints"

# ----------------------------------------------------------------------
# Discover Cilium pods and their nodes
# ----------------------------------------------------------------------
step "Discover Cilium DaemonSet pods"
mapfile -t cilium_pods < <(kubectl get pod -n kube-system -l k8s-app=cilium -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.nodeName}{"\n"}{end}' 2> /dev/null)
if [[ ${#cilium_pods[@]} -eq 0 ]]; then
  err "no Cilium pods found"
  exit 1
fi

printf "  ${BOLD}%-35s %s${NC}\n" "POD" "NODE"
for entry in "${cilium_pods[@]}"; do
  pod=$(awk '{print $1}' <<< "$entry")
  node=$(awk '{print $2}' <<< "$entry")
  printf "  %-35s %s\n" "$pod" "$node"
done

if ! $ASSUME_YES && ! $DRY_RUN; then
  echo
  read -rp "$(printf "${YELLOW}This will restart Cilium agents one at a time. Type 'yes' to proceed: ${NC}")" confirm
  [[ "$confirm" == "yes" ]] || {
    err "aborted"
    exit 1
  }
fi

# ----------------------------------------------------------------------
# Restart pods one at a time
# ----------------------------------------------------------------------
T_START=$(date +%s)

wait_ready() {
  local node=$1
  local deadline=$(($(date +%s) + NODE_READY_TIMEOUT))
  while (($(date +%s) < deadline)); do
    local new_pod ready
    new_pod=$(kubectl get pod -n kube-system -l k8s-app=cilium \
      --field-selector spec.nodeName="$node" --no-headers 2> /dev/null | awk '{print $1}' | head -1)
    [[ -z "$new_pod" ]] && {
      sleep 5
      continue
    }
    ready=$(kubectl get pod -n kube-system "$new_pod" \
      -o jsonpath='{.status.containerStatuses[?(@.name=="cilium-agent")].ready}' 2> /dev/null)
    if [[ "$ready" == "true" ]]; then
      # Also check cilium-dbg status reports OK
      if kubectl exec -n kube-system "$new_pod" -- cilium-dbg status --brief 2> /dev/null | grep -q "^OK$"; then
        echo "$new_pod"
        return 0
      fi
    fi
    printf "${GRAY}[%s]${NC} ${DIM}waiting for cilium on %s…${NC}\r" "$(ts)" "$node"
    sleep 5
    printf "\033[K"
  done
  return 1
}

failed=0
for entry in "${cilium_pods[@]}"; do
  pod=$(awk '{print $1}' <<< "$entry")
  node=$(awk '{print $2}' <<< "$entry")

  step "Restart cilium on $node ($pod)"
  if $DRY_RUN; then
    printf "  ${DIM}[dry-run]${NC} kubectl delete pod -n kube-system %s\n" "$pod"
    continue
  fi

  kubectl delete pod -n kube-system "$pod" > /dev/null 2>&1 || {
    warn "delete failed for $pod (continuing)"
    continue
  }
  ok "deleted $pod"

  if new_pod=$(wait_ready "$node"); then
    ok "new pod ${BOLD}$new_pod${NC} on $node is ready + healthy"
  else
    err "timeout waiting for cilium to come back on $node after ${NODE_READY_TIMEOUT}s"
    failed=$((failed + 1))
    if ! $ASSUME_YES; then
      read -rp "$(printf "${YELLOW}Continue with remaining nodes? Type 'yes' to continue: ${NC}")" cont
      [[ "$cont" == "yes" ]] || {
        err "aborted"
        exit 1
      }
    fi
  fi

  if ((SETTLE_BETWEEN_NODES > 0)); then
    info "settling ${SETTLE_BETWEEN_NODES}s before next node"
    sleep "$SETTLE_BETWEEN_NODES"
  fi
done

# ----------------------------------------------------------------------
# Summary
# ----------------------------------------------------------------------
total_s=$(($(date +%s) - T_START))
printf "\n${BOLD}${MAGENTA}┏━━ Summary ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
kubectl get pod -n kube-system -l k8s-app=cilium -o wide 2>&1 | head -10
echo
if ((failed > 0)); then
  err "$failed node(s) had issues during restart — investigate before assuming success"
  exit 1
fi
ok "all cilium agents restarted cleanly in $((total_s / 60))m$((total_s % 60))s"
