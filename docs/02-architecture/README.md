# Architecture

> Parent: [docs/INDEX.md](../INDEX.md)

## Overview

This section documents the architectural patterns, design decisions, and infrastructure blueprints for the Talos Kubernetes homelab. Understanding these concepts is crucial for maintaining and extending the cluster's capabilities while following established patterns.

## Quick Navigation

### Core patterns

| Topic                                                    | Description                                                                                   | When to Read                                                 |
| -------------------------------------------------------- | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| [dual-gitops.md](dual-gitops.md)                         | **CRITICAL** - Dual GitOps architecture separating infrastructure and application deployments | Before making any infrastructure or application changes      |
| [gitops-responsibilities.md](gitops-responsibilities.md) | Clarifies what Flux manages vs. what ArgoCD manages. **Contradicts `dual-gitops.md`** — it still says Flux is "NOT YET DEPLOYED" and assigns the arr stack / media servers to ArgoCD | Only alongside `dual-gitops.md`, which is authoritative |
| [networking.md](networking.md)                           | Traefik v3 ingress controller architecture and IngressRoute configuration                     | Adding new services or configuring ingress routing           |
| [pihole-ha-pattern.md](pihole-ha-pattern.md)             | LAN DNS HA - 5 Pi-hole replicas behind Cilium LB-IPAM VIP `192.168.1.240`, nebula-sync         | Changing LAN DNS, `*.talos00` resolution, or split-horizon   |
| [service-mesh.md](service-mesh.md)                       | Service mesh strategy - Cilium eBPF mTLS for hybrid cluster integration                       | Understanding service mesh implementation                    |
| [infrastructure-diagrams.md](infrastructure-diagrams.md) | Visual diagrams of cluster architecture and component relationships                           | Understanding overall system design                          |
| [auth-implementation-guide.md](auth-implementation-guide.md) | SSO with Authentik — ForwardAuth middleware, group model, OIDC vs `forward_single`, per-service coverage (re-grounded 2026-08-22; the Authelia option is kept as a marked NEVER-DEPLOYED block) | Putting a new service behind SSO                             |

### Decision records, plans and spikes

| Topic                                                            | Description                                                                                          | When to Read                                            |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | --------------------------------------------------------- |
| [ADR-001-power-resilience.md](ADR-001-power-resilience.md)       | **ADR / PROPOSED** - Power-resilience strategy after the 2026-05-09 UPS incident                     | Planning UPS, etcd snapshot, or unclean-shutdown work   |
| [CONTROL-PLANE-MIGRATION.md](CONTROL-PLANE-MIGRATION.md)         | **PLANNING** - Moving the control plane to a new node                                                | Replacing or relocating `talos00`                       |
| [crossplane-platformapp-plan.md](crossplane-platformapp-plan.md) | **PLAN** - `PlatformApp` Crossplane v2 API to collapse the per-app resource graph                    | Adding many similar services, or evaluating Crossplane  |
| [dry-ssot-cleanup-inventory.md](dry-ssot-cleanup-inventory.md)   | Inventory of hand-written config that Kyverno / reflector / cluster-settings should derive (TALOS-vo0i) | Before hand-writing boilerplate that a policy can derive |
| [embedded-db-migration-audit.md](embedded-db-migration-audit.md) | **AUDIT** - Which workloads' embedded SQLite/HSQLDB/LevelDB stores are worth moving to CNPG or the Mongo operator, to un-pin `local-path` PVCs before a node reset. Conclusion: almost none — see the leave-alone list first (TALOS-k62s) | Before proposing any embedded-DB → Postgres migration, or planning a node reset |
| [mongodb-migration-audit.md](mongodb-migration-audit.md) | **AUDIT** - The MongoDB half of the same survey. Conclusion: no Mongo work is on the control-plane critical path — nothing Mongo-shaped sits on `talos01`/`talos03`, there are zero hand-rolled Mongo deployments, and the one Mongo on `local-path` pins `talos06` while holding 0 documents. Also documents the house pattern for adding a new `MongoDBCommunity` (TALOS-3hl8) | Before proposing any workload → MongoDB migration, or adding a new Mongo instance |
| [vpn-egress-rotation-designs.md](vpn-egress-rotation-designs.md) | **SPIKE** - Inline gluetun sidecar vs. pre-warmed egress gateway pool                                 | Changing VPN egress or rotation behaviour               |

### Stale / superseded

| Topic                                                        | Description                                                                                                                                                                                            | When to Read                              |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| [observability.md](observability.md)                         | **STALE** - Describes the retired v1 stack (Prometheus/kube-prometheus-stack, OpenSearch, Graylog, Fluent Bit). Superseded by the v2 OTEL stack; see [otel-migration](../05-projects/otel-migration/README.md) and `infrastructure/base/monitoring/v2-otel/` | Historical reference only                 |

### Related docs outside this section

| Topic                                            | Description                                                                                   |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------- |
| [SECURITY_ops.md](../../SECURITY_ops.md)         | Security architecture as deployed — CrowdSec LAPI/bouncer, honeypot, iocaine, ban escalation   |
| [TRAEFIK.md](../../TRAEFIK.md)                   | Ingress implementation detail behind [networking.md](networking.md)                            |
| [OBSERVABILITY.md](../../OBSERVABILITY.md)       | The live monitoring stack (supersedes [observability.md](observability.md))                     |
| [patterns/](../patterns/README.md)               | Reusable cluster patterns extracted from these architecture docs                                |
| [07-reference/cluster-crds.md](../07-reference/cluster-crds.md) | Catalog of every operator/CRD referenced by these designs                        |

## Key Concepts

- **Dual GitOps Pattern**: Infrastructure (Flux Kustomizations under `clusters/catalyst-cluster/`) vs. Application (ArgoCD Applications pointing at app repos) deployments are intentionally separated for stability and control
- **Traefik v3**: Uses IngressRoute CRDs instead of traditional Ingress resources, deployed as a Flux `HelmRelease` (`traefik/traefik`) with full CRD support. Runs as a DaemonSet with `hostPort` 80/443 on every node, plus a Cilium LB-IPAM VIP `192.168.1.251`
- **Domain Pattern**: Internal services use `*.talos00`, publicly-reachable ones `*.knowledgedump.space`. Both are resolved on the LAN by the Pi-hole HA VIP (`192.168.1.240`) via dnsmasq wildcards to `192.168.1.54`; `/etc/hosts` entries pointing to `192.168.1.54` remain a fallback for clients not using Pi-hole as resolver
- **Observability Stack**: OTEL/LGTM - Grafana Alloy collects, Mimir stores metrics, Loki stores logs, Tempo stores traces, with ClickStack/HyperDX alongside. Grafana is provisioned by grafana-operator (dashboards as JSON + `GrafanaDashboard` CRs). The old Prometheus/OpenSearch/Graylog stack has been retired
- **GitOps Responsibilities**: Flux manages infrastructure, ArgoCD manages applications - never mix the two

## Common Tasks

### Understanding GitOps Workflow

- [Dual GitOps rules](dual-gitops.md#rules-and-standards) - Separation of concerns and repository patterns
- [Infrastructure deployment](dual-gitops.md#deployment-workflows) - How to add new infrastructure components
- [Application deployment](dual-gitops.md#adding-new-application) - How to add new ArgoCD-managed applications
- [GitOps responsibilities](gitops-responsibilities.md) - What each tool manages

### Configuring Ingress

- [IngressRoute examples](networking.md#ingressroute-example) - Traefik CRD patterns
- [Middleware configuration](networking.md#middleware-example) - Request/response modification
- [Adding new services](networking.md#adding-new-services) - Step-by-step ingress setup

### Working with Observability

> `observability.md` documents the **retired** v1 stack. For the live stack use
> [otel-migration](../05-projects/otel-migration/README.md) and the manifests in
> `infrastructure/base/monitoring/v2-otel/`.

- Access monitoring UIs - `grafana.talos00`, `mimir.talos00`, `loki.talos00`, `hyperdx.talos00` (alerting runs through Mimir Alertmanager, no ingress)
- Configure log collection - Grafana Alloy (`alloy` + `alloy-node`) ships logs to Loki
- [Grafana dashboards](../08-monitoring/GRAFANA-DASHBOARDS.md) - JSON + `GrafanaDashboard` CRs, no generator scripts

### Planning Enhancements

- [Service mesh strategy](service-mesh.md) - Cilium eBPF mTLS approach (mutual auth is now enabled cluster-wide; SPIRE runs in `cilium-spire`)
- [Authentication patterns](auth-implementation-guide.md) - Authentik SSO as deployed (`authentik` namespace): ForwardAuth middleware, 6-group model, 54 `forward_single` + 12 OIDC providers
- [Infrastructure diagrams](infrastructure-diagrams.md) - Visualizing architecture
- [PlatformApp plan](crossplane-platformapp-plan.md) - Collapsing the per-app resource graph behind one CR
- [DRY / SSOT inventory](dry-ssot-cleanup-inventory.md) - What Kyverno, reflector and cluster-settings already derive for you

---

## Related Issues

<!-- Beads tracking for this section -->

- `CILIUM-kkw` - Initial creation of section README (dangling: the `CILIUM-*` prefix was renamed to `TALOS-*`; this ID no longer resolves in `bd`)
