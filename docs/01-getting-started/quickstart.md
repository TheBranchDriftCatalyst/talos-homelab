# Quick Start Guide

## Prerequisites

```bash
# Install required tools
brew install talosctl kubectl go-task/tap/go-task

# Set your node IP
export TALOS_NODE=192.168.1.54
```

## Fresh Cluster Setup

### Option 1: Using the provision script

```bash
./scripts/provision.sh
```

### Option 2: Using Task

```bash
task provision
```

That's it! The script will:
- Generate Talos configs
- Apply configuration to the node
- Bootstrap the cluster
- Download kubeconfig
- Remove control-plane taint
- Auto-deploy Kubernetes Dashboard

## Access Kubernetes Dashboard

```bash
# Terminal 1: Get the token
task dashboard-token

# Terminal 2: Start the proxy
task dashboard-proxy

# Browser: Open this URL
http://localhost:8001/api/v1/namespaces/kubernetes-dashboard/services/https:kubernetes-dashboard:/proxy/
```

## Common Commands

```bash
# Check cluster health
task health

# View nodes
task get-nodes

# View all pods
task get-pods

# Open Talos dashboard
task dashboard

# Get service logs
task service-logs -- SERVICE=kubelet
```

## What's Deployed

After provisioning, your cluster will have:
- **Talos v1.11.1** - Immutable Linux OS
- **Kubernetes v1.34.0** - Container orchestration
- **Flannel** - CNI networking
- **CoreDNS** - DNS resolution
- **Kubernetes Dashboard** - Web UI
- **Single-node** - Control plane with scheduling enabled

## Project Structure

```
configs/        # Talos configs (gitignored - sensitive)
kubernetes/     # K8s manifests
scripts/        # Helper scripts
.output/        # Generated files (gitignored)
```

## Next Steps

1. **Deploy your first app**:
   ```bash
   kubectl --kubeconfig ./.output/kubeconfig run nginx --image=nginx
   ```

2. **Check deployment**:
   ```bash
   task get-pods
   ```

3. **Explore Talos**:
   ```bash
   task dashboard  # Interactive node dashboard
   ```

## Troubleshooting

**Dashboard not accessible?**
- Make sure `kubectl proxy` is running on your LOCAL machine
- The URL is `localhost:8001`, not the node IP
- Token can be retrieved with `task dashboard-token`

**Can't schedule pods?**
- Check taints: `kubectl --kubeconfig ./.output/kubeconfig get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints`
- Should show `<none>` for single-node setup

**Need to reset?**
```bash
task reset  # WARNING: Destructive!
```

## Documentation

See [README.md](README.md) for complete documentation.
