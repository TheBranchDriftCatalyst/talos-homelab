# Blueprint — `system-graph`: live Catalyst-themed topology graph web UI

> Construction plan for epic **TALOS-gsgh**. Cold-start executable: each step is self-contained —
> a fresh agent can execute any unblocked step without reading the others.
> Design record / annotation model: `docs/02-architecture/routing-and-auth-topology.md`.
> Reviewed adversarially 2026-10-25 (Opus); C1–C4 corrections applied — see "Review corrections".

## Objective

A live, annotation-derived, Catalyst-themed topology graph of the homelab — **both** a dedicated
page (`system-graph.talos00`) **and** an injected applet overlay — rendered with the EXISTING
`catalyst-ui` ForceGraph, fed by a Go backend that joins live cluster state, with SVG/PNG export.
End goal: a looksmaxed flex for r/homelab. Scope = maximal (App/Service/Database/Repo/Applet nodes;
serves/owns-db/deployed-from/depends-on/talks-to/netpol edges), so **layout/clustering is the
make-or-break** — and (per review) that clustering is net-new ENGINE work, not a config tweak.

## Phase plan + v1 re-scope (AUTHORITATIVE — dev-team 2026-10-25)

The PM/Architect/Dev/QA review was unanimous: maximal scope fights the primary goal (a legible,
shareable screenshot), and the showpiece rides on the one component that doesn't exist yet
(clustering). Re-scoped by the operator:

- **v1 = MVP.** Dedicated page `system-graph.talos00` only, the **4 STATIC declarative edge kinds**
  (serves / owns-db / deployed-from / depends-on), **clustering/collapse as a v1 PREREQUISITE**
  (not the last step), a **golden-fixture oracle + legibility bar**, and SVG/PNG export.
  Steps: **S1, S2a, S2b, S3, S4, S8** (all P2).
- **Phase 2.** The **applet rail (S5)** and the **Hubble talks-to + netpol flow edges (S7)** —
  the latter is a streaming/sampled data model needing its own aggregated/decay pipeline + tolerance
  tests, not the v1 batch pipeline.
- **Phase 3.** Deeper annotation enrichment (S6 `catalyst.graph/depends-on`, non-CNPG datastore
  attribution) beyond what intrinsic derivation gives for free.

**Clustering is a v1 GATE, re-sequenced to the front.** The page never ships as a hairball: if the
collapse/convex-hull/semantic-zoom engine (S2b) slips, ship the documented **dagre-grouped STATIC
fallback** instead — but something legible gates S3, it is not deferred.

**DERIVATION PRINCIPLE — intrinsic-first, annotations as a thin layer on top.** The graph is built
primarily by interrogating the **live k8s API for INTRINSIC relationships** that exist whether or
not anyone annotated: `ownerReferences`, Service label-selectors → pods, IngressRoute → service,
CNPG `Cluster` → owning namespace, Flux/ArgoCD provenance labels, `CatalystCNPGAppDB` claims.
Annotations (`gethomepage.dev/*`, `catalyst.graph/*`) are an **enrichment layer** for display,
grouping, and logical edges **where intrinsic data is thin — never the primary source.** Therefore
an un-annotated app **still renders** from its intrinsic facts, flagged `unknown-provenance`, and is
**never silently omitted** (a missing node is invisible and worse than a wrong one). This is the
answer to QA's "no oracle / annotation-drift" concern: intrinsic relationships are closer to ground
truth than annotations, and the golden fixture (S8) pins them.

## Review corrections (what the adversarial pass changed)

- **codeloc reuse is small, not "80%"**: `dev-overlay/internal/codeloc/codeloc.go` has **no
  client-go** (deliberately — 11 MB scratch image). It consumes 4 JSON files produced by a separate
  **kubectl CronJob** (`dev-overlay/k8s/base/code-locations/{cronjob,rbac,sync-script}.yaml`,
  `alpine/k8s`) and outputs `map[host]Location` — a host→repo map, **not** nodes/edges. The only
  reusable asset is its ArgoCD-decisive-over-Flux **repo-attribution tier** (1 of 5 node kinds, 1 of
  6 edges). The backend is a new build, RBAC modeled on `code-locations/rbac.yaml` (not kubeview).
- **Hubble doesn't fit the batch-JSON model** → moved entirely into S7 (streaming/periodic ingest).
- **ForceGraph types are hardcoded unions**: `NodeKind`/`EdgeKind` in
  `catalyst-ui/lib/components/ForceGraph/types/index.ts` are closed unions
  (`"container"|"network"|…`). Adding App/Service/Database/Repo/Applet **widens shared types** →
  S2 is NOT additive; it touches `ReactD3Graph`, `useGraphFilters`, `VisibilityState`,
  `GraphNavigator`, `DockerGraphConfig`. The Docker story must still typecheck.
- **Clustering is net-new engine code**: no node collapse/expand, no convex hulls, no semantic
  zoom/LOD exist today (`_zoomScale` is captured but unused). Split into S2a (config+types) + S2b
  (engine) with a concrete fallback.
- **Cross-repo publish gate**: `system-graph` is NOT in the yarn workspace; it imports catalyst-ui
  from the registry. Real edge is **S2 merged → catalyst-ui published → S3**.
- **Edge wire-contract**: backend emits `{src,dst,kind}`; `ReactD3Graph` `enrichGraph()` hydrates
  the type-required `source`/`target` node refs at runtime. Backend must NOT embed node objects.

## Repos & workflow (multi-repo)

| Repo | Hosts | VCS | PR workflow |
|---|---|---|---|
| `panda/system-graph` **(new)** | Go backend + kubectl-dump CronJob + frontend SPA + `k8s/{base,talos00}` | **Forgejo** | branch → PR → `.forgejo/workflows/ci.yml` (runner `node:22-bookworm`, **no** third-party actions, **no** `docker login` — read-only `DOCKER_CONFIG`, plain `docker build` not buildx, `fetch-depth:0`). Template: `panda/dev-overlay`. |
| `catalyst-ui` (existing, published lib `@thebranchdriftcatalyst/catalyst-ui`) | `ForceGraph/config/ClusterGraphConfig.ts` + shared-type widening + the clustering engine feature | GitHub | normal PR **+ version bump + publish** (gates S3) |
| `talos-homelab` (existing) | ArgoCD `Application` + `ImageUpdater` CR + (applet) `CatalystInjectedApplet` | GitHub | branch → PR (lefthook; commit via private `GIT_INDEX_FILE` — 58 nav-e2e artifacts force-staged) |

Image → Zot `registry.knowledgedump.space/talos00-registry/system-graph:sha-<7>`.
ArgoCD source = in-cluster Forgejo `http://forgejo.forgejo.svc.cluster.local:3000/panda/system-graph.git`.

## Reuse (load-bearing prior art — validated 2026-10-25)

- **Frontend renderer** `catalyst-ui/lib/components/ForceGraph/` — exports `ForceGraph`, `Legend`,
  `NodeDetails`, `FilterPanel` (confirmed). `GraphData.nodes` is `Record<id, NodeData>`; edges accept
  the wire shape `{src,dst,kind}` (hydrated by `enrichGraph`). `GraphConfig<TNodeKind,TEdgeKind>` is
  generic; the DATA/visibility types are closed unions that must be widened (C2). Deps present:
  `d3 ^7.9`, `dagre ^0.8.5`, **`@dagrejs/dagre ^3.1.1`** (prefer the @dagrejs one; legacy `dagre`
  drives `utils/layering/dagre.ts` today — confirm before extending).
- **Repo-attribution tier** `dev-overlay/internal/codeloc/codeloc.go` — reuse ONLY the
  ArgoCD-over-Flux host→repo normalization logic (`Derive` L256, ArgoCD tier L326, Flux tier L362,
  `collapse` L407). The k8s read is the sibling kubectl CronJob, not this Go.
- **kubectl dump pattern** `dev-overlay/k8s/base/code-locations/{cronjob,rbac,sync-script}.yaml` —
  the model for S1's cluster read (extend the GVR list; scope RBAC `get/list` only).
- **Annotation discovery** `infrastructure/base/themepark/server/nav/build_nav.py`.
- **Deploy templates** `infrastructure/base/argocd/applications/{dev-overlay,logairr}.yaml`;
  ImageUpdater CR `infrastructure/base/argocd/image-updater/dev-overlay-image-updater.yaml`
  (registered in `argocd/image-updater/kustomization.yaml`) — **note: `image-updater/`, not
  `applications/image-updater/`** (N1); ingress `infra-control/kubeview/websecure-ingress.yaml`
  (`CatalystWebSecureIngress`); applet `dev-overlay/k8s/talos00/applet.yaml` +
  `infrastructure/base/catalyst-injected-applet/`.
- **DB ownership** CNPG `Cluster` via `CatalystCNPGAppDB` claim in the owning app's ns; secret
  `<name>-postgres-app` reflected into the app ns.

## Dependency graph & parallelism

```
S0 scaffold ─┬─► S1 backend (dump+nodes+3 static edges -> /api/graph)  ─┐
             ├─► S2a ClusterGraphConfig + shared-type widening ─► S2b clustering ENGINE ─┐
             └─► S6 depends-on annotation (independent)                                   │
                                                                                          ▼
   (S1 merged) + (catalyst-ui PUBLISHED after S2a/S2b) ───────────────► S3 dedicated app ─► S4 export
                                                                                          ├─► S5 applet
                                                                                          └─► S7 Hubble/netpol
```
- **Parallel after S0:** S1 (Go, system-graph) ∥ S2a (TS, catalyst-ui) — contract fixed by the
  string-kind `GraphData`. S6 independent (talos-homelab annotations).
- **Serial:** S2a → S2b; **S3 needs S1 merged AND catalyst-ui published** (C4); S4/S5/S7 need S3;
  S7 also needs S2b's edge toggles + S1's dump extended for flows.
- **Model — strongest:** S1 (join correctness), S2b (clustering engine). Default: S0, S2a, S3, S4,
  S5, S6, S7.
- **Multi-PR steps (flagged):** S1 ≈ 1 PR after Hubble removed; S3 = 2 PRs (system-graph SPA +
  talos-homelab wiring); S2 = S2a + S2b (2 PRs).

---

## S0 — Scaffold `panda/system-graph` (Forgejo repo + CI + k8s skeleton)
**Repo:** system-graph · **Model:** default · **Depends:** none · **Parallel with:** S1/S2a/S6

**Context brief.** No repo exists. First-party apps live on in-cluster Forgejo, deploy via ArgoCD.
`panda/dev-overlay` is the twin to copy. Needs base/overlay split + a Forgejo CI that builds+pushes
to Zot under the runner constraints.

**Tasks.** Create the Forgejo repo (mint a `forgejo` admin token like the catalyst-themepark push,
revoke after). Copy dev-overlay's `.forgejo/workflows/ci.yml` (incl. the base-purity CI grep —
`kustomize build k8s/base | grep -nE 'registry\.talos00|192\.168|talos00|onepassword|nexus-pull'`,
which is a CI step, not a `task` target — N6), `Taskfile.yml`, `catalyst_repo.yaml`, `CLAUDE.md`.
`k8s/base/`: Namespace, Deployment (Go backend + kubectl-dump CronJob + static SPA), Service,
NetworkPolicies. `k8s/talos00/`: ESO pull secret, kustomization with image tag, ingress/applet
placeholders. CI pushes `sha-<7>`/`<describe>`/`latest`.

**Verify.** base-purity grep clean; `git push` → CI green → stub image pullable from Zot.
**Exit:** repo + green CI + stub image. **Rollback:** delete the Forgejo repo.

---

## S1 — Graph backend: extended kubectl dump + node/edge builder → `GET /api/graph`
**Repo:** system-graph · **Model:** STRONGEST · **Depends:** S0 · **Parallel with:** S2a

**Context brief.** Build a new Go backend (NOT a "fork" of codeloc — codeloc has no client-go). The
live cluster read is a **kubectl CronJob** modeled on `dev-overlay/k8s/base/code-locations/` that
dumps JSON for: IngressRoutes, ArgoCD Applications, Flux Kustomizations, GitRepositories, **CNPG
`Cluster`, `CatalystCNPGAppDB`, `CiliumNetworkPolicy`, `CatalystInjectedApplet`, Services**. The Go
reads those files (codeloc's `Load(dir)` pattern) and builds the graph. REUSE codeloc's
ArgoCD-decisive-over-Flux repo-attribution tier verbatim (that's the only directly reusable logic).
Hubble/netpol edges are OUT of this step (S7).

**Tasks.**
- kubectl CronJob + RBAC: extend `code-locations/` to the GVR list above; RBAC `get/list` ONLY,
  scoped to those GVRs (model on `code-locations/rbac.yaml`, NOT kubeview; do not broaden secret
  read — owns-db can work from the claim+label without reading secret values).
- Node extractors (5): App (IngressRoute+gethomepage, host from `Host(...)`), Service
  (`routes[].services[]`), Database (CNPG Cluster via claim ns), Repo (codeloc tier), Applet
  (`CatalystInjectedApplet`+`catalyst.nav/applet-src`).
- Edge builders (3 here): serves, owns-db (claim ns + `<name>-postgres-app` reflection),
  deployed-from (codeloc tier). Emit edges as **`{src,dst,kind}`** (do NOT embed node objects;
  `enrichGraph` hydrates `source`/`target`). Node `kind` is a string; `group`/`namespace`/`part-of`
  carried as metadata.
- Serve `GET /api/graph` (→ `{nodes:Record<id,NodeData>, edges:[{src,dst,kind}]}`) + `/healthz`;
  cache ~30s.

**Verify.** `go test ./...` (fixtures per node/edge kind; prove each can fail — no tautologies);
`curl …/api/graph | jq '.nodes|length'` ≈ 70 apps + 23 DBs via port-forward. **Exit:** valid
`GraphData`, 5 node kinds + 3 edge kinds. **Rollback:** revert PR; read-only, no cluster write.

---

## S2a — `ClusterGraphConfig.ts` + widen shared NodeKind/EdgeKind
**Repo:** catalyst-ui · **Model:** default · **Depends:** S0 · **Parallel with:** S1

**Context brief.** `config/DockerGraphConfig.ts` is the fork template, but `types/index.ts` hardcodes
`NodeKind`/`EdgeKind` as closed unions and `VisibilityState = Record<NodeKind,boolean>`, consumed by
`ReactD3Graph`, `useGraphFilters`, `GraphNavigator`, `DockerGraphConfig`. Adding the cluster kinds
is therefore a **shared-type change**, not additive.

**Tasks.** Widen `NodeKind`/`EdgeKind` (to `string`, or a union incl. both Docker + cluster kinds)
in `types/index.ts`; keep `GraphConfig<TNodeKind,TEdgeKind>` generic. Author `ClusterGraphConfig.ts`
(kinds App/Service/Database/Repo/Applet; edges serves/owns-db/deployed-from/depends-on/talks-to/
netpol; synthwave palette via catalyst-themepark tokens; legend; quick-filter presets "SSO map" /
"data layer" / "by repo"; talks-to+netpol default OFF). Use a **hand-authored synthetic fixture**
for the story (swap to S1's real snapshot once S1 lands — N2).

**Verify.** `tsc --noEmit` + `yarn build` clean **AND the existing Docker story still typechecks**;
Storybook renders ClusterGraphConfig on the synthetic fixture. **Exit:** both graph domains
typecheck; cluster config renders. **Rollback:** revert PR — note this touches shared types, so
re-verify the Docker graph after revert (NOT purely additive).

---

## S2b — Clustering engine: collapsible hulls + semantic zoom (the make-or-break)
**Repo:** catalyst-ui · **Model:** STRONGEST · **Depends:** S2a

**Context brief.** None of the anti-hairball pieces exist in `ReactD3Graph` today: no node
collapse/expand, no convex-hull rendering, no semantic zoom/LOD (`_zoomScale` is captured but
unused; `d3.zoom` only pans/zooms pixels). This is net-new SHARED engine code with blast radius on
every ForceGraph consumer (incl. the Docker graph) — scope it as engine work, not config.

**Tasks.** Collapse/expand state machine (group → super-node); convex-hull rendering per cluster
(cluster by `group` then namespace), **collapsed by default**; semantic zoom/LOD driven by the
(currently unused) zoom scale (clusters → apps → services/DBs); nested force *inside* a cluster over
a `@dagrejs/dagre` grouped backbone (N5 — pick one dagre). Keep the Docker graph working (regression
story). **Fallback (define concretely):** if collapse/LOD slips, ship a dagre-grouped STATIC layout
with edge-type toggles and a "focus selected node" mode — still legible, no hulls.

**Verify.** Storybook renders the ~70-node fixture collapsed-by-default without a hairball;
expand/zoom/LOD work; the Docker story is visually unchanged. **Exit:** collapsible semantic-zoom
graph (or the documented fallback) + Docker graph non-regressed. **Rollback:** revert; re-verify
Docker graph (shared-engine change).

---

## S3 — Dedicated app `system-graph.talos00` (first shippable showpiece)
**Repo:** system-graph (SPA) + talos-homelab (wiring) · **Model:** default
**Depends:** S1 merged **AND catalyst-ui published** (bump + `yarn publish` after S2a/S2b) · 2 PRs

**Context brief.** Wire the SPA (imports the PUBLISHED `catalyst-ui` ForceGraph + ClusterGraphConfig,
fetches S1's `/api/graph`) into a deployed SSO-gated page. system-graph is NOT in the yarn
workspace — it pulls catalyst-ui from the registry, so **catalyst-ui must be version-bumped and
published first** (or pin a git/prerelease dep and document it). Two PRs, merge SPA before wiring
(the ArgoCD app can't go Healthy until the SPA image exists).

**Tasks.** (PR1, system-graph) SPA shell loading `/api/graph` → `ForceGraph` + `ClusterGraphConfig`;
nginx static + `/api` proxy → Go; synthwave theme; `k8s/talos00` `CatalystWebSecureIngress`
(`system-graph.talos00`, LAN-only + authentik + NetworkPolicy + `catalyst-nav`) + `gethomepage.dev/*`
annotations. (PR2, talos-homelab) `infrastructure/base/argocd/applications/system-graph.yaml`
(template dev-overlay.yaml; register in `applications/kustomization.yaml`) +
`infrastructure/base/argocd/image-updater/system-graph-image-updater.yaml` (**image-updater/ dir**,
CR form, `allowTags: regexp:^sha-[a-f0-9]{7,40}$`, hand-declared finalizer; register in
`image-updater/kustomization.yaml`). No CNPG claim unless caching needs persistence (the graph is
derived live — default NO DB).

**Verify.** ArgoCD Synced/Healthy; `https://system-graph.talos00` → 302 → after login the real graph
loads (node counts ≈ cluster); nav entry appears. Real browser (Playwright), not in-cluster fetch.
**Exit:** live, SSO-gated, renders the cluster graph — **postable showpiece on its own.**
**Rollback:** re-comment the ArgoCD Application (git-off) → prune; one-file revert.

---

## S4 — SVG/PNG export (the Reddit deliverable)
**Repo:** system-graph (SPA) · **Model:** default · **Depends:** S3 · **Parallel with:** S5

**Context brief.** ForceGraph renders SVG. Add "download as SVG/PNG" + a "clean screenshot" mode
(hide chrome). **Tasks.** Serialize the live SVG with computed styles inlined (so the synthwave
palette survives) → SVG download + canvas-rasterized PNG at Reddit resolution; honor clean mode.
**Verify.** Exported SVG opens standalone with theme intact; PNG downloads. **Exit:** one-click
shareable image. **Rollback:** revert (additive UI).

---

## S5 — Applet variant (second delivery rail) — PHASE 2 (descoped from v1)
**Repo:** system-graph · **Model:** default · **Depends:** S3 · **Parallel with:** S4

**Context brief.** Expose the graph as an in-app overlay loaded by `catalyst-nav.js` on every
`*.talos00` host — the dev-overlay `CatalystInjectedApplet` pattern (hostless, same-origin under
`/catalyst/applets/system-graph/` + `/catalyst/api/system-graph/`). **Tasks.** `CatalystInjectedApplet`
claim (template `dev-overlay/k8s/talos00/applet.yaml`); compact applet bundle registering via
`window.__catalystNav.register("system-graph", render)`, reusing the S1 backend + ClusterGraphConfig
in a panel; confirm `build_nav.py` `discover_applets` advertises it. **Verify.** Applet docks in a
real browser; a broken bundle leaves the nav intact. **Exit:** reachable as page AND overlay.
**Rollback:** remove the applet claim; page unaffected.

---

## S6 — `catalyst.graph/depends-on` annotation + non-CNPG datastore attribution — PHASE 3 (enrichment)
**Repo:** talos-homelab (+ S1 backend reads it) · **Model:** default · **Depends:** S0 · **Parallel with:** S1/S2a

**Context brief.** App→app *logical* deps aren't derivable today. Define
`catalyst.graph/depends-on: <app>[,<app>]` on IngressRoutes + a label convention
(`app.kubernetes.io/part-of`) to attribute non-CNPG datastores (Dragonfly/Redis) to an owning app.
**Tasks.** Document in `docs/02-architecture/routing-and-auth-topology.md`; backfill the ~dozen
obvious edges; S1 reads them into `depends-on` edges + promotes attributed datastores to Database
nodes. **Verify.** Annotation present; S1 emits the edges; attributed store shows as a Database.
**Exit:** logical deps + non-CNPG stores in the graph. **Rollback:** annotations are additive.

---

## S8 — Golden-fixture oracle + derivation tests + legibility bar (v1)
**Repo:** system-graph · **Model:** default · **Depends:** S1 · **Blocks:** S3

**Context brief.** The graph is derived from live cluster state, so "is it correct?" needs an
oracle. Capture a read-only **golden snapshot** of the cluster (the same documents S1's joiner
reads: IngressRoutes, ArgoCD/Flux, CNPG, Services, ownerRefs) and assert deterministic node/edge
derivation against it (golden before pixels; no tautologies — mutate the fixture and prove each
derivation can fail). Because derivation is intrinsic-first, un-annotated apps MUST render as
flagged `unknown-provenance` nodes, never be omitted.

**Tasks.** Record the fixture; node/edge derivation unit tests over it; a CI coverage lint that
surfaces apps missing enrichment annotations (warn, not block); a **measurable legibility bar**
(max visible edge crossings / cluster count / time-to-find-a-node) so "legible not hairball" is
testable; SVG/PNG export verified by visual-regression against the DOM render; assert both delivery
surfaces are Authentik-gated (the graph discloses full topology).

**Verify.** Tests fail when a derivation is broken (proven by mutation); lint flags a
deliberately-unannotated app; the legibility metric computes on the ~70-node fixture. **Exit:**
derivation has an oracle + a measurable legibility gate. **Rollback:** tests are additive.

---

## S7 — Hubble talks-to + netpol edges (maximal, toggle-gated) — PHASE 2 (descoped from v1)
**Repo:** system-graph (dump+backend+SPA) · **Model:** default · **Depends:** S1, S2b, S3

**Context brief.** Runtime `talks-to` from Cilium Hubble eBPF flows + declared `netpol` from
`CiliumNetworkPolicy`. Hubble does NOT fit the batch kubectl-JSON dump (it's a stream) — ingest via
the Hubble relay API or a periodic `hubble observe --output jsonl`, aggregate to app↔app,
rate-limited. Default OFF in the UI (from S2b's toggles) so the baseline stays legible. **Tasks.**
Add a Hubble ingester (separate from the kubectl dump); parse `CiliumNetworkPolicy` for declared
edges; frontend toggles surface them OFF by default; "flows for selected node only" mode to avoid
the global hairball. **Verify.** Toggle on → selected app shows real peers; toggle off → identical
to S3. **Exit:** full mesh available, never default. **Rollback:** feature-flag off; revert ingest.

---

## Invariants (verify after every step)
- `catalyst-ui` + `talos-homelab` existing tests/lints stay green; **the Docker ForceGraph graph is
  non-regressed** (S2a/S2b touch shared code); no regression to the nav.
- Backend RBAC stays read-only `get/list`; does NOT broaden secret access.
- talos-homelab commits never sweep the 58 staged `tests/nav-e2e/.artifacts` (private `GIT_INDEX_FILE`).
- Graph legible at first paint (clusters collapsed, talks-to/netpol off) — the hairball test.

## Done = TALOS-gsgh closeable
`system-graph.talos00` live + SSO-gated, the applet docks, `/api/graph` matches the live cluster
(~70 apps / 23 DBs), clusters collapse/expand with semantic zoom (or the documented fallback),
SVG/PNG export works, and a Reddit screenshot has been taken.
