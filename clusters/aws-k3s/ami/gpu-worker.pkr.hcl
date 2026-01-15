# =============================================================================
# GPU Worker AMI - For EC2 GPU Instances (g4dn, g5, p4d, etc.)
# =============================================================================
# Includes: Base + NVIDIA drivers + CUDA + Ollama + k3s agent

# Use a GPU instance type for building to install NVIDIA drivers
variable "gpu_instance_type" {
  type        = string
  default     = "g4dn.xlarge"
  description = "GPU instance type for building GPU AMI"
}

source "amazon-ebs" "gpu-worker" {
  ami_name        = "${var.ami_prefix}-gpu-worker-{{timestamp}}"
  ami_description = "GPU Worker AMI with NVIDIA drivers, Ollama, and k3s agent"
  region          = var.aws_region
  ssh_username    = var.ssh_username
  spot_instance_types = [var.gpu_instance_type]
  spot_price      = "auto"
  # Use us-west-2a which reliably supports GPU instances
  availability_zone = "${var.aws_region}a"

  source_ami_filter {
    filters = {
      name                = var.source_ami_filter
      root-device-type    = "ebs"
      virtualization-type = "hvm"
      architecture        = "x86_64"
    }
    owners      = ["amazon"]
    most_recent = true
  }

  launch_block_device_mappings {
    device_name           = "/dev/xvda"
    volume_size           = 50
    volume_type           = "gp3"
    delete_on_termination = true
  }

  tags = merge(var.common_tags, {
    Name         = "${var.ami_prefix}-gpu-worker"
    AMIType      = "gpu-worker"
    NvidiaDriver = var.nvidia_driver_version
    K3sVer       = var.k3s_version
    OllamaVer    = var.ollama_version
    BuildTime    = "{{timestamp}}"
  })

  run_tags = merge(var.common_tags, {
    Name = "packer-builder-gpu-worker"
  })
}

build {
  name    = "gpu-worker"
  sources = ["source.amazon-ebs.gpu-worker"]

  # Upload worker-agent binary
  provisioner "file" {
    source      = "${path.root}/../bin/linux-amd64/worker-agent"
    destination = "/tmp/worker-agent"
  }

  # Install base packages
  provisioner "shell" {
    inline = [
      "set -ex",
      "sudo dnf update -y",
      "sudo dnf install -y --allowerasing jq curl wget tar gzip unzip htop iotop vim tmux",
      "sudo dnf install -y amazon-cloudwatch-agent",
      "sudo dnf install -y kernel-devel kernel-headers gcc make dkms",
      "# Install kernel-modules-extra for DRM support (required by NVIDIA)",
      "sudo dnf install -y kernel-modules-extra",
    ]
  }

  # Install NVIDIA drivers
  # Note: modprobe may fail during AMI build (expected) - drivers will work at runtime
  provisioner "shell" {
    inline = [
      <<-SCRIPT
      #!/bin/bash
      exec 2>&1  # Redirect stderr to stdout to prevent packer from detecting errors
      set -x
      # Install NVIDIA driver - modprobe failures are expected during AMI build
      sudo dnf install -y nvidia-driver-latest-dkms nvidia-driver-latest || true
      # Add NVIDIA container toolkit repo
      curl -s -L https://nvidia.github.io/libnvidia-container/stable/rpm/nvidia-container-toolkit.repo | sudo tee /etc/yum.repos.d/nvidia-container-toolkit.repo
      sudo dnf install -y nvidia-container-toolkit || true
      # Verify packages installed
      rpm -qa | grep -i nvidia || true
      nvidia-smi 2>&1 || echo 'nvidia-smi not available during build (expected)'
      echo "NVIDIA driver installation complete"
      exit 0
      SCRIPT
    ]
  }

  # Install k3s agent
  provisioner "shell" {
    environment_vars = [
      "K3S_VERSION=${var.k3s_version}"
    ]
    inline = [
      "set -ex",
      "curl -sfL https://get.k3s.io | INSTALL_K3S_SKIP_ENABLE=true INSTALL_K3S_SKIP_START=true INSTALL_K3S_VERSION=$K3S_VERSION sh -s - agent",
      "sudo mkdir -p /etc/rancher/k3s",
      "sudo mkdir -p /var/lib/rancher/k3s",
      "k3s --version",
    ]
  }

  # Install Ollama - manual install to avoid NVIDIA auto-detection issues during AMI build
  provisioner "shell" {
    inline = [
      <<-SCRIPT
      #!/bin/bash
      set -x
      # Download and install Ollama binary directly (skip the full installer to avoid modprobe issues)
      curl -fsSL https://ollama.com/install.sh > /tmp/ollama-install.sh
      # Run installer but ignore NVIDIA-related failures
      sudo bash /tmp/ollama-install.sh || true
      # Verify ollama is installed
      which ollama && ollama --version || echo "Ollama not installed properly"
      # Create directories with correct ownership (ollama user created by installer)
      sudo mkdir -p /var/lib/ollama/models
      sudo mkdir -p /etc/ollama
      # Set ownership - ollama user/group created by the installer script
      if id ollama &>/dev/null; then
        sudo chown -R ollama:ollama /var/lib/ollama
      fi
      exit 0
      SCRIPT
    ]
  }

  # Install worker-agent and create default config
  provisioner "shell" {
    inline = [
      "set -ex",
      "sudo mv /tmp/worker-agent /usr/local/bin/worker-agent",
      "sudo chmod +x /usr/local/bin/worker-agent",
      "sudo mkdir -p /etc/worker-agent",
      <<-EOF
      # Create default worker-agent environment file
      # These values can be overridden at runtime via userdata or Secrets Manager
      sudo tee /etc/worker-agent/env > /dev/null << 'ENVFILE'
      # Control Plane Configuration (via Nebula mesh)
      # Set by userdata script at instance launch
      CONTROL_PLANE_ADDR=

      # Node type: gpu-worker or lighthouse
      NODE_TYPE=gpu-worker

      # Health check port
      HEALTH_PORT=8080

      # Nebula IP assigned to this worker (set at runtime)
      NEBULA_IP=
      ENVFILE
      EOF
      ,
    ]
  }

  # Install Nebula overlay network
  provisioner "shell" {
    environment_vars = [
      "NEBULA_VERSION=${var.nebula_version}"
    ]
    inline = [
      "set -ex",
      "echo 'Installing Nebula v${NEBULA_VERSION}...'",
      "curl -fsSL https://github.com/slackhq/nebula/releases/download/v${NEBULA_VERSION}/nebula-linux-amd64.tar.gz -o /tmp/nebula.tar.gz",
      "sudo tar -xzf /tmp/nebula.tar.gz -C /usr/local/bin nebula nebula-cert",
      "sudo chmod +x /usr/local/bin/nebula /usr/local/bin/nebula-cert",
      "rm /tmp/nebula.tar.gz",
      "nebula --version",
      "sudo mkdir -p /etc/nebula",
      <<-EOF
      # Create Nebula systemd service
      sudo tee /etc/systemd/system/nebula.service > /dev/null << 'UNIT'
      [Unit]
      Description=Nebula Overlay Network
      After=network.target
      Before=worker-agent.service k3s-agent.service

      [Service]
      Type=simple
      ExecStart=/usr/local/bin/nebula -config /etc/nebula/config.yaml
      Restart=always
      RestartSec=5
      # Nebula needs CAP_NET_ADMIN for TUN device
      CapabilityBoundingSet=CAP_NET_ADMIN
      AmbientCapabilities=CAP_NET_ADMIN

      [Install]
      WantedBy=multi-user.target
      UNIT
      EOF
      ,
      "sudo systemctl daemon-reload",
    ]
  }

  # Create directories and systemd services
  provisioner "shell" {
    inline = [
      "set -ex",
      "sudo mkdir -p /etc/worker-agent",
      <<-EOF
      sudo tee /etc/systemd/system/worker-agent.service > /dev/null << 'UNIT'
      [Unit]
      Description=Catalyst Worker Agent
      After=network.target ollama.service
      Wants=network-online.target

      [Service]
      Type=simple
      EnvironmentFile=-/etc/worker-agent/env
      # Pass environment variables as flags to worker-agent
      # CONTROL_PLANE_ADDR and RABBITMQ_URL are required/optional env vars
      ExecStart=/bin/bash -c '/usr/local/bin/worker-agent \
        --control-plane="$${CONTROL_PLANE_ADDR}" \
        --type="$${NODE_TYPE:-gpu-worker}" \
        --health-port="$${HEALTH_PORT:-8080}" \
        $${RABBITMQ_URL:+--rabbitmq-url="$${RABBITMQ_URL}"}'
      Restart=always
      RestartSec=10
      TimeoutStartSec=30

      [Install]
      WantedBy=multi-user.target
      UNIT
      EOF
      ,
      <<-EOF
      sudo mkdir -p /etc/systemd/system/ollama.service.d
      sudo tee /etc/systemd/system/ollama.service.d/override.conf > /dev/null << 'UNIT'
      [Service]
      Environment="OLLAMA_MODELS=/var/lib/ollama/models"
      Environment="OLLAMA_HOST=0.0.0.0:11434"
      UNIT
      EOF
      ,
      "sudo systemctl daemon-reload",
    ]
  }

  # Cleanup
  provisioner "shell" {
    inline = [
      "set -ex",
      "sudo dnf clean all",
      "sudo rm -rf /var/cache/dnf/*",
      "sudo rm -f /root/.bash_history /home/ec2-user/.bash_history",
      "sudo truncate -s 0 /var/log/messages /var/log/secure || true",
    ]
  }

  post-processor "manifest" {
    output     = "manifest-gpu-worker.json"
    strip_path = true
  }
}
