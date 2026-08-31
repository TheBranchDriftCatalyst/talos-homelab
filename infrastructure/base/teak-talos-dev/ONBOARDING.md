# Onboarding the work laptop to `teak-talos-dev`

How to get a second machine deploying into this namespace, and what the cluster's GitOps
controllers will and won't do to what you deploy.

> Prerequisite: the laptop must be on the home LAN — it talks straight to
> `https://192.168.1.54:6443`. There is no VPN or externally-exposed API endpoint.

---

## 1. On the homelab machine — mint the credential

```bash
cd ~/catalyst-devspace/workspace/talos-homelab
task k8s:teak-kubeconfig          # → .output/teak-talos-dev.kubeconfig
```

This mints a token via the TokenRequest API and writes a standalone kubeconfig with the cluster
CA embedded. The identity holds **one namespaced Role and nothing else** — no ClusterRole, no
ClusterRoleBinding.

**The token is valid for 365 days** and the script prints the exact expiry date. Re-run it to
mint a fresh one at any time.

> Why not a never-expiring legacy `service-account-token` Secret: auto-population of those is
> deprecated, and this cluster has zero of them — relying on that controller would bet the
> laptop's access on machinery nothing else here exercises. This apiserver grants the full
> 365 days on TokenRequest (verified), so there is no reason to.

**Revoking access** is `task k8s:teak-rotate-token`. That deletes and recreates the
ServiceAccount, which invalidates *every* token ever issued for it — tokens are bound to the
SA's UID. Simply re-minting does **not** revoke anything; TokenRequest tokens cannot be
individually cancelled.

## 2. On the work laptop — install it

```bash
scp <homelab-host>:~/catalyst-devspace/workspace/talos-homelab/.output/teak-talos-dev.kubeconfig \
    ~/.kube/teak-talos-dev
chmod 600 ~/.kube/teak-talos-dev
export KUBECONFIG=~/.kube/teak-talos-dev     # put this in your shell profile
```

The context is named `teak-talos-dev` and is pre-scoped to the namespace, so bare commands
already do the right thing:

```bash
kubectl get pods                 # no -n needed
kubectl config current-context   # teak-talos-dev
```

**Merging into an existing `~/.kube/config` instead** (if the laptop already has other
clusters):

```bash
KUBECONFIG=~/.kube/config:~/.kube/teak-talos-dev kubectl config view --flatten > /tmp/merged
mv /tmp/merged ~/.kube/config && chmod 600 ~/.kube/config
kubectl config use-context teak-talos-dev
```

Hostnames for the tenant's UIs — add to the laptop's `/etc/hosts`:

```
192.168.1.54  teak-dbgate.talos00 teak-whoami.talos00
```

## 3. Verify the boundary before you trust it

```bash
kubectl auth can-i create clusters.postgresql.cnpg.io    # yes
kubectl auth can-i create rabbitmqclusters.rabbitmq.com  # yes
kubectl auth can-i create dragonflies.dragonflydb.io     # yes
kubectl auth can-i list pods -n kube-system              # no
kubectl auth can-i list secrets --all-namespaces         # no
kubectl auth can-i create namespaces                     # no
kubectl auth can-i create networkpolicies                # no  ← see note below
```

`task k8s:teak-verify` runs all of these from the homelab side.

The **networkpolicies "no" is load-bearing, not an oversight.** Cilium evaluates NetworkPolicy
and CiliumNetworkPolicy additively, so the ability to create one NetworkPolicy would let you
punch straight through the namespace's egress quarantine. If you hit a case where the tenant
genuinely needs to reach something outside, add the rule to `cilium-network-policy.yaml` in
this repo rather than granting the permission.

---

## 4. Tilt

### The three things that will bite you

**a. Tilt refuses unknown contexts.** It blocks any context it doesn't recognise as local, to
stop accidental prod deploys. Your Tiltfile must opt in explicitly:

```python
allow_k8s_contexts('teak-talos-dev')
```

**b. Nothing cluster-scoped may appear in the rendered output.** The tenant identity cannot
create Namespaces, CRDs, ClusterRoles or ClusterRoleBindings — `kubectl apply` returns 403 and
Tilt fails the whole apply, not just that object. In particular **do not include a
`namespace.yaml`** in the kustomization; the namespace already exists and is Flux-managed.
Check before you run:

```bash
kubectl kustomize ./k8s | grep -E '^kind: (Namespace|CustomResourceDefinition|Cluster Role)'
# should print nothing
```

**c. Images must be pullable, and this namespace has no pull secret.** It is deliberately not
opted into the homelab's shared GHCR credential. Either use public images, or create your own
secret with your own work credentials — you have `secrets` write in the namespace:

```bash
kubectl create secret docker-registry work-pull \
  --docker-server=ghcr.io --docker-username=<user> --docker-password=<token>
kubectl patch serviceaccount default \
  -p '{"imagePullSecrets":[{"name":"work-pull"}]}'
```

Then in the Tiltfile: `default_registry('ghcr.io/<your-org>/<repo>')`.

Note image pulls are done by the kubelet on the node, **not** by the pod, so the namespace's
egress quarantine does not affect them.

### A minimal working Tiltfile

```python
# Tiltfile
allow_k8s_contexts('teak-talos-dev')
default_registry('ghcr.io/<your-org>/<repo>')

k8s_yaml(kustomize('./k8s'))          # must render namespaced objects only

docker_build('myapp', '.', dockerfile='Dockerfile')

k8s_resource('myapp', port_forwards='8080:8080', labels=['app'])
```

`port_forwards` works: port-forward traffic reaches the pod from the node, and the namespace's
network policy allows the `host`/`remote-node` identities precisely so kubelet probes and
port-forward keep working under default-deny. `live_update` works for the same reason.

`tilt down` deletes only what Tilt applied. It cannot touch the scaffolding.

---

## 5. Do Flux or ArgoCD need to ignore this namespace?

**Short answer: no, with one collision to design around.**

### ArgoCD — nothing to do

ArgoCD only manages what an Application explicitly points at. All eight Applications on this
cluster target their own app repos with explicit destination namespaces (`media`, `boomtime`,
`catalyst-data`, `catalyst-llm`, `catalyst`, `dungeon-library`, `monitoring`, `openscad`), and
there is no ApplicationSet. Nothing in ArgoCD can reach `teak-talos-dev`. No exclusion needed.

### Flux — no `spec.ignore` needed

**Flux prune is inventory-based.** kustomize-controller records the objects it applied and only
ever deletes things from that inventory. Objects Tilt creates were never applied by Flux, are
not in its inventory, and are invisible to prune. The same is true of drift correction — Flux
only diffs objects it owns.

So you can `tilt up` freely and Flux will not delete, revert, or fight your workloads.

### The one real collision: name clashes with the seed

Flux **does** own the demo workloads in `seed/`. If your kustomize renders an object with the
same kind + name + namespace as one of these:

| kind | name |
|---|---|
| Deployment | `whoami` |
| Cluster (CNPG) | `teak-postgres` |
| Database (CNPG) | `teak-app` |
| Dragonfly | `teak-cache` |
| RabbitmqCluster | `teak-rabbit` |
| Queue | `teak-demo` |
| Deployment / Service / PVC | `dbgate`, `dbgate-data` |

…then Flux and Tilt both manage it, and you get a revert loop: Tilt applies on save, Flux
reverts within 30 minutes. It also churns field ownership, because Tilt does a client-side
apply and Flux a server-side one.

Two clean fixes, in order of preference:

```bash
# 1. Just don't reuse those names. Nothing else is required.

# 2. Retire the demo. The seed is a SEPARATE Flux Kustomization precisely so this is safe:
flux suspend kustomization teak-talos-dev-seed
# ...or delete infrastructure/base/teak-talos-dev/seed/ and its cluster file for good.
```

Do **not** suspend `teak-talos-dev` itself — that is the scaffolding (namespace, quota, RBAC,
network policy, dbgate) your laptop depends on.

---

## 6. Objects you will see that you did not create

Don't be alarmed by these; they are cluster policy doing its job.

- **`NetworkPolicy/allow-monitoring-to-<name>`** — a Kyverno policy generates one per Dragonfly
  so Prometheus can scrape it. It is `policyTypes: [Ingress]` only, from the `monitoring`
  namespace, port 6379. It does not weaken the egress quarantine. It has `synchronize: true`,
  so deleting it just brings it back.
- **`inheritedMetadata.labels.velero.io/exclude-from-backup`** appearing on your CNPG Clusters —
  a Kyverno mutation. Harmless here; the whole namespace is already excluded from Velero.
- **TLS defaults on your IngressRoutes** — `ingressroute-tls-default` fills these in.
- Kyverno mutations are invisible to Flux's drift detection and are preserved by `kubectl
  apply`'s three-way merge, so neither controller will fight you over them.

Your IngressRoutes will **not** show up on the homelab homepage dashboard — those policies
require `gethomepage.dev/enabled: "true"`, which nothing here sets.

---

## 7. Troubleshooting

| Symptom | Cause | Check |
|---|---|---|
| Deployment created, no pods, no events on any pod | Quota rejection happens at the ReplicaSet layer — there is no Pod to describe | `kubectl describe quota teak-talos-dev`; `kubectl describe rs \| grep -i -A3 exceeded` |
| Pod runs but probes fail / restart-loops | network policy | `kubectl -n kube-system exec ds/cilium -- hubble observe --namespace teak-talos-dev --verdict DROPPED` |
| `Error from server (Forbidden)` on `tilt up` | cluster-scoped object in the rendered output | `kubectl kustomize ./k8s \| grep -E '^kind: (Namespace\|CustomResourceDefinition\|ClusterRole)'` |
| `ImagePullBackOff` | no pull secret in this namespace (deliberate) | §4c |
| Your change keeps reverting | name collision with a `seed/` object | §5 |
| CNPG cluster never reaches healthy | it needs the API server from inside the pod; that egress rule exists, but check quota/storage first | `kubectl describe cluster <name>` |
| Tilt: "Stop! ... is not a dev cluster" | missing `allow_k8s_contexts` | §4a |

---

## Related Issues

<!-- Beads tracking for this doc -->
