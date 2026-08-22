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
| [QUICKSTART.md](../QUICKSTART.md)                         | Essential commands (provision, health, kubeconfig, service URLs)                |
| [CONTRIBUTING.md](../CONTRIBUTING.md)                     | Dev setup, lefthook hooks, lint/format/validate task names                      |
| [CLAUDE.md](../CLAUDE.md)                                 | Agent guidance: beads workflow, GitOps rules, session protocol                  |
| [AGENTS.md](../AGENTS.md)                                 | Agent-facing repo conventions                                                   |
| [TRAEFIK.md](../TRAEFIK.md)                               | Ingress: Traefik DaemonSet, entrypoints, TLS, IngressRoutes, LB VIP             |
| [OBSERVABILITY.md](../OBSERVABILITY.md)                   | **Authoritative** monitoring stack — Alloy / Mimir / Loki / Tempo / ClickStack  |
| [SECURITY_ops.md](../SECURITY_ops.md)                     | CrowdSec + bouncer, honeypot, iocaine, allowlists, ban escalation               |
| [SKILLZ.md](../SKILLZ.md)                                 | Catalog of agent skills and which ones apply to this repo                       |
| [IMPLEMENTATION-TRACKER.md](../IMPLEMENTATION-TRACKER.md) | **Frozen 2025-12-12 snapshot** — historical record, not current state           |
| [DAH_REPORT.md](../DAH_REPORT.md)                         | 2026-03-14 three-perspective system analysis (findings marked resolved/changed) |
| [beads-index.md](../beads-index.md)                       | Beads issue-tracker index                                                       |

---

## Sections

| Section                                                  | Contents                                                                  |
| -------------------------------------------------------- | ------------------------------------------------------------------------- |
| [01-getting-started](01-getting-started/README.md)       | Onboarding, cluster facts, fresh-cluster setup, daily commands            |
| [02-architecture](02-architecture/README.md)             | GitOps model, networking, DNS HA, service mesh, auth, ADRs, plans         |
| [03-operations](03-operations/README.md)                 | Provisioning, node shutdown, etcd backup/restore, dev tooling             |
| [04-deployment](04-deployment/README.md)                 | Flux and ArgoCD bootstrap + deployment workflows                          |
| [05-projects](05-projects/README.md)                     | Per-project design docs (OTEL migration, hybrid LLM, optimization, specs) |
| [05-runbooks](05-runbooks/README.md)                     | Step-by-step recovery/migration procedures + Talos machine-config patches  |
| [06-project-management](06-project-management/README.md) | Roadmaps and idea backlogs (work itself is tracked in beads)              |
| [06-troubleshooting](06-troubleshooting/README.md)       | Post-mortems and hardware/kernel workarounds                              |
| [07-reference](07-reference/README.md)                   | CRD catalog, Taskfile reference, cloud GPU sizing                         |
| [08-monitoring](08-monitoring/README.md)                 | Grafana dashboard index and the generated query audit                     |
| [patterns](patterns/README.md)                           | Reusable cluster patterns (why + how + gotchas)                           |
| [investigations](investigations/README.md)               | Dated deep audits and observability investigations                        |
| [changelogs](changelogs/README.md)                       | Image/chart update campaigns and their breaking changes                   |
| [retros](retros/README.md)                               | Incident retrospectives                                                   |
| [_archive](_archive/README.md)                           | Completed migrations, kept for history only                               |

---

## Reports & Standalone Analyses

| Document                                             | What it is                                                    |
| ---------------------------------------------------- | ------------------------------------------------------------- |
| [executive-summary.md](executive-summary.md)         | Whole-system summary of what the homelab does                 |
| [followup-exec-summary.md](followup-exec-summary.md) | Gap analysis + roadmap recommendations derived from the above |
| [HYBRID-CLOUD-PLAYBOOK.md](HYBRID-CLOUD-PLAYBOOK.md) | Nebula + AWS k3s + Carrierarr hybrid-cloud setup              |

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
| [infrastructure/base/traefik/STATUS.md](../infrastructure/base/traefik/STATUS.md)                                            | Traefik status notes — **stale**, see [TRAEFIK.md](../TRAEFIK.md) |
| [infrastructure/base/vpn-gateway/README.md](../infrastructure/base/vpn-gateway/README.md)                                    | VPN egress gateway                                                |
| [infrastructure/base/shared/gluetun-sidecar/README.md](../infrastructure/base/shared/gluetun-sidecar/README.md)              | Reusable gluetun sidecar                                          |
| [infrastructure/base/hybrid-llm/nebula/README.md](../infrastructure/base/hybrid-llm/nebula/README.md)                        | Nebula mesh — manifests only, **not deployed**                    |
| [infrastructure/base/hybrid-llm/ollama/README.md](../infrastructure/base/hybrid-llm/ollama/README.md)                        | Ollama serving                                                    |

### Applications

| Path                                                                                                                                     | Covers                                                       |
| ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| [applications/arr-stack/README.md](../applications/arr-stack/README.md)                                                                  | Media automation stack (Flux-owned, Authentik SSO)           |
| [applications/arr-stack/overlays/themepark/README.md](../applications/arr-stack/overlays/themepark/README.md)                            | theme.park overlay — the overlay Flux actually deploys       |
| [applications/crossplane-demo/README.md](../applications/crossplane-demo/README.md)                                                      | Crossplane demo namespace (smoke tests parked at 0 replicas) |
| [applications/crossplane-demo/flex/README.md](../applications/crossplane-demo/flex/README.md)                                            | Flex composition demo                                        |
| [applications/the-corpus/README.md](../applications/the-corpus/README.md)                                                                | Data/ETL monorepo — **undeployed**, no Flux wiring           |
| [applications/the-corpus/corpus-core/README.md](../applications/the-corpus/corpus-core/README.md)                                        | Core domain package                                          |
| [applications/the-corpus/pipelines/README.md](../applications/the-corpus/pipelines/README.md)                                            | Ingest pipelines                                             |
| [applications/the-corpus/memex/README.md](../applications/the-corpus/memex/README.md)                                                    | memex subsystem                                              |
| [applications/poisonarr/docs/REACT_PATTERN.md](../applications/poisonarr/docs/REACT_PATTERN.md)                                          | ReAct browser-agent pattern — app is **undeployed**          |
| [applications/gaming/base/kubevirt/README.md](../applications/gaming/base/kubevirt/README.md)                                            | KubeVirt gaming VM                                           |
| [applications/home-automation/base/linkwarden/MIGRATION-RUNBOOK.md](../applications/home-automation/base/linkwarden/MIGRATION-RUNBOOK.md) | Linkwarden migration                                         |

### Clusters & Tools

| Path                                                                               | Covers                                                       |
| ---------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| [clusters/aws-k3s/README.md](../clusters/aws-k3s/README.md)                        | AWS k3s + Cilium ClusterMesh — **dormant** (apiserver at 0/0) |
| [clusters/aws-k3s/ami/README.md](../clusters/aws-k3s/ami/README.md)                | AMI build for the k3s node                                   |
| [tools/carrierarr/README.md](../tools/carrierarr/README.md)                        | Carrierarr provisioning tool                                 |
| [tools/carrierarr/PROVISIONING-NOTES.md](../tools/carrierarr/PROVISIONING-NOTES.md) | Provisioning notes                                           |
| [tools/carrierarr/QA-CHECKLIST.md](../tools/carrierarr/QA-CHECKLIST.md)             | QA checklist                                                 |

---

## Known Overlaps & Contradictions

Flagged for a human to resolve — do not assume one silently wins.

- **Monitoring**: [OBSERVABILITY.md](../OBSERVABILITY.md) (grounded, LGTM stack) vs
  [02-architecture/observability.md](02-architecture/observability.md) (retired v1 stack:
  Prometheus / OpenSearch / Graylog). Treat the root doc as authoritative; the architecture doc is
  history and is an archive candidate.
- **GitOps ownership**: [02-architecture/dual-gitops.md](02-architecture/dual-gitops.md) (grounded)
  vs [02-architecture/gitops-responsibilities.md](02-architecture/gitops-responsibilities.md)
  (still asserts Flux is "NOT YET DEPLOYED"). `dual-gitops.md` is authoritative.
- **Quickstarts**: root [QUICKSTART.md](../QUICKSTART.md) and
  [01-getting-started/quickstart.md](01-getting-started/quickstart.md) are both grounded and
  overlap in scope. Merge candidate.
- **Status reports**: [DAH_REPORT.md](../DAH_REPORT.md),
  [executive-summary.md](executive-summary.md) and
  [followup-exec-summary.md](followup-exec-summary.md) overlap heavily.
- **Trackers**: [IMPLEMENTATION-TRACKER.md](../IMPLEMENTATION-TRACKER.md) (frozen) vs
  [06-project-management/](06-project-management/README.md) roadmaps vs beads. Beads is the live
  source of truth.
- **Traefik / storage component docs**: `infrastructure/base/traefik/STATUS.md` and
  `infrastructure/base/storage/STRUCTURE.md` were both confirmed materially drifted but were out of
  scope for the grounding pass.

---

## Conventions

- Section directories carry a `README.md` that lists and one-line-summarizes their children.
- Docs use progressive summarization: TL;DR → Quick Reference → Deep Dive.
- Docs end with a `## Related Issues` footer for beads tracking.
- Component docs live next to their manifests; cluster-wide docs live under `docs/`.
- Work tracking lives in **beads** (`bd ready`), not markdown TODO lists.
