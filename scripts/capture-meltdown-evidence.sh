#!/usr/bin/env bash
#
# capture-meltdown-evidence.sh
#
# Collects diagnostic state BEFORE forcing a recovery reboot during a
# control-plane / Cilium meltdown. Filed in response to the 2026-05-27 and
# 2026-05-29 incidents where each `talosctl reboot --mode=force` wiped the
# kernel/BPF/socket state needed to root-cause the failure.
#
# Output goes to .output/incidents/<UTC-timestamp>/ and runs in <90s on a
# healthy cluster, <2min when API is degraded (most commands tolerate failure).
#
# Usage:
#   ./scripts/capture-meltdown-evidence.sh              # capture all reachable nodes
#   ./scripts/capture-meltdown-evidence.sh talos00      # specific node only
#
# Designed to run even when kubectl is fully down — falls back to talosctl
# for every per-node command. kubectl-dependent commands fail-fast and continue.

set -u # NOT -e: we want to keep going even if individual commands fail

TS=$(date -u +%Y%m%dT%H%M%SZ)
OUTDIR="$(git rev-parse --show-toplevel 2> /dev/null || pwd)/.output/incidents/${TS}"
mkdir -p "${OUTDIR}"

TALOSCONFIG_FLAG="--talosconfig $(git rev-parse --show-toplevel 2> /dev/null || pwd)/configs/talosconfig"

NODES=("${@:-talos00 talos01 talos02-gpu talos03 talos06}")
# shellcheck disable=SC2034 # used via indirect lookup ${NODE_IPS[$node]}
declare -A NODE_IPS
NODE_IPS["talos00"]=192.168.1.54
NODE_IPS["talos01"]=192.168.1.177
NODE_IPS["talos02-gpu"]=192.168.1.144
NODE_IPS["talos03"]=192.168.1.30
NODE_IPS["talos06"]=192.168.1.19

echo "📸 Capturing meltdown evidence to ${OUTDIR}"
echo "    Start: $(date -u +%FT%TZ)"
echo

# Detect a working timeout command (Linux ships GNU coreutils `timeout`;
# macOS typically has neither timeout nor gtimeout unless you `brew install
# coreutils`). Fall back to a perl one-liner that uses SIGALRM — perl is
# part of macOS base install and is reliable.
if command -v gtimeout > /dev/null 2>&1; then
  TIMEOUT_CMD="gtimeout 15"
elif command -v timeout > /dev/null 2>&1; then
  TIMEOUT_CMD="timeout 15"
elif command -v perl > /dev/null 2>&1; then
  # perl -e 'alarm shift; exec @ARGV' 15 cmd args...
  TIMEOUT_CMD="perl -e \"alarm shift @ARGV; exec @ARGV\" 15"
else
  TIMEOUT_CMD=""
fi

# Helper: run with timeout, swallow errors but log them
run() {
  local label=$1
  shift
  local out=$1
  shift
  echo "  - ${label}"
  if [ -n "$TIMEOUT_CMD" ]; then
    eval "$TIMEOUT_CMD" "$@" > "${out}" 2>&1 || echo "  ⚠️  ${label} failed (continuing)" >&2
  else
    "$@" > "${out}" 2>&1 || echo "  ⚠️  ${label} failed (continuing)" >&2
  fi
}

# -------------------------------------------------------------------------
# Cluster-level (kubectl) — best-effort, may fail if API is dead
# -------------------------------------------------------------------------
echo "=== Cluster-level ==="
run "kubectl get nodes" "${OUTDIR}/cluster-nodes.txt" kubectl get nodes -o wide
run "kubectl get pods -A wide" "${OUTDIR}/cluster-pods.txt" kubectl get pods -A -o wide
run "events (last)" "${OUTDIR}/cluster-events.txt" kubectl get events -A --sort-by=.lastTimestamp
run "non-running pods" "${OUTDIR}/cluster-pods-broken.txt" kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded -o wide
run "cilium pods" "${OUTDIR}/cilium-pods.txt" kubectl get pods -n kube-system -l k8s-app=cilium -o wide
run "etcd-backup jobs" "${OUTDIR}/etcd-backup-jobs.txt" kubectl get job -n backup --sort-by=.status.startTime
run "webhooks" "${OUTDIR}/webhooks.txt" kubectl get mutatingwebhookconfigurations,validatingwebhookconfigurations -o yaml
run "endpoints all" "${OUTDIR}/endpoints-all.txt" kubectl get endpoints -A
run "kube-system events" "${OUTDIR}/events-kube-system.txt" kubectl get events -n kube-system --sort-by=.lastTimestamp

# Cilium-specific via kubectl exec
for pod in $(kubectl get pod -n kube-system -l k8s-app=cilium -o name 2> /dev/null); do
  podname=${pod##pod/}
  node=$(kubectl get "$pod" -n kube-system -o jsonpath='{.spec.nodeName}' 2> /dev/null)
  prefix="${OUTDIR}/cilium-${podname}-${node}"
  echo "  Cilium pod: ${podname} on ${node}"
  run "  describe" "${prefix}-describe.txt" kubectl describe "$pod" -n kube-system
  run "  logs --previous" "${prefix}-logs-prev.txt" kubectl logs -n kube-system "$podname" --previous
  run "  logs current" "${prefix}-logs.txt" kubectl logs -n kube-system "$podname" --tail=1000
  run "  cilium-dbg status" "${prefix}-dbg-status.txt" kubectl exec -n kube-system "$podname" -- cilium-dbg status --verbose
  run "  cilium-dbg bpf lb" "${prefix}-bpf-lb.txt" kubectl exec -n kube-system "$podname" -- cilium-dbg bpf lb list
  run "  cilium-dbg metrics" "${prefix}-metrics.txt" kubectl exec -n kube-system "$podname" -- cilium-dbg metrics list
  run "  bpftool prog show" "${prefix}-bpf-progs.txt" kubectl exec -n kube-system "$podname" -- bpftool prog show
  run "  bpftool cgroup show" "${prefix}-cgroup-progs.txt" kubectl exec -n kube-system "$podname" -- bpftool cgroup show /sys/fs/cgroup
  run "  ct map count" "${prefix}-ct-count.txt" bash -c "kubectl exec -n kube-system $podname -- cilium-dbg bpf ct list global 2>/dev/null | wc -l"
  run "  ss TIME_WAIT" "${prefix}-timewait.txt" kubectl exec -n kube-system "$podname" -- ss -tan state time-wait
done

# -------------------------------------------------------------------------
# Per-node (talosctl) — most reliable, hostNetwork data
# -------------------------------------------------------------------------
echo
echo "=== Per-node (talosctl) ==="
for node in ${NODES[@]}; do
  ip=${NODE_IPS[$node]:-$node}
  prefix="${OUTDIR}/node-${node}"
  echo
  echo "Node: ${node} (${ip})"

  run "  health" "${prefix}-health.txt" talosctl ${TALOSCONFIG_FLAG} --nodes "$ip" health --wait-timeout 15s
  run "  service status" "${prefix}-services.txt" talosctl ${TALOSCONFIG_FLAG} --nodes "$ip" service
  run "  containers" "${prefix}-containers.txt" talosctl ${TALOSCONFIG_FLAG} --nodes "$ip" containers -k
  run "  dmesg" "${prefix}-dmesg.txt" talosctl ${TALOSCONFIG_FLAG} --nodes "$ip" dmesg
  run "  kubelet logs" "${prefix}-kubelet.txt" talosctl ${TALOSCONFIG_FLAG} --nodes "$ip" logs kubelet
  run "  etcd service" "${prefix}-etcd-service.txt" talosctl ${TALOSCONFIG_FLAG} --nodes "$ip" service etcd
  run "  apid service" "${prefix}-apid-service.txt" talosctl ${TALOSCONFIG_FLAG} --nodes "$ip" service apid

  # Kernel/network sysctls — small but hugely useful
  for path in \
    /proc/net/sockstat \
    /proc/net/sockstat6 \
    /proc/net/stat/nf_conntrack \
    /proc/sys/net/netfilter/nf_conntrack_count \
    /proc/sys/net/netfilter/nf_conntrack_max \
    /proc/sys/net/ipv4/ip_local_port_range \
    /proc/sys/net/ipv4/tcp_max_tw_buckets \
    /proc/sys/net/ipv4/tcp_tw_reuse \
    /proc/sys/fs/file-nr \
    /proc/sys/fs/file-max \
    /proc/sys/kernel/pid_max \
    /proc/sys/vm/max_map_count; do
    fname=$(echo "$path" | tr '/' '_')
    run "  read ${path}" "${prefix}-proc${fname}.txt" talosctl ${TALOSCONFIG_FLAG} --nodes "$ip" read "$path"
  done

  # Memory pressure on host
  run "  meminfo" "${prefix}-meminfo.txt" talosctl ${TALOSCONFIG_FLAG} --nodes "$ip" read /proc/meminfo
  run "  loadavg" "${prefix}-loadavg.txt" talosctl ${TALOSCONFIG_FLAG} --nodes "$ip" read /proc/loadavg
  run "  vmstat" "${prefix}-vmstat.txt" talosctl ${TALOSCONFIG_FLAG} --nodes "$ip" read /proc/vmstat
done

# Control-plane only: extra etcd + apiserver focus
echo
echo "=== Control-plane only (talos00) ==="
run "talos00 etcd status" "${OUTDIR}/cp-etcd-status.txt" talosctl ${TALOSCONFIG_FLAG} --nodes 192.168.1.54 etcd status
run "talos00 etcd members" "${OUTDIR}/cp-etcd-members.txt" talosctl ${TALOSCONFIG_FLAG} --nodes 192.168.1.54 etcd members
run "talos00 etcd alarm list" "${OUTDIR}/cp-etcd-alarms.txt" talosctl ${TALOSCONFIG_FLAG} --nodes 192.168.1.54 etcd alarm list

# Grab kube-apiserver and controller-manager logs by container ID (latest only)
# The talosctl containers row has a tree-drawing "└─" prefix for sub-containers,
# making column $3 the prefix. The container path is column $4.
# Example row:
#   192.168.1.54  k8s.io  └─ kube-system/kube-apiserver-talos00:kube-apiserver:25f26  registry.k8s.io/...  PID  CONTAINER_RUNNING
for container in kube-apiserver kube-controller-manager kube-scheduler; do
  cid=$(talosctl ${TALOSCONFIG_FLAG} --nodes 192.168.1.54 containers -k 2> /dev/null |
    grep "kube-system/${container}-talos00:${container}" |
    grep -v EXITED | awk '{print $4}' | head -1)
  if [ -n "$cid" ]; then
    run "talos00 ${container} logs" "${OUTDIR}/cp-${container}.txt" talosctl ${TALOSCONFIG_FLAG} --nodes 192.168.1.54 logs -k "$cid"
  fi
done

# -------------------------------------------------------------------------
# Summary
# -------------------------------------------------------------------------
echo
echo "✅ Capture complete: ${OUTDIR}"
echo "    Files: $(find "${OUTDIR}" -type f | wc -l)"
echo "    Size:  $(du -sh "${OUTDIR}" | awk '{print $1}')"
echo "    End:   $(date -u +%FT%TZ)"
echo
echo "Next steps:"
echo "  1. Inspect: ls ${OUTDIR}"
echo "  2. Tar for sharing: tar czf incident-${TS}.tar.gz -C $(dirname "${OUTDIR}") $(basename "${OUTDIR}")"
echo "  3. If recovering, run: talosctl ${TALOSCONFIG_FLAG} --nodes <ip> reboot --mode=force --wait"
