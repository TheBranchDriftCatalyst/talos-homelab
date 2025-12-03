# Hybrid LLM Cluster Provisioning Recipe

This document captures the complete provisioning workflow for the Nebula mesh VPN + AWS GPU compute cluster.

## Quick Start (Automated)

The easiest way to provision the lighthouse is using the unified script:

```bash
# Full provisioning (certificates + AWS infrastructure)
./scripts/hybrid-llm/provision-lighthouse.sh

# Dry run to see what would be created
./scripts/hybrid-llm/provision-lighthouse.sh --dry-run

# Skip certificate generation (if already done)
./scripts/hybrid-llm/provision-lighthouse.sh --skip-certs

# Teardown all resources
./scripts/hybrid-llm/provision-lighthouse.sh --teardown
```

The script:
1. Generates Nebula CA and host certificates
2. Creates AWS SSH key pair
3. Creates security group (UDP 4242, SSH)
4. Allocates Elastic IP
5. Launches EC2 instance with embedded Nebula config
6. Verifies Nebula is running

State is tracked in `.output/lighthouse-state.json` for idempotent runs.

---

## Manual Steps (Reference)

The following sections document each step in detail for troubleshooting or manual execution.

## Prerequisites

1. AWS CLI configured (`aws configure`)
2. AWS account with EC2 permissions
3. Nebula installed locally (`brew install nebula`)
4. 1Password CLI configured (for secrets storage)

## Phase 1: Certificate Generation

### 1.1 Generate Nebula CA

```bash
# Create CA directory
mkdir -p ~/.nebula-ca

# Generate CA certificate (valid for 10 years)
cd ~/.nebula-ca
nebula-cert ca -name "talos-homelab-mesh" -duration 87600h

# Verify CA created
ls -la
# Output: ca.crt, ca.key
```

### 1.2 Generate Host Certificates

```bash
cd ~/.nebula-ca

# Lighthouse (AWS EC2 - will be the coordination point)
nebula-cert sign -name "lighthouse" \
  -ip "10.42.0.1/16" \
  -groups "lighthouse,infrastructure"

# Talos Homelab Node
nebula-cert sign -name "talos-homelab" \
  -ip "10.42.1.1/16" \
  -groups "kubernetes,homelab"

# AWS GPU Worker
nebula-cert sign -name "aws-gpu-worker" \
  -ip "10.42.2.1/16" \
  -groups "kubernetes,infrastructure,gpu-compute"

# Verify all certs created
ls -la
# Output: ca.crt, ca.key, lighthouse.crt, lighthouse.key,
#         talos-homelab.crt, talos-homelab.key,
#         aws-gpu-worker.crt, aws-gpu-worker.key
```

### 1.3 Copy Certificates to Project (for userdata generation)

```bash
cd /Users/panda/catalyst-devspace/workspace/talos-homelab

# Create output directories
mkdir -p .output/nebula/lighthouse

# Copy certificates
cp ~/.nebula-ca/ca.crt .output/nebula/ca.crt
cp ~/.nebula-ca/lighthouse.crt .output/nebula/lighthouse/host.crt
cp ~/.nebula-ca/lighthouse.key .output/nebula/lighthouse/host.key
```

### 1.4 Store CA Key in 1Password

Store `~/.nebula-ca/ca.key` in 1Password as document named `nebula-ca-key` for backup.

## Phase 2: AWS Infrastructure

### 2.1 Create Security Group

```bash
# Get default VPC
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" \
  --query 'Vpcs[0].VpcId' --output text --region us-west-2)

# Create security group
SG_ID=$(aws ec2 create-security-group \
  --group-name "nebula-lighthouse" \
  --description "Nebula Lighthouse - UDP 4242, SSH" \
  --vpc-id "$VPC_ID" \
  --region us-west-2 \
  --output text --query 'GroupId')

echo "Security Group: $SG_ID"
# Result: sg-073072d5da52ae513

# Add rules
aws ec2 authorize-security-group-ingress \
  --group-id "$SG_ID" \
  --protocol udp --port 4242 --cidr 0.0.0.0/0 \
  --region us-west-2

aws ec2 authorize-security-group-ingress \
  --group-id "$SG_ID" \
  --protocol tcp --port 22 --cidr 0.0.0.0/0 \
  --region us-west-2
```

### 2.2 Create SSH Key Pair

```bash
mkdir -p .output/ssh

aws ec2 create-key-pair \
  --key-name hybrid-llm-key \
  --key-type rsa \
  --key-format pem \
  --query 'KeyMaterial' \
  --output text \
  --region us-west-2 > .output/ssh/hybrid-llm-key.pem

chmod 600 .output/ssh/hybrid-llm-key.pem
```

### 2.3 Get Amazon Linux 2023 AMI

```bash
AMI_ID=$(aws ec2 describe-images \
  --owners amazon \
  --filters "Name=name,Values=al2023-ami-2023*-x86_64" \
            "Name=state,Values=available" \
  --query 'Images | sort_by(@, &CreationDate) | [-1].ImageId' \
  --output text \
  --region us-west-2)

echo "AMI: $AMI_ID"
# Result: ami-0b6d6dacf350ebc82
```

### 2.4 Generate Userdata Script

```bash
# Generate userdata with embedded certificates
./scripts/hybrid-llm/lighthouse-userdata.sh > /tmp/lighthouse-userdata.sh

# Verify it has certificates embedded
grep -c "BEGIN NEBULA" /tmp/lighthouse-userdata.sh
# Should output: 3 (CA cert, host cert, host key)
```

### 2.5 Launch EC2 Instance

```bash
INSTANCE_ID=$(aws ec2 run-instances \
  --image-id "$AMI_ID" \
  --instance-type t3.micro \
  --key-name hybrid-llm-key \
  --security-group-ids "$SG_ID" \
  --user-data file:///tmp/lighthouse-userdata.sh \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=nebula-lighthouse}]' \
  --region us-west-2 \
  --query 'Instances[0].InstanceId' \
  --output text)

echo "Instance: $INSTANCE_ID"
# Result: i-0ae1ab612e0bf1e57

# Wait for instance to be running
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID" --region us-west-2
```

### 2.6 Allocate and Associate Elastic IP

```bash
# Allocate Elastic IP
ALLOCATION=$(aws ec2 allocate-address \
  --domain vpc \
  --tag-specifications 'ResourceType=elastic-ip,Tags=[{Key=Name,Value=nebula-lighthouse}]' \
  --region us-west-2)

EIP=$(echo "$ALLOCATION" | jq -r '.PublicIp')
ALLOC_ID=$(echo "$ALLOCATION" | jq -r '.AllocationId')

echo "Elastic IP: $EIP"
echo "Allocation ID: $ALLOC_ID"
# Result: 52.13.210.163 / eipalloc-0e2b103851019ac96

# Associate with instance
aws ec2 associate-address \
  --instance-id "$INSTANCE_ID" \
  --allocation-id "$ALLOC_ID" \
  --region us-west-2
```

## Phase 3: Verification

### 3.1 SSH to Instance

```bash
ssh -i .output/ssh/hybrid-llm-key.pem ec2-user@52.13.210.163
```

### 3.2 Check Nebula Status

```bash
# On the EC2 instance:
sudo systemctl status nebula
sudo journalctl -u nebula -f

# Check Nebula is listening
sudo ss -ulnp | grep 4242
```

### 3.3 Check Bootstrap Log

```bash
# On the EC2 instance:
cat /var/log/nebula-bootstrap.log
```

## Troubleshooting

### Userdata Didn't Run

If the bootstrap log doesn't exist, the userdata script may not have been passed correctly.

**Fix: Run bootstrap manually via SSH:**

```bash
# Copy the generated userdata to the instance
scp -i .output/ssh/hybrid-llm-key.pem /tmp/lighthouse-userdata.sh ec2-user@52.13.210.163:/tmp/

# SSH and run it
ssh -i .output/ssh/hybrid-llm-key.pem ec2-user@52.13.210.163
sudo bash /tmp/lighthouse-userdata.sh
```

### Certificate Path Errors

If cloud-init shows certificate path errors like:
```
ERROR: CA certificate not found at /var/lib/cloud/.output/nebula/ca.crt
```

This means the userdata generator script was passed directly instead of its output. Regenerate:

```bash
# Ensure certs are in .output/nebula/
./scripts/hybrid-llm/lighthouse-userdata.sh > /tmp/lighthouse-userdata.sh

# Verify certs are embedded
grep "BEGIN NEBULA CERTIFICATE" /tmp/lighthouse-userdata.sh
```

### SSH Host Key Changed

If you get a host key verification error after recreating an instance:

```bash
ssh-keygen -R 52.13.210.163
```

## Reference Values

| Resource | Value |
|----------|-------|
| AWS Region | us-west-2 |
| Security Group | sg-073072d5da52ae513 |
| SSH Key | hybrid-llm-key |
| AMI | ami-0b6d6dacf350ebc82 (AL2023) |
| Instance ID | i-0ae1ab612e0bf1e57 |
| Elastic IP | 52.13.210.163 |
| Allocation ID | eipalloc-0e2b103851019ac96 |
| Nebula Lighthouse IP | 10.42.0.1 |
| Talos Homelab Nebula IP | 10.42.1.1 |
| AWS GPU Worker Nebula IP | 10.42.2.1 |

## File Locations

| File | Path |
|------|------|
| CA Certificate | ~/.nebula-ca/ca.crt |
| CA Key | ~/.nebula-ca/ca.key (backup in 1Password) |
| Lighthouse Cert | ~/.nebula-ca/lighthouse.crt |
| Lighthouse Key | ~/.nebula-ca/lighthouse.key |
| SSH Key | .output/ssh/hybrid-llm-key.pem |
| Generated Userdata | /tmp/lighthouse-userdata.sh |
| State File | .output/lighthouse-state.json |

---

## Phase 4: Kubernetes Nebula Deployment

Deploy Nebula to the Talos cluster as a DaemonSet to connect it to the mesh.

### 4.1 Deploy Nebula

```bash
kubectl apply -k infrastructure/base/nebula/
```

### 4.2 Verify Deployment

```bash
kubectl get pods -n nebula-system
# NAME           READY   STATUS    RESTARTS   AGE
# nebula-xxxxx   1/1     Running   0          1m

kubectl logs -n nebula-system -l app.kubernetes.io/name=nebula --tail=20
# Look for: "Nebula interface is active"
# Look for: "Handshake message received" from lighthouse
```

### 4.3 Test Mesh Connectivity

```bash
# From AWS lighthouse, ping the homelab
ssh -i .output/ssh/hybrid-llm-key.pem ec2-user@52.13.210.163 "ping -c 3 10.42.1.1"
# Should show ~37ms latency
```

---

## Phase 5: Liqo Multi-Cluster Federation

### 5.1 Deploy Liqo

```bash
kubectl apply -k infrastructure/base/liqo/
```

### 5.2 Verify Liqo Installation

```bash
kubectl get helmrelease -n liqo
# NAME   AGE   READY   STATUS
# liqo   1m    True    Helm install succeeded

kubectl get pods -n liqo
# All pods should be 1/1 Running

kubectl get networks.ipam.liqo.io -n liqo
# Should show pod-cidr, service-cidr, reserved networks
```

---

## Phase 6: GPU Worker (Pending Quota)

⚠️ **Requires AWS GPU Instance Quota Approval**

Check quota status:
```bash
aws service-quotas get-service-quota \
  --service-code ec2 \
  --quota-code L-3819A6DF \
  --region us-west-2 \
  --query 'Quota.Value' \
  --output text
# Currently: 0 (pending approval)
```

When approved, deploy the GPU worker:

```bash
# Generate certificate (already done)
cd ~/.nebula-ca
nebula-cert sign -name "aws-gpu-worker" \
  -ip "10.42.2.1/16" \
  -groups "kubernetes,infrastructure,gpu-compute"

# Deploy GPU worker
./scripts/hybrid-llm/provision-gpu-worker.sh
```

---

## Current Status

| Component | Status | Notes |
|-----------|--------|-------|
| Nebula CA | ✅ Complete | Stored in ~/.nebula-ca/ and 1Password |
| AWS Lighthouse | ✅ Running | 52.13.210.163, i-0ae1ab612e0bf1e57 |
| Talos Nebula | ✅ Connected | 10.42.1.1 via DaemonSet |
| Mesh Connectivity | ✅ Working | ~37ms latency between homelab and AWS |
| Liqo | ✅ Installed | Ready for cluster peering |
| GPU Quota | ⏳ Pending | Requested G-type instance quota |
| GPU Worker | ⏳ Blocked | Waiting for quota approval |

---

## Network Topology

```
┌────────────────────────────────────────────────────────────┐
│                    Nebula Mesh (10.42.0.0/16)              │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  ┌─────────────────┐        ┌─────────────────┐           │
│  │   AWS EC2       │        │  Talos Homelab  │           │
│  │   Lighthouse    │◄──────►│  (Single Node)  │           │
│  │   10.42.0.1     │  UDP   │   10.42.1.1     │           │
│  │   52.13.210.163 │  4242  │  192.168.1.54   │           │
│  └─────────────────┘        └─────────────────┘           │
│          │                          │                      │
│          │                          │                      │
│          ▼                          ▼                      │
│  ┌─────────────────┐        ┌─────────────────┐           │
│  │  GPU Worker     │        │  Liqo           │           │
│  │  (Future)       │        │  Controller     │           │
│  │  10.42.2.1      │        │  (Ready)        │           │
│  │  g4dn.xlarge    │        │                 │           │
│  └─────────────────┘        └─────────────────┘           │
│                                                            │
└────────────────────────────────────────────────────────────┘
```
