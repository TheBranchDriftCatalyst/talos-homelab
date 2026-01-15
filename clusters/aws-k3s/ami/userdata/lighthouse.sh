#!/bin/bash
# =============================================================================
# EC2 k3s Node Userdata - Bootstrap with Nebula Mesh
# =============================================================================
# Connects to homelab Nebula lighthouse, starts k3s, and registers with Carrierarr
#
# Capabilities:
# - Fetches secrets from AWS Secrets Manager (including Nebula certs)
# - Configures Nebula mesh connection to homelab lighthouse
# - Starts k3s server with Cilium CNI
# - Configures worker-agent for fleet registration via gRPC

set -euo pipefail
exec > >(tee /var/log/userdata.log) 2>&1
echo "=== EC2 k3s Node Bootstrap Started at $(date) ==="

# =============================================================================
# Configuration
# =============================================================================
# Nebula lighthouse endpoint (homelab DDNS)
LIGHTHOUSE_ENDPOINT="${LIGHTHOUSE_ENDPOINT:-nebula.knowledgedump.space:4242}"
# Lighthouse Nebula IP
LIGHTHOUSE_NEBULA_IP="${LIGHTHOUSE_NEBULA_IP:-10.100.0.1}"
# Control plane address via Nebula mesh
CONTROL_PLANE_ADDR="${CONTROL_PLANE_ADDR:-${LIGHTHOUSE_NEBULA_IP}:50051}"

# Cilium/k3s config
CILIUM_CLUSTER_NAME="${CILIUM_CLUSTER_NAME:-aws-k3s}"
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
PUBLIC_IP=$(curl -s -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" http://169.254.169.254/latest/meta-data/public-ipv4 2> /dev/null || echo "")
PRIVATE_IP=$(curl -s -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" http://169.254.169.254/latest/meta-data/local-ipv4)

echo "Instance: ${INSTANCE_ID}, Public: ${PUBLIC_IP}, Private: ${PRIVATE_IP}"

# =============================================================================
# Fetch Secrets from AWS Secrets Manager
# =============================================================================
SECRET_NAME="${SECRET_NAME:-catalyst-llm/nebula-worker-001}"

echo "Fetching secrets from AWS Secrets Manager: ${SECRET_NAME}"
# Fetch secrets - strip ANSI codes that AWS CLI may add
SECRETS_RAW=$(AWS_PAGER="" aws secretsmanager get-secret-value --secret-id "${SECRET_NAME}" --region "${REGION}" --query SecretString --output text 2> /dev/null || echo "{}")
# shellcheck disable=SC2001  # Complex ANSI escape regex requires sed
SECRETS=$(echo "$SECRETS_RAW" | sed 's/\x1B\[[0-9;]*[JKmsu]//g')

K3S_TOKEN=$(echo "$SECRETS" | jq -r '.k3s_token // empty')

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
    # k3s API
    - port: 6443
      proto: tcp
      host: any
    # Cilium ClusterMesh
    - port: 32379
      proto: tcp
      host: any
NEBULACONF

  # Start Nebula
  systemctl enable nebula
  systemctl start nebula

  # Wait for Nebula to establish connection
  echo "Waiting for Nebula tunnel..."
  for i in {1..30}; do
    if ip link show nebula0 &> /dev/null; then
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
NODE_TYPE=k3s-server
INSTANCE_ID=${INSTANCE_ID}
PUBLIC_IP=${PUBLIC_IP}
PRIVATE_IP=${PRIVATE_IP}
NEBULA_IP=${NEBULA_IP}
CONTROL_PLANE_ADDR=${CONTROL_PLANE_ADDR}
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

# Use Nebula IP if available, otherwise fall back to private IP
K3S_ADVERTISE_IP="${NEBULA_IP:-$PRIVATE_IP}"

# Write k3s config - disable flannel, we use Cilium
cat > /etc/rancher/k3s/config.yaml << EOF
node-name: k3s-${INSTANCE_ID}
node-ip: ${K3S_ADVERTISE_IP}
node-external-ip: ${PUBLIC_IP}
bind-address: 0.0.0.0
advertise-address: ${K3S_ADVERTISE_IP}
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

# Add Nebula IP to TLS SANs if available
if [ -n "$NEBULA_IP" ]; then
  echo "  - ${NEBULA_IP}" >> /etc/rancher/k3s/config.yaml
fi

# Start k3s
systemctl enable k3s
systemctl start k3s

echo "Waiting for k3s to be ready..."
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

for i in {1..60}; do
  if kubectl get nodes 2> /dev/null; then
    echo "k3s API is ready!"
    break
  fi
  echo "Waiting for k3s API... ($i/60)"
  sleep 5
done

# =============================================================================
# Install Cilium with ClusterMesh (via Helm)
# =============================================================================
echo "Installing Cilium CNI with ClusterMesh via Helm..."

# Wait for node to be registered (will be NotReady until CNI is installed)
kubectl wait --for=jsonpath='{.status.conditions[?(@.type=="Ready")].status}'=False node --all --timeout=120s || true

# Add Cilium Helm repo
helm repo add cilium https://helm.cilium.io/
helm repo update

# Install Cilium via Helm (required for clustermesh connect to work)
helm install cilium cilium/cilium \
  --version "${CILIUM_VERSION}" \
  --namespace kube-system \
  --set cluster.name="${CILIUM_CLUSTER_NAME}" \
  --set cluster.id="${CILIUM_CLUSTER_ID}" \
  --set ipam.mode=kubernetes \
  --set kubeProxyReplacement=true \
  --set k8sServiceHost="${K3S_ADVERTISE_IP}" \
  --set k8sServicePort=6443 \
  --set hubble.enabled=true \
  --set hubble.relay.enabled=true \
  --set hubble.ui.enabled=true \
  --set clustermesh.useAPIServer=true \
  --set clustermesh.apiserver.replicas=1 \
  --set clustermesh.apiserver.service.type=NodePort \
  --set clustermesh.apiserver.service.nodePort=32379 \
  --set clustermesh.apiserver.tls.auto.enabled=true \
  --set clustermesh.apiserver.tls.auto.method=helm \
  --wait --timeout 10m

echo "Waiting for Cilium to be ready..."
cilium status --wait --wait-duration 5m

# Verify node is ready now
echo "Waiting for node to be Ready..."
kubectl wait --for=condition=ready node --all --timeout=300s

echo "=== EC2 k3s Node Bootstrap Completed at $(date) ==="
echo "Instance ID: ${INSTANCE_ID}"
echo "Public IP: ${PUBLIC_IP}"
echo "Private IP: ${PRIVATE_IP}"
echo "Nebula IP: ${NEBULA_IP}"
echo "k3s API: https://${K3S_ADVERTISE_IP}:6443"
echo "Control Plane: ${CONTROL_PLANE_ADDR}"
echo "Cilium ClusterMesh: ${CILIUM_CLUSTER_NAME} (ID: ${CILIUM_CLUSTER_ID})"
