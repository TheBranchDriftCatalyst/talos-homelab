# Tilt Development Workflow Implementation

**Status:** 🚧 IN PROGRESS
**Date Started:** 2025-11-25
**Goal:** Implement consistent Tilt-based local development pattern across functional namespaces

---

## Overview

Establish a standardized local development workflow for each functional namespace using Tilt, enabling rapid iteration without disrupting Flux-managed production deployments.

## Pattern: Per-Namespace Development Tooling

Each functional namespace will have three standard files:

1. **`Tiltfile`** - Tilt configuration for hot-reload local development
2. **`dashboard.sh`** - Status dashboard for the namespace
3. **`deploy.sh`** - Deployment orchestration script

---

## File Specifications

### 1. Tiltfile

**Purpose:** Local development with live updates, uses dev/local-path overlays

**Key Features:**
- Apply kustomize overlays for local development
- Watch for manifest changes and auto-apply
- Port-forward services for local access
- Display resource status in Tilt UI
- **Flux-aware:** Automatically suspend Flux reconciliation for the namespace during dev

**Template Structure:**
```python
# Load Kubernetes context
allow_k8s_contexts('kubernetes-admin@talos00')

# Suspend Flux reconciliation during dev (optional, controlled by env var)
if os.getenv('SUSPEND_FLUX', 'true') == 'true':
    local('flux suspend kustomization flux-system --context kubernetes-admin@talos00')
    # Resume on Tilt down
    local('tilt down', trigger_mode=TRIGGER_MODE_MANUAL, auto_init=False)

# Apply dev overlay
k8s_yaml(kustomize('overlays/dev'))

# Watch for changes
watch_file('base/')
watch_file('overlays/dev/')

# Port forwards for local access
k8s_resource('service-name', port_forwards='8080:8080')

# Resource grouping
k8s_resource('pod-name', labels=['namespace-name'])
```

### 2. dashboard.sh

**Purpose:** Display current namespace status (already implemented for arr-stack)

**Features:**
- Show all pods with status indicators
- Display service endpoints and ingress URLs
- Show PVC status and storage usage
- Quick command reference
- Color-coded health indicators

**Location:** `applications/<namespace>/dashboard.sh` or `infrastructure/<namespace>/dashboard.sh`

### 3. deploy.sh

**Purpose:** Orchestrate deployment to production via Flux

**Features:**
- Validate manifests (kustomize build, kubectl dry-run)
- Git workflow (commit, push)
- Trigger Flux reconciliation
- Wait for deployment health
- Rollback on failure (optional)

**Flux Integration:**
- Commits to main branch
- Flux auto-reconciles within 10 minutes
- Can force immediate sync with `flux reconcile`

---

## Implementation Plan

### Phase 1: arr-stack Namespace (Prototype)

**Files to Create:**
- ✅ `applications/arr-stack/dashboard.sh` (DONE)
- 🚧 `applications/arr-stack/Tiltfile` (IN PROGRESS)
- 🚧 `applications/arr-stack/deploy.sh` (IN PROGRESS)

**Dev Overlay:** `applications/arr-stack/overlays/dev/`
- Uses `storage/local-path` for fast local storage
- Smaller resource limits for local dev
- Optional: Reduced replica counts

### Phase 2: Infrastructure Namespaces

Apply pattern to:
- `infrastructure/base/monitoring/` (Prometheus, Grafana)
- `infrastructure/base/observability/` (Graylog, OpenSearch)

### Phase 3: Additional Application Namespaces

As new applications are added (catalyst-ui via ArgoCD, etc.)

---

## Tilt Workflow

### Local Development Session

```bash
# Start Tilt for arr-stack
cd applications/arr-stack
tilt up

# Tilt UI opens at http://localhost:10350
# - See all resources
# - View logs
# - Trigger manual updates

# Make changes to manifests
vim base/sonarr/deployment.yaml

# Tilt auto-detects and applies changes
# Watch logs in Tilt UI

# Stop Tilt (resumes Flux if suspended)
tilt down
```

### Deployment to Production

```bash
# After local testing
cd applications/arr-stack

# Run deployment script
./deploy.sh

# Script will:
# 1. Validate manifests
# 2. Commit changes
# 3. Push to GitHub
# 4. Flux auto-syncs (or force reconcile)
# 5. Verify deployment health
```

### Check Status

```bash
# Quick status check
./dashboard.sh

# Full Tilt UI (if running)
tilt up  # Then visit http://localhost:10350
```

---

## Flux Integration Strategy

### Development Mode (Tilt Active)

**Option A: Suspend Flux (Recommended)**
```bash
# Tilt automatically suspends Flux for the namespace
flux suspend kustomization flux-system

# Tilt has full control, no reconciliation conflicts
# Tilt down resumes Flux
```

**Option B: Coexist with Flux**
```bash
# Don't suspend Flux
SUSPEND_FLUX=false tilt up

# Flux may reconcile and overwrite Tilt changes
# Use for testing Flux behavior
```

### Production Mode (Flux Active)

- Flux continuously reconciles from main branch
- Changes via git commit → push → auto-sync
- Manual sync: `flux reconcile kustomization flux-system`

---

## Directory Structure

```
applications/arr-stack/
├── Tiltfile                      # 🆕 Tilt configuration
├── dashboard.sh                  # ✅ Status dashboard
├── deploy.sh                     # 🆕 Deployment script
├── base/                         # Base manifests
│   ├── kustomization.yaml
│   ├── sonarr/
│   ├── radarr/
│   └── ...
└── overlays/
    ├── dev/                      # 🆕 Local dev overlay
    │   └── kustomization.yaml    # Uses storage/local-path
    ├── prod/                     # Production overlay
    │   └── kustomization.yaml    # Uses storage/fatboy-nfs
    └── storage/
        ├── local-path/           # Fast local storage
        └── fatboy-nfs/           # NFS storage
```

---

## Overlay Strategy

### Production (`overlays/prod`)
- **Used by:** Flux (committed to git)
- **Storage:** `storage/fatboy-nfs` (NFS, ReadWriteMany, 1Ti)
- **Resources:** Full production limits
- **Purpose:** Production deployment on Talos cluster

### Development (`overlays/dev`)
- **Used by:** Tilt (local only, not committed)
- **Storage:** `storage/local-path` (Local, ReadWriteOnce, 100Gi)
- **Resources:** Reduced limits for local dev
- **Purpose:** Fast iteration on local machine

### Storage Sub-overlays
- **fatboy-nfs:** NFS storage from Synology (prod)
- **local-path:** Local-path provisioner (dev)

---

## Benefits

1. **Fast Iteration:** Tilt hot-reloads changes without full redeployment
2. **Production Parity:** Same manifests, different overlays
3. **Flux-Safe:** Suspend Flux during dev to avoid conflicts
4. **Visibility:** Tilt UI shows all resources, logs, errors
5. **Consistent Pattern:** Same workflow across all namespaces
6. **GitOps Compatible:** Deploy script manages git → Flux workflow

---

## Installation Requirements

### Tilt

```bash
# Install Tilt
brew install tilt-dev/tap/tilt

# Verify
tilt version
```

### Flux CLI (Already Installed)

```bash
flux version
```

---

## Future Enhancements

1. **Live Update:** Tilt's live_update feature for container hot-reload
2. **Local Registry:** Push images to local registry, Tilt deploys
3. **Helm Integration:** Tilt can manage Helm releases
4. **Multi-Namespace:** Run Tilt for multiple namespaces simultaneously
5. **CI Integration:** Run deploy.sh in CI/CD pipeline

---

## Documentation References

- **Tilt Docs:** https://docs.tilt.dev/
- **Kustomize Overlays:** Already documented in `applications/arr-stack/overlays/storage/README.md`
- **Flux Suspend:** https://fluxcd.io/flux/cmd/flux_suspend_kustomization/
- **Local Development Guide:** TBD - Will create after prototype

---

## Success Criteria

- [ ] Tilt can deploy arr-stack with dev overlay
- [ ] Changes to manifests auto-apply in Tilt
- [ ] Dashboard shows accurate namespace status
- [ ] Deploy script successfully pushes to prod via Flux
- [ ] Flux suspension/resumption works correctly
- [ ] Pattern documented and reusable for other namespaces

---

## Current Status

**Arr-Stack Implementation:**
- ✅ Dashboard (`dashboard.sh`) - COMPLETED
- 🚧 Tiltfile - IN PROGRESS
- 🚧 deploy.sh - IN PROGRESS
- 🚧 overlays/dev/ - NEEDS CREATION

**Next Steps:**
1. Create `overlays/dev/kustomization.yaml`
2. Implement `Tiltfile`
3. Implement `deploy.sh`
4. Test full workflow
5. Document usage in main README

---

## Notes

- Dev overlay should be gitignored or clearly marked as local-only
- Consider adding `.tiltignore` for files Tilt shouldn't watch
- Flux suspension is optional but recommended to avoid conflicts
- Deploy script should validate before pushing to prevent bad commits
