# Handoff: CRD-driven auto-registration of CNPG databases into a consumer UI

> **Audience:** an implementing agent standing this pattern up in a **different repo / cluster /
> consumer**. This doc is self-contained — you do not need access to the originating repo
> (`talos-homelab`). Every manifest you need is reproduced in full below.
>
> **Originating implementation:** `talos-homelab`, tickets `TALOS-7jxm` (single-writer),
> `TALOS-5ccm` (the abandoned Kyverno design), `TALOS-clz4` (per-database, not per-cluster).
> Companion doc: `docs/patterns/cross-namespace-secret-reflection.md`.

---

## 1. TL;DR — what you are building

**Goal:** a database GUI (dbgate) that is pre-connected to *every* CloudNativePG database in the
cluster, present and future, with **zero per-cluster configuration**. Someone commits a new
`Cluster` CR in any namespace; within 15 minutes (or immediately on the next consumer deploy) it
shows up in the UI, connected, with working credentials.

**The mechanism is four parts, not one.** "Reflection" is only the middle step:

| # | Part | Job | Implemented as |
|---|------|-----|----------------|
| 1 | **Auto-annotate** | Stamp mirror-me annotations on every CNPG `<cluster>-app` Secret, existing *and* future, without touching the cluster manifests | Kyverno mutating `ClusterPolicy` + aggregated background RBAC |
| 2 | **Mirror (reflection)** | Copy those Secrets cross-namespace into the consumer's namespace, keep them in sync | emberstack/**reflector** |
| 3 | **Discover + aggregate** | Walk the CNPG **CRDs** (`Cluster` *and* `Database`), join to the mirrored Secrets, build the *complete* connection set atomically | **single-writer** sync script: CronJob (catch-up) + initContainer (deploy-time) |
| 4 | **Consume** | Load the generated set at container start | `envFrom` a generated Secret — **not** `container.env` |

```
CNPG Cluster CR (ns A)  ──creates──▶  A/<cluster>-app Secret  (label cnpg.io/cluster=<cluster>)
       │
  [1] Kyverno ClusterPolicy ──annotates──▶ A/<cluster>-app  (reflector.v1.k8s.emberstack.com/*)
       │
  [2] emberstack/reflector ──mirrors──▶ databases/<cluster>-app   (same name, kept in sync)
       │
  [3] sync.sh (CronJob every 15m  +  dbgate initContainer on every deploy)
         reads:  Cluster CRs (-A)  ∪  Database CRs (-A)   ← CRD reflection, this is the "auto"
         joins:  mirrored <cluster>-app secrets in `databases`
         writes: databases/dbgate-cnpg-connections  Secret   (COMPLETE set, single writer)
       │
  [4] dbgate Deployment ──envFrom──▶ dbgate-cnpg-connections
```

**The single most important thing in this document is §5** — the designs that *look* correct and
silently lose data. If you skip everything else, read that.

---

## 2. Prerequisites in the target cluster

- **CloudNativePG operator** installed (provides `clusters.postgresql.cnpg.io` and, for
  multi-tenant clusters, `databases.postgresql.cnpg.io`).
- **Kyverno** (originating impl: Helm chart `3.8.2`). If Kyverno is unavailable, see §7 for the
  no-Kyverno fallback.
- **emberstack/reflector** (originating impl: Helm chart `10.0.63`, repo
  `https://emberstack.github.io/helm-charts`, installed in `kube-system`).
  - **Size it properly:** it holds a watch on every mirrored secret. Measured steady state
    p50 211Mi / peak 252Mi. Request `320Mi`, limit `512Mi`. A 32Mi request + 256Mi limit
    OOMKilled repeatedly.
- A GitOps reconciler (Flux here). ArgoCD works but see the field-ownership note in §5.3.
- A container image with `kubectl` + `sh` + `base64` + `md5sum` for the sync job. Originating
  impl uses `alpine/k8s:1.31.7`.

**Namespace vocabulary used below** — substitute yours:
- **producer namespaces** — wherever CNPG `Cluster` CRs live (many).
- **consumer namespace** — where the UI lives. Called `databases` throughout.

---

## 3. Implementation, step by step

Deploy in this order. Each step is independently verifiable.

### Step 1 — Kyverno policy + background RBAC (auto-annotate)

**File:** `kyverno-policies/reflect-cnpg-app-secrets.yaml`

```yaml
---
# RBAC: Kyverno's background controller CANNOT read/update Secrets by default (deliberate,
# security). mutateExisting needs it. Grant via an AGGREGATED ClusterRole — the aggregation
# label wires these rules into the kyverno background-controller's role. Without this the
# policy reports "not authorized to update Secret" and silently does nothing.
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kyverno:background:cnpg-secret-reflect
  labels:
    app.kubernetes.io/part-of: kyverno
    rbac.kyverno.io/aggregate-to-background-controller: "true"
rules:
  - apiGroups: [""]
    resources: [secrets]
    verbs: [get, list, watch, update, patch]
---
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: reflect-cnpg-app-secrets
  annotations:
    policies.kyverno.io/title: Reflect CNPG app secrets into the consumer namespace
    policies.kyverno.io/category: Secret Management
    policies.kyverno.io/subject: Secret
spec:
  admission: true      # new/updated secrets trigger on their own admission
  background: true     # existing secrets get retrofitted
  rules:
    - name: annotate-app-secret-for-reflection
      match:
        any:
          - resources:
              kinds: [Secret]
              names: ["*-app"]                  # ONLY the app-creds secret...
              selector:
                matchExpressions:
                  - key: cnpg.io/cluster        # ...and only CNPG's (excludes -ca/-replication/-server)
                    operator: Exists
      mutate:
        mutateExistingOnPolicyUpdate: true      # ← retrofits ALREADY-existing secrets on install/update
        targets:
          - apiVersion: v1
            kind: Secret
            name: "{{ request.object.metadata.name }}"
            namespace: "{{ request.object.metadata.namespace }}"
        patchStrategicMerge:
          metadata:
            annotations:
              reflector.v1.k8s.emberstack.com/reflection-allowed: "true"
              reflector.v1.k8s.emberstack.com/reflection-allowed-namespaces: "databases"
              reflector.v1.k8s.emberstack.com/reflection-auto-enabled: "true"
              reflector.v1.k8s.emberstack.com/reflection-auto-namespaces: "databases"
```

One rule covers both timelines: **existing** secrets via `mutateExistingOnPolicyUpdate`, **new**
secrets via their own admission (the background controller applies the patch shortly after).

**Verify step 1:**
```bash
kubectl get clusterpolicy reflect-cnpg-app-secrets            # READY=true, no failures
kubectl get secret -A -l cnpg.io/cluster -o json | \
  jq -r '.items[] | select(.metadata.name|endswith("-app")) |
         "\(.metadata.namespace)/\(.metadata.name) \(.metadata.annotations["reflector.v1.k8s.emberstack.com/reflection-auto-enabled"] // "MISSING")"'
# every line must end in "true"
```
If any say MISSING, check `kubectl -n kyverno logs deploy/kyverno-background-controller | grep -i "not authorized"` → your aggregated ClusterRole didn't land.

### Step 2 — reflector (mirror)

Install the chart. Nothing else to configure — it is annotation-driven.

**Verify step 2:**
```bash
kubectl -n databases get secrets | grep -- -app     # one per CNPG cluster, same names as source
```

### Step 3 — the single writer (discover + aggregate)

Three objects, all in the consumer namespace: RBAC, the script ConfigMap, the CronJob.

**3a. RBAC** — `dbgate-connection-sync/rbac.yaml`

```yaml
---
apiVersion: v1
kind: ServiceAccount
metadata: { name: dbgate-connection-sync, namespace: databases }
---
# Cluster-wide READ of the CNPG CRDs. `databases` (the CR kind) is required, not optional —
# multi-tenant clusters bootstrap a placeholder DB and declare real tenants as Database CRs,
# so `clusters` alone does NOT describe what to connect to. See §4.
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata: { name: dbgate-connection-sync }
rules:
  - apiGroups: [postgresql.cnpg.io]
    resources: [clusters, databases]
    verbs: [get, list]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata: { name: dbgate-connection-sync }
roleRef: { apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: dbgate-connection-sync }
subjects:
  - { kind: ServiceAccount, name: dbgate-connection-sync, namespace: databases }
---
# In the consumer namespace ONLY: read mirrored -app secrets, write the generated secret,
# restart the consumer when the set changes.
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata: { name: dbgate-connection-sync, namespace: databases }
rules:
  - apiGroups: [""]
    resources: [secrets]
    verbs: [get, list, create, update, patch]
  - apiGroups: [apps]
    resources: [deployments]
    verbs: [get, patch]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata: { name: dbgate-connection-sync, namespace: databases }
roleRef: { apiGroup: rbac.authorization.k8s.io, kind: Role, name: dbgate-connection-sync }
subjects:
  - { kind: ServiceAccount, name: dbgate-connection-sync, namespace: databases }
```

Note the split: **cluster-scoped read** of CRDs, **namespace-scoped write** of secrets. Never grant
cluster-wide secret read — the mirroring step exists precisely so you don't have to.

**3b. The sync script** — `dbgate-connection-sync/configmap-script.yaml`

This is the heart of the pattern. Reproduced verbatim; the seams you must adapt are marked in §6.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: dbgate-connection-sync-script
  namespace: databases
data:
  sync.sh: |
    #!/bin/sh
    set -eu
    NS=databases
    TMP=$(mktemp -d)
    # discover every CNPG cluster: namespace|name|initdb-database
    kubectl get clusters.postgresql.cnpg.io -A \
      -o jsonpath='{range .items[*]}{.metadata.namespace}|{.metadata.name}|{.spec.bootstrap.initdb.database}{"\n"}{end}' \
      > "$TMP/clusters"
    # discover every declarative tenant database: namespace|cluster|dbname|ensure
    # Tolerate failure so a missing CRD or an RBAC gap degrades to the old initdb-only
    # behaviour instead of resolving zero databases.
    if ! kubectl get databases.postgresql.cnpg.io -A \
      -o jsonpath='{range .items[*]}{.metadata.namespace}|{.spec.cluster.name}|{.spec.name}|{.spec.ensure}{"\n"}{end}' \
      > "$TMP/dbcrs" 2>/dev/null; then
      echo "WARNING: cannot list Database CRs - falling back to initdb databases only"
      : > "$TMP/dbcrs"
    fi
    CONNS=""
    : > "$TMP/data"
    while IFS='|' read -r ns name db; do
      [ -z "$name" ] && continue
      id=$(printf '%s' "$name" | sed -e 's/-postgres$//' -e 's/-db$//' -e 's/[^A-Za-z0-9]/_/g')
      sec="${name}-app"
      user=$(kubectl -n "$NS" get secret "$sec" -o jsonpath='{.data.username}' 2>/dev/null | base64 -d 2>/dev/null || true)
      pass=$(kubectl -n "$NS" get secret "$sec" -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null || true)
      if [ -z "$user" ]; then echo "skip $ns/$name (no mirrored $sec yet)"; continue; fi
      [ -z "$db" ] && db=$(kubectl -n "$NS" get secret "$sec" -o jsonpath='{.data.dbname}' 2>/dev/null | base64 -d 2>/dev/null || true)
      [ -z "$db" ] && db="$user"
      # union: initdb database first, then this cluster's Database CRs; awk dedups, keeps order
      {
        [ -n "$db" ] && echo "$db"
        grep "^${ns}|${name}|" "$TMP/dbcrs" 2>/dev/null | while IFS='|' read -r _x _y d ens; do
          [ "$ens" = "absent" ] && continue
          [ -n "$d" ] && echo "$d"
        done
      } | awk 'NF && !seen[$0]++' > "$TMP/dbs"
      ndb=$(wc -l < "$TMP/dbs" | tr -d ' ')
      while read -r d; do
        [ -z "$d" ] && continue
        # Single-database clusters keep their original connection id so existing UI state is
        # not renamed out from under the user; only multi-database clusters get a db suffix.
        if [ "$ndb" -gt 1 ]; then
          slug=$(printf '%s' "$d" | sed -e 's/[^A-Za-z0-9]/_/g')
          cid="${id}_${slug}"
        else
          cid="$id"
        fi
        CONNS="${CONNS:+$CONNS,}$cid"
        {
          echo "ENGINE_$cid=postgres@dbgate-plugin-postgres"
          echo "SERVER_$cid=${name}-rw.${ns}.svc.cluster.local"
          echo "PORT_$cid=5432"
          echo "USER_$cid=$user"
          echo "PASSWORD_$cid=$pass"
          echo "DATABASE_$cid=$d"
          echo "LABEL_$cid=$name/$d ($ns)"
        } >> "$TMP/data"
      done < "$TMP/dbs"
    done < "$TMP/clusters"
    # Never publish an empty set - that would blank the UI on a transient API failure.
    if [ -z "$CONNS" ]; then
      echo "ERROR: resolved zero connections, refusing to overwrite dbgate-cnpg-connections"
      exit 1
    fi
    HASH=$(md5sum < "$TMP/data" | cut -d' ' -f1)
    OLD=$(kubectl -n "$NS" get secret dbgate-cnpg-connections -o jsonpath='{.metadata.annotations.dbgate\.sync/hash}' 2>/dev/null || true)
    # Emit `data:` with base64 values, NOT `stringData:`. kubectl apply can only prune a key
    # it can SEE in the live object, and the API server rewrites stringData into data on write
    # — so last-applied tracked stringData while the object held data, the two never
    # correlated, and removed keys were NEVER deleted. Stale ENGINE_/USER_/PASSWORD_ entries
    # (including old passwords) accumulated forever. Writing data: makes the three-way merge
    # prune correctly.
    {
      echo "apiVersion: v1"
      echo "kind: Secret"
      echo "metadata:"
      echo "  name: dbgate-cnpg-connections"
      echo "  namespace: $NS"
      echo "  annotations: { dbgate.sync/hash: \"$HASH\" }"
      echo "data:"
      echo "  CONNECTIONS: $(printf '%s' "$CONNS" | base64 | tr -d '\n')"
      while IFS= read -r line; do
        [ -z "$line" ] && continue
        k=${line%%=*}
        v=${line#*=}
        echo "  $k: $(printf '%s' "$v" | base64 | tr -d '\n')"
      done < "$TMP/data"
    } > "$TMP/secret.yaml"
    kubectl apply -f "$TMP/secret.yaml"
    echo "connections: [$CONNS]"
    # DO_RESTART=true (CronJob): roll the consumer when the set changed.
    # initContainer sets false — the main container will envFrom the fresh Secret on start.
    if [ "${DO_RESTART:-true}" = "true" ] && [ "$HASH" != "$OLD" ]; then
      echo "connection set changed -> rolling dbgate"
      kubectl -n "$NS" rollout restart deploy/dbgate
    else
      echo "no restart (DO_RESTART=${DO_RESTART:-true})"
    fi
```

**3c. The CronJob** — `dbgate-connection-sync/cronjob.yaml`

```yaml
apiVersion: batch/v1
kind: CronJob
metadata: { name: dbgate-connection-sync, namespace: databases }
spec:
  schedule: "*/15 * * * *"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 1
  failedJobsHistoryLimit: 2
  startingDeadlineSeconds: 120
  jobTemplate:
    spec:
      backoffLimit: 2
      activeDeadlineSeconds: 120
      ttlSecondsAfterFinished: 300
      template:
        metadata:
          labels: { app.kubernetes.io/name: dbgate-connection-sync }
        spec:
          serviceAccountName: dbgate-connection-sync
          restartPolicy: OnFailure
          securityContext:
            runAsNonRoot: true
            runAsUser: 1000
            seccompProfile: { type: RuntimeDefault }
          containers:
            - name: sync
              image: alpine/k8s:1.31.7
              securityContext:
                allowPrivilegeEscalation: false
                readOnlyRootFilesystem: true
                capabilities: { drop: [ALL] }
              command: [sh, /scripts/sync.sh]
              env:
                - { name: DO_RESTART, value: "true" }
              volumeMounts:
                - { name: script, mountPath: /scripts }
                - { name: tmp, mountPath: /tmp }   # required: readOnlyRootFilesystem + mktemp
          volumes:
            - name: script
              configMap: { name: dbgate-connection-sync-script }
            - { name: tmp, emptyDir: {} }
```

### Step 4 — wire the consumer

Two things on the consumer Deployment: the **initContainer** running the *same* script, and
`envFrom` on the main container.

```yaml
spec:
  template:
    spec:
      # The SA that lets the initContainer discover CRDs + read mirrored secrets + write the
      # connections Secret. (Justified here because dbgate is a DB-admin GUI that already holds
      # every credential — it is not an escalation. Re-evaluate for a lower-privilege consumer.)
      serviceAccountName: dbgate-connection-sync
      initContainers:
        # "a deploy = a run": regenerate the Secret BEFORE the main container starts, so every
        # (re)deploy self-syncs — no CronJob lag, never an empty fresh pod.
        - name: sync-connections
          image: alpine/k8s:1.31.7
          command: [sh, /scripts/sync.sh]
          env:
            - { name: DO_RESTART, value: "false" }   # it's already starting
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            runAsNonRoot: true
            runAsUser: 1000
            capabilities: { drop: [ALL] }
          volumeMounts:
            - { name: sync-script, mountPath: /scripts }
            - { name: sync-tmp, mountPath: /tmp }
      containers:
        - name: dbgate
          image: dbgate/dbgate:7.2.4
          env:                       # BASE ENV ONLY — see §5.4
            - { name: WEB_ROOT, value: "/" }
            - { name: LOGINS, value: "" }
          envFrom:
            - secretRef:
                name: dbgate-cnpg-connections
                optional: true       # so the consumer boots before the first sync run
      volumes:
        - name: sync-script
          configMap: { name: dbgate-connection-sync-script }
        - name: sync-tmp
          emptyDir: {}
```

### Step 5 — GitOps ordering

Separate reconciler units with explicit dependencies:

- `kyverno` (install) → `kyverno-policies` (`dependsOn: kyverno`, `wait: true`) — the `kyverno.io`
  CRDs must exist before any ClusterPolicy is applied.
- `reflector` (independent).
- `databases` (consumer + sync) — `dependsOn` your CRD/bootstrap unit; health-check the CNPG
  operator Deployment.

**No `spec.ignore` is needed** on the consumer Kustomization. This is a deliberate outcome of the
single-writer design: the Deployment's `env` is fully git-managed and nothing mutates it. If you
find yourself adding `spec.ignore` for a container env path, you have drifted back into the
broken design — see §5.1.

---

## 4. The discovery contract: **per database, not per cluster**

This is the subtlest correctness bug in the pattern and it was shipped broken first (`TALOS-clz4`).

The naive discovery is `Cluster.spec.bootstrap.initdb.database`. That silently breaks every
**multi-tenant** cluster. Clusters following the *placeholder-bootstrap* pattern — bootstrap a
throwaway database purely so CNPG mints the `-app` Secret, then declare the real tenants as
`Database` CRs — report the **placeholder**. The UI connects fine and shows an empty schema, which
a user reads as "the tool is broken".

Real damage before the fix: one cluster offered `arrstack` (0 tables) while six real tenant
databases had no connection at all; another offered two empty placeholders while its real
`knowledge_graph` and `dagster` databases were unreachable.

**The contract:** the database list per cluster is the **UNION** of the initdb database and every
`Database` CR pointing at that cluster (skipping `spec.ensure: absent`).

Union rather than "prefer Database CRs when present": there is **no reliable way** to distinguish a
placeholder from a legitimately-used initdb database, and showing one empty extra entry is strictly
better than hiding one that holds data.

**Also in the contract:**
- The `Database` CR listing is wrapped in a **tolerated failure** — a missing CRD or an RBAC gap
  degrades to initdb-only rather than resolving zero connections.
- **Connection-id stability:** single-database clusters keep their bare id; only multi-database
  clusters get the `_<dbslug>` suffix. Otherwise you rename every existing connection out from
  under the user's saved UI state on upgrade.

**Generalize this:** whatever CRD family you reflect over, ask *"is the parent CR the whole story,
or does a child CR carry the real unit of work?"* Discover the union.

---

## 5. Design constraints — do NOT "simplify" these

Each of these was tried and failed in production. They look like reasonable simplifications.

### 5.1 Never aggregate N→1 with per-source mutation

The original design (`TALOS-5ccm`) used a **second** Kyverno `mutateExisting` policy to inject the
per-cluster env directly into the consumer Deployment. It does not work:

- *N* source secrets → *N* triggers → *N* concurrent patches of the **same** Deployment. They
  collide on optimistic concurrency (`Operation cannot be fulfilled on deployments "dbgate": the
  object has been modified`) and **Kyverno's background controller does not retry**. A *random
  subset* of the env lands.
- Symptom: `CONNECTIONS` lists a cluster but its `ENGINE_<id>` is missing → the UI errors
  `missing ENGINE` / `could not get driver`. Non-deterministic; not fixable by tuning.

**Rule: aggregating N sources into 1 consumer requires a single writer that rebuilds the complete
set atomically.** That is exactly a CronJob + initContainer. Kyverno is the right tool for the
1→1 annotate step (§3.1) and the wrong tool for the N→1 aggregate step.

### 5.2 Injected env does not survive a Deployment recreation

Image bump, reschedule, node drain — the fresh pod comes up with **zero** connections until some
trigger happens to re-fire. `envFrom` a persistent Secret has no such gap.

### 5.3 Removing a mutation policy leaves its fields behind

Kyverno's injected env is owned by the `background-controller` SSA field manager. Flux only manages
*its* fields, so deleting the policy does **not** prune them — and a stale `CONNECTIONS` in
`container.env` **overrides** `envFrom`. Cleanup requires delete+recreate of the Deployment. Budget
for this if you are migrating an existing broken installation.

### 5.4 `envFrom`, never `container.env`, for the generated set

A key in `container.env` wins over `envFrom`. Keep the consumer's own `env` to base values only so
the generated Secret is authoritative.

### 5.5 Write `data:` with base64 values, never `stringData:`

`kubectl apply` can only prune a key it can *see* in the live object, and the API server rewrites
`stringData` into `data` on write. Last-applied tracked `stringData` while the object held `data`;
the two never correlated and **removed keys were never deleted**. Stale entries — including old
passwords — accumulated forever. Inert (the UI only loads ids listed in `CONNECTIONS`) but it is
invisible credential cruft. Emit `data:` directly.

### 5.6 Refuse to publish an empty set

A transient API failure must not blank the consumer. The script `exit 1`s rather than writing zero
connections. Keep this guard.

### 5.7 Hash-gate the restart

Compare an md5 of the payload against an annotation on the live Secret and only `rollout restart`
on change. Without it, a 15-minute CronJob restarts the consumer 96 times a day.

---

## 6. Adapting to a different context

The pattern has four seams. Everything else is mechanical.

| Seam | This impl | What to change |
|------|-----------|----------------|
| **Producer selector** | `Secret` named `*-app` with label `cnpg.io/cluster` | Whatever label/name your operator stamps. Be precise: CNPG also emits `-ca`, `-replication`, `-server` cert secrets — matching `*-app` **and** the label is what excludes them. |
| **Discovery query** | `clusters` ∪ `databases` (`postgresql.cnpg.io`) via `kubectl -A -o jsonpath` | Your CRD family. Apply §4: find the child CR that carries the real unit. |
| **Connection-id derivation** | strip `-postgres`/`-db` suffix, non-alnum → `_` | Repo-specific naming convention. **Env var names must be `[A-Za-z0-9_]`.** See the collision warning below. |
| **Consumer env schema** | dbgate: `CONNECTIONS` csv + `ENGINE_/SERVER_/PORT_/USER_/PASSWORD_/DATABASE_/LABEL_<id>` (note: `<PARAM>_<id>`, **not** `CONNECTION_<id>_<param>`) | Whatever your consumer reads. If the consumer wants a config *file* instead of env, write the file into the Secret as one key and mount it — the rest of the pattern is unchanged. |

**Non-CNPG producers:** the same four-part structure applies to any operator that mints
credentials in the producer's namespace — MongoDB (`MongoDBCommunity`/MCK), MinIO `Tenant` users,
RabbitMQ, Redis. Extend the Kyverno policy's `match` or add a sibling ClusterPolicy, then teach
`sync.sh` a second discovery loop that emits the appropriate `ENGINE_<id>` driver string.

**Other consumers of the same reflection substrate** (steps 1–2 are generic): shared TLS/wildcard
certs consumed by ingresses in many namespaces, registry pull-secrets, ESO-materialised secrets
used by more than one app. Point `reflection-allowed-namespaces` / `reflection-auto-namespaces` at
the target(s).

---

## 7. If Kyverno is not available

Step 1 exists only to avoid per-cluster boilerplate. Two fallbacks:

1. **CNPG `spec.inheritedMetadata.annotations`** on each `Cluster` propagates the reflector
   annotations onto the generated secret. Correct, but it is per-cluster boilerplate that is easy
   to forget on the next cluster — exactly what the policy eliminates.
2. **Fold it into the sync job.** Give the sync ServiceAccount cluster-wide `get/list` on the
   `-app` secrets and skip mirroring entirely — the script reads sources directly. Simpler
   topology, but it trades a scoped namespace-local secret read for cluster-wide secret read.
   Only acceptable if the consumer is already a full DB-admin surface.

---

## 8. Acceptance criteria

Work through all of these on the target cluster:

```bash
# 1. every CNPG -app secret carries the reflector annotations
kubectl get secret -A -l cnpg.io/cluster -o json | jq -r \
  '.items[] | select(.metadata.name|endswith("-app")) | "\(.metadata.namespace)/\(.metadata.name) \(.metadata.annotations["reflector.v1.k8s.emberstack.com/reflection-auto-enabled"]//"MISSING")"'

# 2. mirrors exist in the consumer namespace, one per cluster
diff <(kubectl get clusters.postgresql.cnpg.io -A -o jsonpath='{range .items[*]}{.metadata.name}-app{"\n"}{end}' | sort) \
     <(kubectl -n databases get secrets -o name | sed 's|secret/||' | grep -- '-app$' | sort)

# 3. the generated Secret exists and CONNECTIONS is non-empty
kubectl -n databases get secret dbgate-cnpg-connections -o jsonpath='{.data.CONNECTIONS}' | base64 -d; echo

# 4. connection count == |initdb databases ∪ Database CRs| (the §4 union, not the cluster count)
kubectl get databases.postgresql.cnpg.io -A -o custom-columns=NS:.metadata.namespace,CLUSTER:.spec.cluster.name,DB:.spec.name,ENSURE:.spec.ensure

# 5. no stale keys: every KEY_<id> suffix appears in CONNECTIONS
kubectl -n databases get secret dbgate-cnpg-connections -o json | jq -r '.data|keys[]' | grep -v '^CONNECTIONS$' | sed 's/^[A-Z]*_//' | sort -u

# 6. a fresh pod is never empty — delete the consumer pod, confirm the initContainer ran
kubectl -n databases delete pod -l app.kubernetes.io/name=dbgate
kubectl -n databases logs -l app.kubernetes.io/name=dbgate -c sync-connections --tail=20

# 7. idempotence: run the CronJob twice; the second run must log "no restart" (hash unchanged)
kubectl -n databases create job --from=cronjob/dbgate-connection-sync sync-manual-1
kubectl -n databases logs job/sync-manual-1

# 8. end-to-end: commit a new CNPG Cluster in a new namespace; within ~15 min (or on the next
#    consumer deploy) it appears connected in the UI with ZERO other changes.
```

**Also verify in the UI, not just in YAML.** The `arrstack` failure in §4 was fully green at the
manifest level: connection present, credentials valid, schema empty. Open each connection and
confirm it lists tables.

---

## 9. Known limitations (unfixed in the originating impl)

Flag these to the operator; do not assume they're handled.

- **Name collision on mirror.** reflector mirrors with the **same name**. Two clusters with the
  same name in different namespaces both mirror to `databases/<name>-app` and fight. Either
  namespace-qualify the mirror target or enforce cluster-name uniqueness.
- **Connection-id collision.** The id derivation strips namespace entirely, so `x-postgres` in two
  namespaces yields id `x` twice — the second wins and one cluster silently vanishes from the UI.
  Include the namespace in the id if your naming isn't globally unique.
- **Credentials live in a Secret in plaintext-at-rest terms.** The generated Secret aggregates
  *every* database password into one object in one namespace. That is an accepted tradeoff for a
  DB-admin GUI on a LAN behind SSO forward-auth. It is **not** acceptable for a lower-trust
  consumer — for those, mount the individual mirrored secrets instead of aggregating.
- **The sync SA is shared with the consumer pod.** The consumer Deployment runs under
  `dbgate-connection-sync` so its initContainer can work. Any RCE in the consumer inherits
  cluster-wide CRD read + namespace secret write. Acceptable for dbgate (it already holds all the
  credentials); split the SA if your consumer is less privileged.
- **User-provided `-app` secrets are invisible to the policy.** If you pre-create the
  `<cluster>-app` Secret yourself (e.g. to pin a password via `bootstrap.initdb.secret`), CNPG
  *adopts* it but does **not** add the `cnpg.io/cluster` label → the selector misses it entirely.
  Fix: add `cnpg.io/cluster: <cluster>` to that secret's manifest, plus a `dbname` key (a
  user-provided basic-auth secret has only `username`/`password`).

---

## 10. Suggested work breakdown

1. Install/verify prerequisites (CNPG, Kyverno, reflector) — sized per §2.
2. Land the Kyverno policy + aggregated RBAC; verify annotations on **existing** secrets (proves
   `mutateExistingOnPolicyUpdate` + background RBAC both work). ← highest-risk step, do it first
3. Verify mirrors land in the consumer namespace.
4. Land RBAC + script ConfigMap + CronJob; trigger a manual Job; inspect the generated Secret
   before touching the consumer.
5. Wire the consumer (`envFrom` + initContainer); confirm the fresh-pod path.
6. Walk §8 end to end, including the new-cluster test and the open-the-connection-in-the-UI check.
7. Write the pattern doc in the target repo; record the §5 constraints there so the next person
   doesn't "simplify" them back out.
