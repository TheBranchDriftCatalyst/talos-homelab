# Homelab GitOps + Arr Stack Implementation Tracker

**Project Start**: 2025-11-09
**Snapshot Date**: 2025-12-12 — everything below describes the cluster **as it was on that date**
**Last Verified Against Cluster**: 2026-08-22
**Status**: ✅ Phases 1-6 Complete — initial build finished, largely superseded since

> **Note**: This document is a **frozen historical record** of the initial implementation
> phases (Nov-Dec 2025). It is NOT a description of the current cluster.
> Ongoing work is tracked in **beads** - see [beads-index.md](beads-index.md) or run `bd ready`.

> **⚠️ Superseded since this snapshot** (verified against the live cluster 2026-08-22).
> The largest deltas — individual sections carry more specific notes:
>
> - **Cluster**: 5 nodes — `talos00` (control-plane, **tainted**, 192.168.1.54), `talos01`
>   (.177), `talos02-gpu` (.144, Intel Arc), `talos03` (.30), `talos06` (.19). Talos
>   **v1.13.2**, Kubernetes **v1.34.10**, maxPods raised 110 → **200**. Workloads no longer
>   schedule on the control plane.
> - **CNI / ingress**: **Cilium** (`ipam: kubernetes`, `routing-mode: tunnel`/vxlan) replaced
>   Flannel. Traefik runs as a **DaemonSet** behind LoadBalancer VIP **192.168.1.251**.
> - **Monitoring**: `kube-prometheus-stack` was **removed**, replaced by the v2-otel stack
>   (Mimir, Loki, Tempo, Alloy, ClickStack/HyperDX, Grafana Operator) under
>   `infrastructure/base/monitoring/v2-otel/`.
> - **Observability**: the OpenSearch + Graylog + MongoDB + Fluent Bit stack was **removed**.
>   The `observability` namespace is empty and `infrastructure/base/observability/` is gone.
> - **Media**: the `media-dev` / `media-prod` namespaces were **removed**. Media now lives in
>   `media`, `media-private`, `media-experimental`, `downloads`, and `tdarr`.
> - **Storage**: TrueNAS was decommissioned. StorageClasses are now `local-path` (default,
>   node NVMe via Talos EPHEMERAL at /var), `fatboy-nfs-appdata`
>   (NFS 192.168.1.36:/volume1/appdata) and `synology-nfs`. The generic `nfs` class is gone.
> - **New platform layers** that did not exist at snapshot time: Authentik SSO, CrowdSec
>   IPS/AppSec, Kyverno ClusterPolicies (which now *derive* homepage annotations, IngressRoute
>   `tls: {}`, the CNPG velero-exclude label, HelmRelease `remediation.retries`, the OIDC
>   hostAlias and CNPG app-secret reflector annotations), CloudNativePG, MinIO, Velero,
>   Crossplane, KubeVirt, KEDA, cert-manager, external-dns and emberstack reflector.

---

## Quick Status

| Phase                              | Status         | Progress |
| ---------------------------------- | -------------- | -------- |
| Phase 1: Directory Structure       | ✅ COMPLETE    | 100%     |
| Phase 2: GitOps Foundation         | ✅ COMPLETE    | 100%     |
| Phase 3: Multi-Environment         | ✅ COMPLETE    | 100%     |
| Phase 4: Storage Setup             | ✅ COMPLETE    | 100%     |
| Phase 5: Monitoring Stack          | ✅ COMPLETE    | 100%     |
| Phase 6: Arr Stack + Media Servers | ✅ COMPLETE    | 100%     |
| Phase 7: Finalize & Document       | 🚧 IN PROGRESS | 70%      |

**Overall Progress**: 96% (24/25 major tasks) — _as of the 2025-12-12 snapshot; the phase
plan below concluded and all later work moved to beads._

---

## Stack Overview (snapshot 2025-12-12)

### Core Infrastructure (DEPLOYED)

- **OS**: Talos Linux v1.11.1 — _now v1.13.2_
- **Kubernetes**: v1.34.0 — _now v1.34.10_
- **GitOps (Infra)**: FluxCD v2.7.3 ✅ — _controllers now helm v1.6.3 / kustomize v1.9.4 /
  notification v1.9.3 / source v1.9.4_
- **GitOps (Apps)**: ArgoCD v2.x ✅ — _now v3.5.1 (argo-cd chart 10.4.0)_
- **Ingress**: Traefik v3.5.3 ✅ — _now v3.7.11 (chart 41.3.0), DaemonSet + LB VIP
  192.168.1.251_
- **Monitoring**: kube-prometheus-stack v65.8.1 ✅ — **REMOVED**; replaced by Mimir + Loki +
  Tempo + Alloy + ClickStack/HyperDX + Grafana Operator
- **Observability**: OpenSearch + Graylog + Fluent Bit ✅ — **REMOVED**; the `observability`
  namespace is now empty
- **Storage**: local-path (default) + NFS StorageClass ✅ — _the generic `nfs` class is gone;
  now `local-path` (default), `fatboy-nfs-appdata`, `synology-nfs`_
- **Secrets**: External Secrets Operator v0.11.0 + 1Password Connect ✅ — _ESO chart now
  2.6.0; the `onepassword` ClusterSecretStore is still the backend_

### Media Applications (DEPLOYED in media-dev)

> **Superseded**: `media-dev` no longer exists. The \*arr stack and media servers run in the
> `media` namespace; Tdarr in `tdarr`; Homepage in `homepage` (8 instances); download/ingest
> tools in `downloads`. Overseerr was replaced by **Seerr**, and the standalone PostgreSQL
> Deployment by **CloudNativePG** Clusters in each app namespace.

- **Indexer Manager**: Prowlarr ✅
- **TV Automation**: Sonarr ✅
- **Movie Automation**: Radarr ✅
- **Media Servers**: Plex ✅ + Jellyfin ✅
- **Request Management**: Overseerr ✅ — _now Seerr (seerr.talos00)_
- **Transcoding**: Tdarr ✅ — _now its own `tdarr` namespace_
- **Dashboard**: Homepage ✅ — _now its own `homepage` namespace_
- **Database**: PostgreSQL ✅ — _now CloudNativePG_

### Infrastructure Testing Tools (DEPLOYED)

> **Renamed**: the `infra-testing` namespace is now **`infra-control`**
> (`infrastructure/base/infra-control/`). All five tools are still running.

- **Headlamp** - Modern K8s dashboard ✅
- **Kubeview** - Cluster visualizer ✅
- **Kube-ops-view** - Operational view ✅
- **Goldilocks** - Resource recommendations ✅
- **VPA** - Vertical Pod Autoscaler ✅

### Development Tools

- **Tilt**: Configured (Tiltfile exists) - Not yet integrated into workflow
- **Taskfile**: 90+ tasks across 4 domains (Talos, k8s, dev, infra) — _now ~147 tasks across
  6 domains: talos, k8s, dev, infra, security, certs_

### Environments

> **Superseded**: namespace-based dev/prod for media was abandoned. Neither `media-dev` nor
> `media-prod` exists; there is a single `media` namespace plus `media-private` and
> `media-experimental` for content/maturity separation, not environment separation.

- **Dev**: `media-dev` namespace ✅ - All apps deployed
- **Prod**: `media-prod` namespace ✅ - Ready for deployment

---

## Phase 1: Directory Structure ✅ COMPLETE

### ✅ Completed Tasks

- [x] Created bootstrap directories (flux, argocd)
- [x] Created infrastructure directories (base + overlays)
- [x] Created applications/arr-stack structure
- [x] Created base dirs for all apps (prowlarr, sonarr, radarr, plex, jellyfin, overseerr, tdarr, homepage)
- [x] Created namespace manifests
- [x] Created storage provisioner manifests
- [x] Created kube-prometheus-stack configuration
- [x] Created Flux bootstrap manifests
- [x] Created ArgoCD bootstrap manifests

### Directory Structure (Implemented)

> **Drifted**: `bootstrap/argocd/` is gone (only `bootstrap/flux/` remains),
> `infrastructure/base/observability/` is gone, `infra-testing/` is now `infra-control/`,
> and `applications/arr-stack/overlays/` now holds `gpu/` and `themepark/` instead of
> `dev/` and `prod/`. Tdarr, Homepage and PostgreSQL moved out of `arr-stack/base/`
> (to `applications/tdarr/`, `applications/homepage/` and CloudNativePG respectively);
> `overseerr/` became `seerr/`. `infrastructure/base/` has grown to ~45 components.

```
talos-homelab/
├── bootstrap/
│   ├── flux/                    # FluxCD installation ✅
│   └── argocd/                  # ArgoCD installation ✅
├── infrastructure/base/         # Managed by Flux ✅
│   ├── namespaces/              # media-dev, media-prod ✅
│   ├── storage/                 # local-path + NFS ✅
│   ├── traefik/                 # Ingress controller ✅
│   ├── monitoring/              # kube-prometheus-stack ✅
│   ├── observability/           # OpenSearch, Graylog, Fluent Bit ✅
│   ├── external-secrets/        # ESO + 1Password ✅
│   ├── infra-testing/           # Headlamp, Kubeview, etc. ✅
│   └── flux-notifications/      # Flux alerts + Discord ✅
├── applications/arr-stack/      # Media applications ✅
│   ├── base/
│   │   ├── prowlarr/            ✅
│   │   ├── sonarr/              ✅
│   │   ├── radarr/              ✅
│   │   ├── plex/                ✅
│   │   ├── jellyfin/            ✅
│   │   ├── overseerr/           ✅
│   │   ├── tdarr/               ✅
│   │   ├── homepage/            ✅
│   │   ├── postgresql/          ✅
│   │   ├── exportarr/           ✅
│   │   └── readarr/             ✅
│   └── overlays/
│       ├── dev/                 ✅
│       └── prod/                ✅
├── scripts/                     # Deployment automation ✅
├── docs/                        # Documentation (7 levels) ✅
├── Tiltfile                     # Tilt configuration ✅
└── Taskfile.yaml               # Task automation ✅
```

---

## Phase 2: GitOps Foundation ✅ COMPLETE

### FluxCD Deployment

**Version**: v2.7.3 (flux-v2.7.3 distribution)

**Controllers Running**:

| Controller              | Version | Status  |
| ----------------------- | ------- | ------- |
| helm-controller         | v1.4.3  | Running |
| kustomize-controller    | v1.7.2  | Running |
| notification-controller | v1.7.4  | Running |
| source-controller       | v1.7.3  | Running |

> **Now** (2026-08-22): helm-controller v1.6.3, kustomize-controller v1.9.4,
> notification-controller v1.9.3, source-controller v1.9.4.

**GitRepository Source**: `flux-system` tracking `main@sha1:5a2553ec`
(`ssh://git@github.com/TheBranchDriftCatalyst/talos-homelab`; the revision pin above is the
commit at snapshot time and has advanced many times since)

### Active Flux Resources

| Namespace        | Resource Type | Name                            | Version | Status |
| ---------------- | ------------- | ------------------------------- | ------- | ------ |
| flux-system      | GitRepository | flux-system                     | -       | ✅     |
| flux-system      | Kustomization | flux-system                     | -       | ✅     |
| external-secrets | HelmRelease   | external-secrets                | 0.11.0  | ✅     |
| kube-system      | HelmRelease   | nfs-subdir-external-provisioner | 4.0.18  | ✅     |
| monitoring       | HelmRelease   | kube-prometheus-stack           | 65.8.1  | ✅     |
| monitoring       | HelmRelease   | prometheus-blackbox-exporter    | 9.8.0   | ✅     |
| observability    | HelmRelease   | fluent-bit                      | 0.48.10 | ✅     |
| observability    | HelmRelease   | mongodb                         | 18.1.9  | ✅     |
| observability    | HelmRelease   | opensearch                      | 3.3.2   | ✅     |

> **Now** (2026-08-22): 9 HelmReleases → **40**, and **59** Flux Kustomizations.
> `kube-prometheus-stack` and all three `observability` releases are **gone**;
> `external-secrets` is chart 2.6.0 and `nfs-subdir-external-provisioner` is range-pinned
> `>=4.0.0 <5.0.0`. Current headline releases include cilium, traefik, authentik, crowdsec,
> cloudnative-pg, kyverno, velero, crossplane, keda, cert-manager, mimir-distributed, loki,
> tempo, alloy, clickstack and grafana-operator.

### Flux Notifications

| Resource | Name                   | Target  | Status |
| -------- | ---------------------- | ------- | ------ |
| Provider | discord                | Discord | ✅     |
| Alert    | critical-errors        | Discord | ✅     |
| Alert    | homelab-infrastructure | Discord | ✅     |

### ArgoCD Deployment

- **Namespace**: `argocd`
- **URL**: argocd.talos00
- **Status**: Running (7 pods) — _now ArgoCD v3.5.1 (chart 10.4.0), managing 8 Applications_

---

## Phase 3: Multi-Environment Setup ✅ COMPLETE

### ✅ Completed Tasks

- [x] Created `media-dev` namespace
- [x] Created `media-prod` namespace
- [x] Configured Traefik IngressRoutes for all services
- [x] Created dev overlay (\*.talos00 domains)
- [x] Routing working for all applications

### Active IngressRoutes (26 total)

> **Superseded** (2026-08-22): there are now **190** IngressRoutes. Of the 26 below,
> the following no longer exist: everything in `media-dev` (namespace deleted), everything in
> `observability` (stack removed), `graylog.talos00`, `prometheus.talos00`,
> `alertmanager.talos00`, `dashboard.talos00` and the `bastion` namespace. `infra-testing`
> is now `infra-control` and Headlamp/Kubeview moved to `*.priv.talos00`. `overseerr.talos00`
> is now `seerr.talos00`. `registry.talos00` now fronts **zot**, not the Docker registry/Nexus.
> Still valid: `argocd.talos00`, `grafana.talos00`, `plex.talos00`, `jellyfin.talos00`,
> `prowlarr.talos00`, `sonarr.talos00`, `radarr.talos00`, `tdarr.talos00`,
> `homepage.talos00`, `goldilocks.talos00`, `kube-ops-view.talos00`, `traefik.talos00`,
> `whoami.talos00`, `registry.talos00`.

| Namespace            | Service           | URL                   | Status |
| -------------------- | ----------------- | --------------------- | ------ |
| argocd               | ArgoCD            | argocd.talos00        | ✅     |
| monitoring           | Grafana           | grafana.talos00       | ✅     |
| monitoring           | Prometheus        | prometheus.talos00    | ✅     |
| monitoring           | Alertmanager      | alertmanager.talos00  | ✅     |
| observability        | Graylog           | graylog.talos00       | ✅     |
| observability        | Grafana           | grafana.talos00       | ✅     |
| observability        | Prometheus        | prometheus.talos00    | ✅     |
| observability        | Alertmanager      | alertmanager.talos00  | ✅     |
| media-dev            | Prowlarr          | prowlarr.talos00      | ✅     |
| media-dev            | Sonarr            | sonarr.talos00        | ✅     |
| media-dev            | Radarr            | radarr.talos00        | ✅     |
| media-dev            | Plex              | plex.talos00          | ✅     |
| media-dev            | Jellyfin          | jellyfin.talos00      | ✅     |
| media-dev            | Overseerr         | overseerr.talos00     | ✅     |
| media-dev            | Tdarr             | tdarr.talos00         | ✅     |
| media-dev            | Homepage          | homepage.talos00      | ✅     |
| infra-testing        | Headlamp          | headlamp.talos00      | ✅     |
| infra-testing        | Kubeview          | kubeview.talos00      | ✅     |
| infra-testing        | Kube-ops-view     | kube-ops-view.talos00 | ✅     |
| infra-testing        | Goldilocks        | goldilocks.talos00    | ✅     |
| registry             | Docker Registry   | registry.talos00      | ✅     |
| kubernetes-dashboard | K8s Dashboard     | dashboard.talos00     | ✅     |
| traefik              | Traefik Dashboard | traefik.talos00       | ✅     |
| default              | whoami-hostname   | whoami.talos00        | ✅     |
| default              | whoami-path       | whoami.talos00/path   | ✅     |
| bastion              | Bastion SSH       | -                     | ✅     |

---

## Phase 4: Storage Setup ✅ COMPLETE

### Storage Classes Available

> **Superseded** (2026-08-22): TrueNAS was decommissioned and the generic `nfs` class no
> longer exists. Current classes:
>
> | Name                 | Provisioner                                   | Reclaim | Binding              |
> | -------------------- | --------------------------------------------- | ------- | -------------------- |
> | `local-path`         | rancher.io/local-path                         | Delete  | WaitForFirstConsumer (default) |
> | `fatboy-nfs-appdata` | cluster.local/nfs-subdir-external-provisioner | Retain  | Immediate            |
> | `synology-nfs`       | kubernetes.io/no-provisioner                  | Retain  | Immediate            |
>
> The NFS backend is `192.168.1.36:/volume1/appdata`. `tdarr-nfs` / `tdarr-appdata` are
> PVC-level names used by `applications/tdarr/base/pvcs.yaml`, not cluster StorageClasses.

| Name       | Provisioner                                   | Reclaim Policy | Status  |
| ---------- | --------------------------------------------- | -------------- | ------- |
| local-path | rancher.io/local-path                         | Delete         | Default |
| nfs        | cluster.local/nfs-subdir-external-provisioner | Retain         | ✅      |

### PVCs in media-dev (14 total, All Bound)

> **Superseded**: the `media-dev` namespace was deleted; none of these PVCs exist. Media app
> config now lives on `fatboy-nfs-appdata` / `local-path` PVCs in the `media`,
> `media-private`, `media-experimental`, `downloads` and `tdarr` namespaces.

| PVC Name              | Capacity | Storage Class | Status |
| --------------------- | -------- | ------------- | ------ |
| prowlarr-config       | 1Gi      | local-path    | Bound  |
| sonarr-config         | 5Gi      | local-path    | Bound  |
| radarr-config         | 5Gi      | local-path    | Bound  |
| plex-config           | 50Gi     | local-path    | Bound  |
| jellyfin-config       | 50Gi     | local-path    | Bound  |
| overseerr-config      | 1Gi      | local-path    | Bound  |
| homepage-config       | 1Gi      | local-path    | Bound  |
| postgresql-data       | 10Gi     | local-path    | Bound  |
| media-shared          | 100Gi    | local-path    | Bound  |
| downloads-shared      | 50Gi     | local-path    | Bound  |
| tdarr-config          | 2Gi      | local-path    | Bound  |
| tdarr-server          | 5Gi      | local-path    | Bound  |
| tdarr-logs            | 2Gi      | local-path    | Bound  |
| tdarr-transcode-cache | 50Gi     | local-path    | Bound  |

---

## Phase 5: Monitoring Stack ✅ COMPLETE

### Monitoring Namespace (monitoring)

> **Superseded** (2026-08-22): `kube-prometheus-stack` was removed. The `monitoring`
> namespace now runs the v2-otel stack — **Mimir** (metrics), **Loki** (logs), **Tempo**
> (traces), **Alloy** + **alloy-node** (collection), **ClickStack/HyperDX**,
> **Grafana Operator** (dashboards as JSON + `GrafanaDashboard` CRs), plus
> kube-state-metrics 8.3.0, prometheus-node-exporter 4.56.1,
> prometheus-blackbox-exporter and prometheus-pushgateway. Only `grafana.talos00` survives
> from the URLs below; `prometheus.talos00` and `alertmanager.talos00` are gone
> (Mimir ships its own ruler + Alertmanager, configured via the alertmanager-config pusher).

| Component                      | Version | Status  | Notes                        |
| ------------------------------ | ------- | ------- | ---------------------------- |
| Prometheus                     | 65.8.1  | Running | 30-day retention             |
| Grafana                        | 65.8.1  | Running | grafana.talos00              |
| Alertmanager                   | 65.8.1  | Running | alertmanager.talos00         |
| kube-state-metrics             | 65.8.1  | Running | K8s metrics                  |
| prometheus-node-exporter       | 65.8.1  | Running | Node metrics                 |
| prometheus-blackbox-exporter   | 9.8.0   | Running | Endpoint monitoring          |
| kube-prometheus-stack-operator | 65.8.1  | Running | Manages Prometheus resources |

### Observability Namespace (observability)

> **REMOVED**: the entire OpenSearch + Graylog + MongoDB + Fluent Bit stack was torn down.
> The `observability` namespace still exists but is empty, and
> `infrastructure/base/observability/` is no longer in the repo. Logs are handled by
> Loki (+ Alloy) and ClickStack/HyperDX. An `opensearch-operator` is still installed in
> `opensearch-operator-system`, but not for Graylog.

| Component  | Version | Status  | Notes                  |
| ---------- | ------- | ------- | ---------------------- |
| OpenSearch | 3.3.2   | Running | Log storage            |
| MongoDB    | 18.1.9  | Running | Graylog backend        |
| Graylog    | -       | Running | graylog.talos00        |
| Fluent Bit | 0.48.10 | Running | Log collection (1 pod) |

---

## Phase 6: Arr Stack + Media Servers ✅ COMPLETE

### Deployed Applications (media-dev namespace)

> **Superseded**: `media-dev` was deleted. The equivalent workloads run in `media`
> (jellyfin, plex, prowlarr, radarr, sonarr, qbittorrent, sabnzbd, seerr, tautulli, kometa,
> maintainerr, posterizarr, posterr, pulsarr), `tdarr` (tdarr-server),
> `homepage` (8 homepage instances) and `downloads` (metube, tubesync).
> Overseerr → **Seerr**; the PostgreSQL Deployment → **CloudNativePG**.

| Application | Status  | IngressRoute      | Purpose            |
| ----------- | ------- | ----------------- | ------------------ |
| Prowlarr    | Running | prowlarr.talos00  | Indexer management |
| Sonarr      | Running | sonarr.talos00    | TV show automation |
| Radarr      | Running | radarr.talos00    | Movie automation   |
| Plex        | Running | plex.talos00      | Media server       |
| Jellyfin    | Running | jellyfin.talos00  | Media server (alt) |
| Overseerr   | Running | overseerr.talos00 | Request management |
| Tdarr       | Running | tdarr.talos00     | Transcoding        |
| Homepage    | Running | homepage.talos00  | Dashboard          |
| PostgreSQL  | Running | -                 | Database backend   |

### ✅ Completed Tasks

- [x] Create Prowlarr manifests (deployment, service, PVC, ingressroute)
- [x] Create Sonarr manifests
- [x] Create Radarr manifests
- [x] Create Plex manifests
- [x] Create Jellyfin manifests
- [x] Create Overseerr manifests
- [x] Create Tdarr manifests
- [x] Create Homepage manifests
- [x] Create PostgreSQL manifests
- [x] Create dev overlays
- [x] Deploy to dev environment
- [x] All services accessible via Traefik IngressRoutes

### 🚧 Remaining Configuration Tasks

> **Stale**: this checklist was never updated after the snapshot. The arr stack is
> configured and running; Plex, Jellyfin and Seerr are live. Treat as historical —
> outstanding work lives in beads.

- [ ] Configure Prowlarr indexers
- [ ] Connect Sonarr → Prowlarr
- [ ] Connect Radarr → Prowlarr
- [ ] Test TV show search/download
- [ ] Test movie search/download
- [ ] Configure Plex libraries
- [ ] Configure Jellyfin libraries
- [ ] Compare Plex vs Jellyfin performance
- [ ] Deploy to prod environment (when ready)

---

## Phase 7: Documentation & Finalization 🚧 70% Complete

### Documentation Status

**Comprehensive docs structure with 7 levels:**

- [x] docs/INDEX.md - Master documentation index
- [x] docs/01-getting-started/ - Onboarding guides
- [x] docs/02-architecture/ - System design (dual-gitops, networking, observability)
- [x] docs/03-operations/ - Cluster operations
- [x] docs/04-deployment/ - Deployment guides
- [x] docs/05-projects/ - Project implementations
- [x] docs/06-project-management/ - Tracking and progress
- [x] docs/07-reference/ - Technical references

> **Grown since**: `docs/` also now contains `05-runbooks/`, `06-troubleshooting/`,
> `08-monitoring/`, `changelogs/`, `investigations/`, `patterns/`, `retros/` and `_archive/`.

**Root-level docs:**

- [x] README.md - Main repository overview
- [x] QUICKSTART.md - Quick reference guide
- [x] TRAEFIK.md - Ingress configuration (repo root)
- [x] OBSERVABILITY.md - Monitoring and logging (repo root)
- [x] CLAUDE.md - AI assistant guidance
- [x] IMPLEMENTATION-TRACKER.md - This file

**Remaining documentation:**

- [ ] Plex vs Jellyfin comparison report
- [ ] Backup/restore procedures
- [ ] Troubleshooting guide expansion

### Taskfile Organization

**6 Domain Structure** (counts verified 2026-08-22):

| Taskfile               | Domain    | Tasks | Purpose                          |
| ---------------------- | --------- | ----- | -------------------------------- |
| Taskfile.yaml          | root      | 28    | Common shortcuts + orchestration |
| Taskfile.talos.yaml    | talos:    | 31    | Talos Linux operations           |
| Taskfile.k8s.yaml      | k8s:      | 18    | Kubernetes operations            |
| Taskfile.dev.yaml      | dev:      | 27    | Development tools                |
| Taskfile.infra.yaml    | infra:    | 24    | Infrastructure deployment        |
| Taskfile.security.yaml | security: | 10    | Security scanning / policy ops   |
| Taskfile.certs.yaml    | certs:    | 9     | Certificate operations           |

**Key Tasks:**

```bash
# Common shortcuts
task health              # Cluster health check
task get-pods            # View all pods
task kubeconfig-merge    # Merge kubeconfig

# Domain-specific
task talos:health        # Talos-specific health
task k8s:get-pods        # K8s pod listing
task dev:lint            # Run all linters
task certs:list          # Certificate operations
```

> **Resolved 2026-08-22**: `task infra:deploy-stack` and its `deploy-stack` root shortcut have
> been removed. Infrastructure is reconciled by Flux; there is no stack-deploy script anymore.

### Development Workflow Status

**Tilt Integration (Planned)**:

- Tiltfile exists with full configuration
- Hot-reload support for infrastructure manifests
- Port-forwarding configured for all services
- Flux control resources defined
- **Status**: Configured but not yet integrated into daily workflow

**Dual Deployment Path (Planned)**:

Future structure will have:

1. **deployment.sh scripts** - Mirroring Tiltfile orchestration
2. **Tiltfile** - Hot-reload development
3. Both paths co-located and using same manifest structure

---

## Additional Components Deployed

### External Secrets Operator

- **Namespace**: external-secrets
- **Version**: 0.11.0 — _now chart 2.6.0_
- **Backend**: 1Password Connect — _still the `onepassword` ClusterSecretStore_
- **Status**: Running (3 pods + 1Password Connect) — _still 3 ESO pods + onepassword-connect_
- **Purpose**: Secure secret management from 1Password

### Infrastructure Testing (infra-testing namespace)

> **Renamed** to `infra-control`. Headlamp and Kubeview moved behind the private hostname
> pattern (`headlamp.priv.talos00`, `kubeview.priv.talos00`); Goldilocks and kube-ops-view
> kept their hostnames.

| Tool            | Purpose                        | URL                   |
| --------------- | ------------------------------ | --------------------- |
| Headlamp        | Modern K8s dashboard           | headlamp.talos00      |
| Kubeview        | Cluster visualization          | kubeview.talos00      |
| Kube-ops-view   | Operational cluster view       | kube-ops-view.talos00 |
| Goldilocks      | Resource recommendations       | goldilocks.talos00    |
| VPA Recommender | Vertical Pod Autoscaler engine | -                     |

### Registry

- **Namespace**: registry
- **URL**: registry.talos00
- **Status**: Running — _the backing workload is now **zot**, not Nexus/`registry:2`_
- **Purpose**: Local Docker registry for custom images

### Bastion

> **REMOVED**: the `bastion` namespace no longer exists.

- **Namespace**: bastion
- **Purpose**: SSH bastion host for cluster access

---

## Cluster Health Summary

### Namespaces (17 total)

> **Superseded** (2026-08-22): **62** namespaces. `bastion`, `infra-testing`, `media-dev` and
> `media-prod` are gone; `observability` remains but is empty.

```
argocd, bastion, default, external-secrets, flux-system,
infra-testing, kube-node-lease, kube-public, kube-system,
kubernetes-dashboard, local-path-storage, media-dev,
media-prod, monitoring, observability, registry, traefik
```

### Pod Status (All namespaces)

- **Total Running Pods**: 50+ — _now ~305 Running of ~335 total pods_
- **Failed/Pending**: None
- **Cluster Health**: Healthy

---

## Deployment Scripts

Paths verified 2026-08-22 — several scripts were moved into subdirectories, renamed, or
deleted outright.

| Script                                             | Purpose                               | Status                             |
| -------------------------------------------------- | ------------------------------------- | ---------------------------------- |
| ~~scripts/deploy-stack.sh~~                        | Main infrastructure deployment        | ❌ deleted (Flux reconciles now)   |
| ~~scripts/deploy-observability.sh~~                | Observability stack deployment        | ❌ deleted (stack removed)         |
| scripts/deploy-infra-testing.sh                    | UI tools deployment                   | ⚠️ inert (its manifests were deleted) |
| scripts/\_\_deploy-tdarr.sh                        | Tdarr transcoding deployment          | ⚠️ deprecated (`__` prefix)        |
| scripts/provision.sh                               | Complete cluster provisioning         | ✅                                 |
| scripts/bootstrap-argocd.sh                        | ArgoCD bootstrap                      | ✅                                 |
| scripts/external-secrets/setup-1password-connect.sh | 1Password Connect setup               | ✅ (moved)                         |
| scripts/developer/kubeconfig-merge.sh              | Merge kubeconfig to ~/.kube/config    | ✅ (moved)                         |
| scripts/developer/kubeconfig-unmerge.sh            | Remove kubeconfig from ~/.kube/config | ✅ (moved)                         |
| scripts/kube-dashboard-token.sh                    | Get K8s Dashboard token               | ✅ (renamed)                       |
| scripts/cluster-audit.sh                           | Generate cluster audit report         | ✅                                 |
| ~~scripts/extract-arr-api-keys.sh~~                | Extract API keys from arr apps        | ❌ deleted                         |

---

## Decision Log

**2025-11-09**: Added Both Plex and Jellyfin

- **Why**: User wants to test Jellyfin alongside Plex
- **Benefit**: Can compare performance and features side-by-side

**2025-11-09**: Dual GitOps (Flux + Argo)

- **Flux**: Infrastructure management via HelmReleases
- **ArgoCD**: Available for app management
- **Benefit**: Declarative infrastructure with GitOps

**2025-11-09**: Namespace-based Environments — **REVERSED**

- **Dev + Prod** in same cluster
- **Benefit**: Adequate isolation for multi-node cluster
- **Outcome**: abandoned. `media-dev` / `media-prod` were deleted; media consolidated into a
  single `media` namespace (plus `media-private` / `media-experimental`, which separate
  content and maturity, not environments).

**2025-11-22**: Added External Secrets Operator

- **Why**: Secure secret management
- **Backend**: 1Password Connect
- **Benefit**: Secrets synced from 1Password vaults

**2025-11-22**: Added Infrastructure Testing Tools

- **Components**: Headlamp, Kubeview, Kube-ops-view, Goldilocks, VPA
- **Benefit**: Better cluster visibility and resource optimization

**2025-11-22**: Flux Notifications via Discord

- **Why**: Real-time alerts for infrastructure changes
- **Alerts**: critical-errors, homelab-infrastructure

**2025-11-23**: Added Tdarr for Transcoding

- **Why**: Automated media transcoding and optimization
- **Integration**: Works with Plex/Jellyfin media libraries

**2025-11-24**: Tilt Configuration Added

- **Why**: Hot-reload development workflow
- **Status**: Configured, not yet integrated into daily workflow
- **Future**: Will mirror deployment.sh scripts structure

---

## Known Issues & Workarounds

### Resolved Issues

1. ✅ **Storage Class**: Using `local-path` as default, `nfs` available — _the `nfs` class was
   replaced by `fatboy-nfs-appdata` / `synology-nfs`_
2. ✅ **Control Plane Scheduling**: Working (allows workloads on control plane) —
   **NO LONGER TRUE**: `talos00` now carries the
   `node-role.kubernetes.io/control-plane` taint and four dedicated workers exist
3. ✅ **Graylog Deployment**: Fixed with Recreate strategy — _moot, Graylog removed_
4. ✅ **Prometheus Storage**: Configured with proper retention — _moot, Prometheus replaced
   by Mimir_
5. ✅ **Fluent Bit**: Running but may have collection issues (1 pod) — _moot, Fluent Bit
   replaced by Alloy_

### Current Blockers

None - all core infrastructure operational _(as of the 2025-12-12 snapshot)_

### Known Risks

1. **Backup Important**: Etcd runs on control plane, need good backups — _Velero now covers
   cluster state and CNPG owns Postgres backups_
2. **Resource Usage**: Monitor with Grafana/Goldilocks
3. **SQLite on NFS**: Apps using local-path for configs (correct approach)

---

## Next Actions

> **Historical**: this list was written on 2025-11-24 and was never maintained. All current
> and planned work is tracked in beads (`bd ready`) — do not work from this list.

### Immediate (This Week)

1. Configure Prowlarr indexers
2. Connect Sonarr/Radarr to Prowlarr
3. Configure media libraries in Plex/Jellyfin
4. Test end-to-end media workflow

### Short Term

1. Document backup/restore procedures
2. Set up Homepage with all service widgets
3. Create Grafana dashboards for arr stack
4. Compare Plex vs Jellyfin performance

### Future Considerations

1. Integrate Tilt into daily development workflow
2. Refactor deployment.sh scripts to mirror Tiltfile structure
3. Deploy to media-prod namespace
4. Add more \*arr apps (Readarr, Lidarr, Bazarr)
5. Consider adding download clients (qBittorrent, SABnzbd)
6. External access via Cloudflare Tunnel or similar

---

**Snapshot Written**: 2025-11-24, last extended 2025-12-12
**Last Verified Against Cluster**: 2026-08-22
**Next Review**: As needed — this file is a frozen record, not a living tracker

---

## Related Issues

<!-- Beads tracking for this doc -->
<!-- Historical implementation tracker; ongoing work tracked in beads (`bd ready`). -->
