# Cluster Bootstrap Runbook

End-to-end procedure for bringing the Talos cluster from bare metal (or full
recovery) back to a fully reconciling GitOps state. This runbook is the
authoritative recovery path — it should be followed top-to-bottom after any
catastrophic event (UPS failure, accidental wipe, fresh hardware, etc.).

## TL;DR

```bash
# 1. Provision Talos + bootstrap etcd
task provision

# 2. Apply machine-config patches (kubelet bind mounts for iSCSI / local-path)
#    One command, all nodes, idempotent:
task talos:patches
# (Or directly: ./scripts/bootstrap-talos-patches.sh)
# Use --check / `task talos:patches-check` for a dry-run preview.

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

# Generate machine configs (writes configs/{controlplane,worker,talosconfig}.yaml)
task talos:gen-config

# First-time apply (use INSECURE=true on a freshly imaged node)
task talos:apply-config INSECURE=true

# Bootstrap etcd on the control plane
task talos:bootstrap

# Wait for the cluster to come up
task talos:health
```

If any step hangs see `docs/03-operations/provisioning.md` for deeper detail.

## Step 2 — Patch kubelet bind mounts

Two machine-config patches must be applied so kubelet can see iSCSI sockets
(Democratic-CSI / TrueNAS) and the local-path-provisioner host directory.
Both patches live in this directory and are idempotent.

The `bootstrap-talos-patches.sh` helper applies them to every node in one
shot. The node IP list is hard-coded in the script — edit `NODES=( ... )` at
the top of the file when the cluster topology changes.

```bash
# Preview (no changes)
task talos:patches-check
# or: ./scripts/bootstrap-talos-patches.sh --check

# Apply to all nodes
task talos:patches
# or: ./scripts/bootstrap-talos-patches.sh
```

These trigger a kubelet restart on each node — expected and finishes in a
few seconds. Re-running on already-patched nodes is a no-op (`talosctl
patch mc` performs a structural merge).

If you only need to patch a single node manually:

```bash
talosctl --talosconfig configs/talosconfig -e "${TALOS_NODE}" \
  patch mc --nodes <node-ip> \
  --patch @docs/05-runbooks/talos-kubelet-iscsi-patch.yaml

talosctl --talosconfig configs/talosconfig -e "${TALOS_NODE}" \
  patch mc --nodes <node-ip> \
  --patch @docs/05-runbooks/talos-kubelet-localpath-patch.yaml
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

## Related

- `infrastructure/base/external-secrets/README.md` — ESO details and ExternalSecret patterns
- `scripts/external-secrets/README.md` — All ESO/1Password helper scripts
- `docs/03-operations/provisioning.md` — Talos provisioning detail
- `docs/04-deployment/flux-setup.md` — Flux bootstrap detail
- `docs/02-architecture/dual-gitops.md` — Why Flux + ArgoCD coexist

## Related Issues

<!-- Beads tracking for this runbook -->
