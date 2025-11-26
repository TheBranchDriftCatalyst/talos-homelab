# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a **Talos Linux single-node Kubernetes cluster** infrastructure repository using a dual GitOps pattern. It manages platform infrastructure (not applications) through manual, controlled deployments.

**Key Characteristics:**

- Single-node cluster: Control plane scheduling enabled, no worker nodes
- Talos Linux: Immutable Kubernetes OS (config via `talosctl`, not SSH)
- Dual GitOps: This repo = infrastructure; App repos = ArgoCD-managed applications
- Node IP: `192.168.1.54` (configurable via `TALOS_NODE` env var)

## Documentation Structure

This repository maintains comprehensive documentation organized in multiple locations:

### Root-Level Documentation

- Quick-start guides and operational references
- Platform-specific documentation (Traefik, Observability)
- Implementation tracking

### `docs/` Directory

- Architecture documentation
- Deployment guides
- Migration assessments
- Progress tracking

### `bootstrap/` Directory

- Bootstrap-specific README files
- Tool-specific setup guides (ArgoCD, Flux)

### `configs/` Directory

- Configuration documentation
- Talos-specific configuration guides

## Documentation Table of Contents

### Root Documentation

| Document                    | Description                                                                                    |
| --------------------------- | ---------------------------------------------------------------------------------------------- |
| `README.md`                 | Main repository documentation - Quick start guide, cluster overview, deployment workflows      |
| `QUICKSTART.md`             | Quick reference guide - Essential commands and common tasks                                    |
| `TRAEFIK.md`                | Traefik ingress controller documentation - IngressRoute configuration, hostnames, certificates |
| `OBSERVABILITY.md`          | Monitoring and logging stack - Prometheus, Grafana, OpenSearch, Graylog, Fluent Bit            |
| `IMPLEMENTATION-TRACKER.md` | Implementation progress tracking - Completed features, pending tasks                           |
| `CLAUDE.md`                 | **THIS FILE** - Guidance for Claude Code instances working in this repository                  |

### docs/ - Detailed Documentation

| Document                            | Description                                                                                          |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `docs/DUAL-GITOPS.md`               | **CRITICAL** - Dual GitOps architecture pattern, rules, and workflows                                |
| `docs/catalyst-ui-deployment.md`    | Catalyst UI deployment guide - Docker registry, ArgoCD application setup, troubleshooting            |
| `docs/DUAL-GITOPS-ARCHITECTURE.md`  | Additional GitOps architecture documentation and diagrams                                            |
| `docs/FLUX-MIGRATION-ASSESSMENT.md` | FluxCD migration assessment - Comparison with ArgoCD, pros/cons                                      |
| `docs/infra-testing-tools.md`       | Infrastructure testing UI tools - Headlamp, Kubeview, Kube-ops-view, Goldilocks deployment and usage |
| `docs/kubernetes-ui-tools.md`       | Comprehensive guide to Kubernetes UI tools - Comparison and evaluation of available options          |
| `docs/LOCAL-TESTING.md`             | Local testing guide - Testing infrastructure changes before deployment                               |
| `docs/node-shutdown-procedure.md`   | Node shutdown and restart guide - Safe procedures for hardware maintenance and recovery              |
| `docs/ENHANCEMENT-ROADMAP.md`       | **Enhancement Roadmap** - MCP server and Tilt extension integration planning (2-stream project)       |
| `docs/PROGRESS-SUMMARY.md`          | Progress summary - Session-by-session tracking of implementation work                                |
| `docs/TALOS-PROVISIONING-STEPS.md`  | Talos provisioning steps - Detailed cluster setup and bootstrap process                              |
| `docs/tilt-development-workflow.md` | Tilt development workflow - Hot-reload development environment for infrastructure manifests          |

### bootstrap/ - Bootstrap Documentation

| Document                     | Description                                                                 |
| ---------------------------- | --------------------------------------------------------------------------- |
| `bootstrap/argocd/README.md` | ArgoCD bootstrap documentation - Installation, configuration, initial setup |
| `bootstrap/flux/README.md`   | Flux bootstrap documentation - Installation steps, repository structure     |

### configs/ - Configuration Documentation

| Document           | Description                                                                         |
| ------------------ | ----------------------------------------------------------------------------------- |
| `configs/TALOS.md` | Talos configuration documentation - Machine config structure, customization options |

### **⚠️ MAINTENANCE INSTRUCTION ⚠️**

**When adding new documentation or making changes to existing documentation:**

1. **Update this CLAUDE.md file** with the new document entry in the appropriate table
2. **Add a brief description** of what the document covers
3. **Mark critical documents** with **CRITICAL** or other importance indicators
4. **Keep the Table of Contents alphabetized** within each section for easy navigation
5. **Update the "Documentation References" section** near the bottom of this file if adding important references

This ensures future Claude Code instances can quickly locate and understand all available documentation.

## Task Automation Structure

This repository uses a **modular Taskfile structure** organized by domain for better maintainability and discoverability.

### Taskfile Organization

```
.
├── Taskfile.yaml          # Root orchestrator with common shortcuts
├── Taskfile.talos.yaml    # Talos Linux operations (33 tasks)
├── Taskfile.k8s.yaml      # Kubernetes operations (18 tasks)
├── Taskfile.dev.yaml      # Development tools (17 tasks)
└── Taskfile.infra.yaml    # Infrastructure deployment (22 tasks)
```

### Task Domains

1. **Talos:** - Talos Linux cluster management
   - Configuration generation, node provisioning, bootstrapping
   - Health checks, service management, troubleshooting
   - Node operations (reboot, shutdown, reset, upgrade)
   - etcd operations

2. **k8s:** - Kubernetes cluster operations
   - Kubeconfig management (merge, unmerge, export)
   - Resource queries (nodes, pods, all resources)
   - Dashboard access and tokens
   - Cluster auditing, events, logs

3. **dev:** - Development tools and code quality
   - Environment setup (Homebrew, Yarn, git hooks)
   - Linting (YAML, shell, markdown, secrets)
   - Formatting (shell, markdown, prettier)
   - Validation (kustomize, kubectl dry-run)
   - CI simulation

4. **infra:** - Infrastructure and application deployment
   - Stack deployment (monitoring, observability)
   - GitOps controllers (ArgoCD, FluxCD)
   - External Secrets Operator, Registry
   - Application deployments

### Using Tasks

```bash
# Show available domains and common tasks
task

# List all tasks
task --list

# Use domain-specific tasks (explicit)
task talos:health
task k8s:get-pods
task dev:lint
task infra:deploy-stack

# Use shortcuts (common tasks)
task health              # → talos:health
task get-pods            # → k8s:get-pods
task lint                # → dev:lint

# Get task details
task --summary talos:health
```

**Full documentation**: See [docs/taskfile-organization.md](docs/taskfile-organization.md) for complete task reference.

## Essential Commands

### Cluster Access & Health

```bash
# Set node IP (required for most commands)
export TALOS_NODE=192.168.1.54

# Merge kubeconfig to ~/.kube/config (enables kubectl/kubectx/k9s)
task kubeconfig-merge

# Check cluster health
task health

# View Talos dashboard
task dashboard

# Get all pods
task get-pods

# Access Kubernetes Dashboard
task dashboard-token    # Get token
task dashboard-proxy    # Start proxy, access at localhost:8001
```

### Infrastructure Deployment

```bash
# Deploy complete stack (monitoring + observability + infrastructure)
./scripts/deploy-stack.sh

# Deploy specific stack components
DEPLOY_MONITORING=true DEPLOY_OBSERVABILITY=false ./scripts/deploy-stack.sh

# Deploy observability stack only
./scripts/deploy-observability.sh

# Bootstrap ArgoCD
./scripts/bootstrap-argocd.sh

# Build and deploy catalyst-ui (application example)
./scripts/build-and-deploy-catalyst-ui.sh
```

### Cluster Provisioning (Fresh Setup)

```bash
# Complete provisioning workflow
task provision
# Or: ./scripts/provision.sh

# Individual steps:
task gen-config              # Generate Talos configs
task apply-config INSECURE=true  # Apply config (first time)
task bootstrap               # Bootstrap etcd
task kubeconfig             # Download kubeconfig
```

### Troubleshooting

```bash
# View service logs
task service-logs -- SERVICE=kubelet

# Follow logs
task logs-follow -- SERVICE=kubelet

# View kernel logs
task dmesg

# List containers
task containers

# Check etcd status
task etcd-status
```

## Architecture & Dual GitOps Pattern

**READ FIRST:** `docs/DUAL-GITOPS.md` - Complete dual GitOps documentation

### Two Distinct Patterns

1. **Infrastructure GitOps (THIS REPO)**
   - Tool: Scripts + `kubectl apply`
   - Deployment: Manual, controlled
   - Manages: Platform services (ArgoCD, Traefik, Registry, Monitoring)
   - Philosophy: Intentional changes, explicit execution

2. **Application GitOps (App Repos)**
   - Tool: ArgoCD
   - Deployment: Automated, continuous
   - Manages: Application workloads
   - Philosophy: Push to main = auto-deploy

### Critical Rules

- **Infrastructure changes**: Modify manifests → Run deployment script → kubectl apply
- **Application changes**: Modify app repo → Push to GitHub → ArgoCD auto-syncs
- **NEVER mix**: Infrastructure manifests stay in this repo, app manifests in app repos
- **ArgoCD Application definitions**: Live in `infrastructure/base/argocd/applications/`

## Repository Structure

```
talos-fix/
├── infrastructure/base/      # Platform infrastructure (modify these)
│   ├── argocd/              # ArgoCD (GitOps controller for apps)
│   ├── traefik/             # Ingress controller
│   ├── registry/            # Docker registry
│   ├── monitoring/          # Prometheus, Grafana, Loki
│   ├── observability/       # OpenSearch, FluentBit, Graylog
│   ├── storage/             # Storage classes, PVCs
│   └── namespaces/          # Infrastructure namespaces
├── infrastructure/overlays/  # Environment-specific overrides
├── applications/arr-stack/  # Media apps (Sonarr, Radarr, etc.)
├── scripts/                 # Deployment automation
├── configs/                 # Talos machine configs (gitignored - sensitive)
└── docs/                    # Documentation
```

### Key Files

- `Taskfile.yaml` - Task automation (preferred over direct talosctl/kubectl)
- `scripts/deploy-stack.sh` - Main infrastructure deployment script
- `scripts/provision.sh` - Complete cluster provisioning
- `configs/controlplane.yaml` - Talos control plane config (gitignored)
- `infrastructure/base/argocd/applications/` - ArgoCD app definitions

## How Infrastructure Deployment Works

### Deployment Script Pattern

All deployment scripts follow this pattern:

1. Verify cluster health
2. Apply namespaces first
3. Apply base manifests (kubectl apply -k)
4. Wait for pods to be ready
5. Apply additional configurations

**Example:**

```bash
# Deploy monitoring stack
kubectl apply -k infrastructure/base/monitoring/kube-prometheus-stack/
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=prometheus -n monitoring
```

### Kustomize Usage

Infrastructure uses Kustomize for configuration management:

- `base/` - Common configurations
- `overlays/dev/` - Development overrides
- `overlays/prod/` - Production overrides

Apply with: `kubectl apply -k path/to/kustomization/`

## Important Talos Specifics

### Talos is NOT a traditional Linux

- **No SSH**: Use `talosctl shell` for emergency access (very limited)
- **No package manager**: Everything runs in Kubernetes
- **Immutable OS**: Changes via machine config only
- **Config application**: `talosctl apply-config` triggers node reboot
- **API access**: Talos API on port 50000, Kubernetes API on 6443

### Single-Node Considerations

- Control plane scheduling **enabled** by default (`allowSchedulingOnControlPlanes: true`)
- No high availability - single point of failure
- All workloads run on one node - watch resource limits
- Control plane taint **removed** during provisioning

### Configuration Management

```bash
# Apply new Talos configuration (TRIGGERS REBOOT)
task apply-config

# Upgrade Talos version
task upgrade -- VERSION=v1.11.2

# DESTRUCTIVE: Reset node (wipes all data)
task reset
```

## Accessing Services

### Via Traefik IngressRoutes

All services accessible via hostname (requires `/etc/hosts` entry for `*.talos00`):

```
192.168.1.54  argocd.talos00 grafana.talos00 prometheus.talos00 \
              alertmanager.talos00 graylog.talos00 registry.talos00 \
              sonarr.talos00 radarr.talos00 prowlarr.talos00 \
              plex.talos00 jellyfin.talos00 tdarr.talos00 catalyst.talos00
```

Access: `http://<service>.talos00`

### Default Credentials

- **Grafana**: admin / prom-operator
- **Graylog**: admin / admin
- **ArgoCD**: admin / (get via `kubectl -n argocd get secret argocd-initial-admin-secret`)

## Common Patterns & Workflows

### Adding a New Infrastructure Component

1. Create manifests: `infrastructure/base/new-component/`
2. Create kustomization.YAML
3. Update deployment script or create new one
4. Test: `kubectl apply -k infrastructure/base/new-component/ --dry-run=client`
5. Deploy: `./scripts/deploy-stack.sh` or specific script
6. Verify: `kubectl get pods -n <namespace>`

### Adding a New Application (ArgoCD)

1. Create k8s manifests in application repo (e.g., `catalyst-ui/k8s/`)
2. Create ArgoCD Application: `infrastructure/base/argocd/applications/my-app.yaml`
3. Apply: `kubectl apply -f infrastructure/base/argocd/applications/my-app.yaml`
4. ArgoCD auto-syncs from app repo going forward

### Debugging Deployment Issues

```bash
# Check pod status
kubectl get pods -A | grep -v Running

# Describe failing pod
kubectl describe pod <pod-name> -n <namespace>

# View logs
kubectl logs <pod-name> -n <namespace>

# Check events
kubectl get events -n <namespace> --sort-by='.lastTimestamp'

# For Talos issues
task service-logs -- SERVICE=kubelet
task dmesg
```

## Storage Configuration

### Available Storage Classes

- `local-path` (default) - Rancher local-path-provisioner
- `nfs` - NFS storage (if configured)
- Manual PVs for specific workloads

### PVC Pattern

Applications use shared PVCs in media namespaces:

- `media-dev` namespace - Development media storage
- `media-prod` namespace - Production media storage
- Shared configs/downloads PVCs across \*arr apps

## Monitoring & Observability Stack

### Components

**Monitoring** (`monitoring` namespace):

- Prometheus - Metrics collection (30-day retention, 50Gi)
- Grafana - Visualization
- Alertmanager - Alert routing

**Observability** (`observability` namespace):

- OpenSearch - Log storage (30Gi)
- Fluent Bit - Log collection
- Graylog - Log management UI
- MongoDB - Graylog backend (20Gi)

### Accessing Metrics

```bash
# Port-forward Prometheus
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-stack-prometheus 9090:9090

# Query via PromQL
curl http://localhost:9090/api/v1/query?query=up
```

## Docker Registry Usage

Local registry for application images:

- URL: `registry.talos00` (HTTP)
- Storage: 50Gi PVC
- Access: Via Traefik IngressRoute or kubectl port-forward

### Building & Pushing Images

```bash
# Example: catalyst-ui
cd ~/catalyst-devspace/workspace/catalyst-ui
docker build -t registry.talos00/catalyst-ui:latest .

# Push via port-forward (NodePort not externally accessible on Talos)
kubectl port-forward -n registry svc/docker-registry 5000:5000 &
docker tag registry.talos00/catalyst-ui:latest localhost:5000/catalyst-ui:latest
docker push localhost:5000/catalyst-ui:latest
```

**Docker daemon.JSON configuration required:**

```json
{
  "insecure-registries": ["localhost:5000", "registry.talos00"]
}
```

## Known Issues & Workarounds

### Docker Registry Access

- **Issue**: NodePort not externally accessible on Talos
- **Workaround**: Use `kubectl port-forward` to localhost:5000
- **Alternative**: HTTP push via Traefik has blob upload issues (404 errors)

### Storage Class

- **Issue**: `openebs-hostpath` not available
- **Solution**: Use `local-path` storage class instead

### Control Plane Scheduling

- **Expected**: Workloads schedule on control plane (single-node cluster)
- **Verification**: `kubectl describe node | grep Taints` should show no taints

## Important File Locations

### Configs (gitignored)

- `configs/controlplane.yaml` - Talos machine config
- `configs/talosconfig` - Talos CLI config
- `.output/kubeconfig` - Kubernetes access config

### Generated Files

- `.output/dashboard-token.txt` - K8s Dashboard token
- `.output/audit/` - Cluster audit reports

### Environment Variables

- `TALOS_NODE` - Node IP address (default: 192.168.1.54)
- `DEPLOY_MONITORING` - Enable monitoring deployment
- `DEPLOY_OBSERVABILITY` - Enable observability deployment
- `DEPLOY_APPS` - Enable application deployment

## Quick Reference

### Most Common Tasks

```bash
# Daily operations
task health                  # Check cluster health
task get-pods               # View all pods
kubectl get all -A          # View all resources

# Deploy changes
./scripts/deploy-stack.sh   # Deploy infrastructure
kubectl apply -k path/      # Apply specific component

# Access services
task dashboard-token        # Get K8s Dashboard token
task dashboard-proxy        # Access dashboard
open http://grafana.talos00 # Access Grafana

# Troubleshooting
task service-logs -- SERVICE=kubelet
kubectl logs <pod> -n <namespace>
kubectl describe pod <pod> -n <namespace>
```

### Emergency Recovery

```bash
# Cluster not responding
task health                 # Check Talos health
task reboot                # Reboot node

# Corrupted config
task gen-config            # Regenerate configs
task provision             # Re-provision cluster

# Complete reset (DESTRUCTIVE)
task reset                 # Wipes all data
task provision             # Rebuild from scratch
```

## Documentation References

- `README.md` - Quick start and cluster overview
- `docs/DUAL-GITOPS.md` - **CRITICAL** - Dual GitOps architecture
- `docs/catalyst-ui-deployment.md` - Application deployment example
- `TRAEFIK.md` - Ingress configuration
- `OBSERVABILITY.md` - Monitoring and logging stack
- `QUICKSTART.md` - Quick reference guide

## Development Workflow

When working on infrastructure changes:

1. **Modify manifests** in `infrastructure/base/<component>/`
2. **Test locally**: `kubectl apply -k <path> --dry-run=client`
3. **Commit changes** to git
4. **Deploy**: Run appropriate deployment script
5. **Verify**: Check pod status and logs
6. **Document**: Update relevant docs if adding new components

When adding applications:

1. **Create manifests** in application repository
2. **Create ArgoCD Application** in this repo
3. **Apply ArgoCD App**: `kubectl apply -f infrastructure/base/argocd/applications/<app>.yaml`
4. **ArgoCD handles the rest** - automatic sync from app repo
