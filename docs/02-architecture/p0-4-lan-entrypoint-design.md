---
type: architecture
status: current
covers:
  - traefik
  - unifi-port-forward
freshness: tracks-code
tickets:
  - TALOS-a8vo
bluf: Traefik routes on `Host()` regardless of entrypoint, so internal services are WAN-reachable by Host-spoof; the fix is a second, unforwarded LAN entrypoint pair rather than inverting the WAN entrypoint default.
---

# P0-4 — Host-spoof remediation: dedicated LAN entrypoint

> Epic **TALOS-a8vo**, P0-4. The companion audit that opened this
> (`ingress-accessibility-audit-2026-09.md`) has since been pruned from `docs/`; this page is
> the surviving record of the design.
> Status: **entrypoints and middleware chains have landed in the manifests; zero IngressRoutes
> have been migrated onto them.**

## TL;DR

- **Exposure:** roughly half the routed hostnames have no `ipAllowList`/`forwardAuth` — the
  exact ratio came from the since-pruned audit, so re-measure with
  `tests/ingress-accessibility/` rather than quoting it. The origin WAN IP is published at
  the `knowledgedump.space` apex (grey-cloud), and Traefik routes on `Host:` **regardless of which
  entrypoint** the request arrived on. So an attacker who hits `origin_ip:443` with
  `Host: grafana.talos00` is routed straight to Grafana — every internal `*.talos00` service is
  WAN-reachable by Host-spoof.
- **The audit's proposed fix ("invert the web/websecure entrypoint default to `lan-only`") is NOT
  cleanly implementable.** A Traefik entrypoint-default middleware applies to **every** router on
  that entrypoint and **cannot be opted out per-router**. Inverting the default would `lan-only` the
  ~11 genuinely-public routes too (forge/registry/zipline/auth/…), blocking Cloudflare + WAN clients.
- **Chosen design:** a **dedicated LAN entrypoint pair** — `weblan` (:8081) / `websecurelan` (:8443)
  — carrying a **default `lan-only`** middleware. `web`/`websecure` (:80/:443) stay WAN-facing and
  keep only the ~11 public routes. Internal `*.talos00` / `*.priv.talos00` routes migrate onto the
  LAN entrypoints. Isolation = the LAN hostPorts are **not forwarded by the edge router** (so WAN
  cannot reach them) + the `lan-only` default (defense-in-depth).
- **Why this is safe:** internal and public routes are **already separate IngressRoute objects**
  (e.g. `forge.knowledgedump.space` and `forge.talos00` are distinct routers, often in the same
  file). The migration rule is purely domain-based — move `*.talos00`, leave `*.knowledgedump.space`
  / `*.amberdark.net`. Public routes are never touched, so they cannot break; a missed internal
  route merely stays as-exposed-as-today (acceptable incompleteness, per the "never break public
  over completeness" priority).

## Why not entrypoint-default `lan-only` (the retracted fix)

Traefik binds entrypoint-default HTTP middlewares via
`--entrypoints.<ep>.http.middlewares=...`; they run on **all** routers on that entrypoint and there
is **no per-router opt-out**. Today `web`/`websecure` carry `strip-authentik-headers,bouncer` as
defaults. Adding `lan-only` there would apply it to the public routes too:

- Cloudflare-proxied public hosts (e.g. `zipline.knowledgedump.space`) arrive from Cloudflare edge IPs —
  not RFC1918 — so `lan-only` (10/8+172.16/12+192.168/16+loopback) would **403 them**.
- Grey-cloud public hosts (`forge`/`registry`/apex) arrive from real WAN client IPs — also blocked.

So inverting the default trades a Host-spoof hole for an outage of every public service. Rejected.

## Why not per-port `hostIP` binding

The audit floated "a 3rd entrypoint bound to `hostIP`=LAN address." **Not viable here:** Traefik
runs as a **5-node DaemonSet** and each node has its own LAN IP, so there is no single `hostIP`
value to template into the chart's port spec. Isolation therefore comes from **(a) the edge router
not forwarding the LAN hostPorts** and **(b)** the `lan-only` default middleware — not from hostIP.

## What landed in this branch (`agent/p0-security`)

`infrastructure/base/traefik/helmrelease.yaml`:

1. **New entrypoints** `weblan` (port/hostPort 8081) and `websecurelan` (port/hostPort 8443).
   No hostPort collisions in the repo. They are **INERT** until routes declare them — with no
   router attached they return 404, so landing them alone changed nothing user-visible, which
   is still true: no IngressRoute in the repo names either entrypoint.
2. **Default middleware chains** for the LAN entrypoints:
   `--entrypoints.weblan.http.middlewares=traefik-strip-authentik-headers@kubernetescrd,traefik-bouncer@kubernetescrd,traefik-lan-only@kubernetescrd`
   (and the same for `websecurelan`). Same strip+bouncer as web/websecure, **plus** `lan-only`.

No IngressRoutes were migrated in this branch — see the cutover plan below.

> Residual: `lan-only` still admits the pod CIDR (`10.0.0.0/8 ⊇ 10.244/16`), so the LAN entrypoints
> are perimeter-only (off-LAN blocked, east-west open). That is the existing P1
> `lan-only`-excludes-pod-CIDR follow-up and is not regressed here.

## The public-route set (STAYS on web/websecure — do NOT migrate)

Enumerated from the manifests (routes whose `Host()` is on a public zone):

| Host                             | Source                                                                        | Notes                                                                                                                                                                                                                                        |
| -------------------------------- | ----------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `linkwarden.knowledgedump.space` | `applications/home-automation/base/linkwarden/ingressroute.yaml`              | web+websecure                                                                                                                                                                                                                                |
| `whoami.knowledgedump.space`     | `infrastructure/base/whoami/ingressroute.yaml`                                | web+websecure (live-probe target L5)                                                                                                                                                                                                         |
| `auth.knowledgedump.space`       | `infrastructure/base/authentik/ingressroute.yaml`                             | login plane                                                                                                                                                                                                                                  |
| `auth.priv.knowledgedump.space`  | `infrastructure/base/authentik/ingressroute.yaml`                             | web+websecure; **review**: `priv` on a public zone                                                                                                                                                                                           |
| `forge.knowledgedump.space`      | `infrastructure/base/forgejo/ingressroute.yaml`                               | web+websecure                                                                                                                                                                                                                                |
| `registry.knowledgedump.space`   | `infrastructure/base/registry/zot/ingressroute.yaml`                          | web+websecure                                                                                                                                                                                                                                |
| `trap.knowledgedump.space`       | `infrastructure/base/security/iocaine/ingressroute.yaml`                      | tarpit                                                                                                                                                                                                                                       |
| `bg.knowledgedump.space`         | `infrastructure/base/authentik/login-background/ingressroute.yaml`            | login background asset                                                                                                                                                                                                                       |
| `analytics.knowledgedump.space`  | `applications/crossplane-demo/plausible/ingressroute.yaml`                    | `/js/` + `/api/event` only                                                                                                                                                                                                                   |
| `zipline.knowledgedump.space`    | `applications/zipline/ingressroute.yaml`                                      | web+websecure                                                                                                                                                                                                                                |
| authentik outpost callback route | `infrastructure/base/authentik/ingressroute.yaml` (`/outpost.goauthentik.io`) | the ONE outpost route; must stay unauth on websecure. Its HostRegexp covers `*.talos00` **and** `*.priv.knowledgedump.space`, so migrating `*.talos00` routes to the LAN entrypoints without moving this one breaks every forward-auth login |
| `boomtime.knowledgedump.space`   | **ArgoCD-managed** (sister repo, not in this Flux tree)                       | verify separately; drift-allowlist                                                                                                                                                                                                           |

Everything else — `*.talos00`, `*.priv.talos00`, `teak.talos00`, `homepage.talos00`,
`${CLUSTER_DOMAIN}`/`${DOMAIN}` (both = `talos00`) — is internal and migrates to the LAN entrypoints.

## Cutover plan (main session, post-merge, live)

Do this as **verified batches**, not one big commit, because each moved service must be reachable on
the new port and TLS must resolve on `websecurelan`.

**Step 0 — router (do FIRST; it is currently WRONG):** the isolation story assumes the edge
router does **not** forward `:8081` or `:8443` to the nodes. It does.
`infrastructure/base/unifi-port-forward/portforward-rules.yaml` declares a `cluster-web` rule
with `externalPort: "80,443,8443"` → `192.168.1.54`, so **`websecurelan` is WAN-reachable
today**. Migrating an internal route onto `websecurelan` before that rule is narrowed to
`80,443` would move it from one WAN-exposed entrypoint to another, leaving only the `lan-only`
middleware between the internet and it — which is defence-in-depth, not the perimeter this
design promised. Narrow the rule first, then confirm, then migrate. (The comment in
`infrastructure/base/traefik/helmrelease.yaml` asserting these hostPorts are not forwarded
predates that rule and is wrong for the same reason.)

**Step 1 — communicate the LAN port change.** Internal bare-hostname access changes from
`http://grafana.talos00` (implicit :80/:443) to `https://grafana.talos00:8443` (or `:8081` plaintext).
`/etc/hosts` entries are unchanged (still `192.168.1.54 ...`). Options to soften this: keep the
`private-domain-redirect` path, or add a LAN DNS/hosts convenience — out of scope here.

**Step 2 — migrate in batches.** For each internal IngressRoute (Host = `*.talos00`/`*.priv.talos00`):
change `entryPoints: [web]` → `[weblan]` and `[websecure]` → `[websecurelan]`. **Do NOT** touch a
route whose Host is on `knowledgedump.space`/`amberdark.net` (many files mix both — edit per-router,
never a blanket file sed). Suggested batch order (lowest-risk first):
`whoami`/`kube-ops-view`/`hubble` → the rest of the admin `SENSITIVE_HOSTS` → media/arr → homepage.
After each batch: `flux reconcile` and verify `https://<host>.talos00:8443` loads on the LAN and that
`https://<origin_ip>/` with `Host: <host>.talos00` now 404s.

**Step 3 — regression net.** Extend `tests/ingress-accessibility/` with a contract that internal
`*.talos00` routes are NOT on `web`/`websecure` once migration completes (fail-closed guard against a
new internal route landing on the WAN entrypoint). Track as a follow-up ticket.

## Live verification (after full migration)

```bash
# 1. Internal service reachable on the LAN entrypoint (from a LAN host):
curl -kso /dev/null -w '%{http_code}\n' https://grafana.talos00:8443/   # expect 200/302 (auth)

# 2. Host-spoof against the WAN entrypoint is dead:
curl -kso /dev/null -w '%{http_code}\n' --resolve grafana.talos00:443:<ORIGIN_IP> \
     https://grafana.talos00/                                            # expect 404

# 3. Public routes still work on :443 (unchanged):
curl -kso /dev/null -w '%{http_code}\n' https://forge.knowledgedump.space/   # expect 200/302

# 4. LAN entrypoint really is LAN-only (from off-LAN / WAN): connection refused / 403.
```

The offline net already asserts the invariants that don't need a cluster; run
`python3 tests/ingress-accessibility/test_ingress_accessibility.py` (and `--live` from the LAN).

---

## Related Issues

- **TALOS-a8vo** — ingress/network accessibility audit; P0-4 host-spoof.
- Follow-up (P1): exclude pod CIDR (`10.244.0.0/16`) from `lan-only` so the LAN entrypoints are not
  merely perimeter-only.
- Follow-up: `auth.priv.knowledgedump.space` — confirm whether a `priv` host belongs on the public zone.
