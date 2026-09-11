# S3 Backend Evaluation — replacing MinIO CE

> Research: 2026-09-11 (5 parallel agents, current-year data). Epic: **TALOS-9aw8**.

## TL;DR

- **MinIO CE is dead, not dormant.** The repo was flagged "NO LONGER MAINTAINED" (2026-02-12) and
  **archived read-only (2026-04-24)**, carrying **2 CRITICAL + 4 HIGH CVEs that will never be
  patched** — including a JWT/OIDC auth bypass (CVE-2026-33322) that hits our exact OIDC config, two
  unauthenticated-object-write bugs, and an STS session-policy bypass matching our scoped-user
  pattern. Our server pin is ~22 months old, so we're exposed to the whole list. **Severity is
  bounded** — `minio`/`s3` are on the LAN-only `web` entrypoint, no internet surface — but this is a
  "leave this quarter," not "sit on it forever."
- **Docker Hub deleted `minio/minio` + `minio/mc`.** Our pins only resolved from node cache. **Fixed
  now** by repointing to `quay.io/minio/*` (surviving official mirror, fresh-pull verified) — commit
  `06333976`. `minio/operator` still lives on Docker Hub.
- **Recommendation: migrate to Garage for general object storage, and strongly consider Versity
  Gateway (versitygw) for the backup-of-record role.** Both are the anti-MinIO in governance. The one
  decision gate is **object versioning** (Garage has none).
- **Not viable here:** Ceph/Rook (all 5 nodes are single-disk — nothing to build OSDs on; ~20–26 GB
  RAM floor). **Wrong risk profile:** SeaweedFS (bus-factor-1 + durability features going paid).
  **Too early:** RustFS (pre-GA, recent CVSS 9.8).

---

## The field of play

| | **MinIO CE** | **Garage** | **versitygw** | **SeaweedFS** | **Ceph/Rook RGW** | **RustFS** |
|---|---|---|---|---|---|---|
| **Latest** | RELEASE.2025-10-15 (last ever) | v2.4.1 (2026-09-08) | v1.8.0 (2026-09-04) | v4.46 (2026-09-08) | Ceph 20.2.4 / Rook 1.20.7 (2026-09) | 1.0.0-rc.6 (2026-09-11) |
| **Cadence** | — | ~3–4 mo + LTS | ~monthly | ~38 rel/yr (rolling) | point ~1–4 mo | pre-GA |
| **90-day commits** | **0** | 85 (20 authors) | active | ~960 (bus-factor 1) | Rook 622 / Ceph 2,887 | high |
| **Status** | ☠️ archived | 🟢 active, rising | 🟢 active | 🟢 active | 🟢 mature | 🟡 pre-GA |
| **License** | AGPL (abandoned) | **AGPL-3.0** | **Apache-2.0** | Apache-2.0 (open-core) | LGPL | Apache-2.0 |
| **Governance** | MinIO Inc (gone) | Deuxfleurs non-profit | Versity (genuine OSS) | 1 person | CNCF / Ceph Fdn (IBM/RH) | CN single-vendor |
| **Web UI** | gutted → deleted | none (NLnet-funded, WIP) | preview-quality | **broad, built-in** | Ceph Dashboard | built-in console |
| **Versioning** | yes | ❌ **none** | opt-in (POSIX) | yes | yes | claimed |
| **Object-lock** | yes | ❌ | unverified | yes | yes | claimed |
| **HA / durability** | erasure coding | replication 1/2/3 | = underlying FS | replication + EC¹ | CRUSH repl/EC | EC |
| **Footprint** | baseline | **~20× lighter** | thin gateway | light–med | **20–26 GB RAM floor** | unknown |
| **K8s** | operator (archived) | community helm | official helm (OCI) | operator + helm | **mature Rook operator** | v0.1 operator |
| **Homelab fit** | — | **4.5/5** | **5/5** (backups) | 3/5 | ⛔ blocked | revisit post-GA |

¹ SeaweedFS **automatic EC shard repair + bitrot scrubbing are paid Enterprise features** — a real caveat for a backup target.

---

## What our consumers actually need

Our S3 is used by **CNPG barman-cloud** (Postgres WAL + base backups), **Velero** (cluster
backup/restore), **ESO static creds**, and the **MinIO operator + tenant** (`servers:1,
volumesPerServer:1` — a simple target). None use the console. Requirements: multipart upload
(barman + Velero), presigned URLs, list/get/put/delete. Object-lock is *nice* for Velero
(immutable backups) but not required. **Versioning is only needed if a specific bucket relies on
it** — the one flag that rules Garage in or out.

---

## Per-option

### Garage — the frontrunner ✅
AGPL-3.0, run by **Deuxfleurs** (French non-profit; published an explicit anti-VC / "commoning
open source" position — structurally the opposite of MinIO). Active: v2.4.1 (2026-09-08), 85
commits/90d across 20 authors, fresh 1-yr NLnet grant (2026-04). **~20× lighter** than our MinIO
tenant; covers everything barman-cloud and Velero need. **Blockers:** (1) **no object versioning
and no lifecycle** — hard-stop for any bucket that needs them; (2) **no built-in console** (an
admin UI is separately NLnet-funded but not shipped); (3) we lose the MinIO Console + the Authentik
OIDC SSO we wired to it. Bus-factor concern (lead ~20% of recent commits — improving; AGPL + no CLA
means a fork is always possible). Issues live on their Forgejo, not GitHub.

### Versity Gateway (versitygw) — the dark horse for backups ✅
Apache-2.0, backed by Versity (commercial archive vendor; this is their genuine OSS front door).
Active: v1.8.0 (2026-09-04), ~monthly. It's an **S3-over-POSIX gateway** — puts an S3 face on the
NVMe/NFS we already have. **Killer property for a backup-of-record target: data stays as ordinary
files** — if versitygw dies, our Postgres basebackups are still readable on disk (no opaque
chunk/EC format). barman-cloud is confirmed working in real CNPG deployments; official Helm chart
(OCI). **Caveats:** it's a gateway, so durability/HA = whatever the filesystem gives (no cross-node
replication of its own); versioning is opt-in on POSIX; **object-lock and Velero end-to-end are
unverified** (must test); UI is preview-quality; multi-replica needs the new standalone IAM
(v1.8.0), not the file-store IAM. TrueNAS independently converged on versitygw as its
"filesystem → S3" answer after dropping community MinIO.

### SeaweedFS — capable, wrong risk profile ⚠️
Apache-2.0, the most active project in the class (~960 commits/90d) with a **broad built-in admin
UI** (closest to the old MinIO Console). But **bus-factor 1** (chrislusf = 71% of recent commits, no
governance/co-maintainer) and **open-core creeping into durability**: automatic EC shard repair and
bitrot scrubbing are **paid Enterprise** features. For a backup-of-last-resort target that's the
wrong trade — and the open-core direction is the very thing we're leaving. Fine as general-purpose
homelab S3 with a second copy elsewhere; not as the sole home for backups.

### Ceph / Rook RGW — best tech, blocked here ⛔
Technically the strongest S3 (RGW: full compat, versioning, object-lock, STS) and safest long-term
bet (CNCF-graduated Rook, Ceph Foundation, 20 yrs). **But blocked on hardware:** all 5 Talos nodes
have exactly one disk (the OS disk) and no spare devices/partitions/block-PVs — Rook has nothing to
build OSDs on. Even with disks added, the realistic **~20–26 GB RAM cluster floor** is 3–5× MinIO
for a WAL-and-tarball workload. Revisit only if the cluster grows dedicated storage nodes.

### RustFS — promising, not yet ⏳
Apache-2.0 Rust MinIO-alike with a built-in console — the most likely eventual drop-in. But
**pre-GA** (1.0.0-rc.6, no GA date), a v0.1 operator, Chinese single-vendor origin, and a recent
**CVSS 9.8** hardcoded-gRPC-token bug. **Re-evaluation trigger: GA + one quiet quarter.** Not for
backups today.

### Escape hatches (no data migration)
- **SILO (`pgsty/minio`)** — a maintained AGPL MinIO-server fork (Pigsty). Because our Tenant CRD
  just runs the server binary, swapping `spec.image` to a SILO tag is plausibly **drop-in** — the
  only option that fixes the security exposure *without* a data migration. Worth a scratch-namespace
  test as a hedge if migration slips.
- **Clyso Chorus** — S3 migration/replication tooling; the cleanest documented path to move off
  MinIO **without downtime** regardless of the target. Evaluate as tooling for the cutover.

### Ruled out
Apache Ozone (no versioning/object-lock, JVM sprawl), Zenko/CloudServer (closed IAM, lab-grade),
CubeFS (Ceph-scale ops, less mature), JuiceFS (circular dep with CNPG backups), Storj (satellite,
not self-host prod), s3proxy/rclone-serve (single-node; rclone has an active critical advisory).
Dead: OpenIO, Riak CS, s3gw.

---

## Recommendation

1. **Now (done):** quay.io repoint (`06333976`) removes the disappearing-image risk.
2. **Decide the versioning question first** — inventory every bucket and whether any relies on
   object versioning / lifecycle / object-lock. This single answer picks the path:
   - **No bucket needs versioning →** Garage for everything. Lightest, most values-aligned, active.
   - **Some do (or we want immutable backups) →** Garage for general object storage **+ versitygw
     for the backup-of-record role** (barman/Velero on readable files), or a single versitygw if we
     want one system and accept gateway-only durability over our NFS/NVMe.
3. **Spike before committing:** (a) versitygw — Velero end-to-end + does object-lock actually work
   on POSIX + versioning-over-NFS sanity; (b) Garage — GitOps deployment story (helm/operator
   maturity) + how we replace the Authentik-SSO'd console.
4. **Hedge:** keep **SILO** in the back pocket as the no-migration security fix if the migration
   can't land this quarter; plan the cutover with **Chorus** for zero downtime.

**Bottom line:** your Garage lean is well-founded — it's the healthiest, lightest, most
philosophically-aligned option, and it covers our backup clients. The only thing that would split
the decision is versioning, where **versitygw** is the surprisingly strong complement (or
alternative) precisely for the backup role.

---

## Related Issues

- **TALOS-9aw8** — Migrate off MinIO CE (this epic)
- **TALOS-9aw8.1** — This comparative analysis
- **TALOS-0xb3** — No Docker Hub pull-through mirror (related supply-chain gap)
