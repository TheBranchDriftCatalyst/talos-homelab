# Liqo Re-Peering Test Log

**Date**: 2025-12-04
**Status**: ON HOLD (pending control plane migration)
**Purpose**: Validate consolidated provisioning scripts by tearing down and re-establishing Liqo peering

> **Note**: This test is paused. The homelab cluster is being migrated to a new control plane node.
> See `CONTROL-PLANE-MIGRATION.md` for the migration plan.
> Resume this test after migration is complete.

## Test Plan

1. Document current state (before teardown)
2. Clean teardown of Liqo peering
3. Re-establish peering using `orchestrate-aws-cluster.sh` (peering step only)
4. Verify virtual node and pod offloading
5. Document any orphaned resources or issues

---

## Phase 1: Pre-Teardown State

### Homelab Cluster

```
# Timestamp: [PENDING]

# Nodes (including virtual)
[PENDING]

# Liqo pods
[PENDING]

# Liqo info
[PENDING]

# ForeignCluster resources
[PENDING]

# VirtualNodes
[PENDING]

# Tenant namespaces
[PENDING]
```

### AWS Cluster

```
# Timestamp: [PENDING]

# Nodes
[PENDING]

# Liqo pods
[PENDING]

# Tenant resources
[PENDING]

# ResourceSlices
[PENDING]
```

---

## Phase 2: Teardown

### Commands Executed

```bash
# [PENDING]
```

### Resources Removed

- [ ] Virtual node removed from homelab
- [ ] ForeignCluster removed
- [ ] Tenant namespace removed from homelab
- [ ] Tenant removed from AWS
- [ ] ResourceSlice removed from AWS
- [ ] Quota removed from AWS

### Issues During Teardown

[PENDING]

---

## Phase 3: Re-Peering

### Command Used

```bash
# [PENDING]
```

### Output

```
[PENDING]
```

### Time to Complete

[PENDING]

---

## Phase 4: Verification

### Virtual Node

```
# kubectl get nodes -l liqo.io/type=virtual-node
[PENDING]
```

### Liqo Status

```
# liqoctl info
[PENDING]
```

### Test Pod Offloading

```
# Pod creation and status
[PENDING]

# Pod logs
[PENDING]
```

---

## Phase 5: Orphan Check

### Homelab - Unexpected Resources

```bash
# Check for orphaned namespaces
kubectl get ns | grep liqo

# Check for orphaned CRDs
kubectl get foreignclusters.core.liqo.io -A
kubectl get virtualnodes.offloading.liqo.io -A
kubectl get namespaceoffloadings.offloading.liqo.io -A
kubectl get resourceslices.authentication.liqo.io -A
```

### AWS - Unexpected Resources

```bash
# Check for orphaned tenants
kubectl get tenants.authentication.liqo.io -A

# Check for orphaned quotas
kubectl get quotas.offloading.liqo.io -A

# Check for orphaned shadowpods
kubectl get shadowpods.offloading.liqo.io -A
```

---

## Results Summary

| Metric | Result |
|--------|--------|
| Teardown Clean | [PENDING] |
| Re-peering Success | [PENDING] |
| Virtual Node Created | [PENDING] |
| Pod Offloading Works | [PENDING] |
| Orphaned Resources | [PENDING] |
| Total Time | [PENDING] |

## Issues Found

[PENDING]

## Script Improvements Needed

[PENDING]
