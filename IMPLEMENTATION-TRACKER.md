# Homelab GitOps + Arr Stack Implementation Tracker

**Project Start**: 2025-11-09
**Last Updated**: 2025-11-24
**Status**: ✅ Phase 6 Complete - Full Stack Operational

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

**Overall Progress**: 96% (24/25 major tasks)

---

## Stack Overview

### Core Infrastructure (DEPLOYED)

- **OS**: Talos Linux v1.11.1
- **Kubernetes**: v1.34.0
- **GitOps (Infra)**: FluxCD v2.7.3 ✅
- **GitOps (Apps)**: ArgoCD v2.x ✅
- **Ingress**: Traefik v3.5.3 ✅
- **Monitoring**: kube-Prometheus-stack v65.8.1 ✅
- **Observability**: OpenSearch + Graylog + Fluent Bit ✅
- **Storage**: local-path (default) + NFS StorageClass ✅
- **Secrets**: External Secrets Operator v0.11.0 + 1Password Connect ✅

### Media Applications (DEPLOYED in media-dev)

- **Indexer Manager**: Prowlarr ✅
- **TV Automation**: Sonarr ✅
- **Movie Automation**: Radarr ✅
- **Media Servers**: Plex ✅ + Jellyfin ✅
- **Request Management**: Overseerr ✅
- **Transcoding**: Tdarr ✅
- **Dashboard**: Homepage ✅
- **Database**: PostgreSQL ✅

### Infrastructure Testing Tools (DEPLOYED)

- **Headlamp** - Modern K8s dashboard ✅
- **Kubeview** - Cluster visualizer ✅
- **Kube-ops-view** - Operational view ✅
- **Goldilocks** - Resource recommendations ✅
- **VPA** - Vertical Pod Autoscaler ✅

### Development Tools

- **Tilt**: Configured (Tiltfile exists) - Not yet integrated into workflow
- **Taskfile**: 90+ tasks across 4 domains (Talos, k8s, dev, infra)

### Environments

- **Dev**: `media-dev` namespace ✅ - All apps deployed
- **Prod**: `media-prod` namespace ✅ - Ready for deployment

---

## Phase 1: Directory Structure ✅ COMPLETE

### ✅ Completed Tasks

- [x] Created bootstrap directories (flux, ArgoCD)
- [x] Created infrastructure directories (base + overlays)
- [x] Created applications/arr-stack structure
- [x] Created base dirs for all apps (prowlarr, sonarr, radarr, plex, jellyfin, overseerr, tdarr, homepage)
- [x] Created namespace manifests
- [x] Created storage provisioner manifests
- [x] Created kube-Prometheus-stack configuration
- [x] Created Flux bootstrap manifests
- [x] Created ArgoCD bootstrap manifests

### Directory Structure (Implemented)

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

**GitRepository Source**: `flux-system` tracking `main@sha1:5a2553ec`

### Active Flux Resources

| Namespace        | Resource Type | Name                            | Version | Status |
| ---------------- | ------------- | ------------------------------- | ------- | ------ |
| flux-system      | GitRepository | flux-system                     | -       | ✅     |
| flux-system      | Kustomization | flux-system                     | -       | ✅     |
| external-secrets | HelmRelease   | external-secrets                | 0.11.0  | ✅     |
| kube-system      | HelmRelease   | nfs-subdir-external-provisioner | 4.0.18  | ✅     |
| monitoring       | HelmRelease   | kube-Prometheus-stack           | 65.8.1  | ✅     |
| monitoring       | HelmRelease   | Prometheus-blackbox-exporter    | 9.8.0   | ✅     |
| observability    | HelmRelease   | fluent-bit                      | 0.48.10 | ✅     |
| observability    | HelmRelease   | mongodb                         | 18.1.9  | ✅     |
| observability    | HelmRelease   | opensearch                      | 3.3.2   | ✅     |

### Flux Notifications

| Resource | Name                   | Target  | Status |
| -------- | ---------------------- | ------- | ------ |
| Provider | discord                | Discord | ✅     |
| Alert    | critical-errors        | Discord | ✅     |
| Alert    | homelab-infrastructure | Discord | ✅     |

### ArgoCD Deployment

- **Namespace**: ArgoCD
- **URL**: ArgoCD.talos00
- **Status**: Running (7 pods)

---

## Phase 3: Multi-Environment Setup ✅ COMPLETE

### ✅ Completed Tasks

- [x] Created `media-dev` namespace
- [x] Created `media-prod` namespace
- [x] Configured Traefik IngressRoutes for all services
- [x] Created dev overlay (\*.talos00 domains)
- [x] Routing working for all applications

### Active IngressRoutes (26 total)

| Namespace            | Service           | URL                   | Status |
| -------------------- | ----------------- | --------------------- | ------ |
| ArgoCD               | ArgoCD            | ArgoCD.talos00        | ✅     |
| monitoring           | Grafana           | Grafana.talos00       | ✅     |
| monitoring           | Prometheus        | Prometheus.talos00    | ✅     |
| monitoring           | Alertmanager      | alertmanager.talos00  | ✅     |
| observability        | Graylog           | graylog.talos00       | ✅     |
| observability        | Grafana           | Grafana.talos00       | ✅     |
| observability        | Prometheus        | Prometheus.talos00    | ✅     |
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
| Kubernetes-dashboard | K8s Dashboard     | dashboard.talos00     | ✅     |
| traefik              | Traefik Dashboard | traefik.talos00       | ✅     |
| default              | whoami-hostname   | whoami.talos00        | ✅     |
| default              | whoami-path       | whoami.talos00/path   | ✅     |
| bastion              | Bastion SSH       | -                     | ✅     |

---

## Phase 4: Storage Setup ✅ COMPLETE

### Storage Classes Available

| Name       | Provisioner                                   | Reclaim Policy | Status  |
| ---------- | --------------------------------------------- | -------------- | ------- |
| local-path | rancher.io/local-path                         | Delete         | Default |
| nfs        | cluster.local/nfs-subdir-external-provisioner | Retain         | ✅      |

### PVCs in media-dev (14 total, All Bound)

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

| Component                      | Version | Status  | Notes                        |
| ------------------------------ | ------- | ------- | ---------------------------- |
| Prometheus                     | 65.8.1  | Running | 30-day retention             |
| Grafana                        | 65.8.1  | Running | Grafana.talos00              |
| Alertmanager                   | 65.8.1  | Running | alertmanager.talos00         |
| kube-state-metrics             | 65.8.1  | Running | K8s metrics                  |
| Prometheus-node-exporter       | 65.8.1  | Running | Node metrics                 |
| Prometheus-blackbox-exporter   | 9.8.0   | Running | Endpoint monitoring          |
| kube-Prometheus-stack-operator | 65.8.1  | Running | Manages Prometheus resources |

### Observability Namespace (observability)

| Component  | Version | Status  | Notes                  |
| ---------- | ------- | ------- | ---------------------- |
| OpenSearch | 3.3.2   | Running | Log storage            |
| MongoDB    | 18.1.9  | Running | Graylog backend        |
| Graylog    | -       | Running | graylog.talos00        |
| Fluent Bit | 0.48.10 | Running | Log collection (1 pod) |

---

## Phase 6: Arr Stack + Media Servers ✅ COMPLETE

### Deployed Applications (media-dev namespace)

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

**Root-level docs:**

- [x] README.md - Main repository overview
- [x] QUICKSTART.md - Quick reference guide
- [x] TRAEFIK.md - Ingress configuration (in docs/)
- [x] OBSERVABILITY.md - Monitoring and logging (in docs/)
- [x] CLAUDE.md - AI assistant guidance
- [x] IMPLEMENTATION-TRACKER.md - This file

**Remaining documentation:**

- [ ] Plex vs Jellyfin comparison report
- [ ] Backup/restore procedures
- [ ] Troubleshooting guide expansion

### Taskfile Organization

**4 Domain Structure:**

| Taskfile            | Domain | Tasks | Purpose                   |
| ------------------- | ------ | ----- | ------------------------- |
| Taskfile.YAML       | Root   | 20+   | Common shortcuts          |
| Taskfile.Talos.YAML | Talos: | 33    | Talos Linux operations    |
| Taskfile.k8s.YAML   | k8s:   | 18    | Kubernetes operations     |
| Taskfile.dev.YAML   | dev:   | 17    | Development tools         |
| Taskfile.infra.YAML | infra: | 22    | Infrastructure deployment |

**Key Tasks:**

```bash
# Common shortcuts
task health              # Cluster health check
task get-pods            # View all pods
task kubeconfig-merge    # Merge kubeconfig
task deploy-stack        # Deploy infrastructure

# Domain-specific
task talos:health        # Talos-specific health
task k8s:get-pods        # K8s pod listing
task dev:lint            # Run all linters
task infra:deploy-stack  # Deploy full stack
```

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
- **Version**: 0.11.0
- **Backend**: 1Password Connect
- **Status**: Running (3 pods + 1Password Connect)
- **Purpose**: Secure secret management from 1Password

### Infrastructure Testing (infra-testing namespace)

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
- **Status**: Running
- **Purpose**: Local Docker registry for custom images

### Bastion

- **Namespace**: bastion
- **Purpose**: SSH bastion host for cluster access

---

## Cluster Health Summary

### Namespaces (17 total)

```
argocd, bastion, default, external-secrets, flux-system,
infra-testing, kube-node-lease, kube-public, kube-system,
kubernetes-dashboard, local-path-storage, media-dev,
media-prod, monitoring, observability, registry, traefik
```

### Pod Status (All namespaces)

- **Total Running Pods**: 50+
- **Failed/Pending**: None
- **Cluster Health**: Healthy

---

## Deployment Scripts

| Script                          | Purpose                               | Status |
| ------------------------------- | ------------------------------------- | ------ |
| scripts/deploy-stack.sh         | Main infrastructure deployment        | ✅     |
| scripts/deploy-observability.sh | Observability stack deployment        | ✅     |
| scripts/deploy-infra-testing.sh | UI tools deployment                   | ✅     |
| scripts/deploy-tdarr.sh         | Tdarr transcoding deployment          | ✅     |
| scripts/provision.sh            | Complete cluster provisioning         | ✅     |
| scripts/bootstrap-ArgoCD.sh     | ArgoCD bootstrap                      | ✅     |
| scripts/setup-1password-connect | 1Password Connect setup               | ✅     |
| scripts/kubeconfig-merge.sh     | Merge kubeconfig to ~/.kube/config    | ✅     |
| scripts/kubeconfig-unmerge.sh   | Remove kubeconfig from ~/.kube/config | ✅     |
| scripts/dashboard-token.sh      | Get K8s Dashboard token               | ✅     |
| scripts/cluster-audit.sh        | Generate cluster audit report         | ✅     |
| scripts/extract-arr-api-keys.sh | Extract API keys from arr apps        | ✅     |

---

## Decision Log

**2025-11-09**: Added Both Plex and Jellyfin

- **Why**: User wants to test Jellyfin alongside Plex
- **Benefit**: Can compare performance and features side-by-side

**2025-11-09**: Dual GitOps (Flux + Argo)

- **Flux**: Infrastructure management via HelmReleases
- **ArgoCD**: Available for app management
- **Benefit**: Declarative infrastructure with GitOps

**2025-11-09**: Namespace-based Environments

- **Dev + Prod** in same cluster
- **Benefit**: Adequate isolation for multi-node cluster

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

1. ✅ **Storage Class**: Using `local-path` as default, `nfs` available
2. ✅ **Control Plane Scheduling**: Working (allows workloads on control plane)
3. ✅ **Graylog Deployment**: Fixed with Recreate strategy
4. ✅ **Prometheus Storage**: Configured with proper retention
5. ✅ **Fluent Bit**: Running but may have collection issues (1 pod)

### Current Blockers

None - all core infrastructure operational

### Known Risks

1. **Backup Important**: Etcd runs on control plane, need good backups
2. **Resource Usage**: Monitor with Grafana/Goldilocks
3. **SQLite on NFS**: Apps using local-path for configs (correct approach)

---

## Next Actions

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

**Last Updated**: 2025-11-24
**Next Review**: As needed
