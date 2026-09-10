# Composition labels & DRY convention

## TL;DR

Every resource produced by a Crossplane composition carries two labels so a dashboard can
tell **composition-managed** resources apart from hand-written **look-alikes** (drying-up
candidates), and each migration records how many lines of YAML it replaced.

| Label / annotation | Value | On | Purpose |
|---|---|---|---|
| `catalyst.io/composition` | `<composition-name>` (e.g. `catalyst-cnpg-appdb`) | every composed resource | identifies the resource as composition-managed + which composition |
| `catalyst.io/managed-by` | `crossplane` | every composed resource | generic "this is composed" flag |
| `catalyst.io/replaced-loc` (annotation) | integer | the composite claim (XR) | lines of hand-written YAML this XR replaced — summed on the dashboard as "LOC dried up" |

Crossplane's built-in `crossplane.io/composite` label lands on the **outer `Object` wrapper
only**, never the real resource — so it can't identify the inner CNPG Cluster / IngressRoute /
NetworkPolicy. The `catalyst.io/*` labels above are patched onto the **inner manifest** to fix
that. No composition function iterates resources (`function-patch-and-transform` only), so the
labels are set directly in each composed resource's `spec.forProvider.manifest.metadata.labels`.

## The drying-up query

A resource of a composed kind (CNPG `Cluster`, Traefik `IngressRoute`, `NetworkPolicy`, …) that
**lacks** `catalyst.io/composition` is a look-alike that could be migrated to a composition:

```promql
# CNPG clusters not yet managed by a composition (drying-up candidates)
count(kube_customresource_cnpg_cluster_info) - count(kube_customresource_cnpg_cluster_info{label_catalyst_io_composition!=""})
```

## Adding the labels to a composition

For each composed resource in the composition's `function-patch-and-transform` `resources:`,
set the labels in the base `manifest.metadata.labels`. For CNPG specifically, also add
`catalyst.io/composition` under `spec.inheritedMetadata.labels` so the operator copies it to
the pods/PVCs. See `infrastructure/base/catalyst-cnpg-appdb/composition.yaml` for the reference.

## LOC dried up

When migrating an app to a composition, count the lines of YAML the composition replaces
(the deleted manifests) and record them on the XR:

```yaml
metadata:
  annotations:
    catalyst.io/replaced-loc: "142"
```

The Compositions dashboard sums these into a single "lines of YAML dried up" stat.

---

## Related Issues

- TALOS-l2sm.10 — CatalystWebSecureIngress composition
- TALOS-l2sm.11 — Composition-adoption observability (this convention + KSM-CRS + dashboard)
