# BookOrbit — Authentik OIDC (operator runbook)

**TL;DR:** **NOT wired, deliberately.** Unlike komga/kavita/audiobookshelf, BookOrbit
cannot be configured declaratively — it stores its OIDC provider config **in its own
database**, editable only through its admin UI. Everything that *can* be prepared in
git has been; the rest is a documented manual step, not a half-finished config.

- BookOrbit **is** a supported Authentik client — upstream lists Authentik as tested
  and working out of the box.
- Callback (register this in Authentik): `https://bookorbit.talos00/oauth2-callback`
- The route is already on `websecure` so this URL works the moment SSO is enabled.
- The pod already carries `catalyst.io/oidc: "true"`, so Kyverno injects the
  `auth.knowledgedump.space` hostAlias before the first token exchange ever happens.

## Why this is not declarative

There are **no OIDC environment variables** for issuer, client ID, client secret or
redirect URI. From upstream's own `server/.env.example`:

> OIDC config is stored in the database (`app_settings` table, key: `oidc_config`)

The schema is `server/src/db/schema/oidc.ts`, table `oidc_providers`
(`slug`, `issuer_uri`, `client_id`, `client_secret`, `scopes`, `claim_mapping`,
`auto_provision`, …). Multiple providers are supported and discovery is automatic
from `.well-known/openid-configuration`.

The only OIDC *env* vars are runtime tuning — `OIDC_STATE_TTL_SECS`,
`OIDC_DISCOVERY_CACHE_TTL_SECS`, `OIDC_JWKS_CACHE_TTL_SECS`,
`OIDC_CLOCK_TOLERANCE_SECS`, `OIDC_TOKEN_EXCHANGE_TIMEOUT_MS`,
`OIDC_ALLOW_LOCAL_ISSUERS`. None of them configure a provider, so none are set.

Consequence: an Authentik blueprint alone would create a provider that nothing
consumes. That is the "half-configured app that appears to work" case, so the
Authentik side was **not** added either — both halves should land together, in one
deliberate pass.

## What enabling it requires

**1. Authentik side** — a native OIDC provider, matching the pattern in
`infrastructure/base/authentik/media-oidc-blueprint.yaml` (the komga / kavita /
audiobookshelf blueprint), *not* the `forward_single` proxy providers in
`media-experimental-blueprint.yaml`. BookOrbit has first-party Kobo / KOReader / OPDS
clients that a forward-auth proxy would break, exactly as it would for komga.

Needs, mirroring the existing entries there:

- `authentik_providers_oauth2.oauth2provider`, `client_type: confidential`,
  `client_id: bookorbit`
- `client_secret: !Env [BOOKORBIT_OIDC_CLIENT_SECRET, ""]`
- redirect URI `https://bookorbit.talos00/oauth2-callback` (strict)
- `issuer_mode: per_provider` → issuer `https://auth.knowledgedump.space/application/o/bookorbit/`
  (the public-cert host, so the pod and any phone both trust it with no homelab-CA
  plumbing — same rationale as the other three)
- an `authentik_core.application` (slug `bookorbit`, group `talos-media`,
  `policy_engine_mode: any`) plus the two PolicyBindings (`talos-media`,
  `cluster-admin`)
- an ESO `Password` generator producing Secret `authentik-bookorbit-oidc` in ns
  `authentik`, reflected into `media-experimental`

Note two orchestrator-owned files must also be touched for a blueprint to take
effect at all, which is part of why this was left as one deliberate change:
`infrastructure/base/authentik/helmrelease.yaml` (`blueprints.configMaps` list, plus
the worker's `BOOKORBIT_OIDC_CLIENT_SECRET` env) and
`infrastructure/base/authentik/kustomization.yaml`.

**2. BookOrbit side** — manual, in the UI, at **Settings → OIDC / SSO**. Paste:

| Field | Value |
| --- | --- |
| Issuer URI | `https://auth.knowledgedump.space/application/o/bookorbit/` |
| Client ID | `bookorbit` |
| Client secret | value of `authentik-bookorbit-oidc` key `client-secret` |
| Scopes | `openid profile email` (the default) |

Then enable the provider.

## Two traps worth knowing before you turn it on

- **Auto-provisioning is OFF by default** (`autoProvision.enabled: false`). Without
  it, a valid Authentik login lands on *"Your account has not been set up"*.
- If any **local BookOrbit accounts already exist** (they will — the setup wizard
  creates the first admin), you must ALSO enable **Allow local account linking**,
  which matches on the username claim. Upstream flags this as a `:::danger:::` —
  skip it and SSO logins create duplicate accounts alongside the local ones instead
  of adopting them.

Group→permission mappings re-sync on every login and *can revoke* permissions;
default permissions are applied once, at account creation.

## Verify (once wired)

```bash
# hostAlias actually injected (this is the bit that silently breaks otherwise)
kubectl -n media-experimental get pod -l app=bookorbit \
  -o jsonpath='{.items[0].spec.hostAliases}'

# Kyverno did NOT skip the mutation
kubectl get policyreport -A -o json | jq -r '.items[] | .metadata.namespace + "/" +
  (.results[]? | select(.policy=="oidc-hostalias" and .result=="fail") | .resources[0].name)'

# discovery reachable from inside the pod
kubectl -n media-experimental exec deploy/bookorbit -- \
  wget -qO- https://auth.knowledgedump.space/application/o/bookorbit/.well-known/openid-configuration
```

---

## Related Issues

<!-- Beads tracking for this doc -->
- EPIC 3 / TALOS-3hl8 — de-pinning media-experimental (BookOrbit is the first
  node-agnostic app in this namespace)
