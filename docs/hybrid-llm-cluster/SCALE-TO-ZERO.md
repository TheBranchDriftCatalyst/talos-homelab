# Scale-to-Zero GPU Worker Architecture

## Overview

The GPU worker instance only runs when needed, scaling down to zero cost when idle.

```
┌─────────────────────────────────────────────────────────────────┐
│                        IDLE STATE ($7/mo)                       │
│                                                                 │
│   Homelab (always on)          AWS (minimal)                    │
│   ┌─────────────┐              ┌─────────────┐                  │
│   │ Talos K8s   │              │ Lighthouse  │                  │
│   │ + Liqo      │◄────────────►│ t3.micro    │                  │
│   │ + Nebula    │   Nebula     │ $7/mo       │                  │
│   └─────────────┘   Mesh       └─────────────┘                  │
│                                       │                         │
│                                       │ GPU Worker: STOPPED     │
│                                       │ Cost: $0                │
│                                       ▼                         │
│                                ┌─────────────┐                  │
│                                │ (dormant)   │                  │
│                                │ g4dn.xlarge │                  │
│                                └─────────────┘                  │
└─────────────────────────────────────────────────────────────────┘

                    │
                    │  LLM Request arrives
                    ▼

┌─────────────────────────────────────────────────────────────────┐
│                    SCALING UP (2-3 min)                         │
│                                                                 │
│   1. Controller detects pending LLM pod                         │
│   2. Starts EC2 GPU instance                                    │
│   3. Instance joins Nebula mesh                                 │
│   4. k3s registers with Liqo                                    │
│   5. Pod scheduled on GPU node                                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

                    │
                    ▼

┌─────────────────────────────────────────────────────────────────┐
│                    ACTIVE STATE (~$0.16/hr spot)                │
│                                                                 │
│   Homelab                      AWS                              │
│   ┌─────────────┐              ┌─────────────┐                  │
│   │ Talos K8s   │              │ Lighthouse  │                  │
│   │ + Liqo      │◄────────────►│ t3.micro    │                  │
│   │             │   Nebula     └─────────────┘                  │
│   │ Virtual     │   Mesh              │                         │
│   │ Node: aws-  │                     │                         │
│   │ gpu-worker  │◄────────────────────┤                         │
│   └─────────────┘                     │                         │
│         │                             ▼                         │
│         │                      ┌─────────────┐                  │
│         │   Pod Offloaded      │ GPU Worker  │                  │
│         └─────────────────────►│ g4dn.xlarge │                  │
│                                │ k3s + Ollama│                  │
│                                │ Running     │                  │
│                                └─────────────┘                  │
└─────────────────────────────────────────────────────────────────┘

                    │
                    │  15 min idle timeout
                    ▼

┌─────────────────────────────────────────────────────────────────┐
│                    SCALING DOWN                                 │
│                                                                 │
│   1. Controller detects idle (no GPU pods for 15 min)           │
│   2. Drains pods from GPU node                                  │
│   3. Stops EC2 instance (not terminate - preserves state)       │
│   4. Virtual node disappears from Liqo                          │
│   5. Returns to IDLE STATE                                      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Cost Analysis

| State | Duration | Cost |
|-------|----------|------|
| Idle | 720 hrs/mo | $7/mo (lighthouse only) |
| Active (spot) | Per hour | ~$0.16/hr |

**Example usage patterns:**

| Usage | Hours/Month | Monthly Cost |
|-------|-------------|--------------|
| Light (2 hr/day) | 60 hrs | $7 + $9.60 = **$17/mo** |
| Medium (4 hr/day) | 120 hrs | $7 + $19.20 = **$26/mo** |
| Heavy (8 hr/day) | 240 hrs | $7 + $38.40 = **$45/mo** |
| Always-on | 720 hrs | $7 + $115 = **$122/mo** |

## Components

### 1. GPU Scaler Controller (runs on homelab)

A Kubernetes controller that:
- Watches for pods with `nvidia.com/gpu` resource requests
- Starts/stops the GPU EC2 instance via AWS API
- Manages idle timeout

```yaml
# Deployment on homelab
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gpu-scaler
  namespace: hybrid-llm
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: gpu-scaler
          image: ghcr.io/your-org/gpu-scaler:latest
          env:
            - name: AWS_REGION
              value: us-west-2
            - name: GPU_INSTANCE_ID
              valueFrom:
                secretKeyRef:
                  name: aws-gpu-config
                  key: instance_id
            - name: IDLE_TIMEOUT
              value: "15m"
```

### 2. GPU Worker Instance (EC2)

Pre-configured AMI with:
- k3s (lightweight Kubernetes)
- Nebula (joins mesh on boot)
- NVIDIA drivers + container runtime
- Liqo agent (peers with homelab)

**Userdata flow on start:**
```bash
#!/bin/bash
# 1. Start Nebula (connect to mesh)
systemctl start nebula

# 2. Start k3s
systemctl start k3s

# 3. Liqo auto-peers via pre-configured token
# Virtual node appears in homelab cluster
```

### 3. LLM Request Flow

```
User Request
     │
     ▼
┌─────────────────────┐
│ Homelab Ingress     │
│ (Traefik)           │
└─────────────────────┘
     │
     ▼
┌─────────────────────┐
│ Ollama Service      │  ◄── If GPU node down, pod is Pending
│ (ClusterIP)         │
└─────────────────────┘
     │
     ▼
┌─────────────────────┐
│ GPU Scaler watches  │  ◄── Detects pending pod with GPU request
│ for pending pods    │
└─────────────────────┘
     │
     ▼
┌─────────────────────┐
│ Start EC2 instance  │  ◄── 2-3 min startup time
│ via AWS API         │
└─────────────────────┘
     │
     ▼
┌─────────────────────┐
│ Pod scheduled on    │  ◄── Liqo offloads to GPU node
│ GPU virtual node    │
└─────────────────────┘
     │
     ▼
┌─────────────────────┐
│ Ollama responds     │
└─────────────────────┘
```

## Implementation Options

### Option A: Simple Script-Based (MVP)

Manual or cron-triggered scripts:

```bash
# Start GPU worker
./scripts/hybrid-llm/gpu-worker.sh start

# Stop GPU worker
./scripts/hybrid-llm/gpu-worker.sh stop

# Status
./scripts/hybrid-llm/gpu-worker.sh status
```

**Pros:** Simple, works now
**Cons:** Manual intervention or basic cron, no auto-scale

### Option B: Kubernetes Controller (Recommended)

Custom controller watching for GPU pods:

```go
// Pseudo-code
func reconcile(pod *v1.Pod) {
    if pod.HasGPURequest() && pod.Status == Pending {
        if !gpuInstanceRunning() {
            startGPUInstance()
        }
    }

    if noGPUPodsFor(15 * time.Minute) {
        stopGPUInstance()
    }
}
```

**Pros:** Fully automatic, Kubernetes-native
**Cons:** More complex to build

### Option C: Karpenter (If using EKS)

Karpenter can auto-provision nodes, but:
- Requires EKS (not k3s)
- More complex networking with Nebula
- Overkill for single-node GPU

**Not recommended for this use case.**

## Startup Time Breakdown

| Phase | Time | Notes |
|-------|------|-------|
| EC2 Start | 30-60s | Instance state: stopped → running |
| OS Boot | 30-45s | Amazon Linux 2023 boot |
| Nebula Connect | 5-10s | Join mesh, handshake |
| k3s Ready | 30-45s | API server, kubelet ready |
| Liqo Peer | 10-20s | Virtual node appears |
| Pod Schedule | 5-10s | Ollama container starts |
| **Total** | **2-3 min** | Cold start to first inference |

## Reducing Cold Start

1. **Use Spot with Hibernate** - Preserves memory state, ~30s resume
2. **Pre-pull Ollama images** - Bake into AMI
3. **Pre-download models** - Store on EBS, mount on start
4. **Warm pool** - Keep instance stopped but pre-initialized

## Configuration

### Environment Variables

```bash
# GPU Scaler Config
GPU_INSTANCE_ID=i-xxxxx          # EC2 instance ID
GPU_INSTANCE_TYPE=g4dn.xlarge    # Instance type
IDLE_TIMEOUT=15m                  # Scale down after idle
SPOT_ENABLED=true                 # Use spot instances
```

### Kubernetes Labels for GPU Workloads

```yaml
# Pod that triggers scale-up
apiVersion: v1
kind: Pod
metadata:
  name: ollama
  labels:
    hybrid-llm/gpu-required: "true"
spec:
  nodeSelector:
    # Liqo virtual node
    liqo.io/type: virtual-node
    node.kubernetes.io/instance-type: g4dn.xlarge
  resources:
    limits:
      nvidia.com/gpu: 1
```

## Next Steps

1. **Create GPU Worker AMI** - Pre-baked with k3s, Nebula, NVIDIA drivers
2. **Build GPU Scaler Controller** - Go/Python controller for scale up/down
3. **Configure Liqo Peering** - Auto-peer when GPU node starts
4. **Deploy Ollama** - With proper GPU resource requests
5. **Test end-to-end** - Request → Scale up → Inference → Scale down
