# Authentication Implementation Guide

> **Status:** Planning
> **Priority:** Low
> **Last Updated:** 2024-11-28

This document tracks authentication options for the Talos homelab cluster, including LDAP, auth gateways, and related technologies.

## Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        AUTHENTICATION STACK                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  USER → Browser/App                                                      │
│           │                                                              │
│           ▼                                                              │
│  ┌─────────────────────────────────────────┐                            │
│  │  AUTH GATEWAY (Authentik/Authelia)      │  ← Layer 7 (HTTP)          │
│  │  - SSO for web apps                     │    "Who are you?" via      │
│  │  - OAuth2/OIDC/SAML                     │    browser redirects       │
│  │  - 2FA/MFA                              │                            │
│  │  - Session management                   │                            │
│  └─────────────────┬───────────────────────┘                            │
│                    │ validates against                                   │
│                    ▼                                                     │
│  ┌─────────────────────────────────────────┐                            │
│  │  LDAP (OpenLDAP/LLDAP/AD)               │  ← Directory Service       │
│  │  - User/group database                  │    "Source of truth"       │
│  │  - Hierarchical structure               │    for identities          │
│  │  - Attributes (email, name, etc.)       │                            │
│  └─────────────────────────────────────────┘                            │
│                                                                          │
│  ┌─────────────────────────────────────────┐                            │
│  │  KERBEROS                               │  ← Network Auth Protocol   │
│  │  - Ticket-based (no passwords on wire)  │    Enterprise/Windows      │
│  │  - Mutual authentication                │    environments            │
│  │  - Used by Active Directory             │                            │
│  └─────────────────────────────────────────┘                            │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Technology Comparison

### What Each Does

| Technology | What It Is | Use Case |
|------------|-----------|----------|
| **LDAP** | Directory database protocol | Store users/groups/attributes. Apps query it to validate credentials |
| **Auth Gateway** | HTTP middleware | Intercept web requests, redirect to login, manage sessions, SSO |
| **Kerberos** | Ticket-based auth protocol | Enterprise networks, Windows domains, SSH without passwords |

### How They Relate

- **LDAP + Auth Gateway:** Auth gateway uses LDAP as its user database backend
- **LDAP + Kerberos:** Often used together in Active Directory (AD uses both)
- **Auth Gateway alone:** Can use built-in user storage without LDAP
- **These are NOT mutually exclusive** - they work at different layers

## Authentication Flow (With Auth Gateway)

```
User visits sonarr.talos00
         │
         ▼
    ┌─────────┐
    │ Traefik │ ──► ForwardAuth middleware
    └────┬────┘
         │
         ▼
    ┌──────────┐     "Is this user authenticated?"
    │ Authentik│ ◄── Checks session cookie
    └────┬─────┘
         │ No session? Redirect to login
         ▼
    ┌──────────┐     "Valid credentials?"
    │   LDAP   │ ◄── Authentik checks username/password
    └──────────┘     (optional - can use built-in DB)
         │
         ▼
    User authenticated → Session created → Access granted
```

## Recommendations for This Cluster

### LDAP - Skip for Now

- **Good for:** 10+ users, multiple apps needing shared auth, enterprise compliance
- **Our situation:** Single user homelab → Not needed
- **If wanted later:** Use **LLDAP** (lightweight) instead of OpenLDAP

### Auth Gateway - Recommended

- Protects all `*.talos00` services with one login
- Adds 2FA to everything
- SSO across Sonarr, Radarr, Grafana, ArgoCD, etc.

### Kerberos - Skip

- Designed for Windows Active Directory environments
- Overkill for homelab
- Only useful if integrating with corporate AD

## Recommended Architecture

```
┌────────────────────────────────────────────────────────┐
│                    Target Setup                        │
├────────────────────────────────────────────────────────┤
│                                                        │
│   Traefik ──► Authelia/Authentik ──► Your Apps        │
│              (ForwardAuth)           (Sonarr, etc.)   │
│                    │                                   │
│                    ▼                                   │
│              Built-in user DB  ← Start here!          │
│              (no LDAP needed)                          │
│                                                        │
│   Later, if needed:                                    │
│              LLDAP ← Lightweight LDAP                  │
│                                                        │
└────────────────────────────────────────────────────────┘
```

## Auth Gateway Options

### Authelia vs Authentik

| Feature | Authelia | Authentik |
|---------|----------|-----------|
| Resource usage | ~50MB RAM | ~500MB+ RAM |
| Setup complexity | Simple YAML | Web UI config |
| User storage | File/LDAP | Built-in DB/LDAP |
| OIDC provider | Yes | Yes |
| 2FA | TOTP, WebAuthn | TOTP, WebAuthn, SMS |
| Dependencies | Redis (optional) | PostgreSQL, Redis |
| Best for | Simple homelab | Multiple users, complex flows |

### Recommendation: Start with Authelia

- Lower resource footprint (important for single-node cluster)
- Simple file-based configuration
- Can upgrade to Authentik later if needed

## Implementation Plan

### Phase 1: Authelia with File-Based Users

1. Deploy Authelia to cluster
2. Configure Traefik ForwardAuth middleware
3. Create file-based user database
4. Protect sensitive services (Grafana, ArgoCD, etc.)

### Phase 2: Expand Coverage (Optional)

1. Add 2FA (TOTP)
2. Protect more services
3. Configure per-service access policies

### Phase 3: LLDAP Integration (Optional)

1. Deploy LLDAP if centralized user management needed
2. Configure Authelia to use LLDAP backend
3. Migrate file-based users to LLDAP

## Configuration Examples

### Authelia Basic Config

```yaml
# authelia/configuration.yml
server:
  host: 0.0.0.0
  port: 9091

authentication_backend:
  file:
    path: /config/users_database.yml

access_control:
  default_policy: one_factor
  rules:
    # Public services (no auth)
    - domain: "plex.talos00"
      policy: bypass

    # Protected services
    - domain: "*.talos00"
      policy: one_factor

session:
  name: authelia_session
  domain: talos00
  expiration: 1h
  inactivity: 5m

storage:
  local:
    path: /config/db.sqlite3

notifier:
  filesystem:
    filename: /config/notification.txt
```

### Authelia Users File

```yaml
# authelia/users_database.yml
users:
  admin:
    displayname: "Admin User"
    password: "$argon2id$v=19$m=65536,t=3,p=4$..."  # Generate with authelia hash-password
    email: admin@talos00
    groups:
      - admins
```

### Traefik ForwardAuth Middleware

```yaml
# infrastructure/base/traefik/middleware-authelia.yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: authelia
  namespace: traefik
spec:
  forwardAuth:
    address: http://authelia.auth.svc.cluster.local:9091/api/verify?rd=https://auth.talos00
    trustForwardHeader: true
    authResponseHeaders:
      - Remote-User
      - Remote-Groups
      - Remote-Name
      - Remote-Email
```

### Apply Middleware to IngressRoute

```yaml
# Example: Protect Grafana
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: grafana
  namespace: monitoring
spec:
  entryPoints:
    - web
  routes:
    - match: Host(`grafana.talos00`)
      kind: Rule
      middlewares:
        - name: authelia
          namespace: traefik
      services:
        - name: kube-prometheus-stack-grafana
          port: 80
```

## Services to Protect

### High Priority (Sensitive)

- [ ] ArgoCD (`argocd.talos00`)
- [ ] Grafana (`grafana.talos00`)
- [ ] Prometheus (`prometheus.talos00`)
- [ ] Alertmanager (`alertmanager.talos00`)
- [ ] Graylog (`graylog.talos00`)
- [ ] Headlamp (`headlamp.talos00`)
- [ ] Nexus Registry (`nexus.talos00`)

### Medium Priority (Media Management)

- [ ] Sonarr (`sonarr.talos00`)
- [ ] Radarr (`radarr.talos00`)
- [ ] Prowlarr (`prowlarr.talos00`)
- [ ] Overseerr (`overseerr.talos00`)
- [ ] Tdarr (`tdarr.talos00`)

### Low Priority / Bypass

- [ ] Plex (`plex.talos00`) - Has own auth
- [ ] Jellyfin (`jellyfin.talos00`) - Has own auth
- [ ] Homepage (`homepage.talos00`) - Dashboard only

## Resources

### Documentation

- [Authelia Docs](https://www.authelia.com/docs/)
- [Authentik Docs](https://goauthentik.io/docs/)
- [LLDAP GitHub](https://github.com/lldap/lldap)
- [Traefik ForwardAuth](https://doc.traefik.io/traefik/middlewares/http/forwardauth/)

### Helm Charts

- Authelia: `https://charts.authelia.com`
- Authentik: `https://charts.goauthentik.io`
- LLDAP: Manual deployment or community charts

## Glossary

| Term | Definition |
|------|------------|
| **LDAP** | Lightweight Directory Access Protocol - protocol for accessing directory services |
| **OIDC** | OpenID Connect - authentication layer on top of OAuth 2.0 |
| **SAML** | Security Assertion Markup Language - XML-based auth standard |
| **SSO** | Single Sign-On - one login for multiple services |
| **ForwardAuth** | Traefik middleware that delegates auth to external service |
| **2FA/MFA** | Two-Factor/Multi-Factor Authentication |
| **TOTP** | Time-based One-Time Password (e.g., Google Authenticator) |
| **WebAuthn** | Web Authentication API (hardware keys, biometrics) |

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2024-11-28 | Skip LDAP initially | Single-user homelab, unnecessary complexity |
| 2024-11-28 | Skip Kerberos | Enterprise/Windows focused, not applicable |
| 2024-11-28 | Plan for Authelia | Lightweight, simple config, low resource usage |
| 2024-11-28 | File-based users first | Simplest starting point, can migrate to LLDAP later |
