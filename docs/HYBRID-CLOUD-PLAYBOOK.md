# Hybrid Cloud Playbook: Nebula + k3s + Carrierarr

This document describes the complete setup for running a hybrid cloud architecture connecting homelab Kubernetes to AWS EC2 instances via Nebula mesh networking.

## Architecture Overview

### High-Level Topology

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         HOMELAB (Talos Cluster)                              │
│                        cluster.id=1 (talos-home)                             │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐          │
│  │  Talos Cluster   │  │ Nebula Lighthouse│  │   Carrierarr     │          │
│  │  5 nodes         │  │   10.100.0.1     │  │  Control Plane   │          │
│  │  135 endpoints   │  └────────┬─────────┘  └────────┬─────────┘          │
│  └──────────────────┘           │ UDP 4242            │ gRPC 50051          │
│                                 │                     │                      │
│  Router: port forward UDP 4242 ─┘                     │                      │
│  DNS: nebula.knowledgedump.space → home public IP     │                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                           ═══════╪═══════  Internet
                                  │
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AWS (k3s Cluster)                                    │
│                        cluster.id=2 (aws-k3s)                                │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                     EC2 Instance (t3.small)                           │  │
│  │  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐          │  │
│  │  │     Nebula     │  │      k3s       │  │  Worker Agent  │          │  │
│  │  │   10.100.2.1   │  │  1 node        │  │   :8080        │          │  │
│  │  │                │  │  6 endpoints   │  │                │          │  │
│  │  └────────────────┘  └────────────────┘  └────────────────┘          │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Cilium ClusterMesh Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      TALOS CLUSTER (talos-home)                              │
│                                                                              │
│  ┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────┐  │
│  │  Cilium Agents  │────▶│  KVStoreMesh Cache   │◀────│ ClusterMesh API │  │
│  │  (per node)     │     │  (local etcd cache)  │     │  :32379/32380   │  │
│  └─────────────────┘     └──────────────────────┘     └────────┬────────┘  │
│                                                                 │           │
│  ┌──────────────────────────────────────────────────────────────┘           │
│  │                                                                           │
│  │  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  │              Port Forwarder DaemonSet (socat)                   │    │
│  │  │  hostNetwork: true                                              │    │
│  │  │  socat TCP-LISTEN:32380 → TCP:10.100.2.1:32380                 │    │
│  │  │  Bridges Nebula TUN → ClusterMesh (bypasses eBPF limitation)   │    │
│  │  └─────────────────────────────────────────────────────────────────┘    │
│  │                                                                           │
└──┼───────────────────────────────────────────────────────────────────────────┘
   │
   │  TLS over Nebula Mesh (10.100.0.0/16)
   │  Combined CA bundle for mutual authentication
   │
   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       AWS K3S CLUSTER (aws-k3s)                              │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │              Port Forwarder DaemonSet (socat)                       │    │
│  │  socat TCP-LISTEN:32380 → TCP:10.100.0.1:32380                     │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                 │           │
│  ┌──────────────────────────────────────────────────────────────┘           │
│  │                                                                           │
│  ┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────┐  │
│  │  Cilium Agents  │────▶│  KVStoreMesh Cache   │◀────│ ClusterMesh API │  │
│  │  (per node)     │     │  (local etcd cache)  │     │  :32379/32380   │  │
│  └─────────────────┘     └──────────────────────┘     └─────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

Key:
  ─────▶  Local communication
  ═══════  Nebula encrypted tunnel (WireGuard-like)
  TLS      Mutual TLS with combined CA bundle
```

### Data Flow

1. **Identity Sync**: Each cluster's KVStoreMesh syncs identities/endpoints to remote cluster
2. **Port Forwarders**: socat DaemonSets bridge Nebula TUN to ClusterMesh etcd ports
3. **Combined CA**: Both Cilium CAs bundled for mutual TLS authentication
4. **KVStoreMesh Mode**: Agents read from local cache, reducing cross-cluster latency

## Components

| Component | Purpose | Location |
|-----------|---------|----------|
| Nebula Lighthouse | Mesh coordinator, NAT traversal | Homelab K8s (nebula namespace) |
| Carrierarr Control Plane | Fleet management, gRPC API | Homelab K8s (carrierarr namespace) |
| Nebula Workers | Mesh participants | AWS EC2 instances |
| k3s Server | Kubernetes in AWS | AWS EC2 instances |
| Worker Agent | Carrierarr client | AWS EC2 instances |

## Prerequisites

### Tools Required
- `nebula-cert` - Nebula certificate generator
- `packer` - AMI builder
- `aws` CLI - AWS management
- `kubectl` - Kubernetes CLI
- `jq` - JSON processor

### AWS Resources
- IAM Instance Profile with SecretsManager access
- Security Group allowing:
  - SSH (22/tcp)
  - Nebula (4242/udp)
  - k3s API (6443/tcp)
  - Health check (8080/tcp)
  - ClusterMesh (32379/tcp)

### Network Requirements
- Home router: Port forward UDP 4242 to control plane IP (192.168.1.54)
- DNS: Create record pointing to home public IP
  - Example: `nebula.knowledgedump.space` → home IP (DNS-only, no proxy)

---

## Phase 1: Generate Nebula Certificates

Nebula uses a PKI for authentication. All certificates must use `/16` subnets to allow routing between different address ranges.

### Generate CA
```bash
cd configs/nebula-certs/
nebula-cert ca -name "talos-homelab-mesh"
```

### Generate Lighthouse Certificate
```bash
nebula-cert sign \
  -name "lighthouse" \
  -ip "10.100.0.1/16" \
  -groups "lighthouse,homelab" \
  -ca-crt ca.crt \
  -ca-key ca.key
```

### Generate Worker Certificate
```bash
nebula-cert sign \
  -name "gpu-worker-001" \
  -ip "10.100.2.1/16" \
  -groups "workers,aws" \
  -ca-crt ca.crt \
  -ca-key ca.key
```

**Important:** Use `/16` subnet masks! Using `/24` will prevent nodes in different subnets from communicating.

---

## Phase 2: Deploy Nebula Lighthouse in Homelab

### Create Namespace
```bash
kubectl apply -f infrastructure/base/nebula/namespace.yaml
```

### Deploy Lighthouse Secret
```bash
kubectl create secret generic nebula-lighthouse-certs \
  --from-file=ca.crt=configs/nebula-certs/ca.crt \
  --from-file=lighthouse.crt=configs/nebula-certs/lighthouse.crt \
  --from-file=lighthouse.key=configs/nebula-certs/lighthouse.key \
  -n nebula --dry-run=client -o yaml | kubectl apply -f -
```

### Deploy Lighthouse
```bash
kubectl apply -k infrastructure/base/nebula/
```

### Verify
```bash
kubectl get pods -n nebula
kubectl logs -n nebula deployment/nebula-lighthouse
```

### Test Connectivity
```bash
nc -vzu nebula.knowledgedump.space 4242
```

---

## Phase 3: Store AWS Secrets

Store Nebula certificates in AWS Secrets Manager for EC2 instances to fetch at boot:

```bash
SECRET_JSON=$(jq -n \
  --arg ca "$(cat configs/nebula-certs/ca.crt)" \
  --arg crt "$(cat configs/nebula-certs/gpu-worker-001.crt)" \
  --arg key "$(cat configs/nebula-certs/gpu-worker-001.key)" \
  --arg ip "10.100.2.1" \
  --arg endpoint "nebula.knowledgedump.space:4242" \
  '{
    nebula_ca_crt: $ca,
    nebula_node_crt: $crt,
    nebula_node_key: $key,
    nebula_ip: $ip,
    lighthouse_endpoint: $endpoint
  }')

aws secretsmanager create-secret \
  --name "catalyst-llm/nebula-worker-001" \
  --secret-string "$SECRET_JSON" \
  --region us-west-2
```

---

## Phase 4: Build AMI with Packer

### Build Worker Agent Binary
```bash
cd tools/carrierarr
GOOS=linux GOARCH=amd64 go build -o bin/linux-amd64/worker-agent ./cmd/worker-agent/
```

### Build Lighthouse AMI
```bash
cd tools/carrierarr/ami
packer init .
packer build -only='lighthouse.*' .
```

**AMI includes:**
- k3s server
- kubectl, helm, cilium CLI
- Nebula + systemd service
- Worker agent
- CloudWatch agent

---

## Phase 5: Launch EC2 Instance

### Create Security Group
```bash
SG_ID=$(aws ec2 create-security-group \
  --group-name "catalyst-llm-lighthouse" \
  --description "Catalyst LLM Lighthouse" \
  --vpc-id vpc-xxxxx \
  --query 'GroupId' --output text)

# Add rules
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 22 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol udp --port 4242 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 6443 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 8080 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 32379 --cidr 0.0.0.0/0
```

### Launch Instance
```bash
aws ec2 run-instances \
  --image-id ami-xxxxx \
  --instance-type t3.small \
  --key-name hybrid-llm-key \
  --security-group-ids $SG_ID \
  --iam-instance-profile Name=catalyst-llm-gpu-worker \
  --user-data file://tools/carrierarr/ami/userdata/lighthouse.sh \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=catalyst-llm-lighthouse}]'
```

---

## Phase 6: Verify Connectivity

### SSH to Instance
```bash
aws ec2-instance-connect send-ssh-public-key \
  --instance-id i-xxxxx \
  --instance-os-user ec2-user \
  --ssh-public-key file://~/.ssh/id_ed25519.pub

ssh -i ~/.ssh/id_ed25519 ec2-user@<public-ip>
```

### Verify Nebula
```bash
# On EC2 instance
ip addr show nebula0
ping 10.100.0.1  # Should reach lighthouse
```

### Verify k3s
```bash
sudo k3s kubectl get nodes
sudo k3s kubectl get pods -A
```

---

## Teardown Procedure

### 1. Terminate EC2 Instance
```bash
aws ec2 terminate-instances --instance-ids i-xxxxx --region us-west-2
```

### 2. Delete Security Group
```bash
aws ec2 delete-security-group --group-id sg-xxxxx --region us-west-2
```

### 3. Delete AWS Secret
```bash
aws secretsmanager delete-secret \
  --secret-id "catalyst-llm/nebula-worker-001" \
  --force-delete-without-recovery \
  --region us-west-2
```

### 4. Remove Homelab Resources
```bash
kubectl delete -k infrastructure/base/nebula/
kubectl delete -k infrastructure/base/carrierarr/
```

### 5. Deregister AMI (optional)
```bash
aws ec2 deregister-image --image-id ami-xxxxx --region us-west-2
```

---

## Troubleshooting

### Nebula Won't Connect
1. Check certificates have `/16` subnet
2. Verify UDP 4242 port forwarding
3. Check DNS resolution: `dig nebula.knowledgedump.space`
4. Check firewall rules on both ends

### AWS CLI Color Codes Breaking jq
Add to commands:
```bash
AWS_PAGER="" aws ... --no-cli-pager --color off
```

Or strip ANSI codes:
```bash
SECRETS=$(aws ... | sed "s/\x1B\[[0-9;]*[JKmsu]//g")
```

### k3s Node NotReady
Expected without CNI. Install Cilium:
```bash
cilium install --cluster-name aws-k3s --cluster-id 2
```

### Nebula "static_host_map key is not in our subnet"
Certificate subnet is too narrow. Regenerate with `/16`:
```bash
nebula-cert sign -name "xxx" -ip "10.100.x.x/16" ...
```

### ClusterMesh TLS Errors

**"certificate is valid for X, not Y"**
Server certificates missing Nebula IPs in SANs. Regenerate with custom OpenSSL config:
```bash
# Create config with Nebula IP in SANs
cat > /tmp/server-cert.cnf <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
CN = clustermesh-apiserver.cilium.io

[v3_req]
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = clustermesh-apiserver.cilium.io
DNS.2 = *.mesh.cilium.io
IP.1 = 127.0.0.1
IP.2 = 10.100.0.1
IP.3 = 10.100.2.1
EOF

# Generate RSA key (must match CA key type)
openssl genrsa -out server.key 2048

# Create CSR and sign with Cilium CA
openssl req -new -key server.key -out server.csr -config /tmp/server-cert.cnf
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days 1095 -extensions v3_req -extfile /tmp/server-cert.cnf
```

**"crypto/rsa: verification error"**
Key type mismatch. Cilium uses RSA keys by default. Regenerate server certs with RSA:
```bash
openssl genrsa -out server.key 2048  # NOT ecparam
```

**KVStoreMesh using wrong endpoint**
Check `cilium-kvstoremesh` secret - ensure endpoints use Nebula IPs:
```bash
kubectl get secret cilium-kvstoremesh -n kube-system -o yaml
# Should show: https://10.100.X.1:32380
```

### ClusterMesh Status Commands

```bash
# Check overall status
cilium --context=admin@catalyst-cluster clustermesh status
cilium --context=aws-lighthouse clustermesh status

# Check KVStoreMesh sync
kubectl exec -n kube-system deploy/clustermesh-apiserver -c kvstoremesh -- kvstoremesh-dbg status

# Verify pod connectivity to remote
kubectl exec -n kube-system deploy/clustermesh-apiserver -c kvstoremesh -- \
  curl -k --cert /var/lib/cilium/clustermesh/aws-k3s.etcd-client.crt \
       --key /var/lib/cilium/clustermesh/aws-k3s.etcd-client.key \
       https://10.100.2.1:32380/health
```

---

## File Locations

| File | Purpose |
|------|---------|
| `configs/nebula-certs/` | Nebula CA and certificates (gitignored) |
| `infrastructure/base/nebula/` | Lighthouse K8s manifests |
| `infrastructure/base/carrierarr/` | Carrierarr control plane |
| `tools/carrierarr/ami/` | Packer templates |
| `tools/carrierarr/ami/userdata/` | EC2 userdata scripts |
| `tools/carrierarr/ami/variables.pkr.hcl` | Packer variables |

---

## Current Status

| Component | Status | Notes |
|-----------|--------|-------|
| Nebula Lighthouse | ✅ Running | Deployed in nebula namespace (10.100.0.1/16) |
| Nebula Worker | ✅ Connected | 10.100.2.1, ~35ms latency to lighthouse |
| k3s Server | ✅ Running | Node Ready with Cilium CNI |
| Cilium CNI (Talos) | ✅ Installed | cluster.name=talos-home, cluster.id=1 |
| Cilium CNI (k3s) | ✅ Installed | cluster.name=aws-k3s, cluster.id=2 |
| ClusterMesh API (Talos) | ✅ Running | NodePort 32379/32380, Nebula 10.100.0.1 |
| ClusterMesh API (k3s) | ✅ Running | NodePort 32379/32380, Nebula 10.100.2.1 |
| **ClusterMesh Peering** | ✅ Connected | KVStoreMesh bidirectional sync active |
| Port Forwarders | ✅ Running | socat bridges Nebula → ClusterMesh |
| Liqo | ❌ Removed | Replaced by ClusterMesh |
| Carrierarr Control Plane | ✅ Running | At fleet.talos00:30052 |
| Worker Agent | ⏳ Pending | Needs Carrierarr integration |

### ClusterMesh Sync Status

| Direction | Nodes | Endpoints | Identities |
|-----------|-------|-----------|------------|
| Talos → k3s | 1 | 6 | 6 |
| k3s → Talos | 5 | 135 | 4716 |

### Next Steps

1. ~~Exchange ClusterMesh secrets between clusters~~ ✅ Complete
2. ~~Verify cross-cluster service discovery~~ ✅ Working
3. Complete carrierarr worker agent integration
4. Add global services for cross-cluster access

### Beads Tracking

- Epic: TALOS-rien (Migrate to Cilium ClusterMesh) - ✅ Closed
- Task: TALOS-rrnk (Configure ClusterMesh) - ✅ Closed
- Epic: TALOS-w5e0 (Carrierarr base image system)
