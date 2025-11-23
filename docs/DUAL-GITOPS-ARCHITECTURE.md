# Dual GitOps Architecture - FluxCD + ArgoCD

**Date**: 2025-11-11
**Status**: ✅ Designed and Ready to Deploy

---

## Overview

This homelab uses a **dual GitOps approach** for clear separation of concerns:

- **FluxCD**: Manages low-level infrastructure (namespaces, storage, monitoring)
- **ArgoCD**: Manages high-level applications (arr stack, media servers)

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     GitHub Repository                            │
│                      (talos-fix)                                 │
└────────────────┬────────────────────────────┬────────────────────┘
                 │                            │
                 │                            │
                 v                            v
        ┌────────────────┐          ┌──────────────────┐
        │    FluxCD      │          │     ArgoCD       │
        │                │          │                  │
        │  Infrastructure│          │   Applications   │
        │   Management   │          │   Management     │
        └────────┬───────┘          └────────┬─────────┘
                 │                            │
                 v                            v
        ┌────────────────┐          ┌──────────────────┐
        │ Infrastructure │          │   Applications    │
        ├────────────────┤          ├──────────────────┤
        │ • Namespaces   │          │ • Prowlarr       │
        │ • Storage      │          │ • Sonarr         │
        │ • Monitoring   │          │ • Radarr         │
        │ • Observability│          │ • Readarr        │
        │                │          │ • Overseerr      │
        │                │          │ • Plex           │
        │                │          │ • Jellyfin       │
        │                │          │ • Homepage       │
        │                │          │ • PostgreSQL     │
        └────────────────┘          └──────────────────┘
```

---

## Responsibility Matrix

| Component                                  | Managed By  | Why                                 |
| ------------------------------------------ | ----------- | ----------------------------------- |
| **Namespaces** (media-dev, media-prod)     | FluxCD      | Low-level infrastructure            |
| **Storage** (local-path, NFS)              | FluxCD      | Low-level infrastructure            |
| **Monitoring** (Prometheus, Grafana)       | FluxCD      | Low-level infrastructure            |
| **Observability** (Graylog, OpenSearch)    | FluxCD      | Low-level infrastructure            |
| **Traefik**                                | Manual/Helm | Pre-installed, not in GitOps        |
| **ArgoCD**                                 | Manual/Helm | Bootstraps itself, not self-managed |
| **Arr Stack** (Prowlarr, Sonarr, etc.)     | ArgoCD      | High-level applications             |
| **Media Servers** (Plex, Jellyfin)         | ArgoCD      | High-level applications             |
| **Supporting Apps** (PostgreSQL, Homepage) | ArgoCD      | High-level applications             |

---

## Current Deployment Status

### ❌ FluxCD - NOT YET DEPLOYED

**Status**: Ready to deploy, bootstrap script created
**Path**: `bootstrap/flux/bootstrap.sh`

**What Flux Will Manage**:

```
infrastructure/base/
├── namespaces/              ← Flux
│   ├── media-dev.yaml
│   ├── media-prod.yaml
│   └── local-path-storage.yaml
├── storage/                 ← Flux
│   └── local-path-provisioner.yaml
├── monitoring/              ← Flux (via HelmRelease)
│   └── kube-prometheus-stack/
└── observability/           ← Flux (via HelmRelease)
    ├── mongodb/
    ├── opensearch/
    ├── graylog/
    └── fluent-bit/
```

### ✅ ArgoCD - DEPLOYED

**Status**: Running in `argocd` namespace
**Access**: http://argocd.talos00

**What ArgoCD Manages**:

```
applications/arr-stack/
├── base/
│   ├── prowlarr/            ← ArgoCD
│   ├── sonarr/              ← ArgoCD
│   ├── radarr/              ← ArgoCD
│   ├── readarr/             ← ArgoCD
│   ├── overseerr/           ← ArgoCD
│   ├── plex/                ← ArgoCD
│   ├── jellyfin/            ← ArgoCD
│   ├── homepage/            ← ArgoCD
│   ├── postgresql/          ← ArgoCD
│   └── exportarr/           ← ArgoCD
└── overlays/
    ├── dev/
    └── prod/
```

---

## Deployment Workflow

### Initial Setup (One-time)

#### 1. Deploy FluxCD

```bash
# Install Flux CLI
brew install fluxcd/tap/flux

# Set environment variables
export GITHUB_USER=your-github-username
export GITHUB_REPO=talos-fix

# Bootstrap Flux
./bootstrap/flux/bootstrap.sh

# Or manually:
flux bootstrap github \
  --owner=$GITHUB_USER \
  --repository=$GITHUB_REPO \
  --branch=main \
  --path=clusters/homelab-single \
  --personal
```

#### 2. Verify Flux Deployment

```bash
# Check Flux status
flux check

# View all Flux resources
flux get all

# Check kustomizations
flux get kustomizations

# Watch reconciliation
flux get kustomizations --watch
```

#### 3. ArgoCD (Already Deployed)

```bash
# ArgoCD is already running
kubectl get pods -n argocd

# Access UI
open http://argocd.talos00

# Login: admin / admin
```

---

## How It Works

### FluxCD Workflow (Infrastructure)

1. **Flux monitors** `clusters/homelab-single/flux-system/` in Git
2. **Detects changes** to infrastructure manifests
3. **Auto-reconciles** every 1 minute (configurable)
4. **Applies changes** to cluster (namespaces, storage, monitoring)
5. **Reports status** via `flux get all`

### ArgoCD Workflow (Applications)

1. **ArgoCD monitors** `applications/arr-stack/` in Git
2. **Detects changes** to application manifests
3. **Shows diff** in UI before applying (manual or auto)
4. **Applies changes** to cluster (arr apps, media servers)
5. **Reports status** via web UI and `argocd app list`

---

## Key Differences

| Feature           | FluxCD                                    | ArgoCD                      |
| ----------------- | ----------------------------------------- | --------------------------- |
| **UI**            | CLI only (or WeaveGitOps for UI)          | Full web UI ✨              |
| **Scope**         | Infrastructure (foundational)             | Applications (user-facing)  |
| **CRDs**          | GitRepository, Kustomization, HelmRelease | Application, ApplicationSet |
| **Sync**          | Automatic (pull-based)                    | Manual or automatic         |
| **Multi-cluster** | Excellent                                 | Excellent                   |
| **Helm Support**  | Via HelmRelease CRD                       | Native via Application      |

---

## Why Dual GitOps?

### Advantages ✅

1. **Separation of Concerns**
   - Infrastructure changes don't affect app deployments
   - Different teams can manage different layers

2. **Best Tool for the Job**
   - Flux: Great for low-level Kubernetes resources
   - Argo: Amazing UI for application management

3. **Safety**
   - Infrastructure failures don't break app deployments
   - Can rollback apps independently from infrastructure

4. **Visibility**
   - Flux: `flux get all` for infrastructure status
   - ArgoCD: Web UI for application status

### Disadvantages ⚠️

1. **Complexity**
   - Two tools to learn and maintain
   - Two sets of CRDs and concepts

2. **Overhead**
   - Both consume cluster resources
   - Two reconciliation loops

3. **Coordination**
   - Need to ensure proper dependency ordering
   - Apps depend on infrastructure being ready

---

## Migration Plan (From Current State)

### Current State

- ✅ ArgoCD deployed via Helm
- ❌ FluxCD not deployed
- ❌ Infrastructure deployed manually via Helm/kubectl

### Migration Steps

#### Phase 1: Deploy FluxCD (No Changes to Cluster)

```bash
# Bootstrap Flux (won't touch existing resources)
./bootstrap/flux/bootstrap.sh

# Verify Flux is running
flux check
flux get kustomizations
```

#### Phase 2: Let Flux Adopt Existing Resources

```bash
# Flux will detect and adopt existing resources
# No recreation needed - Flux uses kubectl apply

# Watch Flux sync
flux get kustomizations --watch
```

#### Phase 3: Verify No Disruption

```bash
# Check all pods still running
kubectl get pods -A

# Verify monitoring still works
curl http://grafana.talos00

# Check arr apps still running
kubectl get pods -n media-dev
```

#### Phase 4: Future Changes via GitOps

```bash
# From now on, change infrastructure via Git
# 1. Edit files in infrastructure/
# 2. Git commit and push
# 3. Flux auto-applies changes
```

---

## Directory Structure

```
talos-fix/
├── bootstrap/
│   ├── flux/                    # FluxCD bootstrap
│   │   ├── bootstrap.sh         # Bootstrap script
│   │   ├── README.md            # Flux documentation
│   │   └── namespace.yaml       # flux-system namespace
│   └── argocd/                  # ArgoCD bootstrap
│       ├── values.yaml          # ArgoCD Helm values
│       └── ingressroute.yaml    # ArgoCD ingress
├── clusters/
│   └── homelab-single/
│       └── flux-system/
│           └── kustomization.yaml   # Flux entry point
├── infrastructure/              # ← Managed by Flux
│   ├── base/
│   │   ├── namespaces/
│   │   ├── storage/
│   │   ├── monitoring/
│   │   └── observability/
│   └── overlays/
│       ├── dev/
│       └── prod/
└── applications/                # ← Managed by ArgoCD
    └── arr-stack/
        ├── base/
        └── overlays/
```

---

## Troubleshooting

### Flux Issues

**Check Flux status:**

```bash
flux check
flux get all
flux logs --all-namespaces
```

**Force reconciliation:**

```bash
flux reconcile source git flux-system
flux reconcile kustomization flux-system
```

**Suspend/Resume:**

```bash
flux suspend kustomization flux-system
flux resume kustomization flux-system
```

### ArgoCD Issues

**Check ArgoCD status:**

```bash
kubectl get pods -n argocd
argocd app list
argocd app get <app-name>
```

**Force sync:**

```bash
argocd app sync <app-name>
argocd app sync --force <app-name>  # Hard refresh
```

**Diff before sync:**

```bash
argocd app diff <app-name>
```

---

## Best Practices

### FluxCD

1. **Use HelmRelease for Helm charts** (not manual helm installs)
2. **Keep infrastructure in `infrastructure/` directory**
3. **Use kustomize overlays for environment-specific config**
4. **Let Flux auto-reconcile** (don't manually kubectl apply)
5. **Watch Flux logs during changes**

### ArgoCD

1. **Create Application CRDs in `argocd-apps/` directory**
2. **Use manual sync for production** (see diff first)
3. **Use auto-sync for dev** (faster iteration)
4. **Monitor via web UI** (better visibility)
5. **Use health checks** (custom if needed)

### Both

1. **Git is source of truth** - don't manually kubectl apply
2. **Test in dev overlay first** before prod
3. **Use semantic commits** for clear change tracking
4. **Tag releases** for easy rollbacks
5. **Document breaking changes** in commit messages

---

## Commands Reference

### FluxCD

```bash
# Bootstrap
flux bootstrap github --owner=USER --repository=REPO --path=clusters/homelab-single

# Status
flux check
flux get all
flux get kustomizations
flux get helmreleases

# Reconcile
flux reconcile kustomization flux-system
flux reconcile helmrelease -n monitoring kube-prometheus-stack

# Logs
flux logs --all-namespaces
flux logs --kind=Kustomization --name=flux-system

# Suspend/Resume
flux suspend kustomization <name>
flux resume kustomization <name>
```

### ArgoCD

```bash
# Login
argocd login argocd.talos00

# Applications
argocd app list
argocd app get <app-name>
argocd app sync <app-name>
argocd app diff <app-name>
argocd app rollback <app-name> <revision>

# Projects
argocd proj list
argocd proj get default

# Cluster
argocd cluster list
```

---

## Decision Log

**2025-11-09**: Dual GitOps Architecture Chosen

- **Flux**: Infrastructure (namespaces, storage, monitoring, observability)
- **ArgoCD**: Applications (arr stack, media servers)
- **Rationale**: Clean separation, best tool for each job

**2025-11-11**: FluxCD Bootstrap Files Restored

- Accidentally deleted in cleanup
- Restored for proper dual GitOps implementation
- Ready to deploy Flux alongside existing ArgoCD

---

## Next Steps

1. ✅ FluxCD bootstrap script created
2. ⏸️ Deploy FluxCD to cluster
3. ⏸️ Verify Flux adopts existing infrastructure
4. ⏸️ Create ArgoCD Applications for arr stack
5. ⏸️ Test end-to-end GitOps workflow
6. ⏸️ Document operational procedures

---

**Last Updated**: 2025-11-11
**Status**: Ready for FluxCD deployment
