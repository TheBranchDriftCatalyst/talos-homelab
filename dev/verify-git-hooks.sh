#!/usr/bin/env bash
# Verify the git hooks still carry what makes them work.
#
# WHY THIS EXISTS (TALOS-chgk): running `lefthook install` in this repo SILENTLY
# DELETED 151 lines across 5 tracked hooks. lefthook rewrites each hook from its
# own template, and these hooks are hand-authored composites of three parts:
#
#   1. the lefthook wrapper (call_lefthook)
#   2. a "BEGIN BEADS INTEGRATION" block that syncs the issue tracker
#   3. for a hook with lefthook jobs, an explicit `exit ${_lefthook_exit}` after (2)
#
# (3) is load-bearing and the easiest to lose. The beads block runs after
# lefthook and exits 0 for its own reasons (timeout, uninitialised db), so
# without the explicit propagation the status of the trailing `fi` becomes the
# hook's exit code, lefthook's verdict is discarded, and the repo reads as
# linted while nothing is enforced.
#
# The propagation requirement is JOB-AWARE, not blanket: it applies to a hook
# only when lefthook.yaml actually defines jobs for it. post-checkout and
# post-merge cannot block anything -- git ignores their exit status -- and carry
# no jobs, so demanding it there would be noise that trains people to ignore
# this script. The case worth catching is someone adding a job to a hook that
# has no propagation, because the symptom is a green gate enforcing nothing.
set -uo pipefail

# HOOKS_DIR is overridable so the selftest can point this at a mutated COPY and
# prove each branch actually fails. A check nobody has seen go red is a check
# nobody should trust.
HOOKS_DIR="${HOOKS_DIR:-$(git rev-parse --git-path hooks)}"
LEFTHOOK_CFG="${LEFTHOOK_CFG:-lefthook.yaml}"
fail=0
note() { printf '  %-22s %s\n' "$1" "$2"; }
bad() {
  fail=1
  printf '  %-22s FAIL  %s\n' "$1" "$2"
}

# Hook names sit at COLUMN 0 in lefthook.yaml ("pre-commit:", not "  pre-commit:").
# Getting this wrong is not a cosmetic bug: it makes has_jobs answer "no" for
# every hook, which disables the propagation check entirely and leaves this
# script reporting all-clear while the thing it guards is broken. That is
# exactly how the pre-push gap (gitleaks-push-range among them) went unnoticed.
has_jobs() { grep -qE "^$1:" "$LEFTHOOK_CFG" 2> /dev/null; }

ALL_HOOKS="commit-msg post-checkout post-merge pre-commit pre-push prepare-commit-msg"

echo "verifying hooks in $HOOKS_DIR"

if [ -z "$(git config core.hooksPath || true)" ]; then
  bad "core.hooksPath" "unset -- git will ignore $HOOKS_DIR entirely"
else
  note "core.hooksPath" "$(git config core.hooksPath)"
fi

for h in $ALL_HOOKS; do
  f="$HOOKS_DIR/$h"
  if [ ! -f "$f" ]; then
    bad "$h" "missing"
    continue
  fi
  [ -x "$f" ] || bad "$h" "not executable"
  grep -q 'call_lefthook' "$f" || bad "$h" "no call_lefthook -- lefthook will never run"

  has_beads=0
  if grep -q 'BEGIN BEADS INTEGRATION' "$f"; then
    has_beads=1
    grep -q 'END BEADS INTEGRATION' "$f" || bad "$h" "BEADS INTEGRATION block is truncated"
  fi

  jobs=no
  has_jobs "$h" && jobs=yes
  # Can this hook block anything? git IGNORES the exit status of post-* hooks, so
  # propagation there is unreachable by construction -- a job that "fails" in
  # post-merge cannot stop anything no matter what the hook returns. Requiring it
  # would be a permanently-red check, which is worse than no check: it trains
  # people to ignore this script, and then the pre-push case hides in the noise.
  blocking=yes
  case "$h" in post-*) blocking=no ;; esac
  last="$(grep -vE '^[[:space:]]*(#|$)' "$f" | tail -1)"

  if [ "$has_beads" -eq 1 ]; then
    if grep -q '_lefthook_exit=\$?' "$f" && [ "${last#exit }" != "$last" ]; then
      note "$h" "ok (beads + explicit propagation; lefthook jobs: $jobs)"
    elif [ "$blocking" = no ]; then
      note "$h" "ok (beads; post-* hook -- git ignores exit status, propagation N/A)"
    elif [ "$jobs" = yes ]; then
      bad "$h" "has lefthook jobs AND a beads block but no exit propagation -- verdict DISCARDED"
    else
      note "$h" "ok (beads, no propagation; lefthook jobs: none -- nothing to mask)"
    fi
  else
    case "$last" in
      *call_lefthook*) note "$h" "ok (bare wrapper; implicit propagation)" ;;
      *) bad "$h" "bare wrapper but last statement is '$last' -- status not propagated" ;;
    esac
  fi
done

if [ "$fail" -ne 0 ]; then
  cat >&2 << 'MSG'

Hook integrity check FAILED.

Most likely cause: something ran `lefthook install`, which rewrites each hook
from lefthook's own template and cannot reproduce the beads block or the exit
propagation. `lefthook run` ALSO installs implicitly unless given
--no-auto-install.

Recover with:
    git checkout -- .beads/hooks

Do NOT re-run `lefthook install` to "fix" it -- that is what broke it.
MSG
  exit 1
fi
echo "all hooks intact"
