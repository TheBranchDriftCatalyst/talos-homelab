# Theme.park Overlay

Adds consistent theming across all arr-stack apps using [theme.park](https://theme-park.dev/) Docker Mods.

## Quick Start

This overlay is **Flux-managed** — it is the deployed entrypoint for the whole
arr-stack, not an optional add-on. `clusters/catalyst-cluster/arr-stack.yaml`
points the Flux Kustomization `arr-stack` (namespace `flux-system`) at
`./applications/arr-stack/overlays/themepark` with `prune: true`.

```bash
# Render locally to check your change
kubectl kustomize applications/arr-stack/overlays/themepark/

# Deploy: commit + push, then let Flux reconcile
flux reconcile kustomization arr-stack --with-source
```

Do **not** `kubectl apply -k` this path — Flux will reconcile over it on its
10m interval.

## Changing the Theme

Edit `themepark-env.yaml` and change `TP_THEME`:

```yaml
data:
  TP_THEME: 'dracula'  # Change this to any theme.park theme
```

Then commit, reconcile, and restart the pods:

```bash
flux reconcile kustomization arr-stack --with-source
kubectl rollout restart deployment -n media -l theming=themepark
```

`themepark-env` is a plain ConfigMap (no `configMapGenerator` hash suffix), so
editing it does **not** trigger a rollout on its own — the restart is required.

Note: the `theming: themepark` label comes from the overlay-wide `labels:` block
in `kustomization.yaml`, so it is on **every** Deployment in the overlay (all 14
in `media`), not just the 8 themed ones. The restart above therefore bounces the
whole namespace.

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
| Plex | `ghcr.io/themepark-dev/theme.park:plex` |
| Jellyfin | `ghcr.io/themepark-dev/theme.park:jellyfin` |
| Tautulli | `ghcr.io/themepark-dev/theme.park:tautulli` |
| qBittorrent | `ghcr.io/themepark-dev/theme.park:qbittorrent` |
| SABnzbd | `ghcr.io/themepark-dev/theme.park:sabnzbd` |

All 8 are LinuxServer.io (`lscr.io/linuxserver/*`) images, which is what makes
`DOCKER_MODS` work.

**Not themed:** Seerr runs the official `ghcr.io/seerr-team/seerr` image, which
does not bundle linuxserver's s6-overlay, so `DOCKER_MODS` cannot inject a
theme. The remaining `media` workloads (kometa, maintainerr, posterizarr,
posterr, pulsarr) are likewise non-LSIO images and are not patched. Tdarr lives
in its own namespace (`applications/tdarr`) and is outside this overlay.

## How It Works

1. Overlay chain: `base/` → `overlays/gpu/` → `overlays/themepark/`. This overlay
   lists `../gpu` in `resources:`, and the GPU overlay lists `../../base`.
2. `themepark-env.yaml` - ConfigMap with `TP_THEME` shared by all apps
3. Per-app patches add the `DOCKER_MODS` env var with the app-specific theme.park
   image, plus an `envFrom` on `themepark-env` (and `arr-common-env` for the
   \*arr/download apps)
4. LinuxServer.io containers load the theme.park mod on startup

### Gotcha: qBittorrent startup time

The theme.park mod rewrites thousands of HTML files on every container start.
For qBittorrent this took long enough to trip the liveness probe and produce a
restart loop (TALOS-0dk). The fix lives in
`applications/arr-stack/base/qbittorrent/deployment.yaml`: a `startupProbe` with
a 30-minute budget (`periodSeconds: 30`, `failureThreshold: 60`) that defers the
aggressive liveness/readiness probes until the mod has finished.

## Combining with GPU Overlay

> **No longer needed.** This section described building a separate combined
> overlay. The themepark overlay now layers directly on top of the GPU overlay
> (`resources: [../gpu]`), which in turn pulls in `../../base` — so deploying
> this overlay already gives you Intel QuickSync patches for Plex and Jellyfin
> plus theming. There is nothing to combine.

Verify with:

```bash
kubectl kustomize applications/arr-stack/overlays/themepark/ | grep -c gpu.intel.com
```

---

## Related Issues

- TALOS-0dk - qBittorrent themepark mod restart loop (closed; fixed via `startupProbe`)
