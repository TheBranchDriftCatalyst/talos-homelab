# Post-Mortem: Six Cilium Cascading Meltdowns in One Day

**Date:** 2026-05-29
**Duration of impact:** Six episodes, each ~5–30 min until force-reboot
**Severity:** Full control-plane unreachable from kubectl, each time
**Blast radius:** Entire cluster (single CP node design)

---

## TL;DR

The cluster fell over **six times in ~8 hours** with the same surface symptom: `kubectl` timed out against `192.168.1.54:6443`, Talos itself was healthy, recovery required `talosctl reboot --mode=force` on talos00.

Each meltdown was triggered by an event that caused **cilium-agent on talos00 to restart**:
1. Continuing fallout from yesterday's network maintenance
2. Recurring (no clear trigger)
3. Apply of new cilium values (rolling restart, recovered cleanly)
4. `helm upgrade --take-ownership` after Flux source resume
5. Flux source resume + cascading kustomization reconciles
6. helm upgrade switching cilium to KubePrism endpoint

**The root cause is structural, not configurable:** on a single-CP cluster with Cilium kubeProxyReplacement, every cilium-agent restart on the CP node disrupts all host networking on that node during the BPF program reload window. Anything that depends on host networking on talos00 — including the kube-apiserver's etcd connection over localhost, kubelet's apiserver connection, KubePrism's outbound to apiservers — breaks for the 30–60s reload window. Combined with the fact that kubelet's response to "container probe failing" is to restart the container (which restarts the cycle), the system finds no recovery basin and the cluster goes dark until a fresh boot.

**No amount of value tuning, probe adjustment, GitOps reconciliation, or webhook hardening fixes this.** The fix is structural: **HA control plane**. Multiple apiservers on different nodes mean that when talos00's cilium restarts, kubectl and Flux still reach apiservers on talos01 or talos06 — the cluster as a whole survives.

---

## Timeline (UTC, 2026-05-29)

| Time | Event |
|---|---|
| ~16:30 | Meltdown #1 noticed by user — `kubectl` timing out, plex broken |
| 16:50 | Force-reboot talos00, cluster recovers, 3 broken operators (cnpg, virt-api, tempo) come back |
| 17:10 | Cognitive council launched (4 subagents) to challenge the analysis from 2026-05-27 |
| 17:30 | Cognitive council returns: architecture is the root cause, not network maintenance trigger |
| 17:40 | Hardening committed (cilium memory 2Gi, hubble buffer 8191, liveness 10, ClusterMesh scale 0, etcd-backup → :17) |
| 18:03 | Cilium values applied via `helm template + kubectl apply` (rolling restart, completed cleanly — no meltdown) |
| 18:13 | Meltdown #2 — `kubectl` timeout after applying Flux Kustomization changes for Cilium-in-Flux migration |
| 18:25 | Force-reboot #2 |
| 18:45 | Meltdown #3 during Flux reconcile of cilium Kustomization |
| 18:55 | Force-reboot #3 |
| ~19:00 | `helm upgrade --install --take-ownership` (helm release secret created, status: failed due to field-manager conflicts) |
| 19:04 | cilium-bbttl on talos00 restarted (helm-driven DS roll due to template annotation change) |
| 19:04–19:05 | New cilium-agent tried apiserver 3× via 192.168.1.54:6443, EOF on every attempt, container exited |
| 19:10 | Meltdown #4 fully visible — `kubectl` unreachable |
| 19:13 | Force-reboot #4 |
| 19:24 | Cilium-in-Flux activation **deferred** (commit 1128b46): documented but not wired into parent kustomization until HA lands |
| 19:34 | Meltdown #5 during 60s `sleep` after resuming Flux source |
| 19:43 | Force-reboot #5 |
| 19:39 | helm upgrade with `--server-side=true --force-conflicts` succeeded (KubePrism endpoint), rev 3 deployed |
| 19:43 | DaemonSet rolled with new KubePrism endpoint |
| 19:45 | Meltdown #6 — cilium-2tnjp died with `Kubernetes service is not ready: Get https://localhost:7445/version: EOF` — **proving KubePrism does NOT bypass the chicken-and-egg** |
| 19:46 | Force-reboot #6 |
| 20:30+ | Cluster stable, all 5 cilium pods 1/1 Ready with KubePrism config |
| 21:15 | Permanent KubeVirt webhook fix committed (TALOS-9cf, commit 92e6306) |

---

## The Symptom Across All 6 Episodes

Pattern was identical:
- `kubectl` from outside: `net/http: TLS handshake timeout` or `dial tcp 192.168.1.54:6443: connect: operation timed out`
- `talosctl` health: Talos services (etcd, apid, kubelet) all healthy
- `talosctl containers -k`: kube-apiserver container running, but kube-controller-manager and kube-scheduler EXITED
- Cilium agent on talos00: either CONTAINER_RUNNING with high PID (just restarted) or EXITED
- Recovery: `talosctl reboot --mode=force --wait` on talos00

---

## What the 4-Member Cognitive Council Found

A team of expert subagents was dispatched mid-incident to challenge our prior analysis (which blamed the 2026-05-27 router/switch reboot). Each agent attacked from a different angle, independently. Consensus:

### Council Member 1: Architecture review
> "Single CP + workloads on the CP + kubeProxyReplacement = circular dependency with no slack. Cilium on the CP node is in the critical path for its own apiserver, the etcd it points at, AND every pod admission across the cluster. The 5/21 incident and the latest blackouts all share this signature: a single jitter on talos00 collapses the universe."

Top 3 architectural fixes (cost-ranked):
1. Enable KubePrism on all nodes + `k8sServiceHost: localhost:7445` (effort: 1 hr, cost: $0)
2. Add 2 more CP nodes for stacked etcd (effort: 4 hrs, cost: ~$300–500 hw)
3. Disable `allowSchedulingOnControlPlanes` AFTER above (effort: 30 min)

### Council Member 2: Cilium/eBPF expert
> "clustermesh-apiserver is pinned to control-plane via nodeAffinity, runs its OWN embedded etcd, alongside Talos's primary etcd, on the SAME single CP node. And `enable-external-workloads=false` means we're paying full meltdown cost for a feature with no peer cluster."

Top 3 likely triggers, ranked:
1. clustermesh-apiserver embedded etcd's hourly compaction causing fsync contention with Talos's primary etcd (HIGHEST)
2. Cilium agent OOM-kill from Hubble flow buffer + SPIRE + clustermesh load on 1 GiB limit (MEDIUM-HIGH)
3. Stale orphaned BPF socket-LB programs intercepting localhost after agent restart (MEDIUM)

### Council Member 3: SRE review of analysis + filed work
> "You've spent three incidents adding shock absorbers to a car whose wheel keeps falling off. Stop tuning suspension. Find out why Cilium can't self-recover from a 30s partition, capture the evidence next time before you reboot, and ship HA."

Identified bistable system with no recovery basin: once Cilium agent and apiserver are both impaired, neither can recover because each needs the other. Tolerance bumps widened the normal basin but added no recovery basin — explaining why fixes bought days, not weeks.

### Council Member 4: Network forensics
> "Hourly etcd snapshot CronJob at `:00` is the highest-probability recurring trigger. `talosctl etcd snapshot` triggers an fsync-heavy BoltDB read of the entire datastore, stalling etcd's write path. While etcd is stalled, kube-apiserver's gRPC client hits dialTimeout → retries via Cilium's eBPF socket-LB (in-kernel connect() rewrite) → race window during reload."

Recommended testable hypothesis: shift snapshot to `:17`, observe whether next meltdown timestamp shifts by 17 minutes.

---

## The Real Root Cause (Now Understood)

```
cilium-agent restart on CP node
  ↓
BPF cgroup socket-LB programs reload (cilium_lb4_*, cgroup_inet4_connect, etc.)
  ↓
ALL host-namespace connect() syscalls disrupted during reload window
  ↓
  - apid's outbound to apiserver: broken
  - kubelet's apiserver connection: broken
  - apiserver's etcd over localhost:2379: broken
  - KubePrism's forwarding (apid is on host): broken
  ↓
apiserver becomes unreachable from outside (responds slowly/never)
  ↓
kubelet sees apiserver probes failing → keeps restarting cilium → cascade
  ↓
cluster goes dark until force-reboot resets everything cleanly
```

### Why KubePrism doesn't help (meltdown #6 evidence)

We hypothesized KubePrism (`localhost:7445` proxy in apid) would let cilium-agent bootstrap independent of Cilium's eBPF, breaking the chicken-and-egg. **Meltdown #6 disproved this.**

The previous container logs from cilium-2tnjp captured at 20:45:28Z:
```
"/healthz returning unhealthy" error="1.16.6 (v1.16.6-9e9f0989)
  Kubernetes service is not ready: Get https://localhost:7445/version: EOF"
```

EOF on `localhost:7445`. **Even with KubePrism configured and listening, the outbound from apid to the actual apiserver still goes through Cilium's BPF cgroup socket-LB.** When those BPF programs reload, apid's outbound to apiserver is also disrupted, and KubePrism returns EOF to its client (cilium-agent).

KubePrism is still valuable — it decouples the apiserver endpoint name from a single IP — but **it does not solve the BPF reload window problem.**

### Why the previous fixes didn't fix it

| Fix | Date | What it addressed | Why it didn't stop the meltdowns |
|---|---|---|---|
| Bump cilium liveness threshold 10 → 30 | 2026-05-22 | Cilium getting killed for slow `/healthz` | Hides the symptom (cluster bleeds silently for 15 min instead of failing visibly) |
| Throttle Flux concurrent/qps | 2026-05-22 | Reducing apiserver pressure | Doesn't prevent triggers from cron jobs, helm upgrades, etc. |
| Bump BPF policy map 16384 → 65536 | 2026-05-21 | Map overflow during identity churn | Doesn't address restart-induced BPF reload window |
| failurePolicy=Ignore on webhooks | 2026-05-29 | Cluster-wide admission stall when webhook backend down | Reduces blast radius of crashes, doesn't prevent the trigger |
| Cilium memory 1 → 2 GiB, Hubble buffer 16383 → 8191 | 2026-05-29 | OOM-killing of cilium agent | Helps with one specific death mode, doesn't fix restart window |
| ClusterMesh scale 1 → 0 | 2026-05-29 | CP-pinned etcd + apiserver load | Removed one trigger but not the underlying fragility |
| KubePrism switch | 2026-05-29 | Decoupling from single CP IP | Doesn't bypass Cilium's BPF cgroup interception |

All real, all valuable hardening — none fix the core: **cilium-agent restart on the CP node = brief but total host network disruption on that node.**

---

## What Actually Fixes This

### Primary: HA Control Plane (TALOS-arx)

Promote talos01 and talos06 from workers to control-plane nodes. 3-member stacked etcd quorum. Each node runs apiserver. KubePrism on each node routes to whichever apiserver is healthy.

When talos00's cilium agent restarts:
- talos00's apiserver is briefly unreachable from talos00-local traffic — that's fine, only affects pods on talos00
- talos01 and talos06's apiservers are unaffected — reachable from their own nodes via normal host networking
- kubectl from outside hits any healthy apiserver (DNS RR or via VIP)
- The cluster as a WHOLE stays operational even during the local Cilium hiccup

Cost: 3-4 hour destructive maintenance window. Two existing workers get reinstalled as CPs (Talos `apply-config` to a node with new role replaces the OS).

### Secondary: Move workloads off CP (after HA)

Once HA is in, set `allowSchedulingOnControlPlanes: false`. CP nodes serve only system pods. Reduces cilium-agent memory pressure on CPs. Reduces blast radius of CP issues.

### Tertiary: Make Cilium DS rolls less disruptive

Even with HA, the LOCAL cilium hiccup still affects local pods on that node briefly. Options:
- Tune `terminationGracePeriodSeconds` on cilium-agent
- `bpf-lb-sock-hostns-only: true` (default in some versions — verify)
- Investigate whether `clean-cilium-state` init container is doing more BPF reload than necessary

---

## Action Items From This Incident

All filed as beads issues, statuses as of 2026-05-29 21:15 UTC:

| ID | Title | Status |
|---|---|---|
| TALOS-arx | EPIC: HA control plane (talos01 + talos06 promoted) | OPEN P1 — the real fix |
| TALOS-ocj | Move Cilium to proper GitOps | BLOCKED on TALOS-arx |
| TALOS-a82 | Debug KubePrism listening | CLOSED (was listening — wrong hex value in my check) |
| TALOS-9cf | Permanent webhook fix for cnpg/virt-api/tempo | virt-api+tempo DONE, cnpg pending |
| TALOS-w4t | Test etcd-snapshot @ :17 hypothesis | OPEN — 7d observation window |
| TALOS-2pz | Wire Alertmanager → Discord | OPEN (no alerts currently route anywhere) |
| TALOS-txl | PrometheusRule: cilium restarts | BLOCKED on TALOS-2pz |
| TALOS-8fk | PrometheusRule: webhook backends | BLOCKED on TALOS-2pz |
| TALOS-7ci | Cilium startup probe investigation | OPEN P2 |
| TALOS-s64 | Post-network-maintenance runbook | OPEN P2 (this doc is part of it) |
| TALOS-0o7 | Auto-heal cilium DRY-RUN CronJob | OPEN P3 |
| TALOS-bbb | Investigate talos02-gpu persistent cilium issues | OPEN P2 |
| TALOS-eqh | capture-meltdown-evidence.sh macOS portability | CLOSED (fixed in this session) |
| TALOS-uqv | etcd-backup CronJob prune broken | OPEN P3 |
| TALOS-nhl | Dual GitOps demarcation tuning | OPEN P2 |
| TALOS-fed-enable / TALOS-4ye | Re-enable ClusterMesh on federation | DEFERRED |

---

## Lessons Learned

1. **Tolerance bumps hide rot.** The May 22 `livenessProbe.failureThreshold: 30` (15 min grace) meant the cluster accumulated 1991 cilium-agent restarts over 5 days before anyone noticed. Reverted to 10 (5 min grace) — pair with PrometheusRules so we hear the alarm instead of muting it.

2. **Capture evidence BEFORE forced recovery.** The script `scripts/capture-meltdown-evidence.sh` was written DURING meltdown #4. Earlier reboots wiped state. Now there's a runnable script that captures dmesg, BPF programs, sockstat, cilium-dbg status, apiserver logs in <2 min before any reboot.

3. **When a symptom recurs, the analysis was wrong — challenge it, don't double down.** The 2026-05-21 post-mortem blamed an admission webhook + DaemonSet restart. The 2026-05-22 fix bumped tolerance. Same symptom recurred on 5/22, 5/27, and 5/29 (×6). The cognitive council finally identified the structural issue.

4. **GitOps is not always the answer.** Putting Cilium in Flux added a recurring trigger (Flux helm reconciles → DS template annotation changes → rolling restart). For a CNI on a single-CP cluster, manual control of when DS rolls happen may be safer until HA is in place.

5. **`failurePolicy: Ignore` is a safety belt, not a fix.** Operators that constantly crash (cnpg-operator 3161 restarts/week, virt-operator 800+/week) still have an underlying problem. Ignore prevents cluster-wide admission stalls but the operators themselves need attention — typically resolves once the meltdowns stop (HA).

6. **Hex math matters.** Spent 30 minutes thinking KubePrism wasn't listening because I grep'd `:1D1D` instead of `:1D15` in `/proc/net/tcp`. 7445 decimal = 0x1D15, NOT 0x1D1D. Verify hex conversions before drawing conclusions.

7. **The CNI bootstrap chicken-and-egg is real and not solvable by endpoint choice alone.** cilium#41108 documents this. The only fix is structural redundancy at the apiserver level.

---

## Related Documents

- [docs/06-troubleshooting/2026-05-21-cilium-cascading-meltdown.md](2026-05-21-cilium-cascading-meltdown.md) — prior meltdown (admission webhook trigger)
- [docs/02-architecture/dual-gitops.md](../02-architecture/dual-gitops.md) — Flux/ArgoCD demarcation
- [scripts/capture-meltdown-evidence.sh](../../scripts/capture-meltdown-evidence.sh) — diagnostic capture before recovery
- [scripts/safe-restart-cilium.sh](../../scripts/safe-restart-cilium.sh) — staged Cilium DS restart (won't help during meltdown but useful for planned maintenance)

External:
- [Cilium issue #41108](https://github.com/cilium/cilium/issues/41108) — config initContainer chicken-and-egg
- [Cilium issue #45208](https://github.com/cilium/cilium/issues/45208) — v1.18.8 DNS proxy regression on Talos (we're on 1.16.6, not affected)
- [Talos issue #9132](https://github.com/siderolabs/talos/issues/9132) — Cilium install instructions assume KubePrism works
