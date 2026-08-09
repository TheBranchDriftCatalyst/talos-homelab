---
name: image-update-implement
description: Execute an image-update beads epic across many packages (often 15+, mostly majors) in a tracked, GitOps way. Aggregate ALL the operator decisions up front via one research pass + a batched decision-set, then bump each stale image/chart in the manifests, verify the real latest, roll out through Flux/ArgoCD, annotate tickets, and maintain a breaking-changes changelog. Use when the user wants to execute/implement an image-update epic created by image-update-epic, apply the version bumps, or roll out the updates.
---

# image-update-implement

Execute an image-update epic (from `image-update-epic`) — the GitOps way — across many packages in a
**tracked** manner. The epic is usually large (10–60 bumps, heavy on majors). The winning shape is to
**aggregate the decisions UP FRONT**: one research pass builds a decision matrix, the operator
approves in a few batched prompts, then you execute the approved set one ticket at a time and leave a
clear breaking-changes changelog behind. Do **not** elevate one-ticket-at-a-time — for a major-heavy
epic that blocks the operator over and over.

## Golden rule — ELEVATE ALL DECISIONS TO THE OPERATOR

You are an executor, not a decision-maker. Never decide these autonomously — they go in the batched
decision-set (Phase 1):

- Any **major** version bump, or one with a **breaking change / migration / changed defaults**.
- A **suspicious "latest"** (build number / date tag / non-semver, or a value that is *lower* than
  current) — version-checker mis-parses, so the reported latest is often wrong (a downgrade).
- Anything touching **data, auth, networking, or storage** (DBs/CNPG, authentik, cilium, traefik, ESO).
- An image that appears **pinned on purpose** (a comment says why, or a chart pins it).
- **Chart-version bumps that require values changes** or where upstream renamed/removed keys — and
  note a *minor app* bump can hide a *major chart* jump (see kinks).
- Any point where you'd otherwise **guess**.

Record every question AND the operator's answer on the ticket (`bd comment`) and in the changelog.
Trivial, in-kind patch/minor bumps of clearly-semver images with no breaking notes and no
values-surface may proceed without asking — but for a major-heavy epic, expect *few* of these, and
still surface them as a single "apply this safe batch?" confirmation rather than silently applying.

## Phase 0 — Survey & research (build the decision matrix)

1. Resolve the epic: epic ID from the user, else `bd list --type=epic` for the newest
   "Update out-of-date container images…" epic. `bd update <epic> --status=in_progress`.
2. Open/refresh the changelog artifact (below).
3. `bd ready` scoped to the epic's children → the full ready set.
4. **Do ONE research pass over the whole ready set** — for a big/major-heavy queue, dispatch a
   RESEARCH-ONLY subagent (no edits, no cluster changes) so it runs in parallel while you prep. For
   EACH bump (or coordinated group) it produces a matrix row:

   `image · current · REAL latest (verified) · where defined (manifest path / "chart X.Y" / "chart-internal") · chart-version delta · risk (low/med/high) · breaking-changes one-liner · recommendation · coordinated-with`

   Verify the REAL latest yourself — `gh release list -R <owner/repo>`, the chart repo `index.yaml`,
   or registry tags — never trust the report's `latest`.

### Research kinks to bake in (learned the hard way)

- **Chart delta ≠ app delta.** A HelmRelease pins a *chart* version, not an image tag; a minor *app*
  bump can be a *major chart* jump. E.g. kube-state-metrics app 2.14→2.19.1 is chart **5.27 → 8.2**
  (three major chart versions) — near-certain values-schema churn. Always compute the CHART delta and
  treat a major chart jump as a values-migration decision, even if the app version looks minor.
- **Coordinated groups move together** as ONE decision and ONE commit — bumping one alone breaks the
  set. Known groups here: cilium + cilium-operator + hubble-relay (all driven by the cilium
  HelmRelease chart version), minio operator + operator-sidecar, kubevirt cdi-operator +
  cdi-uploadproxy. Identify these in the matrix and elevate/execute them as a unit.
- **Bad reported "latest" = downgrade.** version-checker mis-parses non-semver/date/build tags into
  a *lower* version (seen: socat `1.8.0.0 → 1.0.5`, opensearch-operator `3.0.0-alpha → 2.8.0`). If
  the "latest" is lower or a shape-change from current, find the true latest; park/skip it, never
  bump to a downgrade. (These are the `verify-latest`-labelled tickets from the epic.)
- **Chart-internal images have no editable manifest** — e.g. `cert-manager-package-debian` is pulled
  by the cert-manager chart. If `grep` finds no manifest, it's set by a parent chart: bump the parent
  chart (a separate decision) or mark it not-directly-bumpable and close/park with a note.
- **Infra blast radius trumps semver.** CNI (cilium), GitOps controllers (argocd/flux), ingress
  (traefik), and storage/observability backends (minio, mimir, tempo) are high-risk regardless of the
  bump size — and this cluster has prior cilium-meltdown history. Rank these last and give them their
  own decision.

## Phase 1 — Batch elevation (aggregate decisions up front)

Present the matrix and get decisions in as FEW round-trips as possible:

- Group into a small number of `AskUserQuestion` prompts — e.g. one covering the high-risk majors
  (each option carrying your per-item recommendation: bump-as-is / bump-to-different-version /
  needs-values-migration / defer / skip-bad-latest), and one "apply this safe batch?" confirmation
  for any genuinely trivial ones. Don't fire a separate prompt per ticket.
- Capture each answer onto its ticket (`bd comment`) and into the changelog's decision column.
- Build the **execution order** from the approved set: independent/low-risk first, coordinated groups
  as a unit, highest-blast-radius (CNI / GitOps controller / storage) last. Record the plan on the
  epic. Park the deferred/bad-latest ones (`bd update … --status` or a note) so the queue reflects
  reality.

## Phase 2 — Execute (per-ticket loop, approved set only)

For each approved ticket (or coordinated group — one commit for the whole group):

1. `bd update <id> --claim`.
2. **Locate the definition** (already in the matrix): HelmRelease `chart.version` vs Deployment
   `image:`; the app's sister repo in `../<repo>` if ArgoCD-synced from elsewhere.
3. **Apply** the bump — chart version or image tag; for a coordinated group bump all members
   together. Keep it minimal and match surrounding style. Apply any values migration the decision
   called for.
4. **Validate:** `kubectl kustomize <path>` / `flux build` / `--dry-run=server`. For a chart bump with
   a values surface, `helm template`/`flux build` and diff that the custom values still land. Fix or
   re-elevate.
5. **GitOps rollout** (never bypass Flux/ArgoCD): commit (conventional, reference the ticket + TALOS
   id), push, reconcile the owning Flux Kustomization (or let ArgoCD sync), then verify the workload
   is healthy and version-checker flips it to up-to-date on the next scrape.
6. **Annotate the ticket** (`bd comment`): real latest used, chart delta, breaking changes, the
   decision + who made it, values touched, rollback command. Cross-cutting gotchas → `bd remember`.
7. **Append to the changelog** (below).
8. `bd close <id>` only after the workload is confirmed healthy on the new version. If it regresses,
   roll back via the recorded command and re-elevate.

## The breaking-changes changelog artifact (required)

Maintain a single markdown artifact per epic: `docs/changelogs/image-updates-<epic-id>.md`.

```markdown
# Image Updates — <epic-id> (<date range>)
Source report: .output/image-version-report.json

## Summary
- Updated: N | Elevated: M | Deferred/parked: K | Bad-latest skipped: J
- Breaking changes encountered: <count>

## Decision matrix (Phase 0/1)
| image/group | current | real latest | where | chart Δ | risk | decision | notes |
|---|---|---|---|---|---|---|---|

## Changes
### <image/group> <current> → <actual-latest>   [TALOS-xxx]
- Namespaces/pods affected: …
- ⚠️ BREAKING: <what broke / changed defaults / required migration> — how it was handled.
- Decision (operator): <question> → <answer>.
- Manifest: <path> · Rollback: <git/kubectl command> · Verified: <how>.
```

Every entry with a breaking change MUST spell out what broke and the resolution. Keep the decision
matrix current as you execute. Consider publishing the changelog as a shareable Artifact at the end.
Nothing is "done" until it is committed AND pushed.

## Close-out

Update the epic with a rollup (done / elevated / deferred / bad-latest), ensure the changelog is
committed, run the report script again to confirm the out-of-date count dropped, `bd sync`, and push.
