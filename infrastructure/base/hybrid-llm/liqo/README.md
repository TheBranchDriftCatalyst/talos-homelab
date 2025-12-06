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
│  Namespace: liqo (Flux-managed via HelmRelease)                  │
│                                                                  │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                        Peering (via Nebula)
                                 │
┌────────────────────────────────▼────────────────────────────────┐
│                 AWS GPU CLUSTER (Provider)                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Liqo Provider Components                                        │
│  ├── Resource Sharing Controller                                 │
│  ├── Shadow Pod Controller                                       │
│  ├── Tenant Manager                                              │
│  └── Quota Enforcement                                           │
│                                                                  │
│  Namespace: liqo-system (installed via liqoctl)                  │
│                                                                  │
│  Physical Nodes                                                  │
│  ├── lighthouse (k3s control plane)                              │
│  └── gpu-worker (g4dn.xlarge - NVIDIA T4) - future               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Key Concepts

### Authentication Flow

When peering is established, Liqo creates:
1. **Tenant** - Identity for the consumer cluster on the provider
2. **Identity** - Signed credentials for API access
3. **ResourceSlice** - Negotiated resource allocation
4. **Quota** - Provider-side enforcement of resource limits

### Namespace Offloading

To offload pods to remote clusters:
1. Create a `NamespaceOffloading` resource in the source namespace
2. Liqo creates a "twin namespace" on the remote cluster
3. Pods scheduled on virtual nodes are reflected as ShadowPods remotely

## Installation

### Homelab (Consumer) - via Flux

Liqo is deployed via HelmRelease in the `liqo` namespace:

```bash
# Verify Flux manages Liqo
kubectl get helmrelease -n liqo
# NAME   AGE   READY   STATUS
# liqo   1d    True    Helm install succeeded
```

### AWS (Provider) - via liqoctl

On the AWS cluster, Liqo is installed in `liqo-system`:

```bash
# Install Liqo on AWS k3s
liqoctl install k3s \
  --cluster-name aws-gpu-cluster \
  --set networking.internal=false \
  --set auth.config.enableAuthentication=false
```

## Establishing Peering

### Critical: Correct Namespace Flags

**The most common error is incorrect namespace flags.** Each cluster may have Liqo in different namespaces:

| Cluster | Liqo Namespace |
|---------|----------------|
| Homelab (Talos) | `liqo` |
| AWS (k3s) | `liqo-system` |

### Peering Command

```bash
# From homelab (consumer), peer with AWS (provider)
liqoctl peer \
  --remote-kubeconfig /path/to/aws-kubeconfig \
  --namespace liqo \                    # Homelab Liqo namespace
  --remote-namespace liqo-system \      # AWS Liqo namespace
  --networking-disabled                 # We use Nebula instead

# Expected output:
# Ensuring tenant namespace
# INFO: Tenant namespace correctly ensured
# Ensuring nonce secret
# INFO: Nonce secret ensured
# Waiting for nonce to be generated
# INFO: Nonce generated successfully
# ...
# INFO: ResourceSlice authentication: Accepted
# INFO: ResourceSlice resources: Accepted
```

### Verify Peering

```bash
# Check Liqo status
liqoctl info

# Expected output:
# ┌─ Active peerings ─────────────────────────────────────────────┐
# │  cd29e20c-a1a6-4bb0-9665-7c01c26c2fb0                        │
# │      Role:                  Provider                          │
# │      Authentication status: Healthy                           │
# │      Offloading status:     Healthy                           │
# └───────────────────────────────────────────────────────────────┘

# Verify virtual node exists
kubectl get nodes
# NAME                                     STATUS   ROLES           AGE
# talos-xxxxx                              Ready    control-plane   30d
# cd29e20c-a1a6-4bb0-9665-7c01c26c2fb0    Ready    virtual-node    1h
```

## Namespace Offloading

### Enable Offloading for a Namespace

```bash
# Enable offloading for default namespace
kubectl apply -f - <<EOF
apiVersion: offloading.liqo.io/v1beta1
kind: NamespaceOffloading
metadata:
  name: offloading
  namespace: default
spec:
  namespaceMappingStrategy: DefaultName
  podOffloadingStrategy: LocalAndRemote
  clusterSelector:
    nodeSelectorTerms: []
EOF
```

### Verify Offloading Status

```bash
kubectl get namespaceoffloading -n default -o yaml
# Look for:
#   status:
#     offloadingPhase: Ready
#     remoteNamespacesConditions:
#       <cluster-id>:
#         - type: Ready
#           status: "True"
```

## Scheduling Pods on Virtual Node

### Pod Spec Requirements

To schedule a pod on the AWS virtual node:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: test-offload
  namespace: default
spec:
  nodeSelector:
    liqo.io/type: virtual-node
  tolerations:
  - key: "virtual-node.liqo.io/not-allowed"
    operator: "Exists"
    effect: "NoExecute"     # IMPORTANT: Must be NoExecute, not NoSchedule
  containers:
  - name: app
    image: busybox
    command: ["sh", "-c", "sleep 3600"]
```

### Key Points

1. **nodeSelector**: `liqo.io/type: virtual-node` targets the Liqo virtual node
2. **tolerations**: The `NoExecute` effect is required (not `NoSchedule`)
3. **Resource requests**: Recommended to set requests/limits for proper quota enforcement

## Resource Allocation

Default resources shared by provider (configurable):
- **CPU**: 4 cores
- **Memory**: 8Gi
- **Pods**: 110
- **Ephemeral Storage**: 20Gi

To customize, use `liqoctl peer` flags:
```bash
liqoctl peer ... --cpu=8 --memory=16Gi --pods=50
```

## Troubleshooting

### Common Issues

#### 1. "Tenant not found" Error

```
tenants.authentication.liqo.io "xxx" not found
```

**Cause**: Peering was not properly established.

**Fix**: Re-run peering with correct namespace flags:
```bash
liqoctl peer \
  --remote-kubeconfig /path/to/aws-kubeconfig \
  --namespace liqo \
  --remote-namespace liqo-system \
  --networking-disabled
```

#### 2. "Failed getting quota" Error

```
admission webhook "shadowpod.validate.liqo.io" denied the request: failed getting quota
```

**Cause**: Quota wasn't auto-generated because Tenant was missing.

**Fix**: Re-establish peering (see above). The Quota is auto-generated when peering succeeds.

#### 3. Pod Stuck in OffloadingBackOff

**Cause**: Usually namespace offloading not ready or RBAC issues.

**Check**:
```bash
# Check namespace offloading status
kubectl get namespaceoffloading -n <namespace> -o yaml

# Check crd-replicator logs
kubectl logs -n liqo deployment/liqo-crd-replicator --tail=50
```

#### 4. Virtual Node Shows NotReady

**Cause**: Virtual kubelet can't reach remote cluster.

**Check**:
```bash
# Check virtual kubelet logs
kubectl logs -n liqo-tenant-<cluster-id> deployment/vk-<cluster-id> --tail=50

# Verify network connectivity (via Nebula)
kubectl exec -it -n nebula-system daemonset/nebula -- ping 10.42.0.1
```

### Diagnostic Commands

```bash
# Check Liqo status
liqoctl info --verbose

# View peering details
kubectl get foreigncluster -o yaml

# Check ResourceSlice status
kubectl get resourceslices.authentication.liqo.io -A -o yaml

# Check VirtualNode status
kubectl get virtualnodes.offloading.liqo.io -A -o yaml

# View Liqo controller logs
kubectl logs -n liqo deployment/liqo-controller-manager --tail=100

# View crd-replicator logs (handles cross-cluster sync)
kubectl logs -n liqo deployment/liqo-crd-replicator --tail=100
```

## Network Configuration

We use Nebula mesh VPN for cross-cluster networking instead of Liqo's built-in network fabric:

| Component | IP |
|-----------|-----|
| AWS Lighthouse | 10.42.0.1 |
| Homelab | 10.42.1.1 |
| GPU Worker (future) | 10.42.2.1 |

The `--networking-disabled` flag tells Liqo to skip its network setup since we handle it via Nebula.

## Security Considerations

- **Authentication**: Disabled for simplicity (`enableAuthentication: false`)
- **Network**: Encrypted via Nebula mesh VPN
- **RBAC**: Liqo creates tenant-specific namespaces with scoped permissions
- **Quotas**: Provider enforces resource limits

## References

- [Liqo Documentation](https://docs.liqo.io/)
- [Liqo Peering Guide](https://docs.liqo.io/en/latest/usage/peer.html)
- [Offloading in Depth](https://docs.liqo.io/en/latest/advanced/peering/offloading-in-depth.html)
- [Inter-cluster Authentication](https://docs.liqo.io/en/latest/advanced/peering/inter-cluster-authentication.html)
- [Liqo GitHub](https://github.com/liqotech/liqo)
