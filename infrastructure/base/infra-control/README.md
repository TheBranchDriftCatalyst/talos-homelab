# Infrastructure Testing UI Tools

This directory contains Kubernetes manifests for deploying UI and visualization tools to the `infra-control` namespace.

## Tools Included

- **Headlamp** - Modern Kubernetes management UI
- **Kubeview** - Visual graph of resource relationships
- **Kube-ops-view** - Real-time cluster visualization
- **Goldilocks** - Resource right-sizing recommendations (includes VPA)

## Quick Deploy

```bash
# Deploy all tools
task infra:deploy-infra-control

# Or manually
kubectl apply -k infrastructure/base/infra-control/
```

## Access

All tools are accessible via Traefik IngressRoutes:

- http://headlamp.talos00
- http://kubeview.talos00
- http://kube-ops-view.talos00
- http://goldilocks.talos00

**Prerequisites**: Add to `/etc/hosts`:

```
192.168.1.54  headlamp.talos00 kubeview.talos00 kube-ops-view.talos00 goldilocks.talos00
```

## Management

```bash
# Check status
task infra:infra-control-status

# View logs
task infra:infra-control-logs TOOL=headlamp

# Delete all
task infra:infra-control-delete
```

## Documentation

See [docs/infra-control-tools.md](/docs/infra-control-tools.md) for:

- Detailed usage instructions
- Feature descriptions
- Troubleshooting
- Integration with existing monitoring stack

## Directory Structure

```
infra-control/
├── namespace/           # Namespace definition
├── headlamp/           # Modern K8s UI
├── kubeview/           # Resource visualizer
├── kube-ops-view/      # Real-time cluster view
├── goldilocks/         # Resource recommendations + VPA
└── kustomization.yaml  # Main kustomization
```

Each subdirectory contains:

- `deployment.yaml` or `helmrelease.yaml` - Kubernetes resources
- `ingressroute.yaml` - Traefik routing configuration
- `kustomization.yaml` - Kustomize configuration
