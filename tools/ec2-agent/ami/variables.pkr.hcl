# =============================================================================
# Common Variables for All AMIs
# =============================================================================

variable "aws_region" {
  type        = string
  default     = "us-west-2"
  description = "AWS region to build AMI in"
}

variable "source_ami_filter" {
  type        = string
  default     = "al2023-ami-*-kernel-*-x86_64"
  description = "Filter for source AMI (Amazon Linux 2023)"
}

variable "instance_type" {
  type        = string
  default     = "t3.medium"
  description = "Instance type for building AMI"
}

variable "ssh_username" {
  type        = string
  default     = "ec2-user"
  description = "SSH username for the AMI"
}

variable "ami_prefix" {
  type        = string
  default     = "catalyst-llm"
  description = "Prefix for AMI names"
}

variable "k3s_version" {
  type        = string
  default     = "v1.31.2+k3s1"
  description = "k3s version"
}

variable "cilium_version" {
  type        = string
  default     = "1.16.6"
  description = "Cilium CNI version"
}

variable "cilium_cli_version" {
  type        = string
  default     = "v0.16.22"
  description = "Cilium CLI version"
}

variable "nvidia_driver_version" {
  type        = string
  default     = "550"
  description = "NVIDIA driver major version"
}

variable "ollama_version" {
  type        = string
  default     = "latest"
  description = "Ollama version (or 'latest')"
}

# Tags applied to all AMIs
variable "common_tags" {
  type = map(string)
  default = {
    Project     = "catalyst-llm"
    Environment = "production"
    ManagedBy   = "packer"
  }
}
