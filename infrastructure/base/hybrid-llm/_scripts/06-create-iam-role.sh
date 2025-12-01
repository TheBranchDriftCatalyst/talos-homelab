#!/bin/bash
# Create IAM Role for GPU Worker EC2 instances
# Allows access to Secrets Manager and S3

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== Creating IAM Role for GPU Workers ===${NC}"

ROLE_NAME="hybrid-llm-gpu-worker"
INSTANCE_PROFILE_NAME="hybrid-llm-gpu-worker"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION="${AWS_REGION:-us-west-2}"

# Check if role exists
if aws iam get-role --role-name "$ROLE_NAME" 2>/dev/null; then
  echo -e "${GREEN}Role already exists: ${ROLE_NAME}${NC}"
else
  echo "Creating IAM role..."

  # Trust policy for EC2
  TRUST_POLICY='{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Principal": {
          "Service": "ec2.amazonaws.com"
        },
        "Action": "sts:AssumeRole"
      }
    ]
  }'

  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$TRUST_POLICY" \
    --description "IAM role for hybrid-llm GPU worker instances" \
    --tags Key=Project,Value=hybrid-llm \
    --output text > /dev/null

  echo -e "${GREEN}Created role: ${ROLE_NAME}${NC}"
fi

# Create/update policy
POLICY_NAME="hybrid-llm-gpu-worker-policy"
POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/${POLICY_NAME}"

POLICY_DOC=$(cat << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "arn:aws:secretsmanager:${REGION}:${ACCOUNT_ID}:secret:nebula/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::ollama-models-${ACCOUNT_ID}",
        "arn:aws:s3:::ollama-models-${ACCOUNT_ID}/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances",
        "ec2:DescribeTags"
      ],
      "Resource": "*"
    }
  ]
}
EOF
)

# Check if policy exists
if aws iam get-policy --policy-arn "$POLICY_ARN" 2>/dev/null; then
  echo "Updating policy..."
  # Create new version
  aws iam create-policy-version \
    --policy-arn "$POLICY_ARN" \
    --policy-document "$POLICY_DOC" \
    --set-as-default \
    --output text > /dev/null
else
  echo "Creating policy..."
  aws iam create-policy \
    --policy-name "$POLICY_NAME" \
    --policy-document "$POLICY_DOC" \
    --description "Policy for hybrid-llm GPU workers" \
    --tags Key=Project,Value=hybrid-llm \
    --output text > /dev/null
fi

# Attach policy to role
echo "Attaching policy to role..."
aws iam attach-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-arn "$POLICY_ARN" 2>/dev/null || true

# Create instance profile
if aws iam get-instance-profile --instance-profile-name "$INSTANCE_PROFILE_NAME" 2>/dev/null; then
  echo -e "${GREEN}Instance profile already exists: ${INSTANCE_PROFILE_NAME}${NC}"
else
  echo "Creating instance profile..."
  aws iam create-instance-profile \
    --instance-profile-name "$INSTANCE_PROFILE_NAME" \
    --tags Key=Project,Value=hybrid-llm \
    --output text > /dev/null

  # Add role to instance profile
  aws iam add-role-to-instance-profile \
    --instance-profile-name "$INSTANCE_PROFILE_NAME" \
    --role-name "$ROLE_NAME"

  echo -e "${GREEN}Created instance profile: ${INSTANCE_PROFILE_NAME}${NC}"
fi

echo ""
echo -e "${GREEN}=== IAM Role Ready ===${NC}"
echo "Role: ${ROLE_NAME}"
echo "Instance Profile: ${INSTANCE_PROFILE_NAME}"
echo ""
echo "GPU workers will use this profile to:"
echo "  - Fetch Nebula certs from Secrets Manager"
echo "  - Read models from S3"
