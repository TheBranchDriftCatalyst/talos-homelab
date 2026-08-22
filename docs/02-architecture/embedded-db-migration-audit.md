# Embedded-DB Migration Audit

> Parent: [docs/02-architecture/README.md](README.md)
> Audited 2026-08-22 against the live cluster. Read-only audit — nothing was migrated.
> Driver: [TALOS-k62s](../05-runbooks/promote-workers-to-controlplane.md) (EPIC 0 — un-node-bind PVCs before any control-plane reset).

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

**Recommendation on `media-experimental`: do not migrate, and do not move to NFS.** Back the
12 config dirs up to MinIO/NFS, reset the node, restore. Details in [§4](#4-media-experimental--the-answer-is-tar-not-postgres-and-not-nfs).

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
| `media/radarr-db-local` | — | SQLite | **(b)** | Already tracked — [TALOS-l4uo], in flight |
| `media/sonarr-db-local` | — | SQLite | **(b)** | Already tracked — [TALOS-eaa4], queued |
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
| 6 | `media/radarr`, `media/sonarr` db-local | **talos03** | SQLite → CNPG | Already tracked, in flight | — | — |
| — | *Everything below is on a node we do not intend to promote — defer* | | | | | |
| 7 | `catalyst-llm/open-webui` | talos06 | `webui.db` + `chroma.sqlite3` | **Genuine Postgres candidate** (see [§5](#5-real-postgres-candidates-that-are-not-on-a-target-node)) | Medium | Medium |
| 8 | `crowdsec` LAPI | talos06 | SQLite → Postgres supported | Defer — CNPG already exists for crowdsec | Medium | Medium (re-enroll bouncers) |
| 9 | `registry/zot` | talos06 | BoltDB `meta.db` + local OCI blobs | Wrong lever — see [§6](#6-leave-these-alone) | — | — |

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

### Why not NFS either

This is the part worth being explicit about, because "just put them on NFS" was the hoped-for
answer. 9 of the 12 volumes hold live SQLite. Upstream is unusually direct about this:

- Komga docs: *"SQLite should not be used on network filesystems like CIFS or NFS. Always use a
  local filesystem."*
- Audiobookshelf's maintainer says the same about NAS/NFS storage.

The runbook already flagged this risk after auditing 3 of 13; this audit completed the remaining
apps and **confirms the concern applies to 9 of 12**, not 3. So NFS is only safe for
`libation-config` (8 KB of JSON) and `audiobookshelf-metadata` (8 KB, no DB).

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

## Related Issues

- [TALOS-k62s] — EPIC 0: un-node-bind PVCs before any control-plane reset (this audit's driver)
- [TALOS-8tis] — EPIC 1: control plane 1 → 3, blocked by the above
- [TALOS-93cz] — prowlarr → CNPG (done, 2026-08-22)
- [TALOS-l4uo] — radarr → CNPG (in flight)
- [TALOS-eaa4] — sonarr → CNPG (queued)
- [TALOS-0wtt] — Litestream sidecar for jellyfin + plex
