# Ollama LLM Inference

> Self-hosted large language model inference on GPU

## Overview

Ollama provides a simple way to run large language models locally. In this setup:
- Ollama runs on AWS GPU instances via Liqo offloading
- Models are stored in S3 Intelligent-Tiering (cost-optimized)
- Access via IngressRoute from homelab

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    HOMELAB CLUSTER                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  IngressRoute: ollama.talos00                                    │
│       │                                                          │
│       ▼                                                          │
│  Service: ollama (ClusterIP)                                     │
│       │                                                          │
│       │  Liqo Network Fabric                                     │
│       │  (Transparent cross-cluster routing)                     │
│       ▼                                                          │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                    AWS GPU CLUSTER                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Pod: ollama-xxxxx                                               │
│  ├── Container: ollama (ollama/ollama:latest)                   │
│  │   ├── Port: 11434                                            │
│  │   ├── GPU: nvidia.com/gpu: 1                                 │
│  │   └── Model Dir: /root/.ollama                               │
│  │                                                               │
│  └── Volumes:                                                    │
│      ├── models (S3 Mountpoint) → /root/.ollama/models          │
│      └── cache (emptyDir NVMe) → /var/cache/ollama              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    S3 INTELLIGENT-TIERING                        │
│              s3://ollama-models-<account-id>                     │
├─────────────────────────────────────────────────────────────────┤
│  llama2/                                                         │
│  ├── manifest                                                    │
│  └── blobs/                                                      │
│      └── sha256-xxxxx (model weights)                           │
│                                                                  │
│  codellama/                                                      │
│  mistral/                                                        │
│  ...                                                             │
└─────────────────────────────────────────────────────────────────┘
```

## Components

| File | Description |
|------|-------------|
| `kustomization.yaml` | Kustomize entrypoint |
| `deployment.yaml` | Ollama deployment with GPU |
| `service.yaml` | ClusterIP service |
| `ingressroute.yaml` | Traefik IngressRoute |
| `pvc-models.yaml` | S3 Mountpoint PVC for models |

## Prerequisites

1. **Liqo Peering** - AWS cluster accessible as virtual node
2. **NVIDIA Device Plugin** - On AWS cluster
3. **Mountpoint S3 CSI Driver** - On AWS cluster
4. **S3 Bucket** - With models uploaded

## Deployment

```bash
# Apply Ollama manifests
kubectl apply -k infrastructure/base/hybrid-llm/ollama/

# Verify pod scheduled on virtual node
kubectl get pods -n llm-inference -o wide

# Check GPU allocation
kubectl describe pod -n llm-inference ollama-xxx
```

## Model Management

### Uploading Models to S3

```bash
# Pull model locally
ollama pull llama2:7b

# Sync to S3
aws s3 sync ~/.ollama/models s3://ollama-models-xxx/ \
  --storage-class INTELLIGENT_TIERING
```

### Pulling Models in Cluster

```bash
# Exec into Ollama pod
kubectl exec -n llm-inference -it deploy/ollama -- bash

# Pull model (will cache locally)
ollama pull llama2:7b
```

Note: With S3 mount, models are streamed on-demand. First inference may be slower.

## API Usage

### From within cluster

```bash
# Port-forward for local testing
kubectl port-forward -n llm-inference svc/ollama 11434:11434

# Generate text
curl http://localhost:11434/api/generate -d '{
  "model": "llama2",
  "prompt": "Why is the sky blue?"
}'
```

### Via IngressRoute

```bash
# Requires /etc/hosts entry: 192.168.1.54 ollama.talos00
curl http://ollama.talos00/api/generate -d '{
  "model": "llama2",
  "prompt": "Hello!"
}'
```

## Resource Requirements

| Model | VRAM | RAM | Instance |
|-------|------|-----|----------|
| Llama2 7B | ~4GB | 8GB | g4dn.xlarge |
| Llama2 13B | ~8GB | 16GB | g4dn.xlarge |
| CodeLlama 34B | ~18GB | 32GB | g5.xlarge |
| Llama2 70B | ~40GB | 64GB | g5.12xlarge |

## GPU Scheduling

The deployment uses:

```yaml
nodeSelector:
  node-type: gpu
  topology.liqo.io/type: virtual-node

tolerations:
  - key: "nvidia.com/gpu"
    operator: "Exists"
    effect: "NoSchedule"

resources:
  limits:
    nvidia.com/gpu: 1
```

This ensures:
1. Only schedules on GPU-labeled nodes
2. Only schedules on Liqo virtual node (→ AWS)
3. Requests exactly 1 GPU

## Performance Tuning

### Memory Mapping

Ollama uses memory-mapped files for model loading:

```yaml
env:
  - name: OLLAMA_FLASH_ATTENTION
    value: "1"
  - name: OLLAMA_NUM_PARALLEL
    value: "2"
```

### Keep-Alive

For faster repeated queries:

```yaml
env:
  - name: OLLAMA_KEEP_ALIVE
    value: "5m"  # Keep model in memory for 5 minutes
```

## Troubleshooting

```bash
# Check pod status
kubectl get pods -n llm-inference

# View logs
kubectl logs -n llm-inference deploy/ollama

# Check GPU is visible
kubectl exec -n llm-inference deploy/ollama -- nvidia-smi

# Test model loading
kubectl exec -n llm-inference deploy/ollama -- ollama list
```

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Pod pending | No GPU available | Check spot instance is running |
| OOMKilled | Model too large | Use smaller model or larger instance |
| Slow inference | First load from S3 | Pre-cache popular models |
| Connection refused | Service not ready | Wait for pod to be Running |

## References

- [Ollama GitHub](https://github.com/ollama/ollama)
- [Ollama API Documentation](https://github.com/ollama/ollama/blob/main/docs/api.md)
- [AWS Deep Learning AMIs](https://docs.aws.amazon.com/dlami/)
