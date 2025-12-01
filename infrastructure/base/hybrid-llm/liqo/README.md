# Liqo Multi-Cluster Federation

> Seamless pod offloading to remote clusters via Virtual Kubelet

## Overview

Liqo enables dynamic Kubernetes multi-cluster topologies by:
- Creating virtual nodes representing remote clusters
- Transparently offloading pods to remote clusters
- Providing cross-cluster networking (pod-to-pod, pod-to-service)

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                HOMELAB CLUSTER (Consumer)                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  kubectl get nodes                                               │
│  ┌─────────────────┬────────────────────────────────────────────┤
│  │ talos-node-01   │ Ready   control-plane,master               │
│  │ liqo-aws-gpu    │ Ready   virtual-node         ◄── Virtual!  │
│  └─────────────────┴────────────────────────────────────────────┤
│                                                                  │
│  Liqo Controller Manager                                         │
│  ├── Virtual Kubelet (per peered cluster)                       │
│  ├── Network Fabric Controller                                   │
│  └── Resource Negotiator                                         │
│                                                                  │
└────────────────────────────┬────────────────────────────────────┘
                             │
                    Peering (via Nebula)
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                 AWS GPU CLUSTER (Provider)                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Liqo Provider Components                                        │
│  ├── Resource Sharing Controller                                 │
│  ├── Shadow Pod Controller                                       │
│  └── Network Fabric Agent                                        │
│                                                                  │
│  Physical Nodes                                                  │
│  ├── gpu-worker-01 (g4dn.xlarge - NVIDIA T4)                    │
│  └── nvidia-device-plugin                                        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Components

| File | Description |
|------|-------------|
| `kustomization.yaml` | Kustomize entrypoint |
| `helmrelease.yaml` | Liqo Helm chart deployment |
| `peering-secret.yaml` | Credentials for cluster peering |
| `resource-offer.yaml` | Resource sharing configuration |

## Prerequisites

1. **Nebula VPN** - Network connectivity between clusters
2. **Helm** - For Liqo installation
3. **liqoctl** - Liqo CLI tool

## Installation

```bash
# Add Liqo Helm repo
helm repo add liqo https://helm.liqo.io/
helm repo update

# Install on homelab (consumer)
helm install liqo liqo/liqo \
  --namespace liqo-system \
  --create-namespace \
  --set networking.internal=false \
  --set auth.config.enableAuthentication=true

# Install on AWS (provider)
helm install liqo liqo/liqo \
  --namespace liqo-system \
  --create-namespace \
  --set networking.internal=false \
  --set auth.config.enableAuthentication=true
```

## Establishing Peering

```bash
# On homelab: Generate peering command
liqoctl generate peer-command

# On AWS: Execute the peering command
liqoctl peer out-of-band homelab \
  --auth-url https://... \
  --cluster-id ...

# Verify virtual node appears
kubectl get nodes
# Should show: liqo-aws-gpu   Ready   virtual-node
```

## Namespace Offloading

```bash
# Enable offloading for llm-inference namespace
liqoctl offload namespace llm-inference \
  --namespace-mapping-strategy EnforceSameName \
  --pod-offloading-strategy Remote \
  --selector 'node-type=gpu'
```

This configuration:
- Creates twin namespace in AWS cluster
- Schedules pods ONLY on virtual node (→ AWS)
- Targets clusters with `node-type=gpu` label

## Resource Allocation

By default, Liqo shares 90% of provider cluster resources.

To customize:

```yaml
apiVersion: sharing.liqo.io/v1alpha1
kind: ResourceOffer
metadata:
  name: homelab-offer
  namespace: liqo-system
spec:
  clusterId: homelab-cluster-id
  resources:
    limits:
      cpu: "4"
      memory: "16Gi"
      nvidia.com/gpu: "1"
```

## Troubleshooting

```bash
# Check Liqo status
liqoctl status

# View peering status
liqoctl status peer

# Check virtual node
kubectl describe node liqo-aws-gpu

# View Liqo controller logs
kubectl logs -n liqo-system -l app.kubernetes.io/component=controller-manager
```

## Network Fabric

Liqo provides transparent cross-cluster networking:
- Pod IPs are routable across clusters
- Services are accessible via ClusterIP
- No manual IP remapping needed

Note: We use Nebula for the underlying network transport, with Liqo's network fabric layered on top.

## Considerations

### Resource Visibility
- Virtual node shows aggregated resources
- Real-time updates as AWS resources change
- Spot interruption reflected in node status

### Failure Handling
- ShadowPods ensure pod state survives brief disconnects
- Node tolerations handle temporary unavailability
- Manual intervention may be needed for extended outages

### Security
- Authentication tokens between clusters
- RBAC for resource access
- Network policies can restrict traffic

## References

- [Liqo Documentation](https://docs.liqo.io/)
- [Liqo GitHub](https://github.com/liqotech/liqo)
- [Offloading Guide](https://docs.liqo.io/en/stable/features/offloading.html)
- [Peering Guide](https://docs.liqo.io/en/v0.10.1/usage/peer.html)
