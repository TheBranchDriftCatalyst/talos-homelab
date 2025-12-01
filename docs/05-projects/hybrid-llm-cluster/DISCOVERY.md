# Hybrid LLM Cluster Discovery Document

> **Project**: On-demand GPU compute for Ollama via AWS EC2 + Nebula mesh + Liqo federation
> **Status**: Discovery/Planning
> **Created**: 2025-01-28

## Executive Summary

This project adds on-demand LLM inference capability to the Talos homelab cluster by:

1. **Nebula Mesh VPN** - Secure overlay network connecting homelab to AWS
2. **Liqo Multi-Cluster Federation** - Seamless pod offloading to remote clusters
3. **AWS EC2 GPU Spot Instances** - Cost-effective on-demand GPU compute (up to 90% savings)
4. **Ollama** - Self-hosted LLM inference engine

The architecture allows LLM workloads to be scheduled from the homelab cluster and transparently executed on AWS GPU instances, with automatic spin-up/spin-down based on demand.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              NEBULA MESH OVERLAY                             │
│                           (Encrypted P2P Network)                            │
└─────────────────────────────────────────────────────────────────────────────┘
         │                           │                           │
         ▼                           ▼                           ▼
┌─────────────────┐        ┌─────────────────┐        ┌─────────────────────┐
│   LIGHTHOUSE    │        │  HOMELAB CLUSTER │        │   AWS GPU CLUSTER   │
│   (Always On)   │        │  (Control Plane) │        │   (On-Demand)       │
├─────────────────┤        ├─────────────────┤        ├─────────────────────┤
│ - Nebula CA     │        │ - Talos Linux   │        │ - EC2 GPU Instance  │
│ - Discovery     │        │ - 192.168.1.54  │        │ - g4dn/g5/p3        │
│ - NAT Traversal │        │ - Liqo Consumer │        │ - Liqo Provider     │
│                 │        │ - Ollama Client │        │ - Ollama Server     │
│ (t3.micro EC2   │        │                 │        │ - NVIDIA Drivers    │
│  or homelab)    │        │                 │        │ - Spot Instance     │
└─────────────────┘        └─────────────────┘        └─────────────────────┘
                                    │                           │
                                    │      Liqo Peering         │
                                    │◄─────────────────────────►│
                                    │   (Virtual Kubelet)       │
                                    │                           │
                           ┌────────▼────────┐         ┌────────▼────────┐
                           │  Virtual Node   │         │  Physical Node  │
                           │  "aws-gpu-01"   │◄───────►│  GPU Workloads  │
                           │  (Liqo VK)      │  Pods   │  (Ollama)       │
                           └─────────────────┘         └─────────────────┘
```

---

## Component Deep Dives

### 1. Nebula Mesh VPN

#### What is Nebula?

[Nebula](https://github.com/slackhq/nebula) is a scalable overlay networking tool created by Slack, open-sourced in 2019. It powers Slack's global network of 50,000+ production hosts.

#### Key Features

| Feature | Description |
|---------|-------------|
| **Peer-to-Peer** | Direct connections between nodes, no hub-and-spoke bottleneck |
| **NAT Traversal** | UDP hole punching works through most firewalls/NATs |
| **Certificate-Based** | Mutual authentication via signed certificates |
| **Encryption** | ECDH key exchange + AES-256-GCM |
| **Lightweight** | Single static binary, minimal resource usage |
| **Cross-Platform** | Linux, macOS, Windows, iOS, Android |

#### Architecture Components

1. **Certificate Authority (CA)**
   - Generates and signs node certificates
   - Defines network trust boundary
   - CA private key kept offline/secure

2. **Lighthouse Nodes**
   - Always-on nodes with static/routable IPs
   - Enable peer discovery
   - Facilitate NAT hole punching
   - Can be hosted on cheap EC2 t3.micro or at home

3. **Regular Nodes**
   - Get certificates from CA
   - Connect to lighthouses for discovery
   - Establish direct P2P tunnels with peers

#### Why Nebula over Alternatives?

| Solution | Pros | Cons |
|----------|------|------|
| **Nebula** | Self-hosted, no dependencies, performant, Slack-proven | More manual setup |
| **Tailscale** | Easy setup, managed | Dependency on Tailscale infra, costs at scale |
| **WireGuard** | Native in Talos, fast | No built-in discovery, more manual config |
| **OpenVPN** | Widely supported | Slower, heavier, hub-and-spoke |

#### Nebula IP Addressing

```yaml
# Example Nebula network plan
nebula_network: 10.42.0.0/16

nodes:
  lighthouse:
    nebula_ip: 10.42.0.1/16
    public_ip: <EC2 Elastic IP or home static>

  talos-homelab:
    nebula_ip: 10.42.1.1/16
    groups: [homelab, kubernetes, control-plane]

  aws-gpu-worker:
    nebula_ip: 10.42.2.1/16
    groups: [aws, kubernetes, gpu, worker]
```

---

### 2. Liqo Multi-Cluster Federation

#### What is Liqo?

[Liqo](https://liqo.io/) enables dynamic and seamless Kubernetes multi-cluster topologies. It creates "virtual nodes" representing remote clusters, allowing the local scheduler to transparently offload pods.

#### Core Concepts

1. **Peering**
   - Establishes trust between two clusters
   - Negotiates resource quotas
   - Creates secure communication channel

2. **Virtual Nodes**
   - Appear as regular nodes in `kubectl get nodes`
   - Represent aggregated resources from remote cluster
   - Default: 90% of remote cluster resources exposed

3. **Offloading**
   - Pods scheduled on virtual nodes run in remote cluster
   - Twin namespaces created automatically
   - ShadowPods ensure resilience during disconnects

4. **Network Fabric**
   - Transparent pod-to-pod connectivity across clusters
   - Pod-to-service works across boundaries
   - CNI-agnostic (works with any CNI plugin)

#### How Liqo Works

```
┌─────────────────────────────────────────────────────────────────┐
│                     HOMELAB CLUSTER (Consumer)                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  kubectl get nodes                                               │
│  ┌─────────────────┬─────────────────┬─────────────────────────┐│
│  │ NAME            │ STATUS          │ ROLES                   ││
│  ├─────────────────┼─────────────────┼─────────────────────────┤│
│  │ talos-node-01   │ Ready           │ control-plane,master    ││
│  │ liqo-aws-gpu    │ Ready           │ virtual-node            ││ ◄── Virtual!
│  └─────────────────┴─────────────────┴─────────────────────────┘│
│                                                                  │
│  Deployment: ollama                                              │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │ nodeSelector:                                                ││
│  │   node-type: gpu                                             ││
│  │   topology.liqo.io/type: virtual-node                        ││
│  └──────────────────────────────────────────────────────────────┘│
│                            │                                     │
│                            ▼ Liqo Virtual Kubelet                │
└────────────────────────────┬────────────────────────────────────┘
                             │
                    Nebula VPN Tunnel
                             │
                             ▼
┌────────────────────────────┴────────────────────────────────────┐
│                     AWS GPU CLUSTER (Provider)                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ShadowPod created → Real Pod runs here                          │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │ Pod: ollama-xxxxx                                            ││
│  │ Node: gpu-worker-01 (g4dn.xlarge)                            ││
│  │ GPU: NVIDIA T4                                               ││
│  └──────────────────────────────────────────────────────────────┘│
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

#### Liqo Installation

```bash
# On both clusters
helm repo add liqo https://helm.liqo.io/
helm repo update

# Install Liqo
helm install liqo liqo/liqo \
  --namespace liqo-system \
  --create-namespace \
  --set networking.internal=false \  # We use Nebula for networking
  --set auth.config.enableAuthentication=true

# On homelab (consumer): Generate peering command
liqoctl generate peer-command

# On AWS cluster (provider): Execute the peering command
liqoctl peer out-of-band <homelab-cluster> \
  --auth-url https://... \
  --cluster-id ...
```

#### Offloading Namespaces

```bash
# Create namespace for LLM workloads
kubectl create namespace llm-inference

# Enable offloading to AWS GPU cluster only
liqoctl offload namespace llm-inference \
  --namespace-mapping-strategy EnforceSameName \
  --pod-offloading-strategy Remote \
  --selector 'node-type=gpu'
```

---

### 3. AWS EC2 GPU Instances

#### Recommended Instance Types for Ollama

| Instance | GPU | VRAM | Spot Price* | Use Case |
|----------|-----|------|-------------|----------|
| **g4dn.xlarge** | 1x T4 | 16GB | ~$0.16/hr | Small models (7B) |
| **g4dn.2xlarge** | 1x T4 | 16GB | ~$0.23/hr | More CPU/RAM |
| **g5.xlarge** | 1x A10G | 24GB | ~$0.40/hr | Medium models (13B) |
| **g5.2xlarge** | 1x A10G | 24GB | ~$0.48/hr | More CPU/RAM |
| **p3.2xlarge** | 1x V100 | 16GB | ~$0.92/hr | Fastest inference |

*Spot prices vary by region and time. Can be 60-90% off on-demand.

#### Deep Learning AMIs

Use AWS Deep Learning AMIs (pre-installed NVIDIA drivers + CUDA):
- **Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 22.04)**
- Saves 30+ minutes of driver installation

#### Spot Instance Strategy

```yaml
# Karpenter NodePool for GPU spot instances
apiVersion: karpenter.sh/v1beta1
kind: NodePool
metadata:
  name: gpu-spot
spec:
  template:
    spec:
      requirements:
        - key: "karpenter.sh/capacity-type"
          operator: In
          values: ["spot"]
        - key: "node.kubernetes.io/instance-type"
          operator: In
          values: ["g4dn.xlarge", "g4dn.2xlarge", "g5.xlarge"]
        - key: "kubernetes.io/arch"
          operator: In
          values: ["amd64"]
      nodeClassRef:
        name: gpu-node-class
  limits:
    nvidia.com/gpu: 2  # Max 2 GPUs across all nodes
  disruption:
    consolidationPolicy: WhenEmpty
    consolidateAfter: 5m  # Terminate if unused for 5 minutes
```

---

### 4. Ollama Deployment

#### Ollama on Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ollama
  namespace: llm-inference
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ollama
  template:
    metadata:
      labels:
        app: ollama
    spec:
      nodeSelector:
        node-type: gpu
        # Forces scheduling on Liqo virtual node → AWS
        topology.liqo.io/type: virtual-node
      containers:
        - name: ollama
          image: ollama/ollama:latest
          ports:
            - containerPort: 11434
          resources:
            limits:
              nvidia.com/gpu: 1
          volumeMounts:
            - name: ollama-data
              mountPath: /root/.ollama
      volumes:
        - name: ollama-data
          persistentVolumeClaim:
            claimName: ollama-models
---
apiVersion: v1
kind: Service
metadata:
  name: ollama
  namespace: llm-inference
spec:
  selector:
    app: ollama
  ports:
    - port: 11434
      targetPort: 11434
```

#### Accessing Ollama from Homelab

Thanks to Liqo's network fabric, you can access the Ollama service directly:

```bash
# From any pod in homelab cluster
curl http://ollama.llm-inference.svc.cluster.local:11434/api/generate \
  -d '{"model": "llama2", "prompt": "Hello!"}'

# Or via IngressRoute for external access
# ollama.talos00 → Traefik → Liqo → AWS → Ollama
```

---

## Implementation Phases

### Phase 1: Nebula Infrastructure (Week 1)

- [ ] Set up Nebula CA (secure location)
- [ ] Deploy lighthouse node (t3.micro or home server)
- [ ] Install Nebula on Talos homelab node
- [ ] Test basic connectivity

### Phase 2: AWS GPU Cluster (Week 2)

- [ ] Create VPC and networking in AWS
- [ ] Set up EC2 launch template with Deep Learning AMI
- [ ] Configure Auto Scaling Group with spot instances
- [ ] Install Kubernetes (k3s or kubeadm) on GPU instance
- [ ] Join to Nebula mesh

### Phase 3: Liqo Federation (Week 2-3)

- [ ] Install Liqo on both clusters
- [ ] Establish peering
- [ ] Verify virtual node appears in homelab
- [ ] Test namespace offloading

### Phase 4: Ollama Deployment (Week 3)

- [ ] Deploy Ollama to GPU cluster via Liqo
- [ ] Configure model storage (S3 or EBS)
- [ ] Set up IngressRoute for external access
- [ ] Test inference from homelab

### Phase 5: Automation & Scaling (Week 4+)

- [ ] Implement scale-to-zero (Karpenter or custom)
- [ ] Add monitoring (GPU utilization, costs)
- [ ] Create Terraform/Pulumi for reproducibility
- [ ] Document operational procedures

---

## Cost Estimation

### Always-On Costs

| Component | Instance | Monthly Cost |
|-----------|----------|--------------|
| Nebula Lighthouse | t3.micro | ~$8 |
| Elastic IP | 1x | ~$4 |
| **Total Always-On** | | **~$12/month** |

### On-Demand GPU Costs (Spot)

| Usage Pattern | Instance | Hours/Month | Monthly Cost |
|---------------|----------|-------------|--------------|
| Light (2hr/day) | g4dn.xlarge | 60 | ~$10 |
| Medium (8hr/day) | g4dn.xlarge | 240 | ~$38 |
| Heavy (24/7) | g4dn.xlarge | 720 | ~$115 |

### Storage Costs

| Component | Size | Monthly Cost |
|-----------|------|--------------|
| EBS gp3 (models) | 100GB | ~$8 |
| S3 (model cache) | 50GB | ~$1 |

**Estimated Total: $30-150/month** depending on usage.

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Spot instance interruption | LLM inference fails | Use spot fleet with multiple instance types; persist models to EBS |
| Nebula VPN instability | Cluster partitions | Multiple lighthouses; health monitoring |
| Liqo complexity | Debugging difficulty | Start simple; good logging/monitoring |
| Latency (coast-to-coast) | Slow inference | Choose AWS region close to home |
| Cost overrun | Budget exceeded | Set billing alarms; enforce scale-to-zero |

---

## Open Questions

1. **Lighthouse placement**: Home server (free but depends on home internet) vs EC2 (reliable but $12/month)?

2. **AWS region**: Which region is closest and has best spot availability for GPU instances?

3. **Kubernetes on AWS**: Use k3s (simpler) or full kubeadm (more compatible)?

4. **Model storage**: EBS (simpler) or S3 with caching (cheaper for large model libraries)?

5. **Scale trigger**: HTTP request-based (KEDA) or manual?

---

## References

### Nebula
- [Nebula GitHub](https://github.com/slackhq/nebula)
- [Nebula Documentation](https://nebula.defined.net/docs/)
- [Slack Engineering Blog: Introducing Nebula](https://slack.engineering/introducing-nebula-the-open-source-global-overlay-network-from-slack/)

### Liqo
- [Liqo Documentation](https://docs.liqo.io/)
- [Liqo GitHub](https://github.com/liqotech/liqo)
- [Liqo Offloading Guide](https://docs.liqo.io/en/stable/features/offloading.html)
- [Offloading with Policies](https://docs.liqo.io/en/stable/examples/offloading-with-policies.html)

### AWS GPU
- [AWS GPU Instance Types](https://aws.amazon.com/ec2/instance-types/#gpu-instances)
- [Running GPU Workloads on EKS](https://aws.amazon.com/blogs/compute/running-gpu-accelerated-kubernetes-workloads-on-p3-and-p2-ec2-instances-with-amazon-eks/)
- [Karpenter for Spot Instances](https://docs.aws.amazon.com/eks/latest/best-practices/aiml-compute.html)

### Ollama
- [Ollama GitHub](https://github.com/ollama/ollama)
- [Installing Ollama on AWS EC2](https://developer.searchblox.com/docs/installing-ollama-on-aws-ec2)

---

## Next Steps

1. **Decide on open questions** (see above)
2. **Create Nebula CA** and generate initial certificates
3. **Deploy lighthouse** (start with EC2 t3.micro for reliability)
4. **Document Nebula setup** for Talos nodes
