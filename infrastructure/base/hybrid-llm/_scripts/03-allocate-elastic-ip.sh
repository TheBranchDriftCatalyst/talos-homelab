#!/bin/bash
# Allocate and associate Elastic IP to Lighthouse
# This gives the lighthouse a permanent IP that survives reboots

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== Allocating Elastic IP for Lighthouse ===${NC}"

# Find the lighthouse instance
INSTANCE_ID=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=nebula-lighthouse" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' \
  --output text)

if [[ -z "$INSTANCE_ID" || "$INSTANCE_ID" == "None" ]]; then
  echo -e "${RED}Error: Lighthouse instance not found or not running${NC}"
  exit 1
fi

echo "Lighthouse Instance: ${INSTANCE_ID}"

# Check if already has an EIP
EXISTING_EIP=$(aws ec2 describe-addresses \
  --filters "Name=instance-id,Values=${INSTANCE_ID}" \
  --query 'Addresses[0].PublicIp' \
  --output text 2>/dev/null || echo "None")

if [[ "$EXISTING_EIP" != "None" && -n "$EXISTING_EIP" ]]; then
  echo -e "${GREEN}Elastic IP already associated: ${EXISTING_EIP}${NC}"
  exit 0
fi

# Check for existing unassociated EIP with our tag
EXISTING_ALLOC=$(aws ec2 describe-addresses \
  --filters "Name=tag:Name,Values=nebula-lighthouse-eip" \
  --query 'Addresses[0].AllocationId' \
  --output text 2>/dev/null || echo "None")

if [[ "$EXISTING_ALLOC" != "None" && -n "$EXISTING_ALLOC" ]]; then
  echo "Found existing EIP allocation: ${EXISTING_ALLOC}"
  ALLOCATION_ID="$EXISTING_ALLOC"
else
  # Allocate new EIP
  echo "Allocating new Elastic IP..."
  ALLOCATION_ID=$(aws ec2 allocate-address \
    --domain vpc \
    --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=nebula-lighthouse-eip},{Key=Project,Value=hybrid-llm}]" \
    --query 'AllocationId' \
    --output text)
  echo "Allocated: ${ALLOCATION_ID}"
fi

# Associate with instance
echo "Associating with lighthouse instance..."
aws ec2 associate-address \
  --instance-id "$INSTANCE_ID" \
  --allocation-id "$ALLOCATION_ID" \
  --output text > /dev/null

# Get the public IP
PUBLIC_IP=$(aws ec2 describe-addresses \
  --allocation-ids "$ALLOCATION_ID" \
  --query 'Addresses[0].PublicIp' \
  --output text)

echo ""
echo -e "${GREEN}=== Elastic IP Configured ===${NC}"
echo "Allocation ID: ${ALLOCATION_ID}"
echo "Public IP: ${PUBLIC_IP}"
echo ""
echo -e "${YELLOW}Update your Nebula configs with this permanent IP:${NC}"
echo "  LIGHTHOUSE_PUBLIC_IP=${PUBLIC_IP}"
echo ""
echo "This IP will persist across instance reboots."
