# Observability Stack

## TL;DR

The observability stack provides metrics, logs, traces, and alerting for the cluster. It is
an OTEL-native LGTM stack living entirely in the **`monitoring`** namespace:

- **Grafana Alloy** - Unified collector (scrapes metrics, tails pod logs, receives OTLP)
- **Mimir** - Long-term metrics storage + Prometheus-compatible query API + Alertmanager + Ruler
- **Loki** - Log storage and query (the ops tail)
- **Tempo** - Distributed tracing backend
- **ClickStack / HyperDX** - ClickHouse-backed log analytics (SQL over logs)
- **Grafana** - Visualization, deployed and configured by grafana-operator

**Quick Access:**

- Grafana: http://grafana.talos00
- HyperDX: http://hyperdx.talos00
- Mimir (Prometheus API): http://mimir.talos00
- Loki (query API): http://loki.talos00
- Tempo (query API): http://tempo.talos00
- Alloy OTLP ingest: http://otel.talos00 (HTTP/4318)

> **Migrated stack.** Prometheus (kube-prometheus-stack) and the Graylog / OpenSearch /
> MongoDB / Fluent Bit stack that this document used to describe were **removed** during the
> OTEL migration (`TALOS-nh8`). See [Removed Components](#removed-components) below.

---

This document describes the complete observability stack for the Talos Kubernetes homelab,
including monitoring (metrics), logging, and tracing infrastructure.

## Architecture Overview

Everything now lives in a single namespace.

### `monitoring` namespace

**Collection:**

- **Alloy** (Deployment, 1 replica): cluster-wide Prometheus scraping, pod log tailing,
  and the OTLP receiver (gRPC 4317 / HTTP 4318). Fans out: metrics → Mimir (OTLP),
  logs → Loki **and** ClickStack (dual-write), traces → Tempo **and** ClickStack.
- **Alloy-node** (DaemonSet, one pod per node): per-node file tailing —
  kernel-capture logs (`/var/log/kernel-capture/<node>.log`) and netconsole-receiver
  logs → Loki. Deliberately *not* a cluster-wide scraper (that would duplicate metrics).

**Storage / query:**

- **Mimir**: metrics. Distributor / ingester (×3) / querier / query-frontend /
  query-scheduler / store-gateway / compactor / ruler / alertmanager / nginx gateway.
  Blocks live in MinIO (`minio-hl.minio.svc:9000`, bucket `mimir`).
- **Loki**: logs, single-binary mode, chunks in MinIO (bucket `loki`).
- **Tempo**: traces, monolithic `grafana/tempo` Helm chart (chart 1.24.4 — deliberately
  *not* tempo-operator, which would drag in a cert-manager dependency). Blocks in MinIO
  (bucket `tempo`).
- **ClickStack**: HyperDX app + its own OTel collector + an Altinity-operator ClickHouse
  (`chi-hyperdx-logs`) + MongoDB (HyperDX app state only, no log data).

**Presentation / alerting:**

- **Grafana** (grafana-operator managed): dashboards and datasources are CRs, not UI state.
- **Mimir Alertmanager** + **alertmanager-discord** bridge: alert routing to Discord.
- **baseline-alerts**: PrometheusRule CRs, synced into the Mimir ruler by Alloy.

**Exporters:** kube-state-metrics, node-exporter (DaemonSet), blackbox-exporter,
pushgateway, kasa-exporter, tdarr-exporter, nfs-storage-exporter, version-checker,
and per-cache redis-exporters for Dragonfly.

### `observability` namespace

**Retired.** The namespace object still exists but holds no workloads or PVCs. Its former
contents (Graylog, MongoDB, OpenSearch, Fluent Bit) were removed in the OTEL migration and
the `infrastructure/base/observability/` directory no longer exists in the repo.

## Components

### Grafana Alloy

**Deployment Method**: Helm chart (`grafana/alloy`) via Flux HelmRelease

**Configuration**:

- Deployment: `infrastructure/base/monitoring/v2-otel/alloy/helmrelease.yaml`
- DaemonSet: `infrastructure/base/monitoring/v2-otel/alloy-node/helmrelease.yaml`

**Functionality**:

- OTLP receiver on `0.0.0.0:4317` (gRPC) and `0.0.0.0:4318` (HTTP)
- Kubernetes service discovery for pods, nodes, services, endpoints
- `loki.source.kubernetes` tails all pod logs via the API and **dual-writes** them to
  Loki (`http://loki.monitoring.svc:3100/loki/api/v1/push`) and to the ClickStack
  collector (`http://clickstack-otel-collector.monitoring.svc:4318`)
- Metrics exported to Mimir via OTLP: `http://mimir-gateway.monitoring.svc:80/otlp`
- Traces exported to Tempo: `tempo.monitoring.svc:4317`
- `mimir.rules.kubernetes` watches **all** PrometheusRule CRDs cluster-wide and syncs
  them into the Mimir ruler every 30s (tenant `anonymous`)
- Adds cluster label: `talos-homelab`; pod-log job label: `kubernetes-pods`

**Access**: `otel.talos00` → `alloy:4318` (so hosts outside the cluster can push OTLP)

### Mimir

**Deployment Method**: Helm chart (`grafana/mimir-distributed`) via Flux HelmRelease

**Configuration**: `infrastructure/base/monitoring/v2-otel/mimir/helmrelease.yaml`

**Resources** (all persistence on `local-path`):

- Ingester: 3 replicas × 20Gi
- Compactor: 1 × 20Gi
- Store gateway: 1 × 10Gi
- Alertmanager: 1 × 5Gi
- Distributor / querier / query-frontend / query-scheduler: 2 replicas each, no PVC
- Ruler, nginx gateway: 1 replica each

**Retention**: `compactor_blocks_retention_period: 8760h` (1 year)

**Object storage**: MinIO at `minio-hl.minio.svc:9000`, bucket `mimir`, with separate
`alertmanager` and `ruler` storage prefixes. Credentials come from ESO-generated scoped
MinIO users (`mimir-s3-scoped`), not the root account.

**Notes**:

- Chart 6.x's experimental Kafka ingest-storage is explicitly disabled
  (`ingest_storage.enabled=false`, `kafka.enabled=false`).
- OTLP ingest is on `/otlp/v1/metrics` through the gateway.

**Access**: http://mimir.talos00 (Prometheus-compatible API at `/prometheus`)

### Loki

**Deployment Method**: Helm chart (`grafana/loki`) via Flux HelmRelease

**Configuration**: `infrastructure/base/monitoring/v2-otel/loki/helmrelease.yaml`

**Resources**: single-binary, 1 replica, 30Gi `local-path` PVC (WAL/index cache);
read/write/backend replicas set to 0. Chunks in MinIO bucket `loki`
(`s3ForcePathStyle: true`), creds from the scoped `loki-s3-scoped` MinIO user.

**Retention**: `retention_period: 720h` (30 days), compactor retention enabled.

**Notes**: Loki's OTLP endpoint (`/otlp/v1/logs`) is enabled by default in Loki 3.x, but
Alloy pushes via the native Loki push API. Loki PVCs/pods are labelled
`velero.io/exclude-from-backup` by a CronJob in `infrastructure/base/backup/`.

**Access**: http://loki.talos00

### Tempo

**Deployment Method**: Helm chart `grafana/tempo` 1.24.4 (monolithic), via Flux HelmRelease.
The chart is used **instead of** tempo-operator, which requires cert-manager. A
`tempo-operator-controller` pod does exist in the namespace but manages no Tempo CRs.

**Configuration**: `infrastructure/base/monitoring/v2-otel/tempo/helmrelease.yaml`

**Resources**: StatefulSet `tempo` (1 replica), no PVC — blocks go straight to MinIO bucket
`tempo` (scoped `tempo-s3-scoped` user). OTLP receivers on 4317 (gRPC) and 4318 (HTTP).

**Retention**: `block_retention: 168h` (7 days)

**Note**: a postRenderer rewrites the chart's `tempo.yaml` ConfigMap wholesale — the chart
emits an unsupported `defaults: {}` under `overrides`. Edit the postRenderer patch, not a
`values:` block, when changing Tempo config. The monolithic chart caps at app 2.9.0;
2.10+/3.0 is a re-platform.

**Access**: http://tempo.talos00 — but traces are normally viewed through the Grafana
Tempo datasource, not a standalone UI.

### ClickStack / HyperDX

**Deployment Method**: Helm chart `clickstack` 1.1.1 (app 2.8.0) via Flux HelmRelease,
plus an Altinity-operator `ClickHouseInstallation`.

**Configuration**: `infrastructure/base/monitoring/v2-otel/clickstack/`

**Components**:

- `clickstack-app` - HyperDX UI
- `clickstack-otel-collector` - receives the Alloy dual-write on OTLP/4318
- `chi-hyperdx-logs` - ClickHouse (50Gi `local-path`), the analytics store
- `clickstack-mongodb` - HyperDX app state only (users, dashboards, saved searches);
  10Gi data + 2G logs on `local-path`

**Deliberate deviations from chart defaults** (documented inline in the HelmRelease):
bundled ClickHouse disabled in favour of the CHI, MongoDB image bumped 5.0.32 → 8.3.8,
`usageStatsEnabled=false`, chart ingress off in favour of our Traefik IngressRoute, and a
20m Helm timeout because the mongo → app → collector OpAMP startup chain is slow.

**Access**: http://hyperdx.talos00 (HyperDX's own auth; Authentik forward-auth is a
follow-up)

**Relationship to Loki**: Alloy dual-writes. ClickStack is the analytics/SQL surface;
Loki stays the ops tail.

### Grafana

**Deployment Method**: grafana-operator (Helm) + a `Grafana` CR

**Configuration**:

- Operator: `infrastructure/base/monitoring/grafana-operator/`
- Instance: `infrastructure/base/monitoring/grafana-instances/grafana-instance.yaml`
- Datasources: `infrastructure/base/monitoring/v2-otel/grafana-datasources/`
- Dashboards: `infrastructure/base/monitoring/grafana-dashboards/` (JSON + GrafanaDashboard CRs)

**Datasources** (all `GrafanaDatasource` CRs):

| Name  | Type       | URL                                              |
| ----- | ---------- | ------------------------------------------------ |
| Mimir | prometheus | http://mimir-gateway.monitoring.svc:80/prometheus |
| Loki  | loki       | http://loki.monitoring.svc:3100                   |
| Tempo | tempo      | http://tempo.monitoring.svc:3200                  |

**Persistence**: **none by design.** `/var/lib/grafana` is an emptyDir. All state is code —
dashboards are `GrafanaDashboard` CRs, datasources are `GrafanaDatasource` CRs, re-pushed by
the operator on every restart. **UI-only dashboard edits do not survive a pod roll**; promote
anything worth keeping to a CR under `grafana-dashboards/`.

**Auth**:

- OIDC SSO via Authentik (`auth.generic_oauth`), blueprint at
  `infrastructure/base/authentik/grafana-blueprint.yaml`
- Split-host OIDC is deliberate: browser-facing `auth_url` is `http://auth.talos00`,
  while `token_url`/`api_url` use the in-cluster `authentik-server.authentik.svc`
- `Catalyst Admins` / `grafana-admins` group members map to Admin, everyone else Viewer
- Anonymous read-only viewer access is **on**
- Built-in admin login stays enabled as break-glass; credentials come from 1Password via ESO

```bash
# Break-glass admin credentials
kubectl get secret -n monitoring grafana-admin-credentials \
  -o jsonpath='{.data.GF_SECURITY_ADMIN_USER}' | base64 -d; echo
kubectl get secret -n monitoring grafana-admin-credentials \
  -o jsonpath='{.data.GF_SECURITY_ADMIN_PASSWORD}' | base64 -d; echo
```

**Access**: http://grafana.talos00

### Alerting

**Configuration**: `infrastructure/base/monitoring/v2-otel/alertmanager-config/` and
`infrastructure/base/monitoring/v2-otel/baseline-alerts/`

**Flow**:

1. PrometheusRule CRs (`baseline-alerts/` — cert-manager, cilium BPF, cilium identity,
   etcd snapshot, memory pressure, pipeline health, platform regression, spire) are
   synced into the **Mimir ruler** by Alloy's `mimir.rules.kubernetes`.
2. The ruler evaluates them and fires to the **Mimir Alertmanager**.
3. `alertmanager-config-pusher` (CronJob, `*/15 * * * *`) POSTs the rendered tenant
   config from `config-template.yaml` to Mimir's Alertmanager API and pings a heartbeat URL.
4. Alertmanager routes to `alertmanager-discord` — a small Python bridge Deployment
   (service port 9094) that reposts to a Discord webhook.

> Mimir Alertmanager tenant config is **not** a Kubernetes object you can edit in place.
> Edit `alertmanager-config/config-template.yaml`; the CronJob pushes it.

### Exporters

| Exporter               | Namespace  | Purpose                                    |
| ---------------------- | ---------- | ------------------------------------------ |
| kube-state-metrics     | monitoring | Kubernetes object state                    |
| node-exporter          | monitoring | Host metrics (DaemonSet, all 5 nodes)      |
| blackbox-exporter      | monitoring | HTTP/TCP probes                            |
| pushgateway            | monitoring | Batch-job metrics                          |
| kasa-exporter          | monitoring | TP-Link Kasa smart plugs                   |
| tdarr-exporter         | monitoring | Tdarr transcode stats                      |
| nfs-storage-exporter   | monitoring | NAS/NFS free space (node-exporter can't see the NAS) |
| version-checker        | monitoring | Container image staleness                  |
| redis-exporter-\*      | monitoring | Dragonfly caches (multiplexed RESP+HTTP can't be scraped directly) |

Cluster-wide auto-scrape PodMonitors also exist for CloudNativePG, MongoDBCommunity,
RabbitmqCluster, and KEDA — one PodMonitor each rather than per-instance wiring.

## Removed Components

These were real, are documented in this file's history, and **no longer exist**. Left here
so the removal is explicit rather than a silent gap.

### Prometheus / kube-prometheus-stack — REMOVED

Replaced by Mimir (storage + Prometheus-compatible query API + Alertmanager + Ruler) and
Alloy (scraping). `infrastructure/base/monitoring/kube-prometheus-stack/` no longer exists;
`infrastructure/base/monitoring/kustomization.yaml` is an empty deprecation stub pointing at
`v2-otel/`. The `prometheus.talos00` and `alertmanager.talos00` hostnames are gone — use
`mimir.talos00` and Grafana Alerting instead. `ServiceMonitor` / `PodMonitor` /
`PrometheusRule` CRDs are still used; Alloy consumes them.

### Graylog / OpenSearch / MongoDB / Fluent Bit — REMOVED

The whole v1 logging pipeline was retired in the OTEL migration (`TALOS-nh8`). Logs now go
Alloy → Loki (+ ClickStack). `graylog.talos00` no longer resolves to anything, and
`infrastructure/base/observability/` is gone from the repo. An `opensearch-operator` is still
installed, but its only consumer in the repo is the `OpenSearchCluster` in
`applications/crossplane-demo/opensearch.yaml` — nothing to do with logging.

### Exportarr — MANIFESTS PRESENT, NOT DEPLOYED

`applications/arr-stack/base/exportarr/` still exists on disk (deployment, service,
servicemonitor for prowlarr/sonarr/radarr/readarr on port 9707) but it is **not referenced by
`applications/arr-stack/base/kustomization.yaml`** and no exportarr pods are running. The
`media-dev` namespace it targeted no longer exists either — the arr stack lives in `media`
(plus `media-private`, `media-experimental`). Treat this directory as orphaned until someone
decides to re-wire or delete it.

## Deployment

This stack is **Flux-managed**. There is no deploy script — the former
`scripts/deploy-observability.sh` and `scripts/deploy-stack.sh` no longer exist.

### Flux Kustomizations

| Kustomization             | Path                                             | Notes                                  |
| ------------------------- | ------------------------------------------------ | -------------------------------------- |
| `monitoring-v2-operators` | `./infrastructure/base/monitoring/v2-otel/operators` | Operators/CRDs first                |
| `monitoring`              | `./infrastructure/base/monitoring/v2-otel`       | Data plane; depends on the operators ks |
| `control-plane-scrape`    | `./infrastructure/base/monitoring/control-plane-scrape` | etcd/apiserver scrape config    |
| `version-checker`         | `./infrastructure/base/monitoring/version-checker` |                                       |

The operators split exists so CRDs land before anything that references them.

### Making a change

```bash
# 1. Edit the manifest under infrastructure/base/monitoring/...
# 2. Validate
kubectl kustomize infrastructure/base/monitoring/v2-otel >/dev/null

# 3. Commit + push, then reconcile.
#    ALWAYS fetch the source first, or you reconcile a stale revision.
flux reconcile kustomization monitoring --with-source

# 4. Verify
flux get kustomization monitoring
flux get helmrelease -n monitoring
```

## Post-Deployment Configuration

### Grafana

1. **Access**: http://grafana.talos00
2. **Login**: via Authentik SSO ("Sign in with Authentik"), or break-glass admin from the
   `grafana-admin-credentials` secret (command above)
3. **Datasources**: already provisioned as CRs — nothing to add by hand
4. **Dashboards**: add JSON under
   `infrastructure/base/monitoring/grafana-dashboards/json/` and a matching
   `GrafanaDashboard` CR under `.../resources/`. To force a refresh of an existing
   dashboard, delete its `GrafanaDashboard` CR and let Flux recreate it.
   See `docs/08-monitoring/GRAFANA-DASHBOARDS.md`.

### HyperDX

1. **Access**: http://hyperdx.talos00
2. First-run creates the local admin account (HyperDX's own auth, not Authentik yet)
3. Logs arrive automatically from the Alloy dual-write — no input to configure

## Monitoring

### Check Component Status

```bash
# Everything lives in `monitoring`
kubectl get pods -n monitoring
kubectl get pvc -n monitoring
kubectl get svc -n monitoring
kubectl get ingressroute -n monitoring

# GitOps health
flux get helmrelease -n monitoring
flux get kustomizations -A | grep -E 'monitoring|NAME'
```

### View Logs

```bash
# Alloy (collector). NOTE: app.kubernetes.io/name=alloy matches BOTH the
# Deployment and the DaemonSet — select on `instance` to separate them.
kubectl logs -n monitoring -l app.kubernetes.io/instance=alloy        # Deployment
kubectl logs -n monitoring -l app.kubernetes.io/instance=alloy-node   # DaemonSet

# Mimir (per component)
kubectl logs -n monitoring -l app.kubernetes.io/component=ingester
kubectl logs -n monitoring -l app.kubernetes.io/component=distributor

# Loki
kubectl logs -n monitoring -l app.kubernetes.io/name=loki

# Tempo
kubectl logs -n monitoring tempo-0

# Grafana
kubectl logs -n monitoring -l app=grafana

# ClickStack (both pods carry app.kubernetes.io/name=clickstack; the plain
# `app` label is what distinguishes them)
kubectl logs -n monitoring -l app=clickstack        # HyperDX app
kubectl logs -n monitoring -l app=otel-collector    # ClickStack collector
```

### Verify Metrics Collection

```bash
# Alloy's own UI shows every component's health and last error
kubectl port-forward -n monitoring svc/alloy 12345:12345
# http://localhost:12345/  -> component graph
# http://localhost:12345/-/ready

# Query Mimir directly (Prometheus-compatible)
curl -s -H 'X-Scope-OrgID: anonymous' \
  'http://mimir.talos00/prometheus/api/v1/query?query=up' | head -c 400

# Or from Grafana: Explore -> Mimir datasource
```

### Verify Log Collection

```bash
# Loki: are streams arriving?
curl -s 'http://loki.talos00/loki/api/v1/labels'
curl -s --get 'http://loki.talos00/loki/api/v1/query' \
  --data-urlencode 'query={namespace="media"}' | head -c 400

# Or in Grafana Explore -> Loki:
#   {namespace="media"}
#   {job="kernel-capture"} |~ "Kernel panic|BUG:|Oops:"

# ClickStack side of the dual-write
kubectl logs -n monitoring -l app=otel-collector --tail=50
```

### Verify Trace Collection

```bash
# Grafana Explore -> Tempo datasource -> Search
# Or push a test span to Alloy's OTLP endpoint at otel.talos00:80 (HTTP/4318 behind Traefik)
```

## Troubleshooting

### Alloy Issues

**Metrics or logs stopped arriving**:

```bash
# Alloy's component graph shows exactly which exporter is erroring
kubectl port-forward -n monitoring svc/alloy 12345:12345   # then open http://localhost:12345

kubectl logs -n monitoring -l app.kubernetes.io/instance=alloy --tail=200
```

**Remote-write backlog after a Mimir outage**: Alloy's WAL bounds are set explicitly
(`wal { max_keepalive_time }`) precisely because the default is not reliably enforced and a
Mimir outage can otherwise wedge the metrics pipeline for weeks. If the pipeline looks stuck
long after Mimir recovered, restart Alloy.

**Chronic distributed-state wedges**: the `wedge-buster` CronJobs in
`infrastructure/base/kube-system/wedge-buster/` do staggered weekly rollout-restarts of
Alloy/Mimir/spire-agent as a backstop.

### Mimir Issues

**Ingester ring wedged / writes rejected**:

```bash
kubectl get pods -n monitoring -l app.kubernetes.io/component=ingester
kubectl logs -n monitoring mimir-ingester-0 --tail=200

# Ring status lives on the DISTRIBUTOR's admin port, not the nginx gateway
# (http://mimir.talos00/ingester/ring 404s — the gateway only proxies the
# read/write API paths).
kubectl port-forward -n monitoring svc/mimir-distributor 8080:8080
# http://localhost:8080/ingester/ring
```

**S3 `SignatureDoesNotMatch`**: the scoped MinIO users are ESO-generated and **regenerate on
any spec change** (`refreshInterval: 0` does not prevent reconcile-triggered regeneration).
Check the `mimir-s3-scoped` / `loki-s3-scoped` / `tempo-s3-scoped` secrets against MinIO
before assuming a config bug.

### Loki Issues

**No streams / query returns nothing**:

```bash
kubectl logs -n monitoring loki-0 -c loki --tail=200
curl -s http://loki.talos00/ready

# Is Alloy actually pushing?
kubectl logs -n monitoring -l app.kubernetes.io/instance=alloy | grep -i "loki.write"
```

### Grafana Issues

**A dashboard reverted / an edit disappeared**: expected. Grafana has no persistence —
promote the dashboard to a `GrafanaDashboard` CR.

**Dashboard won't update from the CR**: delete the `GrafanaDashboard` CR and let Flux
recreate it; the operator does not always re-push an in-place JSON change.

**SSO login loop**: check the Authentik blueprint and that the split-host OIDC URLs are
intact (browser-facing `auth_url` on `auth.talos00`, in-cluster `token_url`/`api_url`).

### ClickStack Issues

**Collector never becomes ready**: the chart templates the collector's
`CLICKHOUSE_USER`/`CLICKHOUSE_PASSWORD` from `config.users` even with
`clickhouse.enabled=false`. If those don't match the Altinity CHI's users, the collector
fails auth and never starts.

**Looks like a crashloop during rollout**: the Helm timeout is 20m on purpose — the
mongo → app → collector OpAMP handshake chain is slow, and the 5m default was terminating
pods seconds before ready.

## Storage Requirements

Declared PVC sizes for the observability stack (all `local-path`, i.e. node-local NVMe on
the Talos EPHEMERAL partition at `/var`):

| Component            | Size          |
| -------------------- | ------------- |
| Loki                 | 30Gi          |
| Mimir ingester       | 3 × 20Gi      |
| Mimir compactor      | 20Gi          |
| Mimir store-gateway  | 10Gi          |
| Mimir alertmanager   | 5Gi           |
| ClickHouse (HyperDX) | 50Gi          |
| ClickStack MongoDB   | 10Gi + 2G logs |

**Total declared: ~187Gi** of `local-path`. (Some Mimir PVCs are currently bound to
larger legacy recovered PVs — check `kubectl get pvc -n monitoring` for actual capacity.)

Bulk data does **not** live on these volumes: Mimir blocks, Loki chunks, and Tempo blocks
are all in MinIO (buckets `mimir`, `loki`, `tempo`). Tempo has no PVC at all.

**Available storage classes**: `local-path` (default, node NVMe),
`fatboy-nfs-appdata` (NFS, `nfs-subdir-external-provisioner`), `synology-nfs`.
TrueNAS is decommissioned and is not a storage backend for anything here.

## Security Considerations

### Current Security Posture (Homelab)

- Grafana: Authentik OIDC SSO with group→role mapping; **anonymous read-only viewer access
  is intentionally enabled**; built-in admin retained as break-glass, credentials in
  1Password via ESO
- HyperDX: its own local auth, **not** behind Authentik yet
- Mimir / Loki / Tempo IngressRoutes: **no authentication** — LAN-only via the `web`
  entrypoint. Traefik's LoadBalancer VIP is `192.168.1.251`; the usual `/etc/hosts`
  entry for `*.talos00` points at `192.168.1.54` (control plane NodePort), and both paths
  reach the same routes.
- Alloy OTLP endpoint (`otel.talos00`): unauthenticated ingest, LAN-only
- Object-storage credentials are per-service **scoped** MinIO users (bucket-only), not root
- All observability hostnames are plain HTTP on the `web` entrypoint
- Alloy has cluster-wide read access for discovery and log tailing

### Production Recommendations

1. Put HyperDX behind Authentik forward-auth (the house SSO pattern)
2. Add authentication (or drop the IngressRoutes) for Mimir/Loki/Tempo
3. Move the `web` entrypoint routes to `websecure` with TLS
4. Restrict Alloy's RBAC to the namespaces that actually need log collection
5. NetworkPolicies between collector and backends

## Backup and Recovery

The `monitoring` namespace is in the **`velero-critical-data-daily`** schedule
(`30 2 * * *`, alongside `authentik`, `cilium-spire`, `dungeon-library`), and in
`velero-weekly-full` (`0 3 * * 0`, all namespaces).

**Deliberately excluded**: Loki PVCs and pods are labelled
`velero.io/exclude-from-backup` by a CronJob in
`infrastructure/base/backup/loki-backup-exclude.yaml` — the chunks live in MinIO and the
local volume is reconstructible.

**What actually needs protecting**:

1. **MinIO buckets** `mimir`, `loki`, `tempo` — the real metric/log/trace data
2. **Git** — dashboards, datasources, alert rules and all config are code
3. **ClickStack MongoDB** — HyperDX users/dashboards/saved searches (rebuildable)

Grafana itself has nothing to back up (no PVC, all state is CRs).

```bash
# Ad-hoc backup of the monitoring namespace
velero backup create monitoring-adhoc --include-namespaces monitoring

kubectl get schedules -n backup
```

## Integration with Applications

### Sending telemetry from an app

Point any OTLP SDK at Alloy:

- In-cluster gRPC: `alloy.monitoring.svc.cluster.local:4317`
- In-cluster HTTP: `http://alloy.monitoring.svc.cluster.local:4318`
- From the LAN (e.g. a Mac): `http://otel.talos00` (Traefik → alloy:4318)

Metrics land in Mimir, traces in Tempo, logs in Loki **and** ClickStack.

### Scraping an app's Prometheus endpoint

Create a `ServiceMonitor` or `PodMonitor` as usual — Alloy honours them. For the operator-
managed databases you don't need to: cluster-wide PodMonitors already cover CloudNativePG,
MongoDBCommunity, RabbitmqCluster, KEDA, and Dragonfly (via redis-exporter).

### Log Routing

All container logs are collected by Alloy and dual-written to Loki and ClickStack.

Filter in Grafana Explore (Loki):

- Namespace: `{namespace="media"}`
- Pod: `{pod=~"sonarr-.*"}`
- Job: `{job="kubernetes-pods"}` / `{job="kernel-capture"}`
- Cluster: `{cluster="talos-homelab"}`

Or query with SQL in HyperDX for anything Loki's label model can't express.

## Resources

- [Grafana Alloy Documentation](https://grafana.com/docs/alloy/latest/)
- [Mimir Documentation](https://grafana.com/docs/mimir/latest/)
- [Loki Documentation](https://grafana.com/docs/loki/latest/)
- [Tempo Documentation](https://grafana.com/docs/tempo/latest/)
- [ClickStack / HyperDX](https://clickhouse.com/docs/use-cases/observability/clickstack)
- [Grafana Operator](https://grafana.github.io/grafana-operator/)
- `docs/05-projects/otel-migration/README.md` - the v1→v2 migration design doc
- `docs/08-monitoring/GRAFANA-DASHBOARDS.md` - dashboard authoring workflow

---

## Related Issues

<!-- Beads tracking for this documentation domain -->

- [CILIUM-rwr] - Moved from docs/02-architecture/ to root level
- [TALOS-nh8] - OTEL stack migration (Prometheus/Graylog/OpenSearch/Fluent Bit → LGTM)
- [TALOS-cjny] - ClickStack / HyperDX dedicated log-analytics stack
- [TALOS-vbr] - Baseline alerts filling the kube-prometheus-stack gap
- [TALOS-xgrl.12] - Scoped per-service MinIO users for Mimir/Loki/Tempo
