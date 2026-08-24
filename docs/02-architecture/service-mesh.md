# Service Mesh Strategy

This document describes the service mesh implementation strategy for the talos-homelab hybrid cluster.

## TL;DR

**Cilium eBPF** is the chosen service mesh solution. It provides mTLS encryption using SPIFFE identities without sidecar proxies, leveraging eBPF at the kernel level for minimal overhead and seamless integration with our existing Cilium CNI.

**Status**: Cilium CNI deployed, mTLS enablement pending (tracked in beads).

## Current Network Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              HYBRID CLUSTER                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────┐                    ┌─────────────────────┐         │
│  │   HOMELAB (Talos)   │                    │    AWS EC2 (k3s)    │         │
│  │   192.168.1.54      │                    │    On-demand GPU    │         │
│  │   10.42.1.1 (Nebula)│◄──── Nebula ─────►│    10.42.2.1        │         │
│  │                     │     (encrypted)    │                     │         │
│  │   Control Plane     │                    │   Worker Node       │         │
│  │   + Workloads       │                    │   + GPU Workloads   │         │
│  └─────────┬───────────┘                    └──────────┬──────────┘         │
│            │                                           │                     │
│            │              ┌───────────┐                │                     │
│            └──────────────┤   Liqo    ├────────────────┘                     │
│                           │ Federation│                                      │
│                           └───────────┘                                      │
│                                                                              │
│  Lighthouse: 10.42.0.1 (EC2 t3.micro - always on)                           │
│  Nebula Network: 10.42.0.0/16                                               │
│  Pod CIDR: 10.244.0.0/16                                                    │
│  Service CIDR: 10.96.0.0/12                                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Network Layer Stack

| Layer                 | Component          | Purpose                                                 |
| --------------------- | ------------------ | ------------------------------------------------------- |
| L7 (Service Mesh)     | **Cilium mTLS**    | Pod-to-pod mTLS encryption via SPIFFE                   |
| L7 (Ingress)          | Traefik            | External access, IngressRoutes                          |
| L4-L7 (Multi-cluster) | Liqo               | Virtual nodes, pod offloading, cross-cluster networking |
| L3 (CNI)              | Cilium             | Pod-to-pod networking, network policies, eBPF           |
| L3 (Underlay)         | Nebula VPN         | Encrypted node-to-node tunnels across internet          |

## Why Cilium for Service Mesh

### Decision: Cilium over Linkerd

After evaluating Linkerd in the scratch namespace, we decided to use Cilium's built-in service mesh capabilities instead:

**Reasons for choosing Cilium:**

1. **Already deployed as CNI** - No additional components needed
2. **eBPF-based** - No sidecar proxies, lower resource overhead
3. **Unified networking stack** - CNI + Network Policies + Service Mesh in one
4. **Simpler operations** - Fewer moving parts to maintain
5. **Better observability** - Hubble already provides deep network visibility
6. **Lower latency** - No proxy hop for pod-to-pod traffic

**Why Linkerd was removed:**

- Additional resource overhead (~400MB RAM for control plane + proxies)
- Added operational complexity (separate control plane, sidecar injection)
- Limited adoption in the cluster (only scratch namespace meshed)
- Cilium provides equivalent mTLS capabilities natively

### Comparison Matrix

| Feature              | Cilium          | Linkerd         | Istio        |
| -------------------- | --------------- | --------------- | ------------ |
| Architecture         | eBPF (kernel)   | Sidecar proxy   | Sidecar proxy|
| mTLS Support         | SPIFFE          | Built-in        | Built-in     |
| Resource Overhead    | Minimal         | ~20MB/pod       | ~100MB/pod   |
| Control Plane Memory | N/A (integrated)| ~200MB          | ~1GB         |
| Network Policies     | Native          | Separate        | Separate     |
| Observability        | Hubble          | Linkerd-viz     | Kiali        |
| Learning Curve       | Low (already CNI)| Medium         | High         |

## Cilium mTLS Implementation

### SPIFFE Identity

Cilium uses SPIFFE (Secure Production Identity Framework for Everyone) for workload identity:

```
spiffe://cluster.local/ns/<namespace>/sa/<service-account>
```

Each pod gets a cryptographic identity based on its Kubernetes service account.

### Enabling mTLS

To enable Cilium mTLS authentication, update the Cilium configuration:

```yaml
# configs/cilium-values.yaml
authentication:
  enabled: true
  mutual:
    spire:
      enabled: true
      install:
        enabled: true
```

Or use Cilium Network Policies with authentication requirements:

```yaml
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: require-mtls
  namespace: catalyst-llm
spec:
  endpointSelector: {}
  ingress:
    - fromEndpoints:
        - matchLabels: {}
      authentication:
        mode: required
```

### Deployment Steps (Pending)

1. Update `configs/cilium-values.yaml` with authentication settings
2. Regenerate Cilium manifest: `helm template cilium cilium/cilium ...`
3. Apply updated manifest: `kubectl apply -f configs/cilium-manifest.yaml`
4. Verify SPIRE agent is running: `kubectl get pods -n kube-system -l app=spire-agent`
5. Apply CiliumNetworkPolicies to require mTLS for sensitive namespaces

## Integration with Existing Stack

### Nebula + Cilium mTLS

```
Pod A ──► Cilium (eBPF mTLS) ──► Nebula Tunnel ──► Cilium (eBPF mTLS) ──► Pod B
          (encrypted L7)         (encrypted L3)    (encrypted L7)
```

Both encryption layers are complementary:

- **Nebula**: Protects against network-level attacks between nodes
- **Cilium mTLS**: Protects against compromised pods, provides identity verification

### Liqo + Cilium

Liqo creates virtual nodes that represent the AWS cluster. Cilium should:

1. Provide network policies across Liqo peered clusters
2. Establish mTLS connections across the Liqo network fabric
3. Provide end-to-end encryption for offloaded pods

**Note**: Cross-cluster mTLS with Liqo requires testing.

### Traefik + Cilium

Traefik handles north-south traffic (external ingress), Cilium handles east-west (service-to-service):

```
Internet ──► Traefik (Ingress) ──► Cilium ──► Service
                                   (mTLS)
```

## Observability

### Hubble Network Observability

Cilium includes Hubble for network observability:

```bash
# Enable Hubble UI
kubectl port-forward -n kube-system svc/hubble-ui 12000:80
open http://localhost:12000

# CLI access
hubble observe --namespace catalyst-llm
hubble observe --verdict DROPPED
```

### Grafana Dashboards

Cilium dashboards are deployed to Grafana:

- `cilium-agent` - Agent pod metrics, BPF operations
- `cilium-operator` - Operator metrics, IPAM
- `cilium-hubble` - Flow metrics, network observability
- `cilium-hubble-flows` - Detailed L3/L4/L7 traffic
- `cilium-policy-verdicts` - Network policy decisions

### Prometheus Metrics

Cilium exposes Prometheus metrics via ServiceMonitor:

```promql
# Policy verdict rate
sum(rate(cilium_policy_verdict_total[5m])) by (verdict)

# mTLS connection status
cilium_auth_mutual_count_total

# Flow metrics
hubble_flows_processed_total
```

## Security Considerations

### Network Policies

Cilium network policies provide L3-L7 filtering:

```yaml
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: api-access
  namespace: catalyst-llm
spec:
  endpointSelector:
    matchLabels:
      app: api-server
  ingress:
    - fromEndpoints:
        - matchLabels:
            app: frontend
      toPorts:
        - ports:
            - port: "8080"
              protocol: TCP
          rules:
            http:
              - method: GET
                path: "/api/.*"
```

### Zero Trust Model

With Cilium mTLS enabled:

1. All pod-to-pod traffic is encrypted
2. Pods are authenticated via SPIFFE identity
3. Network policies can require authentication
4. No implicit trust between pods

## Cost Impact

### Resource Usage (Cilium mTLS)

| Component        | CPU     | Memory   |
| ---------------- | ------- | -------- |
| Cilium Agent     | 100m    | 300Mi    |
| Hubble Relay     | 50m     | 100Mi    |
| SPIRE Agent      | 50m     | 128Mi    |
| **Per Node**     | ~200m   | ~530Mi   |

Compared to Linkerd:

- No per-pod sidecar overhead
- Control plane resources already allocated (Cilium agent)
- Additional SPIRE agent for mTLS certificates

## Related Beads Issues

- **TALOS-cpl** - Enable Cilium mTLS service mesh (blocked by linkerd removal)
- **TALOS-bxh** - Remove linkerd completely (completed)

## References

- [Cilium Service Mesh](https://docs.cilium.io/en/stable/network/servicemesh/)
- [Cilium Authentication](https://docs.cilium.io/en/stable/network/servicemesh/mutual-authentication/)
- [SPIFFE Documentation](https://spiffe.io/docs/)
- [Hubble Documentation](https://docs.cilium.io/en/stable/observability/hubble/)

---

**Last Updated**: 2025-12-17
**Status**: Cilium CNI deployed, mTLS pending
**Previous State**: Linkerd removed (was in scratch namespace only)
