# GPU Instance Guide for LLM Inference

## Large Context VRAM Requirements

| Model | 4K ctx | 32K ctx | 128K ctx | 200K ctx |
|-------|--------|---------|----------|----------|
| 7B (Q4) | ~5 GB | ~8 GB | ~18 GB | ~28 GB |
| 7B (Q8/FP16) | ~8 GB | ~12 GB | ~24 GB | ~36 GB |
| 13B (Q4) | ~8 GB | ~12 GB | ~24 GB | ~38 GB |
| 13B (Q8) | ~14 GB | ~20 GB | ~40 GB | ~60 GB |
| 30-34B (Q4) | ~20 GB | ~28 GB | ~52 GB | ~80 GB |
| 70B (Q4) | ~40 GB | ~52 GB | ~90 GB | ~140 GB |

## GPU Instances for Large Context

| Instance | GPU(s) | VRAM | Spot $/hr | Max Context Capability |
|----------|--------|------|-----------|------------------------|
| g4dn.xlarge | 1x T4 | 16 GB | ~$0.16 | 7B/32K or 13B/8K |
| g5.xlarge | 1x A10G | 24 GB | ~$0.40 | 7B/128K or 13B/32K |
| g5.2xlarge | 1x A10G | 24 GB | ~$0.60 | Same + more CPU/RAM |
| g6.xlarge | 1x L4 | 24 GB | ~$0.35 | 7B/128K or 13B/32K |
| g5.12xlarge | 4x A10G | 96 GB | ~$1.80 | 70B/32K or 13B/200K |
| g5.48xlarge | 8x A10G | 192 GB | ~$4.00 | 70B/128K+ |
| p4d.24xlarge | 8x A100 | 320 GB | ~$11.00 | Anything |

## AWS Quota Requirements

To use G-class instances, you need quota for "All G and VT Spot Instance Requests":

```bash
# Check current quota
aws service-quotas get-service-quota --service-code ec2 --quota-code L-3819A6DF

# Request increase (need at least 4 vCPUs for g4dn.xlarge, 8 for flexibility)
aws service-quotas request-service-quota-increase \
  --service-code ec2 \
  --quota-code L-3819A6DF \
  --desired-value 8
```

## Recommendations

| Use Case | Instance | Why |
|----------|----------|-----|
| Budget (7B models) | g4dn.xlarge | Cheapest, 16GB enough for 7B/32K |
| Best value (7B-13B) | g6.xlarge | L4 is efficient, 24GB for 128K |
| Large context (13B+) | g5.xlarge | A10G proven, 24GB VRAM |
| 70B models | g5.12xlarge | 4x A10G = 96GB total |

## Current Setup

- **llm-worker**: r5.2xlarge (CPU-only, $0.50/hr on-demand)
- **Upgrade path**: Request G quota → Convert to g5.xlarge or g6.xlarge
