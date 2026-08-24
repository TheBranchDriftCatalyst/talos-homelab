# External Secrets Operator Implementation

**Date:** 2025-11-22
**Session Focus:** Implement External Secrets Operator with 1Password Connect integration, managed by FluxCD

## Summary

Implemented External Secrets Operator (ESO) with 1Password Connect for secure secrets management in the Kubernetes cluster. All components are configured to be managed by FluxCD for GitOps-based infrastructure management.

## Implementation Details

### Components Created

#### 1. External Secrets Operator (Flux-managed)

**Location:** `infrastructure/base/external-secrets/operator/`

- **HelmRepository:** Charts from https://charts.external-secrets.io
- **HelmRelease:** Version 0.11.x with automatic CRD management
- **Features:**
  - ServiceMonitor for Prometheus metrics
  - Webhook validation
  - Cert controller for webhook certificates
  - Resource limits: 10m/64Mi (requests), 100m/128Mi (limits)

#### 2. 1Password Connect Server

**Location:** `infrastructure/base/external-secrets/onepassword-connect/`

- **Deployment:** Two-container setup
  - `connect-api` (port 8080) - REST API for ESO
  - `connect-sync` (port 8081) - Syncs with 1Password cloud
- **Version:** 1.7.3
- **Health checks:** HTTP /health endpoints
- **Storage:** EmptyDir for shared data between containers

#### 3. SecretStore Configurations

**Location:** `infrastructure/base/external-secrets/secretstores/`

- **ClusterSecretStore:** `onepassword` (cluster-wide access)
- **SecretStore:** `onepassword` (namespace-scoped)
- **Example ExternalSecret:** Reference implementation

#### 4. Setup Automation

**Location:** `scripts/setup-1password-connect.sh`

Interactive script to:

- Create namespace if missing
- Create `onepassword-connect-secret` (credentials file)
- Create `onepassword-connect-token` (API token)
- Guide user through vault ID configuration

### Architecture

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

### Directory Structure

```
infrastructure/base/external-secrets/
├── namespace.yaml                    # external-secrets namespace
├── operator/                         # ESO deployment
│   ├── helmrepository.yaml
│   ├── helmrelease.yaml
│   └── kustomization.yaml
├── onepassword-connect/             # 1Password Connect Server
│   ├── deployment.yaml
│   ├── service.yaml
│   └── kustomization.yaml
├── secretstores/                    # SecretStore configs
│   ├── onepassword-secretstore.yaml
│   ├── example-externalsecret.yaml
│   └── kustomization.yaml
├── kustomization.yaml               # Root (operator only by default)
├── README.md                        # Complete setup guide
└── STATUS.md                        # Current status tracking
```

## Deployment Status

### Current State

- ✅ All manifests created and validated
- ✅ Documentation complete (README.md, STATUS.md)
- ✅ Setup script ready
- ⏳ Awaiting 1Password credentials (manual step)
- ⏳ Not yet deployed (pending Flux bootstrap)

### Prerequisites for Deployment

1. **FluxCD must be bootstrapped** (tracked in TODO.md)
2. **1Password credentials required:**
   - `1password-credentials.json` file
   - Connect API token
   - Vault ID

### Deployment Steps

Once prerequisites are met:

```bash
# 1. Run setup script
./scripts/setup-1password-connect.sh

# 2. Update vault ID in SecretStore
vim infrastructure/base/external-secrets/secretstores/onepassword-secretstore.yaml

# 3. Uncomment components in root kustomization
vim infrastructure/base/external-secrets/kustomization.yaml
# Uncomment: onepassword-connect, secretstores

# 4. Deploy via Flux
flux reconcile kustomization external-secrets --with-source
```

## Integration with GitOps

### Flux Manages Infrastructure

ESO is part of the infrastructure layer managed by Flux:

```
FluxCD (Infrastructure):
├── Namespaces
├── Storage (local-path-provisioner)
├── Monitoring (kube-prometheus-stack)
├── Observability (Graylog, OpenSearch, etc.)
└── External Secrets Operator ← NEW
    ├── ESO operator
    ├── 1Password Connect
    └── SecretStores
```

### ArgoCD Manages Applications

Applications use ExternalSecret resources to fetch secrets:

```yaml
# In application repo (managed by ArgoCD)
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: app-secrets
spec:
  secretStoreRef:
    name: onepassword
    kind: ClusterSecretStore
  target:
    name: app-credentials
  data:
    - secretKey: api-key
      remoteRef:
        key: my-app-credentials
        property: api-key
```

## Usage Examples

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

### Example 2: Extract All Fields

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: api-keys
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

## Security Considerations

### Secrets Protection

- 1Password credentials stored as Kubernetes Secrets (base64)
- Connect Server only accessible via ClusterIP (internal)
- No external ingress configured
- Recommend enabling Kubernetes Secrets encryption at rest

### Network Security

- Connect Server communicates with 1Password cloud over HTTPS
- Internal cluster communication unencrypted (ClusterIP)
- Consider NetworkPolicy to restrict access to Connect Server

### RBAC

- ESO operator has cluster-wide permissions (created by Helm chart)
- ExternalSecret resources can be namespace-scoped
- Use SecretStore (namespace) vs ClusterSecretStore (cluster-wide) appropriately

## Monitoring

### Prometheus Metrics

ESO exposes metrics automatically via ServiceMonitor:

```
externalsecret_sync_calls_total
externalsecret_sync_calls_error
externalsecret_status_condition
```

### Grafana Dashboard

- Import dashboard ID: 16170
- URL: https://grafana.com/grafana/dashboards/16170

### Health Checks

```bash
# ESO operator health
kubectl get pods -n external-secrets

# 1Password Connect health
kubectl exec -n external-secrets deployment/onepassword-connect -c connect-api -- \
  wget -qO- http://localhost:8080/health
```

## Documentation

### Created Documentation

| File                                             | Purpose                                            |
| ------------------------------------------------ | -------------------------------------------------- |
| `infrastructure/base/external-secrets/README.md` | Complete setup guide, architecture, usage examples |
| `infrastructure/base/external-secrets/STATUS.md` | Current deployment status, checklist               |
| `scripts/setup-1password-connect.sh`             | Interactive setup script                           |

### CLAUDE.md Updates

Added ESO to documentation table:

```markdown
| `infrastructure/base/external-secrets/README.md` | External Secrets Operator setup - 1Password integration, usage examples |
```

## Next Steps

1. **Complete Flux bootstrap** (prerequisite)
   - Push repo to GitHub
   - Run `./bootstrap/flux/bootstrap.sh`

2. **Obtain 1Password credentials**
   - Create Connect Server at 1Password dashboard
   - Download credentials file
   - Generate API token

3. **Deploy ESO**
   - Run setup script
   - Update vault ID
   - Enable components in kustomization
   - Trigger Flux reconciliation

4. **Migrate existing secrets**
   - Identify manually managed secrets
   - Create items in 1Password
   - Create ExternalSecret resources
   - Validate and test

5. **Create ExternalSecrets for applications**
   - Start with non-critical apps
   - Test thoroughly
   - Roll out to production apps

## Decisions Made

### Why 1Password Connect?

- ✅ Team already uses 1Password
- ✅ Secure vault access without storing passwords in Git
- ✅ Audit trail in 1Password
- ✅ Easy rotation (change in 1Password, auto-syncs)

### Why External Secrets Operator vs Sealed Secrets?

- ✅ ESO supports multiple backends (1Password, Vault, AWS Secrets Manager)
- ✅ No encryption/decryption in Git (secrets stay in 1Password)
- ✅ Better for team workflows (non-technical users can update in 1Password)
- ❌ Sealed Secrets requires encrypting secrets before committing

### Why FluxCD for ESO?

- ✅ ESO is infrastructure, not application
- ✅ Consistent with monitoring/observability stack
- ✅ Automatic reconciliation
- ✅ Clear separation: Flux = infra, ArgoCD = apps

## Issues Encountered

### Issue: Vault ID Placeholder

**Problem:** Default vault ID set to `1` in SecretStore manifests
**Impact:** SecretStore won't be ready without actual vault ID
**Resolution:** Added to deployment checklist, documented in README.md

### Issue: Initial Secrets Required

**Problem:** 1Password Connect needs manual secret creation before deployment
**Impact:** Cannot deploy via pure GitOps initially
**Resolution:** Created interactive setup script, documented in README.md

### Issue: Components Disabled by Default

**Problem:** 1Password Connect and SecretStores commented out in kustomization
**Impact:** ESO operator deploys but cannot sync secrets
**Resolution:** Intentional design - prevents errors before credentials are configured

## Related Work

### Scripts Not Migrated

Decision made **NOT** to convert orchestration scripts to Tilt or Ansible:

- **Tilt:** For application development in separate dev monorepo (catalyst-ui, etc.)
- **Ansible:** For host/VM provisioning (catalyst/@machines already does this)
- **This repo:** Flux handles infrastructure deployment, scripts for bootstrap only

### Scripts Categorization

**Keep (Bootstrap/One-Time):**

- `provision.sh`
- `bootstrap-argocd.sh`
- `bootstrap-flux.sh`
- `setup-1password-connect.sh`
- `kubeconfig-merge.sh`

**Deprecated (Replaced by Flux):**

- `deploy-stack.sh`
- `deploy-observability.sh`

## Testing Plan

### Unit Testing

- ✅ Kustomize builds validated (`kustomize build` succeeds)
- ⏳ Secret creation testing (pending deployment)
- ⏳ ExternalSecret sync testing (pending deployment)

### Integration Testing

1. Deploy ESO operator
2. Deploy 1Password Connect with test credentials
3. Create test ExternalSecret
4. Verify Kubernetes Secret created
5. Verify secret values correct
6. Test refresh on 1Password update

### Production Readiness

- [ ] Metrics integration with Prometheus
- [ ] Grafana dashboard configured
- [ ] Alert rules for sync failures
- [ ] Backup strategy for 1Password credentials
- [ ] Disaster recovery runbook

## References

- [External Secrets Operator Docs](https://external-secrets.io/)
- [1Password Connect](https://developer.1password.com/docs/connect/)
- [ESO 1Password Provider](https://external-secrets.io/latest/provider/1password-sdk/)
- [FluxCD Secrets Management](https://fluxcd.io/flux/security/secrets-management/)

## Commit Message

```
feat: Add External Secrets Operator with 1Password integration

Implement External Secrets Operator (ESO) managed by FluxCD for secure
secrets management using 1Password Connect.

Components:
- ESO operator (Helm v0.11.x) with Prometheus metrics
- 1Password Connect Server (v1.7.3) - API + Sync containers
- ClusterSecretStore and SecretStore configurations
- Interactive setup script for credentials

Documentation:
- Complete README with architecture, setup, usage examples
- STATUS.md tracking deployment progress
- Updated CLAUDE.md with ESO documentation reference

Deployment:
- Managed by FluxCD (infrastructure layer)
- Components disabled by default (requires manual credential setup)
- Run ./scripts/setup-1password-connect.sh to configure

Awaiting:
- Flux bootstrap completion
- 1Password Connect credentials

Refs: TODO.md (External Secrets management)
```

## Session Artifacts

### Files Created

```
infrastructure/base/external-secrets/
├── namespace.yaml
├── operator/{helmrepository,helmrelease,kustomization}.yaml
├── onepassword-connect/{deployment,service,kustomization}.yaml
├── secretstores/{onepassword-secretstore,example-externalsecret,kustomization}.yaml
├── kustomization.yaml
├── README.md
└── STATUS.md

scripts/setup-1password-connect.sh
docs/06-project-management/implementation-sessions/2025-11-22-external-secrets-operator.md (this file)
```

### Files Modified

```
CLAUDE.md (added ESO documentation reference)
```

### Files Removed

```
Tiltfile (removed - Tilt for dev monorepo, not infrastructure)
.tiltignore
tilt_modules/
docs/03-operations/tilt-development.md
```

## Lessons Learned

1. **Tool selection matters:** Almost went down Tilt path before clarifying use case
2. **GitOps layers:** Clear separation between Flux (infra) and ArgoCD (apps)
3. **Bootstrap vs runtime:** Some operations must be manual (1Password credentials)
4. **Documentation is critical:** Future Claude instances need context
