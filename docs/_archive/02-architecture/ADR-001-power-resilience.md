# ADR-001: Power resilience strategy after UPS-2026-05-09 incident

**Date**: 2026-05-21
**Status**: PROPOSED
**Related**: TALOS-asv (incident retro), TALOS-a8g (etcd snapshots, closed)

## Context

On **2026-05-09**, a UPS fault caused all 5 Talos nodes to power off uncleanly.
On recovery the control plane (talos00) failed to boot — ephemeral XFS
(`/dev/sda4`) had corrupted during the unclean shutdown:

```
XFS (sda4): Metadata has LSN (7413:30756) ahead of current LSN (7413:30281)
XFS (sda4): log mount/recovery failed: error -117
```

Talos's auto `xfs_repair` refused with "valuable metadata changes in a log
which needs to be replayed". Talos has no in-cluster shell to run
`xfs_repair -L` manually.

**No etcd snapshots existed** (TALOS-a8g now adds them). Recovery required
a fresh bootstrap with full local-path PVC loss. GitOps reconciled
application manifests, but state-bearing PVCs (Prometheus TSDB, Grafana,
Graylog, OpenSearch, MongoDB, Nexus, dashboards) were unrecoverable.

This is a **known Talos issue**:
- [siderolabs/talos#9217](https://github.com/siderolabs/talos/issues/9217)
- [siderolabs/talos#8292](https://github.com/siderolabs/talos/issues/8292)

Both closed as "not planned" by upstream. XFS on bare-metal Talos breaks on
every power loss.

## Decision drivers

1. **Single point of failure**: 1 control plane, 1 UPS, 1 filesystem choice
2. **Recovery time**: 8-12 hours of manual work the morning after
3. **Data loss surface**: ~50 local-path PVCs (TSDB, dashboards, registry,
   Nexus images, app configs)
4. **Cost ceiling**: this is a homelab; we're not buying enterprise gear
5. **Operator availability**: solo operator, asleep when this happened

## Options considered

### A. Redundant UPS + graceful shutdown automation
- **What**: Second UPS feeding A/B PDU. NUT or apcupsd monitor low battery,
  trigger `talosctl shutdown` before battery dies.
- **Cost**: ~$200-500 for 2nd UPS. Configuration time ~4h.
- **Defense scope**: power events. Does nothing for disk failure or kernel
  panic on the CP node.
- **Confidence**: High. Industry-standard pattern.

### B. HA control plane (3 master nodes)
- **What**: Promote talos01 + talos03 to control-plane. etcd quorum
  survives any 1 node loss with no downtime.
- **Cost**: Lose ~2 nodes worth of workload capacity (CPs prefer to stay
  light). Extra RAM/CPU/electricity 24/7.
- **Defense scope**: single-node failures (disk, kernel, hardware). Does
  NOT help when ALL nodes lose power simultaneously — etcd on whichever
  CP was mid-write can still corrupt.
- **Confidence**: High. Kubernetes-native.

### C. Switch ephemeral filesystem from XFS to ext4
- **What**: ext4 handles unclean shutdowns more gracefully. Smaller log
  corruption blast radius.
- **Cost**: Each node needs `talosctl reset --system-labels-to-wipe=EPHEMERAL`
  after machine config update. Sequential, ~30 min total.
- **Defense scope**: Reduces severity of power-loss corruption. Doesn't
  prevent data loss but Talos's auto-repair is more likely to succeed.
- **Confidence**: Medium. Newer Talos versions expose this, need to verify
  v1.13.x supports `machine.disks.partitions[].filesystem.type: ext4` on
  ephemeral. (siderolabs/talos still defaults to XFS; check current docs.)

### D. Combination of A + B + C

The UPS issue (power loss → all nodes drop) and the etcd quorum issue
(single-node failure) are **independent**. Even with 3 CPs, if all 3 get
power-killed simultaneously, etcd can still corrupt on whichever node had
ongoing writes.

Therefore the layered defense is:
- **A** (power resilience) handles the most common failure mode
- **B** (HA) handles single-node failures + lets us patch one CP at a time
- **C** (ext4) reduces blast radius when A fails

## Decision

**Recommended: A + B (defer C)**.

| Layer | Why | Status |
|-------|-----|--------|
| **A: 2nd UPS + NUT** | Highest leverage; addresses root cause of this incident | Proposed |
| **B: 3-master HA** | Defense-in-depth; cheap once A is in place; enables rolling upgrades without downtime | Proposed |
| **C: ext4 ephemeral** | Optional belt-and-suspenders; revisit after v1.14.x | Deferred |

### A is the priority

The actual incident root cause was *power loss*, not *node hardware
failure*. Adding 2 more CPs doesn't help if they all die at once. A
working UPS + auto-shutdown stops the corruption from happening in the
first place.

### B is cheap defense-in-depth

talos01 (Ryzen 5800U) and talos03 (Ryzen 5800U, mostly idle per
`docs/05-projects/cluster-optimization/`) are strong CP candidates.
talos02 (Intel Ultra 5, 64GB) is too capable to "waste" on a CP role.
Best mix: **talos00 + talos01 + talos03** as CPs; talos02-gpu + talos06
remain pure workers.

### C is opt-in if needed

Newer Talos may support ext4 on ephemeral. If A+B are working, the impact
of XFS corruption is bounded (etcd snapshots restore state, GitOps
restores apps). Filesystem swap is a "nice to have" but not load-bearing.

## Implementation plan

Filed as separate tickets so they can be sequenced/prioritized:

1. **UPS + NUT/apcupsd graceful-shutdown** (TBD ticket) — buy 2nd UPS,
   install NUT client (DaemonSet or Pi sidecar that calls `talosctl
   shutdown`), test by triggering low-battery event
2. **3-master HA promotion** (TBD ticket) — generate CP configs for
   talos01 + talos03, apply via talos machine config, validate etcd
   quorum, document rolling-CP-upgrade procedure
3. **Ephemeral ext4 evaluation** (TBD ticket, lower priority) — verify
   Talos v1.13.x supports `partitions[].filesystem.type: ext4` on
   ephemeral, plan migration if so

## Consequences

**Positive:**
- Power events become a non-incident (UPS rides through, then graceful
  shutdown before exhaustion)
- One CP can fail without cluster downtime
- Rolling Talos upgrades on the CP plane become trivial (we couldn't do
  this before — talos00 outage = full cluster outage)

**Negative:**
- Hardware cost (~$200-500 for UPS #2)
- Ongoing electricity for 24/7 second UPS
- ~10% CPU/RAM overhead per CP node for etcd + control-plane components
- Solo operator must remember to test the NUT shutdown trigger at least
  annually — set a calendar reminder

## Status

PROPOSED — awaiting operator approval to file the 3 implementation tickets
and proceed with UPS purchase.
