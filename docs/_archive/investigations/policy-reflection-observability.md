# Policy & Secret-Reflection Observability — Investigation

> Status: **investigation / recommendation only** (no manifests deployed). Tracking: **TALOS-4b45** (see footer).
> Scope: observe the Kyverno + emberstack/reflector machinery that auto-connects every CloudNativePG (CNPG)
> cluster into dbgate, so a **silent failure surfaces** (policy stops mutating, secret stops mirroring, a CNPG
> cluster never appears in dbgate, a controller degrades).

## TL;DR

- **The single highest-value thing to build first is a tiny "coverage reconcile" CronJob** that walks the whole
  chain end-to-end and pushes per-cluster **coverage gauges** to the existing pushgateway. It is the *only*
  approach that can see the **last hop — dbgate's `CONNECTIONS` env** — which is exactly the class of blind spot
  that made the image-updater outage invisible. Nothing already in the stack (Kyverno metrics, PolicyReports,
  KSM) can observe a Deployment's env.
- **Kyverno's own signals are necessary but not sufficient.** Prometheus metrics (per-controller, port `8000`)
  are great for *controller health* and *"did the last admission error"*, but for a `mutateExisting` policy they
  **do not** tell you whether the mutation is *currently in effect* — mutate/generate rules produce **no
  background-scan report/results entries**, only admission-event ones. PolicyReports are therefore the **wrong**
  primary signal for coverage. Verified against Kyverno docs (see Sources).
- **Reflector exposes no Prometheus metrics.** Detect its health via **state, not metrics**: the mirror's
  `reflector.v1.k8s.emberstack.com/reflected-at` / `reflected-version` annotations (freshness/drift) plus pod
  health. The coverage CronJob reads these directly.
- Everything plugs into the **existing** pipeline with **zero new infrastructure**: `PrometheusRule` CRs →
  Alloy `mimir.rules.kubernetes` → Mimir Ruler; alert routes already exist (severity-based) in the
  Alertmanager-config CronJob; dashboards via the `json/` + `resources/` GrafanaDashboard generator; the
  pushgateway already has a dedicated Alloy scraper with `honor_labels`.

**Minimum viable (~½ day):** coverage CronJob + its 3 alerts (gap / dbgate-gap / dead-man) + enable Kyverno
chart `serviceMonitor` on the 4 controllers + `KyvernoControllerDown` / `KyvernoPolicyError` alerts.
**Full:** add a CNPG `Cluster` KSM custom-resource-state metric, a dedicated `policy-reflection-ops` dashboard
(+ fill the reserved Kyverno row already sitting empty in `policy-ops.json`), reflector pod/staleness panels,
and (optional) a pure-PromQL cross-check via KSM secret annotation metrics.

---

## What we are observing (the invariant)

For **every** CNPG `Cluster` **C** in namespace **N**, all four stages must hold, or dbgate silently loses a DB:

| # | Stage | Produced by | Evidence of success |
|---|-------|-------------|---------------------|
| 1 | `C-app` secret exists in **N**, labelled `cnpg.io/cluster` | CNPG operator | secret present + label |
| 2 | `C-app` carries the `reflector.*/reflection-allowed` annotations | Kyverno `reflect-cnpg-app-secrets` (mutate) | annotation present on source |
| 3 | mirror `C-app` exists in **databases**, kept fresh | emberstack/reflector | mirror present + fresh `reflected-at` |
| 4 | dbgate Deployment env `CONNECTIONS` csv contains C's id | Kyverno `dbgate-cnpg-connections` (mutateExisting) | id ∈ CONNECTIONS csv |

A gap at **any** stage is a silent failure. Stage 4 is both the most valuable and the *only one no existing
telemetry can see*.

Machinery under observation (files):
- `infrastructure/base/kyverno/` — Kyverno 3.8.2 (app 1.18.x) install (admission/background/reports/cleanup, 1 replica each).
- `infrastructure/base/kyverno-policies/reflect-cnpg-app-secrets.yaml` — stage 2 (annotate).
- `infrastructure/base/kyverno-policies/dbgate-cnpg-connections.yaml` — stage 4 (inject dbgate env; `CONNECTIONS` recomputed cluster-wide via apiCall).
- `infrastructure/base/reflector/` — stage 3 (emberstack/reflector 10.0.63).
- `docs/patterns/cross-namespace-secret-reflection.md` — the pattern write-up (delete-drift / inert-key caveats).

---

## 1. Kyverno native observability

### 1a. PolicyReport / ClusterPolicyReport — **do not rely on these for coverage**
- Reports **are** created for `validate`, `mutate`, `generate`, `verifyImages` — **but** background scanning
  "has no effect on either generate or mutate rules for the purposes of reporting." Concretely: our two policies
  are `mutate`/`mutateExisting`, so a report entry is written **only at admission time** of the trigger secret,
  and **never refreshed by background scan**. A report is a record of a *rule execution event*, not of *current
  state*. So a PolicyReport can say "the last time this secret was admitted, the rule passed" — it **cannot** say
  "the dbgate env currently contains this cluster."
- **Verdict:** PolicyReports are fine as a *secondary* "the last admission errored" signal (watch for `result:
  error`/`fail` entries from the reports-controller), but they are the **wrong primary tool** for the coverage
  question. This is the core justification for the reconcile CronJob in §3.
- Policy `.status` (Ready condition, rule counts) is a cheap "policy loaded & accepted by the webhook" check;
  optionally surface via KSM custom-resource-state if we want a `KyvernoPolicyNotReady` alert.

### 1b. Prometheus metrics — **use these for controller health + admission errors**
Kyverno exposes metrics per controller on a ClusterIP `*-metrics` service, port **`8000`**. Relevant series
(names below are for app **1.18.x**; older releases used the `_total` suffix — **ground against Mimir before
finalizing queries**, per repo dashboard discipline):
- `kyverno_policy_results` (counter) — labels `policy`, `rule`, `rule_type` (`validate`/`mutate`/`generate`),
  `rule_execution_cause` (`admission_request`/`background_scan`), `rule_result` (`pass`/`fail`/`error`/`warn`/`skip`).
  Note: for our `mutate` rules only `rule_execution_cause="admission_request"` ever appears (no background rows).
- `kyverno_policy_execution_duration_seconds` / `kyverno_mutating_policy_execution_duration_seconds` (histograms).
- `kyverno_admission_requests_total`, `kyverno_admission_review_duration_seconds`.
- controller-runtime / client-go queue + request metrics, and `up{job=~"kyverno.*"}` for readiness.

**How to scrape here:** the Kyverno Helm chart ships a per-controller `metricsService` (default port 8000,
ClusterIP) and a `<controller>.serviceMonitor.enabled` toggle. Alloy's
`prometheus.operator.servicemonitors "default"` already discovers ServiceMonitors **cluster-wide**, so simply
enabling the chart toggles is enough — no scrape config edits. Enable on **admissionController,
backgroundController, reportsController, cleanupController**. (Alternative: hand-write a ServiceMonitor mirroring
`infrastructure/base/monitoring/version-checker/servicemonitor.yaml`; the chart-native toggle is cleaner.)

**Official Kyverno Grafana dashboards** exist (grafana.com / kyverno.io monitoring guide) but lag on metric names
(some reference `_total`). Use them as a panel *source*, not verbatim — better to extend this repo's dashboards.

---

## 2. Reflector (emberstack/reflector) observability

- **No Prometheus `/metrics` endpoint.** The controller ships no app metrics and the chart has no serviceMonitor.
  So reflector must be observed by **state + pod health**, not by its own metrics.
- **Mirror annotations tell the story** (stamped by reflector on the copy in `databases`):
  - `reflector.v1.k8s.emberstack.com/reflected-at` — ISO-8601 timestamp of last mirror write → **staleness**.
  - `reflector.v1.k8s.emberstack.com/reflected-version` — source `resourceVersion` at mirror time → **drift**
    (compare to the live source `resourceVersion`; unequal + old `reflected-at` ⇒ reflector stopped updating).
  - `reflector.v1.k8s.emberstack.com/reflects` — `namespace/name` of the source.
- **Detecting a stopped mirror or a lost source annotation:** the coverage CronJob (§3) compares
  source-present ⇢ source-annotated ⇢ mirror-present ⇢ mirror-fresh, and flags the exact broken hop.
- **Pod health:** `up` / restart count of the reflector Deployment in `kube-system` (KSM `kube_pod_*`); add a
  `ReflectorPodDown` alert. This is a wedge-class candidate for the existing `wedge-buster` CronJobs if it ever
  wedges.

---

## 3. Coverage / consistency tracking (the ops-critical bit)

Three candidate approaches, compared:

### (a) Pure PromQL count-comparison via kube-state-metrics
- **CNPG `Cluster` count** — add a `Cluster` block to the **existing** KSM `customResourceState` config
  (`kube-state-metrics/helmrelease.yaml` already does this for all Flux kinds). Emits e.g. `cnpg_cluster_info`
  (one series per cluster, labels namespace/name). Requires `rbac.extraRules` for `postgresql.cnpg.io`
  `clusters` (get/list/watch) — same "Forbidden without extraRules" gotcha the Flux CRS block documents.
- **Annotated/mirrored secret counts** — KSM's core Secret collector can emit `kube_secret_annotations` /
  `kube_secret_labels` **only if** you pass `--metric-annotations-allowlist=secrets=[reflector.v1.k8s.emberstack.com/reflected-at,reflector.v1.k8s.emberstack.com/reflection-allowed]`
  and `--metric-labels-allowlist=secrets=[cnpg.io/cluster]`. Then count source `-app` secrets, annotated
  sources, and fresh mirrors with PromQL, and add a recording rule `count(clusters) - count(mirrors)`.
- **Hard limit:** stage 4 (dbgate `CONNECTIONS` env) is **not surfaceable by KSM at all** — KSM does not expose
  Deployment env. So PromQL-only verifies stages 1–3 but is **blind to the most important hop**.
- Side cost: enabling secret annotation/label metrics cluster-wide adds (mild) cardinality and emits annotation
  **values as label values** (no secret *data*, but be deliberate — scope to the reflection keys only).

### (b) Tiny reconcile CronJob → pushgateway coverage gauges — **RECOMMENDED (primary)**
A small `alpine/k8s` CronJob (exact precedent: `infrastructure/base/vpn-gateway/rotation/cronjob.yaml`, which
already curls `http://pushgateway.monitoring:9091/metrics/job/<name>`), read-only SA, every ~15m:
1. `kubectl get clusters.postgresql.cnpg.io -A` → the authoritative cluster set.
2. For each cluster: check the `-app` source secret's reflection annotation (stage 2); check the `databases`
   mirror exists + `reflected-at` fresh (stage 3); parse dbgate's `CONNECTIONS` csv and test id membership
   (stage 4 — count csv membership, **not** raw `*_<id>` env keys, because delete-drift leaves inert orphans).
3. Push gauges to pushgateway (Alloy scrapes it with `honor_labels: true`):
   - `policy_reflection_cnpg_clusters_total`
   - `policy_reflection_annotated_total`, `policy_reflection_mirrored_total`, `policy_reflection_dbgate_connected_total`
   - `policy_reflection_coverage_gap{cluster="…",namespace="…",stage="annotate|mirror|dbgate"} 1` (per-cluster gap identity → the dashboard "gaps list")
   - `policy_reflection_last_run_timestamp` (freshness — pushgateway persists stale gauges, so a dead exporter would otherwise *lie*).
- **Only approach that closes stage 4** and yields **per-cluster** gap identity. ~60 lines, no new images, matches
  existing CronJob idioms. This is the safety net the image-updater outage lacked.

### (c) PolicyReport-based — **rejected as primary**
As established in §1a, mutate reports are admission-event snapshots with no background refresh; they cannot
represent current coverage. Keep only as a secondary "last admission errored" signal.

**Recommendation:** **(b) is primary.** Add **(a)'s CNPG `Cluster` CRS metric** regardless (cheap cluster
inventory, useful to other dashboards, and a PromQL cross-check of the CronJob's cluster count). Treat **(a)'s
secret annotation/label metrics as optional** — the CronJob already covers stages 1–3 more legibly.

---

## 4. Alerting

Mechanism: new `PrometheusRule` CR in `infrastructure/base/monitoring/v2-otel/baseline-alerts/` (Alloy's
`mimir.rules.kubernetes "rules"` syncs **all** PrometheusRules → Mimir Ruler; add the file to that dir's
`kustomization.yaml`). Routing needs **no change** — the Alertmanager-config CronJob already routes
`severity="critical"` → `discord-critical`, else `discord-default`; optionally add a `category="policy"` route.

Proposed rules (`policy-reflection-alerts.yaml`):
| Alert | Expr (sketch) | Severity |
|-------|---------------|----------|
| `PolicyReflectionCoverageGap` | `policy_reflection_coverage_gap{stage=~"annotate\|mirror"} > 0` for 15m | warning |
| `PolicyReflectionDbgateGap` | `policy_reflection_coverage_gap{stage="dbgate"} > 0` for 15m | **critical** (breaks the feature) |
| `PolicyReflectionExporterAbsent` | `absent(policy_reflection_cnpg_clusters_total)` 30m **or** `time() - policy_reflection_last_run_timestamp > 2400` | **critical** (dead-man; mirrors `ScrapeTargetsAbsent`) |
| `KyvernoControllerDown` | `up{job=~"kyverno.*"} == 0` 5m (needs §1b serviceMonitor) | **critical** |
| `KyvernoPolicyError` | `rate(kyverno_policy_results{policy=~"reflect-cnpg-app-secrets\|dbgate-cnpg-connections",rule_result="error"}[10m]) > 0` 10m | warning |
| `ReflectorPodDown` | reflector Deployment `available == 0` 10m (KSM) | warning |
| `KyvernoPolicyNotReady` (opt) | policy `.status` Ready=False via CRS | warning |

---

## 5. Dashboards

There is already an **untracked** `policy-ops.json` (+ `resources/policy-ops.yaml`) — a broad **security-posture**
board (Cilium NetworkPolicy / CrowdSec / cert-manager) that **already reserves an empty "Admission Control
(Kyverno)" row** with a text panel noting *"installed, metrics not yet scraped."* Build on it — don't duplicate.

- **MVP:** once §1b scraping is on, **fill that reserved Kyverno row** in `policy-ops.json` with real panels:
  `kyverno_policy_results` rate by policy/`rule_result`, `kyverno_mutating_policy_execution_duration_seconds`,
  `kyverno_admission_requests_total` rate, and the 4 controllers' `up`.
- **Full:** add a dedicated **`policy-reflection-ops.json`** (the CNPG→dbgate *pipeline*, a different audience
  from security posture), panels:
  - Kyverno row: results/mutation rate per policy, mutate execution duration, admission rate, controller readiness.
  - **Coverage row:** clusters vs annotated vs mirrored vs dbgate-connected (stat + timeseries), **coverage %
    gauge**, and a **GAPS table** driven by `policy_reflection_coverage_gap` (cluster,stage) — the money panel.
  - Reflector/health row: reflector pod up/restarts, max mirror `reflected-at` age.
- Follow the generator pattern: `json/<name>.json` + `resources/<name>.yaml` (`GrafanaDashboard` CR, `folderRef`
  `ops`/`ops-security`, `configMapRef`) + add to `grafana-dashboards/kustomization.yaml`. **Ground every query
  against Mimir before finalizing** (matches how every existing dashboard here was authored).

---

## Ranked recommendation

1. **(HIGHEST) Coverage reconcile CronJob → pushgateway gauges + `CoverageGap` / `DbgateGap` / `ExporterAbsent`
   alerts.** The one thing that catches the image-updater-class silent failure; closes stage 4 which nothing else
   can see; gives per-cluster gap identity.
2. **Scrape Kyverno metrics** (enable chart `serviceMonitor` on the 4 controllers) → `KyvernoControllerDown` +
   `KyvernoPolicyError`; fills the reserved `policy-ops.json` Kyverno row.
3. **CNPG `Cluster` KSM custom-resource-state metric** (cheap inventory + PromQL cross-check).
4. **Dedicated `policy-reflection-ops` dashboard** (Full tier, incl. the GAPS table).
5. **(Optional) KSM secret annotation/label allowlist** for a pure-PromQL stage-1–3 cross-check.

### MVP tier (~½ day) vs Full tier
- **MVP:** items 1 + 2 (CronJob + 3 coverage alerts + Kyverno serviceMonitor + KyvernoControllerDown/PolicyError).
  This alone provides the silent-failure safety net.
- **Full:** add items 3, 4, reflector pod/staleness panels, and optionally item 5.

---

## Concrete file paths (where things land in THIS repo)

| Change | Path |
|--------|------|
| Coverage exporter (new) | `infrastructure/base/monitoring/policy-reflection-exporter/{cronjob.yaml,rbac.yaml,kustomization.yaml}` → add to `infrastructure/base/monitoring/kustomization.yaml` |
| Enable Kyverno metrics | `infrastructure/base/kyverno/helmrelease.yaml` — add `<controller>.serviceMonitor.enabled: true` for admission/background/reports/cleanup (metricsService already defaults to :8000) |
| Alerts | `infrastructure/base/monitoring/v2-otel/baseline-alerts/policy-reflection-alerts.yaml` (+ that dir's `kustomization.yaml`) |
| CNPG Cluster CRS metric | `infrastructure/base/monitoring/v2-otel/kube-state-metrics/helmrelease.yaml` — add `Cluster` block under `customResourceState.config.spec.resources` + `rbac.extraRules` for `postgresql.cnpg.io/clusters`; (optional) `--metric-annotations-allowlist`/`--metric-labels-allowlist` for secrets |
| Dashboard — MVP | fill Kyverno row in `infrastructure/base/monitoring/grafana-dashboards/json/policy-ops.json` |
| Dashboard — Full | `…/grafana-dashboards/json/policy-reflection-ops.json` + `…/resources/policy-reflection-ops.yaml` + `…/grafana-dashboards/kustomization.yaml` |
| Alert routing (optional) | `infrastructure/base/monitoring/v2-otel/alertmanager-config/config-template.yaml` — add a `category="policy"` route |

## Dependencies / ordering
- ServiceMonitor: no dependency — Alloy already discovers ServiceMonitors cluster-wide.
- CNPG CRS metric: `rbac.extraRules` (postgresql.cnpg.io clusters) **must** precede the CRS block or reflectors get `Forbidden`.
- CronJob exporter: read-only ClusterRole (`clusters.postgresql.cnpg.io` get/list, `secrets` get/list, `deployments` get) + pushgateway reachable (already deployed).
- Alerts depend on the metrics/exporter existing first.

## Risks / gaps
- **Kyverno metric-name version drift** (`kyverno_policy_results` vs `…_total`) — ground against Mimir before finalizing queries.
- **`mutateExisting` yields no background report/results** — you cannot confirm "the retro-mutation is currently applied" from Kyverno telemetry alone; only admission-time events. This is precisely why the state-reconciling CronJob is required, not just metrics.
- **Pushgateway gauge staleness** — pushgateway persists gauges until overwritten (the repo's own pushgateway helmrelease comment flags this). A dead exporter would report stale-but-green. Mitigate with `policy_reflection_last_run_timestamp` + the `ExporterAbsent`/freshness alert.
- **KSM secret annotation metrics** — mild cardinality and exposes annotation values as labels (no secret data). Prefer scoping to the reflection keys / `databases` ns, or skip in favor of the CronJob.
- **dbgate delete-drift** — orphaned `*_<id>` env keys are inert; the exporter must test `CONNECTIONS` **csv membership**, not raw env-key presence, to avoid false "connected".

## Sources
- [Kyverno — Policy Reports guide](https://kyverno.io/docs/guides/reports/) (mutate/generate not reported in background scans)
- [Kyverno — Metrics reference](https://kyverno.io/docs/reference/metrics/) (`kyverno_policy_results`, execution-duration, admission metrics, `rule_execution_cause`)
- [Kyverno — Monitoring guide](https://kyverno.io/docs/guides/monitoring/) (metrics service :8000, ServiceMonitor)
- [emberstack/kubernetes-reflector](https://github.com/emberstack/kubernetes-reflector) + [reflected-at annotation behaviour](https://github.com/emberstack/kubernetes-reflector/discussions/509)
- In-repo precedents: `monitoring/version-checker/servicemonitor.yaml`, `vpn-gateway/rotation/cronjob.yaml` (pushgateway push), `kube-state-metrics/helmrelease.yaml` (customResourceState), `v2-otel/baseline-alerts/*` (PrometheusRule→Mimir), `grafana-dashboards/json/policy-ops.json` (reserved Kyverno row)

---

## Related Issues

- TALOS-4b45 — Observability for the Kyverno + reflector CNPG→dbgate machinery (this investigation)
