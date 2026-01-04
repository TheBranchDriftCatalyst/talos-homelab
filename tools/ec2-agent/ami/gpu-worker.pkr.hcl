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
  instance_type   = var.gpu_instance_type
  region          = var.aws_region
  ssh_username    = var.ssh_username

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
      "sudo dnf install -y jq curl wget tar gzip unzip htop iotop vim tmux",
      "sudo dnf install -y amazon-cloudwatch-agent",
      "sudo dnf install -y kernel-devel kernel-headers gcc make dkms",
    ]
  }

  # Install Nebula
  provisioner "shell" {
    environment_vars = [
      "NEBULA_VERSION=${var.nebula_version}"
    ]
    inline = [
      "set -ex",
      "cd /tmp",
      "wget -q https://github.com/slackhq/nebula/releases/download/v$NEBULA_VERSION/nebula-linux-amd64.tar.gz",
      "tar xzf nebula-linux-amd64.tar.gz",
      "sudo mv nebula nebula-cert /usr/local/bin/",
      "sudo chmod +x /usr/local/bin/nebula /usr/local/bin/nebula-cert",
      "rm -f nebula-linux-amd64.tar.gz",
    ]
  }

  # Install NVIDIA drivers
  provisioner "shell" {
    environment_vars = [
      "NVIDIA_DRIVER_VERSION=${var.nvidia_driver_version}"
    ]
    inline = [
      "set -ex",
      "sudo dnf install -y nvidia-driver-$NVIDIA_DRIVER_VERSION || echo 'NVIDIA driver install failed (expected on non-GPU instance)'",
      "curl -s -L https://nvidia.github.io/libnvidia-container/stable/rpm/nvidia-container-toolkit.repo | sudo tee /etc/yum.repos.d/nvidia-container-toolkit.repo",
      "sudo dnf install -y nvidia-container-toolkit || echo 'nvidia-container-toolkit install skipped'",
      "nvidia-smi || echo 'nvidia-smi not available (expected if building on non-GPU instance)'",
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

  # Install Ollama
  provisioner "shell" {
    inline = [
      "set -ex",
      "curl -fsSL https://ollama.com/install.sh | sudo sh",
      "sudo mkdir -p /var/lib/ollama",
      "sudo mkdir -p /etc/ollama",
      "ollama --version || true",
    ]
  }

  # Install worker-agent
  provisioner "shell" {
    inline = [
      "set -ex",
      "sudo mv /tmp/worker-agent /usr/local/bin/worker-agent",
      "sudo chmod +x /usr/local/bin/worker-agent",
    ]
  }

  # Create directories and systemd services
  provisioner "shell" {
    inline = [
      "set -ex",
      "sudo mkdir -p /etc/nebula",
      "sudo mkdir -p /etc/worker-agent",
      <<-EOF
      sudo tee /etc/systemd/system/nebula.service > /dev/null << 'UNIT'
      [Unit]
      Description=Nebula VPN
      After=network.target
      Wants=network-online.target

      [Service]
      Type=simple
      ExecStart=/usr/local/bin/nebula -config /etc/nebula/config.yml
      Restart=always
      RestartSec=5
      LimitNOFILE=65535

      [Install]
      WantedBy=multi-user.target
      UNIT
      EOF
      ,
      <<-EOF
      sudo tee /etc/systemd/system/worker-agent.service > /dev/null << 'UNIT'
      [Unit]
      Description=Catalyst Worker Agent
      After=network.target nebula.service ollama.service
      Wants=network-online.target
      Requires=nebula.service

      [Service]
      Type=simple
      EnvironmentFile=-/etc/worker-agent/env
      ExecStart=/usr/local/bin/worker-agent
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
