# Setting Up Discord Webhook in 1Password

This guide explains how to store the Discord webhook URL in 1Password so it can be synced to Kubernetes via External Secrets Operator.

## Prerequisites

- 1Password vault named `catalyst-eso` (or update the vault name in the ExternalSecret)
- External Secrets Operator installed and configured
- ClusterSecretStore `onepassword` is ready

## Step 1: Get Discord Webhook URL

1. Open your Discord server
2. Go to **Server Settings → Integrations → Webhooks**
3. Click **Create Webhook** or select an existing webhook
4. Configure the webhook:
   - **Name**: Flux Bot (or any name you prefer)
   - **Channel**: Select the channel where you want notifications
5. Click **Copy Webhook URL**

The URL will look like:

```
https://discord.com/api/webhooks/1234567890/AbCdEfGhIjKlMnOpQrStUvWxYz
```

## Step 2: Create 1Password Item

### Option A: Using 1Password App

1. Open 1Password
2. Select your `catalyst-eso` vault
3. Click **New Item** → **API Credential** (or **Password**)
4. Fill in the details:
   - **Title**: `flux-discord-webhook`
   - Add a field named `webhook_url` with the Discord webhook URL
5. Save the item

### Option B: Using 1Password CLI

```bash
# Login to 1Password
eval $(op signin)

# Create the item
op item create \
  --vault=catalyst-eso \
  --category=password \
  --title="flux-discord-webhook" \
  webhook_url[password]="https://discord.com/api/webhooks/YOUR_WEBHOOK_URL"
```

## Step 3: Verify 1Password Item Structure

The item in 1Password should have:

- **Title**: `flux-discord-webhook`
- **Field Name**: `webhook_url`
- **Field Value**: Your Discord webhook URL

You can verify using the debug script:

```bash
./scripts/onepassword-list-secrets.sh
```

Look for the item and ensure the `webhook_url` field is present.

## Step 4: Deploy Flux Notifications

Once the 1Password item is created, deploy the Flux notification configuration:

```bash
kubectl apply -k infrastructure/base/flux-notifications/
```

## Step 5: Verify ExternalSecret

Check that the ExternalSecret synced successfully:

```bash
# Check ExternalSecret status
kubectl get externalsecret discord-webhook -n flux-system

# Should show:
# NAME              STORE         REFRESH INTERVAL   STATUS   READY
# discord-webhook   onepassword   1h                 SecretSynced   True

# Verify the secret was created
kubectl get secret discord-webhook -n flux-system

# Check Provider status
kubectl get provider discord -n flux-system
```

## Step 6: Test Notifications

Trigger a Flux reconciliation to test:

```bash
flux reconcile kustomization flux-system --with-source
```

You should see a notification in your Discord channel!

## Troubleshooting

### ExternalSecret not syncing

Check the ExternalSecret status:

```bash
kubectl describe externalsecret discord-webhook -n flux-system
```

Look for error messages in the status conditions.

### Provider not ready

Check the Provider status:

```bash
kubectl describe provider discord -n flux-system
```

### Secret exists but notifications not working

1. Verify the webhook URL is correct:

   ```bash
   kubectl get secret discord-webhook -n flux-system -o jsonpath='{.data.address}' | base64 -d
   ```

2. Check notification-controller logs:
   ```bash
   kubectl logs -n flux-system -l app=notification-controller -f
   ```

### 1Password item not found

Ensure:

- The vault name matches (`catalyst-eso`)
- The item title is exactly `flux-discord-webhook`
- The field name is `webhook_url` (case-sensitive)
- The ClusterSecretStore is ready: `kubectl get clustersecretstore onepassword`

## ExternalSecret Configuration

The ExternalSecret is configured to:

- **Refresh every hour** - Webhook URL changes are picked up automatically
- **Use ClusterSecretStore** - Works across all namespaces
- **Target namespace**: `flux-system`
- **Secret name**: `discord-webhook`
- **Secret key**: `address` (required by Flux Discord provider)

## 1Password Item Reference

```yaml
# Item in 1Password:
Title: flux-discord-webhook
Vault: catalyst-eso

Fields:
  webhook_url: https://discord.com/api/webhooks/1234567890/AbCdEfGhIjKlMnOpQrStUvWxYz
```

```yaml
# Mapped to Kubernetes Secret:
apiVersion: v1
kind: Secret
metadata:
  name: discord-webhook
  namespace: flux-system
data:
  address: <base64-encoded-webhook-url>
```

## Security Notes

- The webhook URL is sensitive - anyone with it can post to your Discord channel
- Store it securely in 1Password
- Never commit the actual webhook URL to git
- The ExternalSecret automatically keeps the secret in sync with 1Password
- If you need to rotate the webhook, just update it in 1Password and wait for the refresh interval (or force refresh)

## Force Refresh

To immediately sync changes from 1Password:

```bash
# Annotate the ExternalSecret to trigger refresh
kubectl annotate externalsecret discord-webhook -n flux-system \
  force-sync=$(date +%s) --overwrite
```
