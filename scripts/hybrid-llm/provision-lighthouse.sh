#!/bin/bash
# Unified Nebula Lighthouse Provisioning Script
# Provisions complete AWS infrastructure for the Nebula mesh lighthouse
#
# Usage:
#   ./scripts/hybrid-llm/provision-lighthouse.sh
#   ./scripts/hybrid-llm/provision-lighthouse.sh --dry-run
#   ./scripts/hybrid-llm/provision-lighthouse.sh --skip-certs   # Skip cert generation if already done
#   ./scripts/hybrid-llm/provision-lighthouse.sh --teardown     # Destroy all resources
#
# Prerequisites:
#   - AWS CLI configured (aws configure)
#   - nebula-cert installed (brew install nebula)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Configuration
AWS_REGION="${AWS_REGION:-us-west-2}"
INSTANCE_TYPE="${LIGHTHOUSE_INSTANCE_TYPE:-t3.micro}"
KEY_NAME="hybrid-llm-key"
SG_NAME="nebula-lighthouse"

# Output directories
OUTPUT_DIR="$REPO_ROOT/.output"
NEBULA_DIR="$OUTPUT_DIR/nebula"
SSH_DIR="$OUTPUT_DIR/ssh"
CA_DIR="$HOME/.nebula-ca"

# State file for tracking resources
STATE_FILE="$OUTPUT_DIR/lighthouse-state.json"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Parse arguments
DRY_RUN=false
SKIP_CERTS=false
TEARDOWN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --skip-certs)
            SKIP_CERTS=true
            shift
            ;;
        --teardown)
            TEARDOWN=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Save state
save_state() {
    local key="$1"
    local value="$2"

    mkdir -p "$(dirname "$STATE_FILE")"

    if [[ -f "$STATE_FILE" ]]; then
        # Update existing key or add new one
        jq --arg key "$key" --arg value "$value" '.[$key] = $value' "$STATE_FILE" > "${STATE_FILE}.tmp"
        mv "${STATE_FILE}.tmp" "$STATE_FILE"
    else
        echo "{\"$key\": \"$value\"}" > "$STATE_FILE"
    fi
}

# Get state
get_state() {
    local key="$1"
    if [[ -f "$STATE_FILE" ]]; then
        jq -r --arg key "$key" '.[$key] // empty' "$STATE_FILE"
    fi
}

# ============================================
# TEARDOWN
# ============================================
teardown() {
    log_info "Starting teardown..."

    local instance_id=$(get_state "instance_id")
    local alloc_id=$(get_state "allocation_id")
    local sg_id=$(get_state "security_group_id")
    local key_exists=$(aws ec2 describe-key-pairs --key-names "$KEY_NAME" --region "$AWS_REGION" 2>/dev/null || true)

    # Terminate instance
    if [[ -n "$instance_id" ]]; then
        log_info "Terminating instance: $instance_id"
        if [[ "$DRY_RUN" == "false" ]]; then
            aws ec2 terminate-instances --instance-ids "$instance_id" --region "$AWS_REGION" || true
            aws ec2 wait instance-terminated --instance-ids "$instance_id" --region "$AWS_REGION" || true
        fi
    fi

    # Release Elastic IP
    if [[ -n "$alloc_id" ]]; then
        log_info "Releasing Elastic IP: $alloc_id"
        if [[ "$DRY_RUN" == "false" ]]; then
            aws ec2 release-address --allocation-id "$alloc_id" --region "$AWS_REGION" || true
        fi
    fi

    # Delete security group
    if [[ -n "$sg_id" ]]; then
        log_info "Deleting security group: $sg_id"
        if [[ "$DRY_RUN" == "false" ]]; then
            sleep 5  # Wait for instance to fully terminate
            aws ec2 delete-security-group --group-id "$sg_id" --region "$AWS_REGION" || true
        fi
    fi

    # Delete key pair
    if [[ -n "$key_exists" ]]; then
        log_info "Deleting key pair: $KEY_NAME"
        if [[ "$DRY_RUN" == "false" ]]; then
            aws ec2 delete-key-pair --key-name "$KEY_NAME" --region "$AWS_REGION" || true
        fi
    fi

    # Remove state file
    if [[ "$DRY_RUN" == "false" ]]; then
        rm -f "$STATE_FILE"
        rm -f "$SSH_DIR/$KEY_NAME.pem"
    fi

    log_info "Teardown complete!"
}

if [[ "$TEARDOWN" == "true" ]]; then
    teardown
    exit 0
fi

# ============================================
# PROVISIONING
# ============================================

log_info "=== Nebula Lighthouse Provisioning ==="
log_info "Region: $AWS_REGION"
log_info "Instance Type: $INSTANCE_TYPE"
[[ "$DRY_RUN" == "true" ]] && log_warn "DRY RUN MODE - No changes will be made"

# Step 1: Generate certificates
if [[ "$SKIP_CERTS" == "false" ]]; then
    log_info "Step 1: Generating Nebula certificates..."

    mkdir -p "$CA_DIR" "$NEBULA_DIR/lighthouse"

    if [[ ! -f "$CA_DIR/ca.crt" ]]; then
        log_info "  Creating CA certificate..."
        if [[ "$DRY_RUN" == "false" ]]; then
            cd "$CA_DIR"
            nebula-cert ca -name "talos-homelab-mesh" -duration 87600h
        fi
    else
        log_info "  CA certificate already exists"
    fi

    if [[ ! -f "$CA_DIR/lighthouse.crt" ]]; then
        log_info "  Creating lighthouse certificate..."
        if [[ "$DRY_RUN" == "false" ]]; then
            cd "$CA_DIR"
            nebula-cert sign -name "lighthouse" -ip "10.42.0.1/16" -groups "lighthouse,infrastructure"
        fi
    else
        log_info "  Lighthouse certificate already exists"
    fi

    # Copy certs for userdata generator
    if [[ "$DRY_RUN" == "false" ]]; then
        cp "$CA_DIR/ca.crt" "$NEBULA_DIR/ca.crt"
        cp "$CA_DIR/lighthouse.crt" "$NEBULA_DIR/lighthouse/host.crt"
        cp "$CA_DIR/lighthouse.key" "$NEBULA_DIR/lighthouse/host.key"
    fi
else
    log_info "Step 1: Skipping certificate generation (--skip-certs)"
fi

# Step 2: Create SSH key pair
log_info "Step 2: Creating SSH key pair..."
mkdir -p "$SSH_DIR"

existing_key=$(aws ec2 describe-key-pairs --key-names "$KEY_NAME" --region "$AWS_REGION" 2>/dev/null || true)
if [[ -z "$existing_key" ]]; then
    log_info "  Creating new key pair: $KEY_NAME"
    if [[ "$DRY_RUN" == "false" ]]; then
        aws ec2 create-key-pair \
            --key-name "$KEY_NAME" \
            --key-type rsa \
            --key-format pem \
            --query 'KeyMaterial' \
            --output text \
            --region "$AWS_REGION" > "$SSH_DIR/$KEY_NAME.pem"
        chmod 600 "$SSH_DIR/$KEY_NAME.pem"
    fi
else
    log_info "  Key pair already exists: $KEY_NAME"
fi

# Step 3: Create security group
log_info "Step 3: Creating security group..."

# Get default VPC
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" \
    --query 'Vpcs[0].VpcId' --output text --region "$AWS_REGION")
log_info "  VPC: $VPC_ID"

# Check if security group exists
existing_sg=$(aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=$SG_NAME" "Name=vpc-id,Values=$VPC_ID" \
    --query 'SecurityGroups[0].GroupId' --output text --region "$AWS_REGION" 2>/dev/null || echo "None")

if [[ "$existing_sg" == "None" || -z "$existing_sg" ]]; then
    log_info "  Creating security group: $SG_NAME"
    if [[ "$DRY_RUN" == "false" ]]; then
        SG_ID=$(aws ec2 create-security-group \
            --group-name "$SG_NAME" \
            --description "Nebula Lighthouse - UDP 4242, SSH" \
            --vpc-id "$VPC_ID" \
            --region "$AWS_REGION" \
            --output text --query 'GroupId')

        # Add rules
        aws ec2 authorize-security-group-ingress \
            --group-id "$SG_ID" \
            --protocol udp --port 4242 --cidr 0.0.0.0/0 \
            --region "$AWS_REGION"

        aws ec2 authorize-security-group-ingress \
            --group-id "$SG_ID" \
            --protocol tcp --port 22 --cidr 0.0.0.0/0 \
            --region "$AWS_REGION"

        save_state "security_group_id" "$SG_ID"
        log_info "  Created: $SG_ID"
    fi
else
    SG_ID="$existing_sg"
    save_state "security_group_id" "$SG_ID"
    log_info "  Security group already exists: $SG_ID"
fi

# Step 4: Get AMI ID
log_info "Step 4: Getting Amazon Linux 2023 AMI..."
AMI_ID=$(aws ec2 describe-images \
    --owners amazon \
    --filters "Name=name,Values=al2023-ami-2023*-x86_64" \
              "Name=state,Values=available" \
    --query 'Images | sort_by(@, &CreationDate) | [-1].ImageId' \
    --output text \
    --region "$AWS_REGION")
log_info "  AMI: $AMI_ID"

# Step 5: Allocate Elastic IP
log_info "Step 5: Allocating Elastic IP..."

existing_eip=$(get_state "elastic_ip")
if [[ -z "$existing_eip" ]]; then
    if [[ "$DRY_RUN" == "false" ]]; then
        ALLOCATION=$(aws ec2 allocate-address \
            --domain vpc \
            --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=$SG_NAME}]" \
            --region "$AWS_REGION")

        EIP=$(echo "$ALLOCATION" | jq -r '.PublicIp')
        ALLOC_ID=$(echo "$ALLOCATION" | jq -r '.AllocationId')

        save_state "elastic_ip" "$EIP"
        save_state "allocation_id" "$ALLOC_ID"
        log_info "  Allocated: $EIP ($ALLOC_ID)"
    else
        EIP="DRY-RUN-IP"
        ALLOC_ID="DRY-RUN-ALLOC"
    fi
else
    EIP="$existing_eip"
    ALLOC_ID=$(get_state "allocation_id")
    log_info "  Using existing: $EIP"
fi

# Step 6: Generate userdata with Elastic IP
log_info "Step 6: Generating userdata script..."
USERDATA_FILE="/tmp/lighthouse-userdata-$$.sh"

if [[ "$DRY_RUN" == "false" ]]; then
    "$SCRIPT_DIR/lighthouse-userdata.sh" > "$USERDATA_FILE"
    # Replace placeholder with actual Elastic IP
    sed -i.bak "s/ELASTIC_IP_PLACEHOLDER/$EIP/g" "$USERDATA_FILE"
    rm -f "${USERDATA_FILE}.bak"
    log_info "  Generated: $USERDATA_FILE"
fi

# Step 7: Launch EC2 instance
log_info "Step 7: Launching EC2 instance..."

existing_instance=$(get_state "instance_id")
if [[ -n "$existing_instance" ]]; then
    instance_state=$(aws ec2 describe-instances --instance-ids "$existing_instance" \
        --query 'Reservations[0].Instances[0].State.Name' --output text --region "$AWS_REGION" 2>/dev/null || echo "terminated")

    if [[ "$instance_state" != "terminated" ]]; then
        log_warn "  Instance already exists: $existing_instance (state: $instance_state)"
        INSTANCE_ID="$existing_instance"
    fi
fi

if [[ -z "${INSTANCE_ID:-}" ]]; then
    if [[ "$DRY_RUN" == "false" ]]; then
        INSTANCE_ID=$(aws ec2 run-instances \
            --image-id "$AMI_ID" \
            --instance-type "$INSTANCE_TYPE" \
            --key-name "$KEY_NAME" \
            --security-group-ids "$SG_ID" \
            --user-data "file://$USERDATA_FILE" \
            --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$SG_NAME}]" \
            --metadata-options "HttpTokens=optional,HttpEndpoint=enabled" \
            --region "$AWS_REGION" \
            --query 'Instances[0].InstanceId' \
            --output text)

        save_state "instance_id" "$INSTANCE_ID"
        log_info "  Launched: $INSTANCE_ID"

        log_info "  Waiting for instance to be running..."
        aws ec2 wait instance-running --instance-ids "$INSTANCE_ID" --region "$AWS_REGION"
    else
        INSTANCE_ID="DRY-RUN-INSTANCE"
    fi
fi

# Step 8: Associate Elastic IP
log_info "Step 8: Associating Elastic IP..."
if [[ "$DRY_RUN" == "false" ]]; then
    aws ec2 associate-address \
        --instance-id "$INSTANCE_ID" \
        --allocation-id "$ALLOC_ID" \
        --region "$AWS_REGION" || log_warn "  EIP may already be associated"
    log_info "  Associated $EIP with $INSTANCE_ID"
fi

# Step 9: Wait for SSH and verify
log_info "Step 9: Verifying deployment..."
if [[ "$DRY_RUN" == "false" ]]; then
    log_info "  Waiting for SSH to become available..."
    sleep 30  # Wait for instance to fully boot

    for i in {1..10}; do
        if ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 \
            -i "$SSH_DIR/$KEY_NAME.pem" "ec2-user@$EIP" "echo 'SSH OK'" 2>/dev/null; then
            break
        fi
        log_info "  Waiting for SSH... (attempt $i/10)"
        sleep 10
    done

    # Wait for cloud-init to complete
    log_info "  Waiting for cloud-init to complete..."
    ssh -i "$SSH_DIR/$KEY_NAME.pem" "ec2-user@$EIP" \
        "sudo cloud-init status --wait" 2>/dev/null || true

    # Check Nebula status
    log_info "  Checking Nebula status..."
    if ssh -i "$SSH_DIR/$KEY_NAME.pem" "ec2-user@$EIP" \
        "sudo systemctl is-active nebula" 2>/dev/null | grep -q active; then
        log_info "  ✅ Nebula is running!"
    else
        log_warn "  Nebula may not be running yet. Check manually:"
        log_warn "    ssh -i $SSH_DIR/$KEY_NAME.pem ec2-user@$EIP"
        log_warn "    sudo systemctl status nebula"
    fi
fi

# Summary
echo ""
log_info "=== Provisioning Complete ==="
echo ""
echo "Resources created:"
echo "  Instance ID:    ${INSTANCE_ID:-DRY-RUN}"
echo "  Elastic IP:     ${EIP:-DRY-RUN}"
echo "  Security Group: ${SG_ID:-DRY-RUN}"
echo "  SSH Key:        $SSH_DIR/$KEY_NAME.pem"
echo ""
echo "Nebula Mesh:"
echo "  Lighthouse IP:  $EIP:4242"
echo "  Mesh IP:        10.42.0.1"
echo ""
echo "SSH Access:"
echo "  ssh -i $SSH_DIR/$KEY_NAME.pem ec2-user@$EIP"
echo ""
echo "State file: $STATE_FILE"
echo ""
echo "To teardown:"
echo "  $0 --teardown"
