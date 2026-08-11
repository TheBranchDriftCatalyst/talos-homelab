# Komga — Authentik NATIVE OIDC (operator runbook)

**TL;DR:** **Fully declarative** — no admin-UI steps. The Spring Security OAuth2
env vars are in `patch-deployment.yaml`, the client-secret is injected from the
reflected `authentik-komga-oidc` secret, and the provider/application live in
authentik `media-oidc-blueprint.yaml`.

- Config: env vars (`SPRING_SECURITY_OAUTH2_CLIENT_*`, `KOMGA_OAUTH2_ACCOUNT_CREATION`)
- registrationId: `authentik`
- Callback: `https://komga.talos00/login/oauth2/code/authentik`
- Issuer (discovery): `https://auth.knowledgedump.space/application/o/komga/`
- Requires HTTPS (route moved web→websecure; see `patch-ingressroute.yaml`)

## How the secret flows

```
ESO Password generator (ns authentik)
  → Secret authentik-komga-oidc (ns authentik)      ← worker !Env KOMGA_OIDC_CLIENT_SECRET
  → reflector copies → Secret authentik-komga-oidc (ns media-experimental)
      → Komga env SPRING_SECURITY_OAUTH2_CLIENT_REGISTRATION_AUTHENTIK_CLIENT_SECRET
```

Both ends read the SAME generated value, so no manual coordination.

## Verify

```bash
# secret reached media-experimental (reflector)
kubectl -n media-experimental get secret authentik-komga-oidc

# read it if needed
kubectl -n authentik get secret authentik-komga-oidc \
  -o jsonpath='{.data.client-secret}' | base64 -d; echo
```

- Open `https://komga.talos00` → "Login with Authentik".
- First login auto-creates the Komga user (`KOMGA_OAUTH2_ACCOUNT_CREATION=true`),
  inheriting no roles — an existing admin grants library/admin roles afterward.
- Only `talos-media` / `cluster-admin` members are admitted (IdP PolicyBindings).
- Tachiyomi/Mihon/Paperback + OPDS keep using Komga's own credentials/API — native
  OIDC does not gate those.

## Notes / gotchas

- Komga uses `issuer-uri` (discovery), so it fetches
  `…/application/o/komga/.well-known/openid-configuration` **at startup** — if
  Authentik is down when Komga (re)starts, Komga's Spring context fails to boot.
  Authentik is core infra so this is acceptable; if it bites, restart Komga once
  Authentik is healthy.
- `user-name-attribute: preferred_username` gives readable Komga usernames; keep
  "allow username change" disabled in Authentik to avoid identity drift.
- The client-secret secretKeyRef is non-optional: if the reflected secret is not
  yet present the pod waits in `ContainerCreating` (self-heals when reflector
  copies it) rather than CrashLooping.
