# media-experimental config backup / restore

> Parent: [applications/media-experimental](../../) ·
> Rationale: [docs/02-architecture/embedded-db-migration-audit.md §4](../../../../docs/02-architecture/embedded-db-migration-audit.md#4-media-experimental--the-answer-is-tar-not-postgres-and-not-nfs) ·
> Ticket: TALOS-uml1 (EPIC 0 / TALOS-k62s)

## TL;DR

Twelve `local-path` config volumes pin this stack to one node. Measured: **161
files, 63 MB of real data across 60 Gi of claims**, compressing to an 18.5 MB
archive set. So the answer is `tar`, not twelve Postgres migrations and not NFS.

- **Back up:** `kubectl -n media-experimental create job --from=cronjob/config-backup config-backup-$(date +%s)`
- **Prove it restores:** `kubectl -n media-experimental create job --from=cronjob/config-restore-verify config-restore-verify-$(date +%s)`
- **Restore after a node reset:** see [the runbook](#runbook--surviving-a-node-reset) — it is not just the restore Job.

All three CronJobs ship **suspended**. They are manual procedures, not schedules.

**Both halves have been run end to end against the live cluster (2026-08-23):
backup `status=OK` 12/12, restore into throwaway PVCs `12 passed, 0 failed`.**
Verbatim output in [Proof](#proof--this-path-has-been-exercised-not-just-designed).

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

## Proof — this path has been exercised, not just designed

**Run on 2026-08-23 against the live cluster.** Both halves executed; the output
below is verbatim, not the expected output.

### Backup

`config-backup`, run `20260823T010514Z`, `VERIFY=full` (each archive is
re-extracted and re-checksummed before the app is scaled back up):

```
status=OK
```

12 of 12 volumes, 161 files, 62,998,382 bytes, 18.5 MB of archives, 76 seconds
wall clock for the whole stack.

### Restore

`config-restore-verify` restored all 12 archives into **fresh throwaway PVCs** —
generic ephemeral volumes named `<pod>-<volume>`, created empty when the pod
starts and deleted with it. No live config PVC was written to at any point.

```
=== restore from run 20260823T010514Z (/backup/20260823T010514Z) ===
=== FORCE=false QUIESCE=false ===
--- audiobookshelf-config (deployment audiobookshelf)
  owner/mode OK: 18 paths match capture -- uid:gid 0:0=18
  PASS: 16 files, 446217 bytes, all sha256 verified
--- audiobookshelf-metadata (deployment audiobookshelf)
  owner/mode OK: 12 paths match capture -- uid:gid 0:0=12
  PASS: 2 files, 13557 bytes, all sha256 verified
--- bindery-config (deployment bindery)
  owner/mode OK: 2 paths match capture -- uid:gid 0:0=1 1000:1000=1
  PASS: 1 files, 614400 bytes, all sha256 verified
--- booksonic-config (deployment booksonic)
  owner/mode OK: 34 paths match capture -- uid:gid 0:0=3 1000:1000=31
  PASS: 22 files, 473195 bytes, all sha256 verified
--- chaptarr-config (deployment chaptarr)
  owner/mode OK: 16 paths match capture -- uid:gid 1000:1000=16
  PASS: 11 files, 5566119 bytes, all sha256 verified
--- kavita-config (deployment kavita)
  owner/mode OK: 64 paths match capture -- uid:gid 0:0=64
  PASS: 49 files, 46940774 bytes, all sha256 verified
--- komga-config (deployment komga)
  owner/mode OK: 17 paths match capture -- uid:gid 0:0=17
  PASS: 14 files, 653091 bytes, all sha256 verified
--- libation-config (deployment libation)
  owner/mode OK: 3 paths match capture -- uid:gid 0:0=3
  PASS: 2 files, 750 bytes, all sha256 verified
--- librarr-config (deployment librarr)
  owner/mode OK: 3 paths match capture -- uid:gid 0:0=1 1000:1000=2
  PASS: 2 files, 182495 bytes, all sha256 verified
--- livrarr-config (deployment livrarr)
  owner/mode OK: 28 paths match capture -- uid:gid 1000:1000=28
  PASS: 26 files, 1874048 bytes, all sha256 verified
--- mylar3-config (deployment mylar3)
  owner/mode OK: 23 paths match capture -- uid:gid 1000:1000=23
  PASS: 12 files, 557018 bytes, all sha256 verified
--- storyteller-config (deployment storyteller)
  owner/mode OK: 9 paths match capture -- uid:gid 1000:1000=9
  PASS: 4 files, 5676718 bytes, all sha256 verified

=== restore summary: 12 passed, 0 failed (run 20260823T010514Z) ===
```

Every file's sha256 matched, every file count matched, and every path's
uid/gid/mode matched capture time.

### Read the uid:gid histogram correctly

**Not every volume should come back as 1000:1000.** kavita, komga,
audiobookshelf and libation are root-owned *at the source* — those containers run
as root — and this was confirmed straight from the live pods, independently of the
archive:

```
kavita           66 0:0
komga            21 0:0
audiobookshelf   18 0:0
storyteller       9 1000:1000
mylar3           23 1000:1000
chaptarr         20 1000:1000
```

(Live counts run slightly ahead of the snapshot because logs and WAL files were
written after 01:05. That is drift in the source, not a restore discrepancy.)

So the correct property is **restore reproduces captured ownership exactly**, over
a source that is a genuine mix. The volumes that carry 1000:1000 —
`chaptarr` 16/16, `livrarr` 28/28, `mylar3` 23/23, `storyteller` 9/9,
`booksonic` 31/34, `librarr` 2/3, `bindery` 1/2 — are what proves the `CAP_CHOWN`
fix holds. Before it, those all landed as `0:0`, and the apps run as PUID/PGID
1000. A blanket "everything must be 1000:1000" assertion would be wrong here and
would fail on four healthy volumes.

### bindery-config is covered

The embedded-DB audit recorded `bindery-config` as **unverified on disk** because
the image is distroless and could not be `exec`-ed into. That caveat does not
apply to this tooling: both jobs mount the PVC directly and never enter the app
container. bindery is in the backup (one 600 KB `bindery.db`, SQLite confirmed)
and in the restore above, PASS with checksum and ownership verified. It is fully
covered.

### What is deliberately not proven

Restoring into the **real** config PVCs. That step writes live app data and only
happens during the node reset itself (`TALOS-3gte`). It runs the same `restore.sh`
as the verification above — that shared code path is the point — with `QUIESCE=true`
and real PVCs instead of ephemeral ones.

The scratch PVCs and Jobs from this run were deleted afterwards, so the durable
evidence is this section rather than cluster state (Job history is TTL'd after
24 h regardless). Re-run it any time with the two commands in the [TL;DR](#tldr).

## Layout on the backup volume

```
/backup/
  LATEST                       # run id of the newest CLEAN run
  20260823T010514Z/
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

## Measured sizes (2026-08-23, captured by the backup job itself)

Bytes are the sum of regular-file sizes on the volume; archive is the gzipped tar.

| Volume | Deployment | Files | Bytes | Archive | Embedded store |
| --- | --- | ---: | ---: | ---: | --- |
| `kavita-config` | kavita | 49 | 46,940,774 | 17.0 MB | `kavita.db` + `cache.db` + WAL/SHM |
| `storyteller-config` | storyteller | 4 | 5,676,718 | 1.15 MB | `storyteller.db` + WAL |
| `chaptarr-config` | chaptarr | 11 | 5,566,119 | 845 KB | `chaptarr.db` (+cache/logs/staging) + WAL/SHM |
| `livrarr-config` | livrarr | 26 | 1,874,048 | 82 KB | `livrarr.db` + WAL/SHM (+ pre-migrate copies) |
| `komga-config` | komga | 14 | 653,091 | 27 KB | `database.sqlite` + `tasks.sqlite` + WAL/SHM |
| `bindery-config` | bindery | 1 | 614,400 | 25 KB | `bindery.db` — **SQLite, now confirmed on disk** |
| `mylar3-config` | mylar3 | 12 | 557,018 | 47 KB | `mylar.db` + `.mylar_maintenance.db` |
| `booksonic-config` | booksonic | 22 | 473,195 | 233 KB | HSQLDB `airsonic.script` + Lucene index + `.lck` |
| `audiobookshelf-config` | audiobookshelf | 16 | 446,217 | 20 KB | `absdatabase.sqlite` |
| `librarr-config` | librarr | 2 | 182,495 | 6 KB | `librarr.db` |
| `audiobookshelf-metadata` | audiobookshelf | 2 | 13,557 | 2 KB | none — two daily log files |
| `libation-config` | libation | 2 | 750 | 0.6 KB | none — `Settings.json` + `AccountsSettings.json` |
| **Total** | | **161** | **62,998,382** (60 MiB) | **18.5 MB** | across 60 Gi of provisioned claims |

`bindery-config` was recorded as *unverified* by the audit because the image is
distroless with no shell. Mounting the PVC from this job settles it: one 600 KB
`bindery.db`, SQLite, as upstream implied. It stays on `local-path`.

A whole-stack backup takes about **76 seconds**, of which each app is down for a
few seconds.

## The other half of the pin — nodeAffinity audit

Checked against the running cluster, not against the comments.

**There is exactly one `nodeAffinity` block in this stack, not one per app.** It
lives in [`../_instance/deployment.yaml`](../_instance/deployment.yaml) and all 11
Deployments inherit it; every live Deployment carries a byte-identical copy. No
app dir adds, overrides or removes it. (`bookorbit` is the exception — it
deliberately does not inherit `_instance` at all, and has no pin.)

Verified live for all 11: no `nodeSelector`, no tolerations, no `hostPath`, no
`hostNetwork`/`hostPID`, no device resources. The config PVC is the only thing
tying any of them to a node.

| App | Store on its local-path config volume | Other pin? | Co-location claim? | Verdict |
| --- | --- | --- | --- | --- |
| kavita | `kavita.db`, `cache.db` + WAL/SHM | none | none | Justified — by the PVC alone |
| komga | `database.sqlite`, `tasks.sqlite` + WAL/SHM | none | none | Justified — by the PVC alone |
| libation | **none** — 750 bytes of JSON | none | none | **Not justified by data.** See below |
| librarr | `librarr.db` | none | `QB_URL` → qbittorrent Service DNS | Justified — by the PVC alone |
| livrarr | `livrarr.db` + WAL/SHM | none | none | Justified — by the PVC alone |
| mylar3 | `mylar.db`, `.mylar_maintenance.db` | none | none | Justified — by the PVC alone |
| storyteller | `storyteller.db` + WAL | none | none | Justified — by the PVC alone |

`librarr` is the only workload in the stack that references another app, and the
reference is a ClusterIP Service name (`qbittorrent.media.svc.cluster.local`) —
qbittorrent itself runs on **talos06**, and sabnzbd on **talos02-gpu**. So the
sonarr-style "must sit next to its download client" justification would be false
here too. It is not claimed anywhere, but it is now checked.

### What was actually wrong with it

The affinity is not bogus — but it was **hard-coded to `talos03`**, which makes it
an *independent* pin that outlives the volume. That is precisely the sonarr
failure: the PVC was removed and the pod stayed welded to the node while every
check reported green. Worse for a restore: fresh `local-path` PVCs are
`WaitForFirstConsumer`, so after a reset the node is chosen by whichever pod binds
first, and a stale hostname here would send the apps somewhere the data is not.

It is now `${MEDIA_EXPERIMENTAL_NODE}` from `cluster-settings` (default `talos03`,
so nothing rolled), read by both the Deployments and the restore Job.

### Two volumes could leave local-path — and it is not worth doing

`libation-config` (750 bytes of JSON; Libation's actual `LibationContext.db` is
written to `/root/Libation/` **outside any volume**, which is a real data-loss bug
tracked separately) and `audiobookshelf-metadata` (two daily log files) hold no
database and would be safe on `fatboy-nfs-appdata`.

Moving them is still the wrong call: the node stays pinned until **all 12** are
gone, `audiobookshelf-config` next door is SQLite so that app cannot move anyway,
and peeling one app out of the shared `_instance` skeleton to drop its affinity is
the awkward surgery `bookorbit`'s comments already describe. 2 of 12 buys nothing.
Recorded here so it is not rediscovered.

### Known side effect of quiescing

`livrarr` writes a `livrarr.db.pre-migrate-<timestamp>` copy on every start, so
each backup run leaves one more of them on that volume. Harmless, but it grows.

---

## Related Issues

- TALOS-uml1 — this work
- TALOS-3gte — talos03 still has 14 node-bound PVs after the arr apps cleared
- TALOS-k62s — EPIC 0: un-node-bind PVCs before any control-plane reset
- TALOS-3hl8 — EPIC 3: node affinity cleanup
