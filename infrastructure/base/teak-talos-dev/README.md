# teak-talos-dev — isolated work tenant

## TL;DR

A namespace on the homelab cluster that the work laptop can `kubectl apply` into directly,
with the cluster's existing CNPG / Dragonfly / RabbitMQ operators available, and no ability to
see or touch anything else.

```bash
task k8s:teak-kubeconfig       # mint .output/teak-talos-dev.kubeconfig
task k8s:teak-verify           # prove the scoping holds
```

**Setting up a second machine (incl. Tilt): [ONBOARDING.md](ONBOARDING.md).** It also answers
whether Flux/ArgoCD need to ignore anything you deploy here — short version: ArgoCD cannot
reach this namespace at all, and Flux prune is inventory-based so it never touches objects it
did not apply. With the demo removed, the only Flux-owned object left in the namespace is
`dbgate` — don't name anything of yours that.

| | |
|---|---|
| Namespace | `teak-talos-dev` |
| Identity | ServiceAccount `teak-operator` — one namespaced Role, **zero** cluster-scoped grants |
| API endpoint | `https://192.168.1.54:6443` (LAN direct) |
| URL | `https://dbgate.teak.talos00` (`lan-only` ipAllowList) |
| Operators | shared: cloudnative-pg, dragonfly-operator, rabbitmq cluster + topology |

## Who owns what

**Flux owns the scaffolding plus dbgate.** Namespace, ResourceQuota + LimitRange, RBAC, Cilium
policies, the `*.teak.talos00` certificate, and the tenant's own dbgate + its connection-sync
CronJob. It owns **no application workloads** — the MVP demo (whoami + CNPG + Dragonfly +
RabbitMQ) was removed once it had proven the tenant works end to end, and is recoverable from
git history. dbgate is the only thing that actually runs in the namespace.

**Flux does NOT own what the laptop applies.** Flux prune is inventory-based — it only deletes
objects it previously applied. Anything you create is invisible to it and survives
reconciliation.

**What you must NOT delete.** None of these run anything, so they are easy to mistake for
clutter:

| Object | Why |
|---|---|
| `ServiceAccount/teak-operator` + its Role | This is the identity your kubeconfig authenticates as. Delete it and the laptop loses all access. |
| `CiliumNetworkPolicy` (6) | The default-deny and the egress quarantine. Delete them and the tenant can reach the whole homelab. |
| `ResourceQuota` / `LimitRange` | The only thing bounding a runaway work workload on shared nodes. |
| `Certificate/teak-wildcard` | TLS for every `*.teak.talos00` host you expose. |

The one name to avoid reusing is `dbgate` — it is the sole Flux-owned object left that a
Tilt-applied manifest could collide with.

## Everything here runs one replica

A standing convention for this namespace, Postgres included — apply it to what you deploy. It
is a **deliberate deviation** from the homelab rule "never 1 CNPG instance on local-path, scale
to 3", which buys availability a dev tenant does not need at 3x the footprint on shared
hardware.

What you are accepting: **local-path is node-local, so losing the node that holds a PVC loses
the data.** No replica to promote, and this namespace has no Velero coverage and no barman
ObjectStore, so there is nothing to restore from either. Treat everything in `teak-talos-dev`
as reproducible from scratch.

The moment a work project holds something you would be upset to lose, that is the signal to
give that one cluster an `ObjectStore` + `ScheduledBackup`, or to raise it to `instances: 3` —
per workload, not by relaxing the convention.

This is documented, not enforced: nothing stops the work laptop from applying a 3-instance
Cluster (the quota caps CPU/memory/storage, not replica counts). Say the word if you'd rather
have a Kyverno policy pin `instances: 1` in this namespace.

## What the tenant can and cannot do

Enforced in four places, each independently verifiable:

| Boundary | File | Effect |
|---|---|---|
| Authorization | `rbac.yaml` | Namespaced Role only. No ClusterRole, no ClusterRoleBinding. |
| Blast radius | `quota.yaml` | ≤6 CPU / 16Gi requested, 50 pods, 100Gi storage, ≤5 CNPG clusters. |
| Network | `cilium-network-policy.yaml` | Default-deny. No egress to any other namespace or to the LAN. |
| Credentials | the Kyverno exclusion (below) | Work DB creds never reach the homelab dbgate. |

**Two deliberate non-obvious choices:**

1. **The built-in `edit` ClusterRole is NOT bound.** `edit` grants create/update on
   `networking.k8s.io/networkpolicies`, and Cilium evaluates NetworkPolicy and
   CiliumNetworkPolicy *additively* — so a tenant holding `edit` could apply one permissive
   NetworkPolicy and walk straight through the egress quarantine. `rbac.yaml` is `edit` minus
   that hole. If you ever swap it for a plain `edit` binding you silently lose the network
   isolation.
2. **Internet egress is a CIDR rule with exceptions, not `toEntities: [world]`.** Cilium stamps
   `reserved:world` on any non-cluster address — *including* `192.168.1.x`. Using `world` would
   have left the NAS, the router and every other box on the home network reachable from the
   work tenant.

## Credentials do not leave the namespace

The homelab auto-registers every CNPG database into its own dbgate via a Kyverno policy that
annotates `*-app` secrets for emberstack/reflector (see
[`docs/patterns/cross-namespace-secret-reflection.md`](../../../docs/patterns/cross-namespace-secret-reflection.md)).
That policy matches **cluster-wide**, so left alone it would copy this tenant's database
credentials into `databases` and surface them in the homelab UI — the reflection pattern would
quietly defeat the isolation.

`teak-talos-dev` is therefore **excluded** from that policy
([`infrastructure/base/kyverno-policies/reflect-cnpg-app-secrets.yaml`](../kyverno-policies/reflect-cnpg-app-secrets.yaml))
and runs **its own dbgate** instead, which reads the `-app` secrets directly as namespace
siblings. Same auto-provisioning behaviour, none of the cross-namespace exposure — and because
producer and consumer share a namespace, the whole Kyverno + reflector layer collapses away.
`dbgate-connection-sync/` needs no ClusterRole at all.

What the tenant's dbgate registers automatically:

- **every CNPG database** — the union of each Cluster's `initdb.database` *and* every `Database`
  CR pointing at it. Keying on `initdb` alone is the bug that made multi-tenant clusters show an
  empty schema in the homelab implementation.
- **every Dragonfly**, as a Redis connection (assumes no auth — the default-deny policy is what
  protects it). This is an addition over the homelab version; delete the block in
  `dbgate-connection-sync/configmap-script.yaml` if you don't want it.
- RabbitMQ is **not** registered — dbgate speaks no AMQP. Use the management UI.

Provisioning is a single writer (CronJob every 15 min + a dbgate initContainer so *a deploy is
a run*), never per-source mutation. The reasons that matters are in
[`docs/patterns/handoff-crd-driven-auto-registration.md`](../../../docs/patterns/handoff-crd-driven-auto-registration.md) §5.

## Day-2

```bash
# add a database to a CNPG cluster you deployed — dbgate picks it up within 15 min,
# or immediately on the next dbgate redeploy
kubectl apply -f - <<'YAML'
apiVersion: postgresql.cnpg.io/v1
kind: Database
metadata: { name: my-thing, namespace: teak-talos-dev }
spec:
  name: my_thing
  owner: <owner-role>
  cluster: { name: <your-cnpg-cluster> }
YAML

# force a sync now instead of waiting
kubectl -n teak-talos-dev create job --from=cronjob/dbgate-connection-sync sync-now
kubectl -n teak-talos-dev logs job/sync-now

# see what dbgate currently has
kubectl -n teak-talos-dev get secret dbgate-cnpg-connections -o jsonpath='{.data.CONNECTIONS}' | base64 -d

# rotate the laptop's credential
task k8s:teak-rotate-token
```

**When something "just doesn't start", check the quota first.** A quota rejection happens at
the ReplicaSet/StatefulSet layer, so there is no Pod to describe and no obvious error:

```bash
kubectl -n teak-talos-dev describe quota teak-talos-dev
kubectl -n teak-talos-dev describe rs,sts | grep -i -A3 'exceeded\|forbidden'
```

**When a pod starts but nothing connects**, it is almost always the network policy. Every pod
needs the `host`/`remote-node` ingress rule for kubelet probes and the `kube-apiserver` egress
rule (CNPG's instance manager and RabbitMQ's peer discovery both call the API from inside the
pod). Watch drops live:

```bash
kubectl -n kube-system exec ds/cilium -- hubble observe --namespace teak-talos-dev --verdict DROPPED
```

## Relaxing things

- **Reach a homelab service** → add an explicit egress rule to `cilium-network-policy.yaml`.
  Do not grant the tenant NetworkPolicy write instead.
- **Back up work data** → drop the `velero.io/exclude-from-backup` label *and* give the CNPG
  cluster a barman `ObjectStore` + `ScheduledBackup`. Velero is never the restore path for
  Postgres.
- **Private image pulls** → add the `ghcr-pull-secret: enabled` label to `namespace.yaml`
  (this mirrors a personal GHCR credential into the tenant — left off on purpose).
- **Stricter pods** → promote `pod-security.kubernetes.io/enforce` from `baseline` to
  `restricted` once you've confirmed the RabbitMQ operator's PodSpec passes the warnings.

## File map

| File | Role |
|---|---|
| `namespace.yaml` | namespace + PSA `baseline` + Velero exclusion |
| `quota.yaml` | ResourceQuota + LimitRange (incl. per-CRD object caps) |
| `rbac.yaml` | `teak-operator` SA + the explicit Role (no token Secret — see below) |
| `cilium-network-policy.yaml` | default-deny + the six allow rules |
| `dbgate/` | the tenant's own DB UI |
| `dbgate-connection-sync/` | single-writer sync → `dbgate-cnpg-connections` Secret |
| `ONBOARDING.md` | second-machine setup, Tilt, and the Flux/ArgoCD interaction |
| `certificate.yaml` | `*.teak.talos00` wildcard (the shared `*.talos00` cannot match a 2nd label) |
| `../../../clusters/catalyst-cluster/teak-talos-dev.yaml` | the Flux Kustomization |
| `../../../scripts/developer/teak-kubeconfig.sh` | mints the laptop kubeconfig |

---

## Related Issues

<!-- Beads tracking for this doc -->
