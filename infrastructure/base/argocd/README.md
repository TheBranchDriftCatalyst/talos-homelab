# ArgoCD

## TL;DR

ArgoCD provides GitOps continuous delivery for applications in this cluster.

- **Access:** https://argocd.talos00 (plain HTTP 301-redirects to HTTPS; Traefik terminates TLS with the `*.talos00` homelab-CA cert, `argocd-server` itself runs `--insecure`)
- **Credentials:** `admin` / password lives in 1Password (`default-service-admin`) and is synced into `argocd-secret` by ESO. There is **no** `argocd-initial-admin-secret` — the chart sets `configs.secret.createSecret: false`.
- **Role:** Manages application deployments (not infrastructure - see [Dual GitOps Pattern](../../../docs/02-architecture/dual-gitops.md))
- **Philosophy:** Push to `main` = automatic deployment

---

## Quick Reference

### Access ArgoCD

```bash
# The admin password is NOT in the cluster in plaintext. It lives in 1Password
# ("default-service-admin") and ESO syncs the bcrypt hash into argocd-secret via
# admin-credentials-externalsecret.yaml. Verify the sync, then read the password
# from 1Password:
kubectl -n argocd get externalsecret argocd-admin-credentials

# Login via CLI (cert is signed by the internal homelab-ca — add --insecure if
# your machine does not trust that CA)
argocd login argocd.talos00

# Change admin password: edit the "default-service-admin" item in 1Password
# (both the `password` and `password-bcrypt` fields). `argocd account
# update-password` is reverted by the ExternalSecret within refreshInterval (1h).
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
# argocd-server runs with --insecure, so BOTH service ports (80 and 443) point at
# the plain-HTTP container port 8080 — use http:// regardless of which you forward.
kubectl port-forward svc/argocd-server -n argocd 8080:80
# Access: http://localhost:8080
```

---

## Applications Managed

ArgoCD applications are defined in the `applications/` directory and applied by **Flux**
(the `argocd` Flux Kustomization reconciles `./infrastructure/base/argocd`).

| Application         | Repository                                              | Path                                 | Namespace         | Auto-Sync |
| ------------------- | ------------------------------------------------------- | ------------------------------------ | ----------------- | --------- |
| `arr-stack-private` | `git@github.com:TheBranchDriftCatalyst/talos-private`   | `.`                                  | `media`           | ✅        |
| `boomtime`          | github.com/TheBranchDriftCatalyst/boomtime              | `k8s/overlays/talos00-knowledgedump` | `boomtime`        | ✅        |
| `catalyst-data`     | github.com/TheBranchDriftCatalyst/catalyst-data         | `k8s`                                | `catalyst-data`   | ✅        |
| `catalyst-llm`      | github.com/TheBranchDriftCatalyst/catalyst-llm          | `k8s/talos00`                        | `catalyst-llm`    | ✅        |
| `catalyst-ui`       | github.com/TheBranchDriftCatalyst/catalyst-ui           | `k8s`                                | `catalyst`        | ✅        |
| `dungeon-library`   | `git@github.com:TheBranchDriftCatalyst/dungeon-library` | `k8s`                                | `dungeon-library` | ✅        |
| `kasa-exporter`     | github.com/TheBranchDriftCatalyst/kasa-exporter         | `k8s`                                | `monitoring`      | ✅        |
| `openscad`          | github.com/TheBranchDriftCatalyst/openscad              | `k8s/overlays/talos00`               | `openscad`        | ✅        |

All eight use `syncPolicy.automated` with `prune: true` and `selfHeal: true`.

> `immich-video-faces` was removed from `applications/kustomization.yaml` on 2026-08-14 —
> its source repo was deleted from GitHub and the Application tracked zero resources.

**Image updates:** `catalyst-ui`, `catalyst-data` and `boomtime` are updated by ArgoCD Image
Updater via `ImageUpdater` CRs in `image-updater/`; `dungeon-library` and `kasa-exporter`
still use the legacy `argocd-image-updater.argoproj.io/*` annotations on the Application.

### Creating New Applications

Application manifests are Flux-managed. Add the file to git — do **not** `kubectl apply`
or `argocd app create` by hand; Flux reconciles `infrastructure/base/argocd` and will
revert or orphan anything created out-of-band.

```bash
# 1. Create infrastructure/base/argocd/applications/my-app.yaml (template below)
# 2. Add it to infrastructure/base/argocd/applications/kustomization.yaml
# 3. Commit + push to main — Flux applies it

# Optional: pull the new revision immediately instead of waiting for the interval
flux reconcile kustomization argocd --with-source

# Verify
kubectl get application -n argocd my-app
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
      prune: true # Remove resources not in Git
      selfHeal: true # Auto-sync on drift detection
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

# Test direct access via port-forward (plain HTTP — server runs --insecure)
kubectl port-forward svc/argocd-server -n argocd 8080:80
```

### Repository Connection Issues

```bash
# List configured repositories
argocd repo list

# Check repository credentials. These come from 1Password via ESO
# (externalsecret-private-repo.yaml -> secret `private-repo-creds`) and are
# labelled secret-type=repo-creds, NOT secret-type=repository. Adding creds with
# `argocd repo add` creates untracked state — change the 1Password item instead.
kubectl get secret -n argocd -l argocd.argoproj.io/secret-type=repo-creds
kubectl get externalsecret -n argocd

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

| Issue                | Symptom                         | Solution                                           |
| -------------------- | ------------------------------- | -------------------------------------------------- |
| **Sync fails**       | "OutOfSync" status persists     | Check repo credentials, verify manifests are valid |
| **Image pull error** | Pod stuck in `ImagePullBackOff` | Verify image exists, check registry credentials    |
| **503 UI error**     | ArgoCD UI unreachable           | Check `argocd-server` pod, verify IngressRoute     |
| **Slow sync**        | Application takes >5min to sync | Check `argocd-application-controller` resources    |

---

## Deep Dive

→ See [STATUS.md](STATUS.md) for comprehensive status, configuration details, and known issues.

> ⚠️ STATUS.md was last updated 2025-11-11 and its status numbers are stale (it reports
> 1 application and manual sync; the cluster runs 8 auto-synced applications). Treat its
> metrics section as historical until it is refreshed.

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
- **[ArgoCD Setup](../../../docs/04-deployment/argocd-setup.md)** - Bootstrap and application deployment setup
- **[ArgoCD Official Docs](https://argo-cd.readthedocs.io/)** - Upstream documentation

---

## Related Issues

- **[CILIUM-cih]** - Restructured with progressive summarization (2025-12-06)
