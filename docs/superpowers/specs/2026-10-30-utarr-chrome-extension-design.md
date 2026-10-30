# utarr — Chrome extension for Youtarr

**Date:** 2026-10-30
**Status:** Approved design, not yet implemented
**Extension code:** `../chrome-ext/utarr` (new, outside this repo)
**Server change:** this repo, `applications/youtarr/`

## Problem

Youtarr subscriptions and downloads currently require opening the web UI and
pasting a URL. We want a browser action on YouTube pages that can, in one click:
subscribe to the current channel, subscribe to the current playlist, or queue the
current video for download.

## Constraints discovered during design

These three findings shaped the whole design and must not be re-litigated without
re-checking upstream:

1. **The external API does single video downloads ONLY.** `docs/API_INTEGRATION.md`
   states it twice: *"API keys currently support single video downloads only.
   Playlists, channels, and batch operations are not supported via the API."*
   The only external endpoint is `POST /api/videos/download`.
   → Channel and playlist subscribe CANNOT be done via API. They must go through the UI.

2. **Youtarr's add dialogs cannot be pre-filled from a URL.** Its SPA reads only
   `searchParams.get("v")` and `.get("job")`; routes are `/`, `/channels`,
   `/subscriptions`, `/subscriptions/find`, `/videos`, `/videos/find`,
   `/channel/:channel_id`, `/playlist/:id`, `/configuration`, `/login`, `/setup`.
   There is no `?url=` prefill parameter.
   → Deep-linking means "open the page"; the URL itself must arrive via clipboard.

3. **Authentik forward-auth blocks the API, and bypassing it is unsafe as currently
   configured.** `GET /api/health` through the ingress returns 302 to auth.talos00.
   Upstream's warning: *"If you run Youtarr with AUTH_ENABLED=false and rely on the
   proxy for all authentication, Youtarr accepts every request without checking the
   API key. Bypassing the proxy for this path then lets anyone who can reach your
   server queue downloads."* We run exactly that configuration.
   → A bypass MUST carry its own authentication.

Also established: Youtarr has **no trusted-header / Remote-User / proxy-SSO mode**
(`docs/AUTHENTICATION.md`). Its auth is either its own login form or nothing. Chaining
Authentik's identity into a Youtarr session is not possible, so `AUTH_ENABLED=true`
would mean a genuine second login screen.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Overall shape | **Hybrid (C)** — API for video, deep-link for channel/playlist | Only video has an API; hybrid gives the best available UX per flow |
| API auth | **Gate at Traefik (Option 1)** — secret-backed BasicAuth on the bypassed path | Keeps `AUTH_ENABLED=false`, so NO double login, while still authenticating the endpoint |
| Channel/playlist mechanism | **C1 — clipboard + open `/subscriptions`** | Robust. C2 (content-script autofill) couples to Youtarr's DOM and would break silently; Youtarr ships releases weekly |
| Extension tooling | **Vanilla JS, MV3, no build step** | No toolchain to maintain for ~400 lines |

Rejected: `AUTH_ENABLED=true` + native API keys. It buys per-key revocation, per-key
rate limits and usage tracking, at the cost of reintroducing the double login removed
in TALOS-8pbo. Revisit if several clients appear (phone shortcut, Home Assistant, n8n)
and per-client revocation starts to matter.

## Server-side change (this repo)

A new IngressRoute in `applications/youtarr/ingressroute.yaml`:

- Match: ``Host(`youtarr.talos00`) && Path(`/api/videos/download`)``
- Priority: set EXPLICITLY (e.g. `priority: 3000`) above the Authentik route. Traefik
  otherwise orders by rule length, which is too implicit to rely on for a security
  boundary — if the Authentik route ever wins, the extension silently 302s; if this
  route ever widened, the UI would lose SSO.
- Middlewares: `traefik/lan-only` + a new secret-backed `basicAuth` — **NOT** `authentik-lan`
- Service: `youtarr:3011`

Plus, in `applications/youtarr/secret.yaml`, an ESO `Password` generator +
`ExternalSecret` producing the BasicAuth secret. Follows the existing `youtarr-admin`
generator pattern; the credential never appears in git.

> **OPEN IMPLEMENTATION DETAIL — resolve this FIRST, before any extension code.**
> Traefik's `basicAuth` expects a Secret whose `users` key holds **htpasswd** lines
> with an MD5/SHA1/bcrypt-hashed password, not a plaintext one. The ESO `Password`
> generator emits plaintext, and the extension needs that same plaintext to send.
> So the ExternalSecret must emit BOTH: the hash for Traefik and the plaintext for us.
> Resolution order to try:
> 1. An ESO v2.6.0 template function that produces an htpasswd/bcrypt hash, if one
>    exists in this version — fully declarative, preferred.
> 2. Sprig primitives in the template to build the `{SHA}base64(sha1(pw))` form.
> 3. Last resort: a one-shot Job to mint it. This is imperative glue and conflicts
>    with the repo's operator-CRD preference — only if 1 and 2 both fail.
> If none of these is clean, STOP and re-open the auth decision rather than shipping a
> hand-made secret: a manually-created credential is exactly the kind of thing that
> silently rots and is not reproducible on a rebuild.
> Reference: `media-private/desec-basic-auth` has the right shape (a `users` key) but
> is NOT in git, so there is no in-repo pattern to copy.

Precedent in-cluster: `media-private/desec-basic-auth` already uses
`basicAuth: { secret: ... }`, and `media-private/authentik-stash-api` shows per-route
auth variance is an established pattern here.

`Path()` not `PathPrefix()` — exactly one endpoint is exempted, nothing else.

## Extension structure (`../chrome-ext/utarr`)

```
manifest.json      MV3. permissions: activeTab, storage, clipboardWrite
                   host_permissions: https://youtarr.talos00/*
popup.html/.js     detects tab kind, shows only applicable actions
options.html/.js   settings page
lib/detect.js      URL -> {kind: video|channel|playlist, id}
lib/api.js         POST /api/videos/download
icons/             16/48/128
```

### Flows

| Tab is | Action | Mechanism |
|---|---|---|
| `watch?v=`, `youtu.be/`, `/shorts/`, `/live/`, `/embed/` | Download video | `POST /api/videos/download` with `{url, resolution?, subfolder?}` + `Authorization: Basic` |
| `/@handle`, `/channel/UC…`, `/c/…`, `/user/…` | Subscribe to channel | copy URL to clipboard, open `https://youtarr.talos00/subscriptions` |
| `/playlist?list=…` | Subscribe to playlist | copy URL to clipboard, open `https://youtarr.talos00/subscriptions` |

A `watch?v=…&list=…` URL is treated as a **video** (matching the API's own behaviour:
the playlist part is ignored). The popup additionally offers "subscribe to this
playlist" when `list=` is present.

### Settings (`chrome.storage.local`)

| Setting | Default | Notes |
|---|---|---|
| Youtarr base URL | `https://youtarr.talos00` | |
| BasicAuth username / password | empty | Sent as `Authorization: Basic`; stored in `chrome.storage.local` — **not** `sync`, which would replicate the credential through the user's Google account |
| Default subfolder | empty | Maps to the endpoint's `subfolder` override |
| Default resolution | empty (server default) | One of 360/480/720/1080/1440/2160 |

Only `subfolder` and `resolution` are offered because they are the only per-request
overrides `POST /api/videos/download` honours. Folder layout (flat vs per-video) is
NOT per-request settable — it follows the channel's setting or the global default.

### Error handling

| Case | Behaviour |
|---|---|
| 401 / 403 | "Check your credentials in Settings" + link to options |
| 302 to auth.talos00 | Means the BasicAuth route is missing/misconfigured — show "API route not reachable; is the Traefik bypass deployed?" |
| 429 | Surface Youtarr's rate-limit message |
| Network failure | "Cannot reach Youtarr at <base URL>" |
| Not a YouTube page | Popup shows a disabled state explaining what it needs |

Because credentials live in `chrome.storage.sync`, a 401 is the expected first-run
state; the popup must make that recoverable rather than look broken.

## Testing

- `lib/detect.js` is pure and gets unit tests covering every URL form above, plus the
  `watch?v=…&list=…` ambiguity and non-YouTube URLs. This is where the real logic is.
- `lib/api.js` tested against a stub for the 401/429/302/network cases.
- Manual: load unpacked, exercise all three flows against the live instance.
- Server-side: verify `Path(/api/videos/download)` returns 401 without credentials and
  200 with them, and that every OTHER path still 302s to Authentik — the regression
  that would matter most is accidentally widening the bypass.

## Out of scope

- Batch/queue operations (no API support)
- Firefox (MV3 differences; revisit if wanted)
- Reading download status/progress in the popup
- Any content-script DOM automation (explicitly rejected — see C2 above)
