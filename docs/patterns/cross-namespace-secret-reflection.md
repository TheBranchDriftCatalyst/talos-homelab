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
consumer (e.g. dbgate) ─secretKeyRef▶ B/<name>  (in its own namespace)
```

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

### 4. Consume — dbgate predefined connections
[`infrastructure/base/databases/dbgate/deployment.yaml`](../../infrastructure/base/databases/dbgate/deployment.yaml)
reads env-based connections; creds come from the mirrored secret via `secretKeyRef`:

```yaml
env:
  - name: CONNECTIONS
    value: "crowdsec,forgejo"          # dbgate's format is <PARAM>_<id>, not CONNECTION_<id>_<param>
  - { name: ENGINE_crowdsec,   value: "postgres@dbgate-plugin-postgres" }
  - { name: SERVER_crowdsec,   value: "crowdsec-postgres-rw.crowdsec.svc.cluster.local" }
  - { name: PORT_crowdsec,     value: "5432" }
  - { name: USER_crowdsec,     valueFrom: { secretKeyRef: { name: crowdsec-postgres-app, key: username } } }
  - { name: PASSWORD_crowdsec, valueFrom: { secretKeyRef: { name: crowdsec-postgres-app, key: password } } }
  - { name: DATABASE_crowdsec, valueFrom: { secretKeyRef: { name: crowdsec-postgres-app, key: dbname   } } }
```

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
  does **not** add the `cnpg.io/cluster` label → the policy's selector misses it. Fix: add the
  `reflector.*` annotations directly to that secret's manifest.
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
| `infrastructure/base/kyverno-policies/reflect-cnpg-app-secrets.yaml` | the mutating ClusterPolicy + background-controller RBAC |
| `infrastructure/base/reflector/` | emberstack/reflector install |
| `infrastructure/base/databases/dbgate/deployment.yaml` | consumer (dbgate) predefined connections |
| `clusters/catalyst-cluster/{kyverno,kyverno-policies,reflector}.yaml` | Flux Kustomizations |
