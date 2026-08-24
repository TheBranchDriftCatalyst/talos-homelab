# Projects

Per-project design docs, specs and research. These are project-scoped and often dated — the live
state of the cluster is documented under [02-architecture](../02-architecture/README.md) and
[03-operations](../03-operations/README.md), and the live work queue is in beads (`bd ready`).

## Quick Navigation

| Project                                                        | Description                                                                                             | Status                                        |
| -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| [otel-migration/](otel-migration/README.md)                    | Design doc for the v1 → v2 observability migration (Alloy/Mimir/Loki/Tempo replacing Prometheus/Graylog) | Implemented — the v2 stack is live (TALOS-nh8) |
| [hybrid-llm-cluster/](hybrid-llm-cluster/README.md)            | On-demand AWS GPU compute via Nebula mesh + Liqo/ClusterMesh federation (11 docs)                       | Dormant — see the sub-index                   |
| [cluster-optimization/](cluster-optimization/README.md)        | Power and resource right-sizing initiative (created 2025-12-19, single-node era)                        | Planning                                      |
| [darkweb-archiver/SPEC.md](darkweb-archiver/SPEC.md)           | Technical specification for an internal archiving tool (TALOS-3fed)                                     | Draft spec                                    |

> `otel-migration/README.md` is the design record for the migration; for how the stack works today
> read [OBSERVABILITY.md](../../OBSERVABILITY.md).

---

## Related Issues

<!-- Beads tracking for this section -->
