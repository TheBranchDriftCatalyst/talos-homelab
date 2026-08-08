#!/usr/bin/env bash
# image-version-report.sh — pull the out-of-date container-image report from version-checker
# (the data behind the "App Ops — Image Versions" Grafana dashboard) into a structured
# JSON + Markdown report.
#
# Source: version-checker exposes `version_checker_is_latest_version{namespace,pod,container,
# image,current_version,latest_version}` on :8080/metrics (value 0 = out of date, 1 = latest),
# plus `version_checker_is_latest_kube_version` for the cluster channel. We read that endpoint
# directly (via port-forward) — no Prometheus/Mimir query needed.
#
# Consumed by the `image-update-epic` skill, which turns the JSON into a beads epic + tickets.
#
# Usage:  ./scripts/image-version-report.sh
# Env:    VC_NAMESPACE (monitoring) VC_SERVICE (version-checker) VC_PORT (8080)
#         VC_LOCAL_PORT (18080) OUT_DIR (.output) JSON_OUT / MD_OUT (paths)
set -euo pipefail

VC_NAMESPACE="${VC_NAMESPACE:-monitoring}"
VC_SERVICE="${VC_SERVICE:-version-checker}"
VC_PORT="${VC_PORT:-8080}"
VC_LOCAL_PORT="${VC_LOCAL_PORT:-18080}"
OUT_DIR="${OUT_DIR:-.output}"
JSON_OUT="${JSON_OUT:-$OUT_DIR/image-version-report.json}"
MD_OUT="${MD_OUT:-$OUT_DIR/image-version-report.md}"

mkdir -p "$OUT_DIR"

echo "→ port-forwarding svc/$VC_SERVICE ($VC_NAMESPACE) :$VC_PORT → localhost:$VC_LOCAL_PORT" >&2
kubectl port-forward -n "$VC_NAMESPACE" "svc/$VC_SERVICE" "${VC_LOCAL_PORT}:${VC_PORT}" > /dev/null 2>&1 &
PF_PID=$!
trap 'kill "$PF_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 30); do
  curl -sf "http://localhost:${VC_LOCAL_PORT}/metrics" > /dev/null 2>&1 && break
  sleep 0.5
done

TMP_METRICS="$(mktemp)"
trap 'kill "$PF_PID" 2>/dev/null || true; rm -f "$TMP_METRICS"' EXIT
curl -s "http://localhost:${VC_LOCAL_PORT}/metrics" 2> /dev/null > "$TMP_METRICS"
if ! grep -q 'version_checker_is_latest_version{' "$TMP_METRICS"; then
  echo "ERROR: no version_checker metrics scraped from the endpoint." >&2
  exit 1
fi

# NOTE: the Python program is supplied via the heredoc (stdin), so the metrics are passed
# by FILE PATH (argv[1]) — you cannot also pipe them to stdin here.
python3 - "$TMP_METRICS" "$JSON_OUT" "$MD_OUT" << 'PY'
import sys, re, json, datetime, collections
metrics = open(sys.argv[1]).read()
json_out, md_out = sys.argv[2], sys.argv[3]

label_re = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')
def parse_labels(s): return {k: v for k, v in label_re.findall(s)}

def bump_type(cur, lat):
    def nums(v):
        v = v.lstrip("vV"); out = []
        for p in re.split(r'[.\-+_]', v)[:3]:
            if p.isdigit(): out.append(int(p))
            else: break
        return out
    c, l = nums(cur), nums(lat)
    if not c or not l: return "unknown"
    if l[0] != c[0]: return "major"
    if len(l) > 1 and len(c) > 1 and l[1] != c[1]: return "minor"
    if l != c: return "patch"
    return "patch"

updates = collections.defaultdict(lambda: {"occurrences": []})
total = 0
for line in metrics.splitlines():
    if not line.startswith("version_checker_is_latest_version{"): continue
    m = re.match(r'version_checker_is_latest_version\{(.*)\}\s+(\S+)$', line)
    if not m: continue
    labels, val = parse_labels(m.group(1)), m.group(2).strip()
    total += 1
    if val != "0": continue  # keep only out-of-date
    key = (labels.get("image",""), labels.get("current_version",""), labels.get("latest_version",""))
    u = updates[key]
    u.update(image=labels.get("image",""), current=labels.get("current_version",""), latest=labels.get("latest_version",""))
    u["occurrences"].append({"namespace": labels.get("namespace",""), "pod": labels.get("pod",""), "container": labels.get("container","")})

kube = {}
for line in metrics.splitlines():
    if line.startswith("version_checker_is_latest_kube_version{"):
        labels = parse_labels(line[line.index("{")+1:line.rindex("}")])
        kube = {"current": labels.get("current_version",""), "latest": labels.get("latest_version",""), "channel": labels.get("channel","")}

items = []
for (image, cur, lat), u in updates.items():
    items.append({
        "image": image, "current": cur, "latest": lat, "bump": bump_type(cur, lat),
        "namespaces": sorted({o["namespace"] for o in u["occurrences"]}),
        "pod_count": len(u["occurrences"]), "occurrences": u["occurrences"],
    })
order = {"major": 0, "minor": 1, "patch": 2, "unknown": 3}
items.sort(key=lambda x: (order.get(x["bump"], 3), -x["pod_count"], x["image"]))

out_of_date = sum(i["pod_count"] for i in items)
report = {
    "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    "source": "version-checker (monitoring/version-checker :8080/metrics)",
    "kube_version": kube,
    "summary": {
        "out_of_date_containers": out_of_date, "total_tracked": total,
        "pct_up_to_date": round((total - out_of_date) / total * 100, 1) if total else 0,
        "unique_image_updates": len(items),
        "namespaces_affected": len(sorted({n for i in items for n in i["namespaces"]})),
        "by_bump": dict(collections.Counter(i["bump"] for i in items)),
    },
    "updates": items,
}
with open(json_out, "w") as f: json.dump(report, f, indent=2)

s = report["summary"]; L = [f"# Image Version Report — {report['generated_at']}", ""]
L.append(f"- Out-of-date containers: **{s['out_of_date_containers']}** / {s['total_tracked']} tracked ({s['pct_up_to_date']}% up to date)")
L.append(f"- Unique image updates: **{s['unique_image_updates']}** across {s['namespaces_affected']} namespaces")
L.append(f"- By bump: {s['by_bump']}")
if kube: L.append(f"- Kubernetes: {kube.get('current')} → {kube.get('latest')} (channel: {kube.get('channel')})")
L += ["", "| Image | Current | Latest | Bump | Namespaces | Pods |", "|---|---|---|---|---|---|"]
for i in items:
    L.append(f"| `{i['image']}` | {i['current']} | {i['latest']} | {i['bump']} | {', '.join(i['namespaces'])} | {i['pod_count']} |")
with open(md_out, "w") as f: f.write("\n".join(L) + "\n")
print(f"✓ {json_out} + {md_out}: {s['unique_image_updates']} unique updates ({s['by_bump']}), {out_of_date}/{total} containers out of date.")
PY

echo "→ report written to $JSON_OUT (JSON) and $MD_OUT (Markdown)" >&2
