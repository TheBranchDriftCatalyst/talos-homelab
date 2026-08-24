# Bluetooth enablement (Talos)

> Parent: [docs/05-runbooks](./) · Status: **artefacts built, NOT yet applied to any node**

## TL;DR

Stock Talos compiles the entire Bluetooth subsystem out (`# CONFIG_BT is not set`). Fixing it
needs three things, in this order:

```bash
# 1. modules: rebuild the OFFICIAL kernel with a 2-line config delta, keep only the .ko files
# 2. firmware: intel/ibt-* (no official extension ships it); Realtek is covered upstream
# 3. boot arg: REMOVE the signature-enforcement default -- note the leading dash
#      customization.extraKernelArgs: ["-module.sig_enforce"]
```

- We do **not** fork the kernel. We rebuild it, throw it away, and ship only modules.
- `module.sig_enforce=0` **does not work** and fails silently. Use `-module.sig_enforce`.
- The CRC gate proves the modules will load **before** any node is rebooted.

## Why each piece is needed

| Problem | Evidence | Fix |
| --- | --- | --- |
| No Bluetooth code in the kernel | `# CONFIG_BT is not set` in `/proc/config.gz` on a live node, and in `pkgs@f541ca4/kernel/build/config-amd64` | rebuild with `CONFIG_BT=m`, `CONFIG_BT_HCIBTUSB=m` |
| Modules would be rejected at load | `module.sig_enforce=1` on every node's cmdline; signing key is `CN = Build time throw-away kernel key`, generated per build and never published | remove the boot arg |
| Intel radios need firmware | `/lib/firmware` on talos06 has only `i915`, `intel-ucode`; no official extension ships `intel/ibt-*` | custom firmware extension (88 files, 31 MB) |
| Realtek radios need firmware | same | official `siderolabs/realtek-firmware` (already ships `rtl_bt`) |

## The `-module.sig_enforce` trap — read this before editing any schematic

`module.sig_enforce=0` looks correct and is **wrong**. Two facts combine:

1. Talos appends `extraKernelArgs` **after** its defaults, and only `console` and
   `talos.platform` are in the overwrite list (`pkg/imager/imager.go:386-412`). So you end up
   with *both* `module.sig_enforce=1` and `module.sig_enforce=0` on the cmdline.
2. The kernel refuses the downgrade (`kernel/params.c:348`):
   ```c
   /* Don't let them unset it once it's set! */
   if (!new_value && orig_value)
           return -EROFS;
   ```

`=1` wins, the `=0` is discarded, Bluetooth stays dead, and nothing in the config looks wrong.

The negation form deletes the default outright (`go-procfs procfs/cmdline.go:275-283` ->
`DeleteAll`), letting `sig_enforce` fall back to its `false` initialiser.

**Verify after first boot by ABSENCE, not by value:**

```bash
talosctl -n <ip> read /proc/cmdline | tr ' ' '\n' | grep sig_enforce
# CORRECT   -> no output at all
# BROKEN    -> "module.sig_enforce=1"  (negation did not apply)
```

## Radio inventory (verified 2026-08-24 from /sys/kernel/debug/usb/devices)

`Cls=e0(wlcon)` = Bluetooth. All currently show `Driver=(none)`.

| Node | IP | Radios | Firmware needed |
| --- | --- | --- | --- |
| talos00 | 192.168.1.54 | none (VM) | — keep enforcement ON |
| talos01 | 192.168.1.177 | 1 — Intel `8087:0026` | intel-bt-firmware |
| talos02-gpu | 192.168.1.144 | 1 — Intel `8087:0037` | intel-bt-firmware |
| talos03 | 192.168.1.30 | 1 — Realtek `0bda:b85b` | realtek-firmware (official) |
| talos06 | 192.168.1.19 | 2 — Realtek `0bda:a728` + Intel `8087:0026` | both |

Total: **5 radios**. Only talos06 has two.

> Corrections to earlier notes: talos01 is `8087:0026` (not `8087:0032`), and talos03 has
> **one** radio — its second USB device `0d8c:0014` is a C-Media audio adapter
> (`Cls=01(audio)`), not a radio.

## Existing per-node schematics (must be preserved)

| Node | Schematic | Extensions |
| --- | --- | --- |
| talos00 | *(stock installer)* | none |
| talos01 | `c9078f94…` | iscsi-tools |
| talos02-gpu | `4b3cd373…` | i915, intel-ucode |
| talos03 | `1e17720b…` | amd-ucode, amdgpu, iscsi-tools |
| talos06 | `16be3b98…` | intel-ucode, i915, mei |

The **public** Image Factory cannot deliver this: its schematic schema exposes only
`SystemExtensions.OfficialExtensions []string` — no field for a custom OCI image. Build
installers locally with `imager` instead (it keeps the official kernel via
`--base-installer-image`).

```bash
docker run --rm -v $PWD/_out:/out -v /var/run/docker.sock:/var/run/docker.sock \
  ghcr.io/siderolabs/imager:v1.13.9 installer \
    --base-installer-image ghcr.io/siderolabs/installer:v1.13.9 \
    --system-extension-image <registry>/talos-bluetooth:v1.13.9 \
    --system-extension-image <registry>/talos-intel-bt-firmware:v1.13.9 \
    --extra-kernel-arg=-module.sig_enforce
# NOTE the `=` form: a bare `-module.sig_enforce` would be parsed as a CLI flag.
```

Each node also needs its **existing** extensions re-declared in the same invocation.

## Security trade — state this to the operator, do not bury it

Removing `module.sig_enforce` means **any** kernel module the node can read becomes loadable,
not just ours.

- **Not remotely exploitable on its own.** Loading a module needs `CAP_SYS_MODULE`, i.e. the
  Talos API (already total control) or a privileged workload.
- **It is a privilege-escalation amplifier**: it turns "attacker has a privileged container"
  into "attacker executes arbitrary ring-0 code".
- Mitigating: Talos is immutable, modules don't survive reboot, and lockdown is already
  `FORCE_NONE` with SecureBoot unused — the integrity posture was never airtight.
- Aggravating: it is a CIS/KSPP hardening default and an auditor will flag it.

**Scope it.** Only flip it on nodes with radios. **talos00 keeps enforcement** (it is a VM with
no radio). Pair with PodSecurity admission denying privileged/`CAP_SYS_MODULE` outside one
named namespace.

## What a pod needs to actually use a radio

| Requirement | Why |
| --- | --- |
| `hostNetwork: true` — **mandatory** | `bt_sock_create()` starts `if (net != &init_net) return -EAFNOSUPPORT;` (`net/bluetooth/af_bluetooth.c:121`). Bluetooth is not netns-aware; **every** AF_BLUETOOTH socket fails in a pod netns. Not fixable by a device plugin. |
| `CAP_NET_ADMIN` | required to bind `HCI_CHANNEL_USER` (`hci_sock.c:1287`) and for `HCIDEVUP` |
| `CAP_NET_RAW` | required for raw HCI channel and unfiltered commands |
| **no** device node | there is no `/dev/hciN`. `bt_class` is a bare sysfs class with no devnode; access is socket-only. A device plugin therefore cannot hand out a device file — it must pass the adapter **index** (e.g. an env var). |
| exclusive access | `hci_dev_test_and_set_flag(hdev, HCI_USER_CHANNEL)` -> second opener gets `-EUSERS`; and bind fails `-EBUSY` if the adapter is already UP. **Capacity is strictly 1 per radio.** |
| no BlueZ needed | `HCI_CHANNEL_USER` bypasses bluetoothd entirely — and *conflicts* with it, since User Channel calls `mgmt_index_removed()`. Do **not** ship bluetoothd. |

`go-ble` matches this exactly: `unix.Socket(AF_BLUETOOTH, SOCK_RAW, BTPROTO_HCI)` bound with
`SockaddrHCI{Dev: id, Channel: unix.HCI_CHANNEL_USER}`.

## Verification after upgrade (in order)

```bash
talosctl -n <ip> read /proc/cmdline | tr ' ' '\n' | grep sig_enforce   # expect NO output
talosctl -n <ip> list /sys/class/bluetooth                            # expect hci0 (and hci1 on talos06)
talosctl -n <ip> read /sys/kernel/debug/usb/devices | grep -A1 'Vendor=8087'  # Driver=btusb, not (none)
talosctl -n <ip> dmesg | grep -iE 'bluetooth|btusb|btintel|btrtl'     # firmware load lines, no -EINVAL
```

## Rollback

Re-run `imager` for the node **without** the bluetooth/firmware extensions and **without**
`--extra-kernel-arg=-module.sig_enforce`, then `talosctl upgrade` back to it. Enforcement
returns on the next boot. Nothing persists.

## Build results — verified 2026-08-24

Built from `siderolabs/pkgs @ f541ca4` (`git describe` = `v1.13.0-60-gf541ca4`, exactly what
Talos v1.13.9 pins), linux 6.18.44, config delta of **two lines**:

```diff
-# CONFIG_BT is not set
+CONFIG_BT=m
+CONFIG_BT_HCIBTUSB=m
```

Everything else came from Kconfig defaults and `select`. Modules produced:

| Module | Size | depends |
| --- | --- | --- |
| `bluetooth.ko` | 2,330,298 | — |
| `btusb.ko` | 171,378 | bluetooth, btrtl, btintel, btbcm |
| `btintel.ko` | 156,138 | bluetooth |
| `btrtl.ko` | 64,442 | bluetooth |
| `btbcm.ko` | 50,594 | bluetooth |

### Gate 1 — config delta is modules-only: **PASS**

Diffed the build's generated `.config` against `/proc/config.gz` pulled from the running
talos06 kernel. **33 differences, every one in the `CONFIG_BT*` namespace.** Five new `=m`
modules, six BT-internal `=y` sub-options, the rest still `n`. **Zero** changes outside `BT*`,
so nothing that was compiled into the kernel moved.

### Gate 2 — CRC/vermagic equivalence: **PASS**

Four official modules pulled off the live node (`tg3`, `e1000e`, `hid-multitouch`, `xor`) —
covering net, PCI, DMA, HID/USB and crypto — contribute **313 distinct versioned symbols**.
Every one was checked against our `Module.symvers`:

```
DISTINCT symbols checked : 313
CRC mismatches           : 0
Missing from our symvers : 0
vermagic official        : '6.18.44-talos SMP preempt mod_unload modversions '
vermagic ours            : identical for bluetooth.ko and btusb.ko
=== GATE: PASS ===
```

This is a **static proof** that these modules will load into the official Talos kernel. It cost
no reboot and no node change.

> Reproduce: `python3 rungate.py kout/boot/Module.symvers <our .ko>...`

### Trap: our signature looks identical to Sidero's

All five modules end with `~Module signature appended~` and their signer certificate reads:

```
O  = Sidero Labs, Inc.
CN = Build time throw-away kernel key
```

**That is our key, not Sidero's.** The subject strings match because `x509.genkey` is committed
upstream and hardcodes those fields, while the keypair itself is regenerated on every build.
You therefore **cannot** tell an official module from ours by inspecting the signer — only real
signature verification against the kernel's builtin key distinguishes them. Do not use the CN
as evidence that a module will load.

## RFKILL — CONFIG_BT does NOT require it

A reasonable-looking objection is that `CONFIG_BT` depends on `CONFIG_RFKILL`, which is `n` in
Talos. It does not. The actual stanza in `net/bluetooth/Kconfig` (6.18) is:

```kconfig
menuconfig BT
	tristate "Bluetooth subsystem support"
	depends on !S390
	depends on RFKILL || !RFKILL
```

`depends on RFKILL || !RFKILL` is the standard Kconfig **tristate level-matching idiom**, not a
hard dependency. At the boolean level it is a tautology; its real job is to forbid `BT=y` while
`RFKILL=m` (built-in code cannot call into a module). With `RFKILL=n` the `!RFKILL` branch is
true and the dependency is satisfied.

**Proven empirically, not just by reading Kconfig** — the completed build has:

```
# CONFIG_RFKILL is not set
CONFIG_BT=m
```

and produced `bluetooth.ko` and `btusb.ko`. Neither imports a single rfkill symbol
(`bluetooth.ko`: 255 imports, 0 rfkill; `btusb.ko`: 115 imports, 0 rfkill), so there is no
link-time or runtime dependency either.

### Leaving RFKILL off removes a failure mode

`hci_core.c:2637` guards the soft-block path:

```c
if (hdev->rfkill && rfkill_blocked(hdev->rfkill))
        hci_dev_set_flag(hdev, HCI_RFKILLED);
```

With `CONFIG_RFKILL=n`, `hdev->rfkill` is never allocated and stays NULL, so `HCI_RFKILLED` can
never be set. **A radio cannot come up soft-blocked on these nodes.** If `hciN` appears but
`HCIDEVUP` fails, rfkill is not the cause — look at firmware.

### Would enabling RFKILL have been safe anyway?

Yes, in this config — an earlier note in the plan asserted otherwise and that was overstated.
Every rfkill consumer is disabled in Talos: `CFG80211=n`, `WLAN=n`, `NFC=n`, and all the
`*_LAPTOP`/`*_WMI` platform drivers are off. So `RFKILL=m` would have been a clean `n->m` with
no built-in change. It is simply unnecessary, and leaving it off is strictly better per the
soft-block point above.

## Confirmations for the device-plugin work

| Requirement | Status | Evidence |
| --- | --- | --- |
| `/sys/class/bluetooth/hciN` appears | **confirmed** | `hci_init_sysfs()` sets `dev->class = &bt_class` (class name `"bluetooth"`); `dev_set_name(&hdev->dev, "hci%u", id)` → `hci0`, `hci1` |
| radios bind `btusb`, not generic `usb` | **confirmed** | `btusb.ko` declares the generic alias `usb:v*p*d*dc*dsc*dp*icE0isc01ip01in*`; all four radio types report exactly `Cls=e0 Sub=01 Prot=01`, so all match. No explicit VID/PID needed. |
| `machine.kernel.modules` includes btusb | **schema confirmed** | `KernelModuleConfig{ ModuleName, ModuleParameters }` exists in v1.13.9 |
| no BlueZ / bluetoothd | **confirmed** | User Channel calls `mgmt_index_removed()` and bind fails `-EBUSY` if the adapter is UP; bluetoothd would fight go-ble for the adapter |

```yaml
machine:
  kernel:
    modules:
      - name: btusb
```

Declare it explicitly rather than relying on modalias autoload — it is the documented Talos
mechanism and removes a dependency on udev uevent timing.

## Published artefacts (2026-08-24) — built and verified, NOT applied

### Extensions

| Image | Digest | Contents |
| --- | --- | --- |
| `registry.talos00/talos00-registry/talos-bluetooth:v1.13.9` | `sha256:0eba0b34…bcdf94` | 5 modules |
| `registry.talos00/talos00-registry/talos-intel-bt-firmware:v1.13.9` | `sha256:7d5cefd8…a07ffa` | 88 `intel/ibt-*` |

### Per-node installers

Each is built on the node's **existing** factory schematic as `--base-installer-image`, so its
current extensions are preserved exactly, with our extensions and the kernel-arg change layered on.

| Node | Installer image | Digest | Base schematic | Custom extensions added |
| --- | --- | --- | --- | --- |
| talos01 | `…/talos-installer-talos01:v1.13.9-bt` | `sha256:254b1c99…db9d03` | `c9078f94…` (existing) | bluetooth + intel-fw |
| talos02-gpu | `…/talos-installer-talos02-gpu:v1.13.9-bt` | `sha256:4f93f64b…a925a810` | `4b3cd373…` (existing) | bluetooth + intel-fw |
| talos03 | `…/talos-installer-talos03:v1.13.9-bt` | `sha256:751c3f62…fa7459` | `6e369a21…` (**new**) | bluetooth |
| talos06 | `…/talos-installer-talos06:v1.13.9-bt` | `sha256:a407829d…5ab13b` | `6fe7fae0…` (**new**) | bluetooth + intel-fw |

**talos00 is deliberately excluded** — VM, no radio, keeps signature enforcement.

Two **new** factory schematics were registered to add the official `siderolabs/realtek-firmware`
to the nodes with Realtek radios, preserving their existing extensions:

- talos03 `6e369a2167fe2744aa6d6bf6f585a174e66157b44b32106434978f692699b768` — amd-ucode, amdgpu, iscsi-tools, **realtek-firmware**
- talos06 `6fe7fae0cea4942b79e4e1984cbd773aae3f7c25ab6fdcc2a513a10c8417f9b9` — intel-ucode, i915, mei, **realtek-firmware**

### The `-module.sig_enforce` negation is now PROVEN, not inferred

The imager prints the resulting cmdline, which let me run a control experiment. Same base, same
Talos version, only the flag differs:

```
--extra-kernel-arg=module.sig_enforce=0   (the WRONG form)
  -> ... selinux=1 module.sig_enforce=1 module.sig_enforce=0 proc_mem.force_override=never
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ BOTH present; =1 is first and wins (-EROFS)

--extra-kernel-arg=-module.sig_enforce    (the CORRECT form)
  -> ... selinux=1 proc_mem.force_override=never
         token removed entirely; sig_enforce falls back to false
```

Confirmed again in the **shipped artefact** by extracting the UKI's PE sections: profile `ID=main`
carries a `.cmdline` with no `module.sig_enforce` token.

> The UKI also contains a second profile, `ID=reset-maintenance`, whose `.cmdline` includes
> `talos.experimental.wipe=system:EPHEMERAL,STATE`. That is **stock Talos v1.13.9**, present in
> every v1.13.9 UKI, and applies only if that boot entry is deliberately selected. It is not
> something this build introduced.

### Artefact-level content verification (talos06)

Unpacked the UKI `.initrd` (zstd → cpio) and enumerated it:

```
squashfs members:
   rootfs.sqsh        83,214,336   base Talos rootfs
   0.sqsh                565,248   <- our bluetooth extension
   1.sqsh                  4,096   firmware extension skeleton
   modules.dep.sqsh      188,416   <- Talos-generated dependency tree

0.sqsh contents:
   usr/lib/modules/6.18.44-talos/kernel/net/bluetooth/bluetooth.ko
   usr/lib/modules/6.18.44-talos/kernel/drivers/bluetooth/{btusb,btintel,btrtl,btbcm}.ko

Intel BT firmware: 88 files, 30,215,133 bytes, at usr/lib/firmware/intel/ibt-*
```

Note firmware is placed as **plain cpio entries**, not inside the extension's squashfs — Talos
hoists firmware into the initramfs directly so the kernel firmware loader can reach it early.
That is why `1.sqsh` looks almost empty; it is expected, not a packaging fault.

`modules.dep.sqsh` confirms Talos ran depmod across the merged tree, as designed.
