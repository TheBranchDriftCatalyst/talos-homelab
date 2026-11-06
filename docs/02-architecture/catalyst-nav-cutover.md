# Catalyst nav: cutting over to the authenticated manifest

## TL;DR

The nav bar's link list comes from a **public static file** that lists every internal hostname
in the cluster to anyone on the LAN. Phase 4 replaces it, **one app at a time**, with a
**per-identity endpoint** that filters the manifest from the caller's Authentik groups.

- **Cut an app over** by adding `data-nav-manifest="identity"` to its own
  `catalyst-inject-<app>` middleware. **Roll it back** by deleting that one attribute.
- **First two apps: `dbgate`, then `sonarr`.** dbgate is admin-only and low-traffic; sonarr is
  the one non-admins actually use, which is the only way to observe the filtered view.
- **Nothing is live yet.** The client ships with the static file as its default, so the
  per-app attribute is the only switch, and no app has it.
- **Two preconditions before anything:** the operator image must be built and pushed, and
  `clusters/catalyst-cluster/catalyst-nav.yaml` must be applied.

---

## Quick reference

| Action                         | Edit                                                                                                                                             |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| Cut over one app               | `infrastructure/base/themepark/middlewares.yaml` → that app's `catalyst-inject-<app>` → add `data-nav-manifest="identity"` to the `<script>` tag |
| Roll back one app              | Delete that attribute. Nothing else.                                                                                                             |
| Roll back everything           | Revert the same attribute wherever it appears. The route and the operator can stay.                                                              |
| Check which source an app uses | DevTools → Network → look for `catalyst-nav/v1/manifest.json` (identity) vs `resources/catalyst-nav.json` (static)                               |

The exact edit, for one app:

```diff
-          replacement: '<head><script defer src="/catalyst/resources/catalyst-nav.js"></script>'
+          replacement: '<head><script defer src="/catalyst/resources/catalyst-nav.js" data-nav-manifest="identity"></script>'
```

The attribute is a **keyword, not a URL** — the client holds both URLs as constants and the
tag only selects between them by name. A middleware that could name an arbitrary manifest URL
could repoint every link in the bar.

---

## Preconditions

Both are outside this document's edits and neither is optional.

1. **Build and push the operator image.** `deployment.yaml` pins
   `registry.talos00/talos00-registry/catalyst-nav-operator:v0.1.0`; no CI in this repo builds
   images. The build command is in `infrastructure/base/catalyst-nav/operator/Dockerfile`.
   Applied without it, the Deployment sits in ImagePullBackOff and the endpoint answers
   nothing.
2. **Apply `clusters/catalyst-cluster/catalyst-nav.yaml`.** Read its header first — it also
   notes that the NavEntry validating webhook is `failurePolicy: Fail`, so once applied,
   NavEntry CREATE/UPDATE is refused cluster-wide while the operator pod is not Ready. Nothing
   creates NavEntries today, so that blast radius is currently zero.

Until both are done, every app keeps reading the static file whether or not it carries the
attribute — a cut-over app would simply get no bar.

---

## Which apps, and why

### Eligibility is not a preference, it is three hard gates

An app can only be cut over if **all three** hold. Each failure mode is silent.

1. **It has its own `catalyst-inject-<app>` middleware.** The shared `catalyst-inject-nav` is
   used by most of the fleet, so editing _that_ cuts over everything at once and is the
   opposite of a staged rollout. 15 apps have their own injector.
2. **Its route carries `authentik-lan` forward-auth.** The providers are `forward_single`
   with no `cookie_domain`, so the session cookie is scoped to each app's own host. A
   same-origin fetch from an authenticated page carries it; an app with no forward-auth has no
   such cookie, and the fetch gets a 302 to SSO → no bar.
3. **It is served over HTTPS (`websecure`).** Every Authentik proxy provider has an `https`
   external_host, so the session cookie is `Secure` and is **not sent over plain HTTP**. An
   HTTP-only app would get a 200 carrying the _anonymous_ subset and look like it worked.

### The two chosen

**1. `dbgate` — first, because it is the cheapest mistake.**

- Own injector (`catalyst-inject-dbgate`); `authentik-lan` + `websecure` confirmed in
  `infrastructure/base/databases/dbgate/ingressroute.yaml`.
- Gated to `talos-admin` / `cluster-admin`, so _only_ admins can reach it. If the bar breaks,
  the people who see it are the people who can fix it, and no end user is affected.
- Low traffic, and not a tool anyone drives through the nav bar — the bar is incidental here,
  which is exactly what you want from the first one.

**2. `sonarr` — second, because it is the only one that can prove the filtering works.**

- Own injector (`catalyst-inject-sonarr`); `authentik-lan` + `websecure` confirmed in
  `applications/arr-stack/base/sonarr/ingressroute.yaml`.
- **Non-admins can reach it.** dbgate cannot demonstrate the non-member view at all — a
  non-member cannot open dbgate to look at its nav bar. sonarr is where an admin and a
  non-admin can load the same page and see two different bars, which is the entire claim of
  this phase and is otherwise untested in production.
- Its `/api` + `/feed` carve-out is a priority-100 route with **no** forward-auth, for nzb360
  / LunaSea / RSS clients. That does not interact with this change: those clients do not load
  HTML, so they never receive the injected script.

### Explicitly NOT first: `argocd`

It looks ideal — own injector, HTTPS, admin-facing, and a Catalyst base sheet was just written
for it — and it is disqualified by gate 2. `infrastructure/base/argocd/ingressroute.yaml` has
**no forward-auth on purpose**: ArgoCD authenticates its own UI/API/CLI via OIDC, and adding
Authentik would double-auth and break the CLI. So there is no Authentik proxy session cookie
on `argocd.talos00`, and the manifest fetch would 302 to SSO and render no bar. Any
OIDC-native app is in the same position.

Also disqualified, by gate 3: **`plex`, `jellyfin`** — both served over plain HTTP
(`asset-route.yaml` keeps an HTTP twin specifically for them).

### One more thing the route cannot fix

The IngressRoute matches `HostRegexp(^[a-z0-9-]+\.talos00$)`, so it answers on _every_
`*.talos00` host, but it attaches `authentik-lan`. Five routes in the tree still use the older
`authentik` middleware. On those hosts the nav fetch would ask `talos00-outpost` about a
cookie the embedded outpost issued, which fails closed to the anonymous subset. Do not cut
over an app still on `authentik` — migrate it first.

---

## Verifying an admin sees an identical bar

The success condition for cutover #1 is **no visible change for an admin**. Identity filtering
only ever _removes_ entries, and an admin is a member of everything restricted, so an admin's
filtered manifest should equal the unfiltered one.

Only the `infrastructure` NavGroup declares `visibility.authentikGroups`
(`[talos-admin, cluster-admin]`) in `infrastructure/base/catalyst-nav/taxonomy.yaml`. Every
other group is unrestricted. So for an admin, nothing is filtered at all.

1. **Before** the attribute lands, on `https://dbgate.talos00`, save the static manifest as
   the baseline:
   ```
   curl -ks https://dbgate.talos00/catalyst/resources/catalyst-nav.json | python3 -m json.tool > /tmp/nav-before.json
   ```
2. **After**, from a browser logged in as an admin, fetch the identity endpoint _with the
   session_ — this must be done in the browser, because the whole point is the cookie. In the
   DevTools console on `https://dbgate.talos00`:
   ```js
   await (
     await fetch('/catalyst-nav/v1/manifest.json', {
       credentials: 'same-origin',
       cache: 'no-store',
     })
   ).json()
   ```
3. **Compare the group and item names**, not the bytes. The two producers are byte-identical
   on the same input (`task nav:parity`), but the live inputs differ: the static file is
   rebuilt by the sidecar every 300s from the cluster's IngressRoutes, while the operator
   reconciles continuously. A new app can legitimately appear in one before the other.
4. **Confirm the headers**, which are the thing that cannot be allowed to regress:
   ```
   Cache-Control: private, no-store
   Vary: <names Cookie and the group header>
   ```
   If you see `public, max-age=300`, the asset-cache middleware has been attached to the route
   and **one user's nav is being served to another** — revert immediately.
5. **Confirm the bar visually.** Same groups, same order, same gear. The nav is cosmetic and
   degrades to nothing, so "the bar is there and complete" is the real check.

---

## How a non-member's view differs

Do this on **sonarr** (cutover #2), not dbgate — a non-member cannot open dbgate.

As a user in **no** admin group:

- The **Infrastructure** group disappears from the bar entirely — ArgoCD, CrowdSec, MinIO and
  the rest of it. Not greyed out, not empty: absent, because the filter drops the group.
- Every other group is unrestricted today and renders identically to an admin's.
- The bar still works. Fewer links is the _correct_ result, not a degraded one.

The trap to watch for: **an admin seeing the non-member view** is the signature of the cookie
not arriving — `credentials` wrong, the app on plain HTTP, or forward-auth not attached. It
fails closed to the anonymous subset, which looks like a working bar. That is why step 4 above
checks headers, and why this phase was built around `credentials: 'same-origin'`.

To see the anonymous view deliberately without a second account, fetch with no session at all;
the handler's fail-closed default is what serves it:

```
curl -ks https://sonarr.talos00/catalyst-nav/v1/manifest.json | python3 -m json.tool
```

That request carries no cookie, so it is the anonymous view — and it should **not** contain
Infrastructure. If it does, the filter is not being applied and the cutover is unsafe.

---

## Rolling back one app without touching the rest

This is the property the whole design is arranged around.

1. Delete `data-nav-manifest="identity"` from that app's `catalyst-inject-<app>` block in
   `infrastructure/base/themepark/middlewares.yaml`.
2. Commit, push, and let Flux reconcile (`task infra:flux-reconcile` to force it).
3. Hard-reload the app. It is back on the static manifest.

Why it is genuinely isolated:

- Each app has its **own** `catalyst-inject-<app>` Middleware object, so the edit cannot reach
  another app. (The one exception is the shared `catalyst-inject-nav` — never put the
  attribute there, because then rollback is fleet-wide by construction.)
- The **client is one shared file** but its default is the static source, so an app without
  the attribute is byte-for-byte unaffected by the cutover of one that has it.
- The **route and the operator stay deployed** during a rollback. Nothing requests the
  endpoint, so leaving it running costs nothing and avoids a second change under pressure.

**Do not roll back by deleting the IngressRoute.** That takes every cut-over app down at once
and leaves them with no bar — the client treats a 404 as transient, retries three times, and
then renders nothing. Remove the opt-in, not the backend.

### If you must stop everything immediately

Revert the attribute everywhere it appears (two apps, if you followed this doc). The fleet is
back on the static manifest in one reconcile. Suspending the `catalyst-nav` Kustomization is
**not** the fast path — it leaves the attribute in place and the cut-over apps barless.

---

## Why there is no fallback to the static file

The client deliberately does **not** fall back to the static manifest when the identity
endpoint refuses it. It renders no bar.

Falling back would be wrong twice over. The static file is the public everything-manifest this
endpoint exists to stop handing out, so a fallback would re-leak the full host list to exactly
the caller who just failed to prove an identity. And it would disguise a broken cutover as a
working one for as long as nobody looked at the network tab. A missing bar is visible; a bar
that is secretly the public one is not.

For the same reason, the client treats `401`, `403` and a `302`-to-SSO as **terminal** — no
retries. Those are authoritative answers about who the caller is, and asking twice more cannot
change them. `503` and network errors are still retried three times, because the endpoint
answers `503` before its first reconcile and a pod that has just rolled serves the theme
before the manifest exists.

---

## Related Issues

<!-- Beads tracking for this doc -->
