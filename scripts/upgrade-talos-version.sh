#!/usr/bin/env bash
#
# Catalyst Cluster — Talos OS Upgrade
#
# Upgrades every Talos node to a target version, walking through every
# intermediate minor (Talos does not support skipping minors).
#
# Order: control plane first (one at a time), then workers sequentially.
# Each node is upgraded with talosctl, which cordons + drains + reboots it.
# We wait for the node to return Ready in kubectl before moving on.
#
# Usage:
#   ./scripts/upgrade-talos-version.sh <target-version> [--yes] [--dry-run] [--skip-intermediate] [--skip-health-check]
#
# Examples:
#   ./scripts/upgrade-talos-version.sh v1.13.0
#   ./scripts/upgrade-talos-version.sh v1.13.0 --dry-run
#   ./scripts/upgrade-talos-version.sh v1.12.5 --skip-intermediate   # only upgrade to that one version
#   ./scripts/upgrade-talos-version.sh v1.13.0 --skip-health-check   # bypass safety gate (NOT RECOMMENDED)
#
# Env overrides:
#   TALOSCONFIG (default ./configs/talosconfig)
#   INSTALLER_IMAGE_BASE (default ghcr.io/siderolabs/installer)
#   NODE_WAIT_TIMEOUT (default 600s)
#   LATEST_PATCH_<MINOR> (e.g. LATEST_PATCH_1_11=v1.11.4) to pin patch versions
#

set -euo pipefail

TALOSCONFIG="${TALOSCONFIG:-./configs/talosconfig}"
INSTALLER_IMAGE_BASE="${INSTALLER_IMAGE_BASE:-ghcr.io/siderolabs/installer}"
NODE_WAIT_TIMEOUT="${NODE_WAIT_TIMEOUT:-600}"
PING_TIMEOUT=2

ASSUME_YES=false
DRY_RUN=false
SKIP_INTERMEDIATE=false
SKIP_HEALTH_CHECK=false
TARGET_VERSION=""

for arg in "$@"; do
  case "$arg" in
    --yes | -y) ASSUME_YES=true ;;
    --dry-run | -n) DRY_RUN=true ;;
    --skip-intermediate) SKIP_INTERMEDIATE=true ;;
    --skip-health-check) SKIP_HEALTH_CHECK=true ;;
    -h | --help)
      sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    v[0-9]*) TARGET_VERSION="$arg" ;;
    [0-9]*) TARGET_VERSION="v$arg" ;;
    *)
      echo "Unknown arg: $arg" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$TARGET_VERSION" ]]; then
  echo "Error: target version required (e.g. v1.13.0)" >&2
  exit 2
fi

# ----------------------------------------------------------------------
# Pretty output (shared style with shutdown-cluster.sh)
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
   _   _ ____   ____ ____      _    ____  _____
  | | | |  _ \ / ___|  _ \    / \  |  _ \| ____|
  | | | | |_) | |  _| |_) |  / _ \ | | | |  _|
  | |_| |  __/| |_| |  _ <  / ___ \| |_| | |___
   \___/|_|    \____|_| \_\/_/   \_\____/|_____|

  catalyst-cluster · talos OS upgrade
EOF
  printf "${NC}\n"
}

trap 'tput cnorm 2>/dev/null || true' EXIT

declare -A NODE_IP NODE_ROLE NODE_FROM_VER NODE_TO_VER NODE_RESULT NODE_DURATION

T_START=$(date +%s)
banner

# ----------------------------------------------------------------------
# Pre-flight
# ----------------------------------------------------------------------
step "Pre-flight checks"
command -v talosctl > /dev/null || {
  err "talosctl not in PATH"
  exit 1
}
command -v kubectl > /dev/null || {
  err "kubectl not in PATH"
  exit 1
}
[[ -f "$TALOSCONFIG" ]] || {
  err "talosconfig missing at $TALOSCONFIG"
  exit 1
}
ok "talosctl, kubectl, talosconfig present"

# Validate target version format
if ! [[ "$TARGET_VERSION" =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
  err "target version must look like v1.13.0 (got: $TARGET_VERSION)"
  exit 2
fi
TARGET_MAJ="${BASH_REMATCH[1]}"
TARGET_MIN="${BASH_REMATCH[2]}"

# ----------------------------------------------------------------------
# Discover nodes
# ----------------------------------------------------------------------
WORKER_NAMES=()
CP_NAME=""
CP_IP=""
while IFS= read -r line; do
  name=$(awk '{print $1}' <<< "$line")
  ip=$(awk '{print $6}' <<< "$line")
  roles=$(awk '{print $3}' <<< "$line")
  NODE_IP[$name]=$ip
  if [[ "$roles" == *control-plane* ]]; then
    CP_NAME=$name
    CP_IP=$ip
    NODE_ROLE[$name]="control-plane"
  else
    WORKER_NAMES+=("$name")
    NODE_ROLE[$name]="worker"
  fi
done < <(kubectl get nodes --no-headers -o wide)

[[ -n "$CP_NAME" ]] || {
  err "no control-plane node found via kubectl"
  exit 1
}
ok "Found CP: ${BOLD}$CP_NAME${NC} ($CP_IP) + ${#WORKER_NAMES[@]} workers"

# Detect current versions
all_nodes=("$CP_NAME" "${WORKER_NAMES[@]}")
detect_version() {
  local ip=$1
  talosctl --talosconfig "$TALOSCONFIG" --nodes "$ip" version 2> /dev/null |
    awk '/Server:/{found=1; next} found && /Tag:/{print $2; exit}'
}

declare -A CURRENT_VER
min_minor=999
for n in "${all_nodes[@]}"; do
  v=$(detect_version "${NODE_IP[$n]}" || true)
  [[ -z "$v" ]] && {
    err "could not detect version on $n (${NODE_IP[$n]})"
    exit 1
  }
  CURRENT_VER[$n]=$v
  NODE_FROM_VER[$n]=$v
  if [[ "$v" =~ ^v([0-9]+)\.([0-9]+)\. ]]; then
    m="${BASH_REMATCH[2]}"
    ((m < min_minor)) && min_minor=$m
  fi
done
for n in "${all_nodes[@]}"; do
  printf "  %-14s ${DIM}%s${NC} → ${BOLD}%s${NC}\n" "$n" "${CURRENT_VER[$n]}" "$TARGET_VERSION"
done

# ----------------------------------------------------------------------
# Pre-upgrade cluster health check
# ----------------------------------------------------------------------
health_check() {
  local failed=0

  # Determine if we're in "everything cordoned" mode — common after a clean
  # cluster restart where the operator wants to keep workloads paused.
  # In that mode, Pending pods and stale Error replicas are expected and
  # should NOT block a Talos upgrade (talosctl handles cordon/drain itself).
  local total_nodes cordoned_nodes
  total_nodes=$(kubectl get nodes --no-headers 2> /dev/null | wc -l | tr -d ' ')
  cordoned_nodes=$(kubectl get nodes --no-headers 2> /dev/null | awk '$2 ~ /SchedulingDisabled/' | wc -l | tr -d ' ')
  local all_cordoned=false
  ((total_nodes > 0 && cordoned_nodes == total_nodes)) && all_cordoned=true

  if $all_cordoned; then
    info "${YELLOW}all $total_nodes nodes are cordoned${NC} — Pending/Error stale replicas will be tolerated"
  fi

  # 1. talosctl health
  # When all nodes are cordoned, talosctl health will fail on the coredns
  # replica-count check because scheduling is disabled. Demote to warning.
  info "running talosctl health (server-side checks)"
  if talosctl --talosconfig "$TALOSCONFIG" --nodes "$CP_IP" health \
    --server=false --wait-timeout=30s > /tmp/health-talos.log 2>&1; then
    ok "talosctl reports healthy"
  else
    if $all_cordoned && grep -qE "coredns|expected .* ready pods" /tmp/health-talos.log; then
      warn "talosctl health failed on a replica-count check (cordon-induced) — tolerating"
    else
      err "talosctl health failed — see /tmp/health-talos.log"
      tail -5 /tmp/health-talos.log | sed "s/^/    ${DIM}/; s/$/${NC}/"
      failed=$((failed + 1))
    fi
  fi

  # 2. Every node Ready (cordoned is OK)
  info "checking node readiness"
  local node_issues=0
  while IFS= read -r line; do
    local name status
    name=$(awk '{print $1}' <<< "$line")
    status=$(awk '{print $2}' <<< "$line")
    # "Ready" and "Ready,SchedulingDisabled" both indicate kubelet is healthy
    if [[ "$status" != Ready* ]]; then
      warn "node $name status=$status (expected Ready)"
      node_issues=$((node_issues + 1))
    fi
  done < <(kubectl get nodes --no-headers 2> /dev/null)
  if ((node_issues == 0)); then
    if $all_cordoned; then
      ok "all $total_nodes nodes Ready (all cordoned)"
    else
      ok "all $total_nodes nodes Ready"
    fi
  else
    err "$node_issues node(s) not Ready"
    failed=$((failed + 1))
  fi

  # 3. Critical-namespace pods.
  # DaemonSets (cilium, kube-proxy) must be Running.
  # Static control-plane pods (kube-apiserver-*, etc.) must be Running.
  # Other Deployment-managed pods may be Pending if all nodes cordoned.
  info "checking critical system namespaces"
  local critical_ns=(kube-system flannel cilium kube-flannel)
  local critical_bad=0
  for ns in "${critical_ns[@]}"; do
    kubectl get ns "$ns" > /dev/null 2>&1 || continue
    while IFS= read -r line; do
      local pod ready phase
      pod=$(awk '{print $1}' <<< "$line")
      ready=$(awk '{print $2}' <<< "$line")
      phase=$(awk '{print $3}' <<< "$line")
      [[ "$phase" == "Running" || "$phase" == "Completed" || "$phase" == "Succeeded" ]] && continue

      # Tolerate when all nodes are cordoned:
      #   - Pending pods (can't schedule by definition)
      #   - Error/ContainerStatusUnknown pods left over from prior restarts
      if $all_cordoned; then
        case "$phase" in
          Pending | Error | ContainerStatusUnknown | Terminating | Unknown)
            printf "    ${DIM}tolerating [%s] %s — %s${NC}\n" "$ns" "$pod" "$phase"
            continue
            ;;
        esac
      fi

      warn "[$ns] $pod — $phase"
      critical_bad=$((critical_bad + 1))
    done < <(kubectl get pods -n "$ns" --no-headers 2> /dev/null)
  done

  # Verify Cilium DaemonSet pods are actually running (these are the must-haves)
  local cilium_ds_status
  cilium_ds_status=$(kubectl get ds -n kube-system cilium --no-headers 2> /dev/null |
    awk '{printf "desired=%s ready=%s available=%s", $2, $4, $6}')
  if [[ -n "$cilium_ds_status" ]]; then
    local desired ready
    desired=$(awk '{print $2}' <<< "$cilium_ds_status" | cut -d= -f2)
    ready=$(awk '{print $4}' <<< "$cilium_ds_status" | cut -d= -f2)
    if [[ "$desired" == "$ready" && -n "$desired" ]]; then
      ok "Cilium DaemonSet healthy ($cilium_ds_status)"
    else
      err "Cilium DaemonSet not fully ready ($cilium_ds_status)"
      critical_bad=$((critical_bad + 1))
    fi
  fi

  if ((critical_bad == 0)); then
    ok "critical-namespace pods all healthy (or tolerated)"
  else
    err "$critical_bad critical pod(s) unhealthy — fix before upgrading"
    failed=$((failed + 1))
  fi

  # 4. etcd health (CP-side via talos)
  info "checking etcd health"
  if talosctl --talosconfig "$TALOSCONFIG" --nodes "$CP_IP" \
    etcd status > /tmp/health-etcd.log 2>&1; then
    local members
    members=$(grep -c "MEMBER" /tmp/health-etcd.log 2> /dev/null || echo 0)
    ok "etcd reachable ($members member entries reported)"
  else
    err "etcd status query failed — see /tmp/health-etcd.log"
    failed=$((failed + 1))
  fi

  # 5. API server: can we list nodes? (already done implicitly, but be explicit)
  info "checking Kubernetes API server"
  if kubectl version --request-timeout=10s > /dev/null 2>&1; then
    ok "kube API server responsive"
  else
    err "kube API server not responsive"
    failed=$((failed + 1))
  fi

  # 6. Already-cordoned nodes (would block our upgrade's own cordon/uncordon)
  info "checking for pre-existing cordons"
  local cordoned
  cordoned=$(kubectl get nodes --no-headers 2> /dev/null |
    awk '$2 ~ /SchedulingDisabled/ {print $1}')
  if [[ -z "$cordoned" ]]; then
    ok "no nodes already cordoned"
  else
    warn "nodes already cordoned: $cordoned (will be un-cordoned during upgrade)"
  fi

  # 7. Talos version consistency (informational — script handles mixed versions)
  info "checking version skew across nodes"
  local versions_seen=()
  for n in "${all_nodes[@]}"; do
    versions_seen+=("${CURRENT_VER[$n]}")
  done
  local unique_versions
  unique_versions=$(printf '%s\n' "${versions_seen[@]}" | sort -u | wc -l | tr -d ' ')
  if ((unique_versions == 1)); then
    ok "all nodes on ${CURRENT_VER[$CP_NAME]}"
  else
    warn "version skew detected (${unique_versions} versions across nodes) — upgrade will normalize"
  fi

  return $failed
}

step "Pre-upgrade health check"
if $SKIP_HEALTH_CHECK; then
  warn "health check skipped via --skip-health-check"
elif $DRY_RUN; then
  info "dry-run: still running health check (read-only)"
  if health_check; then
    ok "cluster is healthy — safe to proceed"
  else
    err "cluster has issues — upgrade would refuse to run"
  fi
else
  if health_check; then
    ok "cluster is healthy — safe to proceed"
  else
    err "cluster is not healthy. Fix the issues above, or rerun with --skip-health-check to override (NOT recommended)"
    exit 1
  fi
fi

# ----------------------------------------------------------------------
# Compute upgrade path (intermediate minors)
# ----------------------------------------------------------------------
step "Compute upgrade path"
UPGRADE_PATH=()
if $SKIP_INTERMEDIATE; then
  UPGRADE_PATH=("$TARGET_VERSION")
  warn "skipping intermediate-minor walk (NOT RECOMMENDED by Sidero)"
else
  # latest patch per minor — overridable via LATEST_PATCH_X_Y env var
  default_latest_patch() {
    local minor=$1
    local override
    override=$(eval echo "\${LATEST_PATCH_1_${minor}:-}")
    if [[ -n "$override" ]]; then
      echo "$override"
      return
    fi
    # Sane default patch versions known good as of May 2026.
    # Override with LATEST_PATCH_1_<MINOR>=v1.<MINOR>.<patch> if newer exists.
    case "$minor" in
      11) echo "v1.11.4" ;;
      12) echo "v1.12.3" ;;
      13) echo "$TARGET_VERSION" ;; # use target for the final step
      *) echo "v1.${minor}.0" ;;
    esac
  }
  # Walk from min(current minor) up through target minor
  m=$min_minor
  while ((m < TARGET_MIN)); do
    UPGRADE_PATH+=("$(default_latest_patch "$m")")
    m=$((m + 1))
  done
  UPGRADE_PATH+=("$TARGET_VERSION")
fi

echo "  Upgrade steps:"
for v in "${UPGRADE_PATH[@]}"; do echo "    → $v"; done

# ----------------------------------------------------------------------
# Plan summary
# ----------------------------------------------------------------------
step "Plan summary"
printf "  ${BOLD}%-14s %-16s %-14s %s${NC}\n" "NODE" "IP" "ROLE" "CURRENT"
printf "  ${GRAY}%-14s %-16s %-14s %s${NC}\n" "─────────────" "───────────────" "─────────────" "─────────────"
printf "  %-14s %-16s ${YELLOW}%-14s${NC} %s ${YELLOW}(upgrades first)${NC}\n" \
  "$CP_NAME" "$CP_IP" "control-plane" "${CURRENT_VER[$CP_NAME]}"
for n in "${WORKER_NAMES[@]}"; do
  printf "  %-14s %-16s ${GRAY}%-14s${NC} %s\n" "$n" "${NODE_IP[$n]}" "worker" "${CURRENT_VER[$n]}"
done
echo
path_joined=""
for v in "${UPGRADE_PATH[@]}"; do
  if [[ -z "$path_joined" ]]; then path_joined="$v"; else path_joined="$path_joined → $v"; fi
done
# Find min and max current versions across all nodes for accurate display
min_ver=""
max_ver=""
for n in "${all_nodes[@]}"; do
  v="${CURRENT_VER[$n]}"
  [[ -z "$min_ver" || "$v" < "$min_ver" ]] && min_ver="$v"
  [[ -z "$max_ver" || "$v" > "$max_ver" ]] && max_ver="$v"
done
if [[ "$min_ver" == "$max_ver" ]]; then
  echo "  Path: ${min_ver} → ${path_joined}"
else
  echo "  Path: ${DIM}current spans${NC} ${min_ver}…${max_ver} ${DIM}→${NC} ${path_joined}"
fi

if ! $ASSUME_YES && ! $DRY_RUN; then
  echo
  read -rp "$(printf "${YELLOW}This will upgrade ALL nodes via reboots. Type 'yes' to proceed: ${NC}")" confirm
  [[ "$confirm" == "yes" ]] || {
    err "Aborted"
    exit 1
  }
fi

# ----------------------------------------------------------------------
# Upgrade helpers
# ----------------------------------------------------------------------
upgrade_node() {
  local name=$1 ip=$2 version=$3
  local image="${INSTALLER_IMAGE_BASE}:${version}"
  local node_start=$(date +%s)

  info "→ upgrading ${BOLD}$name${NC} (${ip}) to ${BOLD}$version${NC}"

  if $DRY_RUN; then
    printf "  ${DIM}[dry-run]${NC} talosctl upgrade --nodes %s --image %s --wait\n" "$ip" "$image"
    NODE_RESULT[$name]="dry-run"
    return 0
  fi

  # talosctl upgrade does: cordon → drain → reboot into new image, and waits.
  # --preserve protects user data; default for CP. Explicit for clarity.
  if talosctl --talosconfig "$TALOSCONFIG" --nodes "$ip" upgrade \
    --image "$image" --wait --preserve=true 2>&1 | sed "s/^/  ${DIM}[$name]${NC} /"; then
    ok "talosctl upgrade returned for $name"
  else
    err "talosctl upgrade failed for $name"
    NODE_RESULT[$name]="failed"
    NODE_DURATION[$name]=$(elapsed "$node_start")
    return 1
  fi

  # Wait until kubectl reports the node Ready (cordoned/SchedulingDisabled is OK)
  # AND its server-reported Talos version equals the target version.
  info "waiting for $name to return Ready on $version (timeout ${NODE_WAIT_TIMEOUT}s)…"
  local deadline=$(($(date +%s) + NODE_WAIT_TIMEOUT))
  while (($(date +%s) < deadline)); do
    local status
    status=$(kubectl get node "$name" --no-headers 2> /dev/null | awk '{print $2}')
    # Accept "Ready" or "Ready,SchedulingDisabled" — both indicate kubelet is healthy
    if [[ "$status" == Ready* ]]; then
      local new_ver
      new_ver=$(detect_version "$ip" || echo "?")
      if [[ "$new_ver" == "$version" ]]; then
        ok "${BOLD}$name${NC} is $status on $new_ver"
        NODE_RESULT[$name]="ok"
        NODE_TO_VER[$name]=$new_ver
        NODE_DURATION[$name]=$(elapsed "$node_start")
        return 0
      fi
    fi
    printf "${GRAY}[%s]${NC} ${DIM}waiting on %s… status=%s${NC}\r" "$(ts)" "$name" "${status:-?}"
    sleep 5
    printf "\033[K"
  done

  err "$name did not return Ready on $version within ${NODE_WAIT_TIMEOUT}s"
  NODE_RESULT[$name]="timeout"
  NODE_DURATION[$name]=$(elapsed "$node_start")
  return 1
}

# Upgrade all workers in parallel by passing comma-separated IPs to talosctl.
# Sidero supports this; CP is excluded because Talos serializes CP upgrades anyway.
upgrade_workers_parallel() {
  local version=$1
  local image="${INSTALLER_IMAGE_BASE}:${version}"
  local phase_start=$(date +%s)

  [[ ${#WORKER_NAMES[@]} -eq 0 ]] && {
    ok "no workers to upgrade"
    return 0
  }

  # Build comma-separated IP list
  local ips=()
  for w in "${WORKER_NAMES[@]}"; do ips+=("${NODE_IP[$w]}"); done
  local joined
  joined=$(
    IFS=,
    echo "${ips[*]}"
  )

  info "→ upgrading workers in parallel: ${BOLD}${WORKER_NAMES[*]}${NC} to ${BOLD}$version${NC}"
  info "  talosctl --nodes $joined upgrade --image $image"

  if $DRY_RUN; then
    for w in "${WORKER_NAMES[@]}"; do NODE_RESULT[$w]="dry-run"; done
    return 0
  fi

  # Single talosctl call handles all workers concurrently; --wait blocks until all done.
  if talosctl --talosconfig "$TALOSCONFIG" --nodes "$joined" upgrade \
    --image "$image" --wait --preserve=true 2>&1 |
    sed "s/^/  ${DIM}[workers]${NC} /"; then
    ok "talosctl upgrade returned for all workers (took $(elapsed "$phase_start"))"
  else
    err "talosctl upgrade failed for one or more workers"
    for w in "${WORKER_NAMES[@]}"; do NODE_RESULT[$w]="failed"; done
    return 1
  fi

  # Now poll each worker for Ready + correct version (parallel completion)
  info "waiting for workers to return Ready on $version (timeout ${NODE_WAIT_TIMEOUT}s each)…"
  local deadline=$(($(date +%s) + NODE_WAIT_TIMEOUT))
  declare -A done_map
  while (($(date +%s) < deadline)); do
    local still_waiting=()
    for w in "${WORKER_NAMES[@]}"; do
      [[ -n "${done_map[$w]:-}" ]] && continue
      local status
      status=$(kubectl get node "$w" --no-headers 2> /dev/null | awk '{print $2}')
      if [[ "$status" == Ready* ]]; then
        local v
        v=$(detect_version "${NODE_IP[$w]}" || echo "?")
        if [[ "$v" == "$version" ]]; then
          ok "${BOLD}$w${NC} is $status on $v"
          NODE_RESULT[$w]="ok"
          NODE_TO_VER[$w]=$v
          NODE_DURATION[$w]=$(elapsed "$phase_start")
          done_map[$w]=1
          continue
        fi
      fi
      still_waiting+=("$w")
    done
    if [[ ${#still_waiting[@]} -eq 0 ]]; then
      return 0
    fi
    printf "${GRAY}[%s]${NC} ${DIM}still waiting: %s${NC}\r" "$(ts)" "$(
      IFS=,
      echo "${still_waiting[*]}"
    )"
    sleep 5
    printf "\033[K"
  done

  for w in "${WORKER_NAMES[@]}"; do
    if [[ -z "${done_map[$w]:-}" ]]; then
      err "$w did not return Ready on $version within ${NODE_WAIT_TIMEOUT}s"
      NODE_RESULT[$w]="timeout"
    fi
  done
  return 1
}

# ----------------------------------------------------------------------
# Execute upgrade path
# ----------------------------------------------------------------------
overall_fail=0
for VERSION in "${UPGRADE_PATH[@]}"; do
  step "Upgrade phase → $VERSION"

  # Control plane first (sequential — only 1 CP, and Talos serializes anyway)
  if ! upgrade_node "$CP_NAME" "$CP_IP" "$VERSION"; then
    err "control-plane upgrade failed at $VERSION — STOPPING"
    overall_fail=1
    break
  fi

  # Then ALL workers in parallel — Sidero supports this via comma-separated --nodes
  if ! upgrade_workers_parallel "$VERSION"; then
    err "worker upgrade failed at $VERSION — STOPPING"
    overall_fail=1
    break
  fi

  ok "phase $VERSION complete"
done

[[ $step_start_ts -ne 0 ]] && printf "${DIM}└── completed in $(elapsed "$step_start_ts")${NC}\n"
step_start_ts=0

# ----------------------------------------------------------------------
# Final summary
# ----------------------------------------------------------------------
TOTAL=$(elapsed "$T_START")
printf "\n${BOLD}${MAGENTA}┏━━ Summary ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
printf "  ${BOLD}%-14s %-16s %-14s %-10s %-10s %s${NC}\n" "NODE" "IP" "ROLE" "FROM" "TO" "RESULT"
printf "  ${GRAY}%-14s %-16s %-14s %-10s %-10s %s${NC}\n" \
  "─────────────" "───────────────" "─────────────" "─────────" "─────────" "──────────"
for n in "${all_nodes[@]}"; do
  res="${NODE_RESULT[$n]:-skipped}"
  case "$res" in
    ok) res_disp="${GREEN}ok${NC} ${DIM}(${NODE_DURATION[$n]:-?})${NC}" ;;
    failed) res_disp="${RED}failed${NC} ${DIM}(${NODE_DURATION[$n]:-?})${NC}" ;;
    timeout) res_disp="${RED}timeout${NC} ${DIM}(${NODE_DURATION[$n]:-?})${NC}" ;;
    dry-run) res_disp="${DIM}dry-run${NC}" ;;
    *) res_disp="${YELLOW}$res${NC}" ;;
  esac
  printf "  %-14s %-16s %-14s %-10s %-10s %b\n" \
    "$n" "${NODE_IP[$n]}" "${NODE_ROLE[$n]}" \
    "${NODE_FROM_VER[$n]}" "${NODE_TO_VER[$n]:-—}" "$res_disp"
done

printf "\n  ${BOLD}Total elapsed:${NC} ${GREEN}%s${NC}\n" "$TOTAL"

if ((overall_fail)); then
  printf "  ${RED}✗ Upgrade stopped on failure — see logs above.${NC}\n\n"
  exit 1
elif $DRY_RUN; then
  printf "  ${YELLOW}(dry-run — no nodes were touched)${NC}\n\n"
else
  printf "\n  ${GREEN}✓ All nodes upgraded to $TARGET_VERSION.${NC}\n"
  printf "  ${DIM}Next: 'talosctl upgrade-k8s' to upgrade Kubernetes itself if desired.${NC}\n\n"
fi
