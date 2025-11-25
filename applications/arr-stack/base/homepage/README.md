# Homepage Dashboard Configuration

This directory contains the Homepage dashboard configuration for the Talos homelab cluster.

## Overview

Homepage is configured with ConfigMaps containing all service definitions, widgets, and settings. The configuration is mounted into the pod at `/app/config/`.

## Configuration Files

- **configmap.YAML** - Core settings (settings.YAML, Kubernetes.YAML)
- **configmap-services.YAML** - Service definitions, widgets, bookmarks, Docker config
- **deployment.YAML** - Homepage pod deployment
- **service.YAML** - Kubernetes service
- **serviceaccount.YAML** - RBAC permissions for Kubernetes API access
- **pvc.YAML** - Persistent volume (currently not used, configs in ConfigMaps)
- **ingressroute.YAML** - Traefik ingress route

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

Homepage widgets use template variables for API keys that are synced from 1Password using External Secrets Operator.

### Setup via 1Password (Recommended - Already Configured)

The ExternalSecret is already configured in `externalsecret.yaml`. You just need to create the 1Password item:

**See [ONEPASSWORD-SETUP.md](./ONEPASSWORD-SETUP.md) for complete setup instructions.**

Quick summary:

1. Create a 1Password item named `arr-stack-credentials` in the `catalyst-eso` vault
2. Add fields for each API key (sonarr_api_key, radarr_api_key, etc.)
3. The ExternalSecret will automatically sync to a Kubernetes secret
4. Homepage deployment is already configured to use the secret

### Alternative: Manual Secret Creation

If you're not using 1Password/ESO, create a secret manually:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: homepage-secrets
  namespace: media-dev
type: Opaque
stringData:
  HOMEPAGE_VAR_SONARR_KEY: 'your-sonarr-api-key'
  HOMEPAGE_VAR_RADARR_KEY: 'your-radarr-api-key'
  HOMEPAGE_VAR_READARR_KEY: 'your-readarr-api-key'
  HOMEPAGE_VAR_PROWLARR_KEY: 'your-prowlarr-api-key'
  HOMEPAGE_VAR_PLEX_KEY: 'your-plex-token'
  HOMEPAGE_VAR_JELLYFIN_KEY: 'your-jellyfin-api-key'
  HOMEPAGE_VAR_OVERSEERR_KEY: 'your-overseerr-api-key'
  HOMEPAGE_VAR_ARGOCD_KEY: 'your-argocd-token'
  HOMEPAGE_VAR_GRAFANA_USER: 'admin'
  HOMEPAGE_VAR_GRAFANA_PASS: 'your-grafana-password'
```

The deployment is already configured to use this secret via `envFrom`.

### Option 3: Direct ConfigMap Edit (Not Recommended)

Edit the `configmap-services.yaml` and replace the template variables with actual values:

```bash
kubectl edit configmap homepage-services -n media-dev
```

Replace `{{HOMEPAGE_VAR_SONARR_KEY}}` with actual API key, etc.

## Getting API Keys

### \*arr Applications (Sonarr, Radarr, Readarr, Prowlarr)

1. Log into the application web UI
2. Go to Settings → General
3. Copy the API Key

### Plex

1. Follow instructions at: https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/
2. Or use: Settings → Account → XML → Look for `PlexToken`

### Jellyfin

1. Dashboard → API Keys
2. Create a new API key for "Homepage Dashboard"

### Overseerr

1. Settings → General → API Key
2. Copy the API key

### ArgoCD

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

### Grafana

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

1. Check API keys are correctly configured
2. Verify service URLs are accessible from within the cluster
3. Check logs:
   ```bash
   kubectl logs -n media-dev -l app=homepage
   ```

### Permission Errors

The ServiceAccount needs ClusterRole permissions to read Kubernetes resources. Verify:

```bash
kubectl get clusterrolebinding homepage -o yaml
```

### Configuration Not Updating

After changing ConfigMaps, restart the pod:

```bash
kubectl rollout restart deployment homepage -n media-dev
```

## References

- [Homepage Documentation](https://gethomepage.dev/)
- [Service Widgets](https://gethomepage.dev/widgets/services/)
- [Settings Configuration](https://gethomepage.dev/configs/settings/)
- [Kubernetes Integration](https://gethomepage.dev/configs/kubernetes/)
