# Authentication Implementation Guide

> **Status:** Implemented — Authentik
> **Priority:** Low (maintenance; coverage gaps tracked in beads)
> **Last Updated:** 2026-08-22 (re-grounded against repo + live cluster)

This document describes the authentication stack for the Talos homelab cluster: what was
evaluated (LDAP, Kerberos, auth gateways), what was actually built, and how to wire a new
service into it.

## TL;DR

- **Authentik is the auth gateway.** Deployed by Flux from `infrastructure/base/authentik/`,
  namespace `authentik`, Helm chart from `https://charts.goauthentik.io`
  (HelmRelease pins `>=2025.10.0 <2026.0.0`; live: `2025.12.4`).
- **Two integration styles.** Traefik **ForwardAuth** (Middleware `authentik/authentik`) for apps
  with no login of their own, and native **OIDC** for apps that do their own user/role mapping
  (Grafana, Forgejo, MinIO, litellm, Immich, boomtime, ...).
- **No LDAP, no Kerberos.** Authentik's built-in user DB is the directory. There is no
  LLDAP/OpenLDAP anywhere in the repo or the cluster.
- **Authelia was never deployed.** The 2024 plan below called for it; Authentik was built instead.
- **State lives in CNPG + Dragonfly.** Sessions/identities in the `authentik-postgres` CNPG
  cluster (3 instances, `local-path`); cache in the `authentik-cache` Dragonfly (ephemeral).

## Quick Reference

| Thing | Value |
| ----- | ----- |
| Namespace | `authentik` |
| Manifests | `infrastructure/base/authentik/` |
| Portal (LAN) | `http://auth.talos00`, `https://auth.priv.talos00` |
| Portal (public) | `https://auth.knowledgedump.space` (Cloudflare-proxied) |
| ForwardAuth middleware | `name: authentik`, `namespace: authentik` |
| ForwardAuth address | `http://authentik-server.authentik.svc.cluster.local/outpost.goauthentik.io/auth/traefik` |
| Identity DB | CNPG `authentik-postgres` → svc `authentik-postgres-rw:5432` |
| Cache | Dragonfly `authentik-cache:6379` (no auth, cache-only) |
| Secrets | ExternalSecret `authentik-secrets` ← 1Password (`onepassword` ClusterSecretStore) |
| Access groups | `cluster-admin` (superset) + `talos-admin`, `talos-apps`, `talos-gaming`, `talos-home`, `talos-media`, `talos-private` |
| Config as code | Authentik **blueprints** as ConfigMaps, mounted via chart-native `blueprints.configMaps` |

```bash
# Health
kubectl get pods -n authentik
kubectl get helmrelease -n authentik authentik

# Which routes are behind forward-auth?
grep -rn -A2 "middlewares:" --include="*.yaml" infrastructure/ applications/ | grep -B1 "namespace: authentik"
```

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
│  │  AUTH GATEWAY — Authentik  [DEPLOYED]   │  ← Layer 7 (HTTP)          │
│  │  - SSO for web apps                     │    "Who are you?" via      │
│  │  - OAuth2/OIDC + proxy (ForwardAuth)    │    browser redirects       │
│  │  - MFA capable (TOTP/WebAuthn)          │                            │
│  │  - Session management (DB-backed)       │                            │
│  └─────────────────┬───────────────────────┘                            │
│                    │ validates against                                   │
│                    ▼                                                     │
│  ┌─────────────────────────────────────────┐                            │
│  │  Authentik built-in user DB             │  ← Directory Service       │
│  │  (CloudNativePG `authentik-postgres`)   │    "Source of truth"       │
│  │  - Users, groups, policy bindings       │    for identities          │
│  └─────────────────────────────────────────┘                            │
│                                                                          │
│  ┌─────────────────────────────────────────┐                            │
│  │  LDAP (OpenLDAP/LLDAP/AD)   [NOT USED]  │  ← Evaluated, skipped      │
│  │  KERBEROS                   [NOT USED]  │    (see Decisions below)   │
│  └─────────────────────────────────────────┘                            │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Technology Comparison

### What Each Does

| Technology       | What It Is                  | Use Case                                                             |
| ---------------- | --------------------------- | -------------------------------------------------------------------- |
| **LDAP**         | Directory database protocol | Store users/groups/attributes. Apps query it to validate credentials |
| **Auth Gateway** | HTTP middleware             | Intercept web requests, redirect to login, manage sessions, SSO      |
| **Kerberos**     | Ticket-based auth protocol  | Enterprise networks, Windows domains, SSH without passwords          |

### How They Relate

- **LDAP + Auth Gateway:** Auth gateway uses LDAP as its user database backend
- **LDAP + Kerberos:** Often used together in Active Directory (AD uses both)
- **Auth Gateway alone:** Can use built-in user storage without LDAP ← **this is what we do**
- **These are NOT mutually exclusive** - they work at different layers

## Authentication Flow (As Deployed)

```
User visits sonarr.talos00
         │
         ▼
    ┌─────────┐  LoadBalancer VIP 192.168.1.251
    │ Traefik │ ──► Middleware `authentik` (ns authentik) — forwardAuth
    └────┬────┘
         │
         ▼
    ┌───────────────────────────┐  "Is this user authenticated?"
    │ authentik-server          │ ◄── embedded outpost checks session cookie
    │ /outpost.goauthentik.io/  │     at .../auth/traefik
    └────┬──────────────────────┘
         │ No session? 302 to the Authentik login flow
         ▼
    ┌────────────────────────────────┐  "Valid credentials?"
    │ Authentik built-in user DB     │ ◄── CNPG `authentik-postgres`
    │ (+ Dragonfly `authentik-cache`)│     (NO LDAP backend)
    └────┬───────────────────────────┘
         │ PolicyBindings: the app's own group OR cluster-admin
         ▼
    Session created → X-authentik-* headers injected → Access granted
```

Two details that are easy to miss and are load-bearing:

1. **The callback path needs its own route.** Every forward-auth app's
   `/outpost.goauthentik.io/*` must reach `authentik-server`, not the app. That is handled by a
   **single** regexp IngressRoute in `infrastructure/base/authentik/ingressroute.yaml`
   (`HostRegexp(^[a-z0-9.-]+\.talos00$) && PathPrefix(/outpost.goauthentik.io/)`, `priority: 20`,
   no auth middleware). Adding a new forward-auth app requires **no edit** there.
2. **Server-side OIDC callers need the hostAlias.** Pods that make their own OIDC
   discovery/token/JWKS calls to `auth.knowledgedump.space` get blocked by Cloudflare bot
   protection. Label the pod `catalyst.io/oidc: "true"` and the Kyverno ClusterPolicy
   `infrastructure/base/kyverno-policies/oidc-hostalias.yaml` injects a hostAlias pinning that
   hostname to the live Traefik ClusterIP (read at admission via `apiCall`, not hardcoded).

## Decisions for This Cluster

### LDAP — Skipped (still true)

- **Good for:** 10+ users, multiple apps needing shared auth, enterprise compliance
- **Our situation:** small homelab → not needed. Verified 2026-08-22: no LDAP/LLDAP manifests in
  the repo and no LDAP workload in the cluster. Authentik's built-in DB is the directory.
- **If wanted later:** Authentik ships its own **LDAP provider/outpost** — that would be the path,
  rather than standing up LLDAP/OpenLDAP separately.

### Auth Gateway — Implemented (Authentik)

- Protects `*.talos00` / `*.priv.talos00` services with one login
- MFA capable (see the caveat under *Known Gaps*)
- SSO across the *arr stack, Tdarr, Homepage, Headlamp, KubeView, Grafana, Forgejo, MinIO, ...

### Kerberos — Skipped

- Designed for Windows Active Directory environments
- Overkill for homelab
- Only useful if integrating with corporate AD

## Deployed Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                       As Built (2026-08)                         │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│   Traefik ──► Authentik ──► Your Apps                            │
│   (LB VIP     │            (sonarr, tdarr, headlamp, homepage…)  │
│    .1.251)    │                                                  │
│               ├── ForwardAuth (proxy provider, forward_single)   │
│               │   54 providers declared in in-repo blueprints    │
│               │                                                  │
│               └── OIDC (oauth2provider) — 12 providers:          │
│                   grafana, forgejo, minio, zot, litellm,         │
│                   linkwarden, manyfold, immich, boomtime,        │
│                   audiobookshelf, komga, kavita                  │
│                    │                                             │
│                    ▼                                             │
│   Built-in user DB → CNPG `authentik-postgres` (3 instances,     │
│                       local-path NVMe, barman-cloud → MinIO)     │
│   Cache            → Dragonfly `authentik-cache` (ephemeral)     │
│   Secrets          → ExternalSecret ← 1Password                  │
│                                                                  │
│   NOT deployed: LLDAP / OpenLDAP / Kerberos / Authelia           │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

## Auth Gateway Options (2024 evaluation)

### Authelia vs Authentik

| Feature          | Authelia         | Authentik                     |
| ---------------- | ---------------- | ----------------------------- |
| Resource usage   | ~50MB RAM        | ~500MB+ RAM                   |
| Setup complexity | Simple YAML      | Web UI config + blueprints    |
| User storage     | File/LDAP        | Built-in DB/LDAP              |
| OIDC provider    | Yes              | Yes                           |
| 2FA              | TOTP, WebAuthn   | TOTP, WebAuthn, SMS           |
| Dependencies     | Redis (optional) | PostgreSQL, Redis             |
| Best for         | Simple homelab   | Multiple users, complex flows |

### Outcome: Authentik (the 2024 "start with Authelia" call was reversed)

The original recommendation on this page was Authelia, for its footprint. Authentik was deployed
instead and Authelia was never installed. What drove the reversal:

- **Config-as-code turned out fine.** Authentik blueprints (declarative ConfigMaps, mounted via the
  chart's native `blueprints.configMaps`) give the same GitOps story Authelia's YAML would have —
  providers, applications, groups and policy bindings all live in git.
- **A native OIDC provider was needed anyway.** A dozen apps do their own role mapping and want a
  real OAuth2/OIDC IdP, not just a header-injecting gate.
- **Per-app launcher tiles.** `forward_single` providers give each app its own Application and its
  own tile in the Authentik launcher, grouped by access group.
- The dependency cost was absorbed by infrastructure that already existed: CloudNativePG for
  Postgres and the Dragonfly operator for the Redis-compatible cache.

## Implementation Status

### Phase 1 — Gateway + ForwardAuth ✅ Done

1. Authentik deployed to the cluster via Flux HelmRelease
2. Traefik ForwardAuth middleware `authentik/authentik` created
3. Users/groups in Authentik's built-in DB (no file backend, no LDAP)
4. Sensitive infra UIs gated (Headlamp, KubeView, Goldilocks, kube-ops-view, DbGate, CrowdSec, Hubble)

### Phase 2 — Expand Coverage 🔶 In progress

1. Per-app `forward_single` providers + launcher tiles, grouped by access group
2. Consolidated group model: 6 access groups + the `cluster-admin` superset
3. `/api` (and `/feed`) PathPrefix exclusions on apps whose APIs are called by machines —
   e.g. Sonarr/Radarr/Prowlarr `Host(...) && (PathPrefix(/api) || PathPrefix(/feed))` and Seerr
   `PathPrefix(/api)` at `priority: 100`, both with no auth middleware
4. Remaining coverage gaps tracked in **TALOS-xgrl.18**

### Phase 3 — LDAP ❌ Not pursued

Superseded. Centralised user management is handled by Authentik itself; no LLDAP deployment
exists or is planned. Recorded here so the option reads as closed, not forgotten.

## Configuration Examples

These are the **real** manifests in this repo, not illustrative sketches.

### Traefik ForwardAuth Middleware

```yaml
# infrastructure/base/authentik/middleware.yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: authentik
  namespace: authentik
spec:
  forwardAuth:
    address: http://authentik-server.authentik.svc.cluster.local/outpost.goauthentik.io/auth/traefik
    trustForwardHeader: true
    authResponseHeaders:
      - X-authentik-username
      - X-authentik-groups
      - X-authentik-email
      - X-authentik-name
      - X-authentik-uid
      - X-authentik-jwt
      - X-authentik-meta-jwks
      - X-authentik-meta-outpost
      - X-authentik-meta-provider
      - X-authentik-meta-app
      - X-authentik-meta-version
```

### Apply Middleware to an IngressRoute

```yaml
# infrastructure/base/infra-control/headlamp/ingressroute.yaml (abridged)
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: headlamp
  namespace: infra-control
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`headlamp.priv.talos00`)
      kind: Rule
      middlewares:
        - name: authentik
          namespace: authentik
      services:
        - name: headlamp
          port: 80
```

Notes:

- No `tls: {}` here on purpose — the Kyverno ClusterPolicy
  `infrastructure/base/kyverno-policies/ingressroute-tls-default.yaml` adds it to every
  `websecure` IngressRoute (add-if-absent; a hand-set value always wins).
- Likewise the mechanical `gethomepage.dev/href`, `widget.url` and `instance` annotations are
  derived by `homepage-annotation-derivation.yaml` / `homepage-instance-assignment.yaml`.
- Pair every `websecure` route with a `web` route carrying `redirect-https` (ns `traefik`).

### Declaring the App in Authentik (blueprint)

```yaml
# infrastructure/base/authentik/talos-private-blueprint.yaml (abridged)
- model: authentik_providers_proxy.proxyprovider
  id: p-headlamp
  identifiers: {name: headlamp}
  attrs:
    name: headlamp
    mode: forward_single
    external_host: https://headlamp.priv.talos00
    access_token_validity: hours=24
    authorization_flow: !Find [authentik_flows.flow, [slug, default-provider-authorization-implicit-consent]]
    invalidation_flow: !Find [authentik_flows.flow, [slug, default-provider-invalidation-flow]]
- {model: authentik_core.application, id: a-headlamp, identifiers: {slug: headlamp},
   attrs: {name: Headlamp, slug: headlamp, group: talos-admin, provider: !KeyOf p-headlamp,
           policy_engine_mode: any}}
- {model: authentik_policies.policybinding, id: b-headlamp-own,
   identifiers: {target: !KeyOf a-headlamp, group: !KeyOf g-talos-admin, order: 0}, attrs: {enabled: true}}
- {model: authentik_policies.policybinding, id: b-headlamp-ca,
   identifiers: {target: !KeyOf a-headlamp, group: !KeyOf g-cluster-admin, order: 1}, attrs: {enabled: true}}
```

Blueprint ConfigMaps must be listed **twice**: as resources in
`infrastructure/base/authentik/kustomization.yaml`, and by name under
`spec.values.blueprints.configMaps` in `helmrelease.yaml`. There is no label auto-discovery.
The chart mounts them on the **worker** pod (the component that reconciles blueprints).

### Native OIDC Instead of ForwardAuth

Apps with their own user/role model use an `authentik_providers_oauth2.oauth2provider`, and both
ends read the client secret from the same 1Password field. Example: Grafana
(`infrastructure/base/authentik/grafana-blueprint.yaml` plus `auth.generic_oauth` in
`infrastructure/base/monitoring/grafana-instances/grafana-instance.yaml`). Grafana therefore has
**no** `authentik` middleware on its IngressRoute — adding one would cause a double login.

<details>
<summary><b>Historical — Authelia examples (NEVER DEPLOYED, retained for the record)</b></summary>

The following was the 2024-11-28 plan. **None of it exists**: there is no Authelia workload, no
`infrastructure/base/traefik/middleware-authelia.yaml`, and no file-based user database anywhere
in this repo or cluster. Do not use these as a reference for current behaviour.

```yaml
# authelia/configuration.yml  — NOT DEPLOYED
server:
  host: 0.0.0.0
  port: 9091

authentication_backend:
  file:
    path: /config/users_database.yml

access_control:
  default_policy: one_factor
  rules:
    - domain: 'plex.talos00'
      policy: bypass
    - domain: '*.talos00'
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

```yaml
# authelia/users_database.yml — NOT DEPLOYED
users:
  admin:
    displayname: 'Admin User'
    password: '$argon2id$v=19$m=65536,t=3,p=4$...'
    email: admin@talos00
    groups:
      - admins
```

```yaml
# infrastructure/base/traefik/middleware-authelia.yaml — NOT DEPLOYED (file does not exist)
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

</details>

## SSO Coverage

Verified against the repo and the live cluster on 2026-08-22.

### Infra / Sensitive

- [x] Headlamp (`headlamp.priv.talos00`) — ForwardAuth, `talos-admin`
- [x] KubeView (`kubeview.priv.talos00`) — ForwardAuth, `talos-admin`
- [x] Goldilocks, kube-ops-view, DbGate, CrowdSec, Hubble, Plausible — ForwardAuth, `talos-admin`
- [x] Grafana (`grafana.talos00`) — native OIDC (`generic_oauth`), not ForwardAuth
- [x] MinIO, zot (registry), Forgejo, litellm, Linkwarden, Manyfold, boomtime — native OIDC
- [ ] **ArgoCD (`argocd.talos00`)** — still local admin only; `dex.enabled: false` in
      `infrastructure/base/argocd/helmrelease.yaml` and no auth middleware on its IngressRoute.
      Tracked by **TALOS-xgrl.18.1**
- [ ] **Mimir (`mimir.talos00`), Loki (`loki.talos00`), Tempo, HyperDX, Traefik dashboard** —
      no auth middleware on their IngressRoutes. HyperDX tracked by **TALOS-eao7**

> **Removed since this list was first written (2024-11):** Prometheus and Alertmanager no longer
> have their own ingress — metrics moved to **Mimir**, and alerting is the Mimir Alertmanager.
> **Graylog** and **Nexus** are gone: logs are Loki + ClickStack/HyperDX, and the `registry`
> namespace now runs **zot**. Those three checkboxes were dropped from this list rather than
> left as work items.

### Media Management

- [x] Sonarr, Radarr, Prowlarr — ForwardAuth (`talos-media`), with `/api` + `/feed` bypass routes
- [x] Seerr (the Overseerr successor, `seerr.talos00`) — ForwardAuth, with a `/api` bypass route.
      Note: Seerr keeps its own Plex login for per-user request identity, so users see the SSO
      gate *and then* Seerr's sign-in. Expected.
- [x] Tdarr (`tdarr.talos00`) — ForwardAuth; the external-node port 8266 (NodePort 30266) is off
      this HTTP route and is unaffected
- [x] qBittorrent, SABnzbd, Tautulli, Maintainerr, Posterr, Posterizarr, Pulsarr — ForwardAuth
- [x] media-experimental (Bindery, Booksonic, Chaptarr, Libation, Librarr, Livrarr, Mylar3,
      Storyteller) — ForwardAuth
- [x] Audiobookshelf, Komga, Kavita — native OIDC
- [ ] Readarr — gated in the repo (`applications/arr-stack/base/readarr/ingressroute.yaml`) but no
      live IngressRoute exists; the app is not currently deployed
- [ ] Whisparr — `whisparr.priv.talos00` is gated, but the bare `whisparr.talos00` route in the
      `media-private` namespace (owned by the talos-private repo) has **no** auth middleware.
      Part of the vanity-route bypass in **TALOS-xgrl.18.2** / **TALOS-xgrl.14**

### Bypass (own auth)

- [x] Plex (`plex.talos00`) — has own auth, deliberately not gated
- [x] Jellyfin (`jellyfin.talos00`) — has own auth, deliberately not gated
- [x] Homepage (`homepage.talos00` + per-board `*.homepage.talos00`) — **no longer bypass.**
      gethomepage ships with no auth of its own, so it is behind ForwardAuth

### Known Gaps

- **MFA is not IaC.** Authentik supports TOTP/WebAuthn, but no authenticator enrollment or
  validation stage is declared in any in-repo blueprint. Whatever MFA exists was configured in the
  Authentik UI and is not reproducible from git.
- **~36 Homepage-listed apps are not in any SSO group** — TALOS-xgrl.18.
- **`.priv.talos00` vs bare `.talos00`** — two host shapes are in flight; TALOS-xgrl.17 migrates
  the remaining `priv` apps down to the bare label.
- **The identity DB has no verified backup.** `authentik-postgres-backup` has never succeeded —
  TALOS-kmjc.1.

## Resources

### Documentation

- [Authentik Docs](https://goauthentik.io/docs/)
- [Authentik Blueprints](https://docs.goauthentik.io/docs/customize/blueprints/)
- [Traefik ForwardAuth](https://doc.traefik.io/traefik/middlewares/http/forwardauth/)
- [Authelia Docs](https://www.authelia.com/docs/) — reference only; not deployed
- [LLDAP GitHub](https://github.com/lldap/lldap) — reference only; not deployed

### Helm Charts

- Authentik: `https://charts.goauthentik.io` — **in use**
  (`infrastructure/base/authentik/helmrepository.yaml`)
- Authelia: `https://charts.authelia.com` — not used
- LLDAP: not used

## Glossary

| Term                | Definition                                                                        |
| ------------------- | --------------------------------------------------------------------------------- |
| **LDAP**            | Lightweight Directory Access Protocol - protocol for accessing directory services |
| **OIDC**            | OpenID Connect - authentication layer on top of OAuth 2.0                         |
| **SAML**            | Security Assertion Markup Language - XML-based auth standard                      |
| **SSO**             | Single Sign-On - one login for multiple services                                  |
| **ForwardAuth**     | Traefik middleware that delegates auth to external service                        |
| **2FA/MFA**         | Two-Factor/Multi-Factor Authentication                                            |
| **TOTP**            | Time-based One-Time Password (e.g., Google Authenticator)                         |
| **WebAuthn**        | Web Authentication API (hardware keys, biometrics)                                |
| **Outpost**         | Authentik component that terminates proxy/ForwardAuth requests. We use the *embedded* outpost in `authentik-server` |
| **forward_single**  | Proxy-provider mode: one Authentik Application per host → one launcher tile       |
| **forward_domain**  | Proxy-provider mode: one Application covering a whole cookie domain. Retired here in favour of `forward_single` |
| **Blueprint**       | Authentik's declarative config format (YAML), delivered as ConfigMaps             |

## Decision Log

| Date       | Decision                                 | Rationale                                                                 |
| ---------- | ---------------------------------------- | ------------------------------------------------------------------------- |
| 2024-11-28 | Skip LDAP initially                      | Small homelab, unnecessary complexity                                     |
| 2024-11-28 | Skip Kerberos                            | Enterprise/Windows focused, not applicable                                |
| 2024-11-28 | Plan for Authelia                        | Lightweight, simple config, low resource usage — **later reversed**       |
| 2024-11-28 | File-based users first                   | Simplest starting point — **never implemented**                           |
| ~2026-05   | Deploy Authentik instead of Authelia     | Needed a real OIDC provider + per-app launcher tiles; blueprints gave the GitOps story |
| 2026-08-06 | `talos-private` group model (TALOS-h4j)  | Replace the hand-made `kelsboi` setup with fully-IaC groups + forward-auth |
| 2026-08-09 | Authentik Postgres → CNPG (TALOS-fijt)   | Retire the bundled single-replica subchart; 3-instance HA + object backups |
| 2026-08-10 | Redis → Dragonfly (TALOS-5aop)           | Chart 2025.12.x stopped rendering the bundled redis; the cache had silently fallen back to local |
| 2026-08-10 | ONE regexp outpost route (TALOS-xgrl.13) | New forward-auth apps need no per-app `/outpost.goauthentik.io/` edit     |
| 2026-08-10 | Blueprints via `blueprints.configMaps`   | Chart-native mount replaces hand-written volume/volumeMount pairs (TALOS-xgrl.16) |
| 2026-08-21 | `authentik-postgres` on `local-path`     | 20 tx/s (every SSO check writes a session); the NFS fsync round trip was the bottleneck. Safe only at `instances: 3` |

---

## Related Issues

- TALOS-xgrl.18 - Homepage-1:1 SSO coverage (~36 apps not in an SSO group)
- TALOS-xgrl.18.1 - Native OIDC for ArgoCD + Open WebUI
- TALOS-xgrl.18.2 - SSO audit leftovers (mac-node APIs, private vanity-route bypass, sister-repo UIs)
- TALOS-xgrl.17 - Migrate `.priv.talos00` SSO apps down to bare `.talos00`
- TALOS-xgrl.14 - Cut talos-private repo apps over to `priv.talos00` SSO
- TALOS-eao7 - HyperDX behind Authentik forward-auth
- TALOS-b42 - EPIC: Authentik GitHub OAuth Source
- TALOS-kmjc.1 - P0: `authentik-postgres-backup` CronJob has never succeeded
- TALOS-9l2h - Kyverno `oidc-hostalias` cannot open a restrictive egress NetworkPolicy
