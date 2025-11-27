# Talos Node Shutdown & Restart Procedure

This guide covers safely shutting down your Talos node for hardware maintenance and bringing it back online.

## Prerequisites

- `talosctl` configured and working
- `kubectl` access to the cluster
- Node IP exported: `export TALOS_NODE=192.168.1.54`

## Safe Shutdown Procedure

### Step 1: Drain the Node (Optional)

For single-node clusters, draining won't move workloads, but it ensures graceful pod termination:

```bash
kubectl drain talos00 --ignore-daemonsets --delete-emptydir-data
```

**Note:** You can skip this step on single-node clusters since there's nowhere else for pods to go.

### Step 2: Shutdown via Talos

Use `talosctl` to safely shutdown the node:

```bash
export TALOS_NODE=192.168.1.54

# Graceful shutdown (recommended)
talosctl shutdown

# OR force shutdown if needed
talosctl shutdown --force
```

**What happens:**

- All Kubernetes services stop gracefully
- Kubelet terminates
- Filesystems unmount cleanly
- Machine powers off

### Step 3: Perform Hardware Changes

With the system powered off, perform your hardware maintenance:

- RAM upgrades
- Disk additions/replacements
- Network card changes
- etc.

## Startup Procedure

### Step 4: Power On & Wait for Boot

1. **Power on the physical machine** via BIOS/UEFI
2. **Wait for Talos to boot** (typically 30-60 seconds)
3. **Verify Talos API responds:**

```bash
export TALOS_NODE=192.168.1.54

# Check Talos version (verifies API is up)
talosctl version

# Check system health
talosctl health --wait-timeout=5m
```

### Step 5: Verify Cluster Health

Check that Kubernetes services are starting:

```bash
# Check node status
kubectl get nodes

# Verify Talos services
talosctl services

# Check all pods are starting
kubectl get pods -A

# Verify etcd cluster
talosctl etcd status
```

### Step 6: Uncordon Node (If Drained)

If you drained the node in Step 1, make it schedulable again:

```bash
kubectl uncordon talos00
```

## Quick Command Reference

### Complete Shutdown Sequence

```bash
export TALOS_NODE=192.168.1.54
kubectl drain talos00 --ignore-daemonsets --delete-emptydir-data  # Optional
talosctl shutdown
```

### After Hardware Changes and Power-On

```bash
export TALOS_NODE=192.168.1.54
talosctl health --wait-timeout=5m
kubectl get nodes
kubectl get pods -A
kubectl uncordon talos00  # If you drained
```

## Expected Behavior

After powering on the node:

1. **Talos boots** (30-60 seconds)
2. **Kubelet starts** automatically
3. **Control plane pods restart** (kube-apiserver, etcd, kube-controller-manager, kube-scheduler)
4. **All application pods restart** automatically
5. **Cluster fully operational** within 2-3 minutes

## Troubleshooting

### Cluster Not Coming Back

#### Check Talos Services

```bash
talosctl services
talosctl logs kubelet
talosctl dmesg | tail -50
```

#### Check etcd Health

```bash
talosctl etcd status
talosctl etcd members
```

#### Force Recovery (If Needed)

```bash
# Bootstrap etcd if it's stuck
talosctl bootstrap

# Restart kubelet service
talosctl service kubelet restart
```

#### Check API Server

```bash
kubectl get --raw /healthz
kubectl get componentstatuses
```

### Common Issues

**Issue:** Node shows `NotReady`

```bash
# Check kubelet logs
talosctl logs kubelet

# Restart kubelet if needed
talosctl service kubelet restart
```

**Issue:** etcd won't start

```bash
# Check etcd status
talosctl etcd status

# Re-bootstrap etcd (CAUTION: only for single-node clusters)
talosctl bootstrap
```

**Issue:** Pods stuck in `Pending` or `ContainerCreating`

```bash
# Check pod events
kubectl describe pod <pod-name> -n <namespace>

# Check if storage mounts are working
kubectl get pv
kubectl get pvc -A

# Verify NFS provisioner is running
kubectl get pods -n kube-system | grep nfs
```

## Alternative: Reboot Instead of Shutdown

If you only need a reboot (not full power-off for hardware changes):

```bash
talosctl reboot
```

This performs a clean reboot cycle automatically without manual power cycling.

## Important Notes

### Single-Node Cluster Considerations

- **Expect downtime** - All services will be unavailable during shutdown
- **No high availability** - Control plane is unavailable during maintenance
- **Plan maintenance windows** accordingly

### Data Persistence

- **Local-path storage (PostgreSQL)** - Data persists on disk, no data loss
- **NFS mounts** - Automatically reconnect when pods restart
- **Talos state** - Configuration persists in `/system/state` partition
- **Machine config backup** - Always kept in `configs/controlplane.yaml`

### Post-Restart Validation Checklist

- [ ] Node status is `Ready`
- [ ] All system pods running (kube-system namespace)
- [ ] etcd cluster healthy
- [ ] Monitoring stack operational (Prometheus, Grafana)
- [ ] Observability stack operational (Graylog, OpenSearch)
- [ ] Media stack operational (arr-stack, Plex, etc.)
- [ ] Ingress accessible (Traefik responding)

## Emergency Recovery

If the cluster fails to start after hardware changes:

### 1. Check BIOS/Boot Settings

- Verify boot device order
- Check secure boot settings
- Ensure network boot (PXE) is disabled if using local disk

### 2. Verify Talos Installation

```bash
# Check Talos version on boot
talosctl version

# Verify machine config applied
talosctl get machineconfig -o yaml
```

### 3. Re-apply Machine Config (If Needed)

```bash
talosctl apply-config --file configs/controlplane.yaml
```

### 4. Complete Cluster Reset (LAST RESORT)

If the cluster is completely broken and you have backups:

```bash
# Reset the node (DESTRUCTIVE)
talosctl reset --graceful=false --reboot

# Re-provision the cluster
./scripts/provision.sh
```

**WARNING:** This will destroy all data. Only use if you have backups of:

- etcd data
- Application data
- Configuration files

## Related Documentation

- [Talos Provisioning Steps](TALOS-PROVISIONING-STEPS.md) - Complete cluster setup
- [Quick Start Guide](../QUICKSTART.md) - Common operational commands
- [Dual GitOps Architecture](DUAL-GITOPS.md) - Understanding the deployment model
