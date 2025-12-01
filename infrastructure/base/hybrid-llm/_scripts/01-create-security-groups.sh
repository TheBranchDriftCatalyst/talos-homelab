#!/bin/bash
# Create AWS Security Groups for Hybrid LLM Cluster
# Run this first before any EC2 instances

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== Creating Security Groups ===${NC}"

# Configuration
VPC_ID="${VPC_ID:-vpc-3536d651}"
REGION="${AWS_REGION:-us-west-2}"

# Check if security group already exists
EXISTING_SG=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=nebula-lighthouse" "Name=vpc-id,Values=${VPC_ID}" \
  --query 'SecurityGroups[0].GroupId' \
  --output text 2>/dev/null || echo "None")

if [[ "$EXISTING_SG" != "None" && "$EXISTING_SG" != "" ]]; then
  echo -e "${GREEN}Security group 'nebula-lighthouse' already exists: ${EXISTING_SG}${NC}"
  LIGHTHOUSE_SG_ID="$EXISTING_SG"
else
  echo "Creating security group: nebula-lighthouse"
  LIGHTHOUSE_SG_ID=$(aws ec2 create-security-group \
    --group-name nebula-lighthouse \
    --description "Nebula lighthouse - UDP 4242 for mesh VPN" \
    --vpc-id "$VPC_ID" \
    --query 'GroupId' \
    --output text)
  echo -e "${GREEN}Created: ${LIGHTHOUSE_SG_ID}${NC}"

  # Add rules
  echo "Adding ingress rules..."

  # Nebula UDP 4242
  aws ec2 authorize-security-group-ingress \
    --group-id "$LIGHTHOUSE_SG_ID" \
    --protocol udp \
    --port 4242 \
    --cidr 0.0.0.0/0 \
    --output text > /dev/null
  echo "  - UDP 4242 (Nebula)"

  # SSH for management
  aws ec2 authorize-security-group-ingress \
    --group-id "$LIGHTHOUSE_SG_ID" \
    --protocol tcp \
    --port 22 \
    --cidr 0.0.0.0/0 \
    --output text > /dev/null
  echo "  - TCP 22 (SSH)"
fi

# Create GPU worker security group
EXISTING_GPU_SG=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=hybrid-llm-gpu" "Name=vpc-id,Values=${VPC_ID}" \
  --query 'SecurityGroups[0].GroupId' \
  --output text 2>/dev/null || echo "None")

if [[ "$EXISTING_GPU_SG" != "None" && "$EXISTING_GPU_SG" != "" ]]; then
  echo -e "${GREEN}Security group 'hybrid-llm-gpu' already exists: ${EXISTING_GPU_SG}${NC}"
  GPU_SG_ID="$EXISTING_GPU_SG"
else
  echo "Creating security group: hybrid-llm-gpu"
  GPU_SG_ID=$(aws ec2 create-security-group \
    --group-name hybrid-llm-gpu \
    --description "GPU worker for hybrid LLM cluster" \
    --vpc-id "$VPC_ID" \
    --query 'GroupId' \
    --output text)
  echo -e "${GREEN}Created: ${GPU_SG_ID}${NC}"

  # Add rules
  echo "Adding ingress rules..."

  # Nebula UDP 4242
  aws ec2 authorize-security-group-ingress \
    --group-id "$GPU_SG_ID" \
    --protocol udp \
    --port 4242 \
    --cidr 0.0.0.0/0 \
    --output text > /dev/null
  echo "  - UDP 4242 (Nebula)"

  # SSH for management
  aws ec2 authorize-security-group-ingress \
    --group-id "$GPU_SG_ID" \
    --protocol tcp \
    --port 22 \
    --cidr 0.0.0.0/0 \
    --output text > /dev/null
  echo "  - TCP 22 (SSH)"

  # Kubernetes API (from Nebula network only - will be via Nebula)
  # No public K8s API exposure needed
fi

echo ""
echo -e "${GREEN}=== Security Groups Ready ===${NC}"
echo "Lighthouse SG: ${LIGHTHOUSE_SG_ID}"
echo "GPU Worker SG: ${GPU_SG_ID}"
echo ""
echo "Export these for other scripts:"
echo "  export LIGHTHOUSE_SG_ID=${LIGHTHOUSE_SG_ID}"
echo "  export GPU_SG_ID=${GPU_SG_ID}"
