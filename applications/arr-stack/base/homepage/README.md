# Homepage Dashboard Configuration

This directory contains the Homepage dashboard configuration for the Talos homelab cluster.

## Overview

Homepage is configured with ConfigMaps containing all service definitions, widgets, and settings. The configuration is mounted into the pod at `/app/config/`.

## Configuration Files

- **configmap.yaml** - Core settings (settings.yaml, kubernetes.yaml)
- **configmap-services.yaml** - Service definitions, widgets, bookmarks, Docker config
- **deployment.yaml** - Homepage pod deployment
- **service.yaml** - Kubernetes service
- **serviceaccount.yaml** - RBAC permissions for Kubernetes API access
- **pvc.yaml** - Persistent volume (currently not used, configs in ConfigMaps)
- **ingressroute.yaml** - Traefik ingress route
- **secret.yaml** - API keys secret (auto-synced from running services)

## Configured Services

### Media Management

- **Sonarr** - TV series management (widget enabled)
- **Radarr** - Movie management (widget enabled)
- **Readarr** - Book management (widget enabled)
- **Prowlarr** - Indexer manager (widget enabled)

### Media Servers

- **Plex** - Media server (widget enabled)
- **Jellyfin** - Free media server (widget enabled)
- **Overseerr** - Request management (widget enabled)
- **Tdarr** - Media transcoding (widget enabled)

### Infrastructure

- **ArgoCD** - GitOps CD (widget enabled)
- **Traefik** - Ingress controller (widget enabled)
- **Registry** - Container registry
- **Bastion** - Jump host / debug pod

### Monitoring

- **Grafana** - Metrics visualization (widget enabled)
- **Prometheus** - Metrics collection (widget enabled)
- **Alertmanager** - Alert management
- **Graylog** - Log management

### Testing Tools

- **Headlamp** - Kubernetes UI
- **Kubeview** - K8s visualizer
- **Goldilocks** - Resource recommendations
- **Kube Ops View** - Cluster overview

## API Key Configuration

Homepage widgets require API keys which are automatically synced from running services.

### Automatic API Key Sync (Recommended)

The *arr applications generate API keys on first startup. These can be automatically
extracted and synced to the Kubernetes secret using:

```bash
# Sync API keys from all running services
./scripts/sync-api-keys.sh

# Preview what would be synced (dry run)
./scripts/sync-api-keys.sh --dry-run

# Sync a single service
./scripts/sync-api-keys.sh --service sonarr
```

The sync script:
1. Extracts API keys from `/config/config.xml` in *arr containers
2. Gets Overseerr key from `/config/settings.json`
3. Gets Plex token from `Preferences.xml` (if claimed)
4. Creates/updates `arr-api-keys` secret
5. Patches `homepage-secrets` with the synced keys

**Run this after deploying services for the first time, or whenever you need to refresh keys.**

### Secret Structure

The `homepage-secrets` secret contains:

```yaml
stringData:
  # *arr API keys (auto-synced)
  HOMEPAGE_VAR_SONARR_KEY: "<extracted from running service>"
  HOMEPAGE_VAR_RADARR_KEY: "<extracted from running service>"
  HOMEPAGE_VAR_PROWLARR_KEY: "<extracted from running service>"
  HOMEPAGE_VAR_READARR_KEY: "<extracted from running service>"
  HOMEPAGE_VAR_OVERSEERR_KEY: "<extracted from running service>"
  HOMEPAGE_VAR_PLEX_KEY: "<extracted from running service>"
  HOMEPAGE_VAR_JELLYFIN_KEY: "<manual - create in Jellyfin UI>"

  # Infrastructure (set manually or via separate sync)
  HOMEPAGE_VAR_ARGOCD_KEY: "<argocd token>"
  HOMEPAGE_VAR_GRAFANA_USER: "admin"
  HOMEPAGE_VAR_GRAFANA_PASS: "prom-operator"
```

### Manual API Key Sources

For keys that can't be auto-synced:

#### Jellyfin
1. Dashboard -> API Keys
2. Create a new API key for "Homepage Dashboard"

#### ArgoCD
1. Create a readonly account:
   ```bash
   kubectl edit cm argocd-cm -n argocd
   ```
   Add:
   ```yaml
   data:
     accounts.readonly: apiKey
   ```

2. Configure RBAC:
   ```bash
   kubectl edit cm argocd-rbac-cm -n argocd
   ```
   Add:
   ```yaml
   data:
     policy.csv: |
       g, readonly, role:readonly
   ```

3. Generate token:
   ```bash
   argocd account generate-token --account readonly
   ```

#### Grafana
- Default: username `admin`, password `prom-operator`
- Or get from secret:
  ```bash
  kubectl get secret prometheus-grafana -n monitoring -o jsonpath="{.data.admin-password}" | base64 -d
  ```

## Access

Once deployed, access the dashboard at:

- **URL**: http://homepage.talos00
- **Port**: 3000

## Customization

### Modify Services

Edit `configmap-services.yaml` to add/remove services or change widget configurations.

### Change Theme

Edit `configmap.yaml` and modify the `settings.yaml` section:

- `theme: dark` or `light`
- `color: slate` (options: slate, gray, zinc, neutral, stone, red, orange, amber, yellow, lime, green, emerald, teal, cyan, sky, blue, indigo, violet, purple, fuchsia, pink, rose)

### Add Bookmarks

Edit the `bookmarks.yaml` section in `configmap-services.yaml`.

### Modify Layout

Edit the `layout:` section in `configmap.yaml` to change columns, styles, etc.

## Troubleshooting

### Widgets Not Loading

1. Check API keys are correctly synced: `./scripts/sync-api-keys.sh --dry-run`
2. Verify service URLs are accessible from within the cluster
3. Check logs:
   ```bash
   kubectl logs -n media-prod -l app=homepage
   ```

### Permission Errors

The ServiceAccount needs ClusterRole permissions to read Kubernetes resources. Verify:

```bash
kubectl get clusterrolebinding homepage -o yaml
```

### Configuration Not Updating

After changing ConfigMaps, restart the pod:

```bash
kubectl rollout restart deployment homepage -n media-prod
```

### API Keys Showing "pending-sync"

Run the sync script to extract keys from running services:

```bash
./scripts/sync-api-keys.sh
```

## References

- [Homepage Documentation](https://gethomepage.dev/)
- [Service Widgets](https://gethomepage.dev/widgets/services/)
- [Settings Configuration](https://gethomepage.dev/configs/settings/)
- [Kubernetes Integration](https://gethomepage.dev/configs/kubernetes/)
