#!/bin/bash
# =============================================================================
# GPU Worker Userdata - Bootstrap with Nebula Mesh
# =============================================================================
# Connects to homelab Nebula lighthouse and registers with Carrierarr
#
# Capabilities:
# - Fetches secrets from AWS Secrets Manager (including Nebula certs)
# - Configures Nebula mesh connection to homelab lighthouse
# - Configures worker-agent for fleet registration via gRPC
# - Starts Ollama for LLM inference
# - Optionally joins k3s cluster if K3S_TOKEN provided

set -euo pipefail
exec > >(tee /var/log/userdata.log) 2>&1
echo "=== GPU Worker Bootstrap Started at $(date) ==="

# =============================================================================
# Configuration
# =============================================================================
# Nebula lighthouse endpoint (homelab DDNS)
LIGHTHOUSE_ENDPOINT="${LIGHTHOUSE_ENDPOINT:-nebula.knowledgedump.space:4242}"
# Lighthouse Nebula IP
LIGHTHOUSE_NEBULA_IP="${LIGHTHOUSE_NEBULA_IP:-10.100.0.1}"
# Control plane address via Nebula mesh
CONTROL_PLANE_ADDR="${CONTROL_PLANE_ADDR:-${LIGHTHOUSE_NEBULA_IP}:50051}"

# =============================================================================
# Fetch Instance Metadata (IMDSv2)
# =============================================================================
IMDS_TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
REGION=$(curl -s -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" http://169.254.169.254/latest/meta-data/placement/region)
INSTANCE_ID=$(curl -s -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" http://169.254.169.254/latest/meta-data/instance-id)
PUBLIC_IP=$(curl -s -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "")
PRIVATE_IP=$(curl -s -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" http://169.254.169.254/latest/meta-data/local-ipv4)

echo "Instance: ${INSTANCE_ID}, Public: ${PUBLIC_IP}, Private: ${PRIVATE_IP}"

# =============================================================================
# Fetch Secrets from AWS Secrets Manager
# =============================================================================
SECRET_NAME="${SECRET_NAME:-catalyst-llm/gpu-worker}"

echo "Fetching secrets from AWS Secrets Manager: ${SECRET_NAME}"
SECRETS=$(aws secretsmanager get-secret-value --secret-id "${SECRET_NAME}" --region "${REGION}" --query SecretString --output text 2>/dev/null || echo "{}")

K3S_TOKEN=$(echo "$SECRETS" | jq -r '.k3s_token // empty')
K3S_URL=$(echo "$SECRETS" | jq -r '.k3s_url // empty')

# Nebula certificates from secrets
NEBULA_CA_CRT=$(echo "$SECRETS" | jq -r '.nebula_ca_crt // empty')
NEBULA_NODE_CRT=$(echo "$SECRETS" | jq -r '.nebula_node_crt // empty')
NEBULA_NODE_KEY=$(echo "$SECRETS" | jq -r '.nebula_node_key // empty')
NEBULA_IP=$(echo "$SECRETS" | jq -r '.nebula_ip // empty')

# Override lighthouse endpoint from secrets if provided
LIGHTHOUSE_ENDPOINT_SECRET=$(echo "$SECRETS" | jq -r '.lighthouse_endpoint // empty')
if [ -n "$LIGHTHOUSE_ENDPOINT_SECRET" ]; then
  LIGHTHOUSE_ENDPOINT="$LIGHTHOUSE_ENDPOINT_SECRET"
fi

# =============================================================================
# Configure Nebula Mesh
# =============================================================================
if [ -n "$NEBULA_CA_CRT" ] && [ -n "$NEBULA_NODE_CRT" ] && [ -n "$NEBULA_NODE_KEY" ]; then
  echo "Configuring Nebula mesh..."

  # Write certificates
  echo "$NEBULA_CA_CRT" > /etc/nebula/ca.crt
  echo "$NEBULA_NODE_CRT" > /etc/nebula/node.crt
  echo "$NEBULA_NODE_KEY" > /etc/nebula/node.key
  chmod 600 /etc/nebula/node.key

  # Create Nebula config
  cat > /etc/nebula/config.yaml << NEBULACONF
# Nebula Worker Configuration
# Connects to homelab lighthouse

pki:
  ca: /etc/nebula/ca.crt
  cert: /etc/nebula/node.crt
  key: /etc/nebula/node.key

lighthouse:
  am_lighthouse: false
  hosts:
    - "${LIGHTHOUSE_NEBULA_IP}"

static_host_map:
  "${LIGHTHOUSE_NEBULA_IP}":
    - "${LIGHTHOUSE_ENDPOINT}"

listen:
  host: 0.0.0.0
  port: 4242

punchy:
  punch: true
  respond: true

relay:
  am_relay: false
  use_relays: true

tun:
  disabled: false
  dev: nebula0
  mtu: 1300

logging:
  level: info
  format: text

firewall:
  conntrack:
    tcp_timeout: 12m
    udp_timeout: 3m
    default_timeout: 10m

  outbound:
    - port: any
      proto: any
      host: any

  inbound:
    - port: any
      proto: icmp
      host: any
    - port: any
      proto: any
      groups:
        - lighthouse
        - homelab
    - port: 11434
      proto: tcp
      groups:
        - workers
NEBULACONF

  # Start Nebula
  systemctl enable nebula
  systemctl start nebula

  # Wait for Nebula to establish connection
  echo "Waiting for Nebula tunnel..."
  for i in {1..30}; do
    if ip link show nebula0 &>/dev/null; then
      NEBULA_IP=$(ip addr show nebula0 | grep -oP 'inet \K[\d.]+')
      echo "Nebula connected! IP: ${NEBULA_IP}"
      break
    fi
    echo "Waiting for Nebula... ($i/30)"
    sleep 2
  done
else
  echo "WARNING: Nebula certificates not found in secrets, skipping mesh setup"
  NEBULA_IP=""
fi

# =============================================================================
# Configure worker-agent
# =============================================================================
echo "Configuring worker-agent..."

cat > /etc/worker-agent/env << EOF
NODE_TYPE=gpu-worker
INSTANCE_ID=${INSTANCE_ID}
PUBLIC_IP=${PUBLIC_IP}
PRIVATE_IP=${PRIVATE_IP}
NEBULA_IP=${NEBULA_IP}
CONTROL_PLANE_ADDR=${CONTROL_PLANE_ADDR}
EOF

systemctl enable worker-agent
systemctl start worker-agent

# =============================================================================
# Configure k3s agent (if joining cluster)
# =============================================================================
if [ -n "$K3S_TOKEN" ] && [ -n "$K3S_URL" ]; then
  echo "Configuring k3s agent to join: ${K3S_URL}"

  # Configure k3s agent
  cat > /etc/rancher/k3s/config.yaml << EOF
server: ${K3S_URL}
token: ${K3S_TOKEN}
node-name: ${INSTANCE_ID}
node-label:
  - "node.kubernetes.io/instance-type=gpu-worker"
  - "nvidia.com/gpu=true"
node-ip: ${PRIVATE_IP}
EOF

  # Enable k3s agent
  systemctl enable k3s-agent
  systemctl start k3s-agent
else
  echo "K3S_TOKEN or K3S_URL not provided, skipping k3s agent setup"
fi

# =============================================================================
# Configure Ollama
# =============================================================================
echo "Configuring Ollama..."

# Mount models volume if available
if [ -b /dev/xvdb ]; then
  mkfs.xfs /dev/xvdb 2>/dev/null || true
  mkdir -p /var/lib/ollama
  mount /dev/xvdb /var/lib/ollama
  echo "/dev/xvdb /var/lib/ollama xfs defaults,nofail 0 2" >> /etc/fstab
fi

# Start Ollama
systemctl enable ollama
systemctl start ollama

# Wait for Ollama to be ready
echo "Waiting for Ollama to be ready..."
for i in {1..30}; do
  if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "Ollama is ready!"
    break
  fi
  echo "Waiting for Ollama... ($i/30)"
  sleep 2
done

echo "=== GPU Worker Bootstrap Completed at $(date) ==="
echo "Instance ID: ${INSTANCE_ID}"
echo "Public IP: ${PUBLIC_IP}"
echo "Private IP: ${PRIVATE_IP}"
echo "Nebula IP: ${NEBULA_IP}"
echo "Control Plane: ${CONTROL_PLANE_ADDR}"
echo "Ollama: http://${PRIVATE_IP}:11434"
if [ -n "$NEBULA_IP" ]; then
  echo "Ollama via Nebula: http://${NEBULA_IP}:11434"
fi
