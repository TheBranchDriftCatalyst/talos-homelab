#!/bin/bash
# LLM Worker Control Script
# Manages the scale-to-zero LLM worker instance
#
# Usage:
#   ./scripts/hybrid-llm/llm-worker.sh start    # Start the worker
#   ./scripts/hybrid-llm/llm-worker.sh stop     # Stop the worker (preserves state)
#   ./scripts/hybrid-llm/llm-worker.sh status   # Check worker status
#   ./scripts/hybrid-llm/llm-worker.sh ssh      # SSH into the worker
#   ./scripts/hybrid-llm/llm-worker.sh logs     # View bootstrap logs
#   ./scripts/hybrid-llm/llm-worker.sh provision # Create new worker instance
#   ./scripts/hybrid-llm/llm-worker.sh terminate # Destroy worker (loses state)
#   ./scripts/hybrid-llm/llm-worker.sh ollama   # Run ollama commands on worker

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Configuration
AWS_REGION="${AWS_REGION:-us-west-2}"
# GPU Instance Types (g4dn = NVIDIA T4, g5 = NVIDIA A10G):
#   g4dn.xlarge:  4 vCPU, 16GB RAM, 1x T4 (~$0.526/hr on-demand, ~$0.16/hr spot)
#   g4dn.2xlarge: 8 vCPU, 32GB RAM, 1x T4 (~$0.752/hr on-demand)
#   g4dn.4xlarge: 16 vCPU, 64GB RAM, 1x T4 (~$1.204/hr on-demand)
#   g5.xlarge:    4 vCPU, 16GB RAM, 1x A10G (~$1.006/hr on-demand)
#   g5.2xlarge:   8 vCPU, 32GB RAM, 1x A10G (~$1.212/hr on-demand)
INSTANCE_TYPE="${LLM_INSTANCE_TYPE:-g4dn.4xlarge}" # 16 vCPU, 64GB RAM, 1x T4 GPU
USE_SPOT="${LLM_USE_SPOT:-false}"                  # Default to on-demand for reliability
KEY_NAME="hybrid-llm-key"
SG_NAME="nebula-lighthouse" # Reuse lighthouse security group

# AMI Configuration - use pre-baked AMI or fall back to base AL2023
# Set USE_CUSTOM_AMI=false to use legacy userdata provisioning
USE_CUSTOM_AMI="${LLM_USE_CUSTOM_AMI:-true}"
CUSTOM_AMI_PREFIX="catalyst-llm-gpu-worker"
SECRET_NAME="${LLM_SECRET_NAME:-catalyst-llm/gpu-worker}"

# Warm-up timeout (seconds to wait for Ollama to be ready)
WARMUP_TIMEOUT="${LLM_WARMUP_TIMEOUT:-180}" # 3 minutes default

# Model storage EBS volume configuration
MODEL_VOLUME_SIZE="${LLM_MODEL_VOLUME_SIZE:-100}" # GB for model storage
MODEL_VOLUME_TYPE="gp3"
MODEL_VOLUME_NAME="llm-model-storage"

# State files
STATE_FILE="$REPO_ROOT/.output/worker-state.json"
SSH_KEY="$REPO_ROOT/.output/ssh/$KEY_NAME.pem"
LIGHTHOUSE_STATE="$REPO_ROOT/.output/lighthouse-state.json"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Get state value
get_state() {
  local key="$1"
  if [[ -f "$STATE_FILE" ]]; then
    jq -r --arg key "$key" '.[$key] // empty' "$STATE_FILE"
  fi
}

# Save state value
save_state() {
  local key="$1"
  local value="$2"
  mkdir -p "$(dirname "$STATE_FILE")"
  if [[ -f "$STATE_FILE" ]]; then
    jq --arg key "$key" --arg value "$value" '.[$key] = $value' "$STATE_FILE" > "${STATE_FILE}.tmp"
    mv "${STATE_FILE}.tmp" "$STATE_FILE"
  else
    echo "{\"$key\": \"$value\"}" > "$STATE_FILE"
  fi
}

# Get instance status
get_instance_status() {
  local instance_id=$(get_state "instance_id")
  if [[ -z "$instance_id" ]]; then
    echo "not_provisioned"
    return
  fi

  aws ec2 describe-instances \
    --instance-ids "$instance_id" \
    --query 'Reservations[0].Instances[0].State.Name' \
    --output text \
    --region "$AWS_REGION" 2> /dev/null || echo "not_found"
}

# Get worker IP (Nebula mesh IP)
get_worker_ip() {
  echo "10.42.2.1"
}

# Get worker public IP (for SSH before Nebula is up)
get_worker_public_ip() {
  local instance_id=$(get_state "instance_id")
  if [[ -z "$instance_id" ]]; then
    return
  fi
  aws ec2 describe-instances \
    --instance-ids "$instance_id" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text \
    --region "$AWS_REGION" 2> /dev/null
}

# Get the latest custom GPU worker AMI
get_custom_ami() {
  local ami_id=$(aws ec2 describe-images \
    --owners self \
    --filters "Name=name,Values=${CUSTOM_AMI_PREFIX}*" \
              "Name=state,Values=available" \
    --query 'Images | sort_by(@, &CreationDate) | [-1].ImageId' \
    --output text \
    --region "$AWS_REGION" 2>/dev/null)

  if [[ -z "$ami_id" || "$ami_id" == "None" ]]; then
    return 1
  fi
  echo "$ami_id"
}

# Generate minimal userdata for pre-baked AMI
# Just sets environment variables - secrets come from AWS Secrets Manager
generate_minimal_userdata() {
  local lighthouse_public_ip="$1"
  local lighthouse_nebula_ip="${2:-10.42.1.1}"

  cat << EOF
#!/bin/bash
# Minimal bootstrap for pre-baked GPU Worker AMI
# Secrets are fetched from AWS Secrets Manager at boot
set -euo pipefail
exec > >(tee /var/log/userdata.log) 2>&1
echo "=== GPU Worker Bootstrap Started at \$(date) ==="

# Configuration injected at launch time
export SECRET_NAME="${SECRET_NAME}"
export LIGHTHOUSE_NEBULA_IP="${lighthouse_nebula_ip}"
export LIGHTHOUSE_PUBLIC_IP="${lighthouse_public_ip}"
export NEBULA_IP="10.42.2.1"
export CONTROL_PLANE_ADDR="${lighthouse_nebula_ip}:50051"

# Run the pre-installed bootstrap script
if [[ -x /usr/local/bin/bootstrap-gpu-worker.sh ]]; then
  /usr/local/bin/bootstrap-gpu-worker.sh
else
  # Fallback: inline bootstrap for compatibility
  REGION=\$(curl -s http://169.254.169.254/latest/meta-data/placement/region)
  INSTANCE_ID=\$(curl -s http://169.254.169.254/latest/meta-data/instance-id)

  echo "Fetching secrets from AWS Secrets Manager: \${SECRET_NAME}"
  SECRETS=\$(aws secretsmanager get-secret-value --secret-id "\${SECRET_NAME}" --region "\${REGION}" --query SecretString --output text)

  # Extract and write Nebula certificates
  echo "\$SECRETS" | jq -r '.nebula_ca_crt' | base64 -d > /etc/nebula/ca.crt
  echo "\$SECRETS" | jq -r '.nebula_host_crt' | base64 -d > /etc/nebula/host.crt
  echo "\$SECRETS" | jq -r '.nebula_host_key' | base64 -d > /etc/nebula/host.key
  chmod 600 /etc/nebula/host.key

  # Configure Nebula
  cat > /etc/nebula/config.yml << NEBCONF
pki:
  ca: /etc/nebula/ca.crt
  cert: /etc/nebula/host.crt
  key: /etc/nebula/host.key
static_host_map:
  "\${LIGHTHOUSE_NEBULA_IP}": ["\${LIGHTHOUSE_PUBLIC_IP}:4242"]
lighthouse:
  am_lighthouse: false
  interval: 60
  hosts:
    - "\${LIGHTHOUSE_NEBULA_IP}"
listen:
  host: 0.0.0.0
  port: 4242
punchy:
  punch: true
tun:
  dev: nebula1
  mtu: 1300
firewall:
  outbound:
    - port: any
      proto: any
      host: any
  inbound:
    - port: any
      proto: icmp
      host: any
    - port: 22
      proto: tcp
      host: any
    - port: 11434
      proto: tcp
      host: any
NEBCONF

  # Configure worker-agent
  cat > /etc/worker-agent/env << AGENTENV
CONTROL_PLANE_ADDR=\${CONTROL_PLANE_ADDR}
NODE_TYPE=gpu-worker
INSTANCE_ID=\${INSTANCE_ID}
NEBULA_IP=\${NEBULA_IP}
AGENTENV

  # Start services
  systemctl enable nebula worker-agent ollama
  systemctl start nebula
  sleep 5
  systemctl start worker-agent ollama

  # Configure k3s if token available
  K3S_TOKEN=\$(echo "\$SECRETS" | jq -r '.k3s_token // empty')
  K3S_URL=\$(echo "\$SECRETS" | jq -r '.k3s_url // empty')
  if [[ -n "\$K3S_TOKEN" && -n "\$K3S_URL" ]]; then
    cat > /etc/rancher/k3s/config.yaml << K3SCONF
server: \${K3S_URL}
token: \${K3S_TOKEN}
node-name: \${INSTANCE_ID}
node-ip: \${NEBULA_IP}
flannel-iface: nebula1
node-label:
  - "node.kubernetes.io/instance-type=gpu-worker"
  - "nvidia.com/gpu=true"
K3SCONF
    systemctl enable k3s-agent
    systemctl start k3s-agent
  fi
fi

echo "=== GPU Worker Bootstrap Completed at \$(date) ==="
EOF
}

# Get or create persistent EBS volume for model storage
ensure_model_volume() {
  local volume_id=$(get_state "model_volume_id")

  # Check if volume exists
  if [[ -n "$volume_id" ]]; then
    local vol_state=$(aws ec2 describe-volumes \
      --volume-ids "$volume_id" \
      --query 'Volumes[0].State' \
      --output text \
      --region "$AWS_REGION" 2> /dev/null || echo "not_found")

    if [[ "$vol_state" != "not_found" && "$vol_state" != "deleted" ]]; then
      log_info "Using existing model volume: $volume_id"
      echo "$volume_id"
      return
    fi
  fi

  # Get instance AZ for volume placement
  local instance_id=$(get_state "instance_id")
  local az
  if [[ -n "$instance_id" ]]; then
    az=$(aws ec2 describe-instances \
      --instance-ids "$instance_id" \
      --query 'Reservations[0].Instances[0].Placement.AvailabilityZone' \
      --output text --region "$AWS_REGION" 2>/dev/null)
  fi
  # Default to first AZ in region if instance not available yet
  az="${az:-${AWS_REGION}a}"

  # Create new volume
  log_info "Creating persistent EBS volume for models (${MODEL_VOLUME_SIZE}GB) in $az..."
  volume_id=$(aws ec2 create-volume \
    --size "$MODEL_VOLUME_SIZE" \
    --volume-type "$MODEL_VOLUME_TYPE" \
    --availability-zone "$az" \
    --tag-specifications "ResourceType=volume,Tags=[{Key=Name,Value=$MODEL_VOLUME_NAME},{Key=Project,Value=hybrid-llm}]" \
    --region "$AWS_REGION" \
    --query 'VolumeId' \
    --output text)

  save_state "model_volume_id" "$volume_id"

  # Wait for volume to be available
  log_info "Waiting for volume to be available..."
  aws ec2 wait volume-available --volume-ids "$volume_id" --region "$AWS_REGION"

  log_info "Created model volume: $volume_id"
  echo "$volume_id"
}

# Attach model volume to instance
attach_model_volume() {
  local instance_id="$1"
  local volume_id=$(get_state "model_volume_id")

  if [[ -z "$volume_id" ]]; then
    log_warn "No model volume found"
    return
  fi

  # Check current attachment state
  local attachment_state=$(aws ec2 describe-volumes \
    --volume-ids "$volume_id" \
    --query 'Volumes[0].Attachments[0].State' \
    --output text \
    --region "$AWS_REGION" 2> /dev/null || echo "")

  local attached_instance=$(aws ec2 describe-volumes \
    --volume-ids "$volume_id" \
    --query 'Volumes[0].Attachments[0].InstanceId' \
    --output text \
    --region "$AWS_REGION" 2> /dev/null || echo "")

  if [[ "$attachment_state" == "attached" && "$attached_instance" == "$instance_id" ]]; then
    log_info "Model volume already attached to instance"
    return
  fi

  # If attached to different instance, detach first
  if [[ "$attachment_state" == "attached" ]]; then
    log_info "Detaching model volume from previous instance..."
    aws ec2 detach-volume --volume-id "$volume_id" --region "$AWS_REGION" > /dev/null
    aws ec2 wait volume-available --volume-ids "$volume_id" --region "$AWS_REGION"
  fi

  # Attach to instance
  log_info "Attaching model volume to instance..."
  aws ec2 attach-volume \
    --volume-id "$volume_id" \
    --instance-id "$instance_id" \
    --device /dev/xvdf \
    --region "$AWS_REGION" > /dev/null

  # Wait for attachment
  log_info "Waiting for volume attachment..."
  aws ec2 wait volume-in-use --volume-ids "$volume_id" --region "$AWS_REGION"
  log_info "Model volume attached"
}

#############################################
# Commands
#############################################

cmd_status() {
  local status=$(get_instance_status)
  local instance_id=$(get_state "instance_id")
  local instance_mode=$(get_state "instance_mode")
  local model_volume_id=$(get_state "model_volume_id")
  local ami_type=$(get_state "ami_type")

  echo ""
  echo -e "${BLUE}=== LLM Worker Status ===${NC}"
  echo ""

  case "$status" in
    running)
      local public_ip=$(get_worker_public_ip)
      echo -e "State:        ${GREEN}Running${NC}"
      echo "Instance ID:  $instance_id"
      echo "Instance:     $INSTANCE_TYPE ($instance_mode)"
      if [[ "$ami_type" == "custom" ]]; then
        echo -e "AMI:          ${GREEN}Pre-baked${NC} (fast boot)"
      else
        echo "AMI:          AL2023 (legacy)"
      fi
      echo "Public IP:    $public_ip"
      echo "Nebula IP:    10.42.2.1"
      echo "Ollama API:   http://10.42.2.1:11434"
      if [[ -n "$model_volume_id" ]]; then
        echo "Model Volume: $model_volume_id (${MODEL_VOLUME_SIZE}GB persistent)"
      fi
      echo ""

      # Check Nebula connectivity
      if ping -c 1 -W 2 10.42.2.1 > /dev/null 2>&1; then
        echo -e "Mesh:         ${GREEN}Connected${NC}"

        # Check Ollama
        if curl -s --connect-timeout 2 http://10.42.2.1:11434/api/tags > /dev/null 2>&1; then
          echo -e "Ollama:       ${GREEN}Ready${NC}"
          echo ""
          echo "Available models:"
          curl -s http://10.42.2.1:11434/api/tags | jq -r '.models[].name' 2> /dev/null || echo "  (none)"
        else
          echo -e "Ollama:       ${YELLOW}Not ready${NC}"
        fi
      else
        echo -e "Mesh:         ${YELLOW}Not connected (instance may still be booting)${NC}"
      fi
      ;;
    stopped)
      echo -e "State:        ${YELLOW}Stopped${NC}"
      echo "Instance ID:  $instance_id"
      if [[ -n "$model_volume_id" ]]; then
        echo "Model Volume: $model_volume_id (${MODEL_VOLUME_SIZE}GB persistent - models preserved)"
      fi
      echo ""
      echo "Run './scripts/hybrid-llm/llm-worker.sh start' to start"
      ;;
    not_provisioned)
      echo -e "State:        ${RED}Not Provisioned${NC}"
      if [[ -n "$model_volume_id" ]]; then
        echo -e "Model Volume: $model_volume_id (${GREEN}preserved${NC} - will be reattached on provision)"
      fi
      echo ""
      echo "Run './scripts/hybrid-llm/llm-worker.sh provision' to create"
      ;;
    *)
      echo -e "State:        ${RED}$status${NC}"
      echo "Instance ID:  $instance_id"
      ;;
  esac
  echo ""
}

cmd_start() {
  local instance_id=$(get_state "instance_id")
  local status=$(get_instance_status)

  if [[ "$status" == "not_provisioned" ]]; then
    log_error "Worker not provisioned. Run 'provision' first."
    exit 1
  fi

  if [[ "$status" == "running" ]]; then
    log_info "Worker is already running"
    cmd_status
    return
  fi

  log_info "Starting worker instance: $instance_id"

  # Try to start the instance
  if ! aws ec2 start-instances --instance-ids "$instance_id" --region "$AWS_REGION" > /dev/null 2>&1; then
    log_warn "Failed to start instance (may be capacity issue)"
    log_info "Checking if this is a spot instance with capacity issues..."

    # Check if it's a spot instance
    local spot_request=$(aws ec2 describe-instances \
      --instance-ids "$instance_id" \
      --query 'Reservations[0].Instances[0].SpotInstanceRequestId' \
      --output text \
      --region "$AWS_REGION" 2> /dev/null || echo "")

    if [[ -n "$spot_request" && "$spot_request" != "None" ]]; then
      log_warn "This is a spot instance. Consider re-provisioning as on-demand:"
      log_warn "  $0 terminate && $0 provision"
      log_warn "Or wait and try again later when spot capacity is available."
    fi
    exit 1
  fi

  log_info "Waiting for instance to be running..."
  aws ec2 wait instance-running --instance-ids "$instance_id" --region "$AWS_REGION"

  # Attach model volume if exists
  attach_model_volume "$instance_id"

  log_info "Instance running. Waiting for Nebula mesh connection..."
  for i in {1..60}; do
    if ping -c 1 -W 2 10.42.2.1 > /dev/null 2>&1; then
      log_info "Mesh connected!"
      break
    fi
    echo -n "."
    sleep 5
  done
  echo ""

  log_info "Waiting for Ollama to be ready..."
  for i in {1..30}; do
    if curl -s --connect-timeout 2 http://10.42.2.1:11434/api/tags > /dev/null 2>&1; then
      log_info "Ollama is ready!"
      break
    fi
    echo -n "."
    sleep 5
  done
  echo ""

  cmd_status
}

# Warm command - start and wait for full readiness (for automation/APIs)
cmd_warm() {
  local status=$(get_instance_status)
  local start_time=$(date +%s)

  if [[ "$status" == "not_provisioned" ]]; then
    log_error "Worker not provisioned. Run 'provision' first."
    exit 1
  fi

  # Start if not running
  if [[ "$status" != "running" ]]; then
    log_info "Starting worker..."
    cmd_start
  fi

  # Wait for Ollama to be fully ready
  log_info "Waiting for Ollama API to be ready (timeout: ${WARMUP_TIMEOUT}s)..."
  local elapsed=0
  while [[ $elapsed -lt $WARMUP_TIMEOUT ]]; do
    if curl -s --connect-timeout 2 http://10.42.2.1:11434/api/tags > /dev/null 2>&1; then
      local end_time=$(date +%s)
      local total_time=$((end_time - start_time))
      log_info "Worker ready! Total warm-up time: ${total_time}s"
      echo "READY"
      exit 0
    fi
    sleep 5
    elapsed=$((elapsed + 5))
    echo -n "."
  done
  echo ""

  log_error "Timeout waiting for Ollama to be ready"
  exit 1
}

# Check if worker is ready (non-blocking)
cmd_ready() {
  if curl -s --connect-timeout 2 http://10.42.2.1:11434/api/tags > /dev/null 2>&1; then
    echo "READY"
    exit 0
  else
    echo "NOT_READY"
    exit 1
  fi
}

cmd_stop() {
  local instance_id=$(get_state "instance_id")
  local status=$(get_instance_status)

  if [[ "$status" != "running" ]]; then
    log_warn "Worker is not running (status: $status)"
    return
  fi

  log_info "Stopping worker instance: $instance_id"
  aws ec2 stop-instances --instance-ids "$instance_id" --region "$AWS_REGION" > /dev/null

  log_info "Waiting for instance to stop..."
  aws ec2 wait instance-stopped --instance-ids "$instance_id" --region "$AWS_REGION"

  log_info "Worker stopped. State preserved - use 'start' to resume."
}

cmd_provision() {
  local existing_id=$(get_state "instance_id")
  if [[ -n "$existing_id" ]]; then
    local status=$(get_instance_status)
    if [[ "$status" != "terminated" && "$status" != "not_found" ]]; then
      log_error "Worker already exists: $existing_id (status: $status)"
      log_error "Use 'terminate' first to destroy it"
      exit 1
    fi
  fi

  log_info "=== Provisioning LLM Worker ==="
  log_info "Instance type: $INSTANCE_TYPE"
  log_info "Region: $AWS_REGION"

  # Get security group from lighthouse state
  local sg_id=""
  if [[ -f "$LIGHTHOUSE_STATE" ]]; then
    sg_id=$(jq -r '.security_group_id // empty' "$LIGHTHOUSE_STATE")
  fi

  if [[ -z "$sg_id" ]]; then
    log_error "Security group not found. Run lighthouse provisioning first."
    exit 1
  fi
  log_info "Security Group: $sg_id"

  # Get lighthouse public IP for Nebula config
  local lighthouse_public_ip=""
  if [[ -f "$LIGHTHOUSE_STATE" ]]; then
    lighthouse_public_ip=$(jq -r '.elastic_ip // empty' "$LIGHTHOUSE_STATE")
  fi
  if [[ -z "$lighthouse_public_ip" ]]; then
    log_error "Lighthouse public IP not found. Run lighthouse provisioning first."
    exit 1
  fi
  log_info "Lighthouse IP: $lighthouse_public_ip"

  # Get AMI - try custom pre-baked AMI first, fall back to AL2023
  local ami_id=""
  local ami_type=""
  if [[ "$USE_CUSTOM_AMI" == "true" ]]; then
    log_info "Looking for pre-baked GPU worker AMI..."
    ami_id=$(get_custom_ami) || true
    if [[ -n "$ami_id" ]]; then
      ami_type="custom"
      log_info "Using custom AMI: $ami_id (fast boot ~30-60s)"
    else
      log_warn "Custom AMI not found. Build with: cd tools/ec2-agent/ami && packer build gpu-worker.pkr.hcl"
      log_info "Falling back to base AL2023 with legacy userdata (~5 min boot)"
    fi
  fi

  if [[ -z "$ami_id" ]]; then
    log_info "Finding latest Amazon Linux 2023 AMI..."
    ami_id=$(aws ec2 describe-images \
      --owners amazon \
      --filters "Name=name,Values=al2023-ami-2023*-x86_64" \
      "Name=state,Values=available" \
      --query 'Images | sort_by(@, &CreationDate) | [-1].ImageId' \
      --output text \
      --region "$AWS_REGION")
    ami_type="al2023"
    log_info "AMI: $ami_id (legacy provisioning)"
  fi

  # Generate userdata
  local userdata_file="/tmp/worker-userdata-$$.sh"
  if [[ "$ami_type" == "custom" ]]; then
    log_info "Generating minimal userdata for pre-baked AMI..."
    generate_minimal_userdata "$lighthouse_public_ip" > "$userdata_file"
  else
    log_info "Generating full userdata script (legacy mode)..."
    "$SCRIPT_DIR/worker-userdata.sh" > "$userdata_file"
  fi

  # Launch instance (on-demand by default for reliability, spot optional)
  if [[ "$USE_SPOT" == "true" ]]; then
    log_info "Requesting SPOT instance (may have capacity issues)..."
    local instance_id=$(aws ec2 run-instances \
      --image-id "$ami_id" \
      --instance-type "$INSTANCE_TYPE" \
      --key-name "$KEY_NAME" \
      --security-group-ids "$sg_id" \
      --user-data "file://$userdata_file" \
      --instance-market-options 'MarketType=spot,SpotOptions={SpotInstanceType=persistent,InstanceInterruptionBehavior=stop}' \
      --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=llm-worker},{Key=Project,Value=hybrid-llm},{Key=InstanceMode,Value=spot}]" \
      --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":100,"VolumeType":"gp3"}}]' \
      --metadata-options "HttpTokens=optional,HttpEndpoint=enabled" \
      --region "$AWS_REGION" \
      --query 'Instances[0].InstanceId' \
      --output text)
    save_state "instance_mode" "spot"
  else
    log_info "Requesting ON-DEMAND instance..."
    local instance_id=$(aws ec2 run-instances \
      --image-id "$ami_id" \
      --instance-type "$INSTANCE_TYPE" \
      --key-name "$KEY_NAME" \
      --security-group-ids "$sg_id" \
      --user-data "file://$userdata_file" \
      --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=llm-worker},{Key=Project,Value=hybrid-llm},{Key=InstanceMode,Value=on-demand}]" \
      --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":100,"VolumeType":"gp3"}}]' \
      --metadata-options "HttpTokens=optional,HttpEndpoint=enabled" \
      --region "$AWS_REGION" \
      --query 'Instances[0].InstanceId' \
      --output text)
    save_state "instance_mode" "on-demand"
  fi

  rm -f "$userdata_file"

  save_state "instance_id" "$instance_id"
  save_state "instance_type" "$INSTANCE_TYPE"
  save_state "ami_type" "$ami_type"
  save_state "ami_id" "$ami_id"
  save_state "created_at" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  log_info "Instance launched: $instance_id"

  log_info "Waiting for instance to be running..."
  aws ec2 wait instance-running --instance-ids "$instance_id" --region "$AWS_REGION"

  # Create and attach persistent model volume
  ensure_model_volume > /dev/null
  attach_model_volume "$instance_id"

  local public_ip=$(get_worker_public_ip)
  save_state "public_ip" "$public_ip"

  log_info "Instance running at: $public_ip"
  log_info ""
  if [[ "$ami_type" == "custom" ]]; then
    log_info "Bootstrap in progress (~30-60 seconds with pre-baked AMI). Monitor with:"
  else
    log_info "Bootstrap in progress (~3-5 minutes with legacy userdata). Monitor with:"
  fi
  log_info "  $0 logs"
  log_info ""
  log_info "Or wait for full readiness:"
  log_info "  $0 status"
}

cmd_terminate() {
  local instance_id=$(get_state "instance_id")

  if [[ -z "$instance_id" ]]; then
    log_warn "No worker instance found"
    return
  fi

  log_warn "This will DESTROY the worker instance and all its data!"
  read -p "Are you sure? (yes/no): " confirm

  if [[ "$confirm" != "yes" ]]; then
    log_info "Cancelled"
    return
  fi

  # Cancel spot request first
  local spot_request=$(aws ec2 describe-instances \
    --instance-ids "$instance_id" \
    --query 'Reservations[0].Instances[0].SpotInstanceRequestId' \
    --output text \
    --region "$AWS_REGION" 2> /dev/null || echo "")

  if [[ -n "$spot_request" && "$spot_request" != "None" ]]; then
    log_info "Cancelling spot request: $spot_request"
    aws ec2 cancel-spot-instance-requests \
      --spot-instance-request-ids "$spot_request" \
      --region "$AWS_REGION" > /dev/null 2>&1 || true
  fi

  log_info "Terminating instance: $instance_id"
  aws ec2 terminate-instances --instance-ids "$instance_id" --region "$AWS_REGION" > /dev/null

  log_info "Waiting for termination..."
  aws ec2 wait instance-terminated --instance-ids "$instance_id" --region "$AWS_REGION"

  rm -f "$STATE_FILE"
  log_info "Worker terminated"
}

cmd_ssh() {
  local status=$(get_instance_status)

  if [[ "$status" != "running" ]]; then
    log_error "Worker is not running (status: $status)"
    exit 1
  fi

  # Try Nebula IP first, fall back to public IP
  if ping -c 1 -W 2 10.42.2.1 > /dev/null 2>&1; then
    log_info "Connecting via Nebula mesh (10.42.2.1)..."
    ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new ec2-user@10.42.2.1 "$@"
  else
    local public_ip=$(get_worker_public_ip)
    log_info "Connecting via public IP ($public_ip)..."
    ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new "ec2-user@$public_ip" "$@"
  fi
}

cmd_logs() {
  log_info "Fetching bootstrap logs..."
  cmd_ssh "sudo cat /var/log/worker-bootstrap.log 2>/dev/null || echo 'No bootstrap log yet'"
}

cmd_ollama() {
  if [[ $# -eq 0 ]]; then
    echo "Usage: $0 ollama <command>"
    echo ""
    echo "Examples:"
    echo "  $0 ollama list           # List models"
    echo "  $0 ollama pull llama3.2  # Pull a model"
    echo "  $0 ollama run llama3.2   # Interactive chat"
    exit 1
  fi

  local status=$(get_instance_status)
  if [[ "$status" != "running" ]]; then
    log_error "Worker is not running. Start it first."
    exit 1
  fi

  cmd_ssh "ollama $*"
}

#############################################
# Main
#############################################

case "${1:-status}" in
  start)
    cmd_start
    ;;
  stop)
    cmd_stop
    ;;
  status)
    cmd_status
    ;;
  warm)
    cmd_warm
    ;;
  ready)
    cmd_ready
    ;;
  provision)
    cmd_provision
    ;;
  terminate)
    cmd_terminate
    ;;
  ssh)
    shift
    cmd_ssh "$@"
    ;;
  logs)
    cmd_logs
    ;;
  ollama)
    shift
    cmd_ollama "$@"
    ;;
  *)
    echo "LLM Worker Control Script"
    echo ""
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  status     Show worker status (default)"
    echo "  start      Start the worker"
    echo "  stop       Stop the worker (preserves state)"
    echo "  warm       Start worker and wait for Ollama to be fully ready"
    echo "  ready      Check if worker is ready (non-blocking, exits 0 if ready)"
    echo "  provision  Create a new worker instance"
    echo "  terminate  Destroy the worker (keeps model storage volume)"
    echo "  ssh        SSH into the worker"
    echo "  logs       View bootstrap logs"
    echo "  ollama     Run ollama commands on worker"
    echo ""
    echo "Environment variables:"
    echo "  AWS_REGION            AWS region (default: us-west-2)"
    echo "  LLM_INSTANCE_TYPE     Instance type (default: g4dn.4xlarge)"
    echo "  LLM_USE_SPOT          Use spot instances (default: false)"
    echo "  LLM_WARMUP_TIMEOUT    Seconds to wait for warm-up (default: 180)"
    echo "  LLM_MODEL_VOLUME_SIZE Persistent model storage size in GB (default: 100)"
    echo "  LLM_USE_CUSTOM_AMI    Use pre-baked AMI for fast boot (default: true)"
    echo "  LLM_SECRET_NAME       AWS Secrets Manager secret name (default: catalyst-llm/gpu-worker)"
    echo ""
    echo "Storage:"
    echo "  Models are stored on a persistent EBS volume (${MODEL_VOLUME_SIZE}GB gp3)."
    echo "  This volume persists across instance stop/start and terminate/provision."
    echo "  Models only need to be downloaded once."
    echo ""
    echo "Examples:"
    echo "  $0 warm                  # Start and wait for ready"
    echo "  $0 ready && curl ...     # Only call if ready"
    echo "  $0 ollama pull llama3.2  # Download a model (persists on EBS)"
    echo "  LLM_USE_SPOT=true $0 provision  # Use spot (cheaper but less reliable)"
    echo ""
    echo "Pre-baked AMI (recommended for fast boot):"
    echo "  Build AMI:  cd tools/ec2-agent/ami && packer build gpu-worker.pkr.hcl"
    echo "  Provision:  $0 provision  # Auto-detects custom AMI"
    echo "  Legacy:     LLM_USE_CUSTOM_AMI=false $0 provision  # Force legacy mode"
    exit 1
    ;;
esac
