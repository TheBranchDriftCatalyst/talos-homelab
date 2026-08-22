# Arr-Stack - Media Automation

Media automation stack including indexers, download clients, and media servers for TV shows and movies.

**Key facts:**

- **Namespace:** `media` (single namespace, no dev/prod split)
- **Deployed by Flux**, not ArgoCD — `clusters/catalyst-cluster/arr-stack.yaml` points at
  `applications/arr-stack/overlays/themepark` (layer chain: `base` -> `overlays/gpu` -> `overlays/themepark`)
- **Access:** `https://<app>.talos00` via Traefik + Authentik forward-auth SSO.
  Plex and Jellyfin are the exceptions — they serve on the plain `web` entrypoint with their own auth.
- **Storage:** app config on `fatboy-nfs-appdata` (NFS `192.168.1.36:/volume1/appdata`),
  SQLite DBs on `local-path` (node NVMe), media + downloads on `synology-nfs` (RWX)

---

## Components

### Indexer & Management

- **Prowlarr** - Indexer manager for Usenet and torrents

### Media Automation

- **Sonarr** - TV show management
- **Radarr** - Movie management
- **Seerr** - Request management (overseerr fork, `ghcr.io/seerr-team/seerr`)
- **Pulsarr** - Plex watchlist -> Sonarr/Radarr sync
- **Maintainerr** - Rule-based library / collection cleanup

### Download Clients

- **SABnzbd** - Usenet downloader
- **qBittorrent** - Torrent downloader; the pod runs three containers — `qbittorrent`,
  a `gluetun` VPN sidecar (pinned `qmcgaw/gluetun:v3.41.3`), and a `port-sync` sidecar
  that pushes the forwarded port into qBittorrent

### Media Servers

- **Plex** - Media server (Intel QuickSync hardware transcoding via the `gpu` overlay)
- **Jellyfin** - Open-source media server (also GPU-patched)

### Plex Tooling

- **Tautulli** - Plex monitoring and stats
- **Kometa** - Metadata / collection manager
- **Posterizarr** - Automated poster maker (Fanart.tv / TMDB / TVDB)
- **Posterr** - Now-playing / recently-added display board

### Moved or Removed

- **Tdarr** - moved to `applications/tdarr/` (own `tdarr` namespace, own Flux Kustomization,
  universal GPU DaemonSet). No longer part of this stack.
- **Homepage** - moved to `applications/homepage/` (own `homepage` namespace, multi-instance
  boards — TALOS-qt7u). Flux `prune: true` garbage-collected the old media-namespace copy.
- **Readarr** - no longer deployed. `base/readarr/` still exists on disk but is **not**
  referenced by `base/kustomization.yaml`. Book / comic / audiobook managers now live in
  `applications/media-experimental/` as a "Readarr-replacement bake-off"
  (chaptarr, bindery, librarr, livrarr, mylar3).
- **PostgreSQL** - there is no shared Postgres in this stack. The \*arr apps use SQLite
  (see [Database & Storage Layout](#database--storage-layout)). `base/sonarr/db-config.yaml`
  and `base/migration/` are leftovers from the abandoned Postgres attempt and are not
  referenced by any kustomization.
- **Exportarr** - `base/exportarr/` exists on disk but is **not** referenced by
  `base/kustomization.yaml`; nothing is deployed and no exportarr ServiceMonitors exist.

---

## Directory Structure

```
arr-stack/
├── Tiltfile                  # Tilt attach/observe config (Flux owns deploys)
├── dashboard.sh              # Passthrough to scripts/namespace-dashboard.sh media
├── deploy.sh                 # STALE - see note below
├── README.md                 # This file
│
├── base/                     # Base Kubernetes manifests
│   ├── kustomization.yaml    # Main kustomization (namespace: media)
│   ├── common-env.yaml       # arr-common-env ConfigMap (PUID/PGID/TZ)
│   ├── shared/               # sqlite-db-migration ConfigMap + arr-stack-secrets ExternalSecret
│   ├── prowlarr/  sonarr/  radarr/
│   ├── sabnzbd/  qbittorrent/
│   ├── seerr/  pulsarr/  maintainerr/
│   ├── plex/  jellyfin/
│   ├── tautulli/  kometa/  posterizarr/  posterr/
│   ├── readarr/              # NOT in kustomization (not deployed)
│   ├── exportarr/            # NOT in kustomization (not deployed)
│   └── migration/            # NOT in kustomization (legacy one-shot job)
│
├── overlays/
│   ├── gpu/                  # Intel QuickSync patches for plex + jellyfin
│   └── themepark/            # theme.park Docker Mods; THIS is the overlay Flux deploys
│
└── scripts/
    └── sync-api-keys.sh      # Legacy API-key scraper - see note below
```

---

## Development Workflow

### 1. Tiltfile - Attach / Observe

**Purpose:** attach to the live cluster for logs, port-forwards and dev buttons.

This is **not** a hot-reload dev loop. The Tiltfile uses `k8s_attach` only — it never applies
manifests. Flux owns every deployment in this namespace; to change something you commit to
git and let Flux reconcile.

```bash
# Standalone (from repo root)
tilt up -f applications/arr-stack/Tiltfile

# Tilt UI: http://localhost:10350

tilt down
```

The root `Tiltfile` does **not** `include()` this file — it declares its own `k8s_attach`
entries for the `media` namespace.

**Features:**

- Port-forwards services to localhost
- Resource grouping and log viewing
- Kometa ops buttons (`tilt/_shared/kometa_ops.star`)
- "Sync API Keys" button (`tilt/_shared/homepage_ops.star`) — see the caveat below

**Port Forwards** (as declared in `applications/arr-stack/Tiltfile`):

| Service     | Local Port | URL                         |
| ----------- | ---------- | --------------------------- |
| Prowlarr    | 9696       | http://localhost:9696       |
| Sonarr      | 8989       | http://localhost:8989       |
| Radarr      | 7878       | http://localhost:7878       |
| Seerr       | 5055       | http://localhost:5055       |
| SABnzbd     | 8080       | http://localhost:8080       |
| Plex        | 32400      | http://localhost:32400/web  |
| Jellyfin    | 8096       | http://localhost:8096       |
| Tautulli    | 8181       | http://localhost:8181       |
| Posterizarr | 8000       | http://localhost:8000       |
| Posterr     | 3002       | http://localhost:3002       |
| Kometa      | —          | (attached, no port-forward) |

> **Stale entries:** the Tiltfile still declares `tdarr` (8265) and `homepage` (3001) in
> namespace `media`. Both have moved out of this namespace, so those two resources will not
> attach. It also calls `allow_k8s_contexts('admin@homelab-single')`, but the cluster context
> is `admin@catalyst-cluster`.

### 2. dashboard.sh - Status Dashboard

**Purpose:** display current namespace status. It is a thin passthrough that `exec`s the
repo-level `scripts/namespace-dashboard.sh` against the `media` namespace.

```bash
# Pass through any args
./dashboard.sh

# Full gum-based dashboard (no extra args forwarded)
./dashboard.sh --full
```

### 3. deploy.sh - STALE, do not use

`deploy.sh` targets `NAMESPACE=media-prod` and `OVERLAY=overlays/prod`. **Neither exists** —
the namespace is `media` and the only overlays are `gpu` and `themepark`. It also commits,
pushes and reconciles on your behalf.

Deployment is Flux's job. Commit and push, then:

```bash
flux reconcile source git flux-system
flux reconcile kustomization arr-stack --with-source
```

### 4. scripts/sync-api-keys.sh - Legacy

**Purpose (historical):** scrape API keys out of running pods into an `arr-api-keys` Secret
in ns `media`, for the Homepage dashboard to consume via `envFrom`.

That path is dead: no `arr-api-keys` Secret exists in the cluster and Homepage has moved to
its own namespace. API keys now come from 1Password via the `arr-stack-secrets` ExternalSecret
(`base/shared/external-secret.yaml`) and are mirrored into ns `homepage` by emberstack/reflector.
The Tilt "Sync API Keys" button still runs this script and then restarts
`deploy/homepage -n media`, which no longer exists.

---

## Quick Start

### Attach to the Live Stack

```bash
# From repo root
tilt up -f applications/arr-stack/Tiltfile

# Tilt UI opens at http://localhost:10350
# Access services via port-forwards (see table above)

tilt down
```

Manifest changes are **not** applied by Tilt — commit them and let Flux reconcile.

### Production Access

All services are reachable through Traefik. `*.talos00` must resolve to the Traefik
LoadBalancer VIP (`192.168.1.251`).

| Service     | URL                         | Auth             |
| ----------- | --------------------------- | ---------------- |
| Prowlarr    | https://prowlarr.talos00    | Authentik SSO    |
| Sonarr      | https://sonarr.talos00      | Authentik SSO    |
| Radarr      | https://radarr.talos00      | Authentik SSO    |
| Seerr       | https://seerr.talos00       | Authentik SSO    |
| SABnzbd     | https://sabnzbd.talos00     | Authentik SSO    |
| qBittorrent | https://qbittorrent.talos00 | Authentik SSO    |
| Maintainerr | https://maintainerr.talos00 | Authentik SSO    |
| Pulsarr     | https://pulsarr.talos00     | Authentik SSO    |
| Tautulli    | https://tautulli.talos00    | Authentik SSO    |
| Posterizarr | https://posterizarr.talos00 | Authentik SSO    |
| Posterr     | https://posterr.talos00     | Authentik SSO    |
| Plex        | http://plex.talos00         | Plex account     |
| Jellyfin    | http://jellyfin.talos00     | Jellyfin account |

Routing details:

- Every SSO'd app has a **high-priority `/api` rule with no auth middleware** (the \*arr trio
  also exempts `/feed`) so API-key clients (nzb360, LunaSea) and RSS keep working.
- Each SSO'd app also has a companion `<app>-http` IngressRoute on the `web` entrypoint that
  redirects to HTTPS via the `redirect-https` middleware in ns `traefik`.
- The `tls: {}` stanza is **not** written by hand — the Kyverno ClusterPolicy
  `infrastructure/base/kyverno-policies/ingressroute-tls-default.yaml` adds it to every
  `websecure` IngressRoute (default TLSStore serves the `*.talos00` wildcard).
- Homepage annotations are likewise partly derived: `href`, `widget.url`, `siteMonitor` and
  `instance` come from `homepage-annotation-derivation.yaml` / `homepage-instance-assignment.yaml`.
  Only the genuinely-unique ones (name/group/icon/description/widget.type/widget.key) are hand-set.

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

Shared environment variables in `base/common-env.yaml` (ConfigMap `arr-common-env`):

- `PUID=1000` / `PGID=1000` - User/group IDs (LinuxServer.io images)
- `TZ=America/Los_Angeles` - Timezone

There are no `POSTGRES_*` keys — the shared-Postgres design was dropped.

### Secrets

`base/shared/external-secret.yaml` defines the `arr-stack-secrets` ExternalSecret
(ClusterSecretStore `onepassword`, `refreshInterval: 1h`, `mergePolicy: Merge`):

- API keys: sonarr, radarr, prowlarr, sabnzbd, jellyfin, overseerr
- ASP.NET DataProtection encryption keys: sonarr, radarr, prowlarr
- SABnzbd password

It carries emberstack/reflector annotations so the Secret is mirrored into ns `homepage` for
the dashboard widgets.

Other Secrets in ns `media`: `kometa-credentials`, `protonvpn-credentials` (gluetun),
`qbittorrent-webui`, `tautulli-api-key`, `ghcr-secret`.

### Database & Storage Layout

No database server. Each \*arr keeps its own SQLite, split across two volumes because SQLite
locks badly over NFS:

| Volume           | StorageClass         | Contents                                   |
| ---------------- | -------------------- | ------------------------------------------ |
| `<app>-config`   | `fatboy-nfs-appdata` | `config.xml`, logs, app state              |
| `<app>-db-local` | `local-path`         | the SQLite `.db` files (node NVMe)         |
| `synology-*`     | `synology-nfs`       | tv, movies, books, downloads (RWX, shared) |

Apps with a `db-local` volume: sonarr, radarr, prowlarr, plex, jellyfin.

`base/shared/db-migration-configmap.yaml` (ConfigMap `sqlite-db-migration`) provides the
init-container scripts that copy databases off NFS onto local storage on first run. Because
`local-path` is node-local, **sonarr and radarr are pinned to `talos03`** via `nodeAffinity`.

Velero backups are scoped with `backup.velero.io/backup-volumes: "config,db-local"` — media
and downloads volumes are deliberately excluded.

### Overlays

- `overlays/gpu` — Intel QuickSync device patches for `plex` and `jellyfin`.
  Requires the Intel GPU device plugin (`infrastructure/base/intel-gpu/`); the Flux
  Kustomization `dependsOn` it.
- `overlays/themepark` — layers on top of `../gpu` and applies theme.park Docker Mods
  (theme set once in `themepark-env.yaml`) to sonarr, radarr, prowlarr, plex, jellyfin,
  tautulli, qbittorrent, sabnzbd. Seerr is excluded — its official image has no s6-overlay,
  so `DOCKER_MODS` cannot inject themes.

---

## Troubleshooting

### Tilt Issues

**Problem:** Tilt can't connect to Kubernetes

```bash
# Verify context
kubectl config current-context
# Should be: admin@catalyst-cluster
# (note: the Tiltfile's allow_k8s_contexts() still names an older context)

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

The \*arr apps use SQLite, not a database server. Symptoms usually mean the `db-local` volume
did not mount or the migration init-container failed.

```bash
# Check the migration init-container
kubectl logs -n media deploy/sonarr -c migrate-db

# Confirm both volumes are bound
kubectl get pvc -n media | grep -E 'sonarr|radarr|prowlarr'

# Node pinning: sonarr/radarr require talos03 (local-path is node-local)
kubectl get pods -n media -o wide
```

### Storage Issues

```bash
# Check storage class
kubectl get sc
# Expected: local-path (default), fatboy-nfs-appdata, synology-nfs

# Check PV/PVC status
kubectl get pv,pvc -n media
```

### Flux Issues

```bash
flux get kustomization arr-stack
flux reconcile kustomization arr-stack --with-source
```

---

## Metrics & Monitoring

**Exportarr is not deployed.** `base/exportarr/` contains Deployment / Service / ServiceMonitor
manifests for prowlarr, sonarr, radarr and readarr exporters, but the directory is not listed
in `base/kustomization.yaml`, so nothing is reconciled and no exportarr metrics exist.

The only ServiceMonitor live in ns `media` is `qbittorrent-vpn`
(`base/qbittorrent/servicemonitor.yaml`), which scrapes the gluetun sidecar.

Cluster metrics land in Mimir and are visualised in Grafana; logs go to Loki.

---

## Related Documentation

- [Dual GitOps Pattern](../../docs/02-architecture/dual-gitops.md)
- [Networking & Ingress](../../docs/02-architecture/networking.md)
- [Homepage dashboard](../homepage/) — migrated out of this stack (ns `homepage`)
- [Tdarr](../tdarr/) — migrated out of this stack (ns `tdarr`)
- [Media experimental (book/comic/audiobook bake-off)](../media-experimental/)

---

## Notes

- **Namespace:** `media` (single namespace, no dev/prod split)
- **GitOps owner:** Flux (`clusters/catalyst-cluster/arr-stack.yaml`), not ArgoCD
- **Deployed path:** `overlays/themepark` (which pulls in `overlays/gpu`, which pulls in `base`)
- **IngressRoutes:** each app has its own Traefik IngressRoute in its directory; `tls: {}` and
  the homepage `href`/`widget.url`/`siteMonitor`/`instance` annotations are injected by
  Kyverno ClusterPolicies
- **Not deployed but still on disk:** `base/readarr/`, `base/exportarr/`, `base/migration/`,
  `base/sonarr/db-config.yaml`, `base/shared/_downloads-local-pvc.yaml`

## Related Docs

- [overlays/themepark/README.md](overlays/themepark/README.md) — the overlay Flux actually deploys (theme.park Docker Mods)
- [docs/02-architecture/dual-gitops.md](../../docs/02-architecture/dual-gitops.md) — why this stack is Flux-owned, not ArgoCD
- [docs/02-architecture/auth-implementation-guide.md](../../docs/02-architecture/auth-implementation-guide.md) — the Authentik SSO in front of these apps
- [docs/INDEX.md](../../docs/INDEX.md) — all documentation

---

## Related Issues

<!-- Beads tracking for this doc -->

- TALOS-937u - Structural DRY: media-experimental (pilot) then arr-stack base/instance model
- TALOS-qt7u - Split homepage into per-domain boards (homepage left ns `media`)
