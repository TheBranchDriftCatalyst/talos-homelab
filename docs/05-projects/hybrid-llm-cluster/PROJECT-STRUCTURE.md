# Hybrid LLM Cluster - Project Structure

> Directory organization and GitOps patterns for the multi-cluster setup

## Directory Structure

```
talos-homelab/
├── clusters/
│   ├── catalyst-cluster/           # Existing - Talos homelab control plane
│   │   ├── flux-system/
│   │   ├── cluster-settings.yaml
│   │   └── hybrid-llm.yaml       # NEW - Kustomization for hybrid-llm
│   │
│   └── aws-gpu/                  # NEW - AWS GPU worker cluster definition
│       ├── flux-system/          # Optional if using Flux on AWS side
│       ├── cluster-settings.yaml # AWS-specific settings
│       └── liqo-provider.yaml    # Liqo provider config
│
├── infrastructure/
│   └── base/
│       ├── hybrid-llm/           # NEW - Multi-cluster LLM infrastructure
│       │   ├── kustomization.yaml
│       │   ├── namespace.yaml
│       │   │
│       │   ├── nebula/           # Nebula mesh VPN components
│       │   │   ├── kustomization.yaml
│       │   │   ├── namespace.yaml
│       │   │   ├── configmap.yaml       # Nebula config (non-sensitive)
│       │   │   ├── daemonset.yaml       # Nebula agent on nodes
│       │   │   ├── external-secret.yaml # CA cert, node certs from 1Password
│       │   │   └── README.md
│       │   │
│       │   ├── liqo/             # Liqo federation components
│       │   │   ├── kustomization.yaml
│       │   │   ├── helmrelease.yaml     # Liqo Helm chart
│       │   │   ├── peering-secret.yaml  # Peering credentials
│       │   │   ├── resource-offer.yaml  # Resource sharing config
│       │   │   └── README.md
│       │   │
│       │   └── ollama/           # Ollama LLM inference
│       │       ├── kustomization.yaml
│       │       ├── deployment.yaml
│       │       ├── service.yaml
│       │       ├── ingressroute.yaml
│       │       ├── pvc-models.yaml      # S3 CSI PVC
│       │       └── README.md
│       │
│       └── ... (existing infra)
│
├── applications/
│   └── hybrid-llm/               # NEW - Application layer (if needed)
│       └── open-webui/           # Optional: Web UI for Ollama
│
├── configs/
│   └── aws-gpu/                  # NEW - AWS GPU cluster configs
│       ├── nebula-lighthouse.yaml
│       ├── nebula-worker.yaml
│       └── k3s-config.yaml
│
├── scripts/
│   └── hybrid-llm/               # NEW - Automation scripts
│       ├── nebula-ca-init.sh           # Initialize Nebula CA
│       ├── nebula-cert-sign.sh         # Sign new node certs
│       ├── aws-gpu-provision.sh        # Provision AWS GPU instance
│       ├── aws-gpu-teardown.sh         # Terminate GPU instance
│       ├── liqo-peer.sh                # Establish Liqo peering
│       └── ollama-model-sync.sh        # Sync models to S3
│
├── terraform/                    # NEW - AWS infrastructure as code
│   └── hybrid-llm/
│       ├── main.tf
│       ├── variables.tf
│       ├── outputs.tf
│       ├── vpc.tf
│       ├── ec2-gpu.tf
│       ├── s3-models.tf
│       └── iam.tf
│
└── docs/
    └── hybrid-llm-cluster/       # Project documentation (CURRENT)
        ├── DISCOVERY.md          # Architecture overview
        ├── TODO.md               # Implementation tasks
        ├── STORAGE-STRATEGY.md   # S3 model storage
        ├── PROJECT-STRUCTURE.md  # THIS FILE
        ├── GITOPS-PATTERNS.md    # Multi-cluster GitOps
        └── RUNBOOKS/
            ├── nebula-troubleshooting.md
            ├── liqo-troubleshooting.md
            └── gpu-scaling.md
```

---

## GitOps Patterns for Multi-Cluster

### Challenge: Two Clusters, One Repo

We have:

1. **Homelab Cluster** (Talos) - Control plane, Liqo consumer
2. **AWS GPU Cluster** (k3s) - Worker, Liqo provider

Both need manifests, but they're different clusters with different lifecycles.

### Pattern Options

#### Option A: Single Repo, Cluster Overlays (Recommended)

```
infrastructure/
├── base/
│   └── hybrid-llm/
│       ├── nebula/           # Shared Nebula base config
│       ├── liqo/             # Shared Liqo base
│       └── ollama/           # Ollama deployment
│
└── overlays/
    ├── homelab/
    │   └── hybrid-llm/
    │       ├── kustomization.yaml  # Patches for homelab
    │       ├── nebula-patch.yaml   # Homelab Nebula IP
    │       └── liqo-consumer.yaml  # Consumer config
    │
    └── aws-gpu/
        └── hybrid-llm/
            ├── kustomization.yaml  # Patches for AWS
            ├── nebula-patch.yaml   # AWS Nebula IP
            └── liqo-provider.yaml  # Provider config
```

**How it works:**

- Base manifests are shared
- Overlays customize per cluster
- Each cluster's Flux/ArgoCD points to its overlay

#### Option B: Separate Repos

```
talos-homelab/              # Homelab infrastructure
├── infrastructure/
│   └── hybrid-llm/
│       ├── nebula/
│       ├── liqo-consumer/
│       └── ollama/

aws-gpu-cluster/            # Separate repo for AWS
├── infrastructure/
│   ├── nebula/
│   ├── liqo-provider/
│   └── nvidia-device-plugin/
```

**When to use:**

- Different teams own each cluster
- Different security boundaries
- Very different release cycles

#### Option C: Git Branch per Cluster

```
main branch        → Homelab cluster
aws-gpu branch     → AWS GPU cluster
```

**Avoid this** - Hard to maintain, merge conflicts, confusing history.

---

### Recommended: Overlay Pattern with Cluster Selectors

```yaml
# clusters/catalyst-cluster/hybrid-llm.yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: hybrid-llm
  namespace: flux-system
spec:
  interval: 10m
  sourceRef:
    kind: GitRepository
    name: flux-system
  path: ./infrastructure/overlays/homelab/hybrid-llm
  prune: true
  healthChecks:
    - apiVersion: apps/v1
      kind: DaemonSet
      name: nebula
      namespace: hybrid-llm
```

```yaml
# For AWS cluster (deployed via Liqo or separate Flux)
# infrastructure/overlays/aws-gpu/hybrid-llm/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../../base/hybrid-llm/nebula
  - ../../../base/hybrid-llm/liqo

patches:
  - target:
      kind: ConfigMap
      name: nebula-config
    patch: |
      - op: replace
        path: /data/nebula.yaml
        value: |
          # AWS-specific Nebula config
          static_host_map:
            "10.42.0.1": ["<lighthouse-ip>:4242"]
          lighthouse:
            am_lighthouse: false
          listen:
            host: 0.0.0.0
            port: 4242
```

---

## Node Labels and Targeting

### Label Strategy

```yaml
# Homelab node labels
kubectl label node talos-node-01 \
  topology.kubernetes.io/region=homelab \
  topology.kubernetes.io/zone=rack-01 \
  node-type=general \
  gpu=false

# AWS GPU node labels (applied via k3s config or post-deploy)
kubectl label node aws-gpu-worker-01 \
  topology.kubernetes.io/region=aws-us-east-1 \
  topology.kubernetes.io/zone=us-east-1a \
  node-type=gpu \
  gpu=true \
  gpu-type=nvidia-t4

# Liqo virtual node inherits labels from provider
# When peered, homelab sees:
# liqo-aws-gpu-01   Ready   virtual-node   node-type=gpu,gpu=true
```

### Targeting Workloads

```yaml
# Ollama - MUST run on GPU node (AWS via Liqo)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ollama
  namespace: llm-inference
spec:
  template:
    spec:
      nodeSelector:
        node-type: gpu
        # This ensures scheduling on Liqo virtual node
        # which offloads to AWS GPU cluster
      tolerations:
        - key: 'nvidia.com/gpu'
          operator: 'Exists'
          effect: 'NoSchedule'
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: topology.liqo.io/type
                    operator: In
                    values:
                      - virtual-node
```

```yaml
# Nebula - MUST run on physical nodes (both clusters)
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: nebula
spec:
  template:
    spec:
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: topology.liqo.io/type
                    operator: NotIn
                    values:
                      - virtual-node
```

---

## Advanced Topics to Research

### 1. Liqo Resource Negotiation

- How to limit resources shared by AWS cluster
- Dynamic resource adjustment based on spot availability
- Resource quotas for cost control

### 2. Network Policies Across Clusters

- Pod-to-pod communication via Liqo network fabric
- Restricting traffic to Ollama service only
- Nebula firewall rules for cluster communication

### 3. Secrets Management Across Clusters

- Nebula certificates (need to be on both clusters)
- AWS credentials for S3 access
- 1Password Connect integration on AWS side?
- Or use AWS Secrets Manager on AWS side?

### 4. Observability Across Clusters

- Metrics from AWS GPU node → Homelab Prometheus?
- Logs from Ollama → Homelab Graylog?
- Or separate observability stack on AWS?

### 5. Spot Instance Handling

- Graceful shutdown on spot termination
- Model state persistence
- Automatic re-provisioning

### 6. Cost Allocation

- Tagging AWS resources for cost tracking
- Chargeback/showback for GPU usage
- Budget alerts

### 7. Security Considerations

- Nebula certificate rotation
- Liqo authentication between clusters
- Network segmentation
- Audit logging

---

## Implementation Order

Based on dependencies:

```
Phase 1: Foundation
├── 1.1 Nebula CA and Lighthouse
├── 1.2 Nebula on Homelab
└── 1.3 Test mesh connectivity

Phase 2: AWS Infrastructure
├── 2.1 Terraform for VPC, EC2, S3
├── 2.2 k3s on GPU instance
├── 2.3 Nebula on AWS
└── 2.4 Test cross-cloud connectivity

Phase 3: Federation
├── 3.1 Liqo on Homelab
├── 3.2 Liqo on AWS
├── 3.3 Establish peering
└── 3.4 Test pod offloading

Phase 4: Workloads
├── 4.1 S3 model bucket
├── 4.2 Mountpoint CSI driver
├── 4.3 Ollama deployment
└── 4.4 IngressRoute + testing

Phase 5: Automation
├── 5.1 Scale-to-zero automation
├── 5.2 Monitoring dashboards
├── 5.3 Runbooks
└── 5.4 Cost optimization
```

---

## Next Steps

1. **Create base manifests** in `infrastructure/base/hybrid-llm/`
2. **Set up Terraform** in `terraform/hybrid-llm/`
3. **Create overlay structure** for homelab vs AWS
4. **Document GitOps patterns** in `GITOPS-PATTERNS.md`
