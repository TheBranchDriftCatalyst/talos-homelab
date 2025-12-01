# Arr-Stack - Media Automation

Media automation stack including indexers, downloaders, and media servers for TV shows, movies, and music.

## Components

### Indexer & Management

- **Prowlarr** - Indexer manager for Usenet and torrents

### Media Automation

- **Sonarr** - TV show management
- **Radarr** - Movie management
- **Readarr** - Book management (disabled - ARM64 compatibility issues)
- **Overseerr** - Request management

### Media Servers

- **Plex** - Media server (transcoding, clients)
- **Jellyfin** - Open-source media server
- **Tdarr** - Media transcoding and health checking

### Infrastructure

- **PostgreSQL** - Shared database for \*arr apps
- **Homepage** - Dashboard for all services
- **Exportarr** - Prometheus metrics exporter for \*arr apps

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
│   ├── kustomization.yaml    # Main kustomization (namespace: media)
│   ├── common-env.yaml       # Shared environment variables
│   ├── prowlarr/
│   ├── sonarr/
│   ├── radarr/
│   ├── readarr/              # Exists but disabled in main kustomization
│   ├── overseerr/
│   ├── plex/
│   ├── jellyfin/
│   ├── tdarr/
│   ├── postgresql/
│   ├── homepage/
│   └── exportarr/            # Prometheus metrics for *arr apps
│
└── scripts/
    └── sync-api-keys.sh      # Sync API keys between *arr apps
```

---

## Development Workflow

### 1. Tiltfile - Local Development

**Purpose:** Fast local development with hot-reload

```bash
# Start Tilt (from root of repo, includes arr-stack)
tilt up

# Tilt UI: http://localhost:10350
# Make changes to manifests - auto-applies

# Stop Tilt
tilt down
```

**Features:**

- Port-forwards all services to localhost
- Auto-applies manifest changes
- Resource grouping and log viewing
- Dependencies managed (PostgreSQL starts first)

**Port Forwards:**

| Service   | Local Port | URL                         |
| --------- | ---------- | --------------------------- |
| Prowlarr  | 9696       | http://localhost:9696       |
| Sonarr    | 8989       | http://localhost:8989       |
| Radarr    | 7878       | http://localhost:7878       |
| Overseerr | 5055       | http://localhost:5055       |
| Plex      | 32400      | http://localhost:32400/web  |
| Jellyfin  | 8096       | http://localhost:8096       |
| Tdarr     | 8265       | http://localhost:8265       |
| Homepage  | 3000       | http://localhost:3000       |

### 2. dashboard.sh - Status Dashboard

**Purpose:** Display current namespace status

```bash
# Show status
./dashboard.sh

# Or with custom namespace
NAMESPACE=media ./dashboard.sh
```

**Features:**

- ASCII art header
- Pod status with health indicators
- Service endpoints and ingress URLs
- PVC usage and storage info
- Quick command reference

### 3. deploy.sh - Production Deployment

**Purpose:** Deploy to production

```bash
# Interactive deployment
./deploy.sh

# Auto-confirm (for CI/CD)
./deploy.sh --auto-confirm

# Preview only
./deploy.sh --dry-run
```

### 4. scripts/sync-api-keys.sh - API Key Sync

**Purpose:** Sync API keys between \*arr applications

```bash
# Run API key sync
./scripts/sync-api-keys.sh
```

---

## Quick Start

### Local Development

```bash
# Start development environment (from repo root)
tilt up

# Tilt UI opens at http://localhost:10350
# Access services via port-forwards (see table above)

# Make changes to manifests
vim base/sonarr/deployment.yaml

# Tilt detects and auto-applies changes

# Stop development environment
tilt down
```

### Production Access

All services are accessible via Traefik IngressRoutes:

| Service   | URL                      |
| --------- | ------------------------ |
| Prowlarr  | http://prowlarr.talos00  |
| Sonarr    | http://sonarr.talos00    |
| Radarr    | http://radarr.talos00    |
| Overseerr | http://overseerr.talos00 |
| Plex      | http://plex.talos00      |
| Jellyfin  | http://jellyfin.talos00  |
| Tdarr     | http://tdarr.talos00     |
| Homepage  | http://homepage.talos00  |

### Check Status

```bash
# Dashboard
./dashboard.sh

# Kubectl
kubectl get pods -n media
kubectl get pvc -n media
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

PostgreSQL credentials in `base/postgresql/secret.yaml`:

- `postgres-password` - Database password

Each app gets its own databases:

- `sonarr_main` / `sonarr_log`
- `radarr_main` / `radarr_log`
- `prowlarr_main` / `prowlarr_log`

### Enabling Readarr

Readarr is disabled by default due to ARM64 issues. To enable:

1. Add `readarr/` to `base/kustomization.yaml` resources
2. Add Readarr resource to `Tiltfile`

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

**Problem:** Resources stuck in Pending

```bash
# Check PVCs
kubectl get pvc -n media

# Check events
kubectl get events -n media --sort-by='.lastTimestamp'
```

### Database Issues

**Problem:** \*arr apps can't connect to PostgreSQL

```bash
# Check PostgreSQL is running
kubectl get pods -n media -l app=postgresql

# Check PostgreSQL logs
kubectl logs -n media -l app=postgresql

# Verify secret exists
kubectl get secret -n media postgresql-secret
```

### Storage Issues

**Problem:** PVCs not binding

```bash
# Check storage class
kubectl get sc

# Check PV/PVC status
kubectl get pv,pvc -n media
```

---

## Metrics & Monitoring

### Exportarr

Exportarr provides Prometheus metrics for all \*arr applications:

- Sonarr metrics: queue, calendar, wanted
- Radarr metrics: queue, calendar, wanted
- Prowlarr metrics: indexer status

Access via ServiceMonitor in `base/exportarr/servicemonitor.yaml`.

---

## Related Documentation

- [Dual GitOps Pattern](../../docs/02-architecture/dual-gitops.md)
- [Networking & Ingress](../../docs/02-architecture/networking.md)
- [Homepage Configuration](base/homepage/README.md)

---

## Notes

- **Namespace:** `media` (single namespace, no dev/prod split)
- **Readarr:** Disabled by default (ARM64 issues)
- **Exportarr:** Provides metrics for Prometheus/Grafana dashboards
- **IngressRoutes:** Each app has its own Traefik IngressRoute in its directory
