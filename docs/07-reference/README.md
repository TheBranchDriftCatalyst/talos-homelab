# Reference

> Parent: [docs/INDEX.md](../INDEX.md)

## Overview

Deep technical reference material for the Talos Kubernetes homelab — task automation, a catalog of
the operators and CRDs running in the cluster, and cloud GPU sizing for LLM inference. Use this
section when you need authoritative detail rather than a how-to walkthrough.

## Quick Navigation

| Topic                                              | Description                                                                 | When to Read                                              |
| -------------------------------------------------- | --------------------------------------------------------------------------- | -------------------------------------------------------- |
| [cluster-crds.md](cluster-crds.md)                 | Catalog of every operator/platform CRD, its owner, repo path, and live usage (snapshot 2026-08-09) | Understanding what operators exist and whether they're used |
| [taskfile-organization.md](taskfile-organization.md) | Modular Taskfile structure and task reference for the `talos`, `k8s`, `dev` and `infra` domains | Discovering available `task` commands                     |
| [gpu-instance-guide.md](gpu-instance-guide.md)     | AWS EC2 GPU instance sizing for LLM inference — VRAM vs context length, spot pricing, quota requests | Picking a **cloud** GPU instance for model serving (not in-cluster node hardware) |

## Key Concepts

- **CRD ownership** — Operators are filed by domain across `infrastructure/base/` (`cilium/`,
  `traefik/`, `cert-manager/`, `external-secrets/`, `databases/`, `monitoring/`, `kubevirt/`,
  `backup/`, `kyverno/`, `intel-gpu/`, …). `infrastructure/base/operators/` holds only the handful
  of standalone operators that have no domain home — currently argo-workflows, clickhouse-operator,
  crossplane, dragonfly-operator, keda, opensearch-operator, rabbitmq-operator. See
  [cluster-crds.md](cluster-crds.md) for the full owner → repo-path mapping.
- **Bootstrap CRDs** — `infrastructure/base/bootstrap-crds/` vendors a pinned set of CRDs
  (prometheus-operator, Traefik, Argo CD, NFD, Intel device plugins, Grafana operator,
  external-dns DNSEndpoint) so Flux's server-side dry-run passes on a fresh cluster before the
  owning operator finishes installing. Each operator's chart still owns its CRDs in steady state.
- **Living references** — The CRD catalog is a snapshot; it includes the `kubectl` commands to
  regenerate its counts when operators change.
- **Task automation** — All routine operations are wrapped as `task` commands. The root
  `Taskfile.yaml` includes six domains — `talos`, `k8s`, `dev`, `infra`, `security`, `certs`; the
  Taskfile reference documents the first four (the `security` and `certs` domains are not written
  up there yet — use `task --list` for those).

---

## Related Issues

<!-- Beads tracking for this section -->
