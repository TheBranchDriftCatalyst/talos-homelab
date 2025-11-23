# External Secrets Operator with 1Password

This directory contains the configuration for External Secrets Operator (ESO) integrated with 1Password Connect for secrets management in the Kubernetes cluster.

## Architecture

The setup consists of three main components:

1. **External Secrets Operator** - Kubernetes operator that syncs secrets from external secret stores
2. **1Password Connect Server** - Secure bridge between Kubernetes and 1Password
3. **SecretStores** - Configuration that defines how to access 1Password vaults

```
┌─────────────────────────────────────────────────────────┐
│  Kubernetes Cluster                                      │
│                                                          │
│  ┌──────────────────┐      ┌────────────────────────┐  │
│  │ ExternalSecret   │─────▶│ External Secrets       │  │
│  │ Resources        │      │ Operator               │  │
│  └──────────────────┘      └────────────┬───────────┘  │
│                                          │              │
│                             ┌────────────▼───────────┐  │
│                             │ 1Password Connect      │  │
│                             │ Server                 │  │
│                             └────────────┬───────────┘  │
│                                          │              │
└──────────────────────────────────────────┼──────────────┘
                                           │
                                           │ HTTPS
                                           ▼
                                  ┌────────────────┐
                                  │  1Password     │
                                  │  Cloud/Team    │
                                  └────────────────┘
```

## Directory Structure

```
external-secrets/
├── namespace.yaml                    # Namespace definition
├── operator/                         # ESO Helm deployment
│   ├── helmrepository.yaml          # External Secrets Helm repo
│   ├── helmrelease.yaml             # ESO deployment via Flux
│   └── kustomization.yaml
├── onepassword-connect/             # 1Password Connect Server
│   ├── deployment.yaml              # Connect API + Sync containers
│   ├── service.yaml                 # ClusterIP service
│   └── kustomization.yaml
├── secretstores/                    # SecretStore configs
│   ├── onepassword-secretstore.yaml # ClusterSecretStore + SecretStore
│   ├── example-externalsecret.yaml  # Usage example (not deployed)
│   └── kustomization.yaml
└── kustomization.yaml               # Root kustomization
```

## Prerequisites

### 1. 1Password Account Setup

You need a 1Password account with access to create Connect Servers:

1. Go to https://my.1password.com/developer-tools/infrastructure-secrets/connect
2. Create a new Connect Server
3. Download the `1password-credentials.json` file (contains vault tokens)
4. Generate a Connect API token

### 2. Install Flux

This setup is managed by FluxCD. Ensure Flux is installed and bootstrapped:

```bash
# Check Flux installation
flux check

# If not installed, bootstrap Flux
./bootstrap/flux/bootstrap.sh
```

## Installation

### Step 1: Deploy External Secrets Operator

The ESO operator is deployed automatically by Flux from the HelmRelease manifest.

```bash
# ESO will be installed when you apply the kustomization
kubectl apply -k infrastructure/base/external-secrets/operator/

# Or let Flux handle it
flux reconcile kustomization external-secrets
```

Verify installation:

```bash
kubectl get pods -n external-secrets
# Should show: external-secrets-*, external-secrets-cert-controller-*, external-secrets-webhook-*
```

### Step 2: Configure 1Password Credentials

Use the setup script to create the required secrets:

```bash
./scripts/setup-1password-connect.sh
```

This script will prompt you for:
- Path to `1password-credentials.json`
- 1Password Connect API token

It creates two secrets:
- `onepassword-connect-secret` - Contains the credentials file
- `onepassword-connect-token` - Contains the API token

### Step 3: Update Vault Configuration

Edit `infrastructure/base/external-secrets/secretstores/onepassword-secretstore.yaml`:

```yaml
vaults:
  homelab: 1  # Replace '1' with your actual vault ID or name
```

To find your vault ID:
1. Go to https://my.1password.com
2. Navigate to your vault
3. The vault ID is in the URL or visible in vault settings

### Step 4: Enable 1Password Connect and SecretStores

Uncomment the disabled components in `infrastructure/base/external-secrets/kustomization.yaml`:

```yaml
resources:
  - namespace.yaml
  - operator
  - onepassword-connect  # Uncomment this line
  - secretstores         # Uncomment this line
```

### Step 5: Deploy via Flux

```bash
# Apply the kustomization
kubectl apply -k infrastructure/base/external-secrets/

# Or trigger Flux reconciliation
flux reconcile kustomization external-secrets --with-source
```

Verify deployment:

```bash
# Check all pods are running
kubectl get pods -n external-secrets

# Check 1Password Connect is healthy
kubectl logs -n external-secrets deployment/onepassword-connect -c connect-api
kubectl logs -n external-secrets deployment/onepassword-connect -c connect-sync

# Verify SecretStores are ready
kubectl get clustersecretstore
kubectl get secretstore -n external-secrets
```

## Usage

### Creating an ExternalSecret

ExternalSecret resources define which secrets to sync from 1Password to Kubernetes.

**Example 1: Simple secret**

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: database-credentials
  namespace: default
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: onepassword
    kind: ClusterSecretStore
  target:
    name: db-secret
    creationPolicy: Owner
  data:
    - secretKey: password
      remoteRef:
        key: production-database  # 1Password item name
        property: password        # Field in the item
    - secretKey: username
      remoteRef:
        key: production-database
        property: username
```

**Example 2: Extract all fields**

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: api-keys
  namespace: default
spec:
  refreshInterval: 15m
  secretStoreRef:
    name: onepassword
    kind: ClusterSecretStore
  target:
    name: api-credentials
  dataFrom:
    - extract:
        key: api-credentials  # All fields from this 1Password item
```

**Example 3: Template for complex formats**

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: app-config
  namespace: default
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: onepassword
    kind: ClusterSecretStore
  target:
    name: app-config
    template:
      data:
        config.yaml: |
          database:
            host: {{ .db_host }}
            port: {{ .db_port }}
            username: {{ .db_user }}
            password: {{ .db_pass }}
  data:
    - secretKey: db_host
      remoteRef:
        key: app-database
        property: host
    - secretKey: db_port
      remoteRef:
        key: app-database
        property: port
    - secretKey: db_user
      remoteRef:
        key: app-database
        property: username
    - secretKey: db_pass
      remoteRef:
        key: app-database
        property: password
```

### Deploy an ExternalSecret

```bash
# Create the ExternalSecret
kubectl apply -f your-external-secret.yaml

# Verify it was created
kubectl get externalsecret -A

# Check if the target secret was created
kubectl get secret <target-secret-name> -n <namespace>

# View the ExternalSecret status
kubectl describe externalsecret <name> -n <namespace>
```

## Common Operations

### Refresh a Secret Immediately

```bash
# Annotate the ExternalSecret to trigger immediate refresh
kubectl annotate externalsecret <name> -n <namespace> \
  force-sync=$(date +%s) --overwrite
```

### View Secret Values (for debugging)

```bash
# CAUTION: This displays secret values in plaintext
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data}' | jq
```

### Check ESO Logs

```bash
# ESO controller logs
kubectl logs -n external-secrets deployment/external-secrets -f

# 1Password Connect API logs
kubectl logs -n external-secrets deployment/onepassword-connect -c connect-api -f

# 1Password Connect Sync logs
kubectl logs -n external-secrets deployment/onepassword-connect -c connect-sync -f
```

### Test 1Password Connect Connectivity

```bash
# Port-forward to Connect API
kubectl port-forward -n external-secrets svc/onepassword-connect 8080:8080

# Test health endpoint
curl http://localhost:8080/health

# Test with API token (requires token)
curl -H "Authorization: Bearer <your-token>" http://localhost:8080/v1/vaults
```

## Troubleshooting

### ExternalSecret Not Creating Secret

1. **Check ExternalSecret status:**
   ```bash
   kubectl describe externalsecret <name> -n <namespace>
   ```

2. **Common issues:**
   - Item name doesn't exist in 1Password
   - Property/field name is incorrect
   - Vault ID is wrong
   - SecretStore not ready

3. **Check ESO logs:**
   ```bash
   kubectl logs -n external-secrets deployment/external-secrets | grep -i error
   ```

### 1Password Connect Not Starting

1. **Check credentials secret:**
   ```bash
   kubectl get secret onepassword-connect-secret -n external-secrets
   ```

2. **Verify credentials file:**
   ```bash
   kubectl get secret onepassword-connect-secret -n external-secrets -o jsonpath='{.data.1password-credentials\.json}' | base64 -d | jq
   ```

3. **Check Connect logs:**
   ```bash
   kubectl logs -n external-secrets deployment/onepassword-connect -c connect-api
   kubectl logs -n external-secrets deployment/onepassword-connect -c connect-sync
   ```

### SecretStore Not Ready

1. **Check SecretStore status:**
   ```bash
   kubectl get secretstore -A
   kubectl describe clustersecretstore onepassword
   ```

2. **Verify token secret exists:**
   ```bash
   kubectl get secret onepassword-connect-token -n external-secrets
   ```

3. **Check connectivity:**
   ```bash
   kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- \
     curl http://onepassword-connect.external-secrets.svc.cluster.local:8080/health
   ```

## Security Considerations

### Secret Protection

- The `1password-credentials.json` contains vault tokens - protect it carefully
- The Connect API token grants access to create/read/update/delete secrets
- Both secrets are stored as Kubernetes Secrets (base64 encoded, not encrypted at rest by default)

### Encryption at Rest

Consider enabling Kubernetes Secrets encryption:

```bash
# Talos: Configure encryption in machine config
# See: https://www.talos.dev/latest/kubernetes-guides/configuration/encryptionconfig/
```

### Network Policies

Restrict access to 1Password Connect:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: onepassword-connect
  namespace: external-secrets
spec:
  podSelector:
    matchLabels:
      app: onepassword-connect
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: external-secrets
      ports:
        - protocol: TCP
          port: 8080
```

### RBAC

External Secrets Operator requires permissions to read ExternalSecret resources and create/update Secrets. The Helm chart creates appropriate RBAC rules automatically.

## Monitoring

### Prometheus Metrics

ESO exposes Prometheus metrics on port 8080 at `/metrics`:

```yaml
# ServiceMonitor is automatically created by the Helm chart
# Metrics include:
# - externalsecret_sync_calls_total
# - externalsecret_sync_calls_error
# - externalsecret_status_condition
```

View metrics:

```bash
kubectl port-forward -n external-secrets svc/external-secrets-webhook 8080:8080
curl http://localhost:8080/metrics
```

### Grafana Dashboards

Import the official ESO dashboard:
- Dashboard ID: 16170
- URL: https://grafana.com/grafana/dashboards/16170

## Migration from Manual Secrets

If you have existing manually created secrets that you want to migrate to ESO:

1. **Create the ExternalSecret** with the same target secret name
2. **Set `creationPolicy: Merge`** to merge with existing secret
3. **Or delete existing secret first** if you want ESO to own it completely

```yaml
spec:
  target:
    name: existing-secret
    creationPolicy: Merge  # or Owner (deletes existing)
```

## Best Practices

1. **Use ClusterSecretStore** for secrets accessed across multiple namespaces
2. **Use SecretStore** for namespace-specific secrets
3. **Set appropriate refreshInterval** (default: 1h, minimum: 1m)
4. **Use templates** for complex secret formats (config files, certificates)
5. **Monitor ExternalSecret status** in your observability stack
6. **Version your ExternalSecret manifests** in Git (they don't contain secrets)
7. **Use meaningful names** for 1Password items that match your ExternalSecret keys

## Integration with ArgoCD/Flux

ExternalSecret resources work seamlessly with GitOps:

1. **Store ExternalSecret manifests in Git** (safe - no secrets)
2. **ArgoCD/Flux applies ExternalSecret resources**
3. **ESO creates/updates the actual Secret resources**
4. **Applications reference the synced Secrets**

```
Git Repo → Flux/ArgoCD → ExternalSecret → ESO → 1Password → Kubernetes Secret → App
```

## References

- [External Secrets Operator Docs](https://external-secrets.io/)
- [1Password Connect](https://developer.1password.com/docs/connect/)
- [ESO 1Password Provider](https://external-secrets.io/latest/provider/1password-sdk/)
- [FluxCD Secrets Management](https://fluxcd.io/flux/security/secrets-management/)

## Support

For issues specific to this setup:
- Check logs: `kubectl logs -n external-secrets deployment/external-secrets`
- Review ExternalSecret status: `kubectl describe externalsecret <name>`
- Test 1Password Connect health: `kubectl port-forward -n external-secrets svc/onepassword-connect 8080:8080`

For general ESO issues:
- GitHub: https://github.com/external-secrets/external-secrets/issues
- Slack: https://kubernetes.slack.com/messages/external-secrets
