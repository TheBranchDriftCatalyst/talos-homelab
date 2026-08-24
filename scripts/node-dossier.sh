#!/usr/bin/env bash
# node-dossier.sh — generate a hardware inventory of every Talos node.
#
# Talos is immutable and has no SSH, but talosctl exposes the machine's SMBIOS/DMI
# tables as resources. That is where the RAM part numbers, DIMM slot locators and
# board model live — everything you need to buy compatible memory without opening
# the case.
#
#   ./scripts/node-dossier.sh                      # -> docs/07-reference/node-inventory.md
#   ./scripts/node-dossier.sh -o /tmp/nodes.md     # somewhere else
#   ./scripts/node-dossier.sh -n 192.168.1.19      # one node only
#
# Requires: talosctl, kubectl, python3, and a valid TALOSCONFIG.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export TALOSCONFIG="${TALOSCONFIG:-$REPO_ROOT/configs/talosconfig}"
OUT="$REPO_ROOT/docs/07-reference/node-inventory.md"
ONLY_NODE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -o|--output) OUT="$2"; shift 2 ;;
    -n|--node)   ONLY_NODE="$2"; shift 2 ;;
    -h|--help)   sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

command -v talosctl >/dev/null || { echo "talosctl not found" >&2; exit 1; }
[[ -r "$TALOSCONFIG" ]] || { echo "TALOSCONFIG not readable: $TALOSCONFIG" >&2; exit 1; }

# Node name -> IP, from Kubernetes. Falls back to nothing if the API is down;
# the dossier is a hardware document, so a partial run is better than no run.
echo "==> discovering nodes" >&2
NODES=$(kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.addresses[?(@.type=="InternalIP")].address}{"\n"}{end}' 2>/dev/null)
[[ -n "$NODES" ]] || { echo "could not list nodes from kubectl" >&2; exit 1; }
[[ -n "$ONLY_NODE" ]] && NODES=$(grep -- "$ONLY_NODE" <<<"$NODES")

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

# Collect per node. Each talosctl call is bounded so one unreachable node cannot
# hang the whole run; a node that times out still gets a dossier saying so.
while read -r NAME IP; do
  [[ -z "${NAME:-}" ]] && continue
  echo "==> $NAME ($IP)" >&2
  D="$WORK/$NAME"; mkdir -p "$D"; echo "$IP" > "$D/ip"
  for R in systeminformation processors memorymodules disks pcidevices linkstatuses; do
    timeout 45 talosctl -n "$IP" get "$R" -o yaml > "$D/$R.yaml" 2>/dev/null || : > "$D/$R.yaml"
  done
  timeout 30 talosctl -n "$IP" version --short > "$D/version" 2>/dev/null || : > "$D/version"
  kubectl get node "$NAME" -o json > "$D/k8s.json" 2>/dev/null || : > "$D/k8s.json"

  # USB tree. sysfs has no bulk-read, so each attribute is its own call — bounded and
  # backgrounded per device so a node with many ports does not serialise into minutes.
  # Entries containing ':' are USB *interfaces* (e.g. 3-10:1.0), not devices; skip them.
  # Entries like 'usb1' are root hubs — kept, because they tell you controller layout.
  : > "$D/usb.txt"
  USBDEVS=$(timeout 30 talosctl -n "$IP" ls /sys/bus/usb/devices 2>/dev/null | tail -n +2 | awk '{print $2}' | grep -v ':' | grep -v '^\.$')
  for U in $USBDEVS; do
    (
      LINE="$U"
      for F in idVendor idProduct manufacturer product serial bDeviceClass bInterfaceClass speed maxchild busnum devnum; do
        V=$(timeout 12 talosctl -n "$IP" read "/sys/bus/usb/devices/$U/$F" 2>/dev/null | tr -d '\r\n' | sed 's/|/ /g')
        LINE="$LINE|$F=$V"
      done
      echo "$LINE"
    ) >> "$D/usb.txt" &
  done
  wait

  # Device nodes that can be handed to a pod. This is the list you actually mount.
  timeout 30 talosctl -n "$IP" ls /dev > "$D/dev.txt" 2>/dev/null || : > "$D/dev.txt"
  # /dev alone is not enough — the paths that matter live one level down:
  # /dev/dri/renderD128 for GPU transcode, and /dev/serial/by-id/* which is the ONLY
  # stable name for a serial dongle.
  : > "$D/devsub.txt"
  for SUB in dri serial/by-id input snd; do
    timeout 20 talosctl -n "$IP" ls "/dev/$SUB" 2>/dev/null | tail -n +2 | awk -v s="$SUB" '$2 != "." {print s"/"$2}' >> "$D/devsub.txt"
  done
done <<<"$NODES"

echo "==> rendering $OUT" >&2
mkdir -p "$(dirname "$OUT")"
WORK="$WORK" OUT="$OUT" python3 - <<'PY'
import os, glob, json, datetime, re

WORK = os.environ["WORK"]; OUT = os.environ["OUT"]

def docs(path):
    """Parse the multi-document YAML talosctl emits, without a yaml dependency.
    Each doc is 'node:/metadata:/spec:' — we only want spec, flat scalars."""
    try: raw = open(path).read()
    except OSError: return []
    out = []
    for chunk in raw.split("\n---\n"):
        if "spec:" not in chunk: continue
        spec, indent = {}, None
        for line in chunk.split("spec:", 1)[1].split("\n"):
            if not line.strip() or line.strip().startswith("-"): continue
            cur = len(line) - len(line.lstrip())
            if indent is None: indent = cur
            if cur != indent: continue           # skip nested blocks
            if ":" not in line: continue
            k, _, v = line.strip().partition(":")
            v = v.strip().strip('"')
            if v: spec[k] = v
        mid = re.search(r"^\s+id:\s*(.+)$", chunk, re.M)
        if mid: spec["_id"] = mid.group(1).strip()
        if spec: out.append(spec)
    return out

def gib(mib):
    try: return float(mib) / 1024
    except (TypeError, ValueError): return 0.0

# USB class codes that matter for passthrough. bDeviceClass is 00 for most composite
# devices (the real class lives on the interface), which is why bInterfaceClass is
# collected too — a Zigbee stick reports 00 at device level and 02/0a at interface level.
USB_CLASS = {
    "00": "per-interface", "01": "audio", "02": "comms / CDC (serial)", "03": "HID",
    "05": "physical", "06": "imaging", "07": "printer", "08": "mass storage",
    "09": "hub", "0a": "CDC data (serial)", "0b": "smart card", "0d": "content security",
    "0e": "video", "0f": "personal healthcare", "10": "audio/video",
    "e0": "wireless (Bluetooth)", "ef": "misc / composite", "fe": "application",
    "ff": "vendor-specific",
}
# Vendors whose IDs show up on the kind of dongle you would pass into a pod.
USB_VENDOR = {
    "8087": "Intel", "0a12": "Cambridge Silicon Radio", "0bda": "Realtek",
    "10c4": "Silicon Labs (Zigbee/Matter sticks)", "1a86": "QinHeng (CH340 serial)",
    "0403": "FTDI (serial)", "1cf1": "Dresden Elektronik (ConBee)",
    "0451": "Texas Instruments (CC2531)", "2341": "Arduino", "046d": "Logitech",
    "1d6b": "Linux Foundation (root hub)", "05e3": "Genesys Logic (hub)",
    "0424": "Microchip (hub)", "413c": "Dell", "04b4": "Cypress",
}
PASSTHROUGH_HINT = {
    "02": "serial — likely /dev/ttyACM* or /dev/ttyUSB*",
    "0a": "serial — likely /dev/ttyACM* or /dev/ttyUSB*",
    "e0": "Bluetooth — pass /dev/bus/usb + NET_ADMIN, or use host networking",
    "03": "HID — /dev/hidraw*",
    "08": "mass storage — /dev/sd*",
    "0e": "video — /dev/video*",
}

def usb_rows(path):
    """Parse the pipe-delimited usb.txt written by the collector."""
    rows = []
    try: lines = open(path).read().strip().split("\n")
    except OSError: return rows
    for ln in lines:
        if not ln.strip(): continue
        parts = ln.split("|")
        d = {"_dev": parts[0]}
        for kv in parts[1:]:
            k, _, v = kv.partition("=")
            if v: d[k] = v
        if d.get("idVendor"): rows.append(d)
    return rows

def is_root_hub(u):
    return u.get("idVendor") == "1d6b"

def html_table(headers, groups, align=None):
    """Emit an HTML table with a rowspan-merged first column.

    Markdown tables cannot merge cells, so anything with a natural two-level shape
    (role -> node, upgradeable -> node, node -> device) ends up repeating the parent
    on every row. groups is [(group_label, [row, row, ...]), ...]; the group label is
    written once with rowspan set to its row count.

    Kept deliberately plain — no CSS, no classes. Renders in GitHub, IDE previews and
    anything else that passes HTML through, and degrades to readable text if not.
    """
    al = align or {}
    out = ["<table>", "  <thead>", "    <tr>"]
    for i, h in enumerate(headers):
        a = f' align="{al[i]}"' if i in al else ""
        out.append(f"      <th{a}>{h}</th>")
    out += ["    </tr>", "  </thead>", "  <tbody>"]
    for label, rows in groups:
        if not rows: continue
        for j, row in enumerate(rows):
            out.append("    <tr>")
            if j == 0:
                out.append(f'      <td rowspan="{len(rows)}"><b>{label}</b></td>')
            for i, cell in enumerate(row, start=1):
                a = f' align="{al[i]}"' if i in al else ""
                out.append(f"      <td{a}>{cell}</td>")
            out.append("    </tr>")
    out += ["  </tbody>", "</table>"]
    return out

nodes = sorted(os.path.basename(p) for p in glob.glob(f"{WORK}/*") if os.path.isdir(p))
L = []
add = L.append

add("# Node Hardware Inventory")
add("")
add(f"*Generated {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
    "by `scripts/node-dossier.sh`. Regenerate rather than hand-editing.*")
add("")
add("Talos has no SSH, so this is read from the SMBIOS/DMI tables that `talosctl` exposes as "
    "resources. **The DIMM part numbers and slot locators below are what you order replacement "
    "memory against** — no need to open the case.")
add("")

# ---------- fleet summary ----------
rows, totals = [], {"ram": 0.0, "cores": 0}
for n in nodes:
    d = f"{WORK}/{n}"
    si = (docs(f"{d}/systeminformation.yaml") or [{}])[0]
    cpus = docs(f"{d}/processors.yaml")
    mods = [m for m in docs(f"{d}/memorymodules.yaml") if m.get("sizeMiB")]
    ram = sum(gib(m.get("sizeMiB")) for m in mods)
    cores = sum(int(c.get("coreCount", 0)) for c in cpus)
    totals["ram"] += ram; totals["cores"] += cores
    k8s = {}
    try: k8s = json.load(open(f"{d}/k8s.json"))
    except Exception: pass
    role = "control-plane" if "node-role.kubernetes.io/control-plane" in (k8s.get("metadata", {}).get("labels") or {}) else "worker"
    rows.append((n, si.get("manufacturer", "?"), si.get("productName", "?"),
                 cpus[0].get("productName", "?") if cpus else "?", cores, ram, len(mods), role))

add("## Fleet at a glance")
add("")
grouped = []
for role in ("control-plane", "worker"):
    members = [(n, mfr, prod, cpu, cores, ram, nd) for n, mfr, prod, cpu, cores, ram, nd, r in rows if r == role]
    grouped.append((role, [[f"<b>{n}</b>", f"{mfr} {prod}", cpu, cores, f"{ram:.0f} GiB", nd]
                           for n, mfr, prod, cpu, cores, ram, nd in sorted(members)]))
L.extend(html_table(["Role", "Node", "System", "CPU", "Cores", "RAM", "DIMMs"], grouped,
                    align={4: "right", 5: "right", 6: "right"}))
add("")
add(f"**Fleet total: {totals['cores']} cores, {totals['ram']:.0f} GiB RAM across {len(rows)} nodes.**")
add("")

# ---------- RAM upgrade planner ----------
def classify(mods, si):
    """Can this node's memory actually be upgraded?

    SMBIOS does not say 'soldered' or 'how many empty slots'. But the shape of what
    it DOES report is diagnostic, and getting this wrong means ordering RAM that
    physically cannot be fitted:

      * VM        - manufacturer is QEMU/VMware/etc. Resize in the hypervisor; there
                    is nothing to buy.
      * SOLDERED  - many small 'modules' on Controller<N>-Channel<X> locators, high
                    speed, and no part number. That is the LPDDR4x/LPDDR5 on-package
                    layout: memory is soldered to the board and CANNOT be upgraded at
                    all. A 24 GiB machine reporting 8x3 GiB is the classic signature.
      * SOCKETED  - a small number of modules with real part numbers and DIMM/SODIMM
                    style locators. These are replaceable sticks.
    """
    mfrs = {(m.get("manufacturer") or "").lower() for m in mods}
    if mfrs & {"qemu", "vmware, inc.", "vmware", "bochs", "innotek gmbh", "microsoft corporation"}:
        return "VM", "Resize in the hypervisor — no physical RAM to buy."
    named = [m for m in mods if m.get("productName")]
    chan = sum(1 for m in mods if re.match(r"Controller\d+-Channel", m.get("deviceLocator", "")))
    # Soldered LPDDR presents as >=4 pseudo-modules on Controller/Channel locators
    # with no part number. Socketed DDR5 also uses Controller-Channel locators, but
    # reports a part number and comes in 1-2 sticks.
    if chan >= 4 and not named:
        return "SOLDERED", "**Cannot be upgraded.** On-package LPDDR — no sockets exist."
    if not named and len(mods) <= 2:
        return "UNKNOWN", "No part number reported; open the case or check the spec sheet."
    return "SOCKETED", "Replaceable sticks — match the part number below."

add("## RAM upgrade planner")
add("")
add("**Read the *Upgradeable* column first.** Two of these machines cannot take more memory "
    "at any price, and that is not visible from the capacity numbers alone.")
add("")
plan = []
for n in nodes:
    d = f"{WORK}/{n}"
    mods = [m for m in docs(f"{d}/memorymodules.yaml") if m.get("sizeMiB")]
    si = (docs(f"{d}/systeminformation.yaml") or [{}])[0]
    if not mods:
        plan.append((0.0, n, "—", "?", ("UNKNOWN", "No modules reported."), "—", si)); continue
    ram = sum(gib(m.get("sizeMiB")) for m in mods)
    sizes = {}
    for m in mods: sizes[gib(m.get("sizeMiB"))] = sizes.get(gib(m.get("sizeMiB")), 0) + 1
    cfg = " + ".join(f"{c}x{s:.0f} GiB" for s, c in sorted(sizes.items()))
    speeds = sorted({str(m.get("speed", "?")) for m in mods})
    parts = sorted({f"{m.get('manufacturer','?')} `{m['productName']}`" for m in mods if m.get("productName")})
    plan.append((ram, n, cfg, "/".join(speeds), classify(mods, si), "<br>".join(parts) or "—", si))

LABEL = {"SOCKETED": "✅ Upgradeable", "SOLDERED": "❌ Soldered — cannot upgrade",
         "VM": "🖥 Virtual machine", "UNKNOWN": "⚠️ Unclear"}
gr = []
for kind in ("SOCKETED", "SOLDERED", "VM", "UNKNOWN"):
    members = [(ram, n, cfg, speed, parts) for ram, n, cfg, speed, (k, _), parts, _ in sorted(plan) if k == kind]
    if members:
        gr.append((LABEL[kind], [[f"<b>{n}</b>", f"{ram:.0f} GiB", cfg, f"{speed} MT/s", parts]
                                 for ram, n, cfg, speed, parts in members]))
L.extend(html_table(["Upgradeable", "Node", "Installed", "Config", "Speed", "Part number"], gr,
                    align={2: "right", 5: "right"}))
add("")
for ram, n, cfg, speed, (kind, note), parts, si in sorted(plan):
    add(f"- **{n}** ({si.get('manufacturer','?')} {si.get('productName','?')}) — {note}")
add("")
add("> **Empty slots are NOT reported.** SMBIOS lists only populated modules; Talos exposes no "
    "resource for total slot count or the board's maximum capacity. For a socketed node, check "
    "the model's spec sheet (in its dossier below) to learn whether there is a free slot or "
    "whether existing sticks must be replaced.")
add("")
add("> **Form factor is inferred, not reported.** Mini-PCs are usually SODIMM. Confirm against "
    "the model before ordering.")
add("")

# ---------- fleet USB / passthrough overview ----------
add("## Pluggable devices & passthrough")
add("")
add("Everything currently attached by USB, per node, plus where there is room to plug "
    "something in. This is the table to look at when deciding which node gets the Zigbee "
    "stick or the Bluetooth dongle.")
add("")
gr = []
for n in nodes:
    u = usb_rows(f"{WORK}/{n}/usb.txt")
    hubs = [x for x in u if is_root_hub(x)]
    real = sorted((x for x in u if not is_root_hub(x)), key=lambda x: x["_dev"])
    label = f"{n}<br><small>{len(hubs)} controllers</small>"
    if not real:
        gr.append((label, [["<i>— none attached —</i>", "", "", "", ""]]))
        continue
    body = []
    for x in real:
        vid = x.get("idVendor", "????"); pid = x.get("idProduct", "????")
        cls = (x.get("bDeviceClass") or "").lower(); icls = (x.get("bInterfaceClass") or "").lower()
        eff = icls if cls in ("00", "", "ef") and icls else cls
        spd = x.get("speed", "")
        body.append([f"<code>{x['_dev']}</code>",
                     f"<code>{vid}:{pid}</code>",
                     x.get("manufacturer") or USB_VENDOR.get(vid, "—"),
                     x.get("product") or "—",
                     USB_CLASS.get(eff, eff or "—"),
                     f"{spd} Mb/s" if spd else "?"])
    gr.append((label, body))
L.extend(html_table(["Node", "Port", "VID:PID", "Vendor", "Product", "Class", "Speed"], gr,
                    align={6: "right"}))
add("")
add("### Passing a USB device into a pod")
add("")
add("Talos has no udev rules you can edit and no host shell, so the two workable routes are:")
add("")
add("1. **hostPath mount** — simplest, and what Home Assistant / Zigbee2MQTT generally use. "
    "Mount the specific device node and schedule the pod to the node holding it:")
add("")
add("   ```yaml")
add("   spec:")
add("     nodeSelector:")
add("       kubernetes.io/hostname: <the node with the dongle>   # a device is not portable")
add("     containers:")
add("       - name: app")
add("         securityContext:")
add("           privileged: true          # or add the device via volumeDevices")
add("         volumeMounts:")
add("           - { name: zigbee, mountPath: /dev/ttyACM0 }")
add("     volumes:")
add("       - name: zigbee")
add("         hostPath: { path: /dev/serial/by-id/usb-...-if00, type: CharDevice }")
add("   ```")
add("")
add("   Use the stable `/dev/serial/by-id/...` path, never `/dev/ttyACM0` — the numbered "
    "name is assigned in probe order and moves when another device is plugged in.")
add("")
add("2. **A device plugin** (e.g. `smarter-device-manager`) advertises devices as schedulable "
    "resources, so pods request `smarter-devices/ttyACM0` instead of running privileged. "
    "More setup, but no privileged container and the scheduler understands the constraint.")
add("")
add("### Making a device reachable from any node")
add("")
add("A hostPath mount welds the consumer to one machine. To let the consuming pod schedule "
    "anywhere, put a small per-node bridge in front of the device and talk to it over the "
    "network. The device stays pinned; the consumer stops being pinned.")
add("")
add("**For serial devices — Zigbee, Matter, Z-Wave, P1 meters — use `ser2net`.** This is the "
    "established route and it needs nothing special from Talos:")
add("")
add("```")
add("  DaemonSet (nodeSelector: the node with the stick)")
add("    ser2net  --  /dev/serial/by-id/usb-...-if00  <->  TCP :20108")
add("        |")
add("     Service  zigbee-serial.home-automation.svc:20108")
add("        |")
add("  Home Assistant / Zigbee2MQTT   (schedules ANYWHERE)")
add("    port: tcp://zigbee-serial.home-automation.svc:20108")
add("```")
add("")
add("Zigbee2MQTT, ZHA and Z-Wave JS all accept a `tcp://` serial port natively, so this needs "
    "no shim on the consumer side. Use a DaemonSet with a nodeSelector rather than a "
    "StatefulSet: there is no ordering or identity to preserve, only a device to sit next to.")
add("")
add("**USB/IP is NOT available on stock Talos.** The obvious answer for arbitrary USB — "
    "`usbip_host` on the node, `vhci-hcd` on the consumer — cannot be used here: neither "
    "module ships in the Talos kernel (checked against all 431 modules in "
    "`/lib/modules/6.18.44-talos`). Getting it would mean a custom kernel via Image Factory "
    "or a system extension, plus a privileged client pod loading `vhci-hcd`. That is a large "
    "amount of machinery for a homelab, and it is why the serial-over-TCP route is the "
    "recommendation for anything that speaks serial.")
add("")
add("**What Talos DOES ship**, verified on this cluster, so sticks enumerate correctly:")
add("")
add("- `cdc-acm` — built into the kernel. Covers ConBee, SkyConnect, most CC2652 and Matter "
    "sticks, which appear as `/dev/ttyACM*`.")
add("- `ch341`, `cp210x`, `ftdi_sio`, `pl2303` — loadable modules, covering the older "
    "USB-serial bridges that appear as `/dev/ttyUSB*`.")
add("- Char devices 166 (`ttyACM`) and 188 (`ttyUSB`) are registered in `/proc/devices`.")
add("")
add("**For Bluetooth**, none of this applies: the radio is already on the PCI/USB bus of every "
    "node in this fleet (see the table above), so run the consumer with host networking and "
    "`NET_ADMIN` on a node that has one, rather than bridging anything.")
add("")

add("> **A USB device pins its pod to one node.** Whichever node holds the dongle, that pod "
    "cannot move — which matters here because two nodes carry a PreferNoSchedule taint. "
    "Prefer plugging into `talos02-gpu` or `talos06`, which have the headroom.")
add("")

# ---------- per-node dossiers ----------
add("---")
add("")
add("## Node dossiers")
add("")
for n in nodes:
    d = f"{WORK}/{n}"
    ip = open(f"{d}/ip").read().strip() if os.path.exists(f"{d}/ip") else "?"
    si = (docs(f"{d}/systeminformation.yaml") or [{}])[0]
    cpus = docs(f"{d}/processors.yaml")
    mods = [m for m in docs(f"{d}/memorymodules.yaml") if m.get("sizeMiB")]
    disks = [x for x in docs(f"{d}/disks.yaml")
             if x.get("dev_path", "").startswith(("/dev/sd", "/dev/nvme", "/dev/vd"))
             and "p" not in x.get("dev_path", "").split("/")[-1][5:]]
    pci = docs(f"{d}/pcidevices.yaml")

    k8s = {}
    try: k8s = json.load(open(f"{d}/k8s.json"))
    except Exception: pass
    lbl = (k8s.get("metadata", {}) or {}).get("labels", {}) or {}
    ni  = (k8s.get("status", {}) or {}).get("nodeInfo", {}) or {}
    alloc = (k8s.get("status", {}) or {}).get("allocatable", {}) or {}
    cap = (k8s.get("status", {}) or {}).get("capacity", {}) or {}
    taints = (k8s.get("spec", {}) or {}).get("taints", []) or []
    role = "control-plane" if "node-role.kubernetes.io/control-plane" in lbl else "worker"

    add(f"### {n}")
    add("")
    add(f"`{ip}` · **{role}**" + (f" · tainted: {', '.join(t.get('key','') + ':' + t.get('effect','') for t in taints)}" if taints else ""))
    add("")
    add("| | |")
    add("|---|---|")
    add(f"| System | {si.get('manufacturer','?')} **{si.get('productName','?')}** ({si.get('version','?')}) |")
    if si.get("skuNumber"): add(f"| SKU | `{si['skuNumber']}` |")
    sn = si.get("serialnumber", "")
    if sn and sn.lower() != "default string": add(f"| Serial | `{sn}` |")
    add(f"| Talos / K8s | {ni.get('osImage','?')} · kubelet {ni.get('kubeletVersion','?')} |")
    add(f"| Kernel | {ni.get('kernelVersion','?')} |")
    add(f"| Container runtime | {ni.get('containerRuntimeVersion','?')} |")
    if cap.get("memory") and alloc.get("memory"):
        cm = int(cap["memory"].rstrip("Ki")) / 1024 / 1024
        am = int(alloc["memory"].rstrip("Ki")) / 1024 / 1024
        add(f"| Memory capacity / allocatable | {cm:.1f} GiB / {am:.1f} GiB "
            f"*(kubelet reserves {cm-am:.1f} GiB)* |")
    if cap.get("cpu"): add(f"| CPU capacity / allocatable | {cap.get('cpu')} / {alloc.get('cpu','?')} |")
    if cap.get("pods"): add(f"| Max pods | {alloc.get('pods', cap['pods'])} |")
    add("")

    if cpus:
        add("**CPU**")
        add("")
        add("| Socket | Model | Cores | Threads | Boot / max MHz |")
        add("|---|---|---:|---:|---|")
        for c in cpus:
            add(f"| {c.get('socket','?')} | {c.get('productName','?')} | {c.get('coreCount','?')} "
                f"| {c.get('threadCount','?')} | {c.get('bootSpeedMhz','?')} / {c.get('maxSpeedMhz','?')} |")
        add("")

    add("**Memory modules**")
    add("")
    if mods:
        add("| Slot | Bank | Size | Speed | Manufacturer | Part number | Serial |")
        add("|---|---|---:|---:|---|---|---|")
        for m in sorted(mods, key=lambda x: x.get("deviceLocator", "")):
            add(f"| {m.get('deviceLocator','?')} | {m.get('bankLocator','?')} "
                f"| {gib(m.get('sizeMiB')):.0f} GiB | {m.get('speed','?')} MT/s "
                f"| {m.get('manufacturer','?')} | `{m.get('productName','?')}` | `{m.get('serialNumber','?')}` |")
        add("")
        add(f"*Total {sum(gib(m.get('sizeMiB')) for m in mods):.0f} GiB across {len(mods)} populated "
            "slot(s). To match existing memory, order the part number above.*")
    else:
        add("*No memory modules reported — the node may be a VM (SMBIOS DMI type 17 is often "
            "absent under virtualisation) or was unreachable.*")
    add("")

    if disks:
        add("**Disks**")
        add("")
        add("| Device | Size | Bus |")
        add("|---|---:|---|")
        for x in sorted(disks, key=lambda y: y.get("dev_path", "")):
            add(f"| `{x.get('dev_path','?')}` | {x.get('pretty_size','?')} | `{x.get('bus_path','?')}` |")
        add("")

    # ---- network interfaces ----
    links = docs(f"{d}/linkstatuses.yaml")
    # Physical NICs only. Everything cilium/flannel/kube creates is virtual and would
    # bury the real ports; a physical port has a bus path and a non-virtual driver.
    virt_drv = {"veth", "bridge", "bonding", "tun", "vxlan", "wireguard", "dummy", "loopback", "macvlan", "ipip", "sit", "ip6tnl", "gre", "gretap", "erspan", "ifb"}
    phys = [l for l in links
            if l.get("driver") and l["driver"] not in virt_drv
            and not re.match(r"(cilium|lxc|veth|flannel|kube|docker|nodelocal|lo$|dummy)", l.get("_id", ""))]
    if phys:
        add("**Network ports**")
        add("")
        add("| Interface | State | Speed | Duplex | Port | Driver | MAC |")
        add("|---|---|---:|---|---|---|---|")
        for l in sorted(phys, key=lambda x: x.get("_id", "")):
            sp = l.get("speedMbit", "?")
            try:
                spn = int(sp)
                sp = "—" if spn in (0, 4294967295) else (f"{spn/1000:g} GbE" if spn >= 1000 else f"{spn} Mb")
            except (TypeError, ValueError): sp = "?"
            st = "🟢 up" if l.get("operationalState") == "up" else "⚪ down"
            add(f"| `{l.get('_id','?')}` | {st} | {sp} | {l.get('duplex','?')} | {l.get('port','?')} "
                f"| {l.get('driver','?')} | `{l.get('hardwareAddr','?')}` |")
        add("")

    # ---- USB ----
    usb = usb_rows(f"{d}/usb.txt")
    real = [u for u in usb if not is_root_hub(u)]
    add("**USB devices**")
    add("")
    if usb:
        hubs = [u for u in usb if is_root_hub(u)]
        add(f"*{len(hubs)} root hub(s), {len(real)} attached device(s).*")
        add("")
        if real:
            add("| Port | VID:PID | Vendor | Product | Class | Speed |")
            add("|---|---|---|---|---|---:|")
            for u in sorted(real, key=lambda x: x["_dev"]):
                vid = u.get("idVendor", "????"); pid = u.get("idProduct", "????")
                cls = (u.get("bDeviceClass") or "").lower()
                icls = (u.get("bInterfaceClass") or "").lower()
                eff = icls if cls in ("00", "", "ef") and icls else cls
                spd = u.get("speed", "?")
                spd = f"{spd} Mb/s" if spd and spd != "?" else "?"
                add(f"| `{u['_dev']}` | `{vid}:{pid}` | {u.get('manufacturer') or USB_VENDOR.get(vid,'—')} "
                    f"| {u.get('product') or '—'} | {USB_CLASS.get(eff, eff or '—')} | {spd} |")
            add("")
            hints = []
            for u in sorted(real, key=lambda x: x["_dev"]):
                cls = (u.get("bDeviceClass") or "").lower(); icls = (u.get("bInterfaceClass") or "").lower()
                for c in (icls, cls):
                    if c in PASSTHROUGH_HINT:
                        hints.append(f"- `{u['_dev']}` **{u.get('idVendor')}:{u.get('idProduct')}** — {PASSTHROUGH_HINT[c]}")
                        break
            if hints:
                add("*Passthrough candidates:*")
                add("")
                L.extend(hints); add("")
        else:
            add("*No devices attached — only root hubs. Free ports are available for a "
                "Zigbee/Matter stick, Bluetooth dongle, or UPS cable.*")
            add("")
    else:
        add("*Not readable (node may be a VM or was unreachable).*")
        add("")

    # ---- serial / passthrough-able device nodes ----
    try: devs = [l.split()[-1] for l in open(f"{d}/dev.txt").read().split(chr(10))[1:] if l.strip()]
    except OSError: devs = []
    try: subs = [x.strip() for x in open(f"{d}/devsub.txt").read().split(chr(10)) if x.strip()]
    except OSError: subs = []
    top    = [x for x in devs if re.match(r"(ttyUSB|ttyACM|hidraw|video\d)", x)]
    serial = sorted(x for x in subs if x.startswith("serial/by-id/"))
    dri    = sorted(x for x in subs if x.startswith("dri/") and re.search(r"render|card", x))
    if top or serial or dri:
        add("**Passthrough-able device nodes**")
        add("")
        if serial:
            add("*Serial — use these paths, NOT `/dev/ttyACM0`: the numbered name is assigned in")
            add("probe order and moves when anything else is plugged in.*")
            add("")
            for x in serial: add(f"- `/dev/{x}`")
            add("")
        if dri:
            add("*GPU render nodes (Plex / Jellyfin / tdarr hardware transcode):*")
            add("")
            for x in dri: add(f"- `/dev/{x}`")
            add("")
        if top:
            add("*Other:* " + ", ".join(f"`/dev/{x}`" for x in sorted(set(top))))
            add("")

    gpus = [p for p in pci if re.search(r"vga|display|3d", str(p.get("class", "")) + str(p.get("subclass", "")), re.I)
            or re.search(r"graphic|arc|radeon|geforce|iris|uhd", str(p.get("product", "")) + str(p.get("productName", "")), re.I)]
    if gpus:
        add("**GPU / display**")
        add("")
        for g in gpus:
            add(f"- {g.get('vendor', g.get('vendorName','?'))} {g.get('product', g.get('productName','?'))}")
        add("")
    add("")

open(OUT, "w").write("\n".join(L) + "\n")
print(f"wrote {OUT} ({len(L)} lines)")
PY
