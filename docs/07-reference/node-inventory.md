# Node Hardware Inventory

*Generated 2026-08-24 16:19 UTC by `scripts/node-dossier.sh`. Regenerate rather than hand-editing.*

Talos has no SSH, so this is read from the SMBIOS/DMI tables that `talosctl` exposes as resources. **The DIMM part numbers and slot locators below are what you order replacement memory against** — no need to open the case.

## Fleet at a glance

<table>
  <thead>
    <tr>
      <th>Role</th>
      <th>Node</th>
      <th>System</th>
      <th>CPU</th>
      <th align="right">Cores</th>
      <th align="right">RAM</th>
      <th align="right">DIMMs</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td rowspan="3"><b>control-plane</b></td>
      <td><b>talos00</b></td>
      <td>QEMU Standard PC (i440FX + PIIX, 1996)</td>
      <td>pc-i440fx-2.2</td>
      <td align="right">4</td>
      <td align="right">26 GiB</td>
      <td align="right">2</td>
    </tr>
    <tr>
      <td><b>talos01</b></td>
      <td>AZW EQ</td>
      <td>12th Gen Intel(R) Core(TM) i3-1220P</td>
      <td align="right">10</td>
      <td align="right">24 GiB</td>
      <td align="right">8</td>
    </tr>
    <tr>
      <td><b>talos03</b></td>
      <td>HC Technology.,Ltd. HCAR5000-MI</td>
      <td>AMD Ryzen 7 5800U with Radeon Graphics</td>
      <td align="right">8</td>
      <td align="right">16 GiB</td>
      <td align="right">2</td>
    </tr>
    <tr>
      <td rowspan="2"><b>worker</b></td>
      <td><b>talos02-gpu</b></td>
      <td>ASUSTeK COMPUTER INC. NUC15CRHU5</td>
      <td>Intel(R) Core(TM) Ultra 5 225H</td>
      <td align="right">14</td>
      <td align="right">64 GiB</td>
      <td align="right">2</td>
    </tr>
    <tr>
      <td><b>talos06</b></td>
      <td>GMKtec NucBox_EVO-T1</td>
      <td>Intel(R) Core(TM) Ultra 9 285H</td>
      <td align="right">16</td>
      <td align="right">64 GiB</td>
      <td align="right">2</td>
    </tr>
  </tbody>
</table>

**Fleet total: 52 cores, 194 GiB RAM across 5 nodes.**

## RAM upgrade planner

**Read the *Upgradeable* column first.** Two of these machines cannot take more memory at any price, and that is not visible from the capacity numbers alone.

<table>
  <thead>
    <tr>
      <th>Upgradeable</th>
      <th>Node</th>
      <th align="right">Installed</th>
      <th>Config</th>
      <th>Speed</th>
      <th align="right">Part number</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td rowspan="3"><b>✅ Upgradeable</b></td>
      <td><b>talos03</b></td>
      <td align="right">16 GiB</td>
      <td>2x8 GiB</td>
      <td>3200 MT/s</td>
      <td align="right">Unknown `LD4S08G32C22ST`</td>
    </tr>
    <tr>
      <td><b>talos02-gpu</b></td>
      <td align="right">64 GiB</td>
      <td>2x32 GiB</td>
      <td>5600 MT/s</td>
      <td align="right">PNY Technologies Inc `M5S32S68B56MMM90-11`</td>
    </tr>
    <tr>
      <td><b>talos06</b></td>
      <td align="right">64 GiB</td>
      <td>2x32 GiB</td>
      <td>5600 MT/s</td>
      <td align="right">A-DATA Technology `CBDAD5S560032G-BAD`</td>
    </tr>
    <tr>
      <td rowspan="1"><b>❌ Soldered — cannot upgrade</b></td>
      <td><b>talos01</b></td>
      <td align="right">24 GiB</td>
      <td>8x3 GiB</td>
      <td>6600 MT/s</td>
      <td align="right">—</td>
    </tr>
    <tr>
      <td rowspan="1"><b>🖥 Virtual machine</b></td>
      <td><b>talos00</b></td>
      <td align="right">26 GiB</td>
      <td>1x10 GiB + 1x16 GiB</td>
      <td>? MT/s</td>
      <td align="right">—</td>
    </tr>
  </tbody>
</table>

- **talos03** (HC Technology.,Ltd. HCAR5000-MI) — Replaceable sticks — match the part number below.
- **talos01** (AZW EQ) — **Cannot be upgraded.** On-package LPDDR — no sockets exist.
- **talos00** (QEMU Standard PC (i440FX + PIIX, 1996)) — Resize in the hypervisor — no physical RAM to buy.
- **talos02-gpu** (ASUSTeK COMPUTER INC. NUC15CRHU5) — Replaceable sticks — match the part number below.
- **talos06** (GMKtec NucBox_EVO-T1) — Replaceable sticks — match the part number below.

> **Empty slots are NOT reported.** SMBIOS lists only populated modules; Talos exposes no resource for total slot count or the board's maximum capacity. For a socketed node, check the model's spec sheet (in its dossier below) to learn whether there is a free slot or whether existing sticks must be replaced.

> **Form factor is inferred, not reported.** Mini-PCs are usually SODIMM. Confirm against the model before ordering.

## Pluggable devices & passthrough

Everything currently attached by USB, per node, plus where there is room to plug something in. This is the table to look at when deciding which node gets the Zigbee stick or the Bluetooth dongle.

<table>
  <thead>
    <tr>
      <th>Node</th>
      <th>Port</th>
      <th>VID:PID</th>
      <th>Vendor</th>
      <th>Product</th>
      <th>Class</th>
      <th align="right">Speed</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td rowspan="1"><b>talos00<br><small>1 controllers</small></b></td>
      <td><code>1-1</code></td>
      <td><code>0627:0001</code></td>
      <td>QEMU</td>
      <td>QEMU USB Tablet</td>
      <td>per-interface</td>
      <td align="right">12 Mb/s</td>
    </tr>
    <tr>
      <td rowspan="1"><b>talos01<br><small>4 controllers</small></b></td>
      <td><code>3-10</code></td>
      <td><code>8087:0026</code></td>
      <td>Intel</td>
      <td>—</td>
      <td>wireless (Bluetooth)</td>
      <td align="right">12 Mb/s</td>
    </tr>
    <tr>
      <td rowspan="1"><b>talos02-gpu<br><small>4 controllers</small></b></td>
      <td><code>3-10</code></td>
      <td><code>8087:0037</code></td>
      <td>Intel</td>
      <td>—</td>
      <td>wireless (Bluetooth)</td>
      <td align="right">12 Mb/s</td>
    </tr>
    <tr>
      <td rowspan="2"><b>talos03<br><small>4 controllers</small></b></td>
      <td><code>3-3</code></td>
      <td><code>0d8c:0014</code></td>
      <td>C-Media Electronics Inc.</td>
      <td>USB Audio Device</td>
      <td>per-interface</td>
      <td align="right">12 Mb/s</td>
    </tr>
    <tr>
      <td><code>3-4</code></td>
      <td><code>0bda:b85b</code></td>
      <td>Realtek</td>
      <td>Bluetooth Radio</td>
      <td>wireless (Bluetooth)</td>
      <td align="right">12 Mb/s</td>
    </tr>
    <tr>
      <td rowspan="2"><b>talos06<br><small>4 controllers</small></b></td>
      <td><code>3-10</code></td>
      <td><code>8087:0026</code></td>
      <td>Intel</td>
      <td>—</td>
      <td>wireless (Bluetooth)</td>
      <td align="right">12 Mb/s</td>
    </tr>
    <tr>
      <td><code>3-4</code></td>
      <td><code>0bda:a728</code></td>
      <td>Realtek</td>
      <td>Bluetooth 5.4 Radio</td>
      <td>wireless (Bluetooth)</td>
      <td align="right">12 Mb/s</td>
    </tr>
  </tbody>
</table>

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

### Making a device reachable from any node

A hostPath mount welds the consumer to one machine. To let the consuming pod schedule anywhere, put a small per-node bridge in front of the device and talk to it over the network. The device stays pinned; the consumer stops being pinned.

**For serial devices — Zigbee, Matter, Z-Wave, P1 meters — use `ser2net`.** This is the established route and it needs nothing special from Talos:

```
  DaemonSet (nodeSelector: the node with the stick)
    ser2net  --  /dev/serial/by-id/usb-...-if00  <->  TCP :20108
        |
     Service  zigbee-serial.home-automation.svc:20108
        |
  Home Assistant / Zigbee2MQTT   (schedules ANYWHERE)
    port: tcp://zigbee-serial.home-automation.svc:20108
```

Zigbee2MQTT, ZHA and Z-Wave JS all accept a `tcp://` serial port natively, so this needs no shim on the consumer side. Use a DaemonSet with a nodeSelector rather than a StatefulSet: there is no ordering or identity to preserve, only a device to sit next to.

**USB/IP is NOT available on stock Talos.** The obvious answer for arbitrary USB — `usbip_host` on the node, `vhci-hcd` on the consumer — cannot be used here: neither module ships in the Talos kernel (checked against all 431 modules in `/lib/modules/6.18.44-talos`). Getting it would mean a custom kernel via Image Factory or a system extension, plus a privileged client pod loading `vhci-hcd`. That is a large amount of machinery for a homelab, and it is why the serial-over-TCP route is the recommendation for anything that speaks serial.

**What Talos DOES ship**, verified on this cluster, so sticks enumerate correctly:

- `cdc-acm` — built into the kernel. Covers ConBee, SkyConnect, most CC2652 and Matter sticks, which appear as `/dev/ttyACM*`.
- `ch341`, `cp210x`, `ftdi_sio`, `pl2303` — loadable modules, covering the older USB-serial bridges that appear as `/dev/ttyUSB*`.
- Char devices 166 (`ttyACM`) and 188 (`ttyUSB`) are registered in `/proc/devices`.

**For Bluetooth**, none of this applies: the radio is already on the PCI/USB bus of every node in this fleet (see the table above), so run the consumer with host networking and `NET_ADMIN` on a node that has one, rather than bridging anything.

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


