# Tilt Development Workflow

This document describes how to use [Tilt](https://tilt.dev) for rapid iteration on infrastructure manifests in your Talos Kubernetes cluster.

## Overview

Tilt provides a powerful development environment that watches your Kubernetes manifests and automatically applies changes as you edit them. This creates a tight feedback loop for infrastructure development, similar to hot-reload in application development.

**Key Features:**

- **Hot Reload**: Changes to manifests automatically applied to cluster
- **Port Forwarding**: Automatic port forwards for easy local access
- **Resource Organization**: Resources grouped by labels (ui-tools, monitoring, etc.)
- **Manual Triggers**: Quick actions for deployments and cluster operations
- **Flux Integration**: Control Flux reconciliation from Tilt UI

## Prerequisites

### 1. Install Tilt

```bash
# Using Taskfile
task dev:install-tilt

# Or manually via Homebrew
brew install tilt-dev/tap/tilt

# Verify installation
tilt version
```

### 2. Cluster Access

Ensure your kubeconfig is configured:

```bash
# Merge Talos cluster kubeconfig
task kubeconfig-merge

# Verify cluster access
kubectl cluster-info

# Check current context
kubectl config current-context
# Should show: homelab-single (or your cluster context)
```

### 3. Update /etc/hosts

For Traefik IngressRoutes to work:

```bash
# Using script (recommended)
sudo ./scripts/update-hosts.sh

# Or manually add to /etc/hosts:
192.168.1.54  headlamp.talos00 kubeview.talos00 kube-ops-view.talos00 \
              goldilocks.talos00 grafana.talos00 prometheus.talos00 \
              alertmanager.talos00 argocd.talos00 graylog.talos00 registry.talos00
```

## Starting Tilt

### Quick Start

```bash
# Start Tilt
tilt up

# Tilt will:
# 1. Open web UI in your browser (http://localhost:10350)
# 2. Deploy infra-testing stack
# 3. Set up port forwards for all services
# 4. Watch for manifest changes
```

### Alternative Start Methods

```bash
# Start with specific Kubernetes context
tilt up --context homelab-single

# Start with custom namespace
tilt up --set namespace=my-namespace

# Start in headless mode (no browser)
tilt up --hud=false

# Start with streaming logs
tilt up --stream
```

### Using Taskfile

```bash
# Start Tilt
task dev:tilt-up

# Stop Tilt
task dev:tilt-down

# Run CI validation (no UI)
task dev:tilt-ci
```

## Tilt UI Overview

Once Tilt is running, the web UI (http://localhost:10350) provides:

### Resource Groups

Resources are organized by labels:

- **ui-tools**: Headlamp, Kubeview, Kube-ops-view, Goldilocks
- **monitoring**: Prometheus, Grafana, Alertmanager
- **observability**: Graylog, OpenSearch, Fluent Bit
- **gitops**: ArgoCD
- **networking**: Traefik
- **infrastructure**: Docker Registry
- **flux-control**: Flux reconciliation commands
- **cluster-info**: Health checks and resource monitoring
- **setup**: Configuration helpers
- **quick-actions**: Deployment scripts
- **validation**: Manifest validation and linting

### Resource Status

Each resource shows:

- **Green**: Healthy and running
- **Yellow**: Building/updating
- **Red**: Failed or error
- **Gray**: Not started or disabled

### Resource Details

Click any resource to see:

- **Pod logs**: Real-time streaming logs
- **K8s YAML**: Current manifest
- **Events**: Kubernetes events
- **Endpoints**: Links to service UIs

## Development Workflow

### 1. Hot Reload Workflow

Tilt watches these directories for changes:

```
infrastructure/base/
infrastructure/overlays/
applications/
```

**Example: Update Headlamp resource limits**

1. Edit `infrastructure/base/infra-testing/headlamp/helmrelease.yaml`
2. Change memory limit from 512Mi to 1Gi
3. Save the file
4. Tilt automatically detects the change
5. Applies updated manifest to cluster
6. Resource restarts with new settings

**Watch it happen:**

- Tilt UI shows "Updating" status
- Logs stream in real-time
- Status changes to green when complete

### 2. Manual Triggers

Tilt provides manual actions for common tasks:

#### Flux Control

- **flux-reconcile**: Force Flux reconciliation
- **flux-status**: Check Flux resource status
- **flux-suspend-all**: Pause Flux during development
- **flux-resume-all**: Resume Flux after development

#### Cluster Information

- **cluster-health**: Check node and pod status
- **cluster-resources**: View resource usage (CPU/memory)
- **cluster-events**: Recent Kubernetes events

#### Quick Actions

- **deploy-infra-testing**: Deploy UI tools stack
- **deploy-stack**: Deploy monitoring + observability
- **deploy-observability**: Deploy observability stack only

#### Setup & Configuration

- **update-hosts**: Update /etc/hosts entries
- **kubeconfig-merge**: Merge cluster kubeconfig

#### Validation

- **validate-manifests**: Dry-run kubectl apply
- **lint-YAML**: Run YAML linting

### 3. Port Forwards

Tilt automatically sets up port forwards for all services:

| Service       | Traefik URL                  | Port Forward           | Port |
| ------------- | ---------------------------- | ---------------------- | ---- |
| Headlamp      | http://headlamp.talos00      | http://localhost:8080  | 8080 |
| Kubeview      | http://kubeview.talos00      | http://localhost:8081  | 8081 |
| Kube-ops-view | http://kube-ops-view.talos00 | http://localhost:8082  | 8082 |
| Goldilocks    | http://goldilocks.talos00    | http://localhost:8083  | 8083 |
| Prometheus    | http://prometheus.talos00    | http://localhost:9090  | 9090 |
| Grafana       | http://grafana.talos00       | http://localhost:3000  | 3000 |
| Alertmanager  | http://alertmanager.talos00  | http://localhost:9093  | 9093 |
| Graylog       | http://graylog.talos00       | http://localhost:9000  | 9000 |
| ArgoCD        | http://argocd.talos00        | http://localhost:8443  | 8443 |
| Registry      | http://registry.talos00      | http://localhost:5000  | 5000 |
| Traefik HTTP  | -                            | http://localhost:8000  | 8000 |
| Traefik HTTPS | -                            | https://localhost:8888 | 8888 |

**Accessing Services:**

- **Via Traefik**: Use `*.talos00` URLs (requires /etc/hosts)
- **Via Port Forward**: Use `localhost:<port>` URLs (always works)

### 4. Viewing Logs

**From Tilt UI:**

1. Click on any resource
2. Logs tab shows real-time streaming
3. Use search/filter to find specific messages

**From Terminal:**

```bash
# View logs for specific resource
task dev:tilt-logs RESOURCE=infra-testing:headlamp

# Or using kubectl directly
kubectl logs -n infra-testing -l app=headlamp --tail=50 -f
```

### 5. Force Rebuild

Sometimes you need to force a resource rebuild:

1. Click resource in Tilt UI
2. Press 'r' key (or click refresh button)
3. Tilt reapplies the manifest
4. Pod restarts with latest configuration

## Working with Flux

Tilt and Flux can work together, but be careful not to create conflicts.

### Development Pattern

**Option 1: Tilt in Control (Recommended for dev)**

1. Suspend Flux reconciliation:

   ```bash
   # In Tilt UI, trigger: flux-suspend-all
   # Or manually:
   flux suspend kustomization --all
   ```

2. Make changes to manifests
3. Tilt applies changes immediately
4. Test your changes
5. Resume Flux when done:

   ```bash
   # In Tilt UI, trigger: flux-resume-all
   # Or manually:
   flux resume kustomization --all
   ```

**Option 2: Flux in Control (Test Flux workflow)**

1. Keep Flux running
2. Make changes to manifests
3. Commit and push to Git
4. Flux reconciles from Git (may take 1-10 minutes)
5. Use Tilt UI to view the reconciliation

### Best Practices

- **Use Tilt for**: Rapid iteration, testing manifest changes
- **Use Flux for**: Production deployments, GitOps workflow
- **Suspend Flux when**: You want immediate feedback from Tilt
- **Keep Flux running when**: Testing the full GitOps workflow

## Keyboard Shortcuts

In the Tilt UI:

- **SPACE**: Open/close web UI
- **r**: Trigger rebuild for selected resource
- **k**: Show Kubernetes events
- **ctrl-c**: Stop Tilt (in terminal)
- **/** : Search/filter resources
- **↑/↓**: Navigate resources
- **ENTER**: Open resource details

## Advanced Usage

### Custom Tiltfile Configuration

You can pass configuration to the Tiltfile:

```bash
# Use different Kubernetes context
tilt up --set k8s_context=my-cluster

# Use different default namespace
tilt up --set namespace=development

# Enable Flux auto-suspend
tilt up --set flux-suspend=true
```

### Adding New Resources

To add a new resource to Tilt:

1. Edit `Tiltfile`
2. Add new `k8s_resource()` block:

```python
k8s_resource(
    workload='my-service',
    new_name='my-namespace:my-service',
    port_forwards=['8084:8080'],
    labels=['my-category'],
    links=[
        link('http://my-service.talos00', 'My Service (via Traefik)'),
        link('http://localhost:8084', 'My Service (port-forward)')
    ]
)
```

1. Save Tiltfile
2. Tilt automatically reloads configuration

### CI Mode

Run Tilt in CI mode for validation without UI:

```bash
# Validate manifests
task dev:tilt-ci

# Or manually
tilt ci

# Exits with:
# - 0 if all resources healthy
# - 1 if any resource fails
```

## Troubleshooting

### Tilt not connecting to cluster

**Symptom**: "Unable to connect to cluster"

**Solution**:

```bash
# Check kubeconfig
kubectl cluster-info

# Verify context
kubectl config current-context

# Update kubeconfig if needed
task kubeconfig-merge

# Restart Tilt
tilt down && tilt up
```

### Resources stuck in error state

**Symptom**: Red status, pod crashlooping

**Solution**:

1. Click resource in Tilt UI
2. View logs for error messages
3. Fix manifest issue
4. Press 'r' to force rebuild
5. Or manually restart:

   ```bash
   kubectl delete pod -n <namespace> -l app=<label>
   ```

### Port forward conflicts

**Symptom**: "Port already in use"

**Solution**:

```bash
# Find what's using the port
lsof -i :8080

# Kill the process or change port in Tiltfile
# Edit port_forwards=['8085:4466']  # Changed from 8080
```

### Changes not being detected

**Symptom**: Tilt not applying manifest changes

**Solution**:

1. Verify file is in watched directory:
   - infrastructure/base/
   - infrastructure/overlays/
   - applications/
2. Check Tilt logs for errors
3. Force rebuild with 'r' key
4. Restart Tilt if needed

### Flux conflicts with Tilt

**Symptom**: Flux keeps reverting Tilt changes

**Solution**:

```bash
# Suspend Flux during development
flux suspend kustomization --all

# Make changes with Tilt

# Resume Flux when done
flux resume kustomization --all
```

## Best Practices

1. **Suspend Flux during active development**
   - Prevents reconciliation conflicts
   - Gives you full control

2. **Use port forwards for local testing**
   - Faster than setting up Traefik
   - No /etc/hosts configuration needed

3. **Organize resources with labels**
   - Makes it easy to find related services
   - Filter by category in UI

4. **Commit changes when stable**
   - Tilt is for rapid iteration
   - Git is your source of truth

5. **Use manual triggers for one-off tasks**
   - Deployment scripts
   - Validation commands
   - Cluster health checks

6. **Monitor resource usage**
   - Use cluster-resources trigger
   - Single-node cluster has limits
   - Watch for memory/CPU saturation

## Quick Reference

```bash
# Start development
task dev:tilt-up

# Stop development
task dev:tilt-down

# View logs
task dev:tilt-logs RESOURCE=<name>

# Validate only (CI mode)
task dev:tilt-ci

# Install Tilt
task dev:install-tilt

# Cluster health check
# (From Tilt UI, trigger: cluster-health)

# Update /etc/hosts
# (From Tilt UI, trigger: update-hosts)

# Deploy infrastructure
# (From Tilt UI, trigger: deploy-infra-testing)
```

## Additional Resources

- [Tilt Documentation](https://docs.tilt.dev/)
- [Tilt Best Practices](https://docs.tilt.dev/tutorial/3-tiltfile-concepts.html)
- [Flux Documentation](https://fluxcd.io/flux/)
- [Tiltfile API Reference](https://docs.tilt.dev/api.html)

## Sources

- [Local Kubernetes development with Tilt.dev | Codefresh](https://codefresh.io/blog/local-kubernetes-development-tilt-dev/)
- [Tilt: Kubernetes for Prod, Tilt for Dev](https://tilt.dev/)
- [GitHub - tilt-dev/tilt](https://github.com/tilt-dev/tilt)
- [Flux - the GitOps family of projects](https://fluxcd.io/)
- [Maximise Your Productivity: Harness Hot Reloading in Kubernetes](https://cloudnativeengineer.substack.com/p/hot-reloading-in-kubernetes-with-tilt)
