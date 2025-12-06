# Nexus Registry

## TL;DR

Nexus Repository OSS provides artifact storage for Docker images, npm packages, and more. Two registries are available:

**Primary (Nexus):**
- **Nexus UI:** http://nexus.talos00 (login: admin)
- **Docker Registry:** http://registry.talos00 (push/pull via Nexus)
- **Docker Proxy:** http://docker-proxy.talos00 (Docker Hub cache)
- **npm Registry:** http://npm.talos00

**Legacy (Docker Registry v2):**
- **Docker Registry:** http://docker.talos00
- **Registry UI:** http://docker-ui.talos00

## Quick Reference

### Push Docker Image (Recommended: Port-Forward)

```bash
# Start port-forward
kubectl port-forward -n registry svc/nexus-docker 5000:5000 &

# Tag and push
docker tag myimage:latest localhost:5000/myimage:latest
docker push localhost:5000/myimage:latest
```

### Pull Docker Image

```bash
# From cluster or with DNS configured
docker pull registry.talos00/myimage:latest

# Via port-forward
docker pull localhost:5000/myimage:latest
```

### Get Admin Password (First Login)

```bash
kubectl exec -n registry deploy/nexus -- cat /nexus-data/admin.password
```

## Available Registries

| Registry        | URL                         | Service         | Port | Type   | Description                |
| --------------- | --------------------------- | --------------- | ---- | ------ | -------------------------- |
| Nexus UI        | http://nexus.talos00        | nexus           | 8081 | Web UI | Repository management      |
| Docker (Nexus)  | http://registry.talos00     | nexus-docker    | 5000 | Hosted | Private Docker images      |
| Docker Proxy    | http://docker-proxy.talos00 | nexus-docker-proxy | 5001 | Proxy  | Docker Hub cache           |
| npm Registry    | http://npm.talos00          | nexus-npm       | 8082 | Hosted | Private npm packages       |
| Docker (Legacy) | http://docker.talos00       | docker-registry | 5000 | Hosted | Legacy registry:2 instance |
| Docker UI       | http://docker-ui.talos00    | docker-registry-ui | 80   | Web UI | Legacy registry browser    |

## Initial Setup

### 1. Get Admin Password

After first Nexus deployment, retrieve the auto-generated password:

```bash
# Wait for pod to be ready
kubectl wait --for=condition=ready pod -l app=nexus -n registry --timeout=300s

# Get password (only exists on first run)
kubectl exec -n registry deploy/nexus -- cat /nexus-data/admin.password
```

### 2. Login and Configure

1. Open http://nexus.talos00
2. Click "Sign In" → Username: `admin`, Password: (from above)
3. Follow wizard to set new password
4. Configure anonymous access (optional, for public pulls)

### 3. Verify Repositories

Nexus should have these repositories pre-configured:

- **docker-hosted** (port 5000) - Private Docker images
- **docker-proxy** (port 5001) - Docker Hub cache
- **npm-hosted** (port 8082) - Private npm packages

If not created, see "Creating Repositories" section below.

## Pushing Docker Images

### Method 1: Port-Forward (Recommended)

Port-forwarding bypasses Traefik and avoids insecure registry configuration issues:

```bash
# Start port-forward (leave running)
kubectl port-forward -n registry svc/nexus-docker 5000:5000 &

# Build, tag, push
docker build -t myapp:latest .
docker tag myapp:latest localhost:5000/myapp:latest
docker push localhost:5000/myapp:latest

# Verify in Nexus UI
open http://nexus.talos00 → Browse → docker-hosted
```

### Method 2: Via Traefik (Requires Configuration)

Direct push via `registry.talos00` requires Docker daemon configuration:

**Add to `/etc/docker/daemon.json`:**

```json
{
  "insecure-registries": [
    "registry.talos00",
    "localhost:5000"
  ]
}
```

**Restart Docker:**

```bash
# macOS (Docker Desktop)
osascript -e 'quit app "Docker"' && open -a Docker

# Linux
sudo systemctl restart docker
```

**Then push:**

```bash
docker tag myapp:latest registry.talos00/myapp:latest
docker push registry.talos00/myapp:latest
```

### Method 3: Legacy Docker Registry

For the legacy registry at `docker.talos00`:

```bash
# Add to daemon.json
{
  "insecure-registries": ["docker.talos00"]
}

# Push
docker tag myapp:latest docker.talos00/myapp:latest
docker push docker.talos00/myapp:latest
```

## Pulling Docker Images

### From Kubernetes

Reference images in pod specs:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: myapp
spec:
  containers:
    - name: myapp
      image: registry.talos00/myapp:latest
      # Or cluster-internal:
      # image: nexus-docker.registry.svc.cluster.local:5000/myapp:latest
```

### From Local Machine

```bash
# Via hostname (requires DNS or /etc/hosts)
docker pull registry.talos00/myapp:latest

# Via port-forward
kubectl port-forward -n registry svc/nexus-docker 5000:5000 &
docker pull localhost:5000/myapp:latest
```

## npm Package Management

### Configure npm to Use Local Registry

```bash
# Global configuration
npm config set registry http://npm.talos00/repository/npm-hosted/

# Project-specific (.npmrc)
echo "registry=http://npm.talos00/repository/npm-hosted/" > .npmrc
```

### Publish Packages

```bash
# Login (use Nexus credentials)
npm login --registry=http://npm.talos00/repository/npm-hosted/

# Publish
npm publish --registry=http://npm.talos00/repository/npm-hosted/
```

### Install Packages

```bash
# From local registry
npm install mypackage --registry=http://npm.talos00/repository/npm-hosted/

# From proxy (Docker Hub cache equivalent for npm)
# Configure npm-proxy in Nexus first
npm install lodash --registry=http://npm.talos00/repository/npm-proxy/
```

## Creating Repositories (If Needed)

### Docker Hosted Repository

1. Open http://nexus.talos00 → Settings (gear icon) → Repositories
2. Click "Create repository" → Select "docker (hosted)"
3. Configure:
   - **Name:** `docker-hosted`
   - **HTTP port:** `5000`
   - **Enable Docker V1 API:** Yes
   - **Blob store:** default
4. Click "Create repository"

### Docker Proxy Repository (Docker Hub Cache)

1. Repositories → Create repository → "docker (proxy)"
2. Configure:
   - **Name:** `docker-proxy`
   - **HTTP port:** `5001`
   - **Remote storage:** `https://registry-1.docker.io`
   - **Docker Index:** Use Docker Hub
3. Click "Create repository"

### npm Hosted Repository

1. Repositories → Create repository → "npm (hosted)"
2. Configure:
   - **Name:** `npm-hosted`
   - **HTTP port:** `8082`
   - **Blob store:** default
3. Click "Create repository"

## Resource Usage

### Nexus

- **CPU:** 500m request, 2000m limit
- **Memory:** 2Gi request, 4Gi limit
- **Storage:** 100Gi (PVC: `nexus-data` on `fatboy-nfs-appdata`)
- **Startup Time:** 2-3 minutes (Java application)

### Legacy Docker Registry

- **Storage:** 50Gi (PVC: `docker-registry-data` on `fatboy-nfs-appdata`)

## Troubleshooting

### Nexus Won't Start

**Symptoms:** Pod stuck in CrashLoopBackOff or pending

**Check logs:**

```bash
kubectl logs -n registry -l app=nexus -f
```

**Common issues:**

- **Insufficient memory** - Nexus requires 2GB+ heap memory
- **PVC not provisioned** - Check `kubectl get pvc -n registry`
- **Slow startup** - Normal for Java apps, wait 2-3 minutes

**Verify health:**

```bash
# Check pod status
kubectl get pod -n registry -l app=nexus

# Check resource usage
kubectl top pod -n registry -l app=nexus
```

### Can't Push Docker Images via Traefik

**Error:** `server gave HTTP response to HTTPS client` or `connection refused`

**Solution 1: Use port-forward (recommended)**

```bash
kubectl port-forward -n registry svc/nexus-docker 5000:5000 &
docker push localhost:5000/myimage:latest
```

**Solution 2: Configure insecure registry**

Add to `/etc/docker/daemon.json`:

```json
{
  "insecure-registries": ["registry.talos00"]
}
```

Restart Docker and try again.

**Solution 3: Verify middleware configuration**

Check buffering middleware is applied:

```bash
kubectl get middleware -n registry docker-registry-buffering -o yaml
```

Should show `maxRequestBodyBytes: 0` (unlimited).

### Image Push Hangs or Times Out

**Symptoms:** Push starts but never completes, or times out after layer upload

**Cause:** Traefik buffering limits or network timeout

**Solution:**

```bash
# Verify middleware
kubectl get middleware -n registry -o yaml

# Check for buffering middleware on nexus-docker IngressRoute
kubectl get ingressroute -n registry nexus-docker -o yaml | grep middleware

# Use port-forward as workaround
kubectl port-forward -n registry svc/nexus-docker 5000:5000
```

### Repository Not Found in Nexus

**Error:** `404 Not Found` when pushing/pulling

**Check:**

1. Repository exists: Nexus UI → Browse → Repositories
2. HTTP port matches: Settings → Repositories → docker-hosted → HTTP port = 5000
3. Repository is online: Status should be "Online" not "Offline"

**Fix:**

```bash
# Create repository via Nexus UI (see "Creating Repositories" section)
# Or verify existing repository configuration
```

### Anonymous Access Not Working

**Error:** `unauthorized: access forbidden` on pull (no authentication provided)

**Enable anonymous access:**

1. Nexus UI → Settings → Security → Anonymous Access
2. Check "Allow anonymous users to access the server"
3. Settings → Security → Roles → `nx-anonymous`
4. Add privilege: `nx-repository-view-docker-*-browse` and `nx-repository-view-docker-*-read`

### Legacy Registry vs Nexus Confusion

**Issue:** Not sure which registry to use

**Recommendation:**

- **Use Nexus** (`registry.talos00`) for new images - more features, better management
- **Legacy registry** (`docker.talos00`) is deprecated, migrate images to Nexus
- Both registries are isolated, images don't sync between them

**Migration:**

```bash
# Pull from legacy
docker pull docker.talos00/myimage:latest

# Re-tag for Nexus
docker tag docker.talos00/myimage:latest registry.talos00/myimage:latest

# Push to Nexus (via port-forward)
kubectl port-forward -n registry svc/nexus-docker 5000:5000 &
docker tag registry.talos00/myimage:latest localhost:5000/myimage:latest
docker push localhost:5000/myimage:latest
```

### Nexus Data Persistence

**Storage configuration:**

```bash
# Check PVC
kubectl get pvc -n registry nexus-data

# Should show:
# - Capacity: 100Gi
# - StorageClass: fatboy-nfs-appdata
# - Status: Bound
```

**Backup Nexus data:**

```bash
# Via Nexus UI: Settings → System → Tasks → Create task → "Export configuration and metadata"
# Or copy PVC data directly from NFS mount
```

## Related Resources

- [Nexus Repository Manager Documentation](https://help.sonatype.com/repomanager3)
- [Docker Registry v2 Documentation](https://docs.docker.com/registry/)
- [Traefik IngressRoute Documentation](https://doc.traefik.io/traefik/routing/providers/kubernetes-crd/)

---

## Related Issues

- [CILIUM-65t] - Restructured with progressive summarization pattern
