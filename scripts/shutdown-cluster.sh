#!/usr/bin/env bash
#
# Catalyst Cluster Graceful Shutdown
#
# Shuts down all 5 Talos nodes in the correct order:
#   1. etcd snapshot to THIS machine (off-cluster insurance)
#   2. Cordon every node (stops new scheduling)
#   3. Shut down all workers gracefully, in parallel; confirm offline by ping
#   4. Drain ALL control planes while etcd still has quorum
#   5. Shut down control planes one at a time, API endpoint last
#   6. Final verification sweep — the script refuses to say "safe" unless
#      every node is CONFIRMED unreachable
#
# Usage:
#   ./scripts/shutdown-cluster.sh             # interactive
#   ./scripts/shutdown-cluster.sh --yes       # skip confirmation
#   ./scripts/shutdown-cluster.sh --dry-run   # show plan only, zero side effects
#
# Env knobs:
#   TALOSCONFIG            path to talosconfig   (default ./configs/talosconfig)
#   CONTROL_PLANE_IP       API endpoint IP       (default 192.168.1.54)
#   WORKER_WAIT_TIMEOUT    secs to wait for workers to die   (default 180)
#   CP_WAIT_TIMEOUT        secs to wait per control plane    (default 180)
#   FINAL_RECHECK_TIMEOUT  secs for the final verification   (default 60)
#   DRAIN_TIMEOUT          kubectl drain timeout             (default 120s)
#   SNAPSHOT_DIR           where the etcd snapshot lands     (default $HOME)
#   SKIP_SNAPSHOT=1        proceed even if the snapshot fails
#   ALLOW_BROKEN_WEBHOOKS=1  proceed past the admission-webhook gate
#   ALLOW_CONTEXT_MISMATCH=1 proceed if kubectl points at a different cluster
#
# shellcheck disable=SC2059  # colour vars in printf format strings are deliberate

set -euo pipefail

# ----------------------------------------------------------------------
# Bash version guard — associative arrays need bash 4; empty-array
# expansion under `set -u` needs 4.4. macOS /bin/bash is 3.2 and would
# die mid-script in confusing ways; refuse up front instead.
# ----------------------------------------------------------------------
if [[ -z "${BASH_VERSINFO:-}" ]] ||
  ((BASH_VERSINFO[0] < 4)) ||
  ((BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] < 4)); then
  echo "FATAL: this script needs bash >= 4.4; you are running ${BASH_VERSION:-not-bash}." >&2
  echo "macOS /bin/bash is 3.2 — run with a newer bash (brew/nix) or fix PATH." >&2
  exit 1
fi

TALOSCONFIG="${TALOSCONFIG:-./configs/talosconfig}"
CONTROL_PLANE_IP="${CONTROL_PLANE_IP:-192.168.1.54}"
WORKER_WAIT_TIMEOUT="${WORKER_WAIT_TIMEOUT:-180}"
CP_WAIT_TIMEOUT="${CP_WAIT_TIMEOUT:-180}"
FINAL_RECHECK_TIMEOUT="${FINAL_RECHECK_TIMEOUT:-60}"
PING_TIMEOUT="${PING_TIMEOUT:-2}" # seconds, on every platform (see node_is_up)

# Ground truth for THIS cluster, from configs/talconfig.yaml. Used as the
# fallback when kubectl is unavailable AND as a cross-check against kubectl
# discovery: a node kubectl forgot about still gets shut down, not skipped.
EXPECTED_WORKERS=("talos02-gpu:192.168.1.144" "talos06:192.168.1.19")
EXPECTED_CPS=("talos01:192.168.1.177" "talos03:192.168.1.30" "talos00:192.168.1.54")

ASSUME_YES=false
DRY_RUN=false
for arg in "$@"; do
  case "$arg" in
    --yes | -y) ASSUME_YES=true ;;
    --dry-run | -n) DRY_RUN=true ;;
    -h | --help)
      sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown arg: $arg" >&2
      exit 2
      ;;
  esac
done

# ----------------------------------------------------------------------
# Output: colours only on a TTY and only without NO_COLOR, so piping to a
# log file gives clean text. The \r progress line is TTY-only too.
# ----------------------------------------------------------------------
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  IS_TTY=true
  RED='\033[0;31m' GREEN='\033[0;32m' YELLOW='\033[1;33m' BLUE='\033[0;34m'
  CYAN='\033[0;36m' MAGENTA='\033[0;35m' GRAY='\033[0;90m'
  BOLD='\033[1m' DIM='\033[2m' NC='\033[0m'
else
  IS_TTY=false
  RED='' GREEN='' YELLOW='' BLUE='' CYAN='' MAGENTA='' GRAY='' BOLD='' DIM='' NC=''
fi

ts() { date '+%H:%M:%S'; }
elapsed() {
  local s=$(($(date +%s) - ${1:-0}))
  printf '%dm%02ds' $((s / 60)) $((s % 60))
}
info() { printf "${GRAY}[%s]${NC} ${BLUE}i${NC}  %b\n" "$(ts)" "$*"; }
ok() { printf "${GRAY}[%s]${NC} ${GREEN}✓${NC}  %b\n" "$(ts)" "$*"; }
warn() { printf "${GRAY}[%s]${NC} ${YELLOW}⚠${NC}  %b\n" "$(ts)" "$*"; }
err() { printf "${GRAY}[%s]${NC} ${RED}✗${NC}  %b\n" "$(ts)" "$*" >&2; }

# refuse: hard abort on a real run; on --dry-run, show that the real run
# would abort here but keep going so the preview stays complete.
refuse() {
  if $DRY_RUN; then
    warn "${BOLD}REAL RUN WOULD REFUSE HERE:${NC} $*"
  else
    err "$*"
    exit 1
  fi
}

STAGE_TOTAL=9
stage_no=0
stage_start_ts=0
close_stage() {
  [[ $stage_start_ts -ne 0 ]] &&
    printf "${DIM}└── stage done in %s${NC}\n" "$(elapsed "$stage_start_ts")"
  stage_start_ts=0
}
stage() {
  close_stage
  stage_no=$((stage_no + 1))
  stage_start_ts=$(date +%s)
  printf "\n${BOLD}${CYAN}┏━━ [%d/%d] %b ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n" \
    "$stage_no" "$STAGE_TOTAL" "$*"
}
substage() { printf "\n${CYAN}┠── %b${NC}\n" "$*"; }

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

# Per-node tracking
declare -A NODE_OFFLINE_AT=()  # name -> epoch when ping-confirmed offline
declare -A NODE_SHUTDOWN_OK=() # name -> yes | no | dry-run
declare -A NODE_IP=()          # name -> ip
declare -A NODE_ROLE=()        # name -> role

T_START=$(date +%s)
LOG_DIR=$(mktemp -d "${TMPDIR:-/tmp}/cluster-shutdown.XXXXXX")
REACHED_SUMMARY=false
CONFIRMED_RUN=false

# shellcheck disable=SC2329  # invoked via the EXIT trap below
on_exit() {
  $IS_TTY && { tput cnorm 2> /dev/null || true; }
  if ! $REACHED_SUMMARY && $CONFIRMED_RUN && ! $DRY_RUN; then
    printf "\n" >&2
    err "${BOLD}SCRIPT EXITED EARLY — the cluster may be PARTIALLY shut down.${NC}"
    err "Nothing is lost: re-running this script is safe (already-down nodes just"
    err "confirm offline). Logs from this run: ${BOLD}${LOG_DIR}${NC}"
  fi
}
trap on_exit EXIT

# ping with SECONDS semantics on both platforms. On macOS -W is
# MILLISECONDS (the old '-W 2' waited 2ms and could declare a live node
# offline); -t is the overall timeout in seconds. On Linux -W is seconds.
UNAME=$(uname -s)
node_is_up() {
  if [[ "$UNAME" == "Darwin" ]]; then
    ping -c1 -t "$PING_TIMEOUT" "$1" > /dev/null 2>&1
  else
    ping -c1 -W "$PING_TIMEOUT" "$1" > /dev/null 2>&1
  fi
}

banner
$DRY_RUN && info "${YELLOW}${BOLD}DRY RUN${NC} — no node will be touched; commands are printed, not executed"
info "logs for this run: ${DIM}${LOG_DIR}${NC}"

# ----------------------------------------------------------------------
# [1/9] Pre-flight
# ----------------------------------------------------------------------
stage "Pre-flight checks"

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
  warn "kubectl not found — cordon/drain will be skipped (Talos self-drain still applies)"
  HAVE_KUBECTL=false
else
  HAVE_KUBECTL=true
  ok "kubectl present"
  # Guard against kubectl pointing at the WRONG cluster: cordoning and
  # draining someone else's nodes would be destructive and invisible here.
  kctx_server=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}' 2> /dev/null || true)
  if [[ "$kctx_server" == *"$CONTROL_PLANE_IP"* ]]; then
    ok "kubectl context targets this cluster (${DIM}${kctx_server}${NC})"
  elif [[ "${ALLOW_CONTEXT_MISMATCH:-0}" == "1" ]]; then
    warn "kubectl server is '${kctx_server}', not ${CONTROL_PLANE_IP} — continuing (ALLOW_CONTEXT_MISMATCH=1)"
  else
    refuse "kubectl context points at '${kctx_server:-<none>}', not ${CONTROL_PLANE_IP}. Fix the context (kubectx) or re-run with ALLOW_CONTEXT_MISMATCH=1."
    $DRY_RUN && HAVE_KUBECTL=false
  fi
fi

# ----------------------------------------------------------------------
# [2/9] Admission webhook health gate
# See docs/06-troubleshooting/2026-05-21-cilium-cascading-meltdown.md
# A webhook whose backend cannot schedule blocks the API server from
# admitting the very pods that would bring that backend up — a cold-boot
# deadlock at the new house. Worth refusing on, not just warning.
# ----------------------------------------------------------------------
stage "Admission webhook backend gate"
if $HAVE_KUBECTL; then
  # ONE API call for every endpoint in the cluster, then set membership —
  # the per-webhook version took minutes and stopped being run at all.
  ready_set=$(kubectl get endpoints -A \
    -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}{"\t"}{.subsets[*].addresses[*].ip}{"\n"}{end}' 2> /dev/null |
    awk -F'\t' '$2 != "" {print $1}' || true)

  if [[ -z "$ready_set" ]]; then
    warn "could not list endpoints — webhook gate is INCONCLUSIVE, not passed"
  fi
  broken=()
  gate_inconclusive=false
  for kind in mutatingwebhookconfigurations validatingwebhookconfigurations; do
    # shellcheck disable=SC2016  # {{$n}} is go-template syntax, not shell
    if ! hooks=$(kubectl get "$kind" -o go-template='{{range .items}}{{$n := .metadata.name}}{{range .webhooks}}{{if .clientConfig.service}}{{$n}}{{"\t"}}{{.clientConfig.service.namespace}}{{"\t"}}{{.clientConfig.service.name}}{{"\t"}}{{.failurePolicy}}{{"\n"}}{{end}}{{end}}{{end}}' 2> "$LOG_DIR/webhook-$kind.err"); then
      warn "could not list $kind — webhook gate is INCONCLUSIVE for these"
      gate_inconclusive=true
      continue
    fi
    while IFS=$'\t' read -r cfg_name svc_ns svc_name fail_policy; do
      [[ -z "$svc_ns" || -z "$svc_name" ]] && continue
      grep -qxF "${svc_ns}/${svc_name}" <<< "$ready_set" ||
        broken+=("$cfg_name → $svc_ns/$svc_name (no Ready endpoints, failurePolicy=$fail_policy)")
    done <<< "$hooks"
  done

  if [[ ${#broken[@]} -eq 0 ]]; then
    if $gate_inconclusive; then
      warn "no broken webhooks FOUND, but the check was partial — verify by hand if unsure"
    else
      ok "all admission webhooks have healthy backends"
    fi
  else
    err "broken admission webhooks — these will deadlock the next cold boot:"
    for w in "${broken[@]}"; do err "  $w"; done
    if [[ "${ALLOW_BROKEN_WEBHOOKS:-0}" == "1" ]]; then
      warn "continuing anyway because ALLOW_BROKEN_WEBHOOKS=1"
    else
      refuse "fix or delete them, or re-run with ALLOW_BROKEN_WEBHOOKS=1"
    fi
  fi
else
  warn "skipped (no kubectl) — cannot verify webhook backends"
fi

# ----------------------------------------------------------------------
# [3/9] Discovery & plan
#
# CONTROL PLANES GO IN AN ARRAY. The previous version assigned CP_NAME=$name
# inside the loop, so with more than one control plane every match overwrote
# the last and only ONE was ever shut down — it powered off 3 of 5 nodes and
# printed "Safe to swap the UPS" while two control planes were still running.
#
# kubectl discovery is CROSS-CHECKED against the expected node list: a node
# missing from kubectl (removed from the cluster, NotReady and purged, …)
# still gets shut down rather than silently skipped.
# ----------------------------------------------------------------------
stage "Discovery & shutdown plan"
WORKERS=()
CPS=()
add_node() { # role name ip
  NODE_IP[$2]=$3
  NODE_ROLE[$2]=$1
  if [[ "$1" == "control-plane" ]]; then CPS+=("$2:$3"); else WORKERS+=("$2:$3"); fi
}

if $HAVE_KUBECTL && kubectl get nodes -o wide > /dev/null 2>&1; then
  while IFS= read -r line; do
    name=$(awk '{print $1}' <<< "$line")
    ip=$(awk '{print $6}' <<< "$line")
    roles=$(awk '{print $3}' <<< "$line")
    if [[ "$roles" == *control-plane* ]]; then
      add_node control-plane "$name" "$ip"
    else
      add_node worker "$name" "$ip"
    fi
  done < <(kubectl get nodes --no-headers -o wide)
  ok "kubectl discovered ${#WORKERS[@]} worker(s) + ${#CPS[@]} control plane(s)"

  # Cross-check: every EXPECTED node must be in the plan.
  for role_list in "worker:${EXPECTED_WORKERS[*]}" "control-plane:${EXPECTED_CPS[*]}"; do
    role="${role_list%%:*}"
    for pair in ${role_list#*:}; do
      ename="${pair%:*}" eip="${pair#*:}"
      if [[ -z "${NODE_IP[$ename]:-}" ]]; then
        warn "${BOLD}$ename${NC} ($eip) is in the expected node list but NOT in kubectl discovery"
        warn "including it in the shutdown plan anyway — a forgotten node must not stay powered on"
        add_node "$role" "$ename" "$eip"
      fi
    done
  done
else
  # Roles here are DERIVED FROM configs/talconfig.yaml, not guessed. The old
  # fallback listed talos01 and talos03 as workers and would have force-killed
  # two of three control planes in parallel — instant quorum loss.
  warn "node discovery via kubectl failed — using the expected hardcoded list"
  for w in "${EXPECTED_WORKERS[@]}"; do add_node worker "${w%:*}" "${w#*:}"; done
  for c in "${EXPECTED_CPS[@]}"; do add_node control-plane "${c%:*}" "${c#*:}"; done
fi

if [[ ${#CPS[@]} -eq 0 ]]; then
  err "No control planes discovered — refusing to proceed"
  exit 1
fi

# The API endpoint goes LAST: every kubectl call in this script dies with it.
ENDPOINT_IP="${CONTROL_PLANE_IP}"
ordered=()
for c in "${CPS[@]}"; do [[ "${c#*:}" != "$ENDPOINT_IP" ]] && ordered+=("$c"); done
endpoint_found=false
for c in "${CPS[@]}"; do
  if [[ "${c#*:}" == "$ENDPOINT_IP" ]]; then
    ordered+=("$c")
    endpoint_found=true
  fi
done
CPS=("${ordered[@]}")
$endpoint_found || warn "endpoint $ENDPOINT_IP is not among the control planes — ordering is unchanged; check CONTROL_PLANE_IP"

# etcd quorum. Plain `talosctl shutdown` cordons and drains the node itself;
# --force skips both. All nodes are kubectl-drained beforehand, so --force on
# the final CPs only skips a self-drain that could never succeed anyway (the
# API server dies with quorum).
CP_TOTAL=${#CPS[@]}
QUORUM=$(((CP_TOTAL / 2) + 1))

printf "\n  ${BOLD}%-14s %-16s %s${NC}\n" "NODE" "IP" "ORDER"
for w in "${WORKERS[@]}"; do
  printf "  %-14s %-16s workers first (graceful, parallel)\n" "${w%:*}" "${w#*:}"
done
idx=0
for c in "${CPS[@]}"; do
  idx=$((idx + 1))
  left=$((CP_TOTAL - idx))
  if [[ $left -ge $QUORUM ]]; then
    note="control plane ${idx}/${CP_TOTAL} (graceful; quorum survives this stop)"
  else note="control plane ${idx}/${CP_TOTAL} (--force; API may not survive, self-drain impossible)"; fi
  printf "  %-14s %-16s ${YELLOW}%s${NC}\n" "${c%:*}" "${c#*:}" "$note"
done
printf "  ${DIM}etcd quorum is %d of %d; ALL control-plane drains happen BEFORE any CP stops.${NC}\n" "$QUORUM" "$CP_TOTAL"

if ! $ASSUME_YES && ! $DRY_RUN; then
  printf "\n  ${BOLD}This will power off the entire cluster. Type 'yes' to proceed: ${NC}"
  read -r confirm || confirm=""
  [[ "$confirm" == "yes" ]] || {
    err "Aborted — nothing was changed"
    exit 1
  }
fi
CONFIRMED_RUN=true

# ----------------------------------------------------------------------
# [4/9] etcd snapshot, OFF the cluster
#
# The hourly CronJob writes into MinIO, which is backed by NFS on the same
# NAS that is about to be powered off, and is unreadable without the cluster
# running anyway. A snapshot is only insurance if it lands somewhere else.
# ----------------------------------------------------------------------
stage "etcd snapshot to this machine"
SNAP="${SNAPSHOT_DIR:-$HOME}/talos-etcd-$(date +%Y%m%d-%H%M%S).snap"
snapshot_ok=false
if $DRY_RUN; then
  printf "  ${DIM}[dry-run]${NC} talosctl --nodes %s etcd snapshot %s\n" "$ENDPOINT_IP" "$SNAP"
elif talosctl --talosconfig "$TALOSCONFIG" --nodes "$ENDPOINT_IP" etcd snapshot "$SNAP" \
  > "$LOG_DIR/etcd-snapshot.log" 2>&1; then
  snap_bytes=$(wc -c < "$SNAP" | tr -d ' ')
  if [[ "${snap_bytes:-0}" -lt 1000000 ]]; then
    err "snapshot file is suspiciously small (${snap_bytes} bytes) — treating as FAILED"
  else
    ok "snapshot written: ${BOLD}${SNAP}${NC} (${snap_bytes} bytes)"
    snapshot_ok=true
  fi
else
  err "etcd snapshot FAILED:"
  sed 's/^/      /' "$LOG_DIR/etcd-snapshot.log" | tail -5 >&2
fi
if ! $DRY_RUN && ! $snapshot_ok; then
  if [[ "${SKIP_SNAPSHOT:-0}" == "1" ]]; then
    warn "continuing WITHOUT a snapshot because SKIP_SNAPSHOT=1"
  else
    err "not proceeding without a snapshot — this is the only copy that survives the move"
    err "re-run with SKIP_SNAPSHOT=1 only if you have another copy you trust"
    exit 1
  fi
fi

# ----------------------------------------------------------------------
# [5/9] Cordon everything
# ----------------------------------------------------------------------
stage "Cordon all nodes"
if $HAVE_KUBECTL; then
  for n in "${WORKERS[@]}" "${CPS[@]}"; do
    name="${n%:*}"
    if $DRY_RUN; then
      printf "  ${DIM}[dry-run]${NC} kubectl cordon %s\n" "$name"
    elif kubectl cordon "$name" > /dev/null 2>&1; then
      ok "cordoned ${BOLD}$name${NC}"
    else
      warn "could not cordon $name — continuing (Talos shutdown cordons too)"
    fi
  done
else
  warn "skipped (no kubectl)"
fi

# ----------------------------------------------------------------------
# wait_offline: confirm nodes are actually unreachable. A node is only
# declared offline after TWO consecutive failed pings (one lost packet or a
# slow ARP resolution must never count as "powered off"). Timing out leaves
# the node UNCONFIRMED — the summary and exit code stay honest about it.
# ----------------------------------------------------------------------
wait_offline() {
  local label="$1" timeout="$2"
  shift 2
  local list=("$@")
  [[ ${#list[@]} -eq 0 ]] && return 0
  substage "wait for ${label} to go offline (timeout ${timeout}s)"
  local deadline=$(($(date +%s) + timeout))
  local remaining=("${list[@]}")
  local -A miss=()
  local poll=0
  while [[ ${#remaining[@]} -gt 0 && $(date +%s) -lt $deadline ]]; do
    local still_up=()
    for n in "${remaining[@]}"; do
      local nname="${n%:*}" nip="${n#*:}"
      if node_is_up "$nip"; then
        miss[$nname]=0
        still_up+=("$n")
      else
        miss[$nname]=$((${miss[$nname]:-0} + 1))
        if [[ ${miss[$nname]} -ge 2 ]]; then
          NODE_OFFLINE_AT[$nname]=$(date +%s)
          ok "${BOLD}${nname}${NC} (${nip}) confirmed offline at T+$(($(date +%s) - T_START))s"
        else
          still_up+=("$n") # one miss is not confirmation
        fi
      fi
    done
    remaining=("${still_up[@]}")
    if [[ ${#remaining[@]} -gt 0 ]]; then
      poll=$((poll + 1))
      if $IS_TTY; then
        printf "${GRAY}[%s]${NC} ${DIM}polling… still up: %s${NC}\r" "$(ts)" "$(
          IFS=,
          echo "${remaining[*]%:*}"
        )"
      elif [[ $((poll % 10)) -eq 1 ]]; then
        printf "${GRAY}[%s]${NC} still waiting for: %s\n" "$(ts)" "$(
          IFS=,
          echo "${remaining[*]%:*}"
        )"
      fi
      sleep 3
      $IS_TTY && printf "\033[K"
    fi
  done
  if [[ ${#remaining[@]} -gt 0 ]]; then
    warn "timed out; ${BOLD}NOT confirmed offline${NC}: ${remaining[*]%:*} — will re-check at the end"
  fi
  return 0
}

# ----------------------------------------------------------------------
# [6/9] Workers, gracefully and in parallel
#
# NO --force. Plain shutdown makes Talos cordon and drain the node itself, so
# pods get SIGTERM and their terminationGracePeriod — which is what lets
# SQLite, Postgres and friends close their files instead of being killed.
#
# --wait=false everywhere: talosctl's own --wait defaults to true with a 30m
# timeout, and for the endpoint node it tracks progress over a connection the
# shutdown itself kills — it can block for half an hour or report failure for
# a shutdown that worked. Our ping confirmation is the ground truth instead.
# ----------------------------------------------------------------------
stage "Shut down workers (graceful, parallel)"
if [[ ${#WORKERS[@]} -eq 0 ]]; then
  info "no workers to shut down"
else
  pids=()
  for w in "${WORKERS[@]}"; do
    name="${w%:*}"
    ip="${w#*:}"
    if $DRY_RUN; then
      printf "  ${DIM}[dry-run]${NC} talosctl --nodes %s shutdown --wait=false\n" "$ip"
      NODE_SHUTDOWN_OK[$name]="dry-run"
    else
      info "→ sending graceful shutdown to ${BOLD}$name${NC} (${ip})"
      talosctl --talosconfig "$TALOSCONFIG" --nodes "$ip" shutdown --wait=false \
        > "$LOG_DIR/shutdown-$name.log" 2>&1 &
      pids+=("$!:$name")
    fi
  done
  if ! $DRY_RUN; then
    for entry in "${pids[@]}"; do
      pid="${entry%%:*}"
      name="${entry#*:}"
      if wait "$pid"; then
        ok "shutdown request ${BOLD}accepted${NC} by $name ${DIM}(not yet confirmed off)${NC}"
        NODE_SHUTDOWN_OK[$name]="yes"
      else
        warn "shutdown request FAILED for $name: $(tail -1 "$LOG_DIR/shutdown-$name.log" 2> /dev/null)"
        NODE_SHUTDOWN_OK[$name]="no"
      fi
    done
    wait_offline "workers" "$WORKER_WAIT_TIMEOUT" "${WORKERS[@]}"
  fi
fi

# ----------------------------------------------------------------------
# [7/9] Drain EVERY control plane, before shutting ANY of them down
#
# THE ORDERING THAT MATTERS. Once CPs stop, etcd falls below quorum and the
# API server stops accepting writes — so a `kubectl drain` issued against the
# last control plane fails at exactly the moment you need it. Drain them all
# while the cluster can still answer, then power them down.
# ----------------------------------------------------------------------
stage "Drain all control planes (while etcd still has quorum)"
if $HAVE_KUBECTL; then
  for c in "${CPS[@]}"; do
    name="${c%:*}"
    if $DRY_RUN; then
      printf "  ${DIM}[dry-run]${NC} kubectl drain %s --ignore-daemonsets --delete-emptydir-data --force --disable-eviction --timeout=%s\n" \
        "$name" "${DRAIN_TIMEOUT:-120s}"
      # --disable-eviction makes drain DELETE pods rather than go through the
      # eviction API, bypassing PodDisruptionBudgets.
      #
      # THIS IS NOT A SHORTCUT — it is the only thing that CAN work here, and
      # omitting it caused real data corruption on 2026-11-06. A PDB asks "will
      # enough replicas remain?"; in a whole-cluster shutdown the answer is
      # permanently no, so eviction can NEVER drain a PDB-guarded pod. 32 pods
      # across talos01 and talos03 failed to evict for exactly that reason —
      # mostly CNPG Postgres instances, plus crowdsec-lapi, kyverno-admission
      # and virt-api.
      #
      # Those pods then died later inside `talosctl shutdown`, as kubelet stopped
      # with the API server already gone — the least graceful path available. zot
      # came back with a TRUNCATED index.json ("unexpected end of JSON input")
      # and needed hand repair.
      #
      # Deleting still sends SIGTERM and still honours the full
      # terminationGracePeriodSeconds, and it happens HERE while the API server
      # is up and quorum holds — strictly gentler than what respecting the PDBs
      # actually produced.
    elif kubectl drain "$name" --ignore-daemonsets --delete-emptydir-data --force --disable-eviction \
      --timeout="${DRAIN_TIMEOUT:-120s}" > "$LOG_DIR/drain-$name.log" 2>&1; then
      ok "drained ${BOLD}$name${NC}"
    else
      warn "drain incomplete for $name (see $LOG_DIR/drain-$name.log) — continuing"
    fi
  done
else
  warn "skipped (no kubectl)"
fi

# ----------------------------------------------------------------------
# [8/9] Control planes, one at a time, endpoint last
# ----------------------------------------------------------------------
stage "Shut down control planes (sequential, endpoint last)"
idx=0
for c in "${CPS[@]}"; do
  idx=$((idx + 1))
  name="${c%:*}"
  ip="${c#*:}"
  left=$((CP_TOTAL - idx))
  args=(--wait=false)
  if [[ $left -ge $QUORUM ]]; then
    why="quorum survives this stop"
  else
    args+=(--force)
    why="API may not survive; already kubectl-drained, --force only skips the impossible self-drain"
  fi
  substage "control plane ${idx}/${CP_TOTAL}: ${BOLD}$name${NC} @ $ip ${DIM}($why)${NC}"
  if $DRY_RUN; then
    NODE_SHUTDOWN_OK[$name]="dry-run"
    printf "  ${DIM}[dry-run]${NC} talosctl --nodes %s shutdown %s\n" "$ip" "${args[*]}"
  else
    if talosctl --talosconfig "$TALOSCONFIG" --nodes "$ip" shutdown "${args[@]}" \
      > "$LOG_DIR/shutdown-$name.log" 2>&1; then
      ok "shutdown request ${BOLD}accepted${NC} by $name ${DIM}(not yet confirmed off)${NC}"
      NODE_SHUTDOWN_OK[$name]="yes"
    else
      err "shutdown request FAILED for $name: $(tail -1 "$LOG_DIR/shutdown-$name.log" 2> /dev/null)"
      NODE_SHUTDOWN_OK[$name]="no"
    fi
    wait_offline "$name" "$CP_WAIT_TIMEOUT" "$c"
  fi
done

# ----------------------------------------------------------------------
# [9/9] Final verification — every node must be CONFIRMED offline
# ----------------------------------------------------------------------
stage "Final verification sweep"
all_nodes=()
for w in "${WORKERS[@]}"; do all_nodes+=("${w%:*}"); done
for c in "${CPS[@]}"; do all_nodes+=("${c%:*}"); done

if ! $DRY_RUN; then
  unconfirmed=()
  for n in "${all_nodes[@]}"; do
    [[ -z "${NODE_OFFLINE_AT[$n]:-}" ]] && unconfirmed+=("$n:${NODE_IP[$n]}")
  done
  if [[ ${#unconfirmed[@]} -eq 0 ]]; then
    ok "every node already confirmed offline"
  else
    wait_offline "unconfirmed nodes" "$FINAL_RECHECK_TIMEOUT" "${unconfirmed[@]}"
  fi
else
  info "dry-run — nothing to verify"
fi
close_stage

# ----------------------------------------------------------------------
# Summary
# ----------------------------------------------------------------------
REACHED_SUMMARY=true
TOTAL=$(elapsed "$T_START")
printf "\n${BOLD}${MAGENTA}┏━━ Summary ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
printf "  ${BOLD}%-14s %-16s %-14s %-14s %s${NC}\n" "NODE" "IP" "ROLE" "REQUEST" "POWER STATE"
printf "  ${GRAY}%-14s %-16s %-14s %-14s %s${NC}\n" \
  "─────────────" "───────────────" "─────────────" "─────────────" "──────────────────"

down_count=0
for n in "${all_nodes[@]}"; do
  ip="${NODE_IP[$n]:-?}"
  role="${NODE_ROLE[$n]:-?}"
  sd="${NODE_SHUTDOWN_OK[$n]:-?}"
  off="${NODE_OFFLINE_AT[$n]:-}"

  case "$sd" in
    yes) sd_txt="sent" sd_col="$GREEN" ;;
    no) sd_txt="failed" sd_col="$RED" ;;
    dry-run) sd_txt="dry-run" sd_col="$DIM" ;;
    *) sd_txt="not sent" sd_col="$YELLOW" ;;
  esac

  if [[ -n "$off" ]]; then
    down_count=$((down_count + 1))
    ps_txt="CONFIRMED OFF (T+$((off - T_START))s)" ps_col="$GREEN"
  elif $DRY_RUN; then
    ps_txt="dry-run" ps_col="$DIM"
  else
    ps_txt="NOT CONFIRMED — may still be running" ps_col="${RED}${BOLD}"
  fi

  printf "  %-14s %-16s %-14s ${sd_col}%-14s${NC} ${ps_col}%s${NC}\n" \
    "$n" "$ip" "$role" "$sd_txt" "$ps_txt"
done

printf "\n  ${BOLD}Total elapsed:${NC} %s\n" "$TOTAL"

print_poweron_runbook() {
  printf "\n${BOLD}${CYAN}┏━━ Power-on runbook (read this at the new house) ━━━━━━━━━${NC}\n"
  printf "  1. ${BOLD}Synology NAS first${NC} — it serves NFS storage AND hosts the talos00 VM.\n"
  printf "     Wait for NFS shares to come up, then start the ${BOLD}talos00${NC} VM (192.168.1.54).\n"
  printf "  2. Power on the other control planes: ${BOLD}talos01${NC} (192.168.1.177), ${BOLD}talos03${NC} (192.168.1.30).\n"
  printf "     Wait until the API answers and etcd is healthy:\n"
  printf "       ${DIM}talosctl --talosconfig %s --nodes %s etcd status${NC}\n" "$TALOSCONFIG" "$ENDPOINT_IP"
  printf "       ${DIM}kubectl get nodes${NC}   (expect %d control planes Ready)\n" "$CP_TOTAL"
  printf "  3. Power on the workers: ${BOLD}talos02-gpu${NC} (192.168.1.144), ${BOLD}talos06${NC} (192.168.1.19).\n"
  printf "  4. ${BOLD}Uncordon everything${NC} (the nodes were cordoned by this script):\n"
  printf "       ${DIM}kubectl uncordon %s${NC}\n" "${all_nodes[*]}"
  printf "  5. Verify: ${DIM}task talos:health && kubectl get pods -A | grep -v Running${NC}\n"
  printf "  ${YELLOW}${BOLD}NEVER run 'talosctl bootstrap'${NC} — the nodes keep their STATE partition;\n"
  printf "  etcd rejoins on its own. Bootstrap would wreck the existing cluster state.\n\n"
}

if $DRY_RUN; then
  printf "  ${YELLOW}${BOLD}(dry-run — no nodes were touched; the above is the plan only)${NC}\n"
  print_poweron_runbook
  exit 0
fi

if [[ $down_count -eq ${#all_nodes[@]} ]]; then
  printf "\n  ${GREEN}${BOLD}✓ ALL %d NODES CONFIRMED OFFLINE — safe to cut power / swap the UPS.${NC}\n" "${#all_nodes[@]}"
  printf "  etcd snapshot (keep this with you during the move): ${BOLD}%s${NC}\n" "${SNAP:-none}"
  print_poweron_runbook
  exit 0
else
  printf "\n  ${RED}${BOLD}✗ NOT SAFE TO CUT POWER — only %d of %d nodes confirmed offline.${NC}\n" \
    "$down_count" "${#all_nodes[@]}"
  printf "  ${RED}Nodes marked NOT CONFIRMED above may still be running. Verify each one\n"
  printf "  by ping/console before touching power. Re-running this script is safe.${NC}\n"
  printf "  Logs: %s\n\n" "$LOG_DIR"
  exit 1
fi
