# Cilium Migration Guide

This document outlines the migration path from Flannel to Cilium CNI on Talos Linux.

## Current State

- **CNI**: Flannel (Talos default)
- **Issue**: Default flannel has no CPU limits, causing CPUThrottlingHigh alerts
- **Workaround**: CronJob patches flannel resources every 5 minutes (see `configs/controlplane.yaml`)

## Why Consider Cilium?

### Advantages over Flannel

| Feature               | Flannel    | Cilium             |
| --------------------- | ---------- | ------------------ |
| eBPF-based networking | No         | Yes                |
| Network policies      | Basic      | Advanced (L3-L7)   |
| Observability         | None       | Hubble UI/CLI      |
| Service mesh          | No         | Yes (sidecar-free) |
| Load balancing        | kube-proxy | Native eBPF        |
| Bandwidth management  | No         | Yes                |
| Multi-cluster         | No         | ClusterMesh        |
| Resource efficiency   | Moderate   | Better (eBPF)      |

### Cilium Benefits for This Cluster

1. **Better resource management** - No need for hacky CronJob patches
2. **Hubble observability** - Network flow visualization
3. **Future-proof** - Better for Liqo multi-cluster scenarios
4. **eBPF performance** - Lower latency, higher throughput

## Migration Approaches

### Option 1: Fresh Cluster Install (Recommended)

Best for: Planned maintenance windows, minimal data to migrate

**Steps:**

1. **Backup critical data**

   ```bash
   # Export PVCs, secrets, configmaps
   kubectl get pvc -A -o yaml > backup/pvcs.yaml
   kubectl get secrets -A -o yaml > backup/secrets.yaml
   ```

2. **Update Talos machine config**

   ```yaml
   cluster:
     network:
       cni:
         name: none # Disable default flannel
   ```

3. **Prepare Cilium inline manifest**

   ```yaml
   cluster:
     inlineManifests:
       - name: cilium
         contents: |
           # Cilium helm template output
           # See: https://docs.cilium.io/en/stable/installation/k8s-install-helm/
   ```

4. **Reset and reprovision cluster**

   ```bash
   task reset
   task provision
   ```

5. **Restore workloads**

### Option 2: In-Place Migration (Risky)

Best for: Cannot afford downtime, willing to accept risk

**Warning**: This can cause network outages. Not recommended for production.

**Steps:**

1. **Scale down workloads**

   ```bash
   kubectl scale deployment --all --replicas=0 -A
   ```

2. **Install Cilium alongside Flannel**

   ```bash
   helm repo add cilium https://helm.cilium.io/
   helm install cilium cilium/cilium \
     --namespace kube-system \
     --set operator.replicas=1 \
     --set tunnel=vxlan \
     --set bpf.masquerade=true
   ```

3. **Verify Cilium is running**

   ```bash
   cilium status
   kubectl get pods -n kube-system -l k8s-app=cilium
   ```

4. **Update Talos config to disable flannel**

   ```yaml
   cluster:
     network:
       cni:
         name: none
   ```

5. **Apply config (triggers reboot)**

   ```bash
   talosctl apply-config --nodes 192.168.1.54 --file configs/controlplane.yaml
   ```

6. **Delete flannel resources**

   ```bash
   kubectl delete ds kube-flannel -n kube-system
   kubectl delete cm kube-flannel-cfg -n kube-system
   ```

7. **Restart all pods to get new CNI**
   ```bash
   kubectl delete pods --all -A
   ```

### Option 3: Hybrid Approach (Gradual)

Best for: Multi-node clusters (not applicable to single-node)

For multi-node clusters, you can migrate node-by-node using node selectors and taints.

## Cilium Configuration for Talos

### Recommended Cilium Values

```yaml
# cilium-values.yaml
kubeProxyReplacement: strict
k8sServiceHost: 192.168.1.54  # Talos API endpoint
k8sServicePort: 6443

operator:
  replicas: 1

ipam:
  mode: kubernetes

hubble:
  enabled: true
  relay:
    enabled: true
  ui:
    enabled: true

# Resources (adjust based on cluster size)
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 512Mi

operator:
  resources:
    requests:
      cpu: 50m
      memory: 64Mi
    limits:
      cpu: 200m
      memory: 256Mi
```

### Talos Machine Config for Cilium

```yaml
# configs/controlplane.yaml changes
machine:
  # ... existing config ...

cluster:
  network:
    cni:
      name: none # Critical: disable default flannel
    podSubnets:
      - 10.244.0.0/16
    serviceSubnets:
      - 10.96.0.0/12

  inlineManifests:
    - name: cilium-install
      contents: |
        # Generate with: helm template cilium cilium/cilium -n kube-system -f cilium-values.yaml
        # Or use Cilium CLI: cilium install --helm-values cilium-values.yaml --dry-run
```

## Pre-Migration Checklist

- [ ] Backup all PVCs and critical data
- [ ] Document all NetworkPolicies (will need conversion)
- [ ] Note any custom kube-proxy configurations
- [ ] Schedule maintenance window
- [ ] Test Cilium in a lab environment first
- [ ] Ensure Talos version supports Cilium (v1.3+)

## Post-Migration Verification

```bash
# Check Cilium status
cilium status

# Verify connectivity
cilium connectivity test

# Check Hubble (if enabled)
hubble status
hubble observe

# Verify all pods have Cilium endpoint
kubectl get cep -A

# Test cross-namespace communication
kubectl run test --image=busybox --rm -it -- wget -qO- http://service.namespace.svc
```

## Rollback Plan

If migration fails:

1. **Revert Talos config**

   ```yaml
   cluster:
     network:
       cni:
         name: flannel # Re-enable flannel
   ```

2. **Apply config**

   ```bash
   talosctl apply-config --nodes 192.168.1.54 --file configs/controlplane.yaml
   ```

3. **Delete Cilium**

   ```bash
   helm uninstall cilium -n kube-system
   ```

4. **Restart pods**
   ```bash
   kubectl delete pods --all -A
   ```

## References

- [Talos CNI Documentation](https://www.talos.dev/v1.11/kubernetes-guides/network/deploying-cilium/)
- [Cilium Installation Guide](https://docs.cilium.io/en/stable/installation/k8s-install-helm/)
- [Cilium Talos Integration](https://docs.cilium.io/en/stable/installation/k8s-install-talos/)
- [Flannel to Cilium Migration](https://docs.cilium.io/en/stable/installation/k8s-install-migration/)

## Decision Matrix

| Scenario              | Recommended Approach                    |
| --------------------- | --------------------------------------- |
| Fresh cluster setup   | Option 1 (Fresh Install)                |
| Single-node homelab   | Option 1 or stay with Flannel + CronJob |
| Multi-node production | Option 3 (Gradual)                      |
| Dev/test cluster      | Option 2 (In-Place)                     |
| Need zero downtime    | Stay with Flannel + CronJob workaround  |

## Current Recommendation

For this single-node Talos homelab cluster, the **CronJob workaround is acceptable** for now. Consider Cilium migration when:

1. Planning a cluster rebuild/upgrade
2. Adding additional nodes
3. Need advanced network policies
4. Want Hubble observability
5. Planning Liqo multi-cluster expansion

The CronJob approach (`flannel-resource-patcher`) is documented in `configs/controlplane.yaml` and ensures flannel resources are properly set without risking network outages.
