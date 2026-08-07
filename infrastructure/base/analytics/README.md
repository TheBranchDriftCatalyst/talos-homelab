# analytics — central Plausible injection

## TL;DR

One place to manage analytics for every self-hosted app. A Traefik middleware chain injects the
Plausible `<script>` into HTML responses, so you **never edit an app's repo to add/change tracking**.

- **Turn it on for an app:** add one middleware ref to that app's `IngressRoute` (see below).
- **Change the analytics host / script extensions / tracked domain:** edit the single
  `analytics-inject-knowledgedump` middleware in `middlewares.yaml`. Everything opted-in follows.
- **Endpoint it feeds:** `https://analytics.knowledgedump.space` (Plausible, tracking-only public
  route in `applications/crossplane-demo/plausible/`).

## Opt an app in

Add to the app's `IngressRoute` route (the routes live in THIS repo, not the app's repo):

```yaml
    middlewares:
      - name: analytics
        namespace: traefik
```

That's it. The `analytics` chain runs: `strip-accept-encoding` → `analytics-csp` → `analytics-inject-knowledgedump`.

## What each piece does

| Middleware | Role |
|---|---|
| `strip-accept-encoding` | forces `identity` so the body-rewrite plugin sees plaintext HTML (it can't rewrite gzip) |
| `analytics-csp` | **additively** appends `analytics.knowledgedump.space` to an app's CSP `script-src`/`connect-src` (never replaces the policy) |
| `analytics-inject-knowledgedump` | injects the Plausible `<script>` before `</head>` — the single source of truth for host + extensions + `data-domain` |
| `analytics` | the chain of the three above; this is what apps reference |

## Requirements & gotchas

- **Traefik plugins** `rewritebody` (v0.3.1) + `rewriteHeaders` (v0.0.4) are enabled in
  `infrastructure/base/traefik/helmrelease.yaml` (`experimental.plugins`). Traefik fetches them from
  GitHub on pod startup — a rollout needs egress to github.com.
- **Only apps fronted by this Traefik** get injected. External/statically-hosted sites embed the
  snippet at source (same `analytics.knowledgedump.space`).
- **CSP with only `default-src`** (no explicit `script-src`/`connect-src`) won't be matched by the
  additive rewrite — handle those per-app.
- **Per-site `data-domain`:** one inject middleware = one `data-domain`. For another site, copy the
  inject middleware with a new `data-domain` and make a sibling chain.
- **Don't apply globally** at the entrypoint — injecting into admin UIs (Grafana/ArgoCD/*arr) is
  pointless and CSP-fragile. Opt-in per ingress.

## Source-embed snippet (for external sites)

```html
<script defer data-domain="knowledgedump.space"
  src="https://analytics.knowledgedump.space/js/script.file-downloads.hash.outbound-links.pageview-props.tagged-events.js"></script>
<script>window.plausible = window.plausible || function() { (window.plausible.q = window.plausible.q || []).push(arguments) }</script>
```

(The inline stub is only needed where the page fires custom `plausible(...)` events; the injected
variant omits it to stay CSP-clean.)

---

## Related Issues

- TALOS-4gg — Plausible provisioning + analytics strategy
