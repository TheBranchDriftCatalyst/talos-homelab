# LLM Model Storage Strategy

> Optimizing storage costs for Ollama models in a hybrid cloud setup

## The Challenge

Ollama models are **large** (4GB - 70GB each) and accessed **infrequently** (only when GPU node is running). We need:

1. **Lowest possible storage cost** when models are idle
2. **Fast retrieval** when GPU node spins up
3. **Persistent storage** that survives spot instance termination

---

## Storage Options Comparison

### Cost Breakdown (100GB of models, us-east-1)

| Storage Type | $/GB/month | 100GB/month | Retrieval Cost | Best For |
|--------------|------------|-------------|----------------|----------|
| **EBS gp3** | $0.08 | $8.00 | None | Always-attached |
| **S3 Standard** | $0.023 | $2.30 | $0.0004/1K req | Frequent access |
| **S3 Intelligent-Tiering** | $0.0025-0.023 | $0.25-2.30 | None | Unknown patterns |
| **S3 Standard-IA** | $0.0125 | $1.25 | $0.01/GB | Weekly access |
| **S3 Glacier Instant** | $0.004 | $0.40 | $0.03/GB | Rare but fast |
| **S3 Glacier Flexible** | $0.0036 | $0.36 | 3-5 hr retrieval | Archive |

### Key Insight

**S3 Intelligent-Tiering** is the sweet spot:
- Automatically moves to Archive Instant Access tier after 90 days idle
- **No retrieval fees** (unlike Glacier Instant)
- Same millisecond access as Glacier Instant when in Archive tier
- Handles unpredictable access patterns

---

## Recommended Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        S3 INTELLIGENT-TIERING                           │
│                     s3://ollama-models-<account-id>                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Frequent Access        Infrequent Access       Archive Instant Access  │
│  (First 30 days)        (30-90 days idle)       (90+ days idle)         │
│  ┌─────────────┐        ┌─────────────┐         ┌─────────────┐         │
│  │ llama2:7b   │───────►│ codellama   │────────►│ mistral:7b  │         │
│  │ (active)    │        │ (unused)    │         │ (archived)  │         │
│  └─────────────┘        └─────────────┘         └─────────────┘         │
│                                                                          │
│  $0.023/GB              $0.0125/GB              $0.004/GB               │
│  (full price)           (40% savings)           (68% savings)           │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ Mountpoint S3 CSI Driver
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         AWS GPU INSTANCE                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  /root/.ollama/models (S3 mount - read-only)                            │
│  ┌──────────────────────────────────────────┐                           │
│  │ manifest files, blobs (model weights)    │                           │
│  └──────────────────────────────────────────┘                           │
│                                                                          │
│  /var/cache/ollama (Local NVMe - read-write cache)                      │
│  ┌──────────────────────────────────────────┐                           │
│  │ Active model loaded into memory          │                           │
│  │ KV cache, runtime state                  │                           │
│  └──────────────────────────────────────────┘                           │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Implementation Options

### Option 1: Mountpoint S3 CSI Driver (Recommended)

AWS's official solution for mounting S3 as a filesystem in Kubernetes.

**Pros:**
- Official AWS support
- Works with S3 Intelligent-Tiering
- Good performance for large sequential reads
- No retrieval fees with Intelligent-Tiering

**Cons:**
- Read-only for S3 standard (read-write with S3 Express)
- Some POSIX limitations
- Requires IAM configuration

**Implementation:**

```yaml
# StorageClass for S3 Mountpoint
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: s3-models
provisioner: s3.csi.aws.com
parameters:
  bucketName: ollama-models-${AWS_ACCOUNT_ID}
---
# PersistentVolume for Ollama models
apiVersion: v1
kind: PersistentVolume
metadata:
  name: ollama-models-pv
spec:
  capacity:
    storage: 500Gi  # Logical limit
  accessModes:
    - ReadOnlyMany
  storageClassName: s3-models
  csi:
    driver: s3.csi.aws.com
    volumeHandle: ollama-models-bucket
    volumeAttributes:
      bucketName: ollama-models-${AWS_ACCOUNT_ID}
---
# PVC for Ollama deployment
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ollama-models
  namespace: llm-inference
spec:
  accessModes:
    - ReadOnlyMany
  storageClassName: s3-models
  resources:
    requests:
      storage: 500Gi
```

```yaml
# Ollama Deployment with S3 mount
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ollama
  namespace: llm-inference
spec:
  template:
    spec:
      containers:
        - name: ollama
          image: ollama/ollama:latest
          volumeMounts:
            - name: models
              mountPath: /root/.ollama/models
              readOnly: true
            - name: cache
              mountPath: /var/cache/ollama
      volumes:
        - name: models
          persistentVolumeClaim:
            claimName: ollama-models
        - name: cache
          emptyDir:
            sizeLimit: 50Gi  # Uses instance NVMe
```

### Option 2: Init Container with S3 Sync

Pre-download models from S3 to local storage on pod startup.

**Pros:**
- Simpler (no CSI driver needed)
- Full POSIX support
- Can write back to S3

**Cons:**
- Slower startup (download entire model)
- Uses more local storage
- Models not shared across pods

**Implementation:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ollama
  namespace: llm-inference
spec:
  template:
    spec:
      initContainers:
        - name: model-sync
          image: amazon/aws-cli:latest
          command:
            - /bin/sh
            - -c
            - |
              # Sync models from S3
              aws s3 sync s3://ollama-models-${AWS_ACCOUNT_ID}/ /models/ \
                --exclude "*" \
                --include "llama2/*" \
                --include "codellama/*"
          volumeMounts:
            - name: models
              mountPath: /models
          env:
            - name: AWS_REGION
              value: us-east-1
      containers:
        - name: ollama
          image: ollama/ollama:latest
          volumeMounts:
            - name: models
              mountPath: /root/.ollama
      volumes:
        - name: models
          emptyDir:
            sizeLimit: 100Gi
```

### Option 3: Hybrid - S3 + Local Cache (goofys)

Mount S3 with aggressive local caching using goofys.

**Pros:**
- Good read performance with caching
- Lower S3 request costs
- Works well with large sequential reads

**Cons:**
- Requires privileged pods
- goofys project less actively maintained
- More complex setup

---

## Model Management Workflow

### Uploading New Models

```bash
# On a local machine or CI/CD
ollama pull llama2:7b
ollama pull codellama:13b

# Export and upload to S3
OLLAMA_MODELS=~/.ollama/models
aws s3 sync $OLLAMA_MODELS s3://ollama-models-${AWS_ACCOUNT_ID}/ \
  --storage-class INTELLIGENT_TIERING
```

### Syncing Models to S3 (Automation)

```yaml
# CronJob to sync new models (runs on homelab)
apiVersion: batch/v1
kind: CronJob
metadata:
  name: ollama-model-sync
  namespace: llm-inference
spec:
  schedule: "0 2 * * *"  # 2 AM daily
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: sync
              image: amazon/aws-cli:latest
              command:
                - /bin/sh
                - -c
                - |
                  aws s3 sync /models/ s3://ollama-models-${AWS_ACCOUNT_ID}/ \
                    --storage-class INTELLIGENT_TIERING \
                    --delete
              volumeMounts:
                - name: models
                  mountPath: /models
          restartPolicy: OnFailure
          volumes:
            - name: models
              hostPath:
                path: /var/lib/ollama/models
```

---

## Cost Projections

### Scenario: 200GB of Models, Light Usage (2hr/day GPU)

| Component | Calculation | Monthly Cost |
|-----------|-------------|--------------|
| S3 (Intelligent-Tiering, Archive tier) | 200GB × $0.004 | $0.80 |
| S3 Requests (model loads) | ~1000 GET × $0.0004 | $0.04 |
| S3 Data Transfer (to EC2, same region) | Free | $0.00 |
| **Total Storage** | | **~$1/month** |

Compare to:
- EBS gp3 (200GB): $16/month
- EBS gp3 snapshot: $10/month

**Savings: 90-95% on storage costs**

### Scenario: 500GB of Models, Medium Usage (8hr/day GPU)

| Component | Calculation | Monthly Cost |
|-----------|-------------|--------------|
| S3 (Mixed tiers, avg $0.01/GB) | 500GB × $0.01 | $5.00 |
| S3 Requests | ~5000 GET × $0.0004 | $0.20 |
| **Total Storage** | | **~$5/month** |

Compare to:
- EBS gp3 (500GB): $40/month

---

## Tradeoffs Summary

| Approach | Storage Cost | Startup Time | Complexity |
|----------|--------------|--------------|------------|
| **S3 Intelligent-Tiering + Mountpoint** | Lowest ($0.004-0.023/GB) | Fast (stream) | Medium |
| **S3 + Init Sync** | Low ($0.004-0.023/GB) | Slow (download) | Low |
| **EBS gp3** | Highest ($0.08/GB) | Instant | Lowest |
| **EBS Snapshot** | Medium ($0.05/GB) | Medium (restore) | Low |

---

## Recommendation

**Use S3 Intelligent-Tiering with Mountpoint CSI Driver:**

1. **Cheapest long-term storage** - Models in Archive tier at $0.004/GB
2. **No retrieval fees** - Unlike Glacier Instant Retrieval
3. **Automatic tier management** - AWS handles optimization
4. **Fast access** - Millisecond retrieval even from Archive tier
5. **Survives spot termination** - Models persist in S3

**Estimated monthly cost: $1-5** for 200-500GB of models.

---

## Implementation Checklist

- [ ] Create S3 bucket with Intelligent-Tiering
- [ ] Configure bucket policy for EC2 access
- [ ] Install Mountpoint S3 CSI Driver on AWS cluster
- [ ] Create StorageClass and PV/PVC
- [ ] Test Ollama with S3-mounted models
- [ ] Create model upload automation
- [ ] Set up lifecycle rules (optional cleanup)
- [ ] Configure cost alerts

---

## References

- [Mountpoint S3 CSI Driver](https://github.com/awslabs/mountpoint-s3-csi-driver)
- [S3 Intelligent-Tiering](https://docs.aws.amazon.com/AmazonS3/latest/userguide/intelligent-tiering-overview.html)
- [S3 Storage Classes](https://aws.amazon.com/s3/storage-classes/)
- [Ollama Model Storage](https://markaicode.com/clear-ollama-model-cache-storage-guide/)
