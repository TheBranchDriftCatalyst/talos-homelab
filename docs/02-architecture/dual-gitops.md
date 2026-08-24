# Dual GitOps Pattern

## TL;DR

- **FluxCD** reconciles **infrastructure** out of this repo (`talos-homelab`); entrypoint is `clusters/catalyst-cluster/`.
- **ArgoCD** reconciles **applications** out of their own repos (catalyst-ui, boomtime, catalyst-llm, …).
- Both are pull-based and continuous. Commit to `main` — do not `kubectl apply` by hand.
- ArgoCD itself is installed by Flux (`clusters/catalyst-cluster/argocd.yaml` -> `infrastructure/base/argocd`), and the ArgoCD `Application` objects live in this repo too.

## Overview

This Talos Kubernetes cluster uses a **dual GitOps pattern** that separates infrastructure management from application deployment. Infrastructure manifests live in this repository and are reconciled by **FluxCD**; application manifests live in each application's own repository and are reconciled by **ArgoCD**.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Talos Kubernetes Cluster                  │
│                                                               │
│  ┌────────────────────────┐    ┌──────────────────────────┐ │
│  │  Infrastructure GitOps  │    │  Application GitOps       │ │
│  │  (FluxCD Pattern)       │    │  (ArgoCD Pattern)         │ │
│  │                         │    │                           │ │
│  │  Repo: talos-homelab   │    │  Repo: catalyst-ui, ...   │ │
│  │  Tool: FluxCD          │    │  Tool: ArgoCD             │ │
│  │  Scope: Platform       │    │  Scope: Applications      │ │
│  └────────────────────────┘    └──────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Pattern 1: Infrastructure GitOps (FluxCD)

### Purpose

Manage the foundational platform infrastructure that the cluster depends on.

### Repository

- **Location**: `/Users/panda/catalyst-devspace/workspace/talos-homelab` (this repo)
- **Remote**: `github.com/TheBranchDriftCatalyst/talos-homelab` (public)
- **Flux source**: `GitRepository/flux-system` -> `ssh://git@github.com/TheBranchDriftCatalyst/talos-homelab`, branch `main`, polled every `1m`

### What It Manages

- Talos machine configurations (`configs/`, gitignored output)
- Core platform services:
  - ArgoCD (GitOps controller for applications)
  - Cilium (CNI), Traefik (ingress, LoadBalancer VIP `192.168.1.251`)
  - Zot container registry (`registry.talos00`)
  - Monitoring/observability: Mimir (metrics), Loki (logs), Tempo (traces), Grafana, Alloy, ClickStack/HyperDX
  - Authentik (SSO), CrowdSec (IPS/AppSec), cert-manager, External Secrets Operator, Kyverno, reflector, CNPG
- In-repo application workloads under `applications/` (arr stack, homepage, tdarr, metube, …) — also Flux-managed
- Network policies and storage classes
- Cluster bootstrap and recovery scripts

### Deployment Method

**Continuous pull-based reconciliation by Flux**

Flux watches `main` and applies the `Kustomization` objects declared in `clusters/catalyst-cluster/`. There is no deploy script in the normal path — commit and push, or force a reconcile:

```bash
# See what Flux is doing
task flux-status

# Force a re-reconcile, fetching the new commit first
flux reconcile source git flux-system
flux reconcile kustomization <name> --with-source
```

> `./scripts/deploy-stack.sh` no longer exists at that path. It was moved to
> `infrastructure/_scripts/deploy-stack.sh` and is **legacy** — it predates Flux and is not part of
> the reconciliation path. The `infra:deploy-stack` task that invoked it has been removed, along
> with the other `deploy-*` tasks that would have `kubectl apply`-ed over Flux.

### File Structure

```
talos-homelab/
├── clusters/
│   └── catalyst-cluster/  # Flux entrypoint: one Kustomization per component
│       ├── flux-system/   # Flux controllers + GitRepository source
│       ├── argocd.yaml    # -> ./infrastructure/base/argocd
│       ├── traefik.yaml   # -> ./infrastructure/base/traefik
│       └── ...            # ~60 Kustomizations total
├── infrastructure/
│   ├── base/              # Platform manifests (argocd, cilium, traefik,
│   │                      #   registry/zot, monitoring/v2-otel, kyverno, ...)
│   └── _scripts/          # Legacy pre-Flux scripts (not in the normal path)
├── applications/          # In-repo app workloads, also Flux-managed
├── bootstrap/flux/        # One-time Flux bootstrap
├── scripts/               # Provisioning / operational automation
└── docs/                  # Documentation
```

Note: there is **no** `infrastructure/overlays/` directory. Per-environment variation, where it
exists, lives in per-application `overlays/` dirs under `applications/`.

### Update Workflow

1. Modify infrastructure manifests in this repo
2. Commit and push to `main`
3. Flux fetches the new commit (source poll interval `1m`) and reconciles the affected `Kustomization`s
4. Optionally force it: `flux reconcile kustomization <name> --with-source`

### Philosophy

Infrastructure changes are **intentional and controlled** — the gate is code review and the commit
itself, not a manual script run. Because Flux prunes and self-heals, the Git tree is the definition
of the platform: anything applied by hand is transient and will be reverted.

## Pattern 2: Application GitOps (ArgoCD)

### Purpose

Continuously deploy and synchronize application workloads with minimal manual intervention.

### Repository

- **Location**: Application-specific repos (e.g., `catalyst-ui`, `boomtime`, `catalyst-llm`)
- **Remote**: GitHub (public over HTTPS, private over SSH deploy key — e.g. `talos-private`, `dungeon-library`)

Currently registered ArgoCD `Application`s: `catalyst-ui`, `catalyst-llm`, `catalyst-data`,
`boomtime`, `dungeon-library`, `kasa-exporter`, `openscad`, `arr-stack-private`.

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
4. ArgoCD syncs new state to cluster (poll interval `timeout.reconciliation: 120s` in `argocd-cm`)
5. Rolling update occurs automatically

Image tags are bumped separately by **argocd-image-updater**, driven by `ImageUpdater` CRs in
`infrastructure/base/argocd/image-updater/` (catalyst-ui, catalyst-data, boomtime).

### ArgoCD Application Definition

Stored in this repo at `infrastructure/base/argocd/applications/` and applied by the Flux
`argocd` Kustomization — so adding an app is a commit, not a `kubectl apply`.

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
- **Application repos** manage workloads that have their own source repo and build
- Never put platform manifests in an application repo

> Reality check: this repo *does* carry app workloads under `applications/` (arr stack, homepage,
> tdarr, metube, zipline, …). Those are third-party images with no upstream source repo of ours,
> so they are Flux-managed here. The dividing line in practice is **"do we build it?"** — if we
> build the image, the manifests live with the code and ArgoCD owns it; if we only deploy someone
> else's image, Flux owns it from this repo.

### Rule 2: Infrastructure Changes Go Through Flux

- Infrastructure deployments happen when a commit lands on `main` — Flux reconciles it
- Never `kubectl apply` platform manifests; Flux prunes and self-heals over manual changes
- Always review changes before merging
- Document breaking changes in commit messages

### Rule 3: Application Changes Are Automated

- Application deployments are fully automated via ArgoCD
- Push to `main` branch triggers deployment
- No manual intervention required for application updates
- ArgoCD handles rollout strategy and health checks

### Rule 4: Single Source of Truth

- Git is the source of truth for both patterns
- **Infrastructure**: this repo (`talos-homelab`), reconciled by Flux
- **Applications**: respective application repos, reconciled by ArgoCD
- Manual `kubectl` changes are discouraged (emergency only) and will be reverted by both controllers

### Rule 5: Repository Structure

**Infrastructure Repository:**

- Contains platform manifests (`infrastructure/base/`)
- Contains the Flux cluster entrypoint (`clusters/catalyst-cluster/`)
- Contains cluster configuration and operational scripts
- Contains ArgoCD Application definitions

**Application Repositories:**

- Contains application code
- Contains `k8s/` directory with manifests
- Contains Dockerfile
- Does NOT contain infrastructure configs

### Rule 6: Namespace Ownership

- Infrastructure namespaces: created by Flux
  - `argocd`, `traefik`, `registry`, `monitoring`, `flux-system`, `cert-manager`,
    `external-secrets`, `authentik`, `kyverno`, `minio`, `databases`, …
  - Shared/app namespaces declared centrally in `infrastructure/base/namespaces/`
    (`media`, `media-experimental`, `homepage`, `tdarr`, `scratch`, `forgejo`, …)
- Application namespaces: created by ArgoCD Applications via `CreateNamespace=true`
  - `catalyst`, `catalyst-llm`, `catalyst-data`, `boomtime`, `dungeon-library`, `openscad`

> Note: `media` is a Flux-created namespace even though the private arr-stack ArgoCD Application
> also deploys into it (`CreateNamespace=false`); same for `kasa-exporter` into `monitoring`.
> Namespace *creation* is Flux's; workloads inside can come from either side.
> The `observability` namespace still exists but is **empty** — Graylog/OpenSearch/Fluent Bit were
> removed when logging moved to Loki/ClickStack.

### Rule 7: Image Management

- Infrastructure images: public registries (quay.io, ghcr.io, docker.io)
- Application images: **ghcr.io** for anything built in CI (catalyst-ui, catalyst-data, boomtime);
  the in-cluster **Zot** registry at `registry.talos00` is for locally built / not-published images
  (poisonarr, crossplane-demo flex + plausible exporter)
- Build and push application images before ArgoCD deployment
- Tag images with git commit hash for traceability

> `registry.talos00` is served by **Zot** (`infrastructure/base/registry/zot/`), not Nexus. Some
> manifests and secret names still say `nexus-*` from the pre-Zot era.

## Deployment Workflows

### Adding New Infrastructure Component

```bash
# 1. Create manifests in this repo
mkdir -p infrastructure/base/new-component
vim infrastructure/base/new-component/kustomization.yaml
vim infrastructure/base/new-component/deployment.yaml

# 2. Register it as a Flux Kustomization
vim clusters/catalyst-cluster/new-component.yaml   # path: ./infrastructure/base/new-component
                                                   # add dependsOn: as needed

# 3. Commit and push
git add infrastructure/base/new-component clusters/catalyst-cluster/new-component.yaml
git commit -m "feat: Add new infrastructure component"
git push

# 4. Flux reconciles it (or force it)
flux reconcile kustomization new-component --with-source
```

> Several fields are **derived by Kyverno ClusterPolicies** and should not be hand-written:
> homepage annotations (`href`/`widget.url`/`instance`), `tls: {}` on `websecure` IngressRoutes,
> the CNPG `velero.io/exclude-from-backup` label, HelmRelease `remediation.retries`, and the
> Authentik OIDC hostAlias (opt in with label `catalyst.io/oidc=true`). See
> `infrastructure/base/kyverno-policies/`.

### Adding New Application

```bash
# 1. Create k8s manifests in application repo
cd ~/path/to/app-repo
mkdir k8s
vim k8s/deployment.yaml
vim k8s/service.yaml
vim k8s/ingressroute.yaml
vim k8s/kustomization.yaml

# 2. Create ArgoCD Application in this repo
cd ~/catalyst-devspace/workspace/talos-homelab
vim infrastructure/base/argocd/applications/my-app.yaml
# ...and add it to infrastructure/base/argocd/applications/kustomization.yaml

# 3. Commit + push — Flux applies the Application object
git add infrastructure/base/argocd/applications && git commit -m "feat: add my-app" && git push

# 4. ArgoCD automatically syncs from app repo
# Push commits to app repo main branch for updates
```

### Emergency Manual Override

```bash
# Only for emergencies - GitOps will revert manual changes!
kubectl edit deployment -n <namespace> <name>

# To stop a Flux Kustomization from fighting you while you debug:
flux suspend kustomization <name>
# ...and ALWAYS resume it before the end of the session:
flux resume kustomization <name>

# Proper fix: Update Git repo and let GitOps reconcile
```

## Benefits of Dual GitOps

### Infrastructure Side

- **Controlled Changes**: Platform stability through reviewed commits + ordered reconciliation (`dependsOn`)
- **Audit Trail**: Every infrastructure change tracked in Git
- **Recovery**: Easy cluster rebuild from infrastructure repo — `flux bootstrap` and the tree replays
- **Testing**: Test infrastructure changes in isolation

### Application Side

- **Rapid Iteration**: Push code, automatic deployment
- **Rollback**: Git revert = automatic rollback
- **Consistency**: Same deployment process for all apps
- **Developer Experience**: Developers don't need kubectl access

### Combined Benefits

- **Clear Boundaries**: Infrastructure vs. application changes
- **Scalability**: Adding an application is one `Application` manifest here plus a `k8s/` dir there —
  no platform surgery
- **Security**: Applications can't modify platform
- **GitOps Best Practices**: Declarative, versioned, automated

## Monitoring and Observability

### ArgoCD Dashboard

- **URL**: https://argocd.talos00 (Traefik terminates TLS; plain `http://` 301-redirects to HTTPS)
- **Purpose**: Monitor application sync status
- **Access**: ArgoCD authenticates its own UI/API/CLI — deliberately **not** behind Authentik
  forward-auth (that would double-auth and break the CLI). The admin password is **not** the
  chart-generated `argocd-initial-admin-secret` (that secret does not exist here); `argocd-secret`
  is built by the `argocd-admin-credentials` ExternalSecret from the 1Password
  `default-service-admin` item.

### Infrastructure Monitoring

```bash
# Flux: sources + kustomizations + helmreleases
task flux-status
flux get all -A

# Check infrastructure stack status
kubectl get pods -n argocd
kubectl get pods -n traefik
kubectl get pods -n monitoring

# Check application status via ArgoCD
kubectl get applications -n argocd
```

Flux reconciliation failures are also pushed to Discord by the `flux-notifications`
`Provider`/`Alert` pair in `flux-system`.

## Best Practices

### For Infrastructure

1. Dry-run before pushing: `kubectl kustomize infrastructure/base/<component>` and
   `kubectl apply -k <path> --dry-run=client`
2. Use semantic commit messages (`feat:`, `fix:`, `chore:`)
3. Document breaking changes in commit body
4. Wire `dependsOn:` in the Flux Kustomization so CRDs land before consumers
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
# Is Flux even seeing the commit? (a stale source is the #1 cause)
flux get sources git flux-system
flux reconcile source git flux-system

# Why is the Kustomization unhappy?
flux get kustomizations -A
kubectl describe kustomization <name> -n flux-system

# Check if manifests are valid before pushing
kubectl kustomize infrastructure/base/<component>
kubectl apply -k infrastructure/base/<component>/ --dry-run=client

# Controller-level errors
kubectl logs -n flux-system deploy/kustomize-controller
kubectl logs -n flux-system deploy/helm-controller
```

> Gotcha: `flux reconcile kustomization <name>` on its own re-applies the **already-fetched**
> revision. Use `--with-source`, or `flux reconcile source git flux-system` first, or you will
> verify stale state.

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

**This is expected behavior!** Both controllers revert drift — ArgoCD via `selfHeal: true` on the
Application, Flux via `prune: true` on the Kustomization.

**Solution**: Update the Git repository instead. If you need breathing room while debugging,
`flux suspend kustomization <name>` (Flux) or disable auto-sync on the Application (ArgoCD), and
remember to re-enable it.

## Enhancements

### Done since this doc was written

- [x] **FluxCD for infrastructure GitOps** — Flux is now the infrastructure controller (~60 Kustomizations)
- [x] **Helm charts for complex applications** — ~40 Flux `HelmRelease`s in-cluster
- [x] **Policy enforcement** — via **Kyverno**, not OPA (`infrastructure/base/kyverno-policies/`)
- [x] **Secrets management** — via **External Secrets Operator + 1Password**, not Sealed Secrets
- [x] **Automatic image updates** — argocd-image-updater (`ImageUpdater` CRs) for ArgoCD apps

### Still open

- [ ] CI/CD pipeline for automatic image builds
- [ ] Multi-environment support (dev/staging/prod)
- [ ] Automated testing before ArgoCD sync
- [ ] Webhook triggers for instant sync (notification-controller has `Provider`/`Alert` for Discord
      outbound, but no inbound `Receiver`)
- [ ] Progressive delivery with Argo Rollouts (not installed — the `rollout-operator` CRDs present
      are Grafana Mimir's, unrelated)
- [ ] Automated disaster recovery testing

## References

- [ArgoCD Documentation](https://argo-cd.readthedocs.io/)
- [FluxCD Documentation](https://fluxcd.io/flux/)
- [GitOps Principles](https://opengitops.dev/)
- [Kustomize Documentation](https://kustomize.io/)
- [Talos Linux Documentation](https://www.talos.dev/)

Related docs in this repo:

- `docs/02-architecture/gitops-responsibilities.md` — responsibility matrix (**stale**: it still
  describes Flux as "not yet deployed")
- `README.md` — deployment section, Flux reconcile commands
- `OBSERVABILITY.md` — the monitoring/logging stack Flux manages

---

**Last Updated**: 2026-08-22 (truth-alignment pass against live cluster)
**Maintained By**: Infrastructure Team

---

## Related Issues

<!-- Beads tracking for this doc -->
