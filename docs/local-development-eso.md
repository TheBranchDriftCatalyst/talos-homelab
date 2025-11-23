# Local Development Guide - External Secrets Operator

This guide shows how to develop and test External Secrets Operator (ESO) with 1Password Connect using a local Talos cluster and Tilt.

## Overview

**Local Stack:**
- **Talos Local Cluster** - Docker-based single-node Talos cluster
- **Tilt** - Local development tool with live reload
- **External Secrets Operator** - Deployed via Helm in Tilt
- **1Password Connect** - Optional, for testing secret sync

## Prerequisites

```bash
# Install all dev tools
task dev:setup

# Or manually install Tilt
brew install tilt
```

**Required:**
- Docker Desktop (running)
- talosctl (already installed)
- kubectl (already installed)
- helm (already installed)
- tilt (install via task or brew)

## Quick Start

### Option 1: All-in-One (Recommended)

```bash
# Start local cluster + Tilt in one command
task dev:local-up
```

This will:
1. Provision local Talos cluster (`talos-local`)
2. Install core components (Traefik, metrics-server)
3. Launch Tilt with ESO deployment
4. Open Tilt UI in browser (http://localhost:10350)

### Option 2: Step-by-Step

```bash
# 1. Provision local Talos cluster
task talos:provision-local

# 2. Switch to local context
kubectl config use-context talos-local

# 3. Start Tilt
task dev:tilt-up
```

## Tilt UI

Once Tilt is running, open http://localhost:10350

**Resources shown:**
- `external-secrets-operator` - Main ESO deployment
- `onepassword-secretstore` - SecretStore CRD
- `onepassword-cluster-secretstore` - ClusterSecretStore CRD

**Manual Actions (buttons in Tilt UI):**
- `setup-1password` - Run 1Password Connect setup script
- `debug-secretstore` - Run diagnostic script
- `view-eso-logs` - View ESO logs

## Testing External Secrets Operator

### 1. Verify ESO Deployment

```bash
# Check ESO is running
kubectl get pods -n external-secrets

# Check CRDs are installed
kubectl get crds | grep external-secrets

# Expected CRDs:
# - secretstores.external-secrets.io
# - clustersecretstores.external-secrets.io
# - externalsecrets.external-secrets.io
```

### 2. Setup 1Password Connect (Optional)

```bash
# Interactive setup script
./scripts/setup-1password-connect.sh

# Or via Tilt UI: Click "setup-1password" button
```

This script will prompt you for:
- 1Password Connect credentials file (JSON)
- 1Password Connect token
- Vault ID

### 3. Deploy SecretStores

```bash
# Deploy SecretStore and ClusterSecretStore
kubectl apply -k infrastructure/base/external-secrets/secretstores

# Verify
kubectl get secretstores -n external-secrets
kubectl get clustersecretstores
```

### 4. Test Secret Sync

```bash
# Create a test ExternalSecret
kubectl apply -f infrastructure/base/external-secrets/secretstores/example-externalsecret.yaml

# Check if secret was created
kubectl get externalsecret -n external-secrets example-secret
kubectl get secret -n external-secrets example-secret

# View status
kubectl describe externalsecret -n external-secrets example-secret
```

## Debugging

### Run Diagnostic Script

```bash
# Comprehensive diagnostic
./scripts/onepassword-debug.sh

# Or via task
task dev:eso-debug
```

**What it checks:**
- ✓ kubectl connectivity
- ✓ Namespace exists
- ✓ ESO deployment status
- ✓ ESO CRDs installed
- ✓ 1Password Connect status
- ✓ Required secrets exist
- ✓ SecretStore status
- ✓ ClusterSecretStore status
- ✓ ExternalSecrets status
- ✓ 1Password Connect API reachability
- Recent ESO logs

### View ESO Logs

```bash
# Tail logs
kubectl logs -n external-secrets -l app.kubernetes.io/name=external-secrets -f

# Last 50 lines
kubectl logs -n external-secrets -l app.kubernetes.io/name=external-secrets --tail=50

# Via Tilt UI: Click "view-eso-logs" button
```

### Common Issues

#### Issue: "Context 'talos-local' not found"

```bash
# Provision local cluster first
task talos:provision-local

# Or check current context
kubectl config current-context
```

#### Issue: "1Password Connect not responding"

```bash
# Check if deployed
kubectl get pods -n external-secrets | grep onepassword

# Check logs
kubectl logs -n external-secrets -l app=onepassword-connect

# Re-run setup
./scripts/setup-1password-connect.sh
```

#### Issue: "SecretStore not ready"

```bash
# Check SecretStore status
kubectl describe secretstore -n external-secrets onepassword-secretstore

# Common reasons:
# 1. 1Password Connect not running
# 2. Invalid credentials/token
# 3. Wrong vault ID
```

#### Issue: "ExternalSecret sync failed"

```bash
# Check ExternalSecret status
kubectl describe externalsecret -n external-secrets <name>

# Check ESO logs for errors
kubectl logs -n external-secrets -l app.kubernetes.io/name=external-secrets --tail=100

# Common reasons:
# 1. Secret doesn't exist in 1Password vault
# 2. Wrong secret path/key
# 3. SecretStore not ready
```

## Development Workflow

### Making Changes to ESO Configuration

1. **Edit Helm values** in `Tiltfile`:
   ```python
   helm_resource(
       'external-secrets-operator',
       flags=[
           '--set=<your-setting>=<value>',
       ],
   )
   ```

2. **Tilt auto-reloads** - Changes are applied automatically

3. **View in Tilt UI** - Check status and logs

### Testing SecretStore Changes

1. **Edit SecretStore** in `infrastructure/base/external-secrets/secretstores/onepassword-secretstore.yaml`

2. **Tilt watches for changes** - Auto-applies via kustomize

3. **Verify status**:
   ```bash
   kubectl get secretstore -n external-secrets
   kubectl describe secretstore -n external-secrets onepassword-secretstore
   ```

### Testing 1Password Connect

1. **Deploy 1Password Connect**:
   ```bash
   # Uncomment in Tiltfile:
   k8s_yaml(kustomize('infrastructure/base/external-secrets/onepassword-connect'))
   ```

2. **Tilt reloads** - 1Password Connect deployed

3. **Test connectivity**:
   ```bash
   ./scripts/onepassword-debug.sh
   ```

## Cleanup

### Stop Tilt Only

```bash
# Stop Tilt, keep cluster running
task dev:tilt-down
```

### Stop Everything

```bash
# Stop Tilt + destroy cluster
task dev:local-down
```

### Manual Cleanup

```bash
# Stop Tilt
tilt down

# Destroy cluster
task talos:destroy-local

# Or directly with talosctl
talosctl cluster destroy --name talos-local
```

## Local Cluster Details

**Cluster Name:** `talos-local`
**Context:** `talos-local`
**Control Plane:** `https://127.0.0.1:6443`
**Kubeconfig:** `./.output/local/kubeconfig`
**Talosconfig:** `./.output/local/talosconfig`

**Pre-installed:**
- Traefik (Ingress controller)
- metrics-server
- Test whoami service

**Access:**
- Traefik Dashboard: http://traefik.localhost
- Whoami Test: http://whoami.localhost

## Task Reference

```bash
# Complete workflow
task dev:local-up              # Start cluster + Tilt
task dev:local-down            # Stop Tilt + destroy cluster

# Individual steps
task talos:provision-local     # Create local cluster
task talos:destroy-local       # Destroy local cluster
task dev:tilt-up               # Start Tilt only
task dev:tilt-down             # Stop Tilt only

# Debugging
task dev:eso-debug             # Run diagnostic script
./scripts/onepassword-debug.sh # Direct script execution
```

## Next Steps

Once ESO is working locally:

1. **Test with real 1Password vault** - Add actual secrets
2. **Deploy to production cluster** - Use FluxCD (see `infrastructure/base/external-secrets/`)
3. **Create ExternalSecrets** - Define secrets to sync
4. **Monitor in production** - Check Grafana dashboards

## Additional Resources

- [External Secrets Operator Docs](https://external-secrets.io/)
- [1Password Connect Docs](https://developer.1password.com/docs/connect/)
- [Tilt Documentation](https://docs.tilt.dev/)
- [Talos Local Clusters](https://www.talos.dev/latest/talos-guides/install/local-platforms/docker/)
