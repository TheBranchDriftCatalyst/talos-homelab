# Cluster Dashboards

This directory contains dynamic dashboard scripts that display real-time cluster status in a user-friendly ASCII format.

## Available Dashboards

### ARR Stack Dashboard

**Script**: `arr-stack.sh`
**Task**: `task dashboard-arr` or `task infra:dashboard-arr-stack`
**Description**: Displays real-time status of all ARR stack services (Sonarr, Radarr, Prowlarr, Plex, Jellyfin, etc.)

#### Features

- **Dynamic Service Discovery**: Automatically detects deployed services in the namespace
- **Real-Time Status**: Shows pod status, readiness, and health indicators
- **Service Information**: Displays ClusterIP, ports, and ingress URLs
- **Storage Overview**: Shows PVC status and storage usage
- **Color-Coded Status**: Green (✓) for healthy, Yellow (⚠) for pending, Red (✗) for failed
- **Quick Commands**: Provides helpful kubectl commands for common operations

#### Usage

```bash
# Run dashboard (default namespace: media-dev)
./scripts/dashboards/arr-stack.sh

# Or via task
task dashboard-arr

# Use different namespace
NAMESPACE=media-fatboy ./scripts/dashboards/arr-stack.sh

# Use different domain
DOMAIN=homelab.local NAMESPACE=media-dev ./scripts/dashboards/arr-stack.sh
```

#### Environment Variables

- `NAMESPACE` - Kubernetes namespace to query (default: `media-dev`)
- `KUBECONFIG` - Path to kubeconfig file (default: `./.output/kubeconfig`)
- `DOMAIN` - Domain suffix for ingress URLs (default: `talos00`)

#### Example Output

```
 █████  ██████  ██████       ███████ ████████  █████   ██████ ██   ██
██   ██ ██   ██ ██   ██      ██         ██    ██   ██ ██      ██  ██
███████ ██████  ██████  █████ ███████    ██    ███████ ██      █████
██   ██ ██   ██ ██   ██           ██    ██    ██   ██ ██      ██  ██
██   ██ ██   ██ ██   ██      ███████    ██    ██   ██  ██████ ██   ██
                      ⚡ Media Automation Stack ⚡


▸ INDEXER & MANAGEMENT
  ┣━ prowlarr → 10.43.123.45:9696 [✓]
  ┃  Web UI:   http://prowlarr.talos00
  ┃  Internal: prowlarr.media-dev.svc:9696

▸ MEDIA AUTOMATION
  ┣━ sonarr → 10.43.123.46:8989 [✓]
  ┃  Web UI:   http://sonarr.talos00
  ┃  Internal: sonarr.media-dev.svc:8989

  ┣━ radarr → 10.43.123.47:7878 [✓]
  ┃  Web UI:   http://radarr.talos00
  ┃  Internal: radarr.media-dev.svc:7878

  ┣━ readarr → 10.43.123.48:8787 [✓]
  ┃  Web UI:   http://readarr.talos00
  ┃  Internal: readarr.media-dev.svc:8787

  ┗━ overseerr → 10.43.123.49:5055 [✓]
     Web UI:   http://overseerr.talos00
     Internal: overseerr.media-dev.svc:5055

▸ MEDIA SERVERS
  ┣━ plex → 10.43.123.50:32400 [✓]
  ┃  Web UI:   http://plex.talos00
  ┃  Internal: plex.media-dev.svc:32400

  ┗━ jellyfin → 10.43.123.51:8096 [✓]
     Web UI:   http://jellyfin.talos00
     Internal: jellyfin.media-dev.svc:8096

▸ INFRASTRUCTURE
  ┣━ postgresql → 10.43.123.52:5432 [✓]
  ┃  Web UI:   http://postgresql.talos00
  ┃  Internal: postgresql.media-dev.svc:5432
  ┃  DB String: postgresql://mediauser:****@postgresql.media-dev.svc:5432/mediadb

  ┗━ homepage → 10.43.123.53:3000 [✓]
     Web UI:   http://homepage.talos00
     Internal: homepage.media-dev.svc:3000

▸ MONITORING
  ┗━ exportarr → 10.43.123.54:9707
     Metrics:  http://exportarr.media-dev.svc:9707/metrics

▸ STORAGE
  Namespace: media-dev
  PVCs:      8/8 Bound
    • prowlarr-config    1Gi      Bound
    • sonarr-config      1Gi      Bound
    • radarr-config      1Gi      Bound
    • shared-downloads   50Gi     Bound

▸ QUICK COMMANDS
  pods    │ kubectl get pods -n media-dev
  logs    │ kubectl logs -n media-dev <pod> -f
  shell   │ kubectl exec -n media-dev -it <pod> -- /bin/bash
  restart │ kubectl rollout restart deploy/<name> -n media-dev
  events  │ kubectl get events -n media-dev --sort-by='.lastTimestamp'

▸ GETTING STARTED
  Deploy stack:     task infra:deploy-arr-stack
  Port forward:     kubectl port-forward -n media-dev svc/<service> <port>:<port>
  Access via web:   Add to /etc/hosts: <node-ip> <service>.talos00

✓ Cluster is running

▸ POD STATUS
NAME                          READY   STATUS    RESTARTS   AGE
prowlarr-7b8f9c4d5-xyz12      1/1     Running   0          2h
sonarr-6c9d8e3f4-abc34        1/1     Running   0          2h
radarr-5b8c7d2e3-def56        1/1     Running   0          2h
readarr-4a7b6c1d2-ghi78       1/1     Running   0          2h
overseerr-3968b5c0d-jkl90     1/1     Running   0          2h
plex-2857a4b9c-mno12          1/1     Running   0          2h
jellyfin-1746938a8-pqr34      1/1     Running   0          2h
postgresql-0                  1/1     Running   0          2h
homepage-9c8d7b6a5-stu56      1/1     Running   0          2h
exportarr-8b7c6a5d4-vwx78     1/1     Running   0          2h
```

#### How It Works

1. **Service Discovery**: Uses `kubectl get svc` to find all services in the namespace
2. **Status Checks**: Queries pod status, readiness, and health from Kubernetes API
3. **Ingress URLs**: Extracts hostnames from IngressRoute resources (Traefik)
4. **Dynamic Data**: All information is fetched in real-time, no hardcoded values
5. **Smart Formatting**: Uses ANSI color codes and box-drawing characters for clean output

#### Troubleshooting

**Error: "kubectl not found"**
```bash
# Install kubectl
brew install kubectl
# or
task dev:install-brew-deps
```

**Error: "Kubeconfig not found"**
```bash
# Download kubeconfig
task kubeconfig
# or merge to ~/.kube/config
task kubeconfig-merge
```

**Error: "Namespace 'media-dev' not found"**
```bash
# Deploy the arr-stack
task infra:deploy-arr-stack
```

**Services show as "not-found"**
- Ensure services are deployed: `kubectl get svc -n media-dev`
- Check namespace is correct: `kubectl get ns`
- Verify kubeconfig context: `kubectl config current-context`

## Creating New Dashboards

To create a new dashboard script:

1. **Create the script**: `scripts/dashboards/my-dashboard.sh`
2. **Make it executable**: `chmod +x scripts/dashboards/my-dashboard.sh`
3. **Add a task**: Update `Taskfile.infra.yaml` with a new task
4. **Document it**: Add section to this README.md

### Dashboard Script Template

```bash
#!/usr/bin/env bash
set -euo pipefail

# Configuration
NAMESPACE="${NAMESPACE:-default}"
KUBECONFIG_PATH="${KUBECONFIG:-./.output/kubeconfig}"

# Use local kubeconfig if KUBECONFIG env var not set
if [[ -z "${KUBECONFIG:-}" ]]; then
  export KUBECONFIG="$KUBECONFIG_PATH"
fi

# Your dashboard logic here
# Use kubectl commands to query cluster state dynamically
# Format output with color codes and box-drawing characters
```

### Color Code Reference

```bash
RESET='\033[0m'
BOLD='\033[1m'
DIM='\033[2m'
CYAN='\033[96m'
GREEN='\033[92m'
YELLOW='\033[93m'
RED='\033[91m'
MAGENTA='\033[95m'
```

### Box-Drawing Characters

```
┣━  # Branch (middle)
┗━  # Branch (last)
┃   # Vertical line
─   # Horizontal line
│   # Vertical separator
```

## Future Dashboards

Ideas for additional dashboards:

- **Monitoring Stack**: Prometheus, Grafana, Alertmanager status
- **Observability Stack**: OpenSearch, Graylog, Fluent Bit status
- **Infrastructure**: ArgoCD, FluxCD, Traefik, Registry status
- **Cluster Overview**: Nodes, resources, storage, namespaces
- **External Secrets**: ESO, 1Password Connect, SecretStores status

Contributions welcome!
