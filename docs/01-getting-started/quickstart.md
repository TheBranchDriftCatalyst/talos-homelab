# Quick Start Guide

## TL;DR

```bash
# Install tools, generate configs, provision cluster, access services
brew install talosctl kubectl go-task/tap/go-task
export TALOS_NODE=192.168.1.54
task talos:gen-config   # required first - provision.sh does NOT generate configs
task talos:provision
./scripts/kube-dashboard-token.sh && task k8s:dashboard-proxy
```

> This quickstart covers **bringing a node up**. For the full cluster rebuild
> path (Talos -> kubelet patches -> Flux -> 1Password Connect), follow
> [docs/05-runbooks/cluster-bootstrap.md](../05-runbooks/cluster-bootstrap.md),
> which is the authoritative recovery runbook.

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

### Step 0: Generate machine configs (required)

`provision.sh` does **not** generate configs - it aborts if
`configs/controlplane.yaml` is missing. Generate them first:

```bash
task talos:gen-config
```

### Option 1: Using the provision script

```bash
./scripts/provision.sh
```

### Option 2: Using Task

```bash
task talos:provision
```

The script will:

- Check the node is reachable at `$TALOS_NODE`
- Apply `configs/controlplane.yaml` (insecure mode, first boot) and wait ~90s for reboot
- Point `configs/talosconfig` at the node
- Bootstrap etcd
- Download kubeconfig to `.output/kubeconfig`
- Remove the control-plane taint (single-node bring-up; see note below)
- Run a health check and list Talos services
- Merge kubeconfig into `~/.kube/config` (set `AUTO_MERGE_KUBECONFIG=false` to skip)

> **Note on the taint**: the taint removal targets the *first* node and exists so
> a brand-new single-node cluster can schedule workloads. The current 5-node
> cluster deliberately keeps `node-role.kubernetes.io/control-plane:NoSchedule`
> on talos00 - workloads run on talos01/02/03/06.

<!-- -->

> **The node will stay `NotReady` until a CNI is installed.** The machine config
> sets `cluster.network.cni.name: none`; Cilium is delivered by Flux
> (`infrastructure/base/cilium/`). Bootstrap Flux next - see
> [docs/04-deployment/flux-setup.md](../04-deployment/flux-setup.md).

## Access Kubernetes Dashboard

```bash
# Terminal 1: Get the token
./scripts/kube-dashboard-token.sh

# Terminal 2: Start the proxy
task k8s:dashboard-proxy

# Browser: Open this URL
http://localhost:8001/api/v1/namespaces/kubernetes-dashboard/services/https:kubernetes-dashboard:/proxy/
```

> **Broken task**: `task k8s:dashboard-token` invokes `./scripts/dashboard-token.sh`,
> which does not exist in the repo. The working script is
> `scripts/kube-dashboard-token.sh` (it also prints tokens for the other cluster UIs).

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

Straight out of `provision.sh` you get Talos + a bootstrapped control plane +
CoreDNS. Everything else (CNI, ingress, monitoring, dashboards) arrives via Flux.

Current cluster (verify with `kubectl get nodes -o wide`):

- **Talos v1.13.2** - Immutable Linux OS
- **Kubernetes v1.34.10** - Container orchestration
- **Cilium v1.20.0** - CNI networking (Helm chart via Flux; Talos ships `cni: none`)
- **CoreDNS** - DNS resolution
- **Kubernetes Dashboard** - Web UI (deployed separately, *not* by `provision.sh`)
- **5 nodes** - talos00 (control plane, tainted `NoSchedule`) + workers talos01,
  talos02-gpu, talos03, talos06

## Project Structure

```
configs/          # Talos machine configs (sensitive files gitignored)
infrastructure/   # Platform manifests (Flux-managed)
applications/     # Application manifests
clusters/         # Flux cluster entrypoints (catalyst-cluster/)
bootstrap/        # Flux bootstrap
scripts/          # Helper scripts
.output/          # Generated files (gitignored)
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
- Get fresh token: `./scripts/kube-dashboard-token.sh` (the `task k8s:dashboard-token` shortcut is currently broken)

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
# Check node taints. Expected today: talos00 carries
# node-role.kubernetes.io/control-plane:NoSchedule, workers show <none>.
# A Pending pod on a 5-node cluster is normally resources/nodeSelector, not the taint.
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

1. **Full rebuild path**: See [docs/05-runbooks/cluster-bootstrap.md](../05-runbooks/cluster-bootstrap.md) (authoritative)
2. **Deploy Infrastructure**: See [docs/04-deployment/flux-setup.md](../04-deployment/flux-setup.md)
3. **Configure GitOps**: See [docs/02-architecture/gitops-responsibilities.md](../02-architecture/gitops-responsibilities.md)
4. **Add Monitoring**: the monitoring stack is Flux-managed — see
   `clusters/catalyst-cluster/monitoring.yaml`; force a sync with `task infra:flux-reconcile`
5. **Explore Docs**: See [docs/INDEX.md](../INDEX.md) and [README.md](../../README.md)

## Related Issues

<!-- Beads tracking for this doc -->

- CILIUM-7i0 (closed/pruned): original pass to fix this document's commands
