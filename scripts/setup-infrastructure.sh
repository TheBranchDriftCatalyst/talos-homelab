#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  Setup Infrastructure - Wrapper Script                                       ║
# ║  Redirects to infrastructure/base/_scripts/setup-traefik.sh                  ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/../infrastructure/base/_scripts/setup-traefik.sh" "$@"
