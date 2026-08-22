# Runbooks

## Overview

Step-by-step operational procedures for high-consequence changes and recovery scenarios. Runbooks in
this section assume you are executing under pressure — each one leads with a TL;DR, then a quick
reference, then the full detail. Read the TL;DR before you touch anything.

Machine-config patch files live here too, alongside the runbooks that apply them. They are applied by
`scripts/bootstrap-talos-patches.sh`, not by hand.

## Quick Navigation

| Runbook | Description | When to Read |
| --- | --- | --- |
| [cluster-bootstrap.md](cluster-bootstrap.md) | End-to-end bare-metal → fully-reconciling GitOps recovery. The authoritative recovery path. | After any catastrophic event — UPS failure, accidental wipe, fresh hardware |
| [promote-workers-to-controlplane.md](promote-workers-to-controlplane.md) | Promote two workers to control planes, 1 CP → 3 CP. **Destructive** — each promoted node is wiped. | Building etcd HA. Read the local-path and Velero sections **before** scheduling the work |
| [ha-control-plane-migration.md](ha-control-plane-migration.md) | Earlier HA migration plan (TALOS-arx). Its *rationale* stands; its **promotion mechanics are superseded** — see the note below. | Background on why 3 CPs fix the cilium-flap meltdown class |
| [velero-restore.md](velero-restore.md) | Restoring PVC data from a Velero backup after node/PVC loss. | Recovering a lost volume — but check the coverage caveat below first |

## Machine-config patches

| Patch | Purpose |
| --- | --- |
| [talos-kubelet-iscsi-patch.yaml](talos-kubelet-iscsi-patch.yaml) | `extraMounts` for `/etc/iscsi` + `/var/lib/iscsi` (Democratic-CSI / TrueNAS iSCSI) |
| [talos-kubelet-localpath-patch.yaml](talos-kubelet-localpath-patch.yaml) | `extraMount` for `/var/lib/rancher` — without it every local-path volume fails to mount |
| [talos-kubelet-maxpods-patch.yaml](talos-kubelet-maxpods-patch.yaml) | `maxPods` 110 → 200 (TALOS-d5b5). The pod CIDR `/24` is the real ceiling — do not exceed ~240 |
| [talos-controlplane-metrics-patch.yaml](talos-controlplane-metrics-patch.yaml) | Bind kube-scheduler / controller-manager metrics to `0.0.0.0` so Alloy can scrape them |

Apply them all, idempotently, across every node:

```bash
./scripts/bootstrap-talos-patches.sh --check   # dry run
./scripts/bootstrap-talos-patches.sh           # apply
```

## Key Concepts

- **A reset node loses every machine-config patch.** Re-run `scripts/bootstrap-talos-patches.sh`
  after any `talosctl reset`, or the node returns with `maxPods: 110` and local-path broken.
- **Talos machine type is immutable.** Worker → control-plane is a full reset and reinstall, never an
  in-place edit. See [promote-workers-to-controlplane.md §1](promote-workers-to-controlplane.md#1-why-this-requires-a-full-reset).
- **Reset wipes EPHEMERAL (`/var`), which is where local-path provisions.** Every local-path PV on a
  reset node is destroyed. `local-path` is `WaitForFirstConsumer`, so those PVs are pinned to the node
  and cannot migrate themselves.
- **⚠️ Velero does not back up local-path PVs.** They are `hostPath` volumes, and Velero's
  file-system backup skips `hostPath` by design — even when the volume is explicitly named in
  `backup.velero.io/backup-volumes`. It logs a warning per volume but the backup still reports
  `Completed`, so the gap is invisible unless you read the log. Several workloads are annotated as
  though protected and are not. Check the PV's **source type**, not its backup history:
  [promote-workers-to-controlplane.md §3](promote-workers-to-controlplane.md#3-the-velero-gotcha-read-this-before-you-trust-any-backup).
- **Velero lives in the `backup` namespace**, not `velero`.
- **etcd learner mode is automatic.** New control-plane nodes join as non-voting learners and are
  promoted to voters automatically once caught up. A learner does not increase quorum — which is what
  makes an abort safe up until the promotion lands.

> **Note on `ha-control-plane-migration.md`:** it describes promotion as running `apply-config` and
> letting Talos reinstall on a role change. That does not work — Talos cannot change machine type in
> place. Use [promote-workers-to-controlplane.md](promote-workers-to-controlplane.md) for the
> mechanics.

## Related

- [docs/03-operations/etcd-backup-restore.md](../03-operations/etcd-backup-restore.md) — etcd snapshot and restore
- [docs/03-operations/node-shutdown-procedure.md](../03-operations/node-shutdown-procedure.md) — safe shutdown / maintenance
- [docs/03-operations/provisioning.md](../03-operations/provisioning.md) — provisioning levels

---

## Related Issues

<!-- Beads tracking for this doc -->

- **TALOS-arx** — HA control plane epic
- **TALOS-d5b5** — kubelet `maxPods` 110 → 200
