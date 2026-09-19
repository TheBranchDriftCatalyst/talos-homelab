# Documentation Index

Entry point for all documentation in this repo. Every section below has a `README.md` that
summarizes its children — drill down from here.

> **Grounding pass 2026-08-22:** 62 docs were individually verified against the repo and the
> live cluster. Docs known to be stale are labelled inline below rather than deleted.

---

## Start Here (repo root)

| Document                                                  | What it is                                                                     |
| --------------------------------------------------------- | ------------------------------------------------------------------------------ |
| [README.md](../README.md)                                 | Repo overview, cluster facts, task shortcuts, file layout                       |
| [QUICKSTART.md](01-getting-started/quickstart.md)                         | Essential commands (provision, health, kubeconfig, service URLs)                |
| [CONTRIBUTING.md](../CONTRIBUTING.md)                     | Dev setup, lefthook hooks, lint/format/validate task names                      |
| [CLAUDE.md](../CLAUDE.md)                                 | Agent guidance: beads workflow, GitOps rules, session protocol                  |
| [AGENTS.md](../AGENTS.md)                                 | Agent-facing repo conventions                                                   |
| [TRAEFIK.md](02-architecture/traefik.md)                               | Ingress: Traefik DaemonSet, entrypoints, TLS, IngressRoutes, LB VIP             |
| [OBSERVABILITY.md](08-monitoring/observability.md)                   | **Authoritative** monitoring stack — Alloy / Mimir / Loki / Tempo / ClickStack  |
| [SECURITY_ops.md](../infrastructure/base/security/README.md)                     | CrowdSec + bouncer, honeypot, iocaine, allowlists, ban escalation               |

---

## Sections

<!-- docs:gen:nav-sections -->

| Doc                                                      | What it covers                                                                                                                                                                                                                             |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| [01-getting-started](01-getting-started/README.md)       | Entry point for standing this cluster up and running it day to day; the walkthrough itself is quickstart.md.                                                                                                                               |
| [02-architecture](02-architecture/README.md)             | Index of the architecture docs — the patterns, decision records and spikes you read before changing how the cluster is built.                                                                                                              |
| [03-operations](03-operations/README.md)                 | Index of the day-to-day operational docs — node maintenance, etcd backup and restore, and how this repo tests its own infrastructure.                                                                                                      |
| [05-runbooks](05-runbooks/README.md)                     | The standing constraints every runbook here is written against — a reset destroys local-path data, Velero silently skips it while reporting success, and machine-config patches only come back by re-applying the node's generated config. |
| [06-project-management](06-project-management/README.md) | Index of the planning artifacts; the table is generated from the tree, and beads is the source of truth for work tracking.                                                                                                                 |
| [07-reference](07-reference/README.md)                   | Index of the lookup-style reference material — the operator/CRD catalog, the task-automation reference, and the generated component inventory.                                                                                             |
| [08-monitoring](08-monitoring/README.md)                 | Index of the dashboard-level monitoring references; observability.md is the entry point for the stack itself.                                                                                                                              |
| [patterns](patterns/README.md)                           | Index of the reusable cross-cutting patterns; each entry is a self-contained why/how/gotchas reference that applies to more than one component.                                                                                            |

<!-- /docs:gen:nav-sections -->

---

## Root-level Documents

Documents that sit at the top of `docs/` rather than inside a numbered section.

<!-- docs:gen:nav-root-docs -->

| Doc                                      | What it covers                  |
| ---------------------------------------- | ------------------------------- |
| [session-archive.md](session-archive.md) | Session Archive — talos-homelab |

<!-- /docs:gen:nav-root-docs -->

---

## Component Documentation (outside `docs/`)

Docs that live next to the manifests they describe.

### Infrastructure

| Path                                                                                                                         | Covers                                                            |
| ---------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| [infrastructure/base/argocd/README.md](../infrastructure/base/argocd/README.md)                                              | ArgoCD access, apps, image-updater, ESO credentials               |
| [infrastructure/base/argocd/STATUS.md](../infrastructure/base/argocd/STATUS.md)                                              | ArgoCD rollout status notes                                       |
| [infrastructure/base/external-secrets/README.md](../infrastructure/base/external-secrets/README.md)                          | ESO + 1Password Connect                                           |
| [infrastructure/base/aws/README.md](../infrastructure/base/aws/README.md)                                                    | Crossplane AWS providers and XR compositions                      |
| [infrastructure/base/databases/README.md](../infrastructure/base/databases/README.md)                                        | CNPG clusters and shared DB services                              |
| [infrastructure/base/analytics/README.md](../infrastructure/base/analytics/README.md)                                        | Analytics stack                                                   |
| [infrastructure/base/external-dns/README.md](../infrastructure/base/external-dns/README.md)                                  | external-dns wiring                                               |
| [infrastructure/base/flux-notifications/README.md](../infrastructure/base/flux-notifications/README.md)                      | Flux alerting to Discord                                          |
| [infrastructure/base/gpu-inference/README.md](../infrastructure/base/gpu-inference/README.md)                                | In-cluster GPU inference                                          |
| [infrastructure/base/intel-gpu/README.md](../infrastructure/base/intel-gpu/README.md)                                        | Intel Arc device plugin (talos02-gpu)                             |
| [infrastructure/base/infra-control/README.md](../infrastructure/base/infra-control/README.md)                                | Infra control tooling                                             |
| [infrastructure/base/monitoring/grafana-dashboards/README.md](../infrastructure/base/monitoring/grafana-dashboards/README.md) | Dashboard JSON + `GrafanaDashboard` CR workflow                   |
| [infrastructure/base/storage/STRUCTURE.md](../infrastructure/base/storage/STRUCTURE.md)                                      | Storage layout — **stale** (still TrueNAS-centric)                |
| [infrastructure/base/traefik/STATUS.md](../infrastructure/base/traefik/STATUS.md)                                            | Traefik status notes — **stale**, see [TRAEFIK.md](02-architecture/traefik.md) |
| [infrastructure/base/vpn-gateway/README.md](../infrastructure/base/vpn-gateway/README.md)                                    | VPN egress gateway                                                |
| [infrastructure/base/shared/gluetun-sidecar/README.md](../infrastructure/base/shared/gluetun-sidecar/README.md)              | Reusable gluetun sidecar                                          |
| [infrastructure/base/hybrid-llm/ollama/README.md](../infrastructure/base/hybrid-llm/ollama/README.md)                        | Ollama serving                                                    |

### Applications

| Path                                                                                                                                     | Covers                                                       |
| ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| [applications/arr-stack/README.md](../applications/arr-stack/README.md)                                                                  | Media automation stack (Flux-owned, Authentik SSO)           |
| [applications/arr-stack/overlays/themepark/README.md](../applications/arr-stack/overlays/themepark/README.md)                            | theme.park overlay — the overlay Flux actually deploys       |
| [applications/crossplane-demo/README.md](../applications/crossplane-demo/README.md)                                                      | Crossplane demo namespace (smoke tests parked at 0 replicas) |
| [applications/gaming/base/kubevirt/README.md](../applications/gaming/base/kubevirt/README.md)                                            | KubeVirt gaming VM                                           |
| [applications/home-automation/base/linkwarden/MIGRATION-RUNBOOK.md](../applications/home-automation/base/linkwarden/MIGRATION-RUNBOOK.md) | Linkwarden migration                                         |

### Clusters & Tools

| Path                                                                               | Covers                                                       |
| ---------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| [clusters/aws-k3s/README.md](../clusters/aws-k3s/README.md)                        | AWS k3s + Cilium ClusterMesh — **dormant** (apiserver at 0/0) |
| [clusters/aws-k3s/ami/README.md](../clusters/aws-k3s/ami/README.md)                | AMI build for the k3s node                                   |

---

## Known Overlaps & Contradictions

Flagged for a human to resolve — do not assume one silently wins.

- **Quickstarts**: the root `README.md` quick-start block and
  [01-getting-started/quickstart.md](01-getting-started/quickstart.md) overlap in scope. Merge
  candidate.
- **Roadmaps vs beads**: [06-project-management/](06-project-management/README.md) holds planning
  prose; beads (`bd ready`) is the live source of truth for work state. Anything in the former
  that restates ticket status is drift.
- **Traefik / storage component docs**: `infrastructure/base/traefik/STATUS.md` and
  `infrastructure/base/storage/STRUCTURE.md` were both confirmed materially drifted but were out of
  scope for the grounding pass.

> The monitoring, GitOps-ownership and status-report contradictions previously listed here were
> resolved by deletion rather than by a merge: `_archive/observability-v1-stack.md`,
> `02-architecture/gitops-responsibilities.md`, `_archive/2026-03-14-dah-report.md`,
> `executive-summary.md` and `followup-exec-summary.md` no longer exist anywhere in the repo, so
> there is no longer a second document to disagree with.

---

## Conventions

- Section directories carry a `README.md` that lists and one-line-summarizes their children.
- Docs use progressive summarization: TL;DR → Quick Reference → Deep Dive.
- Docs end with a `## Related Issues` footer for beads tracking.
- Component docs live next to their manifests; cluster-wide docs live under `docs/`.
- Work tracking lives in **beads** (`bd ready`), not markdown TODO lists.
