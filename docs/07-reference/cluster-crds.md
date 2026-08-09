# Cluster CRDs & Operators

> **Living reference.** Snapshot of every operator/platform CustomResourceDefinition (CRD)
> installed in the cluster, who owns it, where it is defined in this repo, and whether it is
> actually in use. Regenerate the numbers with the commands in
> [How this was generated](#how-this-was-generated).

## TL;DR

This cluster runs **~28 operators/platforms** exposing **288 CRDs across 59 API groups**.
Snapshot taken **2026-08-09** against the live cluster (`kubectl get crd`).

- **GitOps** — Flux (gotk) drives infra, Argo CD drives apps; Argo Workflows + Image Updater alongside.
- **Networking / CNI** — Cilium (CNI, LB-IPAM, L2, network policy) + external-dns. Gateway API CRDs present but unused.
- **Ingress & Certs** — Traefik (IngressRoute/Middleware) + cert-manager + trust-manager. Traefik Hub CRDs present but unused.
- **Secrets** — External Secrets Operator + 1Password Connect (114 ExternalSecrets — the secret backbone).
- **Databases (relational)** — CloudNativePG is the single Postgres platform (8 clusters).
- **Cache** — Dragonfly operator (Redis-compatible).
- **Messaging** — RabbitMQ cluster operator + messaging-topology operator.
- **NoSQL / object / search** — MongoDB, MinIO, ClickHouse (Altinity), OpenSearch operators.
- **Virtualization** — KubeVirt + CDI (VMs, DataVolumes, instancetypes).
- **Observability** — OTel-first v2 stack: Prometheus-operator CRDs (ServiceMonitors) scraped by Alloy → Mimir; Grafana operator, OpenTelemetry operator, Tempo operator.
- **Autoscaling** — KEDA (event-driven) + VPA via Goldilocks (right-sizing).
- **Policy** — Kyverno (+ PolicyReports / wgpolicyk8s).
- **Backup** — Velero (very active — 1200+ pod-volume backups).
- **Infra-as-code** — Crossplane + providers (demo-level usage).
- **Hardware / nodes** — Intel Device Plugins + Node Feature Discovery.

---

## Quick Reference

CR counts are live instance counts at snapshot time. "0" means the operator/CRD is installed but no
custom resources exist yet.

| Domain | Operator / Project | Key CRDs (Kind) | Repo path | In use? (CRs) |
| --- | --- | --- | --- | --- |
| **GitOps** | Flux (gotk) | Kustomization, HelmRelease, HelmChart, HelmRepository, GitRepository, OCIRepository, Alert, Provider, Receiver | `clusters/catalyst-cluster/flux-system/` | Yes — Kustomization 51, HelmRelease 35, HelmChart 35, HelmRepository 26, GitRepository 1, Alert 2 |
| **GitOps** | Argo CD | Application, ApplicationSet, AppProject | `infrastructure/base/argocd/` | Yes — Application 8, AppProject 1 |
| **GitOps** | Argo CD Image Updater | ImageUpdater | `infrastructure/base/argocd/image-updater/` | Yes — ImageUpdater 3 |
| **GitOps** | Argo Workflows | Workflow, WorkflowTemplate, CronWorkflow (+8 more) | `infrastructure/base/operators/argo-workflows/` | Barely — WorkflowTemplate 1, no active Workflows |
| **Networking / CNI** | Cilium | CiliumIdentity, CiliumEndpoint, CiliumNetworkPolicy, CiliumNode, CiliumLoadBalancerIPPool, CiliumL2AnnouncementPolicy (11 total) | `infrastructure/base/cilium/` | Yes — Identity 256, Endpoint 253, NetworkPolicy 6, Node 5, LBIPPool 1, L2 1 |
| **Networking / CNI** | external-dns | DNSEndpoint | `infrastructure/base/external-dns/` | Yes — DNSEndpoint 1 |
| **Networking / CNI** | Gateway API (SIG) | Gateway, GatewayClass, HTTPRoute, GRPCRoute, ReferenceGrant, BackendTLSPolicy | bundled w/ Cilium | **No — 0 CRs** (ingress via Traefik) |
| **Ingress & Certs** | Traefik | IngressRoute, IngressRouteTCP/UDP, Middleware, TLSStore, TLSOption, TraefikService, ServersTransport | `infrastructure/base/traefik/` (CRDs `bootstrap-crds/`) | Yes — IngressRoute 105, Middleware 16, IngressRouteTCP 4, TLSStore 1, TLSOption 1 |
| **Ingress & Certs** | Traefik Hub | API, APIPortal, APIPlan, ManagedApplication (15 total) | bundled w/ Traefik CRDs | **No — 0 CRs** (Hub not used) |
| **Ingress & Certs** | cert-manager | Certificate, CertificateRequest, Issuer, ClusterIssuer, Order, Challenge | `infrastructure/base/cert-manager/` | Yes — CertRequest 18, Certificate 15, Issuer 8, ClusterIssuer 4, Order 4 |
| **Ingress & Certs** | trust-manager | Bundle | `infrastructure/base/cert-manager/trust-manager.yaml` | Installed — 0 CRs |
| **Secrets** | External Secrets Operator | ExternalSecret, SecretStore, ClusterSecretStore, ClusterExternalSecret, PushSecret (+ 11 generators) | `infrastructure/base/external-secrets/` | Yes — ExternalSecret 114, SecretStore 1, ClusterSecretStore 1, ClusterExternalSecret 1 |
| **Databases** | CloudNativePG (CNPG) | Cluster, Pooler, Backup, ScheduledBackup, ImageCatalog | `infrastructure/base/databases/cloudnative-pg/` | Yes — Cluster 8, ScheduledBackup 1, Backup 1 |
| **Cache** | Dragonfly operator | Dragonfly | `infrastructure/base/operators/dragonfly-operator/` | Yes — Dragonfly 2 |
| **Messaging** | RabbitMQ cluster + topology operator | RabbitmqCluster, Queue, Exchange, Binding, User, Vhost, Permission, Policy (14 total) | `infrastructure/base/operators/rabbitmq-operator/` | Yes — RabbitmqCluster 2, Queue 2 |
| **NoSQL / object / search** | MongoDB (mongodb-kubernetes) | MongoDBCommunity (community) + MongoDB/MongoDBUser/OpsManager (enterprise) | `infrastructure/base/databases/mongodb-operator/` | Partial — MongoDBCommunity 1; enterprise CRDs 0 |
| **NoSQL / object / search** | MinIO operator | Tenant, PolicyBinding | `infrastructure/base/databases/minio-operator/` + `infrastructure/base/minio/` | Yes — Tenant 1 |
| **NoSQL / object / search** | ClickHouse (Altinity) | ClickHouseInstallation, ClickHouseInstallationTemplate, ClickHouseKeeperInstallation | `infrastructure/base/operators/clickhouse-operator/` | Yes — ClickHouseInstallation 2 |
| **NoSQL / object / search** | OpenSearch operator | OpenSearchCluster, OpensearchUser, OpensearchRole (10 kinds × 2 API groups) | `infrastructure/base/operators/opensearch-operator/` | Yes — OpenSearchCluster 1 (`opensearch.org`); `opensearch.opster.io` 0 |
| **Virtualization** | KubeVirt + CDI | KubeVirt, VirtualMachine, VirtualMachineInstance, DataVolume, VM(Cluster)Instancetype/Preference | `infrastructure/base/kubevirt/` | Yes — ClusterInstancetype 48, ClusterPreference 42, VM 1, KubeVirt 1, CDI 1, StorageProfile 3 |
| **Observability** | Prometheus operator (CRDs) | ServiceMonitor, PodMonitor, PrometheusRule, Prometheus, Alertmanager, ScrapeConfig, Probe | CRDs `bootstrap-crds/`; consumed by `monitoring/v2-otel/alloy` | Partial — ServiceMonitor 36, PrometheusRule 15, PodMonitor 9; **no Prometheus/Alertmanager CR** |
| **Observability** | Grafana operator | Grafana, GrafanaDashboard, GrafanaFolder, GrafanaDatasource (+ alerting kinds) | `infrastructure/base/monitoring/grafana-operator/` | Yes — Dashboard 44, Folder 12, Datasource 3, Grafana 1 |
| **Observability** | OpenTelemetry operator | OpenTelemetryCollector, Instrumentation, TargetAllocator, OpAMPBridge | `infrastructure/base/monitoring/v2-otel/operators/otel-operator/` | Installed — 0 CRs |
| **Observability** | Tempo operator | TempoStack, TempoMonolithic | `infrastructure/base/monitoring/v2-otel/operators/tempo-operator/` | Installed — 0 CRs |
| **Observability** | Mimir rollout-operator | ReplicaTemplate, ZoneAwarePodDisruptionBudget | bundled w/ `monitoring/v2-otel/mimir` (mimir-distributed chart) | Installed — 0 CRs |
| **Autoscaling** | KEDA | ScaledObject, ScaledJob, TriggerAuthentication, CloudEventSource | `infrastructure/base/operators/keda/` | Yes — ScaledObject 1 |
| **Autoscaling** | VPA (via Goldilocks) | VerticalPodAutoscaler, VerticalPodAutoscalerCheckpoint | `infrastructure/base/infra-control/goldilocks/` | Yes — VPA 70, Checkpoint 78 |
| **Policy** | Kyverno | ClusterPolicy, Policy, PolicyException, ValidatingPolicy, PolicyReport (7+11+2 kinds) | `infrastructure/base/kyverno/` (policies in `kyverno-policies/`) | Yes — ClusterPolicy 1, PolicyReport 8 |
| **Backup** | Velero | Backup, Restore, Schedule, PodVolumeBackup, BackupRepository, BackupStorageLocation (13 total) | `infrastructure/base/backup/` | Yes (heavy) — PodVolumeBackup 1211, Backup 44, BackupRepository 13, Schedule 3 |
| **Infra-as-code** | Crossplane (+ providers) | Composition, CompositeResourceDefinition, Provider, Function, ManagedResourceDefinition, Object | `infrastructure/base/operators/crossplane/` | Demo-level — ManagedResourceDefinition 4, DeploymentRuntimeConfig 2, Provider 1, Object 1 |
| **Hardware / nodes** | Intel Device Plugins | GpuDevicePlugin, FpgaDevicePlugin, QatDevicePlugin (7 total) + fpga.intel.com | `infrastructure/base/intel-gpu/` (CRDs `bootstrap-crds/`) | Partial — GpuDevicePlugin 1; other plugins 0 |
| **Hardware / nodes** | Node Feature Discovery | NodeFeature, NodeFeatureRule, NodeFeatureGroup | `infrastructure/base/intel-gpu/nfd-helmrelease.yaml` | Yes — NodeFeature 4, NodeFeatureRule 1 |

---

## Deep Dive by Domain

### GitOps

**Flux** (`clusters/catalyst-cluster/flux-system/`) is the primary reconciler for all
infrastructure. Its `toolkit.fluxcd.io` CRDs are the busiest control-plane objects in the
cluster:

- `kustomize.toolkit.fluxcd.io/Kustomization` (51) — one per infra component under `clusters/catalyst-cluster/*.yaml`.
- `helm.toolkit.fluxcd.io/HelmRelease` (35), `source.toolkit.fluxcd.io/HelmChart` (35), `HelmRepository` (26), `GitRepository` (1) — Helm-based installs.
- `notification.toolkit.fluxcd.io/Alert` (2), `Provider` (1) — Discord/Slack notifications (`flux-notifications`).

**Argo CD** (`infrastructure/base/argocd/`) drives *application* GitOps (per the repo's dual-GitOps
model). `argoproj.io/Application` (8) + `AppProject` (1). **Argo CD Image Updater**
(`argocd-image-updater.argoproj.io/ImageUpdater`, 3) automates image bumps.

**Argo Workflows** (`infrastructure/base/operators/argo-workflows/`) installs the full
`argoproj.io` workflow CRD set (Workflow, CronWorkflow, WorkflowTemplate, …) but currently only a
single `WorkflowTemplate` exists — effectively installed-and-idle.

### Networking / CNI

**Cilium** (`infrastructure/base/cilium/`) is the CNI and owns 11 `cilium.io` CRDs. The identity/
endpoint counts (256 / 253) track pod churn — see the memory note that CiliumIdentity bloat >1000
is the known meltdown signal. LB-IPAM (`CiliumLoadBalancerIPPool` 1) and
`CiliumL2AnnouncementPolicy` (1) provide bare-metal service LB.

**Gateway API** CRDs (`gateway.networking.k8s.io`, 6) ship with Cilium but have **zero** CRs —
ingress is handled by Traefik IngressRoute instead. **external-dns** (`externaldns.k8s.io/DNSEndpoint`, 1)
publishes DNS records.

### Ingress & Certificates

**Traefik** (`infrastructure/base/traefik/`) is the ingress controller; `traefik.io/IngressRoute`
(105) is the dominant ingress object, plus Middleware (16), IngressRouteTCP (4), TLSStore/TLSOption
(1 each). Traefik's CRDs are pre-installed via `infrastructure/base/bootstrap-crds/`. The chart also
registers 15 **Traefik Hub** (`hub.traefik.io`) CRDs (API management) — none are used.

**cert-manager** (`infrastructure/base/cert-manager/`) issues TLS: Certificate (15),
CertificateRequest (18), Issuer (8), ClusterIssuer (4), plus ACME Order (4)/Challenge.
**trust-manager** (same dir) adds `Bundle` for CA trust distribution (installed, 0 CRs).

### Secrets

**External Secrets Operator** (`infrastructure/base/external-secrets/`) is the secret backbone:
`ExternalSecret` (114) is one of the most-used CRDs in the cluster, backed by **1Password Connect**
(`onepassword-connect/`) via a `ClusterSecretStore`. Also exposes 11 `generators.external-secrets.io`
CRDs (Password, UUID, GithubAccessToken, …) for dynamic values.

### Databases (relational) — consolidated on CNPG

**CloudNativePG** (`infrastructure/base/databases/cloudnative-pg/`) is the *single* Postgres
platform — all app Postgres runs as `postgresql.cnpg.io/Cluster` (8 clusters: authentik, forgejo,
etc.). Backups via `ScheduledBackup`/`Backup`. This is a deliberate consolidation: no more
per-app Postgres StatefulSets.

### Cache — Dragonfly

**Dragonfly operator** (`infrastructure/base/operators/dragonfly-operator/`) provides
Redis/Memcached-compatible cache via `dragonflydb.io/Dragonfly` (2 instances). The standard cache
layer for apps needing Redis semantics.

### Messaging — RabbitMQ

**RabbitMQ** (`infrastructure/base/operators/rabbitmq-operator/`) installs both the **cluster
operator** (`RabbitmqCluster`, 2) and the **messaging-topology operator** (Queue, Exchange, Binding,
User, Vhost, Permission, Policy — declarative broker topology). Queue (2) confirms topology CRDs are
in active use, not just the cluster CRD.

### NoSQL / Object / Search

- **MongoDB** (`infrastructure/base/databases/mongodb-operator/`, `mongodb-kubernetes` chart) — the
  operator registers both community (`mongodbcommunity.mongodb.com/MongoDBCommunity`, 1 CR) and
  enterprise (`mongodb.com/*`, 0 CRs) API groups. Only community is used.
- **MinIO** (`infrastructure/base/databases/minio-operator/` + `infrastructure/base/minio/`) —
  `minio.min.io/Tenant` (1) for S3-compatible object storage (Velero/Loki/Mimir backends).
- **ClickHouse** (`infrastructure/base/operators/clickhouse-operator/`, Altinity) —
  `ClickHouseInstallation` (2) for OLAP/analytics.
- **OpenSearch** (`infrastructure/base/operators/opensearch-operator/`) — registers 10 kinds under
  *two* API groups (`opensearch.opster.io` legacy + `opensearch.org` current). Only
  `opensearch.org/OpenSearchCluster` (1) has a CR.

### Virtualization — KubeVirt

**KubeVirt + CDI** (`infrastructure/base/kubevirt/`) runs VMs on the cluster. `KubeVirt` (1) +
`VirtualMachine` (1) are the live workload; the large `instancetype.kubevirt.io` counts
(ClusterInstancetype 48, ClusterPreference 42) come from the KubeVirt common-instancetypes bundle,
not per-VM config. CDI (`cdi.kubevirt.io`) handles disk import (DataVolume, StorageProfile 3). Many
sub-groups (snapshot, clone, export, pool, migrations, forklift) are installed but idle with a
single VM.

### Observability — OTel-first v2 stack

The metrics pipeline is **Alloy → Mimir**, *not* a Prometheus server. Key nuance:

- **Prometheus operator CRDs** are installed (via `bootstrap-crds/`) and heavily consumed —
  `ServiceMonitor` (36), `PrometheusRule` (15), `PodMonitor` (9) — but there is **no `Prometheus`,
  `Alertmanager`, or `ThanosRuler` CR**. Alloy discovers ServiceMonitors/PodMonitors and remote-writes
  to Mimir. (See memory: Alloy WAL bounds + Mimir Alertmanager tenant-config CronJob.)
- **Grafana operator** (`infrastructure/base/monitoring/grafana-operator/`, v5.20.0) manages Grafana
  declaratively: GrafanaDashboard (44), GrafanaFolder (12), GrafanaDatasource (3), Grafana (1).
- **OpenTelemetry operator** (`monitoring/v2-otel/operators/otel-operator/`) and **Tempo operator**
  (`.../tempo-operator/`) are installed but have no CRs yet (collectors/traces run via direct Helm
  installs under `v2-otel/`).
- **Mimir rollout-operator** CRDs (`rollout-operator.grafana.com`) come bundled with the
  mimir-distributed chart; 0 CRs.

### Autoscaling

- **KEDA** (`infrastructure/base/operators/keda/`) — event-driven scaling, `ScaledObject` (1) live.
- **VPA / Goldilocks** (`infrastructure/base/infra-control/goldilocks/`) — right-sizing.
  `VerticalPodAutoscaler` (70) + Checkpoints (78) are auto-created by Goldilocks across namespaces.
  Note: VPA CRDs are installed by Goldilocks here, not a standalone `operators/` dir.

### Policy — Kyverno

**Kyverno** (`infrastructure/base/kyverno/`, policies in `infrastructure/base/kyverno-policies/`)
owns three API groups: `kyverno.io` (ClusterPolicy 1, Policy, PolicyException), the newer
`policies.kyverno.io` (ValidatingPolicy/MutatingPolicy/… — the v2 policy types), `reports.kyverno.io`
(EphemeralReport), and emits `wgpolicyk8s.io/PolicyReport` (8) for results.

### Backup — Velero

**Velero** (`infrastructure/base/backup/`, Helm) is very active: `PodVolumeBackup` (1211),
`Backup` (44), `BackupRepository` (13), `Schedule` (3), `BackupStorageLocation` (1, → MinIO).
The 1200+ PodVolumeBackups reflect file-system-level (Kopia/restic) backups accumulated across
scheduled runs.

### Infra-as-code — Crossplane

**Crossplane** (`infrastructure/base/operators/crossplane/`) installs a broad CRD surface across
`pkg.crossplane.io` (Provider, Function, Configuration), `apiextensions.crossplane.io`
(Composition, CompositeResourceDefinition, ManagedResourceDefinition), `ops.crossplane.io`, and the
kubernetes provider (`kubernetes.crossplane.io` + namespaced `kubernetes.m.crossplane.io`, the
Crossplane v2 variant). Usage is demo-level: ManagedResourceDefinition (4), DeploymentRuntimeConfig
(2), Provider (1), Object (1) — see `crossplane-demo` namespace.

### Hardware / Nodes

- **Intel Device Plugins** (`infrastructure/base/intel-gpu/`, CRDs in `bootstrap-crds/`) — 7
  `deviceplugin.intel.com` CRDs (GPU, FPGA, QAT, SGX, DSA, DLB, IAA) + 2 `fpga.intel.com`. Only
  `GpuDevicePlugin` (1) is deployed (iGPU for transcoding); the rest are installed-and-idle.
- **Node Feature Discovery** (`infrastructure/base/intel-gpu/nfd-helmrelease.yaml`) — labels nodes
  by hardware: `NodeFeature` (4), `NodeFeatureRule` (1).
- **NVIDIA CDI** (`infrastructure/base/nvidia-cdi/`) is a plain init manifest (no CRDs).

---

## Notable Findings

- **Installed-but-unused CRD surface** is significant and mostly comes from upstream chart bundles:
  - Traefik Hub (15 CRDs, `hub.traefik.io`) — API-management CRDs shipped with Traefik, unused.
  - Gateway API (6 CRDs) — bundled with Cilium; ingress goes through Traefik instead.
  - OpenTelemetry operator, Tempo operator, Mimir rollout-operator — installed, 0 CRs.
  - Most KubeVirt sub-groups (snapshot/clone/export/pool/migrations/forklift) — idle with 1 VM.
  - 6 of 7 Intel device plugins — only GPU is deployed.
- **Prometheus operator without a Prometheus** — the biggest architectural "gotcha": ServiceMonitors
  are heavily used but scraped by Alloy → Mimir. Don't expect a `Prometheus` CR.
- **Dual API groups** — OpenSearch (`opensearch.opster.io` legacy + `opensearch.org`) and Crossplane
  kubernetes provider (`kubernetes.crossplane.io` + `kubernetes.m.crossplane.io`) each register two
  groups; only one is actively used in each case.
- **MongoDB operator ships enterprise + community** CRDs; only the community CRD has an instance.
- **CRDs are bootstrapped separately** for several components via
  `infrastructure/base/bootstrap-crds/` (Argo CD, Traefik, Prometheus operator, Grafana operator,
  external-dns, Intel device plugins, NFD) — so the CRD is defined there even though the operator/
  workload lives elsewhere. Check both when tracing ownership.
- **Consolidation is real**: CNPG is the only Postgres path (8 clusters), Dragonfly the only cache,
  RabbitMQ topology operator manages broker objects declaratively.

---

## How this was generated

```bash
# 1. Authoritative CRD list (group / kind / plural)
kubectl get crd -o custom-columns=GROUP:.spec.group,KIND:.spec.names.kind,PLURAL:.metadata.name --no-headers | sort

# 2. Group / CRD counts
kubectl get crd -o custom-columns=GROUP:.spec.group --no-headers | sort | uniq -c | sort -rn

# 3. Live CR usage per CRD (nonzero only)
kubectl get crd -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | \
  while read c; do n=$(kubectl get "$c" -A --no-headers 2>/dev/null | wc -l); [ "$n" != 0 ] && echo "$n $c"; done | sort -rn

# 4. Find the owning operator's install path in-repo
grep -rlEi --include='*.yaml' '<operator-name>' infrastructure/ clusters/
```

Re-run and update the counts / paths whenever operators are added or removed.

---

## Related Issues

<!-- Beads tracking for this doc -->
