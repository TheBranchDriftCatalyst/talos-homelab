#!/usr/bin/env python3
"""Generator for json/workload-ops.json  (TALOS-h8b0).

SOURCE OF TRUTH. Edit this file, re-run it, commit BOTH this and the JSON:

    python3 scripts/gen-workload-ops.py

Why a generator for this one dashboard: the pod->workload owner-join below is
repeated in ~25 targets. Hand-editing that much JSON is how the first version
shipped a `group_left()`-with-`and` parse error in three panels. Defined once
here, a join fix is one line instead of twenty-five.

NOTE ON `scripts/grafana-sync.sh pull`: pull (UI->code) is debugging-only in this
repo, so there is no risk of a UI edit silently diverging from this script. If
that ever changes, this generator must be retired in favour of the JSON.
"""
import json
import pathlib

DS = {"type": "prometheus", "uid": "mimir"}
NS = 'namespace=~"$namespace"'

# ── pod -> workload resolution ────────────────────────────────────────────────
# Three owner naming schemes, kept disjoint by owner_kind so they cannot overlap:
#   ReplicaSet  -> "<workload>-<hash>", hash never contains a dash
#   Job         -> CronJob runs are "<workload>-<unix-ish digits>"; bare Jobs are "<workload>"
#   everything else (StatefulSet / DaemonSet / CNPG Cluster / Node) -> owner_name IS the workload
# PromQL regexes are fully anchored, so workload "manyfold" selects ONLY the
# manyfold Deployment pod -- never manyfold-postgres-* or manyfold-cache-*.
WLF = (
    f'kube_pod_owner{{{NS},owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"}}'
    f' or kube_pod_owner{{{NS},owner_kind="Job",owner_name=~"$workload(-[0-9]{{6,}})?"}}'
    f' or kube_pod_owner{{{NS},owner_kind!~"ReplicaSet|Job",owner_name=~"$workload"}}'
)
# Vector MATH (*) may use group_left(). Set operations (and/or/unless) may NOT --
# group_left() there is a PromQL parse error. Hence two selectors.
SEL = f"* on(namespace,pod) group_left() group by (namespace,pod) ({WLF})"
SEL_AND = f"and on(namespace,pod) group by (namespace,pod) ({WLF})"

TOPK = 20  # per-pod panels are bounded so namespace=All / workload=All stays readable

# Any 1-to-1 vector match on (namespace,pod,container) must collapse each side with
# `max by (...)` first: a container that restarts briefly yields two cAdvisor series
# for the same container under different container ids, and PromQL then aborts the
# whole query with 'found duplicate series for the match group'.

panels: list = []
_id = [0]


def _next_id() -> int:
    _id[0] += 1
    return _id[0]


def thresholds(steps):
    return {"color": {"mode": "thresholds"}, "thresholds": {"mode": "absolute", "steps": steps}}


STAT_OPTS = {
    "colorMode": "background",
    "graphMode": "area",
    "justifyMode": "auto",
    "orientation": "auto",
    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
    "textMode": "auto",
}
TS_OPTS = {
    "legend": {"calcs": ["mean", "max", "lastNotNull"], "displayMode": "table",
               "placement": "right", "showLegend": True},
    "tooltip": {"mode": "multi", "sort": "desc"},
}
TS_CUSTOM = {"drawStyle": "line", "fillOpacity": 8, "lineWidth": 1,
             "showPoints": "never", "spanNulls": True}
TBL_TRANSFORM = [{"id": "organize", "options": {"excludeByName": {"Time": True, "Value": True}}}]

# Dashed, unfilled styling for the request/limit reference lines so they read as
# thresholds rather than as another pod's usage.
def ref_overrides(names):
    return [{
        "matcher": {"id": "byRegexp", "options": n},
        "properties": [
            {"id": "custom.lineStyle", "value": {"dash": [10, 10], "fill": "dash"}},
            {"id": "custom.fillOpacity", "value": 0},
            {"id": "custom.lineWidth", "value": 2},
        ],
    } for n in names]


def panel(title, typ, targets, w, h, x, y, unit=None, desc="", opts=None,
          defaults=None, overrides=None, extra=None):
    tg = []
    for i, t in enumerate(targets):
        expr, legend = t[0], t[1]
        instant = len(t) > 2 and t[2]
        d = {"datasource": DS, "editorMode": "code", "expr": expr,
             "legendFormat": legend, "refId": chr(65 + i)}
        if typ == "table":
            d.update({"format": "table", "instant": True, "range": False})
        elif instant:
            d.update({"instant": True, "range": False})
        else:
            d["range"] = True
        tg.append(d)
    dflt = {"custom": {}}
    if unit:
        dflt["unit"] = unit
    if defaults:
        dflt.update(defaults)
    p = {"datasource": DS, "id": _next_id(), "title": title, "type": typ,
         "description": desc, "gridPos": {"h": h, "w": w, "x": x, "y": y},
         "targets": tg,
         "fieldConfig": {"defaults": dflt, "overrides": overrides or []}}
    if opts:
        p["options"] = opts
    if extra:
        p.update(extra)
    panels.append(p)


def row(title, y):
    panels.append({"collapsed": False, "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
                   "id": _next_id(), "panels": [], "title": title, "type": "row"})


def stat_opts(calc="lastNotNull"):
    o = json.loads(json.dumps(STAT_OPTS))
    o["reduceOptions"]["calcs"] = [calc]
    return o


# ══ Overview ══════════════════════════════════════════════════════════════════
row("Overview — is this workload healthy right now?", 0)

# `or vector(0)` is used ONLY where the series provably exists whenever the pod
# does. Elsewhere it would turn "kube-state-metrics stopped scraping" into a
# confident red "0", so those panels use noValue instead.
panel("Pods Running", "stat",
      [(f'count(group by (namespace,pod) ({WLF}) and on(namespace,pod) group by (namespace,pod) '
        f'(kube_pod_status_phase{{{NS},phase="Running"}} == 1))', "running", True)],
      3, 4, 0, 1, unit="short",
      desc="Pods of the selected workload in phase=Running. Shows '—' rather than 0 when the "
           "metric is absent, so a kube-state-metrics outage is not misread as an outage of "
           "your workload.",
      opts=stat_opts(),
      defaults={"decimals": 0, "noValue": "—",
                **thresholds([{"color": "red", "value": None}, {"color": "green", "value": 1}])})

panel("Pods NOT Running", "stat",
      [(f'count(group by (namespace,pod) ({WLF}) and on(namespace,pod) group by (namespace,pod) '
        f'(kube_pod_status_phase{{{NS},phase!="Running",phase!="Succeeded"}} == 1))', "not running", True)],
      3, 4, 3, 1, unit="short",
      desc="Pending / Failed / Unknown. NOTE: this cluster's kube-state-metrics does not expose "
           "kube_pod_status_unschedulable, and kube_pod_status_reason returns no series, so the "
           "REASON a pod is Pending cannot be shown here — use `kubectl describe pod`.",
      opts=stat_opts(),
      defaults={"decimals": 0, "noValue": "—",
                **thresholds([{"color": "green", "value": None}, {"color": "red", "value": 1}])})

panel("Containers Not Ready", "stat",
      [(f'count(kube_pod_container_status_ready{{{NS}}} == 0 {SEL_AND})', "not ready", True)],
      3, 4, 6, 1, unit="short",
      desc="Counts CONTAINERS, not pods (kube_pod_container_status_ready). The pod-level metric "
           "would score a 4-container pod with 3 broken containers as just 1. A not-ready "
           "container means the pod is out of Service rotation.",
      opts=stat_opts(),
      defaults={"decimals": 0, "noValue": "—",
                **thresholds([{"color": "green", "value": None}, {"color": "red", "value": 1}])})

# max_over_time - min_over_time over the DASHBOARD window: no extrapolation, so
# counts are whole restarts. increase() would report 3 restarts as ~13.
panel("Restarts (window)", "stat",
      [(f'clamp_min(sum((max_over_time(kube_pod_container_status_restarts_total{{{NS}}}[$__range]) '
        f'- min_over_time(kube_pod_container_status_restarts_total{{{NS}}}[$__range])) {SEL}), 0) '
        f'or vector(0)', "restarts", True)],
      3, 4, 9, 1, unit="short",
      desc="Restarts across the CURRENTLY SELECTED time range (not a fixed 1h), so it always "
           "agrees with the 'Restarts over time' graph below. Uses max_over_time-min_over_time "
           "rather than increase(), which extrapolates and reports fractional restarts. "
           "clamp_min absorbs the counter reset when a pod is replaced.",
      opts=stat_opts(),
      defaults={"decimals": 0,
                **thresholds([{"color": "green", "value": None}, {"color": "yellow", "value": 1},
                              {"color": "red", "value": 5}])})

# reducer=max: these are PEAK panels. With lastNotNull they rendered the latest
# instant instead (whisparr read 22% when its true peak was 45%), so the
# thresholds below could never fire.
panel("Peak CPU Throttling (window)", "stat",
      [(f'max(100 * sum by (namespace,pod) (rate(container_cpu_cfs_throttled_periods_total{{{NS},container!=""}}[$__rate_interval]) {SEL}) '
        f'/ sum by (namespace,pod) (rate(container_cpu_cfs_periods_total{{{NS},container!=""}}[$__rate_interval]) {SEL}))', "throttled %")],
      3, 4, 12, 1, unit="percent",
      desc="Worst throttling reached during the selected window. A throttled container is "
           "hard-stalled for the remainder of each 100ms CFS period, so latency and probe "
           "timeouts spike while AVERAGE cpu still looks low. Shows 'no limit' when the workload "
           "has no CPU limit — there is then nothing to throttle against, which is NOT the same "
           "as 0% throttling.",
      opts=stat_opts("max"),
      defaults={"decimals": 1, "noValue": "no limit",
                **thresholds([{"color": "green", "value": None}, {"color": "yellow", "value": 25},
                              {"color": "red", "value": 50}])})

# Per-CONTAINER ratio. Summing working-set over all containers and dividing by
# the sum of only the LIMITED containers' limits inflated immich by 58%.
panel("Peak Memory vs Limit (window)", "stat",
      [(f'max(100 * max by (namespace,pod,container) (container_memory_working_set_bytes{{{NS},container!=""}}) '
        f'/ on(namespace,pod,container) max by (namespace,pod,container) (kube_pod_container_resource_limits{{{NS},resource="memory"}}) {SEL})', "% of limit")],
      3, 4, 15, 1, unit="percent",
      desc="Highest any single CONTAINER got to its own memory limit during the window. Computed "
           "per-container: dividing whole-pod usage by only the limited containers' limits "
           "overstates it badly on mixed pods. Memory is incompressible — crossing 100% is an "
           "OOMKill, not a slowdown. 'no limit' means unbounded (it can pressure the NODE instead).",
      opts=stat_opts("max"),
      defaults={"decimals": 1, "noValue": "no limit",
                **thresholds([{"color": "green", "value": None}, {"color": "yellow", "value": 80},
                              {"color": "red", "value": 95}])})

panel("OOM Kills (24h)", "stat",
      [(f'sum(increase(container_oom_events_total{{{NS},container!=""}}[24h]) {SEL}) or vector(0)', "oom kills", True)],
      3, 4, 18, 1, unit="short",
      desc="Real OOM kill events from cAdvisor — the only way to tell a genuine memory kill from "
           "a liveness-probe restart, which look identical in restart counts. container!='' "
           "avoids double-counting the pod-level cgroup, which also receives OOM events on cgroup v2.",
      opts=stat_opts(),
      defaults={"decimals": 0,
                **thresholds([{"color": "green", "value": None}, {"color": "red", "value": 1}])})

# Replaces the old "Pods Ready", which had no denominator: 1/1 and 1/3 looked identical.
panel("Replica Availability", "stat",
      [(f'100 * ( (sum(kube_deployment_status_replicas_ready{{{NS},deployment=~"$workload"}}) '
        f'or sum(kube_statefulset_status_replicas_ready{{{NS},statefulset=~"$workload"}})) '
        f'/ (sum(kube_deployment_spec_replicas{{{NS},deployment=~"$workload"}}) '
        f'or sum(kube_statefulset_replicas{{{NS},statefulset=~"$workload"}})) )', "ready %", True)],
      3, 4, 21, 1, unit="percent",
      desc="ready / desired replicas. Anything under 100% means the workload is degraded even if "
           "the surviving pods look healthy — the pod-count tiles alone cannot tell 1-of-1 from "
           "1-of-3. Blank for DaemonSets and CNPG Clusters, which report neither metric.",
      opts=stat_opts(),
      defaults={"decimals": 0, "noValue": "n/a",
                **thresholds([{"color": "red", "value": None}, {"color": "yellow", "value": 60},
                              {"color": "green", "value": 100}])})

# ══ CPU ═══════════════════════════════════════════════════════════════════════
row("CPU", 5)

panel("CPU usage per container (cores)", "timeseries",
      [(f'topk({TOPK}, sum by (namespace,pod,container) (rate(container_cpu_usage_seconds_total{{{NS},container!=""}}[$__rate_interval]) {SEL}))',
        "{{pod}}/{{container}}"),
       (f'sum by (namespace,pod) (kube_pod_container_resource_requests{{{NS},resource="cpu"}} {SEL})', "{{pod}} request"),
       (f'sum by (namespace,pod) (kube_pod_container_resource_limits{{{NS},resource="cpu"}} {SEL})', "{{pod}} limit")],
      12, 8, 0, 6, unit="short",
      desc=f"Per-CONTAINER usage against that POD's own request/limit (dashed). Both reference "
           f"lines are per-pod on purpose: a workload-wide total would sit N times too high with "
           f"N replicas and invite exactly the wrong conclusion. Usage riding the dashed limit "
           f"while throttling climbs = the limit is the bottleneck. Top {TOPK} series only.",
      opts=TS_OPTS, defaults={"custom": TS_CUSTOM},
      overrides=ref_overrides([".*request$", ".*limit$"]))

panel("CPU throttling % per pod", "timeseries",
      [(f'topk({TOPK}, 100 * sum by (namespace,pod) (rate(container_cpu_cfs_throttled_periods_total{{{NS},container!=""}}[$__rate_interval]) {SEL}) '
        f'/ sum by (namespace,pod) (rate(container_cpu_cfs_periods_total{{{NS},container!=""}}[$__rate_interval]) {SEL}))', "{{pod}}")],
      12, 8, 12, 6, unit="percent",
      desc="THE panel for 'it is slow but the CPU graph looks fine'. Throttling stalls the "
           "container outright for the rest of each 100ms period, so p95 latency and probe "
           "timeouts spike while mean CPU stays low. EMPTY means no CPU limit is set — nothing to "
           "throttle against, not zero throttling.",
      opts=TS_OPTS, defaults={"custom": {**TS_CUSTOM, "fillOpacity": 15}, "max": 100, "min": 0})

# ══ Memory ════════════════════════════════════════════════════════════════════
row("Memory", 14)

panel("Memory working set per container", "timeseries",
      [(f'topk({TOPK}, sum by (namespace,pod,container) (container_memory_working_set_bytes{{{NS},container!=""}} {SEL}))',
        "{{pod}}/{{container}}"),
       (f'sum by (namespace,pod) (kube_pod_container_resource_requests{{{NS},resource="memory"}} {SEL})', "{{pod}} request"),
       (f'sum by (namespace,pod) (kube_pod_container_resource_limits{{{NS},resource="memory"}} {SEL})', "{{pod}} limit")],
      12, 8, 0, 15, unit="bytes",
      desc="Working set is what the kernel counts against the limit (RSS + active page cache) — "
           "this is the number that triggers an OOMKill, not RSS. Split per container so an "
           "unbounded sidecar cannot hide inside a pod total. Reference lines are per-pod.",
      opts=TS_OPTS, defaults={"custom": TS_CUSTOM},
      overrides=ref_overrides([".*request$", ".*limit$"]))

panel("Memory % of limit per container", "timeseries",
      [(f'topk({TOPK}, 100 * max by (namespace,pod,container) (container_memory_working_set_bytes{{{NS},container!=""}}) '
        f'/ on(namespace,pod,container) max by (namespace,pod,container) (kube_pod_container_resource_limits{{{NS},resource="memory"}}) {SEL})',
        "{{pod}}/{{container}}")],
      12, 8, 12, 15, unit="percent",
      desc="Headroom before an OOMKill, per container against its OWN limit. Containers with no "
           "memory limit are ABSENT here by design — they cannot be OOMKilled on their own "
           "account, but they can drive the node into eviction, so check the working-set panel "
           "for them too.",
      opts=TS_OPTS, defaults={"custom": {**TS_CUSTOM, "fillOpacity": 15}, "min": 0})

panel("Memory composition — RSS vs page cache", "timeseries",
      [(f'topk({TOPK}, sum by (namespace,pod,container) (container_memory_rss{{{NS},container!=""}} {SEL}))', "{{pod}}/{{container}} rss"),
       (f'topk({TOPK}, sum by (namespace,pod,container) (container_memory_cache{{{NS},container!=""}} {SEL}))', "{{pod}}/{{container}} cache")],
      24, 7, 0, 23, unit="bytes",
      desc="The immediate follow-up when 'Memory % of limit' goes yellow: is it a real leak or "
           "just reclaimable page cache? Rising RSS is a leak. Rising cache with flat RSS is "
           "usually benign — the kernel reclaims it under pressure — but it still counts toward "
           "the working set and can still trigger an OOMKill.",
      opts=TS_OPTS, defaults={"custom": TS_CUSTOM})

# ══ Restarts & failure modes ══════════════════════════════════════════════════
row("Restarts & failure modes", 30)

# No "interval" override here: $__interval must equal the step, otherwise the
# windows overlap and one restart is drawn as two fractional bars.
panel("Restarts over time", "timeseries",
      [(f'clamp_min(sum by (namespace,pod,container) ((max_over_time(kube_pod_container_status_restarts_total{{{NS}}}[$__interval]) '
        f'- min_over_time(kube_pod_container_status_restarts_total{{{NS}}}[$__interval])) {SEL}), 0)',
        "{{pod}}/{{container}}")],
      12, 7, 0, 31, unit="short",
      desc="WHOLE restart events, per container. Deliberately not increase(), which extrapolates "
           "a single +1 counter step across the window and renders 3 restarts as ~13 fractional "
           "bars. Correlate spikes with the throttling and memory panels to tell a probe-kill "
           "from an OOMKill.",
      opts=TS_OPTS,
      defaults={"custom": {"drawStyle": "bars", "fillOpacity": 70, "lineWidth": 1,
                           "showPoints": "never"}, "decimals": 0})

panel("Last termination reason", "table",
      [(f'sum by (pod, container, reason) (kube_pod_container_status_last_terminated_reason{{{NS}}} {SEL}) > 0', "")],
      6, 7, 12, 31,
      desc="Why each container died last time. OOMKilled = memory. 'Completed' with exit 0 on a "
           "long-running service almost always means a failing liveness probe SIGTERMed it — not "
           "a memory problem. Empty is good: nothing has terminated.",
      extra={"transformations": TBL_TRANSFORM})

panel("Containers waiting (CrashLoopBackOff etc.)", "table",
      [(f'sum by (pod, container, reason) (kube_pod_container_status_waiting_reason{{{NS}}} {SEL}) > 0', "")],
      6, 7, 18, 31,
      desc="Containers stuck waiting and why — CrashLoopBackOff, ImagePullBackOff, "
           "CreateContainerConfigError. Empty is the healthy state.",
      extra={"transformations": TBL_TRANSFORM})

# ══ Network ═══════════════════════════════════════════════════════════════════
row("Network", 38)

NET_DESC = ("Pod-interface traffic only (eth0/tun0). hostNetwork pods are EXCLUDED on purpose: "
            "they share the node's netns, so cAdvisor attributes every veth, cilium_* and "
            "physical NIC counter to them — one such pod reported 2.9x the node's actual "
            "ingress, and an unfiltered leaderboard is just three unrelated pods reporting the "
            "same node. Use a node dashboard for host-level traffic.")

panel("Network receive per pod", "timeseries",
      [(f'topk({TOPK}, sum by (namespace,pod) (rate(container_network_receive_bytes_total{{{NS},interface=~"eth0|tun0"}}[$__rate_interval]) {SEL}))', "{{pod}}")],
      12, 7, 0, 39, unit="Bps", desc=NET_DESC, opts=TS_OPTS, defaults={"custom": TS_CUSTOM})

panel("Network transmit per pod", "timeseries",
      [(f'topk({TOPK}, sum by (namespace,pod) (rate(container_network_transmit_bytes_total{{{NS},interface=~"eth0|tun0"}}[$__rate_interval]) {SEL}))', "{{pod}}")],
      12, 7, 12, 39, unit="Bps", desc=NET_DESC, opts=TS_OPTS, defaults={"custom": TS_CUSTOM})

# ══ Inventory ═════════════════════════════════════════════════════════════════
row("Inventory", 46)

panel("Pods in selection — node, QoS, age", "table",
      [(f'(time() - kube_pod_start_time{{{NS}}}) '
        f'* on(namespace,pod) group_left(node, qos_class) '
        f'(kube_pod_info{{{NS}}} * on(namespace,pod) group_left(qos_class) (kube_pod_status_qos_class{{{NS}}} == 1)) '
        f'{SEL}', "")],
      24, 8, 0, 47, unit="s",
      desc="Every pod the current filter resolves to. Value = pod AGE, which separates 'restarted "
           "3 minutes ago' from 'up 40 days'. QoS matters under node pressure: BestEffort is "
           "evicted first, Guaranteed last. Also the quickest way to confirm the filter is "
           "selecting what you expect.",
      extra={"transformations": [{"id": "organize", "options": {"excludeByName": {"Time": True}}}]})

# ── minimum interval on every $__rate_interval panel ─────────────────────────
# cAdvisor scrapes every 60s here (measured). Grafana's datasource assumes
# shorter, so at wide ranges $__rate_interval collapses to ~60s -- ONE sample per
# window -- and rate() needs TWO, which silently renders "No data" at 24h while
# working at 1h. Deliberately NOT applied to $__interval panels: there it would
# desync the window from the step and double-draw bars.
for _p in panels:
    if any("$__rate_interval" in t.get("expr", "") for t in _p.get("targets", [])):
        _p["interval"] = "2m"

WL_Q = (
    'query_result(group by (workload) ('
    f'label_replace(kube_pod_owner{{{NS},owner_kind="ReplicaSet"}},"workload","$1","owner_name","(.+)-[^-]+$")'
    f' or label_replace(kube_pod_owner{{{NS},owner_kind="Job"}},"workload","$1","owner_name","(.+?)(?:-[0-9]{{6,}})?$")'
    f' or label_replace(kube_pod_owner{{{NS},owner_kind!~"ReplicaSet|Job"}},"workload","$1","owner_name","(.+)")'
    '))'
)

dashboard = {
    "annotations": {"list": []},
    "description": (
        "Per-workload Kubernetes drill-down: pick a namespace and an app, see how it is actually "
        "running. Complements 'Catalyst K8s - Full System Ops' (cluster/node capacity) by "
        "answering the app-level question: is it throttled, is it near its memory limit, why did "
        "it restart. GENERATED by scripts/gen-workload-ops.py -- edit that, not this JSON."
    ),
    "editable": True, "fiscalYearStartMonth": 0, "graphTooltip": 1, "links": [], "liveNow": False,
    "panels": panels, "preload": False, "refresh": "1m", "schemaVersion": 39,
    "tags": ["kubernetes", "workloads", "ops"],
    "templating": {"list": [
        {"current": {"text": "openscad", "value": "openscad"}, "datasource": DS,
         "definition": "label_values(kube_pod_info, namespace)", "includeAll": True, "multi": True,
         "name": "namespace", "label": "Namespace", "options": [],
         "query": {"query": "label_values(kube_pod_info, namespace)", "refId": "ns"},
         "refresh": 2, "sort": 1, "type": "query"},
        # query_result, NOT label_values: Grafana compiles label_values(expr,lbl) into
        # /api/v1/label/<lbl>/values?match[]=expr and match[] accepts only a SERIES
        # SELECTOR, so the label_replace union 400s and the dropdown silently falls
        # back to All. query_result goes through /api/v1/query, which accepts it.
        {"current": {"text": "All", "value": "$__all"}, "datasource": DS,
         "definition": WL_Q, "includeAll": True, "multi": True,
         "name": "workload", "label": "App / Workload", "options": [],
         "query": {"query": WL_Q, "refId": "wl"}, "regex": '/workload="([^"]+)"/',
         "refresh": 2, "sort": 1, "type": "query"},
    ]},
    "time": {"from": "now-6h", "to": "now"}, "timepicker": {}, "timezone": "browser",
    "title": "Workload Ops - Namespace & App Drill-down",
    "uid": "workload-ops", "version": 1, "weekStart": "",
}

out = pathlib.Path(__file__).resolve().parent.parent / "json" / "workload-ops.json"
out.write_text(json.dumps(dashboard, indent=2) + "\n")
print(f"wrote {out}")
print(f"  panels={len([p for p in panels if p['type'] != 'row'])} rows={len([p for p in panels if p['type'] == 'row'])}")
