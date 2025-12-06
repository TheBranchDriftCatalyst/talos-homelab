# GitOps Patterns for Multi-Cluster Setup

> Managing two clusters with different lifecycles from a single repository

## The Challenge

We have two distinct clusters:

| Cluster | Location | Lifecycle | GitOps Tool | Role |
|---------|----------|-----------|-------------|------|
| **Homelab** | On-prem (Talos) | Always-on | Flux | Liqo Consumer |
| **AWS GPU** | Cloud (k3s) | On-demand | None/Manual | Liqo Provider |

The AWS cluster is ephemeral - it spins up when needed and shuts down when idle. This creates unique GitOps challenges.

---

## Pattern: Asymmetric GitOps

### Homelab Cluster (Full GitOps)

```
┌─────────────────────────────────────────────────────────────────┐
│                    HOMELAB CLUSTER                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Flux CD                                                         │
│  ├── GitRepository: talos-homelab (this repo)                   │
│  ├── Kustomization: infrastructure                              │
│  │   └── path: ./infrastructure/overlays/homelab                │
│  └── Kustomization: hybrid-llm                                  │
│       └── path: ./infrastructure/overlays/homelab/hybrid-llm    │
│                                                                  │
│  ArgoCD (for applications)                                       │
│  ├── Application: catalyst-ui                                   │
│  ├── Application: arr-stack                                     │
│  └── Application: open-webui (future)                           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### AWS GPU Cluster (Bootstrap Only)

```
┌─────────────────────────────────────────────────────────────────┐
│                    AWS GPU CLUSTER                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Bootstrap Script (runs once on instance start)                  │
│  ├── Install k3s                                                 │
│  ├── Install NVIDIA device plugin                                │
│  ├── Install Nebula (join mesh)                                  │
│  ├── Install Liqo (provider mode)                                │
│  ├── Apply static manifests                                      │
│  └── kubectl apply -k ./infrastructure/overlays/aws-gpu         │
│                                                                  │
│  NO continuous GitOps - instance is ephemeral                    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Why Not Full GitOps on AWS?

1. **Instance is ephemeral** - Destroyed when not in use
2. **No persistent storage** - Flux state would be lost
3. **Fast bootstrap needed** - Can't wait for reconciliation loops
4. **Cost** - Running Flux controllers costs money

---

## Repository Structure

```
talos-homelab/
├── infrastructure/
│   ├── base/
│   │   └── hybrid-llm/           # Shared base manifests
│   │       ├── nebula/
│   │       ├── liqo/
│   │       └── ollama/
│   │
│   └── overlays/
│       ├── homelab/
│       │   └── hybrid-llm/       # Homelab-specific patches
│       │       ├── kustomization.yaml
│       │       ├── nebula-config.yaml   # Homelab Nebula IP
│       │       └── liqo-consumer.yaml   # Consumer config
│       │
│       └── aws-gpu/
│           └── hybrid-llm/       # AWS-specific patches
│               ├── kustomization.yaml
│               ├── nebula-config.yaml   # AWS Nebula IP
│               ├── liqo-provider.yaml   # Provider config
│               └── nvidia-plugin.yaml   # GPU driver config
│
├── clusters/
│   └── catalyst-cluster/
│       └── hybrid-llm.yaml       # Flux Kustomization
│
└── scripts/
    └── hybrid-llm/
        └── aws-bootstrap.sh      # EC2 user-data script
```

---

## Flux Configuration (Homelab)

```yaml
# clusters/catalyst-cluster/hybrid-llm.yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: hybrid-llm
  namespace: flux-system
spec:
  interval: 10m
  retryInterval: 1m
  timeout: 5m
  sourceRef:
    kind: GitRepository
    name: flux-system
  path: ./infrastructure/overlays/homelab/hybrid-llm
  prune: true
  wait: true
  healthChecks:
    - apiVersion: apps/v1
      kind: DaemonSet
      name: nebula
      namespace: nebula-system
  dependsOn:
    - name: external-secrets  # For Nebula certs
```

---

## AWS Bootstrap Script

This runs as EC2 user-data when the GPU instance starts:

```bash
#!/bin/bash
# scripts/hybrid-llm/aws-bootstrap.sh

set -euo pipefail

# Configuration
NEBULA_VERSION="1.9.0"
K3S_VERSION="v1.29.0+k3s1"
LIQO_VERSION="0.10.0"
HOMELAB_REPO="https://github.com/yourusername/talos-homelab.git"
NEBULA_LIGHTHOUSE_IP="<LIGHTHOUSE_ELASTIC_IP>"

echo "=== Installing k3s ==="
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=$K3S_VERSION sh -s - \
  --disable traefik \
  --disable servicelb \
  --node-label node-type=gpu \
  --node-label gpu=true

# Wait for k3s
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
until kubectl get nodes; do sleep 5; done

echo "=== Installing NVIDIA Device Plugin ==="
kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.1/nvidia-device-plugin.yml

echo "=== Installing Nebula ==="
curl -LO https://github.com/slackhq/nebula/releases/download/v${NEBULA_VERSION}/nebula-linux-amd64.tar.gz
tar xzf nebula-linux-amd64.tar.gz
mv nebula /usr/local/bin/

# Fetch Nebula certs from AWS Secrets Manager
aws secretsmanager get-secret-value --secret-id nebula/ca-crt --query SecretString --output text > /etc/nebula/ca.crt
aws secretsmanager get-secret-value --secret-id nebula/aws-gpu-crt --query SecretString --output text > /etc/nebula/host.crt
aws secretsmanager get-secret-value --secret-id nebula/aws-gpu-key --query SecretString --output text > /etc/nebula/host.key

# Configure Nebula
cat > /etc/nebula/config.yaml <<EOF
pki:
  ca: /etc/nebula/ca.crt
  cert: /etc/nebula/host.crt
  key: /etc/nebula/host.key

static_host_map:
  "10.42.0.1": ["${NEBULA_LIGHTHOUSE_IP}:4242"]

lighthouse:
  am_lighthouse: false
  hosts:
    - "10.42.0.1"

listen:
  host: 0.0.0.0
  port: 4242

punchy:
  punch: true

firewall:
  outbound:
    - port: any
      proto: any
      host: any
  inbound:
    - port: any
      proto: any
      group: kubernetes
    - port: any
      proto: any
      group: homelab
EOF

systemctl enable nebula
systemctl start nebula

# Wait for Nebula mesh
until ping -c 1 10.42.1.1; do sleep 5; done

echo "=== Installing Liqo ==="
curl -sL https://get.liqo.io | LIQO_VERSION=$LIQO_VERSION bash

# Configure as provider
liqoctl install k3s \
  --cluster-name aws-gpu \
  --set networking.internal=false \
  --set auth.config.enableAuthentication=true

echo "=== Applying AWS overlay manifests ==="
git clone --depth 1 $HOMELAB_REPO /tmp/talos-homelab
kubectl apply -k /tmp/talos-homelab/infrastructure/overlays/aws-gpu/hybrid-llm

echo "=== Bootstrap complete ==="
```

---

## Node Labeling Strategy

### Standard Labels

```yaml
# All nodes
kubernetes.io/os: linux
kubernetes.io/arch: amd64

# Topology
topology.kubernetes.io/region: homelab | aws-us-west-2
topology.kubernetes.io/zone: rack-01 | us-west-2a

# Custom
node-type: general | gpu
gpu: "true" | "false"
gpu-type: nvidia-t4 | nvidia-a10g  # if gpu=true
```

### Liqo-Specific Labels

```yaml
# Applied automatically by Liqo to virtual nodes
topology.liqo.io/type: virtual-node
liqo.io/remote-cluster-id: aws-gpu-cluster-xxx
```

---

## Workload Targeting

### Run on Homelab Only

```yaml
spec:
  template:
    spec:
      nodeSelector:
        topology.kubernetes.io/region: homelab
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: topology.liqo.io/type
                    operator: NotIn
                    values: ["virtual-node"]
```

### Run on AWS GPU Only (via Liqo)

```yaml
spec:
  template:
    spec:
      nodeSelector:
        node-type: gpu
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: topology.liqo.io/type
                    operator: In
                    values: ["virtual-node"]
      tolerations:
        - key: "nvidia.com/gpu"
          operator: "Exists"
          effect: "NoSchedule"
```

### Run on Either (Prefer GPU)

```yaml
spec:
  template:
    spec:
      affinity:
        nodeAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              preference:
                matchExpressions:
                  - key: node-type
                    operator: In
                    values: ["gpu"]
```

---

## Secrets Management Across Clusters

### Homelab: 1Password + External Secrets

```yaml
# infrastructure/base/hybrid-llm/nebula/external-secret.yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: nebula-certs
  namespace: nebula-system
spec:
  secretStoreRef:
    name: onepassword
    kind: ClusterSecretStore
  target:
    name: nebula-certs
  data:
    - secretKey: ca.crt
      remoteRef:
        key: Nebula CA Cert
        property: file
    - secretKey: host.crt
      remoteRef:
        key: Nebula Talos Cert
        property: file
    - secretKey: host.key
      remoteRef:
        key: Nebula Talos Key
        property: file
```

### AWS: AWS Secrets Manager

```bash
# Store Nebula certs in AWS Secrets Manager
aws secretsmanager create-secret \
  --name nebula/ca-crt \
  --secret-string "$(cat ca.crt)"

aws secretsmanager create-secret \
  --name nebula/aws-gpu-crt \
  --secret-string "$(cat aws-gpu-worker.crt)"

aws secretsmanager create-secret \
  --name nebula/aws-gpu-key \
  --secret-string "$(cat aws-gpu-worker.key)"
```

EC2 IAM role policy:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "arn:aws:secretsmanager:us-west-2:*:secret:nebula/*"
    }
  ]
}
```

---

## Deployment Workflow

### Initial Setup (One-time)

```bash
# 1. Deploy hybrid-llm infrastructure to homelab
flux reconcile kustomization hybrid-llm

# 2. Verify Nebula is running
kubectl get pods -n nebula-system

# 3. Provision AWS infrastructure (Terraform)
cd terraform/hybrid-llm
terraform apply

# 4. Start GPU instance (triggers bootstrap)
aws ec2 start-instances --instance-ids i-xxx

# 5. Wait for Liqo peering
liqoctl status peer

# 6. Verify virtual node
kubectl get nodes
# Should show: liqo-aws-gpu
```

### Day-to-Day Operations

```bash
# Start GPU workload
aws ec2 start-instances --instance-ids i-xxx
# Wait ~5 minutes for bootstrap
# Ollama becomes available

# Stop GPU workload (save money)
aws ec2 stop-instances --instance-ids i-xxx
# Virtual node goes NotReady, pods evicted
```

---

## Monitoring Across Clusters

### Option A: Federated Prometheus (Complex)

- Homelab Prometheus scrapes AWS Prometheus
- Requires persistent Prometheus on AWS
- Higher cost

### Option B: Push-Based Metrics (Recommended)

```yaml
# On AWS cluster, push metrics to homelab
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-remote-write
data:
  prometheus.yml: |
    remote_write:
      - url: http://10.42.1.1:9090/api/v1/write
        # Via Nebula mesh to homelab Prometheus
```

### Option C: Logs Only

- GPU pod logs flow through Liqo network fabric
- `kubectl logs -n llm-inference deploy/ollama` works from homelab
- No additional infrastructure needed

---

## Cost Optimization

### Auto-Stop Idle Instances

CloudWatch + Lambda to stop instance after idle period:

```python
# Lambda function (simplified)
import boto3

def handler(event, context):
    cw = boto3.client('cloudwatch')
    ec2 = boto3.client('ec2')

    # Get GPU utilization
    response = cw.get_metric_data(
        MetricDataQueries=[{
            'Id': 'gpu',
            'MetricStat': {
                'Metric': {
                    'Namespace': 'CWAgent',
                    'MetricName': 'nvidia_smi_utilization_gpu',
                    'Dimensions': [{'Name': 'InstanceId', 'Value': INSTANCE_ID}]
                },
                'Period': 300,
                'Stat': 'Average'
            }
        }],
        StartTime=datetime.now() - timedelta(minutes=30),
        EndTime=datetime.now()
    )

    # If GPU idle for 30 minutes, stop
    if all(v < 5 for v in response['MetricDataResults'][0]['Values']):
        ec2.stop_instances(InstanceIds=[INSTANCE_ID])
```

### Scheduled Start/Stop

```bash
# Start at 9 AM, stop at 6 PM (weekdays)
aws events put-rule \
  --name gpu-start-weekday \
  --schedule-expression "cron(0 9 ? * MON-FRI *)"

aws events put-rule \
  --name gpu-stop-weekday \
  --schedule-expression "cron(0 18 ? * MON-FRI *)"
```

---

## Summary

| Aspect | Homelab | AWS GPU |
|--------|---------|---------|
| GitOps Tool | Flux CD | Bootstrap script |
| Manifest Sync | Continuous | On-start only |
| Secrets | 1Password + ESO | AWS Secrets Manager |
| Lifecycle | Permanent | Ephemeral |
| Monitoring | Full Prometheus | Push to homelab |
| Updates | Git push → Flux | Re-bootstrap |

This asymmetric approach balances the benefits of GitOps on the permanent homelab cluster with the practical needs of an ephemeral GPU cluster.
