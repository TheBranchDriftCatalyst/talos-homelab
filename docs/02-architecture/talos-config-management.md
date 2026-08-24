# Talos Machine Config Management (talhelper)

**Status:** Proposed — design only, nothing applied. Tracking epic: TALOS-0bo8.
**Date:** 2026-08-23

---

## TL;DR

**This does NOT require rebuilding the cluster.** Talos machine config identity (all five CAs,
the machine token, the k8s bootstrap token, `cluster.id`/`cluster.secret`) can be extracted
from the existing config into a secrets bundle and reused verbatim. Proven empirically below —
every field matched byte-for-byte. Regenerated configs are drop-in applicable to the live nodes.

- **Adopt talhelper.** It turns `talconfig.yaml` (one git-tracked, non-secret file) into
  per-node machine configs. It structurally fixes install-disk, extensions, patches and taints.
- **Do NOT introduce SOPS.** Keep 1Password as the single secrets mechanism. The secrets bundle
  is a bootstrap-time secret that ESO architecturally cannot deliver, and SOPS would add a
  second trust root without removing the first.
- **talhelper does not detect live drift.** That is custom work (~a script + a task), and it is
  the part that actually stops failures 1, 3 and 4 recurring. Do not skip it.
- **The cluster is currently drifted.** Three nodes are running something other than what git
  says. Details in [Current State](#current-state-measured-2026-08-23).

---

## Quick Reference

| Question | Answer |
| --- | --- |
| Does this require a cluster rebuild? | **No.** Identity is fully preservable. |
| Same CA after regeneration? | Yes — `talosctl gen secrets --from-controlplane-config` |
| Does talhelper handle per-node install disks? | Yes — `installDiskSelector` is per node and mandatory |
| Does it handle per-node extensions? | Yes — `schematic:` per node; it computes/registers factory IDs |
| Does it fix `talosctl upgrade` stripping extensions? | Yes — `talhelper gencommand upgrade` emits per-node `--image` |
| Does it guarantee kubelet patches on a rebuilt node? | Yes — patches are baked into the generated config |
| Does it detect drift against the live cluster? | **No** — we build that (see [Verification](#e-verification-the-part-talhelper-does-not-give-you)) |
| New secrets mechanism required? | No — recommend 1Password, not SOPS |

---

## Current State (measured 2026-08-23)

Read live from the cluster with `talosctl get machineconfig`. This is not the repo's view; it is
what the nodes actually have.

### Install target and installer image

| Node | `install.disk` | `install.image` | Running |
| --- | --- | --- | --- |
| talos00 | **`/dev/sda`** | `ghcr.io/siderolabs/installer:v1.13.2` (**stock**) | v1.13.9 |
| talos01 | `diskSelector{type: nvme, size: >= 100GB}` | `factory…c9078f94:v1.13.2` | v1.13.9 |
| talos02-gpu | `/dev/nvme0n1` | `factory…4b3cd373:`**`v1.11.1`** | v1.13.9 |
| talos03 | `diskSelector{type: nvme, size: >= 100GB}` | `factory…1e17720b:v1.13.2` | v1.13.9 |
| talos06 | `/dev/nvme0n1` (**`wipe: true`**) | `factory…16be3b98:`**`v1.11.1`** | v1.13.9 |

Three separate live landmines:

1. **talos00 — the control plane — still has `install.disk: /dev/sda`.** On this hardware
   `/dev/sda` is a 1 GB USB stick. This is the failure that previously required physically
   pulling a drive mid-boot, and it is still armed today on the most important node in the
   cluster.
2. **`install.image` is stale on all five nodes**, by two different amounts. Nothing updates it;
   `talosctl upgrade` does not write it back.
3. **talos06 carries `wipe: true`.** Combined with a wrong disk selector that is a data-loss
   pairing, not just a failed boot.

### Extensions: live vs. what git declares

| Node | git schematic | live schematic | live extensions | verdict |
| --- | --- | --- | --- | --- |
| talos00 | `c9078f94` (iscsi-tools) | *none — stock installer* | *none* | **DRIFT** |
| talos01 | `c9078f94` | `c9078f94` | iscsi-tools | match |
| talos02-gpu | `9ffda6da` (i915, intel-ucode, iscsi-tools) | `4b3cd373` | i915, intel-ucode | **DRIFT** |
| talos03 | `1e17720b` | `1e17720b` | amd-ucode, amdgpu, iscsi-tools | match |
| talos06 | `6b32ee67` (intel-ucode, i915, mei, iscsi-tools) | `16be3b98` | intel-ucode, i915, mei | **DRIFT** |

Every git schematic file was re-POSTed to factory.talos.dev to confirm its content still hashes
to the ID written in its header — all five match, so the files are internally consistent. The
drift is entirely **live-vs-git**: the schematics were edited on 2026-01-16 to add
`iscsi-tools`, and three nodes were never re-imaged. `talos00` is the starkest case — it
declares a schematic in git that it has never run, and has no extensions at all.

The practical consequence: **talos00, talos02-gpu and talos06 cannot attach Democratic-CSI iSCSI
volumes**, and nobody would find out until a workload landed there. Note that the *kubelet
mounts* for iSCSI are present on all five nodes (the patches were applied); it is the
`iscsi-tools` **extension** that is missing, so `/etc/iscsi` is bind-mounted but empty of tooling.

### The stock-installer downgrade trap

`talosctl upgrade` defaults `--image` to `ghcr.io/siderolabs/installer:<CLIENT version>`. The
local client is **v1.13.3**; the cluster runs **v1.13.9**. So a hand-typed `talosctl upgrade`
today would simultaneously **downgrade Talos by six patch releases and strip every extension**.
That is not a hypothetical — it is the default behaviour of the obvious command.

### Kubelet patches

Currently present on all five nodes (`maxPods: 200`, `systemReserved`, `evictionHard`, the iSCSI
and local-path `extraMounts`). They are applied post-hoc by
`scripts/bootstrap-talos-patches.sh`. Nothing ties them to node creation, so a rebuilt node has
them only if someone remembers to run the script.

### Taints

Live state is correct: only talos00 is tainted. But that correctness lives *only* on the running
nodes — `configs/nodes/controlplane.yaml` still carries `machine.nodeTaints`, so regenerating
talos01/talos03 from that shared template re-introduces the bug that cost hours (TALOS-obvn).

---

## C. Can this be done in place? — Yes. Proven.

**This is the most important section, so it is stated plainly: no rebuild, no re-bootstrap, no
new CA, no etcd re-init.**

The mechanism is `talosctl gen secrets --from-controlplane-config`, which reverses config
generation: it reads an existing controlplane machine config and reconstructs the secrets bundle
that produced it. talhelper wraps the same thing as `talhelper gensecret --from-configfile`.

Verified against this cluster by extracting a bundle from `configs/nodes/controlplane.yaml` and
comparing to what talos00 is actually running:

| Identity element | Extracted bundle | Live cluster | |
| --- | --- | --- | --- |
| `machine.token` | `c6jw1s.ndzy…` | `c6jw1s.ndzy…` | match |
| Machine CA (`certs.os`) | `ada0c1359a1f4177` | `ada0c1359a1f4177` | match |
| Kubernetes CA (`certs.k8s`) | `a6d6fc560c88e660` | `a6d6fc560c88e660` | match |
| Aggregator CA | `742177cdc00f7331` | `742177cdc00f7331` | match |
| etcd CA | `34d84976f843a7ee` | `34d84976f843a7ee` | match |
| `cluster.id` | `_h70D_fSmLmFjz…` | `_h70D_fSmLmFjz…` | match |
| `cluster.secret` | `okslvTt/1l8Raue…` | `okslvTt/1l8Raue…` | match |
| k8s bootstrap token | `4ohcdh.tuaa…` | `4ohcdh.tuaa…` | match |
| secretbox encryption secret | `FAXVFA7uV9v9…` | `FAXVFA7uV9v9…` | match |

(CAs compared by SHA-256 of the PEM; the extracted material was deleted immediately after the
comparison.)

Every field round-trips. There is no element of cluster identity that regeneration invents.

**One caveat, and it is minor.** `talhelper genconfig` mints a *fresh client certificate* for
`talosconfig` on every run (365-day TTL, `--crt-ttl` configurable). That cert is signed by the
same machine CA, so it is valid immediately — but it means the generated `talosconfig` differs
between runs. It is a client credential, not cluster identity. Nothing on the nodes changes.

**What applying regenerated configs actually does to a live node.** `install.*` is consulted only
at install/upgrade time, so correcting `install.disk` and `install.image` on a running node is a
**metadata-only change with no runtime effect** — it fixes what *would* happen on the next
install without touching the current one. That is exactly the property that makes this migration
safe: the highest-value fix (talos00's `/dev/sda`) is also the least disruptive one. Kubelet-only
changes restart kubelet. Anything touching networking or certs would reboot; the migration is
sequenced to avoid those (see [Migration](#migration-plan)).

---

## A. Tool verdict: adopt talhelper

talhelper is a config *generator*, not a controller — it is "kustomize for Talos machine
configs". It runs on a laptop, reads `talconfig.yaml` + a secrets bundle, and writes per-node
machine configs into `./clusterconfig/` (which it gitignores for you). There is no cluster-side
component and nothing to operate. That is a good fit here: Talos config is not, and should not
be, GitOps-reconciled — it sits *below* Flux.

Mapping it against the five failures:

| # | Failure | talhelper | How |
| --- | --- | --- | --- |
| 1 | Wrong install disk | **Fixed** | `installDisk`/`installDiskSelector` is a **required, per-node** field. There is no shared template to inherit `/dev/sda` from — omitting it fails validation. |
| 2 | Extensions lost on upgrade | **Fixed** | `schematic:` per node; `gencommand upgrade` emits the correct `--image` per node. |
| 3 | Forgotten kubelet patches | **Fixed** | Patches are declared in `talconfig.yaml` and composed into the generated config, so they exist at apply time rather than being bolted on afterwards. |
| 4 | Unintended taint | **Fixed** | `nodeTaints` is per node. talos00 declares it; talos01/talos03 simply do not. No inheritance path exists unless you put it under `controlPlane:`. |
| 5 | Configs not in git | **Mostly fixed** | `talconfig.yaml` is non-secret and git-tracked. Generated output stays gitignored (it contains certs). The *inputs* become the source of truth. |

### Patch composition and ordering

Documented, deterministic, and the thing that replaces `bootstrap-talos-patches.sh`:

1. top-level `patches:` — every node
2. `controlPlane.patches:` / `worker.patches:` — that group
3. `node.patches:` — that node

Later layers **append** to earlier ones by default; `overridePatches: true` on a node makes its
patches *replace* the group layer instead. Each entry is a strategic-merge patch, an RFC-6902
JSON patch, or `@./path/to/file.yaml`. The existing patch files under `docs/05-runbooks/` are
already in exactly the right format and can be referenced in place — no rewriting.

This is the structural fix for failure 3: today a patch is a thing you *run*, and running it is
optional. After this, a patch is a thing the config *contains*, and a node cannot exist without it.

### What talhelper does NOT solve — be clear about these

1. **It does not detect drift against a live cluster.** `genconfig --dry-run` diffs newly
   generated files against previously generated files — it says nothing about what the nodes
   actually have. Everything in [Verification](#e-verification-the-part-talhelper-does-not-give-you)
   is work we have to build. Given three nodes are silently drifted right now, this is the single
   highest-value piece of the epic.
2. **It cannot stop someone typing `talosctl upgrade` by hand**, and that command's default is
   actively harmful here (downgrade + extension strip, above). Mitigation is procedural: wrap it
   in a task, delete the raw-upgrade paths from the Taskfile, and let the drift check catch it.
3. **`install.image` only takes effect at install/upgrade time.** Correcting it in config does
   not retro-fix an already-installed node — talos02-gpu and talos06 keep their v1.11.1 pin until
   their next upgrade. This is fine, but it means the fleet stays inconsistent until the next
   upgrade cycle and the verify check must compare against *running* version, not just config.
4. **It does not back up the secrets bundle.** That is on us (see below).
5. **It does not flash boot media.** `genurl image` produces the right ISO URL per node; a human
   still writes it to a stick for a brand-new node.
6. **It does not manage Talos↔Kubernetes version skew.** `talosVersion` and `kubernetesVersion`
   are ours to keep sane.

**Alternatives considered.** Staying on hand-maintained per-node YAML is what produced all five
failures. Omni (Sidero's commercial control plane) genuinely solves this class of problem
including drift, but it is a hosted/licensed service and a much larger dependency than a
homelab warrants. A hand-rolled generator script would be strictly worse than talhelper at more
effort. talhelper is the right size for this cluster.

---

## B. Secrets: keep 1Password, do not adopt SOPS

**Verified:** this repo has no SOPS usage. No `.sops.yaml`, no `*.sops.yaml`, no age key at
`~/.config/sops/age/`. The only `sops` string anywhere is inside Flux's vendored
`gotk-components.yaml` — that is kustomize-controller's *built-in capability*, not a configured
use of it. Secrets today are External Secrets Operator backed by 1Password
(`ClusterSecretStore/onepassword`, Valid, 106 days). `sops` and `age` binaries are installed via
Homebrew but unused.

### ESO cannot do this job — and that is the deciding fact

The talsecret bundle is the material needed to *create* the cluster. ESO runs *inside* that
cluster. You cannot fetch, from a cluster, the secret required to build that cluster. This is not
a preference; it is a hard ordering constraint. So "just use ESO like everything else" is not
available, and the real choice is only about how the bundle reaches `talhelper genconfig`.

### Options

| | Where the bundle lives | Trust roots to protect | Repo self-contained? |
| --- | --- | --- | --- |
| **A. SOPS + age** | `talsecret.sops.yaml`, in git | **2** — the age key *and* wherever you back the age key up | Yes |
| **B. 1Password (recommended)** | 1Password item; fetched to a gitignored path at generate time | **1** — the 1Password account | No |
| C. Fully manual | Local file + offline backup | 1, but unmanaged | No |

### Recommendation: option B

Store the bundle as a 1Password document. A task fetches it immediately before generating:

```yaml
gen-config:
  cmds:
    - op document get "talos catalyst-cluster talsecret" --out-file "$(mktemp -d)/talsecret.yaml"
    - talhelper genconfig --secret-file "$TMP/talsecret.yaml"
    - rm -P "$TMP/talsecret.yaml"     # -P overwrites before unlinking
```

**Why this over SOPS, honestly.** The instinct is that SOPS is "more GitOps" — but count the
trust roots. With SOPS you hold an age private key, and that key must itself be backed up
somewhere durable, which in this environment means 1Password. So option A is
"1Password **plus** an age key", not "an age key instead of 1Password". It adds a mechanism
without removing one, and adds a new way to be locked out (lose the age key → the encrypted
bundle in git is scrap). Option B has one credential, one recovery story, and it is the one
already used everywhere else in this repo.

**The honest cost of option B — two real downsides.** First, the repo alone is no longer
sufficient to rebuild the cluster; you also need 1Password access. That genuinely weakens the
"git is the whole truth" property, and it is the strongest argument for SOPS. Second, the bundle
touches disk in plaintext during generation, whereas SOPS decrypts in-process; the `mktemp` +
`rm -P` above narrows that window but does not eliminate it (use a RAM disk if this matters).
Against both: config generation is a rare, deliberate, operator-run action, not something in a
pipeline — the exposure window is small and human-supervised.

**This is reversible.** talhelper reads `talsecret.yaml` or `talsecret.sops.yaml` natively. If
the git-self-contained property later proves worth a second trust root, adopting SOPS is a
one-time `sops -e` and a filename change. Nothing else in the design depends on the choice.

**Non-negotiable regardless of option:** the bundle must be backed up *before* the migration
starts. It is the only thing standing between a lost laptop and an unrecoverable cluster. Today
that material exists solely inside a gitignored `configs/nodes/controlplane.yaml`.

---

## D. Per-node schematics and automatic upgrade images

Both halves are handled, and this is talhelper's strongest single feature here.

**Declaration.** `schematic:` is a per-node (and per-group) field taking the upstream Image
Factory format — the *same YAML already in the `*-schematic.yaml` files*, so migration is
copy-paste:

```yaml
- hostname: talos03
  ipAddress: 192.168.1.30
  controlPlane: true
  installDiskSelector: { type: nvme, size: ">= 100GB" }
  schematic:
    customization:
      systemExtensions:
        officialExtensions:
          - siderolabs/amd-ucode
          - siderolabs/amdgpu
          - siderolabs/iscsi-tools
```

**IDs are generated, not hand-managed.** talhelper POSTs each schematic to factory.talos.dev and
uses the returned ID (`--offline-mode` computes the same ID locally, skipping registration —
useful for CI, but the online POST is needed at least once so the factory can actually *serve*
the image). Either way the ID is a pure function of the content, so **the hand-copied 64-char
hashes and their "to regenerate, curl…" comment blocks disappear entirely.** The class of bug
where a schematic file is edited and its header ID goes stale becomes unrepresentable.

**Upgrades use the right image per node — verified in talhelper's source**
(`pkg/generate/command.go`):

```go
if n.TalosImageURL != "" {
    url = n.TalosImageURL + ":" + cfg.GetTalosVersion()
} else if n.Schematic != nil {
    url, err = talos.GetInstallerURL(n.Schematic, cfg.GetImageFactory(), …)
}
…
upgradeFlags := []string{"--talosconfig=…", "--nodes=" + node, "--image=" + url}
```

So `talhelper gencommand upgrade` emits, per node, a `talosctl upgrade` line already carrying
that node's factory installer URL at the configured `talosVersion`. Failure 2 becomes structural:
the upgrade command is generated *from* the extension declaration, so the two cannot disagree.

The one gap: this only helps if the generated command is what actually gets run. Route it through
a task and remove the raw `talosctl upgrade` escape hatches from `Taskfile.talos.yaml`.

---

## E. Verification — the part talhelper does not give you

A generator makes the repo *authoritative*; only a checker makes it *true*. Two tiers, because
they have different access needs and different run frequencies.

### Tier 1 — static, no cluster access (every PR)

Runs in CI/lefthook against `talconfig.yaml` alone. Fast, and catches the bad config before it
can ever reach a node:

- `talhelper validate talconfig` — schema correctness.
- **No node may use a bare `installDisk` matching `/dev/sd*`.** Prefer `installDiskSelector`.
  This is failure 1 encoded as a lint rule.
- **Every node must declare a `schematic`** (explicitly empty is allowed, but must be written).
- **`nodeTaints` may only appear on an allowlist** — currently `talos00` only. Any other node
  gaining a taint fails the check with a pointer to TALOS-obvn. This is failure 4 as a lint rule.
- **The global patch list must contain the four kubelet patches.** Failure 3 as a lint rule.
- `talosVersion` and `kubernetesVersion` are pinned, not `latest`.

### Tier 2 — live drift detection (scheduled + on demand)

`task talos:verify`. Regenerates configs offline, then for each node:

```bash
talosctl apply-config -n "$IP" -f "clusterconfig/catalyst-cluster-$NODE.yaml" --dry-run
```

`--dry-run` makes Talos itself compute and print the diff it *would* apply, without applying it.
An empty diff is a proof of convergence from the authority that matters — better than any diffing
we could write, because it normalises the config the same way the node does. Non-empty output is
drift, printed as a unified diff.

Then assert the invariants a config diff alone can miss, because they compare against *runtime*
rather than *config*:

| Assertion | Source of truth | Catches |
| --- | --- | --- |
| live schematic ID == talconfig-derived ID | `talosctl get extensions` | talos02-gpu / talos06 missing iscsi-tools |
| running version == `talosVersion` | `talosctl version` | the v1.11.1/v1.13.2/v1.13.9 spread |
| resolved install disk is NVMe ≥100 GB | `talosctl get disks` | talos00's `/dev/sda` |
| `kubectl` node taints == talconfig `nodeTaints` | live node objects | inherited-taint regressions |
| `maxPods` / `systemReserved` present | node status | a rebuilt node missing patches |

Wire the result into the existing observability stack: emit a `talos_config_drift{node,check}`
gauge to Mimir and alert on it, in the same shape as the other homelab checks. Drift then
*announces itself* instead of waiting for an incident — which is the entire point, since the
current drift has apparently been silent since January.

Tier 2 needs Talos API access, so it runs from the operator's machine as a task initially. An
in-cluster CronJob using a scoped `os:reader` talosconfig is the natural follow-up and is filed
as a stretch child.

---

## Target layout

```
talos/
├── talconfig.yaml              # git-tracked. THE source of truth.
├── talsecret.yaml              # gitignored; pulled from 1Password on demand
├── patches/
│   ├── global/                 # every node
│   │   ├── kubelet-iscsi-mounts.yaml
│   │   ├── kubelet-localpath-mount.yaml
│   │   ├── kubelet-maxpods.yaml
│   │   ├── kubelet-memory-reserve.yaml
│   │   └── registry-mirrors.yaml
│   └── controlplane/
│       └── metrics-exposure.yaml
└── clusterconfig/              # generated, gitignored by talhelper
```

The `docs/05-runbooks/talos-*-patch.yaml` files move to `talos/patches/` — keeping their
extensive WHY comment blocks, which are genuinely valuable and should not be lost in the move.
Leave stubs pointing at the new location, since the runbooks reference them by path.

Sketch of `talconfig.yaml` (illustrative — validate at implementation time; in particular
confirm `installDiskSelector.type: nvme` passes `talhelper validate talconfig`, since the
selector is the upstream Talos type):

```yaml
clusterName: catalyst-cluster
endpoint: https://192.168.1.54:6443
talosVersion: v1.13.9
kubernetesVersion: v1.36.4
allowSchedulingOnControlPlanes: true

patches:
  - "@./patches/global/kubelet-iscsi-mounts.yaml"
  - "@./patches/global/kubelet-localpath-mount.yaml"
  - "@./patches/global/kubelet-maxpods.yaml"
  - "@./patches/global/kubelet-memory-reserve.yaml"
  - "@./patches/global/registry-mirrors.yaml"

controlPlane:
  patches:
    - "@./patches/controlplane/metrics-exposure.yaml"

nodes:
  - hostname: talos00
    ipAddress: 192.168.1.54
    controlPlane: true
    installDiskSelector: { type: nvme, size: ">= 100GB" }   # was /dev/sda — a 1GB USB stick
    schematic:
      customization:
        systemExtensions:
          officialExtensions: [siderolabs/iscsi-tools]
    # DELIBERATE, and scoped to this node only. talos00 is RAM-limited and is meant to
    # run the control plane and little else. Do NOT lift this to controlPlane: — that is
    # exactly the inheritance bug TALOS-obvn cost hours to find.
    nodeTaints:
      node-role.kubernetes.io/control-plane: "NoSchedule"

  - hostname: talos01
    ipAddress: 192.168.1.177
    controlPlane: true
    installDiskSelector: { type: nvme, size: ">= 100GB" }
    schematic:
      customization:
        systemExtensions:
          officialExtensions: [siderolabs/iscsi-tools]

  - hostname: talos02-gpu
    ipAddress: 192.168.1.144
    installDiskSelector: { type: nvme, size: ">= 100GB" }
    schematic:
      customization:
        systemExtensions:
          officialExtensions:
            [siderolabs/i915, siderolabs/intel-ucode, siderolabs/iscsi-tools]

  - hostname: talos03
    ipAddress: 192.168.1.30
    controlPlane: true
    installDiskSelector: { type: nvme, size: ">= 100GB" }
    schematic:
      customization:
        systemExtensions:
          officialExtensions:
            [siderolabs/amd-ucode, siderolabs/amdgpu, siderolabs/iscsi-tools]

  - hostname: talos06
    ipAddress: 192.168.1.19
    installDiskSelector: { type: nvme, size: ">= 100GB" }
    schematic:
      customization:
        systemExtensions:
          officialExtensions:
            [siderolabs/intel-ucode, siderolabs/i915, siderolabs/mei, siderolabs/iscsi-tools]
```

Note what is *absent*: no 64-char schematic hashes, no `install.image` strings, no per-node
config files, no taint on talos01/talos03. Roughly 60 KB of generated YAML across five gitignored
files collapses to one ~80-line tracked file.

---

## Migration Plan

Sequenced so that every step is independently verifiable and the riskiest change lands last.
Nothing here re-bootstraps anything.

**Phase 0 — safety net.** Extract the secrets bundle, store it in 1Password, verify it can be
retrieved on a second machine. Take an etcd snapshot. *Do this before anything else* — it is
currently the only copy of the cluster's CA.

**Phase 1 — author, generate, compare (zero cluster impact).** Write `talconfig.yaml`, move the
patches, run `talhelper genconfig`, and diff the output against each node's live config with
`talosctl apply-config --dry-run`. Iterate on `talconfig.yaml` until the only diffs are the ones
intended (the `install.*` corrections). **This is the whole de-risking step**: a clean dry-run is
proof the generated config is equivalent before anything is applied.

**Phase 2 — apply, one node at a time, workers first.** talos02-gpu → talos06 → talos01 →
talos03 → talos00. Workers before control planes; talos00 last because it is both the endpoint
and the one carrying the intentional taint. Health-check between each. Expect kubelet restarts;
the `install.*` corrections are inert until the next install.

**Phase 3 — verification.** Build Tier 1 and Tier 2 checks, wire the drift metric into Mimir.

**Phase 4 — decommission the old path.** Delete `scripts/bootstrap-talos-patches.sh`, rewrite
`gen-config`/`apply-config`/`upgrade` tasks to route through talhelper, remove raw `talosctl
upgrade`, and update the runbooks. Leaving both paths alive is how the repo ends up with two
sources of truth again.

**Phase 5 — reconcile the extension drift.** Separately from the migration, upgrade
talos00/talos02-gpu/talos06 to their correct schematics so `iscsi-tools` is actually present.
This reboots nodes and is real work with real risk, so it is deliberately *not* bundled into the
config migration — but it is the thing that makes the repo's claims true.

---

## Open questions

- **Does `installDiskSelector: {type: nvme}` validate in talhelper?** The selector is the
  upstream Talos type and `type` is a valid upstream field, but this was not executed —
  talhelper is not installed locally and installing it was out of scope for a design pass.
  Confirm in Phase 1; the fallback (`size` + `model`, or a `busPath`) is equivalent.
- **Are talos04/talos05 (NVIDIA) in scope?** They have schematics and configs in `configs/nodes/`
  but are not in the cluster, not in `bootstrap-talos-patches.sh`, and not reporting to the API.
  They appear decommissioned or never joined. Treated as out of scope; confirm before deleting
  their configs, and note their ISOs account for ~1.5 GB of gitignored files in `configs/`.
- **Which `talosVersion` to pin?** v1.13.9 matches reality. Worth confirming against the current
  upstream release at implementation time given the standing preference for latest.

---

## Related Issues

- **TALOS-0bo8** — epic: a node must be rebuildable from git + secrets alone
- TALOS-obvn — the `machine.nodeTaints` inheritance trap (failure 4)
- TALOS-d5b5 — maxPods 110→200
- TALOS-hyga — kubelet memory reservation
- TALOS-hzl0 — control-plane metrics exposure
