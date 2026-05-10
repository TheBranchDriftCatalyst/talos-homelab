# etcd Backup & Restore

How automated etcd snapshots work in this cluster, and how to recover the control plane from one when the etcd state is gone (e.g. the 2026-05-09 UPS-fault scenario).

## TL;DR

- **Snapshots**: hourly via in-cluster CronJob `backup/etcd-backup` to MinIO `s3://backups/etcd/` (NFS-backed)
- **Retention**: last 168 (1 week at hourly cadence), tunable via ConfigMap
- **Restore**: bootstrap a fresh control plane node with `talosctl bootstrap --recover-from=<snapshot>`
- **Restore time**: ~10 minutes from running `bootstrap` to a healthy API server

## Why this exists

etcd holds all Kubernetes API state — every object, secret, ConfigMap, RBAC binding, scheduling history. On Talos, etcd lives on the EPHEMERAL XFS partition. If that partition corrupts (UPS fault, disk failure, kernel panic mid-write), the control plane is unrecoverable without a snapshot. Velero does NOT cover this — Velero needs a working API server to restore.

## How it works

| Component | Path | Purpose |
|---|---|---|
| CronJob | `backup/etcd-backup` | Hourly snapshot job |
| ConfigMap | `backup/etcd-backup-config` | Tunables: `TALOS_NODE`, `RETENTION_COUNT`, S3 target |
| Secret | `backup/talosconfig` | Restricted talosconfig with `os:etcd:backup` role only |
| Secret | `backup/etcd-backup-s3-creds` | MinIO credentials |
| PrometheusRule | `monitoring/etcd-backup-alerts` | Alerts on job failure / not running / missing CronJob |
| Storage | `s3://backups/etcd/` (MinIO, NFS-backed) | Survives EPHEMERAL XFS loss |

Each run:
1. initContainer (`talosctl:v1.11.1`) calls `talosctl etcd snapshot` against the control plane node, writes to a shared emptyDir
2. main container (`mc`) uploads to MinIO with timestamp suffix
3. main container prunes oldest snapshots beyond `RETENTION_COUNT`

Source: `infrastructure/base/backup/etcd-backup.yaml`

## Tuning

Edit the ConfigMap to change cadence/retention/target:

```bash
kubectl edit configmap -n backup etcd-backup-config
# RETENTION_COUNT: "168"   # 1 week hourly. Bump to 720 for 30 days.
```

Schedule lives on the CronJob itself (cron format):

```bash
kubectl edit cronjob -n backup etcd-backup
# spec.schedule: "0 * * * *"   # hourly at :00
```

## Verify it's working

```bash
# Most recent runs
kubectl get jobs -n backup -l app.kubernetes.io/name=etcd-backup

# Last successful schedule time
kubectl get cronjob -n backup etcd-backup \
  -o jsonpath='{.status.lastSuccessfulTime}{"\n"}'

# Snapshot list (open MinIO browser at nexus.talos00 or use mc)
kubectl run mc-check --rm -it --restart=Never \
  --image=minio/mc:latest --namespace=backup \
  --command -- /bin/sh -c '
    mc alias set m http://minio.minio.svc.cluster.local minio minio123 >/dev/null
    mc ls m/backups/etcd/ | tail -20
  '
```

Expect ~one snapshot per hour, sizes climbing slowly (etcd state grows with cluster activity — currently ~60-65 MiB).

## Restore procedure

> **You only need this if etcd is gone or corrupt.** For "I deleted a namespace", use Velero. For "I want to roll back a misapply", just re-apply manifests via Flux/ArgoCD.

### Step 1: confirm you actually need to restore

```bash
# Talos says etcd is unhealthy?
talosctl -n $TALOS_NODE service etcd status
talosctl -n $TALOS_NODE etcd status

# kubelet can't reach API server?
talosctl -n $TALOS_NODE service kubelet logs | tail
```

If etcd is just slow or one member is behind, see [Talos etcd recovery docs](https://www.talos.dev/v1.11/advanced/etcd-maintenance/) — single-member loss in a multi-member cluster is repairable without a snapshot restore.

### Step 2: pick the snapshot

You want the latest snapshot from BEFORE the corruption. If the corruption was sudden (power loss), the most recent snapshot is fine. If it was gradual (slow disk, runaway controller), pick a snapshot from before the symptoms started.

```bash
# Download via mc port-forward, or directly from the MinIO web UI
kubectl port-forward -n minio svc/minio 9000:9000 &
mc alias set local http://localhost:9000 minio minio123
mc ls local/backups/etcd/
mc cp local/backups/etcd/etcd-20260509-230000.snapshot ./db.snapshot
```

### Step 3: reset the control plane node

⚠️ **DESTRUCTIVE** — wipes EPHEMERAL state on the CP node. Worker nodes are untouched.

```bash
export TALOS_NODE=192.168.1.54
talosctl reset --graceful=false --reboot \
  --system-labels-to-wipe=EPHEMERAL \
  --system-labels-to-wipe=STATE \
  -n $TALOS_NODE
```

Wait for the node to reboot in maintenance mode (no API, no etcd, just `talosctl` over the insecure port).

### Step 4: bootstrap from the snapshot

```bash
# Re-apply the machine config (re-creates STATE)
talosctl apply-config --insecure -n $TALOS_NODE \
  --file configs/controlplane.yaml

# Bootstrap etcd FROM THE SNAPSHOT (this is the magic flag)
talosctl bootstrap -n $TALOS_NODE --recover-from=./db.snapshot
```

Talos will start etcd from the snapshot data instead of an empty DB. All API objects, secrets, ConfigMaps, RBAC, etc. from the snapshot moment are restored.

### Step 5: wait + verify

```bash
# kubeconfig may need re-fetching if certs rotated
talosctl kubeconfig -n $TALOS_NODE -f

# Should show all nodes Ready within ~5 min
kubectl get nodes

# etcd should report healthy with revision matching/exceeding the snapshot
talosctl -n $TALOS_NODE etcd status
```

### Step 6: reconcile drift

State that changed between snapshot time and disaster will need reconciling:
- **Flux Kustomizations** auto-reconcile from git on their interval (~5-10 min)
- **ArgoCD Applications** auto-sync from git
- **PVCs** are unaffected (data is on the PV, not in etcd) — pods will mount existing data
- **Pods scheduled after the snapshot** will be re-scheduled by their controllers
- **Manual `kubectl apply` work that wasn't committed** is lost — recover from your shell history if needed

## Caveats

- **Single-CP cluster**: if you only have one control plane node and it's dead-dead (hardware failure, not just corruption), you need replacement hardware before this procedure helps. Work from a spare node with the same machine config.
- **Multi-CP cluster**: don't restore from a snapshot if the *cluster* is healthy — it'll create split-brain. Use Talos's etcd member replacement procedure instead.
- **Snapshot age vs. PVC drift**: if the snapshot is days old, controllers will re-create things. If apps stored runtime state in a PVC AND in etcd (e.g., some operators), you may get inconsistency. The snapshot wins; the PVC may need reconciliation.
- **Secrets**: any secret created/rotated after the snapshot is gone. ESO will re-pull from upstream sources on reconcile, but bootstrap-time secrets (Vault/AWS creds) need to exist before ESO can run.

## Test restores

Not yet performed against this cluster. Filed as a follow-up — needs a non-prod target or a deliberate planned outage. Until tested, treat the restore procedure as untested-but-correct based on Talos docs.

---

## Related Issues

<!-- Beads tracking for this doc -->

- TALOS-a8g — etcd snapshot CronJob (closed, this is the implementation)
- TALOS-asv — UPS fault retro (the incident this addresses)
