# Promote Two Workers to Control Plane (1 CP → 3 CP)

> ## ⚠️ COMPLETED — historical. Do not execute.
>
> This cluster already has three control planes: talos00, talos01 and talos03. There is
> nothing left to promote.
>
> The config-generation steps are also superseded — they build configs with `talosctl gen
> config` from `configs/secrets.yaml` into `configs/nodes/<NODE>/`, and that tree is archived
> to `.scratch/__configs/`. Machine configs now come from `configs/talconfig.yaml` via
> talhelper; a node's control-plane status is the `controlPlane: true` field there.
>
> Kept because the destructive-reset warnings are still true and still the best writeup in
> this repo of them: Talos cannot change machine type in place, `talosctl reset` wipes
> `/var` and therefore every `local-path` PV on that node, and Velero does not back up
> local-path PVs. Read those before any reset, promotion or not.

**Risk:** HIGH — destructive. Each promoted node is wiped and reinstalled.
**Estimated time:** 3–5 hours including data migration. Do not start after 22:00.
**Blast radius:** every `local-path` PersistentVolume on the promoted node is **permanently destroyed**.

> **⚠️ READ THIS FIRST**
> Talos **cannot** change a node's machine type in place. Promotion is `talosctl reset` + apply a
> controlplane config. `talosctl reset` wipes the EPHEMERAL partition, which Talos mounts at `/var` —
> exactly where `local-path` provisions. **A promotion destroys every local-path PV on that node.**
>
> And the part that surprises people: **Velero does not back up local-path PVs.** Not "sometimes" —
> never. See [The Velero Gotcha](#3-the-velero-gotcha-read-this-before-you-trust-any-backup). Do not
> begin until you have read that section and re-run the inventory yourself.

---

## TL;DR (30 seconds)

- **Promotion = full node reset.** No in-place role change exists in Talos. Sidero's position: role
  conversion touches PKI, etcd membership and service topology in ways that cannot be done safely
  in-place, and Talos does not document or test non-reset paths.
- **Reset wipes `/var` → all local-path PVs on that node die.** `local-path` is
  `WaitForFirstConsumer`, so those PVs are pinned to the node and cannot migrate themselves.
- **The fix is to stop having node-bound storage on nodes you plan to reset** — not to evacuate it at
  2am. [§0](#0-un-bind-what-can-be-un-bound-prerequisite--before-you-schedule-anything) sorts each
  node's volumes into un-bindable vs genuinely stuck. **`radarr`/`sonarr`/`prowlarr` can move to
  CNPG Postgres and stop being node-bound at all** — that is a week of project work to do *before*
  the window, not during it. Jellyfin and Plex are SQLite-only and cannot.
- **Velero does NOT protect them.** Every local-path PV is a `hostPath` volume, and Velero's
  file-system backup skips `hostPath` by design — even when you explicitly name the volume in the
  opt-in annotation. The backup still reports `Completed`, so the gap only shows up in the backup
  log. Velero's own log line is quoted in [§3](#3-the-velero-gotcha-read-this-before-you-trust-any-backup).
- **Recommended order: `talos01` first, then `talos03`** — argued in
  [§6](#6-node-ordering-argued-from-the-inventory) from *how much un-binding work each node needs*,
  not from PV count. talos01 needs none; talos03 is gated on the \*arr → CNPG project.
- **The one genuinely fragile window** is between node 2 becoming an etcd *voter* and node 3
  becoming a voter: 2 voters, quorum 2, **tolerates zero failures**. etcd learner mode protects the
  join itself, but not this gap. **Do both nodes in one sitting. Do not stop in between.**
- **One item has no automated backup of any kind: `forgejo/forgejo-data` (git repositories).**
  Hand-copy it. It measured **~156 KB with zero repositories** at time of writing, so today this is
  cheap — but **re-measure**, because that changes the day someone pushes a repo. This is a standing
  gap, not something this procedure creates.
- **After every reset, re-apply the kubelet patches** (`scripts/bootstrap-talos-patches.sh`) or the
  node returns with `maxPods: 110` and local-path broken.

---

## Quick Reference (5 minutes)

Set these once per shell:

```bash
cd /Users/panda/catalyst-devspace/workspace/talos-homelab
export TALOSCONFIG="$PWD/configs/talosconfig"
```

| Node | IP | Role today | Local-path PVs | Running pods (DS / relocatable) |
| --- | --- | --- | --- | --- |
| talos00 | `192.168.1.54` | control-plane (**tainted**) | 1 | 17 (9 / 8) |
| talos01 | `192.168.1.177` | worker | 8 | 39 (12 / 27) |
| talos02-gpu | `192.168.1.144` | worker (**only GPU node**) | 10 | 107 (13 / 94) |
| talos03 | `192.168.1.30` | worker | 16 | 52 (11 / 41) |
| talos06 | `192.168.1.19` | worker | 33 | 90 (13 / 77) |

| Task | Command |
| --- | --- |
| Check etcd membership + learner state | `talosctl -n 192.168.1.54 etcd members` |
| Check cluster health | `talosctl -n 192.168.1.54 health` |
| Inventory a node's local-path PVs | [§4 script](#4-pre-flight-inventory-and-classification-run-this) |
| **DESTRUCTIVE** — reset a node | `talosctl -n <ip> reset --graceful --reboot` |
| Apply controlplane config | `talosctl -n <ip> apply-config --insecure --file <cfg>` |
| Re-apply kubelet patches | `./scripts/bootstrap-talos-patches.sh` |
| Verify maxPods came back at 200 | `kubectl get nodes -o custom-columns=NAME:.metadata.name,MAXPODS:.status.capacity.pods` |

**Go / no-go gate before each node** — all must be true:

- [ ] **§0 class (b) un-binding work is complete and soaked** for *both* target nodes — not just this
      one. Promoting node 1 with node 2 still blocked parks you at 2 voters (§6).
- [ ] `talosctl -n 192.168.1.54 etcd members` shows every existing member healthy, `LEARNER false`
- [ ] No pods in a non-Running/non-Succeeded phase cluster-wide
- [ ] The node's local-path PV inventory has been re-run **today** and every entry is classified
- [ ] Every SINGLETON on the target node is backed up **and the backup has been verified readable**
- [ ] A fresh etcd snapshot exists (< 1 hour old)
- [ ] You have ≥ 3 uninterrupted hours ahead of you

---

## Deep Dive

### 0. Un-bind what can be un-bound (PREREQUISITE — before you schedule anything)

The right fix is not "evacuate the PVs, then reset". It is **stop having node-bound storage on nodes
you intend to reset.** Backup-and-restore is the fallback for what genuinely cannot move, not the
plan.

Sort the target node's local-path PVs into four classes. Only class (d) belongs in the maintenance
window; classes (b) and (c) are **project work to complete first**.

#### (a) ALREADY REPLICATED — no work

Data exists in ≥ 2 more places; the reset costs a rebuild, not a restore.

- **CNPG members of 3-instance clusters** — `authentik-postgres-*`, `boomtime-postgres-*`,
  `forgejo-postgres-*`, `crowdsec-postgres-*`. CNPG re-clones by streaming. Fail over first if the
  node holds the primary (§5a). **But set the maintenance window first — see immediately below;
  deleting the PVC by hand is the fallback, not the procedure.**

> #### ⚠️ Set `nodeMaintenanceWindow` BEFORE resetting a node that holds CNPG replicas
>
> CNPG has a designed path for exactly this, and the default is wrong for a *reset*.
>
> `spec.nodeMaintenanceWindow.reusePVC` defaults to **on**, which per the CRD means *"reuse the
> existing PVC (wait for the node to come up again)"*. That is correct for a reboot. It is wrong
> for `talosctl reset`, which **wipes EPHEMERAL at `/var`** — the node returns, but the data
> behind that PV is gone, so CNPG sits waiting for a volume that will never be valid again.
>
> Setting `reusePVC: false` makes CNPG *"recreate it elsewhere"* — it relocates the replica to a
> different node with a fresh PVC and rebuilds it by physical streaming replication. The CRD is
> explicit that this only applies **when `instances` > 1**, which is precisely why 3-instance
> clusters are safe on `local-path` at all.
>
> **None of our clusters set this today** — `authentik-postgres`, `boomtime-postgres` and
> `arr-postgres` all leave `nodeMaintenanceWindow` unset, so they default to waiting. Both
> `authentik-postgres` and `boomtime-postgres` have a replica on **talos01**, the first promotion
> target.
>
> Before resetting a node, for every 3-instance CNPG cluster with a replica on it:
>
> ```yaml
> spec:
>   nodeMaintenanceWindow:
>     inProgress: true
>     reusePVC: false      # recreate elsewhere via streaming replication
> ```
>
> ```bash
> # which clusters have a replica on the node you are about to reset?
> kubectl get pods -A -l cnpg.io/podRole=instance -o wide \
>   | awk -v n=talos01 '$8==n {print $1, $2}'
> ```
>
> Revert `inProgress` to `false` once the node is back and the replica has re-cloned. Leaving a
> cluster permanently in a maintenance window changes how CNPG reacts to *unplanned* failures.
>
> The hand-rolled alternative — delete the PVC and pod after the reset and let CNPG rebuild — does
> work, and is what was used during the 2026-08-21 NFS→NVMe migrations. But that was a *storage
> migration* on a live node, not a node being wiped. For a reset, use the operator's own path.
- **`monitoring/storage-mimir-ingester-*`** — `replication_factor: 3` across exactly 3 ingesters, so
  every series is on all three.

```bash
# confirm a cluster is really 3-instance before trusting this
kubectl get clusters.postgresql.cnpg.io -A \
  -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,INSTANCES:.spec.instances,READY:.status.readyInstances
```

#### (b) CAN BE UN-BOUND FIRST — the \*arr apps to CNPG

**`radarr`, `sonarr` and `prowlarr` do not need local storage at all.** All \*arr apps support
PostgreSQL as a drop-in replacement for SQLite, configured entirely through **environment variables**
— no `config.xml` edit. Moving them to a CNPG cluster removes the node-binding *and* gives them
backup coverage they do not have today (CNPG → MinIO, which actually works, unlike Velero on
hostPath).

Installed versions are all comfortably past the requirement (Radarr needs ≥ v4.1.0.6133):

| App | Installed | Postgres-capable | Currently pinned to |
| --- | --- | --- | --- |
| radarr | `6.0.4.10291-ls289` | yes | **talos03** |
| sonarr | `4.0.16.2944-ls300` | yes | **talos03** |
| prowlarr | `2.3.0.5236-ls133` | yes | talos02-gpu |

Each app needs **two** databases (main + logs) owned by the same Postgres user. Migration from an
existing SQLite DB is via `pgloader`. Configuration is by env var, e.g.:

```yaml
# illustrative — see the servarr wiki links in References for the authoritative variable list
- { name: PROWLARR__POSTGRES__HOST,     value: arr-postgres-rw.media.svc }
- { name: PROWLARR__POSTGRES__PORT,     value: "5432" }
- { name: PROWLARR__POSTGRES__USER,     valueFrom: { secretKeyRef: { name: arr-postgres-app, key: username } } }
- { name: PROWLARR__POSTGRES__PASSWORD, valueFrom: { secretKeyRef: { name: arr-postgres-app, key: password } } }
- { name: PROWLARR__POSTGRES__MAINDB,   value: prowlarr-main }
- { name: PROWLARR__POSTGRES__LOGDB,    value: prowlarr-log }
```

Doing this also lets you **delete the `nodeAffinity` pins** on radarr and sonarr, which are otherwise
a live trap (§7).

> **Treat this as a prerequisite project, not a maintenance-window step.** Realistically: a CNPG
> cluster plus 6 databases, a `pgloader` run per app against a 267 MB / 548 MB / 8 MB SQLite file,
> env-var plumbing through the Flux kustomization, and a soak period to confirm nothing regressed.
> Budget roughly **a day for the first app and half a day for each of the others, plus a few days of
> soak** — call it a week of elapsed time. Attempting it at 2am alongside a control-plane promotion
> is how you end up with neither.

#### (c) MOVABLE TO NFS — smaller than it looks

> **⚠️ This class is mostly empty here, contrary to the obvious guess.** The 13
> `media-experimental/*-config` volumes on talos03 look like plain config directories. **They are
> not — they hold SQLite**, which is exactly what NFS must not host. Verified:
>
> | App | Found on its config volume |
> | --- | --- |
> | komga | `database.sqlite`, `database.sqlite-wal`, `database.sqlite-shm`, `tasks.sqlite` |
> | audiobookshelf | `absdatabase.sqlite` |
> | mylar3 | `mylar.db`, `.mylar_maintenance.db` |
>
> Moving these to NFS reintroduces precisely the SQLite-over-NFS locking problem that
> `shared/db-migration-configmap.yaml` was written to escape. **Do not do it.**

So audit per app rather than assuming — I confirmed 3 of 13 are SQLite-backed and could not exec into
2 more (`kavita`, `storyteller`); the rest are unverified:

```bash
# run across every candidate before declaring anything NFS-safe
for app in audiobookshelf bindery booksonic chaptarr kavita komga libation \
           librarr livrarr mylar3 storyteller; do
  echo "--- $app ---"
  kubectl exec -n media-experimental deploy/$app -- sh -c \
    'find /config -maxdepth 3 \( -name "*.db" -o -name "*.sqlite*" \) 2>/dev/null | head -4' \
    2>/dev/null || echo "  (could not exec — check by hand)"
done
```

A volume qualifies for class (c) only if that command returns **nothing**. Anything else is class (d)
or needs its own Postgres migration.

#### (d) GENUINELY STUCK — backup/restore, or accept the loss

State this per item, and decide *which* before the window opens:

| Item | Node | Verdict |
| --- | --- | --- |
| `media/jellyfin-db-local`, `media/plex-db-local` | talos02-gpu | **Accept-the-loss or hand-copy.** Jellyfin and Plex are **SQLite-only — no PostgreSQL support exists**, so class (b) is not available to them. They stay pinned. Jellyfin additionally has **no `.nfs-backup` at all** — its `/config/data/data` is a symlink to `/db-local` with no fallback beside it (§5, Catch 1). |
| `cilium-spire/spire-data` | talos03 | **Backup/restore**, low blast radius — no policy uses mutual auth (§5). |
| `monitoring/storage-mimir-{alertmanager,compactor,store-gateway}-0` | talos01 | **Accept the loss.** All three are S3-authoritative; local state is cache/scratch. |
| `forgejo/forgejo-data` | talos01 | **Hand-copy.** No automated backup exists. ~156 KB today (§5). |
| `pihole/etc-pihole-pihole-*` | all | **Accept the loss** — nebula-sync re-seeds standbys within 300s. |

#### What this means for scheduling

`talos01` needs **zero** class (b) or (c) work. `talos03` needs the \*arr → CNPG project first.

> **🔴 Do not promote talos01 and then wait a week for the talos03 prerequisite.** That parks you at
> **2 voters — quorum 2, tolerating zero failures — for the whole week**, which is strictly worse
> than the single control plane you have now. Finish the class (b) work **first**, then promote both
> nodes in one sitting.

### 1. Why this requires a full reset

Talos machine type is immutable. From Sidero: *"Changing roles involves changes to the PKI, etcd
membership, and fundamental service topology that cannot be safely done in-place,"* and *"Talos
developers don't document or test procedures that don't involve full machine reset for role
conversions."*

So the sequence per node is: drain → **reset (wipes disks)** → node returns to maintenance mode →
apply a `controlplane.yaml` → node joins etcd as a learner → auto-promotes to voter.

> **Correction to an existing doc.** `docs/05-runbooks/ha-control-plane-migration.md` (TALOS-arx)
> describes promotion as simply running `apply-config` and letting Talos "see the role change and
> reinstall". **That is not correct** and following it will not produce a control plane. This runbook
> supersedes it for the promotion mechanics. That doc's *rationale* (why 3 CPs fix the cilium-flap
> meltdown class) remains valid and worth reading.

**Ordering rule that matters:** *you must remove the node from etcd before shutting it down. If you
shut down the node first, the etcd cluster sees it as a failed member.* `talosctl reset` is graceful
by default — it cordons, drains, leaves etcd if required, then erases and powers down. A hard
power-off does **not** do this. Always use the graceful path.

**Always pass `--reboot`**, or the node powers off instead of returning to maintenance mode, and you
will be walking to it.

### 2. The local-path problem

> ### 🔴 `talosctl reset` DEFAULTS TO WIPING THE BOOT DISK — this cost us talos01
>
> `--wipe-mode` defaults to **`all`**. That erases the system disk *including the Talos
> install*, so the node does not return to maintenance mode — it comes up to a bare cursor
> with no bootable device and needs recovery media and physical access.
>
> **Confirmed 2026-08-23:** talos01 was reset with `--reboot --graceful=true`, took the
> default `--wipe-mode all`, and never came back. Recovery required writing a factory ISO to
> USB and walking to the machine.
>
> **For a role change, wipe only what you need to:**
>
> ```sh
> talosctl reset --nodes <ip> --system-labels-to-wipe EPHEMERAL,STATE --reboot
> ```
>
> `EPHEMERAL` clears the data, `STATE` clears the config so the node boots into maintenance
> mode ready for a new machine type — and the **boot partition survives**, so the node returns
> on its own. No USB, no physical access.
>
> Keep recovery media staged anyway (`.output/isos/`), but with the correct flags it should be
> insurance rather than the plan.

`talosctl reset --system-labels-to-wipe EPHEMERAL,STATE` wipes the EPHEMERAL partition. Talos mounts EPHEMERAL at `/var`.
`local-path-provisioner` provisions under `/var/lib/rancher/local-path-provisioner` (this is exactly
why `docs/05-runbooks/talos-kubelet-localpath-patch.yaml` exists). Therefore:

> **Reset destroys every local-path PV on that node, unrecoverably.**

Because the storage class is `WaitForFirstConsumer`, each PV carries a `nodeAffinity` pinning it to
its node. The PVs cannot drain, migrate, or be rescheduled. Draining the node moves the *pods*; the
*data* stays behind and is then erased.

**There is no clean candidate node.** Every worker holds some singleton state. The job is not to find
a safe node — it is to make each item on the chosen node safe, one at a time.

> **Note on sizes.** Many PVs show `1Ti`. `local-path` does not enforce quotas, so that is a nominal
> claim, not consumption. Measure real usage before planning a copy:
> `kubectl exec -n <ns> <pod> -- du -sh <mountpath>`

### 3. The Velero gotcha (read this before you trust any backup)

Velero **is** installed and healthy — but in namespace **`backup`**, not `velero`:

```bash
kubectl get schedules.velero.io -A
```

| Schedule | Namespaces | `defaultVolumesToFsBackup` |
| --- | --- | --- |
| `velero-critical-data-daily` | `authentik`, `monitoring`, `cilium-spire`, `dungeon-library` | **true** |
| `velero-daily-all` | `media`, `media-private`, `scratch`, `home-automation`, `catalyst-llm`, `registry`, `vpn-gateway` | false |
| `velero-weekly-full` | `*` except `kube-system`, `kube-public`, `kube-node-lease`, `flux-system`, `minio` | false |

Reading that table you would reasonably conclude that `cilium-spire/spire-data` and the Mimir PVCs
are backed up daily at file level. **They are not.** Velero says so itself, in its own backup log:

```text
level=warning msg="Volume spire-data in pod cilium-spire/spire-server-0 is a hostPath volume
  which is not supported for pod volume backup, skipping"
level=warning msg="Volume storage in pod monitoring/mimir-ingester-0 is a hostPath volume
  which is not supported for pod volume backup, skipping"
```

**`local-path` provisions `hostPath` PVs, and Velero's file-system backup cannot back up `hostPath`
volumes — it skips them by design.** Every local-path PV in this cluster is `hostPath`, with no
exceptions:

```bash
kubectl get pv -o json | jq -r '.items[]
  | select(.spec.storageClassName=="local-path")
  | (.spec | keys | map(select(.=="hostPath" or .=="local" or .=="csi")) | join(","))' | sort -u
# → hostPath
```

**Reproduce the skip list yourself** — this is the authoritative check, and it is re-runnable:

```bash
LATEST=$(kubectl get backups.velero.io -n backup \
  --sort-by=.metadata.creationTimestamp -o name | tail -1 | sed 's|.*/||')
kubectl exec -n backup deploy/velero -- /velero backup logs "$LATEST" \
  | grep -i "hostPath volume which is not supported"
```

**The opt-in annotation does not save you.** The log shows Velero deciding to back the volume up and
*then* skipping it:

```text
level=info    msg="Perform fs-backup action for volume spire-data of pod cilium-spire/spire-server-0
                   due to opt-in/out way"
level=warning msg="Volume spire-data ... is a hostPath volume which is not supported ... skipping"
```

Same for `media/radarr`: the pod is annotated `backup.velero.io/backup-volumes: "config,db-local"`,
and `config` (NFS, `fatboy-nfs-appdata`) **is** backed up while `db-local` (local-path) has **never**
produced a single `PodVolumeBackup`. Same pod, same annotation, same schedule — the storage class is
the only difference.

> **⚠️ A trap when you go looking for evidence.** Querying "has this volume ever produced a
> `PodVolumeBackup`" gives **false positives**. `authentik/authentik-postgres-3` has `pgdata` PVBs —
> but the newest is **2026-08-12**, and it appears in no backup since. Those are stale artifacts from
> before that volume became local-path. A historical PVB is not current coverage.
>
> **Check the PV's source type, not its backup history.** `hostPath` ⇒ not FSB-eligible, full stop.
> That is what the §4 script does.

**Consequence:** for every local-path PV, Velero preserves the Kubernetes **objects** (PVC/PV specs,
Deployments, ConfigMaps, Secrets) and **none of the data**. The workload comes back and re-provisions
an **empty** volume. That is not a restore.

### 4. Pre-flight inventory and classification (RUN THIS)

Run this against the target node on the day you do the work. It gathers facts empirically — including
real Velero coverage and real disk usage — so it does not rot the way a pasted snapshot does.

```bash
#!/usr/bin/env bash
# Usage: ./inventory-node-pvs.sh talos01
# Lists every local-path PV pinned to a node, its REAL on-disk size, whether Velero
# file-system backup can cover it, and which workload owns it.
set -euo pipefail
NODE="${1:?usage: $0 <node-name>}"

printf '%-44s %-7s %-8s %-12s %-26s %s\n' PVC CLAIM ONDISK FSB-ELIGIBLE CONSUMER-POD OWNER
printf '%.0s-' {1..118}; echo

kubectl get pv -o json | jq -r --arg n "$NODE" '
  .items[]
  | select(.spec.storageClassName=="local-path")
  | select((.spec.nodeAffinity.required.nodeSelectorTerms[]?.matchExpressions[]?.values[]? // "") == $n)
  | [ .spec.claimRef.namespace, .spec.claimRef.name, .spec.capacity.storage,
      (if .spec.hostPath then "hostPath" else "other" end) ] | @tsv' \
| while IFS=$'\t' read -r NS PVC SIZE SRC; do
    POD=$(kubectl get pods -n "$NS" -o json 2>/dev/null | jq -r --arg p "$PVC" '
      .items[] | select((.spec.volumes // [])[]?.persistentVolumeClaim.claimName == $p)
      | .metadata.name' | head -1)
    OWNER=$(kubectl get pod -n "$NS" "$POD" -o jsonpath='{.metadata.ownerReferences[0].kind}' 2>/dev/null || true)
    # Velero FSB CANNOT back up hostPath volumes — it skips them by design (see §3).
    # Check the PV source, NOT the PodVolumeBackup history (stale PVBs give false positives).
    [ "$SRC" = "hostPath" ] && FSB="** NO **" || FSB="maybe"
    # Real consumption. The claim size is meaningless — local-path enforces no quota.
    MP=$(kubectl get pod -n "$NS" "$POD" -o json 2>/dev/null | jq -r --arg p "$PVC" '
      . as $pod | ($pod.spec.volumes[] | select(.persistentVolumeClaim.claimName==$p) | .name) as $v
      | [$pod.spec.containers[].volumeMounts[]? | select(.name==$v) | .mountPath][0] // empty')
    DU="-"
    [ -n "${MP:-}" ] && DU=$(kubectl exec -n "$NS" "$POD" -- du -sh "$MP" 2>/dev/null | awk '{print $1}' || echo "?")
    printf '%-44s %-7s %-8s %-12s %-26s %s\n' "$NS/$PVC" "$SIZE" "${DU:-?}" "$FSB" "${POD:-<none>}" "${OWNER:-?}"
  done
```

Sample output for `talos01` (a `?` in ONDISK just means the container has no `du` — measure that one
by hand):

```text
PVC                                          CLAIM   ONDISK   FSB-ELIGIBLE CONSUMER-POD               OWNER
pihole/etc-pihole-pihole-1                   2Gi     30M      ** NO **     pihole-1                   StatefulSet
authentik/authentik-postgres-3               8Gi     749M     ** NO **     authentik-postgres-3       Cluster
forgejo/forgejo-data                         20Gi    156.0K   ** NO **     forgejo-7b578bdc89-f5dqv   ReplicaSet
boomtime/boomtime-postgres-1                 10Gi    1.9G     ** NO **     boomtime-postgres-1        Cluster
monitoring/storage-mimir-alertmanager-0      1Ti     ?        ** NO **     mimir-alertmanager-0       StatefulSet
monitoring/storage-mimir-compactor-0         1Ti     ?        ** NO **     mimir-compactor-0          StatefulSet
monitoring/storage-mimir-ingester-0          1Ti     ?        ** NO **     mimir-ingester-0           StatefulSet
monitoring/storage-mimir-store-gateway-0     1Ti     ?        ** NO **     mimir-store-gateway-0      StatefulSet
```

Note how far the `CLAIM` column is from reality — four "1Ti" claims, and the whole node holds a
couple of GB. **`FSB-ELIGIBLE` is `** NO **` for every local-path PV, on every node.** That column is
a constant, not a discriminator; it is there so nobody re-litigates §3 at 2am.

Then classify **every** row into exactly one of three buckets. The script gives you the facts; the
table below gives you the judgement.

#### (a) REPLICATED — safe, rebuilds itself

Data exists in ≥ 2 more places. After the reset, delete the orphaned PVC and pod; the controller
re-provisions an empty PV and refills it.

```bash
# CNPG replica — after the node is back and Ready:
kubectl delete pvc -n <ns> <cluster>-<n>          # PVC now references a destroyed PV
kubectl delete pod -n <ns> <cluster>-<n>          # CNPG re-clones from the primary via streaming
kubectl get cluster -n <ns> <cluster> -w          # wait for readyInstances back to 3
```

**Before resetting a node holding a CNPG PRIMARY, fail over first** — otherwise the drain forces an
unplanned failover under load:

```bash
kubectl cnpg promote <cluster> <a-replica-not-on-the-target-node> -n <ns>
kubectl get cluster -n <ns> <cluster> -o jsonpath='{.status.currentPrimary}{"\n"}'
```

#### (b) DISPOSABLE — recreate empty

Local state only; the authoritative copy lives elsewhere (object storage, or another replica that
re-syncs). Do nothing before, delete the orphaned PVC + pod after, note the refill time.

#### (c) SINGLETON STATE — **the dangerous class**

Authoritative, single copy, on the node you are about to erase. Must be backed up and restored, or
the workload moved off the node **before** the reset. Enumerated per item in §5.

### 5. Per-singleton migration guidance

#### talos01 — 8 PVs

| PVC | Class | Story |
| --- | --- | --- |
| `monitoring/storage-mimir-ingester-0` | **REPLICATED** | `replication_factor: 3` across exactly 3 ingesters → every series is on all three. Losing one loses nothing. Delete PVC+pod after; it rejoins the ring. |
| `monitoring/storage-mimir-compactor-0` | **DISPOSABLE** | Scratch working dir. Compactor downloads blocks from S3, compacts, uploads. |
| `monitoring/storage-mimir-store-gateway-0` | **DISPOSABLE** | `bucket_store.sync_dir` — a cache of index headers fetched from S3. Rebuilds on start (queries are slower until it warms). |
| `monitoring/storage-mimir-alertmanager-0` | **DISPOSABLE**¹ | `alertmanager_storage.backend: s3` (prefix `alertmanager`). Local `data_dir` is a working copy. |
| `authentik/authentik-postgres-3` | **REPLICATED** | CNPG, 3 instances, this is a replica (primary is `-1`). |
| `boomtime/boomtime-postgres-1` | **REPLICATED — but PRIMARY** | CNPG, 3 instances. **Switch over first** (see §5a). |
| `pihole/etc-pihole-pihole-1` | **DISPOSABLE** | `nebula-sync` restores config to idle standbys every `SYNC_INTERVAL=300`s from the active L2-lease holder. A wiped standby is re-seeded within ~5 min. |
| **`forgejo/forgejo-data`** (20Gi claim, **~156 KB actual**) | **SINGLETON — NO BACKUP EXISTS** | See below. Currently near-empty; re-measure before trusting that. |

¹ *Uncertainty:* Mimir's Alertmanager persists silences and the notification log to object storage
periodically. I did **not** verify the persist interval, so silences created in the minutes before
the reset may be lost. Low impact, but if you are mid-incident with active silences, re-create them
after. Do not treat this footnote as a guarantee.

**`forgejo/forgejo-data` — the item with no automated backup of any kind.**

Forgejo's Postgres *is* protected (CNPG → MinIO, daily base backup + continuous WAL, see
`infrastructure/base/forgejo/scheduledbackup.yaml`). But the **git repositories themselves** live on
this 20Gi local-path PV and are covered by **nothing** — `forgejo` is only in `velero-weekly-full`,
which is metadata-only, and even if it were in an fsBackup schedule the hostPath rule in §3 would
skip it. Restoring Postgres without the git data gives you a Forgejo that lists repositories which no
longer exist.

> **Good news, and check whether it still holds.** At the time of writing this volume held **~156 KB
> and zero git repositories** — `/data/git` was 4 KB and empty, with the rest being SSH host keys
> (24 KB) and Forgejo internals (128 KB). Forgejo is deployed but effectively unused. So today this
> is a trivial copy, not a crisis. **Re-measure before you rely on that** — the moment somebody
> pushes a repo, this becomes the most dangerous item in the runbook:
>
> ```bash
> kubectl exec -n forgejo deploy/forgejo -- sh -c 'du -sh /data; find /data -name "*.git" | head'
> ```

Copy it out by hand regardless — it costs seconds at this size:

```bash
# BEFORE the reset — scale down for a consistent copy, then stream the volume out
kubectl scale deploy/forgejo -n forgejo --replicas=0
kubectl wait --for=delete pod -l app=forgejo -n forgejo --timeout=5m

# run a throwaway pod that mounts the PVC and tars it to your workstation
kubectl run forgejo-rescue -n forgejo --rm -i --restart=Never \
  --image=busybox:latest \
  --overrides='{"spec":{"nodeSelector":{"kubernetes.io/hostname":"talos01"},
    "containers":[{"name":"c","image":"busybox:latest","command":["tar","cf","-","-C","/data","."],
    "stdin":true,"volumeMounts":[{"name":"d","mountPath":"/data"}]}],
    "volumes":[{"name":"d","persistentVolumeClaim":{"claimName":"forgejo-data"}}]}}' \
  > ~/forgejo-data-$(date +%F).tar

# VERIFY THE TARBALL BEFORE YOU RESET ANYTHING
tar tf ~/forgejo-data-$(date +%F).tar | head
ls -lh ~/forgejo-data-$(date +%F).tar
```

Restore is the mirror image after the node is back: scale to 0, `tar xf` into a fresh pod mounting
the newly-provisioned PVC, then scale to 1.

> **Recommendation:** file a beads issue to move `forgejo-data` onto NFS or add a real backup, then
> stop depending on this manual dance. The gap exists today whether or not you promote anything.

#### talos03 — 16 PVs

| PVC | Class | Story |
| --- | --- | --- |
| `cilium-spire/spire-data-spire-server-0` | **SINGLETON — low blast radius** | See below. |
| `media/radarr-db-local`, `media/sonarr-db-local` | **SINGLETON — recoverable with prep** | See below. |
| 13 × `media-experimental/*-config` (5Gi each) | **REBUILDABLE BY RESCAN** | See below. |
| `pihole/etc-pihole-pihole-4` | **DISPOSABLE** | Same `nebula-sync` story as `pihole-1`. |

**`cilium-spire/spire-data` — smaller problem than it looks.** It holds
`/run/spire/data/datastore.sqlite3` (registration entries) plus `keys.json` (the **CA signing keys**
— `ca_key_type = rsa-4096`, trust domain `spiffe.cilium`). Losing it means a new CA and full
re-attestation of every agent.

The reason this is survivable here: **zero CiliumNetworkPolicies currently use mutual
authentication.**

```bash
# verify this is still true on the day — if it returns non-zero, re-assess the risk
kubectl get cnp,ccnp -A -o json | jq '[.items[] | select((.spec // {} | tostring) | test("authentication"))] | length'
```

SPIRE is deployed and running, but nothing is enforcing identity-based policy, so a fresh CA costs
you re-attestation churn rather than a connectivity outage. Snapshot it anyway — it is cheap:

```bash
kubectl exec -n cilium-spire spire-server-0 -c spire-server -- \
  tar cf - -C /run/spire/data . > ~/spire-data-$(date +%F).tar
```

*Uncertainty:* I did not test the restore path, and SPIRE may reject a datastore restored under a
node with a different identity. Treat the tarball as a fallback, not a plan. Expect to
`kubectl delete pod -n kube-system -l k8s-app=cilium` and restart `cilium-operator` afterwards to
force clean re-attestation.

**`media/radarr-db-local` + `media/sonarr-db-local` — two catches.**

*Catch 1 — the data, and what the init container actually does.* These hold the authoritative SQLite
databases (`radarr.db` 267 MB, `sonarr.db` 548 MB) — library, history, quality profiles, indexers.
The `config` PVC is separate and on NFS.

`applications/arr-stack/base/shared/db-migration-configmap.yaml` (`migrate-arr.sh`) runs as an init
container and performs a **one-way** migration: on first run it copies the SQLite DB from NFS to the
local PV, renames the NFS original to `<app>.db.nfs-backup`, and replaces `/config/<app>.db` with a
**symlink** into `/db-local`.

> **⚠️ It does NOT re-migrate after the local PV is destroyed, and the app does NOT roll back to its
> first-migration state.** This is worth being precise about, because the difference is the whole
> library.
>
> The script's first check is `symlink_ok "$DB_FILE" "$DB_LOCAL_PATH/$APP_NAME.db"`, implemented as
> `[ -L "$1" ] && [ "$(readlink "$1")" = "$2" ]`. **`readlink` reports the target string whether or
> not the target exists.** The symlink lives on the surviving NFS `config` volume, so after a reset
> it is still there and still points at `/db-local/<app>.db`. The check passes, the script prints
> "Symlinks already configured correctly, nothing to do" and **exits 0** — the `.nfs-backup` is never
> consulted. The app then opens a dangling symlink and **SQLite creates a brand-new empty database.**
>
> Net effect: **the app comes back as a fresh install with an empty library**, not as a stale one.
> The `.nfs-backup` file survives on NFS and is recoverable *by hand*, but nothing automatic uses it.
>
> Verified live — note how stale those fallbacks are:
>
> | App | `.nfs-backup` (Dec 20 2025) | live `/db-local` (today) |
> | --- | --- | --- |
> | radarr | 671 KB | 267 MB |
> | sonarr | 475 MB | 548 MB |
> | prowlarr | 176 KB | 8.1 MB |
>
> Radarr's and Prowlarr's fallbacks are effectively empty databases. Sonarr's is substantial but
> eight months stale. **Do not treat `.nfs-backup` as a backup.**
>
> The same reasoning applies to the Plex/Jellyfin variant (`migrate.sh`): `$DB_SOURCE_PATH` is itself
> a symlink after first run, so `[ -d ]` follows it and `[ ! -L ]` is false — it takes the "app will
> create fresh ones" branch and never restores.

The actual recovery path is different and better: Radarr and Sonarr write their own weekly backup
zips into the **NFS** config volume, which *is* Velero-covered:

```bash
kubectl exec -n media deploy/radarr -c radarr -- ls -la /config/Backups/scheduled
kubectl exec -n media deploy/sonarr -c sonarr -- ls -la /config/Backups/scheduled
```

At time of writing the newest was 7 days old. **Trigger a fresh backup immediately before the reset**
(Radarr/Sonarr UI → System → Backup → Backup Now), or you silently lose up to a week of library
changes. Then restore via System → Restore after the node returns.

*Catch 2 — the pinning.* Both deployments carry a hard
`requiredDuringSchedulingIgnoredDuringExecution` nodeAffinity onto `talos03`:

```yaml
# applications/arr-stack/base/radarr/deployment.yaml
- key: kubernetes.io/hostname
  operator: In
  values: [talos03]
```

If `talos03` comes back as a **tainted** control plane, radarr and sonarr become permanently
unschedulable — required affinity says "only talos03", the taint says "nothing here". They will sit
Pending and you will chase it for an hour at 2am. Either untaint (see §7) or update the affinity in
git first. This is the single most likely way this runbook bites you.

**The 13 `media-experimental/*-config` volumes.** The *content* (books, comics, audiobooks,
downloads) is on `synology-nfs` and is untouched by any of this. Only each app's config/library
database is on local-path. Losing them means re-scanning libraries from the NFS content — you get
the library back, but you lose **read progress, user accounts, and manual metadata matches**.

Judgement call, and it is the operator's to make: these are *experimental* services (audiobookshelf,
kavita, komga, libation, mylar3, storyteller, bindery, booksonic, chaptarr, librarr, livrarr). If you
care about read progress, tar each one out using the same throwaway-pod pattern as `forgejo-data`. If
you do not, let them rebuild and save yourself two hours.

### 6. Node ordering, argued from the inventory

**Recommendation: `talos01` first, then `talos03`.**

**Rank by un-binding effort, not by PV count.** A node with 16 volumes that are all class (a)/(c) is
cheaper than one with 8 that are all class (d). Scoring the two candidates by §0 class:

| Node | (a) replicated | (b) needs un-binding project | (c) NFS-movable | (d) stuck | Prerequisite work |
| --- | --- | --- | --- | --- | --- |
| **talos01** | 3 | **0** | 0 | 5 (4 accept-loss + 1 hand-copy ~156 KB) | **none** |
| **talos03** | 0 | **2** (radarr, sonarr → CNPG) | 0 confirmed — 3 of 13 proven SQLite, 10 unaudited | 1 spire + 1 pihole + up to 13 media-experimental | **~1 week** |

**Why `talos01` first** — it needs **zero** class (b) or (c) work. Four of its eight PVs are Mimir
components whose authoritative data is in S3/MinIO (`blocks_storage`, `alertmanager_storage`,
`ruler_storage` all `backend: s3`), two are CNPG members of 3-instance clusters that rebuild by
streaming, one is a pihole standby that `nebula-sync` re-seeds in five minutes. That leaves exactly
one item needing manual work, and it is currently ~156 KB.

It also has the fewest relocatable pods (27), making the drain cheapest, and at 22Gi allocatable it
has real headroom for etcd + apiserver + controller-manager + scheduler. Doing the low-risk node
first also means you validate the whole procedure — config generation, reset, learner promotion,
patch re-application — *before* you enter the fragile 2-voter window.

**Why `talos03` second — and why it is gated.** Its two \*arr SQLite databases are class (b): they
*can* stop being node-bound, but only via the CNPG project in §0, which is a week of elapsed work.
Its 13 media-experimental configs are **not** the easy NFS wins they appear to be — at least three
are SQLite-backed and the rest are unaudited. Until that audit is done, treat them as class (d).

**Why `talos03` second, and why not the alternatives:**

- **`talos02-gpu` — excluded.** It is the **only GPU node** (Intel Arc). Promoting it means
  re-establishing the GPU device plugin and extensions on a control plane, and it carries the
  heaviest pod load (107). Wrong on hardware-exclusivity grounds alone, before storage enters it.
- **`talos06` — excluded, and this is the important comparison.** It has 33 PVs, but count is not the
  argument; *content* is. It holds `catalyst-data/neo4j-data`, `catalyst-data/postgres-knowledge`,
  `catalyst-data/dagster-postgres`, `dungeon-library/postgres-storage-postgres-0`,
  `registry/zot-data`, `monitoring/storage-loki-0`, the ClickStack MongoDB and HyperDX ClickHouse
  volumes, and the gaming disks. That is a far deeper pool of genuinely irreplaceable singleton state
  than talos03's, and much of it has no NFS fallback and no rescan path. It is also one of only two
  61Gi nodes, so it needs to stay available to absorb workload during the migration.
- **`talos03` — chosen by elimination, and it is the only candidate whose blockers are *fixable*.**
  Its two \*arr databases are the one class (b) case in the cluster: they can be un-bound outright.
  talos06's neo4j / knowledge-graph / registry / Loki state has no comparable drop-in path.

**Two caveats to weigh before accepting talos03:**

1. **Memory.** At **14Gi allocatable it is the smallest-memory node**, and
   `docs/05-runbooks/talos-kubelet-maxpods-patch.yaml` records it as already memory-bound at ~74%.
   Adding a control plane to the most memory-constrained node is the weakest part of this
   recommendation. Two things make it tolerable: control-plane components are a few Gi, and moving
   radarr/sonarr to CNPG (§0b) plus relocating the media-experimental pods *reduces* talos03's
   post-promotion load rather than adding to it.
2. **It is gated.** Do not start talos03 until the §0 class (b) work is done and soaked.

**Sequencing, which matters more than the ordering itself:**

> **🔴 Complete the §0 class (b) work BEFORE the maintenance window, then promote both nodes in one
> sitting.** The tempting shortcut — promote talos01 now, do the \*arr → CNPG project over the
> following week, then promote talos03 — **parks the cluster at 2 voters for that entire week**.
> Quorum 2 of 2 tolerates zero failures, which is strictly *worse* than the single control plane you
> have today. A week of that is a much larger risk than the promotion itself.

If the \*arr → CNPG project is not something you want to take on right now, the honest alternative is
to **defer the whole promotion** — stay at 1 CP until the prerequisite is done. Staying at one is
safer than stopping at two. Do not drift into a 2-voter state by accident.

### 7. Taints and pod capacity — decide this before you start

`talos00` is **tainted today** (`node-role.kubernetes.io/control-plane:NoSchedule`), holding only 17
pods. Naively repeating that on two more nodes is not viable:

If all three control planes end up tainted, the 76 relocatable pods currently on talos00/01/03 must
fit onto talos02-gpu and talos06, joining the 171 already there — ~137 pods per node. That clears
`maxPods: 200`, but **removes 60Gi of the cluster's ~182Gi allocatable memory from the schedulable
pool (a ~33% cut)** while the workload stays constant. Memory, not pod count, is the binding
constraint. It will not fit.

**Therefore: the promoted nodes must accept workloads.** `cluster.allowSchedulingOnControlPlanes:
true` is already set in `configs/nodes/controlplane.yaml` (line 596), so the generated configs will
carry it.

> **⚠️ Flagging a real anomaly rather than guessing.** `talos00`'s **live** machine config also has
> `allowSchedulingOnControlPlanes: true` — I verified this with
> `talosctl -n 192.168.1.54 get mc v1alpha1 -o yaml` — and yet the node **is** tainted. I could not
> determine why from the cluster state. The likely explanation is that Talos applies this at
> bootstrap/registration time and does not continuously reconcile the taint, so a taint re-added
> later persists. **I did not confirm that.**
>
> Practical consequence: **do not assume the promoted nodes come back untainted.** Check explicitly,
> and untaint if needed:
>
> ```bash
> kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
> # if the promoted node is tainted and you want it schedulable:
> kubectl taint node <node> node-role.kubernetes.io/control-plane:NoSchedule-
> ```
>
> Remember §5's trap: radarr and sonarr are hard-pinned to `talos03` and will be **stuck Pending**
> until this is resolved.

Expected steady state with all 5 nodes schedulable: roughly today's distribution, minus whatever the
descheduler rebalances. Watch for pods that were on the reset node and cannot come back because their
PV is gone — those need the PVC deleted (§4a) before they will schedule.

### 8. The procedure (repeat per node)

Substitute `<NODE>` / `<IP>`: `talos01` / `192.168.1.177`, then `talos03` / `192.168.1.30`.

#### Step 0 — one-time: create the secrets bundle

The generated control-plane config **must** come from the same PKI as the running cluster, or etcd
will reject the join with a cluster-ID mismatch. There is **no `configs/secrets.yaml` in this repo**
today, but it can be derived from the existing control-plane config, which carries the full PKI
(cluster CA, etcd CA, service-account key, `secretboxEncryptionSecret`, bootstrap token):

```bash
talosctl gen secrets \
  --from-controlplane-config configs/nodes/controlplane.yaml \
  --output-file configs/secrets.yaml
```

**`configs/` is gitignored — keep it that way.** This file is cluster-root-equivalent material.

#### Step 1 — snapshot etcd

```bash
kubectl create job -n backup --from=cronjob/etcd-backup pre-promote-$(date +%s)
kubectl get jobs -n backup -w    # ctrl-C at COMPLETIONS 1/1
```

#### Step 2 — migrate the singletons (§5)

Do every SINGLETON item for this node now. **Verify each artifact is readable before continuing.** An
unverified tarball is not a backup.

#### Step 3 — CNPG switchover, if this node holds a primary

```bash
kubectl get clusters.postgresql.cnpg.io -A \
  -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,PRIMARY:.status.currentPrimary
# talos01 holds boomtime-postgres-1, the PRIMARY of a 3-instance cluster:
kubectl cnpg promote boomtime-postgres boomtime-postgres-2 -n boomtime
kubectl get cluster -n boomtime boomtime-postgres -o jsonpath='{.status.currentPrimary}{"\n"}'
```

#### Step 4 — generate the control-plane config

```bash
talosctl gen config \
  --with-secrets configs/secrets.yaml \
  catalyst-cluster https://192.168.1.54:6443 \
  --output-types controlplane \
  --output configs/nodes/<NODE>/controlplane.yaml
```

Then **diff it against the working control plane** and reconcile the differences by hand — hostname,
install disk, any node-specific extensions:

```bash
diff <(grep -vE '^\s*#' configs/nodes/controlplane.yaml) \
     <(grep -vE '^\s*#' configs/nodes/<NODE>/controlplane.yaml) | less
```

Confirm before proceeding:

- `machine.type: controlplane`
- `machine.network.hostname: <NODE>`
- `machine.install.disk` matches the node's actual disk
- `cluster.allowSchedulingOnControlPlanes: true`
- **Node-specific extensions carried over.** Check `configs/nodes/<NODE>/` — `talos03` has
  `talos03-schematic.yaml` (AMD/Intel firmware extensions) and `talos03-hardware.md`. A schematic
  change means an `--image` factory URL on install; losing it means losing the extensions.

#### Step 5 — drain

```bash
kubectl cordon <NODE>
kubectl drain <NODE> --ignore-daemonsets --delete-emptydir-data --grace-period=120 --timeout=15m
kubectl get pods -A -o wide --field-selector spec.nodeName=<NODE>   # only DaemonSets should remain
```

#### Step 6 — **DESTRUCTIVE** — reset

> **🔴 THIS ERASES THE NODE'S DISKS.** Everything in §5 must be done and verified. There is no undo.

```bash
talosctl -n <IP> reset --graceful --reboot
```

`--graceful` (the default) cordons, drains, and **leaves etcd cleanly** — this is what keeps the
cluster from seeing a failed member. `--reboot` returns the node to maintenance mode instead of
powering it off.

Watch it drop out and come back:

```bash
talosctl -n 192.168.1.54 etcd members    # target node should be gone (it was never a member yet)
kubectl get nodes -w
```

#### Step 7 — apply the control-plane config

In maintenance mode the node has no certificates, so `--insecure` is required here (and only here):

```bash
talosctl -n <IP> apply-config --insecure --file configs/nodes/<NODE>/controlplane.yaml
```

#### Step 8 — watch the etcd learner promotion

This is the step that makes the join safe. All new control-plane nodes join etcd as **non-voting
learners** until they have caught up with all transactions. A learner **does not increase quorum**.
Once it is a reliable member it is **automatically promoted** to a voting member — you do not promote
it by hand.

```bash
watch -n 5 'talosctl -n 192.168.1.54 etcd members'
```

Read the **`LEARNER`** column:

```
NODE           ID                 HOSTNAME   PEER URLS                    CLIENT URLS                  LEARNER
192.168.1.54   fba9d7bc26d1ea21   talos00    https://192.168.1.54:2380    https://192.168.1.54:2379    false
192.168.1.177  a1b2c3d4e5f60718   talos01    https://192.168.1.177:2380   https://192.168.1.177:2379   true   ← learner, quorum still 1
```

Wait for `LEARNER` to flip `true` → `false`. Typically a few minutes. Until it flips, quorum is
unchanged and **you can still abort safely** (§9).

```bash
talosctl -n 192.168.1.54 etcd status
kubectl get nodes -o wide          # <NODE> should now show control-plane in ROLES
```

#### Step 9 — 🔴 RE-APPLY THE KUBELET PATCHES 🔴

**A reset node loses all machine-config patches.** Without this it returns with `maxPods: 110` and
**local-path broken** — kubelet's mount namespace will not include `/var/lib/rancher`, so every
local-path volume fails to mount with a confusing "is not a directory" error.

```bash
./scripts/bootstrap-talos-patches.sh --check     # dry run first
./scripts/bootstrap-talos-patches.sh             # idempotent; patch mc merges
```

This applies all three: iSCSI extraMounts (`/etc/iscsi`, `/var/lib/iscsi`), local-path extraMount
(`/var/lib/rancher`), and `maxPods: 110 → 200` (TALOS-d5b5). Verify:

```bash
kubectl get nodes -o custom-columns=NAME:.metadata.name,MAXPODS:.status.capacity.pods
# ALL nodes must read 200. If the promoted node reads 110, the patch did not land — stop and fix.
```

Also consider `docs/05-runbooks/talos-controlplane-metrics-patch.yaml` — the node is a control plane
now, so controller-manager/scheduler metrics binding applies to it where it did not before.

#### Step 10 — restore data, clean up orphans, uncordon

```bash
# orphaned PVCs (their PV was destroyed with the node) — delete so they re-provision empty
kubectl get pvc -A | grep -i pending
kubectl delete pvc -n <ns> <pvc>   # then delete the pod so it re-creates

kubectl uncordon <NODE>
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints   # see §7
```

Restore the §5 singletons. Then let it settle and observe for 15 minutes:

```bash
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded
kubectl get pods -n kube-system -l k8s-app=cilium -o wide
kubectl get cluster -A     # CNPG clusters back to full readyInstances
```

#### Step 11 — update endpoints, then go/no-go for the next node

```bash
talosctl config endpoint 192.168.1.54 192.168.1.177 192.168.1.30
talosctl config info
```

> **🔴 DO NOT STOP HERE.** After the first promotion you have **2 voters, quorum 2, tolerating ZERO
> failures** — strictly more fragile than the single control plane you started with. Any one node
> rebooting now takes the cluster's API down. Re-run the go/no-go gate and proceed to the second node
> **in the same sitting.**

Only after the third member's `LEARNER` flips to `false` do you have 3 voters, quorum 2, tolerating
one failure — the actual goal.

### 9. Rollback points

| Point | Can you abort? | How |
| --- | --- | --- |
| Before Step 6 (reset) | **Yes, fully.** Nothing destructive has happened. | `kubectl uncordon <NODE>`, restore the CNPG primary if you switched it. |
| After reset, before Step 7 | **Yes — but the node's data is already gone.** | Apply the *worker* config instead (`configs/nodes/<NODE>/worker-*.yaml`), re-run the patches, restore data. Cluster returns to 1 CP. |
| Learner joined, `LEARNER true` | **Yes.** A learner does not affect quorum. | `talosctl -n <IP> reset --graceful --reboot`, then re-apply the worker config. |
| **`LEARNER` flipped to `false` (2 voters)** | **Risky.** You are at quorum 2 of 2. | Preferred: **go forward** and promote the third node. To go back, `reset --graceful` so the node leaves etcd cleanly — a hard power-off here loses quorum and the API with it. |
| 3 voters, all healthy | **N/A — done.** | To reduce back to 1 CP, reset one node at a time, letting etcd settle between each. |

**If quorum is lost entirely:** stop improvising and use
`docs/03-operations/etcd-backup-restore.md` with the snapshot from Step 1.

### 10. Final validation

- [ ] `talosctl -n 192.168.1.54 etcd members` → **3 members, all `LEARNER false`**
- [ ] `kubectl get nodes` → 3 control-plane + 2 worker, all `Ready`
- [ ] `kubectl get nodes -o custom-columns=NAME:.metadata.name,MAXPODS:.status.capacity.pods` → all **200**
- [ ] Taints are what you decided in §7 — and **radarr/sonarr are Running, not Pending**
- [ ] All CNPG clusters back to full `readyInstances`
- [ ] Mimir ingesters 3/3, ring healthy; Grafana still renders dashboards
- [ ] `forgejo` serves repositories (git clone something — do not trust the UI listing alone)
- [ ] pihole standbys re-seeded (`nebula_sync_last_success_timestamp_seconds` is recent)
- [ ] No pods Pending on a destroyed PV
- [ ] HA actually works: stop `kube-apiserver` on talos00 and confirm `kubectl` still responds
- [ ] `CLAUDE.md`, `configs/README.md` node inventories updated to reflect 3 CPs

---

## Related Issues

<!-- Beads tracking for this doc -->

- **TALOS-arx** — HA control plane epic. See `ha-control-plane-migration.md`; its promotion mechanics
  are superseded by this document (§1).
- **TALOS-d5b5** — `maxPods` 110 → 200. Re-applied by Step 9 after every reset.
- **Follow-up worth filing:** `forgejo/forgejo-data` has no backup coverage of any kind (§5). This is
  a standing gap independent of this runbook.
- **Follow-up worth filing — the prerequisite project:** migrate `radarr`, `sonarr` and `prowlarr`
  from local-path SQLite to a CNPG PostgreSQL cluster (§0b). Removes their node-binding, drops the
  `nodeAffinity` pins, and gives them real backup coverage. **Blocks the talos03 promotion.**
- **Follow-up worth filing:** audit the remaining 10 `media-experimental/*-config` volumes for SQLite
  (§0c). Three are confirmed SQLite-backed and therefore not NFS-safe; the rest are unknown.
- **Follow-up worth filing:** `migrate-arr.sh` / `migrate.sh` do not detect a destroyed local PV —
  the surviving symlink on NFS makes the idempotency check pass, so the app silently starts on an
  empty database instead of restoring from `.nfs-backup` (§5). A liveness check comparing symlink
  target existence would turn a silent data loss into a loud failure.
- **Follow-up worth filing:** Velero file-system backup skips all `local-path` (hostPath) PVs,
  including volumes explicitly named in `backup.velero.io/backup-volumes` (§3). It logs a warning per
  volume, but the backup still reports `Completed`, so the gap is invisible unless someone reads the
  backup log. Several workloads are annotated as though protected and are not. Worth either an alert
  on that warning, or moving the affected volumes off `local-path`.

## References

- [Talos — control plane](https://www.talos.dev/v1.13/talos-guides/configuration/control-plane/)
- [Talos — etcd maintenance](https://www.talos.dev/v1.13/talos-guides/configuration/etcd-maintenance/)
- [Talos — resetting a machine](https://www.talos.dev/v1.13/talos-guides/resetting-a-machine/)
- [Sonarr — PostgreSQL setup](https://wiki.servarr.com/sonarr/postgres-setup) — env-var config, main + logs DB, pgloader migration
- [Radarr — PostgreSQL setup](https://wiki.servarr.com/radarr/postgres-setup) — requires ≥ v4.1.0.6133
- `applications/arr-stack/base/shared/db-migration-configmap.yaml` — the one-way SQLite→local migration analysed in §5
- `docs/03-operations/etcd-backup-restore.md` — snapshot/restore procedure
- `docs/05-runbooks/velero-restore.md` — Velero restore mechanics
- `scripts/bootstrap-talos-patches.sh` — the three kubelet patches
