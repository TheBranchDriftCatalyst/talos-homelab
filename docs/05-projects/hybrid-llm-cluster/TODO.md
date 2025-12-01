# Hybrid LLM Cluster - Project TODO

> Track implementation progress for the Nebula + Liqo + AWS GPU project

## Legend
- [ ] Not started
- [~] In progress
- [x] Complete
- [!] Blocked

---

## Phase 1: Nebula Infrastructure

### 1.1 Certificate Authority Setup
- [ ] Generate Nebula CA key pair
- [ ] Secure CA private key (1Password? Offline storage?)
- [ ] Document CA key rotation procedure
- [ ] Create certificate signing process

### 1.2 Lighthouse Deployment
- [ ] **Decision**: Home server vs EC2 t3.micro
- [ ] Provision lighthouse host
- [ ] Install Nebula binary
- [ ] Generate lighthouse certificate
- [ ] Configure lighthouse (static IP, port 4242/UDP)
- [ ] Open firewall ports (4242/UDP inbound)
- [ ] Test lighthouse is reachable

### 1.3 Talos Homelab Node
- [ ] Research Nebula on Talos Linux (extension? DaemonSet?)
- [ ] Generate node certificate
- [ ] Configure Nebula (lighthouse address, groups)
- [ ] Deploy Nebula to Talos
- [ ] Verify connectivity to lighthouse
- [ ] Test P2P tunnel establishment

### 1.4 Nebula Documentation
- [ ] Document CA management
- [ ] Document node onboarding process
- [ ] Create certificate template for new nodes
- [ ] Add troubleshooting guide

---

## Phase 2: AWS Infrastructure

### 2.1 AWS Account Setup
- [ ] Create dedicated AWS account (or use existing)
- [ ] Set up IAM roles for EC2
- [ ] Configure billing alerts ($50, $100, $200)
- [ ] Enable Spot Instance advisor access

### 2.2 Networking
- [ ] Create VPC (10.0.0.0/16 or similar)
- [ ] Create public subnet (for Nebula)
- [ ] Create private subnet (optional, for worker nodes)
- [ ] Configure security groups
  - [ ] Nebula: 4242/UDP from anywhere
  - [ ] Kubernetes: 6443/TCP from Nebula network
  - [ ] Ollama: 11434/TCP from Nebula network
- [ ] Set up NAT Gateway (if using private subnet)

### 2.3 EC2 Configuration
- [ ] Find Deep Learning AMI ID for target region
- [ ] Create launch template
  - [ ] Instance types: g4dn.xlarge, g5.xlarge
  - [ ] Spot instance request
  - [ ] User data script (install k3s + Nebula)
- [ ] Create Auto Scaling Group
  - [ ] Min: 0, Max: 1, Desired: 0
  - [ ] Spot allocation strategy: lowest-price
- [ ] Create EBS volume for models (100GB gp3)

### 2.4 GPU Instance Bootstrap Script
- [ ] Install Nebula and join mesh
- [ ] Install k3s (single node mode)
- [ ] Install NVIDIA device plugin
- [ ] Install Liqo
- [ ] Mount model storage
- [ ] Health check endpoint

---

## Phase 3: Liqo Federation

### 3.1 Liqo on Homelab
- [ ] Install Liqo via Helm
- [ ] Configure for out-of-band networking (Nebula)
- [ ] Generate peering credentials
- [ ] Create LLM inference namespace

### 3.2 Liqo on AWS
- [ ] Install Liqo via k3s Helm
- [ ] Configure as resource provider
- [ ] Set resource limits (share 90%)
- [ ] Label nodes (node-type=gpu)

### 3.3 Establish Peering
- [ ] Exchange peering credentials
- [ ] Establish bidirectional peering
- [ ] Verify virtual node appears in homelab
- [ ] Test pod offloading (simple nginx)

### 3.4 Namespace Offloading
- [ ] Create llm-inference namespace
- [ ] Configure offloading policy (Remote only)
- [ ] Verify twin namespace in AWS cluster
- [ ] Test pod scheduling to virtual node

---

## Phase 4: Ollama Deployment

### 4.1 Ollama Manifests
- [ ] Create Deployment (GPU-aware)
- [ ] Create Service
- [ ] Create PVC for models
- [ ] Create IngressRoute (optional)

### 4.2 Model Management
- [ ] Pre-pull base models (llama2, codellama)
- [ ] Configure model storage path
- [ ] Create model pull job/script

### 4.3 Testing
- [ ] Test inference from homelab pod
- [ ] Test inference from homelab CLI
- [ ] Test inference from external (via Traefik)
- [ ] Benchmark latency and throughput

---

## Phase 5: Automation & Operations

### 5.1 Scale-to-Zero
- [ ] Research options (KEDA, custom controller, Lambda trigger)
- [ ] Implement scale-up trigger (HTTP request? queue?)
- [ ] Implement scale-down (idle timeout)
- [ ] Test end-to-end scaling

### 5.2 Infrastructure as Code
- [ ] Create Terraform/Pulumi for AWS resources
- [ ] Create Helm chart for Ollama deployment
- [ ] Create shell scripts for common operations
- [ ] Version control all configs

### 5.3 Monitoring
- [ ] GPU utilization metrics (DCGM exporter)
- [ ] Ollama request metrics
- [ ] Cost tracking dashboard
- [ ] Alerting (Slack/Discord)

### 5.4 Documentation
- [ ] Operational runbook
- [ ] Troubleshooting guide
- [ ] Cost optimization tips
- [ ] Security considerations

---

## Open Decisions

| Decision | Options | Status |
|----------|---------|--------|
| Lighthouse location | Home / EC2 | Pending |
| AWS Region | us-east-1 / us-west-2 | Pending |
| K8s distro on AWS | k3s / kubeadm | Leaning k3s |
| Model storage | EBS / S3+cache | Leaning EBS |
| Scale trigger | KEDA / custom / manual | Pending |
| Nebula on Talos | Extension / DaemonSet | Research needed |

---

## Blockers

| Blocker | Impact | Owner | Status |
|---------|--------|-------|--------|
| None yet | | | |

---

## Notes

### 2025-01-28 - Project Kickoff
- Created discovery document
- Researched Nebula and Liqo
- Identified key architecture components
- Estimated costs: $30-150/month depending on usage
