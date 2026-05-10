#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  Bootstrap Talos kubelet machine-config patches                              ║
# ║                                                                              ║
# ║  Applies the kubelet extraMounts patches required for:                       ║
# ║    - iSCSI / Democratic-CSI       (/etc/iscsi, /var/lib/iscsi)               ║
# ║    - local-path-provisioner       (/var/lib/rancher)                         ║
# ║                                                                              ║
# ║  Run this once after every fresh Talos install / cluster bootstrap.          ║
# ║  Re-running is safe: `talosctl patch mc` merges, so this is idempotent.      ║
# ║                                                                              ║
# ║  Usage:                                                                      ║
# ║    ./scripts/bootstrap-talos-patches.sh             # apply patches          ║
# ║    ./scripts/bootstrap-talos-patches.sh --check     # dry-run, no changes    ║
# ║    ./scripts/bootstrap-talos-patches.sh -h | --help # this help              ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

set -euo pipefail

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

TALOSCONFIG="${TALOSCONFIG:-${REPO_ROOT}/configs/talosconfig}"
TALOS_ENDPOINT="${TALOS_ENDPOINT:-192.168.1.54}"

# Cluster nodes (IP  short-name)
NODES=(
  "192.168.1.54     talos00 (control-plane)"
  "192.168.1.177    talos01 (worker)"
  "192.168.1.144    talos02-gpu (worker)"
  "192.168.1.30     talos03 (worker)"
  "192.168.1.19     talos06 (worker)"
)

# Patch files (path  human-readable label)
PATCHES=(
  "${REPO_ROOT}/docs/05-runbooks/talos-kubelet-iscsi-patch.yaml|iSCSI / Democratic-CSI extraMounts"
  "${REPO_ROOT}/docs/05-runbooks/talos-kubelet-localpath-patch.yaml|local-path-provisioner extraMount"
)

DRY_RUN=false

# ──────────────────────────────────────────────────────────────────────────────
# Args
# ──────────────────────────────────────────────────────────────────────────────
for arg in "$@"; do
  case "$arg" in
    --check | --dry-run | -n)
      DRY_RUN=true
      ;;
    -h | --help)
      sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      echo "Try --help" >&2
      exit 2
      ;;
  esac
done

# ──────────────────────────────────────────────────────────────────────────────
# Pre-flight checks
# ──────────────────────────────────────────────────────────────────────────────
echo "=========================================================================="
echo "  Talos kubelet machine-config patch bootstrap"
echo "=========================================================================="
echo "  Mode:         $($DRY_RUN && echo 'DRY-RUN (--check)' || echo 'APPLY')"
echo "  Endpoint:     ${TALOS_ENDPOINT}"
echo "  Talosconfig:  ${TALOSCONFIG}"
echo "=========================================================================="
echo ""

if ! command -v talosctl > /dev/null 2>&1; then
  echo "ERROR: talosctl not found in PATH" >&2
  exit 1
fi

if [[ ! -f "${TALOSCONFIG}" ]]; then
  echo "WARNING: talosconfig not found at ${TALOSCONFIG}" >&2
  echo "         Set TALOSCONFIG=/path/to/talosconfig or run 'task talos:gen-config' first." >&2
  if ! $DRY_RUN; then
    echo "         Refusing to apply patches without a talosconfig." >&2
    exit 1
  fi
fi

# Verify all patch files exist
missing_patch=false
for entry in "${PATCHES[@]}"; do
  patch_file="${entry%%|*}"
  patch_label="${entry##*|}"
  if [[ ! -f "${patch_file}" ]]; then
    echo "ERROR: missing patch file: ${patch_file} (${patch_label})" >&2
    missing_patch=true
  fi
done
$missing_patch && exit 1

# ──────────────────────────────────────────────────────────────────────────────
# Plan summary
# ──────────────────────────────────────────────────────────────────────────────
echo "Patches to apply:"
for entry in "${PATCHES[@]}"; do
  patch_file="${entry%%|*}"
  patch_label="${entry##*|}"
  echo "  - ${patch_label}"
  echo "    ${patch_file}"
done
echo ""

echo "Target nodes:"
for n in "${NODES[@]}"; do
  echo "  - ${n}"
done
echo ""

if $DRY_RUN; then
  echo "[DRY-RUN] No changes will be made. Re-run without --check to apply."
  echo ""
  for n in "${NODES[@]}"; do
    node_ip="$(echo "$n" | awk '{print $1}')"
    for entry in "${PATCHES[@]}"; do
      patch_file="${entry%%|*}"
      echo "[DRY-RUN] would run: talosctl --talosconfig ${TALOSCONFIG} -e ${TALOS_ENDPOINT} -n ${node_ip} patch mc --patch @${patch_file}"
    done
  done
  exit 0
fi

# ──────────────────────────────────────────────────────────────────────────────
# Apply patches
# ──────────────────────────────────────────────────────────────────────────────
declare -a FAILURES=()
total=0
ok=0

for n in "${NODES[@]}"; do
  node_ip="$(echo "$n" | awk '{print $1}')"
  node_label="$(echo "$n" | awk '{$1=""; print substr($0,2)}')"
  echo "--------------------------------------------------------------------------"
  echo "Node: ${node_ip}  (${node_label})"
  echo "--------------------------------------------------------------------------"

  for entry in "${PATCHES[@]}"; do
    patch_file="${entry%%|*}"
    patch_label="${entry##*|}"
    total=$((total + 1))

    echo "  -> ${patch_label}"
    if talosctl --talosconfig "${TALOSCONFIG}" -e "${TALOS_ENDPOINT}" -n "${node_ip}" \
      patch mc --patch "@${patch_file}"; then
      echo "     OK"
      ok=$((ok + 1))
    else
      rc=$?
      echo "     FAILED (exit=${rc})"
      FAILURES+=("${node_ip} :: ${patch_label}")
    fi
  done
  echo ""
done

# ──────────────────────────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────────────────────────
echo "=========================================================================="
echo "  Summary: ${ok}/${total} patches applied successfully"
echo "=========================================================================="

if ((${#FAILURES[@]} > 0)); then
  echo "Failures:"
  for f in "${FAILURES[@]}"; do
    echo "  - ${f}"
  done
  exit 1
fi

echo ""
echo "All kubelet patches applied. Note: talosctl may have reported"
echo "'no changes' for nodes that already had the patches (idempotent merge)."
echo ""
echo "Next steps:"
echo "  1. talosctl --talosconfig ${TALOSCONFIG} -n <ip> service kubelet status"
echo "  2. kubectl get nodes -o wide"
exit 0
