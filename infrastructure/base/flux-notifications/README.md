# Flux Discord Notifications

Real-time notifications for Flux CD events sent to Discord.

## Features

- **Real-time alerts** for GitRepository, Kustomization, and HelmRelease changes
- **Critical error notifications** with dedicated alert configuration
- **Customizable event severity** filtering (info, error, warning)
- **Rich Discord embeds** with color-coded status indicators

## Setup

### Option A: Using 1Password (Recommended)

The Discord webhook URL is automatically synced from 1Password using External Secrets Operator.

**See [SETUP-1PASSWORD.md](./SETUP-1PASSWORD.md) for detailed instructions.**

Quick steps:
1. Get Discord webhook URL from your server settings
2. Create 1Password item named `flux-discord-webhook` in `catalyst-eso` vault
3. Add field `webhook_url` with the webhook URL
4. Apply configuration: `kubectl apply -k infrastructure/base/flux-notifications/`

The ExternalSecret will automatically sync the webhook URL to Kubernetes.

### Option B: Manual Secret (Not Recommended)

For testing or if 1Password is not available:

```bash
kubectl create secret generic discord-webhook \
  --from-literal=address="https://discord.com/api/webhooks/YOUR_WEBHOOK_URL" \
  --namespace=flux-system

kubectl apply -k infrastructure/base/flux-notifications/
```

**Note**: Manual secrets are not version-controlled and require manual rotation.

### 3. Verify

Check provider status:

```bash
kubectl get provider discord -n flux-system
```

Check configured alerts:

```bash
kubectl get alerts -n flux-system
```

## Alerts Configured

### 1. Homelab Infrastructure Alerts
- **Severity**: Info and above
- **Sources**: All GitRepositories, Kustomizations, HelmReleases
- **Purpose**: General deployment and update notifications

### 2. Critical Errors
- **Severity**: Error only
- **Sources**: All Flux resources
- **Purpose**: Immediate notification of failures

## Notification Examples

You'll receive Discord messages for events like:

- ✅ **HelmRelease deployed successfully** - `external-secrets v0.11.0`
- ⚠️ **Kustomization reconciliation failed** - Check for syntax errors
- 🔄 **GitRepository updated** - New commits detected
- 🚨 **Critical error** - Deployment failed with error details

## Customization

### Change Event Severity

Edit `alert.yaml` to change which events trigger notifications:

```yaml
spec:
  eventSeverity: info  # Options: info, error, warning
```

### Add More Alerts

Create additional Alert resources for specific namespaces or resources:

```yaml
apiVersion: notification.toolkit.fluxcd.io/v1beta3
kind: Alert
metadata:
  name: media-stack-alerts
  namespace: flux-system
spec:
  summary: "Media Stack Deployments"
  providerRef:
    name: discord
  eventSeverity: info
  eventSources:
    - kind: HelmRelease
      name: '*'
      namespace: 'media-*'
```

### Customize Discord Bot Appearance

Edit `provider.yaml`:

```yaml
spec:
  type: discord
  username: "Flux Bot"  # Change bot name
  channel: "flux-alerts"  # Change channel name (cosmetic)
```

## Troubleshooting

### No notifications received

1. Check provider status:
   ```bash
   kubectl describe provider discord -n flux-system
   ```

2. View notification-controller logs:
   ```bash
   kubectl logs -n flux-system -l app=notification-controller -f
   ```

3. Verify webhook URL is correct:
   ```bash
   kubectl get secret discord-webhook -n flux-system -o jsonpath='{.data.address}' | base64 -d
   ```

### Test notifications manually

Trigger a reconciliation:

```bash
flux reconcile kustomization flux-system --with-source
```

Or suspend/resume a resource:

```bash
flux suspend helmrelease external-secrets -n external-secrets
flux resume helmrelease external-secrets -n external-secrets
```

## References

- [Flux Notification Controller](https://fluxcd.io/flux/components/notification/)
- [Discord Provider](https://fluxcd.io/flux/components/notification/providers/#discord)
- [Alert API](https://fluxcd.io/flux/components/notification/alerts/)
