# Control Plane Migration Guide

**Date**: 2025-12-04
**Status**: PLANNING
**Current Node**: talos00 (192.168.1.54)

## Overview

This document outlines the process for migrating the homelab Kubernetes cluster to a new control plane node. The current setup is a multi-node Talos Linux cluster (catalyst-cluster).

## Current Cluster State

### Node Information

| Property           | Value              |
| ------------------ | ------------------ |
| Node Name          | talos00            |
| IP Address         | 192.168.1.54       |
| Mesh IP            | 10.42.1.1          |
| Talos Version      | v1.11.1            |
| Kubernetes Version | v1.34.0            |
| Container Runtime  | containerd://2.1.4 |
| Cluster Age        | 23 days            |

### Workload Summary

- **27 namespaces** deployed
- **~50 persistent volumes** (mix of NFS and local-path)
- **Liqo peering** to AWS GPU cluster established
- **GitOps controllers**: Flux + ArgoCD

### Storage Classes

| Storage Class        | Type           | Usage                                     |
| -------------------- | -------------- | ----------------------------------------- |
| `local-path`         | Local SSD      | Prometheus, Grafana, OpenSearch, MongoDB  |
| `fatboy-nfs-appdata` | NFS (TrueNAS)  | App configs (Plex, Jellyfin, \*arr, etc.) |
| `synology-nfs`       | NFS (Synology) | Large media storage                       |
| `truenas-nfs`        | NFS (TrueNAS)  | Large media storage                       |

### Critical Components

1. **External Secrets Operator** - 1Password integration
2. **Flux** - Infrastructure GitOps
3. **ArgoCD** - Application GitOps
4. **Liqo** - Multi-cluster federation (AWS peering)
5. **Nebula** - Mesh VPN for AWS connectivity
6. **Traefik** - Ingress controller
7. **Monitoring Stack** - Prometheus, Grafana, Loki

---

## Migration Scenarios

### Scenario A: New Hardware, Same IP

Replace hardware but keep the same IP address (192.168.1.54).

**Impact**: Medium - etcd data lost, but Flux/ArgoCD will reconcile
**Downtime**: 30-60 minutes

### Scenario B: New Hardware, New IP

New hardware with a different IP address.

**Impact**: High - Requires kubeconfig updates, Nebula reconfiguration
**Downtime**: 1-2 hours

### Scenario C: Single to Multi-Node (HA)

Add additional control plane nodes for high availability.

**Impact**: Low if done incrementally
**Downtime**: Minimal with proper planning

---

## Pre-Migration Checklist

### 1. Backup Current State

```bash
# Export all resources (for reference, not restore)
kubectl get all -A -o yaml > .output/backup/all-resources-$(date +%Y%m%d).yaml

# Export CRDs
kubectl get crd -o yaml > .output/backup/crds-$(date +%Y%m%d).yaml

# Export secrets (encrypted)
kubectl get secrets -A -o yaml > .output/backup/secrets-$(date +%Y%m%d).yaml

# Export PVs
kubectl get pv -o yaml > .output/backup/pvs-$(date +%Y%m%d).yaml

# Export Talos config (IMPORTANT)
cp configs/controlplane.yaml .output/backup/controlplane-$(date +%Y%m%d).yaml
cp configs/talosconfig .output/backup/talosconfig-$(date +%Y%m%d)
```

### 2. Document External Dependencies

- [ ] NFS server IPs (TrueNAS, Synology)
- [ ] DNS/hosts entries for \*.talos00
- [ ] 1Password Connect credentials
- [ ] AWS Elastic IP and security groups
- [ ] Nebula certificates and lighthouse config

### 3. Verify GitOps State

```bash
# Ensure all changes are committed
cd ~/catalyst-devspace/workspace/talos-homelab
git status

# Verify Flux sources are healthy
flux get sources all

# Verify ArgoCD apps are synced
argocd app list
```

### 4. Scale Down Stateful Workloads

```bash
# Scale down to avoid data corruption during migration
kubectl scale deployment -n observability --all --replicas=0
kubectl scale deployment -n monitoring --all --replicas=0
kubectl scale statefulset -n observability --all --replicas=0
kubectl scale statefulset -n monitoring --all --replicas=0
```

---

## Migration Steps: Scenario A (Same IP)

### Phase 1: Pre-Migration

1. **Complete pre-migration checklist** (above)
2. **Notify dependent systems** (if any)
3. **Document current kubeconfig**:
   ```bash
   cp ~/.kube/config ~/.kube/config.backup
   ```

### Phase 2: Graceful Shutdown

```bash
# Cordon the node to prevent new scheduling
kubectl cordon talos00

# Drain non-critical workloads
kubectl drain talos00 --ignore-daemonsets --delete-emptydir-data

# Graceful Talos shutdown
talosctl shutdown --nodes 192.168.1.54
```

### Phase 3: Hardware Swap

1. Power off old hardware
2. Install/configure new hardware
3. Ensure network connectivity at same IP

### Phase 4: Talos Provisioning

```bash
# Generate new Talos config (if needed)
task talos:gen-config

# Apply config to new node
task talos:apply-config INSECURE=true

# Bootstrap etcd
task talos:bootstrap

# Download new kubeconfig
task talos:kubeconfig
```

### Phase 5: Post-Migration

```bash
# Verify node is ready
kubectl get nodes

# Re-enable scheduling
kubectl uncordon <new-node-name>

# Let Flux reconcile
flux reconcile source git flux-system

# Verify all workloads recover
kubectl get pods -A | grep -v Running
```

---

## Migration Steps: Scenario B (New IP)

### Additional Pre-Steps

1. **Update DNS/hosts entries** for new IP
2. **Update Talos config** with new endpoint IP
3. **Update Nebula config** with new mesh IP (if changing)

### Phase 4 Addition: Configuration Updates

```bash
# Update talosconfig endpoint
sed -i 's/192.168.1.54/NEW_IP/g' configs/talosconfig

# Update CLAUDE.md and scripts
grep -r "192.168.1.54" . | grep -v ".git" | grep -v ".output"

# Update /etc/hosts on local machine
sudo sed -i '' 's/192.168.1.54/NEW_IP/g' /etc/hosts
```

### Liqo Re-Peering Required

After IP change, Liqo peering must be re-established:

```bash
# Unpeer from homelab
liqoctl unpeer --namespace liqo

# Update mesh kubeconfig with new IP
# Re-establish peering
./scripts/hybrid-llm/orchestrate-aws-cluster.sh --step peer
```

---

## Post-Migration Verification

### 1. Core Health Checks

```bash
# Talos health
task talos:health

# Node status
kubectl get nodes -o wide

# All pods running
kubectl get pods -A | grep -v Running | grep -v Completed
```

### 2. Storage Verification

```bash
# PV status
kubectl get pv | grep -v Bound

# PVC status
kubectl get pvc -A | grep -v Bound
```

### 3. GitOps Sync Status

```bash
# Flux reconciliation
flux get all -A

# ArgoCD applications
argocd app list
```

### 4. External Connectivity

```bash
# Nebula mesh
kubectl exec -n nebula-system -it daemonset/nebula -- nebula-cert print -json

# AWS cluster connectivity
ping 10.42.0.1

# Liqo status
liqoctl info
```

### 5. Ingress Verification

```bash
# Test Traefik routes
curl -H "Host: grafana.talos00" http://192.168.1.54
curl -H "Host: argocd.talos00" http://192.168.1.54
```

---

## Rollback Procedure

### If Migration Fails Mid-Way

1. **Re-connect old hardware** (if still available)
2. **Apply original Talos config**:
   ```bash
   talosctl apply-config --insecure --nodes 192.168.1.54 \
     --file .output/backup/controlplane-YYYYMMDD.yaml
   ```
3. **Bootstrap if needed**:
   ```bash
   task talos:bootstrap
   ```

### If New Cluster Has Issues

- Flux will attempt to reconcile all infrastructure
- ArgoCD apps should auto-sync
- Manual intervention may be needed for stateful workloads

---

## Data That WILL Be Lost

| Component        | Data Lost                              | Recovery Method        |
| ---------------- | -------------------------------------- | ---------------------- |
| etcd             | Cluster state                          | Flux/ArgoCD reconciles |
| local-path PVs   | Pod data (Prometheus, Grafana history) | Redeploys from scratch |
| In-memory caches | All cached data                        | Automatic rebuild      |

## Data That WILL Be Preserved

| Component         | Location                  | Notes                         |
| ----------------- | ------------------------- | ----------------------------- |
| NFS PVs           | External NAS              | survives migration            |
| App configs       | fatboy-nfs-appdata        | survives migration            |
| Media files       | synology-nfs, truenas-nfs | survives migration            |
| Git repos         | GitHub                    | Source of truth for GitOps    |
| 1Password secrets | 1Password                 | External Secrets will re-sync |

---

## Timeline Estimate

| Phase                  | Duration     |
| ---------------------- | ------------ |
| Pre-migration backup   | 15 min       |
| Graceful shutdown      | 10 min       |
| Hardware swap          | 30+ min      |
| Talos provisioning     | 15 min       |
| GitOps reconciliation  | 20-30 min    |
| Verification           | 15 min       |
| **Total (Scenario A)** | **~2 hours** |

---

## Questions to Resolve Before Migration

1. **What new hardware?** (Specs, form factor)
2. **Same IP or new IP?**
3. **Keep multi-node setup or expand?**
4. **Timing constraints?** (Maintenance window)
5. **Should Liqo peering be torn down first?** (To avoid orphaned resources)

---

## Related Documentation

- [Talos Provisioning Steps](TALOS-PROVISIONING-STEPS.md)
- [Liqo Re-Peering Test](hybrid-llm-cluster/LIQO-REPEERING-TEST.md) (on hold)
- [Node Shutdown Procedure](node-shutdown-procedure.md)
- [Dual GitOps Architecture](DUAL-GITOPS.md)
