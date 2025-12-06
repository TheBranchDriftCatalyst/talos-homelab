# ArgoCD

## TL;DR

ArgoCD provides GitOps continuous delivery for applications in this cluster.

- **Access:** http://argocd.talos00
- **Credentials:** `kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d`
- **Role:** Manages application deployments (not infrastructure - see [Dual GitOps Pattern](../../../docs/02-architecture/dual-gitops.md))
- **Philosophy:** Push to `main` = automatic deployment

---

## Quick Reference

### Access ArgoCD

```bash
# Get admin password
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d && echo

# Login via CLI
argocd login argocd.talos00

# Change admin password
argocd account update-password
```

### Common Commands

```bash
# List applications
argocd app list

# Check application status
argocd app get <app-name>

# Sync application manually
argocd app sync <app-name>

# View application in terminal
argocd app get <app-name> --refresh
```

### Port-Forward (Alternative Access)

```bash
kubectl port-forward svc/argocd-server -n argocd 8080:443
# Access: https://localhost:8080
```

---

## Applications Managed

ArgoCD applications are defined in `applications/` directory:

| Application        | Repository                                        | Path | Auto-Sync |
| ------------------ | ------------------------------------------------- | ---- | --------- |
| `catalyst-ui`      | github.com/TheBranchDriftCatalyst/catalyst-ui.git | k8s/ | ✅        |
| `arr-stack-private`| Private media stack repository                    | k8s/ | ✅        |
| `kasa-exporter`    | github.com/TheBranchDriftCatalyst/kasa-exporter   | k8s/ | ✅        |

### Creating New Applications

```bash
# Apply application manifest
kubectl apply -f infrastructure/base/argocd/applications/my-app.yaml

# Or via ArgoCD CLI
argocd app create my-app \
  --repo https://github.com/user/repo.git \
  --path k8s \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace my-namespace \
  --sync-policy automated
```

**Application Manifest Template:**

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
      prune: true       # Remove resources not in Git
      selfHeal: true    # Auto-sync on drift detection
    syncOptions:
      - CreateNamespace=true
```

---

## Troubleshooting

### Application Not Syncing

```bash
# Check application status and health
kubectl get application -n argocd <app-name>
kubectl describe application -n argocd <app-name>

# View ArgoCD controller logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller

# Force manual sync
argocd app sync <app-name> --force

# Or via kubectl patch
kubectl patch application -n argocd <app-name> \
  --type merge -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}'
```

### Web UI Not Accessible

```bash
# Check ArgoCD server pod
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-server

# Check IngressRoute
kubectl get ingressroute -n argocd

# View server logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-server

# Test direct access via port-forward
kubectl port-forward svc/argocd-server -n argocd 8080:443
```

### Repository Connection Issues

```bash
# List configured repositories
argocd repo list

# Test repository connectivity
argocd repo add https://github.com/user/repo.git --username <user> --password <token>

# Check repository credentials (secrets)
kubectl get secret -n argocd -l argocd.argoproj.io/secret-type=repository

# View repository connection errors
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server
```

### Image Pull Failures

```bash
# Check if image exists in registry
docker pull <image:tag>

# Verify registry credentials secret
kubectl get secret -n <namespace> <registry-secret>

# Check pod events for pull errors
kubectl describe pod -n <namespace> <pod-name> | grep -A 10 Events
```

### Common Issues

| Issue | Symptom | Solution |
|-------|---------|----------|
| **Sync fails** | "OutOfSync" status persists | Check repo credentials, verify manifests are valid |
| **Image pull error** | Pod stuck in `ImagePullBackOff` | Verify image exists, check registry credentials |
| **503 UI error** | ArgoCD UI unreachable | Check `argocd-server` pod, verify IngressRoute |
| **Slow sync** | Application takes >5min to sync | Check `argocd-application-controller` resources |

---

## Deep Dive

→ See [STATUS.md](STATUS.md) for comprehensive status, configuration details, and known issues.

**STATUS.md includes:**
- Current deployment status and health metrics
- Detailed component breakdown
- Configuration files and structure
- Known issues and TODOs
- Performance metrics
- Best practices and maintenance procedures

---

## Related Documentation

- **[Dual GitOps Pattern](../../../docs/02-architecture/dual-gitops.md)** - Critical: Understand ArgoCD vs Flux roles
- **[Catalyst UI Deployment Guide](../../../docs/catalyst-ui-deployment.md)** - Example application deployment
- **[ArgoCD Official Docs](https://argo-cd.readthedocs.io/)** - Upstream documentation

---

## Related Issues

- **[CILIUM-cih]** - Restructured with progressive summarization (2025-12-06)
