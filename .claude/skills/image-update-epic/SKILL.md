---
name: image-update-epic
description: Generate the out-of-date container-image report (via version-checker) and spawn a single beads epic with child tickets to update everything to latest. Use when the user wants to plan/track bumping stale images, "update images to latest", triage the App Ops — Image Versions dashboard, or turn the image-version report into work items.
---

# image-update-epic

Turn the cluster's out-of-date container images into **one beads epic + child tickets**.

This skill only PLANS (report → tickets). Execution is a separate skill: `image-update-implement`.

## 1. Generate the report

```bash
./scripts/image-version-report.sh          # writes .output/image-version-report.{json,md}
```

The JSON has: `summary`, `kube_version`, and `updates[]` — each a unique image update with
`image, current, latest, bump (major|minor|patch|unknown), namespaces[], pod_count, occurrences[]`,
sorted major-first. Read `.output/image-version-report.json`.

## 2. Create the epic

One epic, titled with the report date, e.g.:

```bash
bd create --type=epic -p1 --title="Update out-of-date container images to latest (YYYY-MM-DD)" \
  -d "Source: version-checker / App Ops — Image Versions. <N> unique image updates across <M>
namespaces (<major>/<minor>/<patch> bumps). Report: .output/image-version-report.json.
Implement with the image-update-implement skill. Decisions elevate to the operator."
```

## 3. Create child tickets (one per unique image update)

For each entry in `updates[]`, create a child linked to the epic (`--parent <epic>`). Guidance:

- **Priority by blast radius, not just semver:** `major` → P1, `minor` → P2, `patch` → P3.
  Bump priority one level for infra-critical namespaces (`kube-system`, `argocd`, `flux-system`,
  `cilium`, `cert-manager`, `traefik`, `external-secrets`, `authentik`, any `*-postgres`/CNPG).
- **Title:** `Bump <image> <current> → <latest>`.
- **Body must include:** current→latest, bump type, affected `namespaces` + `pod_count`, and the
  raw `occurrences` (namespace/pod/container) so the implementer can find them.
- **⚠ Flag suspicious "latest":** version-checker mis-reads non-semver tags — a `latest` that is a
  bare build number (`1220`), a date (`20260805`), or wildly different in shape from `current` is
  probably WRONG. Mark these tickets with label `verify-latest` and a note: "do NOT trust the
  reported latest; confirm the real upstream version before bumping." Do not raise their priority.
- **Batch the noise:** to avoid ticket explosion, you MAY fold all `patch` bumps into a single
  child ticket ("Patch-level image bumps (N images)") listing them, while giving `major` and
  `minor` their own tickets. State whichever grouping you chose in the epic description.

## 4. Kubernetes version is NOT an image ticket

`kube_version` (e.g. 1.34 → 1.36) is a **cluster upgrade**, out of scope for image bumps. Note it
in the epic description and point at the existing version-upgrade campaign (search `bd list` for a
Talos/k8s upgrade epic) rather than creating an image ticket for it.

## 5. Finish

- `bd sync` (persist) and report: epic ID, ticket count, and the major-bump list (the ones that
  will need operator decisions during implementation).
- Do NOT start implementing here — hand off to `image-update-implement`.
