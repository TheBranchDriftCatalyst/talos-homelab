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
kubectl scale -n <namespace> <workload> --replicas=0

# 4. Delete the empty/corrupt PVC so the restore can recreate it
kubectl delete pvc -n <namespace> <pvc-name>

# 5. Restore JUST that PVC + its PV
kubectl exec -n backup deploy/velero -- \
  /velero restore create restore-<name>-$(date +%s) \
    --from-backup critical-data-daily-<TIMESTAMP> \
    --include-namespaces <namespace> \
    --include-resources persistentvolumeclaims,persistentvolumes \
    --restore-volumes=true

# 6. Watch progress, then scale the workload back up and verify
kubectl exec -n backup deploy/velero -- /velero restore describe restore-<name>-<TS>
```

> **PostgreSQL is NOT restored via Velero.** Every CNPG cluster (authentik,
> forgejo, crowdsec, boomtime, homeassistant, linkwarden, plausible, zipline,
> guacamole) backs itself up to MinIO (`cnpg-backups` bucket) via
> barmanObjectStore WAL archiving + a daily `ScheduledBackup`, and its
> pods/PVCs carry `velero.io/exclude-from-backup=true` (via each Cluster's
> `inheritedMetadata`). See the CNPG scenario below.

## What Velero Actually Backs Up

Three schedules write to MinIO bucket `velero` (s3 endpoint
`http://minio.minio.svc.cluster.local`):

| Schedule | When | Scope | Retention | Volumes |
| --- | --- | --- | --- | --- |
| `daily-all` | 02:00 daily | media, media-private, scratch, home-automation, catalyst-llm, registry, vpn-gateway, authentik | 30d | Opt-in via `backup.velero.io/backup-volumes` annotation |
| `critical-data-daily` | 02:30 daily | authentik, monitoring, cilium-spire, dungeon-library (loki + CNPG excluded) | 30d | **All PVCs** (`defaultVolumesToFsBackup: true`) |
| `weekly-full` | 03:00 Sunday | All namespaces (sans kube-system, kube-public, kube-node-lease, flux-system, minio) | 90d | Opt-in via annotation |

Loki's PVC is labeled `velero.io/exclude-from-backup=true` (applied by the
`velero-loki-exclude-labeler` Job in the backup namespace) — Loki logs live in
S3, not on the PVC, so the PVC is just churny chunk cache. CNPG postgres
pods/PVCs carry the same label via each Cluster's `inheritedMetadata` — their
backups are CNPG's job, not Velero's (see below).

## Restore Scenarios

### CNPG PostgreSQL clusters (authentik, forgejo, crowdsec, …)

**Not a Velero restore.** CNPG clusters recover from their own barman backups
in MinIO (`cnpg-backups` bucket, per-cluster prefix) with point-in-time
recovery, via the barman-cloud CNPG-I plugin (the in-tree barmanObjectStore
API was removed in CNPG 1.30 — every cluster has an ObjectStore CR named
after it, e.g. `infrastructure/base/authentik/objectstore.yaml`). The
pattern: create a NEW Cluster that bootstraps from the object store, then
repoint the app (or rename back). Sketch for authentik:

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: authentik-postgres # same name = same -rw service, app untouched
  namespace: authentik
spec:
  # ... same storage/secret/plugins spec as infrastructure/base/authentik/postgres.yaml
  bootstrap:
    recovery:
      source: origin
      # optional PITR: recoveryTarget: { targetTime: "2026-08-12 08:00:00+00" }
  externalClusters:
    - name: origin
      plugin:
        name: barman-cloud.cloudnative-pg.io
        parameters:
          # the existing ObjectStore CR in this namespace
          barmanObjectName: authentik-postgres
          # prefix inside the store = the ORIGINAL cluster's name
          serverName: authentik-postgres
```

Verify backups exist first: `kubectl get backups.postgresql.cnpg.io -n <ns>`
(a `ScheduledBackup` per cluster runs daily; WAL archiving is continuous).
Full docs: https://cloudnative-pg.io/docs/devel/recovery/

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
  (e.g. `postgres-storage-postgres-0`) so the StatefulSet re-binds it.
- **Postgres requires consistent state.** The fs-backup is taken while
  Postgres is running — Kopia copies the on-disk files at one instant. Postgres
  recovery on startup will replay WAL and may complain about a "crashed"
  shutdown; this is normal and self-heals.
- **MinIO has no versioning enabled.** A single accidental `mc rm` on the
  velero bucket destroys all backups. Future hardening: enable bucket
  versioning + lifecycle rules in MinIO.

## Related Issues

<!-- Beads tracking for this doc -->
