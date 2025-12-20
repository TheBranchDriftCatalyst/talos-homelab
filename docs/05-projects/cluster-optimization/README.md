# Cluster Power & Resource Optimization

**Epic:** Cluster Optimization Initiative
**Status:** Planning
**Created:** 2025-12-19
**Last Updated:** 2025-12-19

---

## TL;DR

Optimize the Talos homelab cluster for power efficiency and resource utilization through:

1. **KEDA** - Event-driven autoscaling with scale-to-zero
2. **Descheduler** - Automatic workload rebalancing
3. **Coordination Policy** - Prevent KEDA/Descheduler conflicts

**Key Finding:** talos03 runs at 0% CPU utilization while talos00 is overcommitted at 93%. GPU nodes are severely underutilized outside of transcoding workloads.

---

## Hardware Inventory

| Node | CPU | TDP | RAM | GPU | Role |
|------|-----|-----|-----|-----|------|
| talos00 | AMD Ryzen Embedded V1500B (4c/8t) | 12-25W | 17GB | None | Control Plane |
| talos01 | Intel i3-1220P (12c) | 28W | 24GB | Intel UHD | Worker |
| talos02-gpu | Intel Ultra 5 225H (14c) | 45W | **64GB** | Arc 130T (Meteor Lake) | GPU Worker |
| talos03 | AMD Ryzen 7 5800U (8c/16t) | 15W | 15GB | Vega 8 | GPU Worker |

### Power Characteristics

- **Most Efficient:** talos03 (15W TDP, mobile Ryzen)
- **Highest Capacity:** talos02-gpu (64GB RAM, newest CPU)
- **Most Loaded:** talos00 (control plane, 93% CPU requests)
- **Least Utilized:** talos03 (0% actual CPU usage)

---

## Current State Analysis

### Resource Utilization Snapshot (2025-12-19)

| Node | CPU Used | CPU Requests | Memory Used | Memory Requests | Pods |
|------|----------|--------------|-------------|-----------------|------|
| talos00 | 57% | **93%** | 73% | **82%** | 59 |
| talos01 | 7% | 54% | 30% | **97%** | 45 |
| talos02-gpu | 4% | 32% | 8% | 28% | 11 |
| talos03 | **0%** | **4%** | 11% | 16% | 9 |

### Top Resource Consumers

| Workload | CPU | Memory | Node | Notes |
|----------|-----|--------|------|-------|
| tdarr | 544m | 2.9Gi | talos02-gpu | Video transcoding |
| kube-apiserver | 414m | 1.9Gi | talos00 | Control plane |
| alloy | 196m | 1.5Gi | talos00 | Observability collector |
| kometa | 181m | 1.0Gi | talos00 | Plex metadata manager |
| nexus | 9m | 1.2Gi | talos01 | Artifact registry |

### Key Problems Identified

1. **Control Plane Overload**
   - talos00 hosts 59 pods (36% of cluster)
   - 93% CPU requests on a 4-core embedded CPU
   - Mixing infrastructure + application workloads

2. **GPU Node Underutilization**
   - talos03: 0% CPU, 4% requests - essentially idle
   - talos02-gpu: 4% CPU, 32% requests - mostly idle
   - Both have significant RAM (15GB/64GB) unused

3. **No Autoscaling**
   - No HPA configured
   - No KEDA for scale-to-zero
   - Media apps run 24/7 even when unused

4. **Inefficient Workload Placement**
   - High-memory workloads on memory-constrained nodes
   - Low-priority services competing with control plane

---

## Optimization Strategies

### Strategy 1: KEDA (Event-Driven Autoscaling)

Scale workloads based on events, metrics, or schedules. Enable scale-to-zero for idle workloads.

**Candidates for Scale-to-Zero:**
- Media apps (sonarr, radarr, prowlarr) - only active during downloads
- tdarr-node-gpu - only needed during transcoding
- LLM workloads (Ollama) - scale up on request

**KEDA Scalers to Evaluate:**
- `cron` - Time-based scaling (active hours)
- `prometheus` - Metric-based (request rate)
- `http` - HTTP request-driven (addon required)

### Strategy 2: Descheduler (Workload Rebalancing)

Automatically evict pods to rebalance across nodes.

**Policies to Enable:**
- `LowNodeUtilization` - Move pods from overloaded to underutilized nodes
- `RemovePodsViolatingNodeAffinity` - Ensure GPU workloads on GPU nodes
- `RemovePodsViolatingTopologySpreadConstraint` - Balance across nodes

**Recommended Rebalancing:**

| Move From | Move To | Workloads |
|-----------|---------|-----------|
| talos00 | talos02-gpu | Mimir stack (high memory) |
| talos00 | talos03 | Databases (PostgreSQL) |
| talos01 | talos02-gpu | Loki (high memory) |

### Strategy 3: Coordination Policy

Prevent KEDA and Descheduler from conflicting.

**Rules:**
1. KEDA-managed workloads are excluded from Descheduler
2. Use labels to identify scaling strategy: `scaling.talos.io/managed-by: keda|descheduler|none`
3. PodDisruptionBudgets required for all rebalanced workloads
4. Descheduler runs on schedule (not continuous) to avoid thrashing

### Strategy 4: Control Plane Isolation

Taint the control plane node to prevent non-core workloads from scheduling there.

**Taint Configuration:**
```yaml
machine:
  nodeTaints:
    node-role.kubernetes.io/control-plane: "NoSchedule"
```

**Core Infrastructure (tolerations required):**
| Namespace | Workloads | Notes |
|-----------|-----------|-------|
| kube-system | All | Already has default tolerations |
| cert-manager | All | PKI management |
| external-secrets | All | Secrets management |
| flux-system | All | GitOps controller |
| argocd | All | GitOps controller |
| traefik | DaemonSet | Ingress (runs everywhere) |
| liqo | All | Cluster federation |
| cilium-spire | All | Service mesh identity |
| local-path-storage | All | Storage provisioner |
| node-feature-discovery | DaemonSet | Runs everywhere |

**Workloads to Migrate (no tolerations):**
| Namespace | Move To | Workloads |
|-----------|---------|-----------|
| catalyst, catalyst-llm | talos01/02 | Apps |
| media, media-private | talos01/02/03 | Media apps |
| monitoring | talos02-gpu | Observability (high memory) |
| minio, registry | talos02-gpu | Storage (high memory) |
| scratch | talos01 | Development |
| vpn-gateway | talos01 | VPN |
| authentik | talos01 | Auth |
| infra-control | talos01 | Dashboards |

**Implementation Order:**
1. Add tolerations to core infrastructure deployments
2. Apply taint via Talos machine config
3. Restart/delete non-core pods to trigger rescheduling

### Strategy 5: Karpenter for Hybrid Cloud Scaling

Use Karpenter to provision AWS GPU nodes on-demand for LLM workloads.

**Architecture Flow:**
```
User Request → KEDA ScaledObject → Pod Pending (0→1)
                                        ↓
                              Karpenter detects unschedulable
                                        ↓
                              Provisions g4dn.xlarge spot
                                        ↓
                              Liqo federates node
                                        ↓
                              Pod schedules on GPU
                                        ↓
                              (idle timeout)
                                        ↓
                              Karpenter terminates instance
```

**Components:**
| Component | Purpose |
|-----------|---------|
| KEDA ScaledObject | Triggers scale 0→1 on LLM request |
| Karpenter NodePool | Defines g4dn.xlarge spot instances |
| EC2NodeClass | AMI, security groups, IAM role |
| Liqo | Federates AWS node into homelab |

**This replaces:** Custom llm-scaler with standard Kubernetes primitives

---

## Implementation Plan

### Phase 0: Control Plane Isolation (New)

| Task | Beads ID | Status | Dependencies |
|------|----------|--------|--------------|
| Taint control plane | TALOS-84bs | Open | - |

### Phase 1: Foundation

| Task | Beads ID | Status | Dependencies |
|------|----------|--------|--------------|
| Install KEDA | TALOS-b1gd | Open | - |
| Fix Liqo connectivity | TALOS-txzj | Open | - |
| Define coordination policy | TALOS-hcv1 | Open | TALOS-b1gd |

### Phase 2: Hybrid Cloud Scaling (KEDA + Karpenter)

| Task | Beads ID | Status | Dependencies |
|------|----------|--------|--------------|
| Integrate Karpenter | TALOS-qofw | Open | TALOS-b1gd, TALOS-txzj |
| Create llm-scaler-v2 (KEDA) | TALOS-l13q | Open | TALOS-b1gd, TALOS-txzj |
| Add KEDA ScaledObjects for media | - | Planned | TALOS-b1gd |

### Phase 3: Descheduler

| Task | Beads ID | Status | Dependencies |
|------|----------|--------|--------------|
| Install Descheduler | TALOS-4dz3 | Open | TALOS-hcv1 |
| Configure policies | - | Planned | TALOS-4dz3 |
| Add PDBs to critical services | - | Planned | TALOS-4dz3 |

### Phase 4: Optimization

| Task | Status | Notes |
|------|--------|-------|
| Apply VPA recommendations | Planned | Goldilocks already deployed |
| Migrate workloads to optimal nodes | Planned | After descheduler |
| Monitor power consumption | Planned | Via Kasa smart plugs |

---

## Dependency Graph

```
TALOS-b1gd: Integrate KEDA ─────────────────────────────┐
    │                                                   │
    ├──► TALOS-qofw: Integrate Karpenter ◄──────────────┤
    │        │                                          │
    │        └── related: TALOS-l13q (llm-scaler-v2)    │
    │                                                   │
    ├──► TALOS-l13q: llm-scaler-v2 (KEDA POC)          │
    │        └── blocked by: TALOS-txzj (Fix Liqo) ◄───┘
    │
    └──► TALOS-hcv1: KEDA + Descheduler coordination policy
             │
             └──► TALOS-4dz3: Integrate Descheduler

TALOS-txzj: Fix hybrid cluster (Liqo)
    │
    └──► TALOS-l13q: llm-scaler-v2 (needs remote GPU)
```

---

## Success Metrics

| Metric | Current | Target | Measurement |
|--------|---------|--------|-------------|
| talos00 CPU requests | 93% | <70% | `kubectl describe node` |
| talos03 CPU requests | 4% | >30% | `kubectl describe node` |
| Idle power draw | Unknown | Track baseline | Kasa exporter |
| Scale-to-zero workloads | 0 | 5+ | KEDA ScaledObjects |

---

## Risk Considerations

### KEDA Risks
- **Cold start latency** - Pods scaling from zero may have startup delay
- **Mitigation:** Use `minReplicaCount: 0` with `idleReplicaCount: 1` for critical paths

### Descheduler Risks
- **Pod disruption** - Evictions can cause brief outages
- **Mitigation:** PodDisruptionBudgets, run during low-traffic windows

### Coordination Risks
- **Thrashing** - KEDA scales up, Descheduler moves, KEDA confused
- **Mitigation:** Mutual exclusion via labels, Descheduler on cron schedule

---

## VPA Recommendations Reference

From Goldilocks (subset of high-impact recommendations):

| Workload | Current Request | VPA Target | Delta |
|----------|-----------------|------------|-------|
| tdarr | 4 CPU / 16Gi | 1.7 CPU / 2.7Gi | -58% CPU, -83% mem |
| plex | 50m CPU / 256Mi | 2.4 CPU / 1.8Gi | +4700% CPU* |
| kometa | - | 1 CPU / 1.4Gi | New baseline |
| jellyfin | 50m CPU / 256Mi | 25m CPU / 380Mi | -50% CPU, +48% mem |

*Note: Plex recommendation is burst-based; actual usage is lower due to GPU transcoding.

---

## Related Documentation

- [KEDA Documentation](https://keda.sh/docs/)
- [Descheduler](https://github.com/kubernetes-sigs/descheduler)
- [Goldilocks](https://goldilocks.docs.fairwinds.com/)
- [Hybrid LLM Cluster](../hybrid-llm-cluster/SCALE-TO-ZERO.md)

---

## Changelog

| Date | Change | Author |
|------|--------|--------|
| 2025-12-19 | Initial analysis and task creation | Claude |

---

## Related Issues

<!-- Beads tracking for this project -->

| ID | Title | Type | Status |
|----|-------|------|--------|
| TALOS-84bs | Taint control plane to prevent non-core scheduling | task | open |
| TALOS-b1gd | Integrate KEDA for event-driven autoscaling | feature | open |
| TALOS-qofw | Integrate Karpenter for hybrid-llm node provisioning | feature | open |
| TALOS-l13q | Create llm-scaler-v2 as KEDA-based POC | feature | open |
| TALOS-txzj | Fix hybrid cluster (Liqo) connectivity | bug | open |
| TALOS-hcv1 | Define KEDA + Descheduler coordination policy | task | open |
| TALOS-4dz3 | Integrate Descheduler for workload rebalancing | feature | open |
| ~~TALOS-668~~ | ~~(Duplicate) Descheduler integration~~ | ~~feature~~ | closed |
