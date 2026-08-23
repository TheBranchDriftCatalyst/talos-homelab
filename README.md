# Talos Homelab - Kubernetes Infrastructure

## TL;DR

Production-ready Kubernetes cluster on Talos Linux with dual GitOps (Flux + ArgoCD).

- **Control Plane:** 192.168.1.54 (talos00) — 5 nodes: talos00, talos01, talos02-gpu, talos03, talos06
- **Dashboard:** http://grafana.talos00, http://argocd.talos00
- **Quick Start:** `task kubeconfig && KUBECONFIG=./.output/kubeconfig kubectl get nodes`
- **Architecture:** [TRAEFIK.md](TRAEFIK.md) | [Dual GitOps](docs/02-architecture/dual-gitops.md)
- **All docs:** [docs/INDEX.md](docs/INDEX.md)

> ⚠️ `task kubeconfig-merge` is currently broken — it calls `./scripts/kubeconfig-merge.sh`, which
> no longer exists (the script moved to `scripts/developer/`, and that copy sources a `lib/common.sh`
> that is not there either). Use `task kubeconfig` + `KUBECONFIG` until it is repaired.

## GitOps Architecture

This cluster uses a **dual GitOps pattern** with two distinct deployment workflows:

1. **Infrastructure GitOps** (this repo, FluxCD) - Platform services reconciled from Git
   - Manages: Cilium, Traefik, storage, cert-manager, Authentik, CrowdSec, Kyverno, monitoring,
     external-secrets, and ArgoCD itself
   - Method: ~60 Flux `Kustomization`s under `clusters/catalyst-cluster/`, pointing at
     `infrastructure/base/*` and `applications/*`
   - Status: `task flux-status` (or `flux get kustomizations -A`)

2. **Application GitOps** (app repos, ArgoCD) - Automated, continuous deployments
   - Manages: Application workloads — currently `catalyst-ui`, `catalyst-llm`, `catalyst-data`,
     `boomtime`, `dungeon-library`, `kasa-exporter`, `openscad`, `arr-stack-private`
   - Method: ArgoCD watches each app repo and auto-syncs

> Note: the manual "scripts + kubectl apply" model this section used to describe is retired.
> Direct `kubectl apply` against infrastructure is reverted on the next Flux reconcile.

**Full details**: See [docs/02-architecture/dual-gitops.md](docs/02-architecture/dual-gitops.md)
(authoritative). [gitops-responsibilities.md](docs/02-architecture/gitops-responsibilities.md) covers
the same ground but is stale — it still says Flux is "NOT YET DEPLOYED".

## Documentation

Full navigation: **[docs/INDEX.md](docs/INDEX.md)**.

| Section                                                            | Contents                                                                  |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------- |
| [01-getting-started](docs/01-getting-started/README.md)            | Onboarding, cluster facts, fresh-cluster setup                            |
| [02-architecture](docs/02-architecture/README.md)                  | GitOps model, networking, DNS HA, service mesh, auth, ADRs                |
| [03-operations](docs/03-operations/README.md)                      | Provisioning, node shutdown, etcd backup/restore, dev tooling             |
| [04-deployment](docs/04-deployment/README.md)                      | Flux and ArgoCD bootstrap + deployment workflows                          |
| [05-projects](docs/05-projects/README.md)                          | Per-project design docs (OTEL migration, hybrid LLM, optimization)        |
| [05-runbooks](docs/05-runbooks/README.md)                          | Recovery/migration procedures + Talos machine-config patches              |
| [06-project-management](docs/06-project-management/README.md)      | Roadmaps and idea backlogs (work itself lives in beads)                   |
| [06-troubleshooting](docs/06-troubleshooting/README.md)            | Post-mortems and hardware/kernel workarounds                              |
| [07-reference](docs/07-reference/README.md)                        | CRD catalog, Taskfile reference, cloud GPU sizing                         |
| [08-monitoring](docs/08-monitoring/README.md)                      | Grafana dashboard index and query audit                                   |
| [patterns](docs/patterns/README.md)                                | Reusable cluster patterns                                                 |
| [investigations](docs/investigations/README.md) · [changelogs](docs/changelogs/README.md) · [retros](docs/retros/README.md) · [_archive](docs/_archive/README.md) | Audits, update campaigns, retrospectives, history |

Root-level docs: [QUICKSTART.md](QUICKSTART.md) · [CONTRIBUTING.md](CONTRIBUTING.md) ·
[TRAEFIK.md](TRAEFIK.md) · [OBSERVABILITY.md](OBSERVABILITY.md) · [SECURITY_ops.md](SECURITY_ops.md) ·
[CLAUDE.md](CLAUDE.md) · [AGENTS.md](AGENTS.md) · [SKILLZ.md](SKILLZ.md) ·
[IMPLEMENTATION-TRACKER.md](IMPLEMENTATION-TRACKER.md) (frozen 2025-12-12) ·
[DAH_REPORT.md](DAH_REPORT.md) (2026-03-14 analysis)

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
   task talos:gen-config   # writes controlplane.yaml / worker.yaml / talosconfig into ./configs/
   ```

   > ⚠️ The machine configs actually in use live in `configs/nodes/` (`controlplane.yaml`,
   > `worker-base.yaml`, per-node worker files) — that is what `task talos:apply-config` reads.
   > `task talos:gen-config` and `scripts/provision.sh` still use the flat `configs/` layout.

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

- **Control Plane Scheduling**: `allowSchedulingOnControlPlanes: true` is still set in the machine config
- **Multi-Node**: 5 nodes — talos00 (control plane, 192.168.1.54), talos01 (192.168.1.177),
  talos02-gpu (192.168.1.144, Intel Arc), talos03 (192.168.1.30), talos06 (192.168.1.19)
- **talos00 Is Tainted, The Other Control Planes Are Not**: despite
  `allowSchedulingOnControlPlanes`, the machine config sets
  `machine.nodeTaints: node-role.kubernetes.io/control-plane: NoSchedule`, so talos00 runs only core
  infrastructure. That taint is deliberate for talos00 (RAM-limited) and applies to it alone.
  talos01 and talos03 were promoted to control planes on 2026-08-23 to ADD capacity and had the
  taint removed via `configs/nodes/schedulable-controlplane-patch.yaml`. Four of five nodes are
  schedulable.
  **`allowSchedulingOnControlPlanes` does not override `machine.nodeTaints`** — Talos applies
  nodeTaints on an unconditional code path that never reads that flag, so the two can both be set
  and appear to contradict each other. nodeTaints wins. If a control plane is unexpectedly
  tainted, check `machine.nodeTaints` FIRST, not the cluster flag. See TALOS-obvn and the header of
  `configs/nodes/schedulable-controlplane-patch.yaml`.
- **maxPods**: raised from the Talos default 110 to 200 per node (kubelet patch, see
  `scripts/bootstrap-talos-patches.sh`)

### Included Services

- **Talos Dashboard**: Built-in node monitoring
- **Kubernetes Dashboard**: Web UI for cluster management (auto-deployed via extraManifests). Not
  Flux-managed and effectively unmaintained — the maintained cluster UI is Headlamp at
  <https://headlamp.priv.talos00>
- **CoreDNS**: DNS resolution (2 replicas)
- **Cilium**: CNI networking (v1.20.0) — eBPF, `kubeProxyReplacement: true` (no kube-proxy
  DaemonSet), VXLAN tunnel routing, Kubernetes IPAM, plus LB-IPAM + L2 announcements that hand
  Traefik its LAN VIP
- **etcd**: Distributed key-value store for cluster state

### Observability Stack

Everything below lives in the `monitoring` namespace, under `infrastructure/base/monitoring/`.

- **Mimir**: metrics TSDB and long-term store (1-year retention, MinIO S3 backend)
- **Loki**: log storage (30-day retention, MinIO S3 backend)
- **Tempo**: distributed tracing backend
- **Grafana**: visualization, deployed by grafana-operator; dashboards are JSON files plus
  `GrafanaDashboard` CRs
- **Grafana Alloy**: metrics/logs/OTLP collection (`alloy` deployment + `alloy-node` DaemonSet) —
  this replaced Fluent Bit
- **ClickStack / HyperDX**: ClickHouse-backed session/log exploration (http://hyperdx.talos00)
- **Mimir Alertmanager**: alert routing, with a Discord bridge (`alertmanager-discord`)
- **Exporters**: node-exporter, kube-state-metrics, blackbox-exporter, pushgateway, plus
  per-workload exporters (kasa, tdarr, nfs-storage, redis, version-checker)

> Removed: the previous Prometheus / Alertmanager (kube-prometheus-stack) and the
> Graylog + OpenSearch + MongoDB + Fluent Bit logging stack are gone. The `observability`
> namespace still exists but is empty, and `infrastructure/base/observability/` no longer exists.
> Metrics moved to Mimir, logs to Loki/ClickStack. Exportarr is also no longer deployed (its
> manifests remain at `applications/arr-stack/base/exportarr/` but are not in any kustomization).

### Automatic Dashboard Deployment

The Kubernetes Dashboard is automatically deployed during cluster bootstrap via:

- `extraManifests` (configs/nodes/controlplane.yaml:514-515) - Downloads dashboard YAML
- `inlineManifests` (configs/nodes/controlplane.yaml:517-537) - Creates admin-user ServiceAccount

## Deployment

### Complete Stack Deployment

Infrastructure is deployed by **Flux**, not by a script. Commit to `main`, then let Flux reconcile
(or force it):

```bash
# See what Flux is doing
task flux-status

# Force a re-reconcile, fetching the new commit first
flux reconcile source git flux-system
flux reconcile kustomization <name> --with-source
```

> Removed / relocated: `./scripts/deploy-stack.sh` moved to
> `infrastructure/_scripts/deploy-stack.sh` and is legacy — it predates Flux and is not part of the
> normal workflow. `./scripts/deploy-observability.sh` no longer exists anywhere in the repo. The
> `infra:deploy-stack` and `infra:deploy-observability` tasks that pointed at them have been
> removed — Flux is the deployment path.

### Observability Access URLs

- Grafana: http://grafana.talos00 (admin / see `kubectl get secret -n monitoring grafana-admin-credentials -o jsonpath='{.data.GF_SECURITY_ADMIN_PASSWORD}' | base64 -d`)
- Mimir (metrics): http://mimir.talos00
- Loki (logs): http://loki.talos00
- Tempo (traces): http://tempo.talos00
- HyperDX / ClickStack: http://hyperdx.talos00
- OTLP ingest (Alloy): http://otel.talos00

> `prometheus.talos00`, `alertmanager.talos00` and `graylog.talos00` no longer route — those
> components were removed. Alerting is viewed through Grafana; the Alertmanager itself is
> `mimir-alertmanager` and is configured by the `alertmanager-config-pusher` CronJob.

### Deploy Applications (arr stack)

The arr stack is a Flux `Kustomization` (`clusters/catalyst-cluster/arr-stack.yaml`) pointing at
`applications/arr-stack/overlays/themepark`, deployed into the `media` namespace. There is no
`overlays/dev` — the only overlays are `gpu` and `themepark`. Push to `main` and Flux applies it.

Currently included:

- Prowlarr (indexer manager)
- Sonarr (TV shows)
- Radarr (movies)
- Seerr (request management — replaced Overseerr)
- SABnzbd + qBittorrent (downloaders)
- Plex (media server)
- Jellyfin (media server)
- Tautulli, Kometa, Posterr, Posterizarr, Maintainerr, Pulsarr

> Readarr and Exportarr manifests still exist under `applications/arr-stack/base/` but are commented
> out of / absent from the kustomization and are not running. Homepage moved out to
> `applications/homepage/` (namespace `homepage`); Tdarr moved to `applications/tdarr/`.

## Common Tasks

This repository uses a modular Taskfile structure organized by domain. Tasks are grouped into:

- `talos:*` - Talos Linux operations (config, bootstrap, health, services)
- `k8s:*` - Kubernetes operations (kubeconfig, pods, dashboard, audit, flux status)
- `dev:*` - Development tools (linting, formatting, hooks, validation)
- `infra:*` - Infrastructure deployment (legacy pre-Flux scripts; several are broken, see above)
- `security:*` - Security scanning
- `certs:*` - Homelab CA / certificate trust

**Quick reference:**

```bash
task                # Show available domains and commands
task --list         # List all available tasks
task --list-all     # Include tasks that have no description
```

For complete documentation of all available tasks, see [docs/07-reference/taskfile-organization.md](docs/07-reference/taskfile-organization.md).

> Task/script paths were reconciled on 2026-08-22. Tasks whose scripts had simply moved were
> repointed (`k8s:kubeconfig-merge`, `k8s:kubeconfig-unmerge`, `k8s:dashboard-token`,
> `dev:eso-debug`, `infra:dashboard-arr-stack`); tasks whose work is now Flux's, or whose scripts
> and manifests were deleted, were removed (`infra:setup`, `infra:deploy-stack`,
> `infra:deploy-observability`, `infra:deploy-tdarr`, `infra:deploy-arr-stack`,
> `infra:bootstrap-flux`, `infra:deploy-all`, `infra:redeploy`, the `infra:infra-testing-*`
> family, `dev:local-up` / `dev:local-down`, `talos:provision-local` / `talos:destroy-local`).
> See [docs/07-reference/taskfile-organization.md](docs/07-reference/taskfile-organization.md).

### Cluster Management

Only a handful of tasks have unprefixed root shortcuts (`health`, `dashboard`, `kubeconfig`,
`kubeconfig-merge`, `get-nodes`, `get-pods`, `provision`, `audit`, `flux-*`, `clean`, `clean-all`).
Everything else needs its domain prefix.

```bash
# Check cluster health
task health

# View Talos dashboard
task dashboard

# Get cluster version
task talos:version

# List all services
task talos:services

# View service logs (example: kubelet)
task talos:service-logs SERVICE=kubelet
```

### Kubeconfig Management

**Option 1: Merge to ~/.kube/config (Recommended)**

This allows you to use `kubectl`, `kubectx`, and `k9s` without specifying `--kubeconfig` every time:

```bash
# Merge kubeconfig to your default config
task kubeconfig-merge   # ⚠️ BROKEN: calls ./scripts/kubeconfig-merge.sh, which does not exist

# Now use kubectl without flags
kubectl get nodes
kubectl top nodes
kubectl get pods -A

# Switch contexts with kubectx
kubectx                          # List all contexts
kubectx admin@catalyst-cluster   # Switch to this cluster (context name, not cluster name)
kubectx -                        # Switch to previous context

# Switch namespaces with kubens
kubens                     # List namespaces
kubens kube-system         # Switch to kube-system
kubens -                   # Switch to previous namespace

# Launch k9s TUI
k9s
```

> Until `task kubeconfig-merge` is fixed, use Option 2 (or merge by hand with
> `KUBECONFIG=~/.kube/config:./.output/kubeconfig kubectl config view --flatten`).

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
task talos:dmesg

# Follow service logs
task talos:logs-follow SERVICE=kubelet

# List containers
task talos:containers

# Check etcd status
task talos:etcd-status

# View etcd members
task talos:etcd-members
```

### Node Operations

```bash
# Reboot node
task talos:reboot

# Shutdown a single node
task talos:shutdown

# Gracefully shut down the whole cluster (workers in parallel, control plane last)
task talos:shutdown-cluster

# Upgrade one node (go-task variable syntax, not `-- VERSION=`)
task talos:upgrade VERSION=v1.13.2

# Upgrade every node, walking intermediate minors (preferred)
task talos:upgrade-cluster -- v1.13.2

# Upgrade Kubernetes components cluster-wide (no node reboots)
task talos:upgrade-k8s -- 1.34.10
```

## File Structure

```
.
├── configs/                         # Talos configuration files (gitignored - sensitive)
│   ├── nodes/                      # Machine configs actually in use
│   │   ├── controlplane.yaml       # Control plane configuration
│   │   ├── worker-base.yaml        # Worker node configuration template
│   │   └── talos0X/                # Per-node overrides
│   └── talosconfig                 # Talos CLI configuration
├── clusters/catalyst-cluster/       # Flux entrypoint - one Kustomization per stack
├── infrastructure/base/             # Kubernetes infrastructure manifests (~45 components)
│   ├── cilium/                     # CNI (eBPF, kube-proxy replacement, LB-IPAM)
│   ├── argocd/                     # ArgoCD GitOps controller
│   ├── traefik/                    # Traefik ingress controller
│   ├── authentik/                  # SSO / forward-auth
│   ├── crowdsec/                   # IPS + AppSec
│   ├── kyverno/, kyverno-policies/ # Policy engine + derived-config ClusterPolicies
│   ├── monitoring/                 # Mimir, Loki, Tempo, Grafana, Alloy, ClickStack
│   ├── registry/                   # Zot container registry
│   ├── storage/                    # StorageClasses: local-path (default, node NVMe),
│   │                               #   fatboy-nfs-appdata (192.168.1.36:/volume1/appdata),
│   │                               #   synology-nfs. TrueNAS is decommissioned.
│   └── namespaces/                 # Namespace definitions
├── applications/                    # Application workloads (Flux-managed)
│   ├── arr-stack/                  # Media management applications
│   ├── homepage/                   # Homepage dashboards (moved out of arr-stack)
│   └── tdarr/, metube/, gaming/    # ...and others
├── scripts/                         # Automation scripts
│   ├── provision.sh                # Complete cluster provisioning
│   ├── cluster-audit.sh            # Generate Markdown audit report
│   ├── kube-dashboard-token.sh     # Retrieve dashboard/Headlamp/ArgoCD tokens
│   ├── bootstrap-talos-patches.sh  # Apply Talos machine-config patches (maxPods, etc.)
│   └── developer/                  # kubeconfig-merge / unmerge / update-hosts (see caveats above)
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
│   ├── 05-runbooks/                # Runbooks (bootstrap, recovery, Talos patches)
│   ├── 06-project-management/      # Planning and progress tracking
│   ├── 06-troubleshooting/         # Troubleshooting guides
│   ├── 07-reference/               # Reference documentation
│   └── 08-monitoring/              # Monitoring/alerting reference
├── .gitignore                      # Git ignore patterns
├── Taskfile.yaml                   # Root task orchestrator
├── Taskfile.talos.yaml             # Talos-specific tasks
├── Taskfile.k8s.yaml               # Kubernetes-specific tasks
├── Taskfile.dev.yaml               # Development tooling tasks
├── Taskfile.infra.yaml             # Infrastructure deployment tasks
├── Taskfile.security.yaml          # Security scanning tasks
├── Taskfile.certs.yaml             # Homelab CA / certificate tasks
├── README.md                       # This file
├── QUICKSTART.md                   # Quick reference guide
├── TRAEFIK.md                      # Traefik ingress documentation
├── IMPLEMENTATION-TRACKER.md       # Implementation progress tracking
└── CLAUDE.md                       # Claude Code agent guidance
```

## Important Notes

### Multi-Node Considerations

1. **Nodes**: Control plane talos00 @ 192.168.1.54; workers talos01 @ 192.168.1.177,
   talos02-gpu @ 192.168.1.144 (Intel Arc), talos03 @ 192.168.1.30, talos06 @ 192.168.1.19
2. **Control Plane Scheduling**: `allowSchedulingOnControlPlanes: true`, but talos00 carries an
   explicit `node-role.kubernetes.io/control-plane:NoSchedule` taint from the machine config
3. **Workload Distribution**: general workloads run on the four workers; only core infrastructure
   (with a matching toleration) runs on talos00
4. **Backup Important**: Etcd runs on the single control plane - backup regularly

### Security

- Dashboard admin user has cluster-admin role
- Tokens expire after 1 year by default
- Consider using RBAC for production workloads

### Network Configuration

- Node IP: `192.168.1.54` (configurable via `TALOS_NODE`)
- Kubernetes API: `https://192.168.1.54:6443`
- Pod Network: `10.244.0.0/16`
- Service Network: `10.96.0.0/12`
- Ingress VIP: `192.168.1.251` — Traefik `LoadBalancer`, assigned by Cilium LB-IPAM + L2
  announcements. `*.talos00` names resolve to `192.168.1.54` via Pi-hole; both addresses serve
  the same Traefik routes.

## Configuration Reference

### Key Configuration Settings

**configs/nodes/controlplane.yaml:596** - Allow scheduling on control plane:

```yaml
allowSchedulingOnControlPlanes: true
```

**configs/nodes/controlplane.yaml:233-234** - ...but talos00 is still tainted, so only workloads
with a matching toleration land there:

```yaml
nodeTaints:
  node-role.kubernetes.io/control-plane: 'NoSchedule'
```

**configs/nodes/controlplane.yaml:514-537** - Auto-deploy Dashboard:

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

# Remove control-plane taint — single-node bootstrap only. On the current 5-node cluster the taint
# is INTENTIONAL and declared in configs/nodes/controlplane.yaml; removing it here is transient
# (Talos re-applies nodeTaints) and undoes the "core infra only on talos00" split.
kubectl --kubeconfig ./.output/kubeconfig taint nodes <node-name> node-role.kubernetes.io/control-plane:NoSchedule-

# View all resources
kubectl --kubeconfig ./.output/kubeconfig get all -A
```

## Support

For Talos documentation: https://www.talos.dev/
For Kubernetes documentation: https://kubernetes.io/docs/

## Version Info

Verified against the live cluster:

- Talos: v1.13.2
- Kubernetes: v1.34.10 (kubelet + control plane)
- Cilium: v1.20.0
- Kubernetes Dashboard: v2.7.0 (pinned by `extraManifests`)

## Related Issues

This README was restructured as part of the Cilium migration documentation effort:

- **CILIUM-3l7**: Restructure README.md (root) - Updated paths, added TL;DR, removed duplication
