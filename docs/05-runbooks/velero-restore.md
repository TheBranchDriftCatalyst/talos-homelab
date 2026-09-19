---
type: runbook
status: current
covers:
  - backup
  - catalyst-cnpg-appdb
freshness: tracks-code
tickets:
  - TALOS-1psu
bluf: Velero restores a PVC only into a PVC that does not exist yet — scale the consumer down, delete the volume, then restore; and never reach for it to recover a Postgres database, which is CNPG's job.
---

# Velero Restore Runbook

How to restore PVC data from a Velero backup after a node or PVC loss.

Created in response to UPS-2026-05-09, which lost authentik PostgreSQL state
(no backups existed). This runbook is the recovery path for a repeat incident.

## TL;DR

1. **List the backups** and pick the newest successful one that predates the loss.
   ```bash
   kubectl exec -n backup deploy/velero -- /velero backup get
   kubectl exec -n backup deploy/velero -- \
     /velero backup describe <backup-name> --details
   ```
2. **Scale the consumer to zero.** Velero will not touch a volume that is in use.
   ```bash
   kubectl scale -n <namespace> <workload> --replicas=0
   ```
3. **Delete the empty or corrupt PVC.** This is the step people skip, and skipping it is
   why "the restore said Completed but the data is not there" happens.
   ```bash
   kubectl delete pvc -n <namespace> <pvc-name>
   ```
4. **Restore just that PVC and its PV.**
   ```bash
   kubectl exec -n backup deploy/velero -- \
     /velero restore create restore-<name>-$(date +%s) \
       --from-backup <backup-name> \
       --include-namespaces <namespace> \
       --include-resources persistentvolumeclaims,persistentvolumes \
       --restore-volumes=true
   ```
5. **Watch it, then scale back up and verify.**
   ```bash
   kubectl exec -n backup deploy/velero -- /velero restore describe <restore-name>
   ```

> **⚠️ PostgreSQL is NOT restored via Velero.** CNPG clusters back themselves up to MinIO
> (`cnpg-backups` bucket, one prefix per cluster) via barman WAL archiving plus a daily
> `ScheduledBackup`, and their pods and PVCs carry `velero.io/exclude-from-backup=true` — set
> by the `CatalystCNPGAppDB` composite's `inheritedMetadata`, and backstopped fleet-wide by
> `infrastructure/base/kyverno-policies/cnpg-velero-exclude.yaml`. A filesystem snapshot of a
> running Postgres data directory is a torn copy that looks like a backup and will not restore.
> See the CNPG scenario below.
>
> **⚠️ The exclusion label removes coverage; it does not move it.** A CNPG cluster carrying
> `velero.io/exclude-from-backup=true` _without_ a barman plugin, an ObjectStore and a
> ScheduledBackup has **no backup at all**, silently, and the failure only surfaces at restore
> time. That is TALOS-1psu, found in production. Before trusting any Postgres recovery, confirm
> `kubectl get backups.postgresql.cnpg.io -n <ns>` actually returns something.

## What Velero Actually Backs Up

Three schedules write to the MinIO bucket `velero` (S3 endpoint
`http://minio.minio.svc.cluster.local`). They are declared in
`infrastructure/base/backup/velero.yaml`; read the namespace lists there rather than from here,
because a namespace added to a schedule and not to this file is exactly the drift that makes a
runbook lie.

What is durable about them is the **shape**, which is what you need to reason about under
pressure:

| Schedule              | Volume policy                                                                             | What that means for you                                                              |
| --------------------- | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `daily-all`           | **Opt-in** — only volumes named in the pod's `backup.velero.io/backup-volumes` annotation | A new PVC in an in-scope namespace is **not** backed up until someone annotates it   |
| `critical-data-daily` | **Opt-out** — `defaultVolumesToFsBackup: true`, every PVC in scope                        | Chosen because the upstream Helm charts in these namespaces are not ours to annotate |
| `weekly-full`         | Opt-in, all namespaces bar a short exclusion list                                         | Broad object coverage, thin volume coverage. Do not mistake it for a data backup     |

Two exclusions are deliberate and both are invisible unless you know to look:

- **Loki's PVC** is labelled `velero.io/exclude-from-backup=true` by the
  `velero-loki-exclude-labeler` Job (`infrastructure/base/backup/loki-backup-exclude.yaml`).
  Loki's logs live in S3; the PVC is churny chunk cache and backing it up buys nothing.
- **CNPG pods and PVCs** carry the same label, per the warning above.

> **⚠️ `local-path` PVs are not backed up at all.** They are `hostPath` volumes and Velero's
> filesystem backup skips `hostPath` by design — even when the volume is explicitly named in
> `backup.velero.io/backup-volumes`. It logs a warning per volume and the backup still reports
> `Completed`. Check the PV's **source type**, not its backup history. See
> [README.md](README.md) for the standing version of this gotcha.

## Restore Scenarios

### CNPG PostgreSQL clusters

**Not a Velero restore, and no longer a hand-written `Cluster` either.** Every Postgres
database in this repo is declared as a `CatalystCNPGAppDB` (e.g.
`infrastructure/base/authentik/appdb.yaml`), and the Crossplane composite in
`infrastructure/base/catalyst-cnpg-appdb/` renders the CNPG `Cluster`, its barman `ObjectStore`
and the `ScheduledBackup` from it.

That changes the recovery mechanics in a way worth stating plainly: **do not create a bare
`kind: Cluster` alongside a composite-managed database.** The composite owns that object and
will fight you for it. Recovery goes through the composite, or through a deliberately
differently-named cluster that you then repoint.

Before anything else, confirm there is something to recover from:

```bash
kubectl get backups.postgresql.cnpg.io -n <namespace>
kubectl get objectstores.barmancloud.cnpg.io -n <namespace>
```

The object store prefix inside `cnpg-backups` is the **original cluster's** name — that is the
`serverName` a recovery bootstrap must point at, and it does not change when you rename the
cluster you are restoring _into_.

Upstream procedure (recovery bootstrap, optional PITR target):
<https://cloudnative-pg.io/docs/devel/recovery/>

One cluster-specific trap: authentik's `credentialsSecret` is load-bearing. Authentik's own
configuration reads `authentik-postgres-app`, so a rebuild that lets CNPG mint a fresh random
password locks the identity provider out of its own database — and every service behind SSO
with it. The reasoning is recorded in `infrastructure/base/authentik/appdb.yaml`; read it before
recovering that one.

### Grafana Dashboards / Datasources

Grafana itself has **no persistence** — `/var/lib/grafana` is an `emptyDir`, deliberately. All
its state is code: dashboards are `GrafanaDashboard` CRs and datasources are `GrafanaDatasource`
CRs, re-pushed by grafana-operator on every restart. A UI-only edit does not survive a pod roll
and is not something a restore can bring back.

So the thing worth restoring is the CRs, which `critical-data-daily` captures with the rest of
the `monitoring` namespace:

```bash
kubectl exec -n backup deploy/velero -- /velero restore create \
  --from-backup <backup-name> \
  --include-namespaces monitoring \
  --include-resources grafanadashboards.grafana.integreatly.org,grafanadatasources.grafana.integreatly.org,grafanas.grafana.integreatly.org \
  --restore-volumes=false
```

Note the resource names: the kinds are `GrafanaDashboard` and `GrafanaDatasource`, so the plural
resource names are `grafanadashboards` / `grafanadatasources`. `dashboards.grafana.integreatly.org`
is not a resource in this cluster and `--include-resources` will simply match nothing —
restoring successfully, and restoring nothing.

The better answer is usually not to restore at all: re-apply the CRs from
`infrastructure/base/monitoring/grafana-dashboards/` via Flux.

### Whole-Namespace Restore

Nuclear option — restore an entire namespace from the most recent backup:

```bash
kubectl exec -n backup deploy/velero -- /velero restore create \
  --from-backup <backup-name> \
  --include-namespaces <namespace> \
  --restore-volumes=true \
  --existing-resource-policy=update
```

`existing-resource-policy=update` updates existing Kubernetes resources to match the backup.
**Velero never overwrites a non-empty PVC** — you must delete the PVC first if you want the
volume data restored.

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

The `velero-dr` suite (`infrastructure/base/backup/tests/test_velero_dr.py`) exercises a
backup → delete → restore round trip against a canary and asserts no data loss. Run it armed
(`task test:dr-armed`) when you want to prove the machinery works _before_ you need it.

## Prerequisites for Restore

- MinIO must be reachable — `kubectl get bsl -A` shows the location `Available`
- Velero deployment and the node-agent DaemonSet must be Running:
  ```bash
  kubectl get deploy,ds -n backup
  ```
- The source PVC's StorageClass must exist
- Sufficient free space on the destination node — for `local-path` that is
  `/var/lib/rancher/local-path-provisioner`, the path declared in
  `infrastructure/base/storage/local-path-provisioner.yaml`

## Known Gotchas

- **PVC must not exist before restore.** Velero's fs-backup restores into a newly-created PVC.
  If the PVC already exists (even empty), Velero skips the volume restore — and the restore
  still reports success. Always `kubectl delete pvc` first.
- **StatefulSet ordinal pinning.** Restore the PVC with the same name
  (e.g. `postgres-storage-postgres-0`) so the StatefulSet re-binds it.
- **fs-backup of a running database is a crash-consistent copy.** Kopia copies the on-disk files
  at one instant, so recovery on startup replays WAL and may complain about an unclean shutdown.
  For Postgres this is why CNPG owns the backup instead; for anything else, expect the replay.
- **The `velero` bucket has no versioning.** Versioning is enabled on the `dagster` bucket only
  (`infrastructure/base/minio/tenant.yaml`), so a single accidental `mc rm` against the velero
  bucket destroys every backup with no undo. Hardening it is outstanding work.

---

## Related Issues

<!-- Beads tracking for this doc -->

- TALOS-1psu — a CNPG cluster excluded from Velero while having no CNPG backup of its own
