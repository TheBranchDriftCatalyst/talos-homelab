#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  Bootstrap Talos kubelet machine-config patches — SUPERSEDED, REFUSES TO RUN ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
#
# This script applied five kubelet patches to all five nodes with `talosctl patch mc`:
# iSCSI extraMounts, the local-path extraMount, maxPods, memory reserves, and image GC.
#
# It is superseded. Every one of those values is now DECLARED in configs/talconfig.yaml
# and applied by talhelper (TALOS-ow7w):
#
#   configs/patches/all-kubelet-baseline.yaml   the three bind mounts, systemReserved /
#                                               kubeReserved / evictionHard, imageMaximumGCAge
#   configs/patches/maxpods-200.yaml            maxPods 200, every node except talos03
#   configs/patches/talos03-maxpods.yaml        talos03 is deliberately 60, not 200
#
# Running both mechanisms is how the config drift got bad enough to need this migration in
# the first place. The repo's own migration notes record talos02-gpu and talos06 carrying SIX
# extraMounts — each of the three declared twice — from the iscsi and local-path patches
# having been applied more than once. (Those nodes read clean now; the point is that the
# imperative path could produce that state and the declarative one cannot.)
#
# IT WAS ALSO ALREADY BROKEN, for an unrelated reason and for some time. The third PATCHES
# entry packed three filenames into one space-separated string:
#
#   "${REPO_ROOT}/docs/05-runbooks/talos-kubelet-maxpods-patch.yaml talos-kubelet-memory-reserve-patch.yaml talos-kubelet-image-gc-patch.yaml|maxPods ..."
#
# but the loop read `${entry%%|*}` as a single path. That path never existed, so the preflight
# hit `ERROR: missing patch file` and exited 1 before contacting a node — in --check mode too.
# Nothing this script claimed to do had been happening. Worth knowing if you are reading a
# node's config and wondering why the memory-reserve and image-GC values look unpinned in the
# history: they were applied by hand, not by this.
#
# The header used to claim "re-running is safe: talosctl patch mc merges, so this is
# idempotent". Do not carry that assumption forward. Merge behaviour for list-valued fields
# like extraMounts is not obviously append-free, and duplicated mounts are exactly what was
# found on two nodes.
#
# WHAT TO DO INSTEAD
#
#   task talos:verify-dry-run             ask each node what applying the generated config
#                                         would actually do — read-only, safe any time
#   task talos:verify                     regenerate and diff against every live node
#   task talos:apply-config NODE=talos03  apply one node's generated config (destructive)
#
# If you need a genuinely one-off hand patch during an incident, run talosctl directly and
# then put the change in configs/talconfig.yaml, or the next apply-config silently reverts it.
# The previous working-ish implementation is in git history if you need to read it.

set -euo pipefail

cat >&2 <<'MSG'
==========================================================================
  bootstrap-talos-patches.sh is SUPERSEDED and will not run.
==========================================================================

  The kubelet patches it applied are now declared in configs/talconfig.yaml
  and applied by talhelper:

    configs/patches/all-kubelet-baseline.yaml   bind mounts, reserves, image GC
    configs/patches/maxpods-200.yaml            maxPods 200 (all but talos03)
    configs/patches/talos03-maxpods.yaml        talos03 stays at 60

  Applying them imperatively as well is what produced the config drift this
  cluster migrated to talhelper to stop. It had also been aborting on a
  malformed patch path for some time, so it was not doing this anyway.

  Use instead:

    task talos:verify-dry-run              what applying would do (read-only)
    task talos:verify                      diff generated vs live, all nodes
    task talos:apply-config NODE=<host>    apply one node (destructive)

  See the header of this file for the full story.

==========================================================================
MSG
exit 1
