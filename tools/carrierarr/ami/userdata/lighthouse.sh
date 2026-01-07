#!/bin/bash
# =============================================================================
# Lighthouse Userdata - Minimal Bootstrap (Nebula-free stub)
# =============================================================================
# NOTE: This is a minimal stub. Full implementation pending TALOS-700h
#       which will add proper Nebula mesh with home-as-lighthouse architecture.
#
# Current capabilities:
# - Fetches secrets from AWS Secrets Manager
# - Configures worker-agent for fleet registration
# - Starts k3s server with Cilium CNI

set -euo pipefail
exec > >(tee /var/log/userdata.log) 2>&1
echo "=== Lighthouse Bootstrap Started at $(date) ==="

# =============================================================================
# Configuration
# =============================================================================
RABBITMQ_URL="${RABBITMQ_URL:-}"
CILIUM_CLUSTER_NAME="${CILIUM_CLUSTER_NAME:-aws-lighthouse}"
CILIUM_CLUSTER_ID="${CILIUM_CLUSTER_ID:-2}"
CILIUM_VERSION="${CILIUM_VERSION:-1.16.6}"

# Network CIDRs (must not overlap with Talos cluster)
POD_CIDR="${POD_CIDR:-10.42.0.0/16}"
SERVICE_CIDR="${SERVICE_CIDR:-10.43.0.0/16}"
CLUSTER_DNS="${CLUSTER_DNS:-10.43.0.10}"

# =============================================================================
# Fetch Instance Metadata (IMDSv2)
# =============================================================================
IMDS_TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
REGION=$(curl -s -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" http://169.254.169.254/latest/meta-data/placement/region)
INSTANCE_ID=$(curl -s -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" http://169.254.169.254/latest/meta-data/instance-id)
PUBLIC_IP=$(curl -s -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" http://169.254.169.254/latest/meta-data/public-ipv4)
PRIVATE_IP=$(curl -s -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" http://169.254.169.254/latest/meta-data/local-ipv4)

# =============================================================================
# Fetch Secrets
# =============================================================================
SECRET_NAME="${SECRET_NAME:-catalyst-llm/lighthouse}"

echo "Fetching secrets from AWS Secrets Manager: ${SECRET_NAME}"
SECRETS=$(aws secretsmanager get-secret-value --secret-id "${SECRET_NAME}" --region "${REGION}" --query SecretString --output text 2>/dev/null || echo "{}")

K3S_TOKEN=$(echo "$SECRETS" | jq -r '.k3s_token // empty')

# Get RabbitMQ URL from secret if not provided via env
if [ -z "$RABBITMQ_URL" ]; then
  RABBITMQ_URL=$(echo "$SECRETS" | jq -r '.rabbitmq_url // empty')
fi

# =============================================================================
# Configure worker-agent
# =============================================================================
echo "Configuring worker-agent..."

cat > /etc/worker-agent/env << EOF
NODE_TYPE=lighthouse
INSTANCE_ID=${INSTANCE_ID}
PUBLIC_IP=${PUBLIC_IP}
RABBITMQ_URL=${RABBITMQ_URL}
EOF

systemctl enable worker-agent
systemctl start worker-agent

# =============================================================================
# Configure k3s Server (without default CNI)
# =============================================================================
echo "Configuring k3s server..."

# Generate k3s token if not provided
if [ -z "$K3S_TOKEN" ]; then
  K3S_TOKEN=$(openssl rand -hex 32)
  echo "Generated K3S_TOKEN: ${K3S_TOKEN}"
fi

# Write k3s config - disable flannel, we use Cilium
# Use private IP since we don't have Nebula mesh
cat > /etc/rancher/k3s/config.yaml << EOF
node-name: lighthouse-${INSTANCE_ID}
node-ip: ${PRIVATE_IP}
node-external-ip: ${PUBLIC_IP}
bind-address: 0.0.0.0
advertise-address: ${PRIVATE_IP}
# Disable flannel - we use Cilium
flannel-backend: none
disable-network-policy: true
cluster-cidr: "${POD_CIDR}"
service-cidr: "${SERVICE_CIDR}"
cluster-dns: "${CLUSTER_DNS}"
disable:
  - traefik
  - servicelb
token: ${K3S_TOKEN}
tls-san:
  - ${PRIVATE_IP}
  - ${PUBLIC_IP}
  - ${INSTANCE_ID}
  - localhost
  - 127.0.0.1
EOF

# Start k3s
systemctl enable k3s
systemctl start k3s

echo "Waiting for k3s to be ready..."
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

for i in {1..60}; do
  if kubectl get nodes 2>/dev/null; then
    echo "k3s API is ready!"
    break
  fi
  echo "Waiting for k3s API... ($i/60)"
  sleep 5
done

# =============================================================================
# Install Cilium with ClusterMesh
# =============================================================================
echo "Installing Cilium CNI with ClusterMesh..."

# Wait for node to be registered (will be NotReady until CNI is installed)
kubectl wait --for=jsonpath='{.status.conditions[?(@.type=="Ready")].status}'=False node --all --timeout=120s || true

# Install Cilium with ClusterMesh enabled
cilium install \
  --version ${CILIUM_VERSION} \
  --set cluster.name=${CILIUM_CLUSTER_NAME} \
  --set cluster.id=${CILIUM_CLUSTER_ID} \
  --set ipam.mode=kubernetes \
  --set kubeProxyReplacement=true \
  --set k8sServiceHost=${PRIVATE_IP} \
  --set k8sServicePort=6443 \
  --set hubble.enabled=true \
  --set hubble.relay.enabled=true \
  --set clustermesh.useAPIServer=true \
  --set clustermesh.apiserver.replicas=1 \
  --set clustermesh.apiserver.service.type=NodePort \
  --set clustermesh.apiserver.service.nodePort=32379 \
  --set clustermesh.apiserver.tls.auto.enabled=true \
  --set clustermesh.apiserver.tls.auto.method=helm

echo "Waiting for Cilium to be ready..."
cilium status --wait --wait-duration 5m

# Verify node is ready now
echo "Waiting for node to be Ready..."
kubectl wait --for=condition=ready node --all --timeout=300s

# =============================================================================
# Store outputs for GPU workers to retrieve
# =============================================================================
echo "Storing cluster info..."

# Create/update secret with k3s join info
aws secretsmanager put-secret-value \
  --secret-id "catalyst-llm/gpu-worker" \
  --region "${REGION}" \
  --secret-string "$(
    jq -n \
      --arg token "$K3S_TOKEN" \
      --arg url "https://${PUBLIC_IP}:6443" \
      --arg lighthouse_public_ip "${PUBLIC_IP}" \
      --arg cluster_name "${CILIUM_CLUSTER_NAME}" \
      --arg cluster_id "${CILIUM_CLUSTER_ID}" \
      '{k3s_token: $token, k3s_url: $url, lighthouse_public_ip: $lighthouse_public_ip, cilium_cluster_name: $cluster_name, cilium_cluster_id: $cluster_id}'
  )" || echo "Warning: Could not update gpu-worker secret"

echo "=== Lighthouse Bootstrap Completed at $(date) ==="
echo "k3s server URL: https://${PUBLIC_IP}:6443"
echo "Public IP: ${PUBLIC_IP}"
echo "Private IP: ${PRIVATE_IP}"
echo "Cilium ClusterMesh: ${CILIUM_CLUSTER_NAME} (ID: ${CILIUM_CLUSTER_ID})"
echo ""
echo "NOTE: Nebula mesh is not configured. See TALOS-700h for proper mesh implementation."
