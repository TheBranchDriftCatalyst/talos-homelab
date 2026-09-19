---
type: architecture
status: current
covers:
  - path:configs/patches
  - path:infrastructure/base/backup
  - path:infrastructure/base/storage
freshness: tracks-code
tickets:
  - TALOS-arx
  - TALOS-d5b5
bluf: The standing constraints every runbook here is written against — a reset destroys local-path data, Velero silently skips it while reporting success, and machine-config patches only come back by re-applying the node's generated config.
---

# Runbooks

## TL;DR

Before you execute anything in this directory, know these four things:

1. **Velero does not back up `local-path` PVs** — and the backup still reports `Completed`.
   Several workloads are annotated as though protected and are not.
2. **A `talosctl reset` destroys every `local-path` PV on that node.** Those volumes are
   `WaitForFirstConsumer` and pinned; they cannot migrate themselves out of the way.
3. **Machine-config patches are not separately applied.** Re-applying the node's generated
   config brings the bind mounts, `maxPods`, reserves and image GC back in one step.
4. **Talos machine type is immutable.** Worker → control plane is a full reset and reinstall.

The detail, and the evidence for each, is in [Key Concepts](#key-concepts) below.

## Overview

Step-by-step operational procedures for high-consequence changes and recovery scenarios. Runbooks in
this section assume you are executing under pressure — each one leads with a TL;DR, then a quick
reference, then the full detail. Read the TL;DR before you touch anything.

This file is not just an index. Most of it is the set of cluster-wide invariants the runbooks
assume you already know — they are collected here because every one of them was learned the
expensive way, and because they cut across more than one procedure.

**Machine-config patching is no longer a thing you do.** Every kubelet and control-plane setting
is declared under `configs/patches/` and composed into each node's config by talhelper from
`configs/talconfig.yaml`. The old `scripts/bootstrap-talos-patches.sh` has been deleted; the
`task talos:patches` target survives only to tell you where its work went.

## Quick Navigation

| Runbook                                      | Description                                                                                 | When to Read                                                                |
| -------------------------------------------- | ------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| [cluster-bootstrap.md](cluster-bootstrap.md) | End-to-end bare-metal → fully-reconciling GitOps recovery. The authoritative recovery path. | After any catastrophic event — UPS failure, accidental wipe, fresh hardware |
| [velero-restore.md](velero-restore.md)       | Restoring PVC data from a Velero backup after node/PVC loss.                                | Recovering a lost volume — but check the coverage caveat below first        |

> **Two rows were removed here.** `promote-workers-to-controlplane.md` and
> `ha-control-plane-migration.md` never existed in git history at all; the HA migration
> they described is done, and this cluster now declares three control planes in
> `configs/talconfig.yaml`. Their durable content — the local-path, Velero and etcd-learner
> constraints — is in [Key Concepts](#key-concepts) below, which is why that section is the bulk
> of this file. The table is pending regeneration and is left as-is deliberately.
>
> Not listed in the table but present in this directory:
> [bluetooth-enablement.md](bluetooth-enablement.md),
> [kubernetes-upgrade.md](kubernetes-upgrade.md),
> [talsecret-1password-backup.md](talsecret-1password-backup.md).

## Machine-config patches

> The four `talos-*-patch.yaml` files this table links to were **deleted** from this directory
> once talhelper took over. The table below now names the LIVE patch carrying each setting, so
> the rows point at files that exist. What each setting is _for_ was always the useful part —
> the old per-patch filenames were not.

| Live patch in `configs/patches/`           | What the setting is for                                                                 |
| ------------------------------------------ | --------------------------------------------------------------------------------------- |
| `all-kubelet-baseline.yaml`                | `extraMounts` for `/etc/iscsi` + `/var/lib/iscsi` (Democratic-CSI / TrueNAS iSCSI)      |
| `all-kubelet-baseline.yaml`                | `extraMount` for `/var/lib/rancher` — without it every local-path volume fails to mount |
| `maxpods-200.yaml`, `talos03-maxpods.yaml` | `maxPods` 110 → 200 (TALOS-d5b5). A `/24` cannot host more addresses than it has        |
| `controlplane-baseline.yaml`               | Bind kube-scheduler / controller-manager metrics to `0.0.0.0` so Alloy can scrape them  |

These are applied as part of each node's generated machine config — there is no separate
apply step. Do not apply them by hand with `talosctl patch mc`; that creates drift the next
`task talos:apply-config` reverts.

```bash
task talos:verify           # regenerate and diff against every live node
task talos:verify-dry-run   # ask each node what applying would do — read-only
task talos:apply-config NODE=<hostname>   # apply one node (destructive)
```

## Key Concepts

- **A reset node loses every machine-config patch — but recovering them is now one step.**
  Re-apply the node's generated config (`task talos:apply-config NODE=<hostname>`) and the bind
  mounts, `maxPods`, reserves and image GC all come back with it. Skip it and the node returns
  with `maxPods: 110` and local-path broken.
- **Talos machine type is immutable.** Worker → control-plane is a full reset and reinstall, never an
  in-place edit. The machine type is fixed by each node's `controlPlane:` flag in
  `configs/talconfig.yaml`; changing it changes which config is generated, not what the running
  node is.
- **Reset wipes EPHEMERAL (`/var`), which is where local-path provisions.** Every local-path PV on a
  reset node is destroyed. `local-path` is `WaitForFirstConsumer`, so those PVs are pinned to the node
  and cannot migrate themselves.
- **Un-bind storage before you reset, rather than evacuating it during a window.** Sonarr, Radarr and
  Prowlarr have already been moved off node-bound SQLite onto the `arr-postgres` CNPG cluster — their
  `*__POSTGRES__HOST` env vars are the switch, and their local-path PVCs are gone. What is still
  node-bound in the arr stack is Jellyfin, Plex (SQLite-only by design) and qBittorrent. Check
  `storageClassName: local-path` in the manifests before assuming anything about a given workload.
- **⚠️ The SQLite-to-local-path migration is one-way and does not self-heal.** `migrate-arr.sh`
  (`applications/arr-stack/base/shared/db-migration-configmap.yaml`) keys its idempotency check on a
  symlink that lives on the surviving NFS volume, so after the local PV is destroyed the check still
  passes and the app starts on an **empty** database — it does not restore from `.nfs-backup`. Those
  `.nfs-backup` copies are frozen at first-migration time and are not backups. Jellyfin and Plex are
  the two workloads still mounting this ConfigMap, so they are the two this can still bite.
- **SQLite must not live on NFS** — that is why the local-path binding exists at all. Several
  `media-experimental` config volumes hold SQLite too, so "just move it to NFS" is not a general
  answer.
- **⚠️ Velero does not back up local-path PVs.** They are `hostPath` volumes, and Velero's
  file-system backup skips `hostPath` by design — even when the volume is explicitly named in
  `backup.velero.io/backup-volumes`. It logs a warning per volume but the backup still reports
  `Completed`, so the gap is invisible unless you read the log. Several workloads are annotated as
  though protected and are not. **Check the PV's source type, not its backup history.**
- **Velero lives in the `backup` namespace**, not `velero`. See
  [velero-restore.md](velero-restore.md) for what the schedules actually cover.
- **etcd learner mode is automatic.** New control-plane nodes join as non-voting learners and are
  promoted to voters automatically once caught up. A learner does not increase quorum — which is what
  makes an abort safe up until the promotion lands.

## Related

- [docs/03-operations/etcd-backup-restore.md](../03-operations/etcd-backup-restore.md) — etcd snapshot and restore
- [docs/03-operations/node-shutdown-procedure.md](../03-operations/node-shutdown-procedure.md) — safe shutdown / maintenance
- [cluster-bootstrap.md](cluster-bootstrap.md) — bare metal to reconciling GitOps, the successor to the old provisioning guide

---

## Related Issues

<!-- Beads tracking for this doc -->

- **TALOS-arx** — HA control plane epic
- **TALOS-d5b5** — kubelet `maxPods` 110 → 200
