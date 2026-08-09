# Cross-namespace secret reflection (Kyverno + reflector)

## TL;DR

A secret is produced in namespace **A** but needed in namespace **B**. Kubernetes secrets are
namespace-scoped and `secretKeyRef` can't cross namespaces. This pattern **mirrors** the secret
into B — **automatically, for every current and future producer, with zero per-secret config**:

```
producer (e.g. CNPG)  ──creates──▶  A/<name> secret
        │
Kyverno ClusterPolicy ──annotates──▶  A/<name>  (reflector.* annotations)   ← auto, on match
        │
emberstack/reflector  ──mirrors───▶  B/<name>   (kept in sync)
        │
Kyverno ClusterPolicy ──mutates────▶  B/dbgate Deployment env (secretKeyRef→B/<name>) ← auto, event-driven
        │
consumer (e.g. dbgate) ─secretKeyRef▶ B/<name>  (in its own namespace)
```

The **wiring into the consumer is also event-driven** — a second Kyverno `mutateExisting`
policy injects one dbgate connection per CNPG cluster, so there is **zero per-cluster config**
anywhere (not even in the consumer's manifest). See [§4](#4-consume--dbgate-auto-injected-connections-event-driven).

**Worked example in this repo:** auto-connect **dbgate** (ns `databases`) to every **CloudNativePG**
Postgres cluster, whose `<cluster>-app` credentials live in each cluster's own namespace.

## The problem

- Consumer lives in one namespace (`databases` — dbgate).
- Producers scatter credentials across many namespaces (`crowdsec`, `forgejo`, …; each CNPG
  cluster gets a `<cluster>-app` Secret in *its* namespace).
- `secretKeyRef` is namespace-local, so the consumer can't read them.
- Doing it by hand (copying secrets, or a per-cluster annotation) doesn't scale and drifts.

## The pieces

### 1. Producer — CloudNativePG
Each `Cluster` generates a `<cluster>-app` basic-auth Secret (username/password/dbname/uri/…) in
its namespace, labelled `cnpg.io/cluster: <cluster>`. That label is our selector hook.

### 2. Auto-annotate — Kyverno mutating `ClusterPolicy`
[`infrastructure/base/kyverno-policies/reflect-cnpg-app-secrets.yaml`](../../infrastructure/base/kyverno-policies/reflect-cnpg-app-secrets.yaml)
stamps the reflector annotations onto every matching secret:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata: { name: reflect-cnpg-app-secrets }
spec:
  rules:
    - name: annotate-app-secret-for-reflection
      match:
        any:
          - resources:
              kinds: [Secret]
              names: ["*-app"]                       # only the app-creds secret
              selector:
                matchExpressions:
                  - { key: cnpg.io/cluster, operator: Exists }   # only CNPG's
      mutate:
        mutateExistingOnPolicyUpdate: true           # ← retrofits ALREADY-existing secrets
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

One rule covers both timelines:
- **Existing** secrets → mutated when the policy is installed/updated (`mutateExistingOnPolicyUpdate`).
- **New/updated** secrets → the secret's admission triggers the rule; the background controller
  applies the same patch shortly after.

### 3. Mirror — emberstack/reflector
[`infrastructure/base/reflector`](../../infrastructure/base/reflector) runs the controller. Given the
`reflection-*` annotations on a source secret, it creates/keeps a copy in the target namespace(s)
with the **same name**. Change the source → the mirror updates.

### 4. Consume — dbgate auto-injected connections (event-driven)
dbgate reads env-based connections in the format `<PARAM>_<id>` (**not** `CONNECTION_<id>_<param>`):
`CONNECTIONS` is a csv enumerator (required for multi-connection), and
`ENGINE_/SERVER_/PORT_/USER_/PASSWORD_/DATABASE_/LABEL_<id>` carry each connection. Env-var names
must be `[A-Za-z0-9_]`, so `id` = cluster name with `-` → `_`.

Originally this was a **static, hand-maintained block** in
[`dbgate/deployment.yaml`](../../infrastructure/base/databases/dbgate/deployment.yaml) — one
`secretKeyRef` block per cluster, edited by hand for every new CNPG cluster. That drifted and
didn't scale, so it was replaced (TALOS-5ccm) with a **second Kyverno `mutateExisting` policy**
that injects the connection env automatically, per cluster, event-driven. The dbgate manifest now
ships **only base env** (`WEB_ROOT`, `LOGINS`) — `CONNECTIONS` is deliberately **not** in git
(Kyverno owns it; a git-declared value would fight the mutation over the same SSA-managed key).

[`infrastructure/base/kyverno-policies/dbgate-cnpg-connections.yaml`](../../infrastructure/base/kyverno-policies/dbgate-cnpg-connections.yaml):

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata: { name: dbgate-cnpg-connections }
spec:
  rules:
    - name: inject-dbgate-connection
      match:                                   # TRIGGER = the SOURCE <cluster>-app secret …
        any:
          - resources:
              kinds: [Secret]
              names: ["*-app"]
              selector: { matchExpressions: [ { key: cnpg.io/cluster, operator: Exists } ] }
      context:
        - name: cnpgAppSecrets                 # all -app secrets cluster-wide → CONNECTIONS csv
          apiCall:
            urlPath: "/api/v1/secrets?labelSelector=cnpg.io%2Fcluster"
            jmesPath: "items[?ends_with(metadata.name, '-app')].metadata.name"
        - name: cluster                        # crowdsec-postgres-app → crowdsec-postgres
          variable: { value: "{{ regex_replace_all('-app$', '{{request.object.metadata.name}}', '') }}" }
        - name: id                             # crowdsec-postgres → crowdsec_postgres
          variable: { value: "{{ regex_replace_all('-', '{{cluster}}', '_') }}" }
        - name: connections                    # strip -app, '-'→'_', comma-join → full csv
          variable: { value: "{{ regex_replace_all('-', regex_replace_all('-app', join(',', cnpgAppSecrets), ''), '_') }}" }
      mutate:
        mutateExistingOnPolicyUpdate: true     # retrofit existing clusters on policy install/update
        targets:                               # … TARGET = the dbgate Deployment
          - { apiVersion: apps/v1, kind: Deployment, name: dbgate, namespace: databases }
        patchStrategicMerge:                   # env is merge-keyed by `name` → idempotent
          spec: { template: { spec: { containers: [ { name: dbgate, env: [
            { name: CONNECTIONS, value: "{{ connections }}" },
            { name: "ENGINE_{{ id }}",   value: "postgres@dbgate-plugin-postgres" },
            { name: "SERVER_{{ id }}",   value: "{{ cluster }}-rw.{{ request.object.metadata.namespace }}.svc.cluster.local" },
            { name: "PORT_{{ id }}",     value: "5432" },
            { name: "LABEL_{{ id }}",    value: "{{ cluster }}" },
            { name: "USER_{{ id }}",     valueFrom: { secretKeyRef: { name: "{{ request.object.metadata.name }}", key: username } } },
            { name: "PASSWORD_{{ id }}", valueFrom: { secretKeyRef: { name: "{{ request.object.metadata.name }}", key: password } } },
            { name: "DATABASE_{{ id }}", valueFrom: { secretKeyRef: { name: "{{ request.object.metadata.name }}", key: dbname   } } },
          ] } ] } } }
```

**Why trigger on the SOURCE secret but `secretKeyRef` the MIRROR?** The mirror in `databases`
does *not* keep the `cnpg.io/cluster` label nor a reflected-from annotation, so it can't tell you
the source namespace needed for the `-rw` FQDN. The source `<cluster>-app` secret (in the
cluster's own ns) *does* carry the label, and `request.object.metadata.namespace` gives the ns for
`SERVER_<id> = <cluster>-rw.<ns>.svc.cluster.local`. The injected `secretKeyRef`s point at the
mirror of the **same name** in `databases` (secretKeyRef is namespace-local — dbgate can only read
the mirror).

**Why `CONNECTIONS` is recomputed cluster-wide.** Each secret event only knows its own cluster, but
`CONNECTIONS` must list *all* of them. The `cnpgAppSecrets` apiCall lists every `-app` secret
cluster-wide and the `connections` variable rebuilds the whole csv, which the patch **replaces**
(idempotent). So adding a cluster extends the csv, and a removed cluster drops out of it on the next
mutation — its now-orphaned `*_<id>` env keys are left behind but **inert** (accepted delete-drift;
they're harmless because `CONNECTIONS` no longer enumerates them). Force a re-sync by bumping/
re-applying the policy (`mutateExistingOnPolicyUpdate`) if you want the csv corrected immediately.

**Flux must be told to ignore the injected env.** Because Kyverno writes into a Flux-managed
Deployment, Flux's drift detection would revert it on the next reconcile. The owning
[`databases` Kustomization](../../clusters/catalyst-cluster/databases.yaml) declares:

```yaml
spec:
  ignore:
    - target: { kind: Deployment, name: dbgate, namespace: databases }
      paths: [ /spec/template/spec/containers/0/env ]   # container 0 is dbgate
```

`Kustomization.spec.ignore` **requires Flux ≥ 2.9** (kustomize-controller v1.9). Without it the
env round-trips: Kyverno injects → Flux reverts → Kyverno re-injects. With it, Flux leaves that one
JSON-pointer path alone and manages the rest of the Deployment normally.

## Why Kyverno (vs. per-cluster annotations)

You *can* annotate each producer explicitly — for CNPG, `spec.inheritedMetadata.annotations`
propagates onto the generated secret. But that's per-cluster boilerplate that's easy to forget on
the next cluster. The Kyverno policy makes it **declarative and automatic**: match once, and every
present + future CNPG cluster is covered with no extra config.

## Gotchas (learned the hard way)

- **`mutateExisting` needs extra RBAC.** Kyverno's *background* controller cannot read/update
  Secrets by default (security). Grant it with an aggregated ClusterRole (label
  `rbac.kyverno.io/aggregate-to-background-controller: "true"`) — shipped alongside the policy.
  Without it the policy reports `not authorized to update Secret`.
- **Selector precision.** CNPG also makes `-ca`, `-replication`, `-server` cert secrets. Match
  `names: ["*-app"]` **plus** the `cnpg.io/cluster` label so only the credentials secret is touched.
- **User-provided secrets are invisible to the policy.** If you pre-create the `<cluster>-app`
  secret yourself (e.g. to pin a known password via `bootstrap.initdb.secret`), CNPG *adopts* it but
  does **not** add the `cnpg.io/cluster` label → *both* policies' selectors miss it. Fix: add the
  `cnpg.io/cluster: <cluster>` label to that secret's manifest so it flows through **both** policies
  uniformly (mirror + dbgate-connection injection). Also add any keys the connection policy expects
  (a user-provided basic-auth secret has only `username`/`password`; add a `dbname` key so the
  `DATABASE_<id>` `secretKeyRef` resolves). Example: `homeassistant-postgres-app` in
  [`applications/home-automation/base/homeassistant/postgres.yaml`](../../applications/home-automation/base/homeassistant/postgres.yaml).
- **`mutateExisting` on a Flux-managed target needs `spec.ignore` (Flux ≥ 2.9).** Kyverno and Flux
  will otherwise fight over the mutated field forever. Ignore the exact JSON-pointer path Kyverno
  writes, nothing broader.
- **Don't declare a Kyverno-owned key in git too.** `CONNECTIONS` is set only by Kyverno. If it were
  also in the deployment manifest, Flux (SSA) and Kyverno would each claim ownership of the same
  managed field and thrash. Keep git to base env only.
- **`mutateExisting` background controller needs Deployment write RBAC**, and the reports controller
  needs Secret read (for the apiCall) — grant via aggregated ClusterRoles
  (`rbac.kyverno.io/aggregate-to-background-controller` / `-reports-controller`). Kyverno's
  admission webhook pre-checks these when the policy is created and rejects it otherwise.
- **CRD ordering.** Keep the Kyverno install and the ClusterPolicies in **separate Flux
  Kustomizations** (`kyverno-policies` `dependsOn: kyverno`, `wait: true`) so the `kyverno.io` CRDs
  exist before any policy is applied.

## Reusing this pattern elsewhere

Any "produced here, consumed there" secret is a candidate — see `TALOS-shnu`:
- shared TLS / wildcard certs consumed by ingresses in multiple namespaces,
- a registry pull-secret needed in many namespaces,
- an ESO-materialised secret used by more than one app.

Either extend the existing policy's `match` or add a sibling ClusterPolicy with the right selector,
and point the `reflection-allowed-namespaces` / `reflection-auto-namespaces` at the target(s).

## File map

| File | Role |
|------|------|
| `infrastructure/base/kyverno/` | Kyverno install (HelmRelease 3.8.2, lean single-replica) |
| `infrastructure/base/kyverno-policies/reflect-cnpg-app-secrets.yaml` | mirror policy: annotate `-app` secrets for reflector + background RBAC |
| `infrastructure/base/kyverno-policies/dbgate-cnpg-connections.yaml` | inject policy: auto-wire dbgate env per CNPG cluster + background/reports RBAC |
| `infrastructure/base/reflector/` | emberstack/reflector install |
| `infrastructure/base/databases/dbgate/deployment.yaml` | consumer (dbgate) — base env only; connections injected by Kyverno |
| `clusters/catalyst-cluster/databases.yaml` | `databases` Flux Kustomization — `spec.ignore` on dbgate's env path |
| `clusters/catalyst-cluster/{kyverno,kyverno-policies,reflector}.yaml` | Flux Kustomizations |
