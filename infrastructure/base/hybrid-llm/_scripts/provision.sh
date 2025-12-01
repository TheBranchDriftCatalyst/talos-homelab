#!/bin/bash
# Main Provisioning Script for Hybrid LLM Cluster
# This orchestrates all the individual provisioning scripts
#
# Usage:
#   ./provision.sh              # Run all steps
#   ./provision.sh --step 2     # Run specific step
#   ./provision.sh --from 3     # Run from step 3 onwards
#   ./provision.sh --dry-run    # Show what would be done

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
export AWS_REGION="${AWS_REGION:-us-west-2}"
export VPC_ID="${VPC_ID:-vpc-3536d651}"
export KEY_NAME="${KEY_NAME:-amp-mac-key}"
export NEBULA_CA_DIR="${NEBULA_CA_DIR:-$HOME/.nebula-ca}"

# Parse arguments
DRY_RUN=false
SPECIFIC_STEP=""
START_FROM=1

while [[ $# -gt 0 ]]; do
  case $1 in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --step)
      SPECIFIC_STEP="$2"
      shift 2
      ;;
    --from)
      START_FROM="$2"
      shift 2
      ;;
    --help)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --dry-run     Show what would be done without executing"
      echo "  --step N      Run only step N"
      echo "  --from N      Start from step N"
      echo "  --help        Show this help"
      echo ""
      echo "Steps:"
      echo "  1. Create Security Groups"
      echo "  2. Deploy Nebula Lighthouse"
      echo "  3. Allocate Elastic IP"
      echo "  4. Create S3 Bucket"
      echo "  5. Store Secrets in AWS Secrets Manager"
      echo "  6. Create IAM Role for GPU Workers"
      exit 0
      ;;
    *)
      echo -e "${RED}Unknown option: $1${NC}"
      exit 1
      ;;
  esac
done

# Step definitions
declare -a STEPS=(
  "01-create-security-groups.sh:Create Security Groups"
  "02-deploy-lighthouse.sh:Deploy Nebula Lighthouse"
  "03-allocate-elastic-ip.sh:Allocate Elastic IP"
  "04-create-s3-bucket.sh:Create S3 Bucket for Models"
  "05-store-secrets.sh:Store Secrets in AWS Secrets Manager"
  "06-create-iam-role.sh:Create IAM Role for GPU Workers"
)

# Header
echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║           Hybrid LLM Cluster - AWS Provisioning               ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

echo "Configuration:"
echo "  AWS Region: ${AWS_REGION}"
echo "  VPC ID: ${VPC_ID}"
echo "  SSH Key: ${KEY_NAME}"
echo "  Nebula CA Dir: ${NEBULA_CA_DIR}"
echo ""

# Pre-flight checks
echo -e "${YELLOW}=== Pre-flight Checks ===${NC}"

# Check AWS CLI
if ! command -v aws &> /dev/null; then
  echo -e "${RED}Error: AWS CLI not installed${NC}"
  exit 1
fi
echo -e "${GREEN}✓${NC} AWS CLI installed"

# Check AWS credentials
if ! aws sts get-caller-identity &> /dev/null; then
  echo -e "${RED}Error: AWS credentials not configured or account blocked${NC}"
  echo "  Run: aws configure"
  echo "  Or check if account needs verification"
  exit 1
fi
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo -e "${GREEN}✓${NC} AWS credentials valid (Account: ${ACCOUNT_ID})"

# Check Nebula CA exists
if [[ ! -f "${NEBULA_CA_DIR}/ca.crt" ]]; then
  echo -e "${RED}Error: Nebula CA not found at ${NEBULA_CA_DIR}/ca.crt${NC}"
  echo "  Run: nebula-cert ca -name 'talos-homelab-mesh'"
  exit 1
fi
echo -e "${GREEN}✓${NC} Nebula CA found"

# Check lighthouse cert exists
if [[ ! -f "${NEBULA_CA_DIR}/lighthouse.crt" ]]; then
  echo -e "${RED}Error: Lighthouse cert not found${NC}"
  echo "  Run: nebula-cert sign -name lighthouse -ip 10.42.0.1/16 -groups lighthouse,infrastructure"
  exit 1
fi
echo -e "${GREEN}✓${NC} Lighthouse certificate found"

echo ""

# Run steps
run_step() {
  local step_num=$1
  local script_file=$(echo "${STEPS[$step_num-1]}" | cut -d: -f1)
  local step_name=$(echo "${STEPS[$step_num-1]}" | cut -d: -f2)

  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${YELLOW}Step ${step_num}: ${step_name}${NC}"
  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

  if [[ "$DRY_RUN" == "true" ]]; then
    echo -e "${YELLOW}[DRY RUN] Would execute: ${script_file}${NC}"
    return 0
  fi

  if [[ -f "${SCRIPT_DIR}/${script_file}" ]]; then
    chmod +x "${SCRIPT_DIR}/${script_file}"
    if "${SCRIPT_DIR}/${script_file}"; then
      echo -e "${GREEN}✓ Step ${step_num} completed${NC}"
      return 0
    else
      echo -e "${RED}✗ Step ${step_num} failed${NC}"
      return 1
    fi
  else
    echo -e "${RED}Script not found: ${script_file}${NC}"
    return 1
  fi
}

# Execute steps
TOTAL_STEPS=${#STEPS[@]}

if [[ -n "$SPECIFIC_STEP" ]]; then
  # Run specific step only
  if [[ "$SPECIFIC_STEP" -lt 1 || "$SPECIFIC_STEP" -gt "$TOTAL_STEPS" ]]; then
    echo -e "${RED}Invalid step: ${SPECIFIC_STEP} (valid: 1-${TOTAL_STEPS})${NC}"
    exit 1
  fi
  run_step "$SPECIFIC_STEP"
else
  # Run from START_FROM to end
  for ((i=START_FROM; i<=TOTAL_STEPS; i++)); do
    if ! run_step "$i"; then
      echo ""
      echo -e "${RED}Provisioning failed at step ${i}${NC}"
      echo "Fix the issue and resume with: $0 --from ${i}"
      exit 1
    fi
    echo ""
  done
fi

# Summary
echo -e "${GREEN}"
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║                  Provisioning Complete!                       ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

if [[ "$DRY_RUN" == "false" && -z "$SPECIFIC_STEP" ]]; then
  # Get lighthouse IP
  LIGHTHOUSE_IP=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=nebula-lighthouse" "Name=instance-state-name,Values=running" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text 2>/dev/null || echo "unknown")

  echo "Next Steps:"
  echo ""
  echo "1. Wait 2-3 minutes for lighthouse to bootstrap"
  echo ""
  echo "2. Verify lighthouse is running:"
  echo "   ssh -i ~/.ssh/amp-mac-key.pem ec2-user@${LIGHTHOUSE_IP}"
  echo "   sudo systemctl status nebula"
  echo ""
  echo "3. Configure Talos homelab node with Nebula"
  echo "   (see docs/hybrid-llm-cluster/NEXT-STEPS.md)"
  echo ""
  echo "4. Wait for GPU quota approval, then deploy GPU worker"
  echo ""
  echo -e "${YELLOW}Lighthouse Public IP: ${LIGHTHOUSE_IP}${NC}"
  echo "Save this IP - you'll need it for Nebula configs!"
fi
