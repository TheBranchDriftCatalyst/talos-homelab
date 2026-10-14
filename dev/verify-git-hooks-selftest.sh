#!/usr/bin/env bash
# Prove dev/verify-git-hooks.sh can FAIL. Each case mutates a THROWAWAY COPY of
# the real hooks (never the real ones) to reproduce one way `lefthook install`
# has actually broken them, and asserts the verifier goes red. Without this, an
# all-clear from the verifier means nothing -- see the no-tautological-tests rule.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
REAL="$(git rev-parse --git-path hooks)"
pass=0
failed=0
run_case() {
  local name="$1" expect="$2"
  shift 2
  local tmp
  tmp="$(mktemp -d)"
  cp -R "$REAL/." "$tmp/"
  "$@" "$tmp"
  HOOKS_DIR="$tmp" ./dev/verify-git-hooks.sh > /dev/null 2>&1
  local rc=$?
  rm -rf "$tmp"
  if [ "$rc" -eq "$expect" ]; then
    printf '  PASS  %s (exit %s)\n' "$name" "$rc"
    pass=$((pass + 1))
  else
    printf '  FAIL  %s (exit %s, wanted %s)\n' "$name" "$rc" "$expect"
    failed=$((failed + 1))
  fi
}
m_noop() { :; }
m_strip_beads() {
  sed -i.bak "/BEGIN BEADS INTEGRATION/,/END BEADS INTEGRATION/d" "$1/pre-commit"
  rm -f "$1"/*.bak
}
m_strip_exit() {
  sed -i.bak "/^exit \${_lefthook_exit/d" "$1/pre-push"
  rm -f "$1"/*.bak
}
m_break_wrap() { printf '\necho "trailing junk"\n' >> "$1/commit-msg"; }
m_no_lefthook() {
  sed -i.bak "/call_lefthook/d" "$1/pre-commit"
  rm -f "$1"/*.bak
}
m_not_exec() { chmod -x "$1/pre-commit"; }
m_missing() { rm -f "$1/pre-commit"; }

echo "verify-git-hooks selftest"
# Control: the UNMUTATED hooks must PASS. Without this half, a verifier that
# failed on everything would also satisfy every negative case below.
run_case "control: real hooks pass" 0 m_noop
run_case "pre-commit loses the beads block" 1 m_strip_beads
run_case "pre-push loses exit propagation" 1 m_strip_exit
run_case "commit-msg no longer ends in lefthook" 1 m_break_wrap
run_case "pre-commit loses call_lefthook" 1 m_no_lefthook
run_case "pre-commit not executable" 1 m_not_exec
run_case "pre-commit missing entirely" 1 m_missing
echo "  ---"
printf '  %s passed, %s failed\n' "$pass" "$failed"
[ "$failed" -eq 0 ] || exit 1
