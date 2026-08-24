# Audiobookshelf — Authentik NATIVE OIDC (operator runbook)

**TL;DR:** Provider + Application + client-secret are declarative (authentik
`media-oidc-blueprint.yaml` + `externalsecret.yaml`). The app-side OIDC config is
**admin-UI only** (Audiobookshelf has no OIDC env vars) — do the one-time steps below.

- Config location: **Settings → Authentication → enable OpenID Connect**
- Web callback: `https://audiobookshelf.talos00/auth/openid/callback`
- Mobile: `https://audiobookshelf.talos00/auth/openid/mobile-redirect` + custom scheme `audiobookshelf://oauth`
- Requires HTTPS (route moved web→websecure; see `patch-ingressroute.yaml`)

## 1. Read the generated client secret

```bash
kubectl -n authentik get secret authentik-audiobookshelf-oidc \
  -o jsonpath='{.data.client-secret}' | base64 -d; echo
```

(The ESO Password generator mints it once; reflector also mirrors it into
`media-experimental` as `authentik-audiobookshelf-oidc` if you prefer to read it there.)

## 2. Configure in the Audiobookshelf admin UI

Settings → Authentication → **OpenID Connect Authentication** → enable, then:

| Field | Value |
|-------|-------|
| Issuer URL | `https://auth.knowledgedump.space/application/o/audiobookshelf/` |
| Authorize URL | `https://auth.knowledgedump.space/application/o/authorize/` |
| Token URL | `https://auth.knowledgedump.space/application/o/token/` |
| Userinfo URL | `https://auth.knowledgedump.space/application/o/userinfo/` |
| JWKS URL | `https://auth.knowledgedump.space/application/o/audiobookshelf/jwks/` |
| Logout URL | `https://auth.knowledgedump.space/application/o/audiobookshelf/end-session/` |
| Client ID | `audiobookshelf` |
| Client Secret | *(value from step 1)* |
| Button Text | `Login with Authentik` |
| Auto Register | on (access is already gated by the IdP group policy) |
| **Allowed Mobile Redirect URIs** | `audiobookshelf://oauth` |

Tip: the **Auto-populate** button fills the URLs from the discovery doc — paste the
Issuer URL and let it fetch, then set Client ID/Secret + the mobile redirect URI.

## 3. Verify

- Web: open `https://audiobookshelf.talos00` → "Login with Authentik".
- Mobile app: Server URL `https://audiobookshelf.talos00` → OIDC login.
- Only members of `talos-media` or `cluster-admin` are allowed (IdP PolicyBindings).

## Notes / gotchas

- The Audiobookshelf server does discovery/token server-side; the pod reaches
  `auth.knowledgedump.space` via the in-cluster CoreDNS rewrite → traefik.
- If the worker was restarted after the secret was generated, the provider holds
  the real secret; if you rotate the ESO secret you must re-paste it here (both
  ends must match).
