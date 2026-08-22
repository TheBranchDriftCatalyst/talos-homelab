# Operations

> Parent: [docs/INDEX.md](../INDEX.md)

## Overview

This section covers operational procedures, cluster management, and development workflows for the Talos Kubernetes homelab. These guides help you maintain, troubleshoot, and develop infrastructure safely and efficiently.

## Quick Navigation

| Topic                                                    | Description                                                                | When to Read                                                    |
| -------------------------------------------------------- | -------------------------------------------------------------------------- | --------------------------------------------------------------- |
| [provisioning.md](provisioning.md)                       | Complete step-by-step cluster provisioning guide from bare metal to GitOps | Setting up a fresh cluster or understanding provisioning levels |
| [node-shutdown-procedure.md](node-shutdown-procedure.md) | Safe procedures for node shutdown, restart, and maintenance                | Before any hardware maintenance or planned downtime             |
| [local-development-eso.md](local-development-eso.md)     | Local development workflow for External Secrets Operator — **stale**, see the Local Testing note below | Historical reference only; the local cluster it assumes no longer exists |
| [development-tools.md](development-tools.md)             | Git hooks, linters, formatters, and code quality automation                | Initial development environment setup                           |
| [etcd-backup-restore.md](etcd-backup-restore.md)         | How hourly etcd snapshots work + control-plane restore procedure           | Recovering from EPHEMERAL/etcd corruption (e.g. UPS-fault scenario) |
| [RESOURCE-OPTIMIZATION.md](RESOURCE-OPTIMIZATION.md)     | Point-in-time request/limit right-sizing analysis (dated 2025-12-02, single-node `talos00` era) | Historical reference when re-tuning resource requests           |

## Key Concepts

- **Provisioning Levels**: Cluster setup follows a structured approach from Level 0 (base Talos) through Level 4 (GitOps)
- **Graceful Shutdown**: Talos nodes require proper shutdown procedures to avoid etcd corruption and ensure clean restarts
- **Development Tools**: Automated code quality via lefthook (`lefthook.yaml`) — gitleaks, yamllint, shellcheck, shfmt, markdownlint, plus kustomize/kubectl dry-run validation
- **Local Testing (retired)**: The Docker-based local Talos cluster was removed on 2025-12-20 (commit `b2130815`) and `scripts/provision-local.sh` is now the disabled `scripts/__provision-local.sh`. There is no supported local cluster workflow; validate at the manifest level instead. The root `Tiltfile` is an observe-only ops dashboard pointed at the live `admin@catalyst-cluster` context — it deploys nothing.
- **Conventional Commits**: All commits follow conventional commit format, enforced by the lefthook `commit-msg` hook. (No automated changelog generator is wired up — the files in `docs/changelogs/` are hand-written.)

## Common Tasks

### Cluster Provisioning

- [Fresh cluster setup](provisioning.md#level-0-base-infrastructure--completed) - Bootstrap Talos and Kubernetes
- [Deploy core services](provisioning.md#level-1-core-services--completed) - Namespaces, storage, Traefik
- [Deploy applications](provisioning.md#level-2-applications--next) - Arr stack deployment
- [Setup monitoring](provisioning.md#level-3-monitoring-stack--pending) - Prometheus, Grafana, observability
- [Bootstrap GitOps](provisioning.md#level-4-gitops--pending) - FluxCD and ArgoCD setup

> The `✅ / 🔄 / ⏳` status markers baked into those `provisioning.md` headings (and therefore into
> the anchors above) are stale — Levels 2-4 are all deployed today. Fixing the headings will also
> require updating these anchors.

### Node Management

- [Safe node shutdown](node-shutdown-procedure.md) - Graceful shutdown procedure
- [Node restart](node-shutdown-procedure.md) - Clean restart after maintenance
- [Emergency recovery](node-shutdown-procedure.md) - Troubleshooting boot and etcd issues

### Development Workflow

- [Setup development tools](development-tools.md#quick-start) - One-command dev environment setup
- [Git hooks overview](development-tools.md#git-hooks) - Pre-commit, commit-msg, pre-push hooks
- [Linting and formatting](development-tools.md#linters) - YAML, shell, markdown, secret scanning
- [Kubernetes validation](development-tools.md#kubernetes-validation) - Kustomize and kubectl dry-run

### Local Testing

> **The local Talos-in-Docker workflow was removed** (see `docs/01-getting-started/README.md`).
> `docs/01-getting-started/local-testing.md` no longer exists and `scripts/provision-local.sh` is
> retired as `scripts/__provision-local.sh`. `task dev:local-up` and `task talos:provision-local`
> still exist in the Taskfiles but point at the missing script and will fail.
> [local-development-eso.md](local-development-eso.md) is kept as historical reference only —
> ESO itself is live in-cluster (`external-secrets` namespace, with `onepassword-connect`).

- Validate all kustomizations - `task dev:validate`
- Validate a single component - `kubectl apply -k <path> --dry-run=client`
- Lint YAML / shell / secrets before committing - `task dev:lint`

### Disaster Recovery

- [Restore etcd from snapshot](etcd-backup-restore.md#restore-procedure) - Rebuild control plane after EPHEMERAL/etcd loss
- [Verify backup health](etcd-backup-restore.md#verify-its-working) - Check hourly snapshot pipeline

### Troubleshooting

- [Provisioning issues](provisioning.md#notes-and-lessons-learned) - Hostname changes, storage, multi-environment setup
- [Shutdown/startup problems](node-shutdown-procedure.md) - Node not responding, etcd corruption
- [Linter failures](development-tools.md#troubleshooting) - YAML, secrets, kustomize build errors

## Related Sections

| Section                                                            | Why                                                                       |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------- |
| [05-runbooks](../05-runbooks/README.md)                            | High-risk, low-frequency procedures: bootstrap, HA CP migration, Velero restore |
| [06-troubleshooting](../06-troubleshooting/README.md)              | Post-mortems for cluster-wide incidents                                   |
| [07-reference/taskfile-organization.md](../07-reference/taskfile-organization.md) | Full `task` command reference (incl. known-broken tasks)     |
| [CONTRIBUTING.md](../../CONTRIBUTING.md)                           | Dev environment setup that `development-tools.md` assumes                 |

---

## Related Issues

<!-- Beads tracking for this section -->

- `CILIUM-kkw` - Initial creation of section README (stale reference: the beads prefix is now
  `TALOS-`, and no issue resolves under either prefix - the original was closed and compacted)
