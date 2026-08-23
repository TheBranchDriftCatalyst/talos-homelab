# Cilium SPIRE / Mutual Authentication — Disposition

> Parent: [docs/02-architecture/README.md](README.md)
> Companion to [embedded-db-migration-audit.md](embedded-db-migration-audit.md) §3, which flagged
> SPIRE as a delete candidate. This document verifies that finding independently and takes it
> further.
> Investigated 2026-08-22/23 against the live cluster.
> Driver: [TALOS-1d4o] (blocks [TALOS-3gte] → [TALOS-k62s], EPIC 0 node prep).
>
> ## ✅ EXECUTED 2026-08-22 — user approved after review
>
> The recommendation below was carried out. Commit `9ce8e807` flips the two booleans and
> removes the four postRenderer patches; a follow-up commit removes the artifacts that became
> dead. **The CNI is healthy on all 5 nodes.** See [§10](#10-execution-record-2026-08-22)
> for the before/after health evidence and for two things this document did not predict:
> Server-Side Apply field-ownership residue that stopped Flux from removing the SPIRE
> plumbing on its own, and the fact that `spire-namespace.yaml` was never creating
> `cilium-spire` at all.
>
> **Rollback is `git revert 9ce8e807` plus `flux reconcile kustomization cilium --with-source`.**

## TL;DR

**Recommendation: DISABLE AND REMOVE.** Set `authentication.enabled: false` and
`authentication.mutual.spire.enabled: false` in `infrastructure/base/cilium/values.yaml`.

Every part of the case was verified against the live cluster, not taken on trust:

- **Nothing uses it.** 6 CiliumNetworkPolicies, 0 CiliumClusterwideNetworkPolicies, and **zero**
  references to `authentication` in any of them. SPIRE is enforcing nothing today.
- **It is deprecated in the exact version we run**, verbatim from the v1.20.0 chart:
  *"Deprecated as of Cilium v1.20, this feature will be removed in Cilium v1.21."*
- **The datastore is derived state, not a source of truth.** cilium-operator re-registered
  **258 identities in its first minute** on last startup. The PV is reconstructible.
- **Nothing fails closed.** With no policy in `authentication.mode: required`, removing SPIRE
  changes no traffic decision anywhere in the cluster.
- **The toil is real, ongoing, and NOT fixed.** The "durable fix" landed 2026-08-09 and the
  expired-token wedge still recurred on 2026-08-21. Agents perform a full node re-attestation
  **~10–13 times per hour, cluster-wide, right now** — every one of them reads the projected
  ServiceAccount token. This is the wedge surface, and it is continuous rather than cold-start-only.

**The "1Ti claim" is cosmetic.** The volume holds **14.5 MB**. See [§6](#6-the-1ti-is-not-real).

> **This is a recommendation, not an action.** It touches cluster-wide workload identity and is
> the user's call. Nothing in this investigation modified the cluster.

---

## 1. Is mutual authentication enabled, and is anything using it?

**Enabled as a capability: yes. Used by any policy: no.**

The capability is live in `cilium-config`:

```
mesh-auth-enabled                       = true
mesh-auth-mutual-enabled                = true
mesh-auth-spiffe-trust-domain           = spiffe.cilium
mesh-auth-spire-server-address          = spire-server.cilium-spire.svc:8081
```

But no policy consumes it. The field exists in the CRD (`cnp.spec.egress.authentication.mode`,
enum `disabled | required | test-always-fail`), so this is a real absence and not a naming miss:

| Check | Result |
| --- | --- |
| CiliumNetworkPolicies | **6** — `honeypot/{allow-dns-egress,allow-honeypot-ingress,default-deny-all}`, `iocaine/{allow-dns-egress,allow-traefik-ingress,default-deny-all}` |
| CiliumClusterwideNetworkPolicies | **0** |
| Policies referencing `authentication` | **0** (grep over full YAML of all of the above returns nothing) |

The six live policies are plain L3/L4 default-deny + allow rules for the two honeypot namespaces.
None of them requires authentication.

**Confirms the audit's finding.**

### No other consumer exists

SPIRE here is not general-purpose workload identity that something else might be quietly using:

- **No SPIRE/SPIFFE CRDs** are installed (`kubectl get crd | grep -i 'spiffe\|spire'` → empty).
- The **only** pods mounting a `spire` hostPath are Cilium's own: the 5 `spire-agent` pods,
  `spire-server-0`, the 5 `cilium` agents, and `cilium-operator`.
- The trust domain `spiffe.cilium` appears nowhere in `infrastructure/` or `applications/`
  outside the Cilium HelmRelease itself.

Nothing outside Cilium consumes this trust domain.

---

## 2. Is it genuinely deprecated in the version we run?

**Yes.** Running version, verified from the live DaemonSet and the agent itself:

```
quay.io/cilium/cilium:v1.20.0
Client: 1.20.0 450c5314 2026-07-29T08:53:01+02:00
Daemon: 1.20.0 450c5314 2026-07-29T08:53:01+02:00
```

Upstream `cilium/cilium` chart v1.20.0 `values.yaml`, immediately above the `mutual:` key —
this is the chart this cluster actually installs, not a later one:

```yaml
  # Deprecated as of Cilium v1.20, this feature will be removed in Cilium v1.21.
  # See https://github.com/cilium/cilium/issues/47132 for details.
  mutual:
```

[cilium#47132](https://github.com/cilium/cilium/issues/47132) ("Mutual Auth Deprecation and
Removal", opened 2026-07-13, still open) states it directly:

> Given the lack of progress on Mutual Auth, and the presence and at least equal stability of the
> new feature, **as of Cilium v1.20, Cilium committers are marking the Mutual Auth feature as
> deprecated, and will remove the feature in a later version, most likely v1.21**.

Two further points from that issue that matter here:

- The feature has been **Beta since 2023** and never left Beta.
- **Security support is limited**: *"as a Beta feature, security support is limited, so security
  reports and fixes for this functionality while the code is present will be handled on a
  case-by-case basis."*

It is superseded upstream by [zTunnel support](https://github.com/cilium/cilium/issues/38548),
which is under active development.

**Confirms the audit's finding.** There is no version of this where we get more life out of it:
the next Cilium major removes it. Keeping it means carrying a Beta, security-deprioritised,
scheduled-for-deletion feature that enforces nothing.

---

## 3. What exactly would disabling remove?

Generated by rendering the real chart at the real version with the real values file, twice —
once as-is, once with `authentication.enabled: false` + `mutual.spire.enabled: false` — and
diffing the resource sets. **Both render cleanly**, so disabling passes chart validation (this
matters: the values file has a comment warning that 1.19+ validation rejects
`mutual.spire.enabled` without `authentication.enabled`; turning *both* off is fine).

### 16 resources removed, 0 added

| Kind | Namespace | Name |
| --- | --- | --- |
| StatefulSet | cilium-spire | spire-server |
| DaemonSet | cilium-spire | spire-agent (**5 pods**) |
| Service | cilium-spire | spire-server |
| ConfigMap | cilium-spire | spire-server, spire-agent, spire-bundle |
| ServiceAccount | cilium-spire | spire-server, spire-agent |
| Role / RoleBinding | cilium-spire | spire-server, spire-server, spire-server-pod |
| ClusterRole / ClusterRoleBinding | — | spire-server, spire-agent (×2 each) |
| Namespace | — | cilium-spire |

### Plus, in-place changes

- **`cilium-config`**: 8 keys removed (`mesh-auth-mutual-enabled`, `mesh-auth-mutual-listener-port`,
  `mesh-auth-mutual-connect-timeout`, `mesh-auth-spiffe-trust-domain`, `mesh-auth-spire-agent-socket`,
  `mesh-auth-spire-admin-socket`, `mesh-auth-spire-server-address`,
  `mesh-auth-spire-server-connection-timeout`); `mesh-auth-enabled` flips `true` → `false`.
- **`cilium` DaemonSet and `cilium-operator` Deployment**: the `spire-agent-socket` volume is
  removed from both. **This changes both pod templates → both roll.** See [§5](#5-what-is-the-risk-of-disabling).

### What does NOT get removed automatically

Three things need explicit cleanup — this is the part that would otherwise leave the talos03 pin
in place and defeat the whole point:

1. **The PVC `cilium-spire/spire-data-spire-server-0`.** The StatefulSet's
   `persistentVolumeClaimRetentionPolicy` is `{whenDeleted: Retain, whenScaled: Retain}`, so
   deleting the STS leaves the PVC behind.
2. **The PV `rec-cilium-spire-spire-data-spire-server-0`.** `persistentVolumeReclaimPolicy: Retain`
   → it goes `Released`, not `Deleted`. **This is the talos03 pin.** It must be deleted explicitly.
3. **The `cilium-spire` Namespace**, because `infrastructure/base/cilium/spire-namespace.yaml` is a
   standalone resource in `kustomization.yaml`, independent of the chart. That file must be removed
   from `resources:` as well.

Note also: no CRDs are involved — SPIRE here installs none.

---

## 4. If it stays, what does losing the PV cost?

**Very little. The datastore is derived state, and the evidence is in the operator's own logs.**

This was the crux question in the ticket — *"if it rebuilds itself, the PV is accept-the-loss and
the whole question is moot."* It does rebuild itself.

### The registration entries are reconstructed from CiliumIdentity

`cilium-operator` maintains a SPIRE registration entry per CiliumIdentity. On its last restart
(2026-08-21T18:32) it logged **258 `Upsert identity` events in that single minute**, then settled
into a low background rate:

```
 258 2026-08-21T18:32     <- full reconcile at startup
   2 2026-08-21T18:46
   1 2026-08-21T19:00
  17 2026-08-21T19:02
   ...
```

258 upserts against **265 CiliumIdentities** currently in the cluster is a full reconcile of the
identity set, not a delta replay. The source of truth is the CiliumIdentity CRs in etcd; the
SPIRE datastore is a projection of them.

(The server currently reports **377 registration entries** — the 265 identity entries plus the
`cilium-agent`/`cilium-operator` entries and accumulated stale ones. The excess is itself evidence
that the datastore drifts and is not precious.)

### The agents can all re-attest

All 5 agents report `Can re-attest: true` (k8s_psat is a re-attestable node attestor). Losing the
CA does not strand them — they re-attest and receive new SVIDs.

### The CA keys regenerate, and the trust bundle is republished automatically

`keys.json` (12 KB) is the CA signing key material. If lost, the server generates a **new** CA.
The `Notifier "k8sbundle"` plugin then republishes the new trust bundle into the `spire-bundle`
ConfigMap in `cilium-spire`, which is how agents pick it up. That is a config-driven, automatic
path — no manual re-bootstrap.

### Conclusion on question 4

Losing the PV costs **one re-attestation cycle**. It does not invalidate identities in any way
that requires operator intervention beyond a `rollout restart ds/spire-agent` so agents pick up
the new trust bundle promptly.

**This means the PV is "accept-the-loss" even in the KEEP case.** There is no backup worth taking:
the SQLite file is a rebuildable projection, and the CA keys are *supposed* to be rotatable. The
only correct "backup" is knowing you can throw it away.

> **Do not move this PVC to NFS as a shortcut.** That would put both the SQLite datastore and the
> CA signing keys on NFS. [cilium#46392](https://github.com/cilium/cilium/issues/46392) documents a
> production cluster deadlocking on exactly this shape — the SPIRE datastore's storage control
> plane being gated by the mutual-auth policy SPIRE itself enforces. We are not exposed today
> (`local-path` is a hostPath with no in-cluster CSI traffic, and no policy requires auth), but
> it is a live trap for anyone who later enables a `required`-mode policy.

---

## 5. What is the risk of disabling?

### Nothing fails closed

This is the decisive safety point. In Cilium, mutual auth is enforced **per-policy** via
`authentication.mode: required`. With **zero** policies setting it, there is no traffic decision
anywhere in the cluster that consults SPIRE. Removing it cannot deny traffic that is currently
allowed.

The two namespaces that *do* have `default-deny-all` (honeypot, iocaine) deny on L3/L4 rules that
make no reference to authentication; they are unaffected.

### The real risk is the DaemonSet rollout, not the loss of SPIRE

Disabling removes the `spire-agent-socket` volume from both the `cilium` DaemonSet and the
`cilium-operator` Deployment. That is a pod-template change, so **the CNI DaemonSet rolls across
all 5 nodes.**

In this cluster that is the thing to plan around, not SPIRE itself. The repo's own HelmRelease
comments record why: the 2026-05-29 meltdown involved a DS rollout during take-ownership, and
`prune` is deliberately `false` on the Cilium Flux Kustomization precisely so nothing can mass-
delete CNI resources. Any execution of this change should be done deliberately, watching the
rollout node by node — the same care any Cilium values change gets.

### Reversibility

Fully reversible in the "turn it back on" sense — flip the two values back and the chart
re-renders all 16 resources. What is *not* recovered is the old CA and datastore; a re-enable
starts a fresh trust domain and all agents re-attest. Given [§4](#4-if-it-stays-what-does-losing-the-pv-cost),
that is the same cost as any PV loss, i.e. low.

---

## 6. The "1Ti" is not real

Worth recording because it changes how urgent this looks in PV listings.

The PV advertises `1Ti`, but:

- The **PVC requests `1Gi`** (and so does the StatefulSet's `volumeClaimTemplate`, matching
  `values.yaml`'s `dataStorage.size: 1Gi`).
- The `1Ti` comes from a **hand-written recovery PV**, `recovery/pv-recovery-2026-05-09.yaml`,
  created during the 2026-05-09 UPS incident (`recovery.catalyst/incident: "ups-2026-05-09"`).
- It is a `hostPath` volume on `local-path`. **There is no quota** — the capacity field is a label,
  not a reservation.

Actual contents on talos03, measured directly:

| File | Size | What it is |
| --- | --- | --- |
| `datastore.sqlite3` | 10.2 MB | registration entries, agent records, CA journal |
| `datastore.sqlite3-wal` | 4.2 MB | WAL |
| `datastore.sqlite3-shm` | 32 KB | shared-memory index |
| `journal.pem` | 29 KB | CA journal |
| `keys.json` | 12 KB | **CA signing keys** |
| **Total** | **~14.5 MB** | |

So the pin on talos03 is real and does block the node reset, but nothing about it is large. The
node-bound PV is the entire problem; the capacity is a red herring.

Note this also independently confirms the audit's first reason: `keys.json` sits on the **same
volume** as the SQLite file, so migrating the datastore to Postgres would not remove the PVC and
would not un-pin talos03. Migration was never the answer.

---

## 7. The operational cost — the "durable fix" did not hold

This is the finding that turns "harmless, leave it" into "it is actively costing us".

### The wedge recurred *after* the durable fix was live

The known failure mode: a kubelet restart wedges spire-agent's projected ServiceAccount token into
a self-perpetuating expired-token CrashLoopBackOff. Two mitigations are in the repo:

1. SA token TTL raised 600s → 3600s (HelmRelease postRenderer).
2. `KeyManager "disk"` on an emptyDir `data_dir`, so the agent renews its SVID instead of
   re-attesting — commit `ab933026`, **2026-08-09**.

Both are confirmed live: the DaemonSet's `spire-agent-data` emptyDir and `expirationSeconds: 3600`
are present in ControllerRevision **12** (2026-08-09T14:33) and still present in the current
revision **20**.

**And the wedge happened anyway.** From spire-agent logs on 2026-08-21, on at least talos03 and
talos06:

```
2026-08-21T23:40:29Z level=error msg="Could not reattest agent"
  error="... nodeattestor(k8s_psat): unable to validate token with TokenReview API
  for cluster \"talos-home\": token review API response contains an error:
  [invalid bearer token, service account token has expired]"
```

It ran from 23:40 until the agent pods were recreated at **2026-08-22T00:49:45** (all 5 agents now
show `restarts=0` with that creation time — they were deleted and recreated, the manual fix).
cilium-operator was disconnected from the Workload API for that whole window, logging
`dial unix /run/spire/sockets/agent/agent.sock: connect: no such file or directory` every 30s
until 00:49:57.

So: **the fix that was supposed to end this class of failure was in place for 12 days and did not
prevent the next occurrence.**

### Why it cannot hold — the token is on the hot path continuously

The emptyDir fix assumed re-attestation is a cold-start-only event. It is not. spire-server logs a
steady **10–13 completed `AttestAgent` (k8s_psat) requests per hour**, cluster-wide, measured over
the last 22 hours:

```
10, 10, 10, 12, 13, 10, 10, 10, 10, 12, 13, 10, 10, 10, 10, 11, 13, 11, 10, 10, 10, 13, 10
```

That is 5 agents each doing a **full node re-attestation roughly every 30 minutes**, indefinitely —
with zero pod restarts in the window. Every one of those calls reads the projected SA token and
validates it via TokenReview against the apiserver.

Because the projected token is exercised on a ~30-minute cycle rather than only at pod start, an
emptyDir that survives container restarts cannot take the token off the critical path. The wedge
surface is permanent.

### This recurs on exactly the EPIC 2 path

Every node upgrade restarts kubelet. The 2026-08-22 occurrence was triggered by the maxPods patch
restarting kubelet on all 5 nodes. [TALOS-xipf] (EPIC 2, Talos 1.13.2 → 1.13.9) and
[TALOS-y7q1]/[TALOS-33jl] (Kubernetes upgrades) will each do the same thing across the fleet.

**We would be paying this cost, on every node upgrade, for a Beta feature that enforces nothing and
that upstream deletes in the next release.**

---

## 8. Recommendation

**DISABLE AND REMOVE.**

The case does not rest on any single finding. Independently: it is unused, it is deprecated with a
removal date, its state is reconstructible so there is nothing to protect, nothing fails closed if
it goes, and it is generating recurring toil that the attempted fix demonstrably did not stop.
There is no scenario in which keeping it pays off, because Cilium v1.21 removes it regardless.

Removing it also clears one of the two remaining pins on talos03 and unblocks [TALOS-3gte].

### Steps — if the user approves

All GitOps, per the Flux/infra demarcation. Cilium is CNI → Flux.

1. **Edit `infrastructure/base/cilium/values.yaml`** — set both flags false (both are required;
   `mutual.spire.enabled: true` with `authentication.enabled: false` fails chart validation):

   ```yaml
   authentication:
     enabled: false
     mutual:
       spire:
         enabled: false
   ```

2. **Remove `spire-namespace.yaml`** from `resources:` in
   `infrastructure/base/cilium/kustomization.yaml`, and delete the file. It is standalone and will
   otherwise keep recreating the namespace.

3. **Remove the three SPIRE postRenderer patches** from `infrastructure/base/cilium/helmrelease.yaml`
   — the `cilium-spire` Namespace PSA patch, the SA-token-TTL patch, and the KeyManager-disk
   ConfigMap + emptyDir patches. **This matters:** the token-TTL patch contains an `op: test` guard
   against `/spec/template/spec/volumes/3/...`, and the ConfigMap/DaemonSet patches target
   resources that will no longer be rendered. Leaving them in place means the postRender aborts —
   and per this repo's own history ([helm-postrenderer-add-vs-smp]), a failing postRenderer aborts
   **silently**. Grep helm-controller logs after the reconcile.

4. **Reconcile with source** (`--with-source`, or the reconcile applies the already-fetched
   revision and you verify stale state):

   ```
   flux reconcile source git flux-system
   flux reconcile kustomization cilium --with-source
   ```

5. **Watch the Cilium DaemonSet roll.** This is the actual risk window — see
   [§5](#5-what-is-the-risk-of-disabling). Node by node, confirm agents come back healthy before
   proceeding. Note `prune: false` on the Cilium Flux Kustomization means Flux will **not** delete
   the removed SPIRE resources — step 6 is mandatory, not optional cleanup.

6. **Clean up what Flux will not** (this is what actually un-pins talos03):

   ```
   kubectl -n cilium-spire delete statefulset spire-server
   kubectl -n cilium-spire delete pvc spire-data-spire-server-0
   kubectl delete pv rec-cilium-spire-spire-data-spire-server-0
   kubectl delete namespace cilium-spire
   ```

   Then remove the `rec-cilium-spire-spire-data-spire-server-0` entry from
   `recovery/pv-recovery-2026-05-09.yaml` so it is not resurrected.

7. **Verify**: `kubectl get pv | grep spire` empty, `kubectl get ns cilium-spire` not found,
   `kubectl -n kube-system get cm cilium-config -o yaml | grep mesh-auth` shows only
   `mesh-auth-enabled: "false"`, and cilium/cilium-operator pods healthy on all 5 nodes.

### Also worth doing

[service-mesh.md](service-mesh.md) currently presents Cilium mTLS as the chosen service-mesh
direction and gives step-by-step instructions to *enable* this feature (including a
`require-mtls` policy example). That doc will walk someone straight into a removed feature and
into the [cilium#46392](https://github.com/cilium/cilium/issues/46392) trap. It should be marked
stale or rewritten to point at zTunnel. Not done here — out of scope for this ticket.

---

## 9. Coverage — what was and was not verified

**Verified directly against the live cluster / upstream:**

- Cilium version, from the DaemonSet image *and* `cilium version` on the agent.
- Policy counts and the absence of `authentication`, including confirming the CRD field exists.
- The deprecation text, from the v1.20.0 chart itself and from cilium#47132.
- The removed-resource set, by rendering the real chart at the real version with the real values.
- PVC/PV/STS retention semantics, from live object specs.
- On-disk contents and sizes, read from talos03 via `talosctl`.
- The 258-upsert startup reconcile and the CiliumIdentity count.
- `Can re-attest: true` for all 5 agents, from `spire-server agent list`.
- The 2026-08-21 wedge and the ~10–13/hr re-attestation rate, from Loki.
- That the emptyDir + 3600s TTL fix was live in ControllerRevisions 12 and 20.

**Inferred, not directly observed:**

- That the ~30-min-per-agent re-attestation cadence is what keeps the projected token on the hot
  path. The *rate* and the *wedge* are both measured facts; the causal link between them is a
  reading of SPIRE's attestation flow, not something I reproduced. It does not change the
  recommendation — the wedge recurring after the fix is observed either way.
- Trust-bundle republication after CA loss is read from the `Notifier "k8sbundle"` config and
  SPIRE's documented behaviour; no CA loss was induced to test it.

**Not done (deliberately):** nothing was disabled, deleted, scaled or patched. No backup was taken,
because [§4](#4-if-it-stays-what-does-losing-the-pv-cost) concludes there is nothing worth backing up.

---

## 10. Execution record (2026-08-22)

Executed on user approval. Recorded here because two things did not go the way
[§3](#3-what-exactly-would-disabling-remove) predicted, and both are reusable lessons.

### What was changed in git

| Commit | Contents |
| --- | --- |
| `9ce8e807` | `values.yaml` both booleans → false; all four postRenderer patches removed; `spire-namespace.yaml` deleted and replaced by `kube-system-namespace.yaml` |
| follow-up | dead artifacts: `wedge-buster-spire-agent` CronJob, `spire-alerts.yaml`, the `spire-health` dashboard (CRD + JSON), the `cilium-spire` entries in `velero.yaml` and the OTel operator `namespaceSelector`, and the recovery PV entry |

Before committing, the chart was rendered at v1.20.0 with the real values file both ways and
the resource sets diffed: **63 → 47 resources, exactly the predicted 16 removed, 0 added**, and
the only content changes among the 47 survivors were `cilium-config` and the `spire-agent-socket`
volume leaving the two pod templates. Nothing else moved.

### Surprise 1 — `spire-namespace.yaml` never created `cilium-spire`

`infrastructure/base/cilium/kustomization.yaml` sets `namespace: kube-system`. Kustomize's
namespace transformer does not merely stamp `metadata.namespace` on namespaced resources — for a
`Namespace` object it **rewrites `metadata.name`**. So that file rendered as
`Namespace/kube-system` carrying `pod-security.kubernetes.io/enforce|warn: privileged`, and the
live `kube-system` Namespace is labelled `kustomize.toolkit.fluxcd.io/name: cilium` to prove it.
`cilium-spire` was created by the chart the whole time (`app.kubernetes.io/managed-by: Helm`).

The helmrelease.yaml comment claiming *"the standalone spire-namespace.yaml has been quietly
doing all the work"* was therefore wrong about which namespace it was working on. It was
silently maintaining kube-system's PSA labels. Those labels are **inert** — kube-system is in
the apiserver's PodSecurity `exemptions.namespaces` (with `media-prod` and `local-path-storage`),
so PSA is bypassed there regardless of labels — but they are now asserted by an honestly-named
`kube-system-namespace.yaml` that renders byte-identically, rather than by accident.

### Surprise 2 — SSA field ownership stopped Flux from finishing the job

After `flux reconcile kustomization cilium --with-source`, helm upgraded to release **17** and the
deployed manifest was correct (0 SPIRE references, `mesh-auth-enabled: "false"`). Helm deleted the
`cilium-spire` namespace and everything in it. **But the live `cilium` DaemonSet did not roll** —
generation stayed at 14 and it still mounted `spire-agent-socket`, and `cilium-config` still
carried the 8 `mesh-auth-spire-*` keys.

Cause: `kubectl get ds cilium --show-managed-fields` shows the DaemonSet has **six** field
managers, including `manager=helm op=Apply time=2026-05-29T19:39:50Z` — the original manual
`helm upgrade --take-ownership` — and that stale manager still **owns** the `spire-agent-socket`
volume entry. Server-Side Apply only removes fields the *applying* manager owns. helm-controller
applied a manifest without the volume, but it never owned that field, so the field stayed.

Consequence while stale: the running agents and operator still had mutual auth enabled with SPIRE
already deleted, and retried every 10–20s —
`SPIRE Delegate API Client failed to init watcher` on the agents,
`Failed to watch the Workload API ... no such file or directory` on the operator. Warn-level,
no traffic impact (nothing fails closed, per [§5](#5-what-is-the-risk-of-disabling)), but not a
finished change.

Resolved with three guarded patches, in ascending blast-radius order, converging live state onto
the already-committed desired state:

1. `cilium-config` — removed the 8 stale `mesh-auth-*` keys (no pod impact).
2. `cilium-operator` Deployment — removed the volume + mount; single replica, rolled clean.
3. `cilium` DaemonSet — removed the volume + mount; rolled all 5 nodes at `maxUnavailable: 1`.

> **This is not SPIRE-specific and it is not over.** Any field the pre-Flux manual install set is
> currently beyond Flux's reach on the Cilium DaemonSet, Deployment and ConfigMap. A live audit
> found **17** keys in `cilium-config` that the v1.20.0 chart no longer renders; only 8 were
> SPIRE's. The other 9 — `arping-refresh-period`, `debug-verbose`,
> `enable-k8s-terminating-endpoint`, `enable-local-redirect-policy`,
> `enable-runtime-device-detection`, `enable-svc-source-range-check`,
> `hubble-export-file-max-backups`, `hubble-export-file-max-size-mb`, `policy-cidr-match-mode` —
> are older-chart leftovers that are **still in effect** on the running agents. They were left
> alone deliberately: removing them changes agent behaviour and has nothing to do with SPIRE.
> Worth its own ticket.

### CNI health — before and after

| Check | Before (01:01Z) | After (01:11Z) |
| --- | --- | --- |
| cilium-agent pods Running | 5/5 | **5/5**, all 5 rolled, 0 restarts |
| `cilium-dbg status --brief`, per node | OK ×5 | **OK ×5** |
| Controller Status (talos00) | 64/64 healthy | **75/75 healthy** |
| Modules Health | Degraded(0) OK(116) | **Degraded(0) OK(111)** |
| Nodes Ready | 5/5 | **5/5** |
| Pods stuck ContainerCreating | 0 | **0** |
| agent `level=error` in last 60s | — | **0 on all 5 nodes** |
| CiliumNetworkPolicies | 6 | **6** |
| CiliumClusterwideNetworkPolicies | 0 | **0** |
| Policies referencing `authentication` | 0 | **0** |
| CiliumIdentities | 289 | **290** (stable; meltdown signature is >1000) |

Agents now log `Spire Delegate API Client is disabled as no socket path is configured` and make
no further SPIRE connection attempts. The `--mesh-auth-spire-*` lines still visible in the startup
flag dump are Cilium's compiled-in defaults (note `spire-server.spire.svc`, not our old
`spire-server.cilium-spire.svc`), inert with `mesh-auth-enabled: false`.

### What remained, and why

- **`cilium-spire` Namespace: `Terminating`.** It is empty — all content deleted, no finalizers
  remaining. It is blocked on `NamespaceDeletionDiscoveryFailure` for
  `upload.cdi.kubevirt.io/v1beta1`, a transient CDI aggregated-API discovery failure at 01:03:14Z.
  All APIServices including that one now report `Available=True`, so the namespace controller
  should finalize on retry. **Unrelated to SPIRE** — it would block any namespace deletion.
- **PV `rec-cilium-spire-spire-data-spire-server-0`: `Released`, not deleted.** The PVC is gone
  (so the StatefulSet and its claim are cleared) but the PV has `persistentVolumeReclaimPolicy:
  Retain` and `recovery/` is **not** Flux-managed — it was applied by hand, so removing the entry
  from git cannot delete the live object. **This is still the talos03 pin and still needs one
  manual command**, which requires operator approval:

  ```
  kubectl delete pv rec-cilium-spire-spire-data-spire-server-0
  ```

  Until then talos03 carries **14** node-bound PVs instead of 13. The other 13 are the
  `media-experimental` configs and `pihole/etc-pihole-pihole-4` — a separate workstream.
  The ~14.5 MB of hostPath data under
  `/var/lib/rancher/local-path-provisioner/pvc-e031fb33-..._cilium-spire_spire-data-spire-server-0`
  can be left to the node reset; per [§4](#4-if-it-stays-what-does-losing-the-pv-cost) it is
  worthless.

### Still stale, not touched

[service-mesh.md](service-mesh.md) still presents Cilium mTLS as the chosen direction and gives
instructions to *enable* this feature. It will now walk someone into a removed feature. Flagged in
[§8](#8-recommendation) as out of scope; still true, still needs doing.

---

## Related Issues

- [TALOS-1d4o] — this investigation
- [TALOS-3gte] — talos03 node-bound PVs (blocked by this)
- [TALOS-k62s] — EPIC 0, un-node-bind PVCs before control-plane reset
- [TALOS-xipf] — EPIC 2, Talos fleet upgrade (each node upgrade re-triggers the spire-agent wedge)
- [TALOS-o40f] — cilium-operator SPIRE agent-socket error (closed as "likely transient" —
  §7 shows it was not transient; it was the 2026-08-21 wedge)
