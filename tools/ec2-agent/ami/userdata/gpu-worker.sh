#!/bin/bash
# =============================================================================
# GPU Worker Userdata - Minimal Bootstrap (Nebula-free stub)
# =============================================================================
# NOTE: This is a minimal stub. Full implementation pending TALOS-700h
#       which will add proper Nebula mesh with home-as-lighthouse architecture.
#
# Current capabilities:
# - Fetches secrets from AWS Secrets Manager
# - Configures worker-agent for fleet registration
# - Starts Ollama for LLM inference
# - Optionally joins k3s cluster if K3S_TOKEN provided

set -euo pipefail
exec > >(tee /var/log/userdata.log) 2>&1
echo "=== GPU Worker Bootstrap Started at $(date) ==="

# =============================================================================
# Configuration
# =============================================================================
RABBITMQ_URL="${RABBITMQ_URL:-}"

# =============================================================================
# Fetch Instance Metadata (IMDSv2)
# =============================================================================
IMDS_TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
REGION=$(curl -s -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" http://169.254.169.254/latest/meta-data/placement/region)
INSTANCE_ID=$(curl -s -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" http://169.254.169.254/latest/meta-data/instance-id)
PUBLIC_IP=$(curl -s -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "")
PRIVATE_IP=$(curl -s -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" http://169.254.169.254/latest/meta-data/local-ipv4)

# =============================================================================
# Fetch Secrets from AWS Secrets Manager
# =============================================================================
SECRET_NAME="${SECRET_NAME:-catalyst-llm/gpu-worker}"

echo "Fetching secrets from AWS Secrets Manager: ${SECRET_NAME}"
SECRETS=$(aws secretsmanager get-secret-value --secret-id "${SECRET_NAME}" --region "${REGION}" --query SecretString --output text 2>/dev/null || echo "{}")

K3S_TOKEN=$(echo "$SECRETS" | jq -r '.k3s_token // empty')
K3S_URL=$(echo "$SECRETS" | jq -r '.k3s_url // empty')

# Get RabbitMQ URL from secret if not provided via env
if [ -z "$RABBITMQ_URL" ]; then
  RABBITMQ_URL=$(echo "$SECRETS" | jq -r '.rabbitmq_url // empty')
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
RABBITMQ_URL=${RABBITMQ_URL}
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
echo "Ollama: http://${PRIVATE_IP}:11434"
echo ""
echo "NOTE: Nebula mesh is not configured. See TALOS-700h for proper mesh implementation."
