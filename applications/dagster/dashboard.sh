#!/usr/bin/env bash
# Dagster Platform Dashboard
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [[ "${1:-}" == "--full" ]] || [[ "${1:-}" == "-f" ]]; then
  exec "${PROJECT_ROOT}/scripts/namespace-dashboard.sh" dagster
fi

exec "${PROJECT_ROOT}/scripts/namespace-dashboard.sh" dagster "$@"
