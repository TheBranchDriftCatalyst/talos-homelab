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

### Before you start: stop being single-endpoint

The live client config lists only `192.168.1.54`. When talos00 reboots you lose `talosctl`
entirely — including the commands you would use to see whether it came back. Add the other
control planes as endpoints FIRST:

```bash
talosctl config endpoint 192.168.1.54 192.168.1.177 192.168.1.30
talosctl -n 192.168.1.30 version          # prove a non-talos00 endpoint works
```

The generated `clusterconfig/talosconfig` already lists all three, which is one concrete way
it is better than the current one.

The same applies to `kubectl`: your kubeconfig points at `https://192.168.1.54:6443` only, so
talos00's reboot is a total kubectl outage regardless. Expect it, rather than debugging it.

Order — workers first, endpoint last:

```
talos02-gpu  192.168.1.144   worker
talos06      192.168.1.19    worker
talos01      192.168.1.177   control plane
talos03      192.168.1.30    control plane
talos00      192.168.1.54    control plane — LAST. It is the API endpoint; when it
                             reboots you lose kubectl and talosctl until it returns.
```

### ⚠️ DECIDE ON talos02-gpu's STALE META HOSTNAME BEFORE STARTING

`talos02-gpu` carries a stale hostname in its META partition — the node's **pre-rename** name:

```bash
talosctl -n 192.168.1.144 get metakeys      # key 0x0a contains  hostname: talos02
```

talos03 and talos06 also carry key 0x0a, but their embedded hostnames match their real names.
talos00 and talos01 have none. Only talos02-gpu is stale.

**This is invisible to every config diff** — META is a partition, not machine config. It is
also normally harmless: the configuration layer outranks the platform layer, so while config
loads correctly nothing uses it.

It is the node's **fallback identity**. If the new multi-document config ever fails to load at
boot, the node comes up as `talos02`, registers as a **NEW Node object**, and the **15
local-path PVs pinned to `talos02-gpu` by nodeAffinity become unschedulable** — books, dagster,
postgres-knowledge and manyfold databases among them.

Low probability. Ugly blast radius. And a reboot cycle is precisely when a config-load failure
would occur.

Optional pre-mitigation, **a write — decide deliberately**:

```bash
talosctl -n 192.168.1.144 meta delete 0x0a
```

Deleting it means the node falls back to DHCP/platform defaults for hostname if config ever
fails to load, rather than to a wrong hardcoded name. Either choice is defensible; making it
by accident is not.

### ⚠️ SNAPSHOT EACH NODE'S CURRENT CONFIG FIRST — there is no rollback otherwise

**Talos exposes no machine-config history.** `talosctl get machineconfig` shows only the
current version, and `talosctl rollback` reverts the BOOT PARTITION, not the config. The
obvious fallback — `configs/nodes/*.yaml` — is stale documentation by this repo's own
admission: those nodes were hand-patched with `talosctl patch mc` for months.

So the moment a node is applied, **the only accurate copy of its previous config is gone.**
Before touching each node:

```bash
talosctl -n <ip> get machineconfig -o yaml > /tmp/pre-apply-<node>.yaml
```

Keep those until the cluster has been healthy for a week. Note that rolling back costs a
second reboot — re-adding `stableHostname` is the same reboot-classified transition in reverse.

### Between each node

```bash
task talos:health
kubectl get nodes                       # the node is Ready again
talosctl -n 192.168.1.54 etcd members   # quorum intact before the next control plane

# ⚠️ CNPG — THIS GATE IS NOT OPTIONAL, and the placement makes it concrete
kubectl get cluster.postgresql.cnpg.io -A
# EVERY row must read "Cluster in healthy state" before moving on.
```

**Why that gate exists.** Three CNPG clusters live entirely within the first two nodes of the
reboot order:

```
authentik-postgres   primary + replica on talos02-gpu   ·   replica on talos06
boomtime-postgres    primary + replica on talos02-gpu   ·   replica on talos06
bt-radar-postgres    replica on talos02-gpu             ·   primary on talos06
```

Reboot talos02-gpu, then reboot talos06 before those instances finish re-syncing, and all
three clusters lose **every healthy instance** mid-failover. Node Ready and etcd quorum will
both look fine while that happens — they do not know about Postgres.

### Reboots are deliberately UNDRAINED — do not "improve" this with kubectl drain

Talos `apply-config` reboots without consulting PodDisruptionBudgets, which is why this works.
All 17 CNPG `*-primary` PDBs report **allowed disruptions: 0**. Adding a `kubectl drain` step
would wedge forever on them.

### Expect these to be hard-down, they are not breakage

`talos02-gpu` is the first node and the most loaded (105 pods). It hosts single-instance
databases pinned there by local-path PVs, which cannot move and will be down for the whole
boot: **books-postgres, dagster-postgres, postgres-knowledge, manyfold-postgres**.

`talos03` hosts the entire **Flux control plane** (kustomize/helm/notification controllers),
plus single-replica **cert-manager-webhook** and **external-secrets-webhook**. During its
reboot, Certificate and ExternalSecret admission fails cluster-wide. Transient — but do not
sequence any other deployment during that window.

`talos01` is **dual-homed** (`enp3s0`=192.168.1.177, `enp2s0`=192.168.1.178, both inside the
kubelet `validSubnets`, and etcd already advertises both peer URLs). Pre-existing, not caused
by this migration — but a reboot is when IP selection could flip. Check `INTERNAL-IP` after it
returns.

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
