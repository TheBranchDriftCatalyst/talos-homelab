# media-experimental config backup / restore

> Parent: [applications/media-experimental](../../) ·
> Rationale: [docs/02-architecture/embedded-db-migration-audit.md §4](../../../../docs/02-architecture/embedded-db-migration-audit.md#4-media-experimental--the-answer-is-tar-not-postgres-and-not-nfs) ·
> Ticket: TALOS-uml1 (EPIC 0 / TALOS-k62s)

## TL;DR

Twelve `local-path` config volumes pin this stack to one node. They hold **~67 MB
of real data across 60 Gi of claims**, so the answer is `tar`, not twelve Postgres
migrations and not NFS.

- **Back up:** `kubectl -n media-experimental create job --from=cronjob/config-backup config-backup-$(date +%s)`
- **Prove it restores:** `kubectl -n media-experimental create job --from=cronjob/config-restore-verify config-restore-verify-$(date +%s)`
- **Restore after a node reset:** see [the runbook](#runbook--surviving-a-node-reset) — it is not just the restore Job.

All three CronJobs ship **suspended**. They are manual procedures, not schedules.

## Why not NFS, and why not Postgres

Settled by the audit; do not re-litigate.

- **Not Postgres.** Only 3 of 12 apps support an external database at all, and
  migrating 3 of 12 does not un-pin the node. Partial migration buys nothing here.
- **Not NFS.** 9 of the 12 volumes hold live SQLite. This cluster already ran the
  SQLite-on-NFS experiment on the arr stack, hit locking problems, and migrated
  *off* NFS onto `local-path` in December 2025. The artifact is still on disk
  (`/config/radarr.db.nfs-backup`, 2025-12-20) and the reason is in the header of
  `applications/arr-stack/base/shared/db-migration-configmap.yaml`.

NFS is safe for *this* PVC because it only ever sees whole-file sequential
`tar.gz` writes. It is unsafe for the config volumes because those hold open
databases. Different workload, different answer.

## Why the archives land on `fatboy-nfs-appdata` and not MinIO

1. Off-cluster. `192.168.1.36:/volume1/appdata` survives a node reset and a
   cluster-wide outage. That is the whole point.
2. MinIO would land on the same NAS anyway — the tenant's own `data0` PVC *is*
   `fatboy-nfs-appdata`. S3 adds a hop (tenant pod on talos06) and a failure
   mode, not durability.
3. No credentials. MinIO would need an ESO-generated scoped user, and those
   regenerate on any spec change. A restore job is the worst place to discover
   that.
4. `tar` + `sha256sum` is the entire tool requirement. No `mc`, no secrets.

## What the jobs do

| CronJob | What it does | Touches live data? |
| --- | --- | --- |
| `config-backup` | Scales each Deployment to 0 **one at a time**, tars its volume, writes a checksum list, re-extracts the archive and re-checks every sha256, scales back up | Scales apps; writes only to the backup PVC |
| `config-restore` | Extracts archives back into the config volumes and verifies every file | **Yes** — writes app data |
| `config-restore-verify` | Same `restore.sh`, but into throwaway ephemeral volumes | No |

### SQLite consistency

Nine volumes hold live SQLite. A `tar` of an open database can capture the main
file and its `-wal` out of step and restore to something internally inconsistent.
So `backup.sh` scales the owning Deployment to 0 and **waits for its pods to
actually terminate** before reading the volume; the `.db`, `-wal` and `-shm` files
are then captured as one quiet set and SQLite replays the WAL on next open. If a
Deployment cannot be quiesced the volume is **skipped**, not tarred live — a
missing archive is recoverable, a corrupt one that looks fine is not.

Only one app is down at a time, for a few seconds each. If Flux reconciles the
Deployment back to `replicas: 1` mid-archive, the job notices and fails that
volume rather than trusting it.

### Verification

Three independent layers, because an untested restore is not a backup:

1. Every backup run **re-extracts each archive it just wrote** and re-checks every
   file against the checksum list (`VERIFY=full`).
2. `config-restore-verify` restores the whole set into fresh empty volumes and
   compares file counts and sha256 sums.
3. `config-restore` re-verifies after writing, and refuses to start on an archive
   whose own sha256 does not match the manifest.

Only a fully clean backup run is written to `BACKUP_ROOT/LATEST`, so a partial
run can never become what a restore silently picks up.

## Layout on the backup volume

```
/backup/
  LATEST                       # run id of the newest CLEAN run
  20260823T004500Z/
    MANIFEST.txt               # header + TSV: pvc, deployment, files, bytes, archive_bytes, archive_sha256
    komga-config.tar.gz
    komga-config.sha256        # sha256 of every file, relative paths
    komga-config.meta          # uid/gid/mode/type of every path
    ...
```

Retention keeps the newest `RETAIN` (default 5) runs.

## Knobs

Set as env on the CronJob (or on a one-off Job).

| Var | Default | Meaning |
| --- | --- | --- |
| `VOLUMES` | all 12 | Space-separated `deployment=pvc`. Narrow it to work on one app. |
| `QUIESCE` | `true` | Scale the owning Deployment to 0 first. |
| `VERIFY` | `full` | backup only: `full` re-extracts, `listing` checks the tar stream, `none` skips. |
| `RETAIN` | `5` | backup only: run directories to keep. |
| `RUN_ID` | newest clean | restore only: pin a specific run. |
| `FORCE` | `false` | restore only: `true` wipes a non-empty target first. **Interlock — leave it false unless you mean it.** |

To back up a single app:

```bash
kubectl -n media-experimental create job --from=cronjob/config-backup backup-komga-$(date +%s) --dry-run=client -o yaml \
  | yq '.spec.template.spec.containers[0].env |= map(select(.name != "VOLUMES")) + [{"name":"VOLUMES","value":"komga=komga-config"}]' \
  | kubectl apply -f -
```

## Runbook — surviving a node reset

The volumes are only half the pin. Both halves have to move together.

1. **Back up and prove it, before anything is touched.**

   ```bash
   kubectl -n media-experimental create job --from=cronjob/config-backup config-backup-$(date +%s)
   kubectl -n media-experimental logs -f job/config-backup-<id>          # expect status=OK
   kubectl -n media-experimental create job --from=cronjob/config-restore-verify config-restore-verify-$(date +%s)
   kubectl -n media-experimental logs -f job/config-restore-verify-<id>  # expect 12 passed, 0 failed
   ```

   Do not proceed unless both are clean.

2. **Scale the stack down** so nothing writes after the snapshot:

   ```bash
   kubectl -n media-experimental scale deploy --all --replicas=0
   ```

3. **Reset the node.** (Out of scope here — see the control-plane promotion runbook.)

4. **Delete the dead PVCs.** `local-path` PVs are `Delete` reclaim and node-affine;
   after a reset the PV objects survive but their data does not. Flux recreates the
   PVCs from git within one reconcile.

   ```bash
   kubectl -n media-experimental delete pvc audiobookshelf-config audiobookshelf-metadata \
     bindery-config booksonic-config chaptarr-config kavita-config komga-config \
     libation-config librarr-config livrarr-config mylar3-config storyteller-config
   flux reconcile kustomization media-experimental --with-source
   ```

5. **Point the stack at its new node.** Set `MEDIA_EXPERIMENTAL_NODE` in
   `clusters/catalyst-cluster/cluster-settings.yaml`, commit, and reconcile. This
   single key drives both the Deployments' `nodeAffinity` and the restore Job's,
   so the fresh `WaitForFirstConsumer` volumes provision on the node the pods are
   about to be sent to. Getting these out of step is the failure this design exists
   to prevent.

6. **Restore.**

   ```bash
   kubectl -n media-experimental create job --from=cronjob/config-restore config-restore-$(date +%s)
   kubectl -n media-experimental logs -f job/config-restore-<id>   # expect 12 passed, 0 failed
   ```

7. **Bring the stack back up** and spot-check an app's read progress / users.

   ```bash
   flux reconcile kustomization media-experimental --with-source
   ```

## Measured sizes (2026-08-22, live)

| Volume | Deployment | Real size | Embedded store |
| --- | --- | --- | --- |
| `kavita-config` | kavita | 46.6 MB | `kavita.db` + `cache.db` + WAL/SHM |
| `chaptarr-config` | chaptarr | 13.0 MB | `chaptarr.db` (+cache/logs/staging) + WAL/SHM |
| `storyteller-config` | storyteller | 5.5 MB | `storyteller.db` + WAL |
| `livrarr-config` | livrarr | 1.0 MB | `livrarr.db` (+ pre-migrate copies) |
| `komga-config` | komga | 764 KB | `database.sqlite` + `tasks.sqlite` + WAL/SHM |
| `booksonic-config` | booksonic | 576 KB | HSQLDB `airsonic.script` + Lucene index |
| `mylar3-config` | mylar3 | 568 KB | `mylar.db` |
| `audiobookshelf-config` | audiobookshelf | 456 KB | `absdatabase.sqlite` |
| `librarr-config` | librarr | 180 KB | `librarr.db` |
| `bindery-config` | bindery | 128 KB | SQLite (upstream is SQLite-only) |
| `libation-config` | libation | 8 KB | none — JSON config only |
| `audiobookshelf-metadata` | audiobookshelf | 8 KB | none |
| **Total** | | **~68 MB** | across 60 Gi of provisioned claims |

---

## Related Issues

- TALOS-uml1 — this work
- TALOS-3gte — talos03 still has 14 node-bound PVs after the arr apps cleared
- TALOS-k62s — EPIC 0: un-node-bind PVCs before any control-plane reset
- TALOS-3hl8 — EPIC 3: node affinity cleanup
