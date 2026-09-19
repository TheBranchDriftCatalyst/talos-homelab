---
type: nav
status: current
covers:
  - repo
freshness: tracks-code
bluf: Index of the architecture docs — the patterns, decision records and spikes you read before changing how the cluster is built.
---

# Architecture

> Parent: [docs/INDEX.md](../INDEX.md)

## Overview

Patterns, decision records and spikes for the Talos homelab. Read the relevant one before
changing how a thing is built.

## Quick Navigation

<!-- docs:gen:nav -->

| Doc                                                                  | What it covers                                                                                                                                                                                                         |
| -------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [auth-implementation-guide.md](auth-implementation-guide.md)         | Authentik is the only identity store — Traefik ForwardAuth for apps with no login of their own, native OIDC for apps that do their own role mapping, and no LDAP anywhere.                                             |
| [composition-labels-convention.md](composition-labels-convention.md) | Composed resources carry `catalyst.io/composition` and `catalyst.io/managed-by` on the inner manifest because Crossplane's own label only reaches the outer Object wrapper, which cannot identify the real resource.   |
| [dual-gitops.md](dual-gitops.md)                                     | Flux reconciles infrastructure out of this repo, ArgoCD reconciles applications out of their own repos, and the dividing line is "do we build the image?".                                                             |
| [p0-4-lan-entrypoint-design.md](p0-4-lan-entrypoint-design.md)       | Traefik routes on `Host()` regardless of entrypoint, so internal services are WAN-reachable by Host-spoof; the fix is a second, unforwarded LAN entrypoint pair rather than inverting the WAN entrypoint default.      |
| [s3-backend-evaluation.md](s3-backend-evaluation.md)                 | MinIO CE is archived upstream with unpatchable CVEs, so the object store has to move; Garage covers every bucket except the one that uses versioning, which is versitygw's job.                                        |
| [traefik.md](traefik.md)                                             | Traefik runs as a DaemonSet binding hostPorts on every node and routes purely on `Host()`, with TLS served by SNI from one default TLSStore so an IngressRoute never has to name a certificate.                        |
| [vpn-egress-rotation-designs.md](vpn-egress-rotation-designs.md)     | The inline gluetun sidecar keeps its kill-switch in the app's own netns, which a pre-warmed gateway pool cannot do — so the pool is only worth it for apps that can tolerate a NetworkPolicy as their only leak guard. |

<!-- /docs:gen:nav -->

### Related docs outside this section

| Topic                                                                                        | Description                                                                                      |
| -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| [../../infrastructure/base/security/README.md](../../infrastructure/base/security/README.md) | Security architecture as deployed — CrowdSec LAPI/bouncer, honeypot, iocaine, ban escalation     |
| [security/README.md](../../infrastructure/base/security/README.md)                           | **Start here for security**: how detection, decision and the two enforcement planes fit together |
| [traefik.md](traefik.md)                                                                     | Ingress implementation detail: entrypoints, TLS, IngressRoutes, the LB VIP                       |
| [observability.md](../08-monitoring/observability.md)                                        | The live monitoring stack — Alloy / Mimir / Loki / Tempo / ClickStack                            |
| [patterns/](../patterns/README.md)                                                           | Reusable cluster patterns extracted from these architecture docs                                 |
| [07-reference/cluster-crds.md](../07-reference/cluster-crds.md)                              | Catalog of every operator/CRD referenced by these designs                                        |

## Common Tasks

- **Understand how a change reaches the cluster** — [dual-gitops.md](dual-gitops.md), in
  particular [Rules and Standards](dual-gitops.md#rules-and-standards) and
  [Deployment Workflows](dual-gitops.md#deployment-workflows).
- **Add an ingress route** — [traefik.md](traefik.md#adding-a-new-service). It is the successor
  to the deleted `networking.md`.
- **Put a service behind SSO** — [auth-implementation-guide.md](auth-implementation-guide.md).
- **Work on monitoring** — [08-monitoring/observability.md](../08-monitoring/observability.md)
  is the live stack; the v1 Prometheus/OpenSearch/Graylog stack is retired.

---

## Related Issues

<!-- Beads tracking for this section -->

- `CILIUM-kkw` - Initial creation of section README (dangling: the `CILIUM-*` prefix was renamed to `TALOS-*`; this ID no longer resolves in `bd`)
