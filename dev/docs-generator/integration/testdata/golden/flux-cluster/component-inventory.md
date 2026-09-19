---
type: reference
status: current
covers:
  - cluster
freshness: tracks-code
tickets:
  - TALOS-kll3
  - TALOS-f0sd
bluf: Every Flux Kustomization in clusters/catalyst-cluster, with the manifest that declares it, whether it has a colocated README, and how many nested kustomizations it wraps.
---

# Component Inventory

> Generated file — do not edit by hand. Regenerate with `task docs:generate`.
> The source of truth is the Flux Kustomizations in `clusters/catalyst-cluster/`,
> so a wrong row here is a wrong manifest there.

Every row is one Flux Kustomization — the unit Flux reconciles, and therefore the unit a
doc can honestly claim to cover. The directory tree is not that unit: some directories group
children that are each their own component, others are a single Kustomization wrapping many
nested ones, and nothing in the tree tells the two apart. So this table is built from the
Kustomizations, never from the filesystem.

8 components are declared across 7 manifest files. 4 have a colocated `README.md`,
which is the question this table really asks: a component with no README has no doc home,
and whatever documents it lives somewhere that nothing keeps pointed at it.

| slug               | flux name            | path                        | on disk | readme | nested | suspended |
| ------------------ | -------------------- | --------------------------- | ------- | ------ | ------ | --------- |
| `gateway`          | `gateway-controller` | `platform/gateway`          | yes     | yes    | 1      | -         |
| `legacy-cache`     | `legacy-cache`       | `platform/legacy-cache`     | MISSING | -      | 0      | -         |
| `orchard-api`      | `orchard-api`        | `workloads/orchard-api`     | yes     | yes    | 1      | -         |
| `orchard-web`      | `orchard-web`        | `workloads/orchard-web`     | yes     | yes    | 1      | -         |
| `secrets-operator` | `secrets-operator`   | `platform/secrets-operator` | yes     | yes    | 1      | -         |
| `secrets-store`    | `secrets-store`      | `platform/secrets-store`    | yes     | -      | 1      | -         |
| `storage`          | `storage-stack`      | `platform/storage`          | yes     | -      | 5      | -         |
| `telemetry`        | `telemetry`          | `platform/telemetry`        | yes     | -      | 1      | yes       |

`slug` is the manifest filename; `flux name` is its `metadata.name`. They differ on 2
rows. The filename is the handle this tool uses, because a name that moves when someone
edits a field is not a handle — but `dependsOn` in every other Kustomization refers to the
flux name, so both belong here.

## Reading the nested column

`nested` counts the `kustomization.yaml` files underneath the component's path.

A grouping directory whose children are each their own Flux Kustomization is the CORRECT
pattern and is not what this counts: those children are not inside one component, they are
several components, each with its own row, its own slug and its own doc home.

A high count is the other shape — ONE slug whose single Kustomization applies many nested
kustomizations. All of those nested units deploy, but only the wrapper has a name, so
"component = directory = doc home" is untrue for it: there is no single thing the directory
documents and no one README that could cover it. Run `task docs:rule -- component-shape` for
the outliers.

## Paths that do not exist

These components point at a path that is not in the repo. Flux reports this as a failed
reconcile while the last successfully applied revision keeps running, so the cluster looks
healthy and nothing surfaces it.

- `legacy-cache` (declared in `fleet/prod-west/legacy-cache.yaml`) points at `platform/legacy-cache`

## Related Issues

- TALOS-f0sd — docs as a projection: frontmatter, linting, generation
- TALOS-kll3 — the generator and its whole-file artifacts
