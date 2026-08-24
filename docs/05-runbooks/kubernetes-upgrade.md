# Kubernetes upgrade (Talos)

> Parent: [docs/05-runbooks](./) · Ticket: TALOS-33jl (EPIC 2b)

## TL;DR

```bash
export TALOSCONFIG=configs/talosconfig
talosctl upgrade-k8s --nodes 192.168.1.54 --endpoints 192.168.1.54 --to 1.35.4 --dry-run  # ALWAYS first
talosctl upgrade-k8s --nodes 192.168.1.54 --endpoints 192.168.1.54 --to 1.35.4
```

- **Kubernetes and the Talos OS are separate upgrades.** `talosctl upgrade` moves the OS;
  `talosctl upgrade-k8s` moves Kubernetes. Different commands, different skew rules.
- Run it against **one control-plane node**; it orchestrates the whole cluster from there.
- **One minor version at a time.** 1.34 -> 1.35, then later 1.35 -> 1.36. Do not skip.

## Current state (2026-08-23)

| | |
| --- | --- |
| Kubernetes | v1.34.10 |
| Talos | v1.13.9 (all 5 nodes) |
| Talos 1.13 supports | Kubernetes 1.31 – 1.36 |
| Target | **1.35.4** |

## Pre-flight — all verified clean 2026-08-23

Re-run these before any future upgrade; do not assume they are still true.

### 1. The kube-scheduler landmine — CHECK THIS EVERY TIME

[siderolabs/talos#13350](https://github.com/siderolabs/talos/issues/13350): Talos **v1.13.2**
renders Kubernetes **v1.36** scheduler plugin fields (`placementGenerate`, `placementScore`)
into a **v1.35** kube-scheduler config. Every kube-scheduler static pod then CrashLoopBackOffs
with a strict-decoding error, and **nothing in the cluster can be scheduled** until it is
fixed. Talos v1.13.0 and v1.13.1 are unaffected.

Verify by grepping the dry-run rather than trusting the version number:

```bash
talosctl upgrade-k8s --nodes 192.168.1.54 --endpoints 192.168.1.54 --to <target> --dry-run \
  | grep -icE "placementGenerate|placementScore"     # MUST be 0
```

Verified 0 on Talos v1.13.9 targeting 1.35.4.

### 2. cgroup v2 — a hard blocker, not a warning

The 1.35 kubelet **fails on startup** if it detects cgroup v1. This is a kernel-interface
change, so unlike an API removal it cannot be worked around by editing manifests.

```bash
talosctl -n <node> read /proc/mounts | grep cgroup     # expect cgroup2
```

Verified: `cgroup2` on all five nodes.

### 3. containerd 2.x

containerd 1.x is a dead end past 1.35.

```bash
kubectl get nodes -o jsonpath='{range .items[*]}{.status.nodeInfo.containerRuntimeVersion}{"\n"}{end}'
```

Verified: `containerd://2.2.7` on all five nodes.

### 4. kube-proxy / IPVS

IPVS mode is deprecated ahead of 1.36. **Not applicable here** — this cluster runs Cilium in
kube-proxy replacement mode and has no kube-proxy DaemonSet at all.

### 5. Deprecated API usage

```bash
sum by (group,version,resource,removed_release) (increase(apiserver_requested_deprecated_apis[7d]))
```

Verified: **zero** deprecated API requests in 7 days. The apiserver's own counter is
authoritative here — better than scanning manifests, because it catches controllers and
operators calling old APIs at runtime, which a manifest grep never sees.

## Procedure

1. **Confirm cluster health first.** etcd at full voters, all nodes Ready, no workload
   already degraded. An upgrade is not the time to discover an existing problem.
   ```bash
   talosctl etcd members --nodes 192.168.1.54 --endpoints 192.168.1.54   # expect 3/3
   kubectl get nodes
   ```
2. **Dry run and read it.** Confirm the scheduler-field grep is 0, and that the plan touches
   apiserver/controller-manager/scheduler on every control plane and kubelet on every node.
3. **Run it.** `--pre-pull-images` defaults true, which matters: it pulls before cutting over,
   so a slow or failed pull does not strand a control-plane component mid-upgrade.
4. **Watch the schedulers specifically**, since that is the known failure mode:
   ```bash
   kubectl get pods -n kube-system -w | grep kube-scheduler
   ```
5. **Verify**: `kubectl version`, all nodes on the new kubelet, workloads still Running.

## Why one minor at a time

The control plane supports a kubelet at most one minor version behind. Upgrading
1.34 -> 1.36 directly would move the control plane two minors ahead of kubelets that have
not been updated yet, and the window where that is true is exactly when things break.
`upgrade-k8s` handles kubelets too, but the safe pattern is still one minor per run with a
verification pass between.

## Related

- Talos OS upgrade is a different procedure — see EPIC 2 / TALOS-xipf. The OS must be on a
  version that supports the target Kubernetes version BEFORE the Kubernetes upgrade.
- Node-level kubelet config (maxPods, memory reservation) lives in the sibling patch files
  in this directory and is unaffected by `upgrade-k8s`.

---

## Related Issues

- TALOS-33jl — EPIC 2b, this upgrade
