# Dual GitOps Pattern

## Overview

This Talos Kubernetes cluster uses a **dual GitOps pattern** that separates infrastructure management from application deployment, each with its own Git repository and deployment workflow.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Talos Kubernetes Cluster                  │
│                                                               │
│  ┌────────────────────────┐    ┌──────────────────────────┐ │
│  │  Infrastructure GitOps  │    │  Application GitOps       │ │
│  │  (Bootstrap Pattern)    │    │  (ArgoCD Pattern)         │ │
│  │                         │    │                           │ │
│  │  Repo: talos-fix       │    │  Repo: catalyst-ui        │ │
│  │  Tool: kubectl/scripts │    │  Tool: ArgoCD             │ │
│  │  Scope: Platform       │    │  Scope: Applications      │ │
│  └────────────────────────┘    └──────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Pattern 1: Infrastructure GitOps (Bootstrap)

### Purpose
Manage the foundational platform infrastructure that the cluster depends on.

### Repository
- **Location**: `/Users/panda/talos-fix`
- **Remote**: Private infrastructure repository

### What It Manages
- Talos machine configurations
- Core platform services:
  - ArgoCD (GitOps controller for applications)
  - Traefik (Ingress controller)
  - Docker Registry (Container image storage)
  - Monitoring stack (Prometheus, Grafana, Loki)
  - Observability (OpenSearch, FluentBit)
  - *arr stack (Sonarr, Radarr, etc.)
- Network policies and storage classes
- Cluster bootstrap and recovery scripts

### Deployment Method
**Manual bootstrap with scripted deployment**

```bash
# Infrastructure deployment workflow
./scripts/deploy-stack.sh <stack-name>
```

### File Structure
```
talos-fix/
├── infrastructure/
│   ├── base/              # Base configurations
│   │   ├── argocd/        # ArgoCD installation
│   │   ├── traefik/       # Ingress controller
│   │   ├── registry/      # Docker registry
│   │   └── monitoring/    # Observability stack
│   └── overlays/          # Environment-specific overrides
├── scripts/               # Deployment automation
│   ├── deploy-stack.sh
│   └── bootstrap-cluster.sh
└── docs/                  # Documentation
```

### Update Workflow
1. Modify infrastructure manifests in `talos-fix` repo
2. Commit and push changes
3. Run deployment script: `./scripts/deploy-stack.sh <stack-name>`
4. Script applies changes via `kubectl apply`

### Philosophy
Infrastructure changes are **intentional and controlled**. They require explicit execution because they affect cluster stability and foundational services. This pattern prevents accidental infrastructure changes and provides clear audit trails.

## Pattern 2: Application GitOps (ArgoCD)

### Purpose
Continuously deploy and synchronize application workloads with minimal manual intervention.

### Repository
- **Location**: Application-specific repos (e.g., `catalyst-ui`)
- **Remote**: GitHub (public or private)

### What It Manages
- Application deployments
- Application services and ingress routes
- Application-specific configurations
- Rolling updates and rollbacks

### Deployment Method
**Automated continuous deployment via ArgoCD**

ArgoCD watches application repositories and automatically syncs changes to the cluster.

### File Structure (Example: catalyst-ui)
```
catalyst-ui/
├── k8s/                   # Kubernetes manifests
│   ├── namespace.yaml     # Application namespace
│   ├── deployment.yaml    # Deployment spec
│   ├── service.yaml       # Service definition
│   ├── ingressroute.yaml  # Traefik routing
│   └── kustomization.yaml # Kustomize config
├── Dockerfile             # Container image definition
└── src/                   # Application source code
```

### Update Workflow
1. Modify application code or K8s manifests
2. Commit and push to `main` branch
3. **ArgoCD automatically detects changes**
4. ArgoCD syncs new state to cluster (within ~3 minutes)
5. Rolling update occurs automatically

### ArgoCD Application Definition
Stored in infrastructure repo: `infrastructure/base/argocd/applications/`

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: catalyst-ui
  namespace: argocd
spec:
  source:
    repoURL: https://github.com/TheBranchDriftCatalyst/catalyst-ui.git
    targetRevision: main
    path: k8s
  destination:
    server: https://kubernetes.default.svc
    namespace: catalyst
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

### Philosophy
Application deployments are **continuous and automated**. Developers push code, ArgoCD handles deployment. This enables rapid iteration, GitOps best practices, and clear deployment history.

## Rules and Standards

### Rule 1: Separation of Concerns
- **Infrastructure repos** manage the platform
- **Application repos** manage workloads
- Never mix infrastructure and application manifests in the same repository

### Rule 2: Infrastructure Changes Are Explicit
- Infrastructure deployments require manual script execution
- Use deployment scripts in `scripts/` directory
- Always review changes before deploying
- Document breaking changes in commit messages

### Rule 3: Application Changes Are Automated
- Application deployments are fully automated via ArgoCD
- Push to `main` branch triggers deployment
- No manual intervention required for application updates
- ArgoCD handles rollout strategy and health checks

### Rule 4: Single Source of Truth
- Git is the source of truth for both patterns
- **Infrastructure**: talos-fix repo
- **Applications**: respective application repos
- Manual `kubectl` changes are discouraged (emergency only)

### Rule 5: Repository Structure
**Infrastructure Repository:**
- Contains platform manifests
- Contains deployment scripts
- Contains cluster configuration
- Contains ArgoCD Application definitions

**Application Repositories:**
- Contains application code
- Contains `k8s/` directory with manifests
- Contains Dockerfile
- Does NOT contain infrastructure configs

### Rule 6: Namespace Ownership
- Infrastructure namespace: Managed by infrastructure repo
  - `argocd`, `traefik`, `registry`, `monitoring`, `observability`
- Application namespaces: Managed by ArgoCD Applications
  - `catalyst`, `media`, custom app namespaces

### Rule 7: Image Management
- Infrastructure images: Use public registries (quay.io, ghcr.io, docker.io)
- Application images: Use local cluster registry (`registry.talos00`)
- Build and push application images before ArgoCD deployment
- Tag images with git commit hash for traceability

## Deployment Workflows

### Adding New Infrastructure Component

```bash
# 1. Create manifests in infrastructure repo
mkdir -p infrastructure/base/new-component
vim infrastructure/base/new-component/deployment.yaml

# 2. Create deployment script or update existing
vim scripts/deploy-new-component.sh

# 3. Commit changes
git add infrastructure/base/new-component scripts/
git commit -m "feat: Add new infrastructure component"

# 4. Deploy
./scripts/deploy-new-component.sh
```

### Adding New Application

```bash
# 1. Create k8s manifests in application repo
cd ~/path/to/app-repo
mkdir k8s
vim k8s/deployment.yaml
vim k8s/service.yaml
vim k8s/ingressroute.yaml
vim k8s/kustomization.yaml

# 2. Create ArgoCD Application in infrastructure repo
cd ~/talos-fix
vim infrastructure/base/argocd/applications/my-app.yaml

# 3. Deploy ArgoCD Application
kubectl apply -f infrastructure/base/argocd/applications/my-app.yaml

# 4. ArgoCD automatically syncs from app repo
# Push commits to app repo main branch for updates
```

### Emergency Manual Override

```bash
# Only for emergencies - GitOps will revert manual changes!
kubectl edit deployment -n <namespace> <name>

# Proper fix: Update Git repo and let GitOps reconcile
```

## Benefits of Dual GitOps

### Infrastructure Side
- **Controlled Changes**: Platform stability through explicit deployments
- **Audit Trail**: Every infrastructure change tracked in Git
- **Recovery**: Easy cluster rebuild from infrastructure repo
- **Testing**: Test infrastructure changes in isolation

### Application Side
- **Rapid Iteration**: Push code, automatic deployment
- **Rollback**: Git revert = automatic rollback
- **Consistency**: Same deployment process for all apps
- **Developer Experience**: Developers don't need kubectl access

### Combined Benefits
- **Clear Boundaries**: Infrastructure vs. application changes
- **Scalability**: Add applications without touching infrastructure
- **Security**: Applications can't modify platform
- **GitOps Best Practices**: Declarative, versioned, automated

## Monitoring and Observability

### ArgoCD Dashboard
- **URL**: http://argocd.talos00
- **Purpose**: Monitor application sync status
- **Access**: Admin credentials in cluster secrets

### Infrastructure Monitoring
```bash
# Check infrastructure stack status
kubectl get pods -n argocd
kubectl get pods -n traefik
kubectl get pods -n monitoring

# Check application status via ArgoCD
kubectl get applications -n argocd
```

## Best Practices

### For Infrastructure
1. Always test changes in overlays before base
2. Use semantic commit messages (`feat:`, `fix:`, `chore:`)
3. Document breaking changes in commit body
4. Run deployment scripts from repository root
5. Keep infrastructure minimal - only platform services

### For Applications
1. Keep `k8s/` directory structure consistent
2. Use Kustomize for environment-specific configs
3. Tag container images with git commit hash
4. Include health checks in deployments
5. Set resource requests and limits

### For Both
1. Git is the source of truth - always
2. Review changes before merging to main
3. Use meaningful branch names for features
4. Document complex configurations
5. Keep manifests simple and readable

## Troubleshooting

### Infrastructure Not Applying
```bash
# Check if manifests are valid
kubectl apply --dry-run=client -f infrastructure/base/component/

# Apply manually with verbose output
kubectl apply -f infrastructure/base/component/ -v=8

# Check for resource conflicts
kubectl get all -n <namespace>
```

### ArgoCD Not Syncing Application
```bash
# Check ArgoCD application status
kubectl get application -n argocd <app-name>
kubectl describe application -n argocd <app-name>

# Force sync
kubectl patch application -n argocd <app-name> \
  --type merge -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}'

# Check ArgoCD logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller
```

### Manual Changes Keep Getting Reverted
**This is expected behavior!** ArgoCD will revert manual changes to match Git.

**Solution**: Update the Git repository instead.

## Future Enhancements

### Planned
- [ ] CI/CD pipeline for automatic image builds
- [ ] Multi-environment support (dev/staging/prod)
- [ ] Automated testing before ArgoCD sync
- [ ] Webhook triggers for instant sync
- [ ] Sealed Secrets for sensitive data
- [ ] Progressive delivery with Argo Rollouts

### Under Consideration
- [ ] FluxCD for infrastructure GitOps
- [ ] Helm charts for complex applications
- [ ] OPA policy enforcement
- [ ] Automated disaster recovery testing

## References

- [ArgoCD Documentation](https://argo-cd.readthedocs.io/)
- [GitOps Principles](https://opengitops.dev/)
- [Kustomize Documentation](https://kustomize.io/)
- [Talos Linux Documentation](https://www.talos.dev/)

---

**Last Updated**: 2025-11-12
**Maintained By**: Infrastructure Team
