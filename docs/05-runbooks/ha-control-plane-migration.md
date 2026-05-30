# HA Control Plane Migration Runbook

**Beads issue:** TALOS-arx
**Target topology:** talos00 + talos01 + talos06 (3 CPs), talos02-gpu + talos03 (2 workers)
**Risk:** HIGH — destructive on talos01 and talos06 (full Talos reinstall)
**Estimated time:** 3–4 hours total, ~30 min downtime per promoted node
**Prerequisites:** This runbook assumes everything from the 2026-05-29 post-mortem is committed and Cilium values point at KubePrism (localhost:7445)

---

## Why this is the real fix

Per [docs/06-troubleshooting/2026-05-29-six-meltdowns-and-the-real-root-cause.md](../06-troubleshooting/2026-05-29-six-meltdowns-and-the-real-root-cause.md), the recurring meltdown pattern is:

```
cilium-agent restart on CP node → BPF cgroup reload → host networking briefly broken
  → apiserver unreachable from outside → cluster dark
```

With 3 CPs, the cilium hiccup on talos00 only affects talos00's local pods. kubectl/Flux/users reach apiservers on talos01 or talos06 unaffected. Cluster as a whole survives any single CP cilium flap.

KubePrism (`localhost:7445`) on every node then routes to whichever apiserver is healthy automatically.

---

## Pre-flight — DO NOT SKIP

### 1. Verify cluster is currently healthy

```bash
kubectl get nodes
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded
talosctl --talosconfig configs/talosconfig --nodes 192.168.1.54 etcd status
talosctl --talosconfig configs/talosconfig --nodes 192.168.1.54 etcd members
```

All nodes Ready. No broken pods. etcd healthy. **If any of these fail, fix first — do not start an HA migration on a sick cluster.**

### 2. Backup etcd (in case we need to restore)

```bash
# Trigger a manual snapshot
kubectl create job -n backup --from=cronjob/etcd-backup ha-migration-pre-snapshot-$(date +%s)

# Wait for it to complete
kubectl get jobs -n backup -w  # ctrl-C when ha-migration-pre-snapshot shows COMPLETIONS 1/1

# Verify snapshot is in S3
kubectl logs -n backup -l job-name=ha-migration-pre-snapshot-<TS> | grep "Uploading"
```

### 3. Identify and migrate PVCs on target nodes

talos01 and talos06 will be **wiped and reinstalled** during this process. Any local-path PVCs on them will be destroyed.

```bash
# Find local-path PVs bound to PVCs on talos01 and talos06
for node in talos01 talos06; do
  echo "=== $node ==="
  kubectl get pv -o json | jq -r --arg n "$node" \
    '.items[] | select(.spec.nodeAffinity.required.nodeSelectorTerms[]?.matchExpressions[]?.values[]? == $n) | .metadata.name + " → " + .spec.claimRef.namespace + "/" + .spec.claimRef.name'
done

# For each PVC found:
#   - Identify the workload using it (kubectl get pvc -n NS -o yaml)
#   - Decide: migrate (use Velero or manual restore), recreate (acceptable data loss), or skip the migration
```

**If any irreplaceable PVCs are pinned to talos01/06, STOP and migrate them first.**

### 4. Drain comm + maintenance window

- Tell anyone using the cluster
- Plan for ~30 min API blip per node promotion (2 nodes = 1 hour total cluster degradation potential)
- Schedule outside of backup windows, observability spike windows, etc.

### 5. Verify the talosconfig has all node endpoints

```bash
talosctl --talosconfig configs/talosconfig config info
```

The `Endpoints` should include 192.168.1.54 at minimum. After migration we'll have 3 CPs, so endpoints should eventually be all three.

To add now:
```bash
talosctl --talosconfig configs/talosconfig config endpoint 192.168.1.54 192.168.1.177 192.168.1.19
```

### 6. Verify secrets bundle exists

The Talos secrets bundle (cluster CA, etcd CA, etc.) is required to generate matching machineconfigs for new CP nodes. It was created at cluster bootstrap.

```bash
ls -la configs/  # look for secrets.yaml or similar
```

If missing, you have to extract it from an existing node or regenerate — that's a separate (harder) workflow. Don't proceed without it.

---

## Migration — talos01 (first new CP)

We do ONE NODE AT A TIME to maintain etcd quorum throughout. After talos01 joins, etcd has 2 members (still no fault tolerance — be careful). After talos06 joins, etcd has 3 (1-node failure tolerance restored).

### Step 1: Generate the new controlplane.yaml for talos01

```bash
# Generate a fresh controlplane config from the same secrets bundle
talosctl gen config \
  --with-secrets configs/secrets.yaml \
  catalyst-cluster \
  https://192.168.1.54:6443 \
  --output configs/nodes/talos01/controlplane.yaml \
  --output-types controlplane

# Apply the same patches we use on the existing CP (KubePrism, kubelet patches, etc.)
# If we use Talos config patches, apply them:
# talosctl machineconfig patch configs/nodes/talos01/controlplane.yaml \
#   --patch @configs/patches/iscsi-kubelet-patch.yaml \
#   --output configs/nodes/talos01/controlplane.yaml
```

**VERIFY**: open `configs/nodes/talos01/controlplane.yaml` and confirm:
- `machine.type: controlplane`
- `machine.network.hostname: talos01`
- `cluster.controlPlane.endpoint: https://192.168.1.54:6443` (or your VIP if you set one)
- `cluster.allowSchedulingOnControlPlanes: true` (matches existing CP)
- `cluster.discovery.enabled: true`
- Anything that's set on the existing talos00 controlplane.yaml that should also be on talos01

### Step 2: Cordon and drain talos01

```bash
kubectl cordon talos01
kubectl drain talos01 --ignore-daemonsets --delete-emptydir-data --grace-period=120 --timeout=10m
```

This evicts non-DS workloads to other nodes. Watch:
```bash
kubectl get pods -A -o wide | awk '$8 == "talos01"'
```
Only DaemonSet pods (cilium, cilium-envoy, node-feature-discovery-worker, spire-agent, prometheus-node-exporter, etc.) should remain.

### Step 3: Apply the new config (this REINSTALLS talos01)

This is the destructive moment. Talos sees the role change and reinstalls.

```bash
talosctl --talosconfig configs/talosconfig \
  --nodes 192.168.1.177 \
  apply-config \
  --file configs/nodes/talos01/controlplane.yaml
```

talos01 will reboot into the new role. This takes 3-5 minutes typically.

**Watch:**
```bash
# From another terminal, monitor talos00's etcd to see talos01 join
watch -n 5 talosctl --talosconfig configs/talosconfig --nodes 192.168.1.54 etcd members
```

You'll see talos01 appear as a new etcd member. Initial state will be LEARNER until promoted to voting member by etcd.

### Step 4: Wait for talos01 to be Ready and CP-tagged

```bash
kubectl get nodes -o wide
```

Expected: talos01 shows `Ready` and `control-plane` in the ROLES column. If not after 10 minutes, check:
```bash
talosctl --talosconfig configs/talosconfig --nodes 192.168.1.177 health
talosctl --talosconfig configs/talosconfig --nodes 192.168.1.177 service etcd
talosctl --talosconfig configs/talosconfig --nodes 192.168.1.177 service kubelet
```

### Step 5: Verify etcd quorum is 2 members

```bash
talosctl --talosconfig configs/talosconfig --nodes 192.168.1.54 etcd members
talosctl --talosconfig configs/talosconfig --nodes 192.168.1.54 etcd status
```

You should see 2 voting members. **DO NOT proceed to talos06 until this is confirmed.** With only 2 members, a loss of either kills the cluster (no quorum).

### Step 6: Uncordon talos01

```bash
kubectl uncordon talos01
```

Workloads can now schedule there again (it allows scheduling on CP).

### Step 7: Health checkpoint (10 min observation)

```bash
# Watch for new cilium agent restarts, broken pods, apiserver health
for i in {1..20}; do
  kubectl get pods -n kube-system -l k8s-app=cilium --no-headers
  kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded --no-headers | head -5
  echo "---"
  sleep 30
done
```

If anything looks degraded — STOP. Don't promote talos06 with a half-broken cluster.

---

## Migration — talos06 (second new CP)

Same procedure as talos01, with IP `192.168.1.19`. Repeat steps 1-7 verbatim with substitutions.

After talos06 is promoted and Ready:

```bash
talosctl --talosconfig configs/talosconfig --nodes 192.168.1.54 etcd members
```

**Expected: 3 healthy members.** Now we have proper etcd quorum (can lose 1 node).

---

## Post-Migration

### 1. Update talosconfig endpoints

```bash
talosctl --talosconfig configs/talosconfig config endpoint 192.168.1.54 192.168.1.177 192.168.1.19
talosctl --talosconfig configs/talosconfig config info  # verify
```

Future talosctl commands will load-balance across the three CPs.

### 2. Verify KubePrism on all CPs

```bash
for ip in 192.168.1.54 192.168.1.177 192.168.1.19; do
  echo "=== $ip ==="
  talosctl --talosconfig configs/talosconfig --nodes $ip read /proc/net/tcp | grep ":1D15 " | head -2
done
```

Each should show `0100007F:1D15 ... 0A` (LISTEN on 127.0.0.1:7445).

### 3. Verify Cilium pods are healthy on all 5 nodes

```bash
kubectl get pods -n kube-system -l k8s-app=cilium -o wide
```

All 5 should be 1/1 Ready.

### 4. Validate apiserver redundancy

```bash
# Stop kube-apiserver on talos00 temporarily
talosctl --talosconfig configs/talosconfig --nodes 192.168.1.54 service kube-apiserver stop

# Wait ~30s
sleep 30

# kubectl should still work (routing to talos01 or talos06's apiserver via DNS RR or KubePrism)
kubectl get nodes

# Restart kube-apiserver on talos00
talosctl --talosconfig configs/talosconfig --nodes 192.168.1.54 service kube-apiserver start
```

If kubectl worked while talos00's apiserver was down, **HA is confirmed working**.

### 5. Unblock TALOS-ocj (Cilium-in-Flux)

Now safe to wire the Flux Cilium Kustomization into the parent:

```yaml
# clusters/catalyst-cluster/flux-system/kustomization.yaml
resources:
  - ...existing...
  - ../cilium.yaml   # ← uncomment / add this line
```

Commit, push, wait for Flux to discover. The HelmRelease will reconcile, may trigger a DaemonSet roll — but now with 3 CPs, a roll on any one CP doesn't kill the cluster.

### 6. Update CLAUDE.md and docs

Update:
- `CLAUDE.md` node inventory (talos00/01/06 are CPs, talos02-gpu/03 are workers)
- `docs/02-architecture/dual-gitops.md` if relevant
- `configs/README.md` node inventory table

### 7. Run a Cilium DS roll deliberately as a final test

```bash
# Trigger a deliberate cilium pod restart on talos00 (the one that always wedged before HA)
kubectl delete pod -n kube-system -l k8s-app=cilium --field-selector spec.nodeName=talos00
```

During the restart on talos00:
- Pods on talos00 may briefly lose network — that's expected
- kubectl from outside continues working (hitting talos01/06's apiservers)
- Cluster as a whole stays operational

If this works cleanly, HA is doing its job.

---

## Rollback Plan

If talos01 or talos06 promotion fails and the cluster becomes unstable:

### Path A: Promote one node, abort the second

If talos01 successfully joined (etcd has 2 members) and talos06 promotion is failing:
- Don't proceed with talos06
- Leave talos06 as worker
- File a beads issue to retry talos06 later
- 2-member etcd is workable but fragile (no fault tolerance) — plan to complete HA soon

### Path B: Total restore from etcd snapshot

If etcd state is corrupted or quorum is permanently lost:

```bash
# 1. Get the latest etcd snapshot from S3
kubectl exec -n minio <minio-pod> -- mc cp backup/backups/etcd/etcd-<latest>.snapshot /tmp/

# 2. Stop etcd on all CP nodes
# (depends on talosctl version; for Talos: stop the etcd service on each CP)
for ip in 192.168.1.54 192.168.1.177 192.168.1.19; do
  talosctl --talosconfig configs/talosconfig --nodes $ip service etcd stop
done

# 3. Restore on a single node
# (consult Talos docs for the exact restore command for your version —
#  `talosctl etcd snapshot restore` does not exist in all versions; may need
#  to do this via Kubernetes API or by replacing /var/lib/etcd contents)

# 4. Start etcd on the restore node only
talosctl --talosconfig configs/talosconfig --nodes 192.168.1.54 service etcd start

# 5. Once stable, re-add other CPs as fresh learners
```

### Path C: Reboot everything

If we're truly stuck and can't recover gracefully, the nuclear option is:
```bash
# Force-reboot all 3 CP candidates
for ip in 192.168.1.54 192.168.1.177 192.168.1.19; do
  talosctl --talosconfig configs/talosconfig --nodes $ip reboot --mode=force &
done
wait
```

After everyone reboots, etcd may either come back as 3-member or may need manual intervention.

---

## Common Pitfalls

### "etcd cluster ID mismatch"

talos01 or talos06's config was generated with a different secrets bundle than the existing cluster. Etcd refuses to join. Fix: regenerate the controlplane.yaml from the SAME `configs/secrets.yaml` as the existing CPs.

### "node failed to register"

The node booted but kubelet can't reach apiserver. Check that the new node has network connectivity to 192.168.1.54 (or the VIP) and that no firewall blocks 6443/10250.

### Cilium agent on the new CP won't start

Check:
- `talosctl --nodes <new-ip> logs apid | tail -50`
- `talosctl --nodes <new-ip> dmesg | grep -i cilium`
- KubePrism listening? `talosctl --nodes <new-ip> read /proc/net/tcp | grep ":1D15 "`

### Cluster goes dark during the talos01 promotion

This is the failure mode the post-mortem describes. If it happens during promotion:
1. Run `scripts/capture-meltdown-evidence.sh` (will work for any reachable node)
2. Reboot talos00 (the OLD CP) — it should come back
3. Once back, check whether talos01's promotion completed successfully or failed
4. If failed, the cluster is still in 1-CP state — start over from Pre-flight after fixing whatever caused the failure

### virt-operator / cnpg-operator still crashlooping post-HA

These are downstream. Once apiserver stays reachable continuously for 30+ minutes, these operators should stop their restart cycle. If they don't, file a separate issue.

---

## Validation Checklist (mark each)

- [ ] etcd has 3 healthy members
- [ ] kubectl get nodes shows 3 control-plane + 2 worker
- [ ] kubectl works when talos00's apiserver is stopped temporarily
- [ ] All 5 Cilium pods 1/1 Ready
- [ ] No broken pods cluster-wide
- [ ] KubePrism listening on all 5 nodes
- [ ] virt-operator and cnpg-operator restart count is plateauing (not increasing)
- [ ] Force-deleting a Cilium pod on talos00 doesn't take down cluster
- [ ] Documentation updated (CLAUDE.md, configs/README.md, dual-gitops.md)
- [ ] TALOS-ocj unblocked, Flux now manages Cilium

---

## Related

- [Post-mortem: 6 meltdowns 2026-05-29](../06-troubleshooting/2026-05-29-six-meltdowns-and-the-real-root-cause.md)
- [Talos docs — control plane](https://www.talos.dev/v1.13/talos-guides/configuration/control-plane/)
- [Talos docs — etcd maintenance](https://www.talos.dev/v1.13/talos-guides/configuration/etcd-maintenance/)
- TALOS-arx (EPIC tracking this work)
