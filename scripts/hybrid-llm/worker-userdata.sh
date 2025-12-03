#!/bin/bash
# LLM Worker Userdata Generator
# Reads certificates from .output/nebula/ and outputs a complete EC2 userdata script
# Installs: Nebula + k3s + Ollama
#
# Usage:
#   ./scripts/hybrid-llm/worker-userdata.sh > /tmp/worker-userdata.sh
#   aws ec2 run-instances --user-data file:///tmp/worker-userdata.sh ...

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUTPUT_DIR="$REPO_ROOT/.output/nebula"
CA_DIR="$HOME/.nebula-ca"

# Certificate paths - check both locations
if [[ -f "$OUTPUT_DIR/worker/host.crt" ]]; then
    CA_CRT="$OUTPUT_DIR/ca.crt"
    HOST_CRT="$OUTPUT_DIR/worker/host.crt"
    HOST_KEY="$OUTPUT_DIR/worker/host.key"
elif [[ -f "$CA_DIR/aws-gpu-worker.crt" ]]; then
    CA_CRT="$CA_DIR/ca.crt"
    HOST_CRT="$CA_DIR/aws-gpu-worker.crt"
    HOST_KEY="$CA_DIR/aws-gpu-worker.key"
else
    echo "ERROR: Worker certificates not found" >&2
    echo "Generate with: nebula-cert sign -name aws-gpu-worker -ip 10.42.2.1/16 -groups kubernetes,infrastructure,gpu-compute" >&2
    exit 1
fi

# Lighthouse IP (from state file or default)
STATE_FILE="$REPO_ROOT/.output/lighthouse-state.json"
if [[ -f "$STATE_FILE" ]]; then
    LIGHTHOUSE_IP=$(jq -r '.elastic_ip // "52.13.210.163"' "$STATE_FILE")
else
    LIGHTHOUSE_IP="52.13.210.163"
fi

# Output the userdata script with embedded certificates
cat << 'HEADER'
#!/bin/bash
# LLM Worker Bootstrap Script
# Auto-generated - installs Nebula + k3s + Ollama
# This runs on first boot of the EC2 instance

set -euo pipefail
exec > >(tee /var/log/worker-bootstrap.log) 2>&1

echo "=== Starting LLM Worker Bootstrap ==="
echo "Timestamp: $(date)"

# Install dependencies (--allowerasing handles curl-minimal conflict on AL2023)
dnf install -y --allowerasing tar gzip curl jq

#############################################
# PHASE 0: Mount model storage volume
#############################################
echo "=== Phase 0: Mounting model storage volume ==="

OLLAMA_DATA_DIR="/var/lib/ollama"
MODEL_DEVICE="/dev/xvdf"

# Wait for the EBS volume to be attached
echo "Waiting for model storage volume..."
for i in {1..30}; do
    if [[ -b "$MODEL_DEVICE" ]] || [[ -b "/dev/nvme1n1" ]]; then
        echo "Model volume detected"
        break
    fi
    sleep 2
done

# Determine the actual device (NVMe instances use different naming)
if [[ -b "/dev/nvme1n1" ]]; then
    MODEL_DEVICE="/dev/nvme1n1"
fi

if [[ -b "$MODEL_DEVICE" ]]; then
    # Check if filesystem exists
    if ! blkid "$MODEL_DEVICE" | grep -q "TYPE="; then
        echo "Creating XFS filesystem on model volume..."
        mkfs.xfs -f "$MODEL_DEVICE"
    fi

    # Create mount point and mount
    mkdir -p "$OLLAMA_DATA_DIR"
    mount "$MODEL_DEVICE" "$OLLAMA_DATA_DIR"

    # Add to fstab for persistence across restarts
    if ! grep -q "$OLLAMA_DATA_DIR" /etc/fstab; then
        UUID=$(blkid -s UUID -o value "$MODEL_DEVICE")
        echo "UUID=$UUID $OLLAMA_DATA_DIR xfs defaults,nofail 0 2" >> /etc/fstab
    fi

    echo "Model storage mounted at $OLLAMA_DATA_DIR"
else
    echo "WARNING: Model storage volume not found - using root volume"
    mkdir -p "$OLLAMA_DATA_DIR"
fi

#############################################
# PHASE 1: Install Nebula
#############################################
echo "=== Phase 1: Installing Nebula ==="

NEBULA_VERSION="1.9.5"
cd /tmp
curl -LO "https://github.com/slackhq/nebula/releases/download/v${NEBULA_VERSION}/nebula-linux-amd64.tar.gz"
tar xzf nebula-linux-amd64.tar.gz
mv nebula /usr/local/bin/
mv nebula-cert /usr/local/bin/
chmod +x /usr/local/bin/nebula /usr/local/bin/nebula-cert

mkdir -p /etc/nebula

# Write CA certificate
cat > /etc/nebula/ca.crt << 'CACERT'
HEADER

# Embed CA certificate
cat "$CA_CRT"

cat << 'MIDDLE1'
CACERT

# Write host certificate
cat > /etc/nebula/host.crt << 'HOSTCERT'
MIDDLE1

# Embed host certificate
cat "$HOST_CRT"

cat << 'MIDDLE2'
HOSTCERT

# Write host key
cat > /etc/nebula/host.key << 'HOSTKEY'
MIDDLE2

# Embed host key
cat "$HOST_KEY"

# Embed lighthouse IP
cat << MIDDLE3
HOSTKEY

chmod 600 /etc/nebula/host.key

# Write Nebula config
cat > /etc/nebula/config.yaml << 'EOF'
pki:
  ca: /etc/nebula/ca.crt
  cert: /etc/nebula/host.crt
  key: /etc/nebula/host.key

static_host_map:
  "10.42.0.1": ["${LIGHTHOUSE_IP}:4242"]

lighthouse:
  am_lighthouse: false
  interval: 60
  hosts:
    - "10.42.0.1"

listen:
  host: 0.0.0.0
  port: 4242

punchy:
  punch: true
  respond: true

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
      proto: any
      group: lighthouse
    - port: any
      proto: any
      group: infrastructure
    - port: any
      proto: any
      group: kubernetes
    - port: any
      proto: any
      group: homelab
    - port: any
      proto: icmp
      host: any
    # k3s API
    - port: 6443
      proto: tcp
      host: any
    # Kubelet
    - port: 10250
      proto: tcp
      host: any
    # Ollama API
    - port: 11434
      proto: tcp
      host: any
EOF

# Create systemd service for Nebula
cat > /etc/systemd/system/nebula.service << 'SVCEOF'
[Unit]
Description=Nebula Mesh VPN
Wants=basic.target network-online.target
After=basic.target network-online.target
Before=k3s.service

[Service]
Type=simple
ExecStart=/usr/local/bin/nebula -config /etc/nebula/config.yaml
ExecReload=/bin/kill -HUP \$MAINPID
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable nebula
systemctl start nebula

# Wait for Nebula to establish connection
echo "Waiting for Nebula mesh connection..."
for i in {1..30}; do
    if ip addr show nebula1 2>/dev/null | grep -q "10.42.2.1"; then
        echo "Nebula connected: 10.42.2.1"
        break
    fi
    sleep 2
done

#############################################
# PHASE 2: Install k3s
#############################################
echo "=== Phase 2: Installing k3s ==="

# Install k3s (single node, no traefik - we use the mesh)
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server \
    --disable=traefik \
    --disable=servicelb \
    --node-ip=10.42.2.1 \
    --flannel-iface=nebula1 \
    --write-kubeconfig-mode=644" sh -

# Wait for k3s to be ready
echo "Waiting for k3s to be ready..."
until kubectl get nodes 2>/dev/null | grep -q "Ready"; do
    sleep 5
done
echo "k3s is ready"

#############################################
# PHASE 3: Install Ollama
#############################################
echo "=== Phase 3: Installing Ollama ==="

# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Configure Ollama to listen on all interfaces and use persistent storage
mkdir -p /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/override.conf << 'OLLAMACONF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
Environment="OLLAMA_MODELS=/var/lib/ollama/models"
Environment="HOME=/var/lib/ollama"
OLLAMACONF

# Ensure ollama user owns the data directory
chown -R ollama:ollama /var/lib/ollama 2>/dev/null || true

systemctl daemon-reload
systemctl enable ollama
systemctl start ollama

# Wait for Ollama to be ready
echo "Waiting for Ollama to be ready..."
for i in {1..30}; do
    if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
        echo "Ollama is ready"
        break
    fi
    sleep 2
done

# Pre-pull a default model (can be changed)
echo "Pre-pulling llama3.2 model (this may take a while)..."
ollama pull llama3.2 || echo "Model pull failed - can be done manually later"

#############################################
# PHASE 4: Create Kubernetes resources
#############################################
echo "=== Phase 4: Creating Kubernetes resources ==="

# Create Ollama service for k3s
cat << 'K8SEOF' | kubectl apply -f -
apiVersion: v1
kind: Service
metadata:
  name: ollama
  namespace: default
spec:
  type: ClusterIP
  ports:
    - port: 11434
      targetPort: 11434
      name: http
  selector:
    app: ollama-external
---
apiVersion: v1
kind: Endpoints
metadata:
  name: ollama
  namespace: default
subsets:
  - addresses:
      - ip: 10.42.2.1
    ports:
      - port: 11434
        name: http
K8SEOF

echo "=== LLM Worker Bootstrap Complete ==="
echo "Nebula IP: 10.42.2.1"
echo "Ollama API: http://10.42.2.1:11434"
echo "k3s kubeconfig: /etc/rancher/k3s/k3s.yaml"
MIDDLE3
