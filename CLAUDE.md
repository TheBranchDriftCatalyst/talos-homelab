# CLAUDE.md

## TL;DR

Talos Linux Kubernetes cluster infrastructure repo. Uses **beads** for task tracking, **dual GitOps** (Flux + ArgoCD), and **Taskfile** automation.

**Quick Start:**
```bash
bd ready                    # Find work to do
task talos:health           # Check cluster health
task k8s:kubeconfig-merge   # Enable kubectl access
```

**Key Facts:**
- Control Plane IP: `192.168.1.54` (or `$TALOS_NODE`)
- Services: `http://<service>.talos00` (requires /etc/hosts)
- Talos = immutable OS, no SSH, config via `talosctl`

---

## Beads Workflow (Task Tracking)

This repo uses **beads** for issue tracking via MCP tools. NOT TodoWrite, NOT markdown TODOs.

### Session Protocol

```bash
# Start of session
bd ready                              # Find available work

# Working on task
bd update CILIUM-xxx --status=in_progress  # Claim work
# ... do the work ...
bd close CILIUM-xxx                   # Mark complete

# End of session (CRITICAL - never skip)
git status && git add <files>
bd sync                               # Sync beads to git
git commit -m "..."
git push
```

### Essential Commands

| Command | Purpose |
|---------|---------|
| `bd ready` | Show unblocked issues ready to work |
| `bd list --status=open` | All open issues |
| `bd show <id>` | Detailed view with dependencies |
| `bd create --title="..." --type=task` | Create issue |
| `bd update <id> --status=in_progress` | Claim work |
| `bd close <id>` | Mark complete |
| `bd blocked` | Show blocked issues |
| `bd stats` | Project health |

### Dependencies

```bash
bd dep add <issue> <depends-on>  # issue depends on depends-on
```

### When to Create Issues

- Multi-step work spanning sessions → create issue
- Quick fix done immediately → no issue needed
- Discovery during work → create issue, link as dependency

---

## Documentation Pattern

### Progressive Summarization

All docs should follow this structure:
1. **TL;DR** - 1-2 sentences + bullets (30 sec read)
2. **Quick Reference** - Common operations (5 min)
3. **Deep Dive** - Full details (reference)

### Section READMEs

Parent READMEs (e.g., `docs/01-getting-started/README.md`) summarize children for drill-down navigation.

### Related Issues Footer

Every doc should end with:
```markdown
---
## Related Issues
<!-- Beads tracking for this doc -->
```

### When to Update Docs

- Changed code/config that docs describe → update docs
- Found incorrect docs → fix or create beads issue

---

## Key Documentation

| Doc | Purpose |
|-----|---------|
| `QUICKSTART.md` | Essential commands reference |
| `TRAEFIK.md` | Ingress configuration |
| `OBSERVABILITY.md` | Monitoring/logging stack |
| `docs/02-architecture/dual-gitops.md` | **CRITICAL** - GitOps pattern |

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

**Full documentation**: See [docs/07-reference/taskfile-organization.md](docs/07-reference/taskfile-organization.md) for complete task reference.

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
talos-homelab/
├── infrastructure/base/      # Platform infrastructure (modify these)
│   ├── argocd/              # ArgoCD (GitOps controller for apps)
│   ├── cilium/              # CNI (migrating from Flannel)
│   ├── traefik/             # Ingress controller
│   ├── registry/            # Docker registry (Nexus)
│   ├── monitoring/          # Prometheus, Grafana, Loki
│   ├── observability/       # OpenSearch, FluentBit, Graylog
│   └── storage/             # Storage classes, NFS
├── applications/            # App deployments (arr-stack, etc.)
├── clusters/catalyst-cluster/ # Flux cluster config
├── scripts/                 # Deployment automation
├── configs/                 # Talos machine configs (gitignored)
└── docs/                    # Documentation (numbered sections)
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

### Multi-Node Cluster

- **Nodes**: Control plane (talos00 @ 192.168.1.54) + Worker (talos01 @ 192.168.1.177)
- Control plane scheduling **enabled** (`allowSchedulingOnControlPlanes: true`)
- Workloads can schedule on any node
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
              nexus.talos00 npm.talos00 docker-proxy.talos00 \
              sonarr.talos00 radarr.talos00 prowlarr.talos00 \
              plex.talos00 jellyfin.talos00 tdarr.talos00 catalyst.talos00 \
              hubble.talos00
```

Access: `http://<service>.talos00`

### Default Credentials

- **Grafana**: admin / prom-operator
- **Graylog**: admin / admin
- **ArgoCD**: admin / (get via `kubectl -n argocd get secret argocd-initial-admin-secret`)
- **Nexus**: admin / (get via `kubectl exec -n registry deploy/nexus -- cat /nexus-data/admin.password`)

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

## Nexus Repository Usage

Nexus Repository OSS - Universal artifact repository for Docker, npm, PyPI, and more.

### Available Registries

| Registry        | URL                         | Port | Description              |
| --------------- | --------------------------- | ---- | ------------------------ |
| Nexus UI        | http://nexus.talos00        | 8081 | Web management interface |
| Docker (hosted) | http://registry.talos00     | 5000 | Private Docker images    |
| Docker (proxy)  | http://docker-proxy.talos00 | 5001 | Docker Hub cache         |
| npm             | http://npm.talos00          | 8082 | npm packages             |

### Initial Setup

After first deployment, get the admin password:

```bash
kubectl exec -n registry deploy/nexus -- cat /nexus-data/admin.password
```

Then login at http://nexus.talos00 and create repositories (see `infrastructure/base/registry/README.md`).

### Building & Pushing Docker Images

```bash
# Example: catalyst-ui
cd ~/catalyst-devspace/workspace/catalyst-ui
docker build -t registry.talos00/catalyst-ui:latest .

# Push via port-forward
kubectl port-forward -n registry svc/nexus-docker 5000:5000 &
docker tag registry.talos00/catalyst-ui:latest localhost:5000/catalyst-ui:latest
docker push localhost:5000/catalyst-ui:latest
```

### npm Registry Usage

```bash
# Configure npm to use local registry
npm config set registry http://npm.talos00/repository/npm-hosted/

# Publish package
npm login --registry=http://npm.talos00/repository/npm-hosted/
npm publish
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
- **Workaround**: Use `kubectl port-forward -n registry svc/nexus-docker 5000:5000`
- **Note**: Nexus startup takes 2-3 minutes due to Java initialization

### Storage Class

- **Issue**: `openebs-hostpath` not available
- **Solution**: Use `local-path` storage class instead

### Control Plane Scheduling

- **Expected**: Workloads schedule on all nodes (control plane + workers)
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

> **⚠️ Flux Warning**: This is a Flux-managed repo. Flux may reconcile over manual `kubectl apply` commands. Use Flux Kustomizations for persistent changes.

---

## Related Issues
<!-- Beads tracking for CLAUDE.md -->
- CILIUM-h2b - Initial restructure with beads workflow section