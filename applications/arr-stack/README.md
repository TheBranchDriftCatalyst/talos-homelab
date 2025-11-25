# Arr-Stack - Media Automation

Media automation stack including indexers, downloaders, and media servers for TV shows, movies, and music.

## Components

### Indexer & Management
- **Prowlarr** - Indexer manager for Usenet and torrents

### Media Automation
- **Sonarr** - TV show management
- **Radarr** - Movie management
- **Readarr** - Book management (ARM64 issues - often disabled)
- **Overseerr** - Request management

### Media Servers
- **Plex** - Media server (transcoding, clients)
- **Jellyfin** - Open-source media server
- **Tdarr** - Media transcoding and health checking

### Infrastructure
- **PostgreSQL** - Shared database for \*arr apps
- **Homepage** - Dashboard for all services

---

## Development Workflow

This namespace implements the standardized Tilt development pattern with three key files:

### 1. Tiltfile - Local Development

**Purpose:** Fast local development with hot-reload

```bash
# Start Tilt (suspends Flux automatically)
cd applications/arr-stack
tilt up

# Tilt UI: http://localhost:10350
# Make changes to manifests - auto-applies

# Stop Tilt (resumes Flux)
tilt down
```

**Features:**
- Uses `overlays/dev` (media-dev namespace, local-path storage)
- Automatically suspends Flux during development
- Port-forwards all services to localhost
- Auto-applies manifest changes
- Resource grouping and log viewing

**Environment Variables:**
- `SUSPEND_FLUX=false` - Don't suspend Flux (for testing)

### 2. dashboard.sh - Status Dashboard

**Purpose:** Display current namespace status

```bash
# Show production status
./dashboard.sh

# Show development status
NAMESPACE=media-dev ./dashboard.sh
```

**Features:**
- ASCII art header
- Pod status with health indicators
- Service endpoints and ingress URLs
- PVC usage and storage info
- Quick command reference

### 3. deploy.sh - Production Deployment

**Purpose:** Deploy to production via Flux GitOps

```bash
# Interactive deployment
./deploy.sh

# Auto-confirm (for CI/CD)
./deploy.sh --auto-confirm

# Preview only
./deploy.sh --dry-run
```

**Workflow:**
1. Validates manifests (kustomize build + kubectl dry-run)
2. Shows deployment preview
3. Commits changes to git
4. Pushes to GitHub
5. Triggers Flux reconciliation
6. Waits for pods to be ready

---

## Directory Structure

```
arr-stack/
├── Tiltfile                  # Tilt local dev configuration
├── dashboard.sh              # Namespace status dashboard
├── deploy.sh                 # Production deployment script
├── README.md                 # This file
│
├── base/                     # Base Kubernetes manifests
│   ├── kustomization.yaml
│   ├── common-env.yaml       # Shared environment variables
│   ├── prowlarr/
│   ├── sonarr/
│   ├── radarr/
│   ├── overseerr/
│   ├── plex/
│   ├── jellyfin/
│   ├── tdarr/
│   ├── postgresql/
│   └── homepage/
│
└── overlays/                 # Environment-specific overlays
    ├── dev/                  # Local development (Tilt)
    │   └── kustomization.yaml  # Uses storage/local-path, media-dev namespace
    ├── prod/                 # Production (Flux-managed)
    │   └── kustomization.yaml  # Uses storage/fatboy-nfs, media-prod namespace
    ├── storage/              # Storage backend overlays
    │   ├── local-path/       # Local storage (dev)
    │   └── fatboy-nfs/       # NFS storage (prod)
    └── ingress/
        └── talos00/          # Traefik IngressRoutes
```

---

## Overlay Strategy

### Production (`overlays/prod`)
- **Namespace:** `media-prod`
- **Storage:** NFS via `storage/fatboy-nfs`
- **Managed By:** Flux GitOps
- **Access:** http://*.talos00

### Development (`overlays/dev`)
- **Namespace:** `media-dev`
- **Storage:** Local-path via `storage/local-path`
- **Managed By:** Tilt
- **Access:** Port-forwards to localhost

---

## Quick Start

### Local Development

```bash
# Start development environment
cd applications/arr-stack
tilt up

# Tilt UI opens at http://localhost:10350
# Access services via port-forwards:
# - Sonarr: http://localhost:8989
# - Radarr: http://localhost:7878
# - Prowlarr: http://localhost:9696
# - etc.

# Make changes to manifests
vim base/sonarr/deployment.yaml

# Tilt detects and auto-applies changes

# Stop development environment
tilt down
```

### Production Deployment

```bash
# After testing locally
cd applications/arr-stack

# Deploy to production
./deploy.sh

# Verify deployment
./dashboard.sh
```

### Check Status

```bash
# Dashboard
./dashboard.sh

# Specific namespace
NAMESPACE=media-dev ./dashboard.sh

# Kubectl
kubectl get pods -n media-prod
kubectl get pods -n media-dev
```

---

## Configuration

### Environment Variables

Shared environment variables in `base/common-env.yaml`:
- `PUID=1000` / `PGID=1000` - User/group IDs
- `TZ=America/Los_Angeles` - Timezone
- `POSTGRES_HOST=postgresql` - Database host
- `POSTGRES_PORT=5432` - Database port
- `POSTGRES_USER=mediadb` - Database user

### Database Configuration

PostgreSQL credentials in `base/postgresql/secret.yaml` (managed by External Secrets if configured):
- `postgres-password` - Database password

Each app gets its own databases:
- `sonarr_main` / `sonarr_log`
- `radarr_main` / `radarr_log`
- `prowlarr_main` / `prowlarr_log`

### Storage

**Production (NFS):**
- `media-shared` - 1Ti ReadWriteMany
- `downloads-shared` - 500Gi ReadWriteMany
- App configs - 1-50Gi per app

**Development (Local-Path):**
- `media-shared` - 100Gi ReadWriteOnce
- `downloads-shared` - 50Gi ReadWriteOnce
- App configs - Same as prod

---

## Troubleshooting

### Tilt Issues

**Problem:** Tilt can't connect to Kubernetes
```bash
# Verify context
kubectl config current-context
# Should be: kubernetes-admin@talos00

# Verify cluster access
kubectl get nodes
```

**Problem:** Flux conflicts with Tilt
```bash
# Check if Flux is suspended
flux get kustomizations

# Manually suspend
flux suspend kustomization flux-system

# Resume
flux resume kustomization flux-system
```

**Problem:** Resources stuck in Pending
```bash
# Check PVCs
kubectl get pvc -n media-dev

# Check events
kubectl get events -n media-dev --sort-by='.lastTimestamp'
```

### Deployment Issues

**Problem:** deploy.sh validation fails
```bash
# Manual validation
kustomize build overlays/prod > test.yaml
kubectl apply --dry-run=client -f test.yaml
```

**Problem:** Flux not reconciling
```bash
# Check Flux status
flux get kustomizations

# Force reconcile
flux reconcile source git flux-system
flux reconcile kustomization flux-system
```

---

## Related Documentation

- **Tilt Workflow:** `docs/tilt-dev-workflow-implementation.md`
- **Storage Overlays:** `overlays/storage/README.md`
- **Flux GitOps:** `docs/DUAL-GITOPS.md`
- **Traefik Ingress:** `TRAEFIK.md`

---

## Notes

- **media-dev namespace** is for local development only (not deployed to prod)
- **media-prod namespace** is managed by Flux
- Changes to `base/` affect both dev and prod
- Changes to `overlays/` only affect that environment
- Always test in dev (Tilt) before deploying to prod (deploy.sh)
