# Tilt Shared Modules

Reusable Starlark modules for Tilt infrastructure.

## Usage

```python
# From root Tiltfile
load('./tilt/_shared/labels.star', 'LABELS')
load('./tilt/_shared/flux_ops.star', 'flux_nav_button')

# From application Tiltfile
load('../../tilt/_shared/kometa_ops.star', 'kometa_buttons')
```

## Modules

| Module | Exports |
|--------|---------|
| `labels.star` | `LABELS` struct (MEDIA, HOME, GAMING, PLATFORM, etc.) |
| `flux_ops.star` | `flux_nav_button()` |
| `cluster_ops.star` | `cleanup_nav_button()`, `health_nav_button()`, `pods_nav_button()` |
| `kometa_ops.star` | `kometa_buttons(resource, namespace)` |
| `homepage_ops.star` | `homepage_sync_button(resource, script, namespace)` |
| `ollama_ops.star` | `ollama_buttons(resource, namespace)` |
