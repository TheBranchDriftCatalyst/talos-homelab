# AWS EC2 Instance Types for LLM Workloads

> Quick reference for GPU and compute instance types

## The Quota You Requested: "All G and VT Spot Instance Requests"

This quota controls how many **vCPUs** you can use across all G-series and VT-series spot instances combined.

### What Are G and VT Instances?

| Series | Purpose | GPU Type | Use Case |
|--------|---------|----------|----------|
| **G4dn** | Graphics + ML inference | NVIDIA T4 | **Best for Ollama** - cost effective |
| **G4ad** | Graphics (AMD) | AMD Radeon Pro | Gaming, graphics (not for ML) |
| **G5** | Graphics + ML | NVIDIA A10G | Larger models, faster inference |
| **G5g** | Graphics (ARM) | NVIDIA T4G | ARM workloads |
| **G6** | Latest gen ML | NVIDIA L4 | Newest, most efficient |
| **VT1** | Video transcoding | Xilinx U30 | Video encoding (not for ML) |

**For Ollama/LLM inference, you want: G4dn, G5, or G6**

---

## Instance Breakdown: G4dn (Best Value for Ollama)

| Instance | vCPUs | RAM | GPU | VRAM | Spot $/hr* | Good For |
|----------|-------|-----|-----|------|------------|----------|
| **g4dn.xlarge** | 4 | 16 GB | 1x T4 | 16 GB | ~$0.16 | 7B models |
| g4dn.2xlarge | 8 | 32 GB | 1x T4 | 16 GB | ~$0.23 | 7B + more RAM |
| g4dn.4xlarge | 16 | 64 GB | 1x T4 | 16 GB | ~$0.36 | CPU-heavy work |
| g4dn.8xlarge | 32 | 128 GB | 1x T4 | 16 GB | ~$0.68 | Big context windows |
| g4dn.12xlarge | 48 | 192 GB | 4x T4 | 64 GB | ~$1.20 | Multiple models |
| g4dn.16xlarge | 64 | 256 GB | 1x T4 | 16 GB | ~$1.36 | Huge RAM needs |

*Spot prices vary by region and time. These are approximate for us-west-2.

---

## Instance Breakdown: G5 (More Power)

| Instance | vCPUs | RAM | GPU | VRAM | Spot $/hr* | Good For |
|----------|-------|-----|-----|------|------------|----------|
| **g5.xlarge** | 4 | 16 GB | 1x A10G | 24 GB | ~$0.40 | 13B models |
| g5.2xlarge | 8 | 32 GB | 1x A10G | 24 GB | ~$0.48 | 13B + more RAM |
| g5.4xlarge | 16 | 64 GB | 1x A10G | 24 GB | ~$0.65 | Larger context |
| g5.8xlarge | 32 | 128 GB | 1x A10G | 24 GB | ~$0.98 | Production loads |
| g5.12xlarge | 48 | 192 GB | 4x A10G | 96 GB | ~$1.80 | 70B models |
| g5.24xlarge | 96 | 384 GB | 4x A10G | 96 GB | ~$2.50 | Multi-model serving |

---

## Spot vs On-Demand vs Reserved

| Type | Cost | Availability | Interruption | Best For |
|------|------|--------------|--------------|----------|
| **Spot** | 60-90% off | Variable | Can be interrupted (2 min warning) | Dev, batch, fault-tolerant |
| **On-Demand** | Full price | Always | Never | Production, critical workloads |
| **Reserved** | 30-60% off | Guaranteed | Never | 24/7 workloads, 1-3 year commit |

**For Ollama (on-demand inference):** Spot is perfect because:
- Inference is stateless (can restart)
- We're not running 24/7
- 60-90% savings is huge on GPU instances

---

## What Models Fit Where?

| Model | Parameters | VRAM Needed | Minimum Instance |
|-------|------------|-------------|------------------|
| Llama 3.2 1B | 1B | ~2 GB | g4dn.xlarge |
| Llama 3.2 3B | 3B | ~3 GB | g4dn.xlarge |
| **Llama 2 7B** | 7B | ~4 GB | g4dn.xlarge |
| Mistral 7B | 7B | ~4 GB | g4dn.xlarge |
| **Llama 2 13B** | 13B | ~8 GB | g4dn.xlarge |
| CodeLlama 34B | 34B | ~18 GB | g5.xlarge (24GB VRAM) |
| Llama 2 70B | 70B | ~40 GB | g5.12xlarge (4x A10G) |

**Note:** These are for Q4 quantized models. Full precision needs ~2x VRAM.

---

## vCPU Quota Math

Your quota request was for **vCPUs**, not instances:

| Instance | vCPUs | With 8 vCPU Quota |
|----------|-------|-------------------|
| g4dn.xlarge | 4 | Can run 2 |
| g4dn.2xlarge | 8 | Can run 1 |
| g5.xlarge | 4 | Can run 2 |
| g5.2xlarge | 8 | Can run 1 |

**8 vCPUs is enough for:**
- 2x g4dn.xlarge (for testing/redundancy)
- 1x g4dn.2xlarge (more RAM)
- 1x g5.xlarge (more VRAM for bigger models)

---

## Our Plan: Start Small, Scale Up

### Phase 1: While Waiting for GPU Quota
- Use **t3.micro** for Nebula lighthouse (~$8/month)
- Get all infrastructure ready

### Phase 2: GPU Quota Approved (8 vCPUs)
- Use **g4dn.xlarge** (4 vCPUs, $0.16/hr spot)
- Run Llama 2 7B, Mistral 7B, CodeLlama 7B
- Perfect for most use cases

### Phase 3: If You Need More
- Upgrade to **g5.xlarge** for 13B+ models
- Or request more vCPU quota for multiple instances

---

## Cost Estimates

### Light Usage (2 hours/day)
| Instance | Hours/Month | Spot Cost |
|----------|-------------|-----------|
| g4dn.xlarge | 60 | ~$10 |
| g5.xlarge | 60 | ~$24 |

### Medium Usage (8 hours/day)
| Instance | Hours/Month | Spot Cost |
|----------|-------------|-----------|
| g4dn.xlarge | 240 | ~$38 |
| g5.xlarge | 240 | ~$96 |

### Always-On (24/7) - Not Recommended for Spot
| Instance | Hours/Month | Spot Cost |
|----------|-------------|-----------|
| g4dn.xlarge | 720 | ~$115 |
| g5.xlarge | 720 | ~$288 |

---

## Checking Spot Prices

```bash
# Current spot price for g4dn.xlarge in us-west-2
aws ec2 describe-spot-price-history \
  --instance-types g4dn.xlarge \
  --product-descriptions "Linux/UNIX" \
  --start-time $(date -u +"%Y-%m-%dT%H:%M:%SZ") \
  --query 'SpotPriceHistory[*].[AvailabilityZone,SpotPrice]' \
  --output table

# Compare multiple instance types
aws ec2 describe-spot-price-history \
  --instance-types g4dn.xlarge g4dn.2xlarge g5.xlarge \
  --product-descriptions "Linux/UNIX" \
  --start-time $(date -u +"%Y-%m-%dT%H:%M:%SZ") \
  --query 'SpotPriceHistory[*].[InstanceType,AvailabilityZone,SpotPrice]' \
  --output table
```

---

## Quick Reference

**For Ollama on a budget:** `g4dn.xlarge` - $0.16/hr spot, runs 7B-13B models

**For larger models (34B+):** `g5.xlarge` - $0.40/hr spot, 24GB VRAM

**Quota needed:** 4-8 vCPUs is plenty to start
