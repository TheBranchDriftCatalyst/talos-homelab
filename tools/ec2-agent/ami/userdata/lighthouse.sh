#!/bin/bash
# =============================================================================
# Lighthouse Userdata - Minimal Bootstrap for Pre-baked AMI
# =============================================================================
# This script runs at first boot to configure the Nebula lighthouse,
# k3s server, and Cilium CNI with ClusterMesh for multi-cluster connectivity.
#
# Required Secrets (injected via AWS Secrets Manager):
# - NEBULA_CA_CRT: Nebula CA certificate
# - NEBULA_CA_KEY: Nebula CA private key (for signing new certs)
# - NEBULA_HOST_CRT: This node's certificate
# - NEBULA_HOST_KEY: This node's private key
# - CONTROL_PLANE_ADDR: gRPC control plane address (optional)
# - K3S_TOKEN: k3s cluster token (generated if not provided)

set -euo pipefail
exec > >(tee /var/log/userdata.log) 2>&1
echo "=== Lighthouse Bootstrap Started at $(date) ==="

# =============================================================================
# Configuration
# =============================================================================
NEBULA_IP="${NEBULA_IP:-10.100.1.1}"
CONTROL_PLANE_ADDR="${CONTROL_PLANE_ADDR:-10.100.0.1:50051}"
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

# =============================================================================
# Fetch Secrets
# =============================================================================
SECRET_NAME="${SECRET_NAME:-catalyst-llm/lighthouse}"

echo "Fetching secrets from AWS Secrets Manager: ${SECRET_NAME}"
SECRETS=$(aws secretsmanager get-secret-value --secret-id "${SECRET_NAME}" --region "${REGION}" --query SecretString --output text)

NEBULA_CA_CRT=$(echo "$SECRETS" | jq -r '.nebula_ca_crt')
NEBULA_CA_KEY=$(echo "$SECRETS" | jq -r '.nebula_ca_key // empty')
NEBULA_HOST_CRT=$(echo "$SECRETS" | jq -r '.nebula_host_crt')
NEBULA_HOST_KEY=$(echo "$SECRETS" | jq -r '.nebula_host_key')
K3S_TOKEN=$(echo "$SECRETS" | jq -r '.k3s_token // empty')

# Get RabbitMQ URL from secret if not provided via env
if [ -z "$RABBITMQ_URL" ]; then
  RABBITMQ_URL=$(echo "$SECRETS" | jq -r '.rabbitmq_url // empty')
fi

# =============================================================================
# Configure Nebula Lighthouse
# =============================================================================
echo "Configuring Nebula Lighthouse..."

# Write certificates
echo "$NEBULA_CA_CRT" | base64 -d > /etc/nebula/ca.crt
echo "$NEBULA_HOST_CRT" | base64 -d > /etc/nebula/host.crt
echo "$NEBULA_HOST_KEY" | base64 -d > /etc/nebula/host.key
chmod 600 /etc/nebula/host.key

# Write CA key if provided (for signing new certificates)
if [ -n "$NEBULA_CA_KEY" ]; then
  echo "$NEBULA_CA_KEY" | base64 -d > /etc/nebula/ca.key
  chmod 600 /etc/nebula/ca.key
fi

# Create Nebula lighthouse config
cat > /etc/nebula/config.yml << EOF
pki:
  ca: /etc/nebula/ca.crt
  cert: /etc/nebula/host.crt
  key: /etc/nebula/host.key

static_host_map: {}

lighthouse:
  am_lighthouse: true
  serve_dns: true
  dns:
    host: 0.0.0.0
    port: 53

listen:
  host: 0.0.0.0
  port: 4242

punchy:
  punch: true

tun:
  dev: nebula1
  drop_local_broadcast: false
  drop_multicast: false
  tx_queue: 500
  mtu: 1300

logging:
  level: info
  format: text

firewall:
  outbound:
    - port: any
      proto: any
      host: any

  inbound:
    - port: any
      proto: icmp
      host: any
    - port: 22
      proto: tcp
      host: any
    - port: 6443
      proto: tcp
      host: any
    # VXLAN for Cilium
    - port: 8472
      proto: udp
      host: any
    - port: 10250
      proto: tcp
      host: any
    - port: 53
      proto: any
      host: any
    # ClusterMesh etcd
    - port: 2379
      proto: tcp
      host: any
    - port: 32379
      proto: tcp
      host: any
    # Hubble
    - port: 4244
      proto: tcp
      host: any
EOF

# Start Nebula
systemctl enable nebula
systemctl start nebula

echo "Waiting for Nebula to establish..."
sleep 5

# Verify Nebula is running
if ! ip addr show nebula1 2>/dev/null; then
  echo "ERROR: Nebula interface not up!"
  exit 1
fi

# =============================================================================
# Configure worker-agent
# =============================================================================
echo "Configuring worker-agent..."

cat > /etc/worker-agent/env << EOF
CONTROL_PLANE_ADDR=${CONTROL_PLANE_ADDR}
NODE_TYPE=lighthouse
INSTANCE_ID=${INSTANCE_ID}
NEBULA_IP=${NEBULA_IP}
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
cat > /etc/rancher/k3s/config.yaml << EOF
node-name: lighthouse-${INSTANCE_ID}
node-ip: ${NEBULA_IP}
node-external-ip: ${PUBLIC_IP}
bind-address: 0.0.0.0
advertise-address: ${NEBULA_IP}
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
  - ${NEBULA_IP}
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
  --set k8sServiceHost=${NEBULA_IP} \
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
# Enable ClusterMesh
# =============================================================================
echo "Enabling ClusterMesh..."

# ClusterMesh is already enabled via install, just verify status
cilium clustermesh status || true

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
      --arg url "https://${NEBULA_IP}:6443" \
      --arg lighthouse_ip "${NEBULA_IP}" \
      --arg lighthouse_public_ip "${PUBLIC_IP}" \
      --arg cluster_name "${CILIUM_CLUSTER_NAME}" \
      --arg cluster_id "${CILIUM_CLUSTER_ID}" \
      '{k3s_token: $token, k3s_url: $url, lighthouse_nebula_ip: $lighthouse_ip, lighthouse_public_ip: $lighthouse_public_ip, cilium_cluster_name: $cluster_name, cilium_cluster_id: $cluster_id}'
  )" || echo "Warning: Could not update gpu-worker secret"

echo "=== Lighthouse Bootstrap Completed at $(date) ==="
echo "k3s server URL: https://${NEBULA_IP}:6443"
echo "Nebula IP: ${NEBULA_IP}"
echo "Public IP: ${PUBLIC_IP}"
echo "Cilium ClusterMesh: ${CILIUM_CLUSTER_NAME} (ID: ${CILIUM_CLUSTER_ID})"
echo ""
echo "To connect to Talos ClusterMesh:"
echo "  1. Extract Talos ClusterMesh secrets"
echo "  2. Create cilium-clustermesh secret on this cluster"
echo "  3. Extract this cluster's secrets and apply to Talos"
