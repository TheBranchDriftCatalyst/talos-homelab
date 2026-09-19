---
type: nav
status: current
covers:
  - repo
freshness: tracks-code
bluf: Entry point for standing this cluster up and running it day to day; the walkthrough itself is quickstart.md.
---

# Getting Started

> Parent: [docs/INDEX.md](../INDEX.md)

## Quick Navigation

<!-- docs:gen:nav -->

| Doc                            | What it covers                                                                                                                                                                |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [quickstart.md](quickstart.md) | Get the toolchain from the flake, plan a rebuild with `task talos:provision`, then merge the kubeconfig — this covers bringing nodes up, not the full Flux/secrets bootstrap. |

<!-- /docs:gen:nav -->

## Key Concepts

Four things that stay true. The numbers they imply do not, so read those from the manifest.

- **Talos has no SSH and no package manager.** Every node change is a machine-config change
  applied with `talosctl`; there is no "log in and fix it" path.
- **`configs/talconfig.yaml` is the node inventory** — hostnames, IPs, which nodes are control
  plane, and the pinned versions. Prose copies of it rot.
- **`talos00` is deliberately tainted `NoSchedule`,** and `allowSchedulingOnControlPlanes` does
  **not** override it: Talos applies `machine.nodeTaints` through a separate, unconditional code
  path. Reasoning in `configs/patches/talos00-controlplane-taint.yaml` — never `kubectl taint`
  it away.
- **A freshly applied node stays `NotReady` on purpose.** Talos is configured `cniConfig: none`,
  so installing the CNI is Flux's job (`infrastructure/base/cilium/`), not the installer's.

## Common Tasks

### Fresh Cluster Setup

- [Plan the rebuild](quickstart.md#fresh-cluster-setup) — `task talos:provision` prints the
  commands; it applies nothing itself
- [Kubernetes Dashboard](quickstart.md#access-kubernetes-dashboard) — token and proxy

### Daily Operations

- [Health, pods, node dashboard](quickstart.md#common-commands) — `task talos:health`,
  `task k8s:get-pods`, `task talos:dashboard`

### Testing Infrastructure Changes

No local Talos cluster workflow exists; the Docker-based one was removed. Validate against the
manifests with `task dev:validate`, `kubectl apply -k <path> --dry-run=client`, and
`task dev:lint`.

### Troubleshooting

- [Dashboard, scheduling, Talos API](quickstart.md#troubleshooting)

## Where to Next

| Destination                                                             | Why                                    |
| ----------------------------------------------------------------------- | -------------------------------------- |
| [02-architecture/dual-gitops.md](../02-architecture/dual-gitops.md)     | How changes actually reach the cluster |
| [03-operations](../03-operations/README.md)                             | Day-to-day operations                  |
| [05-runbooks/cluster-bootstrap.md](../05-runbooks/cluster-bootstrap.md) | Full bare-metal / recovery bootstrap   |
| [docs/INDEX.md](../INDEX.md)                                            | Everything else                        |

---

## Related Issues

<!-- Beads tracking for this section -->

- `CILIUM-kkw` — initial creation of this section README. Stale reference: the beads prefix is
  now `TALOS-`, and the original was closed and compacted, so it resolves under neither prefix.
