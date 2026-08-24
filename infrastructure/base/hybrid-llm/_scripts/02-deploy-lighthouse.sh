#!/bin/bash
# Deploy Nebula Lighthouse EC2 Instance
# Requires: 01-create-security-groups.sh to have run first

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== Deploying Nebula Lighthouse ===${NC}"

# Configuration
REGION="${AWS_REGION:-us-west-2}"
VPC_ID="${VPC_ID:-vpc-3536d651}"
KEY_NAME="${KEY_NAME:-amp-mac-key}"
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.micro}"
NEBULA_CA_DIR="${NEBULA_CA_DIR:-$HOME/.nebula-ca}"

# Check for existing lighthouse
EXISTING_INSTANCE=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=nebula-lighthouse" "Name=instance-state-name,Values=running,pending,stopped" \
  --query 'Reservations[0].Instances[0].InstanceId' \
  --output text 2>/dev/null || echo "None")

if [[ "$EXISTING_INSTANCE" != "None" && "$EXISTING_INSTANCE" != "" ]]; then
  echo -e "${YELLOW}Lighthouse instance already exists: ${EXISTING_INSTANCE}${NC}"

  # Get its public IP
  PUBLIC_IP=$(aws ec2 describe-instances \
    --instance-ids "$EXISTING_INSTANCE" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text)

  echo "Public IP: ${PUBLIC_IP}"
  echo ""
  echo "To SSH: ssh -i ~/.ssh/amp-mac-key.pem ec2-user@${PUBLIC_IP}"
  exit 0
fi

# Get security group
LIGHTHOUSE_SG_ID=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=nebula-lighthouse" "Name=vpc-id,Values=${VPC_ID}" \
  --query 'SecurityGroups[0].GroupId' \
  --output text)

if [[ -z "$LIGHTHOUSE_SG_ID" || "$LIGHTHOUSE_SG_ID" == "None" ]]; then
  echo -e "${RED}Error: Security group 'nebula-lighthouse' not found. Run 01-create-security-groups.sh first${NC}"
  exit 1
fi

# Get subnet
SUBNET_ID=$(aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=${VPC_ID}" \
  --query 'Subnets[0].SubnetId' \
  --output text)

# Get latest Amazon Linux 2023 AMI
AMI_ID=$(aws ec2 describe-images \
  --owners amazon \
  --filters "Name=name,Values=al2023-ami-2023*-x86_64" "Name=state,Values=available" \
  --query 'sort_by(Images, &CreationDate)[-1].ImageId' \
  --output text)

echo "Configuration:"
echo "  Region: ${REGION}"
echo "  VPC: ${VPC_ID}"
echo "  Subnet: ${SUBNET_ID}"
echo "  Security Group: ${LIGHTHOUSE_SG_ID}"
echo "  AMI: ${AMI_ID}"
echo "  Instance Type: ${INSTANCE_TYPE}"
echo "  Key Name: ${KEY_NAME}"
echo ""

# Check for Nebula certs
if [[ ! -f "${NEBULA_CA_DIR}/ca.crt" ]]; then
  echo -e "${RED}Error: Nebula CA cert not found at ${NEBULA_CA_DIR}/ca.crt${NC}"
  exit 1
fi

if [[ ! -f "${NEBULA_CA_DIR}/lighthouse.crt" ]]; then
  echo -e "${RED}Error: Lighthouse cert not found at ${NEBULA_CA_DIR}/lighthouse.crt${NC}"
  exit 1
fi

# Read certificates
CA_CRT=$(cat "${NEBULA_CA_DIR}/ca.crt")
HOST_CRT=$(cat "${NEBULA_CA_DIR}/lighthouse.crt")
HOST_KEY=$(cat "${NEBULA_CA_DIR}/lighthouse.key")

# Create user-data script
USER_DATA=$(cat << 'USERDATA_END'
#!/bin/bash
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

mkdir -p /etc/nebula

cat > /etc/nebula/ca.crt << 'CACERT'
__CA_CRT__
CACERT

cat > /etc/nebula/host.crt << 'HOSTCERT'
__HOST_CRT__
HOSTCERT

cat > /etc/nebula/host.key << 'HOSTKEY'
__HOST_KEY__
HOSTKEY

chmod 600 /etc/nebula/host.key

PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)

cat > /etc/nebula/config.yaml << EOF
pki:
  ca: /etc/nebula/ca.crt
  cert: /etc/nebula/host.crt
  key: /etc/nebula/host.key

static_host_map:
  "10.42.0.1": ["\${PUBLIC_IP}:4242"]

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
EOF

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

systemctl daemon-reload
systemctl enable nebula
systemctl start nebula

echo "=== Nebula Lighthouse Bootstrap Complete ==="
echo "Public IP: ${PUBLIC_IP}"
echo "Nebula IP: 10.42.0.1"
USERDATA_END
)

# Replace placeholders with actual certs
USER_DATA="${USER_DATA//__CA_CRT__/$CA_CRT}"
USER_DATA="${USER_DATA//__HOST_CRT__/$HOST_CRT}"
USER_DATA="${USER_DATA//__HOST_KEY__/$HOST_KEY}"

# Write to temp file
USERDATA_FILE=$(mktemp)
echo "$USER_DATA" > "$USERDATA_FILE"

echo "Launching EC2 instance..."

INSTANCE_ID=$(aws ec2 run-instances \
  --image-id "$AMI_ID" \
  --instance-type "$INSTANCE_TYPE" \
  --key-name "$KEY_NAME" \
  --security-group-ids "$LIGHTHOUSE_SG_ID" \
  --subnet-id "$SUBNET_ID" \
  --associate-public-ip-address \
  --user-data "file://${USERDATA_FILE}" \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=nebula-lighthouse},{Key=Project,Value=hybrid-llm}]" \
  --query 'Instances[0].InstanceId' \
  --output text)

rm "$USERDATA_FILE"

echo -e "${GREEN}Instance launched: ${INSTANCE_ID}${NC}"
echo ""
echo "Waiting for instance to be running..."

aws ec2 wait instance-running --instance-ids "$INSTANCE_ID"

# Get public IP
PUBLIC_IP=$(aws ec2 describe-instances \
  --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' \
  --output text)

echo ""
echo -e "${GREEN}=== Lighthouse Deployed ===${NC}"
echo "Instance ID: ${INSTANCE_ID}"
echo "Public IP: ${PUBLIC_IP}"
echo "Nebula IP: 10.42.0.1"
echo ""
echo "Wait 2-3 minutes for bootstrap to complete, then:"
echo "  ssh -i ~/.ssh/amp-mac-key.pem ec2-user@${PUBLIC_IP}"
echo "  sudo systemctl status nebula"
echo "  sudo journalctl -u nebula -f"
echo ""
echo -e "${YELLOW}IMPORTANT: Save this IP for Nebula config:${NC}"
echo "  LIGHTHOUSE_PUBLIC_IP=${PUBLIC_IP}"
