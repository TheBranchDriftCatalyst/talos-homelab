---
type: runbook
status: current
covers:
  - catalyst-websecure-ingress
  - catalyst-nav
  - path:infrastructure/base/catalyst-websecure-ingress
  - path:infrastructure/base/catalyst-nav
  - path:infrastructure/base/infra-control/kubeview
freshness: tracks-code
tickets: []
bluf: Set kustomize.toolkit.fluxcd.io/prune disabled on the XRD, the Composition and the claim and let Flux reconcile that FIRST — only then edit a claim onto spec.nav, one app at a time, and prove each one adopted its IngressRoute rather than replacing it by checking that creationTimestamp did not move.
---

# Catalyst Nav XRD Migration Runbook

Moving a `CatalystWebSecureIngress` claim from annotation-derived nav membership
(`spec.homepage.group` / `.weight` + middleware-name inference) onto the declared
`spec.nav` block added in phase 5.

**Nothing in this repository has been migrated yet.** Phase 5 shipped the schema, the
composition patches and the tests; it deliberately did not touch a single live claim. This
runbook is how the first one gets touched.

## TL;DR

1. **Guard against prune, and let Flux apply the guard, before any schema change lands.**
   `kustomize.toolkit.fluxcd.io/prune: disabled` on the XRD, the Composition and the claim.
   Reconcile. Verify the annotation is on the live objects. Only then continue.
2. **Migrate one claim per commit**, in the order below — the Flux-managed one first,
   because it is the only one this repo can revert on its own.
3. **Prove adoption, not recreation**: the composed IngressRoute's `metadata.creationTimestamp`
   must be unchanged afterwards. A new timestamp means the route was deleted and remade, which
   means its NetworkPolicy was too, which means the app was briefly open east-west.
4. **Roll back by reverting the commit**, which is safe *only because* step 1 already landed.

---

## Why step 1 is not optional

`CatalystWebSecureIngress` is a live XRD with live claims. The thing that makes this migration
dangerous is not the claim edit — it is what Flux does to a Crossplane object graph when a
manifest stops being where it was.

The chain is: Flux owns the XRD and the Composition (`clusters/catalyst-cluster/catalyst-websecure-ingress.yaml`,
`prune: true`) and owns the kubeview claim (`clusters/catalyst-cluster/infra-control.yaml`,
`prune: true`). Crossplane owns what the claim composes — two IngressRoutes and a NetworkPolicy
— through owner references. So:

- Delete the **claim** and Crossplane garbage-collects the routes and the NetworkPolicy. The app
  goes dark *and* loses its east-west lockdown at the same moment. That NetworkPolicy is the
  whole reason this XRD exists (east-west finding 003: forward-auth is perimeter-only, and
  kubeview had no NetworkPolicy at all before the composite).
- Delete the **XRD** and the generated CRD goes with it, taking *every* claim of that kind and
  therefore every composed object in the cluster. One pruned file, every app on the composite.

Flux prunes when a manifest it previously applied is no longer produced by the Kustomization's
build — a renamed file, a moved directory, a kustomization.yaml edit, a path typo. None of
those look dangerous in a diff. This exact failure is on record in this repo from the CNPG
composite conversion: the fix there was to set `prune: disabled` on the live objects **in an
earlier commit**, so that by the time the manifests changed, Flux had already been told not to
delete them.

The annotation is per-object and it takes effect only once Flux has reconciled it onto the live
object. Setting it in the same commit as the change it protects protects nothing.

---

## Step 1 — land the prune guard

Add the annotation to the three manifests:

```yaml
# infrastructure/base/catalyst-websecure-ingress/xrd.yaml  (and composition.yaml)
metadata:
  name: catalystwebsecureingresses.net.catalyst.io
  annotations:
    # Flux must never garbage-collect this object: deleting the XRD deletes the generated
    # CRD, every claim of the kind, and every IngressRoute + NetworkPolicy those claims
    # compose. Removal is a deliberate, hand-run `kubectl delete`, never a side effect of a
    # file move.
    kustomize.toolkit.fluxcd.io/prune: disabled
```

```yaml
# infrastructure/base/infra-control/kubeview/websecure-ingress.yaml
metadata:
  name: kubeview
  namespace: infra-control
  annotations:
    catalyst.io/replaced-loc: "39"
    kustomize.toolkit.fluxcd.io/prune: disabled
```

Commit and push **this and nothing else**. Then reconcile and confirm the annotation is live:

```bash
task infra:flux-reconcile     # fetches the source first; see below
kubectl get xrd catalystwebsecureingresses.net.catalyst.io \
  -o jsonpath='{.metadata.annotations.kustomize\.toolkit\.fluxcd\.io/prune}{"\n"}'
kubectl get catalystwebsecureingress -n infra-control kubeview \
  -o jsonpath='{.metadata.annotations.kustomize\.toolkit\.fluxcd\.io/prune}{"\n"}'
```

Both must print `disabled`. If either prints nothing, Flux has not applied the commit yet —
`flux reconcile kustomization` applies the revision already fetched, so use
`--with-source` (which `task infra:flux-reconcile` does) or run `flux reconcile source git
flux-system` first. Reconciling without it verifies stale state and tells you the guard is
missing when it is not, or worse, that it is present when it is not.

**Do not proceed until both print `disabled`.**

---

## Step 2 — migration order

| # | Claim | Owned by | Where the manifest lives | Notes |
|---|-------|----------|--------------------------|-------|
| 1 | `infra-control/kubeview` | **Flux** (`infra-control`) | this repo | Do this one first. |
| 2 | `system-graph/system-graph` | **ArgoCD** (`system-graph` Application) | the `system-graph` repo, `k8s/talos00` | Not this repo. Read the ArgoCD section below before touching it. |

Those are the only two claims in the cluster (`kubectl get catalystwebsecureingresses -A`).
Every other nav entry still comes from a hand-written IngressRoute and is **out of scope** —
those apps are not on the composite, so they have no `spec.nav` to declare. They keep working
exactly as they do today; see "What is deliberately not migrated" at the end.

kubeview first for one reason: it is the only claim whose manifest this repository controls, so
it is the only one that can be rolled back with `git revert` here. If something about the
declaration turns out to be wrong, you want to find out on the claim with the short feedback
loop.

### Migrating kubeview

The edit is mechanical. Before:

```yaml
  homepage:
    name: KubeView
    description: "Live cluster topology and object browser"
    group: Infrastructure        # <- moves
    icon: kubeview.png
    weight: 30                   # <- moves
```

After:

```yaml
  homepage:
    name: KubeView
    description: "Live cluster topology and object browser"
    icon: kubeview.png
  nav:
    # false: the chain carries catalyst-nav, which adds the bar and leaves kubeview's own
    # styling alone. Declaring true here is REJECTED at admission against spec.middlewares.
    themed: false
    group: infrastructure        # the NavGroup's metadata.name, not its title
    order: 30                    # was gethomepage.dev/weight
```

`group` and `weight` **must** move rather than be copied: the schema makes
`spec.homepage.group` / `.weight` mutually exclusive with `spec.nav`, so leaving either behind
is a rejected claim, not a silent duplicate. That is deliberate — the composition derives both
annotations from the nav fields, and allowing the old pair as well would make the emitted value
depend on patch order.

Three things to get right, each of which the schema will refuse rather than guess:

- **`order` must be a multiple of 10.** kubeview's 30 carries over unchanged. system-graph's
  live weight is **35, which is not admissible** — it becomes 40 (keeping it after kubeview,
  which is the current order) and that is a reviewed choice, not a rounding.
- **`themed` must match the middleware chain.** `catalyst-nav` and any merged `catalyst-nav-*`
  injector mean `themed: false`. A per-app `catalyst-<slug>` theme means `true`. Getting it
  wrong is a rejection quoting both halves.
- **`group` is the object name**, lowercase-kebab, from the eight in
  `infrastructure/base/catalyst-nav/taxonomy.yaml`. `Infrastructure` is rejected;
  `infrastructure` is correct.

Dry-run the render locally before committing — this is the step that catches a mistake while it
is still free:

```bash
# needs docker + the crossplane CLI (xpkg release matching the cluster's Crossplane)
crossplane composition render \
  --xrd=infrastructure/base/catalyst-websecure-ingress/xrd.yaml \
  /path/to/your-edited-claim.yaml \
  infrastructure/base/catalyst-websecure-ingress/composition.yaml \
  functions.yaml
```

The rendered `kubeview-ir-websecure` manifest must carry **all seven** of the gethomepage keys
it carries today (`enabled`, `name`, `description`, `group`, `icon`, `instance`, `weight` — and
`group`/`weight` must hold the same values as before: `Infrastructure` and `"30"`), **plus** the
new declarative set:

```yaml
nav.catalyst.io/group: infrastructure
nav.catalyst.io/order: "30"
nav.catalyst.io/themed: "false"
```

If `gethomepage.dev/group` or `gethomepage.dev/weight` changed value, the nav will visibly
reorder or re-bucket the app. Stop and fix the claim, not the composition.

Then commit, push, reconcile, and verify.

---

## Step 3 — prove adoption, not recreation

This is the check that distinguishes "the route was patched in place" from "the route was
deleted and a new one appeared with the same name". Capture the timestamp **before** the
change:

```bash
kubectl get ingressroute -n infra-control kubeview-websecure \
  -o jsonpath='{.metadata.creationTimestamp}{" uid="}{.metadata.uid}{"\n"}'
# e.g. 2026-09-10T15:47:18Z uid=c72264c7-fa08-49ed-80a3-46488485ac8b
```

And again after Flux and Crossplane have both settled:

```bash
kubectl get catalystwebsecureingress -n infra-control kubeview \
  -o jsonpath='{range .status.conditions[*]}{.type}={.status} {end}{"\n"}'
# want: Synced=True Ready=True Responsive=True

kubectl get ingressroute -n infra-control kubeview-websecure \
  -o jsonpath='{.metadata.creationTimestamp}{" uid="}{.metadata.uid}{"\n"}'
kubectl get networkpolicy -n infra-control kubeview \
  -o jsonpath='{.metadata.creationTimestamp}{" uid="}{.metadata.uid}{"\n"}'
```

**An unchanged `creationTimestamp` and `uid` is the proof of adoption.** The object the
apiserver is holding is the same object it was holding before — it was patched, never
replaced. A *newer* timestamp (or a different uid) means the composed resource was deleted and
recreated, and for the window between those two events the NetworkPolicy did not exist and the
backend was reachable from any pod in the cluster. If you see that, treat it as an incident,
not a cosmetic difference: check `kubectl get events -n infra-control --sort-by=.lastTimestamp`
for the delete, and find out what pruned it.

Then confirm the annotations actually landed and the nav still renders:

```bash
kubectl get ingressroute -n infra-control kubeview-websecure \
  -o jsonpath='{.metadata.annotations}' | python3 -m json.tool

# the live nav manifest the browser gets — the app must still be in it, in the same group
kubectl exec -n themepark deploy/themepark -c nav-discovery \
  -- cat /config/www/resources/catalyst-nav.json | python3 -m json.tool | less
```

Capture that file before the change too, and diff the two. The **catalyst-nav operator**
rebuilds it on every reconcile now, not on a 300-second sidecar loop, so the new manifest is
live as soon as the IngressRoute change is reconciled — there is no refresh to wait out.

The three `nav.catalyst.io/*` keys are **inert** today: the operator's deriver reads
`gethomepage.dev/` and `catalyst.nav/`, and `nav.catalyst.io/` is neither. So a correct
migration changes *nothing* about what the browser receives. That is the point — the
declaration lands on live routes and can be inspected long before anything depends on it.
If the rendered nav *does* change, something about `gethomepage.dev/group` or `/weight`
changed value, and that is a claim error.

---

## Step 4 — the ArgoCD claim (system-graph)

`system-graph`'s claim is **not in this repository.** It lives in the `system-graph` repo under
`k8s/talos00` and is applied by the ArgoCD Application in
`infrastructure/base/argocd/applications/system-graph.yaml`, with `automated: {prune: true,
selfHeal: true}`. Consequences:

- `kustomize.toolkit.fluxcd.io/prune: disabled` is a **Flux** annotation and does nothing here.
  The ArgoCD equivalent is `argocd.argoproj.io/sync-options: Prune=false` on the claim itself.
- `selfHeal: true` means an in-cluster edit is reverted, usually within minutes. There is no
  "try it on the live object first" option; the migration is a PR against the `system-graph`
  repo.
- Do not drive the sync by patching the Application's `.operation` field. A
  `kubectl patch ... '{"operation":{"sync":{}}}'` silently discards **every** entry in
  `syncOptions` — including `ServerSideApply=true` and the prune safeties this app depends on.
  Use `argocd app sync system-graph`, or let autoSync do it.
- Before you push anything to that repo, check `git branch --show-current` and confirm which
  remote ref you are about to push to. A sister-repo push in this workspace has already caused
  an accidental PR merge once.

Everything else — the edit, the `order: 35 -> 40` decision, the adoption check — is the same.

---

## Rollback

**For a claim (either one):** revert the commit that migrated it. The claim goes back to
`spec.homepage.group` / `.weight`, the composition's nav patches become no-ops again because
their source paths are gone, and the composed IngressRoute is patched back to the annotations
it had before. The `nav.catalyst.io/*` keys are **not** removed by this — a patch whose source
disappears is skipped, not reversed, so the stale annotation stays on the object until something
rewrites it. They are inert, so this is cosmetic, but it means "the annotation is present" is
not evidence the claim is still migrated. Read the claim, not the route.

```bash
git revert <migration-commit>
git push
task infra:flux-reconcile
kubectl get catalystwebsecureingress -n infra-control kubeview -o yaml | grep -A6 '^  nav:' || echo "spec.nav is gone"
```

To clear the stale keys as well:

```bash
kubectl annotate ingressroute -n infra-control kubeview-websecure \
  nav.catalyst.io/group- nav.catalyst.io/order- nav.catalyst.io/themed- \
  nav.catalyst.io/visibility.authentik-groups-
```

That is safe here only because Crossplane does not treat an extra annotation as drift it must
remove; if a later phase starts reading these keys, remove the claim's `spec.nav` first.

**For the schema itself (phase 5 as a whole):** reverting the XRD commit removes the `nav`
properties and the six CEL rules. **Do not revert it while any claim still carries
`spec.nav`** — the apiserver will prune the unknown field on the next write, which leaves the
claim silently un-migrated while the git manifest still says otherwise. Migrate every claim
back first, then revert the schema.

**What rollback does not cover:** if the XRD or a claim was pruned because step 1 was skipped,
`git revert` re-creates the object but Crossplane re-creates the composed resources *fresh* —
new uid, new creationTimestamp, and a gap during which there was no NetworkPolicy. Recovery is
possible; the outage is not undone. That asymmetry is the whole argument for step 1.

---

## Pre-flight checklist

Run before and after every migration commit:

```bash
task nav:xrd-schema   # admission rejections + the three copies of the taxonomy agree
task nav:parity       # the Go operator still reproduces build_nav.py's FROZEN output, byte for byte
```

`nav:parity` is the one that would catch a migration having changed what the nav renders. It
diffs against a corpus; for a live sign-off, refresh it first with `task nav:corpus:cluster`
(read-only) so the corpus includes the routes only the cluster has — composition-minted routes
are not in the repo.

---

## What is deliberately not migrated

- **Apps with hand-written IngressRoutes.** Most of the ~40 nav entries. They have no claim, so
  they have nothing to declare; `spec.nav` is a property of the composite, not of the nav. They
  continue to be derived from `gethomepage.dev/*` and middleware-name inference, which is why
  the inference code stays until phase 6. Onboarding them onto `CatalystWebSecureIngress` is a
  separate piece of work with its own risk (it moves their routes under Crossplane ownership).
- **The free-text group values still in the cluster.** `Monitoring` vs `Observability` vs
  `Analytics` are annotations on hand-written routes. The enum cannot reach them; the
  catalyst-nav operator *reports* them (`kubectl describe navgroup observability` shows the
  near-miss list once the operator is deployed), and fixing them means editing those routes'
  annotations, with the nav visibly re-bucketing when you do.
- **`spec.nav.visibility`.** Accepted and emitted, read by nothing. The visibility filter is a
  later phase. Setting it now is harmless and documents intent; it does not gate anything yet.

---

## Related Issues

<!-- Beads tracking for this doc -->
