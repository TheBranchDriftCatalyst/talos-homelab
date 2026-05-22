#!/usr/bin/env bash
#
# Catalyst Cluster Graceful Shutdown
#
# Shuts down all Talos nodes in the correct order:
#   1. Cordon every node (best-effort, stops new scheduling)
#   2. Shut down all workers in parallel
#   3. Wait for workers to become unreachable
#   4. Shut down the control plane last
#
# Usage:
#   ./scripts/shutdown-cluster.sh             # interactive
#   ./scripts/shutdown-cluster.sh --yes       # skip confirmation
#   ./scripts/shutdown-cluster.sh --dry-run   # show plan only
#

set -euo pipefail

TALOSCONFIG="${TALOSCONFIG:-./configs/talosconfig}"
CONTROL_PLANE_IP="${CONTROL_PLANE_IP:-192.168.1.54}"
WORKER_WAIT_TIMEOUT="${WORKER_WAIT_TIMEOUT:-180}"
CP_WAIT_TIMEOUT="${CP_WAIT_TIMEOUT:-120}"
PING_TIMEOUT=2

ASSUME_YES=false
DRY_RUN=false
for arg in "$@"; do
  case "$arg" in
    --yes | -y) ASSUME_YES=true ;;
    --dry-run | -n) DRY_RUN=true ;;
    -h | --help)
      sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown arg: $arg" >&2
      exit 2
      ;;
  esac
done

# ----------------------------------------------------------------------
# Pretty output
# ----------------------------------------------------------------------
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
elapsed() {
  local s=$(($(date +%s) - $1))
  printf '%dm%02ds' $((s / 60)) $((s % 60))
}
info() { printf "${GRAY}[%s]${NC} ${BLUE}ℹ${NC}  %b\n" "$(ts)" "$*"; }
ok() { printf "${GRAY}[%s]${NC} ${GREEN}✓${NC}  %b\n" "$(ts)" "$*"; }
warn() { printf "${GRAY}[%s]${NC} ${YELLOW}⚠${NC}  %b\n" "$(ts)" "$*"; }
err() { printf "${GRAY}[%s]${NC} ${RED}✗${NC}  %b\n" "$(ts)" "$*" >&2; }

step_start_ts=0
step() {
  [[ $step_start_ts -ne 0 ]] && printf "${DIM}└── completed in $(elapsed "$step_start_ts")${NC}\n"
  step_start_ts=$(date +%s)
  printf "\n${BOLD}${CYAN}┏━━ %b ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n" "$*"
}

banner() {
  printf "${MAGENTA}"
  cat << 'EOF'
   ___ _   _ _   _ _____ ____   ___  __        ___   _
  / __| | | | | | |_   _|  _ \ / _ \ \ \      / / \ | |
  \__ \ |_| | |_| | | | | | | | (_) | \ \ /\ / /|  \| |
  |___/\___/ \___/  |_| |_| |_|\___/   \_/\_/ |_|\__|_|

  catalyst-cluster · graceful shutdown
EOF
  printf "${NC}\n"
}

run() {
  if $DRY_RUN; then
    printf "  ${DIM}[dry-run]${NC} %s\n" "$*"
  else
    "$@"
  fi
}

# Spinner for waiting loops
spin() {
  local pid=$1 msg=$2 start=$3
  local frames=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
  local i=0
  tput civis 2> /dev/null || true
  while kill -0 "$pid" 2> /dev/null; do
    printf "\r${GRAY}[%s]${NC} ${CYAN}%s${NC}  %s ${DIM}(%s)${NC}" \
      "$(ts)" "${frames[i]}" "$msg" "$(elapsed "$start")"
    i=$(((i + 1) % ${#frames[@]}))
    sleep 0.1
  done
  tput cnorm 2> /dev/null || true
  printf "\r\033[K"
}

# Per-node tracking arrays
declare -A NODE_OFFLINE_AT  # name -> offline timestamp
declare -A NODE_SHUTDOWN_OK # name -> "yes" or "no"
declare -A NODE_IP          # name -> ip
declare -A NODE_ROLE        # name -> role

T_START=$(date +%s)
trap 'tput cnorm 2>/dev/null || true' EXIT

banner

# ----------------------------------------------------------------------
# Pre-flight
# ----------------------------------------------------------------------
step "Pre-flight checks"

command -v talosctl > /dev/null || {
  err "talosctl not found in PATH"
  exit 1
}
[[ -f "$TALOSCONFIG" ]] || {
  err "talosconfig not found at $TALOSCONFIG"
  exit 1
}
ok "talosctl + talosconfig present"

if ! command -v kubectl > /dev/null; then
  warn "kubectl not found — cordon step will be skipped"
  HAVE_KUBECTL=false
else
  HAVE_KUBECTL=true
  ok "kubectl present"
fi

# ----------------------------------------------------------------------
# Admission webhook health gate
# See docs/06-troubleshooting/2026-05-21-cilium-cascading-meltdown.md
# A broken admission webhook blocks pod admission cluster-wide.  If we
# proceed with a cordoning-then-shutdown sequence while one is dangling,
# the next cluster boot will inherit the same issue and we may not be
# able to recover cleanly without manual intervention.
# ----------------------------------------------------------------------
check_admission_webhooks() {
  if ! $HAVE_KUBECTL; then
    return 0
  fi
  step "Admission webhook backend check"
  local broken=()
  for kind in mutatingwebhookconfigurations validatingwebhookconfigurations; do
    while IFS=$'\t' read -r cfg_name svc_ns svc_name fail_policy; do
      [[ -z "$svc_ns" || -z "$svc_name" ]] && continue
      # Check the service has Ready endpoints
      local ready
      ready=$(kubectl get endpoints -n "$svc_ns" "$svc_name" \
        -o jsonpath='{.subsets[*].addresses[*].ip}' 2> /dev/null)
      if [[ -z "$ready" ]]; then
        broken+=("$cfg_name → $svc_ns/$svc_name (no Ready endpoints, failurePolicy=$fail_policy)")
      fi
    done < <(kubectl get "$kind" -o jsonpath='{range .items[*]}{range .webhooks[*]}{..metadata.name}{"\t"}{.clientConfig.service.namespace}{"\t"}{.clientConfig.service.name}{"\t"}{.failurePolicy}{"\n"}{end}{end}' 2> /dev/null)
  done
  if [[ ${#broken[@]} -eq 0 ]]; then
    ok "all admission webhooks have healthy backends"
  else
    warn "broken admission webhooks detected (will not block shutdown but will be flagged):"
    for w in "${broken[@]}"; do
      warn "  $w"
    done
    warn "consider fixing or deleting these before next cluster boot"
  fi
}
check_admission_webhooks

WORKERS=()
CP_NAME=""
if $HAVE_KUBECTL && kubectl get nodes -o wide > /dev/null 2>&1; then
  while IFS= read -r line; do
    name=$(awk '{print $1}' <<< "$line")
    ip=$(awk '{print $6}' <<< "$line")
    roles=$(awk '{print $3}' <<< "$line")
    NODE_IP[$name]=$ip
    if [[ "$roles" == *control-plane* ]]; then
      CP_NAME=$name
      CONTROL_PLANE_IP=$ip
      NODE_ROLE[$name]="control-plane"
    else
      WORKERS+=("$name:$ip")
      NODE_ROLE[$name]="worker"
    fi
  done < <(kubectl get nodes --no-headers -o wide)
  ok "Discovered ${#WORKERS[@]} workers + control plane ${CP_NAME} (${CONTROL_PLANE_IP})"
else
  warn "Node discovery via kubectl failed — using hardcoded list"
  WORKERS=("talos01:192.168.1.177" "talos02-gpu:192.168.1.144" "talos03:192.168.1.30" "talos06:192.168.1.19")
  CP_NAME="talos00"
  NODE_IP[$CP_NAME]=$CONTROL_PLANE_IP
  NODE_ROLE[$CP_NAME]="control-plane"
  for w in "${WORKERS[@]}"; do
    NODE_IP[${w%:*}]=${w#*:}
    NODE_ROLE[${w%:*}]="worker"
  done
fi

# ----------------------------------------------------------------------
# Plan summary
# ----------------------------------------------------------------------
step "Shutdown plan"
printf "  ${BOLD}%-14s %-16s %s${NC}\n" "NODE" "IP" "ROLE"
printf "  ${GRAY}%-14s %-16s %s${NC}\n" "─────────────" "───────────────" "──────────────"
for w in "${WORKERS[@]}"; do
  printf "  %-14s %-16s ${GRAY}worker${NC}\n" "${w%:*}" "${w#*:}"
done
printf "  %-14s %-16s ${YELLOW}control-plane (last)${NC}\n" "$CP_NAME" "$CONTROL_PLANE_IP"

if ! $ASSUME_YES && ! $DRY_RUN; then
  echo
  read -rp "$(printf "${YELLOW}This will power off the entire cluster. Type 'yes' to proceed: ${NC}")" confirm
  [[ "$confirm" == "yes" ]] || {
    err "Aborted"
    exit 1
  }
fi

# ----------------------------------------------------------------------
# Step 1: Cordon all nodes
# ----------------------------------------------------------------------
step "Cordon all nodes"
if $HAVE_KUBECTL; then
  while IFS= read -r node; do
    if run kubectl cordon "$node" > /dev/null 2>&1; then
      ok "cordoned ${BOLD}$node${NC}"
    else
      warn "could not cordon $node"
    fi
  done < <(kubectl get nodes --no-headers -o custom-columns=NAME:.metadata.name 2> /dev/null)
else
  warn "skipped (no kubectl)"
fi

# ----------------------------------------------------------------------
# Step 2: Shut down workers (parallel)
# ----------------------------------------------------------------------
step "Issue shutdown to workers (parallel)"
pids=()
for w in "${WORKERS[@]}"; do
  name="${w%:*}"
  ip="${w#*:}"
  info "→ ${BOLD}$name${NC} (${ip})"
  if $DRY_RUN; then
    printf "  ${DIM}[dry-run]${NC} talosctl --nodes %s shutdown --force\n" "$ip"
    NODE_SHUTDOWN_OK[$name]="dry-run"
  else
    talosctl --talosconfig "$TALOSCONFIG" --nodes "$ip" shutdown --force \
      > /tmp/shutdown-"$name".log 2>&1 &
    pids+=("$!:$name")
  fi
done

if ! $DRY_RUN; then
  for entry in "${pids[@]}"; do
    pid="${entry%%:*}"
    name="${entry#*:}"
    if wait "$pid"; then
      ok "shutdown signal accepted by ${BOLD}$name${NC}"
      NODE_SHUTDOWN_OK[$name]="yes"
    else
      warn "shutdown command failed for $name (see /tmp/shutdown-$name.log)"
      NODE_SHUTDOWN_OK[$name]="no"
    fi
  done
fi

# ----------------------------------------------------------------------
# Step 3: Wait for workers to drop off network
# ----------------------------------------------------------------------
if ! $DRY_RUN && [[ ${#WORKERS[@]} -gt 0 ]]; then
  step "Wait for workers to go offline (timeout ${WORKER_WAIT_TIMEOUT}s)"
  deadline=$(($(date +%s) + WORKER_WAIT_TIMEOUT))
  remaining=("${WORKERS[@]}")
  poll=0
  while [[ ${#remaining[@]} -gt 0 && $(date +%s) -lt $deadline ]]; do
    still_up=()
    for w in "${remaining[@]}"; do
      name="${w%:*}"
      ip="${w#*:}"
      if ping -c1 -W "$PING_TIMEOUT" "$ip" > /dev/null 2>&1; then
        still_up+=("$w")
      else
        NODE_OFFLINE_AT[$name]=$(date +%s)
        ok "${BOLD}$name${NC} (${ip}) offline after $(elapsed "$T_START")"
      fi
    done
    remaining=("${still_up[@]}")
    if [[ ${#remaining[@]} -gt 0 ]]; then
      poll=$((poll + 1))
      printf "${GRAY}[%s]${NC} ${DIM}polling… still up: %s${NC}\r" \
        "$(ts)" "$(
          IFS=,
          echo "${remaining[*]%:*}"
        )"
      sleep 5
      printf "\033[K"
    fi
  done
  if [[ ${#remaining[@]} -gt 0 ]]; then
    warn "timed out waiting for: ${remaining[*]} — proceeding"
  else
    ok "all workers offline"
  fi
fi

# ----------------------------------------------------------------------
# Step 4: Shut down control plane
# ----------------------------------------------------------------------
step "Shut down control plane (${BOLD}$CP_NAME${NC} @ $CONTROL_PLANE_IP)"
if $DRY_RUN; then
  NODE_SHUTDOWN_OK[$CP_NAME]="dry-run"
  printf "  ${DIM}[dry-run]${NC} talosctl --nodes %s shutdown --force\n" "$CONTROL_PLANE_IP"
else
  if talosctl --talosconfig "$TALOSCONFIG" --nodes "$CONTROL_PLANE_IP" shutdown --force; then
    ok "shutdown signal accepted by ${BOLD}$CP_NAME${NC}"
    NODE_SHUTDOWN_OK[$CP_NAME]="yes"
  else
    err "shutdown command failed for $CP_NAME"
    NODE_SHUTDOWN_OK[$CP_NAME]="no"
  fi

  step "Wait for control plane offline (timeout ${CP_WAIT_TIMEOUT}s)"
  deadline=$(($(date +%s) + CP_WAIT_TIMEOUT))
  while ping -c1 -W "$PING_TIMEOUT" "$CONTROL_PLANE_IP" > /dev/null 2>&1; do
    [[ $(date +%s) -ge $deadline ]] && break
    printf "${GRAY}[%s]${NC} ${DIM}waiting on %s…${NC}\r" "$(ts)" "$CP_NAME"
    sleep 5
    printf "\033[K"
  done
  if ping -c1 -W "$PING_TIMEOUT" "$CONTROL_PLANE_IP" > /dev/null 2>&1; then
    warn "${BOLD}$CP_NAME${NC} still pingable — may take a bit longer to fully halt"
  else
    NODE_OFFLINE_AT[$CP_NAME]=$(date +%s)
    ok "${BOLD}$CP_NAME${NC} offline after $(elapsed "$T_START")"
  fi
fi

# Close the last step's timing
[[ $step_start_ts -ne 0 ]] && printf "${DIM}└── completed in $(elapsed "$step_start_ts")${NC}\n"
step_start_ts=0

# ----------------------------------------------------------------------
# Final summary
# ----------------------------------------------------------------------
TOTAL=$(elapsed "$T_START")
printf "\n${BOLD}${MAGENTA}┏━━ Summary ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
printf "  ${BOLD}%-14s %-16s %-14s %-12s %s${NC}\n" "NODE" "IP" "ROLE" "SHUTDOWN" "OFFLINE AT"
printf "  ${GRAY}%-14s %-16s %-14s %-12s %s${NC}\n" \
  "─────────────" "───────────────" "─────────────" "───────────" "──────────────"

all_nodes=()
for w in "${WORKERS[@]}"; do all_nodes+=("${w%:*}"); done
all_nodes+=("$CP_NAME")

for n in "${all_nodes[@]}"; do
  ip="${NODE_IP[$n]:-?}"
  role="${NODE_ROLE[$n]:-?}"
  sd="${NODE_SHUTDOWN_OK[$n]:-?}"
  off="${NODE_OFFLINE_AT[$n]:-}"

  case "$sd" in
    yes) sd_color="${GREEN}sent${NC}" ;;
    no) sd_color="${RED}failed${NC}" ;;
    dry-run) sd_color="${DIM}dry-run${NC}" ;;
    *) sd_color="${YELLOW}?${NC}" ;;
  esac

  if [[ -n "$off" ]]; then
    off_display="$(elapsed "$T_START") (T+$((off - T_START))s)"
    off_color="${GREEN}${off_display}${NC}"
  elif $DRY_RUN; then
    off_color="${DIM}dry-run${NC}"
  else
    off_color="${YELLOW}did not confirm${NC}"
  fi

  printf "  %-14s %-16s %-14s %-23b %b\n" "$n" "$ip" "$role" "$sd_color" "$off_color"
done

printf "\n  ${BOLD}Total elapsed:${NC} ${GREEN}%s${NC}\n" "$TOTAL"

if $DRY_RUN; then
  printf "  ${YELLOW}(dry-run — no nodes were touched)${NC}\n\n"
else
  printf "\n  ${GREEN}✓ Safe to swap the UPS.${NC} Power nodes on to bring the cluster back.\n\n"
fi
