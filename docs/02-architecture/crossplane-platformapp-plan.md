# Plan: `PlatformApp` — a Crossplane v2 control-plane API to DRY the add-a-service bundle

## Context

Adding an app to talos-homelab today means hand-writing ~8–10 resources that recur near-identically
across every app: a Traefik `IngressRoute` (+ HTTP→HTTPS redirect twin + middleware), external-dns
annotations, a CNPG `Cluster` + `ScheduledBackup` + reflected MinIO creds, an `ExternalSecret`, a
`Deployment`/`Service`/`PVC`, gethomepage annotations, and — for SSO apps — an authentik OIDC blueprint
in 3-way secret lockstep. We just finished a cleanup epic (Kyverno mutate/generate, reflector, kustomize
base/instance) that collapsed the *cluster-wide* invariants; the remaining repetition is the **per-app
resource graph**, which those mechanisms can't collapse. A Crossplane v2 Composition can: one
higher-level CR → the whole graph, generated consistently.

**Honest ROI (drives scope):** for *pure in-cluster* objects a Composition buys little over Flux, which
already reconciles them — so this is **not** a retrofit of the working fleet. It earns its keep as a
**reusable template for net-new full-stack apps**, as the **authentik+DB+ingress+OIDC lockstep**
coordinator, and ultimately when the *same* CR also provisions **external infra Flux structurally can't**
(Cloudflare DNS/tunnels, later AWS). We're already on **Crossplane v2** (chart 2.3.4, provider-kubernetes
v1.2.1) — no v1→v2 migration.

**Operator decisions (this session):**
- **Scope:** build `PlatformApp` for **net-new apps** + do **one proof migration** (linkwarden) to
  validate the data-safe path, **then gate** on whether to migrate more. Do NOT mass-retrofit.
- **Authentik OIDC:** **tackle the full trio now** (hardest piece — see Phase 1C).
- **Horizon:** in-cluster bundle first; **Cloudflare/external-infra is Phase 3** (the real justification).

## Design

**Layered XRDs (not a monolith)** — each variant (grafana external-DB, immich generator-secret,
plausible 4-route, zipline forward-auth) breaks a *different* seam; layering lets a variant opt a whole
stanza out instead of a monolith `if`-explosion. Three `apiextensions.crossplane.io/v2`, `scope: Namespaced` XRDs:

- **`PlatformApp`** (`platform.talos.io`) — the front door. Emits exposure (IngressRoutes + middleware +
  external-dns), gethomepage identity, optional PVC/Deployment/Service; `database{}`/`oidc{}` stanzas
  make it compose nested `PostgresDatabase`/`OidcClient` XRs. Tier-1 CR is ~6 lines via defaults.
- **`PostgresDatabase`** — wraps CNPG `Cluster` + `ScheduledBackup` (invariant barman/MinIO block); relies
  on CNPG's generated `<name>-postgres-app` secret (already reflected by Kyverno `reflect-cnpg-app-secrets`).
- **`OidcClient`** — the authentik trio (Phase 1C).

Composition = **Pipeline mode**, `function-go-templating` (renders each resource as a provider-kubernetes
`Object`) + `function-auto-ready`. The full schema/knobs (~18, grouped Core/Exposure/Identity/Data/Obs)
and the linkwarden/zipline exemplars are captured in the exploration notes; representative files:
`applications/home-automation/base/linkwarden/`, `applications/zipline/`, `applications/crossplane-demo/`.

### The three non-negotiable integration rules (the "get it right" backbone)

1. **Flux owns ONLY the XR file; Crossplane owns the composed graph.** No composed resource appears as a
   Flux-applied file. The XR's Flux Kustomization uses `wait: false`.
2. **Kyverno-disjoint fields (SSA correctness):** the emitted `IngressRoute` manifest **sets** the unique
   homepage annotations (`enabled/name/group/icon/description/widget.*`) and **OMITS** the three Kyverno-
   derived keys (`gethomepage.dev/instance`, `siteMonitor`, `href` — from
   `homepage-instance-assignment` + `homepage-annotation-derivation`). Under SSA, disjoint field managers ⇒ Kyverno's add-if-absent
   mutations are never reverted.
3. **`${CLUSTER_DOMAIN}` doesn't reach composed manifests** (they bypass Flux postBuild) — the XR carries
   `clusterDomain` (it *is* a git manifest, so it's substituted), later a Crossplane `EnvironmentConfig`.

## Phase 0 — Prerequisites (BLOCKING; the safety model rests on these)

Files: `applications/crossplane-demo/crossplane-provider.yaml`, `infrastructure/base/operators/crossplane/helmrelease.yaml`.

1. **Bump Crossplane to latest v2 patch** (currently 2.3.4) + pin provider-kubernetes.
2. **Install functions** as `pkg.crossplane.io/v1` `Function`s: `function-go-templating`, `function-auto-ready`
   (pin latest tags). v2 Compositions are Pipeline-only → go-templating is mandatory.
3. **Enable provider-kubernetes SSA** — `--enable-server-side-apply` arg on the provider
   `DeploymentRuntimeConfig`. **OFF by default in v1.2.1**; without it the provider client-side-applies,
   owns the whole object, and reverts Kyverno every reconcile (permanent flap). Verify with
   `kubectl get ingressroute <canary> -o yaml --show-managed-fields` → provider owns only its fields,
   Kyverno owns `siteMonitor/href/instance` under a different manager.
4. **Enable management policies** — `--enable-management-policies` on the provider. **Without it,
   `["Observe","Update"]` silently no-ops** and stateful objects fall back to FullControl (delete risk).
5. **Extend provider-kubernetes RBAC** — add verbs to the `provider-kubernetes-admin` ClusterRole for
   `postgresql.cnpg.io` (clusters, scheduledbackups), `traefik.io` (ingressroutes, middlewares),
   `external-secrets.io` (externalsecrets), `platform.talos.io` (postgresdatabases, oidcclients).
   Core/apps kinds already covered.

## Phase 1 — Author XRDs + Composition, prove on GREENFIELD (zero existing state)

- **1A. Tier-1 greenfield (stateless):** a net-new `whoami`-class app (Deployment+Service+IngressRoute+ES,
  no DB) — full `["*"]` policies are safe (no data). Prove render → apply → self-heal → GitOps round-trip.
- **1B. Tier-2 greenfield (net-new DB):** a brand-new full-stack app whose CNPG `Cluster` Crossplane
  creates **from empty** (`Create` is safe — no data to lose). Prove CNPG-ready gating
  (`readiness: DeriveFromConditions` + `DependsOn`), backups, the DATABASE_URL handoff (app reads
  `<name>-postgres-app` `uri` — do NOT re-template the password), and the flow-through: Kyverno stamps
  the derived annotations, `externalsecret-defaults` fills the ES store/refresh, reflector fans out creds.
- **1C. Authentik OIDC trio (the hard workstream — "tackle now"):** make `OidcClient` composable end-to-end.
  Blocker today: two touchpoints live *inside* the authentik HelmRelease values (`blueprints.configMaps`
  mount list + worker `!Env`) that a Composition can't patch per-app. **Proposed approach (verify first):**
  (a) one-time authentik HelmRelease change to discover blueprints from **all ConfigMaps carrying a label**
  (`app.kubernetes.io/component: blueprint`) via a projected volume, so a composed blueprint ConfigMap
  auto-loads with no per-app HelmRelease edit; (b) use an ESO **Password generator** for the client secret
  (as immich already does — no 1Password), one Secret in ns `authentik` + reflected to the app ns, injected
  to the worker via `envFrom` a labeled secret set. Then `OidcClient` emits: the generator Secret + the
  labeled blueprint ConfigMap + the app-side reflected secret — zero-touch per app. **Highest-risk step
  (touches the IdP)** — do it behind a throwaway test app + confirm authentik discovers the blueprint before
  wiring a real app.

## Phase 2 — One proof migration (linkwarden), DATA-SAFE, then GATE

Migrate exactly one existing stateful app to prove the adoption path; **the CNPG `Cluster`+PVC must never
be deleted**. provider-kubernetes *adopts* (SSA-merge, no recreate) but force-wins conflicts and a CR
delete can cascade `Object` GC → CNPG delete → data loss. Sequence:

1. **Pre-flight:** fresh CNPG backup + `pg_dump` artifact; patch the PV reclaim policy to `Retain` for the
   window; snapshot field managers.
2. **`prune: false` FIRST** — split linkwarden into its own Flux Kustomization with `prune: false` so
   removing files later can't reap the live `Cluster`. (This single setting is the difference between a
   safe handoff and a disaster.)
3. **Adopt Observe-only** — apply the `PlatformApp` with every existing-resource `Object` at
   `managementPolicies: ["Observe"]` (pure read, zero writes). Confirm all `Object`s `SYNCED`, field
   managers unchanged, app healthy — proves the rendered manifests match reality before any write.
4. **Widen per-leaf, low-risk first** — IngressRoutes/Service/Deployment → `["*"]`; ExternalSecret/PVCs/
   ScheduledBackup → `["Observe","Update"]`; **CNPG `Cluster` → `["Observe","Update"]` permanently** +
   `deletionPolicy: Orphan`.
5. **Remove file duplication** — `git rm` the now-composed YAMLs (prune:false ⇒ no deletion), leaving Flux
   owning only the XR file. Ends the dual-writer condition.
6. **Verify + soak 48h**, then **GATE**: decide whether migrating more existing stateful apps is worth it
   (recommendation: no — keep the rest Flux-owned).

Rollback is clean at every step (Observe/Update ⇒ Cluster never deleted; prune:false ⇒ no Flux reap).

## Phase 3 — The external-infra horizon (what actually justifies Crossplane)

Once the in-cluster bundle is proven, add a provider so the *same* `PlatformApp` renders external infra
Flux can't: install **provider-cloudflare**, add an `exposure.external.dns` path that emits a Cloudflare
DNS record / tunnel alongside the k8s objects (we already run cloudflare-ddns + external-dns). This is the
point Crossplane stops being redundant with Flux. Later horizon (out of scope now): provider-sql for
in-Postgres roles, provider-aws for the burst-compute direction.

## Critical files
- `applications/crossplane-demo/crossplane-provider.yaml` — add Functions, extend RBAC, enable SSA +
  management-policies on the DeploymentRuntimeConfig (Phase 0)
- `infrastructure/base/operators/crossplane/helmrelease.yaml` — version bump; XRD/Composition wiring
- new `infrastructure/base/platform/` (or similar) — the 3 XRDs + Compositions + Functions
- `infrastructure/base/authentik/helmrelease.yaml` + `*-blueprint.yaml` + `externalsecret.yaml` —
  the label-discovery + generator-secret change for Phase 1C
- `applications/home-automation/base/linkwarden/` + `clusters/catalyst-cluster/home-automation.yaml` —
  the Phase 2 migration target (split out, prune:false)
- `infrastructure/base/kyverno-policies/homepage-annotation-derivation.yaml` — defines the annotations the
  Composition must OMIT (rule 2)

## Guardrails (defense-in-depth against the CNPG-delete cascade + ownership fights)
- Stateful `Object`s permanently `["Observe","Update"]` + `deletionPolicy: Orphan`; PV reclaim `Retain`.
- New Kyverno policy: **deny** any `Object` whose manifest is a `postgresql.cnpg.io/Cluster` carrying
  `Create`/`Delete` in managementPolicies — turn the invariant into an admission guardrail.
- Keep the platform/data-plane (CNPG operator, ESO, traefik, authentik) **100% Flux-native, never behind
  an XR** — an app-layer Crossplane outage must not touch the data plane (single-replica Crossplane = SPOF).
- Never leave a resource in both a Flux path and a Composition (the flap condition).

## How this gets tracked (this session: beads only, NO implementation)

Per operator instruction, this session **files the plan as a beads epic + phased child tasks** for later
execution — **no code is written now**. Epic `[EPIC] Crossplane v2 PlatformApp control-plane API`, with
children mirroring the phases: P0 (bump v2 / functions / enable SSA / enable management-policies / extend
RBAC), P1 (author 3 XRDs / author Composition+guardrail / prove Tier-1 greenfield / prove Tier-2 greenfield
/ **authentik OIDC trio** — highest risk), P2 (data-safe linkwarden migration proof → gate), the Kyverno
`Object`-can't-Create/Delete-CNPG guardrail, and P3 (provider-cloudflare external-infra). Dependencies wired
P0 → P1 → P2, P3 gated on P1.

## Verification (end-to-end)
- **Phase 0:** provider shows both flags; canary `Object` → `--show-managed-fields` proves disjoint
  ownership with Kyverno (no revert over 3 reconcile cycles).
- **Phase 1:** greenfield `PlatformApp` Ready; homepage tile renders; Kyverno-derived annotations present
  and stable; CNPG `Cluster` Ready, backup lands in `s3://cnpg-backups/<name>`; a `kubectl delete
  ingressroute` (stateless leaf only) self-heals. OIDC: authentik discovers the composed blueprint, login works.
- **Phase 2:** linkwarden migrated with `Cluster` pod age + PVC UID **unchanged** throughout; bookmarks +
  Meili search + SSO intact; `crossplane beta trace platformapp/linkwarden` clean.
- **Phase 3:** a `PlatformApp` with `external.dns` creates the Cloudflare record; deleting the XR removes it.
