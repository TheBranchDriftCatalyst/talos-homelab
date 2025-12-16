# Talos Homelab - Kubernetes Infrastructure

## TL;DR

Production-ready Kubernetes cluster on Talos Linux with dual GitOps (Flux + ArgoCD).

- **Control Plane:** 192.168.1.54 (talos00)
- **Dashboard:** http://grafana.talos00, http://argocd.talos00
- **Quick Start:** `task kubeconfig-merge && kubectl get nodes`
- **Architecture:** [TRAEFIK.md](TRAEFIK.md) | [Dual GitOps](docs/02-architecture/gitops-responsibilities.md)

## GitOps Architecture

This cluster uses a **dual GitOps pattern** with two distinct deployment workflows:

1. **Infrastructure GitOps** (this repo) - Manual, controlled platform deployments
   - Manages: ArgoCD, Traefik, Registry, Monitoring, Observability
   - Method: Scripts + kubectl apply

2. **Application GitOps** (app repos) - Automated, continuous deployments
   - Manages: Application workloads (e.g., catalyst-ui)
   - Method: ArgoCD watches and auto-syncs

**Full details**: See [docs/02-architecture/gitops-responsibilities.md](docs/02-architecture/gitops-responsibilities.md)

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
   talosctl gen config catalyst-cluster https://$TALOS_NODE:6443 --output-dir . --force
   ```

2. **Provision the Cluster**:

   ```bash
   ./scripts/provision.sh
   ```

   Or using Task:

   ```bash
   task provision
   ```

## Configuration Features

### Cluster Configuration

- **Control Plane Scheduling**: Configured with `allowSchedulingOnControlPlanes: true` to allow workloads on control plane nodes
- **Multi-Node Support**: Control plane (talos00) + worker nodes (talos01, etc.)
- **No Control Plane Taints**: Control-plane taint is removed automatically during provisioning

### Included Services

- **Talos Dashboard**: Built-in node monitoring
- **Kubernetes Dashboard**: Web UI for cluster management (auto-deployed via extraManifests)
- **CoreDNS**: DNS resolution (2 replicas)
- **Flannel**: CNI networking
- **etcd**: Distributed key-value store for cluster state

### Observability Stack

- **Prometheus**: Metrics collection and alerting (30-day retention, 50Gi storage)
- **Grafana**: Metrics visualization and dashboards
- **Alertmanager**: Alert routing and management
- **Graylog**: Centralized log management platform
- **MongoDB**: Database backend for Graylog (20Gi storage)
- **OpenSearch**: Log storage and indexing (30Gi storage)
- **Fluent Bit**: Log collection from all containers
- **Exportarr**: Prometheus exporters for \*arr applications

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

- Grafana: http://grafana.talos00 (admin / see `kubectl get secret -n monitoring grafana-admin-credentials -o jsonpath='{.data.GF_SECURITY_ADMIN_PASSWORD}' | base64 -d`)
- Prometheus: http://prometheus.talos00 (via Mimir at http://mimir.talos00)
- Alertmanager: http://alertmanager.talos00 (via Grafana alerting)
- Graylog: http://graylog.talos00 (admin / admin)

### Deploy Applications (arr stack)

```bash
# Deploy media applications
kubectl apply -k applications/arr-stack/overlays/dev
```

This includes:

- Prowlarr (indexer manager)
- Sonarr (TV shows)
- Radarr (movies)
- Readarr (books)
- Overseerr (request management)
- Plex (media server)
- Jellyfin (media server)
- Homepage (dashboard)
- Exportarr (Prometheus metrics for \*arr apps)

## Common Tasks

This repository uses a modular Taskfile structure organized by domain. Tasks are grouped into:

- `talos:*` - Talos Linux operations (config, bootstrap, health, services)
- `k8s:*` - Kubernetes operations (kubeconfig, pods, dashboard, audit)
- `dev:*` - Development tools (linting, formatting, hooks, validation)
- `infra:*` - Infrastructure deployment (monitoring, observability, apps)

**Quick reference:**

```bash
task                # Show available domains and commands
task --list         # List all available tasks
task --list-all     # Show all tasks with descriptions
```

For complete documentation of all available tasks, see [docs/07-reference/taskfile-organization.md](docs/07-reference/taskfile-organization.md).

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
kubectx catalyst-cluster   # Switch to this cluster
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

### Dashboard Access

See [QUICKSTART.md](QUICKSTART.md#access-kubernetes-dashboard) for complete dashboard access instructions.

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
│   ├── worker.yaml                 # Worker node configuration template
│   └── talosconfig                 # Talos CLI configuration
├── infrastructure/base/             # Kubernetes infrastructure manifests
│   ├── argocd/                     # ArgoCD GitOps controller
│   ├── traefik/                    # Traefik ingress controller
│   ├── monitoring/                 # Prometheus, Grafana, Alertmanager
│   ├── observability/              # OpenSearch, Graylog, Fluent Bit
│   ├── registry/                   # Nexus container registry
│   ├── storage/                    # Storage classes and PVCs
│   └── namespaces/                 # Namespace definitions
├── applications/                    # Application workloads
│   └── arr-stack/                  # Media management applications
├── scripts/                         # Automation scripts
│   ├── provision.sh                # Complete cluster provisioning
│   ├── deploy-stack.sh             # Deploy complete infrastructure stack
│   ├── deploy-observability.sh     # Deploy monitoring and logging
│   ├── cluster-audit.sh            # Generate Markdown audit report
│   ├── dashboard-token.sh          # Retrieve dashboard access token
│   └── kubeconfig-merge.sh         # Merge kubeconfig to ~/.kube/config
├── .output/                         # Generated files (gitignored)
│   ├── kubeconfig                  # Kubernetes cluster access config
│   ├── dashboard-token.txt         # Latest dashboard token
│   └── audit/                      # Cluster audit reports
│       └── cluster-audit-*.md      # Timestamped audit reports
├── docs/                            # Documentation
│   ├── 01-getting-started/         # Quick start guides
│   ├── 02-architecture/            # Architecture decisions and patterns
│   ├── 03-operations/              # Operational procedures
│   ├── 04-deployment/              # Deployment guides
│   ├── 05-projects/                # Project-specific documentation
│   ├── 06-project-management/      # Planning and progress tracking
│   └── 07-reference/               # Reference documentation
├── .gitignore                      # Git ignore patterns
├── Taskfile.yaml                   # Root task orchestrator
├── Taskfile.talos.yaml             # Talos-specific tasks
├── Taskfile.k8s.yaml               # Kubernetes-specific tasks
├── Taskfile.dev.yaml               # Development tooling tasks
├── Taskfile.infra.yaml             # Infrastructure deployment tasks
├── README.md                       # This file
├── QUICKSTART.md                   # Quick reference guide
├── TRAEFIK.md                      # Traefik ingress documentation
├── IMPLEMENTATION-TRACKER.md       # Implementation progress tracking
└── CLAUDE.md                       # Claude Code agent guidance
```

## Important Notes

### Multi-Node Considerations

1. **Nodes**: Control plane (talos00 @ 192.168.1.54) + Worker (talos01 @ 192.168.1.177)
2. **Control Plane Scheduling**: Enabled to allow workloads on control plane
3. **Workload Distribution**: Pods can schedule on any node without taints
4. **Backup Important**: Etcd runs on control plane - backup regularly

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

## Useful Commands

### Direct talosctl Commands

```bash
# Configure endpoints
talosctl config endpoint $TALOS_NODE --talosconfig ./configs/talosconfig
talosctl config node $TALOS_NODE --talosconfig ./configs/talosconfig

# Health check
talosctl --talosconfig ./configs/talosconfig --nodes $TALOS_NODE health --server=false

# Bootstrap (only needed once)
talosctl --talosconfig ./configs/talosconfig --nodes $TALOS_NODE bootstrap
```

### Direct kubectl Commands

```bash
# Check node taints
kubectl --kubeconfig ./.output/kubeconfig describe node | grep -A 5 "Taints:"

# Remove control-plane taint (if needed)
kubectl --kubeconfig ./.output/kubeconfig taint nodes <node-name> node-role.kubernetes.io/control-plane:NoSchedule-

# View all resources
kubectl --kubeconfig ./.output/kubeconfig get all -A
```

## Support

For Talos documentation: https://www.talos.dev/
For Kubernetes documentation: https://kubernetes.io/docs/

## Version Info

- Talos: v1.11.1
- Kubernetes: v1.34.0
- Dashboard: v2.7.0

## Related Issues

This README was restructured as part of the Cilium migration documentation effort:

- **CILIUM-3l7**: Restructure README.md (root) - Updated paths, added TL;DR, removed duplication
