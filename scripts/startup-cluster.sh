#!/usr/bin/env bash
# Bring the cluster back up after a full shutdown — the companion to
# shutdown-cluster.sh.
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

usage() {
  cat << 'EOF'
Bring the cluster back up after a full shutdown — the companion to
shutdown-cluster.sh. It cannot press power buttons; it enforces the bring-up
ORDER (gateway -> NAS -> control planes -> workers), refuses to advance until
each tier answers, waits for etcd to reform, uncordons every node, and prints
a verification table. Never runs 'talosctl bootstrap'.

  ./scripts/startup-cluster.sh            guided bring-up, waits at each tier
  ./scripts/startup-cluster.sh --verify   skip the power-on tiers; checks etcd,
                                          uncordons anything still cordoned,
                                          prints the verification table
  ./scripts/startup-cluster.sh --yes      don't pause for confirmation

Environment knobs (defaults in parentheses):
  TALOSCONFIG      (<repo>/configs/talosconfig)
  GATEWAY_IP       (192.168.1.1)      NAS_IP        (192.168.1.36)
  ENDPOINT_IP      (192.168.1.54)     TIER_TIMEOUT  (900s, per tier)
  PING_TIMEOUT     (2s)               POLL_INTERVAL (5s)
  CPS_OVERRIDE     ("name:ip name:ip …" control planes)
  WORKERS_OVERRIDE ("name:ip name:ip …" workers)
  EXPECT_ETCD      (number of control planes)
EOF
}

# Anchor the default talosconfig to the repo root, not the caller's cwd —
# running this from anywhere but the root used to send the etcd wait into a
# 10-minute spin against a talosconfig that was never found.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TALOSCONFIG="${TALOSCONFIG:-$REPO_ROOT/configs/talosconfig}"
NAS_IP="${NAS_IP:-192.168.1.36}"
GATEWAY_IP="${GATEWAY_IP:-192.168.1.1}"
ENDPOINT_IP="${ENDPOINT_IP:-192.168.1.54}"
TIER_TIMEOUT="${TIER_TIMEOUT:-900}"
PING_TIMEOUT="${PING_TIMEOUT:-2}"
POLL_INTERVAL="${POLL_INTERVAL:-5}"
TALOS_PORT=50000

# macOS ping takes -W in MILLISECONDS (so "-W 2" is a 2ms window that only
# appears to work because late replies still count toward the exit code);
# Linux takes seconds. Use -t (overall deadline, seconds) on Darwin instead —
# same helper shape as shutdown-cluster.sh. On Linux -t would be TTL, hence
# the branch.
UNAME="$(uname -s)"
ping_once() {
  if [[ "$UNAME" == "Darwin" ]]; then
    ping -c1 -t "$PING_TIMEOUT" "$1" > /dev/null 2>&1
  else
    ping -c1 -W "$PING_TIMEOUT" "$1" > /dev/null 2>&1
  fi
}

CPS_DEFAULT="talos00:192.168.1.54 talos01:192.168.1.177 talos03:192.168.1.30"
WORKERS_DEFAULT="talos02-gpu:192.168.1.144 talos06:192.168.1.19"
read -r -a CPS <<< "${CPS_OVERRIDE:-$CPS_DEFAULT}"
read -r -a WORKERS <<< "${WORKERS_OVERRIDE:-$WORKERS_DEFAULT}"
EXPECT_ETCD="${EXPECT_ETCD:-${#CPS[@]}}"
EXPECT_NODES=$((${#CPS[@]} + ${#WORKERS[@]}))

ASSUME_YES=false
VERIFY_ONLY=false
for arg in "$@"; do
  case "$arg" in
    --yes | -y) ASSUME_YES=true ;;
    --verify) VERIFY_ONLY=true ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown arg: $arg" >&2
      exit 2
      ;;
  esac
done

# Colour only when a human on a terminal will read it. Piping this to a log file
# should not fill it with escape codes — and that goes for the \r progress
# spinner too, hence IS_TTY below.
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
if [[ -t 1 ]]; then IS_TTY=true; else IS_TTY=false; fi

# Don't leave the cursor stranded mid-progress-line on Ctrl-C.
trap 'printf "\n"; exit 130' INT TERM

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

# Transient one-line progress on a terminal; honest timestamped lines in a log.
# PROGRESS_N rate-limits the log flavour so a 15-minute wait is ~30 lines.
PROGRESS_N=0
progress() {
  if $IS_TTY; then
    printf "${GRAY}[%s]${NC} ${DIM}%b${NC}\r" "$(ts)" "$*"
  elif ((PROGRESS_N % 6 == 0)); then
    printf "[%s] …  %b\n" "$(ts)" "$*"
  fi
  PROGRESS_N=$((PROGRESS_N + 1))
}
progress_clear() {
  $IS_TTY && printf "\033[K"
  PROGRESS_N=0
}

prompt() {
  $ASSUME_YES && return 0
  printf "\n  ${BOLD}%b${NC}\n  ${DIM}press Enter when done…${NC} " "$*"
  if ! read -r _; then
    # EOF: stdin is closed/exhausted. Blowing through every pause silently
    # would defeat the whole point of this script.
    printf "\n"
    err "stdin closed — cannot pause for the operator. Use --yes for non-interactive runs."
    exit 2
  fi
}

# "Keep waiting?" after a tier timeout. Returns 0 to extend the deadline.
# Non-interactive runs get no say and the timeout stands.
ask_retry() {
  $ASSUME_YES && return 1
  [[ -t 0 ]] || return 1
  printf "  ${BOLD}%b${NC}\n  ${DIM}press Enter to keep waiting another %ss, Ctrl-C to abort…${NC} " "$1" "$TIER_TIMEOUT"
  read -r _ || return 1
}

tcp_up() {                                   # host port
  command -v nc > /dev/null 2>&1 || return 0 # can't check -> don't block on it
  nc -z -w 3 "$1" "$2" > /dev/null 2>&1      # -w, not -G: -G is macOS-only
}

# Poll until every host answers ping AND (when given) a TCP port, or give up.
# Ping alone only proves the network stack: a Talos node answers ping well
# before apid is up, so node tiers also probe the Talos API port.
# Returns 1 on timeout so the caller decides whether that is fatal.
wait_for_hosts() {
  local label="$1" timeout="$2" port="$3"
  shift 3
  local pending=("$@")
  local deadline=$(($(date +%s) + timeout))
  local via=""
  [[ -n "$port" ]] && via=" (talos api :${port})"
  while [[ ${#pending[@]} -gt 0 ]]; do
    local still=()
    local item
    for item in "${pending[@]+"${pending[@]}"}"; do
      if ping_once "${item#*:}" &&
        { [[ -z "$port" ]] || tcp_up "${item#*:}" "$port"; }; then
        progress_clear
        ok "${BOLD}${item%:*}${NC} (${item#*:}) is up${via} — $(elapsed "$T_START")"
      else
        still+=("$item")
      fi
    done
    pending=("${still[@]+"${still[@]}"}")
    [[ ${#pending[@]} -eq 0 ]] && break
    if [[ $(date +%s) -ge $deadline ]]; then
      progress_clear
      err "${label}: still unreachable after ${timeout}s: ${pending[*]%:*}"
      if ask_retry "Hosts can be slow to appear after a cold boot (BIOS, fsck, DSM)."; then
        deadline=$(($(date +%s) + timeout))
        continue
      fi
      err "safe to re-run this script from the top — tiers already up pass straight through"
      return 1
    fi
    progress "waiting on $(
      IFS=,
      echo "${pending[*]%:*}"
    )…"
    sleep "$POLL_INTERVAL"
  done
  progress_clear
  ok "${label}: all up"
  return 0
}

printf "\n${MAGENTA}  catalyst-cluster · cold boot${NC}\n"
printf "%s\n" "${DIM}  Order is load-bearing. Never run 'talosctl bootstrap'.${NC}"

# ── Preflight — fail here, not 10 minutes in ─────────────────────────────────
preflight_bad=false
for bin in talosctl kubectl ping; do
  if ! command -v "$bin" > /dev/null 2>&1; then
    err "preflight: '$bin' not found in PATH"
    preflight_bad=true
  fi
done
# A readability test alone is not enough: talosctl auto-creates an EMPTY stub
# at a missing path, which reads fine and then spins the etcd wait at 0/N
# forever. Check existence first (so we don't plant that stub ourselves), then
# make talosctl prove the config actually resolves a context.
if [[ ! -f "$TALOSCONFIG" ]]; then
  err "preflight: no talosconfig at $TALOSCONFIG"
  err "set TALOSCONFIG to the real one — without it the etcd wait can never succeed"
  preflight_bad=true
elif ! talos_info=$(talosctl --talosconfig "$TALOSCONFIG" config info 2>&1); then
  err "preflight: talosconfig at $TALOSCONFIG is missing or unusable:"
  err "  ${talos_info}"
  err "set TALOSCONFIG to the real one — without it the etcd wait can never succeed"
  preflight_bad=true
elif grep -qi 'expire[ds].*ago\|certificate.*expired' <<< "$talos_info"; then
  err "preflight: the talosconfig client certificate has EXPIRED — talosctl will be"
  err "rejected by every node. Regenerate it (talosctl config new) before continuing."
  preflight_bad=true
fi
$preflight_bad && exit 2
command -v nc > /dev/null 2>&1 ||
  warn "preflight: 'nc' not found — port checks (NFS, Talos API) will be skipped; ping-only gating"
if [[ ${#CPS[@]} -eq 0 || ${#WORKERS[@]} -eq 0 ]]; then
  err "preflight: empty node list (check CPS_OVERRIDE / WORKERS_OVERRIDE)"
  exit 2
fi

if $VERIFY_ONLY; then
  STAGE=4
  info "--verify: skipping the power-on tiers (still waits on etcd, uncordons if needed)"
else
  # ── 1. Network ────────────────────────────────────────────────────────────
  stage "Gateway and switch"
  prompt "Power on the gateway and switch. Confirm the gateway is at ${GATEWAY_IP} and the five node DHCP reservations are intact."
  if ! wait_for_hosts "gateway" "$TIER_TIMEOUT" "" "gateway:$GATEWAY_IP"; then
    err "gateway ${GATEWAY_IP} is not answering — nothing below this will work."
    err "Check its power/WAN lights and this machine's Wi-Fi/ethernet before anything else."
    exit 1
  fi

  # ── 2. NAS ────────────────────────────────────────────────────────────────
  stage "Synology (NFS + the talos00 guest)"
  prompt "Power on the Synology at ${NAS_IP}. It serves every NFS export AND hosts talos00 in VMM."
  wait_for_hosts "NAS" "$TIER_TIMEOUT" "" "synology:$NAS_IP" || exit 1
  if command -v nc > /dev/null 2>&1; then
    # DSM answers ping minutes before it serves NFS. Poll the port — a pod that
    # mounts early doesn't fail, it hangs in D-state.
    nfs_deadline=$(($(date +%s) + TIER_TIMEOUT))
    until tcp_up "$NAS_IP" 2049; do
      if [[ $(date +%s) -ge $nfs_deadline ]]; then
        progress_clear
        warn "NFS (2049) still not answering after ${TIER_TIMEOUT}s — pods with hard mounts will hang, not fail"
        prompt "Check DSM (http://${NAS_IP}:5000) shows the volume mounted and NFS enabled, then continue."
        break
      fi
      progress "waiting for NFS (2049) on ${NAS_IP}… DSM takes a few minutes"
      sleep "$POLL_INTERVAL"
    done
    progress_clear
    tcp_up "$NAS_IP" 2049 && ok "NFS (2049) is answering"
  else
    warn "cannot probe NFS without 'nc' — wait until DSM is fully up (volume mounted) before continuing"
    prompt "Confirm DSM at http://${NAS_IP}:5000 shows the volume healthy, then continue."
  fi

  # ── 3. Control planes ─────────────────────────────────────────────────────
  stage "Control planes"
  info "talos00 is a VM — if VMM autostart is off, start it from DSM (VMM) now."
  prompt "Power on the control planes: ${CPS[*]%:*}"
  wait_for_hosts "control planes" "$TIER_TIMEOUT" "$TALOS_PORT" "${CPS[@]+"${CPS[@]}"}" || exit 1

  # ── 4. Workers ────────────────────────────────────────────────────────────
  stage "Workers"
  prompt "Power on the workers: ${WORKERS[*]%:*}"
  wait_for_hosts "workers" "$TIER_TIMEOUT" "$TALOS_PORT" "${WORKERS[@]+"${WORKERS[@]}"}" || exit 1
fi

# ── 5. etcd quorum ──────────────────────────────────────────────────────────
stage "Wait for etcd to reform"
info "Expecting ${EXPECT_ETCD} members. They rejoin on their own — do NOT bootstrap."
deadline=$(($(date +%s) + TIER_TIMEOUT))
members=0
while :; do
  members=$(talosctl --talosconfig "$TALOSCONFIG" --nodes "$ENDPOINT_IP" etcd members 2> /dev/null |
    awk 'NR>1 && NF>=6 {n++} END {print n+0}')
  [[ "$members" -ge "$EXPECT_ETCD" ]] && break
  if [[ $(date +%s) -ge $deadline ]]; then
    progress_clear
    err "etcd only reached ${members}/${EXPECT_ETCD} after ${TIER_TIMEOUT}s"
    if ask_retry "etcd can lag the nodes by a few minutes on a cold boot."; then
      deadline=$(($(date +%s) + TIER_TIMEOUT))
      continue
    fi
    err ""
    err "${BOLD}DO NOT run 'talosctl bootstrap'.${NC} The members are still registered;"
    err "a lost one is repaired by removing and re-adding it — bootstrap creates a"
    err "second cluster. Diagnose first:"
    err "  talosctl --talosconfig $TALOSCONFIG -n ${CPS[*]#*:} service etcd"
    err "  talosctl --talosconfig $TALOSCONFIG -n $ENDPOINT_IP etcd status"
    err "  talos00 console: DSM -> Virtual Machine Manager -> talos00 -> Connect"
    err "Then: docs/03-operations/node-shutdown-procedure.md"
    err "This script is safe to re-run from the top at any time."
    exit 1
  fi
  progress "etcd members: ${members}/${EXPECT_ETCD}…"
  sleep "$POLL_INTERVAL"
done
progress_clear
ok "etcd has ${members}/${EXPECT_ETCD} members"

# ── 6. Uncordon + verify ────────────────────────────────────────────────────
stage "Uncordon every node"
# The member list can be answerable before the API server is — give kubectl the
# same patience instead of dying on the first try.
kube_deadline=$(($(date +%s) + TIER_TIMEOUT))
until kubectl get nodes > /dev/null 2>&1; do
  if [[ $(date +%s) -ge $kube_deadline ]]; then
    progress_clear
    err "kubectl cannot reach the API server after ${TIER_TIMEOUT}s"
    err "  - etcd is up (above), so this is kube-apiserver or the path to ${ENDPOINT_IP}:6443"
    err "  - check: talosctl --talosconfig $TALOSCONFIG -n $ENDPOINT_IP service kubelet"
    err "  - check: kubectl config current-context   (is it pointing at this cluster?)"
    err "Safe to re-run with --verify once it answers."
    exit 1
  fi
  progress "waiting for the Kubernetes API on ${ENDPOINT_IP}:6443…"
  sleep "$POLL_INTERVAL"
done
progress_clear
ok "Kubernetes API is answering"

ALL_NODES=()
while IFS= read -r n; do [[ -n "$n" ]] && ALL_NODES+=("$n"); done \
  < <(kubectl get nodes --no-headers -o custom-columns=NAME:.metadata.name 2> /dev/null)
if [[ ${#ALL_NODES[@]} -eq 0 ]]; then
  warn "API answered but listed no nodes — kubelets may still be registering; re-run --verify shortly"
fi
UNCORDON_FAILED=0
for n in "${ALL_NODES[@]+"${ALL_NODES[@]}"}"; do
  if [[ "$(kubectl get node "$n" -o jsonpath='{.spec.unschedulable}' 2> /dev/null)" == "true" ]]; then
    if kubectl uncordon "$n" > /dev/null 2>&1; then
      ok "uncordoned ${BOLD}$n${NC}"
    else
      err "failed to uncordon $n — nothing will schedule there until you run: kubectl uncordon $n"
      UNCORDON_FAILED=$((UNCORDON_FAILED + 1))
    fi
  else
    info "$n already schedulable"
  fi
done

stage "Verify"
printf "\n  ${BOLD}%-16s %s${NC}\n" "CHECK" "RESULT"
printf "  ${GRAY}%-16s %s${NC}\n" "───────────────" "──────────────────────────────"

# One snapshot per subsystem; an API hiccup must show as UNKNOWN, never as a
# green row counting an empty string as "zero problems".
YELLOWS=0

nodes_out=$(kubectl get nodes --no-headers 2> /dev/null)
if [[ -z "$nodes_out" ]]; then
  printf "  %-16s ${RED}unknown — API stopped answering${NC}\n" "nodes"
  printf "  %-16s ${RED}unknown — API stopped answering${NC}\n" "cordoned"
  YELLOWS=$((YELLOWS + 1))
else
  nodes_ready=$(printf '%s\n' "$nodes_out" | awk '$2 ~ /^Ready(,|$)/' | wc -l | tr -d ' ')
  nodes_total=$(printf '%s\n' "$nodes_out" | wc -l | tr -d ' ')
  if [[ "$nodes_ready" == "$nodes_total" && "$nodes_total" == "$EXPECT_NODES" ]]; then
    printf "  %-16s ${GREEN}%s/%s Ready${NC}\n" "nodes" "$nodes_ready" "$EXPECT_NODES"
  else
    printf "  %-16s ${YELLOW}%s Ready of %s registered (expected %s)${NC}\n" \
      "nodes" "$nodes_ready" "$nodes_total" "$EXPECT_NODES"
    YELLOWS=$((YELLOWS + 1))
  fi

  cordoned=$(printf '%s\n' "$nodes_out" | grep -c 'SchedulingDisabled' || true)
  if [[ "$cordoned" == "0" && "$UNCORDON_FAILED" == "0" ]]; then
    printf "  %-16s ${GREEN}none${NC}\n" "cordoned"
  else
    printf "  %-16s ${RED}%s still cordoned — kubectl uncordon <node>${NC}\n" "cordoned" "$cordoned"
    YELLOWS=$((YELLOWS + 1))
  fi
fi

# etcd: membership is PERSISTENT REGISTRATION, not health. After a cold boot all
# members stay registered even if one node's etcd is dead, so a row count passes
# while the cluster is degraded. Ask every control plane directly.
etcd_bad=()
for _c in "${CPS[@]}"; do
  _ip="${_c#*:}"
  talosctl --talosconfig "$TALOSCONFIG" --nodes "$_ip" etcd status > /dev/null 2>&1 ||
    etcd_bad+=("${_c%:*}")
done
if [[ ${#etcd_bad[@]} -eq 0 ]]; then
  printf "  %-16s ${GREEN}%s/%s, every CP answers etcd status${NC}\n" "etcd" "$members" "$EXPECT_ETCD"
else
  printf "  %-16s ${RED}%s/%s registered BUT etcd status FAILED on: %s${NC}\n" \
    "etcd" "$members" "$EXPECT_ETCD" "${etcd_bad[*]}"
  YELLOWS=$((YELLOWS + 1))
fi

# CROSS-NODE DATAPATH. This row exists because on 2026-11-06 every other row here
# was green while talos01's Cilium overlay was completely isolated: the node was
# Ready, etcd 3/3, cordons clear, and pods on it could reach nothing.
# cilium-health said "Node: 1/1, Endpoints: 0/1" -- host routing fine, pod-to-pod
# dead -- and the only visible symptoms blamed Flux, authentik, mimir and
# admission webhooks. Four wrong layers. It took manual bisection to find.
#
# THE PROBE MUST BE PINNED PER NODE. An unpinned `kubectl run` landed on the same
# node as CoreDNS, resolved fine, and produced a FALSE PASS that was read as "DNS
# is healthy" while the cluster was broken. A node-local probe cannot see this
# class of fault by construction.
if true; then
  probe_nodes=$(kubectl get nodes --no-headers 2> /dev/null | awk '{print $1}')
  if [[ -z "$probe_nodes" ]]; then
    printf "  %-16s ${YELLOW}unknown — API not listing nodes${NC}\n" "cross-node"
    YELLOWS=$((YELLOWS + 1))
  else
    dns_bad=()
    while read -r _n; do
      [[ -z "$_n" ]] && continue
      kubectl run "coldboot-dns-$_n-$$" --rm -i --restart=Never --image=busybox:1.36 \
        --timeout=75s \
        --overrides="{\"spec\":{\"nodeName\":\"$_n\",\"tolerations\":[{\"operator\":\"Exists\"}]}}" \
        -- nslookup kubernetes.default.svc.cluster.local > /dev/null 2>&1 ||
        dns_bad+=("$_n")
    done <<< "$probe_nodes"
    if [[ ${#dns_bad[@]} -eq 0 ]]; then
      printf "  %-16s ${GREEN}all nodes resolve cluster DNS from their own pods${NC}\n" "cross-node"
    else
      printf "  %-16s ${RED}pods on these nodes CANNOT resolve DNS: %s${NC}\n" "cross-node" "${dns_bad[*]}"
      printf "  %-16s ${DIM}suspect overlay isolation — cilium-health status, Endpoints column${NC}\n" ""
      YELLOWS=$((YELLOWS + 1))
    fi
  fi
fi

# Workloads that can never produce a pod. A Deployment at 0/N with FailedCreate
# is INVISIBLE to every other row here and to Flux, which reports Ready=True
# because the manifest applied fine. themepark hit this on 2026-11-06: the live
# object still named serviceAccountName themepark-nav, deleted with the Python nav
# sidecar, and its managedFields was empty so Flux had nothing to prune against.
# The old pods survived on their old spec; the cold boot recreated them and every
# themed app lost its CSS. Latent drift that only a restart detonates.
if true; then
  zero_reps=$(kubectl get deploy -A --no-headers 2> /dev/null |
    awk '{split($3,a,"/"); if (a[1]=="0" && a[2]+0 > 0) print $1"/"$2}')
  if [[ -z "$zero_reps" ]]; then
    printf "  %-16s ${GREEN}none${NC}\n" "0-replica"
  else
    printf "  %-16s ${RED}%s${NC}\n" "0-replica" "$(printf '%s' "$zero_reps" | tr '\n' ' ')"
    printf "  %-16s ${DIM}kubectl describe rs -n <ns> <name> | grep FailedCreate${NC}\n" ""
    YELLOWS=$((YELLOWS + 1))
  fi
fi

pods_out=$(kubectl get pods -A --no-headers 2> /dev/null)
if [[ -z "$pods_out" ]]; then
  printf "  %-16s ${RED}unknown — API stopped answering${NC}\n" "pods"
  YELLOWS=$((YELLOWS + 1))
else
  # Status column ($4), not whole-line grep: a CrashLoopBackOff pod must never
  # hide behind the word "Running" elsewhere on its line.
  notready=$(printf '%s\n' "$pods_out" | awk '$4!="Running" && $4!="Completed" && $4!="Succeeded"' | wc -l | tr -d ' ')
  stuck=$(printf '%s\n' "$pods_out" | awk '$4=="Running" {split($3,a,"/"); if (a[1]<a[2]) n++} END {print n+0}')
  if [[ "$notready" == "0" && "$stuck" == "0" ]]; then
    printf "  %-16s ${GREEN}all Running and Ready${NC}\n" "pods"
  else
    printf "  %-16s ${YELLOW}%s not Running, %s Running-but-not-Ready${NC}\n" "pods" "$notready" "$stuck"
    YELLOWS=$((YELLOWS + 1))
  fi
fi

# Flux via kubectl, not the flux CLI: `flux get` leaves the REVISION column
# empty before the first fetch and the field shift hides every False row.
flux_out=$(kubectl get kustomizations -A --no-headers 2> /dev/null)
flux_rc=$?
if [[ $flux_rc -ne 0 ]]; then
  printf "  %-16s ${YELLOW}unknown (CRD or API not answering yet)${NC}\n" "flux"
  YELLOWS=$((YELLOWS + 1))
elif [[ -z "$flux_out" ]]; then
  printf "  %-16s ${YELLOW}no Kustomizations found${NC}\n" "flux"
  YELLOWS=$((YELLOWS + 1))
else
  fluxbad=$(printf '%s\n' "$flux_out" | awk '$4!="True"' | wc -l | tr -d ' ')
  if [[ "$fluxbad" == "0" ]]; then
    printf "  %-16s ${GREEN}all Ready${NC}\n" "flux"
  else
    printf "  %-16s ${YELLOW}%s not ready (give it an interval)${NC}\n" "flux" "$fluxbad"
    YELLOWS=$((YELLOWS + 1))
  fi
fi

printf "\n  ${BOLD}Total elapsed:${NC} ${GREEN}%s${NC}\n" "$(elapsed "$T_START")"

if [[ "$YELLOWS" == "0" ]]; then
  printf "\n  ${GREEN}${BOLD}Everything is green. The cluster is back.${NC}\n"
  printf "%s\n\n" "${DIM}  Pi-hole returning is what restores LAN DNS for the rest of the house.${NC}"
else
  printf "\n  ${BOLD}Something above is not green — in the first ~10 minutes that is usually fine.${NC}\n"
  printf "%s\n" "${DIM}  NFS-backed pods settle slowly (hard mounts); Flux reconciles on its interval.${NC}"
  printf "\n  ${BOLD}What to do about each:${NC}\n"
  printf "    pods          kubectl get pods -A | grep -vE 'Running|Completed'\n"
  printf "                  read the LAST log line of a failing pod, not the first\n"
  printf "    nodes         kubectl get nodes; talosctl --talosconfig %s -n <ip> dmesg\n" "$TALOSCONFIG"
  printf "    cordoned      kubectl uncordon <node>   (nothing schedules there until you do)\n"
  printf "    flux          flux get kustomizations -A | grep -v True; task infra:flux-reconcile\n"
  printf "\n  ${BOLD}Re-check without re-prompting the tiers:${NC}\n"
  printf "    ./scripts/startup-cluster.sh --verify\n"
  printf "\n%s\n\n" "${DIM}  And still: never 'talosctl bootstrap'.${NC}"
fi
