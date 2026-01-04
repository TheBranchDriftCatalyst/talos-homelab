#!/bin/bash
# =============================================================================
# GPU Worker Userdata - Minimal Bootstrap for Pre-baked AMI
# =============================================================================
# This script runs at first boot to inject secrets and start services.
# The AMI already has all binaries and dependencies installed.
#
# Required Secrets (injected via AWS Secrets Manager or user-data):
# - NEBULA_CA_CRT: Nebula CA certificate
# - NEBULA_HOST_CRT: This node's certificate
# - NEBULA_HOST_KEY: This node's private key
# - CONTROL_PLANE_ADDR: gRPC control plane address (e.g., 10.42.0.1:50051)
# - K3S_TOKEN: k3s cluster join token
# - K3S_URL: k3s server URL (e.g., https://10.42.1.1:6443)

set -euo pipefail
exec > >(tee /var/log/userdata.log) 2>&1
echo "=== GPU Worker Bootstrap Started at $(date) ==="

# =============================================================================
# Configuration (override via user-data or instance tags)
# =============================================================================
NEBULA_IP="${NEBULA_IP:-}"
LIGHTHOUSE_NEBULA_IP="${LIGHTHOUSE_NEBULA_IP:-10.42.1.1}"
CONTROL_PLANE_ADDR="${CONTROL_PLANE_ADDR:-${LIGHTHOUSE_NEBULA_IP}:50051}"

# =============================================================================
# Fetch Secrets from AWS Secrets Manager
# =============================================================================
SECRET_NAME="${SECRET_NAME:-catalyst-llm/gpu-worker}"
REGION=$(curl -s http://169.254.169.254/latest/meta-data/placement/region)
INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)

echo "Fetching secrets from AWS Secrets Manager: ${SECRET_NAME}"
SECRETS=$(aws secretsmanager get-secret-value --secret-id "${SECRET_NAME}" --region "${REGION}" --query SecretString --output text)

# Extract secrets
NEBULA_CA_CRT=$(echo "$SECRETS" | jq -r '.nebula_ca_crt')
NEBULA_HOST_CRT=$(echo "$SECRETS" | jq -r '.nebula_host_crt')
NEBULA_HOST_KEY=$(echo "$SECRETS" | jq -r '.nebula_host_key')
K3S_TOKEN=$(echo "$SECRETS" | jq -r '.k3s_token // empty')
K3S_URL=$(echo "$SECRETS" | jq -r '.k3s_url // empty')

# Get nebula IP from secret or generate from instance ID
if [ -z "$NEBULA_IP" ]; then
  NEBULA_IP=$(echo "$SECRETS" | jq -r '.nebula_ip // empty')
fi

# =============================================================================
# Configure Nebula
# =============================================================================
echo "Configuring Nebula VPN..."

# Write certificates
echo "$NEBULA_CA_CRT" | base64 -d > /etc/nebula/ca.crt
echo "$NEBULA_HOST_CRT" | base64 -d > /etc/nebula/host.crt
echo "$NEBULA_HOST_KEY" | base64 -d > /etc/nebula/host.key
chmod 600 /etc/nebula/host.key

# Create Nebula config
cat > /etc/nebula/config.yml << EOF
pki:
  ca: /etc/nebula/ca.crt
  cert: /etc/nebula/host.crt
  key: /etc/nebula/host.key

static_host_map:
  "${LIGHTHOUSE_NEBULA_IP}": ["$(echo "$SECRETS" | jq -r '.lighthouse_public_ip'):4242"]

lighthouse:
  am_lighthouse: false
  interval: 60
  hosts:
    - "${LIGHTHOUSE_NEBULA_IP}"

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
    - port: 11434
      proto: tcp
      host: any
    - port: 6443
      proto: tcp
      host: any
    - port: 8472
      proto: udp
      host: any
EOF

# Start Nebula
systemctl enable nebula
systemctl start nebula

echo "Waiting for Nebula to establish connection..."
for i in {1..30}; do
  if ip addr show nebula1 2> /dev/null | grep -q "inet"; then
    echo "Nebula connected!"
    break
  fi
  sleep 2
done

# =============================================================================
# Configure worker-agent
# =============================================================================
echo "Configuring worker-agent..."

cat > /etc/worker-agent/env << EOF
CONTROL_PLANE_ADDR=${CONTROL_PLANE_ADDR}
NODE_TYPE=gpu-worker
INSTANCE_ID=${INSTANCE_ID}
NEBULA_IP=${NEBULA_IP}
EOF

systemctl enable worker-agent
systemctl start worker-agent

# =============================================================================
# Configure k3s agent (if joining cluster)
# =============================================================================
if [ -n "$K3S_TOKEN" ] && [ -n "$K3S_URL" ]; then
  echo "Configuring k3s agent..."

  # Wait for nebula to be ready
  sleep 5

  # Configure k3s agent
  cat > /etc/rancher/k3s/config.yaml << EOF
server: ${K3S_URL}
token: ${K3S_TOKEN}
node-name: ${INSTANCE_ID}
node-label:
  - "node.kubernetes.io/instance-type=gpu-worker"
  - "nvidia.com/gpu=true"
node-ip: ${NEBULA_IP}
flannel-iface: nebula1
EOF

  # Enable k3s agent
  systemctl enable k3s-agent
  systemctl start k3s-agent
fi

# =============================================================================
# Configure Ollama
# =============================================================================
echo "Configuring Ollama..."

# Mount models volume if available
if [ -b /dev/xvdb ]; then
  mkfs.xfs /dev/xvdb 2> /dev/null || true
  mkdir -p /var/lib/ollama
  mount /dev/xvdb /var/lib/ollama
  echo "/dev/xvdb /var/lib/ollama xfs defaults,nofail 0 2" >> /etc/fstab
fi

# Start Ollama
systemctl enable ollama
systemctl start ollama

echo "=== GPU Worker Bootstrap Completed at $(date) ==="
