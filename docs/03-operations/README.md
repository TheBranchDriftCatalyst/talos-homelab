---
type: nav
status: current
covers:
  - path:docs/03-operations
freshness: tracks-code
bluf: Index of the day-to-day operational docs — node maintenance, etcd backup and restore, and how this repo tests its own infrastructure.
---

# Operations

> Parent: [docs/INDEX.md](../INDEX.md)

## Overview

This section covers operational procedures, cluster management, and development workflows for the Talos Kubernetes homelab. These guides help you maintain, troubleshoot, and develop infrastructure safely and efficiently.

## Quick Navigation

<!-- docs:gen:nav -->

| Doc                                                      | What it covers                                                                                                                                                                                      |
| -------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [etcd-backup-restore.md](etcd-backup-restore.md)         | etcd snapshots land in MinIO on a schedule; recovering a dead control plane means reset the node, re-apply its generated machine config, then bootstrap with `--recover-from`.                      |
| [node-shutdown-procedure.md](node-shutdown-procedure.md) | Drain, shut down through the Talos API rather than the power button, then verify etcd quorum before uncordoning — and never re-bootstrap a node that still has surviving peers.                     |
| [testing.md](testing.md)                                 | Four test layers all run under one pytest, selected by suite marker, and all are safe/offline by default — anything that touches the live cluster or destroys something is behind an explicit flag. |

<!-- /docs:gen:nav -->

## Key Concepts

- **Graceful shutdown**: stop nodes through the Talos API, never the power button — a hard cut risks etcd corruption on EPHEMERAL.
- **etcd is the one thing Velero cannot save**: it needs a snapshot taken off-node, which is why the CronJob exists.
- **Code quality** is enforced by lefthook (`lefthook.yaml`): gitleaks, yamllint, shellcheck, shfmt, markdownlint, kustomize and `kubectl --dry-run`. Commit messages are checked by its `commit-msg` hook.
- **No local cluster.** No Talos-in-Docker workflow, no `provision-local` script or task; validate at the manifest level. The root `Tiltfile` observes the live cluster and deploys nothing — Flux owns deployment.

## Common Tasks

### Node Management

- [Shutdown, restart and emergency recovery](node-shutdown-procedure.md) — draining, powering down through the Talos API, and what not to do to etcd on the way back up.

### Disaster Recovery

- [Restore etcd from snapshot](etcd-backup-restore.md#restore-procedure) — rebuild the control plane after EPHEMERAL/etcd loss.
- [Verify backup health](etcd-backup-restore.md#verify-its-working) — check the snapshot pipeline before you need it.

### Validation before committing

```bash
task dev:validate                         # every kustomization
kubectl apply -k <path> --dry-run=client  # one component
task dev:lint                             # YAML / shell / markdown / secrets
```

See [testing.md](testing.md) for the four test layers and how to add to them, and
[07-reference/taskfile-organization.md](../07-reference/taskfile-organization.md) for the full
task catalogue.

## Related Sections

| Section                                                                           | Why                                                                             |
| --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| [05-runbooks](../05-runbooks/README.md)                                           | High-risk, low-frequency procedures: bootstrap, HA CP migration, Velero restore |
| [07-reference/taskfile-organization.md](../07-reference/taskfile-organization.md) | Full `task` command reference (incl. known-broken tasks)                        |
| [CONTRIBUTING.md](../../CONTRIBUTING.md)                                          | Dev environment setup that `development-tools.md` assumes                       |

---

## Related Issues

<!-- Beads tracking for this section -->

- `CILIUM-kkw` — section README origin. Dangling: the prefix is now `TALOS-` and no issue resolves under either.
