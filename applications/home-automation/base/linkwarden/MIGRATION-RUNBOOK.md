# Linkwarden co-pod Postgres → CloudNativePG migration (TALOS-3eui)

**DATA IS NOT DISPOSABLE.** The source DB holds the user's bookmarks / collections /
tags. This is a `pg_dump` (custom format) → `pg_restore` logical migration across a
major version (**source PG 16.11 → target PG 17.0**). Custom-format dumps restore
forward across majors cleanly. **The old PVC is not deleted until bookmarks are
verified in the UI.**

## Facts verified live (2026-08-09)

| Thing | Value |
|---|---|
| Source pod | `linkwarden-<rs>` in ns `home-automation`, container `postgres` |
| Source engine | `postgres:16-alpine`, server_version **16.11** |
| Source DB / owner | db `linkwarden`, owned by role **`postgres`** (no `linkwarden` role exists) |
| Source app user | connects as `postgres` (old DATABASE_URL) |
| Source DB size | ~9.4 MB logical / ~64 MB on-disk PGDATA |
| Old DB PVC | `linkwarden-postgres` (5Gi, NFS) — RETIRE after verify |
| Keep PVCs | `linkwarden-data` (app files), `linkwarden-meili` (search index) |
| Target cluster | CNPG `linkwarden-postgres`, 1 instance, PG 17.0, db+owner `linkwarden` |
| Target secret | `linkwarden-postgres-app` (CNPG-generated: user/pass/host/port/dbname/uri) |
| Target rw svc | `linkwarden-postgres-rw:5432` |

> Because the source objects are owned by `postgres` and the target role is
> `linkwarden`, the dump uses `--no-owner --no-acl` and the restore uses
> `--no-owner --role=linkwarden`, so every object lands owned by `linkwarden`.

Set once:

```bash
export NS=home-automation
export SRCPOD=$(kubectl get pod -n $NS -l app=linkwarden -o jsonpath='{.items[0].metadata.name}')
echo "source pod: $SRCPOD"
```

---

## Step A — Dump the source DB (co-pod STILL running, BEFORE any manifest change)

```bash
# Custom-format dump, no ownership/ACLs (source owner is `postgres`)
kubectl exec -n $NS "$SRCPOD" -c postgres -- \
  pg_dump -U postgres -d linkwarden --no-owner --no-acl -Fc -f /tmp/lw.dump

# Copy it out to the workstation
kubectl cp -c postgres "$NS/$SRCPOD:/tmp/lw.dump" ./lw.dump

# Sanity: file exists and is non-trivial, and lists the expected tables
ls -lh ./lw.dump
pg_restore -l ./lw.dump | grep -iE 'TABLE .*(Link|Collection|User|Tag)' | head
```

Keep `./lw.dump` until the very end — it is the rollback artifact.

---

## Step B — Deploy the CNPG cluster (empty, fresh app secret)

The cluster is defined in `postgres-appdb.yaml` (a `CatalystCNPGAppDB`, which renders the
Cluster, its ObjectStore and its ScheduledBackup) and wired into `kustomization.yaml`.
It was `postgres.yaml`, a hand-written Cluster, when this runbook was written.
Let Flux reconcile, or force it:

```bash
# via Flux
flux reconcile kustomization <the-flux-kustomization-that-owns-home-automation> --with-source
# (or, targeted apply of just the cluster if you want it up before the deployment change)
# kubectl apply -f applications/home-automation/base/linkwarden/postgres-appdb.yaml

# Wait for the cluster to be healthy (1/1)
kubectl -n $NS wait --for=condition=Ready cluster/linkwarden-postgres --timeout=300s
kubectl get cluster -n $NS linkwarden-postgres
kubectl get secret -n $NS linkwarden-postgres-app -o jsonpath='{.data.uri}' | base64 -d; echo
```

---

## Step C — Restore INTO the CNPG primary

```bash
export CNPGPOD=$(kubectl get pod -n $NS -l cnpg.io/cluster=linkwarden-postgres,role=primary -o jsonpath='{.items[0].metadata.name}')
echo "cnpg primary: $CNPGPOD"

# Copy the dump into the CNPG primary
kubectl cp ./lw.dump "$NS/$CNPGPOD:/var/lib/postgresql/data/lw.dump" -c postgres

# Restore as the `linkwarden` role into the CNPG-created `linkwarden` DB.
# Inside a CNPG pod, `psql`/`pg_restore` run as the postgres superuser via the
# local socket, so --role=linkwarden re-owns objects to linkwarden. The DB and
# role already exist (initdb), so NO --create / NO -C.
kubectl exec -n $NS "$CNPGPOD" -c postgres -- \
  pg_restore --no-owner --role=linkwarden -d linkwarden --exit-on-error \
  /var/lib/postgresql/data/lw.dump

# (If pre-existing Prisma-seeded empty tables cause "already exists" noise on a
#  fresh initdb they won't — the DB is empty. If ever needed, add --clean --if-exists.)

# Verify row counts landed
kubectl exec -n $NS "$CNPGPOD" -c postgres -- \
  psql -U linkwarden -d linkwarden -c '\dt' -c 'SELECT count(*) AS links FROM "Link";' -c 'SELECT count(*) AS collections FROM "Collection";'

# Clean up the dump copy inside the pod
kubectl exec -n $NS "$CNPGPOD" -c postgres -- rm -f /var/lib/postgresql/data/lw.dump
```

---

## Step D — Cut over the Deployment

The manifest changes (co-pod removed, `DATABASE_URL` → `linkwarden-postgres-app`
`uri`, `postgres-data` volume gone) are already in git. Reconcile:

```bash
flux reconcile kustomization <the-flux-kustomization-that-owns-home-automation> --with-source
kubectl rollout status deploy/linkwarden -n $NS --timeout=300s
```

**SSA / field-ownership note:** this Deployment is Flux-managed (server-side
apply), and the co-pod container is being *removed* (a list-element deletion) plus
`DATABASE_URL` is changing from an inline/secret ref. Flux's SSA normally handles
this via a rolling replace (strategy is `Recreate` here, so the old pod is torn
down first). If the rollout wedges on the stale 3-container ReplicaSet or you see a
field-ownership conflict, force a clean replace:

```bash
kubectl rollout restart deploy/linkwarden -n $NS
# last resort if a stuck pod holds the old inline postgres field:
kubectl delete pod -n $NS -l app=linkwarden
```

Do NOT `kubectl delete deploy` unless truly stuck — Flux will recreate it, but you
lose nothing by letting reconcile drive it.

---

## Step E — VERIFY (all must pass before retiring anything)

```bash
# 1. Pod is 2/2 (linkwarden + meilisearch only — NO postgres container)
kubectl get pod -n $NS -l app=linkwarden -o wide
kubectl get pod -n $NS -l app=linkwarden -o jsonpath='{.items[0].spec.containers[*].name}'; echo

# 2. App connected, no DB errors, Prisma sees the migrated schema
kubectl logs -n $NS deploy/linkwarden -c linkwarden --tail=100 | grep -iE 'error|prisma|database|listen' 

# 3. HTTP up
kubectl exec -n $NS deploy/linkwarden -c linkwarden -- wget -qO- http://localhost:3000/ >/dev/null && echo "http OK"
```

Then **in the browser** at `https://linkwarden.knowledgedump.space` (or
`http://linkwarden.talos00`):

- Log in (Authentik SSO still works — those creds untouched).
- **Bookmarks, collections, and tags are all present** (compare against the counts
  from Step C).
- Open a bookmark; **Meilisearch full-text search still returns results** (the
  `linkwarden-meili` PVC was never touched).

---

## Step F — Retire the old DB PVC (ONLY after Step E fully passes)

```bash
# The bare co-pod PVC is already removed from git (pvc.yaml) but NOT deleted live.
kubectl get pvc -n $NS linkwarden-postgres
kubectl delete pvc -n $NS linkwarden-postgres
```

Keep `./lw.dump` archived for a few days as belt-and-suspenders.

---

## ROLLBACK (any failure before Step F)

Nothing destructive happens until Step F, so rollback is clean:

1. `git revert` / restore the deployment.yaml + pvc.yaml + external-secret.yaml +
   kustomization.yaml changes (bring back the `postgres:16-alpine` co-pod and the
   `linkwarden-postgres` PVC volume, and the old `DATABASE_URL`/`postgres-password`).
2. `flux reconcile ...` — the old co-pod re-attaches the **untouched**
   `linkwarden-postgres` PVC, so all bookmarks are exactly as they were.
3. Optionally `kubectl delete cluster -n $NS linkwarden-postgres` to remove the
   half-migrated CNPG cluster (and its `linkwarden-postgres-1` PVC).
4. The `./lw.dump` remains a second recovery path if the PVC were ever lost.

**PG16→17 caveat:** the forward major jump is only safe because this is a *logical*
dump/restore (`pg_dump -Fc` → `pg_restore`), never a binary/`pg_upgrade` of the PG16
data directory onto the PG17 cluster. Do not attempt to point CNPG PG17 at the old
PGDATA. If `pg_restore` reports version/extension errors, they will surface in Step
C (before cutover) — abort and rollback there, the source is still live.
