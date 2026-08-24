# Backing up the Talos secrets bundle to 1Password

**Do this before applying any talhelper-generated config.** Tracking: TALOS-w04r.

---

## What this file is, and why it matters

`talos/talsecret.yaml` holds the cluster's **identity**:

| | |
|---|---|
| 5 certificate authorities | `os`, `k8s`, `etcd`, `k8s-aggregator`, `k8s-serviceaccount` |
| `cluster.id` / `cluster.secret` | what makes this *this* cluster |
| machine token | lets a node join |
| k8s bootstrap token | lets a node register with the API server |
| secretbox encryption secret | encrypts secrets at rest in etcd |

**Anyone holding this file can mint a node into your cluster.** It is gitignored and must
stay that way.

It is also **irreplaceable**. Lose it and you cannot regenerate a node that the existing
cluster will accept — every CA would differ, so etcd would reject the new member and kubelet
would fail TLS to the API server. The only recovery is rebuilding the cluster from scratch and
restoring workloads from Velero and CNPG backups.

Right now **one copy exists**, on this laptop, untracked. That is the whole reason this
runbook exists.

---

## Step by step

### 1. Open a terminal in the repo

```bash
cd ~/catalyst-devspace/workspace/talos-homelab
```

### 2. Confirm the file is there and looks right

```bash
ls -la talos/talsecret.yaml
grep -c "crt:" talos/talsecret.yaml     # expect 5
```

If `ls` says no such file, regenerate it — this is safe and produces the same content,
because it EXTRACTS identity rather than creating new:

```bash
talosctl gen secrets --from-controlplane-config configs/nodes/controlplane.yaml \
  -o talos/talsecret.yaml
```

### 3. Confirm git cannot see it

```bash
git check-ignore -v talos/talsecret.yaml
```

You want output naming `.gitignore`. **If you get NO output, stop** — the file is not ignored
and must not be committed. Tell me and I will fix it before you continue.

### 4. Copy the contents

```bash
cat talos/talsecret.yaml | pbcopy
```

That puts the whole file on your clipboard. (`pbcopy` is macOS built-in; nothing to install.)

### 5. In the 1Password app

1. Click **New Item** → choose **Secure Note**
2. **Title:** `talos-secrets-bundle`
3. In the note body, press **⌘V** to paste
4. Add these fields (click *add more* → *text*), so future-you knows what this is without
   opening it:
   - `cluster` → `catalyst-cluster`
   - `talos-version` → `v1.13.9`
   - `extracted-from` → `configs/nodes/controlplane.yaml`
   - `date` → today's date
   - `purpose` → `Talos machine config identity. Required to regenerate node configs. Cluster is UNRECOVERABLE without this.`
5. Put it in whichever vault your other infrastructure secrets live in — the same one as
   `nexus-admin`, so it is found by whoever looks for infra credentials
6. **Save**

### 6. Verify you can read it back

In 1Password, open the item and check the note starts with `cluster:` and contains
`bootstraptoken`. **Do not skip this** — a backup you have not read back is not a backup.

### 7. Clear your clipboard

```bash
pbcopy < /dev/null
```

---

## What NOT to do

- **Do not** email it, Slack it, or put it in a note app.
- **Do not** commit it, even to a private repo. Git history is forever and this file has no
  business in any repo.
- **Do not** store it only on this laptop. A single copy on one disk is the situation this
  runbook exists to end.
- **Do not** paste it into an AI chat, including me. I do not need to see it to do any of this
  work, and I have never read its contents — only checked which keys are present.

---

## Why not automate this?

The 1Password CLI (`op`) is not installed on this machine — the `op` on PATH resolves to macOS
`open`, which is why an earlier attempt produced "The file whoami does not exist". ESO reaches
1Password through a Connect server running *in the cluster*, which is the wrong direction: this
secret is what you would need to REBUILD that cluster, so it cannot depend on it.

That circularity is the real reason this stays manual. A bootstrap secret must be recoverable
without the thing it bootstraps.

---

## Related Issues

- TALOS-w04r — this task
- TALOS-0bo8 — flatten Talos config; a node must be rebuildable from git + secrets alone
