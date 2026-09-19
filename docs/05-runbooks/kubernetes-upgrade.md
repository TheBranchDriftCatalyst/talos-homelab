---
type: runbook
status: current
covers:
  - path:configs/talconfig.yaml
  - path:dev/Taskfile.talos.yaml
freshness: tracks-code
tickets:
  - TALOS-33jl
  - TALOS-xipf
bluf: Kubernetes moves with talosctl upgrade-k8s, one minor at a time, driven from a single control plane — and you must bump kubernetesVersion in configs/talconfig.yaml afterwards or the next apply-config downgrades every kubelet back.
---

# Kubernetes upgrade (Talos)

> Parent: [docs/05-runbooks](./)

## TL;DR

```bash
export TALOSCONFIG=configs/talosconfig
CP=<control-plane-ip>   # any one control plane; it orchestrates the rest

talosctl upgrade-k8s --nodes $CP --endpoints $CP --to <target> --dry-run  # ALWAYS first
talosctl upgrade-k8s --nodes $CP --endpoints $CP --to <target>
# THEN: edit kubernetesVersion: in configs/talconfig.yaml to <target> and commit.
```

- **Kubernetes and the Talos OS are separate upgrades.** `talosctl upgrade` moves the OS;
  `talosctl upgrade-k8s` moves Kubernetes. Different commands, different skew rules.
- Run it against **one control-plane node**; it orchestrates the whole cluster from there.
- **One minor version at a time.** Do not skip a minor.
- **The repo does not follow the cluster on its own.** `task talos:upgrade-k8s` is a bare
  `talosctl` call with no wrapper — nothing writes the new version back into
  `configs/talconfig.yaml`. Forget that edit and the repo declares the old version while the
  cluster runs the new one, so `task talos:verify` reports permanent drift and the next
  `task talos:apply-config` **downgrades that node's kubelet**.

## Versions

`configs/talconfig.yaml` is the source of truth for both `talosVersion` and
`kubernetesVersion`. Read them there; they are deliberately not restated here, because a copy
of a version number in prose is wrong the day after the next upgrade.

What you need to establish before picking a target:

| Question                                             | Where the answer is                                                   |
| ---------------------------------------------------- | --------------------------------------------------------------------- |
| What version does the repo declare?                  | `kubernetesVersion:` in `configs/talconfig.yaml`                      |
| What is actually running?                            | `kubectl version`, and the kubelet version in `kubectl get nodes`     |
| What Kubernetes band does the running Talos support? | The release notes for the `talosVersion:` in `configs/talconfig.yaml` |

If the first two disagree, resolve that **before** upgrading — the drift is the bug described in
the TL;DR, and upgrading on top of it compounds it.

## Pre-flight

Re-run all of these before any upgrade. Each was verified clean on 2026-08-23 for a 1.35 target;
that is a dated record of one upgrade, not a standing guarantee.

### 1. The kube-scheduler landmine — CHECK THIS EVERY TIME

[siderolabs/talos#13350](https://github.com/siderolabs/talos/issues/13350): some Talos releases
render scheduler plugin fields from a _newer_ Kubernetes than the one being installed
(`placementGenerate`, `placementScore`) into the kube-scheduler config. Every kube-scheduler
static pod then CrashLoopBackOffs with a strict-decoding error, and **nothing in the cluster can
be scheduled** until it is fixed.

Verify by grepping the dry-run rather than trusting the version number — the mapping between
Talos patch release and which fields it emits is not something you can reason about from the
outside:

```bash
talosctl upgrade-k8s --nodes $CP --endpoints $CP --to <target> --dry-run \
  | grep -icE "placementGenerate|placementScore"     # MUST be 0
```

### 2. cgroup v2 — a hard blocker, not a warning

Recent kubelets **fail on startup** if they detect cgroup v1. This is a kernel-interface change,
so unlike an API removal it cannot be worked around by editing manifests.

```bash
talosctl -n <node> read /proc/mounts | grep cgroup     # expect cgroup2
```

### 3. containerd 2.x

containerd 1.x is a dead end on current Kubernetes.

```bash
kubectl get nodes -o jsonpath='{range .items[*]}{.status.nodeInfo.containerRuntimeVersion}{"\n"}{end}'
```

### 4. kube-proxy / IPVS

IPVS mode is deprecated. **Not applicable here** — this cluster runs Cilium in kube-proxy
replacement mode (`infrastructure/base/cilium/values.yaml`) and has no kube-proxy DaemonSet at
all.

### 5. Deprecated API usage

```promql
sum by (group,version,resource,removed_release) (increase(apiserver_requested_deprecated_apis[7d]))
```

The apiserver's own counter is authoritative here — better than scanning manifests, because it
catches controllers and operators calling old APIs at runtime, which a manifest grep never sees.
Expect zero over a window long enough to include your CronJobs.

## Procedure

1. **Confirm cluster health first.** etcd at full voters, all nodes Ready, no workload already
   degraded. An upgrade is not the time to discover an existing problem.
   ```bash
   task talos:etcd-members
   kubectl get nodes
   ```
2. **Dry run and read it.** Confirm the scheduler-field grep is 0, and that the plan touches
   apiserver/controller-manager/scheduler on every control plane and kubelet on every node.
3. **Run it.** `--pre-pull-images` defaults true, which matters: it pulls before cutting over,
   so a slow or failed pull does not strand a control-plane component mid-upgrade.
   ```bash
   task talos:upgrade-k8s -- <target>
   ```
4. **Watch the schedulers specifically**, since that is the known failure mode:
   ```bash
   kubectl get pods -n kube-system -w | grep kube-scheduler
   ```
5. **Verify**: `kubectl version`, all nodes on the new kubelet, workloads still Running.
6. **Bump `kubernetesVersion:` in `configs/talconfig.yaml` and commit.** Then
   `task talos:verify` should report no drift. Skipping this step is the single most damaging
   thing you can do in this runbook — see the TL;DR.

## Why one minor at a time

The control plane supports a kubelet at most one minor version behind. Upgrading two minors
directly would move the control plane two minors ahead of kubelets that have not been updated
yet, and the window where that is true is exactly when things break. `upgrade-k8s` handles
kubelets too, but the safe pattern is still one minor per run with a verification pass between.

## Related

- Talos OS upgrade is a different procedure — TALOS-xipf. The OS must be on a version that
  supports the target Kubernetes version BEFORE the Kubernetes upgrade. That path _does_ write
  its result back (`scripts/upgrade-talos.py` bumps `talosVersion:` itself); this one does not.
- Node-level kubelet config (`maxPods`, memory reservation) lives in `configs/patches/` and is
  unaffected by `upgrade-k8s`.

---

## Related Issues

- TALOS-33jl — EPIC 2b, the 1.34 → 1.35 upgrade this runbook was written for (closed)
