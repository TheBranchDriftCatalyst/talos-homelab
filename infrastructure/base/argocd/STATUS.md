# ArgoCD Subsystem Status

**Component:** ArgoCD - GitOps Continuous Delivery
**Owner:** Infrastructure Team
**Last Updated:** 2025-11-11

---

## 📊 Current Status

| Metric                   | Value         | Health          |
| ------------------------ | ------------- | --------------- |
| **Deployment Status**    | ✅ Deployed   | 🟢 Healthy      |
| **Version**              | Latest (Helm) | 🟢 Current      |
| **Uptime**               | >99%          | 🟢 Stable       |
| **Applications Managed** | 8             | 🟢 Active       |
| **Sync Status**          | Manual        | 🟡 Needs Config |

**Health Legend:** 🟢 Healthy | 🟡 Degraded | 🔴 Down | 🔵 Development

---

## 🎯 Purpose

ArgoCD serves as the **Application GitOps controller** in our dual-GitOps architecture:

- **Manages:** Application workloads (not infrastructure)
- **Method:** Automated continuous sync from application repositories
- **Philosophy:** Push to `main` = automatic deployment

See: [docs/02-architecture/dual-gitops.md](../../../docs/02-architecture/dual-gitops.md)

---

## 📦 Deployed Resources

### Namespace

- `argocd` - ArgoCD control plane

### Core Components

- `argocd-server` - Web UI and API server
- `argocd-repo-server` - Git repository connector
- `argocd-application-controller` - Sync reconciliation loop
- `argocd-dex-server` - SSO/OIDC provider (optional)
- `argocd-redis` - Caching layer

### Access

- **URL:** http://argocd.talos00
- **Auth:** admin / (see secret)
- **IngressRoute:** Traefik HTTP

### Applications Defined

| Application   | Repository                                        | Path | Status                  |
| ------------- | ------------------------------------------------- | ---- | ----------------------- |
| `catalyst-ui` | github.com/TheBranchDriftCatalyst/catalyst-ui.git | k8s/ | 🟡 Defined, not syncing |

---

## 🔧 Configuration

### Deployment Method

- **Tool:** Helm (via kubectl apply)
- **Chart:** `argo/argo-cd`
- **Values:** Default + custom patches

### Sync Policy

```yaml
syncPolicy:
  automated:
    prune: true # Remove resources not in Git
    selfHeal: true # Auto-sync on drift detection
```

### Files

```text
infrastructure/base/argocd/
├── STATUS.md (this file)
├── README.md
├── kustomization.yaml
├── namespace.yaml
├── helmrelease.yaml                          # Flux HelmRelease — this IS how ArgoCD is deployed
├── values.yaml                               # NOT referenced by kustomization.yaml or the HelmRelease
├── ingressroute.yaml
├── servicemonitor.yaml
├── netpol-allow-monitoring.yaml
├── dragonfly.yaml                            # Dragonfly cache, replaces the chart's bundled redis
├── admin-credentials-externalsecret.yaml
├── discord-webhook-externalsecret.yaml
├── externalsecret-private-repo.yaml
├── image-updater/                            # ArgoCD Image Updater + per-app update CRs
└── applications/
    ├── kustomization.yaml
    ├── arr-stack-private.yaml
    ├── boomtime.yaml
    ├── catalyst-data.yaml
    ├── catalyst-llm.yaml
    ├── catalyst-ui.yaml
    ├── dungeon-library.yaml
    ├── kasa-exporter.yaml
    └── openscad.yaml
```

---

## ✅ What's Working

- ✅ ArgoCD server accessible via Traefik
- ✅ Web UI functional
- ✅ CLI access configured
- ✅ Application CRDs deployed
- ✅ Repository credentials configured

---

## 🔴 Known Issues

### 1. Catalyst UI Not Syncing

- **Status:** 🔴 Critical
- **Impact:** Application not deploying
- **Cause:** Under investigation (likely repo access or image pull)
- **Workaround:** None yet
- **Fix ETA:** Next sprint

### 2. HTTP Only (No HTTPS)

- **Status:** 🟡 Medium Priority
- **Impact:** Security risk, credentials transmitted in plaintext
- **Cause:** cert-manager not deployed
- **Workaround:** Use on trusted network only
- **Fix ETA:** TBD

### 3. No SSO/OIDC Configured

- **Status:** 🟡 Low Priority
- **Impact:** Single admin account only
- **Cause:** Not configured
- **Workaround:** Share admin password
- **Fix ETA:** Future enhancement

---

## 📋 TODOs

### High Priority

- [ ] Debug catalyst-ui sync failure
- [ ] Verify repository credentials
- [ ] Test manual sync via CLI
- [ ] Add health checks to Application manifest

### Medium Priority

- [ ] Configure HTTPS ingress with cert-manager
- [ ] Set up admin notifications (Slack/Email)
- [ ] Add backup for ArgoCD configs
- [ ] Document application creation workflow

### Low Priority

- [ ] Configure SSO/OIDC (GitHub/GitLab)
- [ ] Add ArgoCD image updater for automatic image tag updates
- [ ] Set up ArgoCD notifications
- [ ] Create custom resource hooks

---

## 🚀 Deployment Commands

### Initial Deployment

```bash
# Deploy ArgoCD via bootstrap script
./scripts/bootstrap-argocd.sh

# Or manually
kubectl apply -k infrastructure/base/argocd/
```

### Access Admin Password

```bash
# Get initial admin password
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d

# Change admin password
argocd account update-password
```

### Create Application

```bash
# Apply application manifest
kubectl apply -f infrastructure/base/argocd/applications/my-app.yaml

# Or via CLI
argocd app create my-app \
  --repo https://github.com/user/repo.git \
  --path k8s \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace my-namespace
```

---

## 🔍 Troubleshooting

### Application Not Syncing

```bash
# Check application status
kubectl get application -n argocd catalyst-ui
kubectl describe application -n argocd catalyst-ui

# Check ArgoCD logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller

# Force sync
kubectl patch application -n argocd catalyst-ui \
  --type merge -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}'
```

### Web UI Not Accessible

```bash
# Check ArgoCD server pod
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-server

# Check IngressRoute
kubectl get ingressroute -n argocd

# Port-forward for direct access
kubectl port-forward svc/argocd-server -n argocd 8080:443
# Access: https://localhost:8080
```

### Repository Connection Issues

```bash
# Test repository connectivity
argocd repo add https://github.com/user/repo.git

# List repositories
argocd repo list

# Check credentials
kubectl get secret -n argocd -l argocd.argoproj.io/secret-type=repository
```

---

## 📊 Metrics & Monitoring

### Prometheus Metrics

- **Endpoint:** `argocd-metrics:8082/metrics`
- **Scraped by:** kube-Prometheus-stack (if configured)

### Key Metrics

- `argocd_app_sync_total` - Application sync count
- `argocd_app_reconcile_count` - Reconciliation loops
- `argocd_cluster_connection_status` - Cluster health
- `argocd_app_health_status` - Application health

### Grafana Dashboard

- **Dashboard ID:** TBD (import from Grafana.com)
- **Access:** http://grafana.talos00

---

## 🔗 Related Documentation

- [Dual GitOps Architecture](../../../docs/02-architecture/dual-gitops.md)
- `scripts/bootstrap-argocd.sh` — the one-time bootstrap; the script is the procedure

---

## 📈 Performance

### Resource Usage (Current)

- CPU: ~100m (low)
- Memory: ~512Mi (acceptable)
- Storage: <1Gi (minimal)

### Scalability

- **Current:** 1 application, 1 cluster
- **Target:** 10+ applications, 1 cluster
- **Max:** 100s of applications, multiple clusters

---

## 🎓 Best Practices

### Application Manifest Structure

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/user/repo.git
    targetRevision: main
    path: k8s
  destination:
    server: https://kubernetes.default.svc
    namespace: my-namespace
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

### Sync Strategies

- **Auto-sync:** For stable applications (recommended)
- **Manual sync:** For critical infrastructure or testing
- **Sync waves:** For ordered deployments

### Repository Structure

```text
app-repo/
├── k8s/                    # Kubernetes manifests
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingressroute.yaml
│   └── kustomization.yaml  # Optional
├── Dockerfile              # Application container
└── README.md
```

---

## 🔄 Maintenance

### Regular Tasks

- **Weekly:** Review application sync status
- **Monthly:** Update ArgoCD version
- **Quarterly:** Audit application definitions

### Backup Strategy

```bash
# Export all applications
kubectl get applications -n argocd -o yaml > argocd-apps-backup.yaml

# Export all AppProjects
kubectl get appprojects -n argocd -o yaml > argocd-projects-backup.yaml
```

---

**Next Review Date:** 2025-11-18
**Status Owner:** Infrastructure Team
