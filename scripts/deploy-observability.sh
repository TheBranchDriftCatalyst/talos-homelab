#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  Deploy Observability - Wrapper Script                                       ║
# ║  Redirects to infrastructure/base/_scripts/deploy-observability.sh           ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/../infrastructure/base/_scripts/deploy-observability.sh" "$@"
