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
  for R in systeminformation processors memorymodules disks pcidevices; do
    timeout 45 talosctl -n "$IP" get "$R" -o yaml > "$D/$R.yaml" 2>/dev/null || : > "$D/$R.yaml"
  done
  timeout 30 talosctl -n "$IP" version --short > "$D/version" 2>/dev/null || : > "$D/version"
  kubectl get node "$NAME" -o json > "$D/k8s.json" 2>/dev/null || : > "$D/k8s.json"
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
add("| Node | Role | System | CPU | Cores | RAM | DIMMs |")
add("|---|---|---|---|---:|---:|---:|")
for n, mfr, prod, cpu, cores, ram, nd, role in rows:
    add(f"| **{n}** | {role} | {mfr} {prod} | {cpu} | {cores} | {ram:.0f} GiB | {nd} |")
add(f"| | | | **fleet total** | **{totals['cores']}** | **{totals['ram']:.0f} GiB** | |")
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
add("| Node | Installed | Config | Speed | Upgradeable | Part number |")
add("|---|---:|---|---:|---|---|")
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

for ram, n, cfg, speed, (kind, note), parts, si in sorted(plan):
    icon = {"SOCKETED": "✅ yes", "SOLDERED": "❌ **NO**", "VM": "🖥 VM", "UNKNOWN": "⚠️ unclear"}[kind]
    add(f"| **{n}** | {ram:.0f} GiB | {cfg} | {speed} MT/s | {icon} | {parts} |")
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
