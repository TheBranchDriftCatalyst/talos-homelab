# Getting Started

> Parent: [docs/INDEX.md](../INDEX.md)

## Overview

This section provides essential guides for getting started with the Talos Kubernetes homelab. Whether you're setting up the cluster for the first time or looking for a daily operations reference, these guides will help you get up and running quickly.

## Quick Navigation

| Topic                                | Description                                           | When to Read                                                |
| ------------------------------------ | ----------------------------------------------------- | ----------------------------------------------------------- |
| [quickstart.md](quickstart.md)       | Fast-track cluster setup and common commands          | First time setup, daily operations reference                |

## Key Concepts

- **Talos Linux** is an immutable Kubernetes OS configured via machine configs, not SSH
- **Control Plane IP** defaults to `192.168.1.54` (configurable via `TALOS_NODE` env var)
- **Five-node cluster** - control plane `talos00` (192.168.1.54) plus workers `talos01` (192.168.1.177), `talos02-gpu` (192.168.1.144), `talos03` (192.168.1.30), `talos06` (192.168.1.19)
- **Control plane is tainted** - `talos00` carries `node-role.kubernetes.io/control-plane:NoSchedule`, so general workloads land on the worker nodes unless they tolerate it
- **Cilium** is the CNI (not Flannel); Traefik fronts ingress on LoadBalancer VIP `192.168.1.251`
- **Kubernetes Dashboard** runs in the `kubernetes-dashboard` namespace and is reached via `task k8s:dashboard-token` + `task k8s:dashboard-proxy`. It is **not** deployed by `scripts/provision.sh`

## Common Tasks

### Fresh Cluster Setup

- [Provision using Task](quickstart.md#fresh-cluster-setup) - `task provision` or `./scripts/provision.sh`
- [Access Kubernetes Dashboard](quickstart.md#access-kubernetes-dashboard) - Get token and start proxy

### Daily Operations

- [Check cluster health](quickstart.md#common-commands) - `task health`
- [View all pods](quickstart.md#common-commands) - `task get-pods`
- [Access Talos dashboard](quickstart.md#common-commands) - `task dashboard`

### Testing Infrastructure Changes

> **Local Docker-based testing was removed (2025-12-20).** `local-testing.md` was deleted in
> commit `b2130815`, and `scripts/provision-local.sh` is retired - it now sits at
> `scripts/__provision-local.sh` (the `__` prefix marks a disabled script). There is currently
> no supported local Talos cluster workflow; validate against manifests instead.

- Validate all kustomizations - `task dev:validate`
- Validate a single component - `kubectl apply -k <path> --dry-run=client`
- Lint YAML / secrets before committing - `task dev:lint`

### Troubleshooting

- [Dashboard access issues](quickstart.md#troubleshooting) - Proxy and token troubleshooting
- [Pod scheduling issues](quickstart.md#troubleshooting) - Check taints and node status
- [Talos API connectivity](quickstart.md#troubleshooting) - `task talos:ping`, `task talos:check-api`

## Where to Next

| Destination                                                    | Why                                                        |
| -------------------------------------------------------------- | ---------------------------------------------------------- |
| [QUICKSTART.md](../../QUICKSTART.md)                           | Root-level command reference (overlaps with `quickstart.md`) |
| [02-architecture/dual-gitops.md](../02-architecture/dual-gitops.md) | How changes actually reach the cluster                 |
| [03-operations](../03-operations/README.md)                    | Day-to-day operations and provisioning                     |
| [05-runbooks/cluster-bootstrap.md](../05-runbooks/cluster-bootstrap.md) | Full bare-metal / recovery bootstrap               |
| [docs/INDEX.md](../INDEX.md)                                   | Everything else                                            |

---

## Related Issues

<!-- Beads tracking for this section -->

- `CILIUM-kkw` - Initial creation of section README (stale reference: the beads prefix is now
  `TALOS-`, and no issue resolves under either prefix - the original was closed and compacted)
