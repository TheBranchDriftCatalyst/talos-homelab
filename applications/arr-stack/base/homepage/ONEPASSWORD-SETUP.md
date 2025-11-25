# 1Password Setup for Homepage Dashboard

This guide explains how to set up 1Password to securely store and sync API keys for the Homepage dashboard.

## Overview

The Homepage dashboard uses External Secrets Operator (ESO) to sync credentials from 1Password. All API keys and tokens are stored in a single 1Password item called `arr-stack-credentials`.

## Prerequisites

- 1Password account with a vault named `catalyst-eso`
- External Secrets Operator installed in the cluster
- 1Password Connect Server deployed and configured
- ClusterSecretStore `onepassword` configured

## 1Password Item Structure

Create a single 1Password item in the `catalyst-eso` vault with the following structure:

### Item Name: `arr-stack-credentials`

**Type:** Password or Secure Note

### Fields Required

Create the following custom fields in the 1Password item:

| Field Name          | Type     | Description               | Where to Find                            |
| ------------------- | -------- | ------------------------- | ---------------------------------------- |
| `sonarr_api_key`    | password | Sonarr API Key            | Sonarr → Settings → General → API Key    |
| `radarr_api_key`    | password | Radarr API Key            | Radarr → Settings → General → API Key    |
| `readarr_api_key`   | password | Readarr API Key           | Readarr → Settings → General → API Key   |
| `prowlarr_api_key`  | password | Prowlarr API Key          | Prowlarr → Settings → General → API Key  |
| `plex_token`        | password | Plex Authentication Token | See Plex Token Instructions below        |
| `jellyfin_api_key`  | password | Jellyfin API Key          | Jellyfin → Dashboard → API Keys          |
| `overseerr_api_key` | password | Overseerr API Key         | Overseerr → Settings → General → API Key |
| `argocd_token`      | password | ArgoCD Token              | See ArgoCD Token Instructions below      |
| `grafana_username`  | text     | Grafana Username          | Default: `admin`                         |
| `grafana_password`  | password | Grafana Password          | Default: `prom-operator` or from secret  |

## Step-by-Step Setup

### 1. Create the 1Password Item

Using 1Password CLI:

```bash
# Create the item
op item create \
  --category="Secure Note" \
  --title="arr-stack-credentials" \
  --vault="catalyst-eso"
```

Or use the 1Password web interface or desktop app to create a new item manually.

### 2. Add Fields to the Item

Using 1Password CLI:

```bash
# Add each field
op item edit arr-stack-credentials \
  sonarr_api_key[password]="YOUR_SONARR_API_KEY" \
  radarr_api_key[password]="YOUR_RADARR_API_KEY" \
  readarr_api_key[password]="YOUR_READARR_API_KEY" \
  prowlarr_api_key[password]="YOUR_PROWLARR_API_KEY" \
  plex_token[password]="YOUR_PLEX_TOKEN" \
  jellyfin_api_key[password]="YOUR_JELLYFIN_API_KEY" \
  overseerr_api_key[password]="YOUR_OVERSEERR_API_KEY" \
  argocd_token[password]="YOUR_ARGOCD_TOKEN" \
  grafana_username[text]="admin" \
  grafana_password[password]="YOUR_GRAFANA_PASSWORD" \
  --vault="catalyst-eso"
```

Or add fields manually in the 1Password interface:

1. Open the `arr-stack-credentials` item
2. Click "Add Field"
3. Select "Password" or "Text" type
4. Enter the field name exactly as shown above
5. Enter the value
6. Save the item

### 3. Getting API Keys and Tokens

#### \*arr Applications (Sonarr, Radarr, Readarr, Prowlarr)

For each \*arr application:

1. Navigate to the web interface (e.g., http://sonarr.talos00)
2. Go to **Settings** → **General**
3. Scroll to **Security** section
4. Copy the **API Key**
5. Add to the corresponding field in 1Password

#### Plex Token

**Method 1: From Plex Web App**

1. Open Plex Web App and sign in
2. Open any media item
3. Click "Get Info" (three dots)
4. Click "View XML"
5. Look for `X-Plex-Token` in the URL
6. Copy the token value

**Method 2: Using curl**

```bash
curl -u "YOUR_PLEX_USERNAME:YOUR_PLEX_PASSWORD" \
  https://plex.tv/users/sign_in.json \
  -X POST \
  | jq -r '.user.authToken'
```

**Method 3: From Plex Settings**

1. Sign in to plex.tv
2. Settings → Account → "Get Token" at the bottom
3. Copy your authentication token

Reference: https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/

#### Jellyfin API Key

1. Navigate to http://jellyfin.talos00
2. Go to **Dashboard** → **API Keys**
3. Click **"+"** to create a new API key
4. Name it "Homepage Dashboard"
5. Copy the generated API key
6. Add to 1Password

#### Overseerr API Key

1. Navigate to http://overseerr.talos00
2. Go to **Settings** → **General**
3. Scroll to **API Key** section
4. Copy the API key
5. Add to 1Password

#### ArgoCD Token

**Create a readonly service account:**

1. Create the account:

```bash
kubectl edit configmap argocd-cm -n argocd
```

Add under `data:`:

```yaml
accounts.readonly: apiKey
```

1. Configure RBAC:

```bash
kubectl edit configmap argocd-rbac-cm -n argocd
```

Add under `data:`:

```yaml
policy.csv: |
  g, readonly, role:readonly
```

1. Restart ArgoCD:

```bash
kubectl rollout restart deployment argocd-server -n argocd
```

1. Generate the token:

```bash
# Get the ArgoCD admin password first
ARGOCD_PASS=$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d)

# Login
argocd login argocd.talos00 --username admin --password "$ARGOCD_PASS"

# Generate token for readonly account
argocd account generate-token --account readonly
```

1. Copy the token to 1Password

#### Grafana Credentials

**Get the password from the secret:**

```bash
kubectl get secret prometheus-grafana -n monitoring \
  -o jsonpath="{.data.admin-password}" | base64 -d
```

Default credentials:

- Username: `admin`
- Password: `prom-operator` (or value from secret above)

Add both to 1Password.

### 4. Verify the ExternalSecret

Once the 1Password item is created, verify the ExternalSecret is syncing:

```bash
# Check ExternalSecret status
kubectl get externalsecret homepage-secrets -n media-dev

# Check if the secret was created
kubectl get secret homepage-secrets -n media-dev

# Verify secret contents (will show the keys, not values)
kubectl describe secret homepage-secrets -n media-dev
```

Expected output:

```
NAME               TYPE     DATA   AGE
homepage-secrets   Opaque   10     1m
```

### 5. Deploy Homepage

Once the secret is syncing successfully:

```bash
# Apply the homepage configuration
kubectl apply -k applications/arr-stack/base/homepage/

# Check deployment
kubectl get pods -n media-dev -l app=homepage

# Check logs for any errors
kubectl logs -n media-dev -l app=homepage
```

## Troubleshooting

### ExternalSecret Not Syncing

Check the ExternalSecret status:

```bash
kubectl describe externalsecret homepage-secrets -n media-dev
```

Look for error messages in the status section.

### Common Issues

**Issue: "secret not found in 1Password"**

- Verify the item name is exactly `arr-stack-credentials`
- Check that it's in the `catalyst-eso` vault
- Verify ClusterSecretStore vault mapping

**Issue: "property not found"**

- Verify field names match exactly (case-sensitive)
- Check that fields are the correct type (password vs text)
- Field names use underscores, not hyphens

**Issue: "unable to connect to 1Password Connect"**

- Verify 1Password Connect is running:
  ```bash
  kubectl get pods -n external-secrets -l app=onepassword-connect
  ```
- Check connect token secret exists:
  ```bash
  kubectl get secret onepassword-connect-token -n external-secrets
  ```

### Verify Widget Functionality

After deployment, check that widgets are loading:

1. Access Homepage: http://homepage.talos00
2. Check that service widgets display data (not error messages)
3. If widgets show "API Error", check:
   - Service is accessible from homepage pod
   - API key is correct
   - Service URL is correct

Test individual service access:

```bash
# Test from inside the homepage pod
kubectl exec -n media-dev -it deploy/homepage -- sh

# Test Sonarr API
wget -qO- http://sonarr.media-dev.svc.cluster.local:8989/api/v3/system/status \
  --header "X-Api-Key: $HOMEPAGE_VAR_SONARR_KEY"
```

## Updating Credentials

To update any credential:

1. Edit the 1Password item `arr-stack-credentials`
2. Update the field value
3. Wait up to 1 hour (refreshInterval) or force refresh:
   ```bash
   kubectl annotate externalsecret homepage-secrets -n media-dev \
     force-sync=$(date +%s) --overwrite
   ```
4. Restart homepage pod to pick up new values:
   ```bash
   kubectl rollout restart deployment homepage -n media-dev
   ```

## Security Notes

- Never commit API keys or tokens to git
- The ExternalSecret creates a Kubernetes secret that is ephemeral
- Credentials are stored securely in 1Password
- Homepage pod reads credentials as environment variables
- Use readonly tokens where possible (e.g., ArgoCD)
- Regularly rotate API keys and tokens

## Related Documentation

- [External Secrets Operator](../../infrastructure/base/external-secrets/README.md)
- [1Password Connect Setup](../../infrastructure/base/external-secrets/onepassword-connect/)
- [Homepage Configuration](./README.md)
- [ClusterSecretStore Configuration](../../infrastructure/base/external-secrets/secretstores/onepassword-secretstore.yaml)
