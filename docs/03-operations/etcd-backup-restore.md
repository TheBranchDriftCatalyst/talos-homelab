---
type: runbook
status: current
covers:
  - backup
  - path:configs/talconfig.yaml
freshness: tracks-code
tickets:
  - TALOS-a8g
  - TALOS-asv
bluf: etcd snapshots land in MinIO on a schedule; recovering a dead control plane means reset the node, re-apply its generated machine config, then bootstrap with `--recover-from`.
---

# etcd Backup & Restore

How automated etcd snapshots work in this cluster, and how to recover the control plane from one when the etcd state is gone (e.g. the 2026-05-09 UPS-fault scenario).

## TL;DR

1. Confirm etcd is actually gone — a single lagging member in a multi-member cluster is repairable without a restore.
2. Pull the newest snapshot from before the corruption out of MinIO.
3. `talosctl reset` the control-plane node, wiping `EPHEMERAL` and `STATE`.
4. Regenerate configs and re-apply **that node's** machine config.
5. `talosctl bootstrap --recover-from=<snapshot>`.
6. Let Flux and ArgoCD reconcile the drift between snapshot time and now.

Budget roughly ten minutes from `bootstrap` to a healthy API server.

## Why this exists

etcd holds all Kubernetes API state — every object, secret, ConfigMap, RBAC binding, scheduling history. On Talos, etcd lives on the EPHEMERAL XFS partition. If that partition corrupts (UPS fault, disk failure, kernel panic mid-write), the control plane is unrecoverable without a snapshot. Velero does NOT cover this — Velero needs a working API server to restore.

The snapshot target is MinIO rather than a node-local path for exactly this reason: the failure being insured against destroys EPHEMERAL, so a copy sitting on EPHEMERAL insures nothing. MinIO's own storage is NFS-backed, i.e. off-node.

## How it works

| Object                                         | What it is for                                                                                                         |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| CronJob `backup/etcd-backup`                   | Takes the snapshot and uploads it                                                                                      |
| ConfigMap `backup/etcd-backup-config`          | Tunables: target node, retention count, S3 target                                                                      |
| Secret `backup/talosconfig`                    | Restricted talosconfig — `os:etcd:backup` role only, so a leak cannot run arbitrary Talos API calls                    |
| Secret `backup/minio-root-credentials`         | Reflected from ns `minio` by emberstack/reflector; source ExternalSecret is in `infrastructure/base/minio/tenant.yaml` |
| PrometheusRule `monitoring/etcd-backup-alerts` | Alerts on job failure, job not running, and CronJob missing entirely                                                   |

Each run:

1. An initContainer running `talosctl` calls `talosctl etcd snapshot` against the control-plane node and writes to a shared `emptyDir`.
2. The main container (`mc`) uploads it to MinIO with a timestamp suffix.
3. The same container prunes the oldest snapshots beyond the retention count.

Source of truth for schedule, retention and S3 target: `infrastructure/base/backup/etcd-backup.yaml`. They are deliberately not repeated here — the retention window only has to outlive the time it takes a human to _notice_ corruption, and that judgement belongs next to the value.

## Tuning

Both knobs live in the manifest and should be changed there, not live — Flux reverts a `kubectl edit`. To see what is currently in force:

```bash
kubectl get configmap -n backup etcd-backup-config -o yaml   # retention, target node, S3 target
kubectl get cronjob -n backup etcd-backup -o jsonpath='{.spec.schedule}{"\n"}'
```

## Verify it's working

```bash
# Most recent runs
kubectl get jobs -n backup -l app.kubernetes.io/name=etcd-backup

# Last successful schedule time
kubectl get cronjob -n backup etcd-backup \
  -o jsonpath='{.status.lastSuccessfulTime}{"\n"}'

# Snapshot list
kubectl run mc-check --rm -it --restart=Never \
  --image=minio/mc:latest --namespace=backup \
  --command -- /bin/sh -c '
    # Root creds live in 1Password (item "minio": root-user / root-password);
    # export them first, e.g. from the minio-root-credentials Secret:
    #   AWS_ACCESS_KEY_ID=$(kubectl get secret -n backup minio-root-credentials -o jsonpath="{.data.AWS_ACCESS_KEY_ID}" | base64 -d)
    #   AWS_SECRET_ACCESS_KEY=$(kubectl get secret -n backup minio-root-credentials -o jsonpath="{.data.AWS_SECRET_ACCESS_KEY}" | base64 -d)
    mc alias set m http://minio.minio.svc.cluster.local "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY" >/dev/null
    mc ls m/backups/etcd/ | tail -20
  '
```

Expect one snapshot per scheduled interval, with sizes climbing slowly — etcd state grows with cluster activity, so a snapshot that suddenly shrinks is a signal, not a saving.

The `etcd-dr` suite (`tests/etcd-dr/test_etcd_dr.py`) asserts the same things automatically: the machinery exists, the CronJob is healthy, the newest snapshot is fresh, and a freshly taken snapshot loads and hashes cleanly. Run it with `task test:dr`.

## Restore procedure

> **You only need this if etcd is gone or corrupt.** For "I deleted a namespace", use Velero. For "I want to roll back a misapply", just re-apply manifests via Flux/ArgoCD.

### Step 1: confirm you actually need to restore

```bash
# Talos says etcd is unhealthy?
talosctl -n $TALOS_NODE service etcd status
talosctl -n $TALOS_NODE etcd status

# kubelet can't reach API server?
talosctl -n $TALOS_NODE service kubelet logs | tail
```

If etcd is just slow or one member is behind, see [Talos etcd recovery docs](https://www.talos.dev/v1.11/advanced/etcd-maintenance/) — single-member loss in a multi-member cluster is repairable without a snapshot restore. This cluster declares three control planes in `configs/talconfig.yaml`, so that is the likely case, not the total loss this procedure addresses.

### Step 2: pick the snapshot

You want the latest snapshot from BEFORE the corruption. If the corruption was sudden (power loss), the most recent snapshot is fine. If it was gradual (slow disk, runaway controller), pick a snapshot from before the symptoms started.

```bash
# Download via mc port-forward, or directly from the MinIO web UI
kubectl port-forward -n minio svc/minio 9000:9000 &
# MinIO root creds are in 1Password (item "minio"); pull them from the Secret:
AWS_ACCESS_KEY_ID=$(kubectl get secret -n backup minio-root-credentials -o jsonpath='{.data.AWS_ACCESS_KEY_ID}' | base64 -d)
AWS_SECRET_ACCESS_KEY=$(kubectl get secret -n backup minio-root-credentials -o jsonpath='{.data.AWS_SECRET_ACCESS_KEY}' | base64 -d)
mc alias set local http://localhost:9000 "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY"
mc ls local/backups/etcd/
mc cp local/backups/etcd/etcd-20260509-230000.snapshot ./db.snapshot
```

### Step 3: reset the control plane node

⚠️ **DESTRUCTIVE** — wipes EPHEMERAL state on the CP node. Worker nodes are untouched.

```bash
export TALOS_NODE=192.168.1.54
talosctl reset --graceful=false --reboot \
  --system-labels-to-wipe=EPHEMERAL \
  --system-labels-to-wipe=STATE \
  -n $TALOS_NODE
```

Wait for the node to reboot in maintenance mode (no API, no etcd, just `talosctl` over the insecure port).

### Step 4: bootstrap from the snapshot

```bash
# Re-apply the machine config (re-creates STATE).
# Machine configs are GENERATED — regenerate first so you re-apply what the repo
# currently declares, and use the file for THIS node. They are not interchangeable:
# each node has its own install disk, schematic and patches.
task talos:gen-config
talosctl apply-config --insecure -n $TALOS_NODE \
  --file configs/clusterconfig/catalyst-cluster-<node>.yaml

# Bootstrap etcd FROM THE SNAPSHOT (this is the magic flag)
talosctl bootstrap -n $TALOS_NODE --recover-from=./db.snapshot
```

`configs/talsecret.yaml` must be present before `gen-config` — it holds the cluster CA and is gitignored, so a fresh clone will not have it. See [talsecret-1password-backup.md](../05-runbooks/talsecret-1password-backup.md).

Talos will start etcd from the snapshot data instead of an empty DB. All API objects, secrets, ConfigMaps, RBAC, etc. from the snapshot moment are restored.

### Step 5: wait + verify

```bash
# kubeconfig may need re-fetching if certs rotated
talosctl kubeconfig -n $TALOS_NODE -f

# Should show all nodes Ready within ~5 min
kubectl get nodes

# etcd should report healthy with revision matching/exceeding the snapshot
talosctl -n $TALOS_NODE etcd status
```

### Step 6: reconcile drift

State that changed between snapshot time and disaster will need reconciling:

- **Flux Kustomizations** auto-reconcile from git on their interval
- **ArgoCD Applications** auto-sync from git
- **PVCs** are unaffected (data is on the PV, not in etcd) — pods will mount existing data
- **Pods scheduled after the snapshot** will be re-scheduled by their controllers
- **Manual `kubectl apply` work that wasn't committed** is lost — recover from your shell history if needed

## Caveats

- **Multi-CP cluster**: do not restore from a snapshot while the _cluster_ is healthy — it creates split-brain. Use Talos's etcd member replacement procedure instead. With three control planes declared, member replacement is the normal repair and this runbook is the exception.
- **Dead hardware, not dead data**: if the control-plane hardware itself is gone you need replacement hardware before this procedure helps. Work from a spare node with the same machine config.
- **Snapshot age vs. PVC drift**: if the snapshot is days old, controllers will re-create things. If apps stored runtime state in a PVC AND in etcd (e.g., some operators), you may get inconsistency. The snapshot wins; the PVC may need reconciliation.
- **Secrets**: any secret created/rotated after the snapshot is gone. ESO will re-pull from upstream sources on reconcile, but bootstrap-time secrets need to exist before ESO can run.

## Why the restore path is not tested end-to-end

The `etcd-dr` suite proves the snapshot half: a freshly taken snapshot loads and passes its hash check, and the newest stored snapshot is fresh. It deliberately stops there — `test_restore_into_canary_documented_noop` is an explicit no-op, because a real `talosctl bootstrap --recover-from=` REPLACES live etcd and there is no spare Talos node to aim it at.

So the restore steps above are correct per Talos documentation and have never been executed against this cluster. Treat them accordingly: read them before you need them, not during.

---

## Related Issues

<!-- Beads tracking for this doc -->

- TALOS-a8g — etcd snapshot CronJob (closed, this is the implementation)
- TALOS-asv — UPS fault retro (the incident this addresses)
