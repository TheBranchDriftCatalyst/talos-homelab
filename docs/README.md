# Documentation

Start at **[INDEX.md](INDEX.md)** — it lists every section, every root-level doc, and every
component doc that lives next to its manifests.

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
