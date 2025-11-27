# Nexus Repository Manager

Sonatype Nexus Repository OSS - Universal artifact repository supporting Docker, npm, PyPI, Maven, and more.

## Access

| Service         | URL                         | Port | Description                             |
| --------------- | --------------------------- | ---- | --------------------------------------- |
| Nexus UI        | http://nexus.talos00        | 8081 | Web interface for repository management |
| Docker Registry | http://registry.talos00     | 5000 | Docker push/pull (hosted)               |
| Docker Proxy    | http://docker-proxy.talos00 | 5001 | Docker Hub cache/proxy                  |
| npm Registry    | http://npm.talos00          | 8082 | npm packages                            |

## Initial Setup

### 1. Get Admin Password

After first deployment, retrieve the auto-generated admin password:

```bash
# Wait for Nexus to be ready
kubectl wait --for=condition=ready pod -l app=nexus -n registry --timeout=300s

# Get the admin password (only available on first run)
kubectl exec -n registry deploy/nexus -- cat /nexus-data/admin.password
```

### 2. Login and Change Password

1. Go to http://nexus.talos00
2. Click "Sign In" (top right)
3. Username: `admin`
4. Password: (from command above)
5. Follow the wizard to set a new password and configure anonymous access

### 3. Create Docker Hosted Repository

1. Go to **Settings** (gear icon) > **Repositories** > **Create repository**
2. Select **Docker (hosted)**
3. Configure:
   - Name: `docker-hosted`
   - HTTP port: `5000`
   - Enable Docker V1 API: Yes (for compatibility)
   - Blob store: default
4. Click **Create repository**

### 4. Create Docker Proxy Repository (Optional - Cache Docker Hub)

1. Go to **Repositories** > **Create repository**
2. Select **Docker (proxy)**
3. Configure:
   - Name: `docker-proxy`
   - HTTP port: `5001`
   - Remote storage: `https://registry-1.docker.io`
   - Docker Index: Use Docker Hub
4. Click **Create repository**

### 5. Create npm Hosted Repository (Optional)

1. Go to **Repositories** > **Create repository**
2. Select **npm (hosted)**
3. Configure:
   - Name: `npm-hosted`
   - HTTP port: `8082`
4. Click **Create repository**

## Usage

### Docker Images

#### Configure Docker Daemon

Add to `/etc/docker/daemon.json` (or Docker Desktop settings):

```json
{
  "insecure-registries": ["localhost:5000", "registry.talos00"]
}
```

Restart Docker after changes.

#### Push Images

```bash
# Via port-forward (recommended)
kubectl port-forward -n registry svc/nexus-docker 5000:5000 &
docker tag myimage:latest localhost:5000/myimage:latest
docker push localhost:5000/myimage:latest

# Via Traefik (if insecure registry configured)
docker tag myimage:latest registry.talos00/myimage:latest
docker push registry.talos00/myimage:latest
```

#### Pull Images

```bash
docker pull registry.talos00/myimage:latest
```

### npm Packages

#### Configure npm

```bash
# Set registry for a project
npm config set registry http://npm.talos00/repository/npm-hosted/

# Or use .npmrc in project
echo "registry=http://npm.talos00/repository/npm-hosted/" > .npmrc
```

#### Publish Packages

```bash
# Login first
npm login --registry=http://npm.talos00/repository/npm-hosted/

# Publish
npm publish --registry=http://npm.talos00/repository/npm-hosted/
```

## Kubernetes Usage

Reference images in deployments:

```yaml
spec:
  containers:
    - name: myapp
      image: registry.talos00/myapp:latest
```

For cluster-internal access:

```yaml
image: nexus-docker.registry.svc.cluster.local:5000/myapp:latest
```

## Storage

- PVC: `nexus-data` (100Gi)
- Storage Class: `local-path`
- Mount: `/nexus-data`

## Resources

- Requests: 500m CPU, 2Gi RAM
- Limits: 2000m CPU, 4Gi RAM

Nexus requires significant memory for Java heap. Adjust `INSTALL4J_ADD_VM_PARAMS` in deployment if needed.

## Troubleshooting

### Nexus Won't Start

Check logs:

```bash
kubectl logs -n registry -l app=nexus -f
```

Common issues:

- Insufficient memory (needs 2GB+ heap)
- PVC not provisioned
- Slow startup (normal, wait 2-3 minutes)

### Can't Push Images

1. Verify Docker hosted repository exists and has HTTP port 5000
2. Check insecure-registries in Docker daemon
3. Use port-forward: `kubectl port-forward -n registry svc/nexus-docker 5000:5000`

### Anonymous Access

If you need anonymous pull access:

1. **Settings** > **Security** > **Anonymous Access**
2. Enable "Allow anonymous users to access the server"
3. Assign `nx-anonymous` role read access to repositories

## Cleanup Old Docker Registry

If migrating from the old registry:2 deployment:

```bash
# Delete old PVC (data will be lost)
kubectl delete pvc registry-data -n registry

# The new nexus-data PVC will be created automatically
```
