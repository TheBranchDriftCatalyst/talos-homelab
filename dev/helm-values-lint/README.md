# helm-values-lint

## TL;DR

Flags `HelmRelease` `spec.values` keys that the chart **does not define**. Helm
ignores those silently, so the manifest says one thing and the cluster does
another, forever, with no error anywhere.

```bash
task dev:helm-values:check      # offline, no cluster, no network
task dev:helm-values:selftest   # prove the checker actually fires
task dev:helm-values:refresh    # NETWORK: rebuild cache/ after a chart bump
```

- **42** HelmReleases in the repo, **40** checked, **26** findings across **12**
  releases on the first run (see [Findings](#findings-first-run-2026-10-14)).
- `check` is **offline**: it reads committed schema fingerprints from `cache/`,
  not the network. A release with no fingerprint is reported as **SKIPPED**,
  never as a pass.
- Deliberately **not** in `task lint` or `task dev:ci`. See
  [Making this a gate](#making-this-a-gate).

---

## Why this exists

Beads ticket `TALOS-o1sb`. Four recorded incidents of the same class:

| #   | Release | Dead path                                           | Consequence                                               |
| --- | ------- | --------------------------------------------------- | --------------------------------------------------------- |
| 1   | tempo   | —                                                   | ran unrequested                                           |
| 2   | mimir   | `nginx`                                             | the whole block never applied                             |
| 3   | argocd  | `rbac`                                              | `policy.csv` / `policy.default` rendered EMPTY for months |
| 4   | argocd  | `configs.params.application.resourceTrackingMethod` | valid key, renders into the WRONG ConfigMap — inert       |

Incidents 2 and 3 are what this tool catches. Incident 2 is **still live** and
this tool found it again (`mimir`'s `nginx:` block is still in the manifest).
Incident 4 is **out of scope** — see below.

---

## What it checks

For every `HelmRelease` under `infrastructure/`, `applications/` and
`clusters/`, it walks `spec.values` against the chart's real schema and reports:

- **UNKNOWN** — the key resolves to no path the chart defines. This is the dead
  key class.
- **TYPE** — the chart's default at that path is a map but the manifest sets a
  scalar or list (or vice versa). A shape mismatch that usually renders as
  nothing.

The walk is **nested**, not just top-level, and stops descending the moment a
path becomes free-form (below).

### Where the schema comes from

`refresh` runs `helm pull --untar` for each referenced chart — resolving
`HelmRepository` CRs from the repo itself, including semver ranges and OCI
repos — then derives a small **fingerprint** per chart+version into
`cache/<chart>@<version>.json`:

- `paths` — every path in the chart's `values.yaml`, with its default's _kind_
  (`map`, `map-empty`, `list`, `null`, `scalar`).
- `refs` — every `.Values.<path>` the chart's own templates and `values.yaml`
  mention.
- `dumps` — the subset of those dumped **verbatim** (`toYaml`), which makes the
  subtree free-form.
- `dependencies`, `has_schema`, the resolved version, the repo URL, and the
  `helm` version that produced it.

`refresh` uses an **isolated `HELM_*` home**. Without that, `helm pull --repo
<url>` still reads the caller's `helm repo list`, and one unreachable index.yaml
in the operator's local config made all 40 pulls fail. The fingerprints are
committed, so `check` is hermetic and works in CI with no network and no
cluster.

---

## What it deliberately does NOT check

An over-eager checker that cries wolf is worse than none. These are blind spots
on purpose; each one was added because it produced noise, and each one is
recorded with its evidence in [`allow.yaml`](allow.yaml).

1. **Instance #4's whole class — which ConfigMap the consumer reads.**
   `configs.params.application.resourceTrackingMethod` is a _valid_ argo-cd
   value. It renders. It lands in `argocd-cmd-params-cm`. ArgoCD reads that
   setting from `argocd-cm`. A values-diff cannot see any of that: it would need
   a model of every component's config-source precedence. **This tool cannot and
   does not catch instance #4.** Verifying that a rendered key reaches its
   consumer stays a manual, per-component job — read the live ConfigMap, not the
   manifest.

2. **Children of free-form Kubernetes structures.** `resources`,
   `securityContext`, `nodeSelector`, `podAnnotations`, `env`, `extraArgs`, … A
   chart whose `values.yaml` shows only `resources.requests` still honours
   `resources.limits`, because it `toYaml`s the whole thing. So a typo _inside_
   one of these (`resources.limit`) is missed. The full list is
   `opaque_leaf_names` in `allow.yaml`.
   **This only stops descent.** A misspelling of the structure's own name is
   still caught — that is how `prometheus-blackbox-exporter`'s `podLabels` (the
   chart has `pod.labels`) and `kyverno`'s `admissionController.resources` (the
   chart has `admissionController.container.resources`) were found.

3. **Subtrees a chart dumps verbatim.** When a template does
   `toYaml .Values.loki.limits_config`, the chart's `values.yaml` is not an
   enumeration of the legal keys — it is an example, and charts routinely ship
   the real options **commented out** (tempo's `# s3:` block is exactly that).
   Detected automatically, including the `{{- with .Values.x }}{{- toYaml . }}`
   form. This removed 6 Loki `limits_config` findings and tempo's
   `tempo.storage.trace.s3`, all genuine false positives.

4. **Keys read through an alias.** `$t := .Values.operator.telemetry` then
   `$t.send.enabled` is a real read of a key `values.yaml` never declares. The
   checker cannot follow it. Three such cases are allowlisted with the grep that
   proves them (authentik's recursive env flattener, mongodb's telemetry alias,
   traefik's `ports` range). Where this is _suspected_ but unproven, the finding
   is kept and annotated `VERIFY: .Values.<parent> is read bare by a template`
   — that annotation sits on traefik's `service.type`, which is a **confirmed
   real defect**, so the annotation is a prompt, not a dismissal.

5. **`valuesFrom`.** Values injected from ConfigMaps/Secrets via
   `spec.valuesFrom` are not read. Only inline `spec.values` is checked.

6. **Charts from a `GitRepository` or `chartRef`.** `helm pull` cannot resolve
   them. One release (`hubble-observer`) is reported as SKIPPED, loudly, every
   run.

7. **Whether a value is _correct_.** Only whether the chart has somewhere to put
   it.

---

## Proving it fires

Repo gotcha #11: _a check that reports success is not a check that ran._

```bash
$ task dev:helm-values:selftest
  PASS fixture fires: flagged ['controller.replicaCountTypo', 'notAKey', 'rbac']
  PASS fixture stays quiet: 12 legitimate keys not flagged
  PASS historical argocd (before the fix): flagged the dead top-level `rbac` block
  PASS historical argocd (after the fix): no longer flags `rbac` — the fix is recognised
```

Four cases, and all four have to run — an unrunnable case fails rather than
passing quietly:

1. **`testdata/bad-helmrelease.yaml`** carries the real defect shape
   (top-level `rbac:`), a nonsense top-level key, and a dead leaf under a real
   parent. Checked against the _real_ cached argo-cd fingerprint, not a mock.
2. The **same fixture's negative controls** — 12 legitimate keys that must stay
   unflagged, including the dotted literal `configs.rbac.policy.default` and an
   allowlisted free-form subtree. Without this half, a checker that flagged
   everything would pass.
3. **`git show d26be8a4^:infrastructure/base/argocd/helmrelease.yaml`** — the
   actual argocd manifest from before the fix. The checker must flag `rbac`.
4. **`git show d26be8a4:…`** — the fix commit. The checker must _stop_ flagging
   it.

Case 3 is the one that matters: it catches the real, historical, months-long
defect from real git history, not from a fixture someone wrote to match the
implementation.

Two bugs were found _by_ these cases and are worth knowing about, because both
are the "silently suppressed everything" failure mode:

- argo-cd bundles the `redis-ha` subchart, whose templates read
  `.Values.rbac.create` — meaning `redis-ha`'s own rbac. Scanning subchart
  templates into the parent's namespace suppressed the known-dead top-level
  `rbac`. Subcharts are now scanned with their root as a prefix.
- `toYaml .annotations` matched a "dumps the whole subtree" regex that meant to
  match `toYaml .`, which hid mimir's `gateway.enabledNonEnterprise`.

---

## Findings (first run, 2026-10-14)

42 HelmReleases found · 40 checked · 1 with no `spec.values` · 1 skipped
(`hubble-observer`, GitRepository chart) · **26 findings** · 10 suppressed.

Every finding below was verified by hand against the chart and, where the
component is deployed, against the live cluster. **None of the 26 is a false
positive.**

### Confirmed live, with impact

| Release                           | Dead path(s)                                                                                                                         | Chart actually reads                                       | Proof                                                                                                                                                                                                               |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **mimir**                         | `ingester.persistence`, `compactor.persistence`, `store_gateway.persistence`, `alertmanager.persistence.{enabled,size,storageClass}` | `*.persistentVolume.*`                                     | Manifest asks 20Gi/20Gi/10Gi/5Gi. Live PVCs are **2Gi/2Gi/2Gi/1Gi** — the chart defaults. `storageClass: local-path` matches only because local-path is the cluster default.                                        |
| **kyverno**                       | `admissionController.resources`                                                                                                      | `admissionController.container.resources`                  | Manifest asks 192Mi req / 448Mi limit (measured in TALOS-gj3n). Live: **128Mi / 384Mi** — chart defaults. `backgroundController.resources` _is_ a valid path and did apply, which is why only one of them is wrong. |
| **traefik**                       | `service.type`                                                                                                                       | `service.spec.type`                                        | Manifest says `ClusterIP`. Live Service is **LoadBalancer** (the chart default), holding an LB-IPAM address.                                                                                                        |
| **keda-add-ons-http**             | `interceptor.additionalEnvVars`                                                                                                      | `interceptor.extraEnvs` (a **map**, not a list)            | The three 600s timeouts meant to match Traefik are absent from the live interceptor env, which has only the 6 chart defaults.                                                                                       |
| **intel-device-plugins-operator** | `operator`, `kubeRbacProxy`                                                                                                          | top-level `resources`; no kube-rbac-proxy exists in 0.36.0 | Live container runs chart-default 100m/100Mi–100m/120Mi, not the manifest's 10m/64Mi. The deployment has **one** container, so the whole `kubeRbacProxy.image` override is moot.                                    |
| **mimir**                         | `nginx` (whole block)                                                                                                                | `gateway.*`                                                | **Incident #2, never removed.** The manifest comment acknowledges it. Its only mention anywhere in the chart is a legacy variable in `NOTES.txt`.                                                                   |
| **prometheus-blackbox-exporter**  | `podLabels`, `replicaCount`                                                                                                          | `pod.labels`, `replicas`                                   | Live pod labels carry no `app: blackbox-exporter`. `replicaCount: 1` happens to equal the default, so it would fail silently only on the day someone scales it.                                                     |

### Confirmed dead, currently no impact (inert pins — incident #4's flavour)

These give false assurance: the manifest states an intent that is not in force,
and happens to agree with the default.

| Release            | Dead path(s)                            | Note                                                                                                                                                                                     |
| ------------------ | --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **argocd**         | `applicationSet.enabled`                | No such key in argo-cd 10.x; the ApplicationSet controller is always installed. Setting it to `false` would not disable anything.                                                        |
| **traefik**        | `metrics.prometheus.enabled`            | Prometheus metrics are enabled by the block's presence, not by an `enabled` key.                                                                                                         |
| **minio-operator** | `console`                               | Removed from the `operator` chart in v7. `enabled: false` matches reality by accident.                                                                                                   |
| **falco**          | `falcosidekick.config.loki.apiendpoint` | falcosidekick's Loki output takes `endpoint`; `apiendpoint` is the **quickwit** output's key. The value set equals the default.                                                          |
| **tempo**          | `search`, `traces`                      | Both dropped from the `tempo` chart; receivers now come from the literal `config:` string, which is what the live ConfigMap shows. The `traces.*.enabled: false` pins are inert.         |
| **authentik**      | `redis`                                 | The chart dropped the redis dependency. **Already known** — the manifest comment says the block is "kept purely to document prior state". The comment can stay; the dead keys should go. |

### Latent (component not deployed)

| Release  | Dead path(s)                                                                                                                                                                                                   |
| -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **liqo** | `metrics`, `networking.gatewayTemplates`, `networking.ipMappingMode`, `webhook.enabled` — keys from a newer liqo than the pinned v0.10.3. No `liqo` namespace exists and nothing in `clusters/` references it. |

---

## Making this a gate

Repo gotcha #8: `task lint` is already red repo-wide, so anything wired into it
is born ignored. This lives in its own task with its own exit code instead.

Exit codes: `0` clean · `1` findings · `1` with `--strict` if anything was
skipped or any allowlist entry went stale.

To enforce it, in order:

1. Fix or allowlist the 26 findings above. The fixes are small; the two in the
   "latent" and "already known" rows may just be deletions.
2. Add `task dev:helm-values:check` to `lefthook.yaml` `pre-push`. It needs no
   network and no cluster, and takes about a second.
3. Only then add it to `dev:ci`, and consider `--strict` so a skipped release or
   a rotted allowlist entry also fails.

After any chart version bump, run `task dev:helm-values:refresh` and commit
`cache/`. A stale fingerprint is a correctness problem: `check` matches a
fingerprint by exact version first, then by the recorded version constraint, and
reports a release as SKIPPED if neither matches — so the failure mode is a loud
skip, not a silent pass.

---

## Layout

```text
dev/helm-values-lint/
├── helm_values_lint.py            # the whole tool (check / refresh / selftest)
├── allow.yaml                     # suppressions, each with its evidence
├── cache/<chart>@<version>.json   # committed schema fingerprints (40 charts)
├── testdata/bad-helmrelease.yaml  # the fixture that proves the checker fires
└── README.md
```

Python rather than a second Go module: the flake's `pythonEnv` already provides
`pyyaml`, so there is no build step and `check` runs straight from a clean
checkout. `dev/docs-generator/` remains the precedent for a self-contained tool
directory under `dev/` with its own task namespace.

---

## Related Issues

- TALOS-o1sb — argocd rbac was at a dead Helm value path; audit other
  helmreleases for the same class
