# Getting Started

## Overview

This section provides essential guides for getting started with the Talos Kubernetes homelab. Whether you're setting up the cluster for the first time or testing changes locally, these guides will help you get up and running quickly.

## Quick Navigation

| Topic | Description | When to Read |
|-------|-------------|--------------|
| [quickstart.md](quickstart.md) | Fast-track cluster setup and common commands | First time setup, daily operations reference |
| [local-testing.md](local-testing.md) | Running Talos cluster locally with Docker for testing | Testing infrastructure changes before deploying to hardware |

## Key Concepts

- **Talos Linux** is an immutable Kubernetes OS configured via machine configs, not SSH
- **Control Plane IP** defaults to `192.168.1.54` (configurable via `TALOS_NODE` env var)
- **Multi-node cluster** supports control plane (talos00) + worker nodes (talos01, etc.)
- **Kubernetes Dashboard** is auto-deployed during provisioning for cluster visibility
- **Local testing** uses Docker-based clusters to validate changes before production deployment

## Common Tasks

### Fresh Cluster Setup
- [Provision using Task](quickstart.md#fresh-cluster-setup) - `task provision` or `./scripts/provision.sh`
- [Access Kubernetes Dashboard](quickstart.md#access-kubernetes-dashboard) - Get token and start proxy

### Daily Operations
- [Check cluster health](quickstart.md#common-commands) - `task health`
- [View all pods](quickstart.md#common-commands) - `task get-pods`
- [Access Talos dashboard](quickstart.md#common-commands) - `task dashboard`

### Testing Infrastructure Changes
- [Create local test cluster](local-testing.md#quick-start) - `./scripts/provision-local.sh`
- [Deploy test applications](local-testing.md#deploy-test-applications) - Test arr stack locally
- [Validate manifests](local-testing.md#testing-gitops-manifests) - Dry-run before production

### Troubleshooting
- [Dashboard access issues](quickstart.md#troubleshooting) - Proxy and token troubleshooting
- [Pod scheduling issues](quickstart.md#troubleshooting) - Check taints and node status
- [Local cluster issues](local-testing.md#troubleshooting) - Docker and cluster creation problems

---

## Related Issues
<!-- Beads tracking for this section -->
- [CILIUM-kkw] - Initial creation of section README
