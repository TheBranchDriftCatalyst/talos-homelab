# Theme.park Overlay

Adds consistent theming across all arr-stack apps using [theme.park](https://theme-park.dev/) Docker Mods.

## Quick Start

```bash
# Deploy arr-stack with theming
kubectl apply -k applications/arr-stack/overlays/themepark/

# Or reference this overlay in ArgoCD
```

## Changing the Theme

Edit `themepark-env.yaml` and change `TP_THEME`:

```yaml
data:
  TP_THEME: 'dracula'  # Change this to any theme.park theme
```

Then reapply:

```bash
kubectl apply -k applications/arr-stack/overlays/themepark/
kubectl rollout restart deployment -n media -l theming=themepark
```

## Available Themes

See [theme.park themes](https://docs.theme-park.dev/themes/) for full list:

- `dracula` (default)
- `nord`
- `aquamarine`
- `hotline`
- `overseerr`
- `plex`
- `organizr-dark`
- `space-gray`
- `dark`
- `maroon`
- and many more...

## Apps with Theming

| App | Docker Mod |
|-----|------------|
| Sonarr | `ghcr.io/themepark-dev/theme.park:sonarr` |
| Radarr | `ghcr.io/themepark-dev/theme.park:radarr` |
| Prowlarr | `ghcr.io/themepark-dev/theme.park:prowlarr` |
| Overseerr | `ghcr.io/themepark-dev/theme.park:overseerr` |
| Plex | `ghcr.io/themepark-dev/theme.park:plex` |
| Jellyfin | `ghcr.io/themepark-dev/theme.park:jellyfin` |
| Tautulli | `ghcr.io/themepark-dev/theme.park:tautulli` |
| qBittorrent | `ghcr.io/themepark-dev/theme.park:qbittorrent` |
| SABnzbd | `ghcr.io/themepark-dev/theme.park:sabnzbd` |

## How It Works

1. `themepark-env.yaml` - ConfigMap with `TP_THEME` shared by all apps
2. Per-app patches add `DOCKER_MODS` env var with app-specific theme.park image
3. LinuxServer.io containers load the theme.park mod on startup

## Combining with GPU Overlay

To use both GPU acceleration and theming:

```yaml
# Create a combined overlay
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../themepark
patches:
  # Include GPU patches from gpu overlay
  - path: ../gpu/plex-gpu-patch.yaml
    target:
      kind: Deployment
      name: plex
  # ... etc
```
