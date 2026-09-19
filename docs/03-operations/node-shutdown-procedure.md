---
type: runbook
status: current
covers:
  - path:configs/talconfig.yaml
  - path:dev/Taskfile.talos.yaml
freshness: tracks-code
bluf: Drain, shut down through the Talos API rather than the power button, then verify etcd quorum before uncordoning — and never re-bootstrap a node that still has surviving peers.
---

# Talos Node Shutdown & Restart Procedure

How to take a single Talos node down for hardware maintenance and bring it back, without losing etcd.

## TL;DR

1. Drain the node so its workloads move elsewhere.
2. Shut it down through the Talos API (`task talos:shutdown`), never by holding the power button.
3. Do the hardware work.
4. Power on and wait for the Talos API to answer.
5. Verify node health and etcd membership.
6. Uncordon.

**The one rule that matters:** this cluster declares multiple control planes in `configs/talconfig.yaml`. Taking one down is routine; `talosctl bootstrap` on a node whose peers are still alive is not a repair, it is a second cluster. See [Troubleshooting](#troubleshooting).

## Prerequisites

- `talosctl` configured and working
- `kubectl` access to the cluster
- Node IP exported: `export TALOS_NODE=<node-ip>` (the control-plane addresses are declared in `configs/talconfig.yaml`)
- You know whether the node you are taking down is a control plane. `kubectl get nodes -l node-role.kubernetes.io/control-plane` answers it.

## Safe Shutdown Procedure

### Step 1: Drain the Node

Draining migrates workloads to other nodes and lets pods terminate gracefully:

```bash
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data
```

**Note:** drain cannot help volumes that are pinned to this node. `local-path` PVs are `WaitForFirstConsumer` and live on the node's disk — their pods will go `Pending` rather than migrate, and that is expected. A graceful shutdown preserves the data; only a `reset` destroys it.

### Step 2: Shutdown via Talos

```bash
task talos:shutdown           # targets TALOS_NODE, with a confirmation prompt
```

Equivalent explicit form — note that the node is named explicitly, because `talosctl` with no `--nodes` uses whatever the talosconfig defaults to and that is not necessarily the node you meant:

```bash
talosctl --nodes <node-ip> shutdown
```

To take the _whole_ cluster down (workers in parallel, control planes last) use `task talos:shutdown-cluster`, which runs `scripts/shutdown-cluster.sh` — it sequences the nodes so etcd loses quorum last.

**What happens:**

- All Kubernetes services stop gracefully
- Kubelet terminates
- Filesystems unmount cleanly
- Machine powers off

### Step 3: Perform Hardware Changes

With the system powered off, perform your hardware maintenance: RAM, disks, NICs, and so on.

## Startup Procedure

### Step 4: Power On & Wait for Boot

1. **Power on the physical machine.**
2. **Wait for Talos to boot** (tens of seconds on this hardware).
3. **Verify the Talos API responds:**

```bash
export TALOS_NODE=<node-ip>
talosctl version                # API is up
task talos:health               # cluster-level health check
```

### Step 5: Verify Cluster Health

```bash
kubectl get nodes
task talos:services             # Talos services on the node
kubectl get pods -A
task talos:etcd-status
task talos:etcd-members         # on a control plane: confirm the member rejoined
```

### Step 6: Uncordon Node

```bash
kubectl uncordon <node>
```

## Quick Command Reference

```bash
# Down
export TALOS_NODE=<node-ip>
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data
task talos:shutdown

# Up
export TALOS_NODE=<node-ip>
task talos:health
kubectl get nodes
task talos:etcd-members
kubectl uncordon <node>
```

## Expected Behavior

After powering on the node:

1. **Talos boots.**
2. **Kubelet starts** automatically.
3. On a control plane, the **static pods restart** (kube-apiserver, etcd, kube-controller-manager, kube-scheduler) and the etcd member rejoins.
4. **Application pods restart** automatically.
5. **Node is fully operational** within a few minutes.

## Troubleshooting

### Node not coming back

```bash
task talos:services
task talos:service-logs -- SERVICE=kubelet
task talos:dmesg
```

### etcd

```bash
task talos:etcd-status
task talos:etcd-members
```

> ⚠️ **Do not run `talosctl bootstrap` to "fix" etcd on this cluster.**
> `bootstrap` initialises a _new_ etcd cluster. Multiple control planes are declared in
> `configs/talconfig.yaml`, so a surviving peer almost always exists, and bootstrapping
> against it produces a split brain that is far worse than the outage you started with.
> A single lost member is repaired by removing and re-adding it — see the Talos etcd
> maintenance docs. `bootstrap` is correct only during first provisioning
> ([cluster-bootstrap.md](../05-runbooks/cluster-bootstrap.md)) or when every control plane
> is gone and you are restoring from a snapshot
> ([etcd-backup-restore.md](etcd-backup-restore.md)).

### API server

```bash
kubectl get --raw /healthz
```

### Common Issues

**Issue:** Node shows `NotReady`

```bash
task talos:service-logs -- SERVICE=kubelet
talosctl --nodes <node-ip> service kubelet restart
```

**Issue:** Pods stuck in `Pending` or `ContainerCreating`

```bash
kubectl describe pod <pod-name> -n <namespace>
kubectl get pv
kubectl get pvc -A

# NFS provisioner runs in kube-system (infrastructure/base/storage/nfs-provisioner/)
kubectl get pods -n kube-system | grep nfs
```

If the pod's PVC is on `local-path`, check it is scheduled to the node that holds the volume — `local-path` PVs cannot move.

## Alternative: Reboot Instead of Shutdown

If you only need a reboot (not a power-off for hardware changes):

```bash
task talos:reboot
```

This performs a clean reboot cycle without manual power cycling.

## Important Notes

### Control plane vs. worker

- **Worker** — workloads migrate automatically; nothing cluster-wide is at risk.
- **Control plane** — you are spending one unit of etcd fault tolerance for the duration. Take one down at a time, confirm the member rejoined with `task talos:etcd-members` before touching the next, and never have two down simultaneously.

### Data Persistence

- **`local-path` volumes** — persist on the node's disk across a graceful shutdown. They do **not** survive a `talosctl reset`, which wipes EPHEMERAL.
- **NFS mounts** — reconnect automatically when pods restart.
- **Talos machine state** — persists in the `STATE` partition; the node comes back with the config it had.
- **Machine config source** — declared in `configs/talconfig.yaml` (git-tracked) and regenerated into `configs/clusterconfig/` by `task talos:gen-config`. The CA and bootstrap tokens live in `configs/talsecret.yaml`, which is gitignored and backed up in 1Password — see [talsecret-1password-backup.md](../05-runbooks/talsecret-1password-backup.md).

### Post-Restart Validation Checklist

- [ ] Node status is `Ready`
- [ ] etcd member count back to the declared control-plane count
- [ ] All `kube-system` pods running
- [ ] Flux reconciling (`flux get kustomizations`)
- [ ] Ingress responding (Traefik)

## Emergency Recovery

If the node fails to start after hardware changes:

### 1. Check BIOS/Boot Settings

- Verify boot device order
- Check secure boot settings
- Ensure network boot (PXE) is disabled if using local disk

### 2. Verify Talos Installation

```bash
talosctl --nodes <node-ip> version
talosctl --nodes <node-ip> get machineconfig -o yaml
```

### 3. Re-apply Machine Config (If Needed)

Check what it would do first — this is read-only and safe at any time:

```bash
task talos:verify-dry-run
```

Then, if the diff is what you expect:

```bash
task talos:gen-config
task talos:apply-config NODE=<hostname>
```

`NODE=` takes a **hostname**, not an IP, and is required — each node has its own install disk, schematic and patch set, so the generated configs are not interchangeable. Note there is no `--` before `NODE=`; go-task only binds variables in the bare form.

### 4. Complete Cluster Reset (LAST RESORT)

This destroys the node's data. Only do it if you have verified backups, and prefer the
full rebuild path in [cluster-bootstrap.md](../05-runbooks/cluster-bootstrap.md) over
improvising:

```bash
talosctl reset --graceful=false --reboot --nodes <node-ip>
```

Before you do: `local-path` PVs on that node are gone afterwards, and Velero does **not**
cover them — see the standing gotcha in [docs/05-runbooks](../05-runbooks/README.md).

## Related Documentation

- [Cluster Bootstrap Runbook](../05-runbooks/cluster-bootstrap.md) — bare metal to reconciling GitOps
- [etcd Backup & Restore](etcd-backup-restore.md) — recovering the control plane from a snapshot
- [Quick Start Guide](../01-getting-started/quickstart.md) — common operational commands
- [Dual GitOps Architecture](../02-architecture/dual-gitops.md) — understanding the deployment model

---

## Related Issues

<!-- Beads tracking for this doc -->
