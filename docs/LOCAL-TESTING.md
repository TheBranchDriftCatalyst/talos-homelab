# Local Talos Cluster Testing

This guide explains how to run a local Talos Kubernetes cluster on your Mac using Docker for testing the GitOps configuration.

## Prerequisites

1. **Docker Desktop** - Install from https://www.docker.com/products/docker-desktop
   - Allocate at least 4GB RAM and 2 CPUs to Docker
   - Make sure Docker is running before proceeding

2. **Talosctl** - Talos CLI tool
   ```bash
   brew install siderolabs/tap/talosctl
   ```

3. **Kubectl** - Kubernetes CLI
   ```bash
   brew install kubectl
   ```

4. **Helm** - Kubernetes package manager
   ```bash
   brew install helm
   ```

## Quick Start

### 1. Create Local Cluster

```bash
./scripts/provision-local.sh
```

This script will:
- Create a single-node Talos cluster running in Docker
- Install metrics-server
- Install Traefik ingress controller
- Deploy a test whoami service
- Merge kubeconfig to `~/.kube/config`

### 2. Verify Cluster

```bash
# Check nodes
kubectl get nodes

# Check pods
kubectl get pods -A

# Test Traefik dashboard
open http://traefik.localhost

# Test whoami service
curl http://whoami.localhost
```

### 3. Deploy Test Applications

The local cluster is perfect for testing your arr stack manifests:

```bash
# Create test namespace
kubectl create namespace media-dev

# Apply storage manifests (local-path only)
kubectl apply -k infrastructure/base/storage/

# Deploy Prowlarr
kubectl apply -k applications/arr-stack/base/prowlarr/
kubectl -n media-dev port-forward svc/prowlarr 9696:9696

# Access Prowlarr
open http://localhost:9696
```

## Cluster Details

### Configuration

- **Cluster Name**: `talos-local`
- **Control Plane**: Single node (no workers)
- **Kubeconfig**: `.output/local/kubeconfig`
- **Talosconfig**: `.output/local/talosconfig`
- **API Server**: `https://127.0.0.1:6443`

### Networking

- Traefik uses LoadBalancer service type (Docker provides LB)
- Access services via `http://*.localhost`
- No need to modify `/etc/hosts` - `.localhost` resolves automatically

### Storage

- **local-path-provisioner** is built into Talos
- Creates volumes under `/var/lib/rancher/local-path-provisioner` in the container
- NFS storage is NOT available in local Docker cluster

## Useful Commands

### Cluster Management

```bash
# View cluster status
talosctl --talosconfig .output/local/talosconfig \
    --nodes 127.0.0.1 dashboard

# Get cluster info
kubectl cluster-info

# Watch all pods
kubectl get pods -A -w

# View Talos logs
talosctl --talosconfig .output/local/talosconfig \
    --nodes 127.0.0.1 logs
```

### Testing GitOps Manifests

```bash
# Validate Kustomize builds
kustomize build infrastructure/base | kubectl apply --dry-run=client -f -

# Apply infrastructure
kubectl apply -k infrastructure/base/namespaces/
kubectl apply -k infrastructure/base/storage/

# Test app deployment
kubectl apply -k applications/arr-stack/base/prowlarr/
kubectl -n media-dev get all
```

### Port Forwarding

Since services use `.localhost` domains, you may want to port-forward for direct access:

```bash
# Prowlarr
kubectl -n media-dev port-forward svc/prowlarr 9696:9696

# Sonarr
kubectl -n media-dev port-forward svc/sonarr 8989:8989

# Radarr
kubectl -n media-dev port-forward svc/radarr 7878:7878

# Plex
kubectl -n media-dev port-forward svc/plex 32400:32400

# Jellyfin
kubectl -n media-dev port-forward svc/jellyfin 8096:8096
```

## Differences from Production

### Storage
- ❌ No NFS storage (Synology)
- ✅ local-path-provisioner only
- ⚠️  Data persists in Docker volume (lost on cluster destroy)

### Networking
- ❌ No hostPort binding (80/443)
- ✅ LoadBalancer service type
- ✅ Access via `*.localhost` domains

### Resources
- ⚠️  Limited to Docker Desktop resource allocation
- ⚠️  Single node (no HA)
- ✅ Good for testing deployments and configs

## Cleanup

### Destroy Cluster

```bash
talosctl cluster destroy --name talos-local
```

This removes:
- All Docker containers
- All Docker volumes
- Cluster data

### Remove from Kubeconfig

```bash
kubectl config delete-context talos-local
kubectl config delete-cluster talos-local
```

## Troubleshooting

### Docker Issues

**Error: Cannot connect to Docker daemon**
```bash
# Start Docker Desktop
open -a Docker

# Wait for Docker to start, then retry
./scripts/provision-local.sh
```

**Error: Out of disk space**
```bash
# Clean up Docker
docker system prune -a --volumes
```

### Cluster Issues

**Error: Cluster creation timeout**
```bash
# Destroy and retry
talosctl cluster destroy --name talos-local
./scripts/provision-local.sh
```

**Error: Can't reach *.localhost**
```bash
# Get Traefik LoadBalancer IP
kubectl -n traefik get svc traefik

# Use port-forward instead
kubectl -n traefik port-forward svc/traefik 8080:80
# Access: http://localhost:8080
```

### Application Issues

**Pods stuck in Pending**
```bash
# Check PVC binding
kubectl -n media-dev get pvc

# Check events
kubectl -n media-dev get events --sort-by='.lastTimestamp'

# Describe pod
kubectl -n media-dev describe pod <pod-name>
```

## Next Steps

Once you've validated your manifests locally:

1. Push changes to Git repository
2. Bootstrap FluxCD on production cluster
3. Let Flux reconcile infrastructure and applications
4. Monitor with ArgoCD UI

## Resources

- [Talos Documentation](https://www.talos.dev/docs/)
- [Talos Local Clusters](https://www.talos.dev/docs/talos-guides/install/local-platforms/)
- [Docker Desktop](https://docs.docker.com/desktop/)
