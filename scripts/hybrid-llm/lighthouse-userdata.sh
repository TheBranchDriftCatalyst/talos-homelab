#!/bin/bash
# Nebula Lighthouse Bootstrap Script
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
-----BEGIN NEBULA CERTIFICATE-----
CkQKEnRhbG9zLWhvbWVsYWItbWVzaCifhKrJBjCf667YBjogsux//EUZXETfe/EW
Vu26zW2E+Q4LKDZqKxLAjcc/t6tAARJALlAtaZZDQmtuctVoAT62Y7jCt+qllwUB
jwge5XSICiKrj6pYkXe2jpi+ejs5DeBpHPiOMyvd96mTGkVgbt+oAQ==
-----END NEBULA CERTIFICATE-----
CACERT

# Write host certificate
cat > /etc/nebula/host.crt << 'HOSTCERT'
-----BEGIN NEBULA CERTIFICATE-----
CoMBCgpsaWdodGhvdXNlEgmBgKhRgID8/w8iCmxpZ2h0aG91c2UiDmluZnJhc3Ry
dWN0dXJlKNGFqskGMJ7rrtgGOiBm58sDCRUYMqaevRXyh+tcPOV2aC6hj/i8S3lz
9Rd1XEogLQHSiDonzGWMHwyY1tCsc8mrv/ztEZNGDXsXIr70gAYSQAvJ12Ur2Dwb
rN5ar11xK+ENsIdiOCLIJfVaSbRuigHcb9auqOZeYpw24Lf9ehCo13RWCrlg0+UF
L0EqhyINrAM=
-----END NEBULA CERTIFICATE-----
HOSTCERT

# Write host key
cat > /etc/nebula/host.key << 'HOSTKEY'
-----BEGIN NEBULA X25519 PRIVATE KEY-----
zStAbsNBCYCOMksrMjh+2sRoHrC63HDf8MypsD+34FE=
-----END NEBULA X25519 PRIVATE KEY-----
HOSTKEY

chmod 600 /etc/nebula/host.key

# Get public IP for config
PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)

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
cat > /etc/systemd/system/nebula.service << 'EOF'
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
EOF

# Enable and start Nebula
systemctl daemon-reload
systemctl enable nebula
systemctl start nebula

echo "=== Nebula Lighthouse Bootstrap Complete ==="
echo "Public IP: ${PUBLIC_IP}"
echo "Nebula IP: 10.42.0.1"
