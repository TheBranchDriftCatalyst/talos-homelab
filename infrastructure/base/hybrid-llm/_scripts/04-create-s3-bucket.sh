#!/bin/bash
# Create S3 bucket for Ollama models with Intelligent-Tiering

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== Creating S3 Bucket for Ollama Models ===${NC}"

# Configuration
REGION="${AWS_REGION:-us-west-2}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
BUCKET_NAME="ollama-models-${ACCOUNT_ID}"

echo "Account ID: ${ACCOUNT_ID}"
echo "Bucket Name: ${BUCKET_NAME}"
echo "Region: ${REGION}"
echo ""

# Check if bucket exists
if aws s3api head-bucket --bucket "$BUCKET_NAME" 2>/dev/null; then
  echo -e "${GREEN}Bucket already exists: ${BUCKET_NAME}${NC}"
else
  echo "Creating bucket..."

  # Create bucket (us-east-1 doesn't need LocationConstraint)
  if [[ "$REGION" == "us-east-1" ]]; then
    aws s3api create-bucket \
      --bucket "$BUCKET_NAME" \
      --region "$REGION"
  else
    aws s3api create-bucket \
      --bucket "$BUCKET_NAME" \
      --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION"
  fi

  echo -e "${GREEN}Created bucket: ${BUCKET_NAME}${NC}"
fi

# Enable versioning (for safety)
echo "Enabling versioning..."
aws s3api put-bucket-versioning \
  --bucket "$BUCKET_NAME" \
  --versioning-configuration Status=Enabled

# Configure Intelligent-Tiering
echo "Configuring Intelligent-Tiering..."
aws s3api put-bucket-intelligent-tiering-configuration \
  --bucket "$BUCKET_NAME" \
  --id "entire-bucket" \
  --intelligent-tiering-configuration '{
    "Id": "entire-bucket",
    "Status": "Enabled",
    "Tierings": [
      {"Days": 90, "AccessTier": "ARCHIVE_ACCESS"},
      {"Days": 180, "AccessTier": "DEEP_ARCHIVE_ACCESS"}
    ]
  }'

# Add tags
echo "Adding tags..."
aws s3api put-bucket-tagging \
  --bucket "$BUCKET_NAME" \
  --tagging 'TagSet=[{Key=Project,Value=hybrid-llm},{Key=Purpose,Value=ollama-models}]'

# Block public access
echo "Blocking public access..."
aws s3api put-public-access-block \
  --bucket "$BUCKET_NAME" \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

echo ""
echo -e "${GREEN}=== S3 Bucket Ready ===${NC}"
echo "Bucket: s3://${BUCKET_NAME}"
echo ""
echo "Features enabled:"
echo "  - Intelligent-Tiering (auto archive after 90 days)"
echo "  - Versioning"
echo "  - Public access blocked"
echo ""
echo "To upload models:"
echo "  aws s3 sync ~/.ollama/models s3://${BUCKET_NAME}/ --storage-class INTELLIGENT_TIERING"
