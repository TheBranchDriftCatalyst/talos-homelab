# talhelper cutover — the swap procedure

**Do NOT run `rm -rf configs/ && mv talos/ configs/`.** That was the original plan and an audit
established it would destroy unrecoverable material and leak secrets. This runbook replaces it.

Tracking: TALOS-0bo8. Prerequisite: TALOS-w04r (secrets bundle backed up to 1Password).

---

## What the naive swap would have done

| | |
|---|---|
| **Destroyed 6 private keys** | `configs/nebula-certs/ca.key`, `configs/securexng-mtls/ca.key` + 4 client keys. **Untracked, on disk only, not re-derivable.** A CA private key cannot be regenerated — every certificate it ever signed becomes worthless. |
| **Destroyed the admin client config** | `configs/talosconfig` is untracked. It is what every `talosctl` command uses, including the ones you would reach for mid-incident. |
| **Leaked the Talos secrets bundle** | `.gitignore` matched `talos/talsecret.yaml` by *anchored path*. After the rename that rule stops matching, and the next `git add` stages all five CAs and every token. *(Fixed — the rules are now filename-matched and survive the move. Verified under both paths.)* |
| **Broke every recovery tool** | `./configs/talosconfig` is hardcoded in 10+ places: `Taskfile.yaml:15`, `Taskfile.talos.yaml:6`, `Taskfile.k8s.yaml:6`, `scripts/lib/common.sh:161`, `shutdown-cluster.sh`, `upgrade-talos-version.sh`, `bootstrap-talos-patches.sh`, `node-dossier.sh`, `capture-meltdown-evidence.sh`, `test-suspect-*.sh`. `Taskfile.talos.yaml:9-12` also references `configs/nodes/*.yaml`. |

---

## The procedure

### 0. Prerequisites

- [ ] `talos/talsecret.yaml` is in 1Password (`docs/05-runbooks/talsecret-1password-backup.md`)
- [ ] Working tree clean, `git status` empty
- [ ] `python3 talos/verify-diff.py` output reviewed — every difference explained

### 1. Preserve what is untracked and irreplaceable

```bash
cd ~/catalyst-devspace/workspace/talos-homelab
mkdir -p /tmp/configs-preserve
cp -a configs/talosconfig configs/nebula-certs configs/securexng-mtls /tmp/configs-preserve/
ls -R /tmp/configs-preserve            # eyeball it before continuing
```

Anything else in `configs/` that is untracked and you care about goes here too:

```bash
git ls-files --others --exclude-standard configs/ | head -50
```

### 2. Move, do not delete

```bash
mv configs configs.pre-talhelper       # NOT rm -rf
mv talos configs
```

Keep `configs.pre-talhelper/` until the cluster has run happily for a week. It is the only
copy of those CA keys.

### 3. Restore the preserved material into the new tree

```bash
cp -a /tmp/configs-preserve/nebula-certs configs/
cp -a /tmp/configs-preserve/securexng-mtls configs/
cp -a /tmp/configs-preserve/talosconfig configs/talosconfig
```

`configs/talosconfig` must keep working — see step 5 on whether to replace it.

### 4. Verify nothing secret became visible to git

```bash
git status --porcelain configs/ | head -30
git check-ignore -v configs/talsecret.yaml     # MUST print a .gitignore line
git check-ignore -v configs/clusterconfig/     # MUST print a .gitignore line
git ls-files configs/ | grep -iE "key|secret|talosconfig"   # MUST be empty
```

**If any of those three checks fails, stop and fix `.gitignore` before committing.**

### 5. Decide on the client config

The generated `configs/clusterconfig/talosconfig` is **better** than the current one — same OS
CA (verified identical), valid admin cert, and it lists **all three control planes** as
endpoints where the current one lists only `192.168.1.54`. That matters: with one endpoint, a
talos00 reboot takes your CLI with it.

But its context is named `catalyst-cluster` where the existing one is `homelab-single`, so
`talosctl config merge` adds a context rather than updating. Either keep the old file in place
(simplest, everything keeps working) or merge and switch context deliberately.

### 6. Update the hardcoded paths — same commit

Every reference listed in the table above. `configs/talosconfig` still resolves if you did
step 3, so this is not urgent for correctness, but `configs/nodes/*.yaml` in
`Taskfile.talos.yaml:9-12` no longer exists.

### 7. Commit

```bash
git add -A
git status                      # READ IT. No .key, no talosconfig, no talsecret.
git commit
```

---

## Applying the configs is a separate decision

⚠️ **Applying reboots every node.** Verified by dry-run on all five: `Applied configuration
with a reboot`. The cause was bisected — talhelper must remove `machine.features.stableHostname`
(Talos rejects it coexisting with the HostnameConfig document it emits), and Talos classifies
that removal as reboot-required. It is unavoidable with talhelper's output.

This is not a drift-close; it is **a planned rolling reboot of the fleet**.

Order — workers first, endpoint last:

```
talos02-gpu  192.168.1.144   worker
talos06      192.168.1.19    worker
talos01      192.168.1.177   control plane
talos03      192.168.1.30    control plane
talos00      192.168.1.54    control plane — LAST. It is the API endpoint; when it
                             reboots you lose kubectl and talosctl until it returns.
```

Between each node:

```bash
task talos:health
kubectl get nodes                    # the node is Ready again
talosctl -n 192.168.1.54 etcd members   # quorum intact before the next control plane
```

After the first control plane, before continuing, confirm the API cert is still right:

```bash
openssl s_client -connect 192.168.1.30:6443 </dev/null 2>/dev/null \
  | openssl x509 -noout -ext subjectAltName
```

Reboot is not reinstall: `wipe: false` on every node and the `install:` section is only
consulted at upgrade time.

---

## Related Issues

- TALOS-0bo8 — flatten Talos config
- TALOS-w04r — back up the secrets bundle first
- TALOS-1mog — Bluetooth enablement, gated behind this
