#!/usr/bin/env bash
# ARR Stack Dashboard - Passthrough to generic namespace dashboard
#
# This is a convenience wrapper that calls the generic namespace dashboard
# with the media namespace and arr-stack specific options.
#
# For the full-featured dashboard with gum styling and full credentials:
#   ./scripts/namespace-dashboard.sh media
#
# Usage:
#   ./dashboard.sh              # Quick overview (inline credentials)
#   ./dashboard.sh --full       # Full dashboard via namespace-dashboard.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Check for --full flag to use the gum-based dashboard
if [[ "${1:-}" == "--full" ]] || [[ "${1:-}" == "-f" ]]; then
  exec "${PROJECT_ROOT}/scripts/namespace-dashboard.sh" media
fi

# Default: use the generic dashboard
exec "${PROJECT_ROOT}/scripts/namespace-dashboard.sh" media "$@"
