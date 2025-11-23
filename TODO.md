# Project TODO & Status Tracker

**Central tracking for all subsystems, projects, and infrastructure components**

Last Updated: 2025-11-11

---

## 📊 System-Wide Status Overview

| Subsystem                               | Status          | Health         | Priority | Owner          |
| --------------------------------------- | --------------- | -------------- | -------- | -------------- |
| [ArgoCD](#argocd)                       | ✅ Deployed     | 🟢 Healthy     | High     | Infrastructure |
| [Traefik](#traefik)                     | ✅ Deployed     | 🟢 Healthy     | High     | Infrastructure |
| [Registry](#registry)                   | ✅ Deployed     | 🟡 Issues      | Medium   | Infrastructure |
| [Monitoring](#monitoring)               | ✅ Deployed     | 🟢 Healthy     | High     | Infrastructure |
| [Observability](#observability)         | ✅ Deployed     | 🟡 Partial     | Medium   | Infrastructure |
| [FluxCD](#fluxcd)                       | 🔴 Not Deployed | ⚪ N/A         | Low      | Infrastructure |
| [Catalyst UI](#catalyst-ui)             | 🟡 In Progress  | 🟡 Testing     | Medium   | Application    |
| [Catalyst DNS Sync](#catalyst-dns-sync) | 🟡 In Progress  | 🔵 Development | High     | Application    |
| [Media Stack](#media-stack)             | 🔴 Not Deployed | ⚪ N/A         | Low      | Application    |

**Legend:**

- Status: ✅ Deployed | 🟡 In Progress | 🔴 Not Started
- Health: 🟢 Healthy | 🟡 Degraded | 🔴 Down | 🔵 Dev | ⚪ N/A

---

## 🎯 High-Priority TODOs

### Critical Path Items

- [ ] **Fix Docker Registry blob upload issues** (Blocks catalyst-ui deployment)
  - Status: Investigating
  - Workaround: kubectl port-forward working
  - See: [infrastructure/base/registry/STATUS.md](infrastructure/base/registry/STATUS.md)

- [ ] **Complete Catalyst DNS Sync MVP Phase 1**
  - Status: 70% complete
  - Remaining: Web UI, metrics endpoint
  - See: [catalyst-dns-sync/STATUS.md](catalyst-dns-sync/STATUS.md)

- [ ] **Deploy FluxCD alongside ArgoCD**
  - Status: Assessment complete, manifests partial
  - Blocked by: None (SAFE TO DEPLOY)
  - TODO: DJ: Need to get to this- requires creating github repo and pushing current manifests
  - we need to do this cause we accidently deployed some stuff via argo that should be flux etc, and are shoring up the boudnary between flux controll/boostrap and argo application management
  - See: [docs/06-project-management/migration-assessments/flux-migration.md](docs/06-project-management/migration-assessments/flux-migration.md)

### Important But Not Blocking

- [ ] **Standardize domain naming** (.lab vs .talos00)
- [ ] **Complete configs/Talos.md** documentation
- [ ] **Add HTTPS/TLS to Traefik** (currently HTTP only)
- [ ] **Implement backup strategy** for etcd and PVCs

---

## 📦 Subsystem Status Details

### ArgoCD

**Location:** `infrastructure/base/argocd/`
**Status:** ✅ Deployed & Operational

**Current State:**

- Version: Latest (Helm chart)
- Access: http://argocd.talos00
- Applications: catalyst-ui (defined, not syncing yet)

**TODOs:**

- [ ] Configure HTTPS ingress
- [ ] Set up SSO/OIDC authentication
- [ ] Add backup schedule for ArgoCD configs
- [ ] Document application creation workflow

**See:** [infrastructure/base/ArgoCD/STATUS.md](infrastructure/base/argocd/STATUS.md)

---

### Traefik

**Location:** `infrastructure/base/traefik/`
**Status:** ✅ Deployed & Operational

**Current State:**

- Version: v3.x
- IngressRoutes: All services accessible
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
**Status:** ✅ Deployed (🟡 Issues with HTTP push)

**Current State:**

- Storage: 50Gi PVC
- Access: http://registry.talos00 (read-only working)
- Push: Via kubectl port-forward only

**Issues:**

- ❌ HTTP blob upload returns 404 via Traefik
- ✅ Workaround: port-forward to localhost:5000

**TODOs:**

- [ ] Debug Traefik proxy issues for blob uploads
- [ ] Implement authentication (Docker-registry supports basic auth)
- [ ] Add HTTPS support
- [ ] Create automated image cleanup job

**See:** [infrastructure/base/registry/STATUS.md](infrastructure/base/registry/STATUS.md)

---

### Monitoring

**Location:** `infrastructure/base/monitoring/`
**Status:** ✅ Deployed & Operational

**Current State:**

- Prometheus: ✅ Running (30-day retention, 50Gi)
- Grafana: ✅ Running (http://grafana.talos00)
- Alertmanager: ✅ Running
- Exportarr: 🔴 Not deployed

**TODOs:**

- [ ] Deploy Exportarr for \*arr stack metrics
- [ ] Configure Alertmanager notifications (Slack/Email)
- [ ] Add custom dashboards for Talos metrics
- [ ] Increase retention to 90 days if storage allows

**See:** [infrastructure/base/monitoring/STATUS.md](infrastructure/base/monitoring/STATUS.md)

---

### Observability

**Location:** `infrastructure/base/observability/`
**Status:** ✅ Deployed (🟡 Partial)

**Current State:**

- OpenSearch: ✅ Running (30Gi storage)
- Graylog: ✅ Running (http://graylog.talos00)
- MongoDB: ✅ Running (Graylog backend)
- Fluent Bit: ✅ Running (log collection)

**TODOs:**

- [ ] Configure Graylog inputs and streams
- [ ] Add index lifecycle policies
- [ ] Integrate with Alertmanager
- [ ] Add log retention automation

**See:** [infrastructure/base/observability/STATUS.md](infrastructure/base/observability/STATUS.md)

---

### FluxCD

**Location:** `bootstrap/flux/`, `infrastructure/base/{monitoring,observability}/`
**Status:** ✅ Manifests Ready (🔴 Not Deployed - Awaiting GitHub Push)

**Assessment:** SAFE TO DEPLOY - Zero-downtime migration confirmed

**Current State:**

- ✅ HelmRelease manifests created for all observability components
- ✅ Kustomization files configured
- ✅ Bootstrap script ready (`bootstrap/flux/bootstrap.sh`)
- ✅ Migration assessment complete (docs/FLUX-MIGRATION-ASSESSMENT.md)
- ✅ All kustomize builds validated
- 🔴 Repository not yet pushed to GitHub (required for Flux bootstrap)

**Created HelmRelease Manifests:**

- ✅ MongoDB (Bitnami chart v18.1.9) - `infrastructure/base/observability/mongodb/helmrelease.yaml`
- ✅ OpenSearch (OpenSearch chart v3.3.2) - `infrastructure/base/observability/opensearch/helmrelease.yaml`
- ✅ Fluent Bit (Fluent chart v0.48.x) - `infrastructure/base/observability/fluent-bit/helmrelease.yaml`
- ✅ kube-Prometheus-stack (already existed) - `infrastructure/base/monitoring/kube-prometheus-stack/helmrelease.yaml`

**Cleanup Completed:**

- ✅ Removed old `values.yaml` files (replaced by HelmRelease)
- ✅ Removed unused `loki-stack/` directory
- ✅ Created namespace definitions for observability
- ✅ Created top-level kustomization files for monitoring and observability

**Next Steps - FluxCD Deployment:**

**PREREQUISITE:** Repository must be pushed to GitHub first!

1. **Create/Configure GitHub Repository:**

   ```bash
   # Create new repo on GitHub (or rename/move existing)
   # Add remote to local repo
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git

   # Push all commits
   git push -u origin main
   ```

2. **Set GitHub Credentials:**

   ```bash
   export GITHUB_USER=your-username
   export GITHUB_TOKEN=your-github-personal-access-token
   ```

   Token needs these scopes:
   - `repo` (full control)
   - `workflow` (if using GitHub Actions)

3. **Bootstrap FluxCD:**

   ```bash
   # Option A: Use bootstrap script
   ./bootstrap/flux/bootstrap.sh

   # Option B: Manual bootstrap
   flux bootstrap github \
     --owner=$GITHUB_USER \
     --repository=YOUR_REPO_NAME \
     --branch=main \
     --path=clusters/homelab-single \
     --personal \
     --read-write-key
   ```

4. **Verify Deployment:**

   ```bash
   # Check Flux installation
   flux check

   # View all Flux resources
   flux get all

   # Check kustomizations
   flux get kustomizations --watch

   # Verify no pod restarts (zero-downtime validation)
   kubectl get pods -A
   ```

5. **Post-Deployment Validation:**

   ```bash
   # Verify Flux adopted existing Helm releases
   flux get helmreleases -A

   # Check for any errors
   flux logs --all-namespaces

   # Confirm monitoring stack still healthy
   kubectl get pods -n monitoring

   # Confirm observability stack still healthy
   kubectl get pods -n observability
   ```

**What Flux Will Manage (Dual GitOps Architecture):**

**FluxCD** (Infrastructure - Low-level):

- ✅ Namespaces (media-dev, media-prod, observability)
- ✅ Storage (local-path-provisioner)
- ✅ Monitoring (kube-Prometheus-stack via HelmRelease)
- ✅ Observability (MongoDB, OpenSearch, Fluent Bit via HelmRelease, Graylog via Deployment)

**ArgoCD** (Applications - High-level):

- Media Stack (Prowlarr, Sonarr, Radarr, etc.)
- Media Servers (Plex, Jellyfin)
- Supporting Apps (PostgreSQL, Homepage, Overseerr)

**Migration Safety:**

- 🟢 **Risk Level: LOW**
- ✅ No cleanup needed
- ✅ No shutdown required
- ✅ Zero downtime migration
- ✅ Flux uses Server-Side Apply (adopts existing resources without recreation)
- ✅ All resources deployed via `kubectl apply` (Flux-compatible)
- ✅ Clear rollback plan available

**Rollback Plan:**

```bash
# If issues occur:
# Option 1: Suspend Flux reconciliation
flux suspend kustomization flux-system

# Option 2: Complete removal
flux uninstall
# (All resources stay running, returns to manual management)
```

**TODOs:**

- [ ] **BLOCKER:** Push repository to GitHub
- [ ] Configure GitHub repository and remote
- [ ] Create GitHub Personal Access Token with repo scope
- [ ] Run FluxCD bootstrap script
- [ ] Verify zero-downtime adoption of existing resources
- [ ] Test dual GitOps workflow (Flux + ArgoCD)
- [ ] Monitor Flux reconciliation for 24 hours
- [ ] Update documentation with actual deployment results

**Estimated Time:** 1 hour (including verification)

**See:**

- [docs/FLUX-MIGRATION-ASSESSMENT.md](docs/workstreams/FLUX-MIGRATION-ASSESSMENT.md) - Full migration analysis
- [docs/DUAL-GITOPS-ARCHITECTURE.md](docs/DUAL-GITOPS-ARCHITECTURE.md) - Architecture details
- [bootstrap/flux/bootstrap.sh](bootstrap/flux/bootstrap.sh) - Bootstrap script

---

### Catalyst UI

**Location:** `~/catalyst-devspace/workspace/catalyst-ui`
**Infrastructure:** `infrastructure/base/argocd/applications/catalyst-ui.yaml`
**Status:** 🟡 In Progress (Docker build complete, deployment pending)

**Current State:**

- Dockerfile: ✅ Created & tested
- K8s Manifests: ✅ Created (k8s/)
- ArgoCD Application: ✅ Defined
- Image Push: 🟡 Works via port-forward
- Deployment: 🔴 Not synced yet

**Blocking Issues:**

- Docker registry HTTP push issues (workaround available)
- ArgoCD application not syncing (needs investigation)

**TODOs:**

- [ ] Push catalyst-ui image to registry
- [ ] Debug ArgoCD sync issues
- [ ] Verify application accessibility at http://catalyst.talos00
- [ ] Set up CI/CD pipeline for auto-builds
- [ ] Commit Dockerfile and k8s/ to git repo

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

**TODOs:**

- [ ] Complete Prometheus /metrics endpoint
- [ ] Add comprehensive testing
- [ ] Finalize web UI design
- [ ] Create Kubernetes manifests
- [ ] Deploy to cluster

**See:**

- [catalyst-dns-sync/STATUS.md](catalyst-dns-sync/STATUS.md)
- [docs/05-projects/catalyst-dns-sync/mvp.md](docs/05-projects/catalyst-dns-sync/mvp.md)
- [docs/05-projects/catalyst-dns-sync/proposal.md](docs/05-projects/catalyst-dns-sync/proposal.md)

---

### Media Stack (\*arr Applications)

**Location:** `applications/arr-stack/`
**Status:** 🔴 Not Deployed

**Planned Components:**

- Prowlarr (indexer management)
- Sonarr (TV shows)
- Radarr (movies)
- Readarr (books)
- Overseerr (request management)
- Plex/Jellyfin (media server)
- Homepage (dashboard)

**TODOs:**

- [ ] Deploy base media stack
- [ ] Configure shared PVCs for downloads/media
- [ ] Set up Exportarr for metrics
- [ ] Configure indexers in Prowlarr
- [ ] Test complete download workflow
- [ ] Add to ArgoCD for automated management

**See:** [applications/arr-stack/STATUS.md](applications/arr-stack/STATUS.md)

---

## 📋 Documentation TODOs

### High Priority

- [ ] Move existing docs to new progressive structure
- [ ] Create subsystem STATUS.md files (in progress)
- [ ] Add cross-reference links between documents
- [ ] Update CLAUDE.md with new structure

### Medium Priority

- [ ] Create glossary of terms
- [ ] Add Mermaid diagrams for architecture
- [ ] Split OBSERVABILITY.md into monitoring vs logging
- [ ] Create troubleshooting decision tree

### Low Priority

- [ ] Generate automated API documentation
- [ ] Create video walkthroughs
- [ ] Add FAQ document
- [ ] Create contributor guidelines

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
- [ ] External secrets management (Sealed Secrets/Vault)
- [ ] Service mesh evaluation (Istio/Linkerd)
- [ ] GitOps CI/CD integration testing

---

## 📈 Project Management

### Current Sprint (Week of 2025-11-11)

1. **Complete documentation reorganization** ✅ In Progress
2. **Deploy FluxCD** ⏳ Pending
3. **Fix catalyst-ui deployment** ⏳ Pending
4. **Finish catalyst-dns-sync MVP** ⏳ In Progress

### Next Sprint

1. Deploy media stack
2. Implement HTTPS/TLS
3. Set up monitoring alerts
4. Complete Flux migration

### Completed Recently

- ✅ ArgoCD deployment and configuration
- ✅ Traefik ingress setup
- ✅ Observability stack deployment
- ✅ Docker registry deployment
- ✅ Catalyst UI Dockerfile creation

---

## 🎯 Success Criteria

### Infrastructure

- ✅ Cluster provisioned and stable
- ✅ GitOps tooling deployed (ArgoCD)
- 🟡 All infrastructure services healthy (registry issues)
- 🔴 HTTPS enabled across all services
- 🔴 Monitoring alerts configured

### Applications

- 🟡 Catalyst UI deployed via ArgoCD
- 🟡 Catalyst DNS Sync MVP complete
- 🔴 Media stack operational
- 🔴 All services accessible via HTTPS

### Documentation

- 🟡 Progressive documentation structure
- 🔴 All subsystems have STATUS.md
- 🔴 All cross-references added
- 🔴 Troubleshooting guides complete

---

## 📞 Quick Links

- **Main Index:** [docs/INDEX.md](docs/INDEX.md)
- **Implementation Tracker:** [docs/06-project-management/implementation-tracker.md](docs/06-project-management/implementation-tracker.md)
- **Progress Summary:** [docs/06-project-management/progress-summary.md](docs/06-project-management/progress-summary.md)
- **Dual GitOps Architecture:** [docs/02-architecture/dual-gitops.md](docs/02-architecture/dual-gitops.md)

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
