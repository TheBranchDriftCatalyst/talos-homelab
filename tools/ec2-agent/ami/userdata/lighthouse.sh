#!/bin/bash
# =============================================================================
# Lighthouse Userdata - Minimal Bootstrap for Pre-baked AMI
# =============================================================================
# This script runs at first boot to configure the Nebula lighthouse,
# k3s server, and Liqo for multi-cluster federation.
#
# Required Secrets (injected via AWS Secrets Manager):
# - NEBULA_CA_CRT: Nebula CA certificate
# - NEBULA_CA_KEY: Nebula CA private key (for signing new certs)
# - NEBULA_HOST_CRT: This node's certificate
# - NEBULA_HOST_KEY: This node's private key
# - CONTROL_PLANE_ADDR: gRPC control plane address
# - K3S_TOKEN: k3s cluster token (generated if not provided)
# - LIQO_CLUSTER_NAME: Name for this Liqo cluster

set -euo pipefail
exec > >(tee /var/log/userdata.log) 2>&1
echo "=== Lighthouse Bootstrap Started at $(date) ==="

# =============================================================================
# Configuration
# =============================================================================
NEBULA_IP="${NEBULA_IP:-10.42.1.1}"
CONTROL_PLANE_ADDR="${CONTROL_PLANE_ADDR:-10.42.0.1:50051}"
LIQO_CLUSTER_NAME="${LIQO_CLUSTER_NAME:-ec2-lighthouse}"

# =============================================================================
# Fetch Secrets
# =============================================================================
SECRET_NAME="${SECRET_NAME:-catalyst-llm/lighthouse}"
REGION=$(curl -s http://169.254.169.254/latest/meta-data/placement/region)
INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)
PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)

echo "Fetching secrets from AWS Secrets Manager: ${SECRET_NAME}"
SECRETS=$(aws secretsmanager get-secret-value --secret-id "${SECRET_NAME}" --region "${REGION}" --query SecretString --output text)

NEBULA_CA_CRT=$(echo "$SECRETS" | jq -r '.nebula_ca_crt')
NEBULA_CA_KEY=$(echo "$SECRETS" | jq -r '.nebula_ca_key // empty')
NEBULA_HOST_CRT=$(echo "$SECRETS" | jq -r '.nebula_host_crt')
NEBULA_HOST_KEY=$(echo "$SECRETS" | jq -r '.nebula_host_key')
K3S_TOKEN=$(echo "$SECRETS" | jq -r '.k3s_token // empty')

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
    - port: 8472
      proto: udp
      host: any
    - port: 10250
      proto: tcp
      host: any
    - port: 53
      proto: any
      host: any
EOF

# Start Nebula
systemctl enable nebula
systemctl start nebula

echo "Waiting for Nebula to establish..."
sleep 5

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
EOF

systemctl enable worker-agent
systemctl start worker-agent

# =============================================================================
# Configure k3s Server
# =============================================================================
echo "Configuring k3s server..."

# Generate k3s token if not provided
if [ -z "$K3S_TOKEN" ]; then
  K3S_TOKEN=$(openssl rand -hex 32)
  echo "Generated K3S_TOKEN: ${K3S_TOKEN}"
fi

# Write k3s config
cat > /etc/rancher/k3s/config.yaml << EOF
node-name: ${INSTANCE_ID}
node-ip: ${NEBULA_IP}
node-external-ip: ${PUBLIC_IP}
bind-address: 0.0.0.0
advertise-address: ${NEBULA_IP}
flannel-iface: nebula1
cluster-cidr: "10.43.0.0/16"
service-cidr: "10.44.0.0/16"
cluster-dns: "10.44.0.10"
disable:
  - traefik
  - servicelb
token: ${K3S_TOKEN}
tls-san:
  - ${NEBULA_IP}
  - ${PUBLIC_IP}
  - ${INSTANCE_ID}
EOF

# Start k3s
systemctl enable k3s
systemctl start k3s

echo "Waiting for k3s to be ready..."
for i in {1..60}; do
  if kubectl get nodes 2> /dev/null; then
    echo "k3s is ready!"
    break
  fi
  sleep 5
done

# =============================================================================
# Install Liqo
# =============================================================================
echo "Installing Liqo..."

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

# Wait for k3s to be fully ready
kubectl wait --for=condition=ready node --all --timeout=300s

# Install Liqo using liqoctl
liqoctl install k3s \
  --cluster-name="${LIQO_CLUSTER_NAME}" \
  --timeout=10m

echo "Waiting for Liqo to be ready..."
kubectl wait --for=condition=ready pod -l app.kubernetes.io/part-of=liqo -n liqo-system --timeout=300s || true

# =============================================================================
# Store outputs for GPU workers to retrieve
# =============================================================================
echo "Storing cluster info..."

# Create secret with k3s join info
aws secretsmanager put-secret-value \
  --secret-id "catalyst-llm/gpu-worker" \
  --region "${REGION}" \
  --secret-string "$(
    jq -n \
      --arg token "$K3S_TOKEN" \
      --arg url "https://${NEBULA_IP}:6443" \
      --arg lighthouse_ip "${NEBULA_IP}" \
      --arg lighthouse_public_ip "${PUBLIC_IP}" \
      '{k3s_token: $token, k3s_url: $url, lighthouse_nebula_ip: $lighthouse_ip, lighthouse_public_ip: $lighthouse_public_ip}'
  )" || echo "Warning: Could not update gpu-worker secret"

echo "=== Lighthouse Bootstrap Completed at $(date) ==="
echo "k3s server URL: https://${NEBULA_IP}:6443"
echo "k3s token: ${K3S_TOKEN}"
