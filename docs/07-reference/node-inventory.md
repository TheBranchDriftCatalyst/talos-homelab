# Node Hardware Inventory

*Generated 2026-08-24 16:09 UTC by `scripts/node-dossier.sh`. Regenerate rather than hand-editing.*

Talos has no SSH, so this is read from the SMBIOS/DMI tables that `talosctl` exposes as resources. **The DIMM part numbers and slot locators below are what you order replacement memory against** — no need to open the case.

## Fleet at a glance

| Node | Role | System | CPU | Cores | RAM | DIMMs |
|---|---|---|---|---:|---:|---:|
| **talos00** | control-plane | QEMU Standard PC (i440FX + PIIX, 1996) | pc-i440fx-2.2 | 4 | 26 GiB | 2 |
| **talos01** | control-plane | AZW EQ | 12th Gen Intel(R) Core(TM) i3-1220P | 10 | 24 GiB | 8 |
| **talos02-gpu** | worker | ASUSTeK COMPUTER INC. NUC15CRHU5 | Intel(R) Core(TM) Ultra 5 225H | 14 | 64 GiB | 2 |
| **talos03** | control-plane | HC Technology.,Ltd. HCAR5000-MI | AMD Ryzen 7 5800U with Radeon Graphics | 8 | 16 GiB | 2 |
| **talos06** | worker | GMKtec NucBox_EVO-T1 | Intel(R) Core(TM) Ultra 9 285H | 16 | 64 GiB | 2 |
| | | | **fleet total** | **52** | **194 GiB** | |

## RAM upgrade planner

**Read the *Upgradeable* column first.** Two of these machines cannot take more memory at any price, and that is not visible from the capacity numbers alone.

| Node | Installed | Config | Speed | Upgradeable | Part number |
|---|---:|---|---:|---|---|
| **talos03** | 16 GiB | 2x8 GiB | 3200 MT/s | ✅ yes | Unknown `LD4S08G32C22ST` |
| **talos01** | 24 GiB | 8x3 GiB | 6600 MT/s | ❌ **NO** | — |
| **talos00** | 26 GiB | 1x10 GiB + 1x16 GiB | ? MT/s | 🖥 VM | — |
| **talos02-gpu** | 64 GiB | 2x32 GiB | 5600 MT/s | ✅ yes | PNY Technologies Inc `M5S32S68B56MMM90-11` |
| **talos06** | 64 GiB | 2x32 GiB | 5600 MT/s | ✅ yes | A-DATA Technology `CBDAD5S560032G-BAD` |

- **talos03** (HC Technology.,Ltd. HCAR5000-MI) — Replaceable sticks — match the part number below.
- **talos01** (AZW EQ) — **Cannot be upgraded.** On-package LPDDR — no sockets exist.
- **talos00** (QEMU Standard PC (i440FX + PIIX, 1996)) — Resize in the hypervisor — no physical RAM to buy.
- **talos02-gpu** (ASUSTeK COMPUTER INC. NUC15CRHU5) — Replaceable sticks — match the part number below.
- **talos06** (GMKtec NucBox_EVO-T1) — Replaceable sticks — match the part number below.

> **Empty slots are NOT reported.** SMBIOS lists only populated modules; Talos exposes no resource for total slot count or the board's maximum capacity. For a socketed node, check the model's spec sheet (in its dossier below) to learn whether there is a free slot or whether existing sticks must be replaced.

> **Form factor is inferred, not reported.** Mini-PCs are usually SODIMM. Confirm against the model before ordering.

## Pluggable devices & passthrough

Everything currently attached by USB, per node, plus where there is room to plug something in. This is the table to look at when deciding which node gets the Zigbee stick or the Bluetooth dongle.

| Node | USB controllers | Attached devices | Notable |
|---|---:|---:|---|
| **talos00** | 1 | 1 | — |
| **talos01** | 4 | 1 | Bluetooth (Intel) |
| **talos02-gpu** | 4 | 1 | Bluetooth (Intel) |
| **talos03** | 4 | 2 | Bluetooth (Bluetooth Radio) |
| **talos06** | 4 | 2 | Bluetooth (Intel), Bluetooth (Bluetooth 5.4 Radio) |

### Passing a USB device into a pod

Talos has no udev rules you can edit and no host shell, so the two workable routes are:

1. **hostPath mount** — simplest, and what Home Assistant / Zigbee2MQTT generally use. Mount the specific device node and schedule the pod to the node holding it:

   ```yaml
   spec:
     nodeSelector:
       kubernetes.io/hostname: <the node with the dongle>   # a device is not portable
     containers:
       - name: app
         securityContext:
           privileged: true          # or add the device via volumeDevices
         volumeMounts:
           - { name: zigbee, mountPath: /dev/ttyACM0 }
     volumes:
       - name: zigbee
         hostPath: { path: /dev/serial/by-id/usb-...-if00, type: CharDevice }
   ```

   Use the stable `/dev/serial/by-id/...` path, never `/dev/ttyACM0` — the numbered name is assigned in probe order and moves when another device is plugged in.

2. **A device plugin** (e.g. `smarter-device-manager`) advertises devices as schedulable resources, so pods request `smarter-devices/ttyACM0` instead of running privileged. More setup, but no privileged container and the scheduler understands the constraint.

> **A USB device pins its pod to one node.** Whichever node holds the dongle, that pod cannot move — which matters here because two nodes carry a PreferNoSchedule taint. Prefer plugging into `talos02-gpu` or `talos06`, which have the headroom.

---

## Node dossiers

### talos00

`192.168.1.54` · **control-plane** · tainted: node-role.kubernetes.io/control-plane:NoSchedule

| | |
|---|---|
| System | QEMU **Standard PC (i440FX + PIIX, 1996)** (pc-i440fx-2.2) |
| Talos / K8s | Talos (v1.13.9) · kubelet v1.36.4 |
| Kernel | 6.18.44-talos |
| Container runtime | containerd://2.2.7 |
| Memory capacity / allocatable | 25.4 GiB / 22.9 GiB *(kubelet reserves 2.5 GiB)* |
| CPU capacity / allocatable | 4 / 3600m |
| Max pods | 200 |

**CPU**

| Socket | Model | Cores | Threads | Boot / max MHz |
|---|---|---:|---:|---|
| CPU 0 | pc-i440fx-2.2 | 4 | 1 | 2000 / 2000 |

**Memory modules**

| Slot | Bank | Size | Speed | Manufacturer | Part number | Serial |
|---|---|---:|---:|---|---|---|
| DIMM 0 | ? | 16 GiB | ? MT/s | QEMU | `?` | `?` |
| DIMM 1 | ? | 10 GiB | ? MT/s | QEMU | `?` | `?` |

*Total 26 GiB across 2 populated slot(s). To match existing memory, order the part number above.*

**Disks**

| Device | Size | Bus |
|---|---:|---|
| `/dev/sda` | 266 GB | `/pci0000:00/0000:00:0a.0/virtio3/host2/target2:0:1/2:0:1:0` |

**Network ports**

| Interface | State | Speed | Duplex | Port | Driver | MAC |
|---|---|---:|---|---|---|---|
| `ens3` | 🟢 up | — | Unknown | Other | virtio_net | `02:11:32:22:d2:c2` |

**USB devices**

*1 root hub(s), 1 attached device(s).*

| Port | VID:PID | Vendor | Product | Class | Speed |
|---|---|---|---|---|---:|
| `1-1` | `0627:0001` | QEMU | QEMU USB Tablet | per-interface | 12 Mb/s |

**Passthrough-able device nodes**

*Other:* `/dev/hidraw0`

**GPU / display**

- VMware SVGA II Adapter


### talos01

`192.168.1.177` · **control-plane** · tainted: catalyst.io/memory-constrained:PreferNoSchedule

| | |
|---|---|
| System | AZW **EQ** (Default string) |
| SKU | `Default string` |
| Serial | `Y12204KF20440` |
| Talos / K8s | Talos (v1.13.9) · kubelet v1.36.4 |
| Kernel | 6.18.44-talos |
| Container runtime | containerd://2.2.7 |
| Memory capacity / allocatable | 23.2 GiB / 20.7 GiB *(kubelet reserves 2.5 GiB)* |
| CPU capacity / allocatable | 12 / 11600m |
| Max pods | 200 |

**CPU**

| Socket | Model | Cores | Threads | Boot / max MHz |
|---|---|---:|---:|---|
| U3E1 | 12th Gen Intel(R) Core(TM) i3-1220P | 10 | 12 | 3762 / 4400 |

**Memory modules**

| Slot | Bank | Size | Speed | Manufacturer | Part number | Serial |
|---|---|---:|---:|---|---|---|
| Controller0-ChannelA | BANK 0 | 3 GiB | 6600 MT/s | Micron Technology | `?` | `20000000` |
| Controller0-ChannelB | BANK 1 | 3 GiB | 6600 MT/s | Micron Technology | `?` | `20000000` |
| Controller0-ChannelC | BANK 2 | 3 GiB | 6600 MT/s | Micron Technology | `?` | `20000000` |
| Controller0-ChannelD | BANK 3 | 3 GiB | 6600 MT/s | Micron Technology | `?` | `20000000` |
| Controller1-ChannelA | BANK 0 | 3 GiB | 6600 MT/s | Micron Technology | `?` | `20000000` |
| Controller1-ChannelB | BANK 1 | 3 GiB | 6600 MT/s | Micron Technology | `?` | `20000000` |
| Controller1-ChannelC | BANK 2 | 3 GiB | 6600 MT/s | Micron Technology | `?` | `20000000` |
| Controller1-ChannelD | BANK 3 | 3 GiB | 6600 MT/s | Micron Technology | `?` | `20000000` |

*Total 24 GiB across 8 populated slot(s). To match existing memory, order the part number above.*

**Disks**

| Device | Size | Bus |
|---|---:|---|
| `/dev/nvme0n1` | 500 GB | `/pci0000:00/0000:00:06.0/0000:01:00.0/nvme` |

**Network ports**

| Interface | State | Speed | Duplex | Port | Driver | MAC |
|---|---|---:|---|---|---|---|
| `enp2s0` | 🟢 up | 1 GbE | Full | TwistedPair | r8169 | `e8:ff:1e:d4:d6:7a` |
| `enp3s0` | 🟢 up | 1 GbE | Full | TwistedPair | r8169 | `e8:ff:1e:d4:d6:79` |

**USB devices**

*4 root hub(s), 1 attached device(s).*

| Port | VID:PID | Vendor | Product | Class | Speed |
|---|---|---|---|---|---:|
| `3-10` | `8087:0026` | Intel | — | wireless (Bluetooth) | 12 Mb/s |

*Passthrough candidates:*

- `3-10` **8087:0026** — Bluetooth — pass /dev/bus/usb + NET_ADMIN, or use host networking

**GPU / display**

- Intel Corporation Alder Lake-UP3 GT1 [UHD Graphics]


### talos02-gpu

`192.168.1.144` · **worker**

| | |
|---|---|
| System | ASUSTeK COMPUTER INC. **NUC15CRHU5** (90AR00Q2-M001P0) |
| SKU | `RNUC15CRHU50000U` |
| Serial | `T6ARQK001930JDM` |
| Talos / K8s | Talos (v1.13.9) · kubelet v1.36.4 |
| Kernel | 6.18.44-talos |
| Container runtime | containerd://2.2.7 |
| Memory capacity / allocatable | 62.1 GiB / 59.6 GiB *(kubelet reserves 2.5 GiB)* |
| CPU capacity / allocatable | 14 / 13600m |
| Max pods | 200 |

**CPU**

| Socket | Model | Cores | Threads | Boot / max MHz |
|---|---|---:|---:|---|
| U3E1 | Intel(R) Core(TM) Ultra 5 225H | 14 | 14 | 4158 / 4900 |

**Memory modules**

| Slot | Bank | Size | Speed | Manufacturer | Part number | Serial |
|---|---|---:|---:|---|---|---|
| Controller0-ChannelA-DIMM0 | BANK 0 | 32 GiB | 5600 MT/s | PNY Technologies Inc | `M5S32S68B56MMM90-11` | `00000000` |
| Controller1-ChannelA-DIMM0 | BANK 0 | 32 GiB | 5600 MT/s | PNY Technologies Inc | `M5S32S68B56MMM90-11` | `00000000` |

*Total 64 GiB across 2 populated slot(s). To match existing memory, order the part number above.*

**Disks**

| Device | Size | Bus |
|---|---:|---|
| `/dev/nvme0n1` | 2.0 TB | `/pci0000:00/0000:00:01.0/0000:01:00.0/nvme` |

**Network ports**

| Interface | State | Speed | Duplex | Port | Driver | MAC |
|---|---|---:|---|---|---|---|
| `enp86s0` | 🟢 up | 2.5 GbE | Full | TwistedPair | igc | `88:ae:dd:73:dc:32` |

**USB devices**

*4 root hub(s), 1 attached device(s).*

| Port | VID:PID | Vendor | Product | Class | Speed |
|---|---|---|---|---|---:|
| `3-10` | `8087:0037` | Intel | — | wireless (Bluetooth) | 12 Mb/s |

*Passthrough candidates:*

- `3-10` **8087:0037** — Bluetooth — pass /dev/bus/usb + NET_ADMIN, or use host networking

**Passthrough-able device nodes**

*GPU render nodes (Plex / Jellyfin / tdarr hardware transcode):*

- `/dev/dri/card0`
- `/dev/dri/renderD128`

**GPU / display**

- Intel Corporation Arrow Lake-P [Arc Pro 130T/140T]


### talos03

`192.168.1.30` · **control-plane** · tainted: catalyst.io/memory-constrained:PreferNoSchedule

| | |
|---|---|
| System | HC Technology.,Ltd. **HCAR5000-MI** (Default string) |
| SKU | `Default string` |
| Talos / K8s | Talos (v1.13.9) · kubelet v1.36.4 |
| Kernel | 6.18.44-talos |
| Container runtime | containerd://2.2.7 |
| Memory capacity / allocatable | 15.0 GiB / 12.5 GiB *(kubelet reserves 2.5 GiB)* |
| CPU capacity / allocatable | 16 / 15600m |
| Max pods | 60 |

**CPU**

| Socket | Model | Cores | Threads | Boot / max MHz |
|---|---|---:|---:|---|
| FP6 | AMD Ryzen 7 5800U with Radeon Graphics | 8 | 16 | 1900 / 4450 |

**Memory modules**

| Slot | Bank | Size | Speed | Manufacturer | Part number | Serial |
|---|---|---:|---:|---|---|---|
| DIMM 0 | P0 CHANNEL A | 8 GiB | 3200 MT/s | Unknown | `LD4S08G32C22ST` | `D1124024` |
| DIMM 0 | P0 CHANNEL B | 8 GiB | 3200 MT/s | Unknown | `LD4S08G32C22ST` | `D1124024` |

*Total 16 GiB across 2 populated slot(s). To match existing memory, order the part number above.*

**Disks**

| Device | Size | Bus |
|---|---:|---|
| `/dev/nvme0n1` | 2.0 TB | `/pci0000:00/0000:00:01.2/0000:01:00.0/nvme` |

**Network ports**

| Interface | State | Speed | Duplex | Port | Driver | MAC |
|---|---|---:|---|---|---|---|
| `eno1` | 🟢 up | 1 GbE | Full | TwistedPair | r8169 | `c8:ff:bf:00:7b:48` |
| `enp4s0` | ⚪ down | — | Unknown | TwistedPair | igc | `c8:ff:bf:00:7b:49` |

**USB devices**

*4 root hub(s), 2 attached device(s).*

| Port | VID:PID | Vendor | Product | Class | Speed |
|---|---|---|---|---|---:|
| `3-3` | `0d8c:0014` | C-Media Electronics Inc. | USB Audio Device | per-interface | 12 Mb/s |
| `3-4` | `0bda:b85b` | Realtek | Bluetooth Radio | wireless (Bluetooth) | 12 Mb/s |

*Passthrough candidates:*

- `3-4` **0bda:b85b** — Bluetooth — pass /dev/bus/usb + NET_ADMIN, or use host networking

**Passthrough-able device nodes**

*GPU render nodes (Plex / Jellyfin / tdarr hardware transcode):*

- `/dev/dri/card0`
- `/dev/dri/renderD128`

*Other:* `/dev/hidraw0`

**GPU / display**

- Advanced Micro Devices, Inc. [AMD/ATI] Cezanne [Radeon Vega Series / Radeon Vega Mobile Series]


### talos06

`192.168.1.19` · **worker**

| | |
|---|---|
| System | GMKtec **NucBox_EVO-T1** (V1.1) |
| SKU | `EVO-T1-001` |
| Talos / K8s | Talos (v1.13.9) · kubelet v1.36.4 |
| Kernel | 6.18.44-talos |
| Container runtime | containerd://2.2.7 |
| Memory capacity / allocatable | 62.3 GiB / 59.8 GiB *(kubelet reserves 2.5 GiB)* |
| CPU capacity / allocatable | 16 / 15600m |
| Max pods | 200 |

**CPU**

| Socket | Model | Cores | Threads | Boot / max MHz |
|---|---|---:|---:|---|
| U3E1 | Intel(R) Core(TM) Ultra 9 285H | 16 | 16 | 4059 / 5400 |

**Memory modules**

| Slot | Bank | Size | Speed | Manufacturer | Part number | Serial |
|---|---|---:|---:|---|---|---|
| Controller0-ChannelA-DIMM0 | BANK 0 | 32 GiB | 5600 MT/s | A-DATA Technology | `CBDAD5S560032G-BAD` | `00098174` |
| Controller1-ChannelA-DIMM0 | BANK 0 | 32 GiB | 5600 MT/s | A-DATA Technology | `CBDAD5S560032G-BAD` | `00098176` |

*Total 64 GiB across 2 populated slot(s). To match existing memory, order the part number above.*

**Disks**

| Device | Size | Bus |
|---|---:|---|
| `/dev/nvme0n1` | 1.0 TB | `/pci0000:00/0000:00:06.0/0000:01:00.0/nvme` |

**Network ports**

| Interface | State | Speed | Duplex | Port | Driver | MAC |
|---|---|---:|---|---|---|---|
| `enp44s0` | ⚪ down | — | Unknown | TwistedPair | r8169 | `84:47:09:6d:09:a3` |
| `enp45s0` | 🟢 up | 2.5 GbE | Full | TwistedPair | r8169 | `84:47:09:6d:09:a2` |

**USB devices**

*4 root hub(s), 2 attached device(s).*

| Port | VID:PID | Vendor | Product | Class | Speed |
|---|---|---|---|---|---:|
| `3-10` | `8087:0026` | Intel | — | wireless (Bluetooth) | 12 Mb/s |
| `3-4` | `0bda:a728` | Realtek | Bluetooth 5.4 Radio | wireless (Bluetooth) | 12 Mb/s |

*Passthrough candidates:*

- `3-10` **8087:0026** — Bluetooth — pass /dev/bus/usb + NET_ADMIN, or use host networking
- `3-4` **0bda:a728** — Bluetooth — pass /dev/bus/usb + NET_ADMIN, or use host networking

**Passthrough-able device nodes**

*GPU render nodes (Plex / Jellyfin / tdarr hardware transcode):*

- `/dev/dri/card0`
- `/dev/dri/renderD128`

**GPU / display**

- Intel Corporation Arrow Lake-P [Arc Pro 130T/140T]


