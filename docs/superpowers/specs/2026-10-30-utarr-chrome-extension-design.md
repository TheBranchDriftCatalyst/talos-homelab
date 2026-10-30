# utarr — Chrome extension for Youtarr

**Date:** 2026-10-30
**Status:** Approved design, not yet implemented
**Extension code:** `../@catalyst-swiss-army-knife/src/applets/utarr/` (an applet in the
existing extension — NOT a new project)
**Server changes:** this repo — `applications/youtarr/` (API route) and a new static
host for CRX distribution

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
| Extension host | **Applet inside `@catalyst-swiss-army-knife`** | It is already a plugin mount point with an applet router; reuses its build, lint and Taskfile DX instead of standing up a second extension |
| Extension tooling | **Inherited TypeScript + React + webpack** | Comes with the host extension. (An earlier revision chose vanilla JS with no build step, for a standalone project — superseded.) |
| Distribution | **Self-hosted CRX + enterprise policy (B)** | Real install and auto-update without publishing. Drag-to-install `.crx` is dead and plain self-hosting needs policy anyway |

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

## Extension host: @catalyst-swiss-army-knife

utarr is an **applet** inside the existing `@catalyst-swiss-army-knife` extension, which
is already a plugin mount point. It is NOT a standalone project; an earlier revision of
this spec proposed `../chrome-ext/utarr` with vanilla JS and no build step, and that is
superseded. We inherit TypeScript + React + webpack, ESLint/Prettier, and the Taskfile.

The applet contract (`src/applets/index.ts`) is one entry:

```ts
export interface AppletRoute {
  pattern: RegExp;  // matched against hostname
  loader: () => Promise<{ default: React.ComponentType<unknown> }>;
}
```

utarr registers:

```ts
{ pattern: /^(?:.+\.)?youtube\.com$/i, loader: () => import("./utarr") }
```

That hostname pattern covers `www.`, `m.` and `music.youtube.com`. The full URL is
inspected inside the applet to decide video vs channel vs playlist.

```
src/applets/utarr/
  index.tsx   default-exported React component (the popup UI)
  detect.ts   URL -> {kind: video|channel|playlist, id}   <- the real logic
  api.ts      POST /api/videos/download
  types.ts
```

Settings live in the extension's existing Options page / Context, not a separate page.

### TASK ZERO — the manifest is invalid JSON

`manifest.json` contains a `//` comment (line 34, inside the `content_scripts` block).
Both the source and the copied `dist/manifest.json` fail `json.load`. CopyPlugin copies
it verbatim, and **Chrome refuses to load an extension whose manifest is not valid
JSON**. The extension as committed cannot load.

This is pre-existing and unrelated to utarr, but nothing here is testable until it is
fixed. Fix it FIRST, as its own commit, before any utarr code.

### Manifest additions for utarr

- `host_permissions`: `https://youtarr.talos00/*`
- `permissions`: add `clipboardWrite`
- `key`: the extension's public key — pins a **stable extension ID** across rebuilds.
  Required for policy-based install (see Distribution); without it the ID changes and
  the policy silently stops matching.
- `update_url`: points at the self-hosted `updates.xml`

### Flows

| Tab is | Action | Mechanism |
|---|---|---|
| `watch?v=`, `youtu.be/`, `/shorts/`, `/live/`, `/embed/` | Download video | `POST /api/videos/download` with `{url, resolution?, subfolder?}` + `Authorization: Basic` |
| `/@handle`, `/channel/UC...`, `/c/...`, `/user/...` | Subscribe to channel | copy URL to clipboard, open `https://youtarr.talos00/subscriptions` |
| `/playlist?list=...` | Subscribe to playlist | copy URL to clipboard, open `https://youtarr.talos00/subscriptions` |

A `watch?v=...&list=...` URL is treated as a **video**, matching the API's own behaviour
(it ignores the playlist part). The popup additionally offers "subscribe to this
playlist" when `list=` is present.

### Settings (`chrome.storage.local`)

| Setting | Default | Notes |
|---|---|---|
| Youtarr base URL | `https://youtarr.talos00` | |
| BasicAuth username / password | empty | Sent as `Authorization: Basic`; `storage.local`, **not** `sync`, which would replicate the credential through the user's Google account |
| Default subfolder | empty | Maps to the endpoint's `subfolder` override |
| Default resolution | empty (server default) | One of 360/480/720/1080/1440/2160 |

Only `subfolder` and `resolution` are offered because they are the only per-request
overrides `POST /api/videos/download` honours. Folder layout is NOT per-request
settable — it follows the channel's setting or the global default.

### Error handling

| Case | Behaviour |
|---|---|
| 401 / 403 | "Check your credentials in Settings" + link to options |
| 302 to auth.talos00 | The BasicAuth route is missing/misconfigured — "API route not reachable; is the Traefik bypass deployed?" |
| 429 | Surface Youtarr's rate-limit message |
| Network failure | "Cannot reach Youtarr at <base URL>" |
| Not a YouTube page | Applet does not load (hostname pattern); popup shows the host extension's default |

Credentials start empty, so a 401 is the expected first-run state. The popup must make
that recoverable rather than look broken.

## Build & release tooling

Existing (keep): `task build`, `task watch`, `task clean`, `task dev`, `task chrome`;
npm `build`/`watch`/`lint`/`typecheck`.

Add:

| Task | Purpose |
|---|---|
| `task package` | Build, then emit a version-stamped `utarr-<version>.zip` of `dist/` |
| `task release` | `package` + sign the CRX + regenerate `updates.xml` + print the publish step |
| `task chrome:strict` | Launch Chrome WITHOUT `--disable-web-security` (see below) |

> **DX TRAP — `task dev` passes `--disable-web-security`.**
> Harmless for most applets, but utarr's entire risk surface is a cross-origin
> authenticated call from `youtube.com` to `youtarr.talos00`. That flag hides exactly
> the failure mode we care about: it will work in `task dev` and break in a real
> browser. Every CORS/auth change MUST be verified via `task chrome:strict`.

## Distribution (self-hosted CRX + enterprise policy)

Chrome removed drag-to-install for `.crx`, and plain self-hosting without policy does
not work on current Chrome. The supported path is enterprise policy:

1. **Sign** the extension with a persistent PEM key -> `utarr.crx`. The public half goes
   into `manifest.json` as `key` so the extension ID is stable. **The PEM is a secret and
   must never be committed** — losing it changes the extension ID; leaking it lets
   someone ship a counterfeit update.
2. **Host** `utarr.crx` and `updates.xml` from a small static service in this repo,
   behind Traefik on the `*.talos00` cert. The server MUST serve `.crx` as
   `application/x-chrome-extension`; the wrong MIME type is a silent install failure.
3. **`updates.xml`** advertises the extension ID, version and CRX URL. Chrome polls it
   for auto-update.
4. **Policy** (per machine, macOS, requires sudo): an `ExtensionInstallForcelist` entry
   of the form `<extension-id>;https://<host>/updates.xml` in a Chrome managed-preferences
   plist. Note the policy points at the **XML, not the CRX**.

Rejected: unlisted Chrome Web Store — easiest install and auto-update, but it means
publishing, which the operator explicitly does not want yet. Revisit if the
per-machine sudo step becomes annoying across devices.

Accepted cost: policy install is per-machine and needs sudo. There is no MDM here, so
this is not push-button across devices.

## Testing

- `detect.ts` is pure and gets unit tests covering every URL form above, plus the
  `watch?v=...&list=...` ambiguity and non-YouTube URLs. This is where the real logic is.
- `api.ts` tested against a stub for the 401/429/302/network cases.
- Manual: `task chrome:strict` (NOT `task dev`) and exercise all three flows against the
  live instance — the dev task's `--disable-web-security` would mask CORS failures.
- Distribution: verify the CRX installs via policy on a clean Chrome profile, and that
  bumping the version in `updates.xml` triggers an auto-update.
- Server-side: verify `Path(/api/videos/download)` returns 401 without credentials and
  200 with them, and that every OTHER path still 302s to Authentik — the regression
  that would matter most is accidentally widening the bypass.

## Out of scope

- Batch/queue operations (no API support)
- Firefox (MV3 differences; revisit if wanted)
- Publishing to the Chrome Web Store, listed or unlisted
- MDM-based policy distribution (no MDM in this environment)
- Reading download status/progress in the popup
- Any content-script DOM automation (explicitly rejected — see C2 above)
