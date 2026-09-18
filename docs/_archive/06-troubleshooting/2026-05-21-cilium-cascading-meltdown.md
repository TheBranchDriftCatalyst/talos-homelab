# Post-Mortem: Cilium DS Restart Caused Cluster Meltdown

**Date:** 2026-05-21
**Duration of impact:** ~40 minutes
**Severity:** Full control-plane unreachable from kubectl
**Blast radius:** All 5 nodes affected (control plane network broken)

## TL;DR

A routine fix to Cilium's BPF policy map size triggered a `DaemonSet rollout restart`
which, combined with a **latent broken admission webhook** (opentelemetry-operator),
caused the cluster control plane to become unreachable. Recovery required:

1. Force-rebooting `talos00` (control plane)
2. Deleting the `opentelemetry-operator-{mutation,validation}` webhook configs that
   were blocking apiserver on every pod create/update

The actual change (BPF map size bump) was correct and necessary — the **trigger** was
how it was applied (DS rollout restart) interacting with a pre-existing webhook problem.

## What Triggered It

After the Talos v1.13.2 upgrade earlier in the session, we discovered Flux controllers
were stuck in `ContainerCreating` with errors like:

```
plugin type="cilium-cni" failed (add): unable to create endpoint:
Cilium API client timeout exceeded
```

Root cause: Cilium's BPF policy map was full:

```
"Failed to add PolicyMap key" ... error="update map cilium_policy_00771:
update: no space left on device"
```

Default `bpf-policy-map-max: "16384"` was overflowing under our identity count
(~50 namespaces × multiple policies). Increasing to `65536` was the correct fix.

## The Fix We Applied (Correct in Isolation)

```bash
kubectl patch cm -n kube-system cilium-config --type=merge \
  -p '{"data":{"bpf-policy-map-max":"65536","bpf-lb-map-max":"65536"}}'
kubectl rollout restart ds -n kube-system cilium
```

We also persisted it in `configs/cilium-values.yaml` and `configs/cilium-manifest.yaml`.

## Why It Cascaded

1. **`kubectl rollout restart ds cilium`** brought down all 5 Cilium agents
   approximately simultaneously (the DaemonSet's default rollingUpdate.maxUnavailable=1
   _should_ have prevented this, but the rolling restart is staggered by pod terminationGracePeriod
   and during heavy load each agent took several minutes to come up healthy, so multiple
   agents were down at once).

2. **Cilium agent startup deadlock**: each fresh agent attempts to connect to apiserver
   at `https://192.168.1.54:6443` with a **65-second total startup health check**.
   While agents are starting:
   - apiserver pod's networking is impaired (CNI in transition)
   - apiserver is also processing a flood of Flux Kustomization reconciliations
     (~50 controllers all trying to re-establish watches at once)
   - Pod admission webhooks are called on every pod create

3. **The hidden poison: opentelemetry-operator webhook**. Its operator pod had been
   stuck in `CrashLoopBackOff` for 12 days but its
   `MutatingWebhookConfiguration` was still registered. Every pod create — including
   Cilium agent pods — caused apiserver to call:
   ```
   POST https://opentelemetry-operator-webhook.monitoring.svc:443/mutate-v1-pod
   ```
   With `failurePolicy: Ignore` it should have failed open after timeout, but the
   error pattern was:
   ```
   dial tcp 10.96.253.148:443: connect: operation not permitted
   ```
   ("operation not permitted" likely from Cilium's eBPF filter rejecting the service
   IP route while Cilium itself was in flux.) Each call took 10s before "failing open".

4. **The cascade**:
   - Cilium DS rollout begins → first agent restarts → apiserver tries to admit it → webhook stall
   - More agents go down before first one comes up
   - Cilium on talos00 (control plane) crashes → apiserver's network impaired
   - Other Cilium agents can't reach apiserver → their 65s startup timeout expires → `FATAL`
   - Stuck.

5. **kube-controller-manager and kube-scheduler crashed** on talos00 from connection
   loops to the localhost talos-api-proxy that ultimately needed Cilium to be healthy.

## Recovery Steps

```bash
# 1. Force-reboot the control plane (cleanest path back from network meltdown)
talosctl --talosconfig ./configs/talosconfig --nodes 192.168.1.54 reboot --mode=force --wait

# 2. After reboot, Cilium agents still couldn't start because of the webhook.
#    Identify and delete the offending webhooks:
kubectl delete mutatingwebhookconfigurations opentelemetry-operator-mutation
kubectl delete validatingwebhookconfigurations opentelemetry-operator-validation

# 3. Delete the failing Cilium pods to force fresh startup
kubectl delete pod -n kube-system -l k8s-app=cilium --field-selector status.phase!=Running
```

Within ~2 minutes all 5 Cilium agents were `Running` and the cluster was healthy.

## Preventive Fixes — Apply These BEFORE Future Cluster-Wide Operations

### 1. Pre-flight webhook health check in cluster automation

Any script that performs cluster-wide restart (`shutdown-cluster.sh`, `upgrade-talos.py`,
or a future "rolling-restart-cilium" script) must first verify all admission webhooks
have a healthy backend. Code sketch:

```python
def check_admission_webhooks() -> list[str]:
    """Return a list of webhooks whose service backend isn't responsive."""
    broken = []
    for w in (kubectl_get("mutatingwebhookconfigurations") +
              kubectl_get("validatingwebhookconfigurations")):
        for wh in w["webhooks"]:
            svc = wh.get("clientConfig", {}).get("service")
            if not svc:
                continue
            # Verify the service has Ready endpoints
            eps = kubectl_get(f"endpoints/{svc['name']}", namespace=svc["namespace"])
            if not eps.get("subsets"):
                broken.append(f"{w['metadata']['name']}/{wh['name']} → {svc['namespace']}/{svc['name']} (no endpoints)")
    return broken
```

If any webhook is broken, the script must:
- WARN loudly
- Refuse to run cluster-wide operations
- Suggest deleting the broken webhook or fixing its backend first

### 2. Set `failurePolicy: Ignore` on opentelemetry-operator webhook

In `infrastructure/base/monitoring/opentelemetry-operator/`, ensure the helm values
include:
```yaml
admissionWebhooks:
  failurePolicy: Ignore
  namespaceSelector:
    matchExpressions:
      - key: kubernetes.io/metadata.name
        operator: NotIn
        values: [kube-system, flux-system, monitoring, cilium-spire]
```

Even with `Ignore`, the 10s timeout still delays pod admission — but at least won't
block.

### 3. Track BPF map sizes in Cilium values, not just defaults

`configs/cilium-values.yaml` now has:
```yaml
bpf:
  policyMapMax: 65536
  lbMapMax: 65536
```

For clusters > 50 namespaces, this should be the **starting** value, not a reactive fix.
Document this in the cluster bootstrap runbook.

### 4. Cilium DS restart should be staged, not parallel

For future BPF/Cilium config changes, do a careful one-node-at-a-time rollout:

```bash
# Don't: kubectl rollout restart ds -n kube-system cilium
# Do:
for pod in $(kubectl get pod -n kube-system -l k8s-app=cilium -o name); do
  kubectl delete "$pod"
  sleep 60
  # Verify the new pod is Running before continuing
  until kubectl wait --for=condition=ready pod -n kube-system -l k8s-app=cilium \
          --field-selector spec.nodeName=$node --timeout=120s; do
    sleep 10
  done
done
```

Better yet: build this as `scripts/safe-restart-cilium.sh`.

### 5. Add a "cluster integrity" pre-check to `upgrade-talos.py`'s health check

The current `health_check()` function should ALSO verify:
- All `MutatingWebhookConfiguration` and `ValidatingWebhookConfiguration` have healthy
  service endpoints
- BPF policy map utilization (read from a sample Cilium agent)

Failing webhook = upgrade aborts unless `--skip-health-check`. (We saw exactly why
that gate is important — proceeding through a known-broken-webhook cluster is
explicitly dangerous.)

### 6. Document this scenario in `docs/05-runbooks/cilium-meltdown-recovery.md`

A runbook that says: "If kubectl times out and Cilium agents are stuck FATAL on
apiserver timeouts, check webhooks first. Reboot CP last."

## Action Items Tracker

- [ ] Add `check_admission_webhooks()` pre-flight to `upgrade-talos.py` (this script)
- [ ] Add `check_admission_webhooks()` pre-flight to `shutdown-cluster.sh`
- [ ] Set `failurePolicy: Ignore` on opentelemetry-operator webhook
- [ ] Create `scripts/safe-restart-cilium.sh` for staged DS restart
- [ ] Document BPF map sizing in cluster-bootstrap runbook
- [ ] Fix the underlying opentelemetry-operator CrashLoopBackOff (was broken 12d+)
