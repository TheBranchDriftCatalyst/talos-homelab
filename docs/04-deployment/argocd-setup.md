# ArgoCD Bootstrap

ArgoCD will be deployed via FluxCD for infrastructure-as-code management of applications.

## Installation

ArgoCD will be automatically deployed by Flux once the Flux bootstrap is complete.

## Access ArgoCD UI

1. **Via Traefik IngressRoute**: http://argocd.lab (configure DNS or /etc/hosts)

2. **Get initial admin password**:
```bash
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d && echo
```

Default credentials:
- Username: `admin`
- Password: `admin` (change immediately after first login)

## Change Admin Password

```bash
# Login to ArgoCD CLI
argocd login argocd.lab

# Update password
argocd account update-password
```

## Add Git Repository

```bash
# Add your GitOps repository
argocd repo add https://github.com/<username>/<repo>.git \
  --username <username> \
  --password <token>
```

## Deploy Applications via ArgoCD

Applications are defined in `argocd-apps/` directory:

```bash
# Apply Application definitions
kubectl apply -f argocd-apps/
```

## ArgoCD Application Structure

```
argocd-apps/
├── arr-stack-dev.yaml       # Arr stack in media-dev
├── arr-stack-prod.yaml      # Arr stack in media-prod
├── media-servers-dev.yaml   # Plex + Jellyfin in media-dev
└── media-servers-prod.yaml  # Plex + Jellyfin in media-prod
```

## Verification

```bash
# Check ArgoCD pods
kubectl -n argocd get pods

# List applications
argocd app list

# Check application status
argocd app get <app-name>

# Sync application
argocd app sync <app-name>
```

## Architecture

- **FluxCD** manages infrastructure (storage, networking, monitoring, ArgoCD itself)
- **ArgoCD** manages applications (arr stack, media servers)
- Both watch the same Git repository but different paths
