# Deployment

## Overview

This section covers GitOps deployment strategies and setup procedures for continuous delivery controllers. Both FluxCD and ArgoCD are used in a dual GitOps pattern to manage infrastructure and applications separately.

## Quick Navigation

| Topic                              | Description                                           | When to Read                                      |
| ---------------------------------- | ----------------------------------------------------- | ------------------------------------------------- |
| [flux-setup.md](flux-setup.md)     | FluxCD bootstrap configuration and installation guide | Setting up infrastructure-level GitOps automation |
| [argocd-setup.md](argocd-setup.md) | ArgoCD bootstrap and application deployment setup     | Setting up application-level GitOps automation    |

## Key Concepts

- **FluxCD**: Manages infrastructure components (storage, networking, monitoring, ArgoCD itself) via GitOps
- **ArgoCD**: Manages application workloads (arr stack, media servers) via GitOps with UI visibility
- **Dual GitOps**: Infrastructure and applications are managed by different tools for separation of concerns
- **Bootstrap Process**: FluxCD is bootstrapped first, then it deploys ArgoCD as infrastructure
- **Git Repository**: Both tools watch the same repository but manage different resource paths

## Common Tasks

### FluxCD Setup

- [Install Flux CLI](flux-setup.md#installation) - Install CLI tool via Homebrew or curl
- [Bootstrap FluxCD](flux-setup.md#installation) - Connect Flux to Git repository
- [Verify Flux reconciliation](flux-setup.md#verification) - Check system status and logs
- [Manual Flux installation](flux-setup.md#manual-installation-alternative) - Alternative to bootstrap

### ArgoCD Setup

- [Deploy ArgoCD via Helm](argocd-setup.md#deploy-argocd-via-argocd) - Install ArgoCD in cluster
- [Access ArgoCD UI](argocd-setup.md#access-argocd-ui) - Get admin password and login
- [Add Git repository](argocd-setup.md#add-git-repository) - Connect ArgoCD to GitOps repo
- [Deploy applications](argocd-setup.md#deploy-applications-via-argocd) - Apply Application definitions
- [Verify sync status](argocd-setup.md#verification) - Check application sync and health

### GitOps Workflow

- [Understand dual GitOps pattern](../02-architecture/dual-gitops.md) - Architecture and philosophy
- [Infrastructure deployment](../02-architecture/dual-gitops.md#deployment-workflows) - How Flux manages infrastructure
- [Application deployment](../02-architecture/dual-gitops.md#adding-new-application) - How ArgoCD manages apps
- [GitOps responsibilities](../02-architecture/gitops-responsibilities.md) - What each tool manages

### Troubleshooting

- [Flux reconciliation issues](flux-setup.md#verification) - Check Flux logs and kustomizations
- [ArgoCD sync problems](argocd-setup.md#verification) - Check application status and sync

---

## Related Issues

<!-- Beads tracking for this section -->

- [CILIUM-kkw] - Initial creation of section README
