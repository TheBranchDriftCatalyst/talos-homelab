# =============================================================================
# Lighthouse AMI - k3s Server + Cilium
# =============================================================================
# Central coordination node for the hybrid cluster
# Provides: k3s server, Cilium CNI with ClusterMesh

source "amazon-ebs" "lighthouse" {
  ami_name        = "${var.ami_prefix}-lighthouse-{{timestamp}}"
  ami_description = "Lighthouse AMI with k3s server and Cilium"
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
    volume_size           = 40
    volume_type           = "gp3"
    delete_on_termination = true
  }

  tags = merge(var.common_tags, {
    Name      = "${var.ami_prefix}-lighthouse"
    AMIType   = "lighthouse"
    K3sVer    = var.k3s_version
    CiliumVer = var.cilium_version
    BuildTime = "{{timestamp}}"
  })

  run_tags = merge(var.common_tags, {
    Name = "packer-builder-lighthouse"
  })
}

build {
  name    = "lighthouse"
  sources = ["source.amazon-ebs.lighthouse"]

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
      # curl-minimal is pre-installed; skip curl to avoid conflict
      "sudo dnf install -y jq wget tar gzip unzip htop iotop vim tmux",
      "sudo dnf install -y amazon-cloudwatch-agent",
    ]
  }

  # Install k3s server (without default CNI - we'll use Cilium)
  provisioner "shell" {
    environment_vars = [
      "K3S_VERSION=${var.k3s_version}"
    ]
    inline = [
      "set -ex",
      "curl -sfL https://get.k3s.io | INSTALL_K3S_SKIP_ENABLE=true INSTALL_K3S_SKIP_START=true INSTALL_K3S_VERSION=$K3S_VERSION sh -",
      "sudo mkdir -p /etc/rancher/k3s",
      "sudo mkdir -p /var/lib/rancher/k3s",
      "k3s --version",
    ]
  }

  # Install kubectl and helm
  provisioner "shell" {
    inline = [
      "set -ex",
      "KUBECTL_VERSION=$(curl -L -s https://dl.k8s.io/release/stable.txt)",
      "curl -LO https://dl.k8s.io/release/$${KUBECTL_VERSION}/bin/linux/amd64/kubectl",
      "sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl",
      "rm kubectl",
      "curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash",
    ]
  }

  # Install Cilium CLI
  provisioner "shell" {
    environment_vars = [
      "CILIUM_CLI_VERSION=${var.cilium_cli_version}"
    ]
    inline = [
      "set -ex",
      "curl -L --fail --remote-name-all https://github.com/cilium/cilium-cli/releases/download/$CILIUM_CLI_VERSION/cilium-linux-amd64.tar.gz",
      "sudo tar xzvfC cilium-linux-amd64.tar.gz /usr/local/bin",
      "rm cilium-linux-amd64.tar.gz",
      "cilium version --client",
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

  # Install Nebula overlay network
  provisioner "shell" {
    environment_vars = [
      "NEBULA_VERSION=${var.nebula_version}"
    ]
    inline = [
      "set -ex",
      "echo 'Installing Nebula v$${NEBULA_VERSION}...'",
      "curl -fsSL https://github.com/slackhq/nebula/releases/download/v$${NEBULA_VERSION}/nebula-linux-amd64.tar.gz -o /tmp/nebula.tar.gz",
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
      Before=worker-agent.service k3s.service

      [Service]
      Type=simple
      ExecStart=/usr/local/bin/nebula -config /etc/nebula/config.yaml
      Restart=always
      RestartSec=5
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

  # Create systemd services
  provisioner "shell" {
    inline = [
      "set -ex",
      "sudo mkdir -p /etc/worker-agent",
      <<-EOF
      sudo tee /etc/systemd/system/worker-agent.service > /dev/null << 'UNIT'
      [Unit]
      Description=Catalyst Worker Agent
      After=network.target k3s.service
      Wants=network-online.target

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
    output     = "manifest-lighthouse.json"
    strip_path = true
  }
}
