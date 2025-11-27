# Project TODO & Status Tracker

**Central tracking for all subsystems, projects, and infrastructure components**

Last Updated: 2025-11-24

---

## 📊 System-Wide Status Overview

| Subsystem                               | Status         | Health         | Priority | Owner          |
| --------------------------------------- | -------------- | -------------- | -------- | -------------- |
| [FluxCD](#fluxcd)                       | ✅ Deployed    | 🟢 Healthy     | High     | Infrastructure |
| [ArgoCD](#argocd)                       | ✅ Deployed    | 🟢 Healthy     | High     | Infrastructure |
| [Traefik](#traefik)                     | ✅ Deployed    | 🟢 Healthy     | High     | Infrastructure |
| [Registry](#registry)                   | ✅ Deployed    | 🟢 Healthy     | Medium   | Infrastructure |
| [Monitoring](#monitoring)               | ✅ Deployed    | 🟢 Healthy     | High     | Infrastructure |
| [Observability](#observability)         | ✅ Deployed    | 🟢 Healthy     | Medium   | Infrastructure |
| [External Secrets](#external-secrets)   | ✅ Deployed    | 🟢 Healthy     | High     | Infrastructure |
| [Media Stack](#media-stack)             | ✅ Deployed    | 🟢 Healthy     | Medium   | Application    |
| [Infra Testing](#infra-testing)         | ✅ Deployed    | 🟢 Healthy     | Low      | Infrastructure |
| [Catalyst UI](#catalyst-ui)             | 🟡 In Progress | 🟡 Testing     | Medium   | Application    |
| [Catalyst DNS Sync](#catalyst-dns-sync) | 🟡 In Progress | 🔵 Development | High     | Application    |
| [Tilt Integration](#tilt-integration)   | 🟡 Configured  | 🔵 Not Active  | Medium   | Development    |

**Legend:**

- Status: ✅ Deployed | 🟡 In Progress | 🔴 Not Started
- Health: 🟢 Healthy | 🟡 Degraded | 🔴 Down | 🔵 Dev | ⚪ N/A

---

## 🎯 High-Priority TODOs

### Critical Path Items

- [ ] **Complete Catalyst DNS Sync MVP Phase 1**
  - Status: 70% complete
  - Remaining: Web UI, metrics endpoint
  - See: [catalyst-dns-sync/STATUS.md](catalyst-dns-sync/STATUS.md)

- [ ] **Configure Media Stack Applications**
  - Status: Deployed, needs app configuration
  - Remaining: Prowlarr indexers, Sonarr/Radarr connections, media libraries
  - Apps: Prowlarr, Sonarr, Radarr, Plex, Jellyfin, Overseerr, Tdarr

- [ ] **Integrate Tilt into daily workflow**
  - Status: Tiltfile configured, not yet used
  - Plan: Will mirror deployment.sh scripts structure

### Important But Not Blocking

- [ ] **Standardize domain naming** (.lab vs .talos00)
- [ ] **Add HTTPS/TLS to Traefik** (currently HTTP only)
- [ ] **Implement backup strategy** for etcd and PVCs
- [ ] **Complete Plex vs Jellyfin comparison**
- [ ] **Set up Homepage dashboard** with all service widgets

---

## 📦 Subsystem Status Details

### FluxCD

**Location:** `bootstrap/flux/`, `flux-system` namespace
**Status:** ✅ Deployed & Operational
**Version:** v2.7.3 (flux-v2.7.3 distribution)

**Current State:**

- ✅ All controllers running (helm, kustomize, notification, source)
- ✅ GitRepository: flux-system tracking main branch
- ✅ Discord notifications configured (critical-errors, homelab-infrastructure)
- ✅ Managing infrastructure via HelmReleases

**Managed HelmReleases:**

| Namespace        | Release                         | Version | Status |
| ---------------- | ------------------------------- | ------- | ------ |
| external-secrets | external-secrets                | 0.11.0  | ✅     |
| kube-system      | nfs-subdir-external-provisioner | 4.0.18  | ✅     |
| monitoring       | kube-Prometheus-stack           | 65.8.1  | ✅     |
| monitoring       | Prometheus-blackbox-exporter    | 9.8.0   | ✅     |
| observability    | fluent-bit                      | 0.48.10 | ✅     |
| observability    | mongodb                         | 18.1.9  | ✅     |
| observability    | opensearch                      | 3.3.2   | ✅     |

**TODOs:**

- [x] Push repository to GitHub
- [x] Bootstrap FluxCD
- [x] Configure Discord notifications
- [ ] Add additional alerts for specific failure conditions
- [ ] Document Flux reconciliation workflow

**See:** [bootstrap/flux/README.md](bootstrap/flux/README.md)

---

### ArgoCD

**Location:** `infrastructure/base/argocd/`
**Status:** ✅ Deployed & Operational

**Current State:**

- Version: Latest (Helm chart)
- Access: http://argocd.talos00
- Pods: 7 running
- Applications: Available for app management

**TODOs:**

- [ ] Configure HTTPS ingress
- [ ] Set up SSO/OIDC authentication
- [ ] Add backup schedule for ArgoCD configs
- [ ] Document application creation workflow
- [ ] Deploy applications via ArgoCD (currently manual)

**See:** [infrastructure/base/ArgoCD/STATUS.md](infrastructure/base/argocd/STATUS.md)

---

### Traefik

**Location:** `infrastructure/base/traefik/`
**Status:** ✅ Deployed & Operational

**Current State:**

- Version: v3.x
- IngressRoutes: 26+ services accessible
- Middleware: Basic auth configured
- Cert Manager: Not deployed

**TODOs:**

- [ ] Implement HTTPS with cert-manager
- [ ] Add rate limiting middleware
- [ ] Configure Let's Encrypt certificates
- [ ] Add access logs to observability stack

**See:** [infrastructure/base/traefik/STATUS.md](infrastructure/base/traefik/STATUS.md)

---

### Registry

**Location:** `infrastructure/base/registry/`
**Status:** ✅ Deployed & Operational

**Current State:**

- Storage: 50Gi PVC
- Access: http://registry.talos00
- Push: Working via port-forward

**TODOs:**

- [ ] Implement authentication (Docker-registry supports basic auth)
- [ ] Add HTTPS support
- [ ] Create automated image cleanup job

**See:** [infrastructure/base/registry/STATUS.md](infrastructure/base/registry/STATUS.md)

---

### Monitoring

**Location:** `infrastructure/base/monitoring/`
**Status:** ✅ Deployed & Operational (Managed by FluxCD)

**Current State:**

- Prometheus: ✅ Running (v65.8.1, 30-day retention)
- Grafana: ✅ Running (http://grafana.talos00)
- Alertmanager: ✅ Running (http://alertmanager.talos00)
- Blackbox Exporter: ✅ Running (v9.8.0)
- Node Exporter: ✅ Running
- kube-state-metrics: ✅ Running

**TODOs:**

- [ ] Deploy Exportarr for \*arr stack metrics
- [ ] Configure Alertmanager notifications (Slack/Email)
- [ ] Add custom dashboards for Talos metrics
- [ ] Create arr stack Grafana dashboards

**See:** [infrastructure/base/monitoring/STATUS.md](infrastructure/base/monitoring/STATUS.md)

---

### Observability

**Location:** `infrastructure/base/observability/`
**Status:** ✅ Deployed & Operational (Managed by FluxCD)

**Current State:**

- OpenSearch: ✅ Running (v3.3.2, 30Gi storage)
- Graylog: ✅ Running (http://graylog.talos00)
- MongoDB: ✅ Running (v18.1.9, Graylog backend)
- Fluent Bit: ✅ Running (v0.48.10, log collection)

**TODOs:**

- [ ] Configure Graylog inputs and streams
- [ ] Add index lifecycle policies
- [ ] Integrate with Alertmanager
- [ ] Add log retention automation

**See:** [infrastructure/base/observability/STATUS.md](infrastructure/base/observability/STATUS.md)

---

### External Secrets

**Location:** `infrastructure/base/external-secrets/`
**Status:** ✅ Deployed & Operational (Managed by FluxCD)

**Current State:**

- ESO Version: 0.11.0
- Backend: 1Password Connect
- Pods: 3 ESO pods + 1Password Connect (2 containers)

**TODOs:**

- [ ] Document ExternalSecret creation workflow
- [ ] Add more secrets from 1Password
- [ ] Set up secret rotation policies

---

### Media Stack

**Location:** `applications/arr-stack/`
**Status:** ✅ Deployed (media-dev namespace)

**Deployed Applications:**

| Application | Status  | URL               | Purpose            |
| ----------- | ------- | ----------------- | ------------------ |
| Prowlarr    | Running | prowlarr.talos00  | Indexer management |
| Sonarr      | Running | sonarr.talos00    | TV automation      |
| Radarr      | Running | radarr.talos00    | Movie automation   |
| Plex        | Running | plex.talos00      | Media server       |
| Jellyfin    | Running | jellyfin.talos00  | Media server (alt) |
| Overseerr   | Running | overseerr.talos00 | Request management |
| Tdarr       | Running | tdarr.talos00     | Transcoding        |
| Homepage    | Running | homepage.talos00  | Dashboard          |
| PostgreSQL  | Running | -                 | Database backend   |

**Configuration TODOs:**

- [ ] Configure Prowlarr indexers
- [ ] Connect Sonarr → Prowlarr
- [ ] Connect Radarr → Prowlarr
- [ ] Test TV show search/download
- [ ] Test movie search/download
- [ ] Configure Plex libraries
- [ ] Configure Jellyfin libraries
- [ ] Set up Homepage widgets for all services
- [ ] Compare Plex vs Jellyfin performance
- [ ] Deploy to media-prod namespace (when ready)

**See:** [applications/arr-stack/STATUS.md](applications/arr-stack/STATUS.md)

---

### Infra Testing

**Location:** `infrastructure/base/infra-testing/`
**Status:** ✅ Deployed & Operational

**Deployed Tools:**

| Tool            | URL                   | Purpose                  |
| --------------- | --------------------- | ------------------------ |
| Headlamp        | headlamp.talos00      | Modern K8s dashboard     |
| Kubeview        | kubeview.talos00      | Cluster visualization    |
| Kube-ops-view   | kube-ops-view.talos00 | Operational view         |
| Goldilocks      | goldilocks.talos00    | Resource recommendations |
| VPA Recommender | -                     | Vertical Pod Autoscaler  |

**TODOs:**

- [ ] Use Goldilocks recommendations to optimize resource requests/limits
- [ ] Document UI tool usage

---

### Tilt Integration

**Location:** `Tiltfile`, `docs/tilt-development-workflow.md`
**Status:** 🟡 Configured (Not Active)

**Current State:**

- Tiltfile: ✅ Created with full configuration
- Hot-reload: ✅ Configured for infrastructure manifests
- Port-forwards: ✅ Defined for all services
- Flux control: ✅ Manual triggers available
- **Usage**: Not yet integrated into daily workflow

**Features Available:**

- Hot-reload for infrastructure/base/\* manifests
- Automatic port-forwards (Headlamp:8080, Kubeview:8081, etc.)
- Flux control (suspend/resume/reconcile)
- Quick deployment actions
- Manifest validation

**TODOs:**

- [ ] Start using Tilt for development workflow
- [ ] Refactor deployment.sh scripts to mirror Tiltfile structure
- [ ] Create dual deployment path documentation
- [ ] Test hot-reload workflow with infrastructure changes

**See:** [docs/tilt-development-workflow.md](docs/tilt-development-workflow.md)

---

### Catalyst UI

**Location:** `~/catalyst-devspace/workspace/catalyst-ui`
**Infrastructure:** `infrastructure/base/argocd/applications/catalyst-ui.yaml`
**Status:** 🟡 In Progress

**Current State:**

- Dockerfile: ✅ Created & tested
- K8s Manifests: ✅ Created (k8s/)
- ArgoCD Application: ✅ Defined
- Image Push: ✅ Works via port-forward

**TODOs:**

- [ ] Push catalyst-ui image to registry
- [ ] Sync ArgoCD application
- [ ] Verify application accessibility at http://catalyst.talos00
- [ ] Set up CI/CD pipeline for auto-builds

**See:** [docs/05-projects/catalyst-ui/deployment-guide.md](docs/05-projects/catalyst-ui/deployment-guide.md)

---

### Catalyst DNS Sync

**Location:** `catalyst-dns-sync/`
**Status:** 🟡 In Progress (Phase 1: 70% complete)

**Current State:**

- Core CRUD: ✅ Implemented
- CLI: ✅ Working (dev-mode)
- Metrics: 🟡 Partial
- Health Checks: ✅ Implemented
- Web UI: 🔴 Not started (Phase 2)

**Phase 1 MVP Checklist:**

- [x] DNS record create/read/update/delete
- [x] Technitium API integration
- [x] Dev mode (manual sync)
- [x] CLI commands
- [x] Health check endpoint
- [ ] Prometheus metrics endpoint
- [ ] Complete unit tests
- [ ] Complete integration tests

**Phase 2 Checklist:**

- [ ] Web UI (React/Vue/Svelte)
- [ ] Automatic K8s reconciliation loop
- [ ] Kubernetes deployment manifests
- [ ] ArgoCD application definition

**See:**

- [catalyst-dns-sync/STATUS.md](catalyst-dns-sync/STATUS.md)
- [docs/05-projects/catalyst-dns-sync/mvp.md](docs/05-projects/catalyst-dns-sync/mvp.md)

---

## 📋 Documentation TODOs

### High Priority

- [ ] Complete Plex vs Jellyfin comparison report
- [ ] Document backup/restore procedures
- [ ] Expand troubleshooting guides

### Medium Priority

- [ ] Add Mermaid diagrams for architecture
- [ ] Create troubleshooting decision tree
- [ ] Document Tilt development workflow best practices

### Low Priority

- [ ] Generate automated API documentation
- [ ] Create video walkthroughs
- [ ] Add FAQ document

**See:** [docs/INDEX.md](docs/INDEX.md) for complete documentation structure

---

## 🔄 Infrastructure Improvements

### Planned Enhancements

- [ ] Implement etcd backup automation
- [ ] Add PVC snapshot capabilities
- [ ] Configure network policies for isolation
- [ ] Implement pod security policies
- [ ] Add resource quotas per namespace
- [ ] Create disaster recovery runbook

### Future Considerations

- [ ] Multi-node cluster expansion
- [ ] High availability setup
- [ ] Service mesh evaluation (Istio/Linkerd)
- [ ] External access via Cloudflare Tunnel
- [ ] Add download clients (qBittorrent, SABnzbd)
- [ ] Add more \*arr apps (Readarr, Lidarr, Bazarr)

---

## 📈 Project Management

### Current Sprint (Week of 2025-11-24)

1. **Configure media stack applications** ⏳ In Progress
2. **Set up Homepage dashboard** ⏳ Pending
3. **Integrate Tilt workflow** ⏳ Pending
4. **Finish catalyst-dns-sync MVP** ⏳ In Progress

### Next Sprint

1. Implement HTTPS/TLS
2. Set up monitoring alerts
3. Create Grafana dashboards for arr stack
4. Deploy to media-prod namespace

### Completed Recently

- ✅ FluxCD deployment and configuration
- ✅ External Secrets Operator with 1Password Connect
- ✅ Media stack deployment (all 9 apps)
- ✅ Infrastructure testing tools (Headlamp, Kubeview, etc.)
- ✅ Tdarr transcoding service
- ✅ Flux Discord notifications
- ✅ NFS storage class via Flux HelmRelease
- ✅ Prometheus blackbox exporter
- ✅ Documentation reorganization (7-level structure)
- ✅ Taskfile refactoring (4 domains)
- ✅ Tiltfile configuration

---

## 🎯 Success Criteria

### Infrastructure

- ✅ Cluster provisioned and stable
- ✅ Dual GitOps tooling deployed (Flux + ArgoCD)
- ✅ All infrastructure services healthy
- ✅ External Secrets with 1Password
- ✅ Monitoring stack operational
- ✅ Observability stack operational
- 🔴 HTTPS enabled across all services
- 🟡 Monitoring alerts configured (Discord working)

### Applications

- ✅ Media stack deployed (media-dev)
- 🟡 Media stack configured (needs app setup)
- 🟡 Catalyst UI deployed via ArgoCD
- 🟡 Catalyst DNS Sync MVP complete

### Documentation

- ✅ Progressive documentation structure (7 levels)
- ✅ Implementation tracker updated
- 🟡 All subsystems have STATUS.md
- 🔴 Troubleshooting guides complete

---

## 📞 Quick Links

- **Main Index:** [docs/INDEX.md](docs/INDEX.md)
- **Implementation Tracker:** [IMPLEMENTATION-TRACKER.md](IMPLEMENTATION-TRACKER.md)
- **Progress Summary:** [docs/06-project-management/progress-summary.md](docs/06-project-management/progress-summary.md)
- **Dual GitOps Architecture:** [docs/02-architecture/dual-gitops.md](docs/02-architecture/dual-gitops.md)
- **Tilt Workflow:** [docs/tilt-development-workflow.md](docs/tilt-development-workflow.md)

---

**Maintenance Schedule:**

- **Daily:** Update individual subsystem STATUS.md files
- **Weekly:** Review high-priority TODOs, update sprint progress
- **Monthly:** Full system health check, update all statuses

**How to Update:**

1. Update subsystem STATUS.md when making changes
2. Update this TODO.md for cross-cutting concerns
3. Update Progress Summary for completed work
4. Update Implementation Tracker for phase completions
