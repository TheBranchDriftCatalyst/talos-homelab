# crossplane-demo

## TL;DR

A **learning + smoke-test** stack (`TALOS-ja5`) that provisions **one minimal CR of every
operator** in the cluster and a tiny Go `flex` service that pokes each backend and reports
OK/FAIL/SKIPPED. It also hosts **Plausible Analytics** (`TALOS-4gg`), the only real
user-facing app in here.

**The actual Crossplane bit is deliberately trivial** — a `provider-kubernetes` `Object` that
renders a ConfigMap (`crossplane-made-this`). It exists to *demonstrate* Crossplane's
reconciliation loop, not to do real work.

> **Don't spread Crossplane into real workloads from this demo.** See
> [When (not) to reach for Crossplane](#when-not-to-reach-for-crossplane) below — in this
> cluster Flux + ArgoCD already cover everything Crossplane would, unless you're managing
> *external, non-k8s* infra.

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

# The flex self-test service (no ingress — port-forward or exec)
kubectl exec -n crossplane-demo deploy/demo-flex -- /flex -once   # JSON report, exit 0 = all ok
kubectl port-forward -n crossplane-demo deploy/demo-flex 8080:8080 &
open http://localhost:8080/status                                 # HTML status table
```

### Web UIs

| URL | Exposure | What |
| --- | --- | --- |
| `http://plausible.talos00` | LAN-only (`lan-only` middleware) | Plausible **admin dashboard** |
| `https://analytics.knowledgedump.space/js/*`, `/api/event` | Public (Cloudflare-proxied) | Plausible **tracker script + event ingest only** — everything else 404s |
| `demo-flex :8080/status` | Cluster-internal (no ingress) | flex OK/FAIL/SKIPPED HTML table |

---

## Deep Dive

### What's in here

| Path | What it provisions |
| --- | --- |
| `dragonfly.yaml` | Dragonfly (Redis-compatible) |
| `rabbitmq.yaml` | RabbitmqCluster + Queue |
| `clickhouse.yaml` | ClickHouseInstallation (Altinity operator) |
| `opensearch.yaml` | OpenSearchCluster |
| `crossplane-provider.yaml` | `provider-kubernetes` install + RBAC (pkg.crossplane.io CRDs) |
| `object/` | **The Crossplane demo:** ProviderConfig + `Object` → ConfigMap `crossplane-made-this` |
| `argo-workflow.yaml` | Argo WorkflowTemplate + SA/RBAC |
| `celery/` | Celery worker + KEDA ScaledObject |
| `flex/` | Go service that exercises every backend above (see `flex/README.md`) |
| `plausible/` | Plausible Analytics — CNPG Postgres + Altinity ClickHouse + app (`TALOS-4gg`) |
| `tests/` | Jest integration test (dev tooling, **not** part of the Flux build) |

### The Flux split (why `object/` is separate)

`object/` (the ProviderConfig + `Object`) is a **separate Flux Kustomization**
(`clusters/catalyst-cluster/crossplane-demo-object.yaml`) that `dependsOn` this one. The
`kubernetes.crossplane.io` CRDs only exist *after* `provider-kubernetes` installs, so the
`Object` can't be dry-run/applied in the same pass that installs the provider.

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

| Provider | Manages as a CR |
| --- | --- |
| provider-aws | S3 buckets, RDS, IAM, VPCs |
| provider-cloudflare | DNS records, zones, tunnels |
| provider-sql | databases/roles *inside* a Postgres/MySQL |
| provider-kubernetes | k8s objects (this demo — the pointless case) |

**Recommendation for this cluster:** keep this as the learning/smoke-test artifact it is; do
**not** introduce Crossplane into real workloads. Almost everything it could do for us, a
purpose-built operator (external-dns, CNPG, the RabbitMQ/ClickHouse operators here) or Flux
already does more simply. Revisit only if a concrete need appears to provision an *external*
system (e.g. Cloudflare zones, AWS resources) declaratively from this repo — that's the moment
Crossplane is worth the third reconciler.

---

## Related Issues

<!-- Beads tracking for this doc -->

- `TALOS-ja5` — crossplane-demo: one minimal CR per operator + flex service + Celery/KEDA
- `TALOS-4gg` — Plausible Analytics (CNPG Postgres + Altinity ClickHouse)
