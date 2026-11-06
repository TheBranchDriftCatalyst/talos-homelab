#!/usr/bin/env bash
# Bring the cluster back up after a full shutdown — the companion to
# shutdown-cluster.sh.
#
#   ./scripts/startup-cluster.sh            guided bring-up, waits at each tier
#   ./scripts/startup-cluster.sh --verify   skip the waiting, just check health
#   ./scripts/startup-cluster.sh --yes      don't pause for confirmation
#
# THIS SCRIPT CANNOT PRESS POWER BUTTONS. Four of the five nodes are physical
# mini-PCs and the fifth is a VM on the NAS, so bring-up is inherently manual.
# What it does instead is enforce the ORDER and refuse to advance until the tier
# below is genuinely up — which is the part that goes wrong when someone is
# tired and powers everything on at once.
#
# ── WHY THE ORDER IS WHAT IT IS ──────────────────────────────────────────────
#   1. Gateway + switch. Node IPs are DHCP reservations held by the gateway, and
#      kubelet pins validSubnets to 192.168.1.0/24 — on a different subnet it
#      will not register at all. CoreDNS also forwards every external lookup to
#      192.168.1.1.
#   2. The Synology (192.168.1.36). It serves EVERY NFS export, and it hosts the
#      talos00 guest in Virtual Machine Manager — talos00 is a VM, not a
#      physical node, and it is also the API endpoint and the *.talos00 DNS
#      target. NFS mounts are `hard`, so a pod that starts before the NAS is
#      answering does not fail fast: it hangs in D-state forever.
#   3. talos00, then the other control planes, until etcd reports 3 members.
#   4. Workers.
#   5. UNCORDON EVERYTHING. The shutdown cordoned all five, and
#      spec.unschedulable lives in etcd — it survives the reboot. Skip this and
#      the cluster comes up healthy and schedules nothing.
#
# ── NEVER RUN talosctl bootstrap ─────────────────────────────────────────────
# The nodes keep their STATE partition across a clean shutdown, so etcd reforms
# on its own. `bootstrap` initialises a NEW etcd cluster; running it against
# nodes whose peers are alive produces a split brain that is far worse than the
# outage you are trying to end. It is correct ONLY during first provisioning, or
# when every control plane is gone and you are restoring from a snapshot.
set -uo pipefail

TALOSCONFIG="${TALOSCONFIG:-./configs/talosconfig}"
NAS_IP="${NAS_IP:-192.168.1.36}"
GATEWAY_IP="${GATEWAY_IP:-192.168.1.1}"
ENDPOINT_IP="${ENDPOINT_IP:-192.168.1.54}"
TIER_TIMEOUT="${TIER_TIMEOUT:-600}"
PING_TIMEOUT="${PING_TIMEOUT:-2}"
POLL_INTERVAL="${POLL_INTERVAL:-5}"

CPS_DEFAULT="talos00:192.168.1.54 talos01:192.168.1.177 talos03:192.168.1.30"
WORKERS_DEFAULT="talos02-gpu:192.168.1.144 talos06:192.168.1.19"
read -r -a CPS <<< "${CPS_OVERRIDE:-$CPS_DEFAULT}"
read -r -a WORKERS <<< "${WORKERS_OVERRIDE:-$WORKERS_DEFAULT}"
EXPECT_ETCD="${EXPECT_ETCD:-${#CPS[@]}}"

ASSUME_YES=false
VERIFY_ONLY=false
for arg in "$@"; do
  case "$arg" in
    --yes | -y) ASSUME_YES=true ;;
    --verify) VERIFY_ONLY=true ;;
    -h | --help)
      sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown arg: $arg" >&2
      exit 2
      ;;
  esac
done

# Colour only when a human on a terminal will read it. Piping this to a log file
# should not fill it with escape codes.
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  RED=$'\033[0;31m'
  GREEN=$'\033[0;32m'
  YELLOW=$'\033[0;33m'
  BLUE=$'\033[0;34m'
  MAGENTA=$'\033[0;35m'
  GRAY=$'\033[0;90m'
  BOLD=$'\033[1m'
  DIM=$'\033[2m'
  NC=$'\033[0m'
else
  RED=''
  GREEN=''
  YELLOW=''
  BLUE=''
  MAGENTA=''
  GRAY=''
  BOLD=''
  DIM=''
  NC=''
fi

T_START=$(date +%s)
STAGE=0
STAGE_TOTAL=7 # gateway, NAS, CPs, workers, etcd, uncordon, verify
ts() { date '+%H:%M:%S'; }
elapsed() {
  local s=$(($(date +%s) - $1))
  printf '%dm%02ds' $((s / 60)) $((s % 60))
}
info() { printf "${GRAY}[%s]${NC} ${BLUE}i${NC}  %b\n" "$(ts)" "$*"; }
ok() { printf "${GRAY}[%s]${NC} ${GREEN}✓${NC}  %b\n" "$(ts)" "$*"; }
warn() { printf "${GRAY}[%s]${NC} ${YELLOW}!${NC}  %b\n" "$(ts)" "$*"; }
err() { printf "${GRAY}[%s]${NC} ${RED}✗${NC}  %b\n" "$(ts)" "$*" >&2; }

stage() {
  STAGE=$((STAGE + 1))
  printf "\n${BOLD}${MAGENTA}┏━━ [%d/%d] %s ${NC}\n" "$STAGE" "$STAGE_TOTAL" "$*"
}

prompt() {
  $ASSUME_YES && return 0
  printf "\n  ${BOLD}%b${NC}\n  ${DIM}press Enter when done…${NC} " "$*"
  read -r _
}

# Poll until every host answers, or give up. Returns 1 on timeout so the caller
# decides whether that is fatal.
wait_for_hosts() {
  local label="$1" timeout="$2"
  shift 2
  local pending=("$@")
  local deadline=$(($(date +%s) + timeout))
  while [[ ${#pending[@]} -gt 0 && $(date +%s) -lt $deadline ]]; do
    local still=()
    local item
    for item in "${pending[@]}"; do
      if ping -c1 -W "$PING_TIMEOUT" "${item#*:}" > /dev/null 2>&1; then
        ok "${BOLD}${item%:*}${NC} (${item#*:}) is up — $(elapsed "$T_START")"
      else
        still+=("$item")
      fi
    done
    pending=("${still[@]+"${still[@]}"}")
    if [[ ${#pending[@]} -gt 0 ]]; then
      printf "${GRAY}[%s]${NC} ${DIM}waiting on %s…${NC}\r" "$(ts)" "$(
        IFS=,
        echo "${pending[*]%:*}"
      )"
      sleep "$POLL_INTERVAL"
      printf "\033[K"
    fi
  done
  if [[ ${#pending[@]} -gt 0 ]]; then
    err "${label}: still unreachable after ${timeout}s: ${pending[*]%:*}"
    return 1
  fi
  ok "${label}: all up"
  return 0
}

printf "\n${MAGENTA}  catalyst-cluster · cold boot${NC}\n"
printf "${DIM}  Order is load-bearing. Never run 'talosctl bootstrap'.${NC}\n"

if $VERIFY_ONLY; then
  STAGE=4
  info "--verify: skipping the power-on tiers"
else
  # ── 1. Network ────────────────────────────────────────────────────────────
  stage "Gateway and switch"
  prompt "Power on the gateway and switch. Confirm the gateway is at ${GATEWAY_IP} and the five node DHCP reservations are intact."
  if ping -c1 -W "$PING_TIMEOUT" "$GATEWAY_IP" > /dev/null 2>&1; then
    ok "gateway ${GATEWAY_IP} responding"
  else
    err "gateway ${GATEWAY_IP} is not answering — nothing below this will work"
    exit 1
  fi

  # ── 2. NAS ────────────────────────────────────────────────────────────────
  stage "Synology (NFS + the talos00 guest)"
  prompt "Power on the Synology at ${NAS_IP}. It serves every NFS export AND hosts talos00 in VMM."
  wait_for_hosts "NAS" "$TIER_TIMEOUT" "synology:$NAS_IP" || exit 1
  if command -v nc > /dev/null 2>&1; then
    if nc -z -G 3 "$NAS_IP" 2049 > /dev/null 2>&1; then
      ok "NFS (2049) is answering"
    else
      warn "NFS (2049) not answering yet — pods with hard mounts will hang, not fail"
      prompt "Wait for DSM to finish starting, then continue."
    fi
  fi

  # ── 3. Control planes ─────────────────────────────────────────────────────
  stage "Control planes"
  info "talos00 is a VM — if VMM autostart is off, start it from DSM now."
  prompt "Power on the control planes: ${CPS[*]%:*}"
  wait_for_hosts "control planes" "$TIER_TIMEOUT" "${CPS[@]}" || exit 1

  # ── 4. Workers ────────────────────────────────────────────────────────────
  stage "Workers"
  prompt "Power on the workers: ${WORKERS[*]%:*}"
  wait_for_hosts "workers" "$TIER_TIMEOUT" "${WORKERS[@]}" || exit 1
fi

# ── 5. etcd quorum ──────────────────────────────────────────────────────────
stage "Wait for etcd to reform"
info "Expecting ${EXPECT_ETCD} members. They rejoin on their own — do NOT bootstrap."
deadline=$(($(date +%s) + TIER_TIMEOUT))
members=0
while [[ $(date +%s) -lt $deadline ]]; do
  members=$(talosctl --talosconfig "$TALOSCONFIG" --nodes "$ENDPOINT_IP" etcd members 2> /dev/null |
    awk 'NR>1 && NF {n++} END {print n+0}')
  [[ "$members" -ge "$EXPECT_ETCD" ]] && break
  printf "${GRAY}[%s]${NC} ${DIM}etcd members: %s/%s…${NC}\r" "$(ts)" "$members" "$EXPECT_ETCD"
  sleep "$POLL_INTERVAL"
  printf "\033[K"
done
if [[ "$members" -ge "$EXPECT_ETCD" ]]; then
  ok "etcd has ${members}/${EXPECT_ETCD} members"
else
  err "etcd only reached ${members}/${EXPECT_ETCD} after ${TIER_TIMEOUT}s"
  err "DO NOT run 'talosctl bootstrap'. A lost member is repaired by removing and"
  err "re-adding it; bootstrap creates a second cluster. See"
  err "docs/03-operations/node-shutdown-procedure.md"
  exit 1
fi

# ── 6. Uncordon + verify ────────────────────────────────────────────────────
stage "Uncordon every node"
if ! kubectl get nodes > /dev/null 2>&1; then
  err "kubectl cannot reach the API server yet"
  exit 1
fi
ALL_NODES=()
while IFS= read -r n; do [[ -n "$n" ]] && ALL_NODES+=("$n"); done \
  < <(kubectl get nodes --no-headers -o custom-columns=NAME:.metadata.name 2> /dev/null)
for n in "${ALL_NODES[@]+"${ALL_NODES[@]}"}"; do
  if [[ "$(kubectl get node "$n" -o jsonpath='{.spec.unschedulable}' 2> /dev/null)" == "true" ]]; then
    if kubectl uncordon "$n" > /dev/null 2>&1; then
      ok "uncordoned ${BOLD}$n${NC}"
    else
      err "failed to uncordon $n — nothing will schedule there"
    fi
  else
    info "$n already schedulable"
  fi
done

stage "Verify"
printf "\n  ${BOLD}%-16s %s${NC}\n" "CHECK" "RESULT"
printf "  ${GRAY}%-16s %s${NC}\n" "───────────────" "──────────────────────────────"

nodes_ready=$(kubectl get nodes --no-headers 2> /dev/null | awk '$2=="Ready"' | wc -l | tr -d ' ')
nodes_total=$(kubectl get nodes --no-headers 2> /dev/null | wc -l | tr -d ' ')
if [[ "$nodes_ready" == "$nodes_total" && "$nodes_total" -gt 0 ]]; then
  printf "  %-16s ${GREEN}%s/%s Ready${NC}\n" "nodes" "$nodes_ready" "$nodes_total"
else
  printf "  %-16s ${YELLOW}%s/%s Ready${NC}\n" "nodes" "$nodes_ready" "$nodes_total"
fi

cordoned=$(kubectl get nodes -o jsonpath='{range .items[*]}{.spec.unschedulable}{"\n"}{end}' 2> /dev/null | grep -c true)
if [[ "$cordoned" == "0" ]]; then
  printf "  %-16s ${GREEN}none${NC}\n" "cordoned"
else
  printf "  %-16s ${RED}%s still cordoned${NC}\n" "cordoned" "$cordoned"
fi

printf "  %-16s ${GREEN}%s/%s${NC}\n" "etcd members" "$members" "$EXPECT_ETCD"

notready=$(kubectl get pods -A --no-headers 2> /dev/null | grep -vcE "Running|Completed")
if [[ "$notready" == "0" ]]; then
  printf "  %-16s ${GREEN}all Running/Completed${NC}\n" "pods"
else
  printf "  %-16s ${YELLOW}%s not Running (NFS settling is normal)${NC}\n" "pods" "$notready"
fi

if command -v flux > /dev/null 2>&1; then
  fluxbad=$(flux get kustomizations -A 2> /dev/null | awk 'NR>1 && $5=="False"' | wc -l | tr -d ' ')
  if [[ "$fluxbad" == "0" ]]; then
    printf "  %-16s ${GREEN}all Ready${NC}\n" "flux"
  else
    printf "  %-16s ${YELLOW}%s not ready (give it an interval)${NC}\n" "flux" "$fluxbad"
  fi
fi

printf "\n  ${BOLD}Total elapsed:${NC} ${GREEN}%s${NC}\n" "$(elapsed "$T_START")"
printf "\n  ${DIM}Expect transient ContainerCreating while NFS settles. Pi-hole returning is\n"
printf "  what restores LAN DNS. If something looks wrong, read the LAST log line of the\n"
printf "  failing pod, not the first.${NC}\n\n"
