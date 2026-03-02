# Tilt Shared Modules

Reusable Starlark modules for Tilt infrastructure.

## Usage

Load modules from your Tiltfile:

```python
# Relative import (from application Tiltfile)
load('../../tilt/_shared/labels.star', 'LABELS')
load('../../tilt/_shared/kometa_ops.star', 'kometa_buttons')

# From root Tiltfile
load('./tilt/_shared/labels.star', 'LABELS')
load('./tilt/_shared/flux_ops.star', 'flux_nav_button')
```

## Modules

| Module | Description |
|--------|-------------|
| `labels.star` | Centralized label constants for UI grouping |
| `kometa_ops.star` | Kometa operation buttons (Run, Overlays, Collections) |
| `homepage_ops.star` | Homepage API sync button |
| `flux_ops.star` | Flux GitOps nav buttons (sync, suspend, resume) |
| `cluster_ops.star` | Cluster maintenance nav buttons (cleanup, health) |
| `ollama_ops.star` | Ollama model management buttons |

## Label Hierarchy

Labels control sidebar grouping in Tilt UI (sorted alphabetically):

```
1-apps-media     - Media automation (arr stack, plex, jellyfin)
1-apps-home      - Home automation (homeassistant, linkwarden)
1-apps-gaming    - Gaming (VMs, opensim, guacamole)
2-infra-platform - Platform services (ArgoCD, Traefik, Registry)
3-infra-observe  - Observability (Grafana, Loki, Tempo)
4-tools          - Testing/debug tools
5-ops            - Operations (cluster status, GPU tests)
6-vpn-gateway    - VPN services
7-catalyst-llm   - LLM infrastructure
8-local-dev      - Local development resources
```
