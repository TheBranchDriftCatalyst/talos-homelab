# External Secrets Operator - Status

**Last Updated:** 2025-11-22

## Current Status

| Component | Status | Health | Notes |
|-----------|--------|--------|-------|
| ESO Operator | 🟡 Ready | ⚪ Not Deployed | HelmRelease created, awaiting Flux |
| 1Password Connect | 🟡 Ready | ⚪ Not Deployed | Manifests created, needs credentials |
| ClusterSecretStore | 🟡 Ready | ⚪ Not Deployed | Needs vault ID update |
| SecretStore | 🟡 Ready | ⚪ Not Deployed | Needs vault ID update |

**Legend:**
- Status: ✅ Deployed | 🟡 Ready | 🔴 Not Started
- Health: 🟢 Healthy | 🟡 Degraded | 🔴 Down | ⚪ Not Deployed

## Overview

External Secrets Operator (ESO) integration with 1Password Connect is configured and ready for deployment. All manifests are in place and managed by FluxCD.

## Deployment Checklist

### Prerequisites
- [x] FluxCD installed and bootstrapped
- [x] ESO HelmRepository manifest created
- [x] ESO HelmRelease manifest created
- [x] 1Password Connect deployment manifests created
- [x] SecretStore configurations created
- [x] Setup script created
- [x] Documentation completed

### Configuration Required
- [ ] Obtain 1Password Connect credentials file
- [ ] Generate 1Password Connect API token
- [ ] Run setup script: `./scripts/setup-1password-connect.sh`
- [ ] Update vault ID in `secretstores/onepassword-secretstore.yaml`
- [ ] Uncomment 1Password Connect and SecretStores in root kustomization

### Deployment
- [ ] Deploy ESO operator: `kubectl apply -k infrastructure/base/external-secrets/operator/`
- [ ] Verify ESO pods running
- [ ] Deploy 1Password Connect: `kubectl apply -k infrastructure/base/external-secrets/onepassword-connect/`
- [ ] Verify Connect pods running
- [ ] Deploy SecretStores: `kubectl apply -k infrastructure/base/external-secrets/secretstores/`
- [ ] Verify SecretStores ready

### Validation
- [ ] Create test ExternalSecret
- [ ] Verify secret created in Kubernetes
- [ ] Check Prometheus metrics endpoint
- [ ] Review logs for errors

## Components

### External Secrets Operator

**Version:** 0.11.x (latest compatible)
**Namespace:** external-secrets
**Management:** FluxCD HelmRelease

**Features Enabled:**
- CRD auto-install/upgrade
- ServiceMonitor for Prometheus
- Webhook for validation
- Cert controller for webhook certs

**Resource Limits:**
- Controller: 10m CPU / 64Mi RAM (requests), 100m CPU / 128Mi RAM (limits)
- Cert Controller: 10m CPU / 64Mi RAM (requests), 100m CPU / 128Mi RAM (limits)

### 1Password Connect Server

**Version:** 1.7.3
**Namespace:** external-secrets
**Components:**
- connect-api (port 8080) - REST API for external clients
- connect-sync (port 8081) - Syncs with 1Password cloud

**Resource Limits (per container):**
- Requests: 50m CPU / 128Mi RAM
- Limits: 200m CPU / 256Mi RAM

**Health Checks:**
- Liveness: HTTP GET /health (every 30s)
- Readiness: HTTP GET /health (every 10s)

**Storage:**
- EmptyDir volume for shared data between API and Sync containers

### SecretStores

**ClusterSecretStore:** `onepassword`
- Scope: Cluster-wide
- Provider: 1Password Connect
- Connect URL: `http://onepassword-connect.external-secrets.svc.cluster.local:8080`

**SecretStore:** `onepassword` (namespace: external-secrets)
- Scope: external-secrets namespace only
- Provider: 1Password Connect
- Same configuration as ClusterSecretStore

## Usage Patterns

### Example 1: Database Credentials

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: postgres-creds
  namespace: default
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: onepassword
    kind: ClusterSecretStore
  target:
    name: postgres-secret
  data:
    - secretKey: username
      remoteRef:
        key: production-postgres
        property: username
    - secretKey: password
      remoteRef:
        key: production-postgres
        property: password
```

### Example 2: API Keys (Extract All)

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
        key: api-credentials
```

## Integration Points

### With GitOps (Flux/ArgoCD)

ESO works seamlessly with GitOps workflows:

1. **ExternalSecret manifests** stored in Git (safe - no secrets)
2. **Flux/ArgoCD** applies ExternalSecret resources
3. **ESO** syncs secrets from 1Password
4. **Applications** consume Kubernetes Secrets

### With Monitoring Stack

- **ServiceMonitor** automatically created for Prometheus scraping
- **Metrics endpoint:** `:8080/metrics`
- **Key metrics:**
  - `externalsecret_sync_calls_total`
  - `externalsecret_sync_calls_error`
  - `externalsecret_status_condition`

### With Applications

Applications reference the synced secrets normally:

```yaml
env:
  - name: DB_PASSWORD
    valueFrom:
      secretKeyRef:
        name: postgres-secret  # Created by ExternalSecret
        key: password
```

## Known Issues

### 1. Vault ID Placeholder

**Issue:** Default vault ID is set to `1` in SecretStore manifests
**Impact:** SecretStore will not be ready until updated with actual vault ID
**Resolution:** Update `vaults` section in `secretstores/onepassword-secretstore.yaml`

### 2. Initial Secrets Required

**Issue:** 1Password Connect requires two manual secrets before deployment
**Impact:** Cannot deploy Connect server without credentials
**Resolution:** Run `./scripts/setup-1password-connect.sh`

### 3. Components Disabled by Default

**Issue:** 1Password Connect and SecretStores are commented out in kustomization
**Impact:** ESO operator will deploy but cannot sync secrets
**Resolution:** Uncomment after running setup script

## Security Considerations

### Secret Management

- **Credentials file** (`1password-credentials.json`) contains vault access tokens
- **API token** grants full access to configured vaults
- Both stored as Kubernetes Secrets (base64, not encrypted at rest by default)

### Recommendations

1. **Enable Secrets Encryption at Rest** (Talos config)
2. **Restrict RBAC** for external-secrets namespace
3. **Implement NetworkPolicy** to limit Connect access
4. **Rotate tokens** regularly
5. **Audit access logs** in 1Password

### Network Security

- Connect server only exposed via ClusterIP (internal)
- No external ingress configured
- Communication with 1Password cloud over HTTPS

## Monitoring & Observability

### Metrics

Access ESO metrics:

```bash
kubectl port-forward -n external-secrets svc/external-secrets-webhook 8080:8080
curl http://localhost:8080/metrics | grep externalsecret
```

### Logs

Monitor ESO activity:

```bash
# ESO controller
kubectl logs -n external-secrets deployment/external-secrets -f

# 1Password Connect API
kubectl logs -n external-secrets deployment/onepassword-connect -c connect-api -f

# 1Password Connect Sync
kubectl logs -n external-secrets deployment/onepassword-connect -c connect-sync -f
```

### Health Checks

```bash
# ESO webhook health
kubectl get pods -n external-secrets -l app.kubernetes.io/name=external-secrets

# Connect server health
kubectl exec -n external-secrets deployment/onepassword-connect -c connect-api -- \
  wget -qO- http://localhost:8080/health
```

## Next Steps

1. **Obtain 1Password Credentials**
   - Create Connect Server at https://my.1password.com/developer-tools/infrastructure-secrets/connect
   - Download credentials file
   - Generate API token

2. **Run Setup Script**
   ```bash
   ./scripts/setup-1password-connect.sh
   ```

3. **Update Configuration**
   - Edit vault ID in SecretStore manifests
   - Uncomment disabled components

4. **Deploy via Flux**
   ```bash
   flux reconcile kustomization external-secrets --with-source
   ```

5. **Create Test ExternalSecret**
   - Use example from `secretstores/example-externalsecret.yaml`
   - Verify secret creation

6. **Migrate Existing Secrets**
   - Identify manually managed secrets
   - Create ExternalSecret resources
   - Validate and test

## Rollback Plan

If issues occur:

```bash
# Suspend Flux reconciliation
flux suspend kustomization external-secrets

# Or manually delete resources
kubectl delete -k infrastructure/base/external-secrets/

# ESO CRDs will remain (safe)
# Manual secrets unaffected
```

## References

- [README.md](./README.md) - Complete setup guide
- [External Secrets Operator Docs](https://external-secrets.io/)
- [1Password Connect](https://developer.1password.com/docs/connect/)
- [Flux Secrets Management](https://fluxcd.io/flux/security/secrets-management/)

## Change Log

### 2025-11-22
- ✅ Initial ESO configuration created
- ✅ 1Password Connect manifests created
- ✅ SecretStore configurations created
- ✅ Setup script created
- ✅ Documentation completed
- ⏳ Awaiting 1Password credentials
