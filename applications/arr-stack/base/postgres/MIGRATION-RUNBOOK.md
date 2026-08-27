# SQLite -> CNPG Postgres migration for the \*arr apps

Proven end-to-end on **Prowlarr** (TALOS-93cz), **Radarr** (TALOS-l4uo) and
**Sonarr** (TALOS-eaa4), all on 2026-08-22, against the same `arr-postgres`
cluster. The steps are the same for all three; the *delete list* was different
for all three. Read the whole thing before starting another one — the deviations
from the Servarr wiki are the parts that matter.

## TL;DR

0. All three `*arr` apps are done. Plex and Jellyfin still hold `db-local` PVs
   (both pinned to talos02-gpu) and still use `shared/db-migration-configmap.yaml`;
   they are the remaining candidates if this is ever repeated.
1. Add two `Database` CRs (`<app>-main`, `<app>-log`) to `databases.yaml`.
2. Back up the SQLite file with `sqlite3 .backup` — **from the local-path PV**.
3. Add `<APP>__POSTGRES__*` env to the Deployment and let it start once. This
   builds the schema; pgloader loads data only and will not create it.
4. Suspend the Flux Kustomization, scale the app to 0.
5. Delete the seeded rows that collide on primary key.
6. Run pgloader with `--with "quote identifiers"`.
7. Compare row counts per table, then scale up and resume Flux.
8. **Get the migration validated by a human**, then unbind: remove the volume,
   the volumeMount and the `<app>-db-local` PVC, and delete the PV.

Until step 8 the rollback is deleting the env block and the SQLite file is only
ever read. Step 8 is the one that cannot be undone, and it is also the only step
that actually un-node-binds the app.

---

## The data-loss trap

`shared/db-migration-configmap.yaml` copies the SQLite DB from the NFS config
volume to a local-path PV **once**, renames the NFS original to
`<app>.db.nfs-backup`, and symlinks `/config/<app>.db` at the local copy. From
then on the local-path copy is the only live database and the NFS one is frozen
at first-migration time.

Reading the wrong file succeeds silently. Prowlarr's numbers:

| file | size | mtime |
| --- | ---: | --- |
| `/db-local/prowlarr.db` (**authoritative**) | 8 138 752 B | 2026-08-22 |
| `/config/prowlarr.db` | symlink -> `/db-local/prowlarr.db` | |
| `/config/prowlarr.db.nfs-backup` (**stale trap**) | 176 128 B | 2025-12-20 |

And Radarr's, where the gap is wider still:

| file | size | mtime |
| --- | ---: | --- |
| `/db-local/radarr.db` (**authoritative**) | 267 309 056 B | 2026-08-22 |
| `/config/radarr.db` | symlink -> `/db-local/radarr.db` | |
| `/config/radarr.db.nfs-backup` (**stale trap**) | 671 744 B | 2025-12-20 |

And Sonarr's, which is the dangerous one:

| file | size | mtime |
| --- | ---: | --- |
| `/db-local/sonarr.db` (**authoritative**) | 548 564 992 B | 2026-08-22 |
| `/config/sonarr.db` | symlink -> `/db-local/sonarr.db` | |
| `/config/sonarr.db.nfs-backup` (**stale trap**) | 475 467 776 B | 2025-12-20 |

Prove it before you load anything. `stat` plus `sha256sum` settles it in one
command — but **read the mtime, not the size.** The size ratio was 46x for
Prowlarr and 398x for Radarr, either of which screams at you. Sonarr's trap file
is 87% the size of the live one, which screams nothing at all: it is a real
Sonarr database with a real library in it, eight months stale. A gap you can
eyeball is luck, not a check. The mtime gap is eight months in all three cases.
Then sanity-check the row counts against what the app's own API reports. Loading
the trap file would have cost 5 393 movies on Radarr and imported 0.

Check the app version at the same time; Postgres needs Radarr/Sonarr
>= v4.1.0.6133. `GET /api/v3/system/status` reports `version` and, once the
cutover lands, `databaseType` — which is how you confirm the switch actually
flipped rather than assuming it from the env var being present.

## Helper pod

The migration needs `sqlite3`, which none of the app images carry. The PV has
`nodeAffinity` to the node holding the data, so the scheduler places this
correctly on its own; RWO permits a second pod on the same node.

```yaml
apiVersion: v1
kind: Pod
metadata: {name: prowlarr-sqlite-tools, namespace: media}
spec:
  restartPolicy: Never
  securityContext: {fsGroup: 1000, supplementalGroups: [100, 1000]}
  containers:
    - name: tools
      image: alpine:3.22
      command: ["/bin/sh", "-c", "apk add --no-cache sqlite curl jq && sleep 3600"]
      volumeMounts:
        - {name: db-local, mountPath: /db-local}
        - {name: config, mountPath: /config}
  volumes:
    - {name: db-local, persistentVolumeClaim: {claimName: prowlarr-db-local}}
    - {name: config, persistentVolumeClaim: {claimName: prowlarr-config}}
```

## Step 1 — back up

`cp` is not a backup of a live SQLite database; the WAL is not in the file.
`.backup` takes a consistent online snapshot:

```sh
sqlite3 /db-local/prowlarr.db ".backup '/config/pg-migration-backup/prowlarr-$(date -u +%Y%m%dT%H%M%SZ).db'"
sqlite3 /config/pg-migration-backup/prowlarr-<ts>.db 'PRAGMA integrity_check;'
```

`/config` is the NFS PVC — a different failure domain from the local-path PV,
and inside Velero's `backup-volumes` annotation. Pull a copy off-cluster with
`kubectl cp` too.

## Step 2 — create the schema

Add the env block to the Deployment (see `prowlarr/deployment.yaml`) and let
Flux roll it. `<APP>__POSTGRES__HOST` is the single switch that flips
`ConnectionStringFactory` from SQLite to Postgres; `config.xml` is never edited,
so the API key other apps authenticate with does not change.

**Take the row counts AFTER this rollout, not before.** A clean shutdown
checkpoints the WAL into the main file — Prowlarr's grew 8 138 752 -> 8 142 848 B
and gained one History row on the way down. From that moment the file is frozen
and it is the exact input pgloader will read.

## Step 3 — delete the seeded rows

Suspend Flux first or it will restart the app underneath you:

```sh
flux suspend kustomization arr-stack
kubectl -n media scale deploy prowlarr --replicas=0
```

The Servarr wiki's delete list is written for Radarr/Sonarr. **Do not run it
blind.** Query what the fresh schema actually seeded:

```sql
SELECT relname, n_live_tup FROM pg_stat_user_tables WHERE n_live_tup > 0;
```

`n_live_tup` is a planner **estimate**, fine for "which tables did the app
seed", never for verification. Everywhere a number has to be trusted, use exact
counts — build the query rather than typing twenty of them:

```sql
SELECT string_agg(format('SELECT %L AS t, COUNT(*) AS n FROM %I', tablename, tablename), ' UNION ALL ')
FROM pg_tables WHERE schemaname = 'public';
```

What that returned for Prowlarr:

| table | wiki list | exists in Prowlarr | seeded rows |
| --- | --- | --- | ---: |
| `QualityProfiles` | yes | **no** | — |
| `QualityDefinitions` | yes | **no** | — |
| `DelayProfiles` | yes | **no** | — |
| `Metadata` | yes | **no** | — |
| `Config` | yes | yes | 0 (delete is a no-op) |
| `VersionInfo` | yes | yes | 41 |
| `ScheduledTasks` | yes | yes | 8 |
| `AppSyncProfiles` | **no** | yes | 1 |

Four of the wiki's seven tables do not exist in Prowlarr at all — it is an
indexer manager, not a library app. And `AppSyncProfiles`, which the wiki does
not mention, seeds the "Standard" profile at `Id=1` and **does** collide.

And what it returned for Radarr (TALOS-l4uo), which is a library app and so has
the four Prowlarr lacked:

| table | wiki list | exists in Radarr | seeded rows |
| --- | --- | --- | ---: |
| `QualityProfiles` | yes | yes | 6 |
| `QualityDefinitions` | yes | yes | 30 |
| `DelayProfiles` | yes | yes | 1 |
| `Metadata` | yes | yes | 5 |
| `Config` | yes | yes | 0 (delete is a no-op) |
| `VersionInfo` | yes | yes | 138 |
| `ScheduledTasks` | yes | yes | 11 |
| `NamingConfig` | **no** | yes | 1 |
| `Commands` | **no** | yes | 2 |
| `AppSyncProfiles` | **no** | **no** | — |

**Two tables outside the wiki's list seed rows in Radarr and both collide.**
`NamingConfig` holds the single naming-format row at `Id=1`, and `Commands` gets
two rows from the startup tasks the app fires the moment it comes up — the fresh
schema is only "empty" until the app touches it. Neither is in the wiki, neither
was in Prowlarr's list, and Prowlarr's `AppSyncProfiles` does not exist here.

And Sonarr (TALOS-eaa4), which is a library app like Radarr and has the same 38
tables — and still needs a *different* list:

| table | wiki list | exists in Sonarr | seeded rows |
| --- | --- | --- | ---: |
| `QualityProfiles` | yes | yes | 6 |
| `QualityDefinitions` | yes | yes | 22 |
| `DelayProfiles` | yes | yes | 1 |
| `Metadata` | yes | yes | 5 |
| `Config` | yes | yes | **1 — a real collision, not a no-op** |
| `VersionInfo` | yes | yes | 211 |
| `ScheduledTasks` | yes | yes | 11 |
| `Commands` | **no** | yes | 2 |
| `NamingConfig` | **no** | yes | **0 — do not delete, unlike Radarr** |
| `AppSyncProfiles` | **no** | **no** | — |

Eight statements, and **the two differences from Radarr both run the opposite
way**, which is exactly why the union of the previous lists is not the answer:

- `Config` seeds one row in Sonarr (`Id=1`, `Key=enablecompleteddownloadhandling`)
  and genuinely collides. In Prowlarr and Radarr the same `DELETE` was a
  documented no-op. Carrying "it's a no-op" forward would have left a live
  primary-key collision in the load.
- `NamingConfig` seeds one row in Radarr and **zero** in Sonarr, so here the
  delete is the no-op. Two library apps, same table, opposite behaviour.

So the delete list is different for every app, and the union of the previous two
is still not the right answer for the next one. **Re-derive it. Every time.**
`Commands` in particular grows while the app is running, so derive it in the same
suspended window in which you delete — not before you scale to 0.

## Step 4 — pgloader

`--with "quote identifiers"` is mandatory; the schema is PascalCase.

```yaml
apiVersion: batch/v1
kind: Job
metadata: {name: prowlarr-sqlite-to-pg, namespace: media}
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: pgloader
          image: ghcr.io/roxedus/pgloader:latest
          command: ["/bin/sh", "-c"]
          args:
            - |
              set -eu
              cp -v /db-local/prowlarr.db /work/prowlarr.db
              PW=$(printf '%s' "$PGPASSWORD" | sed -e 's/%/%25/g' -e 's/:/%3A/g' -e 's|/|%2F|g' -e 's/@/%40/g' -e 's/?/%3F/g' -e 's/#/%23/g')
              exec pgloader --with "quote identifiers" --with "data only" \
                --with "prefetch rows = 100" --with "batch size = 1MB" \
                /work/prowlarr.db \
                "postgresql://${PGUSER}:${PW}@arr-postgres-rw:5432/prowlarr-main"
          env:
            - name: PGUSER
              valueFrom: {secretKeyRef: {name: arr-postgres-app, key: username}}
            - name: PGPASSWORD
              valueFrom: {secretKeyRef: {name: arr-postgres-app, key: password}}
          volumeMounts:
            - {name: db-local, mountPath: /db-local, readOnly: true}
            - {name: work, mountPath: /work}
      volumes:
        - {name: db-local, persistentVolumeClaim: {claimName: prowlarr-db-local, readOnly: true}}
        - {name: work, emptyDir: {}}
```

Three details worth keeping:

- **The Job copies only `<app>.db`, and deliberately leaves `-wal` behind — so
  check that the `-wal` is empty of anything that matters.** A clean shutdown is
  supposed to checkpoint and remove it, but Sonarr's pod left a 123 KB
  `sonarr.db-wal` on the volume after scaling to 0. Residue like that is
  normally already-checkpointed, but "normally" is not verification, and a bare
  `cp` of the main file would silently drop anything that was not. Prove it
  costs one command: copy the main file somewhere scratch, count every table
  against the WAL-inclusive counts, and diff. For Sonarr they were identical, so
  the runbook's `cp` was safe. If they had differed, the fix is to load from the
  `sqlite3 .backup` copy instead — it is a single self-contained file with no
  WAL by construction — not to checkpoint the authoritative file, which is
  supposed to stay read-only until the human validates.
- It copies to an `emptyDir` and mounts the PV `readOnly`, so pgloader never
  holds a writable handle on the authoritative file. Opening a SQLite DB
  read-write can create `-shm`/`-wal` siblings; the rollback copy stays pristine
  this way.
- The `Id` columns are `serial`, not identity. A data-only load inserts explicit
  `Id`s without advancing the sequence, which would make the app's next INSERT
  fail on a duplicate key. **pgloader handles this** — look for
  `Reset Sequences  0  19` in its summary and verify.

  Do not verify with `pg_sequences`: it has no `is_called` column, and
  `is_called` is the whole question. `last_value = max(Id)` with
  `is_called = true` is the CORRECT state — the next `nextval()` returns
  `max(Id) + 1`, so the equality is not an off-by-one. The failure mode is
  `is_called = false`, where `nextval()` hands back `last_value` itself and
  collides with the row already holding it. Read it off the sequence relations,
  all of them at once:

```sql
SELECT string_agg(
         format('SELECT %L AS seq, last_value, is_called FROM %I', relname, relname),
         ' UNION ALL ')
FROM pg_class WHERE relkind = 'S' AND relnamespace = 'public'::regnamespace;
-- then run what that prints
```

  All 19 of Prowlarr's and all 40 of Radarr's came back `is_called = t` with
  `last_value = max(Id)`, as did all 37 of Sonarr's. Prowlarr's `History` and
  `Commands` sequences have since advanced past their post-load values under live
  use with no duplicate-key errors, which is the empirical version of the same
  check.

  **Do not check sequences by guessing the name `<Table>_Id_seq`.** Sonarr has 38
  tables and 37 sequences, and the arithmetic lies about which table is missing
  one. Three tables do not own a sequence *called after themselves*:

  | table | its actual sequence |
  | --- | --- |
  | `Blocklist` | `Blacklist_Id_seq` — renamed table, sequence kept the old name |
  | `ReleaseProfiles` | `Restrictions_Id_seq` — same |
  | `VersionInfo` | none; it is keyed on `Version`, not an `Id` |

  Only `VersionInfo` is genuinely sequence-less. A name-pattern check reports
  three gaps and two of them are phantoms — while a real gap on `Blocklist`
  (93 rows, `max(Id)` 870) would be a duplicate-key error on the next blocklist
  write. pgloader resolves the owning sequence properly rather than guessing, and
  set `Blacklist_Id_seq` to `last_value = 870, is_called = t`. Ask Postgres which
  sequence owns the column — read `column_default` from
  `information_schema.columns`, or use `pg_get_serial_sequence` — and enumerate
  from `pg_class WHERE relkind = 'S'`, never from the table names.

Radarr and Sonarr are 267 MB and 549 MB against Prowlarr's 8 MB, so budget
minutes rather than the half-second this took. In the event Radarr's 496 288
rows loaded in 10.2 s, so Sonarr should be comfortable too.

The type-cast `WARNING`s (`bigserial` vs `integer`, `bigint` vs `boolean`) are
expected and benign: SQLite has no native boolean and pgloader describes its own
inferred type before deferring to the existing column.

## Step 5 — verify

`pgloader exited 0` is not verification. Three checks:

1. **Exact row counts per table** (`COUNT(*)`, not `n_live_tup`), SQLite vs
   Postgres, against the frozen source file. Read a number that looks
   engineered rather than measured — Prowlarr's Postgres `History` landed on
   16384, exactly 2^14 — and chase it to the source before accepting it. That
   one was a coincidence plus five rows of live use since cutover, but a
   power-of-two row count is precisely what a silent truncation looks like.
2. **The app's own API**, which proves it is reading what was loaded —
   `/api/v1/indexer`, `/api/v1/applications`, `/api/v1/history?pageSize=1`
   (`totalRecords`).
3. **`POST /api/v1/indexer/testall`.** The strongest check available: indexer
   credentials are encrypted with keys stored in `Config`
   (`rijndaelpassphrase`, `hmacpassphrase`, and the salts). If those rows
   migrated correctly the tests pass; if they did not, every indexer fails to
   authenticate. `POST /api/v3/downloadclient/testall` proves the same thing
   about the other set of stored credentials. Both only test *enabled*
   providers, so a `1/1` pass on an app with two download clients is not a
   partial failure — check `enable` before reading the ratio as a problem.
4. **Content digests, not just counts.** Equal row counts do not prove equal
   rows. Select the salient columns from both sides, sort, and hash:

   ```sh
   sqlite3 -separator '|' radarr.db 'SELECT "Id","Path","QualityProfileId","Monitored" FROM "Movies";' | sort | shasum -a 256
   psql -F'|' -At -c 'SELECT "Id","Path","QualityProfileId","Monitored"::int FROM "Movies";' | sort | shasum -a 256
   ```

   Cast Postgres booleans back to `int` — SQLite stores them as `0`/`1` and
   `psql` renders them `t`/`f`, so an uncast comparison fails on formatting and
   tells you nothing. Radarr matched on all eight tables checked this way.

Confirm the app is on Postgres and not still on SQLite:

```sql
SELECT datname, usename, client_addr FROM pg_stat_activity WHERE datname LIKE 'prowlarr%';
```

Both `-main` and `-log` should show a connection from the app's pod IP.

Then bring it back:

```sh
kubectl -n media scale deploy prowlarr --replicas=1
flux resume kustomization arr-stack
```

If another agent or person is working in the same `arr-stack` Kustomization,
tell them about the suspend window. While it is suspended their
`flux reconcile kustomization arr-stack` reports success and applies nothing,
which reads exactly like a change that did not take.

### What Radarr came out at

267 MB, 41 tables, **496 288 rows, 0 errors, 10.2 s** — the prefetch and batch
flags are doing real work at this size. Every table matched exactly; the numbers
worth naming are `Movies` 5 393, `MovieMetadata` 6 533, `MovieFiles` 5 015,
`History` 4 722, `Credits` 272 664, `MovieTranslations` 152 582,
`QualityProfiles` 6.

`Reset Sequences 0 40` leaves every sequence with `last_value = max(Id)` and
`is_called = true`, which is correct — the next `nextval()` returns `max(Id)+1`.
Do not read `last_value = max(Id)` as an off-by-one; the failure to look for is
`is_called = false`, and `pg_sequences` does not expose that column. Read it off
the sequence relation itself:

```sql
SELECT last_value, is_called FROM "Movies_Id_seq";
```

### What Sonarr came out at

549 MB, 38 tables, **166 321 rows, 0 errors, 12.3 s, 516.2 MB** — larger file
than Radarr, a third of the rows. Sonarr's bulk is in wide rows, not many rows:
`EpisodeFiles` is 25 191 rows and 452 MB of that 516 MB, all of it `MediaInfo`
blobs. Do not use row count as a proxy for how long a load will take.

Every one of the 38 tables matched exactly. The numbers worth naming are
`Series` 845, `Episodes` 55 398, `EpisodeFiles` 25 191, `History` 36 780,
`SceneMappings` 15 630, `MetadataFiles` 15 122, `DownloadHistory` 11 879,
`Commands` 3 628, `QualityProfiles` 7, `Indexers` 1, `DownloadClients` 1,
`RootFolders` 1. `Reset Sequences 0 37`, all `is_called = t`.

Content digests matched on `Series`, `Episodes`, `EpisodeFiles`, `History`,
`QualityProfiles`, `Indexers`, `DownloadClients` and `RootFolders`. Keep
timestamp columns *out* of the digest — SQLite stores them as text and Postgres
renders them its own way, so a `Date` or `Added` column fails the comparison on
formatting and tells you nothing, the same trap as uncast booleans.

`Commands` is a live counter, and that is useful: it read 3 628 in SQLite,
loaded 3 628, then fell to 3 616 within a minute of the app coming up as Sonarr
trimmed old rows, and climbed again from there. **A `Commands` count that moves
after cutover is the cheapest proof that writes are landing in Postgres** — pair
it with the SQLite file's mtime staying frozen, which is the proof they are not
landing in the old database.

## Storage choice — reclaim policies are not uniform

Worth knowing before picking a storage class for the CNPG cluster:

| StorageClass | reclaimPolicy | binding | default |
| --- | --- | --- | --- |
| `local-path` | **Delete** | WaitForFirstConsumer | **yes** |
| `fatboy-nfs-appdata` | Retain | Immediate | no |
| `synology-nfs` | Retain | Immediate | no |

The existing `rec-media-<app>-db-local` PVs are `Retain`, but that is
hand-written on each PV, not inherited — someone protected them deliberately
after the 2026-05-09 UPS incident (see their `recovery.catalyst/incident`
label). **A new PV provisioned on `local-path` gets the class default, which is
`Delete`.** Putting the Postgres cluster there would have created volumes with
*less* protection than the SQLite PVs it was replacing, on the cluster's default
class, quietly.

`arr-postgres` is on `fatboy-nfs-appdata`, which carries `Retain`, and all three
of its PVs were verified `Retain` after provisioning. That was the primary
reason for the choice; node-independence and the "never `instances: 1` on
`local-path`" rule point the same way.

## Decisions taken for Prowlarr

- **The `-log` database was created but its data was not migrated.** Servarr
  calls log migration optional. The logs are rolling debug output with no
  operational value, and replaying them would push churn into a WAL stream that
  is archived to MinIO and shared with Radarr and Sonarr. The app repopulates it.

- **The old PVC was kept BOUND and mounted at `/db-local-old`, `readOnly`, until
  a human validated the migration — then unbound entirely.** Two stages on
  purpose. While it was mounted, rollback was one revert away and nothing could
  garbage-collect it; moving it off `/db-local` and making it `readOnly` meant
  the app could not reach the stale database even by accident. Do not skip
  straight to the unbind.

- **The `migrate-db` initContainer was removed at the remount, and this needed
  care.** `migrate-arr.sh` does not only copy — it also symlinks
  `/config/<app>.db` at `DB_LOCAL_PATH`. Keeping the container and repointing
  `DB_LOCAL_PATH` to `/db-local-old` would have had it rewrite that symlink to a
  path that *is* mounted, handing the app back a live read/write route to the
  stale database under exactly the name it looks for. Deleting the container is
  what stops the symlink being recreated. Nothing else consumed it: no backup
  CronJob reads prowlarr's `*.db`, and the Velero annotation was narrowed to
  `config`.

- **The three orphaned `/config/<app>.db*` symlinks were renamed to
  `*.sqlite-era`,** so nothing dangles where the app would look for a database.
  They are left in place as a record; `<app>.db.nfs-backup`, the `.replaced-*`
  files and the SQLite-era `logs.db` are untouched too.

- **Deleting the PVC is a git operation, deleting the PV is not.** Removing the
  PVC from `pvc.yaml` is what deletes it — the arr-stack Kustomization runs
  `prune: true`. The PV (`rec-media-<app>-db-local`) is hand-written in
  `recovery/pv-recovery-2026-05-09.yaml`, which no Kustomization applies, so it
  has to go by hand after the PVC is pruned and it goes `Released`.

- **The host directory is NOT reclaimed, and that is correct.** `Retain` means
  the kubelet leaves the data alone, and because these PVs were hand-written
  rather than provisioned, `local-path-provisioner` has no claim on them either.
  After deleting the PV, `prowlarr.db` was still on talos02-gpu at
  `/var/lib/rancher/local-path-provisioner/pvc-…_media_prowlarr-db-local`,
  unreferenced by any Kubernetes object. Verify with
  `talosctl -n <node-ip> list -l <path>` and either clean it deliberately or
  leave it as a last cold copy — but know which you chose.

- **The `-log` database was created but its data was not migrated.** Servarr
  calls log migration optional. The logs are rolling debug output with no
  operational value, and replaying them would push churn into a WAL stream that
  is archived to MinIO and shared with Radarr and Sonarr. The app repopulates it.

- `shared/db-migration-configmap.yaml` is untouched — Sonarr, Radarr, Plex and
  Jellyfin still use it.

## Proving the app is actually un-node-bound

> **ONLY AFTER THE UNBIND.** This test is meaningless — worse, actively
> misleading — while the app still mounts its `<app>-db-local` PVC. That PV has
> `nodeAffinity`, so cordoning its node leaves the pod **Pending**, which reads
> exactly like a failed migration and is not one. An app sitting in the
> validated-but-not-yet-unbound state is *supposed* to still be node-bound.
> Check `kubectl -n media get deploy <app> -o yaml | grep db-local` returns
> nothing before you run any of this.

### There are TWO pins, and dropping the volume only removes one

**Radarr and Sonarr also carry a hard `nodeAffinity` on the Deployment itself**,
independent of any volume. Prowlarr never had one, so this step does not exist
in its history and is easy to miss:

```yaml
      # Pin to talos03 for local SQLite DB storage      <- radarr's wording
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: kubernetes.io/hostname
                    operator: In
                    values: [talos03]
```

Delete the volume and leave this, and the pod stays welded to the node while
every other signal says the migration succeeded. It is a silent failure: the
app is healthy, the SQLite PVC is gone, and the objective is still not met.

**Sonarr's copy of this block is commented `# Pin to talos03 for local downloads
storage`, which is simply wrong** — `synology-downloads-complete` and
`-incomplete` are `synology-nfs`, exported from the Synology at
`192.168.1.36:/volume1/downloads/{complete,incomplete}` with no `nodeAffinity`
on either PV. Nothing about the downloads is local to talos03. Do not read that
comment as a reason to keep the pin; radarr's said "for local SQLite DB storage"
and was equally obsolete.

The comment is really making a *co-location* argument — that the app has to sit
where its downloads land, for hardlinks and atomic moves at import. That is a
real concern in general, and the storage class alone does not settle it, so
check the claim the comment is actually making rather than only the one it
writes down. **The running cluster already disproves it**: Sonarr's only enabled
download client, SABnzbd, has no affinity at all and was running on
**talos02-gpu** — a different node from Sonarr — mounting the *same*
`synology-downloads-complete` and `-incomplete` claims. qbittorrent was on
talos06 doing likewise. Cross-node import has been working in production this
whole time, so co-location was never what the pin was buying. Sonarr's one
`RemotePathMappings` row (`sabnzbd:/downloads/complete/` ->
`/data/downloads/complete/`) is a path translation between two containers'
mount points, not a node constraint.

#### Retiring a pin: the general procedure

A `nodeAffinity` block is a claim that something about this app needs *this
node*. Retiring it means falsifying that claim, and the comment above it is
evidence of intent, not of fact — all three of these were obsolete, and two were
actively wrong about their own reason. Work the claim, not the wording:

1. **Enumerate every volume and look at the PV's *source*, not the PVC's name.**
   An app-specific claim name says nothing about whether the storage is
   node-local. Anything backed by `nfs` with no `nodeAffinity` cannot pin
   anything.
2. **If the claim is co-location with another workload** — hardlinks and atomic
   moves at import are the usual reason for an `*arr` app — then storage class
   alone does not settle it, because the argument is about two pods sharing a
   filesystem, not about where the bytes live. **Find the peer and see where it
   already runs.** If it is on a different node against the same claims, the
   requirement is already being violated in production and the pin is not
   buying it:

   ```sh
   # the peer here is the app's own enabled download client -- check which ones
   # are actually enabled, a disabled client proves nothing
   kubectl -n media get pods -l app=<peer> -o custom-columns=POD:.metadata.name,NODE:.spec.nodeName
   kubectl -n media get deploy <peer> -o jsonpath='{.spec.template.spec.volumes}'
   kubectl -n media get deploy <peer> -o jsonpath='{.spec.template.spec.affinity}'
   ```

3. **Clear the rest of the scheduling surface** before calling the affinity the
   last pin — `nodeSelector`, `tolerations`, `hostNetwork`, `hostPID`,
   `runtimeClassName`, `priorityClassName`, `topologySpreadConstraints`, and any
   `/dev/*` device mount. Sonarr had none of these. An app with a GPU or a
   `hostPath` has a real reason and this whole procedure stops there.

If 1-3 all come back clean the pin is decoration and can go. If any one of them
finds a genuine requirement, stop and say so rather than removing it.

### Proving it

Removing the mount is not the proof; scheduling somewhere else is. The static
check first — no PV backing the pod should carry `nodeAffinity`, and there
should be no `nodeSelector` or `affinity`. Check **every** volume, not just
`<app>-config`, and look at the volume *source*, since an app-specific PVC name
says nothing about whether the storage is node-local:

```sh
for c in $(kubectl -n media get pod <pod> -o jsonpath='{range .spec.volumes[*]}{.persistentVolumeClaim.claimName}{"\n"}{end}'); do
  v=$(kubectl -n media get pvc "$c" -o jsonpath='{.spec.volumeName}')
  echo "$c -> $(kubectl get pv "$v" -o jsonpath='{.spec.nodeAffinity}')"   # must be empty
done
kubectl -n media get deploy <app> -o jsonpath='{.spec.template.spec.affinity}'      # must be empty
```

Radarr's four survivors are all `nfs` volume sources pointing at 192.168.1.x
with no `nodeAffinity` — `radarr-config` on `fatboy-nfs-appdata`, the movies and
downloads claims on `synology-nfs`.

Then make it move. Cordon the node it was pinned to, delete the pod, and watch
where it lands — uncordon immediately after:

```sh
kubectl cordon talos02-gpu
kubectl -n media delete pod -l app=<app>
kubectl -n media get pods -l app=<app> -o wide   # expect a different node
kubectl uncordon talos02-gpu
```

Prowlarr moved from talos02-gpu to talos06 and served its full indexer list from
there. Before this work it could only ever run on talos02-gpu.

Sonarr needed no forcing at all: the `Recreate` rollout that dropped the volume
put it straight on talos02-gpu. That is the proof, but take it further —
"it moved once" and "it can go anywhere" are different claims. A `NotIn` listing
**both** the old pin and wherever it just landed forces a third placement, and
Sonarr went to talos06 and served 845 series from there. It settled back on
talos02-gpu when the patch came off, with `affinity` empty and no drift from
git.

### Un-pinning an app on `:latest` will silently upgrade it

Every one of these Deployments runs `image: <app>:latest` with
`imagePullPolicy: IfNotPresent`, and the node it was welded to had been holding
one specific `latest` since the image was first pulled there. **Rescheduling
onto a node without that cached layer pulls a genuinely newer image.** Sonarr
went 4.0.16.2944 -> 4.0.19.2979 on the move — an unplanned app upgrade arriving
as a side effect of storage work, in the same window as a database migration,
which is a bad place to be debugging.

It was benign here, and that was checked rather than assumed: `VersionInfo`
stayed at exactly 211 rows (max `Version` 217, so the loaded schema was already
current and 4.0.19 had no migrations to apply), and `Series`, `Episodes`,
`EpisodeFiles`, `History`, `QualityProfiles`, `Indexers`, `DownloadClients` and
`RootFolders` all still read exactly their post-load values. **Do that check
after the move, not just after the load** — and read `version` from
`/api/v3/system/status` on both sides of the reschedule so you know whether you
are even comparing the same app:

```sh
kubectl -n media get pod -l app=<app> -o jsonpath='{.items[0].status.containerStatuses[0].imageID}'
```

If the app had jumped a minor version, the new binary would have run
FluentMigrator against the freshly loaded Postgres database on first start, and
any problem would look like a migration fault rather than an image change.

**If someone else is mid-migration on the node you would cordon, do not cordon
it.** A colleague who scales their app to 0 and back while the node is
unschedulable gets a Pending pod and a false failure. Force the move with a
temporary `NotIn` affinity on your own Deployment instead — it proves the same
thing, touches only your app, and is one `kubectl patch --type=json -p
'[{"op":"remove","path":"/spec/template/spec/affinity"}]'` to undo:

```sh
kubectl -n media patch deploy <app> --type=strategic -p '{"spec":{"template":{"spec":{"affinity":{"nodeAffinity":{"requiredDuringSchedulingIgnoredDuringExecution":{"nodeSelectorTerms":[{"matchExpressions":[{"key":"kubernetes.io/hostname","operator":"NotIn","values":["talos03"]}]}]}}}}}}}'
```

That is how radarr was proven: it moved talos03 -> talos02-gpu, served the full
5 393-movie library and 5 163 readable movie directories over NFS from there,
and the patch was removed immediately after. Sonarr was mid-migration on talos03
at the time, so cordoning it was not an option.

**Expect this to move the Postgres primary too.** CNPG will not leave a primary
on an unschedulable node: cordoning talos02-gpu produced
`SwitchingOver: Current primary is running on unschedulable node talos02-gpu,
switching over from arr-postgres-1 to arr-postgres-2`. A clean switchover, not a
failover, and the cluster stayed healthy — but in-flight connections drop for a
moment, and every app on the shared cluster feels it, not just the one being
tested. Do not run this during someone else's load.

Which is the reason never to hardcode an instance name. **Resolve the primary
every time**, in scripts and in ad-hoc `psql` alike:

```sh
PRIMARY=$(kubectl -n media get cluster arr-postgres -o jsonpath='{.status.currentPrimary}')
kubectl -n media exec "$PRIMARY" -c postgres -- psql -d <app>-main -c '...'
```

A hardcoded `arr-postgres-1` works right up until it doesn't, and it fails
mid-migration with a connection error that looks like a data problem.

## Rollback

**Before the unbind**, rollback is cheap: `git revert` the cutover commits. That
restores the `/db-local` mount, brings the initContainer back — which recreates
the `/config/<app>.db` symlinks by itself — and drops the `<APP>__POSTGRES__*`
env, so the app reopens the SQLite file the procedure only ever read. Verify
with `sha256sum` against the value recorded at cutover; for Prowlarr that was
`17784f0d98a7f35148bd89e1c34eb6a4e4bb802aab792d84d7f2c031f78f6be7`. Data written
to Postgres after cutover does not come back — the SQLite file is a
point-in-time rollback, not a live mirror.

**After the unbind, that door is closed.** The PVC and PV are gone and reverting
the commit gives the app an empty database. Recovery is one of:

1. the cold `sqlite3 .backup` copies under `/config/pg-migration-backup/` on the
   NFS config PVC — for Prowlarr, `prowlarr-20260822T155746Z-final.db`, the
   exact 8 142 848-byte file pgloader read;
2. the host directory left behind on the old node, if it has not been cleaned;
3. a CNPG point-in-time restore of `arr-postgres` from the barman objectstore in
   MinIO — the right answer for anything written after cutover.

Take the unbind step only once a human has confirmed the data is correct.

---

## Whisparr — the ArgoCD-managed, NFS-resident variant (TALOS, 2026-08-27)

The fourth migration, and the first that is **not** in this repo or under Flux. Whisparr lives
in `talos-private` (namespace `media-private`, ArgoCD app `arr-stack-private`). It is `<Branch>v2`
(Sonarr-v3-based) at 2.2.0.231 — and yes, v2 supports Postgres: the schema-build rollout flipped
`databaseType` to `postgreSQL`, which is the only proof that matters, take it before assuming.

Two things made it *simpler* than the public apps, and two made it *harder*. The hard ones are
the parts that matter.

### Simpler: it was never on the db-local/local-path pattern

Whisparr's SQLite sits **directly on its NFS config PVC** (`whisparr-config`, `fatboy-nfs-appdata`)
as `/config/whisparr2.db` — v2 versions the filename, it is not `whisparr.db`. There is no
`db-local` PV, no `migration-configmap` symlink, no `nfs-backup` stale trap, and no node
`nodeAffinity` on either the volume or the Deployment. So the entire "un-node-bind" half of this
runbook (steps 8, the two-pins section, the host-directory reclaim) **does not apply**. The
migration is the core path only: schema build -> delete seeded -> pgloader -> verify. The reward
for finishing is also different — there is nothing to un-pin, the win is purely getting SQLite
off NFS, which is what corrupted it in the first place (`logs.db` went "database disk image is
malformed" on 2026-08-27; `whisparr2.db` survived `integrity_check`, so the library was intact).

Its cluster is its own `whisparr-postgres` (2 instances, `local-path`), not the shared
`arr-postgres` — a CNPG `Database` CR must live in its cluster's namespace, and `media-private`
is a deliberate trust boundary. Note the storage choice is now `local-path`, not the
`fatboy-nfs-appdata` this runbook's older "Storage choice" section landed on: putting the
replacement database back on the filesystem that corrupted the original defeats the exercise.
`arr-postgres` has since moved to local-path too.

### Harder #1: ArgoCD `selfHeal` is not `flux suspend`

`flux suspend kustomization` (step 3) has no ArgoCD equivalent that a `kubectl scale` survives.
With `syncPolicy.automated.selfHeal: true`, **ArgoCD reverts a live `kubectl scale deploy … 0`
back to the git-declared replicas within seconds** — and worse, removing
`/spec/syncPolicy/automated` off the Application does NOT stick if the Application itself is
GitOps-managed (an app-of-apps reconcile restores it). It came back mid-migration here, whisparr
scaled to 1, and the running app wrote fresh rows into tables pgloader was about to load.

The reliable stop is to make **git** say zero: commit `spec.replicas: 0` to the Deployment.
selfHeal then *keeps* it at 0 because 0 is the desired state. Revert the commit to bring it back
up after validation. This is the ArgoCD translation of the suspend window — and like the suspend
window, tell anyone else in the app that it is in force.

### Harder #2: the schema-build window contaminates the load if the app keeps running

Step 2 (let the app start once to build the schema) is a **write window**. On an empty Postgres,
whisparr's startup tasks wrote a handful of rows to `EpisodeFiles`, `History`, `DownloadHistory`
and `Commands` before it was scaled down — and because selfHeal kept bringing it back (Harder #1),
it kept doing so. pgloader then hit `duplicate key value violates unique constraint "PK_History"`
on exactly those tables, aborting their load (23834 rows dropped to 17284, 3 tables short at
4/4/8 — the window-write counts).

The fix is Harder #1 done right (pin replicas:0 in git so the app is genuinely down), then
`TRUNCATE <all public tables> RESTART IDENTITY CASCADE` and re-run pgloader into a provably empty
schema. A clean load is 23834 rows / 0 errors / `Reset Sequences 0 35`, every table matching
SQLite exactly. If pgloader reports *any* PK-violation error, the schema was not empty — do not
paper over it, truncate and reload. Verify emptiness with exact `COUNT(*)`, not `n_live_tup`.

### The per-app delete list, re-derived (as always)

Whisparr seeded 7 tables: `VersionInfo`, `QualityDefinitions`, `ScheduledTasks`,
`QualityProfiles`, `Metadata`, `Commands`, `DelayProfiles`. Two deviations from Sonarr, both the
kind this runbook keeps warning about: **`Config` seeded 0 rows here** (Sonarr seeded 1 and it was
a real collision) and **`NamingConfig` seeded 0** (Radarr seeded 1). The union of the previous
lists is still not the answer. Re-derive, every time — and if you truncate-and-reload per Harder
#2, the delete list is moot anyway because TRUNCATE clears the seed too.

### What it came out at

52 MB, `whisparr2.db`, **23834 rows, 0 errors, 0.8 s**, all 35 sequences `is_called = t`. Whisparr
is Sonarr-shaped: `Episodes` 14440, `EpisodeFiles` 2721, `Commands` 2694, `History` 1961,
`DownloadHistory` 1868, `Series` 20, `Indexers` 4, `DownloadClients` 2, `RemotePathMappings` 2,
`RootFolders` 1. `POST /api/v3/downloadclient/testall` returned both clients valid — the encrypted
`Config` credentials decrypt, which is the load's strongest proof. `whisparr2.db` mtime stayed
frozen at the schema-build shutdown while writes landed in Postgres: the two halves of "it flipped".

A YAML footgun worth one line: inserting `replicas: 0` above an existing `replicas: 1` gives a
Deployment with a duplicate key, and YAML takes the **last** — so the pin silently resolves to 1
and the app stays up. Replace the value, do not prepend a second one; `kubectl kustomize` will
not warn you.
