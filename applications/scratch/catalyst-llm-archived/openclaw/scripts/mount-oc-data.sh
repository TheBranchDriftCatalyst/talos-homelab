#!/usr/bin/env bash
# Mount/unmount OpenClaw data directory from NFS
#
# Usage:
#   ./mount-oc-data.sh          # Mount
#   ./mount-oc-data.sh mount    # Mount
#   ./mount-oc-data.sh unmount  # Unmount
#   ./mount-oc-data.sh status   # Check mount status

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOUNT_POINT="${SCRIPT_DIR}/../openclaw-data"
NFS_SERVER="192.168.1.36"
NFS_PATH="/volume1/appdata/home-automation/openclaw-data"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info() { echo -e "${GREEN}[INFO]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

check_mount() {
  if mount | grep -q "${MOUNT_POINT}"; then
    return 0
  fi
  return 1
}

do_mount() {
  if check_mount; then
    info "Already mounted at ${MOUNT_POINT}"
    return 0
  fi

  info "Creating mount point: ${MOUNT_POINT}"
  mkdir -p "${MOUNT_POINT}"

  info "Mounting ${NFS_SERVER}:${NFS_PATH}"
  info "  -> ${MOUNT_POINT}"

  if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS mount options
    sudo mount -t nfs -o vers=4.1,resvport,rw,nolock "${NFS_SERVER}:${NFS_PATH}" "${MOUNT_POINT}"
  else
    # Linux mount options
    sudo mount -t nfs4 -o rw,nolock "${NFS_SERVER}:${NFS_PATH}" "${MOUNT_POINT}"
  fi

  if check_mount; then
    info "Successfully mounted!"
    echo ""
    info "OpenClaw data directory contents:"
    ls -la "${MOUNT_POINT}" 2> /dev/null || true
  else
    error "Mount failed"
    return 1
  fi
}

do_unmount() {
  if ! check_mount; then
    warn "Not currently mounted at ${MOUNT_POINT}"
    return 0
  fi

  info "Unmounting ${MOUNT_POINT}"

  if [[ "$OSTYPE" == "darwin"* ]]; then
    sudo umount "${MOUNT_POINT}"
  else
    sudo umount "${MOUNT_POINT}"
  fi

  if ! check_mount; then
    info "Successfully unmounted!"
    # Optionally remove empty mount point
    rmdir "${MOUNT_POINT}" 2> /dev/null || true
  else
    error "Unmount failed"
    return 1
  fi
}

do_status() {
  echo "NFS Server:  ${NFS_SERVER}"
  echo "NFS Path:    ${NFS_PATH}"
  echo "Mount Point: ${MOUNT_POINT}"
  echo ""

  if check_mount; then
    info "Status: MOUNTED"
    echo ""
    df -h "${MOUNT_POINT}" 2> /dev/null || true
  else
    warn "Status: NOT MOUNTED"
  fi
}

show_help() {
  cat << EOF
OpenClaw NFS Data Mount Script

Usage: $(basename "$0") [command]

Commands:
  mount     Mount the NFS share (default)
  unmount   Unmount the NFS share
  status    Show current mount status
  help      Show this help message

Mount Point: ${MOUNT_POINT}
NFS Source:  ${NFS_SERVER}:${NFS_PATH}

After mounting, you can:
  - Open in VSCode:   code ${MOUNT_POINT}
  - Open in Obsidian: Create vault at ${MOUNT_POINT}/workspace
EOF
}

# Main
case "${1:-mount}" in
  mount)
    do_mount
    ;;
  unmount | umount)
    do_unmount
    ;;
  status)
    do_status
    ;;
  help | --help | -h)
    show_help
    ;;
  *)
    error "Unknown command: $1"
    show_help
    exit 1
    ;;
esac
