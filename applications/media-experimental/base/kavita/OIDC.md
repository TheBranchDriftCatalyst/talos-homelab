# Kavita — Authentik NATIVE OIDC (operator runbook)

**TL;DR:** Provider + Application + client-secret are declarative (authentik
`media-oidc-blueprint.yaml` + `externalsecret.yaml`). The app-side OIDC config is
**admin-UI only** (stored in the config PVC's `appsettings.json`) — do the one-time
steps below.

> **VERSION FLAG:** Kavita OIDC/SSO landed in **v0.8.8** (NOT 0.8.6 as originally
> assumed). The deployment runs `jvmilazz0/kavita:latest`. Confirm the running pod
> is ≥ 0.8.8 before configuring — if the Settings page has **no OpenID Connect
> section**, the image predates OIDC; pull a newer `:latest` / pin ≥ 0.8.8.
> ```bash
> kubectl -n media-experimental exec deploy/kavita -- cat /kavita/wwwroot/../BUILD_VERSION 2>/dev/null || \
> kubectl -n media-experimental get deploy kavita -o jsonpath='{.spec.template.spec.containers[0].image}'
> ```
> (Or just check Settings → the OIDC tab only renders on ≥ 0.8.8.)

- Config location: **Settings → Users → OpenID Connect** (admin only)
- Login callback: `https://kavita.talos00/signin-oidc`
- Post-logout callback: `https://kavita.talos00/signout-callback-oidc`
- Requires HTTPS (route moved web→websecure; see `patch-ingressroute.yaml`)

## 1. Read the generated client secret

```bash
kubectl -n authentik get secret authentik-kavita-oidc \
  -o jsonpath='{.data.client-secret}' | base64 -d; echo
```

## 2. Configure in the Kavita admin UI

Settings → Users → **OpenID Connect**:

| Field | Value |
|-------|-------|
| Authority | `https://auth.knowledgedump.space/application/o/kavita/` |
| Client ID | `kavita` |
| Secret | *(value from step 1)* |
| Auto-provision / account creation | on (IdP group policy already gates access) |
| Require verified email | optional |
| Custom scopes | leave default (`openid profile email`) |

Kavita registers `/signin-oidc` and `/signout-callback-oidc` itself — both are
already in the provider `redirect_uris`. **Save, then restart Kavita** (Authority /
Client ID / Secret changes require a manual app restart to take effect):

```bash
kubectl -n media-experimental rollout restart deploy/kavita
```

## 3. Verify

- Open `https://kavita.talos00` → the OIDC login button appears.
- Only `talos-media` / `cluster-admin` members are admitted.
- OPDS + API-key clients (Paperback etc.) are unaffected — they use per-user API
  keys, not the OIDC web flow.

## Notes / gotchas

- OidcSettings persist to `appsettings.json` in the config PVC — do NOT try to
  mount a ConfigMap over it (the app rewrites the file); admin-UI is the source of truth.
- Known issue: some Kavita builds submit `http` as the redirect scheme behind a
  proxy — serving the app on websecure (this change) keeps it `https`.
