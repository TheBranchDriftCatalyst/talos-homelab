# Flux Bootstrap

This directory contains the Flux CD bootstrap configuration for the homelab cluster.

## Installation

Flux will be installed using the official CLI tool and bootstrap process:

```bash
# Install Flux CLI (macOS)
brew install fluxcd/tap/flux

# Or using curl
curl -s https://fluxcd.io/install.sh | sudo bash

# Bootstrap Flux (when Git repo is ready)
flux bootstrap github \
  --owner=<your-github-username> \
  --repository=<your-repo-name> \
  --branch=main \
  --path=clusters/homelab-single \
  --personal
```

## Directory Structure

After bootstrap, Flux will manage:

- `infrastructure/` - Infrastructure components (storage, networking, monitoring)
- `applications/` - Application deployments (arr stack, media servers)
- `clusters/homelab-single/` - Cluster-specific configuration

## Components Managed by Flux

### Infrastructure
- Local-path-provisioner (storage)
- NFS CSI driver (Synology storage)
- Traefik (ingress controller) - already manually installed
- Metrics-server - already manually installed
- kube-prometheus-stack (monitoring)
- ArgoCD (application GitOps)

### Post-Bootstrap Steps

1. Create Git repository for GitOps manifests
2. Push all manifests to the repository
3. Run flux bootstrap command with repository details
4. Verify reconciliation: `flux get all`
5. Check kustomizations: `flux get kustomizations`

## Manual Installation (Alternative)

If you prefer to install Flux manually without bootstrap:

```bash
# Install Flux components
flux install --export > bootstrap/flux/flux-components.yaml
kubectl apply -f bootstrap/flux/flux-components.yaml

# Create GitRepository source
kubectl apply -f clusters/homelab-single/flux-system/sources/git-repo.yaml

# Create root Kustomization
kubectl apply -f clusters/homelab-single/flux-system/kustomizations/root.yaml
```

## Verification

```bash
# Check Flux system
flux check

# Watch reconciliation
flux get kustomizations --watch

# View logs
flux logs --all-namespaces --follow
```
