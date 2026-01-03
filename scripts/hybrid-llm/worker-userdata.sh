#!/bin/bash
# LLM Worker (k3s Agent) Userdata Generator
# Reads certificates from .output/nebula/ and outputs a complete EC2 userdata script
# Installs: Nebula + k3s agent (joins lighthouse control plane) + Ollama
#
# The worker joins the lighthouse's k3s cluster as an agent node.
# This allows Liqo to see and schedule GPU workloads on this node.
#
# Prerequisites:
#   - Lighthouse must be running with k3s server
#   - K3S_TOKEN must be set (from lighthouse: cat /var/lib/rancher/k3s/server/node-token)
#
# Usage:
#   K3S_TOKEN="xxx" ./scripts/hybrid-llm/worker-userdata.sh > /tmp/worker-userdata.sh
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

# Lighthouse config (from state file or default)
STATE_FILE="$REPO_ROOT/.output/lighthouse-state.json"
if [[ -f "$STATE_FILE" ]]; then
  LIGHTHOUSE_PUBLIC_IP=$(jq -r '.elastic_ip // "52.10.38.70"' "$STATE_FILE")
else
  LIGHTHOUSE_PUBLIC_IP="${LIGHTHOUSE_PUBLIC_IP:-52.10.38.70}"
fi

# k3s token for joining the cluster
# Can be set via environment or read from a file
K3S_TOKEN_FILE="$REPO_ROOT/.output/k3s-token"
if [[ -z "${K3S_TOKEN:-}" ]]; then
  if [[ -f "$K3S_TOKEN_FILE" ]]; then
    K3S_TOKEN=$(cat "$K3S_TOKEN_FILE")
  else
    echo "ERROR: K3S_TOKEN not set and $K3S_TOKEN_FILE not found" >&2
    echo "" >&2
    echo "Get the token from the lighthouse:" >&2
    echo "  ssh -i .output/ssh/hybrid-llm-key.pem ec2-user@$LIGHTHOUSE_PUBLIC_IP 'sudo cat /var/lib/rancher/k3s/server/node-token'" >&2
    echo "" >&2
    echo "Then either:" >&2
    echo "  1. Set K3S_TOKEN environment variable" >&2
    echo "  2. Save to $K3S_TOKEN_FILE" >&2
    exit 1
  fi
fi

# Lighthouse Nebula mesh IP (always 10.42.0.1)
LIGHTHOUSE_MESH_IP="10.42.0.1"

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
cat << 'MIDDLE3'
HOSTKEY

chmod 600 /etc/nebula/host.key

# Write Nebula config
cat > /etc/nebula/config.yaml << 'EOF'
pki:
  ca: /etc/nebula/ca.crt
  cert: /etc/nebula/host.crt
  key: /etc/nebula/host.key

static_host_map:
  "10.42.0.1": ["${LIGHTHOUSE_PUBLIC_IP}:4242"]

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
# PHASE 2: Install k3s Agent
#############################################
echo "=== Phase 2: Installing k3s Agent ==="

# k3s server URL and token (embedded at userdata generation time)
K3S_URL="https://10.42.0.1:6443"
K3S_TOKEN="${K3S_TOKEN}"

# Wait for lighthouse k3s API to be reachable via Nebula
echo "Waiting for k3s API server at \$K3S_URL..."
for i in {1..60}; do
    if curl -sk "\$K3S_URL/healthz" 2>/dev/null | grep -q "ok"; then
        echo "k3s API server is reachable"
        break
    fi
    echo "  Attempt \$i/60 - waiting for k3s API..."
    sleep 5
done

# Install k3s as AGENT (joins lighthouse's cluster)
# - Uses Nebula mesh for cluster communication
# - Labeled as GPU node for Liqo/scheduler targeting
curl -sfL https://get.k3s.io | K3S_URL="\$K3S_URL" K3S_TOKEN="\$K3S_TOKEN" \
    INSTALL_K3S_EXEC="agent \
    --node-ip=10.42.2.1 \
    --flannel-iface=nebula1 \
    --node-label=node-type=gpu \
    --node-label=topology.kubernetes.io/region=aws \
    --node-label=topology.kubernetes.io/zone=us-west-2 \
    --node-label=nvidia.com/gpu.present=true" sh -

# Wait for this node to be Ready in the cluster
echo "Waiting for node to join cluster..."
for i in {1..60}; do
    if curl -sk "\$K3S_URL/api/v1/nodes" -H "Authorization: Bearer \$K3S_TOKEN" 2>/dev/null | grep -q "gpu-worker"; then
        echo "Node joined cluster successfully"
        break
    fi
    sleep 5
done
echo "k3s agent is ready"

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
# PHASE 4: Install NVIDIA drivers (if GPU instance)
#############################################
echo "=== Phase 4: Checking for GPU and installing drivers ==="

# Check if this is a GPU instance
if lspci | grep -i nvidia > /dev/null 2>&1; then
    echo "NVIDIA GPU detected - installing drivers..."

    # Install NVIDIA drivers (Amazon Linux 2023)
    dnf install -y kernel-devel kernel-headers
    dnf config-manager --add-repo https://developer.download.nvidia.com/compute/cuda/repos/amzn2023/x86_64/cuda-amzn2023.repo
    dnf install -y nvidia-driver nvidia-driver-cuda

    # Install NVIDIA container toolkit for k3s
    curl -s -L https://nvidia.github.io/libnvidia-container/stable/rpm/nvidia-container-toolkit.repo | \
        tee /etc/yum.repos.d/nvidia-container-toolkit.repo
    dnf install -y nvidia-container-toolkit

    # Configure containerd for NVIDIA
    nvidia-ctk runtime configure --runtime=containerd
    systemctl restart containerd || true

    echo "NVIDIA drivers installed"
else
    echo "No NVIDIA GPU detected - skipping driver installation"
fi

#############################################
# PHASE 5: Self-Destruct Watchdog (Cost Control)
#############################################
echo "=== Phase 5: Installing Self-Destruct Watchdog ==="

# The watchdog monitors ollama activity and shuts down after 120 minutes of inactivity
# This prevents runaway EC2 costs from forgotten instances

IDLE_TIMEOUT_MINUTES=120

cat > /usr/local/bin/llm-watchdog.sh << 'WATCHDOG'
#!/bin/bash
# LLM Worker Self-Destruct Watchdog
# Monitors ollama activity and shuts down instance after idle timeout
# Runs every minute via systemd timer

ACTIVITY_FILE="/var/run/llm-activity"
IDLE_TIMEOUT_SECONDS=$((120 * 60))  # 120 minutes in seconds
LOG_FILE="/var/log/llm-watchdog.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOG_FILE"
}

# Check if ollama is actively processing
check_activity() {
    # Check if any model is currently loaded (indicates active use)
    local ps_output=$(curl -s http://localhost:11434/api/ps 2>/dev/null)

    if [[ -n "$ps_output" ]] && echo "$ps_output" | jq -e '.models | length > 0' >/dev/null 2>&1; then
        return 0  # Active - models are loaded
    fi

    # Also check for recent API requests via ollama logs
    # If ollama received a request in the last minute, consider it active
    if journalctl -u ollama --since "1 minute ago" 2>/dev/null | grep -qE "request|generation|model"; then
        return 0  # Active - recent requests
    fi

    return 1  # Idle
}

# Get last activity timestamp (seconds since epoch)
get_last_activity() {
    if [[ -f "$ACTIVITY_FILE" ]]; then
        cat "$ACTIVITY_FILE"
    else
        # First run - set to now
        date +%s
    fi
}

# Update last activity timestamp
update_activity() {
    date +%s > "$ACTIVITY_FILE"
}

# Main watchdog logic
main() {
    local now=$(date +%s)
    local last_activity=$(get_last_activity)
    local idle_seconds=$((now - last_activity))

    if check_activity; then
        # Active - reset timer
        update_activity
        log "Active: resetting idle timer"
    else
        # Idle - check if we should shutdown
        local remaining=$((IDLE_TIMEOUT_SECONDS - idle_seconds))

        if [[ $idle_seconds -ge $IDLE_TIMEOUT_SECONDS ]]; then
            log "SHUTDOWN: Idle for $((idle_seconds / 60)) minutes - initiating self-destruct"
            echo "LLM Worker idle for $((idle_seconds / 60)) minutes - shutting down to save costs"

            # Graceful shutdown
            systemctl stop ollama
            systemctl stop k3s-agent || true

            # Use AWS CLI to stop this instance (more reliable than just OS shutdown)
            INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)
            if [[ -n "$INSTANCE_ID" ]]; then
                log "Stopping instance $INSTANCE_ID via AWS API"
                aws ec2 stop-instances --instance-ids "$INSTANCE_ID" --region us-west-2 2>/dev/null || \
                    shutdown -h now
            else
                shutdown -h now
            fi
        else
            log "Idle: ${idle_seconds}s / ${IDLE_TIMEOUT_SECONDS}s (${remaining}s remaining)"
        fi
    fi
}

main
WATCHDOG

chmod +x /usr/local/bin/llm-watchdog.sh

# Create systemd service for the watchdog
cat > /etc/systemd/system/llm-watchdog.service << 'WDSVC'
[Unit]
Description=LLM Worker Self-Destruct Watchdog
After=ollama.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/llm-watchdog.sh
WDSVC

# Create systemd timer to run watchdog every minute
cat > /etc/systemd/system/llm-watchdog.timer << 'WDTIMER'
[Unit]
Description=LLM Worker Watchdog Timer
Requires=llm-watchdog.service

[Timer]
OnBootSec=5min
OnUnitActiveSec=1min
AccuracySec=30s

[Install]
WantedBy=timers.target
WDTIMER

# Initialize activity file (first activity = now)
mkdir -p /var/run
date +%s > /var/run/llm-activity

# Enable and start the timer
systemctl daemon-reload
systemctl enable llm-watchdog.timer
systemctl start llm-watchdog.timer

echo "Self-destruct watchdog installed:"
echo "  - Monitors every minute"
echo "  - Shuts down after 120 minutes of inactivity"
echo "  - Activity resets on any ollama API usage"

#############################################
# Summary
#############################################
echo ""
echo "=== LLM Worker Bootstrap Complete ==="
echo ""
echo "Nebula:"
echo "  Mesh IP: 10.42.2.1"
echo "  Lighthouse: 10.42.0.1"
echo ""
echo "k3s Agent:"
echo "  Joined cluster at: https://10.42.0.1:6443"
echo "  Node labels: node-type=gpu"
echo ""
echo "Ollama:"
echo "  API: http://10.42.2.1:11434"
echo "  Models: /var/lib/ollama/models"
echo ""
echo "Self-Destruct Watchdog:"
echo "  Idle timeout: 120 minutes"
echo "  Log: /var/log/llm-watchdog.log"
echo ""
echo "This node is now part of the aws-gpu-cluster and visible via Liqo."
echo "Workloads with nodeSelector 'node-type: gpu' will schedule here."
echo ""
echo "NOTE: Instance will auto-shutdown after 120 minutes of inactivity!"
echo ""
MIDDLE3
