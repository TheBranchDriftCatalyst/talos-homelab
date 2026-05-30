#!/usr/bin/env bash
#
# test-suspect-talos00-memory.sh
#
# Suspect: Memory pressure on talos00 (control-plane) is causing OOM kills,
# Go-GC thrashing near GOMEMLIMIT, or kubelet eviction of cilium-agent and
# other critical pods.  This script collects evidence for/against that
# hypothesis across the whole cluster, but with extra scrutiny on talos00
# because it carries the cilium-on-CP load (Hubble Relay + SPIRE +
# clustermesh-apiserver + kube-apiserver + etcd + controller-manager +
# scheduler + cilium-operator + cilium-envoy + tempo + KubeVirt CP).
#
# Background:
#   - 2026-05-29 retro: 10 meltdowns / day on a single-CP cluster.  Throttle
#     fix improved cycle 1h → 2h but did not eliminate.
#   - Earlier today we bumped cilium-agent memory limit 1Gi → 2Gi
#     (infrastructure/base/cilium/values.yaml resources.limits.memory).
#     The Cilium Helm chart wires limits.memory into the GOMEMLIMIT env var
#     for the agent, so a 2Gi limit == 2Gi soft GC ceiling.  When the
#     resident set approaches GOMEMLIMIT, Go enters near-continuous GC and
#     the agent can stall its BPF/control-plane work.
#   - kernel-capture DaemonSet writes /dev/kmsg to
#     /var/log/kernel-capture/<node>.log on each node (persists across
#     reboots on the EPHEMERAL /var partition).
#
# Pass/Fail criteria:
#   PASS  - All cilium-agent containers <70% of their memory limit AND no
#           OOM events in the captured kernel log in the last 24h AND no
#           MemoryPressure node condition AND no eviction events for
#           cilium-agent pods.
#   FAIL  - Any cilium-agent >90% of its memory limit, OR any OOM event
#           naming cilium-agent / kube-apiserver / etcd in the kernel log,
#           OR talos00 MemAvailable < 15% of MemTotal, OR a MemoryPressure
#           condition flipped to true in the last 24h.
#   WARN  - Anything in between (70-90% usage, transient PSI spikes, etc.).
#
# Usage:
#   ./scripts/test-suspect-talos00-memory.sh                # all nodes
#   ./scripts/test-suspect-talos00-memory.sh talos00        # one node
#   ./scripts/test-suspect-talos00-memory.sh talos00 talos01
#
# Output: .output/suspect-tests/talos00-memory-<UTC-timestamp>/
#
# Designed to keep going when individual commands fail (set -u, NOT -e).

set -u

REPO_ROOT="$(git rev-parse --show-toplevel 2> /dev/null || pwd)"
TS=$(date -u +%Y%m%dT%H%M%SZ)
OUTDIR="${REPO_ROOT}/.output/suspect-tests/talos00-memory-${TS}"
mkdir -p "${OUTDIR}"

TALOSCONFIG_FLAG="--talosconfig ${REPO_ROOT}/configs/talosconfig"

# Default to all 5 nodes.  Override via positional args.
DEFAULT_NODES=(talos00 talos01 talos02-gpu talos03 talos06)
if [ "$#" -gt 0 ]; then
  NODES=("$@")
else
  NODES=("${DEFAULT_NODES[@]}")
fi

declare -A NODE_IPS
NODE_IPS["talos00"]=192.168.1.54
NODE_IPS["talos01"]=192.168.1.177
NODE_IPS["talos02-gpu"]=192.168.1.144
NODE_IPS["talos03"]=192.168.1.30
NODE_IPS["talos06"]=192.168.1.19

# Thresholds (override via env if needed)
PASS_THRESHOLD_PCT="${PASS_THRESHOLD_PCT:-70}"
FAIL_THRESHOLD_PCT="${FAIL_THRESHOLD_PCT:-90}"
MEMAVAIL_FAIL_PCT="${MEMAVAIL_FAIL_PCT:-15}" # FAIL if MemAvailable < this % of MemTotal

# Tally for final verdict
FAILS=0
WARNS=0

echo "Talos00 memory-pressure suspect test"
echo "Output dir: ${OUTDIR}"
echo "Start: $(date -u +%FT%TZ)"
echo "Nodes: ${NODES[*]}"
echo

# Timeout shim (macOS may not have GNU timeout)
if command -v gtimeout > /dev/null 2>&1; then
  TIMEOUT_CMD="gtimeout 15"
elif command -v timeout > /dev/null 2>&1; then
  TIMEOUT_CMD="timeout 15"
else
  TIMEOUT_CMD=""
fi

run() {
  local label=$1
  shift
  local out=$1
  shift
  echo "  - ${label}"
  if [ -n "$TIMEOUT_CMD" ]; then
    eval "$TIMEOUT_CMD" "$@" > "${out}" 2>&1 ||
      echo "    (failed, continuing)" >&2
  else
    "$@" > "${out}" 2>&1 || echo "    (failed, continuing)" >&2
  fi
}

# -------------------------------------------------------------------------
# Phase 1: per-node host memory + PSI
# -------------------------------------------------------------------------
echo "=== Phase 1: per-node host memory + PSI ==="
for node in "${NODES[@]}"; do
  ip=${NODE_IPS[$node]:-$node}
  prefix="${OUTDIR}/host-${node}"
  echo
  echo "Node: ${node} (${ip})"

  run "  /proc/meminfo" "${prefix}-meminfo.txt" talosctl ${TALOSCONFIG_FLAG} --nodes "$ip" read /proc/meminfo
  run "  /proc/loadavg" "${prefix}-loadavg.txt" talosctl ${TALOSCONFIG_FLAG} --nodes "$ip" read /proc/loadavg
  run "  /proc/pressure/memory" "${prefix}-psi-memory.txt" talosctl ${TALOSCONFIG_FLAG} --nodes "$ip" read /proc/pressure/memory
  run "  /proc/pressure/cpu" "${prefix}-psi-cpu.txt" talosctl ${TALOSCONFIG_FLAG} --nodes "$ip" read /proc/pressure/cpu
  run "  /proc/pressure/io" "${prefix}-psi-io.txt" talosctl ${TALOSCONFIG_FLAG} --nodes "$ip" read /proc/pressure/io
  run "  /proc/vmstat" "${prefix}-vmstat.txt" talosctl ${TALOSCONFIG_FLAG} --nodes "$ip" read /proc/vmstat

  # Compute MemAvailable % from the captured meminfo file.
  if [ -s "${prefix}-meminfo.txt" ]; then
    mem_total=$(awk '/^MemTotal:/{print $2}' "${prefix}-meminfo.txt")
    mem_avail=$(awk '/^MemAvailable:/{print $2}' "${prefix}-meminfo.txt")
    if [ -n "${mem_total:-}" ] && [ -n "${mem_avail:-}" ] && [ "$mem_total" -gt 0 ]; then
      pct=$(awk -v a="$mem_avail" -v t="$mem_total" 'BEGIN{printf "%.1f", (a/t)*100}')
      printf "    MemAvailable: %s kB / %s kB (%.1f%%)\n" "$mem_avail" "$mem_total" "$pct"
      # FAIL gate: very low MemAvailable, especially on talos00
      avail_int=$(awk -v p="$pct" 'BEGIN{printf "%d", p}')
      if [ "$avail_int" -lt "$MEMAVAIL_FAIL_PCT" ]; then
        echo "    FAIL: MemAvailable < ${MEMAVAIL_FAIL_PCT}% on ${node}" |
          tee -a "${OUTDIR}/_verdict.txt"
        FAILS=$((FAILS + 1))
      fi
    fi
  fi

  # PSI memory: "some avg10" and "full avg10" are the most useful at-a-glance.
  if [ -s "${prefix}-psi-memory.txt" ]; then
    grep -E "^(some|full)" "${prefix}-psi-memory.txt" | sed 's/^/    psi: /'
    # WARN gate: full avg10 > 5 means real stalls.
    full10=$(awk '/^full /{for(i=1;i<=NF;i++)if($i ~ /^avg10=/){split($i,a,"=");print a[2]}}' "${prefix}-psi-memory.txt")
    if [ -n "${full10:-}" ]; then
      bad=$(awk -v v="$full10" 'BEGIN{print (v+0 > 5.0) ? 1 : 0}')
      if [ "$bad" = "1" ]; then
        echo "    WARN: PSI memory full avg10=${full10} on ${node}" |
          tee -a "${OUTDIR}/_verdict.txt"
        WARNS=$((WARNS + 1))
      fi
    fi
  fi
done

# -------------------------------------------------------------------------
# Phase 2: kernel log scan for OOM / page-allocation failures
# -------------------------------------------------------------------------
echo
echo "=== Phase 2: kernel-capture log scan (OOM / killed process) ==="
KERNEL_PATTERN='(oom|Out of memory|killed process|page allocation failure|invoked oom-killer|memory.events|Memory cgroup out of memory)'
for node in "${NODES[@]}"; do
  ip=${NODE_IPS[$node]:-$node}
  out="${OUTDIR}/kernel-${node}-oom.txt"
  echo "  - ${node}: /var/log/kernel-capture/${node}.log"
  # Pull the entire kernel-capture file (it is capped at 100MB by the DS).
  # If absent (node hasn't rotated or DS not running), skip silently.
  if eval "$TIMEOUT_CMD" talosctl ${TALOSCONFIG_FLAG} --nodes "$ip" \
    read "/var/log/kernel-capture/${node}.log" 2> /dev/null |
    grep -iE "$KERNEL_PATTERN" > "${out}"; then
    if [ -s "${out}" ]; then
      count=$(wc -l < "${out}")
      echo "    FAIL: ${count} OOM/killed-process lines in kernel log for ${node}" |
        tee -a "${OUTDIR}/_verdict.txt"
      head -20 "${out}" | sed 's/^/      /'
      FAILS=$((FAILS + 1))
    else
      echo "    OK: no OOM lines"
    fi
  else
    echo "    (kernel-capture log unavailable for ${node})"
  fi
done

# -------------------------------------------------------------------------
# Phase 3: cilium-agent container memory vs limit
# -------------------------------------------------------------------------
echo
echo "=== Phase 3: cilium-agent memory vs 2Gi limit ==="

# kubectl top: needs metrics-server / kubelet metrics.  Best-effort.
run "  kubectl top pod (cilium)" "${OUTDIR}/cilium-top.txt" \
  kubectl top pod -n kube-system -l k8s-app=cilium --containers --no-headers

# Per cilium-agent pod, exec into the container and read cgroup v2 memory state.
# Talos uses cgroup v2 unified hierarchy; kubelet writes pod cgroups under
# /sys/fs/cgroup/kubepods.slice/kubepods-besteffort.slice/<pod>/<container>/.
# Inside the cilium-agent container, the pod sees its own cgroup as
# /sys/fs/cgroup which makes the path trivially `/sys/fs/cgroup/memory.current`.
mapfile -t CILIUM_PODS < <(kubectl get pod -n kube-system -l k8s-app=cilium \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.nodeName}{"\n"}{end}' 2> /dev/null)

if [ "${#CILIUM_PODS[@]}" -eq 0 ]; then
  echo "  (no cilium pods reachable via kubectl — skipping container-level memory probe)"
fi

CILIUM_LIMIT_BYTES=$((2 * 1024 * 1024 * 1024)) # matches values.yaml resources.limits.memory: 2Gi
for line in "${CILIUM_PODS[@]}"; do
  [ -z "$line" ] && continue
  pod=$(echo "$line" | awk '{print $1}')
  node=$(echo "$line" | awk '{print $2}')
  prefix="${OUTDIR}/cilium-${pod}-${node}"
  echo
  echo "  Pod: ${pod} on ${node}"

  # memory.current — current usage in bytes (cgroup v2)
  current=$(kubectl exec -n kube-system "$pod" -c cilium-agent -- \
    cat /sys/fs/cgroup/memory.current 2> /dev/null | tr -d '\r\n')
  # memory.max — limit in bytes ("max" means unlimited)
  cmax=$(kubectl exec -n kube-system "$pod" -c cilium-agent -- \
    cat /sys/fs/cgroup/memory.max 2> /dev/null | tr -d '\r\n')
  # memory.events — counters for low / high / max / oom / oom_kill
  kubectl exec -n kube-system "$pod" -c cilium-agent -- \
    cat /sys/fs/cgroup/memory.events 2> /dev/null > "${prefix}-memory.events.txt" || true
  # memory.stat — anon / file / kernel / shmem breakdown
  kubectl exec -n kube-system "$pod" -c cilium-agent -- \
    cat /sys/fs/cgroup/memory.stat 2> /dev/null > "${prefix}-memory.stat.txt" || true

  echo "    memory.current = ${current:-?}"
  echo "    memory.max     = ${cmax:-?}"

  if [ -s "${prefix}-memory.events.txt" ]; then
    oom_count=$(awk '/^oom /{print $2}' "${prefix}-memory.events.txt" || echo 0)
    oomkill_count=$(awk '/^oom_kill /{print $2}' "${prefix}-memory.events.txt" || echo 0)
    high_count=$(awk '/^high /{print $2}' "${prefix}-memory.events.txt" || echo 0)
    max_count=$(awk '/^max /{print $2}' "${prefix}-memory.events.txt" || echo 0)
    echo "    memory.events: high=${high_count} max=${max_count} oom=${oom_count} oom_kill=${oomkill_count}"
    if [ "${oomkill_count:-0}" != "0" ]; then
      echo "    FAIL: cilium-agent on ${node} has oom_kill=${oomkill_count}" |
        tee -a "${OUTDIR}/_verdict.txt"
      FAILS=$((FAILS + 1))
    fi
    if [ "${high_count:-0}" != "0" ] || [ "${max_count:-0}" != "0" ]; then
      echo "    WARN: cilium-agent on ${node} hit memory.high/max ceiling" |
        tee -a "${OUTDIR}/_verdict.txt"
      WARNS=$((WARNS + 1))
    fi
  fi

  # Compute % of 2Gi limit (or actual cgroup limit if not "max").
  if [ -n "${current:-}" ] && [[ "$current" =~ ^[0-9]+$ ]]; then
    limit=$CILIUM_LIMIT_BYTES
    if [ -n "${cmax:-}" ] && [[ "$cmax" =~ ^[0-9]+$ ]]; then
      limit=$cmax
    fi
    pct=$(awk -v c="$current" -v l="$limit" 'BEGIN{printf "%.1f", (c/l)*100}')
    echo "    usage = ${pct}% of limit"
    pct_int=$(awk -v p="$pct" 'BEGIN{printf "%d", p}')
    if [ "$pct_int" -ge "$FAIL_THRESHOLD_PCT" ]; then
      echo "    FAIL: ${pct}% >= ${FAIL_THRESHOLD_PCT}% on ${node}" |
        tee -a "${OUTDIR}/_verdict.txt"
      FAILS=$((FAILS + 1))
    elif [ "$pct_int" -ge "$PASS_THRESHOLD_PCT" ]; then
      echo "    WARN: ${pct}% >= ${PASS_THRESHOLD_PCT}% on ${node}" |
        tee -a "${OUTDIR}/_verdict.txt"
      WARNS=$((WARNS + 1))
    fi
  fi

  # Crash/restart history for this pod (would be set by kubelet on OOMKill).
  reason=$(kubectl get pod -n kube-system "$pod" \
    -o jsonpath='{.status.containerStatuses[?(@.name=="cilium-agent")].lastState.terminated.reason}' 2> /dev/null)
  if [ "$reason" = "OOMKilled" ]; then
    echo "    FAIL: lastState.terminated.reason=OOMKilled" |
      tee -a "${OUTDIR}/_verdict.txt"
    FAILS=$((FAILS + 1))
  fi
done

# -------------------------------------------------------------------------
# Phase 4: talos00 top memory consumers (where is the RAM going?)
# -------------------------------------------------------------------------
echo
echo "=== Phase 4: top memory consumers on talos00 ==="
run "  kubectl top pod on talos00 (sorted)" "${OUTDIR}/talos00-pods-by-memory.txt" \
  kubectl top pod --all-namespaces --field-selector spec.nodeName=talos00 \
  --sort-by=memory --no-headers
echo "  (see ${OUTDIR}/talos00-pods-by-memory.txt — top 10)"
head -10 "${OUTDIR}/talos00-pods-by-memory.txt" 2> /dev/null | sed 's/^/    /'

run "  talosctl processes on talos00" "${OUTDIR}/talos00-processes.txt" \
  talosctl ${TALOSCONFIG_FLAG} --nodes 192.168.1.54 processes

# kubelet eviction events for any node
run "  evicted pods (cluster-wide)" "${OUTDIR}/evicted-pods.txt" \
  kubectl get pod -A --field-selector=status.phase=Failed -o wide
if grep -i "evicted" "${OUTDIR}/evicted-pods.txt" > /dev/null 2>&1; then
  echo "    WARN: evicted pods found cluster-wide" | tee -a "${OUTDIR}/_verdict.txt"
  WARNS=$((WARNS + 1))
fi

# Node MemoryPressure conditions
run "  node conditions" "${OUTDIR}/node-conditions.txt" \
  kubectl get nodes -o json
if grep -A1 '"type": "MemoryPressure"' "${OUTDIR}/node-conditions.txt" 2> /dev/null |
  grep -q '"status": "True"'; then
  echo "    FAIL: at least one node has MemoryPressure=True" |
    tee -a "${OUTDIR}/_verdict.txt"
  FAILS=$((FAILS + 1))
fi

# -------------------------------------------------------------------------
# Verdict
# -------------------------------------------------------------------------
echo
echo "=== Verdict ==="
if [ "$FAILS" -gt 0 ]; then
  verdict="FAIL"
elif [ "$WARNS" -gt 0 ]; then
  verdict="WARN"
else
  verdict="PASS"
fi
echo "  Verdict: ${verdict}  (fails=${FAILS} warns=${WARNS})"
echo "  ${verdict}: fails=${FAILS} warns=${WARNS} ts=${TS}" >> "${OUTDIR}/_verdict.txt"
echo
echo "Done.  Evidence: ${OUTDIR}"
echo "End:  $(date -u +%FT%TZ)"

# Exit non-zero on FAIL so this can run in CI / cron and trip an alert.
if [ "$verdict" = "FAIL" ]; then exit 1; fi
exit 0
