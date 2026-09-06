#!/usr/bin/env bash
# Remove all agent/workflow worktrees whose work is already merged into main,
# then delete their branches. Validated by scripts/worktree-audit.sh first.
#
# Branch SHAs are printed before deletion — recover any with: git branch <name> <sha>
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"

echo "== recovery record (recover with: git branch <name> <sha>) =="
git branch --list 'worktree-*' --format='%(objectname:short) %(refname:short)'
echo

n=$(ls -1 .claude/worktrees 2>/dev/null | wc -l | tr -d ' ')
[ "$n" = "0" ] && { echo "no worktrees to clean"; exit 0; }
echo "== removing $n worktrees ($(du -sh .claude/worktrees 2>/dev/null | cut -f1)) =="

ok=0
for wt in .claude/worktrees/*/; do
  git worktree remove --force "$wt" 2>/dev/null && ok=$((ok+1)) || echo "  FAILED: $(basename "$wt")"
done
git worktree prune
echo "worktrees removed: $ok"

d=0
for b in $(git branch --list 'worktree-*' --format='%(refname:short)'); do
  git branch -D "$b" >/dev/null 2>&1 && d=$((d+1)) || echo "  FAILED branch: $b"
done
echo "branches deleted: $d"
echo
echo "== after =="
git worktree list
