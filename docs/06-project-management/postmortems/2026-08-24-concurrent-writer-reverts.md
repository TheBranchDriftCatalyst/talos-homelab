# Post-mortem: four silent reverts of the same work in one session

**Date:** 2026-08-24
**Impact:** No outage. ~2 hours lost to recovery — more than the analysis it kept destroying.
**Severity:** Low impact, high signal. Every safeguard we added failed in turn.

---

## TL;DR

One agent's measurement work was reverted **four times**, by **four different commits**,
**all of them mine**. Nothing was lost permanently and the cluster was never degraded. The
mechanism was not a bad git recipe — we fixed the recipe twice and it happened again both
times. The mechanism was **several writers sharing one worktree**.

The fix that worked was **consolidating to a single writer**. Nothing else did.

---

## What actually happened

A subagent measured real memory usage across ~80 workload groups and produced sizing
changes. It committed and pushed correctly each time. Four times, a later commit of mine
silently reverted it.

| # | My commit | Its stated purpose | What it also did |
|---|-----------|--------------------|------------------|
| 1 | `b137b2bc` | unpin cowrie from talos03 | reverted 7 eda0 files |
| 2 | `94a619ad` | unpin media-experimental | reverted the same 7 again |
| 3 | `2f82d0e2` | steer alloy off tight nodes | reverted 3 tdarr/kometa files |
| 4 | `fc7103db` | repel 3 singletons from talos03 | reverted **14** gj3n files |

### The mechanism

`git commit` writes a tree from **HEAD plus your staged changes**. If HEAD is behind
origin, every file you did *not* stage silently reverts to its state at your stale HEAD.

The commit looks perfect. `git show --stat` on commit #1 shows one file. The diff against
origin shows eight. Nothing errors. Nothing warns.

### Why it kept passing our checks

- **File-count gate** — passed every time. The tree stayed a healthy 1631 files. A content
  revert does not change file count.
- **Post-push content check** — passed on attempt #2 and the work was *still* reverted 20
  minutes later. The check is only valid at the instant it runs; the window stays open
  until the next writer pushes.
- **`git pull --rebase` before push** — I ran it. It **errored** with
  `cannot pull with rebase: You have unstaged changes`, I checked `HEAD == origin/main`
  separately, saw a match, and proceeded. The peer's push landed between that check and my
  commit.

Each fix was correct and each was defeated by the next occurrence.

---

## Root cause

**A shared worktree with concurrent writers.** Every agent and the lead operated on the
same checkout. Sizing work touches many files across many components, so any two writers
overlap in time even when they do not overlap in files.

The safeguards all addressed *the symptom in the writer's own commit*. None of them could
see a second writer. This is a **structural** property of the setup, not a discipline
failure — which is why discipline kept failing.

---

## The compounding error: reporting success on false evidence

After revert #4, I reported gj3n as landed, cited "traefik 5/5 and alloy-node 5/5 Running",
and **closed the ticket**.

Both DaemonSets were at full coverage. The reading was real. The conclusion was wrong:
`fc7103db` had reverted traefik's request from 512Mi back to 128Mi, so what fit on talos03
was the **old, smaller** traefik. I had verified the *symptom I wanted* rather than the
*value I had changed*.

The agent caught it. With the real values restored, it did **not** fit — three pods went
Pending and 832Mi more had to be freed before it did.

**This is the most important lesson of the session and it is not about git.**

---

## The pattern behind almost everything

Repeatedly, **the layer reporting success was not the layer that was broken**:

| Reported | Reality |
|----------|---------|
| Flux: `applied revision 94a619ad` ✅ | git no longer contained the change |
| HelmRelease `Ready`, `applied revision 1.11.1` ✅ | a duplicate `controller:` YAML key had silently discarded the affinity |
| minio-operator `Running`, 0 restarts, 11h ✅ | watches died at 21:43; it had stopped reconciling entirely |
| traefik DaemonSet `5/5 ready` ✅ | it fit only because its request had been reverted |
| `kustomize build` exit 0 ✅ | an unsupported chart values key renders clean and moves nothing |

**Rule: when a control loop reports success and the effect is absent, verify the OUTPUT
object, not the controller's status.** Every one of these was caught by reading the live
object and none by reading a status field.

---

## What we changed

**Process**
1. **Single writer for overlapping work.** The only measure with a clean record. Applied by
   the lead carrying the agent's content into its own commits.
2. **In-sync at commit time, in one command** — `git fetch && [ HEAD = origin/main ] || exit 1`
   fused to the `git add && git commit`, leaving no window. Necessary, not sufficient.
3. **Verify the live object, never the commit or the reconcile status.**

**Technical**
- `TALOS-bze9` — minio-operator silent reconcile failure, proposed as a wedge-buster target.
- `TALOS-3zf9` updated with the recurrence: talos03 was freed twice and refilled both times.

---

## The unresolved structural issue

**talos03 attracts exactly the workloads it cannot afford.** It has the **most CPU in the
fleet (15600m)** and the **least memory (12.8Gi allocatable)**. kube-scheduler's default
`BalancedAllocation` scoring favours nodes whose CPU and memory utilisation are *out of
balance* — and a memory-heavy pod is precisely what "corrects" that imbalance.

So the node least able to afford memory keeps winning the memory-hungry singletons. It was
freed twice today — 4032Mi after unpinning media-experimental — and refilled both times.

**Six per-workload repels were needed** (media-experimental, cowrie, kube-state-metrics,
version-checker, mimir-distributor, reflector, posterizarr, clickstack). That is
whack-a-mole and it will recur on the next sizing change.

The systemic fix is a **`PreferNoSchedule` taint on talos03**. Unlike `NoSchedule` it never
blocks scheduling — it only deprioritises — so DaemonSets still land and nothing goes
Pending. **Not applied:** the user explicitly asked that only talos00 carry a taint, so this
is their decision.

---

## What went right

- The subagent **stopped and reported** instead of repairing quietly, every time. Had it
  silently re-committed, we would have had duelling commits and no diagnosis.
- It caught the false "gj3n fits" claim by checking the live spec after a reconcile it had
  been told had succeeded.
- It refused to trim measured values to make them fit, and escalated instead — which is what
  surfaced that talos03 is structurally too small, rather than hiding it in smaller numbers.
- It found two **errors in the ticket itself**: velero is *under*-declared (p50 196Mi, peak
  481Mi vs a 128Mi request) where the ticket said to cut it to 96Mi, and kube-apiserver is
  the largest remaining under-declaration at 2048Mi requested against a **5622Mi p50 /
  8288Mi peak**.

---

## Follow-ups

| Item | Status |
|------|--------|
| `PreferNoSchedule` on talos03 | **awaiting user decision** |
| kube-apiserver sizing (`TALOS-7q34`) — largest remaining under-declaration | open |
| velero: do NOT cut to 96Mi; it needs 256Mi | corrected in `TALOS-gj3n` |
| minio-operator → wedge-buster (`TALOS-bze9`) | open |
| `TALOS-3zf9` rebalance — needs a 14d window, re-check ~2026-08-31 | open |
