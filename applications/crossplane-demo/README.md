# crossplane-demo

## TL;DR

A **learning + smoke-test** stack (`TALOS-ja5`) that provisions **one minimal CR of every
operator** in the cluster and a tiny Go `flex` service that pokes each backend and reports
OK/FAIL/SKIPPED. It also hosts **Plausible Analytics** (`TALOS-4gg`), the only real
user-facing app in here.

> **Current state: the demo half is PARKED at zero.** Under `TALOS-4gg` this namespace was cut
> down to *Plausible-only*. `demo-flex`, `demo-celery-worker`, the Dragonfly, the RabbitMQ
> cluster and the OpenSearch cluster all declare **`replicas: 0` in git**, and the Celery
> `ScaledObject` carries `autoscaling.keda.sh/paused-replicas: "0"`. The CRs still exist and
> reconcile — the operators just hold them at zero, so nothing from the smoke-test half is
> running. Only Plausible + its CNPG Postgres + its Altinity ClickHouse are actually up.
> Waking any of it back up is a manifest edit (Flux will revert a `kubectl scale`).

**The actual Crossplane bit is deliberately trivial** — a `provider-kubernetes` `Object` that
renders a ConfigMap (`crossplane-made-this`). It exists to *demonstrate* Crossplane's
reconciliation loop, not to do real work.

> **Don't spread Crossplane into real *in-cluster* workloads from this demo.** See
> [When (not) to reach for Crossplane](#when-not-to-reach-for-crossplane) below — in this
> cluster Flux + ArgoCD already cover everything Crossplane would for native k8s objects. The
> *external, non-k8s* exception has since been taken up for real: AWS lives in
> `infrastructure/base/aws/` (`TALOS-hk7i`), **not** here.

---

## Quick Reference

```bash
# What's running
kubectl get pods -n crossplane-demo

# The visible Crossplane aspect — desired state (the Object CR) vs the thing it made
kubectl get objects.kubernetes.crossplane.io            # SYNCED / READY
kubectl get providers.pkg.crossplane.io                 # provider-kubernetes INSTALLED/HEALTHY
kubectl get cm crossplane-made-this -n crossplane-demo -o yaml

# See the reconciliation loop with your own eyes
kubectl delete cm crossplane-made-this -n crossplane-demo   # drift it
kubectl annotate object crossplane-made-this poke="$(date +%s)" --overwrite  # force re-observe
kubectl get cm crossplane-made-this -n crossplane-demo      # it's back

# The flex self-test service (no ingress — port-forward or exec).
# NOTE: demo-flex is parked at replicas:0 (see TL;DR), as are the backends it probes.
# These commands need the manifests scaled back up in git first.
kubectl exec -n crossplane-demo deploy/demo-flex -- /flex -once   # JSON report, exit 0 = all ok
kubectl port-forward -n crossplane-demo deploy/demo-flex 8080:8080 &
open http://localhost:8080/status                                 # HTML status table
```

### Web UIs

| URL | Exposure | What |
| --- | --- | --- |
| `https://plausible.talos00` | LAN-only (`lan-only`) **+ Authentik forward-auth** (`talos-admin` / `cluster-admin`); `http://` redirects to `https://` | Plausible **admin dashboard** |
| `https://analytics.knowledgedump.space/js/*`, `/api/event` | Public (Cloudflare-proxied, external-dns-managed) | Plausible **tracker script + event ingest only** — everything else 404s |
| `demo-flex :8080/status` (Service `demo-flex:80` → pod `:8080`) | Cluster-internal (no ingress) — **currently 0 replicas** | flex OK/FAIL/SKIPPED HTML table |

---

## Deep Dive

### What's in here

| Path | What it provisions |
| --- | --- |
| `registry-pull-secret.yaml` | ESO `dockerconfigjson` for `registry.talos00` (the flex image pull secret) |
| `dragonfly.yaml` | Dragonfly (Redis-compatible) — *paused at `replicas: 0`* |
| `rabbitmq.yaml` | RabbitmqCluster + Queue — *paused at `replicas: 0`* |
| `clickhouse.yaml` | ClickHouseInstallation `demo` (Altinity operator, 1 shard / 1 replica, `local-path`) — *paused via `spec.stop: "yes"`; operator holds the StatefulSet at 0* |
| `opensearch.yaml` | OpenSearchCluster — *paused, nodePool at `replicas: 0`* |
| `crossplane-provider.yaml` | `provider-kubernetes` v1.2.1 Provider + DeploymentRuntimeConfig + RBAC (pkg.crossplane.io CRDs) |
| `object/` | **The Crossplane demo:** ProviderConfig + `Object` → ConfigMap `crossplane-made-this` |
| `argo-workflow.yaml` | Argo WorkflowTemplate `demo-hello` + SA/RBAC |
| `celery/` | Celery worker + KEDA ScaledObject — *ScaledObject paused at 0* |
| `flex/` | Go service that exercises every backend above, plus the MinIO tenant in ns `minio` (see `flex/README.md`) — *paused at `replicas: 0`* |
| `plausible/` | Plausible Analytics (`TALOS-4gg`) — CNPG Postgres + Altinity ClickHouse + app, plus a sites registry + reconciler CronJob, a Stats-API Prometheus exporter, and a CNPG barman-cloud ObjectStore + ScheduledBackup |
| `tests/` | Jest integration test (dev tooling, **not** part of the Flux build) |

### The Flux split (why `object/` is separate)

`object/` (the ProviderConfig + `Object`) is a **separate Flux Kustomization**
(`clusters/catalyst-cluster/crossplane-demo-object.yaml`) that `dependsOn` this one, gated on a
health check for the `provider-kubernetes` Deployment in `crossplane-system`. The
`kubernetes.crossplane.io` CRDs only exist *after* `provider-kubernetes` installs, so the
`Object` can't be dry-run/applied in the same pass that installs the provider.

The parent `crossplane-demo` Kustomization (`clusters/catalyst-cluster/crossplane-demo.yaml`)
`dependsOn` `operators`, `databases` and `storage`, and runs with **`wait: false`** on purpose —
it only needs to *apply* the CRs; the operators provision asynchronously and the Jest suite
verifies behaviour. (Gating Flux readiness on the `demo-flex` Deployment made a registry hiccup
cascade-block `crossplane-demo-object`.) Both Kustomizations **are** registered in
`clusters/catalyst-cluster/flux-system/kustomization.yaml` and reconcile Ready.

### What the Crossplane demo actually shows

`Object` is a Crossplane **managed resource**: you declare desired state (`forProvider.manifest`
= a ConfigMap) and the provider's control loop drives reality to match — creating it, and
**re-creating it if it drifts**.

**Watch out for the poll interval.** `provider-kubernetes` (default settings) does *not* watch
the managed object; it re-observes on an interval. So after a manual `kubectl delete cm`, the
`Object` will still report `Synced=True` for a while (stale cache) and the ConfigMap stays gone
until the next poll — or until you force it (`kubectl annotate object ... poke=...`). That lag is
a provider config choice, not proof the loop is broken.

### When (NOT) to reach for Crossplane

**Plain Kubernetes does NOT self-heal a deleted ConfigMap** — leaf objects (ConfigMap/Secret/
Service) have no owning controller. So the self-healing you see here is Crossplane, not k8s.
**But Flux would heal it too** if it were a plain manifest in git. The `provider-kubernetes`
case (Crossplane managing a native k8s object) is the *degenerate* one — it buys nothing over
the Flux + ArgoCD this cluster already runs.

Crossplane earns its place only for **external, non-k8s resources** managed as k8s CRs via
GitOps (the Terraform alternative):

| Provider | Manages as a CR | Status in this cluster |
| --- | --- | --- |
| `provider-aws-s3` + `upbound-provider-family-aws` v2.7.0 | S3 buckets (and, via POC-DEMO XRDs, EC2 / ECS Fargate) | **Installed + healthy, in real use** — `infrastructure/base/aws/` |
| provider-cloudflare | DNS records, zones, tunnels | Not installed — external-dns already writes Cloudflare DNS |
| provider-sql | databases/roles *inside* a Postgres/MySQL | Not installed |
| `provider-kubernetes` v1.2.1 | k8s objects (this demo — the pointless case) | Installed; only consumer is this demo |

**Recommendation for this cluster (updated — the escape hatch below has since been taken):**
the original call was "keep this a learning artifact, don't introduce Crossplane into real
workloads," and that still holds for *in-cluster* objects — a purpose-built operator
(external-dns, CNPG, the RabbitMQ/ClickHouse operators here) or Flux does it more simply. But
the *external* case arrived: **`TALOS-hk7i` put real AWS infra on Crossplane.**
`provider-aws-s3` + `upbound-provider-family-aws` v2.7.0 are installed and healthy, and
`infrastructure/base/aws/` holds the XRDs + Compositions:

- `XBucket` — the real one; `offsite-backups` and `models-library` XBucket CRs exist and compose
  (`SYNCED=True`; `READY` was still `False` at the time of this pass)
- `XFargateApp`, `XInstance`, `XGPUInstance` (`TALOS-455u`) — **POC-DEMO, human-gated**

That work lives **there**, not here. This directory stays the `provider-kubernetes`
learning/smoke-test artifact.

---

## Related Issues

<!-- Beads tracking for this doc -->

- `TALOS-ja5` — crossplane-demo: one minimal CR per operator + flex service + Celery/KEDA
- `TALOS-4gg` — Plausible Analytics (CNPG Postgres + Altinity ClickHouse); also the reason the
  demo half is parked at 0 replicas (Plausible-only)
- `TALOS-hk7i` — AWS S3 via Crossplane (`provider-aws-s3` + XBucket) — lives in
  `infrastructure/base/aws/`, referenced above for contrast
- `TALOS-455u` — XGPUInstance POC-DEMO (same, `infrastructure/base/aws/`)
