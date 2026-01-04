# =============================================================================
# Base AMI - Common Foundation for All Node Types
# =============================================================================
# Includes: Amazon Linux 2023, Nebula, worker-agent, systemd services

source "amazon-ebs" "base" {
  ami_name        = "${var.ami_prefix}-base-{{timestamp}}"
  ami_description = "Base AMI with Nebula and worker-agent for Catalyst fleet"
  instance_type   = var.instance_type
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
    volume_size           = 30
    volume_type           = "gp3"
    delete_on_termination = true
  }

  tags = merge(var.common_tags, {
    Name      = "${var.ami_prefix}-base"
    AMIType   = "base"
    NebulaVer = var.nebula_version
    BuildTime = "{{timestamp}}"
  })

  run_tags = merge(var.common_tags, {
    Name = "packer-builder-base"
  })
}

build {
  name    = "base"
  sources = ["source.amazon-ebs.base"]

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
      "nebula --version",
    ]
  }

  # Install worker-agent
  provisioner "shell" {
    inline = [
      "set -ex",
      "sudo mv /tmp/worker-agent /usr/local/bin/worker-agent",
      "sudo chmod +x /usr/local/bin/worker-agent",
      "/usr/local/bin/worker-agent --help || true",
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
      After=network.target nebula.service
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
    output     = "manifest-base.json"
    strip_path = true
  }
}
