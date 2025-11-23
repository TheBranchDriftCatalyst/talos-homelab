# Catalyst UI Deployment Setup

## Overview

This document describes the setup for deploying catalyst-ui to the Talos Kubernetes cluster using ArgoCD GitOps.

## Status: IN PROGRESS

The infrastructure is set up but ArgoCD deployment is currently paused pending Docker Desktop issues.

## Components

### 1. Docker Registry
- **Location**: `registry` namespace
- **Service**: `docker-registry` (ClusterIP + NodePort)
- **Storage**: 50Gi PVC using `local-path` storage class
- **Access**:
  - Internal: `http://docker-registry.registry.svc.cluster.local:5000`
  - Traefik HTTP: `http://registry.talos00` (IngressRoute)
  - NodePort: `192.168.1.54:32553` (not externally accessible on Talos)

**Note**: NodePort is not accessible from outside the cluster on Talos. Use kubectl port-forward for external access.

### 2. ArgoCD Application

Location: `infrastructure/base/argocd/applications/catalyst-ui.yaml`

- **Source**: https://github.com/TheBranchDriftCatalyst/catalyst-ui.git
- **Path**: `k8s/`
- **Target Namespace**: `catalyst`
- **Sync Policy**: Automated with self-healing
- **Image Override**: Uses `registry.talos00/catalyst-ui:latest`

### 3. Catalyst UI Kubernetes Manifests

Location: `~/catalyst-devspace/workspace/catalyst-ui/k8s/`

Files:
- `namespace.yaml` - Creates `catalyst` namespace
- `deployment.yaml` - Runs catalyst-ui pods (2 replicas)
- `service.yaml` - ClusterIP service
- `ingressroute.yaml` - Traefik routing to `http://catalyst.talos00`
- `kustomization.yaml` - Kustomize configuration
- `README.md` - Deployment instructions

### 4. Build and Deploy Script

Location: `scripts/build-and-deploy-catalyst-ui.sh`

**What it does**:
1. Verifies catalyst-ui directory exists
2. Ensures registry is deployed and ready
3. Gets git hash for image tagging
4. Builds Docker image using existing catalyst-ui Dockerfile
5. Sets up kubectl port-forward to registry (localhost:5000)
6. Pushes image to registry via port-forward
7. Applies ArgoCD Application manifest
8. Waits for ArgoCD to sync

**Usage**:
```bash
./scripts/build-and-deploy-catalyst-ui.sh
```

### 5. Dockerfile

Location: `~/catalyst-devspace/workspace/catalyst-ui/Dockerfile`

**Build Strategy**:
- Multi-stage build (Node 24 + nginx:alpine)
- Uses existing `yarn build:app` command
- Configured for production with `VITE_BASE_PATH=/` and `NODE_ENV=production`
- Runs as non-root `nginx` user
- Includes custom nginx config for SPA routing

## Docker Configuration

**Required**: Docker Desktop must trust the local registry

File: `~/.docker/daemon.json`
```json
{
  "insecure-registries": [
    "registry.talos00",
    "192.168.1.54:32553",
    "localhost:5000"
  ]
}
```

After updating, restart Docker Desktop.

## Access URLs

Once deployed:
- **ArgoCD UI**: http://argocd.talos00
- **Registry UI**: http://registry.talos00
- **Catalyst UI**: http://catalyst.talos00

## Current Issues

### Docker Desktop Restart Problems
Docker Desktop has been experiencing issues restarting after daemon.json updates. The configuration is valid but Docker takes a long time to start or fails to start.

**Workaround**: Manually restart Docker Desktop through macOS menu bar.

### Registry Access
- **HTTP via Traefik**: The registry is accessible via Traefik on port 80, but Docker's registry client has issues with the blob upload endpoints returning 404 errors.
- **NodePort**: NodePort services are not externally accessible on Talos Linux.
- **Current Solution**: Use `kubectl port-forward` to localhost:5000 for pushing images.

## Next Steps

1. Resolve Docker Desktop restart issues
2. Successfully push catalyst-ui image to registry
3. Verify ArgoCD application syncs correctly
4. Test GitOps workflow (push to main triggers deployment)
5. Consider alternatives to port-forward for CI/CD scenarios

## Files Created/Modified

### In talos-fix repo:
- `infrastructure/base/registry/deployment.yaml` - Registry deployment
- `infrastructure/base/argocd/applications/catalyst-ui.yaml` - ArgoCD app
- `scripts/build-and-deploy-catalyst-ui.sh` - Build and deploy script
- `docs/catalyst-ui-deployment.md` - This file

### In catalyst-ui repo:
- `Dockerfile` - Multi-stage production build
- `.dockerignore` - Optimized build context
- `k8s/namespace.yaml` - Namespace definition
- `k8s/deployment.yaml` - Deployment manifest
- `k8s/service.yaml` - Service manifest
- `k8s/ingressroute.yaml` - Traefik routing
- `k8s/kustomization.yaml` - Kustomize config
- `k8s/README.md` - K8s deployment docs

## Git Commits Required

The catalyst-ui Dockerfile and k8s manifests need to be committed and pushed:

```bash
cd ~/catalyst-devspace/workspace/catalyst-ui
git add Dockerfile .dockerignore k8s/
git commit -m "feat: Add Kubernetes deployment manifests and Dockerfile

- Multi-stage Dockerfile for production builds
- Kubernetes manifests for ArgoCD deployment
- Traefik IngressRoute for external access
- Optimized .dockerignore for build context

🤖 Generated with Claude Code
Co-Authored-By: Claude <noreply@anthropic.com>"
git push origin main
```

## Troubleshooting

### Registry not accessible
```bash
# Check registry pod
kubectl get pods -n registry

# Check registry logs
kubectl logs -n registry -l app=docker-registry

# Test from within cluster
kubectl run -it --rm curl-test --image=curlimages/curl -- \
  curl http://docker-registry.registry.svc.cluster.local:5000/v2/
```

### ArgoCD not syncing
```bash
# Check application status
kubectl get application -n argocd catalyst-ui

# View application details
kubectl describe application -n argocd catalyst-ui

# Check ArgoCD logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller
```

### Docker build fails
```bash
# Verify build works locally
cd ~/catalyst-devspace/workspace/catalyst-ui
docker build -t test-catalyst-ui .

# Check for missing files
ls -la build/ CHANGELOG.md
```
