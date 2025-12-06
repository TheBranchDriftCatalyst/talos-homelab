# Quick Start Guide

## TL;DR

```bash
# Install tools, provision cluster, access services
brew install talosctl kubectl go-task/tap/go-task
export TALOS_NODE=192.168.1.54
task talos:provision
task k8s:dashboard-token && task k8s:dashboard-proxy
```

## Prerequisites

### Required Tools

Install via Homebrew (macOS/Linux):

```bash
brew install talosctl kubectl go-task/tap/go-task
```

Or manually:

- **talosctl** - Talos CLI ([installation guide](https://www.talos.dev/latest/introduction/getting-started/))
- **kubectl** - Kubernetes CLI ([installation guide](https://kubernetes.io/docs/tasks/tools/))
- **go-task** - Task runner ([installation guide](https://taskfile.dev/installation/))

### Environment Variables

```bash
# Set your control plane node IP
export TALOS_NODE=192.168.1.54

# Optional: Add to ~/.zshrc or ~/.bashrc for persistence
echo 'export TALOS_NODE=192.168.1.54' >> ~/.zshrc
```

### Network Requirements

- Node must be reachable at `$TALOS_NODE`
- Ports 50000 (Talos API) and 6443 (K8s API) must be accessible
- For multi-node: All nodes must be on the same network

## Fresh Cluster Setup

### Option 1: Using the provision script

```bash
./scripts/provision.sh
```

### Option 2: Using Task

```bash
task talos:provision
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
task k8s:dashboard-token

# Terminal 2: Start the proxy
task k8s:dashboard-proxy

# Browser: Open this URL
http://localhost:8001/api/v1/namespaces/kubernetes-dashboard/services/https:kubernetes-dashboard:/proxy/
```

## Common Commands

```bash
# Check cluster health
task talos:health

# View nodes
task k8s:get-nodes

# View all pods
task k8s:get-pods

# Open Talos dashboard
task talos:dashboard

# Get service logs
task talos:service-logs -- SERVICE=kubelet
```

## What's Deployed

After provisioning, your cluster will have:

- **Talos v1.11.1** - Immutable Linux OS
- **Kubernetes v1.34.0** - Container orchestration
- **Flannel** - CNI networking
- **CoreDNS** - DNS resolution
- **Kubernetes Dashboard** - Web UI
- **Multi-node** - Control plane (talos00) + workers (talos01, etc.)

## Project Structure

```
configs/        # Talos configs (gitignored - sensitive)
kubernetes/     # K8s manifests
scripts/        # Helper scripts
.output/        # Generated files (gitignored)
```

## Quick Test

Deploy a test application to verify everything works:

1. **Deploy test app**:

   ```bash
   kubectl --kubeconfig ./.output/kubeconfig run nginx --image=nginx
   ```

2. **Check deployment**:

   ```bash
   task k8s:get-pods
   ```

3. **Explore Talos**:

   ```bash
   task talos:dashboard  # Interactive node dashboard
   ```

## Troubleshooting

### Dashboard not accessible?

**Symptoms**: Can't access Kubernetes Dashboard at localhost:8001

**Solutions**:
- Ensure `kubectl proxy` is running: `task k8s:dashboard-proxy`
- Verify the proxy is listening on localhost:8001
- URL must be `localhost:8001`, NOT the node IP
- Get fresh token: `task k8s:dashboard-token`

### Can't connect to Talos API?

**Symptoms**: `task talos:health` fails with connection errors

**Solutions**:
```bash
# Verify TALOS_NODE is set
echo $TALOS_NODE

# Ping the node
task talos:ping

# Check if Talos API is responding
task talos:check-api

# Verify network connectivity
ping $TALOS_NODE
```

### Pods won't schedule?

**Symptoms**: Pods stuck in `Pending` state

**Solutions**:
```bash
# Check node taints (should show <none> for control plane scheduling)
kubectl --kubeconfig ./.output/kubeconfig get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints

# Check node status
task k8s:get-nodes

# View pod events
task k8s:events -- NAMESPACE=default

# Describe problematic pod
task k8s:describe-pod -- POD=<pod-name> NAMESPACE=default
```

### Need to reset cluster?

**WARNING**: This is destructive and wipes all data!

```bash
# Complete cluster reset
task talos:reset

# Re-provision after reset
task talos:provision
```

## Next Steps

After your cluster is running:

1. **Deploy Infrastructure**: See [docs/04-deployment/flux-setup.md](../04-deployment/flux-setup.md)
2. **Configure GitOps**: See [docs/02-architecture/gitops-responsibilities.md](../02-architecture/gitops-responsibilities.md)
3. **Add Monitoring**: Run `task infra:deploy-stack`
4. **Explore Docs**: See [README.md](../../README.md) for complete documentation

## Related Issues

- CILIUM-7i0: Fix docs/01-getting-started/quickstart.md commands (this document)
- See [docs/06-project-management/implementation-tracker.md](../06-project-management/implementation-tracker.md) for more
