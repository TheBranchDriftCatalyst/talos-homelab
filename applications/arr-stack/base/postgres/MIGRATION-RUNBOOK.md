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

Rollback at any point is deleting the env block. The SQLite file is only ever
read.

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

Prove it before you load anything — the sizes differ by 46x and the mtimes by
eight months, so `stat` plus `sha256sum` settles it in one command. Then
sanity-check the row counts against what the app's own API reports.

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
Radarr and Sonarr will have the four library tables and will not have
`AppSyncProfiles`; re-derive the list from `pg_stat_user_tables` for each.

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
  `Reset Sequences  0  19` in its summary and verify:

```sql
SELECT sequencename, last_value FROM pg_sequences WHERE schemaname='public';
```

Radarr and Sonarr are 267 MB and 549 MB against Prowlarr's 8 MB, so budget
minutes rather than the half-second this took.

The type-cast `WARNING`s (`bigserial` vs `integer`, `bigint` vs `boolean`) are
expected and benign: SQLite has no native boolean and pgloader describes its own
inferred type before deferring to the existing column.

## Step 5 — verify

`pgloader exited 0` is not verification. Three checks:

1. **Row counts per table**, SQLite vs Postgres, against the frozen source file.
2. **The app's own API**, which proves it is reading what was loaded —
   `/api/v1/indexer`, `/api/v1/applications`, `/api/v1/history?pageSize=1`
   (`totalRecords`).
3. **`POST /api/v1/indexer/testall`.** The strongest check available: indexer
   credentials are encrypted with keys stored in `Config`
   (`rijndaelpassphrase`, `hmacpassphrase`, and the salts). If those rows
   migrated correctly the tests pass; if they did not, every indexer fails to
   authenticate.

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

## Decisions taken for Prowlarr

- **The `-log` database was created but its data was not migrated.** Servarr
  calls log migration optional. The logs are rolling debug output with no
  operational value, and replaying them would push churn into a WAL stream that
  is archived to MinIO and shared with Radarr and Sonarr. The app repopulates it.
- **`db-local` stays mounted.** It is the rollback and it is deliberately still
  there. Note the consequence: the local-path PV still carries `nodeAffinity`,
  so **the app is not actually un-node-bound until that volume and the
  `migrate-db` initContainer are removed from the Deployment.** That cleanup is
  TALOS-6ck8, after all three apps are migrated and proven.

## Rollback

Delete the `<APP>__POSTGRES__*` env block and reconcile. The app reopens
`/db-local/<app>.db`, which this procedure only ever read — verify with
`sha256sum` against the value recorded at cutover. Data written to Postgres
after cutover does not come back; the SQLite file is a point-in-time rollback,
not a live mirror.
