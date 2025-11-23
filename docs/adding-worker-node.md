# Adding a New Talos Worker Node to Your Cluster

Based on your existing single-node cluster setup, this guide walks you through adding a more powerful worker node.

## Prerequisites

**What you need:**
- New physical machine/VM with IP address (let's call it `NEW_NODE_IP`)
- Talos ISO or metal image installed on the new node
- The existing `worker.yaml` config from your talos-homelab directory

## Current Cluster Status

- **Current Node**: talos00 (192.168.1.54) - Single control-plane node
- **Kubernetes**: v1.34.0
- **Talos**: v1.11.1
- **Context**: homelab-single

## Step-by-Step Process

### 1. Prepare Worker Configuration

Your worker config already exists at:
```
configs/worker.yaml
```

This config contains the shared cluster secrets needed to join the cluster:
- CA certificate (shared cluster identity)
- Join token: `<EXAMPLE_TOKEN>` (will be generated during config generation)
- Kubernetes version: v1.34.0

### 2. Apply Configuration to New Node (First Boot)

```bash
# Set your new node IP
export NEW_NODE_IP=192.168.1.XXX  # Replace with actual IP

# Apply worker config to the new node (insecure mode for first-time setup)
talosctl apply-config \
  --insecure \
  --nodes ${NEW_NODE_IP} \
  --file configs/worker.yaml
```

**What happens:**
- Talos installs the configuration on the new node
- Node automatically joins the cluster using the shared token
- Node downloads Kubernetes components
- Takes ~2-5 minutes to become Ready

### 3. Wait for Node to Join

```bash
# Watch for the new node to appear
kubectl get nodes -w

# Check node status
kubectl get nodes -o wide
```

You should see your new node appear as a worker with `Ready` status.

### 4. Verify Node Health

```bash
# Check Talos services on the new node
talosctl --nodes ${NEW_NODE_IP} services

# Check Kubernetes components
kubectl get pods -n kube-system -o wide | grep ${NEW_NODE_IP}

# Full health check
talosctl --nodes ${NEW_NODE_IP} health --wait-timeout=10s
```

### 5. Label the Worker Node (Optional but Recommended)

```bash
# Get the node name first
kubectl get nodes

# Add labels for workload targeting
kubectl label node <new-node-name> \
  node-role.kubernetes.io/worker=worker \
  workload-type=compute-intensive

# Add taints if you want to dedicate it to specific workloads
kubectl taint node <new-node-name> \
  workload=high-performance:NoSchedule
```

## Node Configuration Customization (Optional)

If you want to customize the worker config for your more powerful node:

### Create a Customized Worker Config

```bash
# Copy the existing worker config
cp configs/worker.yaml configs/worker-powerful.yaml

# Edit the new config to add:
# - More CPU/memory allocations
# - GPU support (if applicable)
# - Custom kubelet flags
# - Storage configuration
```

### Example Modifications for a Powerful Node

Add these sections to `worker-powerful.yaml`:

```yaml
# Under machine.kubelet:
kubelet:
  image: ghcr.io/siderolabs/kubelet:v1.34.0
  extraArgs:
    max-pods: "250"  # More pods for powerful node
    kube-reserved: cpu=2,memory=4Gi  # Reserve more for system

  # For GPU nodes, add:
  extraMounts:
    - destination: /dev/nvidia0
      type: bind
      source: /dev/nvidia0
      options:
        - bind
        - rshared
        - rw

# Under machine:
sysctls:
  net.core.somaxconn: "65535"  # For high-performance networking
```

## Dual GitOps Integration

Once your worker node is running, it automatically inherits your dual GitOps setup:

### Infrastructure (Bootstrap Pattern)
Your worker node automatically gets:
- ✅ Traefik ingress (DaemonSet runs on all nodes)
- ✅ Monitoring agents (Prometheus node exporter)
- ✅ CNI networking (Flannel)
- ✅ Local-path provisioner

No additional infrastructure deployment needed!

### Applications (ArgoCD Pattern)
ArgoCD applications will automatically schedule on the new node based on:
- Resource availability
- Node selectors
- Taints/tolerations
- Pod affinity rules

### Targeting Specific Workloads to the Powerful Node

#### Example: Move Tdarr to the New Node

```bash
# 1. Add labels to identify the powerful node
kubectl label node <new-node-name> hardware=high-performance

# 2. Update tdarr deployment to target it
kubectl patch deployment tdarr -n media-dev --type='json' -p='[
  {
    "op": "add",
    "path": "/spec/template/spec/nodeSelector",
    "value": {"hardware": "high-performance"}
  }
]'

# 3. For permanent changes, update the manifest in your repo:
# applications/arr-stack/base/tdarr/deployment.yaml
```

Add to the deployment YAML:

```yaml
spec:
  template:
    spec:
      nodeSelector:
        hardware: high-performance
```

Then commit and deploy:

```bash
git add applications/arr-stack/base/tdarr/deployment.yaml
git commit -m "feat: Target tdarr to high-performance node"
./scripts/deploy-tdarr.sh
```

## Managing Control-Plane Scheduling

Since you're adding a dedicated worker, consider your control-plane scheduling strategy:

### Option A: Keep Control-Plane Schedulable (Current Setup)
```bash
# Remove taint (if present) to allow scheduling on control-plane
kubectl taint nodes talos00 node-role.kubernetes.io/control-plane:NoSchedule-
```

### Option B: Dedicate Control-Plane to System Workloads Only
```bash
# Add taint to prevent user workloads on control-plane
kubectl taint nodes talos00 \
  node-role.kubernetes.io/control-plane:NoSchedule

# System pods (kube-system, argocd, traefik) tolerate this automatically
```

## Resource Quota Considerations

With a new powerful node, you may want to adjust namespace quotas:

```bash
# Check current quotas
kubectl describe resourcequota -n media-dev

# Example: Increase media-dev quota for the new capacity
kubectl patch resourcequota media-dev-quota -n media-dev --type='json' -p='[
  {"op": "replace", "path": "/spec/hard/limits.cpu", "value": "32"},
  {"op": "replace", "path": "/spec/hard/limits.memory", "value": "64Gi"}
]'
```

## Troubleshooting

### Node Not Appearing

```bash
# Check if Talos is running on new node
talosctl --nodes ${NEW_NODE_IP} version

# Check Talos logs
talosctl --nodes ${NEW_NODE_IP} logs kubelet

# Check if node can reach control-plane
talosctl --nodes ${NEW_NODE_IP} get members
```

### Node Stuck in NotReady

```bash
# Check CNI (Flannel) pods
kubectl get pods -n kube-system -l app=flannel -o wide

# Describe the node to see events
kubectl describe node <new-node-name>

# Check kubelet logs on the new node
talosctl --nodes ${NEW_NODE_IP} logs kubelet
```

### Permission Denied

```bash
# Make sure you're using the correct talosconfig
export TALOSCONFIG=./configs/talosconfig

# Or add to your ~/.bashrc:
echo 'export TALOSCONFIG=/Users/panda/catalyst-devspace/workspace/.scratch/talos-homelab/configs/talosconfig' >> ~/.bashrc
```

### Token or Certificate Errors

If you see errors about invalid tokens or certificates, regenerate the worker config:

```bash
# Backup old config
cp configs/worker.yaml configs/worker.yaml.bak

# Regenerate from existing cluster secrets
talosctl --nodes 192.168.1.54 gen config \
  homelab-single https://192.168.1.54:6443 \
  --output-dir ./configs \
  --with-secrets secrets.yaml

# Apply new worker config to node
talosctl apply-config --insecure \
  --nodes ${NEW_NODE_IP} \
  --file configs/worker.yaml
```

## Quick Reference Commands

```bash
# Apply worker config (first time)
talosctl apply-config --insecure \
  --nodes <NEW_IP> \
  --file configs/worker.yaml

# Watch nodes join
kubectl get nodes -w

# Check node health
talosctl --nodes <NEW_IP> health

# Get detailed node info
kubectl get node <node-name> -o yaml

# Check node resources
kubectl top node <node-name>

# Drain node (for maintenance)
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data

# Uncordon node (resume scheduling)
kubectl uncordon <node-name>

# Remove node from cluster
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data --force
kubectl delete node <node-name>
talosctl --nodes <NEW_IP> reset
```

## Task Automation (Optional)

Add to `Taskfile.yaml`:

```yaml
  add-worker:
    desc: Add a new worker node to the cluster
    cmds:
      - |
        echo "Enter new node IP address:"
        read NODE_IP
        echo "Applying worker config to ${NODE_IP}..."
        talosctl apply-config --insecure \
          --nodes ${NODE_IP} \
          --file {{.WORKER_CONFIG}}
        echo "Waiting for node to join..."
        sleep 60
        kubectl get nodes -o wide
    vars:
      WORKER_CONFIG: './configs/worker.yaml'

  worker-health:
    desc: Check worker node health (use -- NODE=<ip>)
    cmds:
      - talosctl --nodes {{.NODE}} health --wait-timeout=10s
      - kubectl get node -o wide | grep {{.NODE}}
    vars:
      NODE: '{{.NODE | default "192.168.1.55"}}'
```

## Implementation Checklist

- [ ] Install Talos on new physical machine
- [ ] Verify new machine has network connectivity to existing cluster
- [ ] Get IP address of new node: `__________________`
- [ ] Apply worker config: `talosctl apply-config --insecure --nodes <NEW_IP> --file configs/worker.yaml`
- [ ] Wait for node to appear: `kubectl get nodes -w`
- [ ] Verify node is Ready: `kubectl get nodes`
- [ ] Label node appropriately: `kubectl label node <name> workload-type=compute-intensive`
- [ ] Update tdarr to use new node (if desired)
- [ ] Update namespace resource quotas (if needed)
- [ ] Test workload scheduling on new node
- [ ] Monitor in ArgoCD: `http://argocd.talos00`
- [ ] Document new node in cluster inventory

## Next Steps

1. **Set up your new physical machine** with Talos
2. **Get the IP address** of the new node
3. **Apply the worker config** using the commands above
4. **Update workload deployments** to use the powerful node
5. **Monitor the node** in ArgoCD dashboard: `http://argocd.talos00`
6. **Update resource quotas** to take advantage of new capacity

## Related Documentation

- [Talos Linux Documentation](https://www.talos.dev/)
- [Dual GitOps Pattern](./DUAL-GITOPS.md)
- [Quickstart Guide](../QUICKSTART.md)
- [Cluster Audit Script](../scripts/cluster-audit.sh)

---

**Created**: 2025-11-20
**Cluster**: homelab-single
**Talos Version**: v1.11.1
**Kubernetes Version**: v1.34.0
