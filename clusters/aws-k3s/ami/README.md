# Catalyst Fleet AMI Templates

Packer templates for building pre-baked AMIs for the Catalyst hybrid cluster.

## AMI Types

| AMI | Description | Instance Types |
|-----|-------------|----------------|
| `base` | Common foundation (Nebula + worker-agent) | t3.medium |
| `lighthouse` | k3s server + Liqo + Nebula lighthouse | t3.medium |
| `gpu-worker` | NVIDIA drivers + Ollama + k3s agent | g4dn.xlarge, g5.xlarge |

## Prerequisites

1. **Build the Go binaries first:**
   ```bash
   # From tools/carrierarr/
   make build-linux
   ```

2. **Install Packer:**
   ```bash
   brew install packer
   ```

3. **AWS credentials configured:**
   ```bash
   aws configure
   # Or set AWS_PROFILE
   ```

## Building AMIs

```bash
# Initialize Packer plugins
packer init .

# Build all AMIs
make ami-all

# Build specific AMI
make ami-base
make ami-lighthouse
make ami-gpu-worker

# Or use Packer directly with custom vars
packer build -only=gpu-worker.* -var 'aws_region=us-west-2' .
```

## Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `aws_region` | us-east-1 | AWS region to build in |
| `nebula_version` | 1.9.0 | Nebula VPN version |
| `k3s_version` | v1.31.2+k3s1 | k3s version |
| `nvidia_driver_version` | 550 | NVIDIA driver major version |
| `ollama_version` | latest | Ollama version |
| `ami_prefix` | catalyst | AMI name prefix |

## Runtime Configuration

At boot time, minimal userdata scripts inject secrets and configuration:

- **Nebula certificates** - From AWS Secrets Manager
- **k3s token/URL** - For cluster joining
- **Control plane address** - For worker-agent registration

See `userdata/` for the bootstrap scripts used at instance launch.

## Directory Structure

```
ami/
├── variables.pkr.hcl     # Shared variables
├── base.pkr.hcl          # Base AMI template
├── lighthouse.pkr.hcl    # Lighthouse AMI template
├── gpu-worker.pkr.hcl    # GPU worker AMI template
├── userdata/
│   ├── lighthouse.sh     # Lighthouse bootstrap script
│   └── gpu-worker.sh     # GPU worker bootstrap script
├── base/scripts/         # Base provisioner scripts
├── lighthouse/scripts/   # Lighthouse provisioner scripts
└── gpu-worker/scripts/   # GPU worker provisioner scripts
```

## Cold Start Time Comparison

| Stage | Before (userdata) | After (AMI) |
|-------|-------------------|-------------|
| Instance start | 30s | 30s |
| Package install | 120s | 0s |
| NVIDIA drivers | 180s | 0s |
| Ollama install | 30s | 0s |
| k3s install | 60s | 0s |
| Config + secrets | 30s | 30s |
| **Total** | **~8 min** | **~1 min** |

## Security Notes

- AMIs contain no secrets (certificates injected at boot)
- worker-agent uses Nebula VPN for all control plane communication
- k3s uses Nebula interface for cluster networking
- AWS Secrets Manager stores all credentials
