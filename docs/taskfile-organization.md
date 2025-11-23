# Taskfile Organization

This repository uses a modular Taskfile structure with domain-specific task files to improve organization and maintainability.

## Structure

```
.
├── Taskfile.yaml          # Root orchestrator with common shortcuts
├── Taskfile.talos.yaml    # Talos Linux operations
├── Taskfile.k8s.yaml      # Kubernetes operations
├── Taskfile.dev.yaml      # Development tools (linting, formatting, hooks)
└── Taskfile.infra.yaml    # Infrastructure deployment
```

## Task Domains

### Root (`task` or `task <command>`)

The root Taskfile provides:
- Default help output showing all available domains
- Common shortcuts for frequently used tasks
- Cleanup tasks (`clean`, `clean-all`)

**Example commands:**
```bash
task                    # Show help
task health            # Check cluster health
task get-pods          # Get all pods
task setup             # Install development tools
```

### Talos Domain (`task talos:<command>`)

Talos Linux operations for cluster management.

**Tasks:**
- `gen-config` - Generate fresh Talos configuration files
- `apply-config` - Apply configuration to Talos node
- `bootstrap` - Bootstrap etcd on control plane
- `provision` - Complete provisioning workflow
- `health` - Check cluster health
- `version` - Get Talos version
- `dashboard` - Open Talos dashboard
- `services` - List all Talos services
- `service-logs` - Get logs for a specific service
- `dmesg` - View kernel logs
- `shell` - Get interactive shell (limited)
- `containers` - List running containers
- `reboot` - Reboot the node
- `shutdown` - Shutdown the node
- `reset` - Reset node (DESTRUCTIVE)
- `upgrade` - Upgrade Talos version
- `config-merge` - Merge talosconfig to default location
- `ping` - Ping the node
- `check-api` - Check if Talos API is responding
- `etcd-members` - List etcd members
- `etcd-status` - Get etcd status

**Example commands:**
```bash
task talos:health
task talos:service-logs -- SERVICE=kubelet
task talos:upgrade -- VERSION=v1.11.2
```

### Kubernetes Domain (`task k8s:<command>`)

Kubernetes cluster operations and troubleshooting.

**Tasks:**
- `kubeconfig` - Download kubeconfig from Talos
- `kubeconfig-merge` - Merge kubeconfig to ~/.kube/config
- `kubeconfig-unmerge` - Remove homelab context
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

**Example commands:**
```bash
task k8s:kubeconfig-merge
task k8s:get-pods
task k8s:logs -- POD=prometheus-0 NAMESPACE=monitoring
```

### Development Domain (`task dev:<command>`)

Development tools for code quality, linting, formatting, and validation.

**Tasks:**
- `setup` - Install all development tools (Homebrew + Yarn + hooks)
- `install-brew-deps` - Install Homebrew dependencies
- `install-yarn-deps` - Install Yarn dependencies
- `hooks-install` - Install git hooks with lefthook
- `hooks-uninstall` - Uninstall git hooks
- `hooks-run` - Manually run git hooks
- `lint` - Run all linters (yaml, shell, markdown, secrets)
- `lint-yaml` - Lint YAML files with yamllint
- `lint-shell` - Lint shell scripts with shellcheck
- `lint-secrets` - Scan for secrets with gitleaks
- `lint-secrets-report` - Scan and generate report
- `format` - Format all code (shell, markdown, prettier)
- `format-shell` - Format shell scripts with shfmt
- `validate` - Validate all infrastructure manifests
- `validate-kustomize` - Validate kustomizations
- `validate-k8s` - Validate K8s manifests with dry-run
- `ci` - Run full CI pipeline locally

**Example commands:**
```bash
task dev:setup
task dev:lint
task dev:format
task dev:ci
```

### Infrastructure Domain (`task infra:<command>`)

Infrastructure deployment and application management.

**Tasks:**
- `setup` - Install core infrastructure
- `deploy-stack` - Deploy complete stack (monitoring + observability)
- `deploy-observability` - Deploy observability stack
- `deploy-arr-stack` - Deploy ARR media stack
- `deploy-tdarr` - Deploy Tdarr transcoding
- `bootstrap-argocd` - Bootstrap ArgoCD
- `argocd-apps` - Apply ArgoCD applications
- `bootstrap-flux` - Bootstrap FluxCD
- `flux-reconcile` - Force Flux reconciliation
- `flux-status` - Check Flux status
- `deploy-eso` - Deploy External Secrets Operator
- `setup-1password` - Setup 1Password Connect secrets
- `deploy-registry` - Deploy Docker registry
- `registry-port-forward` - Port-forward to registry
- `build-catalyst-ui` - Build and deploy catalyst-ui
- `apply-namespaces` - Apply all namespaces
- `apply-storage` - Apply storage classes
- `deploy-all` - Deploy complete infrastructure
- `redeploy` - Force redeployment (DESTRUCTIVE)

**Example commands:**
```bash
task infra:deploy-stack
task infra:bootstrap-flux
task infra:deploy-eso
task infra:registry-port-forward
```

## Common Workflows

### Initial Cluster Setup
```bash
task talos:gen-config
task talos:apply-config -- INSECURE=true
task talos:bootstrap
task k8s:kubeconfig
task k8s:kubeconfig-merge
task talos:health
```

### Deploy Infrastructure
```bash
task infra:apply-namespaces
task infra:deploy-stack
task infra:bootstrap-flux
task infra:deploy-eso
```

### Development Setup
```bash
task dev:setup
task dev:hooks-install
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
   task --list                # Short list
   task --list-all            # With descriptions
   ```

2. **Get help for a specific task:**
   ```bash
   task <domain>:<task> --help
   ```

3. **Pass variables to tasks:**
   ```bash
   task talos:upgrade -- VERSION=v1.11.2
   task k8s:logs -- POD=name NAMESPACE=default
   ```

4. **Use shortcuts for common tasks:**
   Root Taskfile provides shortcuts like `task health`, `task get-pods`, etc.

5. **Chain multiple tasks:**
   ```bash
   task dev:lint && task dev:validate && task dev:format
   ```

## Variables

Common variables available across all Taskfiles:

- `TALOS_NODE` - Node IP address (default: `192.168.1.54`)
- `TALOSCONFIG` - Talos config path (default: `./configs/talosconfig`)
- `KUBECONFIG` - Kubernetes config path (default: `./.output/kubeconfig`)

Override variables with environment variables:
```bash
export TALOS_NODE=192.168.1.55
task talos:health
```
