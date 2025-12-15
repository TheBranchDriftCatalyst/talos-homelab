# External Secrets / 1Password Scripts

Scripts for managing External Secrets Operator and 1Password Connect integration.

## Scripts

### setup-1password-connect.sh

Bootstrap script for setting up 1Password Connect secrets. Creates the required Kubernetes secrets for 1Password Connect to authenticate.

```bash
# Auto mode (recommended) - uses env vars and local files
./setup-1password-connect.sh --auto

# Force recreate existing secrets
./setup-1password-connect.sh --auto --force

# Interactive mode
./setup-1password-connect.sh
```

**Requirements for auto mode:**
- `OP_CONNECT_TOKEN` environment variable
- `1password-credentials.json` in project root (or set `OP_CREDENTIALS_FILE`)

### resync-externalsecrets.sh

Force resync all ExternalSecrets by annotating them with a timestamp.

```bash
# Resync all ExternalSecrets
./resync-externalsecrets.sh

# Resync only 1Password-backed ExternalSecrets
./resync-externalsecrets.sh --onepassword-only
```

### onepassword-debug.sh

Comprehensive debug tool that checks:
- Cluster connectivity
- External Secrets Operator status
- 1Password Connect deployment
- SecretStore/ClusterSecretStore status
- ExternalSecrets sync status
- API connectivity

```bash
./onepassword-debug.sh
```

### onepassword-list-secrets.sh

Lists all secrets from 1Password Connect API. Runs an ephemeral pod to query vaults and items.

```bash
# List secrets from default vault (catalyst-eso)
./onepassword-list-secrets.sh

# List secrets from a specific vault
VAULT_NAME=my-vault ./onepassword-list-secrets.sh
```

### debug-job-list-secrets.yaml

Kubernetes Job manifest that does the same as `onepassword-list-secrets.sh` but runs as a cluster job. Useful for debugging from within the cluster.

```bash
kubectl apply -f debug-job-list-secrets.yaml
kubectl logs -f job/onepassword-debug -n external-secrets
```

## Quick Recovery

If 1Password Connect stops working (e.g., after namespace recreation):

```bash
# Re-setup the bootstrap secrets
./setup-1password-connect.sh --auto --force

# Force resync all ExternalSecrets
./resync-externalsecrets.sh
```
