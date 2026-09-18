# MongoDB Migration Audit

> Parent: [docs/02-architecture/README.md](README.md)
> Companion to [embedded-db-migration-audit.md](embedded-db-migration-audit.md) — that document
> is the Postgres/CNPG half of the same survey; this is the MongoDB half. Read them as a pair.
> Audited 2026-08-23 against the live cluster. Read-only audit — nothing was migrated.
> Driver: [TALOS-3hl8] (EPIC 3 — eliminate unnecessary node affinities), via [TALOS-k62s] (EPIC 0).
> Coverage and confidence: see [§9](#9-coverage--what-was-and-was-not-verified).

## TL;DR

**No MongoDB work is on the critical path. Nothing Mongo-shaped sits on `talos01` or `talos03`.**

That is the whole headline. The two nodes being promoted to control planes carry 22 node-bound
PVs between them ([TALOS-3gte]) and **not one of them is a MongoDB, nor belongs to a workload
that could become one.** Everything below is either housekeeping on `talos06` or a
leave-alone.

- **There are no hand-rolled MongoDB deployments in this cluster.** This is the direct analogue
  of the four hand-rolled `pgvector` Postgres the Postgres audit found — and here the count is
  **zero**. Every mongod running is already under the `mongodb-kubernetes` operator. The one
  hand-rolled Mongo this repo ever had (`observability/mongodb`, Bitnami chart, `auth.enabled:
  false`) was deleted with the v1 observability stack in December 2025 (`34de46d5`).
- **No node-bound workload supports MongoDB as an external backend.** Every candidate in the
  pin set is SQLite, LevelDB, HSQLDB, BoltDB, Postgres or MySQL. Not one has a Mongo driver.
  See [§4](#4-no-workload-is-a-mongodb-migration-candidate) for the app-by-app evidence.
- **The only Mongo on `local-path` is `monitoring/clickstack-mongodb`, and it pins `talos06`**
  — a housekeeping node, not a promotion target. Its 10Gi PVC holds **239 MB, of which ~237 MB
  is preallocated WiredTiger journal and FTDC diagnostic data**. The actual `hyperdx` database
  is **11 collections and 0 documents, 118 KB on disk**. There is nothing to migrate.
- **`scratch/scratch-mongodb` is already on `fatboy-nfs-appdata` and pins nothing.** No action.

> **Found while auditing — a live defect, not a migration question.** `clickstack-app` is
> failing SCRAM auth against `clickstack-mongodb` roughly continuously (114 `AuthenticationFailed`
> events in the last 2000 log lines; mongod logs `storedKey mismatch`). Verified cause: the
> **running pod's injected `MONGO_URI` password is stale** — the ConfigMap has been re-rendered
> with the current credential but `envFrom` freezes values at pod start and nothing restarted
> the Deployment. That is why HyperDX has zero persisted state. Fix is a rollout restart, not a
> migration. Filed as [TALOS-j4jy]; detail in [§5](#5-live-defect-clickstack-app-holds-a-stale-mongo_uri).

---

## Quick Reference — the complete MongoDB inventory

Three mongod processes exist in this cluster. That is the entire surface.

| Instance | Kind | Version | Storage | Node pinned? | Real size | Disposition |
| --- | --- | --- | --- | --- | --- | --- |
| `monitoring/clickstack-mongodb` | `MongoDBCommunity` | 8.0.4 | `local-path` ×2 (`data-volume` 10Gi, `logs-volume` 2G) | **`talos06`** | 239 MB data / 43 MB logs — **0 documents** | Housekeeping only. Delete + rebuild, or leave |
| `scratch/scratch-mongodb` | `MongoDBCommunity` | 7.0.14 | `fatboy-nfs-appdata` ×2 (5Gi + 1Gi) | **No** — NFS, no `nodeAffinity` | 528 MB (300 MB journal + 208 MB FTDC) | **Nothing to do.** Already un-pinned |
| `databases/mongodb-kubernetes-operator` | Deployment | 1.10.0 | none | No | — | Operator itself; stateless |

Neither node being promoted appears in that table. Reproduce with:

```bash
kubectl get pv -o json | jq -r '.items[]
  | select(.spec.storageClassName=="local-path")
  | "\(.spec.nodeAffinity.required.nodeSelectorTerms[0].matchExpressions[0].values[0])\t\(.spec.claimRef.namespace)/\(.spec.claimRef.name)"' \
  | sort | grep -Ei "talos0[13]"
```

Result on 2026-08-23: 14 rows for `talos03` (1 SPIRE, 12 `media-experimental`, 1 Pi-hole) and
8 for `talos01` (4 Mimir, 2 CNPG, 1 Forgejo, 1 Pi-hole). **No Mongo in either list.**

---

## 1. Prioritised list

Value = (un-pins a node we actually want to reset) × (low migration risk). Every row here scores
zero on the first factor, which is the finding.

| # | Workload | Node | What it really is | Recommended action | Effort | Risk |
| --- | --- | --- | --- | --- | --- | --- |
| — | *Nothing on `talos01` or `talos03`.* | — | — | — | — | — |
| 1 | `clickstack-app` stale credential | — | Live auth failure, **not** a storage or migration issue | **Rollout restart** `deploy/clickstack-app`, then add a config checksum annotation | Trivial | Very low |
| 2 | `monitoring/clickstack-mongodb` ×2 PVCs | talos06 | 12Gi of PVC holding 0 documents | **Leave.** If talos06 is ever reset, delete + let it rebuild — nothing is lost that isn't already lost | Trivial | Very low |
| 3 | `scratch/scratch-mongodb` | — | Demo instance on NFS | **Leave, or delete if the example has served its purpose.** Pins nothing either way | Trivial | None |

There is no #4. The list is genuinely this short.

---

## 2. Why `talos01` and `talos03` have no Mongo work

Two independent checks, both negative:

**Storage side.** The complete `local-path` PV → node map (66 PVs, all 5 nodes) contains exactly
two Mongo claims — `monitoring/data-volume-clickstack-mongodb-0` and
`monitoring/logs-volume-clickstack-mongodb-0` — and both carry `nodeAffinity` to **`talos06`**.
`scratch-mongodb`'s two claims are on `fatboy-nfs-appdata`, which is NFS to `192.168.1.36` with
no `nodeAffinity` at all.

**Workload side.** Every workload that *does* pin `talos01` or `talos03` was checked for a Mongo
driver, and none has one:

| Pin on a target node | Embedded store | Mongo support? |
| --- | --- | --- |
| `forgejo/forgejo-data` (talos01) | none — already CNPG | Forgejo: SQLite/MySQL/Postgres/MSSQL. **No Mongo** |
| 4 × Mimir PVs (talos01) | S3-backed caches + TSDB WAL | Not a database |
| `authentik-postgres-3`, `boomtime-postgres-1` (talos01) | CNPG members | Already replicated Postgres |
| `cilium-spire/spire-data` (talos03) | SQLite + `keys.json` | SPIRE SQL DataStore: `sqlite3`, `postgres`, `mysql`, `aws_postgresql`. **No Mongo** |
| 12 × `media-experimental` configs (talos03) | SQLite / HSQLDB | **None** — see the per-app table in the Postgres audit [§4]; the three with any external-DB story (chaptarr, booksonic, libation) are Postgres/JDBC, not Mongo |
| `pihole/etc-pihole-pihole-{1,4}` | SQLite (`gravity.db`, `pihole-FTL.db`) | Pi-hole FTL is SQLite-only. **No Mongo**. Also deliberate — see [pihole-ha-pattern.md](pihole-ha-pattern.md) |

So the conclusion is not "we looked and it was close" — the two questions do not intersect at all.

---

## 3. `clickstack-mongodb` — the only Mongo pin, and it holds nothing

This is the instance the brief asked about specifically. It pins **`talos06`**, and here is
whether that matters.

### It is already the fix, not the problem

The CR (`infrastructure/base/monitoring/v2-otel/clickstack/mongodb.yaml`) exists *because* the
chart's bundled mongo was a plain Deployment whose local-path PVC bound to `talos00` while
`talos00` was schedulable — and went permanently `Pending` once the control-plane taint came
back. The MongoDBCommunity CR carries a `node-role.kubernetes.io/control-plane: DoesNotExist`
node affinity precisely so that cannot recur. That guard is correct and should stay.

### The PVC is 98% overhead

Measured in-pod on 2026-08-23:

```
239M  /data          total
200M  /data/journal          <- preallocated WiredTiger journal files
 37M  /data/diagnostic.data  <- FTDC, rolling telemetry, disposable
 ~1M  everything else        <- the actual collections
```

Authenticated `db.stats()` against the `hyperdx` database:

```
collections: 11   objects: 0   dataSize: 0   storageSize: 0.043 MB   indexes: 18
```

All 11 collections (`users`, `teams`, `sources`, `dashboards`, `alerts`, `savedsearches`,
`connections`, `webhooks`, `sessions`, `teaminvites`, `alerthistories`) are **empty**. HyperDX
has never persisted a team, a user or a source since the 2026-08-20 migration — which
[§5](#5-live-defect-clickstack-app-holds-a-stale-mongo_uri) explains.

The `logs-volume` (2G claim) holds 43 MB, all of it `automation-agent-verbose.log` rotations
from the MongoDB agent. Also disposable.

**This is the same shape as Forgejo's 20Gi-holding-156 KB and the 1Ti Mimir claims** — a big
PVC that looks like a migration problem and is not.

### Does the `talos06` pin matter?

Not today. `talos06` is not a promotion target, and per the descheduler's `PodsWithPVC`
protection (`protectedStorageClasses: [local-path]`) the pod will not be evicted out from under
its PV. If `talos06` is ever rebuilt, delete both PVCs and let the operator re-provision — you
lose 0 documents.

**One forward-looking caution.** The CR's affinity excludes control-plane nodes *as they are at
scheduling time*. If the PVCs are ever deleted and re-provisioned **before** `talos01`/`talos03`
are promoted, `WaitForFirstConsumer` could bind the new volume onto one of them and create a
fresh pin on a promotion target. If you touch these PVCs during the control-plane window, pin
the pod away from `talos01`/`talos03` for the duration, or do it after promotion when the
existing control-plane exclusion covers them automatically.

---

## 4. No workload is a MongoDB migration candidate

The brief's category 2 — "applications whose upstream supports MongoDB as a backing store and
which currently use something node-bound instead" — came back **empty**. Every `local-path`
holder in the cluster was checked. The interesting ones, with evidence:

| Workload | Node | Current store | External Mongo? | Evidence |
| --- | --- | --- | --- | --- |
| `catalyst-llm/open-webui` | talos06 | `webui.db` + `chroma.sqlite3` | **No** | `DATABASE_URL` accepts SQLite, PostgreSQL, MySQL and SQLCipher only — SQLAlchemy, no Mongo dialect ([env config](https://docs.openwebui.com/reference/env-configuration/), [discussion #8700](https://github.com/open-webui/open-webui/discussions/8700)). Remains the Postgres candidate the other audit named |
| `catalyst-llm/lobe-chat-data` | talos06 | server DB | **No** | LobeChat server mode is Postgres + pgvector; no Mongo driver |
| `crowdsec` LAPI | talos06 | SQLite | **No** | `DB_TYPE` ∈ `sqlite`, `mysql`, `postgresql` — the `ent` ORM has no Mongo dialect ([docs](https://docs.crowdsec.net/docs/local_api/database/)) |
| `crowdsec/crowdsec-web-ui-data` | talos06 | `better-sqlite3` | **No** | Third-party dashboard, no connection-string config at all |
| `registry/zot-data` | talos06 | BoltDB `meta.db` + OCI blobs | **No** | zot's only remote cache drivers are DynamoDB and Redis. Confirmed in the Postgres audit; unchanged |
| `cilium-spire/spire-data` | **talos03** | SQLite + CA `keys.json` | **No** | SQL DataStore plugin supports `sqlite3` / `postgres` / `mysql` / `aws_postgresql` only |
| `gaming/opensim-data` | talos06 | SQLite | **No** | OpenSimulator's external engine is MySQL/MariaDB. Not Mongo, not Postgres |
| `catalyst-data/neo4j-data` | talos06 | Neo4j store | **N/A** | A graph database, not a document store. Namespace is scaled to 0/0 anyway |
| `catalyst-data/postgres-knowledge`, `dagster-postgres`, `catalyst-llm/litellm-postgresql`, `dungeon-library/postgres-storage` | talos06 | `pgvector/pgvector:pg16` | **N/A** | These are the hand-rolled *Postgres*; their destination is CNPG, tracked in the Postgres audit |
| 12 × `media-experimental` configs | **talos03** | SQLite / HSQLDB | **No** | Per-app evidence already established in the Postgres audit [§4]; none ships a Mongo driver |
| `tdarr/tdarr-server` | talos06 (`nodeSelector`) | SQLite (`DB2/SQL/database.db`) | **No** | Tdarr has no external-database configuration variable of any kind — only `jobReportsPath` for relocating job report *files* ([config variables](https://docs.tdarr.io/docs/installation/variables/)) |

### Apps that *are* Mongo-native — and aren't here

For completeness, because it is the obvious next question: the classic Mongo-backed self-hosted
apps are **not deployed in this cluster**. `observability` is an empty namespace — Graylog and
its MongoDB were removed in `34de46d5`, and `CLAUDE.md`'s description of a Graylog/OpenSearch
stack is stale. There is no Unifi controller, Rocket.Chat, NodeBB, Wekan or Zammad. The full
image inventory across all 62 namespaces contains exactly three Mongo-related images, all
operator-managed.

---

## 5. Live defect: `clickstack-app` holds a stale `MONGO_URI`

Not a migration finding, but it is why [§3](#3-clickstack-mongodb--the-only-mongo-pin-and-it-holds-nothing)
reports an empty database, so it belongs here.

**Symptom.** `deploy/clickstack-app` logs `MongoServerError: Authentication failed` (code 18)
continuously — 114 occurrences in the last 2000 log lines, from both the `[API]` and
`[ALERT-TASK]` processes. Readiness stays green throughout because `/health` does not touch
Mongo.

**Server side.** `clickstack-mongodb-0`'s mongod log gives the precise reason:

```
"msg":"Failed to authenticate","attr":{"client":"10.244.4.102:45696","mechanism":"SCRAM-SHA-256",
"user":"hyperdx","db":"hyperdx","error":"AuthenticationFailed: SCRAM authentication failed,
storedKey mismatch","result":18}
```

`10.244.4.102` is the `clickstack-app` pod. Connections from the metrics sidecar and from the
mongod pod itself authenticate successfully as the *same* `hyperdx` user in the same log window,
so the server-side credential is fine.

**Verified cause — and what it is not.** The password inside `cm/clickstack-app-config`'s
`MONGO_URI` **matches** the current ESO-generated secret, so the rendered config is correct. But
the *running pod's injected* `MONGO_URI` password does **not** match. The chart delivers
`MONGO_URI` via `envFrom.configMapRef`, which is evaluated once at pod start; the ConfigMap was
re-rendered when the ESO `Password` generator regenerated (secret `creationTimestamp`
2026-08-20T22:58Z, i.e. the mongo migration itself), the Deployment's pod spec did not change,
so Helm never rolled the pods. The pod has been running with the pre-rotation credential for two
days.

**Fix (not applied — this audit is read-only):** `kubectl -n monitoring rollout restart
deploy/clickstack-app`. To stop it recurring, the HelmRelease needs a checksum annotation on the
pod template derived from the credential, or the URI needs to come from a `secretKeyRef` the
kubelet can refresh.

**This is the [eso-generator-rotation gotcha] with a new tail.** The known failure mode is
"generator regenerates → consumers drift". The new part is that even when Flux *does* re-render
the consumer's ConfigMap correctly, an `envFrom` consumer never picks it up. Any future
MongoDBCommunity wired the same way inherits this. Worth folding into the house pattern below.

---

## 6. The house pattern — how to add a new MongoDB

Recorded because the brief asked for it, and because the pattern is genuinely good apart from
the caveat in [§5](#5-live-defect-clickstack-app-holds-a-stale-mongo_uri).

**Operator:** `mongodb-kubernetes` (MCK) 1.10.0, `HelmRelease` in `databases`, `watchNamespace:
"*"`, `watchedResources: [mongodbcommunity]`, telemetry off. It reconciles the same
`mongodbcommunity.mongodb.com/v1` kind the deprecated community-operator did.

To add a new instance:

1. **ServiceAccount + Role + RoleBinding named `mongodb-kubernetes-appdb` in the target
   namespace.** The operator defaults the StatefulSet pod SA to this name and does **not**
   create it in watched namespaces. Both existing instances ship their own copy.
2. **An ESO `Password` generator + `ExternalSecret`** producing a key literally named `password`
   (MongoDBCommunity's `passwordSecretRef` reads that key), plus a templated full
   `mongodb://…` URI from the *same* generated value so the two cannot drift. Set `symbols: 0` —
   the value goes into a URI.
3. **Inject the URI via HelmRelease `valuesFrom`, not Kustomization `postBuild`.** `postBuild`
   runs `envsubst` over every manifest in the path and has already broken an unrelated Mimir
   HelmRelease whose config legitimately contains a runtime `${AWS_ACCESS_KEY_ID}` literal.
   `valuesFrom` is scoped to one release and reads the Secret from the release's own namespace,
   so no cross-namespace mirroring is needed either.
   *(The `clickstack-mongodb-secret.yaml` header still describes the older `postBuild` route and
   its reflector annotations to `flux-system`; the HelmRelease has since moved to `valuesFrom`.
   The reflector annotations are now vestigial.)*
4. **Secret must live in a Kustomization that reconciles BEFORE the consumer** — hence
   `v2-otel/operators/`, with the consumer's Kustomization `dependsOn` it. Putting it beside the
   HelmRelease deadlocks permanently.
5. **Label the pod `catalyst.io/mongodb: instance`** in
   `statefulSet.spec.template.metadata.labels`. The global PodMonitor in
   `infrastructure/base/monitoring/mongodb-monitoring/` selects that label across all namespaces.
   One label = fully scraped; nothing else to wire.
6. **Add a `percona/mongodb_exporter` sidecar** with `--collect-all`, and grant the user
   `clusterMonitor` on `admin`. Without the grant the exporter *nil-derefs* rather than
   degrading — 3/3 Ready, serving nothing. The operator ships no metrics of its own.
7. **Add a config-checksum annotation** so credential rotation actually restarts the consumer.
   See [§5](#5-live-defect-clickstack-app-holds-a-stale-mongo_uri). This step does not exist in
   either current instance and is the gap this audit found.

### Storage: the two instances disagree, and clickstack is right

`clickstack-mongodb` uses `local-path` with the comment *"NOT on NFS — MongoDB explicitly
advises against NFS for dbPath."* `scratch-mongodb` uses `fatboy-nfs-appdata`. Both have run
without incident.

MongoDB's own position is a strong discouragement rather than a prohibition: the Production
Notes say to **avoid NFS for `dbPath`** because it "can result in degraded and unstable
performance", while allowing that WiredTiger objects *may* live on a remote filesystem if it
conforms to POSIX.1, with specific mount options (`bg`, `hard`, `nolock`, `noatime`) if you do
([Production Notes](https://www.mongodb.com/docs/manual/administration/production-notes/)).

**So NFS is not available as a free un-pinning shortcut for a Mongo that matters** — but it is
defensible for a scratch instance, which is what `scratch-mongodb` is. Keep the split as it
stands; do not "fix" `scratch-mongodb` onto local-path, since that would *create* a pin to solve
a problem it does not have.

---

## 7. Where Mongo is the wrong answer

The brief asked explicitly for this. Two cases:

### FerretDB — considered and rejected

FerretDB is a MongoDB wire-protocol layer backed by PostgreSQL, and there is a published
walkthrough of it working as a drop-in for HyperDX's MongoDB
([FerretDB blog](https://blog.ferretdb.io/full-stack-observability-hyperdx-ferretdb/)). On paper
that is attractive here: CNPG is by far the more mature setup in this cluster (12 clusters,
barman backups, a proven migration runbook at
`applications/arr-stack/base/postgres/MIGRATION-RUNBOOK.md`), so folding the one Mongo consumer
onto Postgres would remove an entire operator.

**Recommend against it.** The walkthrough uses the bundled `ferretdb-eval:2` image and makes no
production claim; it would swap a working, monitored, operator-managed MongoDB for an extra
translation layer; and the benefit — removing a `talos06` pin on a database holding zero
documents — is nil. Revisit only if the MongoDB operator itself becomes a maintenance burden.

### There is no "hand-rolled Mongo that should be Postgres instead"

The Postgres audit's most actionable operator finding was four hand-rolled `pgvector` Postgres
that should be CNPG. The symmetric finding here would be a hand-rolled Mongo that should be
either the Mongo operator *or* CNPG. **There isn't one.** The only hand-rolled Mongo this repo
ever contained was `observability/mongodb` (Bitnami chart 18.1.9, standalone, `auth.enabled:
false`, 20Gi) backing Graylog, and it was deleted along with the whole v1 observability stack in
`34de46d5` (2025-12-16). Nothing replaced it.

---

## 8. Leave these alone

| Workload | Why not |
| --- | --- |
| **`scratch/scratch-mongodb`** | Already on `fatboy-nfs-appdata`, no `nodeAffinity`, pins nothing. It is the operator usage example. Delete it if the example is no longer wanted, but there is no migration here |
| **`monitoring/clickstack-mongodb`** | Already operator-managed, already guarded against control-plane binding, on a non-target node, holding 0 documents. Migrating it would be work with no beneficiary |
| **HyperDX / ClickStack app state** | Mongoose-only. There is no Postgres option; the only alternative is a compatibility layer — see [§7](#7-where-mongo-is-the-wrong-answer) |
| **All `media-experimental` apps** | Already settled by the Postgres audit as backup/restore, not migration. None supports Mongo, so this audit changes nothing |
| **SPIRE** | Datastore is `sqlite3`/`postgres`/`mysql`. Already a *delete* candidate ([TALOS-1d4o]), not a database-migration candidate of any flavour |
| **Pi-hole (5 PVs)** | SQLite-only by design, and the per-pod local-path pattern is deliberate — see [pihole-ha-pattern.md](pihole-ha-pattern.md) |
| **Mimir, Loki, Tempo, ClickHouse** | Object-storage-backed telemetry stores. No embedded-DB concept applies |
| **`registry/zot`, `gaming/opensim`, `crowdsec` LAPI, `crowdsec-web-ui`, Frigate, Scrypted, jellyfin, plex** | Each already has a documented disposition in the Postgres audit [§6], and none of them gains a MongoDB option that would change it |
| **`tdarr/tdarr-server`** | SQLite with no external-DB option. Its PVs are NFS with no `nodeAffinity`, so it pins nothing by storage. Its `nodeSelector: talos06` is an EPIC 3 question, not a database one — but see [§9](#incidental-findings-worth-their-own-tickets) |

---

## Incidental findings worth their own tickets

Three things surfaced that are outside the Mongo question but should not be lost.

**1. Tdarr is running a 610 MB SQLite database on NFS, with a 627 MB WAL.** Measured in-pod:
`/app/server/Tdarr/DB2/SQL/database.db` is 639,479,808 bytes with a 656,983,472-byte `-wal` and a
1.2 MB `-shm`, on `tdarr-server-pv` → `192.168.1.36:/volume1/appdata/media/tdarr-server`. This is
exactly the SQLite-on-NFS shape this cluster already regressed on with the arr stack in December
2025 and deliberately migrated *off*. It is currently working, and Tdarr is single-writer so the
locking exposure is lower than the arr case — but a WAL larger than the database suggests
checkpointing is not completing, which is itself an NFS-flavoured symptom. Worth a look
independently of any migration. (`DB2/JobReports` is a further 11 GB of loose files.)

**2. `tdarr-server` carries `nodeSelector: kubernetes.io/hostname: talos06` with no PV
requiring it.** All three of its `tdarr-appdata` PVs are plain NFS with `nodeAffinity: none`. This
is a candidate class-(a) accidental pin for [TALOS-3hl8] — the same shape as the sonarr/radarr
"pin to talos03 for local downloads" comment that proved false. It is on `talos06`, so it is not
urgent, but it should be verified rather than assumed structural. EPIC 3 currently lists it under
*candidates* for class (c).

**3. The Postgres audit's `arr-stack-private` coverage gap can be closed.** That audit recorded
`talos-private.git` as "private repo, not inspected". It **is** checked out locally at
`/Users/panda/catalyst-devspace/workspace/talos-private`. Inspected for this audit: it contains
**zero** Mongo references and **zero** `local-path` claims — every PVC is `fatboy-nfs-appdata`,
`synology-nfs` or `tdarr-nfs`. The inference the Postgres audit made was correct, and can now be
recorded as verified.

---

## 9. Coverage — what was and was not verified

### Method

Three independent sweeps, so a miss would have to evade all three:

1. **Image inventory.** Every container image across all 62 namespaces, filtered for
   `mongo|documentdb|ferretdb`. Result: 3 images, all operator-managed.
2. **Storage sweep.** The complete `local-path` PV → node → PVC → pod map (66 PVs, 5 nodes),
   plus a storage-class census of all 129 PVCs. A workload with no `local-path` PVC cannot pin a
   node, so this bounds the problem exhaustively.
3. **Manifest + history sweep.** `grep -ril mongo` across `talos-homelab` and every sister repo
   under `workspace/`, plus `git log -S` and `--diff-filter=D` for hand-rolled Mongo that once
   existed. This catches manifests that are in git but not deployed.

Candidates were then probed in-pod (`du`, `mongosh db.stats()`, `rs.status()`) rather than
trusting PVC claim sizes, and upstream external-DB support was researched and cited inline.

### Verified against the live cluster (high confidence)

- The complete Mongo inventory: 2 `MongoDBCommunity` CRs, 1 operator, 3 mongod-family images.
- `clickstack-mongodb` on-disk breakdown (239 MB, 200 MB journal, 37 MB FTDC) and authenticated
  `db.stats()` showing 11 collections / **0 documents** / 118 KB; `rs.status()` showing a
  single-member `PRIMARY`.
- `scratch-mongodb` on-disk breakdown (528 MB, 300 MB journal, 208 MB FTDC) and its
  `fatboy-nfs-appdata` PVCs with no `nodeAffinity`.
- The `talos01` (8) and `talos03` (14) pin sets, re-derived independently and matching
  [TALOS-3gte]. Note `media/radarr-db-local` and `media/sonarr-db-local` are **gone** — those two
  migrations completed since the Postgres audit was written.
- `clickstack-app`'s `MONGO_URI` source (`cm/clickstack-app-config` via `envFrom`), the
  ConfigMap-vs-secret match, and the **running pod's env-vs-secret mismatch**.
- mongod's `storedKey mismatch` auth failures attributed to the app pod's IP, alongside
  successful auths for the same user from the sidecar.
- Tdarr's on-disk SQLite sizes and its PVs' storage classes / absent `nodeAffinity`.
- `talos-private` contents: no Mongo, no `local-path`.
- `observability` namespace is empty (`No resources found`).

### Evidenced upstream claims (docs URL / config keys cited inline)

Open WebUI, CrowdSec, SPIRE, zot, OpenSimulator, Tdarr, HyperDX/FerretDB, MongoDB's own NFS
guidance. Each carries a link at the point of use.

### NOT verified — do not act on these as fact

- **Why `clickstack-app`'s auth failures are intermittent rather than total.** The stale-env
  mismatch is verified; whether the interleaved "Connection established" lines represent genuine
  successful operations or just mongoose topology events was not established. It does not change
  the fix, but do not read those lines as "it mostly works".
- **Whether HyperDX's empty database is *entirely* explained by the stale credential.** It is the
  obvious and sufficient cause, but nobody may simply have logged in since 2026-08-20 either.
- **Tdarr's WAL behaviour.** The 627 MB WAL alongside a 610 MB database is reported as measured.
  Whether checkpointing is actually failing, and whether NFS is the reason, was not diagnosed.
- **Whether `tdarr-server`'s `nodeSelector` is genuinely unnecessary.** Only established that no
  PV requires it. There may be a hardware or transcode reason not visible in the manifests.
- **`scratch-mongodb`'s purpose.** Treated as the operator usage example because that is what
  `applications/scratch/example-mongodb/` says. Nobody was asked whether it is still wanted.
- **`bindery-config`** remains unverified on disk (distroless, no shell) — inherited from the
  Postgres audit. Upstream is SQLite-only either way, so it is not a Mongo candidate regardless.

### Explicitly out of scope

Namespaces with neither a `local-path` PVC nor a Mongo-capable workload were not probed for
embedded stores; they cannot pin a node and cannot become a Mongo migration. The Postgres audit's
out-of-scope list applies unchanged. If any of them later grows a `local-path` PVC *or* a Mongo
dependency, re-check it.

---

## Related Issues

- [TALOS-3hl8] — EPIC 3: eliminate unnecessary node affinities cluster-wide (this audit's driver)
- [TALOS-k62s] — EPIC 0: un-node-bind PVCs before any control-plane reset
- [TALOS-3gte] — talos03 still has 14 node-bound PVs (independently confirmed here; no Mongo among them)
- [TALOS-1d4o] — Decide SPIRE: keep and back up, or disable
- [TALOS-uml1] — Back up + restore the 12 media-experimental configs
- [TALOS-j4jy] — **filed by this audit** — clickstack-app stale `MONGO_URI`, continuous SCRAM auth failures ([§5](#5-live-defect-clickstack-app-holds-a-stale-mongo_uri))
- [TALOS-r6ib] — **filed by this audit** — tdarr SQLite-on-NFS + a `talos06` `nodeSelector` no PV requires (blocks [TALOS-3hl8])
- [embedded-db-migration-audit.md](embedded-db-migration-audit.md) — the Postgres/CNPG half of this survey
