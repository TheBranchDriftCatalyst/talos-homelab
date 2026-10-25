# Blueprint — `system-graph`: live Catalyst-themed topology graph web UI

> Construction plan for epic **TALOS-gsgh**. Cold-start executable: each step is self-contained —
> a fresh agent can execute any unblocked step without reading the others.
> Design record / annotation model: `docs/02-architecture/routing-and-auth-topology.md`.

## Objective

A live, annotation-derived, Catalyst-themed topology graph of the homelab — **both** a dedicated
page (`system-graph.talos00`) **and** an injected applet overlay — rendered with the EXISTING
`catalyst-ui` ForceGraph, fed by a Go backend that joins live cluster state, with SVG/PNG export.
End goal: a looksmaxed flex for r/homelab. Scope = maximal (App/Service/Database/Repo/Applet nodes;
serves/owns-db/deployed-from/depends-on/talks-to/netpol edges), so **layout/clustering is the
make-or-break**.

## Repos & workflow (multi-repo)

| Repo | Hosts | VCS | PR workflow |
|---|---|---|---|
| `panda/system-graph` **(new)** | Go backend + frontend SPA + `k8s/{base,talos00}` | **Forgejo** (`forge.knowledgedump.space`) | branch → PR → `.forgejo/workflows/ci.yml` (runner: `node:22-bookworm`, **no** third-party actions, **no** `docker login` — read-only `DOCKER_CONFIG` bind-mount, plain `docker build` not buildx). Template: dev-overlay. |
| `catalyst-ui` (existing) | `lib/components/ForceGraph/config/ClusterGraphConfig.ts` | GitHub | normal PR |
| `talos-homelab` (existing) | ArgoCD `Application` + `ImageUpdater` + (applet) `CatalystInjectedApplet` | GitHub | branch → PR (lefthook gates; commit via private `GIT_INDEX_FILE` — 58 nav-e2e artifacts are force-staged in the index) |

Image: built → Zot `registry.knowledgedump.space/talos00-registry/system-graph`, tag `sha-<7>`.
ArgoCD source = in-cluster Forgejo `http://forgejo.forgejo.svc.cluster.local:3000/panda/system-graph.git`.

## Reuse (do NOT rebuild — these are the load-bearing prior art)

- **Frontend renderer**: `catalyst-ui/lib/components/ForceGraph/` — D3 force graph consuming
  `{nodes:{id,kind,name,...}, edges:[{src,dst,kind}]}` (`types/index.ts`). Exports `ForceGraph`,
  `Legend`, `NodeDetails`, `FilterPanel`. Config template: `config/DockerGraphConfig.ts`.
  Layout deps already present: `d3 ^7.9`, `dagre ^0.8.5`, `@dagrejs/dagre ^3.1.1`.
- **Backend join engine**: `dev-overlay/internal/codeloc/codeloc.go` — already joins ArgoCD
  Applications + IngressRoutes + Flux Kustomizations + GitRepositories into a host→repo map
  (`Derive()` L256; ArgoCD tier L326; Flux tier L362; `collapse` L407). Fork/extend, don't rewrite.
- **Annotation discovery pattern**: `infrastructure/base/themepark/server/nav/build_nav.py`
  (gethomepage.dev/* scan, group/weight, middleware-name classification).
- **Deploy templates**: `infrastructure/base/argocd/applications/{dev-overlay,logairr}.yaml` +
  `image-updater/dev-overlay-image-updater.yaml`; ingress `CatalystWebSecureIngress` (see
  `infra-control/kubeview/websecure-ingress.yaml`); applet `CatalystInjectedApplet`
  (`dev-overlay/k8s/talos00/applet.yaml` + `infrastructure/base/catalyst-injected-applet/`).
- **DB ownership**: CNPG `Cluster` via `CatalystCNPGAppDB` claim in the owning app's namespace;
  secret `<name>-postgres-app` reflected into the app ns.

## Dependency graph & parallelism

```
S0 scaffold ─┬─► S1 backend (Go join → /api/graph)   ─┐
             └─► S2 ClusterGraphConfig (catalyst-ui)  ─┼─► S3 dedicated app ─► S4 export
                                                        │                      ├─► S5 applet
                                                        │                      └─► (ship/flex)
             S6 depends-on annotation (independent) ────┘
                                                            S7 Hubble/netpol ─ after S1+S2+S3
```
- **Parallel after S0:** S1 (Go, system-graph repo) and S2 (TS, catalyst-ui repo) — different repos,
  contract fixed by ForceGraph's `GraphData` type. S6 is independent (talos-homelab annotations).
- **Serial:** S3 needs S1+S2; S4 needs S3; S5 needs S3; S7 needs S1+S2+S3.
- **Model tier — strongest:** S1 (join correctness), S2 (clustering/layout = make-or-break).
  Default: S0, S3, S4, S5, S6, S7.

---

## S0 — Scaffold `panda/system-graph` (Forgejo repo + CI + k8s skeleton)
**Repo:** system-graph · **Model:** default · **Depends:** none · **Parallel with:** S6

**Context brief.** No repo exists yet. First-party apps live on in-cluster Forgejo and deploy via
ArgoCD (house rule: "do we build the image? → yes → ArgoCD, manifests with the code"). dev-overlay
is the closest twin. The repo needs a base/overlay split (`k8s/base` portable, `k8s/talos00`
cluster-specific) and a Forgejo CI that builds+pushes to Zot under the runner constraints.

**Tasks.**
- Create the Forgejo repo via API/CLI (token minted from the `forgejo` admin like the
  catalyst-themepark push; revoke after). Scaffold from `workspace/@git-repo-template` + copy
  dev-overlay's `.forgejo/workflows/ci.yml`, `Taskfile.yml`, `catalyst_repo.yaml`, `CLAUDE.md`.
- `k8s/base/`: Namespace `system-graph`, Deployment (Go backend + static SPA), Service,
  NetworkPolicies, a `task manifests` base-purity check (fails on `registry.talos00`/`192.168.`/
  `talos00`/`onepassword`/`nexus-pull` leaking into base).
- `k8s/talos00/`: pull secret (ESO → `nexus-pull-dockercfg`), `kustomization.yaml` with the image
  tag, placeholder for the ingress/applet (added in S3/S5).
- CI: `runs-on: docker` → `node:22-bookworm`; plain `docker build` (not buildx); push
  `sha-<7>` + `<git-describe>` + `latest` to Zot; `fetch-depth: 0` for describe.

**Verify.** `task manifests` passes; `git push` triggers CI; CI pushes an image (probe pullable via
`registry.knowledgedump.space/talos00-registry/system-graph:latest`). **Exit:** repo exists, CI
green, a (stub) image in Zot.
**Rollback:** delete the Forgejo repo; nothing deployed yet.

---

## S1 — Graph backend (Go): live cluster join → `GET /api/graph`
**Repo:** system-graph · **Model:** STRONGEST · **Depends:** S0 · **Parallel with:** S2

**Context brief.** Fork `dev-overlay/internal/codeloc/codeloc.go`'s join (it already reads ArgoCD
Applications, IngressRoutes, Flux Kustomizations, GitRepositories via the k8s API with read-only
RBAC). Extend the document set with CNPG `Cluster` (`postgresql.cnpg.io`), `CatalystCNPGAppDB`
claims (`db.catalyst.io`), `CiliumNetworkPolicy`, `CatalystInjectedApplet` (`net.catalyst.io`), and
Hubble flows. Emit the exact shape `catalyst-ui/ForceGraph` consumes (see `types/index.ts`).

**Tasks.**
- Nodes: App (IngressRoute + `gethomepage.dev/{name,group,description,icon,weight}`; host from
  `Host(...)`), Service (`routes[].services[]` name+port), Database (CNPG Cluster via claim ns),
  Repo (ArgoCD `spec.source` tier-1 / Flux `kustomize.toolkit.fluxcd.io/name` tier-2, codeloc's
  normalization), Applet (`CatalystInjectedApplet` + `catalyst.nav/applet-src`).
- Edges: serves, owns-db (claim ns + `<name>-postgres-app` reflection), deployed-from, depends-on
  (Flux `dependsOn`), talks-to (Hubble — relay API or `hubble observe --output jsonl`), netpol
  (`CiliumNetworkPolicy` ingress/egress). Tag each edge `kind` + `source` so the frontend can toggle.
- Grouping metadata on nodes: `group` (gethomepage), `namespace`, `part-of`.
- Serve `GET /api/graph` (JSON) + `GET /healthz`. Read-only ServiceAccount RBAC modeled on
  kubeview (`infra-control/kubeview/deployment.yaml:14-60` — note the secrets-read exception
  comment; do NOT grant secret read beyond what owns-db strictly needs, prefer label-only).
- Cache the join (~30s TTL) so the graph endpoint is cheap under repeated loads.

**Verify.** `go test ./...` (unit-test the join against recorded fixtures — no tautological tests,
prove each edge kind can fail); `curl localhost:PORT/api/graph | jq '.nodes|length'` ≈ 70 apps +
23 DBs locally against the live cluster via port-forward. **Exit:** `/api/graph` returns a valid
`GraphData` with all 5 node kinds + at least 5 edge kinds populated.
**Rollback:** revert the PR; no cluster write (read-only RBAC).

---

## S2 — `ClusterGraphConfig.ts` + clustering/layout (the headline work)
**Repo:** catalyst-ui · **Model:** STRONGEST · **Depends:** S0 · **Parallel with:** S1

**Context brief.** `catalyst-ui/lib/components/ForceGraph/config/DockerGraphConfig.ts` is a complete
reference domain-config (node kinds, edge kinds, status filters, quick-filter presets, legend).
Fork it to `ClusterGraphConfig.ts`. Maximal scope = hairball risk, so clustering is the deliverable,
not an afterthought. The `GraphData` contract is fixed by `types/index.ts` (matches S1's output).

**Tasks.**
- Node kinds App/Service/Database/Repo/Applet; edge kinds serves/owns-db/deployed-from/depends-on/
  talks-to/netpol; synthwave palette per kind (reuse catalyst-themepark tokens); legend; NodeDetails.
- **Clustering (make-or-break):** cluster by `gethomepage.dev/group` first, namespace second, as
  collapsible hulls — **collapsed by default**, expand on click. Semantic zoom (clusters → apps →
  services/DBs as you zoom in). dagre (existing dep) for the layered/grouped backbone; force only
  *within* a cluster — never a global uncontrolled force layout (that is what makes these look bad).
- Edge-type toggles via `FilterPanel`; **talks-to + netpol default OFF** so the default view is
  legible. Quick-filter presets (e.g. "SSO map", "data layer", "by repo").
- A "clean screenshot" mode that hides chrome/controls (for the Reddit grab).

**Verify.** Storybook story renders `ClusterGraphConfig` against a recorded `GraphData` fixture
(the ~70-node real snapshot from S1); `yarn build` + `tsc --noEmit` clean; visual check that
collapsed-by-default is legible and expand/zoom work. **Exit:** the config renders the real snapshot
without a hairball; toggles + collapse + semantic zoom functional in Storybook.
**Rollback:** revert the PR; it is additive (new file + export), no existing config touched.

---

## S3 — Dedicated app `system-graph.talos00` (first shippable showpiece)
**Repo:** system-graph (frontend) + talos-homelab (wiring) · **Model:** default · **Depends:** S1, S2

**Context brief.** Wire the SPA (consuming `catalyst-ui` `ForceGraph` + the S2 `ClusterGraphConfig`,
fetching S1's `/api/graph`) into a deployed, SSO-gated page. talos-homelab holds ONLY the ArgoCD
Application + ImageUpdater; everything else is in the system-graph repo.

**Tasks.**
- system-graph frontend: SPA shell that loads `/api/graph` and mounts `ForceGraph` with
  `ClusterGraphConfig`; synthwave theme; served by the same pod (nginx static + proxy `/api` → Go).
- talos-homelab: `infrastructure/base/argocd/applications/system-graph.yaml` (template:
  dev-overlay.yaml — `repoURL` the in-cluster Forgejo, `path: k8s/talos00`, `ServerSideApply`,
  `ignoreDifferences` for ESO/CNPG/claims) + register in that dir's `kustomization.yaml`;
  `image-updater/system-graph-image-updater.yaml` (CR form, `allowTags: regexp:^sha-[a-f0-9]{7,40}$`,
  hand-declared finalizer) + register.
- system-graph `k8s/talos00`: `CatalystWebSecureIngress` (host `system-graph.talos00`, LAN-only +
  authentik + NetworkPolicy + `catalyst-nav`) + `gethomepage.dev/*` annotations (most derived by
  Kyverno) so it auto-joins the nav; the CatalystCNPGAppDB claim only if the backend needs state
  (it likely does NOT — the graph is derived live; skip the DB unless caching needs persistence).

**Verify.** ArgoCD app Synced/Healthy; `https://system-graph.talos00` → 302 forward-auth; after
login the graph loads with live node counts ≈ cluster; nav entry appears. Verify from a real
browser (Playwright), not an in-cluster fetch (injection/SSO caveats). **Exit:** the page is live,
SSO-gated, renders the real cluster graph. **This milestone alone is a postable showpiece.**
**Rollback:** re-comment the ArgoCD Application (git-off) → ArgoCD prunes; one-file revert.

---

## S4 — SVG/PNG export (the Reddit deliverable)
**Repo:** system-graph (frontend) · **Model:** default · **Depends:** S3

**Context brief.** ForceGraph renders SVG. Add a "download as SVG/PNG" that serializes the live
SVG (+ rasterizes via canvas) and a "clean screenshot" mode (S2) that hides chrome.

**Tasks.** Export button → serialize SVG (inline computed styles so the synthwave palette survives)
→ offer SVG download + canvas-rasterized PNG. Honor the clean-screenshot toggle.

**Verify.** Click export → a standalone SVG opens correctly in a browser with the theme intact; PNG
downloads at a Reddit-friendly resolution. **Exit:** one-click export produces a shareable image.
**Rollback:** revert the PR (additive UI).

---

## S5 — Applet variant (second delivery rail)
**Repo:** system-graph · **Model:** default · **Depends:** S3 · **Parallel with:** S4

**Context brief.** Besides the dedicated page, expose the graph as an in-app overlay loaded by
`catalyst-nav.js` on every `*.talos00` host — the dev-overlay `CatalystInjectedApplet` pattern
(hostless, served same-origin under `/catalyst/applets/system-graph/` + `/catalyst/api/system-graph/`).

**Tasks.** Add a `CatalystInjectedApplet` claim (`net.catalyst.io`, template
`dev-overlay/k8s/talos00/applet.yaml`); build a compact applet bundle that registers via
`window.__catalystNav.register("system-graph", render)` and reuses the S1 backend + S2 config in a
panel layout. Verify `build_nav.py`'s `discover_applets` advertises it (defaults.applets).

**Verify.** From a real browser inside any `*.talos00` app, the applet docks and renders; a broken
bundle leaves the nav intact (silent-fail discipline). **Exit:** graph reachable as both a page and
an overlay. **Rollback:** remove the applet claim; the dedicated page is unaffected.

---

## S6 — `catalyst.graph/depends-on` annotation + non-CNPG datastore attribution
**Repo:** talos-homelab (+ system-graph backend reads it) · **Model:** default · **Depends:** S0 · **Parallel with:** S1/S2

**Context brief.** App→app *logical* deps are not derivable today (Hubble talks-to is noisy; Flux
`dependsOn` is infra-only). Define a `catalyst.graph/depends-on: <app>[,<app>]` annotation
convention on IngressRoutes, backfill the obvious edges, and a label convention
(`app.kubernetes.io/part-of`) to attribute non-CNPG datastores (Dragonfly/Redis) to an owning app.

**Tasks.** Document the annotation in `docs/02-architecture/routing-and-auth-topology.md`; backfill
the dozen obvious edges (arr-stack → prowlarr, apps → their Dragonfly, etc.); S1 backend reads the
annotation into `depends-on` edges + promotes attributed datastores to Database nodes.

**Verify.** The annotation appears on backfilled routes; S1 emits the new edges; a datastore with
the label shows as a Database node. **Exit:** logical deps + non-CNPG stores in the graph.
**Rollback:** annotations are additive; remove them (no behavior change elsewhere).

---

## S7 — Hubble talks-to + netpol edges (maximal, toggle-gated)
**Repo:** system-graph (backend + frontend) · **Model:** default · **Depends:** S1, S2, S3

**Context brief.** Add runtime `talks-to` edges from Cilium Hubble eBPF flows and declared `netpol`
edges from `CiliumNetworkPolicy`. Default OFF in the UI so the baseline view stays legible; power
users opt into the full mesh.

**Tasks.** S1 ingests Hubble (relay API / `hubble observe`, aggregated to app↔app, rate-limited);
parse `CiliumNetworkPolicy` for declared edges; frontend toggles (from S2) surface them, OFF by
default; consider a "show flows for selected node only" mode to avoid the global hairball.

**Verify.** With the toggle on, selecting an app shows its real observed peers; with it off the
view is unchanged from S3. **Exit:** the full mesh is available but never the default.
**Rollback:** feature-flag off; revert the edge ingestion.

---

## Invariants (verify after every step)
- `catalyst-ui` + `talos-homelab` existing tests/lints stay green; no regression to the nav.
- The backend RBAC stays read-only and does NOT broaden secret access.
- talos-homelab commits never sweep the 58 staged `tests/nav-e2e/.artifacts` (private `GIT_INDEX_FILE`).
- The graph is legible at first paint (clusters collapsed, talks-to/netpol off) — the hairball test.

## Done = TALOS-gsgh closeable
`system-graph.talos00` live + SSO-gated, the applet docks, `/api/graph` matches the live cluster
(~70 apps / 23 DBs), clusters collapse/expand with semantic zoom, SVG/PNG export works, and a
Reddit screenshot has been taken.
