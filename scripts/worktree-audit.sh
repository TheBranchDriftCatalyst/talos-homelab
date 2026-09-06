#!/usr/bin/env bash
# Audit agent/workflow worktrees: is each branch's work already merged into main?
# Read-only. Run this BEFORE scripts/worktree-cleanup.sh.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"

n=$(ls -1 .claude/worktrees 2>/dev/null | wc -l | tr -d ' ')
[ "$n" = "0" ] && { echo "no worktrees"; exit 0; }
echo "worktrees: $n   disk: $(du -sh .claude/worktrees | cut -f1)"
echo "(git worktree list shows $((n+1)) rows — the extra one is the main checkout, not a leak)"
echo
printf "%-34s %6s %8s %8s %9s\n" BRANCH FILES MISSING DIFFER VERDICT
rc=0
for wt in .claude/worktrees/*/; do
  b="worktree-$(basename "$wt")"
  base=$(git merge-base main "$b" 2>/dev/null) || continue
  tot=0; missing=0; differ=0
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    tot=$((tot+1))
    if ! git cat-file -e "main:$f" 2>/dev/null; then
      git cat-file -e "$b:$f" 2>/dev/null && missing=$((missing+1))
    else
      # normalise the ESO v1beta1->v1 migration already committed to main
      a=$(git show "$b:$f" | sed 's|external-secrets.io/v1beta1|external-secrets.io/v1|' | shasum -a1 | cut -d' ' -f1)
      c=$(git show "main:$f" | shasum -a1 | cut -d' ' -f1)
      [ "$a" != "$c" ] && differ=$((differ+1))
    fi
  done <<< "$(git diff --name-only "$base" "$b" 2>/dev/null)"
  if [ "$missing" -gt 0 ]; then v="UNIQUE"; rc=1; else v="MERGED"; fi
  printf "%-34s %6s %8s %8s %9s\n" "$(basename "$wt")" "$tot" "$missing" "$differ" "$v"
done
echo
[ $rc -eq 0 ] && echo "✅ all merged — safe for: task dev:worktree:clean" \
              || echo "⚠️  UNIQUE rows have files absent from main — DO NOT clean until reviewed"
exit $rc
