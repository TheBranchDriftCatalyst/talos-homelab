# AWS k3s Cluster

Hybrid cluster connecting to Talos homelab via Cilium ClusterMesh over Nebula mesh network.

## Quick Start

```bash
cd clusters/aws-k3s
tilt up
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      TALOS CLUSTER (talos-home, ID:1)                        │
│  Nodes: 5  |  Endpoints: ~135  |  Nebula IP: 10.100.0.1                     │
│                                                                              │
│  ┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────┐  │
│  │  Cilium Agents  │────▶│  KVStoreMesh Cache   │◀────│ ClusterMesh API │  │
│  │  (per node)     │     │  (local etcd cache)  │     │  :32379/32380   │  │
│  └─────────────────┘     └──────────────────────┘     └────────┬────────┘  │
│                                                                 │           │
│  Port Forwarder: socat TCP:32380 → 10.100.2.1:32380            │           │
└─────────────────────────────────────────────────────────────────┼───────────┘
                                                                  │
                          Nebula Mesh (10.100.0.0/16)             │
                          TLS with Combined CA Bundle             │
                                                                  │
┌─────────────────────────────────────────────────────────────────┼───────────┐
│  Port Forwarder: socat TCP:32380 → 10.100.0.1:32380            │           │
│                                                                 │           │
│  ┌─────────────────┐     ┌──────────────────────┐     ┌────────┴────────┐  │
│  │  Cilium Agents  │────▶│  KVStoreMesh Cache   │◀────│ ClusterMesh API │  │
│  │  (per node)     │     │  (local etcd cache)  │     │  :32379/32380   │  │
│  └─────────────────┘     └──────────────────────┘     └─────────────────┘  │
│                                                                              │
│                       AWS K3S CLUSTER (aws-k3s, ID:2)                        │
│  Nodes: 1  |  Endpoints: ~6  |  Nebula IP: 10.100.2.1                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

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

```bash
# ClusterMesh status
cilium --context=admin@catalyst-cluster clustermesh status
cilium --context=aws-lighthouse clustermesh status

# KVStoreMesh sync status
kubectl --context=admin@catalyst-cluster exec -n kube-system deploy/clustermesh-apiserver -c kvstoremesh -- kvstoremesh-dbg status

# Test Nebula connectivity
kubectl --context=admin@catalyst-cluster exec -n nebula deploy/nebula-lighthouse -- ping 10.100.2.1

# Restart KVStoreMesh
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
| `infrastructure/base/nebula/` | Nebula lighthouse manifests |
| `tools/carrierarr/` | EC2 provisioning automation |
| `configs/nebula-certs/` | Nebula certificates (gitignored) |
