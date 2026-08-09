# Reference

## Overview

Deep technical reference material for the Talos Kubernetes homelab — task automation, hardware
guides, and a live catalog of the operators and CRDs running in the cluster. Use this section when
you need authoritative detail rather than a how-to walkthrough.

## Quick Navigation

| Topic                                              | Description                                                                 | When to Read                                              |
| -------------------------------------------------- | --------------------------------------------------------------------------- | -------------------------------------------------------- |
| [cluster-crds.md](cluster-crds.md)                 | Catalog of every operator/platform CRD, its owner, repo path, and live usage | Understanding what operators exist and whether they're used |
| [taskfile-organization.md](taskfile-organization.md) | Modular Taskfile structure and full task reference                          | Discovering available `task` commands                     |
| [gpu-instance-guide.md](gpu-instance-guide.md)     | GPU / instance hardware reference                                           | Working with GPU workloads or node hardware               |

## Key Concepts

- **CRD ownership** — Most operators live under `infrastructure/base/operators/`, but several CRDs
  are bootstrapped separately via `infrastructure/base/bootstrap-crds/`. See
  [cluster-crds.md](cluster-crds.md) for the full owner → repo-path mapping.
- **Living references** — The CRD catalog is a snapshot; it includes the `kubectl` commands to
  regenerate its counts when operators change.
- **Task automation** — All routine operations are wrapped as `task` commands; the Taskfile
  reference documents the domain-based organization.
