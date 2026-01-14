# Carrierarr Hybrid Cloud Provisioning Notes

This document captures all manual steps for automating in the Tiltfile.

## Prerequisites

### Tools Required (local machine)
- `aws` CLI with credentials
- `packer` for AMI building
- `cilium` CLI
- `liqoctl` CLI
- `kubectl` with homelab context
- `nebula-cert` for certificate generation

### AWS Resources Needed
- IAM Instance Profile: `catalyst-llm-gpu-worker`
- Key Pair: `hybrid-llm-key`
- VPC with public subnet (default VPC works)

---

## Phase 1: Nebula Certificates

### Generate CA (one-time)
```bash
cd configs/nebula-certs/
nebula-cert ca -name "talos-homelab-mesh"
```

### Generate Lighthouse Cert
```bash
nebula-cert sign \
  -name "lighthouse" \
  -ip "10.100.0.1/16" \
  -groups "lighthouse,homelab" \
  -ca-crt ca.crt \
  -ca-key ca.key
```

### Generate Worker Cert (per worker)
```bash
WORKER_IP="10.100.2.1"  # Increment for each worker
WORKER_NAME="gpu-worker-001"

nebula-cert sign \
  -name "${WORKER_NAME}" \
  -ip "${WORKER_IP}/16" \
  -groups "workers,aws" \
  -ca-crt ca.crt \
  -ca-key ca.key
```

**CRITICAL**: Use `/16` subnet mask, not `/24`!

---

## Phase 2: AWS Secrets

### Store Nebula Certs in Secrets Manager
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

## Phase 3: Build AMI

### Build Lighthouse AMI
```bash
cd tools/carrierarr/ami
packer init .
packer build -only='lighthouse.*' .
```

**Output**: AMI ID for use in EC2 launch

---

## Phase 4: Create Security Group

```bash
SG_ID=$(aws ec2 create-security-group \
  --group-name "carrierarr-lighthouse" \
  --description "Carrierarr Lighthouse" \
  --vpc-id ${VPC_ID} \
  --query 'GroupId' --output text \
  --region us-west-2)

# SSH
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 22 --cidr 0.0.0.0/0 --region us-west-2
# Nebula
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol udp --port 4242 --cidr 0.0.0.0/0 --region us-west-2
# k3s API
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 6443 --cidr 0.0.0.0/0 --region us-west-2
# Health check
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 8080 --cidr 0.0.0.0/0 --region us-west-2
# ClusterMesh
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 32379 --cidr 0.0.0.0/0 --region us-west-2
# Liqo gateway
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol udp --port 32380 --cidr 0.0.0.0/0 --region us-west-2
```

---

## Phase 5: Launch EC2 Instance

```bash
aws ec2 run-instances \
  --image-id ${AMI_ID} \
  --instance-type t3.small \
  --key-name hybrid-llm-key \
  --security-group-ids ${SG_ID} \
  --iam-instance-profile Name=catalyst-llm-gpu-worker \
  --user-data file://tools/carrierarr/ami/userdata/lighthouse.sh \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=carrierarr-lighthouse}]' \
  --region us-west-2
```

---

## Phase 6: Verify Nebula Mesh

### Check lighthouse logs for handshake
```bash
kubectl logs -n nebula deploy/nebula-lighthouse | grep -E "handshake|10.100.2"
```

### SSH to EC2 and verify
```bash
# Send SSH key (expires in 60s)
aws ec2-instance-connect send-ssh-public-key \
  --instance-id ${INSTANCE_ID} \
  --instance-os-user ec2-user \
  --ssh-public-key file://~/.ssh/id_ed25519.pub \
  --region us-west-2

# Connect immediately after
ssh -i ~/.ssh/id_ed25519 ec2-user@${PUBLIC_IP} "ip addr show nebula0"
```

---

## Phase 7: Install Cilium on EC2 k3s

```bash
# SSH to instance and run:
NEBULA_IP=$(ip addr show nebula0 | grep -oP 'inet \K[\d.]+')

sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml cilium install \
  --version 1.16.6 \
  --set cluster.name=aws-k3s \
  --set cluster.id=2 \
  --set ipam.mode=kubernetes \
  --set kubeProxyReplacement=true \
  --set k8sServiceHost=${NEBULA_IP} \
  --set k8sServicePort=6443 \
  --set hubble.enabled=true \
  --set hubble.relay.enabled=true \
  --set clustermesh.useAPIServer=true \
  --set clustermesh.apiserver.replicas=1 \
  --set clustermesh.apiserver.service.type=NodePort \
  --set clustermesh.apiserver.service.nodePort=32379

# Wait for node Ready
sudo k3s kubectl wait --for=condition=ready node --all --timeout=300s
```

---

## Phase 8: Install Liqo

### On Homelab
```bash
liqoctl install \
  --cluster-id="catalyst-homelab" \
  --cluster-name="catalyst-homelab" \
  --pod-cidr="10.244.0.0/16" \
  --service-cidr="10.96.0.0/12" \
  --enable-metrics
```

### On EC2 k3s
```bash
# SSH to instance:
sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml liqoctl install \
  --cluster-id="aws-k3s" \
  --cluster-name="aws-k3s" \
  --pod-cidr="10.42.0.0/16" \
  --service-cidr="10.43.0.0/16" \
  --enable-metrics
```

---

## Phase 9: Peer Clusters

### Generate peering command from homelab
```bash
liqoctl generate peer-command --only-command
```

### Run on EC2 k3s
```bash
sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml liqoctl peer <PEERING_COMMAND>
```

---

## Phase 10: Verify Carrierarr Agent

### Check agent status on EC2
```bash
sudo systemctl status worker-agent
```

### Check agent registration in homelab control plane
```bash
kubectl logs -n carrierarr deploy/carrierarr-control-plane
```

---

## Teardown

### 1. Terminate EC2
```bash
aws ec2 terminate-instances --instance-ids ${INSTANCE_ID} --region us-west-2
```

### 2. Delete Security Group (wait for instance termination)
```bash
aws ec2 delete-security-group --group-id ${SG_ID} --region us-west-2
```

### 3. Delete Secret
```bash
aws secretsmanager delete-secret \
  --secret-id "catalyst-llm/nebula-worker-001" \
  --force-delete-without-recovery \
  --region us-west-2
```

### 4. Deregister AMI (optional)
```bash
aws ec2 deregister-image --image-id ${AMI_ID} --region us-west-2
```

---

## Current Session Resources

| Resource | ID |
|----------|-----|
| EC2 Instance | i-0f57e0c1f67c76e3c |
| Security Group | sg-021cf468b720b9f24 |
| AMI | ami-0f24e5b7febd29ea3 |
| Secret | catalyst-llm/nebula-worker-001 |
| Public IP | 52.40.37.117 |
| Nebula IP | 10.100.2.1 |

---

## Tiltfile Automation

The Tiltfile in this directory (`tools/carrierarr/Tiltfile`) now includes full provisioning automation.

### Usage

```bash
cd tools/carrierarr

# Start Tilt with default worker
tilt up

# Custom worker configuration
tilt up -- --worker-name=gpu-worker-002 --nebula-ip=10.100.2.2

# Full options
tilt up -- \
  --worker-name=gpu-worker-001 \
  --nebula-ip=10.100.2.1 \
  --instance-type=t3.small \
  --ami-id=ami-0f24e5b7febd29ea3 \
  --region=us-west-2
```

### Provisioning Resources

In the Tilt UI, under "4-provisioning" label:

1. **provision-nebula-cert** - Generate Nebula certificate for worker
2. **provision-aws-secret** - Store certs in AWS Secrets Manager
3. **provision-security-group** - Create EC2 security group
4. **provision-ec2** - Launch EC2 instance with k3s
5. **provision-verify-nebula** - Verify Nebula mesh connectivity
6. **provision-cilium** - Install Cilium CNI via SSH
7. **provision-status** - Show current status
8. **provision-teardown** - Destroy all resources

### One-Click Provisioning

Use the "🚀 Provision All" button on the `provision-nebula-cert` resource to run the full provisioning flow.

### Teardown

Use the "🗑️ Teardown" button on `provision-teardown` or:

```bash
tilt trigger provision-teardown
```

---

## Known Issues

### Liqo Installation
Liqo install times out due to PodSecurity restrictions on Talos. Needs custom securityContext configuration for privileged components. Currently not automated.

### jq/kubectl Color Codes
Some shell commands may fail due to ANSI color codes from shell aliases. Use `command kubectl` and `command jq` to bypass aliases.

### Stuck Namespaces
Kubernetes namespaces with custom finalizers may get stuck terminating. Use the finalize API endpoint to clear finalizers:

```bash
kubectl get namespace <ns> -o json | \
  sed 's/\x1B\[[0-9;]*[mJKsu]//g' | \
  jq --monochrome-output 'del(.spec.finalizers)' > /tmp/ns.json

kubectl replace --raw "/api/v1/namespaces/<ns>/finalize" -f /tmp/ns.json
```
