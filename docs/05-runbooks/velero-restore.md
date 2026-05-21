# Velero Restore Runbook

How to restore PVC data from a Velero backup after a node/PVC loss.

Created in response to UPS-2026-05-09, which lost authentik PostgreSQL state
(no backups existed). This runbook is the recovery path for a repeat incident.

## TL;DR

```bash
# 1. List available backups
kubectl exec -n backup deploy/velero -- /velero backup get

# 2. Pick the most recent successful critical-data-daily-* backup
kubectl exec -n backup deploy/velero -- \
  /velero backup describe critical-data-daily-<TIMESTAMP> --details

# 3. Scale down the consumer (critical — Velero won't overwrite live PVCs)
kubectl scale -n authentik statefulset/authentik-postgresql --replicas=0
kubectl wait -n authentik --for=delete pod/authentik-postgresql-0 --timeout=60s

# 4. Delete the empty/corrupt PVC so the restore can recreate it
kubectl delete pvc -n authentik data-authentik-postgresql-0

# 5. Restore JUST that PVC + its PV
kubectl exec -n backup deploy/velero -- \
  /velero restore create restore-authentik-$(date +%s) \
    --from-backup critical-data-daily-<TIMESTAMP> \
    --include-namespaces authentik \
    --include-resources persistentvolumeclaims,persistentvolumes \
    --restore-volumes=true

# 6. Watch progress
kubectl exec -n backup deploy/velero -- /velero restore describe restore-authentik-<TS>

# 7. Scale Postgres back up
kubectl scale -n authentik statefulset/authentik-postgresql --replicas=1

# 8. Verify Postgres comes up healthy and authentik can log in
kubectl logs -n authentik authentik-postgresql-0
kubectl get pod -n authentik
```

## What Velero Actually Backs Up

Three schedules write to MinIO bucket `velero` (s3 endpoint
`http://minio.minio.svc.cluster.local`):

| Schedule | When | Scope | Retention | Volumes |
| --- | --- | --- | --- | --- |
| `daily-all` | 02:00 daily | media, scratch, home-automation, catalyst-llm, registry, vpn-gateway, authentik | 30d | Opt-in via `backup.velero.io/backup-volumes` annotation |
| `critical-data-daily` | 02:30 daily | authentik, monitoring (loki excluded) | 30d | **All PVCs** (`defaultVolumesToFsBackup: true`) |
| `weekly-full` | 03:00 Sunday | All namespaces (sans kube-system, kube-public, kube-node-lease, flux-system, minio) | 90d | Opt-in via annotation |

For Authentik recovery, **always use `critical-data-daily-*`** — it's the only
schedule that captures the postgres data volume without per-pod annotations.

Loki's PVC is labeled `velero.io/exclude-from-backup=true` (applied by the
`velero-loki-exclude-labeler` Job in the backup namespace) — Loki logs live in
S3, not on the PVC, so the PVC is just churny chunk cache.

## Restore Scenarios

### Authentik PostgreSQL (UPS-2026-05-09 redux)

The actual scenario from the original outage. Authentik refuses to start
because the database is empty/corrupt.

```bash
LATEST=$(kubectl exec -n backup deploy/velero -- /velero backup get \
  -o name | grep critical-data-daily | head -1)
echo "Restoring from $LATEST"

# Stop authentik components so they don't fight the restore
kubectl scale -n authentik deploy/authentik-server --replicas=0
kubectl scale -n authentik deploy/authentik-worker --replicas=0
kubectl scale -n authentik statefulset/authentik-postgresql --replicas=0
kubectl wait -n authentik --for=delete pod/authentik-postgresql-0 --timeout=120s

# Drop the broken PVC
kubectl delete pvc -n authentik data-authentik-postgresql-0

# Restore PVC + PV from backup. Velero fs-backup (Kopia) restores into a
# fresh PVC of the same name, which the StatefulSet will then re-mount.
kubectl exec -n backup deploy/velero -- /velero restore create \
  --from-backup ${LATEST#backup/} \
  --include-namespaces authentik \
  --include-resources persistentvolumeclaims,persistentvolumes,pods \
  --restore-volumes=true \
  --wait

# Bring everything back
kubectl scale -n authentik statefulset/authentik-postgresql --replicas=1
kubectl wait -n authentik pod/authentik-postgresql-0 --for=condition=ready --timeout=300s
kubectl scale -n authentik deploy/authentik-server --replicas=1
kubectl scale -n authentik deploy/authentik-worker --replicas=1
```

After ~5 min, log in to https://authentik.talos00 with your previous admin
credentials. All users, applications, providers, and groups should be intact.

### Grafana Dashboards / Datasources

Grafana itself runs from `emptyDir` (data is ephemeral pod-side), but
**dashboards and datasources are managed by `grafana-operator` as CRDs**
(`Dashboard`, `Datasource`). Velero captures these CRD instances in every
`critical-data-daily` backup.

```bash
# Restore just the Grafana CRDs from the latest backup
kubectl exec -n backup deploy/velero -- /velero restore create \
  --from-backup critical-data-daily-<TIMESTAMP> \
  --include-namespaces monitoring \
  --include-resources dashboards.grafana.integreatly.org,datasources.grafana.integreatly.org,grafanas.grafana.integreatly.org \
  --restore-volumes=false
```

### Whole-Namespace Restore

Nuclear option — restore an entire namespace from the most recent backup:

```bash
kubectl exec -n backup deploy/velero -- /velero restore create \
  --from-backup critical-data-daily-<TIMESTAMP> \
  --include-namespaces authentik \
  --restore-volumes=true \
  --existing-resource-policy=update
```

`existing-resource-policy=update` will update existing K8s resources to match
the backup. **Velero never overwrites a non-empty PVC** — you must delete the
PVC first if you want the volume data restored (see the authentik scenario).

## Verification

After any restore:

```bash
# Restore status
kubectl exec -n backup deploy/velero -- /velero restore get

# Per-PV restore status
kubectl get podvolumerestore -n backup -l velero.io/restore-name=<restore-name>

# Application health
kubectl get pod -n <namespace>
kubectl logs -n <namespace> <pod>
```

## Prerequisites for Restore

- MinIO must be reachable (check `kubectl get bsl -A` shows `Available`)
- Velero deployment + node-agent DaemonSet must be Running:
  ```
  kubectl get deploy,ds -n backup
  ```
- Source PVC's StorageClass (`local-path`) must exist
- Sufficient free space on the destination node's local-path directory
  (`/var/local-path-provisioner/`)

## Known Gotchas

- **PVC must not exist before restore.** Velero's fs-backup restores into a
  newly-created PVC. If the PVC already exists (even empty), Velero will skip
  volume restore. Always `kubectl delete pvc` first.
- **StatefulSet ordinal pinning.** Restore the PVC with the same name
  (`data-authentik-postgresql-0`) so the StatefulSet re-binds it.
- **Postgres requires consistent state.** The fs-backup is taken while
  Postgres is running — Kopia copies the on-disk files at one instant. Postgres
  recovery on startup will replay WAL and may complain about a "crashed"
  shutdown; this is normal and self-heals.
- **MinIO has no versioning enabled.** A single accidental `mc rm` on the
  velero bucket destroys all backups. Future hardening: enable bucket
  versioning + lifecycle rules in MinIO.

## Related Issues

<!-- Beads tracking for this doc -->
