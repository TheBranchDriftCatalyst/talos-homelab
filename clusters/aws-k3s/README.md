# AWS k3s Cluster

Hybrid cluster connecting to Talos homelab via Cilium ClusterMesh over Nebula mesh network.

> **STATUS — DORMANT (verified 2026-08-22).** The hybrid link is not currently running:
>
> - `clustermesh.apiserver.replicas: 0` in `infrastructure/base/cilium/values.yaml` (scaled down 2026-05-29 during the control-plane meltdown work). Live, `deployment/clustermesh-apiserver` in `kube-system` is `0/0`.
> - The Nebula lighthouse is not deployed — there is no `nebula` namespace. `infrastructure/base/nebula/` is not referenced by any Flux Kustomization (the `nebula` dependency in `clusters/catalyst-cluster/catalyst-llm.yaml` is commented out).
> - Neither port-forwarder manifest set (`infrastructure/base/cilium/clustermesh-forwarders/`, `clusters/aws-k3s/manifests/clustermesh/`) is listed in `infrastructure/base/cilium/kustomization.yaml`, so Flux never applies them.
> - The `aws-lighthouse` kube context still exists but its API server does not answer.
>
> Everything below describes the **intended** topology and how to bring it back. Re-enable is tracked in **TALOS-4ye**.

## Quick Start

```bash
cd clusters/aws-k3s
tilt up
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      TALOS CLUSTER (talos-home, ID:1)                       │
│  Nodes: 5  |  Endpoints: ~275  |  Nebula IP: 10.100.0.1                     │
│                                                                             │
│  ┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────┐   │
│  │  Cilium Agents  │────▶│  KVStoreMesh Cache   │◀────│ ClusterMesh API │   │
│  │  (per node)     │     │  (local etcd cache)  │     │ NodePort :32379 │   │
│  └─────────────────┘     └──────────────────────┘     └────────┬────────┘   │
│                                                                │            │
│  Forwarders on talos00 (socat, hostNetwork):                   │            │
│    out  :32380 → 10.100.2.1:32380   (Talos → AWS)              │            │
│    in   :32381 → 127.0.0.1:32379    (AWS → Talos)              │            │
└────────────────────────────────────────────────────────────────┼────────────┘
                                                                 │
                          Nebula Mesh (10.100.0.0/16)            │
                          TLS with Combined CA Bundle            │
                                                                 │
┌────────────────────────────────────────────────────────────────┼────────────┐
│  Forwarders on the k3s node (socat, hostNetwork):              │            │
│    out  :32381 → 10.100.0.1:32381   (AWS → Talos)              │            │
│    in   :32380 → clustermesh-apiserver.kube-system:2379        │            │
│                                                                │            │
│  ┌─────────────────┐     ┌──────────────────────┐     ┌────────┴────────┐   │
│  │  Cilium Agents  │────▶│  KVStoreMesh Cache   │◀────│ ClusterMesh API │   │
│  │  (per node)     │     │  (local etcd cache)  │     │ NodePort :32379 │   │
│  └─────────────────┘     └──────────────────────┘     └─────────────────┘   │
│                                                                             │
│                       AWS K3S CLUSTER (aws-k3s, ID:2)                       │
│  Nodes: 1  |  Endpoints: ~6  |  Nebula IP: 10.100.2.1                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

The ClusterMesh apiserver is only ever exposed on NodePort **32379**. Ports 32380
and 32381 belong to the socat forwarders, one per direction — see the port table
in `docs/HYBRID-CLOUD-PLAYBOOK.md`.

## Components

| Component | Purpose |
|-----------|---------|
| Nebula Mesh | L3 overlay network (10.100.0.0/16) |
| Port Forwarders | socat DaemonSets bridging Nebula TUN to ClusterMesh |
| KVStoreMesh | Centralized sync - agents read from local cache |
| Combined CA | Both Cilium CAs bundled for mutual TLS |

## Contexts

| Context | Cluster | Nebula IP |
|---------|---------|-----------|
| `admin@catalyst-cluster` | Talos homelab | 10.100.0.1 |
| `aws-lighthouse` | AWS k3s | 10.100.2.1 |

## Common Commands

These assume the mesh is actually up. While it is dormant (see Status above) the
ClusterMesh commands report nothing and the `nebula` exec fails — the namespace
does not exist.

```bash
# ClusterMesh status
cilium --context=admin@catalyst-cluster clustermesh status
cilium --context=aws-lighthouse clustermesh status

# KVStoreMesh sync status
kubectl --context=admin@catalyst-cluster exec -n kube-system deploy/clustermesh-apiserver -c kvstoremesh -- kvstoremesh-dbg status

# Test Nebula connectivity
kubectl --context=admin@catalyst-cluster exec -n nebula deploy/nebula-lighthouse -- ping 10.100.2.1

# Restart KVStoreMesh (no-op at replicas: 0 — scale up first)
kubectl --context=admin@catalyst-cluster rollout restart deployment/clustermesh-apiserver -n kube-system
```

## Global Services

To make a service accessible across clusters, add the annotation:

```yaml
metadata:
  annotations:
    io.cilium/global-service: "true"
```

## Troubleshooting

See `docs/HYBRID-CLOUD-PLAYBOOK.md` for detailed troubleshooting including:
- TLS certificate issues
- KVStoreMesh endpoint configuration
- Port forwarder deployment

## Related Files

| Path | Purpose |
|------|---------|
| `docs/HYBRID-CLOUD-PLAYBOOK.md` | Complete hybrid cloud setup guide |
| `infrastructure/base/nebula/` | Nebula lighthouse manifests (not currently wired into Flux) |
| `infrastructure/base/cilium/clustermesh/` | ClusterMesh apiserver manifests (not in the cilium kustomization) |
| `infrastructure/base/cilium/clustermesh-forwarders/` | Talos-side socat forwarders, :32380 out / :32381 in |
| `clusters/aws-k3s/manifests/clustermesh/` | AWS-side socat forwarder, :32381 → 10.100.0.1:32381 |
| `clusters/aws-k3s/ami/` | Packer templates + EC2 userdata (base, lighthouse, gpu-worker) |
| `tools/carrierarr/` | EC2/Fargate fleet management agent + provisioning notes |
| `configs/nebula-certs/` | Nebula certificates (gitignored) |

---

## Related Issues

- TALOS-4ye - Re-enable Cilium ClusterMesh when federation peer cluster goes live
