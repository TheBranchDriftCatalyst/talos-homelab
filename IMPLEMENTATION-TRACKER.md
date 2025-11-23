# Homelab GitOps + Arr Stack Implementation Tracker

**Project Start**: 2025-11-09
**Target Completion**: 6 weeks
**Status**: 🚧 Phase 1 - Directory Structure Created

---

## Quick Status

| Phase                              | Status         | Progress |
| ---------------------------------- | -------------- | -------- |
| Phase 1: Directory Structure       | 🚧 IN PROGRESS | 25%      |
| Phase 2: GitOps Foundation         | ⏸️ PENDING     | 0%       |
| Phase 3: Multi-Environment         | ⏸️ PENDING     | 0%       |
| Phase 4: Storage Setup             | ⏸️ PENDING     | 0%       |
| Phase 5: Monitoring Stack          | ⏸️ PENDING     | 0%       |
| Phase 6: Arr Stack + Media Servers | ⏸️ PENDING     | 0%       |
| Phase 7: Finalize & Document       | ⏸️ PENDING     | 0%       |

**Overall Progress**: 4% (1/25 major tasks)

---

## Stack Overview

### Core Infrastructure

- **OS**: Talos Linux v1.11.1
- **Kubernetes**: v1.34.0
- **GitOps (Infra)**: FluxCD v2.x
- **GitOps (Apps)**: ArgoCD v2.x
- **Ingress**: Traefik v3.5.3
- **Monitoring**: kube-Prometheus-stack
- **Storage**: Synology NFS + local-path-provisioner

### Media Applications

- **Indexer Manager**: Prowlarr
- **TV Automation**: Sonarr
- **Movie Automation**: Radarr
- **Media Servers**: **Plex** (primary) + **Jellyfin** (testing/comparison)

### Environments

- **Dev**: `media-dev` namespace, `*.dev.lab` domains
- **Prod**: `media-prod` namespace, `*.lab` domains

---

## Phase 1: Directory Structure ✅ 25% Complete

### ✅ Completed Tasks

- [x] Created bootstrap directories (flux, ArgoCD)
- [x] Created infrastructure directories (base + overlays)
- [x] Created applications/arr-stack structure
- [x] Created base dirs for all apps (prowlarr, sonarr, radarr, plex, jellyfin)

### 🚧 In Progress

- [ ] Create namespace manifests
- [ ] Create storage provisioner manifests
- [ ] Create kube-Prometheus-stack configuration
- [ ] Create Flux bootstrap manifests
- [ ] Create ArgoCD bootstrap manifests

### Directory Structure

```
talos-fix/
├── bootstrap/
│   ├── flux/                    # FluxCD installation
│   └── argocd/                  # ArgoCD installation
├── infrastructure/               # Managed by Flux
│   ├── base/
│   │   ├── namespaces/          # media-dev, media-prod
│   │   ├── storage/             # NFS + local-path
│   │   ├── traefik/             # Ingress controller
│   │   ├── cert-manager/        # TLS certificates
│   │   └── monitoring/
│   │       └── kube-prometheus-stack/
│   └── overlays/
│       ├── dev/                 # Dev environment patches
│       └── prod/                # Prod environment patches
├── applications/                 # Managed by ArgoCD
│   └── arr-stack/
│       ├── base/
│       │   ├── prowlarr/        # Indexer manager
│       │   ├── sonarr/          # TV automation
│       │   ├── radarr/          # Movie automation
│       │   ├── plex/            # Media server (primary)
│       │   └── jellyfin/        # Media server (testing)
│       └── overlays/
│           ├── dev/
│           └── prod/
├── clusters/homelab-single/
├── argocd-apps/
└── docs/
```

---

## Phase 2: GitOps Foundation (Week 2)

### Goals

- Install FluxCD
- Install ArgoCD via Flux
- Deploy storage provisioners
- Migrate Traefik to Flux management

### Tasks

- [ ] Write `bootstrap-flux.sh` script
- [ ] Create Flux bootstrap manifests
- [ ] Install Flux to cluster
- [ ] Create GitRepository source
- [ ] Deploy NFS StorageClass
- [ ] Deploy local-path-provisioner
- [ ] Create ArgoCD Helm release (via Flux)
- [ ] Deploy ArgoCD
- [ ] Access ArgoCD UI
- [ ] Create root App-of-Apps

---

## Phase 3: Multi-Environment Setup (Week 3)

### Goals

- Create dev/prod namespaces
- Configure environment-specific routing
- Set up Kustomize overlays

### Tasks

- [ ] Create `media-dev` namespace with resource quotas
- [ ] Create `media-prod` namespace with resource quotas
- [ ] Configure Traefik for multi-env routing
- [ ] Create dev overlay (\*.dev.lab domains)
- [ ] Create prod overlay (\*.lab domains)
- [ ] Test routing isolation

---

## Phase 4: Storage Setup (Week 3)

### Synology NFS Configuration

```
/volume1/media/           # RWX - Shared media library
├── tv/                   # TV shows
├── movies/               # Movies
└── music/                # Music

/volume1/downloads/       # RWX - Download client
├── complete/             # Finished downloads
└── incomplete/           # In-progress downloads
```

### Local Storage (SQLite - MUST be local, not NFS)

- Prowlarr config: 5Gi RWO
- Sonarr config: 10Gi RWO
- Radarr config: 10Gi RWO
- Plex metadata: 20Gi RWO
- Jellyfin config: 10Gi RWO

### Tasks

- [ ] Configure Synology NFS shares
- [ ] Create NFS StorageClass manifest
- [ ] Deploy local-path-provisioner
- [ ] Test NFS PVC provisioning
- [ ] Test local-path PVC provisioning
- [ ] Create PVC templates for all apps

---

## Phase 5: Monitoring Stack (Week 4)

### kube-Prometheus-stack Components

- Prometheus Operator
- Prometheus (metrics collection)
- Alertmanager (alert routing)
- Grafana (visualization)
- node-exporter (node metrics)
- kube-state-metrics (K8s metrics)

### Tasks

- [ ] Create kube-Prometheus-stack HelmRelease
- [ ] Configure Prometheus storage (20Gi PVC)
- [ ] Configure Grafana admin password
- [ ] Create IngressRoutes (Grafana.dev.lab, Prometheus.dev.lab)
- [ ] Import arr stack dashboards
- [ ] Create custom dashboards for Plex/Jellyfin comparison
- [ ] Configure ServiceMonitors for arr apps
- [ ] Test metrics collection

---

## Phase 6: Arr Stack + Media Servers (Week 4-5)

### Deployment Order

1. **Prowlarr** (indexer manager) - Deploy first
2. **Sonarr** (TV) - Connect to Prowlarr
3. **Radarr** (Movies) - Connect to Prowlarr
4. **Plex** (primary media server)
5. **Jellyfin** (comparison/testing)

### Media Server Comparison Goals

- Side-by-side performance testing
- UI/UX comparison
- Resource usage monitoring (Grafana dashboards)
- Transcoding performance
- Mobile app experience
- Choose primary server after testing

### IngressRoutes

**Dev Environment**:

- `prowlarr.dev.lab` → Prowlarr
- `sonarr.dev.lab` → Sonarr
- `radarr.dev.lab` → Radarr
- `plex.dev.lab` → Plex
- `jellyfin.dev.lab` → Jellyfin

**Prod Environment**:

- `prowlarr.lab` → Prowlarr
- `sonarr.lab` → Sonarr
- `radarr.lab` → Radarr
- `plex.lab` → Plex
- `jellyfin.lab` → Jellyfin

### Tasks

- [ ] Create Prowlarr manifests (deployment, service, PVC, ingressroute)
- [ ] Create Sonarr manifests
- [ ] Create Radarr manifests
- [ ] Create Plex manifests
- [ ] Create Jellyfin manifests
- [ ] Create dev/prod overlays
- [ ] Deploy to dev environment
- [ ] Configure Prowlarr indexers
- [ ] Connect Sonarr → Prowlarr
- [ ] Connect Radarr → Prowlarr
- [ ] Test TV show search/download
- [ ] Test movie search/download
- [ ] Verify media in both Plex and Jellyfin
- [ ] Compare Plex vs Jellyfin performance
- [ ] Deploy to prod environment

---

## Phase 7: Documentation & Finalization (Week 6)

### Documentation

- [ ] Architecture diagram
- [ ] Plex vs Jellyfin comparison report
- [ ] Deployment procedures
- [ ] Troubleshooting guide
- [ ] Backup/restore procedures

### Taskfile Commands

```bash
# GitOps
task bootstrap-flux
task bootstrap-argocd
task sync-flux
task sync-argocd

# Storage
task setup-storage
task test-storage

# Arr Stack
task deploy-arr-dev
task deploy-arr-prod

# Monitoring
task grafana-ui
task prometheus-ui

# Media Servers
task plex-ui
task jellyfin-ui
```

---

## Environment Configuration

### Dev Environment (`media-dev`)

- **Namespace**: `media-dev`
- **Domains**: `*.dev.lab`
- **Resources**: Lower limits for testing
- **Logging**: DEBUG level
- **Purpose**: Testing new configurations

### Prod Environment (`media-prod`)

- **Namespace**: `media-prod`
- **Domains**: `*.lab`
- **Resources**: Higher limits for performance
- **Logging**: INFO level
- **Purpose**: Stable media consumption

---

## Plex vs Jellyfin Comparison

### Will Track

- **Performance**: Response time, load time
- **Resource Usage**: CPU, memory (monitored in Grafana)
- **Transcoding**: Quality, speed, format support
- **Features**: Mobile apps, sharing, user management
- **UI/UX**: Ease of use, aesthetics
- **Stability**: Uptime, crashes

### Both Share Same

- Media library (Synology NFS `/volume1/media`)
- Same hardware resources
- Same network configuration

### Decision Point

After 2-4 weeks of testing, choose primary server:

- Keep both if needed
- Or standardize on one
- Track decision in this document

---

## Storage Architecture

```
┌─────────────────────────────────────────────┐
│           Synology NAS (NFS)                │
│  /volume1/media (RWX) - Shared by all      │
│  /volume1/downloads (RWX) - Shared by all  │
└─────────────────────────────────────────────┘
                    ↓ NFS Mount
┌─────────────────────────────────────────────┐
│         Kubernetes Cluster (Talos)          │
│                                             │
│  ┌─────────────────────────────────────┐  │
│  │  Apps with SQLite (Local Storage)   │  │
│  │  - Prowlarr config (5Gi RWO)        │  │
│  │  - Sonarr config (10Gi RWO)         │  │
│  │  - Radarr config (10Gi RWO)         │  │
│  │  - Plex metadata (20Gi RWO)         │  │
│  │  - Jellyfin config (10Gi RWO)       │  │
│  └─────────────────────────────────────┘  │
│                                             │
│  All apps mount NFS for media/downloads    │
└─────────────────────────────────────────────┘
```

---

## Testing Checklist

### Infrastructure

- [ ] Flux reconciles automatically
- [ ] ArgoCD syncs applications
- [ ] Traefik routes correctly to both envs
- [ ] NFS volumes mount successfully
- [ ] Local volumes provision correctly
- [ ] Prometheus collects metrics
- [ ] Grafana displays dashboards

### Arr Stack

- [ ] Prowlarr indexers working
- [ ] Sonarr finds TV shows
- [ ] Radarr finds movies
- [ ] Downloads complete successfully
- [ ] Media files organized correctly

### Media Servers

- [ ] Plex discovers media library
- [ ] Jellyfin discovers media library
- [ ] Both can stream without buffering
- [ ] Transcoding works (if needed)
- [ ] Mobile apps work (if testing)
- [ ] Remote access configured (optional)

---

## Next Actions

### This Week (Phase 1)

1. ✅ Create directory structure
2. Create namespace manifests
3. Create storage manifests
4. Create Flux bootstrap files
5. Create ArgoCD bootstrap files

### Next Week (Phase 2)

1. Install FluxCD
2. Deploy storage provisioners
3. Install ArgoCD
4. Test GitOps workflows

---

## Decision Log

**2025-11-09**: Added Both Plex and Jellyfin

- **Why**: User wants to test Jellyfin alongside Plex
- **Benefit**: Can compare performance and features side-by-side
- **Resource Impact**: ~2-4GB additional memory for second server
- **Monitoring**: Will track resource usage in Grafana to compare

**2025-11-09**: Dual GitOps (Flux + Argo)

- **Flux**: Infrastructure management (storage, traefik, monitoring)
- **ArgoCD**: Application management (arr stack, media servers)
- **Benefit**: Clean separation, better UI for apps

**2025-11-09**: Namespace-based Environments

- **Dev + Prod** in same cluster
- **Benefit**: Simpler for single-node, adequate isolation

---

## Issues & Blockers

### Current Blockers

None

### Known Risks

1. **SQLite on NFS**: Must use local storage for configs
2. **Single-Node**: No HA, need good backups
3. **Resource Usage**: Plex + Jellyfin + Monitoring may be heavy

---

**Last Updated**: 2025-11-09 16:05 PST
**Next Review**: Daily during Phase 1-2
