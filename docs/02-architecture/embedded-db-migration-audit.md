# Embedded-DB Migration Audit

> Parent: [docs/02-architecture/README.md](README.md)
> Companion to [mongodb-migration-audit.md](mongodb-migration-audit.md) — that document is the
> MongoDB half of the same survey. Read them as a pair.
> Audited 2026-08-22 against the live cluster. Read-only audit — nothing was migrated.
> Driver: [TALOS-k62s](../05-runbooks/promote-workers-to-controlplane.md) (EPIC 0 — un-node-bind PVCs before any control-plane reset).
> Coverage and confidence: see [§9](#9-coverage--what-was-and-was-not-verified).

## TL;DR

**The audit found no new database migrations worth doing.** Every remaining pin on the two
nodes we actually want to reset (`talos01`, `talos03`) is cheaper to solve some other way.

- **`talos01` needs zero DB migrations.** 4 of its 8 PVs are Mimir caches already backed by
  MinIO S3 (delete and rebuild), 2 are CNPG members, 1 is Pi-hole (re-synced by nebula-sync),
  and the last — `forgejo-data`, a 20Gi PVC — holds **156 KB** and Forgejo is *already* on
  CNPG. That one is a plain NFS move and is the cheapest win in this audit.
- **`talos03` needs zero *new* DB migrations.** radarr/sonarr are already tracked
  ([TALOS-l4uo], [TALOS-eaa4]). The 12 `media-experimental` PVCs are **not** a Postgres job
  and **not** an NFS move — they are a `tar` job (~67 MB of real data across 60Gi of PVCs).
- **SPIRE is a delete candidate, not a CNPG candidate.** Moving its datastore to Postgres
  would *not even remove the PVC*, and the feature is deprecated in the Cilium version we run.
- The one genuinely clean Postgres candidate found (**Open WebUI**) is on `talos06`, which is
  not a promotion target. Deferred.
- The clearest *operator* wins are four **hand-rolled Postgres** deployments already running
  `pgvector` on `local-path` outside CNPG — but all four are on talos06, so none is urgent.
- Two talos03 pins turn out to be already resolved or nearly so: **radarr is on CNPG already**
  and no longer mounts its PVC, and sonarr's migration is running right now.

**Recommendation on `media-experimental`: do not migrate, and do not move to NFS.** Back the
12 config dirs up to MinIO/NFS, reset the node, restore. Details in [§4](#4-media-experimental--the-answer-is-tar-not-postgres-and-not-nfs).

> **The NFS question is settled by this cluster's own history, not by theory.** The arr stack
> already ran its SQLite on NFS, hit locking problems, and was migrated *off* NFS onto
> `local-path` in December 2025. The migration tooling is still in the repo
> (`applications/arr-stack/base/shared/db-migration-configmap.yaml`, header comment: *"Used by
> media apps to avoid NFS locking issues with SQLite"*) and the artifacts are still on disk
> (`/config/radarr.db.nfs-backup`, dated 2025-12-20). Moving 9 SQLite-holding
> `media-experimental` configs onto NFS would re-run an experiment this cluster has already
> failed. See [§4](#4-media-experimental--the-answer-is-tar-not-postgres-and-not-nfs).

---

## Quick Reference — disposition of the two target nodes

`local-path` is `WaitForFirstConsumer`, and `talosctl reset` wipes EPHEMERAL at `/var` where
local-path provisions. So every row below is a thing that must be resolved before the node is reset.

Classification follows TALOS-k62s: **(a)** already replicated · **(b)** can be un-bound
permanently · **(c)** genuinely stuck.

### talos01 — 8 PVs

| PVC | Size (real) | Embedded store | Class | Action |
| --- | --- | --- | --- | --- |
| `forgejo/forgejo-data` | 20Gi req / **156 KB used** | none — Forgejo is already on CNPG | **(b)** | **Move to `fatboy-nfs-appdata`.** Highest value / lowest risk item in the audit |
| `monitoring/storage-mimir-alertmanager-0` | 1Ti req | none — `alertmanager_storage.backend: s3` | **(a)** | Delete + rebuild from MinIO |
| `monitoring/storage-mimir-compactor-0` | 1Ti req | none — scratch `data_dir` | **(a)** | Delete + rebuild |
| `monitoring/storage-mimir-store-gateway-0` | 1Ti req | none — `sync_dir` cache of S3 blocks | **(a)** | Delete + rebuild |
| `monitoring/storage-mimir-ingester-0` | 1Ti req | TSDB WAL only | **(a)** | RF=3 across 3 ingesters; lose ≤ head-compaction window |
| `authentik/authentik-postgres-3` | 8Gi | CNPG replica (primary is `-2`) | **(a)** | Delete PVC+pod after reset; streams from replica |
| `boomtime/boomtime-postgres-1` | 10Gi | **CNPG PRIMARY** | **(a)** | Switchover to another instance *first*, then as above |
| `pihole/etc-pihole-pihole-1` | 2Gi / 30 MB | SQLite (`gravity.db`, `pihole-FTL.db`) | **(a)** | Disposable — nebula-sync restores from the active replica |

**Verified:** the entire Mimir config uses `backend: s3` against `minio-hl.minio.svc:9000` for
blocks, alertmanager and ruler storage. These four PVs are caches and WAL, not databases.

### talos03 — 16 PVs

| PVC | Size (real) | Embedded store | Class | Action |
| --- | --- | --- | --- | --- |
| `media/radarr-db-local` | — | SQLite (no longer used) | **(b)** | **Already free.** radarr now runs on `arr-postgres-rw` and no pod mounts this PVC. Delete it — see [§2](#radarr-is-already-done-the-pvc-is-just-left-over) |
| `media/sonarr-db-local` | — | SQLite | **(b)** | [TALOS-eaa4] — migration actively running (`sonarr-sqlite-to-pg` job present) |
| `cilium-spire/spire-data-spire-server-0` | 1Gi | SQLite **+ `keys.json`** | **(b)** | **Not a CNPG job** — see [§3](#3-spire--not-a-cnpg-candidate-a-delete-candidate) |
| 12 × `media-experimental/*-config` | 60Gi req / **~67 MB used** | mostly SQLite | **(b)** | **Backup/restore, not migration** — see [§4](#4-media-experimental--the-answer-is-tar-not-postgres-and-not-nfs) |
| `pihole/etc-pihole-pihole-4` | 2Gi / 30 MB | SQLite | **(a)** | Disposable — nebula-sync |

Note `media-experimental`'s actual media (`books`, `comics`, `audiobooks`, `downloads-complete`)
is already on `synology-nfs`. Only the config dirs pin the node.

---

## 1. Prioritised list — highest value first

Value = (un-pins a node we actually want to reset) × (low migration risk).

| # | Workload | Node | What it really is | Recommended action | Effort | Risk |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `forgejo/forgejo-data` | **talos01** | 20Gi PVC holding 156 KB of config + ssh host keys. Forgejo's actual DB is already CNPG (`forgejo-postgres`, 3 instances) | **Change storageClass to `fatboy-nfs-appdata`.** No SQLite, so no NFS locking concern | Trivial | Very low — regenerable content |
| 2 | 12 × `media-experimental` configs | **talos03** | ~67 MB total across 60Gi of PVCs | **Backup to MinIO, reset, restore.** Not a DB migration | Low (one Job) | Low — experimental apps, media on NFS is untouched |
| 3 | `cilium-spire/spire-data` | **talos03** | SQLite datastore **and** CA `keys.json` on one PVC | **Disable Cilium mutual auth** (deprecated, unused), or just let the PVC die | Trivial | Low — verified 0 policies use it |
| 4 | `boomtime/boomtime-postgres-1` | **talos01** | CNPG **primary** | Switchover, then delete PVC+pod | Low | Low — but *must* switchover before reset |
| 5 | 4 × Mimir PVs | **talos01** | S3-backed caches / WAL | Delete + let rebuild from MinIO | Trivial | Low — ≤1 head-compaction window of metrics |
| 6 | `media/radarr-db-local` | **talos03** | Orphan — radarr already on CNPG, PVC unmounted | **Delete the PVC.** Pin already resolved | Trivial | Very low |
| 7 | `media/sonarr-db-local` | **talos03** | SQLite → CNPG | Already tracked, migration running now | — | — |
| — | *Everything below is on a node we do not intend to promote — defer* | | | | | |
| 8 | `catalyst-llm/open-webui` | talos06 | `webui.db` + `chroma.sqlite3` | **Genuine Postgres candidate** (see [§5](#5-real-postgres-candidates-that-are-not-on-a-target-node)) | Medium | Medium |
| 9 | 4 × hand-rolled Postgres | talos06 | Already Postgres, just not under the operator | Move to CNPG — lowest-risk class here (same engine), but no urgency | Low | Low |
| 10 | `crowdsec` LAPI | talos06 | SQLite → Postgres supported | Defer — CNPG already exists for crowdsec | Medium | Medium (re-enroll bouncers) |
| 11 | `catalyst-data` (4 PVCs, 45Gi) | talos06 | Namespace scaled to 0/0 | Nothing to migrate — confirm intent, then delete | Trivial | Low |
| 12 | `registry/zot` | talos06 | BoltDB `meta.db` + local OCI blobs | Wrong lever — see [§6](#6-leave-these-alone) | — | — |

---

## 2. The three findings that changed the recommendation

### Mimir's PVs are not databases
All Mimir storage is `backend: s3` against MinIO. `alertmanager`, `compactor` and
`store-gateway` keep only working dirs and block caches; `ingester` keeps a TSDB WAL with
`replication_factor: 3`. Four of talos01's eight PVs therefore need no migration of any kind —
delete them and they rehydrate.

### Forgejo's 20Gi PVC holds 156 KB
Verified in-pod: `/data` is 156 KB total (`gitea` 128 KB, `ssh` 24 KB, `git` 4 KB). Forgejo is
already pointed at CNPG via `FORGEJO__database__*` secret refs. There is no embedded database
here at all — this was miscategorised as a storage problem. A one-line storageClass change
un-pins talos01's largest-looking PV.

### The `config → NFS, SQLite → local-path` split does not help media-experimental
The arr stack deliberately splits config onto `fatboy-nfs-appdata` and the SQLite DB onto a
separate `db-local` local-path PVC — `docs/03-operations/provisioning.md` records the reason
("SQLite databases CANNOT use NFS due to locking issues"). Applying that same pattern to
`media-experimental` would still leave a local-path DB PVC behind, so it does **not** un-pin
talos03. That is why the answer for those 12 is backup/restore instead.

### radarr is already done; the PVC is just left over
Verified live: radarr's Deployment carries `RADARR__POSTGRES__HOST=arr-postgres-rw` (plus
`MAINDB=radarr-main`, `LOGDB=radarr-log`), its old SQLite symlinks in `/config` have been
renamed to `*.sqlite-era`, and **no pod in the `media` namespace mounts `radarr-db-local`**
(only jellyfin, plex and sonarr still mount a `db-local`). So one of talos03's pins is already
resolved and merely needs the PVC deleted. Sonarr's migration is mid-flight — a
`sonarr-sqlite-to-pg` job pod and a `sonarr-sqlite-tools` pod are both present and still
holding `sonarr-db-local`.

One nuance worth recording: radarr's `/config/logs.db` (36 MB) is still a **real file on NFS**,
not a symlink. The back-out moved only the main DB to local-path. That has evidently been
tolerated because `logs.db` is low-write and disposable — but it means "the arr stack keeps no
SQLite on NFS" is not quite true, and nobody should cite it as precedent for moving a
*primary* database there.

---

## 3. SPIRE — not a CNPG candidate, a *delete* candidate

`cilium-spire/spire-server-0` looked like the audit's best Postgres candidate: it is a singleton
on talos03 and its config says `database_type = "sqlite3"`. SPIRE genuinely does support
Postgres ([SQL DataStore plugin](https://github.com/spiffe/spire/blob/v1.15.2/doc/plugin_server_datastore_sql.md),
`database_type = "postgres"`). Migrating it is still the wrong call, for four independent reasons:

1. **It would not remove the PVC.** The same ConfigMap sets `KeyManager "disk"` with
   `keys_path = "/run/spire/data/keys.json"` — the CA signing keys live on the *same volume* as
   the SQLite file. No SPIRE server KeyManager plugin stores keys in SQL. Moving the datastore
   to CNPG leaves the PVC in place and splits the CA keys from the `CAJournal` that references
   them — strictly worse than one store.
2. **The feature is deprecated in the version we run.** Verified: `quay.io/cilium/cilium:v1.20.0`.
   Cilium's own values.yaml marks mutual auth deprecated as of v1.20, removed in v1.21
   ([cilium#47132](https://github.com/cilium/cilium/issues/47132)).
3. **Nothing uses it.** Verified live: 6 CiliumNetworkPolicies, 0 CiliumClusterwideNetworkPolicies,
   and **0** of them reference `authentication`. SPIRE is currently enforcing nothing.
4. **The Cilium chart exposes no datastore key.** The `spire-server` ConfigMap hardcodes
   `sqlite3`; changing it means post-rendering a verbatim copy of an upstream template for a
   feature with a removal date.

**Recommended:** set `authentication.mutual.spire.enabled: false`. That deletes the StatefulSet,
the PVC, the talos03 pin, and the recurring spire-agent token-TTL toil class in one values change.

**If we want to keep it:** just delete the PVC and let it rebuild. cilium-operator's
`IdentityWatcher` recreates every registration entry from the existing CiliumIdentities on
start, and all agents report `Can re-attest: true`. Follow with
`kubectl -n cilium-spire rollout restart ds/spire-agent` so agents pick up the new trust bundle.

> Do **not** move this PVC to NFS as a shortcut — that puts both the SQLite datastore and the CA
> keys on NFS, and this cluster's mutual-auth path is fail-closed when actually in use
> ([cilium#46392](https://github.com/cilium/cilium/issues/46392) documents a whole-cluster wedge
> from exactly this shape).

---

## 4. media-experimental — the answer is `tar`, not Postgres, and not NFS

This is the largest cluster of pins on a target node (12 of talos03's 16 PVs), so it drove most
of the audit. **It should not become 12 Postgres migrations.**

### What is actually on those volumes (verified in-pod)

| App | Store on disk | Real size | External Postgres upstream? |
| --- | --- | --- | --- |
| audiobookshelf | `absdatabase.sqlite` | 456 KB (+8 KB metadata PVC) | **NO** — `dialect: 'sqlite'` hardcoded, no `pg` driver shipped ([#2046](https://github.com/advplyr/audiobookshelf/issues/2046) open since 2023, "not at all a priority") |
| komga | `database.sqlite` + `tasks.sqlite` + WAL/SHM | 764 KB | **NO — by design.** Maintainer closed [#1269](https://github.com/gotson/komga/issues/1269) and [#1327](https://github.com/gotson/komga/issues/1327) as `not_planned` |
| kavita | `kavita.db` + `cache.db` | 45 MB (incl. 15 MB of its own backup zips) | **NO** — connection string is a hardcoded literal; `Npgsql` absent repo-wide |
| storyteller | `storyteller.db` | 5.5 MB | **NO** — `better-sqlite3` + a custom SQLite C extension (hard engine lock-in) |
| mylar3 | `mylar.db` | 564 KB | **NO** — raw `import sqlite3`, no ORM |
| chaptarr | `chaptarr.db` + cache/logs/staging | 13 MB | **YES** — Readarr/Servarr lineage, `Chaptarr__Postgres__*` env vars. *But* `staging.db` stays SQLite regardless |
| booksonic | **HSQLDB** (`airsonic.script`) + Lucene `index19` | 576 KB | **YES** — Airsonic JDBC path, `DatabaseConfigType=embed`. Fork unmaintained since 2023; no HSQLDB→PG migration exists |
| libation | config JSON only — **DB is not on the volume** | 8 KB | **YES** — `LIBATION_CONNECTION_STRING` + official `libationcli copydb`. See bug below |
| librarr | `librarr.db` | 180 KB | **NO** — `modernc.org/sqlite` only |
| livrarr | `livrarr.db` | 448 KB | **NO** — sqlx built without the `postgres` feature (compile-time exclusion) |
| bindery | (distroless, could not exec) | — | **NO** — README: "SQLite, no external database"; `modernc.org/sqlite` only |

**Total real data: ~67 MB across 60Gi of provisioned PVCs.**

### Why not Postgres

Only 3 of 11 support it, and only Libation has a first-party migration tool. Crucially,
**migrating 3 of 12 PVCs does not un-pin talos03** — the node stays pinned until all 12 are
gone. Partial migration buys nothing here, so the only approaches that work are uniform ones.

### Why not NFS either — the direct answer to "can these just move to `fatboy-nfs-appdata`?"

**No. Per app, NFS is unsafe for 9 of the 12 and safe for 2 (1 unverified).**

| PVC | Holds a `*.db` / SQLite file? | NFS safe? |
| --- | --- | --- |
| `audiobookshelf-config` | yes — `absdatabase.sqlite` | **No** |
| `audiobookshelf-metadata` | no — 8 KB, no DB | **Yes** |
| `komga-config` | yes — `database.sqlite` + `tasks.sqlite` + WAL/SHM | **No** |
| `kavita-config` | yes — `kavita.db`, `cache.db` + WAL/SHM | **No** |
| `storyteller-config` | yes — `storyteller.db` | **No** |
| `mylar3-config` | yes — `mylar.db` | **No** |
| `chaptarr-config` | yes — `chaptarr.db`, `cache.db`, `logs.db`, `staging.db` | **No** |
| `booksonic-config` | yes — HSQLDB (`airsonic.script`) + Lucene index + `.lck` lockfile | **No** |
| `librarr-config` | yes — `librarr.db` | **No** |
| `livrarr-config` | yes — `livrarr.db` | **No** |
| `bindery-config` | *unverified on-disk* (distroless, no shell) — upstream is SQLite-only | **Assume no** |
| `libation-config` | no — 8 KB of JSON only | **Yes** |

Three independent lines of evidence, strongest first:

1. **This cluster already ran this experiment and reverted it.**
   `applications/arr-stack/base/shared/db-migration-configmap.yaml` exists specifically to move
   arr SQLite databases *off* NFS onto local-path — its header reads *"Used by media apps to
   avoid NFS locking issues with SQLite"*. `migrate-arr.sh` copies `<app>.db`, `-shm` and `-wal`
   to `/db-local`, renames the originals to `.nfs-backup`, and symlinks them back. Verified on
   disk: `/config/radarr.db.nfs-backup`, 671 KB, dated **2025-12-20**. This is not a
   hypothetical risk — it is a regression this cluster has already paid for once.
2. **Upstream says no.** Komga's docs: *"SQLite should not be used on network filesystems like
   CIFS or NFS. Always use a local filesystem."* Audiobookshelf's maintainer says the same about
   NAS/NFS. Open WebUI's docs go further and name Kubernetes network-backed PVCs explicitly as
   unsupported.
3. **The runbook's partial audit was directionally right but understated.** It had confirmed 3
   of 13; completing the remaining apps raises that to **9 of 12**.

So the storageClass change is not available as a shortcut here. It *is* available for
`libation-config` and `audiobookshelf-metadata`, but moving 2 of 12 does not un-pin the node.

### The backup tooling for the recommended path already exists

The same ConfigMap ships a `backup.sh` that copies `*.db`, `*.db-shm` and `*.db-wal` from a
local-path mount to an NFS backup directory with 5-day retention. That is exactly the mechanism
this audit recommends for the 12 `media-experimental` configs — it needs pointing at new paths,
not writing from scratch.

### What to do instead

Treat all 12 uniformly as backup/restore. At ~67 MB, a single Job can `tar` every config dir to
MinIO in seconds, and restore just as fast after the node is rebuilt. Keep them on local-path.

Two refinements worth folding in:

- **Five of these apps have real built-in backup/restore** — audiobookshelf, kavita (uses
  `VACUUM INTO`, so it is a consistent hot snapshot), chaptarr, bindery, librarr. Prefer the
  app's own mechanism where it exists; it is the supported path.
- **Or accept the loss.** These are experimental apps whose media lives on `synology-nfs` and
  survives regardless. A rescan rebuilds libraries; what is lost is per-user read progress,
  users/API keys, and metadata matches. For several of these that is an acceptable trade — but
  **storyteller is the exception** (position sync is the entire product, and re-ingest means
  re-running forced alignment), so back that one up properly.

### Bug found in passing — libation is already losing data

`silelmot/libation-container` symlinks only `Settings.json` / `AccountsSettings.json` /
`appsettings.json` into the mounted config dir. `LibationContext.db` is written to
`/root/Libation/` — **outside any volume** — so it is discarded on every container recreate.
The official `rmcrackan/libation` image handles this correctly. Worth fixing independently of
this audit; filed separately from the migration work.

---

## 5. Real Postgres candidates that are *not* on a target node

Listed for completeness. All are on `talos06` or `talos02-gpu`; per TALOS-k62s, talos02-gpu is
the only GPU node and promoting it is likely wrong regardless. **Recommend deferring all of these.**

- **`catalyst-llm/open-webui`** — the cleanest technical candidate in the cluster. Supports
  `DATABASE_URL=postgresql://…`, and the Chroma vector store can move too via `VECTOR_DB=pgvector`
  + `PGVECTOR_DB_URL`. Note it takes **three** changes to actually un-pin: app DB, vector DB, *and*
  `STORAGE_PROVIDER=s3` for `uploads/` — doing only the first leaves the volume in place. No
  official SQLite→Postgres migration; vectors are re-indexable, uploads are not.
  ([docs](https://docs.openwebui.com/reference/env-configuration/))
- **CrowdSec LAPI** — supports `DB_TYPE=postgresql`, and a CNPG cluster already exists in the
  `crowdsec` namespace. Migration warning from upstream: machines and bouncers are **not**
  migrated and must be re-registered, which will break bouncers mid-flight if unplanned.
  ([docs](https://docs.crowdsec.net/docs/local_api/database/))

### Hand-rolled Postgres that should be CNPG (all talos06)

These are not embedded-DB migrations at all — they are already PostgreSQL, just running as
plain Deployments/StatefulSets on `local-path` instead of under the operator. Moving them to
CNPG is the lowest-risk class of change in this document (same engine, `pg_dump`/restore or a
CNPG bootstrap), and it would buy backups and replication. None of them is on a target node, so
none is urgent — but they are the clearest "should eventually be CNPG" list in the cluster.

| Workload | Namespace | Image | PVC |
| --- | --- | --- | --- |
| `litellm-postgresql` | `catalyst-llm` | `pgvector/pgvector:pg16` (Deployment) | `litellm-postgresql` 100Gi |
| `postgres-0` | `dungeon-library` | `pgvector/pgvector:pg16` (StatefulSet) | `postgres-storage-postgres-0` 5Gi |
| `postgres-knowledge` | `catalyst-data` | `pgvector/pgvector:pg16` (Deployment) | `postgres-knowledge` 10Gi |
| `dagster-postgres` | `catalyst-data` | (Deployment) | `dagster-postgres` 5Gi |

Note all four use `pgvector` — any CNPG move must keep the `vector` extension available.

### Sister-repo apps deployed via ArgoCD

Eight ArgoCD Applications, checked against their source repos where available locally:

| Application | Source | Storage findings |
| --- | --- | --- |
| `catalyst-llm` | `catalyst-llm.git` `k8s/talos00` | `catalyst-llm-config` + `catalyst-llm-data` **already on `fatboy-nfs-appdata`**. Remaining local-path: `open-webui-data`, `lobe-chat-data`, `litellm-postgresql` — all talos06 |
| `catalyst-data` | `catalyst-data.git` `k8s` | `postgres-knowledge` and `neo4j` are hand-rolled Deployments on `local-path` (`pgvector/pgvector:pg16`, `neo4j:5-community`). **Entire namespace is scaled to 0/0** — see below |
| `boomtime` | `boomtime.git` `k8s/overlays/talos00-knowledgedump` | Already CNPG (`boomtime-postgres` ×3, `books-postgres`). Only `persistence-boomtime-rabbit-server-0` (1Gi, talos06) is local-path — RabbitMQ, not a database |
| `openscad` | `openscad.git` `k8s/overlays/talos00` | Already CNPG (`manyfold-postgres` on NFS); library PV is a separate 1Ti volume. **No action** |
| `dungeon-library` | `dungeon-library.git` `k8s` | Hand-rolled Postgres StatefulSet — see table above |
| `arr-stack-private` | `talos-private.git` | Private repo, not inspected — see [§9](#9-coverage--what-was-and-was-not-verified) |
| `catalyst-ui` | `catalyst-ui.git` `k8s` | No persistent storage. **No action** |
| `kasa-exporter` | `kasa-exporter.git` `k8s` | Repo not present locally; no local-path PVC in the cluster for it. **No action** |

### Dormant workloads still holding PVCs

`catalyst-data` has every Deployment scaled to **0/0** (`dagster-daemon`, `dagster-webserver`,
`dagster-postgres`, `congress-data`, `catalyst-data-homepage`) yet still holds four bound
local-path PVCs on talos06 totalling **45Gi** (`dagster-postgres` 5Gi, `model-cache` 20Gi,
`neo4j-data` 10Gi, `postgres-knowledge` 10Gi). There is nothing to migrate here — if the
namespace is genuinely retired, these are free deletions. **Confirm intent before deleting;**
this audit did not establish whether the scale-down is deliberate or an outage.

There are also several `Available`/`Released` PVs (`default/litellm-postgresql`,
`default/postgres-knowledge`, `default/pterodactyl-*`, `media/prowlarr-db-local`) — leftovers
from completed migrations and earlier experiments, safe to reap.

### gaming/opensim — MySQL, not Postgres

`gaming/opensim` holds real SQLite (`OpenSim.db`, `auth.db`, `griduser.db`,
`userprofiles.db`) on `opensim-data` (20Gi, talos06). OpenSimulator **does** support an external
database, but the supported external engine is **MySQL/MariaDB, not PostgreSQL** —
`[DatabaseService] StorageProvider = "OpenSim.Data.MySQL.dll"` plus a `ConnectionString`, set in
`StandaloneCommon.ini` / `GridCommon.ini`
([OpenSimulator Database Settings](http://opensimulator.org/wiki/Database_Settings)). So it is
**not** a CNPG candidate; it would require introducing a MySQL operator. On a non-target node,
that is not worth it. Leave alone.

---

## 6. Leave these alone

A short list with reasons, so this does not get re-audited.

| Workload | Why not |
| --- | --- |
| **jellyfin, plex** | SQLite-only; no Postgres support exists. Already decided — Litestream sidecar ([TALOS-0wtt]) |
| **Mimir (all 4 PVs)** | Not databases. S3/MinIO-backed caches and WAL; delete and rebuild |
| **Pi-hole (5 PVs)** | Deliberate design — per-pod local-path SQLite, never NFS, 5 replicas behind one VIP with nebula-sync. Losing one replica's PV is a non-event. See [pihole-ha-pattern.md](pihole-ha-pattern.md) |
| **All CNPG members** | Already replicated. Delete PVC+pod post-reset and it streams from a survivor. Only rule: never reset a node holding the **primary** without a switchover first |
| **Frigate** | SQLite-only by explicit maintainer decision ([#9496](https://github.com/blakeblackshear/frigate/issues/9496) closed not-planned). Docs warn against network storage. Also: deleting `frigate.db` *orphans recordings* — they stop being pruned and silently fill disk. Not disposable |
| **Scrypted** | LevelDB (not SQLite), hardcoded, no abstraction to extend. Holds device configs, users and the TLS keypair — worst disposability in the audit |
| **`registry/zot`** | BoltDB `meta.db` regenerates from the OCI blobs on disk, so the metadata store is the wrong lever. What pins the node is `storage.rootDirectory`. If zot ever matters, point `rootDirectory` at MinIO — that is an object-storage change, not a DB migration. zot supports only DynamoDB/Redis as remote cache, **never Postgres** |
| **`crowdsec-web-ui`** | Third-party dashboard (`better-sqlite3` only, no connection-string config). Mostly a re-syncable LAPI mirror; cheapest option is to treat it as expendable and re-enroll passkeys/TOTP |
| **All `media` / `media-private` configs** | **Already on NFS** — see [§7](#7-already-un-pinned--no-action-needed) |
| **`gaming/opensim`** | Supports external **MySQL**, not Postgres — would need a MySQL operator, and it is on talos06. Not a CNPG candidate |
| **`gaming` Windows/VM volumes** | `windows-gameserver-disk` (150Gi), `windows-iso`, `virtio-drivers` — VM disks and ISOs, not databases. Nothing to migrate |
| **`crossplane-demo` (4 PVs)** | Demo namespace — ClickHouse, RabbitMQ and a demo Postgres. Disposable by definition; delete rather than migrate |
| **`boomtime` / `crossplane-demo` RabbitMQ** | Message broker state, not a database. Queues rebuild; no external-DB concept applies |
| **`monitoring/loki-0`, `tempo`, ClickHouse/HyperDX** | Object-storage-backed or log/trace stores with their own retention. Not embedded-DB migration candidates |
| **`catalyst-llm` config/data** | Already on `fatboy-nfs-appdata` |

---

## 7. Already un-pinned — no action needed

Worth recording, because it is easy to assume otherwise. These are already on
`fatboy-nfs-appdata` or `synology-nfs` and do **not** pin any node:

`prowlarr-config`, `radarr-config`, `sonarr-config`, `sabnzbd-config`, `qbittorrent-config-nfs`,
`tautulli-config-nfs`, `overseerr-config`, `maintainerr-data`, `pulsarr-data`, `kometa-config-nfs`,
`posterizarr-config-nfs`, `posterr-config-nfs`, `jellyfin-config`, `plex-config`,
`whisparr-config`, `stash-config`, `immich-uploads`, `zipline-uploads`, `homeassistant-config-nfs`,
`linkwarden-data`, `dbgate-data`, and all `media-experimental` media volumes
(`books`, `comics`, `audiobooks`, `downloads-complete`).

### Already on an external DB (previously unrecorded)

- **Forgejo** — already CNPG via `FORGEJO__database__*`. Its `forgejo-data` PVC is config only.
- **CNPG clusters (12):** authentik, books, boomtime, crowdsec, forgejo, guacamole,
  homeassistant, linkwarden, manyfold, plausible, zipline, and `media/arr-postgres`
  (3 instances, now serving prowlarr).
- **MongoDBCommunity (2):** `monitoring/clickstack-mongodb`, `scratch/scratch-mongodb`.
  Surveyed in full by [mongodb-migration-audit.md](mongodb-migration-audit.md): neither is on a
  promotion target, and no workload in the cluster is a MongoDB migration candidate.

---

## 8. Risk notes

- **CNPG primary on a target node.** `boomtime-postgres-1` is currently the primary and sits on
  talos01. Resetting that node without a switchover first is the single most damaging mistake
  available in this plan. Verify with
  `kubectl get cluster.postgresql.cnpg.io -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,PRIMARY:.status.currentPrimary`
  immediately before any reset — the primary moves.
- **SPIRE fail-closed.** Mutual auth drops traffic when required and unsatisfied. It is
  currently unused (0 policies), which is what makes disabling it safe *today*. Re-verify before
  acting; if someone adds an `authentication` policy first, the calculus changes.
- **`media-experimental` restore is untested.** The backup half is trivial; the restore half is
  not proven. Restore into a scratch namespace once before relying on it for a node reset.
- **Recoverability.** Everything in the priority list is recoverable: Mimir rehydrates from
  MinIO, CNPG streams from replicas, Pi-hole re-syncs via nebula-sync, SPIRE regenerates from
  CiliumIdentities, forgejo-data is 156 KB of regenerable config, and media-experimental's
  actual media is on NFS and never at risk. The only genuinely unrecoverable loss on a target
  node would be `media-experimental` read progress and users if we skip the backup step.

### The structural option we do not currently have

Frigate, Scrypted, jellyfin, plex and the 9 SQLite-only media-experimental apps all share one
root cause: they need POSIX locking semantics that NFS cannot reliably give, so they need
node-local storage. The general fix for that whole class is **RWO block storage on a
network-backed CSI** (Ceph RBD, iSCSI, or Longhorn), which presents as a local block device and
keeps SQLite/LevelDB locking intact while still being detachable and re-attachable to another
node. This cluster has NFS and local-path but no block CSI. Adding one would retire this entire
category of problem permanently — worth considering as its own piece of work rather than
continuing to solve it one app at a time.

---

## 9. Coverage — what was and was not verified

### Method

Started from `kubectl get pv` filtered to `storageClassName=local-path`, mapped every PV to its
`claimRef` and its `nodeAffinity` node, then mapped each PVC to the pod that mounts it. That
enumerates the pin set exhaustively — a workload with no local-path PVC cannot pin a node, so
namespaces with no local-path claim were correctly out of scope. Each candidate was then probed
in-pod (`du`, `find` for `*.db` / `*.sqlite*` / HSQLDB / LevelDB) to establish what is *actually*
on the volume rather than what the chart implies. Upstream DB support was researched separately
and is cited inline.

### Verified against the live cluster (high confidence)

- The complete local-path PV → node → PVC → pod map, all 5 nodes.
- On-disk contents of 10 of 11 `media-experimental` apps, plus radarr, forgejo, pihole, spire,
  frigate, scrypted, crowdsec-web-ui, open-webui, opensim.
- Mimir's storage backends (`backend: s3` → MinIO) read from the live `mimir-config` ConfigMap.
- SPIRE's `database_type = "sqlite3"` **and** `KeyManager "disk"` `keys_path` on the same PVC,
  read from the live `spire-server` ConfigMap.
- Cilium image `v1.20.0`; 6 CiliumNetworkPolicies, 0 CiliumClusterwideNetworkPolicies, **0**
  referencing `authentication`.
- radarr/sonarr/prowlarr `*__POSTGRES__*` env; which pods still mount a `db-local` PVC.
- The CNPG (12) and MongoDBCommunity (2) inventories, and current CNPG primaries.

### Evidenced upstream claims (docs URL / env vars / source cited inline)

Every "supports external Postgres" verdict in §4, §5 and §6 carries a citation. The ones acted
on in the priority list are: audiobookshelf, komga, kavita, storyteller, mylar3, chaptarr,
booksonic-air, libation, librarr, livrarr, bindery, open-webui, crowdsec, frigate, scrypted,
zot, SPIRE, opensim.

### NOT verified — do not act on these as fact

- **`bindery-config` on-disk contents.** The image is distroless with no shell, and confirming
  it would have required creating a debug pod, which this read-only audit did not do. Upstream
  evidence (`modernc.org/sqlite` as the only DB driver; README: *"no external database"*) says
  SQLite, so it is treated as NFS-unsafe. Confidence: high on upstream, unverified on disk.
- **`arr-stack-private`** (`talos-private.git`) was not inspected — private repo. Its workloads
  live in `media-private`, whose PVCs are all already on NFS, so it is unlikely to hold a pin,
  but that is an inference rather than a check.
  **Closed 2026-08-23:** the repo *is* checked out locally at `workspace/talos-private` and was
  inspected for the [MongoDB audit](mongodb-migration-audit.md) — zero `local-path` claims (all
  `fatboy-nfs-appdata` / `synology-nfs` / `tdarr-nfs`) and zero Mongo. The inference was correct.
- **`openscad` and `kasa-exporter` repos** are not checked out locally; assessed from cluster
  state only.
- **Whether `catalyst-data`'s 0/0 scale-down is deliberate.** Affects whether 45Gi of PVCs are
  free deletions or an outage waiting to be noticed.
- **`media-experimental` restore has never been exercised.** The backup half is trivial and the
  tooling exists; the restore half is untested.
- **Exact sizes for `radarr-db-local` / `sonarr-db-local`** were not captured (the mount was
  gone from radarr's current pod). Not decision-relevant — both are already tracked.

### Explicitly out of scope

Namespaces with no local-path PVC cannot pin a node and were not probed for embedded stores:
`argo`, `argocd`, `backup`, `cert-manager`, `external-dns`, `external-secrets`, `flux-system`,
`keda`, `kyverno`, `kubevirt`, `traefik`, `minio`, `observability`, `tdarr`, `homepage`,
`immich`, `mail`, `honeypot`, `iocaine`, `infra-control`, and the operator namespaces. If one of
these later grows a local-path PVC, re-check it.

---

## Related Issues

- [TALOS-k62s] — EPIC 0: un-node-bind PVCs before any control-plane reset (this audit's driver)
- [TALOS-8tis] — EPIC 1: control plane 1 → 3, blocked by the above
- [TALOS-93cz] — prowlarr → CNPG (done, 2026-08-22)
- [TALOS-l4uo] — radarr → CNPG (in flight)
- [TALOS-eaa4] — sonarr → CNPG (queued)
- [TALOS-0wtt] — Litestream sidecar for jellyfin + plex
- [mongodb-migration-audit.md](mongodb-migration-audit.md) — the MongoDB half of this survey
