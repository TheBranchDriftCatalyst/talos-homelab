# Cluster Bootstrap Runbook

End-to-end procedure for bringing the Talos cluster from bare metal (or full
recovery) back to a fully reconciling GitOps state. This runbook is the
authoritative recovery path — it should be followed top-to-bottom after any
catastrophic event (UPS failure, accidental wipe, fresh hardware, etc.).

## TL;DR

```bash
# 1. Plan the rebuild, then run the commands it prints.
#    task provision APPLIES NOTHING — it prints the talhelper sequence for you to run.
task talos:provision

# 2. (nothing to do — the kubelet bind mounts, maxPods, reserves and image GC are
#     part of the machine config now, so step 1 already applied them)

# 3. Merge kubeconfig
task kubeconfig-merge

# 4. Bootstrap Flux (GitOps controller)
GITHUB_USER=<you> GITHUB_REPO=talos-homelab GITHUB_TOKEN=<pat> \
  ./bootstrap/flux/bootstrap.sh

# 5. Bootstrap 1Password Connect (unblocks ~9 ExternalSecret-dependent stacks)
export OP_CONNECT_TOKEN='<token-from-1password-developer-tools>'
# Place 1password-credentials.json at repo root (gitignored)
task setup-1password

# 6. Verify
task health
flux get kustomizations
kubectl get externalsecret -A
```

The whole sequence is idempotent — re-running any step is safe.

## Prerequisites

Before you start, gather these. They are NOT in the repo (and must not be):

| Item | Source | Where it lives during bootstrap |
| --- | --- | --- |
| `1password-credentials.json` | 1Password developer-tools → Connect → catalyst-eso → "Download credentials" | Project root, `./1password-credentials.json` (gitignored on line 35 of `.gitignore`) |
| `OP_CONNECT_TOKEN` | 1Password developer-tools → Connect → catalyst-eso → access token | Shell env var |
| `GITHUB_TOKEN` (PAT) | GitHub → settings → developer settings → fine-grained PAT, scope: `repo` | Shell env var, used only by `flux bootstrap` |
| Talos node IP | `192.168.1.54` (control plane) | `TALOS_NODE` env var |

CLI tools required (install with `task deps:install`):
`talosctl`, `kubectl`, `flux`, `kustomize`, `helm`, `task`.

## Step 1 — Install Talos & bootstrap etcd

```bash
export TALOS_NODE=192.168.1.54

# Generate every node's machine config from configs/talconfig.yaml
# -> configs/clusterconfig/catalyst-cluster-<node>.yaml
task talos:gen-config

# Print the ordered rebuild sequence. This APPLIES NOTHING, and refuses outright
# if any node already answers the Talos API.
task talos:provision

# Then run the printed commands from configs/. Per node, freshly imaged:
task talos:apply-config NODE=talos00 INSECURE=true

# Bootstrap etcd on ONE control plane, ONCE. The other two join on their own.
task talos:bootstrap

# Wait for the cluster to come up
task talos:health
```

`NODE=` is required and takes a hostname, not an IP — the five nodes each have their own
install disk, factory schematic and patch set, so their configs are not interchangeable.
Note there is no `--` before `NODE=`; go-task only binds variables in the bare form.

`configs/talsecret.yaml` must exist before any of this. It holds the cluster CA and is
gitignored, so a fresh clone will not have it — restore it from 1Password first
([talsecret-1password-backup.md](talsecret-1password-backup.md)). Do **not** run
`talhelper gensecret` with no arguments to "fix" a missing one: that mints a new CA, which
does not recover this cluster but defines a different one.

If any step hangs see `docs/03-operations/provisioning.md` for deeper detail.

## Step 2 — Patch kubelet bind mounts *(no longer a step)*

**Nothing to do here.** Step 1 already applied these.

The kubelet bind mounts for iSCSI (Democratic-CSI / TrueNAS) and the local-path-provisioner
host directory — plus `maxPods`, the memory reserves and image GC — are declared in
`configs/talconfig.yaml` and generated into every node's machine config:

| Setting | Declared in |
| --- | --- |
| `/etc/iscsi`, `/var/lib/iscsi`, `/var/lib/rancher` bind mounts | `configs/patches/all-kubelet-baseline.yaml` |
| `systemReserved` / `kubeReserved` / `evictionHard` | `configs/patches/all-kubelet-baseline.yaml` |
| `imageMaximumGCAge: 336h` | `configs/patches/all-kubelet-baseline.yaml` |
| `maxPods: 200` (every node except talos03) | `configs/patches/maxpods-200.yaml` |
| `maxPods: 60` (talos03 — deliberately lower) | `configs/patches/talos03-maxpods.yaml` |

`scripts/bootstrap-talos-patches.sh` and `task talos:patches` used to do this with
`talosctl patch mc`. Both are retired and now refuse to run. Applying these by hand as well
creates drift the next `task talos:apply-config` reverts.

To check a node actually has them:

```bash
task talos:verify           # regenerate and diff against every live node
task talos:verify-dry-run   # ask each node what applying would do — read-only
```

## Step 3 — Merge kubeconfig

```bash
task k8s:kubeconfig          # download to .output/kubeconfig
task k8s:kubeconfig-merge    # merge into ~/.kube/config

# Sanity check
kubectl get nodes
```

## Step 4 — Bootstrap Flux

Flux owns the GitOps reconciliation of `clusters/catalyst-cluster/`. Once it
is running, every other manifest in the repo is applied automatically — but
ExternalSecret-backed manifests will stay in `NotReady` until Step 5.

```bash
export GITHUB_USER=<your-gh-handle>
export GITHUB_REPO=talos-homelab
export GITHUB_TOKEN=<fine-grained-pat-with-repo-scope>

./bootstrap/flux/bootstrap.sh
```

Verify:

```bash
flux check
flux get kustomizations
```

It is normal to see kustomizations like `authentik`, `cert-manager-issuers`,
`monitoring`, and `argocd-secrets` stuck in `ReconciliationFailed` at this
point — they depend on secrets synced from 1Password, which is the next
step.

## Step 5 — Bootstrap 1Password Connect (one command)

This is the recovery step that previously required digging through scripts
and remembering env-var names. It is now a single Taskfile target with
explicit prerequisite checks:

```bash
# Pre-flight: place creds and export token
cp ~/Downloads/1password-credentials.json ./1password-credentials.json
export OP_CONNECT_TOKEN='<paste-from-1password>'

# One-shot, idempotent:
task setup-1password
```

Equivalent forms (all do the same thing):

```bash
task setup-1password         # root-level shortcut
task infra:setup-1password   # fully-qualified domain task
```

If a previous bootstrap left stale Kubernetes secrets in place and you want
to forcibly recreate them:

```bash
task infra:setup-1password-force
```

What it does, idempotently:

1. Verifies `OP_CONNECT_TOKEN` is in the environment (errors with a clear
   message if not).
2. Verifies `./1password-credentials.json` exists at the project root
   (errors with a clear message if not).
3. Invokes `scripts/external-secrets/setup-1password-connect.sh --auto`,
   which:
   - Creates the `external-secrets` namespace if missing.
   - Skips the `onepassword-connect-secret` Secret if it already exists
     (use `setup-1password-force` to recreate).
   - Skips the `onepassword-connect-token` Secret if it already exists.
   - Restarts the `onepassword-connect` Deployment if present.

Once this completes, ESO can authenticate to 1Password and the dependent
Flux Kustomizations (authentik, cert-manager-issuers, monitoring chain,
ArgoCD secrets, etc.) will sync on their next reconciliation interval.
To force them now:

```bash
flux reconcile kustomization external-secrets --with-source
flux reconcile kustomization authentik --with-source
flux reconcile kustomization cert-manager-issuers --with-source
```

## Step 6 — Verify

```bash
# Cluster health
task health
kubectl get nodes
kubectl get pods -A | grep -v 'Running\|Completed'

# Flux reconciliation
flux get kustomizations          # all should be Ready=True
flux get sources git

# ExternalSecrets sync
kubectl get clustersecretstore                 # onepassword: Valid
kubectl get externalsecret -A                  # all SyncedAt populated, Status=Ready

# 1Password Connect pods
kubectl get pods -n external-secrets -l app.kubernetes.io/name=onepassword-connect
```

## Recovery UX

After a UPS event or any catastrophic recovery, the operator runs
**`task setup-1password`** with `OP_CONNECT_TOKEN` exported and
`./1password-credentials.json` in place — that single command unblocks the
~9 downstream Flux Kustomizations that depend on ESO.

## Sizing Considerations (verify on a re-bootstrap)

### Cilium BPF map sizes

`configs/cilium-values.yaml` should include explicit BPF map sizes — defaults
are too small for a homelab cluster with ~50 namespaces:

```yaml
bpf:
  masquerade: true
  policyMapMax: 65536  # default 16384 — overflows at ~200 pods × many policies
  lbMapMax: 65536      # already 65536 default, keep explicit
```

Symptoms of an undersized `policyMapMax`:

```
Failed to add PolicyMap key" ... error="update map cilium_policy_NNNN:
update: no space left on device"
```

…followed by every new pod sandbox failing with `Cilium API client timeout`.
See `docs/06-troubleshooting/2026-05-21-cilium-cascading-meltdown.md`.

### Kubelet maxPods (per-node)

Default is 110. For GPU nodes that gather GPU-pinned workloads (Plex, Jellyfin,
Tdarr, ML inference) plus their dependencies, this fills quickly. If you see
`FailedScheduling ... Too many pods` on a node, increase via Talos machine
config:

```yaml
machine:
  kubelet:
    extraConfig:
      maxPods: 200
```

Apply with `talosctl apply-config` — kubelet restarts, no node reboot required.

### Admission webhook failurePolicy

All operators we deploy that register MutatingWebhookConfigurations must use
`failurePolicy: Ignore` (with a `namespaceSelector` excluding kube-system).
The cluster meltdown of 2026-05-21 was caused by a webhook with
`failurePolicy: Fail` whose operator had crashed — every pod admission was
blocking. The pre-flight in `upgrade-talos.py` and `shutdown-cluster.sh`
detects this state now, but the defense lives in the helm values too.

## Related

- `infrastructure/base/external-secrets/README.md` — ESO details and ExternalSecret patterns
- `scripts/external-secrets/README.md` — All ESO/1Password helper scripts
- `docs/03-operations/provisioning.md` — Talos provisioning detail
- `docs/04-deployment/flux-setup.md` — Flux bootstrap detail
- `docs/02-architecture/dual-gitops.md` — Why Flux + ArgoCD coexist

## Related Issues

<!-- Beads tracking for this runbook -->
