---
name: image-update-implement
description: Work through an image-update beads epic — bump each stale image in the GitOps manifests, verify the real latest, elevate every decision to the operator, annotate tickets with domain-specific gotchas, and maintain a breaking-changes changelog artifact. Use when the user wants to execute/implement an image-update epic created by image-update-epic, apply the version bumps, or roll out the updates.
---

# image-update-implement

Execute an image-update epic (from `image-update-epic`) — one ticket at a time — the GitOps way,
elevating decisions to the operator and leaving a clear breaking-changes changelog behind.

## Golden rule — ELEVATE ALL DECISIONS TO THE OPERATOR

You are an executor, not a decision-maker. The instant a ticket needs a **judgment call**, STOP and
ask the operator with `AskUserQuestion` (offer concrete options + your recommendation). Never decide
these autonomously:

- Any **major** version bump, or one with a **breaking change / migration / changed defaults**.
- A **suspicious "latest"** (build number / date tag / non-semver) — the reported latest may be wrong.
- Anything touching **data, auth, networking, or storage** (DBs/CNPG, authentik, cilium, traefik, ESO).
- An image that appears **pinned on purpose** (a comment says why, or a chart pins it).
- Chart-version bumps that require **values changes**, or where upstream renamed/removed keys.
- Any point where you'd otherwise **guess**.

Record the question AND the operator's answer on the ticket (`bd comment`) and in the changelog.
Trivial, in-kind patch/minor bumps of clearly-semver images with no breaking notes may proceed
without asking — but when unsure, ask. This is the escape hatch: if a task requires a decision you
cannot make safely, elevate it and move on to the next ticket.

## Setup

1. Resolve the epic: take the epic ID from the user, else `bd list --type=epic` for the newest
   "Update out-of-date container images…" epic. `bd update <epic> --status=in_progress`.
2. Create/open the changelog artifact (see below).
3. `bd ready` scoped to the epic's children → the work queue. Do highest priority first
   (major → minor → patch). Confirm with the operator which set to tackle if it's large.

## Per-ticket loop

For each ticket:

1. `bd update <id> --claim`.
2. **Locate the definition:** grep the repo for the image + current tag
   (`grep -rn "<image>" infrastructure applications` and the app's sister repo in `../<repo>` if it's
   ArgoCD-synced from elsewhere — see the workspace layout). A HelmRelease pins a `chart` version, not
   an image tag; a Deployment pins `image:`. Note if it's live-only (no manifest) and elevate.
3. **Verify the REAL latest** — do not trust the report's `latest`:
   `gh release list -R <owner/repo>`, the chart repo index, or the registry tags. Prefer the true
   latest stable (per the prefer-latest-versions preference). If the report's latest was garbage,
   note it and use the real one (or elevate if ambiguous).
4. **Read the breaking changes** — release notes / CHANGELOG / upgrade guide for the span
   current→latest. Summarize what matters for THIS cluster.
5. **Decision gate:** if anything from the Golden Rule applies → `AskUserQuestion`, record the answer.
6. **Apply** the bump (image tag or chart version). Keep it minimal and match surrounding style.
7. **Validate:** `kubectl kustomize <path>` / `flux build` / `--dry-run=server`. Fix or elevate.
8. **GitOps rollout** (never bypass Flux/ArgoCD): commit (conventional, reference the ticket + TALOS
   id), push, reconcile the owning Flux Kustomization (or let ArgoCD sync), then verify the workload
   is healthy and version-checker flips it to up-to-date on the next scrape.
9. **Annotate the ticket** with the domain-specific findings — `bd comment <id>`: the real latest used,
   breaking changes, decisions + who decided, values touched, rollback command. Cross-cutting gotchas
   worth future recall → `bd remember`.
10. **Append to the changelog** (below).
11. `bd close <id>` only after the workload is confirmed healthy on the new version.

## The breaking-changes changelog artifact (required)

Maintain a single markdown artifact per epic: `docs/changelogs/image-updates-<epic-id>.md`.

Structure — keep it clear and skimmable:

```markdown
# Image Updates — <epic-id> (<date range>)
Source report: .output/image-version-report.json

## Summary
- Updated: N images | Elevated to operator: M | Deferred/blocked: K
- Breaking changes encountered: <count>

## Changes
### <image> <current> → <actual-latest>   [TALOS-xxx]
- Namespaces/pods affected: …
- ⚠️ BREAKING: <what broke / changed defaults / required migration> — how it was handled.
- Decision (operator): <question> → <answer>.
- Manifest: <path> · Rollback: <git/kubectl command> · Verified: <how>.
```

Every entry that had a breaking change MUST spell out what broke and the resolution. At the end,
consider publishing the changelog as a shareable Artifact (web page) so the operator has a clean
record. Nothing is "done" until it is committed AND pushed.

## Close-out

Update the epic with a rollup (done / elevated / deferred), ensure the changelog is committed, run
the report script again to confirm the out-of-date count dropped, `bd sync`, and push.
