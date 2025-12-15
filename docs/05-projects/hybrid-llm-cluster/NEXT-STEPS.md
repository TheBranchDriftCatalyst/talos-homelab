# Immediate Next Steps

> Manual tasks required before infrastructure deployment

## Prerequisites Checklist

### AWS Account Setup

- [ ] **AWS Account** - Dedicated account or existing one?
  - Recommendation: Use existing account with separate IAM user
  - Set up billing alerts: $50, $100, $200

- [ ] **IAM User/Role**

  ```bash
  # Create IAM user for Terraform
  aws iam create-user --user-name talos-hybrid-llm

  # Attach policies (or create custom least-privilege policy)
  aws iam attach-user-policy --user-name talos-hybrid-llm \
    --policy-arn arn:aws:iam::aws:policy/AmazonEC2FullAccess
  aws iam attach-user-policy --user-name talos-hybrid-llm \
    --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess
  aws iam attach-user-policy --user-name talos-hybrid-llm \
    --policy-arn arn:aws:iam::aws:policy/AmazonVPCFullAccess

  # Create access keys
  aws iam create-access-key --user-name talos-hybrid-llm
  ```

- [ ] **AWS Region Selection**
      | Region | GPU Spot Availability | Latency to West Coast |
      |--------|----------------------|----------------------|
      | us-west-2 | Good | ~20ms |
      | us-east-1 | Best | ~70ms |
      | us-east-2 | Good | ~60ms |

  **Recommendation**: `us-west-2` for lowest latency

- [ ] **Spot Instance Limits**

  ```bash
  # Check current vCPU limits
  aws service-quotas get-service-quota \
    --service-code ec2 \
    --quota-code L-34B43A08  # All G and VT Spot Instance Requests

  # Request increase if needed (g4dn.xlarge = 4 vCPUs)
  aws service-quotas request-service-quota-increase \
    --service-code ec2 \
    --quota-code L-34B43A08 \
    --desired-value 8
  ```

---

## Phase 0: Manual Infrastructure Setup

### 0.1 AWS Credentials

Store in 1Password or local env:

```bash
# Option A: Environment variables
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_DEFAULT_REGION="us-west-2"

# Option B: AWS CLI profile
aws configure --profile talos-hybrid-llm
```

### 0.2 Nebula CA Initialization

**CRITICAL**: This creates the root of trust. Keep `ca.key` secure!

```bash
# Create directory for Nebula CA (NOT in git!)
mkdir -p ~/.nebula-ca
cd ~/.nebula-ca

# Download Nebula binaries
NEBULA_VERSION="1.9.0"
curl -LO https://github.com/slackhq/nebula/releases/download/v${NEBULA_VERSION}/nebula-darwin-arm64.tar.gz
tar xzf nebula-darwin-arm64.tar.gz

# Generate CA (KEEP ca.key SAFE!)
./nebula-cert ca -name "talos-homelab-mesh"

# Output:
# - ca.crt (public - distribute to all nodes)
# - ca.key (PRIVATE - keep secure, never on cluster)

# Store CA key in 1Password
op item create \
  --category=document \
  --title="Nebula CA Key" \
  --vault="homelab" \
  --file-path="ca.key"

# Store CA cert (for distribution)
op item create \
  --category=document \
  --title="Nebula CA Cert" \
  --vault="homelab" \
  --file-path="ca.crt"
```

### 0.3 Nebula Lighthouse Decision

**Option A: Homelab (Free but less reliable)**

- Requires static IP or DDNS
- Requires port forwarding (UDP 4242)
- Depends on home internet uptime

**Option B: AWS t3.micro (Recommended - ~$8/month)**

- Always available
- Elastic IP for static address
- Reliable for NAT traversal

For Option B:

```bash
# Quick deploy lighthouse (before Terraform)
aws ec2 run-instances \
  --image-id ami-0c55b159cbfafe1f0 \
  --instance-type t3.micro \
  --key-name your-key \
  --security-group-ids sg-xxx \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=nebula-lighthouse}]'

# Allocate Elastic IP
aws ec2 allocate-address --domain vpc
aws ec2 associate-address --instance-id i-xxx --allocation-id eipalloc-xxx
```

### 0.4 DNS/Hosts Entries

Add to `/etc/hosts` on your Mac:

```bash
# Edit hosts file
sudo nano /etc/hosts

# Add entries (adjust IPs as needed)
# Nebula overlay network (future)
10.42.0.1   lighthouse.nebula
10.42.1.1   talos.nebula
10.42.2.1   aws-gpu.nebula

# Existing Traefik ingress
192.168.1.54  ollama.talos00
```

---

## Phase 1: Nebula Infrastructure

### 1.1 Sign Lighthouse Certificate

```bash
cd ~/.nebula-ca

# Sign lighthouse cert
./nebula-cert sign \
  -name "lighthouse" \
  -ip "10.42.0.1/16" \
  -groups "lighthouse,infrastructure"

# Store in 1Password
op item create --category=document --title="Nebula Lighthouse Cert" \
  --vault="homelab" --file-path="lighthouse.crt"
op item create --category=document --title="Nebula Lighthouse Key" \
  --vault="homelab" --file-path="lighthouse.key"
```

### 1.2 Deploy Lighthouse

SSH to lighthouse instance:

```bash
# Install Nebula
curl -LO https://github.com/slackhq/nebula/releases/download/v1.9.0/nebula-linux-amd64.tar.gz
tar xzf nebula-linux-amd64.tar.gz
sudo mv nebula /usr/local/bin/

# Create config directory
sudo mkdir -p /etc/nebula

# Copy certs (from 1Password or local)
sudo nano /etc/nebula/ca.crt      # Paste CA cert
sudo nano /etc/nebula/host.crt    # Paste lighthouse cert
sudo nano /etc/nebula/host.key    # Paste lighthouse key

# Create config
sudo nano /etc/nebula/config.yaml
```

Lighthouse config:

```yaml
pki:
  ca: /etc/nebula/ca.crt
  cert: /etc/nebula/host.crt
  key: /etc/nebula/host.key

static_host_map:
  '10.42.0.1': ['<ELASTIC_IP>:4242']

lighthouse:
  am_lighthouse: true
  interval: 60

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
      group: infrastructure
    - port: any
      proto: any
      group: kubernetes
```

Start Nebula:

```bash
# Create systemd service
sudo nano /etc/systemd/system/nebula.service
```

```ini
[Unit]
Description=Nebula VPN
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/nebula -config /etc/nebula/config.yaml
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable nebula
sudo systemctl start nebula
sudo systemctl status nebula
```

### 1.3 Sign Homelab Node Certificate

```bash
cd ~/.nebula-ca

./nebula-cert sign \
  -name "talos-homelab" \
  -ip "10.42.1.1/16" \
  -groups "homelab,kubernetes,control-plane"

# Store in 1Password for External Secrets
op item create --category=document --title="Nebula Talos Cert" \
  --vault="homelab" --file-path="talos-homelab.crt"
op item create --category=document --title="Nebula Talos Key" \
  --vault="homelab" --file-path="talos-homelab.key"
```

### 1.4 Test Connectivity

From homelab (once Nebula is deployed):

```bash
# Ping lighthouse
ping 10.42.0.1

# Check Nebula status
nebula-cert print -json -path /etc/nebula/host.crt
```

---

## Phase 2: AWS GPU Infrastructure

### 2.1 Create S3 Bucket for Models

```bash
# Create bucket with Intelligent-Tiering
aws s3api create-bucket \
  --bucket ollama-models-$(aws sts get-caller-identity --query Account --output text) \
  --region us-west-2 \
  --create-bucket-configuration LocationConstraint=us-west-2

# Enable Intelligent-Tiering
aws s3api put-bucket-intelligent-tiering-configuration \
  --bucket ollama-models-xxx \
  --id entire-bucket \
  --intelligent-tiering-configuration '{
    "Id": "entire-bucket",
    "Status": "Enabled",
    "Tierings": [
      {"Days": 90, "AccessTier": "ARCHIVE_ACCESS"},
      {"Days": 180, "AccessTier": "DEEP_ARCHIVE_ACCESS"}
    ]
  }'
```

### 2.2 Upload Initial Models

```bash
# Pull models locally (requires local Ollama)
ollama pull llama2:7b
ollama pull codellama:7b

# Sync to S3
aws s3 sync ~/.ollama/models s3://ollama-models-xxx/ \
  --storage-class INTELLIGENT_TIERING
```

### 2.3 Create VPC and Security Groups

See `terraform/hybrid-llm/` for full Terraform config.

Quick manual setup:

```bash
# Create VPC
VPC_ID=$(aws ec2 create-vpc --cidr-block 10.0.0.0/16 --query 'Vpc.VpcId' --output text)
aws ec2 create-tags --resources $VPC_ID --tags Key=Name,Value=hybrid-llm

# Create subnet
SUBNET_ID=$(aws ec2 create-subnet \
  --vpc-id $VPC_ID \
  --cidr-block 10.0.1.0/24 \
  --availability-zone us-west-2a \
  --query 'Subnet.SubnetId' --output text)

# Create security group
SG_ID=$(aws ec2 create-security-group \
  --group-name hybrid-llm-gpu \
  --description "GPU instance for LLM" \
  --vpc-id $VPC_ID \
  --query 'GroupId' --output text)

# Allow Nebula (UDP 4242)
aws ec2 authorize-security-group-ingress \
  --group-id $SG_ID \
  --protocol udp \
  --port 4242 \
  --cidr 0.0.0.0/0

# Allow SSH (temporary, for setup)
aws ec2 authorize-security-group-ingress \
  --group-id $SG_ID \
  --protocol tcp \
  --port 22 \
  --cidr YOUR_IP/32
```

---

## Phase 3: Tooling Installation

### 3.1 Install Required CLI Tools

```bash
# Nebula CLI (for cert management)
brew install nebula

# Liqo CLI
brew install liqotech/tap/liqoctl

# AWS CLI (if not installed)
brew install awscli

# Terraform
brew install terraform
```

### 3.2 Verify Tools

```bash
nebula-cert --version
liqoctl version
aws --version
terraform version
```

---

## Decision Points

Before proceeding, decide on these:

| Question            | Options               | Recommendation          |
| ------------------- | --------------------- | ----------------------- |
| AWS Region          | us-west-2, us-east-1  | us-west-2 (latency)     |
| Lighthouse location | Homelab, AWS t3.micro | AWS (reliability)       |
| K8s on AWS GPU      | k3s, kubeadm, EKS     | k3s (simplicity)        |
| Model storage       | S3 mount, init sync   | S3 mount (cost)         |
| Scale trigger       | Manual, KEDA, Lambda  | Manual first, then KEDA |

---

## Estimated Timeline

| Phase     | Tasks                      | Time           |
| --------- | -------------------------- | -------------- |
| Phase 0   | AWS setup, Nebula CA       | 1-2 hours      |
| Phase 1   | Lighthouse, homelab Nebula | 2-3 hours      |
| Phase 2   | AWS VPC, GPU instance      | 2-3 hours      |
| Phase 3   | Liqo federation            | 1-2 hours      |
| Phase 4   | Ollama deployment          | 1-2 hours      |
| **Total** |                            | **8-12 hours** |

---

## Next Action

**Start with Phase 0.2**: Generate Nebula CA

```bash
mkdir -p ~/.nebula-ca && cd ~/.nebula-ca
curl -LO https://github.com/slackhq/nebula/releases/download/v1.9.0/nebula-darwin-arm64.tar.gz
tar xzf nebula-darwin-arm64.tar.gz
./nebula-cert ca -name "talos-homelab-mesh"
```

Then store `ca.key` in 1Password immediately!
