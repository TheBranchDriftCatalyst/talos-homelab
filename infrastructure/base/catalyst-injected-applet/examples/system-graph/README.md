# system-graph injected-applet — delivery rail (TALOS-gsgh.5)

Surfaces the live system-graph topology as an in-app **overlay on every `*.talos00`
host**, docked into the catalyst navbar — in addition to its existing page at
`system-graph.talos00`. Built on the house `CatalystInjectedApplet` abstraction
(`../../xrd.yaml`, `../../composition.yaml`), same pattern as dev-overlay.

> **This directory is a REFERENCE STAGE, not reconciled.** It is deliberately absent from
> `../../kustomization.yaml`, so Flux never applies it from talos-homelab. The two files
> below belong in the **system-graph repo** (ArgoCD-synced), per the dual-GitOps rule the
> system-graph ArgoCD Application already states: "Everything system-graph is … lives in
> the system-graph repo under k8s/."

## What goes where

| File (here) | Destination | Owner |
| --- | --- | --- |
| `applet.yaml` | `system-graph/k8s/talos00/applet.yaml` (+ add to that dir's `kustomization.yaml` `resources:`) | orchestrator / system-graph repo |
| `system-graph.js` | `system-graph/demo/system-graph-applet.js` (new file; synced into `server/web/` by `scripts/sync-web.sh` + the Dockerfile copy) | orchestrator / system-graph frontend |

The **one talos-homelab change** for this rail is already applied:
`infrastructure/base/argocd/applications/system-graph.yaml` gained an `ignoreDifferences`
entry for `net.catalyst.io/CatalystInjectedApplet` (`/status`), so the composite's status
writes do not park the ArgoCD app permanently OutOfSync.

## REQUIRED system-graph SERVER change (do not skip — the claim is inert without it)

`server/internal/server/server.go` serves the mux at the ROOT only:

```go
mux.HandleFunc("/healthz", s.healthz)
mux.HandleFunc("/api/graph", s.graph)
mux.Handle("/", s.static)          // the embedded SPA
```

The `CatalystInjectedApplet` claim routes two same-origin prefixes to this Service:

- `PathPrefix(/catalyst/applets/system-graph/)` → the loader bundle **and** the UI index
- `PathPrefix(/catalyst/api/system-graph/)` → the live graph JSON

The server must be **prefix-aware** and answer under those real public paths (there is NO
stripPrefix middleware — the composite forbids it, and the mux must emit its real public
mount, exactly like dev-overlay's Go mux). Concretely, additionally register:

- `GET /catalyst/applets/system-graph/system-graph.js` → the new applet bundle
- `GET /catalyst/applets/system-graph/` (+ assets: `style.css`, `app.js`, `data/`, `icons/`,
  `vendor/`) → the embedded SPA, served under that prefix. The SPA's `index.html` currently
  uses **root-relative** asset hrefs (`style.css`, `app.js`) and the app reads
  `window.CATALYST_GRAPH` / fetches the graph; all of those must resolve under the prefix
  when framed there. Serving the embedded FS under the prefix (e.g.
  `http.StripPrefix`-free sub-mux + prefix-relative asset URLs, or a `<base href>` in the
  framed document) is the frontend half of this.
- `GET /catalyst/api/system-graph/graph` → the same handler as `/api/graph`.

No auth logic is needed in the server for these: the `/catalyst/` prefix is gated at the
edge by `HostRegexp(^[a-z0-9-]+\.talos00$)` + `lan-only` and is NOT behind authentik — that
is the whole point of serving same-origin.

## SSO / framing analysis

- **Same-origin design (this bundle's default `UI_SRC = /catalyst/applets/system-graph/`):**
  no SSO, no CORS, no framing headers needed. The iframe is same-origin with the host page,
  gated only by `lan-only`. This is why the server prefix change above is the right fix.
- The server sets **no** `X-Frame-Options` / CSP today, and `/api/graph` already returns
  `Access-Control-Allow-Origin: *` — so framing is not blocked at the app layer for the
  same-origin path.

### Interim cross-origin fallback (only if the server prefix work is not ready)

Point the bundle at `UI_SRC = "https://system-graph.talos00/"` (cross-origin). This reuses
the existing SSO-gated UI as-is, but requires, on `system-graph.talos00` / its authentik
outpost:

1. **Framing allowed:** no `X-Frame-Options: DENY/SAMEORIGIN`, and
   `Content-Security-Policy: frame-ancestors 'self' http://*.talos00 https://*.talos00`
   (or the specific hosts) — on BOTH the app responses and the authentik login responses,
   or the login redirect inside the frame is blocked.
2. **Cross-site cookie:** the authentik session cookie must be `SameSite=None; Secure`, or
   it is not sent in the third-party iframe context and every open hits the login flow.

Because (1) and (2) are authentik/server changes anyway, the same-origin rail is both
cleaner and less work overall. Recommend NOT shipping the cross-origin fallback.

## How it appears to a user

On any themed `*.talos00` host (grafana, sonarr, …) the catalyst navbar grows one extra
button (a small graph glyph) in the bar's right-hand dock, next to the gear. Clicking it
opens a full-viewport overlay titled "System Graph" containing the live topology UI; the
dimmed margin or Escape or the × closes it. Nothing new to visit, no second login within an
already-authenticated LAN session.

## Validation performed (talos-homelab side)

- `yamllint -c dev/yamllint.yaml --strict` on `applet.yaml` and the edited ArgoCD app: clean.
- `kustomize build infrastructure/base/catalyst-injected-applet` and
  `…/argocd/applications`: clean; this `examples/` tree is not pulled into either.
- `kubectl apply --dry-run=server` of `applet.yaml` against the live
  `catalystinjectedapplets.net.catalyst.io` CRD: accepted (schema + composition valid).
