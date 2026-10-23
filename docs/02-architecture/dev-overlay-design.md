# dev-overlay — design & project handoff

**Status:** approved design, not yet implemented · **Date:** 2026-10-22
**Scope:** 4 repos — `workspace/dev-overlay` (new), `workspace/catalyst-themepark`,
`workspace/catalyst-ui`, `talos-homelab`

## TL;DR

A developer-annotation applet injected into every app on `*.talos00`: enter annotation
mode anywhere, point at a component, leave a note. Notes live in a CNPG database and
resolve back to the repo they came from.

- It rides **inside** the existing navbar injection — a second `rewriteBody` cannot be
  chained, so `catalyst-nav.js` gains a slot API and an applet loader.
- Bundle and API are mounted **same-origin** under `/catalyst/`, which kills CSP, CORS and
  cookie-scope problems in one move.
- Gated `HostRegexp` + `lan-only`, the two-control pattern adopted after a real disclosure.
  Never served publicly.
- The catalyst-ui implementation is **deleted**, not ported. This is v3.

Start at **M0** (fix the themepark drift) then **M1** (slot API + loader). Full milestone
table and the fresh-session handoff are below.

---

## Context

The developer-annotation system in catalyst-ui (`lib/dev/annotation/`, ~2,240 LOC) is
orphaned. Its source-location feature reads `_debugSource`, which **React 19 deleted**, so
no annotation has ever carried a file path. Its sync endpoint is never mounted
(`i18nApiPlugin` is absent from both Vite configs, and `/api` is proxied to the LLM
operator), so localStorage is the only live tier. There are **three drifted `Annotation`
type definitions**, **three competing UI generations** (the documented one is the dead
one), and **zero tests**. It only works inside catalyst-ui's own app.

The goal is to lift that idea out to the cluster: enter annotation mode on **any** app
served on `*.talos00`, select a component, attach a note; notes persist in a real database;
each note resolves back to the repo it came from. Along the way, turn "inject an applet"
into a named, reusable abstraction instead of a copy-paste of the navbar's chain.

**Decisions taken with the operator:**
1. **Solo** — notes to self. No identity, permissions, or resolve/assign workflow.
2. **All apps, degraded anchoring** — first-party apps get rich anchoring; third-party apps
   get DOM-level anchoring with `repo: unknown`. Capability detected at runtime.
3. **Reify as a Crossplane XRD** (`CatalystInjectedApplet`), matching the house
   `CatalystWebSecureIngress` / `CatalystCNPGAppDB` pattern.
4. **Loader delivery** — nav.js dynamically loads the applet. One rewriteBody, not two.
5. **Two-tier code location** — stable interface now, coarse resolver in v1.

---

## Objectives

1. **Annotate any app, from anywhere in the cluster.** Enter annotation mode on any of the
   ~40 apps on `*.talos00`, point at something, leave a note. No per-app integration work,
   no code change in the annotated app.
2. **Make notes durable and queryable.** Move off per-origin `localStorage` — which today
   means a note left on Sonarr is invisible from Radarr and dies with the browser profile —
   onto one Postgres the whole cluster shares.
3. **Make notes actionable.** Every annotation should answer "which repo do I open to fix
   this?" Exactly today where we can; repo-level where we can't; honestly `unknown` where
   there is no repo at all.
4. **Turn injection into an abstraction.** "Inject an applet" becomes a declarative claim,
   not a copy-paste of a four-middleware chain plus an asset route plus manifest plumbing.
   The second applet should be cheap; today it is a research project.
5. **Extract and delete — this is v3, not a port.** The catalyst-ui implementation is the
   donor of the *idea*, not the code. Its ~2,240 LOC get **deleted**, not migrated: the
   source-location path is dead, there are three drifted `Annotation` types, and three
   competing UI generations of which the documented one is the unused one. Carry forward
   exactly two things — the fiber-walk technique (`ComponentInspector.tsx:41-46`) and the
   `todo|bug|note|docs` × `low|medium|high` taxonomy, which is good and worth keeping.
   Everything else is designed fresh against the cluster-wide requirements.
6. **Tighten the contracts between the four repos.** Today the couplings are informal and
   one of them is already broken: catalyst-ui → themepark is a *hand-port enforced by a
   comment* (and the palette has silently diverged — `--neon-gold` means two different
   colors); themepark → talos-homelab is enforced by `build.sh --check` but is **red right
   now**; and dev-overlay is about to add two more edges (it consumes catalyst-ui
   components and docks into themepark's bar). Every edge should end this project with a
   mechanical check, not a comment. Where the cheap fix is a shared artifact rather than a
   check, note it for the DRY epic rather than doing it inline.

## Success criteria

- Annotation mode reachable on every `*.talos00` app carrying the nav, from the bar itself.
- A note survives a browser restart, a pod restart, and is visible from a *different* app.
- Every stored annotation carries a `code_location` with an explicit `confidence`.
- `curl -H 'Host: sonarr.talos00' https://<wan-ip>/catalyst/applets/...` from off-LAN
  returns **not-200**. Verified from outside, not with `--resolve`.
- A broken or missing applet bundle leaves the navbar fully functional and prints nothing
  to the host app's console.
- `task lint:theme-drift` green, and the gear feature lives in `src/60-nav.js`.
- Adding a *second* applet requires one claim and zero edits to shared middleware.

## Non-goals (explicitly out of scope)

- **Multi-user anything.** No identity, attribution, permissions, sharing, or comment
  threads. Solo scratchpad. (Revisit only if a second person ever uses it.)
- **An issue tracker.** `status` is `open|done` and nothing more. Beads already tracks work;
  this must not grow into a competitor.
- **Public exposure.** Never injected on `*.knowledgedump.space`. The nav-split epic is the
  named prerequisite for *any* public injection, and it is not this project.
- **Theming or restyling apps.** That is catalyst-themepark's job and stays there.
- **Editing app content.** Annotations are a layer *over* apps; the applet never mutates
  the host application's DOM beyond its own overlay.
- **"Open in editor".** Attractive, and the `exact` tier makes it possible later, but it
  needs a local agent and is not in M0–M6.

---

## Two findings that shape everything

### 1. You cannot chain a second `rewriteBody`

A `catalyst-inject-devoverlay` middleware stacked onto the ~40 routes already carrying
`catalyst-nav` would **silently no-op** — the documented failure mode at
`infrastructure/base/monitoring/v2-otel/hyperdx-rum/middlewares.yaml:12-17`, enforced by
comment at `infrastructure/base/monitoring/grafana-instances/ingressroute.yaml:37-38`.

So the applet ships **inside the existing injection**: `catalyst-nav.js` gains an applet
loader, and dev-overlay is a separately-versioned bundle it fetches at runtime.

```
rewriteBody (unchanged, 40 routes)
  └─ <script src=/catalyst/resources/catalyst-nav.js>
       ├─ builds the bar
       ├─ reads manifest.applets[]
       └─ injects <script src=/catalyst/applets/dev-overlay.js>
            └─ docks into the bar via the slot API
                 └─ fetch /catalyst/api/dev-overlay/*  (same-origin)
```

### 2. Mount the applet and its API **same-origin**, under `/catalyst/`

This is the single most load-bearing structural decision. Serving the bundle and the API
on each app's **own origin** — not on a `dev-overlay.talos00` host — collapses three
separate problems at once:

- **CSP.** qBittorrent sends `script-src 'self'`; `middlewares.yaml:364-368` notes
  same-origin `/catalyst/` assets already satisfy it, but an applet **POSTing** elsewhere
  would need a per-app `connect-src` repair, and a shared `catalyst-csp` is unsafe because
  `rewriteHeaders` has no conditionals.
- **CORS.** No preflight, no allowlist of 40 origins.
- **Cookies.** A `.talos00` cookie is rejected as a public suffix
  (`catalyst-nav.js:238-247`); same-origin sidesteps the question entirely.

### Never public — reuse the two-control pattern

`infrastructure/base/themepark/asset-route.yaml:22-57` records a **confirmed disclosure**:
the asset route once had no Host matcher and served `catalyst-nav.json` — which enumerates
every internal host — on all 28 public hostnames. The fix uses two controls because each
closes the other's bypass:

```yaml
- match: PathPrefix(`/catalyst/`) && HostRegexp(`^[a-z0-9-]+\.talos00$`)
  priority: 10000          # must beat apps' catch-all Host() rules
  middlewares:
    - {name: lan-only, namespace: traefik}   # FIRST
```

`HostRegexp` alone is defeated by a client-supplied `Host:` header against the WAN IP
(measured: 200, full manifest). `lan-only` closes it because the source address is the one
thing a client cannot choose. **dev-overlay's routes copy this verbatim.** Never verify the
gate with `curl --resolve` from the LAN — assert on Traefik's logged `ClientHost`.

---

## Repo layout

House rule is **"do we build it?"** (`docs/02-architecture/dual-gitops.md:217-221`) — we
build it, so manifests live *with the code* and **ArgoCD** owns it.

| Repo | Change |
|---|---|
| `workspace/dev-overlay/` **(new)** | applet bundle, API server, `k8s/{base,talos00}` |
| `workspace/catalyst-themepark/` | slot API + applet loader in `src/60-nav.js` |
| `workspace/catalyst-ui/` | remove `lib/dev/annotation/` (last milestone) |
| `talos-homelab` | ArgoCD `Application`, the `CatalystInjectedApplet` XRD |

Scaffold from `workspace/@git-repo-template` (`catalyst_repo.yaml`, `lefthook.yml`,
`Taskfile.yml`, `CLAUDE.md`). Follow `logAIrr` as the closest complete first-party
template. ArgoCD `Application` copies `infrastructure/base/argocd/applications/logairr.yaml`
— `ServerSideApply=true`, `PruneLast=true`, the ESO `ignoreDifferences` block, and for the
CNPG cluster both `managedFieldsManagers: [manager]` **and** the
`argocd.argoproj.io/compare-options: ServerSideDiff=true` annotation (without the
annotation the managedFields entry silently does nothing — `boomtime.yaml:10-14`).

### Hosted on in-cluster Forgejo (fully-private path)

Repo created with the Forgejo CLI **at M2, from inside the repo** — not before. This puts
dev-overlay on the `logAIrr` / `fchat-bouncer` chain rather than the GitHub/ghcr one:

- **ArgoCD source:** `http://forgejo.forgejo.svc.cluster.local:3000/panda/dev-overlay.git`.
  The in-cluster Service URL is deliberate — sync must not depend on Traefik, external-dns
  or the WAN (`logairr.yaml:27-30`). Credentials come from the existing `repo-creds` prefix
  secret (`infrastructure/base/argocd/externalsecret-forgejo-repo.yaml`); **its URL prefix
  must keep matching** or the new repo silently fails to authenticate.
- **CI:** `.forgejo/workflows/ci.yml`. Constraints that bite, all from `logAIrr`:
  `runs-on: docker` means `node:22-bookworm`; **no third-party actions** (the runner pins
  `DEFAULT_ACTIONS_URL` to code.forgejo.org); **no `docker login`** — the runner
  bind-mounts a read-only `DOCKER_CONFIG` holding the Zot credential, which is also why it
  must be plain `docker build` and **not** buildx (buildx needs a writable `$DOCKER_CONFIG`).
- **Push to the public host, pull from the internal one.** `registry.talos00` is a Pi-hole
  LAN name CoreDNS has never heard of, so an in-pod push dies with `no such host`. Push to
  `registry.knowledgedump.space`, deliberately **unproxied** so Cloudflare's 100 MB body cap
  cannot truncate a layer. Image path is `registry.talos00/talos00-registry/dev-overlay`.
- **Three tags**, and only one drives deployment: `sha-<7>` (immutable, what ArgoCD tracks),
  `<version>` from `git describe` (needs `fetch-depth: 0`), and `latest` for humans.
- **Image updater:** `allowTags: "regexp:^sha-[a-f0-9]{7,40}$"`, excluding `latest`/`main`.
  With mutable tags allowed the first reconcile pins `:latest`, which then produces no
  manifest diff — ArgoCD never syncs, pods never restart, and the updater still logs
  `errors=0`. The finalizer must also be declared by hand (image-updater v1.2.2 fails its
  own finalizer-add with `spec.namespace: Required value`).
- The app namespace needs its own kubelet pull secret (ESO → `nexus-pull-dockercfg`), and
  Zot challenges `/v2/` even with `defaultPolicy: ["read"]`.

---

## Data model

One `CatalystCNPGAppDB` claim (`db.catalyst.io/v1alpha1`, namespaced, Crossplane v2).
House rules: `instances: 3` (never 1 — local-path is WaitForFirstConsumer and a
single-instance cluster gets a PDB with `disruptionsAllowed=0` that deadlocks drains),
`storageClass: local-path` (never NFS), and `backupSchedule` is **required with no
default** so the fleet stagger isn't collapsed. Taken slots run 02:00→04:30; **claim 04:45**.

Collapse the three drifted types into one record. Solo, so no author column:

```
id            uuid pk
created_at    timestamptz        updated_at timestamptz
host          text        -- "sonarr.talos00"   (the app)
url           text        -- full href at capture time
kind          text        -- todo | bug | note | docs
priority      text        -- low | medium | high
body          text
anchor        jsonb       -- { selector, textSnippet, componentName, treePath }
code_location jsonb       -- { repo, path, line, confidence }
status        text        -- open | done     (solo-grade, not a workflow)
```

`anchor.treePath` is deliberately **stored but not trusted as identity**. catalyst-ui hashed
the full ancestor-name path into an `instanceId`, and because that path includes Radix and
Framer internals, any wrapper refactor silently orphaned every annotation beneath it, with
no detection. Here the stable key is `(host, url, selector)`; treePath is a *hint* for
re-anchoring and for display.

---

## Anchoring — three tiers, detected at runtime

| Tier | Mechanism | `confidence` |
|---|---|---|
| React app we build | fiber walk + `data-catalyst-src` stamp | `exact` |
| Any React app | fiber walk (`__reactFiber$*`) → component name, treePath | `repo-only` |
| Any app at all | `document.elementFromPoint` → CSS selector + text snippet | `unknown` |

The fiber walk is worth porting from `catalyst-ui/lib/dev/annotation/ComponentInspector.tsx:41-46`
— it is the one genuinely good part of the old system, and it works on any React app in the
same realm, which covers most of the arr-stack. Fix its filter while porting: the current
`buildTreePath` only drops names containing `Context`/`Provider`/`ForwardRef`, so
`Primitive.div` and `motion.div` leak into the path.

### CodeLocation (the approved contract)

```ts
interface CodeLocation {
  repo?: string          // "catalyst-ui"
  path?: string          // "lib/ui/button.tsx"
  line?: number
  confidence: "exact" | "repo-only" | "unknown"
}
```

**v1 (coarse, ships now):** a `host → repo` map. Every annotation gets a repo, derived
from data we already have. **v2 (precise, later):** a Vite plugin stamping
`data-catalyst-src="repo:path:line"`, only for apps we build. The resolver is pluggable, so
the applet needs no change when v2 lands.

---

## Reifying the pattern: `CatalystInjectedApplet`

> **Naming flag.** The operator called this `CatalystInjectedMiddleware`. I'd argue for
> `CatalystInjectedApplet`, because the composite deliberately does **not** mint a
> middleware — minting a second `rewriteBody` is the one thing that silently breaks here,
> and a name promising a middleware invites exactly that mistake from the next reader. It
> renders routes plus registration. Operator's call; the plan says `Applet` pending a
> decision, and it is a rename either way.

Because a second `rewriteBody` is forbidden, the XRD **registers** an applet rather than
minting an injector. One namespaced claim renders:

1. the same-origin asset IngressRoute (`PathPrefix(/catalyst/applets/<name>/)` +
   `HostRegexp` + `lan-only` + `priority: 10000`) pointed at the applet's Service
2. the same-origin API IngressRoute (`/catalyst/api/<name>/`), same gating
3. discovery metadata so the nav sidecar advertises it

Discovery stays **derived, not configured**, matching how the nav already works: the XRD
stamps `catalyst.io/applet: "true"` plus name/version/entrypoint annotations, and
`build_nav.py` grows an `applets[]` section the same way it builds `groups[]` today. No new
transport, no new file, no pod restart — and the existing `CONFIG_KEYS` allowlist
(`build_nav.py:71-79`) already gives per-host enable/disable for free.

Client-side, `assign()` (`catalyst-nav.js:98-105`) copies only declared keys, so the
loader must validate `applets[]` the same way — a manifest is consumed inside third-party
apps and must never be able to inject arbitrary script URLs. **Allowlist to same-origin
`/catalyst/` paths only.**

---

## Prerequisite: fix the themepark drift (mine)

`catalyst-themepark` publishes three artifacts into talos-homelab via `./build.sh --publish`,
guarded by `task lint:theme-drift`. Today's commit `b2999734` (the settings gear) was written
**directly into the vendored copy**, never into `src/60-nav.js`. The files are now **557 vs
424 lines** and the drift check fails on `main`.

Port the gear back into `src/60-nav.js`, rebuild, republish, confirm `task lint:theme-drift`
is green. This is step zero — the slot API and loader both land in that same file, and
building on a drifted base would deepen exactly the divergence the check exists to catch.

---

## This is too large for one spec — proposed decomposition

| # | Sub-project | Output |
|---|---|---|
| **M0** | Fix themepark drift | `lint:theme-drift` green |
| **M1** | Nav slot API + applet loader | nav can dock and load *any* applet; no applet yet |
| **M2** | dev-overlay scaffold: repo, API, CNPG, ArgoCD | `/catalyst/api/dev-overlay/health` answers |
| **M3** | The applet: anchoring + annotation UI | end-to-end note on a real app |
| **M4** | CodeLocation coarse tier | every annotation carries a repo |
| **M5** | `CatalystInjectedApplet` XRD | pattern reified; dev-overlay migrated onto it |
| **M6** | **Delete** `lib/dev/annotation/` from catalyst-ui | one system, not two |
| **M7** | Tighten the four repo edges | every coupling has a mechanical check |

**M6 is a deletion, not a migration.** Scope: `lib/dev/annotation/` (10 files), the
annotation half of `lib/dev/context/AnnotationContext.tsx`, `server/api/annotations.ts`,
the handler wiring in `build/vite-plugin-i18n-api.ts:3,54`, the stale committed
`annotations.json`, the HMR ignore at `vite.app.config.ts:75`, and the annotation section
of the `DeveloperTab` docs. **The one real obstacle** is that `DevProviders` bundles
annotations *and* i18n text editing (`DevProviders.tsx:33-34`), and the i18n half has four
live consumers — so `DevProviders`/`DevModeToggle` must be split, not deleted wholesale.

**M7** closes the loop on objective 6: a check on catalyst-ui → themepark token parity
(the `--neon-gold` inversion is a live bug a check would have caught), `lint:theme-drift`
wired into CI rather than only lefthook, and a dev-overlay → catalyst-ui version pin.

**Recommendation: spec and build M0+M1 first.** They are the risky, load-bearing part
(touching the script injected into 40 apps), they are independently valuable — a slot API
makes *any* future applet cheap — and they can ship without a database existing. M2–M6
each get their own spec→plan→implement cycle.

**M1 carries the real risk**: `catalyst-nav.js` is injected into ~40 third-party apps. A
throw in the loader must never surface into someone else's app — the existing manifest
fetch is deliberately silent after three tries (`catalyst-nav.js:531-542`) and the loader
must match that discipline. Also note the z-index minefield: the bar is 9998 under a 9999
scanline overlay, and an annotation tool that must *receive clicks over app content* lands
squarely in it.

---

## Follow-up epic (file in beads, do not do inline)

DRY opportunities surfaced during analysis:

- **Palette duplicated by hand** between `catalyst-ui/lib/contexts/Theme/styles/catalyst.css`
  and `catalyst-themepark/src/00-tokens.css`. **Real bug:** `--neon-gold` / `--neon-yellow`
  are *inverted* between them, so `--neon-gold` is not the same color in the two systems
  despite a comment claiming they are in sync.
- **Three font delivery mechanisms** for the same three faces: a Google Fonts link
  (`fonts.ts:43`), a second independent `@import` of the same URL (`playground.css:10`),
  and base64 woff2 inlined by `build.sh:19-41`.
- **Effects implemented twice** — scanlines/grid in `catalyst-ui/.../effects/scanlines.css`
  behind `data-effect-scanlines`, and again in themepark layer 30 behind
  `data-catalyst-anim`. Two pictures, two switches.
- **15 near-identical injector+chain pairs** in `themepark/middlewares.yaml` — a candidate
  for the same XRD treatment.
- **catalyst-ui annotation debris**: three drifted `Annotation` types, three UI generations
  (the documented one is dead), an unreachable `updateAnnotation`, a committed stale
  `annotations.json`, and exporters the docs advertise that do not exist.
- **`.claude/commands/new-service.md`** self-describes as outdated — still recommends
  `fatboy-nfs-appdata` and `external-secrets.io/v1beta1`, and predates the Crossplane
  composites.
- **No `net.catalyst.io` composite for public routes**, so adding a middleware across the
  LAN surface is still a ~40-file edit — the same scaling problem `asset-route.yaml` solved
  for assets.

---

## Handoff — orienting a fresh session

**This document is the handoff.** It lives here, in the repo that owns the injection
plumbing all of this hangs off. Copy it into `workspace/dev-overlay/SPEC.md` when that repo
is created at M2, and keep this copy as the architecture-side record.

A fresh session should be able to start from this file alone — it carries the objectives,
the decisions and *why* they were taken, the traps, the milestone order, and the
verification commands. It deliberately does not assume any of the conversation that
produced it.

**The four repos and who owns what**

| Repo | Role | Deployed by |
|---|---|---|
| `workspace/dev-overlay` | applet + API + `k8s/` | ArgoCD, from in-cluster Forgejo |
| `workspace/catalyst-themepark` | **source of truth** for nav.js/css | published into talos-homelab |
| `talos-homelab` | vendored nav artifacts, XRD, ArgoCD `Application` | Flux |
| `workspace/catalyst-ui` | donor of the annotation idea; component library | ArgoCD |

**Read these first, in this order**

1. `infrastructure/base/themepark/middlewares.yaml:1-130` — the injection contract. The
   whole rule is "put ONE middleware reference on the route that serves its HTML."
2. `infrastructure/base/themepark/asset-route.yaml:22-75` — the disclosure writeup. Explains
   why both `HostRegexp` and `lan-only` are required and why neither alone is enough.
3. `infrastructure/base/themepark/server/nav/build_nav.py:130-200` — the derived-discovery
   philosophy the applet registry must follow.
4. `infrastructure/base/themepark/server/resources/catalyst-nav.js:379-439` — `build()`,
   where the slot API has to go.
5. `catalyst-themepark/build.sh:140-175` — the publish contract. **Note `build.sh:143` is an
   explicit file list for the nav-only subset while `:103` is a glob**, so a new
   `src/65-applet.css` lands in `catalyst.css` automatically and is **silently missing**
   from `catalyst-nav.css` — i.e. absent from the 40 nav-only apps, which is most of the
   cluster. Add it to both lists.

**Five traps that have already cost time in this cluster**

- **Two `rewriteBody` middlewares never chain.** Silent. The second regex just never fires.
- **Flux postBuild envsubst runs in strict mode over every rendered resource**, including
  inline shell scripts. A `${VAR}` in a CronJob command fails the *entire* Kustomization,
  not one resource. `kubectl kustomize` does **not** catch it; `flux build kustomization`
  does. Opt a resource out with `kustomize.toolkit.fluxcd.io/substitute: disabled`.
- **Never `rollout restart` a Flux-managed workload** — Flux strips `restartedAt` and you
  get two bounces. `kubectl delete pod` instead.
- **Never verify an IP gate with `curl --resolve` from the LAN.** Inbound WAN is DNAT-only
  so the source survives; it is hairpinned LAN traffic that gets SNAT'd. Test from cellular
  or read Traefik's logged `ClientHost`.
- **`task lint:theme-drift` is currently red** (M0). Do not build on the vendored copy.

**Conventions that are easy to get wrong**

- `base/` must carry nothing cluster-specific — `bt-radar/Makefile:177-186` has a `manifests`
  target that *fails* if base leaks `registry.talos00`, a `192.168.` IP, a `talos00` host
  match, `onepassword`, or `nexus-pull`. Copy that check.
- **ArgoCD has no envsubst.** Sister-repo overlays write hostnames literally
  (`logAIrr/k8s/talos00/ingressroute.yaml:4-6`); only Flux-managed manifests get
  `${CLUSTER_DOMAIN}`.
- Never put `web` and `websecure` on one IngressRoute — a Kyverno policy injects `tls: {}`,
  making the router TLS-only and silently 404-ing the plaintext route.
- Give `/api` a `priority: 100` route with **no** middlewares: forward-auth answers 302,
  which native clients and websocket upgrades cannot follow, and `catalyst-nav` must not
  rewrite JSON bodies.
- OpenGym is deliberately excluded from injection (PWA — the service worker caches injected
  markup and serves a frozen copy offline). The applet inherits that exclusion.

**Open questions deferred, not forgotten**

- Does the applet need a kill switch independent of the nav's gear toggle? (Probably yes —
  an applet that traps clicks needs an escape hatch that does not require the bar.)
- Re-anchoring strategy when an app's DOM changes under a stored annotation. v1 stores
  enough to detect orphans (`selector` + `textSnippet`); it does not yet decide what to
  *do* with them.
- Whether M5's XRD should also absorb the 15 existing per-app injectors, or leave them.

## Verification

- **M0:** `task lint:theme-drift` exits 0; `diff` of all three artifacts is empty.
- **M1:** `flux build kustomization themepark --path infrastructure/base/themepark` (catches
  the strict-envsubst trap that `kubectl kustomize` misses); then Playwright on
  `http://grafana.talos00/login` — assert the bar still builds, 51 links, 12 groups, gear
  present, and a stub applet docks. Assert a deliberately-broken applet URL leaves the bar
  intact and logs nothing to the app's console.
- **M2:** `kubectl -n dev-overlay get cluster` reports 3 ready instances; a `Backup` with
  `method: plugin` + `pluginConfiguration.name: barman-cloud.cloudnative-pg.io` completes
  (the legacy `barmanObjectStore` method fails with "cluster has no backup section").
- **Scoping (every milestone):** from off-LAN,
  `curl -k -H 'Host: sonarr.talos00' https://<wan-ip>/catalyst/applets/dev-overlay.js`
  must not return 200. Verify from cellular or Traefik's logged `ClientHost`, never with
  `--resolve` from the LAN.

---

## Related Issues

<!-- Beads tracking for this doc -->
- **TALOS-maet** — EPIC: dev-overlay (children M0–M7 below)
  - TALOS-x0hb M0 · TALOS-fp1r M1 · TALOS-e3tl M2 · TALOS-mbee M3
  - TALOS-7ese M4 · TALOS-b1g6 M5 · TALOS-slyd M6 · TALOS-jtxp M7
- **TALOS-36m6** — EPIC: DRY the catalyst design-system + injection duplication

`bd ready` currently surfaces **TALOS-x0hb (M0)** as the only startable task; the rest are
dependency-gated into build order.
