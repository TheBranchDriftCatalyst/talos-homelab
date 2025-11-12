# Homelab Provisioning Steps

Complete guide for provisioning the Talos Kubernetes homelab environment from scratch.

---

## Level 0: Base Infrastructure ✅ COMPLETED

### Prerequisites
- Talos Linux ISO/Image
- Target hardware (bare metal or VM)
- Network connectivity (192.168.1.54 in this setup)

### Steps Taken

1. **Initial Talos Installation**
   ```bash
   # Generate Talos secrets
   talosctl gen secrets -o configs/secrets.yaml

   # Generate machine configs
   talosctl gen config homelab https://192.168.1.54:6443 \
     --config-patch @configs/patches/controlplane.yaml \
     --output configs/

   # Apply configuration to node
   talosctl apply-config --insecure \
     --nodes 192.168.1.54 \
     --file configs/controlplane.yaml
   ```

2. **Bootstrap Kubernetes**
   ```bash
   # Bootstrap etcd
   talosctl bootstrap --nodes 192.168.1.54 --talosconfig configs/talosconfig

   # Wait for cluster to be ready (~2-3 minutes)
   talosctl health --nodes 192.168.1.54 --talosconfig configs/talosconfig
   ```

3. **Extract Kubeconfig**
   ```bash
   # Get kubeconfig
   talosctl kubeconfig .output/kubeconfig \
     --nodes 192.168.1.54 \
     --talosconfig configs/talosconfig

   # Merge into ~/.kube/config
   ./scripts/kubeconfig-merge.sh

   # Switch context
   kubectx homelab-single
   ```

4. **Set Node Hostname**
   ```bash
   # Edit configs/controlplane.yaml to add:
   network:
     hostname: talos00

   # Apply configuration
   talosctl apply-config --nodes 192.168.1.54 \
     --talosconfig configs/talosconfig \
     --file configs/controlplane.yaml
   ```

   **Note**: Changing hostname AFTER cluster bootstrap causes Kubernetes to see it as a new node. This required cleanup:
   ```bash
   # Delete old node entry
   kubectl delete node talos-v8c-548

   # Reset node (if needed)
   talosctl reset --graceful --reboot \
     --nodes 192.168.1.54 \
     --talosconfig configs/talosconfig
   ```

### Verification
```bash
# Check node status
kubectl get nodes
# Expected: NAME=talos00, STATUS=Ready

# Check system pods
kubectl get pods -A
# Expected: All coredns, flannel pods Running

# Check Talos health
talosctl health --nodes 192.168.1.54 --talosconfig configs/talosconfig
```

**Current State**:
- Node: `talos00` (Ready)
- Kubernetes: v1.34.0
- Talos: v1.11.1
- CNI: Flannel
- IP: 192.168.1.54

---

## Level 1: Core Services ✅ COMPLETED

### 1.1 Deploy Namespaces

```bash
# Apply namespace manifests
kubectl apply -k infrastructure/base/namespaces/

# Verify
kubectl get namespaces
```

**Created Namespaces**:
- `media-dev` - Development environment (4 CPU / 8Gi RAM quota)
- `media-prod` - Production environment (8 CPU / 16Gi RAM quota)
- `local-path-storage` - Storage provisioner namespace

**Files**:
- `infrastructure/base/namespaces/media-dev.yaml` - Dev namespace with ResourceQuota and LimitRange
- `infrastructure/base/namespaces/media-prod.yaml` - Prod namespace with ResourceQuota and LimitRange
- `infrastructure/base/namespaces/kustomization.yaml` - Kustomize manifest

### 1.2 Deploy Storage Provisioners

```bash
# Apply storage manifests
kubectl apply -k infrastructure/base/storage/

# Wait for local-path-provisioner to be ready
kubectl wait --for=condition=ready pod -l app=local-path-provisioner \
  -n local-path-storage --timeout=120s

# Verify storage classes
kubectl get storageclass
```

**Storage Classes Created**:
- `local-path` (default) - Local path provisioner for SQLite databases (RWO)
- `nfs-synology` - NFS storage for media files (RWX)

**PersistentVolumes Created**:
- `nfs-media` - 1Ti NFS volume for media files
- `nfs-downloads` - 200Gi NFS volume for downloads

**PersistentVolumeClaims Created** (per namespace):
- `media-pvc` - Claim for media files (RWX)
- `downloads-pvc` - Claim for downloads (RWX)

**Critical Note**: SQLite databases CANNOT use NFS due to locking issues. All arr apps use local-path storage for config/databases.

**Files**:
- `infrastructure/base/storage/local-path-provisioner.yaml` - Complete local-path-provisioner deployment
- `infrastructure/base/storage/nfs-storageclass.yaml` - NFS StorageClass, PVs, and PVCs
- `infrastructure/base/storage/kustomization.yaml` - Kustomize manifest

**TODO**: Update NFS server IP in `nfs-storageclass.yaml`:
```yaml
nfs:
  server: ${SYNOLOGY_NFS_SERVER}  # Update this before deploying to prod
  path: /volume1/media
```

### 1.3 Verify Traefik Ingress

Traefik was already installed in a previous step. Verified it's working:

```bash
# Check Traefik pods
kubectl get pods -n traefik

# Check IngressRoutes
kubectl get ingressroute -A

# Test access
curl http://whoami.talos00
```

**Domain Changes**: All domains updated from `.lab` to `.talos00`:
```bash
# Global find/replace across all YAML files
find . -name "*.yaml" -type f -exec sed -i '' 's/\.lab/\.talos00/g' {} +
```

**Access Points**:
- Traefik Dashboard: http://traefik.talos00
- Whoami Test: http://whoami.talos00

**Add to `/etc/hosts`**:
```
192.168.1.54 traefik.talos00 whoami.talos00
```

### Verification
```bash
# Run deployment script
./scripts/deploy-stack.sh

# Or manual verification
kubectl get namespaces | grep media
kubectl get storageclass
kubectl get pv
kubectl get pvc -n media-dev
kubectl get pvc -n media-prod
kubectl get pods -n traefik
```

**Current State**:
- ✅ Namespaces: media-dev, media-prod, local-path-storage
- ✅ Storage: local-path (default), nfs-synology
- ✅ PVs: nfs-media (1Ti), nfs-downloads (200Gi)
- ✅ PVCs: Created in both dev and prod namespaces
- ✅ Traefik: Running and accessible

---

## Level 2: Applications 🔄 NEXT

Deploy arr stack applications for media automation.

### 2.1 Deploy to Development Environment

```bash
# Deploy Prowlarr (indexer manager)
kubectl apply -k applications/arr-stack/base/prowlarr/ -n media-dev

# Deploy Sonarr (TV automation)
kubectl apply -k applications/arr-stack/base/sonarr/ -n media-dev

# Deploy Radarr (movie automation)
kubectl apply -k applications/arr-stack/base/radarr/ -n media-dev

# Deploy Plex (media server)
kubectl apply -k applications/arr-stack/base/plex/ -n media-dev

# Deploy Jellyfin (media server - testing)
kubectl apply -k applications/arr-stack/base/jellyfin/ -n media-dev
```

### 2.2 Verify Deployments

```bash
# Check all pods in dev namespace
kubectl get pods -n media-dev

# Wait for pods to be ready
kubectl wait --for=condition=ready pod -l app=prowlarr -n media-dev --timeout=300s
kubectl wait --for=condition=ready pod -l app=sonarr -n media-dev --timeout=300s
kubectl wait --for=condition=ready pod -l app=radarr -n media-dev --timeout=300s
kubectl wait --for=condition=ready pod -l app=plex -n media-dev --timeout=300s
kubectl wait --for=condition=ready pod -l app=jellyfin -n media-dev --timeout=300s

# Check PVCs are bound
kubectl get pvc -n media-dev

# Check IngressRoutes
kubectl get ingressroute -n media-dev
```

### 2.3 Access Applications

**Add to `/etc/hosts`**:
```
192.168.1.54 prowlarr.talos00 sonarr.talos00 radarr.talos00 plex.talos00 jellyfin.talos00
```

**Access URLs** (development):
- Prowlarr: http://prowlarr.talos00
- Sonarr: http://sonarr.talos00
- Radarr: http://radarr.talos00
- Plex: http://plex.talos00
- Jellyfin: http://jellyfin.talos00

### 2.4 Deploy to Production (Optional)

Once tested in dev, deploy to production:

```bash
# Deploy to production namespace
kubectl apply -k applications/arr-stack/base/prowlarr/ -n media-prod
kubectl apply -k applications/arr-stack/base/sonarr/ -n media-prod
kubectl apply -k applications/arr-stack/base/radarr/ -n media-prod
kubectl apply -k applications/arr-stack/base/plex/ -n media-prod
kubectl apply -k applications/arr-stack/base/jellyfin/ -n media-prod
```

**Production URLs**:
- Prowlarr: http://prowlarr.prod.talos00
- Sonarr: http://sonarr.prod.talos00
- Radarr: http://radarr.prod.talos00
- Plex: http://plex.prod.talos00
- Jellyfin: http://jellyfin.prod.talos00

### Storage Architecture

Each application gets:
- **Config Volume**: local-path storage (SQLite databases)
  - Cannot use NFS due to SQLite locking issues
  - Each pod gets its own local-path PVC
- **Media Volume**: NFS storage (read-only for most apps)
  - Mounted from shared `media-pvc` (RWX)
  - Points to Synology NFS share
- **Downloads Volume**: NFS storage (read-write)
  - Mounted from shared `downloads-pvc` (RWX)
  - Shared between Sonarr/Radarr for completed downloads

---

## Level 3: Monitoring Stack ⏳ PENDING

Deploy kube-prometheus-stack for comprehensive monitoring.

### 3.1 Add Helm Repository

```bash
# Add prometheus-community repo
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts

# Update repos
helm repo update
```

### 3.2 Deploy Monitoring Stack

```bash
# Create namespace
kubectl create namespace monitoring

# Deploy kube-prometheus-stack
helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring \
  --create-namespace \
  -f infrastructure/base/monitoring/kube-prometheus-stack/values.yaml

# Wait for all pods
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=kube-prometheus-stack \
  -n monitoring --timeout=600s
```

### 3.3 Components Deployed

- **Prometheus Operator**: Manages Prometheus, Alertmanager, ServiceMonitors
- **Prometheus**: Metrics collection and storage (50Gi)
- **Grafana**: Visualization and dashboards (10Gi)
- **Alertmanager**: Alert routing and silencing (10Gi)
- **Node Exporter**: Node metrics
- **kube-state-metrics**: Kubernetes object metrics
- **ServiceMonitors**: Automatic scraping configuration

### 3.4 Access Monitoring

**Add to `/etc/hosts`**:
```
192.168.1.54 grafana.talos00 prometheus.talos00 alertmanager.talos00
```

**Access URLs**:
- Grafana: http://grafana.talos00
- Prometheus: http://prometheus.talos00
- Alertmanager: http://alertmanager.talos00

**Default Credentials**:
- Username: `admin`
- Password: `prom-operator` (change in values.yaml)

### 3.5 Verification

```bash
# Check all monitoring pods
kubectl get pods -n monitoring

# Check ServiceMonitors
kubectl get servicemonitor -n monitoring

# Check PrometheusRules
kubectl get prometheusrule -n monitoring

# Check storage
kubectl get pvc -n monitoring
```

---

## Level 4: GitOps ⏳ PENDING

Deploy FluxCD and ArgoCD for automated deployments.

### 4.1 Prerequisites

1. **Create Git Repository**:
   ```bash
   # Initialize git repo (if not already done)
   git init
   git add .
   git commit -m "Initial homelab configuration"

   # Create GitHub repo and push
   gh repo create talos-homelab --private
   git remote add origin git@github.com:yourusername/talos-homelab.git
   git push -u origin main
   ```

2. **Create GitHub Personal Access Token**:
   - Go to GitHub Settings → Developer settings → Personal access tokens
   - Generate token with `repo` scope
   - Save token securely

### 4.2 Bootstrap FluxCD

FluxCD manages infrastructure (namespaces, storage, monitoring).

```bash
# Set environment variables
export GITHUB_USER=yourusername
export GITHUB_TOKEN=ghp_xxxxxxxxxxxxx
export GITHUB_REPO=talos-homelab

# Bootstrap Flux
flux bootstrap github \
  --owner=$GITHUB_USER \
  --repository=$GITHUB_REPO \
  --branch=main \
  --path=bootstrap/flux \
  --personal \
  --private=true

# Wait for Flux to reconcile
flux check
```

**What Flux Manages**:
- Namespaces
- Storage classes
- Monitoring stack (kube-prometheus-stack)
- Infrastructure configuration

**Files**:
- `bootstrap/flux/gotk-components.yaml` - Flux installation
- `bootstrap/flux/gotk-sync.yaml` - Flux sync configuration
- `bootstrap/flux/kustomization.yaml` - Flux Kustomization

### 4.3 Deploy ArgoCD

ArgoCD manages applications (arr stack, media servers).

```bash
# Apply ArgoCD namespace
kubectl apply -f bootstrap/argocd/namespace.yaml

# Deploy ArgoCD via Helm
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update

helm install argocd argo/argo-cd \
  -n argocd \
  --create-namespace \
  -f bootstrap/argocd/values.yaml

# Wait for ArgoCD to be ready
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=argocd-server \
  -n argocd --timeout=300s

# Get admin password
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d
```

### 4.4 Access ArgoCD

**Add to `/etc/hosts`**:
```
192.168.1.54 argocd.talos00
```

**Access URL**: http://argocd.talos00

**Login**:
- Username: `admin`
- Password: (from previous step)

### 4.5 Configure ArgoCD Applications

```bash
# Apply ArgoCD Application manifests
kubectl apply -k applications/arr-stack/argocd/

# Verify applications
argocd app list
```

**ArgoCD Applications Created**:
- `prowlarr-dev` - Prowlarr in media-dev namespace
- `sonarr-dev` - Sonarr in media-dev namespace
- `radarr-dev` - Radarr in media-dev namespace
- `plex-dev` - Plex in media-dev namespace
- `jellyfin-dev` - Jellyfin in media-dev namespace

### 4.6 Verification

```bash
# Check Flux status
flux get all -A

# Check Flux Kustomizations
flux get kustomizations

# Check ArgoCD applications
argocd app list

# Check ArgoCD sync status
argocd app get prowlarr-dev
```

---

## Quick Reference

### Cluster Context Management

```bash
# List contexts
kubectx

# Switch to homelab
kubectx homelab-single

# Switch to local test cluster
kubectx talos-local

# Switch namespace
kubens media-dev
```

### Common Commands

```bash
# Check cluster health
kubectl get nodes
kubectl get pods -A

# Check specific namespace
kubectl get all -n media-dev

# Check storage
kubectl get storageclass
kubectl get pv
kubectl get pvc -A

# Check Traefik
kubectl get ingressroute -A

# Check logs
kubectl logs -n media-dev -l app=sonarr

# Restart deployment
kubectl rollout restart deployment/sonarr -n media-dev
```

### Troubleshooting

```bash
# Check pod events
kubectl describe pod <pod-name> -n <namespace>

# Check pod logs
kubectl logs <pod-name> -n <namespace>

# Check node conditions
kubectl describe node talos00

# Check Talos logs
talosctl logs --nodes 192.168.1.54 --talosconfig configs/talosconfig

# Check etcd health
talosctl etcd status --nodes 192.168.1.54 --talosconfig configs/talosconfig
```

---

## Environment Variables

Create `.env` file for sensitive values:

```bash
# NFS Configuration
SYNOLOGY_NFS_SERVER=192.168.1.xxx

# GitHub Configuration (for GitOps)
GITHUB_USER=yourusername
GITHUB_TOKEN=ghp_xxxxxxxxxxxxx
GITHUB_REPO=talos-homelab

# ArgoCD Configuration
ARGOCD_ADMIN_PASSWORD=changeme

# Monitoring Configuration
GRAFANA_ADMIN_PASSWORD=changeme
```

**Note**: `.env` is gitignored. Never commit secrets to Git.

---

## Current Status Summary

### ✅ Completed (Levels 0-1)
- Talos node provisioned and configured (hostname: talos00)
- Kubernetes v1.34.0 running
- Namespaces deployed (media-dev, media-prod)
- Storage provisioners deployed (local-path, nfs-synology)
- Traefik ingress working (whoami.talos00, traefik.talos00)
- All system pods Running and healthy

### 🔄 Next Steps (Level 2)
- Deploy arr stack applications to media-dev
- Test applications in dev environment
- Configure NFS server IP in storage manifests

### ⏳ Pending (Levels 3-4)
- Deploy monitoring stack (kube-prometheus-stack)
- Create Git repository and push configuration
- Bootstrap FluxCD for infrastructure management
- Deploy ArgoCD for application management

---

## Notes and Lessons Learned

### Hostname Change Issue
- Changing hostname AFTER cluster bootstrap causes Kubernetes to register a new node
- This creates network conflicts (Flannel CNI bridge IP mismatch)
- **Solution**: Always set hostname BEFORE first bootstrap, or be prepared to:
  1. Delete old node entry
  2. Reset node with graceful reboot
  3. Wait for network to re-initialize

### Storage Strategy
- SQLite databases CANNOT use NFS (locking issues)
- Use local-path storage for all app config and databases
- Use NFS only for media files (large, sequential reads)
- Arr apps require separate config volumes per pod

### Multi-Environment Setup
- Use namespace-based separation (media-dev, media-prod)
- ResourceQuotas prevent resource exhaustion
- LimitRanges provide pod-level defaults
- IngressRoutes use hostname-based routing (.talos00 vs .dev.talos00)

### Kubeconfig Management
- `.output/` directory structure supports multiple environments
- `kubeconfig-merge.sh` automatically discovers all configs
- Context names derived from directory structure
- Use `kubectx` for easy context switching
