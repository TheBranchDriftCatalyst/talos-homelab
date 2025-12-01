#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  Deploy Stack - Wrapper Script                                               ║
# ║  Redirects to infrastructure/base/_scripts/deploy-stack.sh                   ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
#
# This is a compatibility wrapper. The actual script lives at:
#   infrastructure/base/_scripts/deploy-stack.sh
#
# You can call either location - they are equivalent.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/../infrastructure/base/_scripts/deploy-stack.sh" "$@"
