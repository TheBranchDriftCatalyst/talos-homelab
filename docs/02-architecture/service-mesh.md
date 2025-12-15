# Service Mesh Strategy

This document tracks the service mesh implementation strategy for the talos-homelab hybrid cluster.

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

| Layer                 | Component              | Purpose                                                 |
| --------------------- | ---------------------- | ------------------------------------------------------- |
| L7 (Application)      | **Service Mesh** (TBD) | mTLS, observability, traffic management                 |
| L7 (Ingress)          | Traefik                | External access, IngressRoutes                          |
| L4-L7 (Multi-cluster) | Liqo                   | Virtual nodes, pod offloading, cross-cluster networking |
| L3 (Overlay)          | Flannel CNI            | Pod-to-pod networking within cluster                    |
| L3 (Underlay)         | Nebula VPN             | Encrypted node-to-node tunnels across internet          |

## Service Mesh Options Analysis

### Option 1: Linkerd (Recommended)

**Pros:**

- Lightweight (~20MB per proxy)
- Simple installation and operation
- Automatic mTLS with zero config
- Low learning curve
- Great for multi-node + hybrid setups

**Cons:**

- Fewer advanced features than Istio
- Less ecosystem tooling

**Resource Impact:**

- Control plane: ~200MB RAM
- Per-pod proxy: ~20MB RAM

### Option 2: Istio

**Pros:**

- Feature-rich (traffic management, security policies)
- Large ecosystem
- Advanced observability

**Cons:**

- Heavy resource footprint (~100MB per proxy)
- Complex configuration
- Overkill for homelab

**Resource Impact:**

- Control plane: ~1GB RAM
- Per-pod proxy: ~50-100MB RAM

### Option 3: Cilium (eBPF-based)

**Pros:**

- eBPF-based (no sidecars for some features)
- Can replace CNI + provide mesh features
- Network policies built-in
- Lower overhead than sidecar-based meshes

**Cons:**

- Requires Linux kernel 5.4+
- More complex to understand
- Talos compatibility needs verification

### Option 4: No Service Mesh (Current State)

**Current Security:**

- Nebula: Node-to-node encryption
- Liqo: Cross-cluster networking
- No pod-to-pod mTLS within cluster

**When this is sufficient:**

- Trusted internal network
- No compliance requirements
- Acceptable to trust pod-to-pod traffic

## Recommendation

**Start with Linkerd** for the scratch namespace as a learning exercise, then evaluate for broader adoption.

### Why Linkerd for this setup

1. **Hybrid-friendly**: Works well with multi-cluster setups
2. **Liqo compatible**: Can mesh across virtual nodes
3. **Nebula synergy**: Defense-in-depth (Nebula encrypts node traffic, Linkerd encrypts pod traffic)
4. **Low overhead**: Important for homelab cluster
5. **gRPC native**: Optimized for gRPC traffic (like our scratch examples)

## Implementation Plan

### Phase 1: Scratch Namespace PoC ✅ COMPLETE

- [x] Install Linkerd control plane
- [x] Inject into scratch namespace only
- [x] Verify gRPC services work with mTLS (grpc-go ↔ grpc-python)
- [ ] Test observability (metrics, traces)
- [ ] Document learnings

### Phase 2: Evaluate for Hybrid

- [ ] Test with Liqo virtual nodes
- [ ] Verify cross-cluster mTLS works
- [ ] Measure latency impact (homelab <-> EC2)
- [ ] Test failure scenarios

### Phase 3: Production Rollout (if successful)

- [ ] Inject into media namespace
- [ ] Inject into monitoring namespace
- [ ] Configure traffic policies
- [ ] Set up dashboards

## Linkerd Installation (Phase 1)

```bash
# Install CLI
curl -sL https://run.linkerd.io/install | sh
export PATH=$PATH:$HOME/.linkerd2/bin

# Verify cluster readiness
linkerd check --pre

# Install CRDs
linkerd install --crds | kubectl apply -f -

# Install control plane
linkerd install | kubectl apply -f -

# Verify installation
linkerd check

# Inject into scratch namespace
kubectl annotate namespace scratch linkerd.io/inject=enabled

# Restart deployments to get sidecars
kubectl rollout restart deployment -n scratch
```

## Integration with Existing Stack

### Nebula + Linkerd

```
Pod A (scratch) ──► Linkerd Proxy ──► Nebula Tunnel ──► Linkerd Proxy ──► Pod B (AWS)
                    (mTLS L7)         (encrypted L3)    (mTLS L7)
```

Both encryption layers are complementary:

- **Nebula**: Protects against network-level attacks between nodes
- **Linkerd**: Protects against compromised pods, provides identity verification

### Liqo + Linkerd

Liqo creates virtual nodes that represent the AWS cluster. Linkerd should:

1. Inject sidecars into pods regardless of where they're scheduled
2. Establish mTLS connections across the Liqo network fabric
3. Provide end-to-end encryption for offloaded pods

**Testing needed**: Verify Linkerd's multi-cluster features work with Liqo's networking model.

### Traefik + Linkerd

Traefik handles north-south traffic (external ingress), Linkerd handles east-west (service-to-service):

```
Internet ──► Traefik (Ingress) ──► Linkerd Proxy ──► Service
```

Options:

1. **Traefik outside mesh**: Traefik terminates external TLS, forwards to Linkerd-meshed services
2. **Traefik inside mesh**: Inject Linkerd into Traefik pods for full mesh coverage

Recommend Option 1 initially for simplicity.

## Security Considerations

### mTLS Certificate Management

Linkerd uses its own CA for mTLS certificates:

- Auto-generated on install
- Can integrate with cert-manager for production
- Certificates rotate automatically

### Network Policies

Consider adding network policies alongside service mesh:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: scratch-isolation
  namespace: scratch
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: scratch
        - namespaceSelector:
            matchLabels:
              name: traefik
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              name: scratch
    - to:
        - namespaceSelector:
            matchLabels:
              name: monitoring
      ports:
        - port: 9090 # Prometheus scrape
```

## Observability Integration

### Prometheus Metrics

Linkerd exposes Prometheus metrics:

- `linkerd_proxy_*` - Proxy-level metrics
- `request_total` - Request counts by route
- `response_latency_ms` - Latency histograms

Add ServiceMonitor:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: linkerd
  namespace: monitoring
spec:
  selector:
    matchLabels:
      linkerd.io/control-plane-ns: linkerd
  namespaceSelector:
    matchNames:
      - linkerd
  endpoints:
    - port: admin-http
```

### Grafana Dashboards

Linkerd provides official Grafana dashboards:

- Linkerd Health
- Linkerd Top Line
- Linkerd Deployment
- Linkerd Route

## Cost Impact

### Resource Usage (Linkerd)

| Component             | CPU      | Memory    |
| --------------------- | -------- | --------- |
| Control Plane (total) | 100m     | 200Mi     |
| Per-pod proxy         | 10m      | 20Mi      |
| 10 meshed pods        | 100m     | 200Mi     |
| **Total (10 pods)**   | **200m** | **400Mi** |

Acceptable for homelab cluster with distributed workload.

## Open Questions

1. **Liqo compatibility**: Does Linkerd multi-cluster work with Liqo's virtual node model?
2. **Talos specifics**: Any Talos-specific configuration needed for Linkerd?
3. **GPU pods**: Should Ollama/LLM pods be meshed? (probably not - adds latency)
4. **Nebula interaction**: Ensure no MTU issues with double encryption

## References

- [Linkerd Documentation](https://linkerd.io/docs/)
- [Linkerd Multi-cluster](https://linkerd.io/2.14/features/multicluster/)
- [Liqo Documentation](https://docs.liqo.io/)
- [Nebula VPN](https://github.com/slackhq/nebula)

---

**Last Updated**: 2025-11-30
**Status**: Active (scratch namespace)
**Current State**: Linkerd control plane running, scratch namespace pods have sidecars injected
