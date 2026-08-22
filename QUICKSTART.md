# Quick Start Guide

## Prerequisites

```bash
# Install the pinned toolchain (Brewfile at repo root)
brew bundle

# ...or just the minimum needed to provision
brew install siderolabs/tap/talosctl kubectl go-task

# Set your node IP (control plane; also the Taskfile default)
export TALOS_NODE=192.168.1.54
```

## Fresh Cluster Setup

Generate the machine configs first — `provision.sh` expects
`configs/controlplane.yaml` to already exist and aborts if it does not:

```bash
task talos:gen-config
```

### Option 1: Using the provision script

```bash
./scripts/provision.sh
```

### Option 2: Using Task

```bash
task provision
```

That's it! The script will:

- Check the node is reachable
- Apply configuration to the node (insecure mode, first boot)
- Wait for the reboot and point `configs/talosconfig` at the node
- Bootstrap etcd
- Download kubeconfig to `.output/kubeconfig`
- Remove the control-plane taint (single-node bootstrap)
- Run a health check and list Talos services

> ⚠️ The final auto-merge step calls `scripts/kubeconfig-merge.sh`, which does not
> exist in this repo — the script will exit non-zero there. Run with
> `AUTO_MERGE_KUBECONFIG=false ./scripts/provision.sh` and then `task kubeconfig-merge`.

## Access Kubernetes Dashboard

> Note: the Kubernetes Dashboard in the `kubernetes-dashboard` namespace was
> deployed by hand during the original bootstrap and is **not** managed by Flux
> or the provision script. The maintained cluster UI is Headlamp at
> <https://headlamp.priv.talos00>.

```bash
# Terminal 1: Get the token
./scripts/kube-dashboard-token.sh
# (`task k8s:dashboard-token` is currently broken — it calls a missing scripts/dashboard-token.sh)

# Terminal 2: Start the proxy
task k8s:dashboard-proxy

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
task talos:service-logs -- SERVICE=kubelet
```

## What's Deployed

The running cluster:

- **Talos v1.13.2** - Immutable Linux OS
- **Kubernetes v1.34.10** - Container orchestration
- **Cilium** - CNI networking (a bare `task talos:gen-config` bootstrap comes up on
  Talos' default Flannel; Cilium is installed afterwards via Flux)
- **CoreDNS** - DNS resolution
- **Kubernetes Dashboard** - Web UI (legacy manual deploy, see note above)
- **5 nodes** - Control plane `talos00` (192.168.1.54) + workers `talos01`,
  `talos02-gpu`, `talos03`, `talos06`

## Project Structure

```
configs/          # Talos configs (gitignored - sensitive)
infrastructure/   # Platform manifests (Flux-managed)
applications/     # Application manifests
clusters/         # Flux cluster entrypoints (catalyst-cluster, aws-k3s)
bootstrap/        # Flux bootstrap
scripts/          # Helper scripts
docs/             # Documentation
.output/          # Generated files (gitignored)
```

## Next Steps

1. **Merge kubeconfig so plain `kubectl` works**:

   ```bash
   task kubeconfig-merge
   ```

2. **Deploy your first app**:

   ```bash
   kubectl --kubeconfig ./.output/kubeconfig run nginx --image=nginx
   ```

3. **Check deployment**:

   ```bash
   task get-pods
   ```

4. **Explore Talos**:

   ```bash
   task dashboard  # Interactive node dashboard
   ```

## Troubleshooting

**Dashboard not accessible?**

- Make sure `kubectl proxy` is running on your LOCAL machine
- The URL is `localhost:8001`, not the node IP
- Token can be retrieved with `./scripts/kube-dashboard-token.sh`

**Can't schedule pods?**

- Check taints: `kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints`
- On the current multi-node cluster `talos00` intentionally keeps the
  `node-role.kubernetes.io/control-plane:NoSchedule` taint; the four workers show
  `<none>`. A workload that must land on the control plane needs a toleration.

**Need to reset?**

```bash
task talos:reset  # WARNING: Destructive!
```

## Documentation

See [README.md](README.md) for complete documentation.

---

## Related Issues

<!-- Beads tracking for this doc -->
