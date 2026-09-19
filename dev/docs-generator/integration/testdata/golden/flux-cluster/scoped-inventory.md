---
type: table
status: current
covers:
  - path:platform
freshness: follows-cluster
tickets:
  - ORCH-201
summary: The Kustomizations under platform/, which is the half of this cluster the platform team owns.
---

# Component Inventory — `platform`

> Generated file — do not edit by hand. Regenerate with `task docs:generate`.
> The source of truth is the Flux Kustomizations in `fleet/prod-west/`,
> so a wrong row here is a wrong manifest there.

SCOPED inventory — only components whose path is inside `platform/`
appear below. That is what makes this a members table rather than a hand-written list:
a component added to or removed from the folder changes this file, and one that moves
out of it leaves.

Every row is one Flux Kustomization — the unit Flux reconciles, and therefore the unit a
doc can honestly claim to cover. The directory tree is not that unit: some directories group
children that are each their own component, others are a single Kustomization wrapping many
nested ones, and nothing in the tree tells the two apart. So this table is built from the
Kustomizations, never from the filesystem.

6 components are declared across 5 manifest files. 2 have a colocated `README.md`,
which is the question this table really asks: a component with no README has no doc home,
and whatever documents it lives somewhere that nothing keeps pointed at it.

| slug               | flux name            | path                        | on disk | readme | nested | suspended |
| ------------------ | -------------------- | --------------------------- | ------- | ------ | ------ | --------- |
| `gateway`          | `gateway-controller` | `platform/gateway`          | yes     | yes    | 1      | -         |
| `legacy-cache`     | `legacy-cache`       | `platform/legacy-cache`     | MISSING | -      | 0      | -         |
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

## Tracking

- ORCH-201 — the component inventory artifact
