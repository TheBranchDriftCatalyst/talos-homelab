# Deployment

> Parent: [docs/INDEX.md](../INDEX.md)

## Overview

This section covers GitOps deployment strategies and setup procedures for continuous delivery controllers. Both FluxCD and ArgoCD are used in a dual GitOps pattern to manage infrastructure and applications separately.

## Quick Navigation

| Topic                              | Description                                           | When to Read                                      |
| ---------------------------------- | ----------------------------------------------------- | ------------------------------------------------- |
| [flux-setup.md](flux-setup.md)     | FluxCD bootstrap configuration and installation guide | Setting up infrastructure-level GitOps automation |
| [argocd-setup.md](argocd-setup.md) | ArgoCD bootstrap and application deployment setup. **Partly stale** — it describes an `argocd-apps/` directory and `arr-stack-dev`/`media-servers-*` Applications that no longer exist | Setting up application-level GitOps automation    |

## Key Concepts

- **FluxCD**: Reconciles **this** repo (`talos-homelab`) from `clusters/catalyst-cluster/` — platform
  infrastructure under `infrastructure/base/` (storage, networking, monitoring, ArgoCD itself) **and**
  the in-repo app workloads under `applications/` (arr stack, media servers, homepage, tdarr, gaming, …)
- **ArgoCD**: Reconciles first-party application repos — `catalyst-ui`, `boomtime`, `catalyst-llm`,
  `catalyst-data`, `kasa-exporter`, `dungeon-library`, `openscad`, plus the private media stack
  (`talos-private` -> `arr-stack-private`) — with UI visibility
- **Dual GitOps**: Infrastructure and applications are managed by different tools for separation of concerns
- **Bootstrap Process**: FluxCD is bootstrapped first, then it deploys ArgoCD as infrastructure
  (Helm chart `argo-cd`, pinned `>=10.0.0 <11.0.0` / ArgoCD v3.x)
- **Separate Repositories**: The two tools do **not** watch the same repo. Flux watches this repo;
  each ArgoCD `Application` points at that application's own repo. Only the `Application` objects
  themselves live here, in `infrastructure/base/argocd/applications/` — and Flux applies those.

## Common Tasks

### FluxCD Setup

- [Apply Talos kubelet patches](flux-setup.md#prerequisite-apply-talos-kubelet-patches-first) - **Do this first** on a fresh cluster, or storage-dependent workloads fail to mount
- [Install Flux CLI](flux-setup.md#installation) - Install CLI tool via Homebrew or curl
- [Bootstrap FluxCD](flux-setup.md#installation) - Connect Flux to Git repository
- [Verify Flux reconciliation](flux-setup.md#verification) - Check system status and logs
- [Manual Flux installation](flux-setup.md#manual-installation-alternative) - Alternative to bootstrap

### ArgoCD Setup

- [Install ArgoCD](argocd-setup.md#installation) - Deployed by Flux from `infrastructure/base/argocd/` (HelmRelease); nothing to run by hand
- [Access ArgoCD UI](argocd-setup.md#access-argocd-ui) - Login at `argocd.talos00`. Note: `argocd-initial-admin-secret` no longer exists — the admin password comes from 1Password via ESO (`ExternalSecret/argocd-admin-credentials`)
- [Add Git repository](argocd-setup.md#add-git-repository) - Connect ArgoCD to an application repo
- [Deploy applications](argocd-setup.md#deploy-applications-via-argocd) - Add an `Application` to `infrastructure/base/argocd/applications/`; Flux applies it, ArgoCD then syncs the app repo
- [Verify sync status](argocd-setup.md#verification) - Check application sync and health

### GitOps Workflow

- [Understand dual GitOps pattern](../02-architecture/dual-gitops.md) - Architecture and philosophy
- [Infrastructure deployment](../02-architecture/dual-gitops.md#deployment-workflows) - How Flux manages infrastructure
- [Application deployment](../02-architecture/dual-gitops.md#adding-new-application) - How ArgoCD manages apps
- [GitOps responsibilities](../02-architecture/gitops-responsibilities.md) - What each tool manages. **Stale** — it still says Flux is "NOT YET DEPLOYED" and assigns the arr stack / media servers / homepage to ArgoCD; Flux has been running for ~100d and owns those. Treat [dual-gitops.md](../02-architecture/dual-gitops.md) as authoritative

### Troubleshooting

- [Flux reconciliation issues](flux-setup.md#verification) - Check Flux logs and kustomizations
- [ArgoCD sync problems](argocd-setup.md#verification) - Check application status and sync

## Component Documentation

The manifests these guides deploy carry their own docs:

| Path                                                                                       | Covers                                                                  |
| ------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------- |
| [infrastructure/base/argocd/README.md](../../infrastructure/base/argocd/README.md)          | ArgoCD access (HTTPS via Traefik), the 8 Applications, image-updater, ESO-owned admin credentials |
| [infrastructure/base/argocd/STATUS.md](../../infrastructure/base/argocd/STATUS.md)          | ArgoCD rollout status notes                                             |
| [infrastructure/base/external-secrets/README.md](../../infrastructure/base/external-secrets/README.md) | ESO + 1Password Connect — a prerequisite for most Flux-deployed components |
| [infrastructure/base/flux-notifications/README.md](../../infrastructure/base/flux-notifications/README.md) | Flux reconciliation alerts to Discord                       |
| [05-runbooks/cluster-bootstrap.md](../05-runbooks/cluster-bootstrap.md)                     | The end-to-end bootstrap procedure these setup guides slot into          |

---

## Related Issues

<!-- Beads tracking for this section -->

- [CILIUM-kkw] - Initial creation of section README
