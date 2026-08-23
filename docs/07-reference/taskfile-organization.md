# Taskfile Organization

This repository uses a modular Taskfile structure with domain-specific task files to improve organization and maintainability.

## Structure

```
.
├── Taskfile.yaml          # Root orchestrator with common shortcuts
├── Taskfile.talos.yaml    # Talos Linux operations
├── Taskfile.k8s.yaml      # Kubernetes operations
├── Taskfile.dev.yaml      # Development tools (linting, formatting, hooks, Tilt)
├── Taskfile.infra.yaml    # Infrastructure deployment
├── Taskfile.security.yaml # CrowdSec decisions/bans + honeypot visibility
└── Taskfile.certs.yaml    # cert-manager PKI + local CA trust
```

All six domain files are wired up via `includes:` in the root `Taskfile.yaml`.

## Task Domains

### Root (`task` or `task <command>`)

The root Taskfile provides:

- Default help output showing the task domains (`task` with no arguments)
- Dependency bootstrap (`deps:install`, plus internal `_check-homebrew` / `_install-*` helpers)
- Common shortcuts for frequently used tasks: `health`, `dashboard`, `kubeconfig`,
  `kubeconfig-merge`, `trust-cert`, `trust-ca`, `get-pods`, `get-nodes`, `provision`, `lint`,
  `format`, `validate`, `ci`, `audit`, `dashboard-arr`, `flux-suspend`,
  `flux-resume`, `flux-status`, `setup-1password`
- Script discovery: `scripts` (list) and `scripts:run` (interactive, requires fzf)
- `tdarr` - Tdarr worker cache dashboard
- Cleanup tasks (`clean`, `clean-all`)

**Example commands:**

```bash
task                    # Show help
task health            # Check cluster health
task get-pods          # Get all pods
task deps:install      # Install all dependencies (Homebrew, Yarn, Tilt, git hooks)
task setup             # Alias for deps:install
```

### Talos Domain (`task talos:<command>`)

Talos Linux operations for cluster management.

**Tasks:**

- `gen-config` - Generate fresh Talos configuration files
- `apply-config` - Apply configuration to Talos node
- `bootstrap` - Bootstrap etcd on control plane
- `patches` - Apply required kubelet machine-config patches (iSCSI + local-path) to all nodes
- `patches-check` - Dry-run the kubelet machine-config patch bootstrap
- `provision` - Complete provisioning workflow
- `health` - Check cluster health
- `version` - Get Talos version
- `dashboard` - Open Talos dashboard
- `services` - List all Talos services
- `service-logs` - Get logs for a specific service
- `logs-follow` - Follow logs for a service
- `dmesg` - View kernel logs
- `shell` - Get interactive shell (limited)
- `containers` - List running containers
- `reboot` - Reboot the node
- `shutdown` - Shutdown a single node (defaults to `TALOS_NODE`)
- `shutdown-cluster` - Gracefully shut down the entire cluster (workers first, control plane last)
- `reset` - Reset node (DESTRUCTIVE)
- `upgrade` - Upgrade Talos on a single node
- `upgrade-cluster` - Upgrade all Talos nodes, walking through intermediate minors
- `upgrade-cluster-legacy` - Legacy bash upgrade script (fallback)
- `upgrade-k8s` - Upgrade Kubernetes components cluster-wide (no node reboots)
- `config-merge` - Merge talosconfig to default location
- `config-info` - Show current Talos config info
- `ping` - Ping the node
- `check-api` - Check if Talos API is responding
- `etcd-members` - List etcd members
- `etcd-status` - Get etcd status

**Example commands:**

```bash
task talos:health
task talos:service-logs SERVICE=kubelet
task talos:upgrade VERSION=v1.13.2
task talos:upgrade-cluster -- v1.13.2      # this one reads CLI_ARGS, so it needs --
```

> Note: `talos:upgrade` reads a `VERSION` task variable, so it is passed **without** `--`.
> `talos:upgrade-cluster`, `talos:upgrade-k8s` and `talos:shutdown-cluster` read `CLI_ARGS`
> and therefore **do** need `--`. See [Tips](#tips).

### Kubernetes Domain (`task k8s:<command>`)

Kubernetes cluster operations and troubleshooting.

**Tasks:**

- `kubeconfig` - Download kubeconfig from Talos
- `kubeconfig-merge` - Merge kubeconfig to ~/.kube/config
- `kubeconfig-unmerge` - Remove the `catalyst-cluster` context from ~/.kube/config
- `kubeconfig-export` - Print the `export KUBECONFIG=...` line for the current shell
- `get-nodes` - Get Kubernetes nodes
- `get-pods` - Get all pods in all namespaces
- `get-all` - Get all resources
- `dashboard-token` - Get K8s Dashboard token
- `dashboard-proxy` - Start kubectl proxy for Dashboard
- `audit` - Generate cluster audit report
- `namespaces` - List all namespaces
- `events` - Get events in all namespaces
- `describe-pod` - Describe a specific pod
- `logs` - Get logs from a pod
- `logs-follow` - Follow logs from a pod
- `flux-suspend` - Suspend all Flux reconciliation (enables manual control)
- `flux-resume` - Resume all Flux reconciliation (re-enables GitOps)
- `flux-status` - Show Flux reconciliation status

**Example commands:**

```bash
task k8s:kubeconfig-merge
task k8s:get-pods
task k8s:logs POD=prometheus-0 NAMESPACE=monitoring
```

### Development Domain (`task dev:<command>`)

Development tools for code quality, linting, formatting, validation and local Tilt development.

Note the sub-task names use **colons**, not hyphens (`dev:lint:yaml`, not `dev:lint-yaml`).

**Tasks:**

- `setup` - Install development tools (Homebrew + Yarn)
- `deps:brew` - Install Homebrew dependencies from `Brewfile`
- `deps:yarn` - Install Yarn dependencies (markdownlint, prettier)
- `hooks:install` - Install git hooks with lefthook
- `hooks:uninstall` - Uninstall git hooks
- `hooks:run` - Manually run git hooks
- `lint` - Run all linters (YAML, shell, `yarn lint` for markdown/prettier, secrets)
- `lint:yaml` - Lint YAML files with yamllint
- `lint:shell` - Lint shell scripts with shellcheck
- `lint:secrets` - Scan for secrets with gitleaks
- `lint:secrets:report` - Scan and generate report
- `format` - Format all code (shell via shfmt, then `yarn format` for markdown/prettier)
- `format-shell` - Format shell scripts with shfmt
- `validate` - Validate all infrastructure manifests
- `validate:kustomize` - Validate kustomizations build
- `validate:k8s` - Validate K8s manifests with kubectl dry-run
- `tilt-up` / `tilt-down` / `tilt-ci` / `tilt-logs` - Tilt lifecycle (observe-only dashboard
  against the live cluster; it deploys nothing)
- `install-tilt` - Install Tilt (macOS via Homebrew)
- `eso-debug` - Debug External Secrets Operator and 1Password integration
- `trust-ca` / `trust-ca:check` - Add / check the homelab-ca root cert in the macOS keychain
- `ci` - Run full CI pipeline locally (lint + validate)

**Example commands:**

```bash
task dev:setup
task dev:lint
task dev:format
task dev:ci
```

### Infrastructure Domain (`task infra:<command>`)

Bootstrap, reconciliation control, and read-only infrastructure operations.

Deployment itself does not happen here. Flux reconciles everything under `infrastructure/` and
`applications/` from the Kustomizations in `clusters/catalyst-cluster/`, and ArgoCD reconciles
application repos. To deploy, commit to git and let Flux reconcile; use `flux-reconcile` to force
it. The old `deploy-*` tasks shelled out to scripts that `kubectl apply`-ed over Flux and were
removed along with their deleted scripts and manifests.

**Tasks:**

- `bootstrap-argocd` - Bootstrap ArgoCD
- `argocd-apps` - Apply ArgoCD applications
- `flux-reconcile` - Force Flux reconciliation (`flux reconcile kustomization flux-system --with-source`)
- `flux-status` - Check Flux status
- `deploy-eso` - Deploy External Secrets Operator
- `setup-1password` - Bootstrap 1Password Connect secrets (idempotent)
- `setup-1password-force` - Re-bootstrap 1Password Connect secrets (recreates)
- `deploy-registry` - Deploy the in-cluster registry
- `registry-port-forward` - Port-forward to the registry (localhost:5000)
- `apply-namespaces` - Apply all namespaces
- `apply-storage` - Apply storage classes
- `dashboard-arr-stack` - ARR stack dashboard with real-time status

> Removed: `infra:build-catalyst-ui` no longer exists. catalyst-ui is deployed by ArgoCD from its
> own repo (see the dual-GitOps docs), not by a task in this repo.

**Example commands:**

```bash
task infra:deploy-eso
task infra:apply-namespaces
task infra:flux-status
```

### Security Domain (`task security:<command>`)

CrowdSec decisions/bans and Cowrie honeypot visibility — wraps `cscli` inside the CrowdSec LAPI pod
(`deploy/crowdsec-lapi` in the `crowdsec` namespace) so you never have to `kubectl exec` by hand.
Run `task security:` (or `task --list`) for the current task list.

### Certificates Domain (`task certs:<command>`)

cert-manager PKI operations and local CA trust (`trust-cert`, `untrust-cert`, `export-ca`, `list`,
`check-expiry`, `status`, `renew`, `issuers`). Run `task certs:` (or `task --list`) for details.

## Task/Script Path Reconciliation

Reconciled 2026-08-22. An audit found 12 tasks pointing at scripts that no longer existed at the
referenced path, plus several pointing at deleted manifest directories or a renamed Service. Two
different root causes, so two different fixes.

**Repointed** - the script still exists, the caller drifted when `scripts/` was reorganized into
subdirectories:

| Task | Now runs |
| ---- | -------- |
| `k8s:kubeconfig-merge` | `scripts/developer/kubeconfig-merge.sh` |
| `k8s:kubeconfig-unmerge` | `scripts/developer/kubeconfig-unmerge.sh` |
| `k8s:dashboard-token` | `scripts/kube-dashboard-token.sh` |
| `dev:eso-debug` | `scripts/external-secrets/onepassword-debug.sh` |
| `infra:dashboard-arr-stack` | `applications/arr-stack/dashboard.sh` |
| `infra:registry-port-forward` | `svc/zot` (the registry Service was renamed) |

**Removed** - the work these tasks did is now Flux's, or the workflow was retired and its script
and manifests deleted. Restoring them would have meant `kubectl apply`-ing over Flux, which is the
anti-pattern this repo's `CLAUDE.md` warns about:

| Task | Why removed |
| ---- | ----------- |
| `infra:setup` | `scripts/setup-infrastructure.sh` deleted; Traefik and metrics-server are Flux-managed |
| `infra:deploy-stack`, root `deploy-stack` | script is legacy pre-Flux, parked at `infrastructure/_scripts/deploy-stack.sh` |
| `infra:deploy-observability` | deleted as obsolete in `e5eda33f`; the OpenSearch/Graylog stack is gone |
| `infra:deploy-tdarr` | disabled as `scripts/__deploy-tdarr.sh`; tdarr is Flux-managed via `clusters/catalyst-cluster/tdarr.yaml` |
| `infra:deploy-arr-stack` | arr-stack is Flux-managed; the referenced `overlays/dev/` never existed |
| `infra:bootstrap-flux` | no such script; Flux is bootstrapped with `flux bootstrap github` per `bootstrap/flux/README.md` |
| `infra:deploy-infra-testing`, `infra:infra-testing-*` | `infrastructure/base/infra-testing/` was deleted |
| `infra:deploy-all`, `infra:redeploy` | called the removed tasks and deleted manifest directories |
| `dev:local-up`, `dev:local-down`, `talos:provision-local`, `talos:destroy-local` | the Docker-based local cluster was retired in `b2130815`; `scripts/provision-local.sh` is disabled as `scripts/__provision-local.sh` |

`scripts/deploy-infra-testing.sh` is still on disk but inert - every path it applies was deleted.

## Common Workflows

### Initial Cluster Setup

```bash
task talos:gen-config
task talos:apply-config INSECURE=true
task talos:bootstrap
task k8s:kubeconfig
task k8s:kubeconfig-merge
task talos:health
```

### Deploy Infrastructure

Day-to-day infrastructure is reconciled by Flux, not by these tasks — see
[docs/02-architecture/dual-gitops.md](../02-architecture/dual-gitops.md). The bootstrap-oriented
tasks below are only for a fresh cluster, and several are currently broken (see
[Known-Broken Tasks](#known-broken-tasks)).

```bash
task infra:apply-namespaces
task infra:deploy-eso
task infra:flux-status
```

### Development Setup

```bash
task dev:setup
task dev:hooks:install
task dev:lint
task dev:validate
```

### Daily Operations

```bash
task health                    # Check cluster health
task k8s:get-pods              # View pods
task k8s:events               # Check events
task k8s:audit                # Generate audit report
```

## Tips

1. **List all available tasks:**

   ```bash
   task --list                # Tasks that have a description
   task --list-all            # Every task, including undescribed ones
   ```

2. **Get help for a specific task:**

   ```bash
   task --summary <domain>:<task>
   ```

   (`task <task> --help` prints go-task's global usage, not the task's summary.)

3. **Pass variables to tasks:**

   Task variables are set as bare `KEY=value` arguments — **not** after `--`. Anything after `--`
   becomes `CLI_ARGS`, so `task talos:upgrade -- VERSION=v1.13.2` silently uses the default version.

   ```bash
   task talos:upgrade VERSION=v1.13.2
   task talos:service-logs SERVICE=kubelet
   task k8s:logs POD=name NAMESPACE=default
   ```

   Only tasks that explicitly template `{{.CLI_ARGS}}` take `--`: `talos:upgrade-cluster`,
   `talos:upgrade-cluster-legacy`, `talos:upgrade-k8s`, `talos:shutdown-cluster`, `scripts`,
   and `tdarr`.

   ```bash
   task talos:upgrade-k8s -- 1.34.10
   ```

   Several Taskfile `desc:` strings still say "use -- VAR=value"; those descriptions are wrong for
   variable-style tasks.

4. **Use shortcuts for common tasks:**
   Root Taskfile provides shortcuts like `task health`, `task get-pods`, etc.

5. **Chain multiple tasks:**

   ```bash
   task dev:lint && task dev:validate && task dev:format
   ```

## Variables

Variables are declared per Taskfile, not globally:

| Taskfile                 | Variables                                                                                                                                                                                                                  |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Taskfile.yaml` (root)   | `TALOS_NODE` (default `192.168.1.54`), `TALOSCONFIG` (`./configs/talosconfig`), `KUBECONFIG` (`./.output/kubeconfig`)                                                                                                       |
| `Taskfile.talos.yaml`    | the above, plus `CLUSTER_NAME` (`catalyst-cluster`), `CLUSTER_ENDPOINT` (`https://{{.TALOS_NODE}}:6443`), `CONTROLPLANE_CONFIG` (`./configs/nodes/controlplane.yaml`), `WORKER_CONFIG` (`./configs/nodes/worker-base.yaml`) |
| `Taskfile.k8s.yaml`      | `TALOS_NODE`, `TALOSCONFIG`, `KUBECONFIG`                                                                                                                                                                                  |
| `Taskfile.infra.yaml`    | `KUBECONFIG`                                                                                                                                                                                                               |
| `Taskfile.security.yaml` | `KUBECONFIG`, `NS` (`crowdsec`), `LAPI` (`deploy/crowdsec-lapi`)                                                                                                                                                           |
| `Taskfile.certs.yaml`    | `CA_SECRET` (`homelab-ca-secret`), `CA_NS` (`cert-manager`), `CA_FILE` (`$HOME/homelab-ca.crt`)                                                                                                                             |
| `Taskfile.dev.yaml`      | none                                                                                                                                                                                                                       |

`TALOS_NODE` is the control-plane node (`talos00`). Tasks that target it explicitly hit only that
node; the cluster also runs `talos01`, `talos02-gpu`, `talos03` and `talos06`.

Note that tasks using `--kubeconfig {{.KUBECONFIG}}` read `./.output/kubeconfig`, which only exists
after `task k8s:kubeconfig`. A merged `~/.kube/config` (via `task kubeconfig-merge`) is not used by
those tasks.

Override variables with environment variables — the `{{.VAR | default ... }}` pattern picks up the
process environment:

```bash
export TALOS_NODE=192.168.1.177
task talos:health
```

---

## Related Issues

<!-- Beads tracking for this doc -->
