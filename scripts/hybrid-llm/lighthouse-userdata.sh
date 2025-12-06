#!/bin/bash
# Nebula Lighthouse + k3s Control Plane + Liqo Provider Userdata Generator
# Reads certificates from .output/nebula/ and outputs a complete EC2 userdata script
#
# This creates an always-on AWS control plane that:
# - Runs Nebula lighthouse for mesh coordination
# - Runs k3s server as the AWS cluster control plane
# - Runs Liqo provider to peer with homelab (Talos)
# - GPU workers join this cluster as k3s agents
#
# Prerequisites:
#   ./scripts/hybrid-llm/nebula-certs.sh init        # Generate CA
#   ./scripts/hybrid-llm/nebula-certs.sh lighthouse  # Generate lighthouse cert
#
# Usage:
#   # Generate userdata and pass to AWS CLI
#   ./scripts/hybrid-llm/lighthouse-userdata.sh > /tmp/userdata.sh
#   aws ec2 run-instances --user-data file:///tmp/userdata.sh ...
#
#   # Or pipe directly (base64 encoded)
#   ./scripts/hybrid-llm/lighthouse-userdata.sh | base64 | aws ec2 run-instances --user-data ...

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUTPUT_DIR="$REPO_ROOT/.output/nebula"

# Certificate paths
CA_CRT="$OUTPUT_DIR/ca.crt"
HOST_CRT="$OUTPUT_DIR/lighthouse/host.crt"
HOST_KEY="$OUTPUT_DIR/lighthouse/host.key"

# Verify certificates exist
check_certs() {
    local missing=0
    if [[ ! -f "$CA_CRT" ]]; then
        echo "ERROR: CA certificate not found at $CA_CRT" >&2
        missing=1
    fi
    if [[ ! -f "$HOST_CRT" ]]; then
        echo "ERROR: Lighthouse certificate not found at $HOST_CRT" >&2
        missing=1
    fi
    if [[ ! -f "$HOST_KEY" ]]; then
        echo "ERROR: Lighthouse key not found at $HOST_KEY" >&2
        missing=1
    fi

    if [[ $missing -eq 1 ]]; then
        echo "" >&2
        echo "Generate certificates first:" >&2
        echo "  $SCRIPT_DIR/nebula-certs.sh init" >&2
        echo "  $SCRIPT_DIR/nebula-certs.sh lighthouse" >&2
        exit 1
    fi
}

check_certs

# Output the userdata script with embedded certificates
cat << 'HEADER'
#!/bin/bash
# Nebula Lighthouse + k3s + Liqo Bootstrap Script
# Auto-generated - certificates embedded from .output/nebula/
# This runs on first boot of the EC2 instance

set -euo pipefail
exec > >(tee /var/log/lighthouse-bootstrap.log) 2>&1

echo "=== Starting Lighthouse Bootstrap (Nebula + k3s + Liqo) ==="
echo "Timestamp: $(date)"

#############################################
# PHASE 0: Install dependencies
#############################################
echo "=== Phase 0: Installing dependencies ==="
dnf install -y --allowerasing tar gzip curl jq git

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

# Create config directory
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

cat << 'FOOTER'
HOSTKEY

chmod 600 /etc/nebula/host.key

# Get public IP for config (using IMDSv2 with token)
TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
PUBLIC_IP=$(curl -s -H "X-aws-ec2-metadata-token: \$TOKEN" http://169.254.169.254/latest/meta-data/public-ipv4)

# Fallback to Elastic IP if metadata fails
if [[ -z "\$PUBLIC_IP" ]]; then
    echo "WARNING: Could not get public IP from metadata service"
    PUBLIC_IP="ELASTIC_IP_PLACEHOLDER"
fi

# Write Nebula config
cat > /etc/nebula/config.yaml << EOF
pki:
  ca: /etc/nebula/ca.crt
  cert: /etc/nebula/host.crt
  key: /etc/nebula/host.key

static_host_map:
  "10.42.0.1": ["${PUBLIC_IP}:4242"]

lighthouse:
  am_lighthouse: true
  interval: 60

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
    # Allow all traffic from infrastructure group
    - port: any
      proto: any
      group: infrastructure

    # Allow all traffic from kubernetes group
    - port: any
      proto: any
      group: kubernetes

    # Allow all traffic from homelab group
    - port: any
      proto: any
      group: homelab

    # Allow ICMP from anywhere in the mesh
    - port: any
      proto: icmp
      host: any

    # k3s API server (for GPU workers to join)
    - port: 6443
      proto: tcp
      host: any

    # Kubelet API
    - port: 10250
      proto: tcp
      host: any
EOF

# Create systemd service for Nebula
cat > /etc/systemd/system/nebula.service << 'SVCEOF'
[Unit]
Description=Nebula Mesh VPN
Wants=basic.target network-online.target
After=basic.target network-online.target
Before=sshd.service k3s.service

[Service]
Type=simple
ExecStart=/usr/local/bin/nebula -config /etc/nebula/config.yaml
ExecReload=/bin/kill -HUP \$MAINPID
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVCEOF

# Enable and start Nebula
systemctl daemon-reload
systemctl enable nebula
systemctl start nebula

# Wait for Nebula to establish interface
echo "Waiting for Nebula interface..."
for i in {1..30}; do
    if ip addr show nebula1 2>/dev/null | grep -q "10.42.0.1"; then
        echo "Nebula connected: 10.42.0.1"
        break
    fi
    sleep 2
done

#############################################
# PHASE 2: Install k3s (Server Mode)
#############################################
echo "=== Phase 2: Installing k3s Server ==="

# Install k3s as server (control plane)
# - Binds to Nebula mesh IP for cluster communication
# - Disables traefik/servicelb (we use homelab's Traefik)
# - Uses Nebula interface for flannel CNI
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server \
    --disable=traefik \
    --disable=servicelb \
    --node-ip=10.42.0.1 \
    --advertise-address=10.42.0.1 \
    --flannel-iface=nebula1 \
    --write-kubeconfig-mode=644 \
    --node-label=topology.kubernetes.io/region=aws \
    --node-label=topology.kubernetes.io/zone=us-west-2 \
    --node-label=node-type=control-plane" sh -

# Wait for k3s to be ready (node Ready + API responsive)
echo "Waiting for k3s to be ready..."
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
echo "export KUBECONFIG=/etc/rancher/k3s/k3s.yaml" >> /root/.bashrc

# Wait for node to be Ready
for i in {1..60}; do
    if /usr/local/bin/kubectl get nodes 2>/dev/null | grep -q "Ready"; then
        echo "k3s node is Ready"
        break
    fi
    echo "  Waiting for node... (attempt $i/60)"
    sleep 5
done

# Wait for API server to be fully responsive (all system pods ready)
echo "Waiting for k3s API to be fully ready..."
for i in {1..30}; do
    if /usr/local/bin/kubectl get pods -n kube-system 2>/dev/null | grep -v "NAME" | grep -v "Running\|Completed" | wc -l | grep -q "^0$"; then
        echo "k3s API is fully ready"
        break
    fi
    echo "  Waiting for system pods... (attempt $i/30)"
    sleep 10
done

# Final API health check
echo "Verifying API health..."
/usr/local/bin/kubectl cluster-info || echo "Warning: cluster-info check failed"

# Create a script to get the node token (for GPU workers to join)
cat > /usr/local/bin/get-k3s-token << 'TOKENSCRIPT'
#!/bin/bash
cat /var/lib/rancher/k3s/server/node-token
TOKENSCRIPT
chmod +x /usr/local/bin/get-k3s-token

#############################################
# PHASE 3: Install Helm
#############################################
echo "=== Phase 3: Installing Helm ==="

curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

#############################################
# PHASE 4: Install Liqo
#############################################
echo "=== Phase 4: Installing Liqo ==="

# Add Liqo Helm repo
helm repo add liqo https://helm.liqo.io/
helm repo update

# Install Liqo as provider cluster with retry logic
# This will peer with homelab (Talos) to share GPU resources
echo "Installing Liqo (with retry)..."
for attempt in 1 2 3; do
    echo "  Attempt $attempt/3..."
    if helm install liqo liqo/liqo \
        --namespace liqo-system \
        --create-namespace \
        --set discovery.config.clusterName=aws-gpu-cluster \
        --set networking.internal=true \
        --set ipam.podCIDR="10.43.0.0/16" \
        --set ipam.serviceCIDR="10.44.0.0/16" \
        --set auth.config.enableAuthentication=false \
        --set controllerManager.config.resourceSharingPercentage=90 \
        --timeout=5m 2>&1; then
        echo "Liqo installed successfully"
        break
    else
        echo "  Liqo install attempt $attempt failed"
        if [ $attempt -lt 3 ]; then
            echo "  Waiting 30s before retry..."
            sleep 30
            helm uninstall liqo -n liqo-system 2>/dev/null || true
        fi
    fi
done

# Wait for Liqo pods to be ready
echo "Waiting for Liqo pods to be ready..."
/usr/local/bin/kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=liqo -n liqo-system --timeout=300s || true

# Install liqoctl for easier management
LIQO_VERSION="v1.0.1"
curl -Lo /usr/local/bin/liqoctl "https://github.com/liqotech/liqo/releases/download/${LIQO_VERSION}/liqoctl-linux-amd64"
chmod +x /usr/local/bin/liqoctl

# Generate peering info for homelab
echo "=== Generating Liqo Peering Information ==="
mkdir -p /root/liqo-peering
/usr/local/bin/liqoctl generate peer-command --only-command > /root/liqo-peering/peer-command.txt 2>/dev/null || echo "Peering command will be available after Liqo is fully initialized"

#############################################
# PHASE 5: Label node for GPU workers
#############################################
echo "=== Phase 5: Configuring node labels ==="

# Label this node as control-plane only (no GPU workloads here)
/usr/local/bin/kubectl label node \$(hostname) node-type=control-plane --overwrite
/usr/local/bin/kubectl taint node \$(hostname) node-role.kubernetes.io/control-plane=:NoSchedule --overwrite || true

#############################################
# Summary
#############################################
echo ""
echo "=== Lighthouse Bootstrap Complete ==="
echo ""
echo "Nebula:"
echo "  Public IP: \${PUBLIC_IP}"
echo "  Mesh IP:   10.42.0.1"
echo ""
echo "k3s:"
echo "  API Server: https://10.42.0.1:6443"
echo "  Kubeconfig: /etc/rancher/k3s/k3s.yaml"
echo "  Node Token: /var/lib/rancher/k3s/server/node-token"
echo ""
echo "Liqo:"
echo "  Cluster:   aws-gpu-cluster"
echo "  Namespace: liqo-system"
echo "  Peering:   /root/liqo-peering/peer-command.txt"
echo ""
echo "To join GPU workers:"
echo "  K3S_TOKEN=\$(cat /var/lib/rancher/k3s/server/node-token)"
echo "  curl -sfL https://get.k3s.io | K3S_URL=https://10.42.0.1:6443 K3S_TOKEN=\\\$K3S_TOKEN sh -s - agent"
echo ""
FOOTER
