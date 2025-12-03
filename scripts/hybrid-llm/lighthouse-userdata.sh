#!/bin/bash
# Nebula Lighthouse Userdata Generator
# Reads certificates from .output/nebula/ and outputs a complete EC2 userdata script
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
# Nebula Lighthouse Bootstrap Script
# Auto-generated - certificates embedded from .output/nebula/
# This runs on first boot of the EC2 instance

set -euo pipefail
exec > >(tee /var/log/nebula-bootstrap.log) 2>&1

echo "=== Starting Nebula Lighthouse Bootstrap ==="

# Install dependencies
dnf install -y tar gzip

# Download and install Nebula
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
EOF

# Create systemd service
cat > /etc/systemd/system/nebula.service << 'SVCEOF'
[Unit]
Description=Nebula Mesh VPN
Wants=basic.target network-online.target
After=basic.target network-online.target
Before=sshd.service

[Service]
Type=simple
ExecStart=/usr/local/bin/nebula -config /etc/nebula/config.yaml
ExecReload=/bin/kill -HUP $MAINPID
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVCEOF

# Enable and start Nebula
systemctl daemon-reload
systemctl enable nebula
systemctl start nebula

echo "=== Nebula Lighthouse Bootstrap Complete ==="
echo "Public IP: ${PUBLIC_IP}"
echo "Nebula IP: 10.42.0.1"
FOOTER
