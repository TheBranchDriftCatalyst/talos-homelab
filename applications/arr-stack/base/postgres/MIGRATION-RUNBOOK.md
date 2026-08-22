# SQLite -> CNPG Postgres migration for the \*arr apps

Proven end-to-end on **Prowlarr** (TALOS-93cz, 2026-08-22). Radarr (TALOS-l4uo)
and Sonarr (TALOS-eaa4) follow the same steps against the same `arr-postgres`
cluster. Read the whole thing before starting the next one — the deviations from
the Servarr wiki are the parts that matter.

## TL;DR

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

Prove it before you load anything — the sizes differ by 46x for Prowlarr and
398x for Radarr, the mtimes by eight months, so `stat` plus `sha256sum` settles
it in one command. Then sanity-check the row counts against what the app's own
API reports. Loading the trap file would have cost 5 393 movies and imported 0.

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

Two details worth keeping:

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
  `last_value = max(Id)`. Prowlarr's `History` and `Commands` sequences have
  since advanced past their post-load values under live use with no duplicate-key
  errors, which is the empirical version of the same check.

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

Removing the mount is not the proof; scheduling somewhere else is. The static
check first — no PV backing the pod should carry `nodeAffinity`, and there
should be no `nodeSelector` or `affinity`:

```sh
kubectl -n media get pvc <app>-config -o jsonpath='{.spec.volumeName}'
kubectl get pv <that-pv> -o jsonpath='{.spec.nodeAffinity}'   # must be empty
```

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
