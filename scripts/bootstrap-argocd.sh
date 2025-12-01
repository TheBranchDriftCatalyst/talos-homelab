#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  Bootstrap ArgoCD - Wrapper Script                                           ║
# ║  Redirects to infrastructure/base/_scripts/bootstrap-argocd.sh               ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/../infrastructure/base/_scripts/bootstrap-argocd.sh" "$@"
