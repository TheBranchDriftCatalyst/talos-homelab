---
type: reference
status: current
covers:
  - path:infrastructure/base/security
freshness: tracks-code
tickets:
  - TALOS-f0sd.5
bluf: The Flux Kustomizations whose manifests live under infrastructure/base/security, with whether each has a colocated README and how many nested kustomizations it wraps.
---

# Component Inventory — `infrastructure/base/security`

> Generated file — do not edit by hand. Regenerate with `task docs:generate`.
> The source of truth is the Flux Kustomizations in `clusters/catalyst-cluster/`,
> so a wrong row here is a wrong manifest there.

SCOPED inventory — only components whose path is inside `infrastructure/base/security/`
appear below. That is what makes this a members table rather than a hand-written list:
a component added to or removed from the folder changes this file, and one that moves
out of it leaves.

Every row is one Flux Kustomization — the unit Flux reconciles, and therefore the unit a
doc can honestly claim to cover. The directory tree is not that unit: some directories group
children that are each their own component, others are a single Kustomization wrapping many
nested ones, and nothing in the tree tells the two apart. So this table is built from the
Kustomizations, never from the filesystem.

4 components are declared across 4 manifest files. 4 have a colocated `README.md`,
which is the question this table really asks: a component with no README has no doc home,
and whatever documents it lives somewhere that nothing keeps pointed at it.

| slug        | flux name   | path                                     | on disk | readme | nested | suspended |
| ----------- | ----------- | ---------------------------------------- | ------- | ------ | ------ | --------- |
| `crowdsec`  | `crowdsec`  | `infrastructure/base/security/crowdsec`  | yes     | yes    | 2      | -         |
| `falco`     | `falco`     | `infrastructure/base/security/falco`     | yes     | yes    | 1      | -         |
| `honeypots` | `honeypots` | `infrastructure/base/security/honeypots` | yes     | yes    | 1      | -         |
| `iocaine`   | `iocaine`   | `infrastructure/base/security/iocaine`   | yes     | yes    | 1      | -         |

`slug` is the manifest filename; `flux name` is its `metadata.name`. They differ on 0
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

Every declared `spec.path` resolves to a directory in this repo.

## Related Issues

- TALOS-f0sd.5 — artifact scoping, which is what makes a per-section inventory possible
