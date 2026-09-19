---
type: nav
status: current
covers:
  - repo
freshness: tracks-code
bluf: Index of the lookup-style reference material — the operator/CRD catalog, the task-automation reference, and the generated component inventory.
---

# Reference

> Parent: [docs/INDEX.md](../INDEX.md)

## Overview

Deep technical reference material for the Talos Kubernetes homelab — task automation and a catalog
of the operators and CRDs running in the cluster. Use this section when you need authoritative
detail rather than a how-to walkthrough.

## Quick Navigation

<!-- docs:gen:nav -->

| Doc                                                  | What it covers                                                                                                                                                             |
| ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [cluster-crds.md](cluster-crds.md)                   | Which operator owns each CRD group, where that operator is declared in this repo, and which CRDs are installed but carry no custom resources at all.                       |
| [component-inventory.md](component-inventory.md)     | Every Flux Kustomization in clusters/catalyst-cluster, with the manifest that declares it, whether it has a colocated README, and how many nested kustomizations it wraps. |
| [taskfile-organization.md](taskfile-organization.md) | Why the task automation is split into per-domain Taskfiles under dev/, what each domain owns, and which variables each one declares.                                       |

<!-- /docs:gen:nav -->

## Key Concepts

- **CRD ownership** — Operators are filed by domain under `infrastructure/base/`.
  `infrastructure/base/operators/` is the exception: it holds only the standalone operators that
  have no domain home. [cluster-crds.md](cluster-crds.md) carries the owner → repo-path mapping.
- **Bootstrap CRDs** — `infrastructure/base/bootstrap-crds/` vendors a pinned CRD set so Flux's
  server-side dry-run passes on a fresh cluster before the owning operator finishes installing.
  Each operator's chart still owns its CRDs in steady state.
- **Living references** — The CRD catalog is a dated snapshot of the live cluster and ships the
  `kubectl` commands to regenerate its counts.
- **Task automation** — `Taskfile.yaml` is the only Taskfile at the repo root; the domain files
  live under `dev/`. The Taskfile reference explains the split; `task --list` is authoritative.

---

## Related Issues

<!-- Beads tracking for this section -->
