# Talos Single-Node Cluster

This repository contains configuration and scripts for managing a single-node Talos Kubernetes cluster.

## Quick Start

### Prerequisites

**Required:**
- `talosctl` CLI installed
- `kubectl` CLI installed
- Set `TALOS_NODE` environment variable to your node's IP address

**Recommended:**
- `task` (Taskfile) installed - Task runner for automation
- `kubectx` + `kubens` - Fast context and namespace switching
- `k9s` - Terminal UI for Kubernetes clusters
- `helm` - Kubernetes package manager

```bash
# Set node IP
export TALOS_NODE=192.168.1.54

# Install recommended tools (macOS)
brew install go-task/tap/go-task kubectx k9s helm
```

### Initial Setup

1. **Generate Configuration** (if not already done):
   ```bash
   talosctl gen config homelab-single https://$TALOS_NODE:6443 --output-dir . --force
   ```

2. **Provision the Cluster**:
   ```bash
   ./provision.sh
   ```
   Or using Task:
   ```bash
   task provision
   ```

## Configuration Features

### Single-Node Optimizations
- **Control Plane Scheduling**: Configured with `allowSchedulingOnControlPlanes: true` in `controlplane.yaml:551`
- **No Taints**: Control-plane taint is removed automatically during provisioning
- **All-in-One**: Single node acts as both control plane and worker

### Included Services
- **Talos Dashboard**: Built-in node monitoring
- **Kubernetes Dashboard**: Web UI for cluster management (auto-deployed via extraManifests)
- **CoreDNS**: DNS resolution (2 replicas)
- **Flannel**: CNI networking
- **etcd**: Single-node cluster

### Observability Stack
- **Prometheus**: Metrics collection and alerting (30-day retention, 50Gi storage) ✅ DEPLOYED
- **Grafana**: Metrics visualization and dashboards ✅ DEPLOYED
- **Alertmanager**: Alert routing and management ✅ DEPLOYED
- **Graylog**: Centralized log management platform ✅ DEPLOYED
- **MongoDB**: Database backend for Graylog (20Gi storage) ✅ DEPLOYED
- **OpenSearch**: Log storage and indexing (30Gi storage) ✅ DEPLOYED
- **Fluent Bit**: Log collection from all containers ✅ DEPLOYED
- **Exportarr**: Prometheus exporters for *arr applications ✅ DEPLOYED

### GitOps & Management
- **ArgoCD**: GitOps continuous delivery (v3.2.0) ✅ DEPLOYED
- **Homepage**: Unified dashboard for all services ✅ DEPLOYED

### Media Applications (Arr Stack)
- **Prowlarr**: Indexer manager ✅ RUNNING
- **Sonarr**: TV show automation ✅ RUNNING
- **Radarr**: Movie automation ✅ RUNNING
- **Readarr**: Book automation ✅ RUNNING
- **Overseerr**: Media request management ✅ RUNNING
- **Plex**: Media server ✅ RUNNING
- **Jellyfin**: Alternative media server ✅ RUNNING
- **PostgreSQL**: Database for Overseerr ✅ RUNNING

### Automatic Dashboard Deployment

The Kubernetes Dashboard is automatically deployed during cluster bootstrap via:
- `extraManifests` (controlplane.yaml:510-511) - Downloads dashboard YAML
- `inlineManifests` (controlplane.yaml:514-534) - Creates admin-user ServiceAccount

## Deployment

### Complete Stack Deployment

Deploy the entire homelab stack from scratch:

```bash
# Deploy everything (infrastructure + monitoring + observability)
./scripts/deploy-stack.sh

# Or with options
DEPLOY_MONITORING=true DEPLOY_OBSERVABILITY=true ./scripts/deploy-stack.sh
```

### Deploy Observability Stack Only

```bash
# Deploy monitoring and logging stack
./scripts/deploy-observability.sh
```

This will install:
- Prometheus + Grafana + Alertmanager (kube-prometheus-stack)
- MongoDB + OpenSearch + Graylog (logging stack)
- Fluent Bit (log collection)

Access URLs after deployment:
- **Monitoring**:
  - Grafana: http://grafana.talos00 (admin / prom-operator)
  - Prometheus: http://prometheus.talos00
  - Alertmanager: http://alertmanager.talos00
  - Graylog: http://graylog.talos00 (admin / admin)
- **GitOps**:
  - ArgoCD: http://argocd.talos00 (admin / admin)
- **Media Apps** (all in media-dev namespace):
  - Homepage: http://homepage.talos00
  - Prowlarr: http://prowlarr.talos00
  - Sonarr: http://sonarr.talos00
  - Radarr: http://radarr.talos00
  - Readarr: http://readarr.talos00
  - Overseerr: http://overseerr.talos00
  - Plex: http://plex.talos00
  - Jellyfin: http://jellyfin.talos00

### Deploy Applications (arr stack) ✅ DEPLOYED

All media applications are currently deployed to the `media-dev` namespace:

```bash
# View all deployed apps
kubectl get deployments -n media-dev

# Check app status
kubectl get pods -n media-dev
```

**Deployed Applications**:
- Prowlarr (indexer manager) ✅
- Sonarr (TV shows) ✅
- Radarr (movies) ✅
- Readarr (books) ✅
- Overseerr (request management) ✅
- Plex (media server) ✅
- Jellyfin (media server) ✅
- Homepage (dashboard) ✅
- PostgreSQL (database) ✅
- Exportarr (Prometheus metrics - 4 instances) ⚠️ Needs API keys

**Configuration Needed**:
1. Configure Exportarr API keys (see `scripts/extract-arr-api-keys.sh`)
2. Configure Prowlarr indexers
3. Connect Sonarr/Radarr/Readarr to Prowlarr
4. Configure Plex and Jellyfin media libraries

## Common Tasks

### Cluster Management

```bash
# Check cluster health
task health

# View Talos dashboard
task dashboard

# Get cluster version
task version

# List all services
task services

# View service logs (example: kubelet)
task service-logs -- SERVICE=kubelet
```

### Kubeconfig Management

**Option 1: Merge to ~/.kube/config (Recommended)**

This allows you to use `kubectl`, `kubectx`, and `k9s` without specifying `--kubeconfig` every time:

```bash
# Merge kubeconfig to your default config
task kubeconfig-merge

# Now use kubectl without flags
kubectl get nodes
kubectl top nodes
kubectl get pods -A

# Switch contexts with kubectx
kubectx                    # List all contexts
kubectx homelab-single     # Switch to this cluster
kubectx -                  # Switch to previous context

# Switch namespaces with kubens
kubens                     # List namespaces
kubens kube-system         # Switch to kube-system
kubens -                   # Switch to previous namespace

# Launch k9s TUI
k9s
```

**Option 2: Use local kubeconfig (Manual)**

```bash
# Download kubeconfig to .output/kubeconfig
task kubeconfig

# Use with --kubeconfig flag
kubectl --kubeconfig ./.output/kubeconfig get nodes
kubectl --kubeconfig ./.output/kubeconfig get pods -A

# Or export for current shell session
export KUBECONFIG=./.output/kubeconfig
kubectl get nodes  # Works in this shell only
```

### Kubernetes Operations

```bash
# Get nodes
task get-nodes

# Get all pods
task get-pods

# View resource usage (requires metrics-server)
kubectl top nodes
kubectl top pods -A

# Generate cluster audit report
task audit
```

### Kubernetes Dashboard

1. **Get Access Token**:
   ```bash
   task dashboard-token
   # Token is saved to ./dashboard-token.txt
   ```

2. **Start Proxy**:
   ```bash
   task dashboard-proxy
   ```

3. **Access Dashboard**:
   - Open: http://localhost:8001/api/v1/namespaces/kubernetes-dashboard/services/https:kubernetes-dashboard:/proxy/
   - Use the token from step 1 to login

### Troubleshooting

```bash
# View kernel logs
task dmesg

# Follow service logs
task logs-follow -- SERVICE=kubelet

# List containers
task containers

# Check etcd status
task etcd-status

# View etcd members
task etcd-members
```

### Node Operations

```bash
# Reboot node
task reboot

# Shutdown node
task shutdown

# Upgrade Talos (specify version)
task upgrade -- VERSION=v1.11.2
```

## File Structure

```
.
├── configs/                         # Talos configuration files (gitignored - sensitive)
│   ├── controlplane.yaml           # Control plane configuration
│   ├── worker.yaml                 # Worker configuration (unused in single-node)
│   └── talosconfig                 # Talos CLI configuration
├── kubernetes/                      # Kubernetes manifests
│   ├── dashboard-ingressroute.yaml # Dashboard ingress via Traefik
│   ├── traefik-values.yaml         # Traefik Helm values
│   └── whoami-ingressroute.yaml    # Test service with ingress
├── scripts/                         # Automation scripts
│   ├── provision.sh                # Complete cluster provisioning
│   ├── setup-infrastructure.sh     # Install Traefik & metrics-server
│   ├── cluster-audit.sh            # Generate Markdown audit report
│   ├── dashboard-token.sh          # Retrieve dashboard access token
│   └── kubeconfig-merge.sh         # Merge kubeconfig to ~/.kube/config
├── .output/                         # Generated files (gitignored)
│   ├── kubeconfig                  # Kubernetes cluster access config
│   ├── dashboard-token.txt         # Latest dashboard token
│   └── audit/                      # Cluster audit reports
│       └── cluster-audit-*.md      # Timestamped audit reports
├── .gitignore                      # Git ignore patterns
├── Taskfile.yaml                   # Task automation definitions
├── README.md                       # This file
├── QUICKSTART.md                   # Quick reference guide
└── TRAEFIK.md                      # Traefik documentation
```

## Important Notes

### Single-Node Considerations

1. **No High Availability**: Single point of failure
2. **Resource Constraints**: All workloads run on one node
3. **Control Plane Scheduling**: Enabled by default for single-node setup
4. **Backup Important**: Etcd runs on single node - backup regularly

### Security

- Dashboard admin user has cluster-admin role
- Tokens expire after 1 year by default
- Consider using RBAC for production workloads

### Network Configuration

- Node IP: `192.168.1.54` (configurable via `TALOS_NODE`)
- Kubernetes API: `https://192.168.1.54:6443`
- Pod Network: `10.244.0.0/16`
- Service Network: `10.96.0.0/12`

## Configuration Reference

### Key Configuration Settings

**configs/controlplane.yaml:551** - Allow scheduling on control plane:
```yaml
allowSchedulingOnControlPlanes: true
```

**configs/controlplane.yaml:510-534** - Auto-deploy Dashboard:
```yaml
extraManifests:
  - https://raw.githubusercontent.com/kubernetes/dashboard/v2.7.0/aio/deploy/recommended.yaml

inlineManifests:
  - name: dashboard-admin-user
    contents: |-
      # ServiceAccount and ClusterRoleBinding for dashboard access
```

## Cleanup

```bash
# Remove generated/output files only (.output directory)
task clean

# Remove ALL configs including Talos configs (destructive!)
task clean-all
```

## Dashboard Access Instructions

The kubectl proxy **must run on your local machine** (not the Talos node):

1. **Get Token** (on your Mac):
   ```bash
   task dashboard-token
   # Or: ./scripts/dashboard-token.sh
   ```

2. **Start Proxy** (on your Mac):
   ```bash
   task dashboard-proxy
   # Or: kubectl --kubeconfig ./.output/kubeconfig proxy
   ```

3. **Access Dashboard** (on your Mac browser):
   - URL: http://localhost:8001/api/v1/namespaces/kubernetes-dashboard/services/https:kubernetes-dashboard:/proxy/
   - Login with token from step 1

**Note**: The proxy creates a tunnel from your local machine to the cluster. The dashboard is NOT accessible directly from the node IP.

## Useful Commands

### Direct talosctl Commands

```bash
# Configure endpoints
talosctl config endpoint $TALOS_NODE --talosconfig ./talosconfig
talosctl config node $TALOS_NODE --talosconfig ./talosconfig

# Health check
talosctl --talosconfig ./talosconfig --nodes $TALOS_NODE health --server=false

# Bootstrap (only needed once)
talosctl --talosconfig ./talosconfig --nodes $TALOS_NODE bootstrap
```

### Direct kubectl Commands

```bash
# Check node taints
kubectl --kubeconfig ./kubeconfig describe node | grep -A 5 "Taints:"

# Remove control-plane taint (if needed)
kubectl --kubeconfig ./kubeconfig taint nodes <node-name> node-role.kubernetes.io/control-plane:NoSchedule-

# View all resources
kubectl --kubeconfig ./kubeconfig get all -A
```

## Support

For Talos documentation: https://www.talos.dev/
For Kubernetes documentation: https://kubernetes.io/docs/

## Version Info

### Core Infrastructure
- **Talos**: v1.11.1
- **Kubernetes**: v1.34.0
- **Dashboard**: v2.7.0
- **Traefik**: v3.5.3

### Deployed Services
- **ArgoCD**: v3.2.0
- **kube-prometheus-stack**: v0.86.2 (Prometheus Operator v0.86.2)
- **MongoDB**: v8.2.1
- **OpenSearch**: v3.3.2
- **Graylog**: Latest
- **Fluent Bit**: Latest

### Scripts Available
- `provision.sh` - Cluster provisioning
- `setup-infrastructure.sh` - Infrastructure deployment
- `deploy-stack.sh` - Complete stack deployment (monitoring + observability)
- `deploy-observability.sh` - Observability stack only
- `bootstrap-argocd.sh` - ArgoCD installation
- `bootstrap-complete-system.sh` - Full system bootstrap
- `build-and-deploy-catalyst-ui.sh` - Catalyst UI GitOps deployment
- `extract-arr-api-keys.sh` - Extract API keys from arr apps
- `cluster-audit.sh` - Generate cluster audit report
- `kubeconfig-merge.sh` - Merge kubeconfig to ~/.kube/config
- `kubeconfig-unmerge.sh` - Remove kubeconfig from ~/.kube/config
- `dashboard-token.sh` - Get Kubernetes Dashboard token
