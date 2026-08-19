# Grafana Dashboard Query Audit

Generated: 2026-08-19T01:42:05.870709+00:00

This is the canonical verification checklist for every live `GrafanaDashboard` CRD and dashboard query.
Regenerate it with `scripts/audit-grafana-dashboards.py`; `EMPTY` is a review item, not automatically a defect.

## Summary

- Dashboard CRDs: 51
- Live Grafana dashboards: 51
- Queries: 1511
- PASS: 1084
- EMPTY: 416
- FAIL: 4
- REVIEW: 7
- SKIP: 0
- NOT_RUN: 0

## Audit findings and remediation queue

This section compares backend results with the live Kubernetes state observed during the audit. The detailed query checklist below is the evidence ledger.

| Check | Priority | Dashboard / scope | Finding | Evidence and recommended action |
|---|---|---|---|---|
| [ ] | P0 | Alerts & Thresholds — Active Alerts | Invalid PromQL compares a sample value to the string `"on_peak"`. | Mimir returns HTTP 400. Model `on_peak` as a label selector or compare the metric to a numeric value. |
| [ ] | P0 | Alerts & Thresholds — Anomaly Count | Invalid range selector on an expression. | Mimir returns HTTP 400 for `count_over_time((... == 1)[$__range])`; use subquery syntax such as `[$__range:]` or redesign the over-time expression. |
| [ ] | P0 | Alerts & Thresholds — Last Alert Time | Invalid vector/scalar composition in the over-time/timestamp expression. | Mimir returns HTTP 400. Rework the expression into valid instant/range-vector stages and validate it independently before restoring the fallback. |
| [ ] | P0 | Battery Sizing — Battery State of Charge | `clamp_max` receives a scalar expression. | Mimir returns HTTP 400 because `clamp_max` requires an instant vector; wrap the scalar in `vector(...)` or avoid the vector function. |
| [x] | P1 | Dagster Pipelines | Expected idle state: all three Dagster Deployments are deliberately paused at `spec.replicas=0`, so all 61 queries are empty and no `dagster_*` series exist. | Keep the dashboard and retest when Dagster is resumed; no query defect is established while its tracked workloads are scaled down. |
| [ ] | P1 | KubeVirt Control Plane | 41 queries are empty; the dashboard's selected instance resolves to stale `192.168.216.11:10250`. | Current nodes are on `192.168.1.0/24`. Replace the hardcoded/default instance selection with live label discovery. |
| [x] | P1 | Ping Exporter | Confirmed unmanaged Grafana database remnant: no dashboard CR/source, no ping-exporter workload, and no `ping_*` series exist. | Backed up and removed the stale dashboard from Grafana; no GitOps resource existed to remove. |
| [x] | P1 | Cilium Flows — Hubble Observer | Retired Grafana.com import 23862 because it requires a `hubble-observer` log container; this cluster runs Hubble relay/UI and native Hubble metrics instead. | Removed its declarative CR. The custom Network Ops dashboard remains the supported Cilium/Hubble view and returns live data. |
| [x] | P1 | CloudNativePG Databases | False positive fixed in the auditor: `$cluster` embedded in a pod regex was replaced as a scalar, corrupting otherwise valid queries. | Corrected matcher-aware substitution. Ten CNPG clusters are healthy, `cnpg_collector_up` exposes 25 live instances, and the corrected representative query returns all 25. |
| [x] | P1 | KEDA Autoscaling — HPA panels | Fixed: HPA discovery now joins `kube_horizontalpodautoscaler_info` scale targets to KEDA `scaledObject`/`exported_namespace` labels instead of assuming `keda-hpa-.*`. | Live validation returns both `boomtime/keda-hpa-boomtime-worker` and custom-named `openscad/manyfold-performance-worker`; current/desired/min/max values are populated for both. |
| [ ] | P2 | KubeVirt VM Info / VM Ops | 58 combined queries are empty and there are currently no VMIs. | Empty inventory/workload panels are expected today; verify that control-plane-only panels remain useful and retest when a VMI exists. |
| [ ] | P2 | Empty-result corpus | 416 queries executed successfully with no six-hour result. | Work through the per-dashboard review queue below. Event/error panels may be healthy when empty; capacity, inventory, and availability panels generally should not be. |
| [ ] | P2 | Grafana template helpers | Seven `label_values`/Grafana helper queries require UI-side verification. | Backend APIs cannot execute Grafana helper syntax directly; verify dropdown population in Grafana after the query defects above are fixed. |

Audit guarantees:

- All 51 live `GrafanaDashboard` CRDs report `DashboardSynchronized=True`.
- All 51 rendered dashboards were fetched from the live Grafana API, including Grafana.com imports and application-owned dashboards.
- Every one of the 1,511 discovered panel and query-variable expressions has a stable checklist row below.
- Every PromQL/LogQL expression supported by the auditor was executed against live Mimir/Loki after resolving Grafana macros and dashboard variables.
- `PASS` means backend acceptance plus at least one result; it does not prove the visualization, units, thresholds, or semantic intent are correct.

## Browser/render audit

The Playwright pass used Grafana's canonical catalog URLs over the LAN ingress, a 1920×1080 viewport, disabled animations, a six-hour window, and one full-page screenshot per dashboard.

| Check | Observation | Result |
|---|---|---|
| [x] | Dashboard pages returning HTTP 200 | 51 / 51 |
| [x] | Dashboard title rendered | 51 / 51 |
| [x] | Access-denied / unauthorized pages | 0 |
| [ ] | Pages containing visible `No data` panels | 28 / 51 |
| [ ] | Pages with browser console errors | 1 / 51 (`Alerts & Thresholds`, HTTP 400) |
| [x] | Pages containing visible query-error text after the capture wait | 0 / 51 |

Screenshots and the machine-readable render result are intentionally untracked runtime artifacts at `/tmp/grafana-audit/screenshots/` and `/tmp/grafana-audit/render-results.json`. Eight pages had datasource requests aborted when the deterministic capture window closed; those queries were independently exercised by the backend audit and are not classified as dashboard failures.

## Backend-rejected queries

These are confirmed query defects: the selected backend returned an error after variable substitution.

| Check | Dashboard | Panel | Ref | Query | Backend finding |
|---|---|---|---|---|---|
| [ ] | 🚨 Alerts & Thresholds | 🚨 Anomaly Count (Time Range) | A | `count_over_time((consumption_cost:anomaly{version=~"$version"} == 1)[$__range])` | command failed (1): kubectl -n monitoring exec deploy/grafana-deployment -- wget --timeout=45 -qO- http://mimir-gateway.monitoring.svc/prometheus/api/v1/query?query=count_over_time%28%28consumption_cost%3Aanomaly%7Bversion%3D~%22.%2A%22%7D%20%3D%3D%201%29%5B6h%5D%29 wget: server returned error: HTTP/1.1 400 Bad Request command terminated with exit code 1  |
| [ ] | 🚨 Alerts & Thresholds | 🚨 Active Alerts | A | `(   count(current_consumption:total{version=~"$version"} > $power_alert_threshold) or vector(0) ) + (   count(consumption_cost:total{version=~"$version"} > $cost_alert_threshold) or vector(0) ) + (   count(consumption_cost:anomaly{version=~"$version"} == 1) or vector(0) ) + (   count(rate_class{version=~"$version"} == "on_peak") or vector(0) ) + (   count(state{version=~"$version"} != 1) or vector(0) )` | command failed (1): kubectl -n monitoring exec deploy/grafana-deployment -- wget --timeout=45 -qO- http://mimir-gateway.monitoring.svc/prometheus/api/v1/query?query=%28%0A%20%20count%28current_consumption%3Atotal%7Bversion%3D~%22.%2A%22%7D%20%3E%20500%29%20or%20vector%280%29%0A%29%20%2B%20%28%0A%20%20count%28consumption_cost%3Atotal%7Bversion%3D~%22.%2A%22%7D%20%3E%201.0%29%20or%20vector%280%29%0A%29%20%2B%20%28%0A%20%20count%28consumption_cost%3Aanomaly%7Bversion%3D~%22.%2A%22%7D%20%3D%3D%201%29%20or%20vector%280%29%0A%29%20%2B%20%28%0A%20%20count%28rate_class%7Bversion%3D~%22.%2A%22%7D%20%3D%3D%20%22on_peak%22%29%20or%20vector%280%29%0A%29%20%2B%20%28%0A%20%20count%28state%7Bversion%3D~%22.%2A%22%7D%20%21%3D%201%29%20or%20vector%280%29%0A%29 wget: server returned error: HTTP/1.1 400 Bad Request command terminated with exit code 1  |
| [ ] | 🚨 Alerts & Thresholds | 🔔 Last Alert Time | A | `time() - max(   max_over_time((current_consumption:total{version=~"$version"} > $power_alert_threshold)[1h:]) > bool $power_alert_threshold   * on() group_left() timestamp(current_consumption:total{version=~"$version"}) ) or time() - 86400` | command failed (1): kubectl -n monitoring exec deploy/grafana-deployment -- wget --timeout=45 -qO- http://mimir-gateway.monitoring.svc/prometheus/api/v1/query?query=time%28%29%20-%20max%28%0A%20%20max_over_time%28%28current_consumption%3Atotal%7Bversion%3D~%22.%2A%22%7D%20%3E%20500%29%5B1h%3A%5D%29%20%3E%20bool%20500%0A%20%20%2A%20on%28%29%20group_left%28%29%20timestamp%28current_consumption%3Atotal%7Bversion%3D~%22.%2A%22%7D%29%0A%29%20or%20time%28%29%20-%2086400 wget: server returned error: HTTP/1.1 400 Bad Request command terminated with exit code 1  |
| [ ] | 🔋 Battery Sizing & Analysis | 📈 Battery State of Charge Timeline | B | `clamp_max((($solar_panel_watts * $inverter_efficiency) / ($battery_voltage * $battery_capacity_ah)) * 100 * (time() % 86400) / 3600, 100)` | command failed (1): kubectl -n monitoring exec deploy/grafana-deployment -- wget --timeout=45 -qO- http://mimir-gateway.monitoring.svc/prometheus/api/v1/query?query=clamp_max%28%28%28400%20%2A%200.90%29%20%2F%20%2848%20%2A%20200%29%29%20%2A%20100%20%2A%20%28time%28%29%20%25%2086400%29%20%2F%203600%2C%20100%29 wget: server returned error: HTTP/1.1 400 Bad Request command terminated with exit code 1  |

## Empty-result review queue

These queries are syntactically valid but returned no data in the six-hour audit window. Verify each against intended deployment state.

| Check | Dashboard | Empty queries |
|---|---|---|
| [ ] | Dagster Pipelines - Catalyst Data | 61 |
| [ ] | CloudNativePG Databases | 49 |
| [ ] | KubeVirt / Control Plane | 41 |
| [ ] | KubeVirt VM Ops | 31 |
| [ ] | KubeVirt VM Info | 27 |
| [ ] | boomtime · Domain & Jobs | 25 |
| [ ] | boomtime · Reading monitor (whispersync cadence) | 13 |
| [ ] | boomtime · Service & Infra | 12 |
| [ ] | 🚨 Alerts & Thresholds | 12 |
| [ ] | Ping Exporter | 11 |
| [ ] | Pod Cleanup Job | 10 |
| [ ] | ArgoCD | 9 |
| [ ] | Cilium Flows - Hubble Observer | 9 |
| [ ] | Cowrie Ops | 9 |
| [ ] | Network Ops — Cilium & Hubble | 9 |
| [ ] | VPN Gateway | 9 |
| [ ] | Flux2 | 8 |
| [ ] | Logging Dashboard via Loki v2 | 7 |
| [ ] | Security Ops — CrowdSec | 7 |
| [ ] | 🌊 Real-Time Monitoring | 7 |
| [ ] | Cilium v1.12 Operator Metrics | 6 |
| [ ] | External DNS | 6 |
| [ ] | ArgoCD / Operational / Overview | 5 |
| [ ] | ArgoCD / Application / Overview | 4 |
| [ ] | Central Cluster Storage | 4 |
| [ ] | Analytics Ops | 3 |
| [ ] | Argo Ops | 3 |
| [ ] | SPIRE Health & Mesh-Auth Correlation | 3 |
| [ ] | Workload Ops - Namespace & App Drill-down | 3 |
| [ ] | Cilium BPF Map Pressure | 2 |
| [ ] | Talos Cluster Debug | 2 |
| [ ] | ⚡ TOU Cost Optimization | 2 |
| [ ] | 📊 Comparative Analytics | 2 |
| [ ] | Catalyst K8s — Full System Ops | 1 |
| [ ] | Talos00 Memory Deep-Dive | 1 |
| [ ] | Uptime / SLO | 1 |
| [ ] | Web monitoring | 1 |
| [ ] | 🔮 Forecasting & Predictions | 1 |

## Grafana-helper review queue

These template helpers are evaluated by Grafana rather than directly by Prometheus/Loki and require a UI/API-variable check.

| Check | Dashboard | Variable | Query | Finding |
|---|---|---|---|---|
| [ ] | Logging Dashboard via Loki v2 | Variable: container | `label_values({container=~".+"}, container)` | Loki variable helper requires Grafana UI evaluation |
| [ ] | Logging Dashboard via Loki v2 | Variable: pod | `label_values({container="$container"}, pod)` | Loki variable helper requires Grafana UI evaluation |
| [ ] | Logging Dashboard via Loki v2 | Variable: stream | `label_values({container="$container"}, stream)` | Loki variable helper requires Grafana UI evaluation |
| [ ] | ArgoCD / Application / Overview | Variable: job | `label_values(job)` | Grafana variable helper requires UI evaluation |
| [ ] | ArgoCD / Operational / Overview | Variable: job | `label_values(job)` | Grafana variable helper requires UI evaluation |
| [ ] | 🔋 Battery Sizing & Analysis | Variable: version | `label_values(version)` | Grafana variable helper requires UI evaluation |
| [ ] | 🔋 Battery Sizing & Analysis | Variable: device | `label_values(alias)` | Grafana variable helper requires UI evaluation |

## CRD reconciliation checklist

| Check | Namespace | CRD | Source | Synchronized |
|---|---|---|---|---|
| [x] | boomtime | boomtime-domain-jobs | {'key': 'domain-jobs-dashboard.json', 'name': 'dashboard-boomtime-domain-jobs'} | True |
| [x] | boomtime | boomtime-reading-monitor | {'key': 'reading-monitor-dashboard.json', 'name': 'dashboard-boomtime-reading-monitor'} | True |
| [x] | boomtime | boomtime-service-infra | {'key': 'service-infra-dashboard.json', 'name': 'dashboard-boomtime-service-infra'} | True |
| [x] | catalyst-data | dagster-pipelines | inline | True |
| [x] | monitoring | analytics-ops | {'key': 'analytics-ops.json', 'name': 'dashboard-analytics-ops'} | True |
| [x] | monitoring | app-ops-image-versions | {'key': 'app-ops-image-versions.json', 'name': 'dashboard-app-ops-image-versions'} | True |
| [x] | monitoring | argo-ops | {'key': 'argo-ops.json', 'name': 'dashboard-argo-ops'} | True |
| [x] | monitoring | argocd-applications | grafana.com/19974 | True |
| [x] | monitoring | argocd-operational | grafana.com/19993 | True |
| [x] | monitoring | argocd-overview | grafana.com/14584 | True |
| [x] | monitoring | catalyst-k8s-dashboard | {'key': 'catalyst-k8s-dashboard.json', 'name': 'dashboard-catalyst-k8s-dashboard'} | True |
| [x] | monitoring | central-cluster-storage | {'key': 'central-cluster-storage.json', 'name': 'dashboard-central-cluster-storage'} | True |
| [x] | monitoring | cilium-bpf-pressure | {'key': 'cilium-bpf-pressure.json', 'name': 'dashboard-cilium-bpf-pressure'} | True |
| [x] | monitoring | cilium-hubble-flows | grafana.com/23862 | True |
| [x] | monitoring | cilium-operator | grafana.com/16612 | True |
| [x] | monitoring | cnpg-databases | {'key': 'cnpg-databases.json', 'name': 'dashboard-cnpg-databases'} | True |
| [x] | monitoring | cowrie-ops | {'key': 'cowrie-ops.json', 'name': 'dashboard-cowrie-ops'} | True |
| [x] | monitoring | crowdsec-ops | {'key': 'crowdsec-ops.json', 'name': 'dashboard-crowdsec-ops'} | True |
| [x] | monitoring | dragonfly-cache | {'key': 'dragonfly-cache.json', 'name': 'dashboard-dragonfly-cache'} | True |
| [x] | monitoring | etcd-snapshot-correlation | {'key': 'etcd-snapshot-correlation.json', 'name': 'dashboard-etcd-snapshot-correlation'} | True |
| [x] | monitoring | external-dns | {'key': 'external-dns.json', 'name': 'dashboard-external-dns'} | True |
| [x] | monitoring | flux-cluster-stats | grafana.com/16714 | True |
| [x] | monitoring | flux-control-plane | grafana.com/19761 | True |
| [x] | monitoring | flux-ops | {'key': 'flux-ops.json', 'name': 'dashboard-flux-ops'} | True |
| [x] | monitoring | goldilocks-vpa | grafana.com/16516 | True |
| [x] | monitoring | kasa-alerts-monitoring | https://raw.githubusercontent.com/TheBranchDriftCatalyst/kasa-exporter/main/etc/grafana/provisioning/dashboards/dashboards/6-alerts-monitoring.json | True |
| [x] | monitoring | kasa-battery-sizing | https://raw.githubusercontent.com/TheBranchDriftCatalyst/kasa-exporter/main/etc/grafana/provisioning/dashboards/dashboards/3-battery-sizing.json | True |
| [x] | monitoring | kasa-comparative-analytics | https://raw.githubusercontent.com/TheBranchDriftCatalyst/kasa-exporter/main/etc/grafana/provisioning/dashboards/dashboards/5-comparative-analytics.json | True |
| [x] | monitoring | kasa-forecasting-analytics | https://raw.githubusercontent.com/TheBranchDriftCatalyst/kasa-exporter/main/etc/grafana/provisioning/dashboards/dashboards/4-forecasting-analytics.json | True |
| [x] | monitoring | kasa-real-time-monitoring | https://raw.githubusercontent.com/TheBranchDriftCatalyst/kasa-exporter/main/etc/grafana/provisioning/dashboards/dashboards/1-real-time-monitoring.json | True |
| [x] | monitoring | kasa-tou-cost-optimization | https://raw.githubusercontent.com/TheBranchDriftCatalyst/kasa-exporter/main/etc/grafana/provisioning/dashboards/dashboards/2-tou-cost-optimization.json | True |
| [x] | monitoring | keda | {'key': 'keda.json', 'name': 'dashboard-keda'} | True |
| [x] | monitoring | kubernetes-logs-loki | grafana.com/18494 | True |
| [x] | monitoring | kubevirt-control-plane | {'key': 'kubevirt-control-plane.json', 'name': 'dashboard-kubevirt-control-plane'} | True |
| [x] | monitoring | kubevirt-vm-info | {'key': 'kubevirt-vm-info.json', 'name': 'dashboard-kubevirt-vm-info'} | True |
| [x] | monitoring | kubevirt-vm-ops | {'key': 'kubevirt-vm-ops.json', 'name': 'dashboard-kubevirt-vm-ops'} | True |
| [x] | monitoring | logging-loki-v2 | grafana.com/18042 | True |
| [x] | monitoring | monitoring-ops | {'key': 'monitoring-ops.json', 'name': 'dashboard-monitoring-ops'} | True |
| [x] | monitoring | network-ops | {'key': 'network-ops.json', 'name': 'dashboard-network-ops'} | True |
| [x] | monitoring | pihole | {'key': 'pihole.json', 'name': 'dashboard-pihole'} | True |
| [x] | monitoring | pod-cleanup | {'key': 'pod-cleanup.json', 'name': 'dashboard-pod-cleanup'} | True |
| [x] | monitoring | rabbitmq | {'key': 'rabbitmq.json', 'name': 'dashboard-rabbitmq'} | True |
| [x] | monitoring | resource-efficiency | {'key': 'resource-efficiency.json', 'name': 'dashboard-resource-efficiency'} | True |
| [x] | monitoring | spire-health | {'key': 'spire-health.json', 'name': 'dashboard-spire-health'} | True |
| [x] | monitoring | talos-cluster-debug | {'key': 'talos-cluster-debug.json', 'name': 'dashboard-talos-cluster-debug'} | True |
| [x] | monitoring | talos00-memory-deepdive | {'key': 'talos00-memory-deepdive.json', 'name': 'dashboard-talos00-memory-deepdive'} | True |
| [x] | monitoring | tdarr-transcoding | {'key': 'tdarr-transcoding.json', 'name': 'dashboard-tdarr-transcoding'} | True |
| [x] | monitoring | traefik-ops | {'key': 'traefik-ops.json', 'name': 'dashboard-traefik-ops'} | True |
| [x] | monitoring | uptime-slo | {'key': 'uptime-slo.json', 'name': 'dashboard-uptime-slo'} | True |
| [x] | monitoring | vpn-gateway | {'key': 'vpn-gateway.json', 'name': 'dashboard-vpn-gateway'} | True |
| [x] | monitoring | workload-ops | {'key': 'workload-ops.json', 'name': 'dashboard-workload-ops'} | True |

## Query verification checklist

### Analytics Ops (`analytics-ops`)

Folder: Analytics · Panels: 33 · Queries: 36

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: site | site | mimir | `label_values(plausible_visitors, site)` | query executed and returned data |
| [x] | PASS | panel | Plausible sites | A | mimir | `analytics_provider_sites{provider="plausible"} or analytics_sites_total` | query executed and returned data |
| [x] | PASS | panel | GA tags | A | mimir | `analytics_provider_sites{provider="ga"}` | query executed and returned data |
| [x] | PASS | panel | Realtime visitors | A | mimir | `sum(plausible_realtime_visitors)` | query executed and returned data |
| [x] | PASS | panel | Event ingest rate | A | mimir | `sum(rate(traefik_router_requests_total{router=~".*plausible.*tracking.*"}[$__rate_interval]))` | query executed and returned data |
| [ ] | EMPTY | panel | Injection error % | A | mimir | `sum(rate(traefik_router_requests_total{router=~".*plausible.*tracking.*",code=~"5.."}[$__rate_interval])) / clamp_min(sum(rate(traefik_router_requests_total{router=~".*plausible.*tracking.*"}[$__rate_interval])), 0.0001) * 100` | query executed successfully but returned no data |
| [x] | PASS | panel | plausible | A | mimir | `clamp_max(kube_deployment_status_replicas_available{namespace="crossplane-demo",deployment="plausible"}, 1)` | query executed and returned data |
| [x] | PASS | panel | clickhouse-plausible | A | mimir | `min(kube_pod_status_ready{namespace="crossplane-demo",pod=~"chi-plausible.*",condition="true"})` | query executed and returned data |
| [x] | PASS | panel | plausible-db | A | mimir | `min(kube_pod_status_ready{namespace="crossplane-demo",pod=~"plausible-db.*",condition="true"})` | query executed and returned data |
| [x] | PASS | panel | Tracking request rate | A | mimir | `sum(rate(traefik_router_requests_total{router=~".*plausible.*tracking.*"}[$__rate_interval]))` | query executed and returned data |
| [ ] | EMPTY | panel | Tracking request rate | B | mimir | `sum(rate(traefik_router_requests_total{router=~".*plausible.*tracking.*",code=~"5.."}[$__rate_interval]))` | query executed successfully but returned no data |
| [x] | PASS | panel | Status-code breakdown | A | mimir | `sum by (code) (rate(traefik_router_requests_total{router=~".*plausible.*tracking.*"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Tracking latency (p50/p95/p99) | A | mimir | `histogram_quantile(0.50, sum by (le) (rate(traefik_router_request_duration_seconds_bucket{router=~".*plausible.*tracking.*"}[$__rate_interval])))` | query executed and returned data |
| [x] | PASS | panel | Tracking latency (p50/p95/p99) | B | mimir | `histogram_quantile(0.95, sum by (le) (rate(traefik_router_request_duration_seconds_bucket{router=~".*plausible.*tracking.*"}[$__rate_interval])))` | query executed and returned data |
| [x] | PASS | panel | Tracking latency (p50/p95/p99) | C | mimir | `histogram_quantile(0.99, sum by (le) (rate(traefik_router_request_duration_seconds_bucket{router=~".*plausible.*tracking.*"}[$__rate_interval])))` | query executed and returned data |
| [x] | PASS | panel | Per-app request rate through injected routers | A | mimir | `sum by (router) (rate(traefik_router_requests_total{router=~"$injected"}[$__rate_interval]))` | query executed and returned data |
| [ ] | EMPTY | panel | Active injected routers | A | mimir | `count(count by (router) (rate(traefik_router_requests_total{router=~"$injected"}[$__rate_interval]) > 0))` | query executed successfully but returned no data |
| [x] | PASS | panel | Unique visitors ($period) | A | mimir | `plausible_visitors{site=~"$site",period="$period"}` | query executed and returned data |
| [x] | PASS | panel | Pageviews ($period) | A | mimir | `plausible_pageviews{site=~"$site",period="$period"}` | query executed and returned data |
| [x] | PASS | panel | Bounce rate ($period) | A | mimir | `plausible_bounce_rate_percent{site=~"$site",period="$period"}` | query executed and returned data |
| [x] | PASS | panel | Avg visit duration ($period) | A | mimir | `plausible_visit_duration_seconds{site=~"$site",period="$period"}` | query executed and returned data |
| [x] | PASS | panel | Realtime visitors (per site) | A | mimir | `plausible_realtime_visitors{site=~"$site"}` | query executed and returned data |
| [x] | PASS | panel | Sites — current values ($period) | A | mimir | `plausible_visitors{site=~"$site",period="$period"}` | query executed and returned data |
| [x] | PASS | panel | Sites — current values ($period) | B | mimir | `plausible_pageviews{site=~"$site",period="$period"}` | query executed and returned data |
| [x] | PASS | panel | Sites — current values ($period) | C | mimir | `plausible_bounce_rate_percent{site=~"$site",period="$period"}` | query executed and returned data |
| [x] | PASS | panel | Sites — current values ($period) | D | mimir | `plausible_visit_duration_seconds{site=~"$site",period="$period"}` | query executed and returned data |
| [x] | PASS | panel | Sites — current values ($period) | E | mimir | `plausible_realtime_visitors{site=~"$site"}` | query executed and returned data |
| [x] | PASS | panel | Pod ready (plausible / clickhouse / db) | A | mimir | `kube_pod_status_ready{namespace="crossplane-demo",pod=~"plausible.*\|chi-plausible.*",condition="true"}` | query executed and returned data |
| [x] | PASS | panel | Restarts (2h increase) | A | mimir | `sum by (pod) (increase(kube_pod_container_status_restarts_total{namespace="crossplane-demo",pod=~"plausible.*\|chi-plausible.*"}[2h]))` | query executed and returned data |
| [x] | PASS | panel | CPU usage (cores) | A | mimir | `sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="crossplane-demo",pod=~"plausible.*\|chi-plausible.*",container!=""}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Memory working set | A | mimir | `sum by (pod) (container_memory_working_set_bytes{namespace="crossplane-demo",pod=~"plausible.*\|chi-plausible.*",container!=""})` | query executed and returned data |
| [x] | PASS | panel | Reconciler — since last success | A | mimir | `time() - max(kube_cronjob_status_last_successful_time{cronjob="plausible-site-reconciler"})` | query executed and returned data |
| [x] | PASS | panel | Reconciler job success/fail | A | mimir | `sum(kube_job_status_succeeded{job_name=~"plausible-site-reconciler.*"})` | query executed and returned data |
| [x] | PASS | panel | Reconciler job success/fail | B | mimir | `sum(kube_job_status_failed{job_name=~"plausible-site-reconciler.*"})` | query executed and returned data |
| [x] | PASS | panel | Exporter plausible_up | A | mimir | `plausible_up` | query executed and returned data |
| [x] | PASS | panel | Exporter scrape duration | A | mimir | `plausible_scrape_duration_seconds` | query executed and returned data |

### App Ops — Image Versions (`app-ops-image-versions`)

Folder: App · Panels: 11 · Queries: 9

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: namespace | namespace | mimir | `label_values(version_checker_is_latest_version, namespace)` | query executed and returned data |
| [x] | PASS | panel | Out-of-date containers | A | mimir | `count(version_checker_is_latest_version == 0)` | query executed and returned data |
| [x] | PASS | panel | Total tracked | A | mimir | `count(version_checker_is_latest_version)` | query executed and returned data |
| [x] | PASS | panel | % up-to-date | A | mimir | `avg(version_checker_is_latest_version)*100` | query executed and returned data |
| [x] | PASS | panel | Namespaces w/ stale images | A | mimir | `count(count by(namespace)(version_checker_is_latest_version == 0))` | query executed and returned data |
| [x] | PASS | panel | Kubernetes version | A | mimir | `version_checker_is_latest_kube_version` | query executed and returned data |
| [x] | PASS | panel | Out-of-date images | A | mimir | `version_checker_is_latest_version{namespace=~"$namespace"} == 0` | query executed and returned data |
| [x] | PASS | panel | Stale images per namespace | A | mimir | `sum by(namespace)(version_checker_is_latest_version{namespace=~"$namespace"} == bool 0)` | query executed and returned data |
| [x] | PASS | panel | Full image inventory | A | mimir | `version_checker_is_latest_version{namespace=~"$namespace"}` | query executed and returned data |

### Argo Ops (`argo-ops`)

Folder: GitOps · Panels: 26 · Queries: 25

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: project | project | mimir | `label_values(argocd_app_info, project)` | query executed and returned data |
| [x] | PASS | variable | Variable: health | health | mimir | `label_values(argocd_app_info, health_status)` | query executed and returned data |
| [x] | PASS | variable | Variable: sync | sync | mimir | `label_values(argocd_app_info, sync_status)` | query executed and returned data |
| [x] | PASS | panel | Total Apps | A | mimir | `count(argocd_app_info)` | query executed and returned data |
| [x] | PASS | panel | OutOfSync | A | mimir | `count(argocd_app_info{sync_status="OutOfSync"}) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | Degraded / Missing / Unknown | A | mimir | `count(argocd_app_info{health_status=~"Degraded\|Missing\|Unknown"}) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | Auto-sync OFF | A | mimir | `count(argocd_app_info{autosync_enabled="false"}) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | Apps by Health | A | mimir | `sum by(health_status)(argocd_app_info)` | query executed and returned data |
| [x] | PASS | panel | Apps by Sync | A | mimir | `sum by(sync_status)(argocd_app_info)` | query executed and returned data |
| [x] | PASS | panel | Application Health × Sync | A | mimir | `argocd_app_info{project=~"$project", health_status=~"$health", sync_status=~"$sync"}` | query executed and returned data |
| [ ] | EMPTY | panel | OutOfSync Apps | A | mimir | `argocd_app_info{sync_status="OutOfSync", project=~"$project"}` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Degraded / Missing Apps | A | mimir | `argocd_app_info{health_status=~"Degraded\|Missing\|Unknown", project=~"$project"}` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Orphaned Resources by App | A | mimir | `argocd_app_orphaned_resources_count > 0` | query executed successfully but returned no data |
| [x] | PASS | panel | Sync Rate by Phase | A | mimir | `sum by(phase)(rate(argocd_app_sync_total[15m]))` | query executed and returned data |
| [x] | PASS | panel | Failed / Errored Sync Rate | A | mimir | `sum(rate(argocd_app_sync_total{phase=~"Failed\|Error"}[15m])) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | Reconcile Latency (p50 / p99) | A | mimir | `histogram_quantile(0.50, sum by(le)(rate(argocd_app_reconcile_bucket[5m])))` | query executed and returned data |
| [x] | PASS | panel | Reconcile Latency (p50 / p99) | B | mimir | `histogram_quantile(0.99, sum by(le)(rate(argocd_app_reconcile_bucket[5m])))` | query executed and returned data |
| [x] | PASS | panel | Git Fetch Failure Rate | A | mimir | `sum(rate(argocd_git_fetch_fail_total[5m])) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | Git Request Latency p99 | A | mimir | `histogram_quantile(0.99, sum by(le)(rate(argocd_git_request_duration_seconds_bucket[5m])))` | query executed and returned data |
| [x] | PASS | panel | Repo-server Pending Requests | A | mimir | `sum(argocd_repo_pending_request_total)` | query executed and returned data |
| [x] | PASS | panel | kubectl exec Pending | A | mimir | `sum(argocd_kubectl_exec_pending)` | query executed and returned data |
| [x] | PASS | panel | Redis Request Rate | A | mimir | `sum(rate(argocd_redis_request_total[5m]))` | query executed and returned data |
| [x] | PASS | panel | Cluster Connection Status (1=connected) | A | mimir | `argocd_cluster_connection_status` | query executed and returned data |
| [x] | PASS | panel | Cluster Cache Age | A | mimir | `argocd_cluster_cache_age_seconds` | query executed and returned data |
| [x] | PASS | panel | K8s API Request Rate (app-controller) | A | mimir | `sum(rate(argocd_app_k8s_request_total[5m]))` | query executed and returned data |

### ArgoCD (`qPkgGHg7k`)

Folder: GitOps · Panels: 50 · Queries: 41

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: namespace | namespace | $datasource | `label_values(kube_pod_info, namespace)` | query executed and returned data |
| [x] | PASS | variable | Variable: cluster | cluster | $datasource | `label_values(argocd_cluster_info, server)` | query executed and returned data |
| [x] | PASS | panel | Uptime | A | Prometheus | `time() - max(process_start_time_seconds{job="argocd-server-metrics",namespace=~"$namespace"})` | query executed and returned data |
| [x] | PASS | panel | Clusters | A | Prometheus | `count(count by (server) (argocd_cluster_info{namespace=~"$namespace"}))` | query executed and returned data |
| [x] | PASS | panel | Applications | A | Prometheus | `sum(argocd_app_info{namespace=~"$namespace",dest_server=~"$cluster",health_status=~"$health_status",sync_status=~"$sync_status"})` | query executed and returned data |
| [x] | PASS | panel | Repositories | A | Prometheus | `count(count by (repo) (argocd_app_info{namespace=~"$namespace"}))` | query executed and returned data |
| [ ] | EMPTY | panel | Operations | A | Prometheus | `sum(argocd_app_info{namespace=~"$namespace",dest_server=~"$cluster",operation!=""})` | query executed successfully but returned no data |
| [x] | PASS | panel | Applications | A | Prometheus | `sum(argocd_app_info{namespace=~"$namespace",dest_server=~"$cluster",health_status=~"$health_status",sync_status=~"$sync_status"}) by (namespace)` | query executed and returned data |
| [x] | PASS | panel | Health Status | A | Prometheus | `sum(argocd_app_info{namespace=~"$namespace",dest_server=~"$cluster",health_status=~"$health_status",sync_status=~"$sync_status",health_status!=""}) by (health_status)` | query executed and returned data |
| [x] | PASS | panel | Sync Status | A | Prometheus | `sum(argocd_app_info{namespace=~"$namespace",dest_server=~"$cluster",health_status=~"$health_status",sync_status=~"$sync_status",health_status!=""}) by (sync_status)` | query executed and returned data |
| [x] | PASS | panel | Sync Activity | A | Prometheus | `sum(round(increase(argocd_app_sync_total{namespace=~"$namespace",dest_server=~"$cluster"}[$interval]))) by ($grouping)` | query executed and returned data |
| [ ] | EMPTY | panel | Sync Failures | A | Prometheus | `sum(round(increase(argocd_app_sync_total{namespace=~"$namespace",phase=~"Error\|Failed",dest_server=~"$cluster"}[$interval]))) by ($grouping, phase)` | query executed successfully but returned no data |
| [x] | PASS | panel | Reconciliation Activity | A | Prometheus | `sum(increase(argocd_app_reconcile_count{namespace=~"$namespace",dest_server=~"$cluster"}[$interval])) by ($grouping)` | query executed and returned data |
| [x] | PASS | panel | Reconciliation Performance | A | Prometheus | `sum(increase(argocd_app_reconcile_bucket{namespace=~"$namespace"}[$interval])) by (le)` | query executed and returned data |
| [x] | PASS | panel | K8s API Activity | A | Prometheus | `sum(increase(argocd_app_k8s_request_total{namespace=~"$namespace",server=~"$cluster"}[$interval])) by (verb, resource_kind)` | query executed and returned data |
| [x] | PASS | panel | Workqueue Depth | A | Prometheus | `sum(workqueue_depth{namespace=~"$namespace",name=~"app_.*"}) by (name)` | query executed and returned data |
| [x] | PASS | panel | Pending kubectl run | A | Prometheus | `sum(argocd_kubectl_exec_pending{namespace=~"$namespace"}) by (command)` | query executed and returned data |
| [ ] | EMPTY | panel | Memory Usage | A | Prometheus | `go_memstats_heap_alloc_bytes{job="argocd-metrics",namespace=~"$namespace"}` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | CPU Usage | A | Prometheus | `irate(process_cpu_seconds_total{job="argocd-metrics",namespace=~"$namespace"}[1m])` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Goroutines | A | Prometheus | `go_goroutines{job="argocd-metrics",namespace=~"$namespace"}` | query executed successfully but returned no data |
| [x] | PASS | panel | Resource Objects Count | A | Prometheus | `sum(argocd_cluster_api_resource_objects{namespace=~"$namespace",server=~"$cluster"}) by (server)` | query executed and returned data |
| [x] | PASS | panel | API Resources Count | A | Prometheus | `sum(argocd_cluster_api_resources{namespace=~"$namespace",server=~"$cluster"}) by (server)` | query executed and returned data |
| [x] | PASS | panel | Cluster Events Count | A | Prometheus | `sum(increase(argocd_cluster_events_total{namespace=~"$namespace",server=~"$cluster"}[$interval])) by (server)` | query executed and returned data |
| [x] | PASS | panel | Git Requests (ls-remote) | A | Prometheus | `sum(increase(argocd_git_request_total{request_type="ls-remote", namespace=~"$namespace"}[10m])) by (namespace)` | query executed and returned data |
| [x] | PASS | panel | Git Requests (checkout) | A | Prometheus | `sum(increase(argocd_git_request_total{request_type="fetch", namespace=~"$namespace"}[10m])) by (namespace)` | query executed and returned data |
| [x] | PASS | panel | Git Fetch Performance | A | Prometheus | `sum(increase(argocd_git_request_duration_seconds_bucket{request_type="fetch", namespace=~"$namespace"}[$interval])) by (le)` | query executed and returned data |
| [x] | PASS | panel | Git Ls-Remote Performance | A | Prometheus | `sum(increase(argocd_git_request_duration_seconds_bucket{request_type="ls-remote", namespace=~"$namespace"}[$interval])) by (le)` | query executed and returned data |
| [ ] | EMPTY | panel | Memory Used | A | Prometheus | `go_memstats_heap_alloc_bytes{job="argocd-repo-server",namespace=~"$namespace"}` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Goroutines | A | Prometheus | `go_goroutines{job="argocd-repo-server",namespace=~"$namespace"}` | query executed successfully but returned no data |
| [x] | PASS | panel | Memory Used | A | Prometheus | `go_memstats_heap_alloc_bytes{job="argocd-server-metrics",namespace=~"$namespace"}` | query executed and returned data |
| [x] | PASS | panel | Goroutines | A | Prometheus | `go_goroutines{job="argocd-server-metrics",namespace=~"$namespace"}` | query executed and returned data |
| [ ] | EMPTY | panel | GC Time Quantiles | A | Prometheus | `go_gc_duration_seconds{job="argocd-server-metrics", quantile="1", namespace=~"$namespace"}` | query executed successfully but returned no data |
| [x] | PASS | panel | ApplicationService Requests | A | Prometheus | `sum(increase(grpc_server_handled_total{job="argocd-server-metrics",grpc_service="application.ApplicationService",namespace=~"$namespace"}[$interval])) by (grpc_code, grpc_method)` | query executed and returned data |
| [x] | PASS | panel | ClusterService Requests | A | Prometheus | `sum(increase(grpc_server_handled_total{job="argocd-server-metrics",grpc_service="cluster.ClusterService",namespace=~"$namespace"}[$interval])) by (grpc_code, grpc_method)` | query executed and returned data |
| [x] | PASS | panel | ProjectService Requests | A | Prometheus | `sum(increase(grpc_server_handled_total{job="argocd-server-metrics",grpc_service="project.ProjectService",namespace=~"$namespace"}[$interval])) by (grpc_code, grpc_method)` | query executed and returned data |
| [x] | PASS | panel | RepositoryService Requests | A | Prometheus | `sum(increase(grpc_server_handled_total{job="argocd-server-metrics",grpc_service="repository.RepositoryService",namespace=~"$namespace"}[$interval])) by (grpc_code, grpc_method)` | query executed and returned data |
| [x] | PASS | panel | SessionService Requests | A | Prometheus | `sum(increase(grpc_server_handled_total{job="argocd-server-metrics",grpc_service="session.SessionService",namespace=~"$namespace"}[$interval])) by (grpc_code, grpc_method)` | query executed and returned data |
| [x] | PASS | panel | VersionService Requests | A | Prometheus | `sum(increase(grpc_server_handled_total{job="argocd-server-metrics",grpc_service="version.VersionService",namespace=~"$namespace"}[$interval])) by (grpc_code, grpc_method)` | query executed and returned data |
| [x] | PASS | panel | AccountService Requests | A | Prometheus | `sum(increase(grpc_server_handled_total{job="argocd-server-metrics",grpc_service="account.AccountService",namespace=~"$namespace"}[$interval])) by (grpc_code, grpc_method)` | query executed and returned data |
| [ ] | EMPTY | panel | SettingsService Requests | A | Prometheus | `sum(increase(grpc_server_handled_total{job="argocd-server-metrics",grpc_service="settings.SettingsService",namespace=~"$namespace"}[$interval])) by (grpc_code, grpc_method)` | query executed successfully but returned no data |
| [x] | PASS | panel | Requests by result | A |  | `sum(increase(argocd_redis_request_total{namespace=~"$namespace"}[$interval])) by (failed)` | query executed and returned data |

### ArgoCD / Application / Overview (`argo-cd-application-overview-kask`)

Folder: GitOps · Panels: 14 · Queries: 18

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: cluster | cluster | ${datasource} | `label_values(argocd_app_info{}, cluster)` | query executed and returned data |
| [x] | PASS | variable | Variable: namespace | namespace | ${datasource} | `label_values(argocd_app_info{cluster="$cluster"}, namespace)` | query executed and returned data |
| [ ] | REVIEW | variable | Variable: job | job | ${datasource} | `label_values(job)` | Grafana variable helper requires UI evaluation |
| [x] | PASS | variable | Variable: kubernetes_cluster | kubernetes_cluster | ${datasource} | `label_values(argocd_app_info{cluster="$cluster", namespace=~"$namespace", job=~"$job"}, dest_server)` | query executed and returned data |
| [x] | PASS | variable | Variable: project | project | ${datasource} | `label_values(argocd_app_info{cluster="$cluster", namespace=~"$namespace", job=~"$job", dest_server=~"$kubernetes_cluster"}, project)` | query executed and returned data |
| [x] | PASS | variable | Variable: application_namespace | application_namespace | ${datasource} | `label_values(argocd_app_info{cluster="$cluster", namespace=~"$namespace", job=~"$job", dest_server=~"$kubernetes_cluster", project=~"$project"}, exported_namespace)` | query executed and returned data |
| [x] | PASS | variable | Variable: application | application | ${datasource} | `label_values(argocd_app_info{cluster="$cluster", namespace=~"$namespace", job=~"$job", dest_server=~"$kubernetes_cluster", project=~"$project", exported_namespace=~"$application_namespace"}, name)` | query executed and returned data |
| [x] | PASS | panel | Application Health Status |  | default | `sum(   argocd_app_info{     cluster="$cluster", namespace=~"$namespace", job=~"$job"  , dest_server=~"$kubernetes_cluster", project=~"$project"    } ) by (job, project, health_status)` | query executed and returned data |
| [x] | PASS | panel | Application Sync Status |  | default | `sum(   argocd_app_info{     cluster="$cluster", namespace=~"$namespace", job=~"$job"  , dest_server=~"$kubernetes_cluster", project=~"$project"    } ) by (job, project, sync_status)` | query executed and returned data |
| [x] | PASS | panel | Application Syncs |  | default | `sum(   round(     increase(       argocd_app_sync_total{         cluster="$cluster", namespace=~"$namespace", job=~"$job"  , dest_server=~"$kubernetes_cluster", project=~"$project"        }[$__rate_interval]     )   ) ) by (job, project, phase)` | query executed and returned data |
| [x] | PASS | panel | Application Auto Sync Enabled |  | default | `sum(   argocd_app_info{     cluster="$cluster", namespace=~"$namespace", job=~"$job"  , dest_server=~"$kubernetes_cluster", project=~"$project"    } ) by (job, project, autosync_enabled)` | query executed and returned data |
| [ ] | EMPTY | panel | Unhealthy Applications |  | default | `sum(   argocd_app_info{     cluster="$cluster", namespace=~"$namespace", job=~"$job"  , dest_server=~"$kubernetes_cluster", project=~"$project" ,     health_status!~"Healthy\|Progressing"   } ) by (job, dest_server, project, name, exported_namespace, health_status) > 0` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Out Of Sync Applications |  | default | `sum(   argocd_app_info{     cluster="$cluster", namespace=~"$namespace", job=~"$job"  , dest_server=~"$kubernetes_cluster", project=~"$project" ,     sync_status!="Synced"   } ) by (job, dest_server, project, name, exported_namespace, sync_status) > 0` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Applications That Failed to Sync (7d) |  | default | `sum(   round(     increase(       argocd_app_sync_total{         cluster="$cluster", namespace=~"$namespace", job=~"$job"  , dest_server=~"$kubernetes_cluster", project=~"$project" ,         phase!="Succeeded"       }[7d]     )   ) ) by (job, dest_server, project, name, exported_namespace, phase) > 0` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Applications With Auto Sync Disabled |  | default | `sum(   argocd_app_info{     cluster="$cluster", namespace=~"$namespace", job=~"$job"  , dest_server=~"$kubernetes_cluster", project=~"$project" ,     autosync_enabled!="true"   } ) by (job, dest_server, project, name, exported_namespace, autosync_enabled) > 0` | query executed successfully but returned no data |
| [x] | PASS | panel | Application Health Status by Application |  | default | `sum(   argocd_app_info{     cluster="$cluster", namespace=~"$namespace", job=~"$job"  , dest_server=~"$kubernetes_cluster", project=~"$project" , exported_namespace=~"$application_namespace", name=~"$application"    } ) by (namespace, job, dest_server, project, name, exported_namespace, health_status)` | query executed and returned data |
| [x] | PASS | panel | Application Sync Status by Application |  | default | `sum(   argocd_app_info{     cluster="$cluster", namespace=~"$namespace", job=~"$job"  , dest_server=~"$kubernetes_cluster", project=~"$project" , exported_namespace=~"$application_namespace", name=~"$application"    } ) by (namespace, job, dest_server, project, name, exported_namespace, sync_status)` | query executed and returned data |
| [x] | PASS | panel | Application Sync Result by Application |  | default | `sum(   round(     increase(       argocd_app_sync_total{         cluster="$cluster", namespace=~"$namespace", job=~"$job"  , dest_server=~"$kubernetes_cluster", project=~"$project" , exported_namespace=~"$application_namespace", name=~"$application"        }[$__rate_interval]     )   ) ) by (namespace, job, dest_server, project, name, exported_namespace, phase)` | query executed and returned data |

### ArgoCD / Operational / Overview (`argo-cd-operational-overview-kask`)

Folder: GitOps · Panels: 52 · Queries: 49

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: cluster | cluster | ${datasource} | `label_values(argocd_app_info{}, cluster)` | query executed and returned data |
| [x] | PASS | variable | Variable: namespace | namespace | ${datasource} | `label_values(argocd_app_info{cluster="$cluster"}, namespace)` | query executed and returned data |
| [ ] | REVIEW | variable | Variable: job | job | ${datasource} | `label_values(job)` | Grafana variable helper requires UI evaluation |
| [x] | PASS | variable | Variable: kubernetes_cluster | kubernetes_cluster | ${datasource} | `label_values(argocd_app_info{cluster="$cluster", namespace=~"$namespace", job=~"$job"}, dest_server)` | query executed and returned data |
| [x] | PASS | variable | Variable: project | project | ${datasource} | `label_values(argocd_app_info{cluster="$cluster", namespace=~"$namespace", job=~"$job", dest_server=~"$kubernetes_cluster"}, project)` | query executed and returned data |
| [x] | PASS | panel | Clusters |  | default | `sum(   argocd_cluster_info{     cluster="$cluster", namespace=~"$namespace", job=~"$job"     } )` | query executed and returned data |
| [x] | PASS | panel | Repositories |  | default | `count(   count(     argocd_app_info{       cluster="$cluster", namespace=~"$namespace", job=~"$job"       }   )   by (repo) )` | query executed and returned data |
| [x] | PASS | panel | Applications |  | default | `sum(   argocd_app_info{     cluster="$cluster", namespace=~"$namespace", job=~"$job"  , dest_server=~"$kubernetes_cluster", project=~"$project"    } )` | query executed and returned data |
| [x] | PASS | panel | Health Status |  | default | `sum(   argocd_app_info{     cluster="$cluster", namespace=~"$namespace", job=~"$job"  , dest_server=~"$kubernetes_cluster", project=~"$project"    } ) by (health_status)` | query executed and returned data |
| [x] | PASS | panel | Sync Status |  | default | `sum(   argocd_app_info{     cluster="$cluster", namespace=~"$namespace", job=~"$job"  , dest_server=~"$kubernetes_cluster", project=~"$project"    } ) by (sync_status)` | query executed and returned data |
| [x] | PASS | panel | Applications |  | default | `sum(   argocd_app_info{     cluster="$cluster", namespace=~"$namespace", job=~"$job"  , dest_server=~"$kubernetes_cluster", project=~"$project"    } ) by (job, dest_server, project, name, health_status, sync_status)` | query executed and returned data |
| [x] | PASS | panel | Sync Activity |  | default | `sum(   round(     increase(       argocd_app_sync_total{         cluster="$cluster", namespace=~"$namespace", job=~"$job"  , dest_server=~"$kubernetes_cluster", project=~"$project"        }[$__rate_interval]     )   ) ) by (job, dest_server, project, name) > 0` | query executed and returned data |
| [ ] | EMPTY | panel | Sync Failures |  | default | `sum(   round(     increase(       argocd_app_sync_total{         cluster="$cluster", namespace=~"$namespace", job=~"$job"  , dest_server=~"$kubernetes_cluster", project=~"$project" ,         phase=~"Error\|Failed"       }[$__rate_interval]     )   ) ) by (job, dest_server, project, name, phase) > 0` | query executed successfully but returned no data |
| [x] | PASS | panel | Reconciliation Activity |  | default | `sum(   round(     increase(       argocd_app_reconcile_count{         cluster="$cluster", namespace=~"$namespace", job=~"$job"         }[$__rate_interval]     )   ) ) by (namespace, job)` | query executed and returned data |
| [x] | PASS | panel | Reconciliation Performance |  | default | `sum(   rate(     argocd_app_reconcile_bucket{       cluster="$cluster", namespace=~"$namespace", job=~"$job"       }[$__rate_interval]   ) ) by (le)` | query executed and returned data |
| [x] | PASS | panel | K8s API Activity |  | default | `sum(   round(     increase(       argocd_app_k8s_request_total{         cluster="$cluster", namespace=~"$namespace", job=~"$job"         }[$__rate_interval]     )   ) ) by (job, verb, resource_kind)` | query executed and returned data |
| [x] | PASS | panel | Resource Event Processing Duration |  | default | `sum(   rate(     argocd_resource_events_processing_bucket{       cluster="$cluster", namespace=~"$namespace", job=~"$job"       }[$__rate_interval]   ) ) by (le)` | query executed and returned data |
| [x] | PASS | panel | Resource Events Batch Size |  | default | `sum(   argocd_resource_events_processed_in_batch{     cluster="$cluster", namespace=~"$namespace", job=~"$job"     } ) by (namespace, job)` | query executed and returned data |
| [x] | PASS | panel | Pending Kubectl Runs |  | default | `sum(   argocd_kubectl_exec_pending{     cluster="$cluster", namespace=~"$namespace", job=~"$job"     } ) by (job, command)` | query executed and returned data |
| [x] | PASS | panel | Kubectl Exec Total |  | default | `sum(   round(     increase(       argocd_kubectl_exec_total{         cluster="$cluster", namespace=~"$namespace", job=~"$job"         }[$__rate_interval]     )   ) ) by (namespace, job, command)` | query executed and returned data |
| [x] | PASS | panel | Kubectl Requests Total |  | default | `sum(   rate(     argocd_kubectl_requests_total{       cluster="$cluster", namespace=~"$namespace", job=~"$job"       }[$__rate_interval]   ) ) by (container, method, code)` | query executed and returned data |
| [x] | PASS | panel | Kubectl Requests Total by Host (6h) |  | default | `topk(20,   sum(     increase(       argocd_kubectl_requests_total{         cluster="$cluster", namespace=~"$namespace", job=~"$job"         }[6h]     )   ) by (host) )` | query executed and returned data |
| [x] | PASS | panel | Kubectl Request Duration by Verb (P95) |  | default | `histogram_quantile(   0.95,   sum(     rate(       argocd_kubectl_request_duration_seconds_bucket{         cluster="$cluster", namespace=~"$namespace", job=~"$job"         }[$__rate_interval]     )   ) by (le, container, verb) )` | query executed and returned data |
| [x] | PASS | panel | Kubectl Request Duration by Host (6h) |  | default | `topk(20,   histogram_quantile(     0.95,     sum(       increase(         argocd_kubectl_request_duration_seconds_bucket{           cluster="$cluster", namespace=~"$namespace", job=~"$job"           }[6h]       )     ) by (le, host)   ) )` | query executed and returned data |
| [x] | PASS | panel | Kubectl Request Retries |  | default | `sum(   rate(     argocd_kubectl_request_retries_total{       cluster="$cluster", namespace=~"$namespace", job=~"$job"       }[$__rate_interval]   ) ) by (container, method, code)` | query executed and returned data |
| [x] | PASS | panel | Kubectl Request Retries by Host (6h) |  | default | `topk(20,   sum(     increase(       argocd_kubectl_request_retries_total{         cluster="$cluster", namespace=~"$namespace", job=~"$job"         }[6h]     )   ) by (host) )` | query executed and returned data |
| [x] | PASS | panel | Kubectl Rate Limiter Duration (P95) |  | default | `histogram_quantile(   0.95,   sum(     rate(       argocd_kubectl_rate_limiter_duration_seconds_bucket{         cluster="$cluster", namespace=~"$namespace", job=~"$job"         }[$__rate_interval]     )   ) by (le, verb) )` | query executed and returned data |
| [x] | PASS | panel | Kubectl Rate Limiter Duration P95 by Host (6h) |  | default | `topk(20,   histogram_quantile(     0.95,     sum(       increase(         argocd_kubectl_rate_limiter_duration_seconds_bucket{           cluster="$cluster", namespace=~"$namespace", job=~"$job"           }[6h]       )     ) by (le, host)   ) )` | query executed and returned data |
| [x] | PASS | panel | Kubectl Request Size |  | default | `sum(   rate(     argocd_kubectl_request_size_bytes_bucket{       cluster="$cluster", namespace=~"$namespace", job=~"$job"       }[$__rate_interval]   ) ) by (le)` | query executed and returned data |
| [x] | PASS | panel | Kubectl Response Size |  | default | `sum(   rate(     argocd_kubectl_response_size_bytes_bucket{       cluster="$cluster", namespace=~"$namespace", job=~"$job"       }[$__rate_interval]   ) ) by (le)` | query executed and returned data |
| [ ] | EMPTY | panel | Kubectl Exec Plugin Calls |  | default | `sum(   round(     increase(       argocd_kubectl_exec_plugin_call_total{         cluster="$cluster", namespace=~"$namespace", job=~"$job"         }[$__rate_interval]     )   ) ) by (call_status, code)` | query executed successfully but returned no data |
| [x] | PASS | panel | Kubectl Transport Create Calls |  | default | `sum(   round(     increase(       argocd_kubectl_transport_create_calls_total{         cluster="$cluster", namespace=~"$namespace", job=~"$job"         }[$__rate_interval]     )   ) ) by (namespace, job)` | query executed and returned data |
| [x] | PASS | panel | gRPC Requests Handled |  | default | `sum(   rate(     grpc_server_handled_total{       cluster="$cluster", namespace=~"$namespace", job=~"$job"       }[$__rate_interval]   ) ) by (namespace, job, grpc_service, grpc_method, grpc_code) > 0` | query executed and returned data |
| [x] | PASS | panel | gRPC Messages Sent |  | default | `sum(   rate(     grpc_server_msg_sent_total{       cluster="$cluster", namespace=~"$namespace", job=~"$job"       }[$__rate_interval]   ) ) by (namespace, job, grpc_service, grpc_method) > 0` | query executed and returned data |
| [ ] | EMPTY | panel | gRPC Server Handling Duration (P50) |  | default | `histogram_quantile(   0.5,   sum(     rate(       grpc_server_handling_seconds_bucket{         cluster="$cluster", namespace=~"$namespace", job=~"$job"         }[$__rate_interval]     )   ) by (le, grpc_service, grpc_method) ) and sum(   rate(     grpc_server_handling_seconds_count{       cluster="$cluster", namespace=~"$namespace", job=~"$job"       }[$__rate_interval]   ) ) by (grpc_service, grpc_method) > 0` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | gRPC Server Handling Duration (P95) |  | default | `histogram_quantile(   0.95,   sum(     rate(       grpc_server_handling_seconds_bucket{         cluster="$cluster", namespace=~"$namespace", job=~"$job"         }[$__rate_interval]     )   ) by (le, grpc_service, grpc_method) ) and sum(   rate(     grpc_server_handling_seconds_count{       cluster="$cluster", namespace=~"$namespace", job=~"$job"       }[$__rate_interval]   ) ) by (grpc_service, grpc_method) > 0` | query executed successfully but returned no data |
| [x] | PASS | panel | Cluster Connection Status |  | default | `sum(   argocd_cluster_connection_status{     cluster="$cluster", namespace=~"$namespace", job=~"$job"  ,     server=~"$kubernetes_cluster"   } ) by (namespace, job, server, k8s_version)` | query executed and returned data |
| [x] | PASS | panel | Cluster Cache Age |  | default | `argocd_cluster_cache_age_seconds{   cluster="$cluster", namespace=~"$namespace", job=~"$job"  ,   server=~"$kubernetes_cluster" }` | query executed and returned data |
| [x] | PASS | panel | Resource Objects |  | default | `sum(   argocd_cluster_api_resource_objects{     cluster="$cluster", namespace=~"$namespace", job=~"$job"  ,     server=~"$kubernetes_cluster"   } ) by (namespace, job, server)` | query executed and returned data |
| [x] | PASS | panel | API Resources |  | default | `sum(   argocd_cluster_api_resources{     cluster="$cluster", namespace=~"$namespace", job=~"$job"  ,     server=~"$kubernetes_cluster"   } ) by (namespace, job, server)` | query executed and returned data |
| [x] | PASS | panel | Cluster Events |  | default | `sum(   increase(     argocd_cluster_events_total{       cluster="$cluster", namespace=~"$namespace", job=~"$job"  ,       server=~"$kubernetes_cluster"     }[$__rate_interval]   ) ) by (namespace, job, server)` | query executed and returned data |
| [x] | PASS | panel | Pending Repo Requests |  | default | `sum(   argocd_repo_pending_request_total{     cluster="$cluster", namespace=~"$namespace", job=~"$job"     } ) by (namespace, job)` | query executed and returned data |
| [ ] | EMPTY | panel | Git Fetch Failures |  | default | `sum(   increase(     argocd_git_fetch_fail_total{       cluster="$cluster", namespace=~"$namespace", job=~"$job"       }[$__rate_interval]   ) ) by (namespace, job, repo)` | query executed successfully but returned no data |
| [x] | PASS | panel | Git Requests (ls-remote) |  | default | `sum(   increase(     argocd_git_request_total{       cluster="$cluster", namespace=~"$namespace", job=~"$job"  ,       request_type="ls-remote"     }[$__rate_interval]   ) ) by (namespace, job, repo)` | query executed and returned data |
| [x] | PASS | panel | Git Requests (checkout) |  | default | `sum(   increase(     argocd_git_request_total{       cluster="$cluster", namespace=~"$namespace", job=~"$job"  ,       request_type="fetch"     }[$__rate_interval]   ) ) by (namespace, job, repo)` | query executed and returned data |
| [x] | PASS | panel | Git Fetch Performance |  | default | `sum(   rate(     argocd_git_request_duration_seconds_bucket{       cluster="$cluster", namespace=~"$namespace", job=~"$job"  ,       request_type="fetch"     }[$__rate_interval]   ) ) by (le)` | query executed and returned data |
| [x] | PASS | panel | Git Ls-remote Performance |  | default | `sum(   rate(     argocd_git_request_duration_seconds_bucket{       cluster="$cluster", namespace=~"$namespace", job=~"$job"  ,       request_type="ls-remote"     }[$__rate_interval]   ) ) by (le)` | query executed and returned data |
| [x] | PASS | panel | Redis Request Rate |  | default | `sum(   rate(     argocd_redis_request_total{       cluster="$cluster", namespace=~"$namespace", job=~"$job"       }[$__rate_interval]   ) ) by (namespace, job, initiator)` | query executed and returned data |
| [x] | PASS | panel | Redis Request Duration |  | default | `sum(   rate(     argocd_redis_request_duration_seconds_bucket{       cluster="$cluster", namespace=~"$namespace", job=~"$job"       }[$__rate_interval]   ) ) by (le)` | query executed and returned data |

### boomtime · Domain & Jobs (`boomtime-domain-jobs`)

Folder: Apps · Panels: 35 · Queries: 36

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | panel | Heartbeats ingested (range) | A | mimir | `sum(increase(boomtime_heartbeats_ingested_total{namespace="boomtime"}[$__range]))` | query executed and returned data |
| [x] | PASS | panel | Heartbeat rate | A | mimir | `sum(rate(boomtime_heartbeats_ingested_total{namespace="boomtime"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Job success ratio | A | mimir | `sum(increase(jobs_run_total{namespace="boomtime",status="done"}[$__range])) / clamp_min(sum(increase(jobs_run_total{namespace="boomtime"}[$__range])), 1e-9)` | query executed and returned data |
| [ ] | EMPTY | panel | Jobs failed (range) | A | mimir | `sum(increase(jobs_run_total{namespace="boomtime",status="failed"}[$__range]))` | query executed successfully but returned no data |
| [x] | PASS | panel | Hardcover pushes (range) | A | mimir | `sum(increase(hardcover_calls_total{namespace="boomtime",outcome="executed"}[$__range]))` | query executed and returned data |
| [x] | PASS | panel | Heartbeat ingest rate | A | mimir | `sum(rate(boomtime_heartbeats_ingested_total{namespace="boomtime"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Job run rate by kind & status | A | mimir | `sum by (kind, status) (rate(jobs_run_total{namespace="boomtime"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Job-limiter events by kind & outcome | A | mimir | `sum by (kind, outcome) (rate(jobs_limiter_events_total{namespace="boomtime"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | External call rates — Hardcover & Amazon | A | mimir | `sum by (outcome) (rate(hardcover_calls_total{namespace="boomtime"}[$__rate_interval]))` | query executed and returned data |
| [ ] | EMPTY | panel | External call rates — Hardcover & Amazon | B | mimir | `sum by (transport) (rate(amazon_calls_total{namespace="boomtime"}[$__rate_interval]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | AMQP job deliveries by outcome | A | mimir | `sum by (queue, outcome) (rate(boomtime_amqp_deliveries_total{namespace="boomtime"}[$__rate_interval]))` | query executed successfully but returned no data |
| [x] | PASS | panel | Reading-monitor active books | A | mimir | `sum by (source) (boomtime_reading_monitor_active_books{namespace="boomtime"})` | query executed and returned data |
| [ ] | EMPTY | panel | Reading-monitor advance rate | A | mimir | `sum by (source) (rate(boomtime_reading_monitor_advances_total{namespace="boomtime"}[$__rate_interval]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Job runs by kind | A | loki-v2 | `sum by (kind) (count_over_time({namespace="boomtime", app_kubernetes_io_name=~"$proc"} \|~ "jobs: done\|jobs: failed" \| json \| msg =~ `jobs: (done\|failed.*)` \| kind =~ "$kind" [$bucket]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Job kinds over the range | A | loki-v2 | `sum by (kind) (count_over_time({namespace="boomtime", app_kubernetes_io_name=~"$proc"} \|= "jobs: done" \| json \| msg = "jobs: done" \| kind =~ "$kind" [$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Job kinds over the range | B | loki-v2 | `sum by (kind) (count_over_time({namespace="boomtime", app_kubernetes_io_name=~"$proc"} \|= "jobs: retry scheduled" \| json \| kind =~ "$kind" [$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Job kinds over the range | C | loki-v2 | `sum by (kind) (count_over_time({namespace="boomtime", app_kubernetes_io_name=~"$proc"} \|= "jobs: failed (attempts exhausted)" \| json \| kind =~ "$kind" [$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Job outcomes over time | A | loki-v2 | `sum(count_over_time({namespace="boomtime", app_kubernetes_io_name=~"$proc"} \|= "jobs: done" \| json \| msg = "jobs: done" \| kind =~ "$kind" [$bucket]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Job outcomes over time | B | loki-v2 | `sum(count_over_time({namespace="boomtime", app_kubernetes_io_name=~"$proc"} \|= "jobs: retry scheduled" \| json \| kind =~ "$kind" [$bucket]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Job outcomes over time | C | loki-v2 | `sum(count_over_time({namespace="boomtime", app_kubernetes_io_name=~"$proc"} \|= "jobs: failed (attempts exhausted)" \| json \| kind =~ "$kind" [$bucket]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Job failures and retries — with the reason | A | loki-v2 | `{namespace="boomtime", app_kubernetes_io_name=~"$proc"} \|~ "jobs: failed\|jobs: retry scheduled\|jobs: no handler" \| json \| msg =~ `jobs: (failed.*\|retry scheduled\|no handler for kind)` \| kind =~ "$kind" \| line_format "{{.kind}}  job={{.id}}  attempt={{.attempt}}{{.attempts}}  {{.msg}}  {{.err}}"` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Wakatime heartbeats imported | A | loki-v2 | `sum(sum_over_time({namespace="boomtime", app_kubernetes_io_name=~"$proc"} \|= "import completed" \| json \| unwrap imported [$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Audible library items backfilled | A | loki-v2 | `sum(sum_over_time({namespace="boomtime", app_kubernetes_io_name=~"$proc"} \|= "audible backfill complete" \| json \| unwrap libraryItems [$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Books newly finished | A | loki-v2 | `sum(sum_over_time({namespace="boomtime", app_kubernetes_io_name=~"$proc"} \|= "audible forward: newly finished" \| json \| unwrap count [$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Pushed to Hardcover | A | loki-v2 | `sum(count_over_time({namespace="boomtime", app_kubernetes_io_name=~"$proc"} \|= "hardcover: pushed finished book" [$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Label-image generation runs | A | loki-v2 | `sum(sum_over_time({namespace="boomtime", app_kubernetes_io_name=~"$proc"} \|= "labelimages: run complete" \| json \| unwrap generated [$bucket]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Label-image generation runs | B | loki-v2 | `sum(sum_over_time({namespace="boomtime", app_kubernetes_io_name=~"$proc"} \|= "labelimages: run complete" \| json \| unwrap skipped_existing [$bucket]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Label-image generation runs | C | loki-v2 | `sum(sum_over_time({namespace="boomtime", app_kubernetes_io_name=~"$proc"} \|= "labelimages: run complete" \| json \| unwrap failed [$bucket]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Domain outcome feed | A | loki-v2 | `{namespace="boomtime", app_kubernetes_io_name=~"$proc"} \|~ "import completed\|audible backfill complete\|audible forward: newly finished\|hardcover: pushed finished book\|labelimages: run complete\|labelimages: saved\|avatar regen: saved" \| json \| line_format "{{.msg}}  {{.user}}{{.id}}"` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Kindle reading minutes (range) | A | mimir | `sum(increase(boomtime_reading_activity_seconds_total{namespace="boomtime",source="kindle"}[$__range])) / 60` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Reading activity landed (rate) | A | mimir | `sum by (source) (rate(boomtime_reading_activity_seconds_total{namespace="boomtime"}[$__rate_interval]))` | query executed successfully but returned no data |
| [x] | PASS | panel | Most-requested domain endpoints | A | loki-v2 | `topk(20, sum by (path) (count_over_time({namespace="boomtime", app_kubernetes_io_name=~"$proc"} \|~ "/api/" \| json \| msg = "http request" \| method = "GET" \| path =~ `/api/.+` [$__range])))` | query executed and returned data |
| [ ] | EMPTY | panel | Read-path errors by status | A | loki-v2 | `sum by (status) (count_over_time({namespace="boomtime", app_kubernetes_io_name=~"$proc"} \|~ "/api/" \| json \| msg = "http request" \| method = "GET" \| path =~ `/api/.+` \| status >= 400 [$bucket]))` | query executed successfully but returned no data |
| [x] | PASS | panel | Top warnings and errors | A | loki-v2 | `topk(20, sum by (level, msg) (count_over_time({namespace="boomtime", app_kubernetes_io_name=~"$proc"} \|~ `"level":"(WARN\|ERROR)"` \| json [$__range])))` | query executed and returned data |
| [ ] | EMPTY | panel | Warnings and errors (live) | A | loki-v2 | `{namespace="boomtime", app_kubernetes_io_name=~"$proc"} \|~ `"level":"(WARN\|ERROR)"` \| json \| line_format "{{.level}}  {{.msg}}  {{.err}}"` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Ingest and aggregation failures | A | loki-v2 | `{namespace="boomtime", app_kubernetes_io_name=~"$proc"} \|~ "failed to store heartbeats\|aggregation query failed\|derived status failed\|failed to store" \| json \| line_format "{{.level}}  {{.msg}}  {{.err}}"` | query executed successfully but returned no data |

### boomtime · Reading monitor (whispersync cadence) (`boomtime-reading-monitor`)

Folder: Apps · Panels: 15 · Queries: 15

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [ ] | EMPTY | variable | Variable: source | source | mimir | `label_values(boomtime_reading_monitor_advances_total, source)` | query executed successfully but returned no data |
| [x] | PASS | panel | Active books | A | mimir | `sum(boomtime_reading_monitor_active_books{namespace="boomtime", source=~"$source"})` | query executed and returned data |
| [ ] | EMPTY | panel | Advance rate | A | mimir | `sum(rate(boomtime_reading_monitor_advances_total{namespace="boomtime", source=~"$source"}[$__rate_interval]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | p50 advance interval (≈ T2) | A | mimir | `histogram_quantile(0.50, sum(rate(boomtime_reading_monitor_advance_interval_seconds_bucket{namespace="boomtime", source=~"$source"}[$__rate_interval])) by (le))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | p90 advance interval (≈ G) | A | mimir | `histogram_quantile(0.90, sum(rate(boomtime_reading_monitor_advance_interval_seconds_bucket{namespace="boomtime", source=~"$source"}[$__rate_interval])) by (le))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | p99 advance interval | A | mimir | `histogram_quantile(0.99, sum(rate(boomtime_reading_monitor_advance_interval_seconds_bucket{namespace="boomtime", source=~"$source"}[$__rate_interval])) by (le))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Advance-interval percentiles (p50 / p90 / p99) | A | mimir | `histogram_quantile(0.50, sum(rate(boomtime_reading_monitor_advance_interval_seconds_bucket{namespace="boomtime", source=~"$source"}[$__rate_interval])) by (le))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Advance-interval percentiles (p50 / p90 / p99) | B | mimir | `histogram_quantile(0.90, sum(rate(boomtime_reading_monitor_advance_interval_seconds_bucket{namespace="boomtime", source=~"$source"}[$__rate_interval])) by (le))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Advance-interval percentiles (p50 / p90 / p99) | C | mimir | `histogram_quantile(0.99, sum(rate(boomtime_reading_monitor_advance_interval_seconds_bucket{namespace="boomtime", source=~"$source"}[$__rate_interval])) by (le))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Advance-interval histogram | A | mimir | `sum(rate(boomtime_reading_monitor_advance_interval_seconds_bucket{namespace="boomtime", source=~"$source"}[$__rate_interval])) by (le)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Advance rate by source | A | mimir | `sum by (source) (rate(boomtime_reading_monitor_advances_total{namespace="boomtime", source=~"$source"}[$__rate_interval]))` | query executed successfully but returned no data |
| [x] | PASS | panel | Active books over time | A | mimir | `sum by (source) (boomtime_reading_monitor_active_books{namespace="boomtime", source=~"$source"})` | query executed and returned data |
| [ ] | EMPTY | panel | Seconds per location (p50 / p90) | A | mimir | `histogram_quantile(0.50, sum(rate(boomtime_reading_monitor_sec_per_location_bucket{namespace="boomtime", source=~"$source"}[$__rate_interval])) by (le))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Seconds per location (p50 / p90) | B | mimir | `histogram_quantile(0.90, sum(rate(boomtime_reading_monitor_sec_per_location_bucket{namespace="boomtime", source=~"$source"}[$__rate_interval])) by (le))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Whispersync advances (book · location · Δloc · interval) | A | loki-v2 | `{namespace="boomtime"} \|~ `reading monitor: advance` \| json \| source =~ `$source` \| line_format "{{.source}}  {{.owner}}  {{.book}}  loc={{.location}}  Δloc={{.dloc}}  interval={{.interval_s}}s  ({{.creation_time}})  asin={{.asin}}"` | query executed successfully but returned no data |

### boomtime · Service & Infra (`boomtime-service-infra`)

Folder: App · Panels: 44 · Queries: 53

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | panel | Build | A | mimir | `boomtime_build_info{namespace="boomtime"}` | query executed and returned data |
| [x] | PASS | panel | Request rate | A | mimir | `sum(rate(http_requests_total{namespace="boomtime"}[$__rate_interval]))` | query executed and returned data |
| [ ] | EMPTY | panel | 5xx error ratio | A | mimir | `sum(rate(http_requests_total{namespace="boomtime",status_class="5xx"}[$__rate_interval])) / clamp_min(sum(rate(http_requests_total{namespace="boomtime"}[$__rate_interval])), 1e-9)` | query executed successfully but returned no data |
| [x] | PASS | panel | p95 latency | A | mimir | `histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{namespace="boomtime"}[$__rate_interval])))` | query executed and returned data |
| [x] | PASS | panel | WS connections | A | mimir | `sum(ws_active_connections{namespace="boomtime"})` | query executed and returned data |
| [x] | PASS | panel | Worker replicas | A | mimir | `sum(kube_deployment_status_replicas{namespace="boomtime", deployment="boomtime-worker"})` | query executed and returned data |
| [x] | PASS | panel | Request rate by route | A | mimir | `sum by (route) (rate(http_requests_total{namespace="boomtime"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Requests by status class | A | mimir | `sum by (status_class) (rate(http_requests_total{namespace="boomtime"}[$__rate_interval]))` | query executed and returned data |
| [ ] | EMPTY | panel | Error ratio by route (4xx+5xx) | A | mimir | `sum by (route) (rate(http_requests_total{namespace="boomtime",status_class=~"4xx\|5xx"}[$__rate_interval])) / clamp_min(sum by (route) (rate(http_requests_total{namespace="boomtime"}[$__rate_interval])), 1e-9)` | query executed successfully but returned no data |
| [x] | PASS | panel | Latency p50 / p95 by route | A | mimir | `histogram_quantile(0.95, sum by (le, route) (rate(http_request_duration_seconds_bucket{namespace="boomtime"}[$__rate_interval])))` | query executed and returned data |
| [x] | PASS | panel | Latency p50 / p95 by route | B | mimir | `histogram_quantile(0.50, sum by (le, route) (rate(http_request_duration_seconds_bucket{namespace="boomtime"}[$__rate_interval])))` | query executed and returned data |
| [x] | PASS | panel | Outbound rate by host | A | mimir | `sum by (host) (rate(http_client_requests_total{namespace="boomtime"}[$__rate_interval]))` | query executed and returned data |
| [ ] | EMPTY | panel | Outbound error ratio by host | A | mimir | `sum by (host) (rate(http_client_requests_total{namespace="boomtime",status_class=~"4xx\|5xx\|error"}[$__rate_interval])) / clamp_min(sum by (host) (rate(http_client_requests_total{namespace="boomtime"}[$__rate_interval])), 1e-9)` | query executed successfully but returned no data |
| [x] | PASS | panel | Outbound p95 latency by host | A | mimir | `histogram_quantile(0.95, sum by (le, host) (rate(http_client_request_duration_seconds_bucket{namespace="boomtime"}[$__rate_interval])))` | query executed and returned data |
| [x] | PASS | panel | Job-limiter headroom (in-flight / max) by kind | A | mimir | `sum by (kind) (jobs_limiter_in_flight{namespace="boomtime"}) / clamp_min(max by (kind) (jobs_limiter_max{namespace="boomtime"}), 1)` | query executed and returned data |
| [x] | PASS | panel | Limiter events by outcome | A | mimir | `sum by (outcome) (rate(jobs_limiter_events_total{namespace="boomtime"}[$__rate_interval]))` | query executed and returned data |
| [ ] | EMPTY | panel | At-limit (back-pressure) rate by kind | A | mimir | `sum by (kind) (rate(jobs_limiter_events_total{namespace="boomtime",outcome="atlimit"}[$__rate_interval]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | HTTP rate-limiter decisions | A | mimir | `sum by (scope) (rate(http_ratelimit_decisions_total{namespace="boomtime",decision="throttled"}[$__rate_interval]))` | query executed successfully but returned no data |
| [x] | PASS | panel | HTTP rate-limiter decisions | B | mimir | `sum(rate(http_ratelimit_decisions_total{namespace="boomtime",decision="allowed"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Goroutines | A | mimir | `sum(go_goroutines{namespace="boomtime"})` | query executed and returned data |
| [x] | PASS | panel | Memory (heap in-use / RSS) | A | mimir | `sum(go_memstats_heap_inuse_bytes{namespace="boomtime"})` | query executed and returned data |
| [x] | PASS | panel | Memory (heap in-use / RSS) | B | mimir | `sum(process_resident_memory_bytes{namespace="boomtime"})` | query executed and returned data |
| [x] | PASS | panel | CPU / open FDs | A | mimir | `sum(rate(process_cpu_seconds_total{namespace="boomtime"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | CPU / open FDs | B | mimir | `sum(process_open_fds{namespace="boomtime"})` | query executed and returned data |
| [x] | PASS | panel | DB pool — connections vs max | A | mimir | `sum(db_pool_acquired_conns{namespace="boomtime"})` | query executed and returned data |
| [x] | PASS | panel | DB pool — connections vs max | B | mimir | `sum(db_pool_idle_conns{namespace="boomtime"})` | query executed and returned data |
| [x] | PASS | panel | DB pool — connections vs max | C | mimir | `sum(db_pool_constructing_conns{namespace="boomtime"})` | query executed and returned data |
| [x] | PASS | panel | DB pool — connections vs max | D | mimir | `sum(db_pool_total_conns{namespace="boomtime"})` | query executed and returned data |
| [x] | PASS | panel | DB pool — connections vs max | E | mimir | `max(db_pool_max_conns{namespace="boomtime"})` | query executed and returned data |
| [x] | PASS | panel | DB pool — acquire pressure | A | mimir | `sum(rate(db_pool_acquire_count{namespace="boomtime"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | DB pool — acquire pressure | B | mimir | `sum(rate(db_pool_empty_acquire_count{namespace="boomtime"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | DB pool — acquire pressure | C | mimir | `sum(rate(db_pool_acquire_duration_seconds_total{namespace="boomtime"}[$__rate_interval])) / clamp_min(sum(rate(db_pool_acquire_count{namespace="boomtime"}[$__rate_interval])), 1e-9)` | query executed and returned data |
| [x] | PASS | panel | Redis pool — hit ratio by purpose | A | mimir | `sum by (purpose) (rate(redis_pool_hits_total{namespace="boomtime"}[$__rate_interval])) / clamp_min(sum by (purpose) (rate(redis_pool_hits_total{namespace="boomtime"}[$__rate_interval])) + sum by (purpose) (rate(redis_pool_misses_total{namespace="boomtime"}[$__rate_interval])), 1e-9)` | query executed and returned data |
| [x] | PASS | panel | Redis pool — conns & timeouts | A | mimir | `sum by (purpose) (redis_pool_total_conns{namespace="boomtime"})` | query executed and returned data |
| [x] | PASS | panel | Redis pool — conns & timeouts | B | mimir | `sum by (purpose) (redis_pool_idle_conns{namespace="boomtime"})` | query executed and returned data |
| [x] | PASS | panel | Redis pool — conns & timeouts | C | mimir | `sum by (purpose) (rate(redis_pool_timeouts_total{namespace="boomtime"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Cache hit rate by cache | A | mimir | `sum by (cache) (rate(cache_requests_total{namespace="boomtime",result="hit"}[$__rate_interval])) / clamp_min(sum by (cache) (rate(cache_requests_total{namespace="boomtime"}[$__rate_interval])), 1e-9)` | query executed and returned data |
| [ ] | EMPTY | panel | Queue depth (ready) |  | mimir | `sum(rabbitmq_queue_messages_ready{namespace="boomtime", queue="boomtime.image-jobs"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Consumers |  | mimir | `sum(rabbitmq_queue_consumers{namespace="boomtime", queue="boomtime.image-jobs"})` | query executed successfully but returned no data |
| [x] | PASS | panel | boomtime-worker replicas |  | mimir | `sum(kube_deployment_status_replicas{namespace="boomtime", deployment="boomtime-worker"})` | query executed and returned data |
| [ ] | EMPTY | panel | Unacked (in-flight) |  | mimir | `sum(rabbitmq_queue_messages_unacked{namespace="boomtime", queue="boomtime.image-jobs"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Queue depth over time |  | mimir | `sum(rabbitmq_queue_messages_ready{namespace="boomtime", queue="boomtime.image-jobs"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Queue depth over time |  | mimir | `sum(rabbitmq_queue_messages_unacked{namespace="boomtime", queue="boomtime.image-jobs"})` | query executed successfully but returned no data |
| [x] | PASS | panel | boomtime-worker replicas (KEDA scaling activity) |  | mimir | `sum(kube_deployment_status_replicas{namespace="boomtime", deployment="boomtime-worker"})` | query executed and returned data |
| [x] | PASS | panel | boomtime-worker replicas (KEDA scaling activity) |  | mimir | `sum(kube_deployment_spec_replicas{namespace="boomtime", deployment="boomtime-worker"})` | query executed and returned data |
| [ ] | EMPTY | panel | Publish / deliver rate |  | mimir | `sum(rate(rabbitmq_queue_messages_published_total{namespace="boomtime", queue="boomtime.image-jobs"}[5m]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Publish / deliver rate |  | mimir | `sum(rate(rabbitmq_queue_messages_delivered_total{namespace="boomtime", queue="boomtime.image-jobs"}[5m]))` | query executed successfully but returned no data |
| [x] | PASS | panel | Scaler active (queue has work) |  | mimir | `max(keda_scaler_active{scaledObject="boomtime-worker"})` | query executed and returned data |
| [x] | PASS | panel | ScaledObject paused |  | mimir | `max(keda_scaled_object_paused{scaledObject="boomtime-worker"})` | query executed and returned data |
| [x] | PASS | panel | Scaler errors (5m rate) |  | mimir | `sum(rate(keda_scaled_object_errors_total{scaledObject="boomtime-worker"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Trigger metric value (queue depth KEDA reads) vs threshold |  | mimir | `max(keda_scaler_metrics_value{scaledObject="boomtime-worker"})` | query executed and returned data |
| [x] | PASS | panel | Trigger metric value (queue depth KEDA reads) vs threshold |  | mimir | `vector(5)` | query executed and returned data |
| [x] | PASS | panel | All ScaledObjects — active state (cluster) |  | mimir | `max by (scaledObject, namespace) (keda_scaler_active)` | query executed and returned data |

### Catalyst K8s — Full System Ops (`catalyst-k8s-dashboard`)

Folder: Cluster · Panels: 41 · Queries: 51

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: namespace | namespace | mimir | `label_values(kube_pod_info{job="kube-state-metrics"}, namespace)` | query executed and returned data |
| [x] | PASS | variable | Variable: node | node | mimir | `label_values(kube_node_info{job="kube-state-metrics"}, node)` | query executed and returned data |
| [x] | PASS | panel | Nodes Ready | A | mimir | `sum(kube_node_status_condition{job="kube-state-metrics", condition="Ready", status="true"})` | query executed and returned data |
| [x] | PASS | panel | Nodes NotReady | A | mimir | `sum(kube_node_status_condition{job="kube-state-metrics", condition="Ready", status="false"}) + sum(kube_node_status_condition{job="kube-state-metrics", condition="Ready", status="unknown"})` | query executed and returned data |
| [x] | PASS | panel | Pods Running | A | mimir | `sum(kube_pod_status_phase{job="kube-state-metrics", phase="Running", namespace=~"$namespace"})` | query executed and returned data |
| [x] | PASS | panel | Pods Pending | A | mimir | `sum(kube_pod_status_phase{job="kube-state-metrics", phase="Pending", namespace=~"$namespace"})` | query executed and returned data |
| [x] | PASS | panel | Pods Failed | A | mimir | `sum(kube_pod_status_phase{job="kube-state-metrics", phase="Failed", namespace=~"$namespace"})` | query executed and returned data |
| [x] | PASS | panel | Container Restarts (1h) | A | mimir | `sum(increase(kube_pod_container_status_restarts_total{job="kube-state-metrics", namespace=~"$namespace"}[1h]))` | query executed and returned data |
| [x] | PASS | panel | CPU Committed | A | mimir | `100 * sum(kube_pod_container_resource_requests{job="kube-state-metrics", resource="cpu"}) / sum(kube_node_status_allocatable{job="kube-state-metrics", resource="cpu"})` | query executed and returned data |
| [x] | PASS | panel | Memory Committed | A | mimir | `100 * sum(kube_pod_container_resource_requests{job="kube-state-metrics", resource="memory"}) / sum(kube_node_status_allocatable{job="kube-state-metrics", resource="memory"})` | query executed and returned data |
| [ ] | EMPTY | panel | Pods not Running | A | mimir | `kube_pod_status_phase{job="kube-state-metrics", phase=~"Pending\|Failed\|Unknown", namespace=~"$namespace"} > 0` | query executed successfully but returned no data |
| [x] | PASS | panel | Top Container Restarts (1h) | A | mimir | `topk(20, sum by (namespace, pod, container) (increase(kube_pod_container_status_restarts_total{job="kube-state-metrics", namespace=~"$namespace"}[1h]))) > 0` | query executed and returned data |
| [x] | PASS | panel | Unhealthy Workloads (deployments) | A | mimir | `(kube_deployment_spec_replicas{job="kube-state-metrics", namespace=~"$namespace"} - kube_deployment_status_replicas_available{job="kube-state-metrics", namespace=~"$namespace"}) > 0` | query executed and returned data |
| [x] | PASS | panel | Cluster CPU — requests / limits / usage / allocatable | A | mimir | `sum(rate(container_cpu_usage_seconds_total{container!="", namespace=~"$namespace"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Cluster CPU — requests / limits / usage / allocatable | B | mimir | `sum(kube_pod_container_resource_requests{job="kube-state-metrics", resource="cpu", namespace=~"$namespace"})` | query executed and returned data |
| [x] | PASS | panel | Cluster CPU — requests / limits / usage / allocatable | C | mimir | `sum(kube_pod_container_resource_limits{job="kube-state-metrics", resource="cpu", namespace=~"$namespace"})` | query executed and returned data |
| [x] | PASS | panel | Cluster CPU — requests / limits / usage / allocatable | D | mimir | `sum(kube_node_status_allocatable{job="kube-state-metrics", resource="cpu", node=~"$node"})` | query executed and returned data |
| [x] | PASS | panel | Cluster Memory — requests / limits / usage / allocatable | A | mimir | `sum(container_memory_working_set_bytes{container!="", namespace=~"$namespace"})` | query executed and returned data |
| [x] | PASS | panel | Cluster Memory — requests / limits / usage / allocatable | B | mimir | `sum(kube_pod_container_resource_requests{job="kube-state-metrics", resource="memory", namespace=~"$namespace"})` | query executed and returned data |
| [x] | PASS | panel | Cluster Memory — requests / limits / usage / allocatable | C | mimir | `sum(kube_pod_container_resource_limits{job="kube-state-metrics", resource="memory", namespace=~"$namespace"})` | query executed and returned data |
| [x] | PASS | panel | Cluster Memory — requests / limits / usage / allocatable | D | mimir | `sum(kube_node_status_allocatable{job="kube-state-metrics", resource="memory", node=~"$node"})` | query executed and returned data |
| [x] | PASS | panel | CPU requests % of allocatable, per node | A | mimir | `100 * sum by (node) (kube_pod_container_resource_requests{job="kube-state-metrics", resource="cpu", node=~"$node"}) / sum by (node) (kube_node_status_allocatable{job="kube-state-metrics", resource="cpu", node=~"$node"})` | query executed and returned data |
| [x] | PASS | panel | Memory requests % of allocatable, per node | A | mimir | `100 * sum by (node) (kube_pod_container_resource_requests{job="kube-state-metrics", resource="memory", node=~"$node"}) / sum by (node) (kube_node_status_allocatable{job="kube-state-metrics", resource="memory", node=~"$node"})` | query executed and returned data |
| [x] | PASS | panel | Pods % of capacity, per node | A | mimir | `100 * count by (node) (kube_pod_info{job="kube-state-metrics", node=~"$node"}) / sum by (node) (kube_node_status_capacity{job="kube-state-metrics", resource="pods", node=~"$node"})` | query executed and returned data |
| [x] | PASS | panel | Node Inventory | Ready | mimir | `max by (node) (kube_node_status_condition{job="kube-state-metrics", condition="Ready", status="true", node=~"$node"})` | query executed and returned data |
| [x] | PASS | panel | Node Inventory | CPUa | mimir | `sum by (node) (kube_node_status_allocatable{job="kube-state-metrics", resource="cpu", node=~"$node"})` | query executed and returned data |
| [x] | PASS | panel | Node Inventory | CPUp | mimir | `100 * sum by (node) (kube_pod_container_resource_requests{job="kube-state-metrics", resource="cpu", node=~"$node"}) / sum by (node) (kube_node_status_allocatable{job="kube-state-metrics", resource="cpu", node=~"$node"})` | query executed and returned data |
| [x] | PASS | panel | Node Inventory | MEMa | mimir | `sum by (node) (kube_node_status_allocatable{job="kube-state-metrics", resource="memory", node=~"$node"})` | query executed and returned data |
| [x] | PASS | panel | Node Inventory | MEMp | mimir | `100 * sum by (node) (kube_pod_container_resource_requests{job="kube-state-metrics", resource="memory", node=~"$node"}) / sum by (node) (kube_node_status_allocatable{job="kube-state-metrics", resource="memory", node=~"$node"})` | query executed and returned data |
| [x] | PASS | panel | Node Inventory | Pods | mimir | `count by (node) (kube_pod_info{job="kube-state-metrics", node=~"$node"})` | query executed and returned data |
| [x] | PASS | panel | Node Inventory | PodP | mimir | `100 * count by (node) (kube_pod_info{job="kube-state-metrics", node=~"$node"}) / sum by (node) (kube_node_status_capacity{job="kube-state-metrics", resource="pods", node=~"$node"})` | query executed and returned data |
| [x] | PASS | panel | Top 15 pods by CPU usage | A | mimir | `topk(15, sum by (namespace, pod) (rate(container_cpu_usage_seconds_total{container!="", namespace=~"$namespace"}[5m])))` | query executed and returned data |
| [x] | PASS | panel | Top 15 pods by Memory (working set) | A | mimir | `topk(15, sum by (namespace, pod) (container_memory_working_set_bytes{container!="", namespace=~"$namespace"}))` | query executed and returned data |
| [x] | PASS | panel | etcd Has Leader | A | mimir | `min(etcd_server_has_leader{job="kube-etcd"})` | query executed and returned data |
| [x] | PASS | panel | etcd Leader Changes (1h) | A | mimir | `max(increase(etcd_server_leader_changes_seen_total{job="kube-etcd"}[1h]))` | query executed and returned data |
| [x] | PASS | panel | etcd DB % of Quota | A | mimir | `100 * max(etcd_mvcc_db_total_size_in_bytes{job="kube-etcd"} / etcd_server_quota_backend_bytes{job="kube-etcd"})` | query executed and returned data |
| [x] | PASS | panel | apiserver Request Rate | A | mimir | `sum(rate(apiserver_request_total[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | apiserver 5xx % | A | mimir | `(sum(rate(apiserver_request_total{code=~"5.."}[$__rate_interval])) or vector(0)) / sum(rate(apiserver_request_total[$__rate_interval])) * 100` | query executed and returned data |
| [x] | PASS | panel | KCM Workqueue Depth | A | mimir | `sum(workqueue_depth{job="kube-controller-manager-metrics"})` | query executed and returned data |
| [x] | PASS | panel | etcd disk sync p99 — WAL fsync / backend commit | A | mimir | `histogram_quantile(0.99, sum by(le)(rate(etcd_disk_wal_fsync_duration_seconds_bucket[$__rate_interval])))` | query executed and returned data |
| [x] | PASS | panel | etcd disk sync p99 — WAL fsync / backend commit | B | mimir | `histogram_quantile(0.99, sum by(le)(rate(etcd_disk_backend_commit_duration_seconds_bucket[$__rate_interval])))` | query executed and returned data |
| [x] | PASS | panel | etcd DB size vs quota | A | mimir | `max(etcd_mvcc_db_total_size_in_bytes{job="kube-etcd"})` | query executed and returned data |
| [x] | PASS | panel | etcd DB size vs quota | B | mimir | `max(etcd_server_quota_backend_bytes{job="kube-etcd"})` | query executed and returned data |
| [x] | PASS | panel | apiserver request rate | A | mimir | `sum(rate(apiserver_request_total[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | apiserver 5xx error % | A | mimir | `(sum(rate(apiserver_request_total{code=~"5.."}[$__rate_interval])) or vector(0)) / sum(rate(apiserver_request_total[$__rate_interval])) * 100` | query executed and returned data |
| [x] | PASS | panel | apiserver p99 latency by verb | A | mimir | `histogram_quantile(0.99, sum by(le, verb)(rate(apiserver_request_duration_seconds_bucket{verb!~"WATCH\|CONNECT"}[$__rate_interval])))` | query executed and returned data |
| [x] | PASS | panel | Scheduler attempts by result | A | mimir | `sum by(result)(rate(scheduler_schedule_attempts_total{job="kube-scheduler-metrics"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Scheduler attempt duration p99 | A | mimir | `histogram_quantile(0.99, sum by(le)(rate(scheduler_scheduling_attempt_duration_seconds_bucket{job="kube-scheduler-metrics"}[$__rate_interval])))` | query executed and returned data |
| [x] | PASS | panel | KCM workqueue depth by queue (top 10) | A | mimir | `topk(10, sum by(name)(workqueue_depth{job="kube-controller-manager-metrics"}))` | query executed and returned data |
| [x] | PASS | panel | KCM workqueue add rate | A | mimir | `sum(rate(workqueue_adds_total{job="kube-controller-manager-metrics"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | KCM workqueue work duration p99 | A | mimir | `histogram_quantile(0.99, sum by(le)(rate(workqueue_work_duration_seconds_bucket{job="kube-controller-manager-metrics"}[$__rate_interval])))` | query executed and returned data |

### Central Cluster Storage (`central-cluster-storage`)

Folder: Storage · Panels: 68 · Queries: 68

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: node | node | mimir | `label_values(node_filesystem_size_bytes, node)` | query executed and returned data |
| [x] | PASS | variable | Variable: namespace | namespace | mimir | `label_values(kube_persistentvolumeclaim_info{job="kube-state-metrics"}, namespace)` | query executed and returned data |
| [x] | PASS | variable | Variable: storageclass | storageclass | mimir | `label_values(kube_persistentvolumeclaim_info{job="kube-state-metrics"}, storageclass)` | query executed and returned data |
| [x] | PASS | variable | Variable: pvc | pvc | mimir | `label_values(kubelet_volume_stats_capacity_bytes, persistentvolumeclaim)` | query executed and returned data |
| [x] | PASS | panel | Physical Capacity (raw) | A | mimir | `sum(node_filesystem_size_bytes{fstype!~"tmpfs\|overlay\|ramfs\|squashfs\|iso9660\|rootfs\|autofs\|fuse.*\|nfs.*\|cifs\|devtmpfs\|mqueue\|tracefs\|debugfs\|bpf\|cgroup.*\|configfs\|securityfs\|pstore\|efivarfs",node!=""})` | query executed and returned data |
| [x] | PASS | panel | Physical Used | A | mimir | `sum(node_filesystem_size_bytes{fstype!~"tmpfs\|overlay\|ramfs\|squashfs\|iso9660\|rootfs\|autofs\|fuse.*\|nfs.*\|cifs\|devtmpfs\|mqueue\|tracefs\|debugfs\|bpf\|cgroup.*\|configfs\|securityfs\|pstore\|efivarfs",node!=""}) - sum(node_filesystem_avail_bytes{fstype!~"tmpfs\|overlay\|ramfs\|squashfs\|iso9660\|rootfs\|autofs\|fuse.*\|nfs.*\|cifs\|devtmpfs\|mqueue\|tracefs\|debugfs\|bpf\|cgroup.*\|configfs\|securityfs\|pstore\|efivarfs",node!=""})` | query executed and returned data |
| [x] | PASS | panel | PV Capacity (provisioned) | A | mimir | `sum(kube_persistentvolume_capacity_bytes{job="kube-state-metrics"})` | query executed and returned data |
| [x] | PASS | panel | PVC Requested (allocated) | A | mimir | `sum(kube_persistentvolumeclaim_resource_requests_storage_bytes{job="kube-state-metrics"})` | query executed and returned data |
| [x] | PASS | panel | MinIO Used | A | mimir | `minio_cluster_usage_total_bytes` | query executed and returned data |
| [x] | PASS | panel | NAS Free (NFS backend) | A | mimir | `min(nfs_backend_avail_bytes)` | query executed and returned data |
| [x] | PASS | panel | Largest PVC | A | mimir | `max(kube_persistentvolumeclaim_resource_requests_storage_bytes{job="kube-state-metrics"})` | query executed and returned data |
| [x] | PASS | panel | Databases Total | A | mimir | `sum(cnpg_pg_database_size_bytes{datname!~"template.*"})` | query executed and returned data |
| [x] | PASS | panel | Per-node disk %used | A | mimir | `100 * (1 - sum by(node)(node_filesystem_avail_bytes{fstype!~"tmpfs\|overlay\|ramfs\|squashfs\|iso9660\|rootfs\|autofs\|fuse.*\|nfs.*\|cifs\|devtmpfs\|mqueue\|tracefs\|debugfs\|bpf\|cgroup.*\|configfs\|securityfs\|pstore\|efivarfs",node!=""}) / sum by(node)(node_filesystem_size_bytes{fstype!~"tmpfs\|overlay\|ramfs\|squashfs\|iso9660\|rootfs\|autofs\|fuse.*\|nfs.*\|cifs\|devtmpfs\|mqueue\|tracefs\|debugfs\|bpf\|cgroup.*\|configfs\|securityfs\|pstore\|efivarfs",node!=""}))` | query executed and returned data |
| [x] | PASS | panel | Node filesystem used bytes (stacked) | A | mimir | `sum by(node)(node_filesystem_size_bytes{fstype!~"tmpfs\|overlay\|ramfs\|squashfs\|iso9660\|rootfs\|autofs\|fuse.*\|nfs.*\|cifs\|devtmpfs\|mqueue\|tracefs\|debugfs\|bpf\|cgroup.*\|configfs\|securityfs\|pstore\|efivarfs",node!=""}) - sum by(node)(node_filesystem_avail_bytes{fstype!~"tmpfs\|overlay\|ramfs\|squashfs\|iso9660\|rootfs\|autofs\|fuse.*\|nfs.*\|cifs\|devtmpfs\|mqueue\|tracefs\|debugfs\|bpf\|cgroup.*\|configfs\|securityfs\|pstore\|efivarfs",node!=""})` | query executed and returned data |
| [x] | PASS | panel | Node filesystems | A | mimir | `node_filesystem_size_bytes{fstype!~"tmpfs\|overlay\|ramfs\|squashfs\|iso9660\|rootfs\|autofs\|fuse.*\|nfs.*\|cifs\|devtmpfs\|mqueue\|tracefs\|debugfs\|bpf\|cgroup.*\|configfs\|securityfs\|pstore\|efivarfs",node!=""}` | query executed and returned data |
| [x] | PASS | panel | Node filesystems | B | mimir | `node_filesystem_avail_bytes{fstype!~"tmpfs\|overlay\|ramfs\|squashfs\|iso9660\|rootfs\|autofs\|fuse.*\|nfs.*\|cifs\|devtmpfs\|mqueue\|tracefs\|debugfs\|bpf\|cgroup.*\|configfs\|securityfs\|pstore\|efivarfs",node!=""}` | query executed and returned data |
| [x] | PASS | panel | Node filesystems | C | mimir | `node_filesystem_size_bytes{fstype!~"tmpfs\|overlay\|ramfs\|squashfs\|iso9660\|rootfs\|autofs\|fuse.*\|nfs.*\|cifs\|devtmpfs\|mqueue\|tracefs\|debugfs\|bpf\|cgroup.*\|configfs\|securityfs\|pstore\|efivarfs",node!=""} - on(node,device,mountpoint,fstype) node_filesystem_avail_bytes{fstype!~"tmpfs\|overlay\|ramfs\|squashfs\|iso9660\|rootfs\|autofs\|fuse.*\|nfs.*\|cifs\|devtmpfs\|mqueue\|tracefs\|debugfs\|bpf\|cgroup.*\|configfs\|securityfs\|pstore\|efivarfs",node!=""}` | query executed and returned data |
| [x] | PASS | panel | Node filesystems | D | mimir | `100 * (1 - node_filesystem_avail_bytes{fstype!~"tmpfs\|overlay\|ramfs\|squashfs\|iso9660\|rootfs\|autofs\|fuse.*\|nfs.*\|cifs\|devtmpfs\|mqueue\|tracefs\|debugfs\|bpf\|cgroup.*\|configfs\|securityfs\|pstore\|efivarfs",node!=""} / on(node,device,mountpoint,fstype) node_filesystem_size_bytes{fstype!~"tmpfs\|overlay\|ramfs\|squashfs\|iso9660\|rootfs\|autofs\|fuse.*\|nfs.*\|cifs\|devtmpfs\|mqueue\|tracefs\|debugfs\|bpf\|cgroup.*\|configfs\|securityfs\|pstore\|efivarfs",node!=""})` | query executed and returned data |
| [x] | PASS | panel | PVC count | A | mimir | `count(kube_persistentvolumeclaim_info{job="kube-state-metrics"})` | query executed and returned data |
| [x] | PASS | panel | PVC Requested total | A | mimir | `sum(kube_persistentvolumeclaim_resource_requests_storage_bytes{job="kube-state-metrics"})` | query executed and returned data |
| [x] | PASS | panel | PV Capacity total | A | mimir | `sum(kube_persistentvolume_capacity_bytes{job="kube-state-metrics"})` | query executed and returned data |
| [x] | PASS | panel | Requested by StorageClass | A | mimir | `sum by(storageclass)(kube_persistentvolumeclaim_resource_requests_storage_bytes{job="kube-state-metrics"} * on(namespace,persistentvolumeclaim) group_left(storageclass) kube_persistentvolumeclaim_info{job="kube-state-metrics"})` | query executed and returned data |
| [x] | PASS | panel | Top 15 PVC consumers (requested) | A | mimir | `topk(15, sum by(namespace,persistentvolumeclaim)(kube_persistentvolumeclaim_resource_requests_storage_bytes{job="kube-state-metrics"}))` | query executed and returned data |
| [x] | PASS | panel | PVC requested over time by namespace | A | mimir | `sum by(namespace)(kube_persistentvolumeclaim_resource_requests_storage_bytes{job="kube-state-metrics"})` | query executed and returned data |
| [x] | PASS | panel | All PVCs | A | mimir | `kube_persistentvolumeclaim_resource_requests_storage_bytes{job="kube-state-metrics"} * on(namespace,persistentvolumeclaim) group_left(storageclass,volumename) kube_persistentvolumeclaim_info{job="kube-state-metrics"}` | query executed and returned data |
| [x] | PASS | panel | MinIO usable %used | A | mimir | `100 * minio_cluster_usage_total_bytes / minio_cluster_capacity_usable_total_bytes` | query executed and returned data |
| [x] | PASS | panel | Usable capacity | A | mimir | `minio_cluster_capacity_usable_total_bytes` | query executed and returned data |
| [x] | PASS | panel | Usable free | A | mimir | `minio_cluster_capacity_usable_free_bytes` | query executed and returned data |
| [x] | PASS | panel | Used | A | mimir | `minio_cluster_usage_total_bytes` | query executed and returned data |
| [x] | PASS | panel | Objects | A | mimir | `minio_cluster_usage_object_total` | query executed and returned data |
| [ ] | EMPTY | panel | Usage by bucket | A | mimir | `sum by(bucket)(minio_bucket_usage_total_bytes)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Bucket usage over time | A | mimir | `sum by(bucket)(minio_bucket_usage_total_bytes)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Objects per bucket over time | A | mimir | `sum by(bucket)(minio_bucket_usage_object_total)` | query executed successfully but returned no data |
| [x] | PASS | panel | DB total size | A | mimir | `sum(cnpg_pg_database_size_bytes{datname!~"template.*"})` | query executed and returned data |
| [x] | PASS | panel | DB count | A | mimir | `count(cnpg_pg_database_size_bytes{datname!~"template.*"})` | query executed and returned data |
| [x] | PASS | panel | Databases by size | A | mimir | `sum by(namespace,datname)(cnpg_pg_database_size_bytes{datname!~"template.*"})` | query executed and returned data |
| [x] | PASS | panel | Database size over time | A | mimir | `sum by(namespace,pod,datname)(cnpg_pg_database_size_bytes{datname!~"template.*"})` | query executed and returned data |
| [x] | PASS | panel | Database sizes | A | mimir | `cnpg_pg_database_size_bytes{datname!~"template.*"}` | query executed and returned data |
| [x] | PASS | panel | Last backup age | A | mimir | `time() - max(velero_backup_last_successful_timestamp)` | query executed and returned data |
| [x] | PASS | panel | Backup data (last) | A | mimir | `sum(velero_backup_tarball_size_bytes)` | query executed and returned data |
| [x] | PASS | panel | Velero backup size by schedule | A | mimir | `sum by(schedule)(velero_backup_tarball_size_bytes)` | query executed and returned data |
| [x] | PASS | panel | NAS volume size | A | mimir | `max(nfs_backend_size_bytes)` | query executed and returned data |
| [x] | PASS | panel | NAS used | A | mimir | `max(nfs_backend_used_bytes)` | query executed and returned data |
| [x] | PASS | panel | NAS free | A | mimir | `min(nfs_backend_avail_bytes)` | query executed and returned data |
| [x] | PASS | panel | NAS %used | A | mimir | `100 * max(nfs_backend_used_bytes) / max(nfs_backend_size_bytes)` | query executed and returned data |
| [x] | PASS | panel | NAS free over time | A | mimir | `nfs_backend_avail_bytes` | query executed and returned data |
| [x] | PASS | panel | Unbound / Pending PVCs | A | mimir | `count(kube_persistentvolumeclaim_status_phase{phase=~"Pending\|Lost"}==1) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | PVs Failed / Released | A | mimir | `count(kube_persistentvolume_status_phase{phase=~"Failed\|Released"}==1) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | Read-only mounts | A | mimir | `count(node_filesystem_readonly{fstype!~"tmpfs\|overlay\|ramfs\|squashfs\|iso9660\|rootfs\|autofs\|fuse.*\|nfs.*\|cifs\|devtmpfs\|mqueue\|tracefs\|debugfs\|bpf\|cgroup.*\|configfs\|securityfs\|pstore\|efivarfs"}==1) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | Device-error mounts | A | mimir | `count(node_filesystem_device_error{fstype!~"tmpfs\|overlay\|ramfs\|squashfs\|iso9660\|rootfs\|autofs\|fuse.*\|nfs.*\|cifs\|devtmpfs\|mqueue\|tracefs\|debugfs\|bpf\|cgroup.*\|configfs\|securityfs\|pstore\|efivarfs"}==1) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | NFS exporter up | A | mimir | `min(nfs_backend_scrape_success)` | query executed and returned data |
| [x] | PASS | panel | MinIO cluster health | A | mimir | `max(minio_cluster_health_status)` | query executed and returned data |
| [x] | PASS | panel | MinIO drives online | A | mimir | `max(minio_cluster_drive_online_total)` | query executed and returned data |
| [x] | PASS | panel | MinIO drives offline | A | mimir | `max(minio_cluster_drive_offline_total)` | query executed and returned data |
| [x] | PASS | panel | MinIO nodes online | A | mimir | `max(minio_cluster_nodes_online_total)` | query executed and returned data |
| [x] | PASS | panel | Per-node inode %used | A | mimir | `max by(node)(100*(1 - node_filesystem_files_free{fstype!~"tmpfs\|overlay\|ramfs\|squashfs\|iso9660\|rootfs\|autofs\|fuse.*\|nfs.*\|cifs\|devtmpfs\|mqueue\|tracefs\|debugfs\|bpf\|cgroup.*\|configfs\|securityfs\|pstore\|efivarfs",node!=""}/node_filesystem_files{fstype!~"tmpfs\|overlay\|ramfs\|squashfs\|iso9660\|rootfs\|autofs\|fuse.*\|nfs.*\|cifs\|devtmpfs\|mqueue\|tracefs\|debugfs\|bpf\|cgroup.*\|configfs\|securityfs\|pstore\|efivarfs",node!=""}))` | query executed and returned data |
| [x] | PASS | panel | Velero backup status by schedule | A | mimir | `velero_backup_last_status` | query executed and returned data |
| [x] | PASS | panel | Velero backup failure rate | A | mimir | `sum by(schedule)(rate(velero_backup_failure_total[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | NFS RPC retransmission rate | A | mimir | `sum by(instance)(rate(node_nfs_rpc_retransmissions_total[$__rate_interval]))` | query executed and returned data |
| [ ] | EMPTY | panel | Pending / Lost PVCs (by namespace) | A | mimir | `kube_persistentvolumeclaim_status_phase{phase=~"Pending\|Lost"}==1` | query executed successfully but returned no data |
| [x] | PASS | panel | NFS PVCs >85% full | A | mimir | `count(max by (namespace, persistentvolumeclaim) (100 * kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes) > 85) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | Projected full <7d | A | mimir | `count(max by (namespace, persistentvolumeclaim) (predict_linear(kubelet_volume_stats_available_bytes[24h], 7*86400)) < 0) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | NFS PVC fill — capacity / used / available / used-% | A | mimir | `max by (namespace, persistentvolumeclaim) (kubelet_volume_stats_capacity_bytes{persistentvolumeclaim=~"$pvc"})` | query executed and returned data |
| [x] | PASS | panel | NFS PVC fill — capacity / used / available / used-% | B | mimir | `max by (namespace, persistentvolumeclaim) (kubelet_volume_stats_used_bytes{persistentvolumeclaim=~"$pvc"})` | query executed and returned data |
| [x] | PASS | panel | NFS PVC fill — capacity / used / available / used-% | C | mimir | `max by (namespace, persistentvolumeclaim) (kubelet_volume_stats_available_bytes{persistentvolumeclaim=~"$pvc"})` | query executed and returned data |
| [x] | PASS | panel | NFS PVC fill — capacity / used / available / used-% | D | mimir | `max by (namespace, persistentvolumeclaim) (100 * kubelet_volume_stats_used_bytes{persistentvolumeclaim=~"$pvc"} / kubelet_volume_stats_capacity_bytes{persistentvolumeclaim=~"$pvc"})` | query executed and returned data |
| [x] | PASS | panel | Available bytes per PVC (trend) | A | mimir | `max by (namespace, persistentvolumeclaim) (kubelet_volume_stats_available_bytes{persistentvolumeclaim=~"$pvc"})` | query executed and returned data |
| [x] | PASS | panel | Fill forecast — days to full (actively filling PVCs) | A | mimir | `(max by (namespace, persistentvolumeclaim) (kubelet_volume_stats_available_bytes{persistentvolumeclaim=~"$pvc"}) / max by (namespace, persistentvolumeclaim) (clamp_min(deriv(kubelet_volume_stats_used_bytes{persistentvolumeclaim=~"$pvc"}[6h]), 1)) / 86400) and max by (namespace, persistentvolumeclaim) (deriv(kubelet_volume_stats_used_bytes{persistentvolumeclaim=~"$pvc"}[6h])) > 0` | query executed and returned data |

### Cilium BPF Map Pressure (`cilium-bpf-pressure`)

Folder: Network · Panels: 13 · Queries: 13

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: node | node | mimir | `label_values(cilium_bpf_map_pressure, node)` | query executed and returned data |
| [x] | PASS | panel | Cluster max BPF map pressure |  | mimir | `max(cilium_bpf_map_pressure)` | query executed and returned data |
| [x] | PASS | panel | BPF insert error rate (cluster) |  | mimir | `sum(rate(cilium_bpf_map_ops_total{outcome!="success"}[5m]))` | query executed and returned data |
| [ ] | EMPTY | panel | Policy import error rate (cluster) |  | mimir | `sum(rate(cilium_policy_change_total{outcome="failure"}[10m]))` | query executed successfully but returned no data |
| [x] | PASS | panel | Identity count (max across nodes) |  | mimir | `max(cilium_identity)` | query executed and returned data |
| [x] | PASS | panel | Per-map pressure (sorted) | A | mimir | `max by (node, map_name) (cilium_bpf_map_pressure)` | query executed and returned data |
| [x] | PASS | panel | LB map pressure over time (per node) |  | mimir | `max by (node) (cilium_bpf_map_pressure{map_name=~"lb[46].*"})` | query executed and returned data |
| [x] | PASS | panel | BPF map insert error rate (per node/map/op) |  | mimir | `sum by (node, map_name, operation) (rate(cilium_bpf_map_ops_total{outcome!="success"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Policy import: count + error rate |  | mimir | `sum by (node) (cilium_policy)` | query executed and returned data |
| [ ] | EMPTY | panel | Policy import: count + error rate |  | mimir | `sum by (node) (rate(cilium_policy_change_total{outcome="failure"}[5m]))` | query executed successfully but returned no data |
| [x] | PASS | panel | Identity + endpoint counts (per node) |  | mimir | `max by (node) (cilium_identity)` | query executed and returned data |
| [x] | PASS | panel | Identity + endpoint counts (per node) |  | mimir | `max by (node) (cilium_endpoint)` | query executed and returned data |
| [x] | PASS | panel | Policy pressure vs cilium-agent restarts (correlation) |  | mimir | `sum by (node) (kube_pod_container_status_restarts_total{namespace="kube-system",container="cilium-agent"})` | query executed and returned data |

### Cilium Flows - Hubble Observer (`ozk-cilium-flows-hubble-observer`)

Folder: Network · Panels: 13 · Queries: 9

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [ ] | EMPTY | panel | Total Flows | A | Loki | `sum(     count_over_time(         {namespace="$hubbleobservernamespace",container="hubble-observer"} \|~ `(?i)$searchregex` !~ `(?i)$excluderegex`         \| $logparser \| flow_source_namespace=~"$sourcenamespace" \| flow_destination_namespace=~"$destinationnamespace" \| flow_traffic_direction=~"$direction" \| flow_IP_ipVersion=~"$ipversion"     [$__range]) )` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Flows per Verdict | A | Loki | `sum by(flow_verdict) (     count_over_time(         {namespace="$hubbleobservernamespace",container="hubble-observer"} \|~ `(?i)$searchregex` !~ `(?i)$excluderegex`         \| $logparser \| flow_source_namespace=~"$sourcenamespace" \| flow_destination_namespace=~"$destinationnamespace" \| flow_traffic_direction=~"$direction" \| flow_IP_ipVersion=~"$ipversion"     [$__range]) )` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Flows per Direction | A | Loki | `sum by(flow_traffic_direction) (     count_over_time(         {namespace="$hubbleobservernamespace",container="hubble-observer"} \|~ `(?i)$searchregex` !~ `(?i)$excluderegex`         \| $logparser \| flow_source_namespace=~"$sourcenamespace" \| flow_destination_namespace=~"$destinationnamespace" \| flow_traffic_direction=~"$direction" \| flow_IP_ipVersion=~"$ipversion"     [$__range]) )` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Flows per Source Namespace | A | Loki | `sum by(flow_source_namespace) (     count_over_time(         {namespace="$hubbleobservernamespace",container="hubble-observer"} \|~ `(?i)$searchregex` !~ `(?i)$excluderegex`         \| $logparser \| flow_source_namespace!="" \| flow_source_namespace=~"$sourcenamespace" \| flow_destination_namespace=~"$destinationnamespace" \| flow_traffic_direction=~"$direction" \| flow_IP_ipVersion=~"$ipversion"     [$__range]) )` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Flows per Destination | A | Loki | `sum by(flow_destination_name) (     count_over_time(         {namespace="$hubbleobservernamespace",container="hubble-observer"} \|~ `(?i)$searchregex` !~ `(?i)$excluderegex`         \| $logparser \| flow_source_namespace=~"$sourcenamespace" \| flow_destination_namespace=~"$destinationnamespace" \| flow_traffic_direction=~"$direction" \| flow_IP_ipVersion=~"$ipversion" \| json flow_destination_name="flow.destination_names[0]" \| flow_destination_name!=""      [$__range]) )` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Untitled | A | Loki | `sum by(flow_verdict) (     count_over_time(         {namespace="$hubbleobservernamespace",container="hubble-observer"} \|~ `(?i)$searchregex` !~ `(?i)$excluderegex`         \| $logparser \| flow_source_namespace=~"$sourcenamespace" \| flow_destination_namespace=~"$destinationnamespace" \| flow_traffic_direction=~"$direction" \| flow_IP_ipVersion=~"$ipversion"     [$__auto]) )` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Cilium Flows over Time | A | Loki | `{namespace="$hubbleobservernamespace",container="hubble-observer"} \|~ `(?i)$searchregex` !~ `(?i)$excluderegex` \| $logparser  \| flow_source_namespace=~"$sourcenamespace" \| flow_destination_namespace=~"$destinationnamespace" \| flow_traffic_direction=~"$direction" \| flow_IP_ipVersion=~"$ipversion" \| json flow_destination_name="flow.destination_names[0]" \| pattern `<_>"source":{<_>"labels":[<sourceLabels>]<_>}<_>,"destination":{<_>"labels":[<destinationLabels>]}<_>` \| pattern `<_>"k8s:job-name=<sourceJobName>"<_>` \| label_format      Verdict=`{{.flow_verdict}}`,     Source_IP=`{{.flow_IP_source}}`,     Source=`{{ if .flow_source_pod_name }}{{.flow_source_pod_name}} (Pod) {{else if .sourceJobName}} {{.sourceJobName}} (Job) {{else}} {{.sourceLabels}} (Label) {{end}}`,     Source_Namespace=`{{.flow_source_namespace}}`,     Direction=`{{.flow_traffic_direction}}`,     Dest_Port=`{{ if .flow_l4_TCP_destination_port}}TCP-{{.flow_l4_TCP_destination_port}}{{else if .flow_l4_UDP_destination_port}}UDP-{{.flow_l4_UDP_destination_port}}{{else if .flow_l4_ICMPv4_type}} ICMPv4 {{else}}{{end}}`, #     #Destination=`{{.flow_destination_name}}`,     Destination=`{{ if .flow_destination_pod_name }}{{.flow_destination_pod_name}} (Pod) {{ else if .flow_destination_name }}{{.flow_destination_name}} (URL){{else}} {{.destinationLabels}} (Label) {{end}}`,     #Destination_Pod=`{{.flow_destination_pod_name}}`,     Destination_Namespace=`{{.flow_destination_namespace}}`,     Destination_IP=`{{.flow_IP_destination}}`,      Drop_Description=`{{.flow_drop_reason_desc}}`,     Flow_UUID=`{{.flow_uuid}}`` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Unique Cilium Flows | A | Loki | `{namespace="$hubbleobservernamespace",container="hubble-observer"} \|~ `(?i)$searchregex` !~ `(?i)$excluderegex` \| $logparser  \| flow_source_namespace=~"$sourcenamespace" \| flow_destination_namespace=~"$destinationnamespace" \| flow_traffic_direction=~"$direction" \| flow_IP_ipVersion=~"$ipversion" \| json flow_destination_name="flow.destination_names[0]" \| pattern `<_>"source":{<_>"labels":[<sourceLabels>]<_>}<_>,"destination":{<_>"labels":[<destinationLabels>]}<_>` \| pattern `<_>"k8s:job-name=<sourceJobName>"<_>` \| label_format      Verdict=`{{.flow_verdict}}`,     Source_IP=`{{.flow_IP_source}}`,     Source=`{{ if .flow_source_pod_name }}{{.flow_source_pod_name}} (Pod) {{else if .sourceJobName}} {{.sourceJobName}} (Job) {{else}} {{.sourceLabels}} (Label) {{end}}`,     Source_Namespace=`{{.flow_source_namespace}}`,     Direction=`{{.flow_traffic_direction}}`,     Dest_Port=`{{ if .flow_l4_TCP_destination_port}}TCP-{{.flow_l4_TCP_destination_port}}{{else if .flow_l4_UDP_destination_port}}UDP-{{.flow_l4_UDP_destination_port}}{{else if .flow_l4_ICMPv4_type}} ICMPv4 {{else}}{{end}}`, #     #Destination=`{{.flow_destination_name}}`,     Destination=`{{ if .flow_destination_pod_name }}{{.flow_destination_pod_name}} (Pod) {{ else if .flow_destination_name }}{{.flow_destination_name}} (URL){{else}} {{.destinationLabels}} (Label) {{end}}`,     #Destination_Pod=`{{.flow_destination_pod_name}}`,     Destination_Namespace=`{{.flow_destination_namespace}}`,     Destination_IP=`{{.flow_IP_destination}}`,      Drop_Description=`{{.flow_drop_reason_desc}}`,     Flow_UUID=`{{.flow_uuid}}`` | query executed successfully but returned no data |
| [ ] | EMPTY | panel |  | A | Loki | `{namespace="$hubbleobservernamespace",container="hubble-observer"} \|~ `(?i)$searchregex` !~ `(?i)$excluderegex` \| $logparser  \| flow_traffic_direction=~"$direction" \| flow_IP_ipVersion=~"$ipversion" \| json flow_destination_name="flow.destination_names[0]"` | query executed successfully but returned no data |

### Cilium v1.12 Operator Metrics (`1GC0TT4Wz`)

Folder: Network · Panels: 10 · Queries: 13

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | panel | CPU Usage per node | A | Mimir | `min(irate(cilium_operator_process_cpu_seconds_total{io_cilium_app="operator"}[1m])) by (pod) * 100` | query executed and returned data |
| [x] | PASS | panel | CPU Usage per node | B | Mimir | `avg(irate(cilium_operator_process_cpu_seconds_total{io_cilium_app="operator"}[1m])) by (pod) * 100` | query executed and returned data |
| [x] | PASS | panel | CPU Usage per node | C | Mimir | `max(irate(cilium_operator_process_cpu_seconds_total{io_cilium_app="operator"}[1m])) by (pod) * 100` | query executed and returned data |
| [x] | PASS | panel | Resident memory status | C | Mimir | `avg(cilium_operator_process_resident_memory_bytes{io_cilium_app="operator"})` | query executed and returned data |
| [x] | PASS | panel | Resident memory status | D | Mimir | `max(cilium_operator_process_resident_memory_bytes{io_cilium_app="operator"})` | query executed and returned data |
| [x] | PASS | panel | Resident memory status | E | Mimir | `min(cilium_operator_process_resident_memory_bytes{io_cilium_app="operator"})` | query executed and returned data |
| [ ] | EMPTY | panel | IP Addresses | A | Mimir | `avg(cilium_operator_ipam_ips) by (type)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | EC2 API Interactions | A | Mimir | `rate(cilium_operator_ec2_api_duration_seconds_sum[1m])/rate(cilium_operator_ec2_api_duration_seconds_count[1m])` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Number of nodes | A | Mimir | `cilium_operator_ipam_nodes` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | # interfaces with addresses available | A | Mimir | `cilium_operator_ipam_available` | query executed successfully but returned no data |
| [x] | PASS | panel | Metadata Resync Operations | A | Mimir | `rate(cilium_operator_ipam_resync_total[1m])` | query executed and returned data |
| [ ] | EMPTY | panel | EC2 client side rate limiting | A | Mimir | `rate(cilium_operator_ec2_api_rate_limit_duration_seconds_sum[1m])/rate(cilium_operator_ec2_api_rate_limit_duration_seconds_count[1m])` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Interface Creation | A | Mimir | `avg(rate(cilium_operator_ipam_interface_creation_ops[1m])) by (subnetId, status)` | query executed successfully but returned no data |

### CloudNativePG Databases (`cnpg-databases`)

Folder: Databases · Panels: 39 · Queries: 59

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: namespace | namespace | mimir | `label_values(cnpg_collector_up, namespace)` | query executed and returned data |
| [x] | PASS | variable | Variable: cluster | cluster | mimir | `label_values(cnpg_collector_up{namespace=~"$namespace"}, pod)` | query executed and returned data |
| [ ] | EMPTY | panel | Clusters | A | mimir | `count(max by (namespace, pod) (cnpg_pg_replication_in_recovery{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"}) == 0)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Instances | A | mimir | `count(max by (namespace, pod) (cnpg_collector_up{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"}))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Instances Healthy | A | mimir | `count(max by (namespace, pod) (cnpg_collector_up{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"}) == 1)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Total DB Size | A | mimir | `sum(max by (namespace, datname) (cnpg_pg_database_size_bytes{datname!~"template.*", namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"}))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Connections | A | mimir | `sum(max by (namespace, pod, state) (cnpg_backends_total{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"}))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Fleet TPS | A | mimir | `sum(max by (namespace, pod) (rate(cnpg_pg_stat_database_xact_commit{datname="", namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"}[$__rate_interval]))) + sum(max by (namespace, pod) (rate(cnpg_pg_stat_database_xact_rollback{datname="", namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"}[$__rate_interval])))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Provisioned Databases & Instances | Version | mimir | `max by (namespace, pod) (cnpg_collector_postgres_version{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Provisioned Databases & Instances | Role | mimir | `max by (namespace, pod) (cnpg_pg_replication_in_recovery{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Provisioned Databases & Instances | Started | mimir | `max by (namespace, pod) (cnpg_pg_postmaster_start_time{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"}) * 1000` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Provisioned Databases & Instances | Up | mimir | `max by (namespace, pod) (cnpg_collector_up{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Provisioned Databases & Instances | Conn | mimir | `sum by (namespace, pod) (max by (namespace, pod, state) (cnpg_backends_total{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"}))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Provisioned Databases & Instances | Max | mimir | `max by (namespace, pod) (cnpg_pg_settings_setting{name="max_connections", namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | CPU — requests / limits / usage | A | mimir | `sum by (namespace, pod) (rate(container_cpu_usage_seconds_total{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$", container="postgres"}[$__rate_interval]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | CPU — requests / limits / usage | B | mimir | `max by (namespace, pod) (kube_pod_container_resource_requests{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$", container="postgres", resource="cpu"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | CPU — requests / limits / usage | C | mimir | `max by (namespace, pod) (kube_pod_container_resource_limits{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$", container="postgres", resource="cpu"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Memory — requests / limits / usage | A | mimir | `max by (namespace, pod) (container_memory_working_set_bytes{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$", container="postgres"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Memory — requests / limits / usage | B | mimir | `max by (namespace, pod) (kube_pod_container_resource_requests{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$", container="postgres", resource="memory"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Memory — requests / limits / usage | C | mimir | `max by (namespace, pod) (kube_pod_container_resource_limits{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$", container="postgres", resource="memory"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Storage — provisioned PVC vs data size | A | mimir | `max by (namespace, persistentvolumeclaim) (kube_persistentvolumeclaim_resource_requests_storage_bytes{namespace=~"$namespace", persistentvolumeclaim=~"($cluster)-[0-9]+$"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Storage — provisioned PVC vs data size | B | mimir | `sum by (namespace, pod) (max by (namespace, pod, datname) (cnpg_pg_database_size_bytes{datname!~"template.*", namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"}))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Connections by state | A | mimir | `max by (namespace, pod, state) (cnpg_backends_total{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Connection usage % of max | A | mimir | `100 * sum by (namespace, pod) (max by (namespace, pod, state) (cnpg_backends_total{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"})) / max by (namespace, pod) (cnpg_pg_settings_setting{name="max_connections", namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Transactions/sec — commit vs rollback | A | mimir | `max by (namespace, pod) (rate(cnpg_pg_stat_database_xact_commit{datname="", namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"}[5m]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Transactions/sec — commit vs rollback | B | mimir | `max by (namespace, pod) (rate(cnpg_pg_stat_database_xact_rollback{datname="", namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"}[5m]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Cache hit ratio | A | mimir | `100 * max by (namespace, pod) (rate(cnpg_pg_stat_database_blks_hit{datname="", namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"}[5m])) / (max by (namespace, pod) (rate(cnpg_pg_stat_database_blks_hit{datname="", namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"}[5m])) + max by (namespace, pod) (rate(cnpg_pg_stat_database_blks_read{datname="", namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"}[5m])))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Tuple I/O [5m] | A | mimir | `sum(max by (namespace, pod) (rate(cnpg_pg_stat_database_tup_fetched{datname="", namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"}[5m])))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Tuple I/O [5m] | B | mimir | `sum(max by (namespace, pod) (rate(cnpg_pg_stat_database_tup_returned{datname="", namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"}[5m])))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Tuple I/O [5m] | C | mimir | `sum(max by (namespace, pod) (rate(cnpg_pg_stat_database_tup_inserted{datname="", namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"}[5m])))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Tuple I/O [5m] | D | mimir | `sum(max by (namespace, pod) (rate(cnpg_pg_stat_database_tup_updated{datname="", namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"}[5m])))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Tuple I/O [5m] | E | mimir | `sum(max by (namespace, pod) (rate(cnpg_pg_stat_database_tup_deleted{datname="", namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"}[5m])))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Deadlocks & temp bytes [5m] | A | mimir | `sum(max by (namespace, pod) (rate(cnpg_pg_stat_database_deadlocks{datname="", namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"}[5m])))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Deadlocks & temp bytes [5m] | B | mimir | `sum(max by (namespace, pod) (rate(cnpg_pg_stat_database_temp_bytes{datname="", namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"}[5m])))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Replication lag | A | mimir | `max by (namespace, pod) (cnpg_pg_replication_lag{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Streaming replicas | A | mimir | `max by (namespace, pod) (cnpg_pg_replication_streaming_replicas{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | WAL segments | A | mimir | `max by (namespace, pod) (cnpg_collector_pg_wal{value="count", namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | WAL archiver [5m] | A | mimir | `max by (namespace, pod) (rate(cnpg_pg_stat_archiver_archived_count{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"}[5m]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | WAL archiver [5m] | B | mimir | `max by (namespace, pod) (rate(cnpg_pg_stat_archiver_failed_count{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"}[5m]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Time since last successful backup | A | mimir | `time() - max by (namespace, pod) ({__name__=~"cnpg_collector_last_available_backup_timestamp\|barman_cloud_cloudnative_pg_io_last_available_backup_timestamp", namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"} > 0)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Last collection error (0 = OK) | A | mimir | `max by (namespace, pod) (cnpg_collector_last_collection_error{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Metrics collection duration | A | mimir | `max by (namespace, pod) (cnpg_collector_collection_duration_seconds{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | XID / MXID wraparound age per database | XID | mimir | `max by (namespace, datname) (cnpg_pg_database_xid_age{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | XID / MXID wraparound age per database | MXID | mimir | `max by (namespace, datname) (cnpg_pg_database_mxid_age{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Max XID age (selected) | A | mimir | `max (cnpg_pg_database_xid_age{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Max MXID age (selected) | A | mimir | `max (cnpg_pg_database_mxid_age{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Time since last FAILED backup | A | mimir | `time() - max by (namespace, pod) (cnpg_collector_last_failed_backup_timestamp{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"} > 0)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | PITR window (age of oldest recoverable point) | A | mimir | `time() - max by (namespace, pod) (cnpg_collector_first_recoverability_point{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"} > 0)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Seconds since last WAL archival | A | mimir | `max by (namespace, pod) (cnpg_pg_stat_archiver_seconds_since_last_archival{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Max transaction age (long-running txn) | A | mimir | `max by (namespace, pod) (cnpg_backends_max_tx_duration_seconds{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Backends waiting on locks | A | mimir | `sum by (namespace, pod) (cnpg_backends_waiting_total{namespace=~"$namespace", pod=~"($cluster)-[0-9]+$"})` | query executed successfully but returned no data |
| [x] | PASS | panel | Fleet safety overview — per cluster (all clusters, ignores $namespace / $cluster) | Up | mimir | `max by (namespace, cnpgcluster) (label_replace(cnpg_collector_up, "cnpgcluster", "$1", "pod", "(.*)-[0-9]+$"))` | query executed and returned data |
| [x] | PASS | panel | Fleet safety overview — per cluster (all clusters, ignores $namespace / $cluster) | Inst | mimir | `count by (namespace, cnpgcluster) (label_replace(cnpg_collector_up, "cnpgcluster", "$1", "pod", "(.*)-[0-9]+$"))` | query executed and returned data |
| [x] | PASS | panel | Fleet safety overview — per cluster (all clusters, ignores $namespace / $cluster) | Conn | mimir | `100 * sum by (namespace, cnpgcluster) (label_replace(max by (namespace, pod, state) (cnpg_backends_total), "cnpgcluster", "$1", "pod", "(.*)-[0-9]+$")) / sum by (namespace, cnpgcluster) (label_replace(max by (namespace, pod) (cnpg_pg_settings_setting{name="max_connections"}), "cnpgcluster", "$1", "pod", "(.*)-[0-9]+$"))` | query executed and returned data |
| [x] | PASS | panel | Fleet safety overview — per cluster (all clusters, ignores $namespace / $cluster) | Size | mimir | `sum by (namespace, cnpgcluster) (max by (namespace, cnpgcluster, datname) (label_replace(cnpg_pg_database_size_bytes{datname!~"template.*"}, "cnpgcluster", "$1", "pod", "(.*)-[0-9]+$")))` | query executed and returned data |
| [x] | PASS | panel | Fleet safety overview — per cluster (all clusters, ignores $namespace / $cluster) | Lag | mimir | `max by (namespace, cnpgcluster) (label_replace(cnpg_pg_replication_lag, "cnpgcluster", "$1", "pod", "(.*)-[0-9]+$"))` | query executed and returned data |
| [x] | PASS | panel | Fleet safety overview — per cluster (all clusters, ignores $namespace / $cluster) | Xid | mimir | `max by (namespace, cnpgcluster) (label_replace(cnpg_pg_database_xid_age, "cnpgcluster", "$1", "pod", "(.*)-[0-9]+$"))` | query executed and returned data |
| [x] | PASS | panel | Fleet safety overview — per cluster (all clusters, ignores $namespace / $cluster) | Backup | mimir | `time() - max by (namespace, cnpgcluster) (label_replace({__name__=~"cnpg_collector_last_available_backup_timestamp\|barman_cloud_cloudnative_pg_io_last_available_backup_timestamp"}, "cnpgcluster", "$1", "pod", "(.*)-[0-9]+$") > 0)` | query executed and returned data |
| [x] | PASS | panel | Fleet safety overview — per cluster (all clusters, ignores $namespace / $cluster) | Fail | mimir | `time() - max by (namespace, cnpgcluster) (label_replace(cnpg_collector_last_failed_backup_timestamp, "cnpgcluster", "$1", "pod", "(.*)-[0-9]+$") > 0)` | query executed and returned data |

### Cowrie Ops (`cowrie-ops`)

Folder: Security · Panels: 16 · Queries: 12

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [ ] | EMPTY | panel | Commands Captured | A | loki-v2 | `sum(count_over_time({namespace="honeypot", container="logship"} \| json \| eventid=`cowrie.command.input` [$__range]))` | query executed successfully but returned no data |
| [x] | PASS | panel | Sessions | A | loki-v2 | `sum(count_over_time({namespace="honeypot", container="logship"} \| json \| eventid=`cowrie.session.connect` [$__range]))` | query executed and returned data |
| [ ] | EMPTY | panel | Unique Attacker IPs | A | loki-v2 | `count(sum by (src_ip) (count_over_time({namespace="honeypot", container="logship"} \| json \| src_ip!="" \| src_ip!~`10.244..*` [$__range])))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Failed Logins | A | loki-v2 | `sum(count_over_time({namespace="honeypot", container="logship"} \| json \| eventid=`cowrie.login.failed` [$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Captured Commands (live) | A | loki-v2 | `{namespace="honeypot", container="logship"} \| json \| eventid=`cowrie.command.input` \| line_format "{{.src_ip}}  [{{.session}}]  $ {{.input}}"` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Login Attempts (success vs failed) | A | loki-v2 | `sum(count_over_time({namespace="honeypot", container="logship"} \| json \| eventid=`cowrie.login.success` [5m]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Login Attempts (success vs failed) | B | loki-v2 | `sum(count_over_time({namespace="honeypot", container="logship"} \| json \| eventid=`cowrie.login.failed` [5m]))` | query executed successfully but returned no data |
| [x] | PASS | panel | Sessions Over Time | A | loki-v2 | `sum(count_over_time({namespace="honeypot", container="logship"} \| json \| eventid=`cowrie.session.connect` [5m]))` | query executed and returned data |
| [ ] | EMPTY | panel | Top Attacker IPs | A | loki-v2 | `topk(10, sum by (src_ip) (count_over_time({namespace="honeypot", container="logship"} \| json \| src_ip!="" \| src_ip!~`10.244..*` [$__range])))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Top Commands | A | loki-v2 | `topk(15, sum by (input) (count_over_time({namespace="honeypot", container="logship"} \| json \| eventid=`cowrie.command.input` \| input!="" [$__range])))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Captured Credentials (successful logins) | A | loki-v2 | `topk(20, sum by (username, password) (count_over_time({namespace="honeypot", container="logship"} \| json \| eventid=`cowrie.login.success` [$__range])))` | query executed successfully but returned no data |
| [x] | PASS | panel | Event Breakdown | A | loki-v2 | `sum by (eventid) (count_over_time({namespace="honeypot", container="logship"} \| json \| eventid!="" [$__range]))` | query executed and returned data |

### Dagster Pipelines - Catalyst Data (`dagster-pipelines-catalyst`)

Folder: catalyst-data · Panels: 58 · Queries: 61

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [ ] | EMPTY | variable | Variable: code_location | code_location | mimir | `label_values(catalyst_asset_records_processed_total, code_location)` | query executed successfully but returned no data |
| [ ] | EMPTY | variable | Variable: asset_key | asset_key | mimir | `label_values(catalyst_asset_materialization_duration_seconds_bucket{code_location=~"$code_location"}, asset_key)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Active Materializations | A | mimir | `count(count by (step_key) (catalyst_asset_records_processed_total{job="dagster_step"}))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Records Processed | A | mimir | `sum(increase(catalyst_asset_records_processed_total[$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Records Processed by Asset | A | mimir | `sum by (code_location, asset_key) (increase(catalyst_asset_records_processed_total{code_location=~"$code_location"}[$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | LLM Request Duration | A | mimir | `histogram_quantile(0.5, sum by (le, model, operation) (catalyst_llm_request_duration_seconds_bucket))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | LLM Request Duration | B | mimir | `histogram_quantile(0.99, sum by (le, model, operation) (catalyst_llm_request_duration_seconds_bucket))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | LLM Tokens Used | A | mimir | `sum by (model, token_type) (increase(catalyst_llm_tokens[$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | LLM Requests Rate | A | mimir | `sum by (model) (increase(catalyst_llm_requests_total[$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | LLM Requests by Status | A | mimir | `sum by (status) (increase(catalyst_llm_requests_total{status!="pending"}[$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | LLM Error Rate by Model | A | mimir | `sum by (model) (increase(catalyst_llm_requests_total{status="error"}[$__range])) / sum by (model) (increase(catalyst_llm_requests_total[$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | S3 Operations Rate | A | mimir | `sum by (operation) (increase(catalyst_s3_operations_total[$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | S3 Bytes Transferred | A | mimir | `sum by (direction) (increase(catalyst_s3_bytes_total[$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Embedding Batch Duration | A | mimir | `histogram_quantile(0.5, sum by (le, provider, model) (catalyst_embedding_batch_duration_seconds_bucket))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Embedding Batch Duration | B | mimir | `histogram_quantile(0.99, sum by (le, provider, model) (catalyst_embedding_batch_duration_seconds_bucket))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Embedding Vectors/sec | A | mimir | `sum by (provider) (increase(catalyst_embedding_vectors_total[$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Entities Extracted Rate by Type | A | mimir | `sum by (entity_type) (increase(catalyst_entities_extracted_total[$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Assertions/sec by Domain | A | mimir | `sum by (code_location) (increase(catalyst_assertions_created_total{code_location=~"$code_location"}[$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Graph DB Operations | A | mimir | `sum by (operation) (increase(catalyst_graph_db_operations_total[$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Log Volume by Level | A | loki-v2 | `sum by (level) (count_over_time({namespace="catalyst-data"} \| json \| level != "" [1m]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Errors Only | A | loki-v2 | `{namespace="catalyst-data"} \| json \| level=~"ERROR\|CRITICAL"` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Pod CPU Usage | A | mimir | `sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="catalyst-data", container!=""}[5m]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Pod Memory Usage | A | mimir | `sum by (pod) (container_memory_working_set_bytes{namespace="catalyst-data", container!=""})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Pod Restart Count (1h) | A | mimir | `sum by (pod) (increase(kube_pod_container_status_restarts_total{namespace="catalyst-data", pod!~"dagster-run-.*\|dagster-step-.*"}[1h])) > 0` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Transcription Duration by Backend | A | mimir | `histogram_quantile(0.5, sum by (le) (catalyst_transcription_duration_seconds_bucket))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Transcription Duration by Backend | B | mimir | `histogram_quantile(0.95, sum by (le) (catalyst_transcription_duration_seconds_bucket))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Transcription Duration by Backend | C | mimir | `histogram_quantile(0.99, sum by (le) (catalyst_transcription_duration_seconds_bucket))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Transcription Real-Time Factor | A | mimir | `histogram_quantile(0.5, sum by (le) (catalyst_transcription_realtime_factor_bucket))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Transcription Real-Time Factor | B | mimir | `histogram_quantile(0.95, sum by (le) (catalyst_transcription_realtime_factor_bucket))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Diarization Duration | A | mimir | `histogram_quantile(0.5, sum by (le) (catalyst_diarization_duration_seconds_bucket))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Diarization Duration | B | mimir | `histogram_quantile(0.95, sum by (le) (catalyst_diarization_duration_seconds_bucket))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Diarization Duration | C | mimir | `histogram_quantile(0.99, sum by (le) (catalyst_diarization_duration_seconds_bucket))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Diarization Real-Time Factor | A | mimir | `histogram_quantile(0.5, sum by (le, device) (catalyst_diarization_realtime_factor_bucket))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Diarization Real-Time Factor | B | mimir | `histogram_quantile(0.95, sum by (le, device) (catalyst_diarization_realtime_factor_bucket))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Transcode Duration | A | mimir | `histogram_quantile(0.5, sum by (le) (catalyst_transcode_duration_seconds_bucket))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Transcode Duration | B | mimir | `histogram_quantile(0.99, sum by (le) (catalyst_transcode_duration_seconds_bucket))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Transcode Compression Ratio | A | mimir | `histogram_quantile(0.5, sum by (le) (catalyst_transcode_compression_ratio_bucket))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Transcode Compression Ratio | B | mimir | `histogram_quantile(0.95, sum by (le) (catalyst_transcode_compression_ratio_bucket))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Transcode Bytes Saved Rate | A | mimir | `sum(increase(catalyst_transcode_saved_bytes_total[$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Model Load Duration | A | mimir | `histogram_quantile(0.5, sum by (le) (catalyst_model_load_duration_seconds_bucket))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Model Load Duration | B | mimir | `histogram_quantile(0.99, sum by (le) (catalyst_model_load_duration_seconds_bucket))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Throughput by Domain | A | mimir | `sum by (code_location) (increase(catalyst_asset_records_processed_total{code_location=~"$code_location"}[$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Records Processed by Domain | A | mimir | `sum by (code_location) (increase(catalyst_asset_records_processed_total{code_location=~"$code_location"}[$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Asset Duration by Domain (p95) | A | mimir | `histogram_quantile(0.95, sum by (code_location, le) (catalyst_asset_materialization_duration_seconds_bucket{code_location=~"$code_location"}))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Runs / 1h | A | mimir | `sum by (code_location) (increase(catalyst_dagster_run_status_total{code_location=~"$code_location"}[1h]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Failure % | A | mimir | `100 * sum by (code_location) (increase(catalyst_dagster_run_status_total{code_location=~"$code_location", status="failure"}[1h])) / clamp_min(sum by (code_location) (increase(catalyst_dagster_run_status_total{code_location=~"$code_location"}[1h])), 1)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | p95 Run Duration | A | mimir | `histogram_quantile(0.95, sum by (code_location, le) (catalyst_dagster_run_duration_seconds_bucket{code_location=~"$code_location"}))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Asset Freshness (max staleness) | A | mimir | `max by (code_location) (time() - catalyst_asset_last_materialized_timestamp_seconds{code_location=~"$code_location"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Alignment Edges by Type | A | mimir | `sum by (alignment_type) (increase(catalyst_alignment_edges_total{source_location=~"$code_location"}[$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Alignment Signal Mix | A | mimir | `sum by (top_signal) (increase(catalyst_alignment_edges_total{source_location=~"$code_location"}[$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Entity Reduction Ratio | A | mimir | `sum by (code_location, le) (increase(catalyst_entity_reduction_ratio_bucket{code_location=~"$code_location"}[$__rate_interval]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Canonical Entities by Merge Count | A | mimir | `sum by (source_count_bucket) (increase(catalyst_canonical_entities_total[$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Assets Last Materialized (freshness gauge) | A | mimir | `time() - catalyst_asset_last_materialized_timestamp_seconds{code_location=~"$code_location"}` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Assertions Created by Code Location | A | mimir | `sum by (code_location) (increase(catalyst_assertions_created_total{code_location=~"$code_location"}[$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Canonical Entities Gold-to-Platinum Funnel | A | mimir | `sum by (entity_type) (increase(catalyst_canonical_entities_total[$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Run Outcomes by Job | A | mimir | `sum by (job_name, status) (increase(catalyst_dagster_run_status_total{code_location=~"$code_location"}[$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Run Duration p50/p95/p99 | A | mimir | `histogram_quantile(0.50, sum by (code_location, le) (catalyst_dagster_run_duration_seconds_bucket{code_location=~"$code_location"}))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Run Duration p50/p95/p99 | B | mimir | `histogram_quantile(0.95, sum by (code_location, le) (catalyst_dagster_run_duration_seconds_bucket{code_location=~"$code_location"}))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Run Duration p50/p95/p99 | C | mimir | `histogram_quantile(0.99, sum by (code_location, le) (catalyst_dagster_run_duration_seconds_bucket{code_location=~"$code_location"}))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Sensor Tick Outcomes | A | mimir | `sum by (sensor_name, outcome) (increase(catalyst_dagster_sensor_tick_total{code_location=~"$code_location"}[$__range]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | LLM Prompt Cache Hit Rate | A | mimir | `sum by (model) (rate(catalyst_llm_tokens_cached[$__rate_interval]))` | query executed successfully but returned no data |

### Dragonfly / Redis Cache (`dragonfly-cache`)

Folder: Databases · Panels: 20 · Queries: 29

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: redis | redis | mimir | `label_values(redis_up, redis_cache)` | query executed and returned data |
| [x] | PASS | panel | Caches up | A | mimir | `count(redis_up{redis_cache=~"$redis"} == 1)` | query executed and returned data |
| [x] | PASS | panel | Total memory used | A | mimir | `sum(max by (redis_cache) (redis_memory_used_bytes{redis_cache=~"$redis"}))` | query executed and returned data |
| [x] | PASS | panel | Connected clients | A | mimir | `sum(max by (redis_cache) (redis_connected_clients{redis_cache=~"$redis"}))` | query executed and returned data |
| [x] | PASS | panel | Fleet ops/sec | A | mimir | `sum(rate(redis_commands_processed_total{redis_cache=~"$redis"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Total keys | A | mimir | `sum(max by (redis_cache, db) (redis_db_keys{redis_cache=~"$redis"}))` | query executed and returned data |
| [x] | PASS | panel | Fleet hit ratio [5m] | A | mimir | `sum(rate(redis_keyspace_hits_total{redis_cache=~"$redis"}[5m])) / (sum(rate(redis_keyspace_hits_total{redis_cache=~"$redis"}[5m])) + sum(rate(redis_keyspace_misses_total{redis_cache=~"$redis"}[5m])))` | query executed and returned data |
| [x] | PASS | panel | Caches | Info | mimir | `max by (redis_cache, redis_version) (redis_instance_info{redis_cache=~"$redis"})` | query executed and returned data |
| [x] | PASS | panel | Caches | Up | mimir | `max by (redis_cache) (redis_up{redis_cache=~"$redis"})` | query executed and returned data |
| [x] | PASS | panel | Caches | Uptime | mimir | `max by (redis_cache) (redis_uptime_in_seconds{redis_cache=~"$redis"})` | query executed and returned data |
| [x] | PASS | panel | Caches | Cli | mimir | `max by (redis_cache) (redis_connected_clients{redis_cache=~"$redis"})` | query executed and returned data |
| [x] | PASS | panel | Caches | MemU | mimir | `max by (redis_cache) (redis_memory_used_bytes{redis_cache=~"$redis"})` | query executed and returned data |
| [x] | PASS | panel | Caches | MemM | mimir | `max by (redis_cache) (redis_memory_max_bytes{redis_cache=~"$redis"})` | query executed and returned data |
| [x] | PASS | panel | Caches | Keys | mimir | `sum by (redis_cache) (max by (redis_cache, db) (redis_db_keys{redis_cache=~"$redis"}))` | query executed and returned data |
| [x] | PASS | panel | Memory used vs max (maxmemory) | A | mimir | `max by (redis_cache) (redis_memory_used_bytes{redis_cache=~"$redis"})` | query executed and returned data |
| [x] | PASS | panel | Memory used vs max (maxmemory) | B | mimir | `max by (redis_cache) (redis_memory_used_rss_bytes{redis_cache=~"$redis"})` | query executed and returned data |
| [x] | PASS | panel | Memory used vs max (maxmemory) | C | mimir | `max by (redis_cache) (redis_memory_max_bytes{redis_cache=~"$redis"})` | query executed and returned data |
| [x] | PASS | panel | Memory usage % of maxmemory | A | mimir | `100 * max by (redis_cache) (redis_memory_used_bytes{redis_cache=~"$redis"}) / max by (redis_cache) (redis_memory_max_bytes{redis_cache=~"$redis"} > 0)` | query executed and returned data |
| [x] | PASS | panel | Evicted & expired keys/sec [5m] | A | mimir | `max by (redis_cache) (rate(redis_evicted_keys_total{redis_cache=~"$redis"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Evicted & expired keys/sec [5m] | B | mimir | `max by (redis_cache) (rate(redis_expired_keys_total{redis_cache=~"$redis"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Commands processed/sec | A | mimir | `max by (redis_cache) (rate(redis_commands_processed_total{redis_cache=~"$redis"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Keyspace hits vs misses/sec [5m] | A | mimir | `max by (redis_cache) (rate(redis_keyspace_hits_total{redis_cache=~"$redis"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Keyspace hits vs misses/sec [5m] | B | mimir | `max by (redis_cache) (rate(redis_keyspace_misses_total{redis_cache=~"$redis"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Connected & blocked clients | A | mimir | `max by (redis_cache) (redis_connected_clients{redis_cache=~"$redis"})` | query executed and returned data |
| [x] | PASS | panel | Connected & blocked clients | B | mimir | `max by (redis_cache) (redis_blocked_clients{redis_cache=~"$redis"})` | query executed and returned data |
| [x] | PASS | panel | Network I/O bytes/sec [5m] | A | mimir | `max by (redis_cache) (rate(redis_net_input_bytes_total{redis_cache=~"$redis"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Network I/O bytes/sec [5m] | B | mimir | `max by (redis_cache) (rate(redis_net_output_bytes_total{redis_cache=~"$redis"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Keys per cache | A | mimir | `sum by (redis_cache) (max by (redis_cache, db) (redis_db_keys{redis_cache=~"$redis"}))` | query executed and returned data |
| [x] | PASS | panel | Uptime | A | mimir | `max by (redis_cache) (redis_uptime_in_seconds{redis_cache=~"$redis"})` | query executed and returned data |

### etcd Snapshot Correlation (`etcd-snapshot-correlation`)

Folder: Cluster · Panels: 18 · Queries: 15

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | panel | etcd commit p99 (last 5m) |  | mimir | `histogram_quantile(0.99, sum by (le) (rate(etcd_disk_backend_commit_duration_seconds_bucket[5m])))` | query executed and returned data |
| [x] | PASS | panel | etcd WAL fsync p99 (last 5m) |  | mimir | `histogram_quantile(0.99, sum by (le) (rate(etcd_disk_wal_fsync_duration_seconds_bucket[5m])))` | query executed and returned data |
| [x] | PASS | panel | Snapshot Jobs Active |  | mimir | `sum(kube_job_status_active{namespace="backup", job_name=~"etcd-backup-.*"})` | query executed and returned data |
| [x] | PASS | panel | Cilium Restarts (1h) |  | mimir | `sum(increase(kube_pod_container_status_restarts_total{namespace="kube-system", container="cilium-agent"}[1h]))` | query executed and returned data |
| [x] | PASS | panel | etcd commit + fsync latency (p50/p95/p99) |  | mimir | `histogram_quantile(0.50, sum by (le) (rate(etcd_disk_backend_commit_duration_seconds_bucket[5m])))` | query executed and returned data |
| [x] | PASS | panel | etcd commit + fsync latency (p50/p95/p99) |  | mimir | `histogram_quantile(0.95, sum by (le) (rate(etcd_disk_backend_commit_duration_seconds_bucket[5m])))` | query executed and returned data |
| [x] | PASS | panel | etcd commit + fsync latency (p50/p95/p99) |  | mimir | `histogram_quantile(0.99, sum by (le) (rate(etcd_disk_backend_commit_duration_seconds_bucket[5m])))` | query executed and returned data |
| [x] | PASS | panel | etcd commit + fsync latency (p50/p95/p99) |  | mimir | `histogram_quantile(0.99, sum by (le) (rate(etcd_disk_wal_fsync_duration_seconds_bucket[5m])))` | query executed and returned data |
| [x] | PASS | panel | apiserver_request_duration p99 by verb |  | mimir | `histogram_quantile(0.99, sum by (le, verb) (rate(apiserver_request_duration_seconds_bucket{verb!~"WATCH\|CONNECT"}[5m])))` | query executed and returned data |
| [x] | PASS | panel | apiserver write request rate |  | mimir | `sum by (verb) (rate(apiserver_request_total{verb=~"POST\|PUT\|PATCH\|DELETE"}[1m]))` | query executed and returned data |
| [x] | PASS | panel | etcd-backup Job duration (per run) |  | mimir | `kube_job_status_completion_time{namespace="backup", job_name=~"etcd-backup-.*"} - kube_job_status_start_time{namespace="backup", job_name=~"etcd-backup-.*"}` | query executed and returned data |
| [x] | PASS | panel | etcd-backup Job run count |  | mimir | `sum(kube_job_status_succeeded{namespace="backup", job_name=~"etcd-backup-.*"})` | query executed and returned data |
| [x] | PASS | panel | etcd-backup Job run count |  | mimir | `sum(kube_job_status_failed{namespace="backup", job_name=~"etcd-backup-.*"})` | query executed and returned data |
| [x] | PASS | panel | Cilium agent restart rate (restarts/min) — overlay with snapshot annotations |  | mimir | `rate(kube_pod_container_status_restarts_total{namespace="kube-system", container="cilium-agent"}[5m]) * 60` | query executed and returned data |
| [x] | PASS | panel | Snapshot Job logs (Loki) | A | loki-v2 | `{namespace="backup"} \|~ "(Snapshot\|Uploading\|Done\|snapshot)"` | query executed and returned data |

### External DNS (`eea5u_I7z`)

Folder: Network · Panels: 24 · Queries: 30

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: instance | instance | mimir | `label_values(external_dns_controller_last_sync_timestamp_seconds, job)` | query executed and returned data |
| [x] | PASS | panel | Controller Health |  | mimir | `max(up{job=~"$instance"})` | query executed and returned data |
| [x] | PASS | panel | Last Sync Age |  | mimir | `time() - max(external_dns_controller_last_sync_timestamp_seconds{job=~"$instance"})` | query executed and returned data |
| [x] | PASS | panel | Last Reconcile Age |  | mimir | `time() - max(external_dns_controller_last_reconcile_timestamp_seconds{job=~"$instance"})` | query executed and returned data |
| [x] | PASS | panel | Managed Records |  | mimir | `max(external_dns_registry_endpoints_total{job=~"$instance"})` | query executed and returned data |
| [x] | PASS | panel | Desired Records (sources) |  | mimir | `max(external_dns_source_endpoints_total{job=~"$instance"})` | query executed and returned data |
| [x] | PASS | panel | Unreconciled (drift) |  | mimir | `max(external_dns_source_endpoints_total{job=~"$instance"}) - max(external_dns_registry_endpoints_total{job=~"$instance"})` | query executed and returned data |
| [x] | PASS | panel | Errors (15m) |  | mimir | `sum(increase(external_dns_registry_errors_total{job=~"$instance"}[15m])) + sum(increase(external_dns_source_errors_total{job=~"$instance"}[15m]))` | query executed and returned data |
| [x] | PASS | panel | Reconcile Heartbeat (15m) |  | mimir | `sum(increase(external_dns_controller_no_op_runs_total{job=~"$instance"}[15m]))` | query executed and returned data |
| [x] | PASS | panel | Record Inventory — live from Cloudflare | A | mimir | `external_dns_cf_record_info` | query executed and returned data |
| [ ] | EMPTY | panel | Managed Records by Type | A | mimir | `max(external_dns_registry_a_records{job=~"$instance"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Managed Records by Type | B | mimir | `max(external_dns_registry_aaaa_records{job=~"$instance"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Managed Records by Type | C | mimir | `max(external_dns_registry_endpoints_total{job=~"$instance"}) - max(external_dns_registry_a_records{job=~"$instance"}) - max(external_dns_registry_aaaa_records{job=~"$instance"})` | query executed successfully but returned no data |
| [x] | PASS | panel | Managed Records by Type | D | mimir | `max(external_dns_registry_endpoints_total{job=~"$instance"})` | query executed and returned data |
| [x] | PASS | panel | Desired vs Managed Endpoints |  | mimir | `max(external_dns_source_endpoints_total{job=~"$instance"})` | query executed and returned data |
| [x] | PASS | panel | Desired vs Managed Endpoints |  | mimir | `max(external_dns_registry_endpoints_total{job=~"$instance"})` | query executed and returned data |
| [ ] | EMPTY | panel | Managed Records by Type (over time) | A | mimir | `max(external_dns_registry_a_records{job=~"$instance"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Managed Records by Type (over time) | B | mimir | `max(external_dns_registry_aaaa_records{job=~"$instance"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Managed Records by Type (over time) | C | mimir | `max(external_dns_registry_endpoints_total{job=~"$instance"}) - max(external_dns_registry_a_records{job=~"$instance"}) - max(external_dns_registry_aaaa_records{job=~"$instance"})` | query executed successfully but returned no data |
| [x] | PASS | panel | Error Rate |  | mimir | `sum(rate(external_dns_source_errors_total{job=~"$instance"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Error Rate |  | mimir | `sum(rate(external_dns_registry_errors_total{job=~"$instance"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Reconcile Heartbeat |  | mimir | `sum(rate(external_dns_controller_no_op_runs_total{job=~"$instance"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | external-dns Activity Log (heartbeat filtered) | A | loki-v2 | `{namespace="external-dns", app_kubernetes_io_name="external-dns"} != `All records are already up to date`` | query executed and returned data |
| [x] | PASS | panel | Records by Status Over Time | A | mimir | `sum by (status) (external_dns_cf_records)` | query executed and returned data |
| [x] | PASS | panel | Cloudflare vs external-dns (record counts) | A | mimir | `external_dns_cf_managed_records` | query executed and returned data |
| [x] | PASS | panel | Cloudflare vs external-dns (record counts) | B | mimir | `max(external_dns_registry_endpoints_total{job="external-dns"})` | query executed and returned data |
| [x] | PASS | panel | Cloudflare vs external-dns (record counts) | C | mimir | `max(external_dns_source_endpoints_total{job="external-dns"})` | query executed and returned data |
| [x] | PASS | panel | Cloudflare vs external-dns (record counts) | D | mimir | `external_dns_cf_zone_records_total` | query executed and returned data |
| [x] | PASS | panel | CF Exporter — Last Scrape Age | A | mimir | `time() - max(external_dns_cf_last_scrape_timestamp_seconds)` | query executed and returned data |
| [x] | PASS | panel | Records by Status (now) | A | mimir | `sum by (status) (external_dns_cf_records)` | query executed and returned data |

### Flux Ops (`flux-ops`)

Folder: GitOps · Panels: 25 · Queries: 22

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: controller | controller | mimir | `label_values(controller_runtime_reconcile_total{namespace="flux-system"}, controller)` | query executed and returned data |
| [x] | PASS | panel | Controllers Reporting | A | mimir | `count(count by (app) (controller_runtime_reconcile_total{namespace="flux-system"}))` | query executed and returned data |
| [x] | PASS | panel | Reconciles /s | A | mimir | `sum(rate(controller_runtime_reconcile_total{namespace="flux-system"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Reconcile Error % | A | mimir | `100 * (sum(rate(controller_runtime_reconcile_total{namespace="flux-system",result="error"}[$__rate_interval])) or vector(0)) / sum(rate(controller_runtime_reconcile_total{namespace="flux-system"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Not Ready Objects | A | mimir | `count(gotk_reconcile_condition{type="Ready",status="False"} == 1) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | Suspended Objects | A | mimir | `count(gotk_suspend_status == 1) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | Tracked Flux Objects | A | mimir | `count(gotk_resource_info) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | Reconcile Rate by Controller | A | mimir | `sum by (controller) (rate(controller_runtime_reconcile_total{namespace="flux-system",controller=~"$controller"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Reconcile Errors /s by Controller | A | mimir | `sum by (controller) (rate(controller_runtime_reconcile_errors_total{namespace="flux-system",controller=~"$controller"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Reconcile Duration by Kind (p50 / p99) | A | mimir | `histogram_quantile(0.99, sum by (le, kind) (rate(gotk_reconcile_duration_seconds_bucket[$__rate_interval])))` | query executed and returned data |
| [x] | PASS | panel | Reconcile Duration by Kind (p50 / p99) | B | mimir | `histogram_quantile(0.50, sum by (le, kind) (rate(gotk_reconcile_duration_seconds_bucket[$__rate_interval])))` | query executed and returned data |
| [x] | PASS | panel | Busiest Objects (reconciles /s, top 10) | A | mimir | `topk(10, sum by (kind, exported_namespace, name) (rate(gotk_reconcile_duration_seconds_count[$__rate_interval])))` | query executed and returned data |
| [x] | PASS | panel | Queue Depth | A | mimir | `sum by (name) (workqueue_depth{namespace="flux-system",name=~"$controller"})` | query executed and returned data |
| [x] | PASS | panel | Queue Adds /s | A | mimir | `sum by (name) (rate(workqueue_adds_total{namespace="flux-system",name=~"$controller"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Queue Wait p99 | A | mimir | `histogram_quantile(0.99, sum by (le, name) (rate(workqueue_queue_duration_seconds_bucket{namespace="flux-system",name=~"$controller"}[$__rate_interval])))` | query executed and returned data |
| [x] | PASS | panel | Kubernetes API Requests /s by Controller | A | mimir | `sum by (app) (rate(rest_client_requests_total{namespace="flux-system"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | API Non-2xx Responses /s | A | mimir | `sum by (app, code) (rate(rest_client_requests_total{namespace="flux-system",code!~"2.."}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Controller Restarts (increase, 1h window) | A | mimir | `sum by (pod) (increase(kube_pod_container_status_restarts_total{namespace="flux-system"}[1h]))` | query executed and returned data |
| [x] | PASS | panel | Not-Ready Objects Over Time | A | mimir | `count(gotk_reconcile_condition{type="Ready",status="False"} == 1) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | Not-Ready Objects (now) | A | mimir | `gotk_reconcile_condition{type="Ready",status="False"} == 1` | query executed and returned data |
| [x] | PASS | panel | Flux Object Inventory | A | mimir | `gotk_resource_info` | query executed and returned data |
| [x] | PASS | panel | Suspended Objects (now) | A | mimir | `gotk_suspend_status == 1` | query executed and returned data |

### Flux2 (`eM7_f4V7z`)

Folder: GitOps · Panels: 12 · Queries: 13

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: namespace | namespace | $DS_PROMETHEUS | `label_values(gotk_reconcile_condition, exported_namespace)` | query executed and returned data |
| [ ] | EMPTY | panel | Sources | A | Mimir | `count(gotk_reconcile_condition{exported_namespace=~"$namespace",type="Ready",status="True",kind=~"GitRepository\|HelmRepository\|Bucket"}) - sum(gotk_reconcile_condition{exported_namespace=~"$namespace",type="Ready",status="Deleted",kind=~"GitRepository\|HelmRepository\|Bucket"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Failing sources | A | Mimir | `sum(gotk_reconcile_condition{exported_namespace=~"$namespace",type="Ready",status="False",kind=~"GitRepository\|HelmRepository\|Bucket"})` | query executed successfully but returned no data |
| [x] | PASS | panel | Avg. source reconciliation | A | Mimir | `sum(rate(gotk_reconcile_duration_seconds_sum{exported_namespace=~"$namespace",kind=~"GitRepository\|HelmRepository\|Bucket"}[5m])) by (kind) / sum(rate(gotk_reconcile_duration_seconds_count{exported_namespace=~"$namespace",kind=~"GitRepository\|HelmRepository\|Bucket"}[5m])) by (kind)` | query executed and returned data |
| [ ] | EMPTY | panel | Applications | A | Mimir | `count(gotk_reconcile_condition{exported_namespace=~"$namespace",type="Ready",status="True",kind=~"Kustomization\|HelmRelease"}) - sum(gotk_reconcile_condition{exported_namespace=~"$namespace",type="Ready",status="Deleted",kind=~"Kustomization\|HelmRelease"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Failing application | A | Mimir | `sum(gotk_reconcile_condition{exported_namespace=~"$namespace",type="Ready",status="False",kind=~"Kustomization\|HelmRelease"})` | query executed successfully but returned no data |
| [x] | PASS | panel | Avg. app reconciliation | A | Mimir | `sum(rate(gotk_reconcile_duration_seconds_sum{exported_namespace=~"$namespace",kind=~"Kustomization\|HelmRelease"}[5m])) by (kind) / sum(rate(gotk_reconcile_duration_seconds_count{exported_namespace=~"$namespace",kind=~"Kustomization\|HelmRelease"}[5m])) by (kind)` | query executed and returned data |
| [ ] | EMPTY | panel | Source acquisition readiness  | A | Mimir | `label_join(gotk_reconcile_condition{exported_namespace=~"$namespace",type="Ready",status="False",kind=~"GitRepository\|HelmRepository\|Bucket"}, "join_key", ",", "kind", "exported_namespace", "name")` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Source acquisition readiness  | B | Mimir | `label_join(gotk_suspend_status{exported_namespace=~"$namespace",kind=~"GitRepository\|HelmRepository\|Bucket"} - 2, "join_key", ",", "kind", "exported_namespace", "name")` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Application reconciliation readiness  | A | Mimir | `label_join(gotk_reconcile_condition{exported_namespace=~"$namespace",type="Ready",status="False",kind=~"Kustomization\|HelmRelease"}, "join_key", ",", "kind", "exported_namespace", "name")` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Application reconciliation readiness  | B | Mimir | `label_join(gotk_suspend_status{exported_namespace=~"$namespace",kind=~"Kustomization\|HelmRelease"} - 2, "join_key", ",", "kind", "exported_namespace", "name")` | query executed successfully but returned no data |
| [x] | PASS | panel | Source reconciliation duration | A | Mimir | `sum(rate(gotk_reconcile_duration_seconds_sum{exported_namespace=~"$namespace",kind=~"GitRepository\|HelmRepository\|Bucket"}[5m])) by (kind, exported_namespace, name) / sum(rate(gotk_reconcile_duration_seconds_count{exported_namespace=~"$namespace",kind=~"GitRepository\|HelmRepository\|Bucket"}[5m])) by (kind, exported_namespace, name)` | query executed and returned data |
| [x] | PASS | panel | Application reconciliation duration | A | Mimir | `sum(rate(gotk_reconcile_duration_seconds_sum{exported_namespace=~"$namespace",kind=~"Kustomization\|HelmRelease"}[5m])) by (kind, name, exported_namespace) / sum(rate(gotk_reconcile_duration_seconds_count{exported_namespace=~"$namespace",kind=~"Kustomization\|HelmRelease"}[5m])) by (kind, name, exported_namespace)` | query executed and returned data |

### KEDA Autoscaling (`keda-autoscaling`)

Folder: Cluster · Panels: 21 · Queries: 25

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: namespace | namespace | mimir | `label_values(keda_resource_registered_total, exported_namespace)` | query executed and returned data |
| [x] | PASS | variable | Variable: scaledObject | scaledObject | mimir | `label_values(keda_scaler_active{exported_namespace=~"$namespace"}, scaledObject)` | query executed and returned data |
| [x] | PASS | panel | ScaledObjects | A | mimir | `sum(max by (exported_namespace, type) (keda_resource_registered_total{type="scaled_object", exported_namespace=~"$namespace"})) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | ScaledJobs | A | mimir | `sum(max by (exported_namespace, type) (keda_resource_registered_total{type="scaled_job", exported_namespace=~"$namespace"})) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | Active scalers | A | mimir | `sum(max by (exported_namespace, scaledObject, scaler, triggerIndex) (keda_scaler_active{exported_namespace=~"$namespace", scaledObject=~"$scaledObject"})) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | Scalers in error [5m] | A | mimir | `count(max by (exported_namespace, scaledObject, scaler, triggerIndex) (rate(keda_scaler_detail_errors_total{exported_namespace=~"$namespace", scaledObject=~"$scaledObject"}[5m])) > 0) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | KEDA-managed HPAs | A | mimir | `count(kube_horizontalpodautoscaler_spec_max_replicas{horizontalpodautoscaler=~"keda-hpa-.*", namespace=~"$namespace"})` | query executed and returned data |
| [x] | PASS | panel | Current replicas (managed) | A | mimir | `sum(kube_horizontalpodautoscaler_status_current_replicas{horizontalpodautoscaler=~"keda-hpa-.*", namespace=~"$namespace"})` | query executed and returned data |
| [x] | PASS | panel | ScaledObjects — scaler activity & resulting HPA replicas | Act | mimir | `label_replace(max by (exported_namespace, scaledObject) (keda_scaler_active{exported_namespace=~"$namespace", scaledObject=~"$scaledObject"}), "namespace", "$1", "exported_namespace", "(.*)")` | query executed and returned data |
| [x] | PASS | panel | ScaledObjects — scaler activity & resulting HPA replicas | Val | mimir | `label_replace(max by (exported_namespace, scaledObject) (keda_scaler_metrics_value{exported_namespace=~"$namespace", scaledObject=~"$scaledObject"}), "namespace", "$1", "exported_namespace", "(.*)")` | query executed and returned data |
| [x] | PASS | panel | ScaledObjects — scaler activity & resulting HPA replicas | Cur | mimir | `label_replace(max by (namespace, horizontalpodautoscaler) (kube_horizontalpodautoscaler_status_current_replicas{horizontalpodautoscaler=~"keda-hpa-.*", namespace=~"$namespace"}), "scaledObject", "$1", "horizontalpodautoscaler", "keda-hpa-(.*)")` | query executed and returned data |
| [x] | PASS | panel | ScaledObjects — scaler activity & resulting HPA replicas | Des | mimir | `label_replace(max by (namespace, horizontalpodautoscaler) (kube_horizontalpodautoscaler_status_desired_replicas{horizontalpodautoscaler=~"keda-hpa-.*", namespace=~"$namespace"}), "scaledObject", "$1", "horizontalpodautoscaler", "keda-hpa-(.*)")` | query executed and returned data |
| [x] | PASS | panel | ScaledObjects — scaler activity & resulting HPA replicas | Min | mimir | `label_replace(max by (namespace, horizontalpodautoscaler) (kube_horizontalpodautoscaler_spec_min_replicas{horizontalpodautoscaler=~"keda-hpa-.*", namespace=~"$namespace"}), "scaledObject", "$1", "horizontalpodautoscaler", "keda-hpa-(.*)")` | query executed and returned data |
| [x] | PASS | panel | ScaledObjects — scaler activity & resulting HPA replicas | Max | mimir | `label_replace(max by (namespace, horizontalpodautoscaler) (kube_horizontalpodautoscaler_spec_max_replicas{horizontalpodautoscaler=~"keda-hpa-.*", namespace=~"$namespace"}), "scaledObject", "$1", "horizontalpodautoscaler", "keda-hpa-(.*)")` | query executed and returned data |
| [x] | PASS | panel | Scaler active (1 = active) | A | mimir | `max by (exported_namespace, scaledObject, scaler, triggerIndex) (keda_scaler_active{exported_namespace=~"$namespace", scaledObject=~"$scaledObject"})` | query executed and returned data |
| [x] | PASS | panel | Scaler metric value | A | mimir | `max by (exported_namespace, scaledObject, scaler, metric, triggerIndex) (keda_scaler_metrics_value{exported_namespace=~"$namespace", scaledObject=~"$scaledObject"})` | query executed and returned data |
| [x] | PASS | panel | Scaler metric latency | A | mimir | `max by (exported_namespace, scaledObject, scaler, triggerIndex) (keda_scaler_metrics_latency_seconds{exported_namespace=~"$namespace", scaledObject=~"$scaledObject"})` | query executed and returned data |
| [x] | PASS | panel | HPA replicas — current vs desired | A | mimir | `max by (namespace, horizontalpodautoscaler) (kube_horizontalpodautoscaler_status_current_replicas{horizontalpodautoscaler=~"keda-hpa-.*", namespace=~"$namespace"})` | query executed and returned data |
| [x] | PASS | panel | HPA replicas — current vs desired | B | mimir | `max by (namespace, horizontalpodautoscaler) (kube_horizontalpodautoscaler_status_desired_replicas{horizontalpodautoscaler=~"keda-hpa-.*", namespace=~"$namespace"})` | query executed and returned data |
| [x] | PASS | panel | Trigger totals by type | A | mimir | `max by (type) (keda_trigger_registered_total)` | query executed and returned data |
| [x] | PASS | panel | Resource totals by type | A | mimir | `sum by (type) (max by (exported_namespace, type) (keda_resource_registered_total{exported_namespace=~"$namespace"}))` | query executed and returned data |
| [x] | PASS | panel | KEDA build info | A | mimir | `max by (version) (keda_build_info)` | query executed and returned data |
| [x] | PASS | panel | Error rates [5m] | A | mimir | `max by (exported_namespace, scaledObject) (rate(keda_scaled_object_errors_total{exported_namespace=~"$namespace", scaledObject=~"$scaledObject"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Error rates [5m] | B | mimir | `max by (exported_namespace, scaledObject, scaler, triggerIndex) (rate(keda_scaler_detail_errors_total{exported_namespace=~"$namespace", scaledObject=~"$scaledObject"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Metrics-apiserver gRPC calls [5m] (live today) | A | mimir | `sum by (grpc_method, grpc_code) (rate(keda_internal_metricsservice_grpc_client_handled_total[5m]))` | query executed and returned data |

### Kubernetes Logs from Loki (`ae3ec2c4-1c19-4450-9403-226270fe0c4f`)

Folder: Observability · Panels: 2 · Queries: 2

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | panel | Untitled | A | Loki | `sum(count_over_time({namespace=~"$namespace", pod=~"$pod"} \|~ "$search"[$__interval]))` | query executed and returned data |
| [x] | PASS | panel | Logs Panel | A | Loki | `{namespace=~"$namespace", pod=~"$pod"} \|~ "(?i)$search"` | query executed and returned data |

### KubeVirt / Control Plane (`V1Qq_IBM_za0`)

Folder: Virtualization · Panels: 46 · Queries: 47

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: cluster | cluster | $datasource | `label_values(apiserver_request_total, cluster)` | query executed and returned data |
| [ ] | EMPTY | variable | Variable: instance | instance | $datasource | `label_values(container_cpu_usage_seconds_total{service="kubelet", cluster="$cluster"}, instance)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | VMI Creation Time | E | Cluster Prometheus | `histogram_quantile(0.95, sum(rate(kubevirt_vmi_phase_transition_time_from_creation_seconds_bucket{instance=~"$instance"}[5m])) by (phase, le))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | VMI Start Rate | A | Cluster Prometheus | `sum(rate(kubevirt_vmi_phase_transition_time_from_creation_seconds_count{phase="Running", instance=~"$instance"}[5m])) by (instance)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | VMI Phase Transition Latency | A | Cluster Prometheus | `histogram_quantile(0.95, sum(rate(kubevirt_vmi_phase_transition_time_seconds_bucket{phase="Pending", instance=~"$instance"}[5m])) by (le,phase))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | VMI Phase Transition Latency | B | Cluster Prometheus | `histogram_quantile(0.95, sum(rate(kubevirt_vmi_phase_transition_time_seconds_bucket{phase="Scheduling", instance=~"$instance"}[5m])) by (le,phase))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | VMI Phase Transition Latency | C | Cluster Prometheus | `histogram_quantile(0.95, sum(rate(kubevirt_vmi_phase_transition_time_seconds_bucket{phase="Scheduled", instance=~"$instance"}[5m])) by (le,phase))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | VMI Phase Transition Latency | D | Cluster Prometheus | `histogram_quantile(0.95, sum(rate(kubevirt_vmi_phase_transition_time_seconds_bucket{phase="Running", instance=~"$instance"}[5m])) by (le,phase))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | VMI Phase Transition Latency | E | Cluster Prometheus | `histogram_quantile(0.95, sum(rate(kubevirt_vmi_phase_transition_time_seconds_bucket{phase="Succeeded", instance=~"$instance"}[5m])) by (le,phase))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | VMI Phase Transition Latency | F | Cluster Prometheus | `histogram_quantile(0.95, sum(rate(kubevirt_vmi_phase_transition_time_seconds_bucket{phase="Failed", instance=~"$instance"}[5m])) by (le,phase))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | VMI Count (approx.) | A | Cluster Prometheus | `sum(increase(kubevirt_vmi_phase_transition_time_from_creation_seconds_count{phase="Failed", instance=~"$instance"}[20m])) by (instance)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | VMI Count (approx.) | B | Cluster Prometheus | `sum(increase(kubevirt_vmi_phase_transition_time_from_creation_seconds_count{phase="Running", instance=~"$instance"}[20m])) by (instance)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | API Server - Read Requests Rate | A | Cluster Prometheus | `sum(rate(apiserver_request_total{group=~".*kubevirt.*", instance=~"$instance", verb=~"LIST\|GET"}[5m])) by (code, group)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | API Server - Read Requests Duration | A | Cluster Prometheus | `histogram_quantile(0.90, sum(rate(apiserver_request_duration_seconds_bucket{group="kubevirt.io", instance=~"$instance", verb=~"LIST\|GET", scope="cluster"}[5m])) by (le, resource, verb))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | API Server - Write Requests Rate | B | Cluster Prometheus | `sum(irate(rest_client_requests_total{instance=~"$instance", pod=~"virt-controller.*\|virt-handler.*\|virt-operator.*\|virt-api.*\|vm.*\|hco.*\|kubevirt.*", container!="", method=~"POST\|PUT\|PATCH\|DELETE"}[2m])) by (code, group, container, job, verb, method) > 0` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | API Server - Write Requests Duration | A | Cluster Prometheus | `histogram_quantile(0.90, sum(rate(apiserver_request_duration_seconds_bucket{group="kubevirt.io", instance=~"$instance", verb=~"POST\|PUT\|PATCH\|DELETE"}[5m])) by (le, verb, resource)) > 0` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | API Client - Read Requests Rate | B | Cluster Prometheus | `sum(irate(rest_client_requests_total{instance=~"$instance", pod=~"virt-controller.*\|virt-handler.*\|virt-operator.*\|virt-api.*\|vm.*\|hco.*\|kubevirt.*", container!="", method=~"GET\|LIST"}[2m])) by (code, container, job, verb, method) > 0` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | API Client - Read Requests Duration | A | Cluster Prometheus | `histogram_quantile(0.99, sum(rate(rest_client_request_latency_seconds_bucket{instance=~"$instance", verb=~"GET\|LIST", container!=""}[2m])) by (le, verb, container)) > 0` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | API Client - Write Requests Rate | B | Cluster Prometheus | `sum(irate(rest_client_requests_total{instance=~"$instance", pod=~"virt-controller.*\|virt-handler.*\|virt-operator.*\|virt-api.*\|vm.*\|hco.*\|kubevirt.*", container!="", method=~"POST\|PUT\|PATCH\|DELETE"}[2m])) by (code, container, job, verb, method) > 0` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | API Client - Write Requests Duration | B | Cluster Prometheus | `histogram_quantile(0.99, sum(rate(rest_client_request_latency_seconds_bucket{instance=~"$instance", verb=~"POST\|PUT\|PATCH\|DELETE", container!=""}[2m])) by (le, verb, container)) > 0` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | API Client - Rate Limiter Duration | A | Cluster Prometheus | `histogram_quantile(0.99, sum(irate(rest_client_rate_limiter_duration_seconds_bucket{instance=~"$instance", container!=""}[5m])) by (container, le))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Work Queue - Add Rate | A | Cluster Prometheus | `sum(rate(kubevirt_workqueue_adds_total{job=~".*kubevirt.*", instance=~"$instance"}[1m])) by (instance, name)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Work Queue - Depth | A | Cluster Prometheus | `kubevirt_workqueue_depth{job=~".*kubevirt.*", instance=~"$instance"}` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Work Queue - Queue Duration | B | Cluster Prometheus | `histogram_quantile(0.99, sum(rate(kubevirt_workqueue_queue_duration_seconds_bucket{job=~".*kubevirt.*", instance=~"$instance"}[1m])) by (instance, name, le))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Work Queue - Work Duration | B | Cluster Prometheus | `histogram_quantile(0.99, sum(rate(kubevirt_workqueue_work_duration_seconds_bucket{job=~".*kubevirt.*", instance=~"$instance"}[1m])) by (instance, name, le))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Work Queue - Unfinished Work | A | Cluster Prometheus | `kubevirt_workqueue_unfinished_work_seconds{job=~".*kubevirt.*", instance=~"$instance"}` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Work Queue - Retry Rate | A | Cluster Prometheus | `rate(kubevirt_workqueue_retries_total{instance=~"$instance"}[1m])` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Work Queue - Longest Running Processor | A | Cluster Prometheus | `kubevirt_workqueue_longest_running_processor_seconds{job=~".*kubevirt.*", instance=~"$instance"}` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | API Client - Read Requests Rate | B | Cluster Prometheus | `sum(irate(rest_client_requests_total{instance=~"$instance", pod!~"virt-controller.*\|virt-handler.*\|virt-operator.*\|virt-api.*\|vm.*\|hco.*\|kubevirt.*", container!="", method=~"GET\|LIST"}[2m])) by (code, container, job, verb, method) > 0` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | API Server - Read Requests Duration | A | Cluster Prometheus | `histogram_quantile(0.90, sum(rate(apiserver_request_duration_seconds_bucket{group!="kubevirt.io", instance=~"$instance", verb=~"GET\|LIST"}[5m])) by (le, verb, resource)) > 0` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | API Client - Write Requests Rate | B | Cluster Prometheus | `sum(irate(rest_client_requests_total{instance=~"$instance", pod!~"virt-controller.*\|virt-handler.*\|virt-operator.*\|virt-api.*\|vm.*\|hco.*\|kubevirt.*", container!="", method=~"POST\|PUT\|PATCH\|DELETE"}[2m])) by (code, container, job, verb, method) > 0` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | API Server - Write Requests Duration | A | Cluster Prometheus | `histogram_quantile(0.90, sum(rate(apiserver_request_duration_seconds_bucket{group!="kubevirt.io", instance=~"$instance", verb=~"POST\|PUT\|PATCH\|DELETE"}[5m])) by (le, verb, resource)) > 0` | query executed successfully but returned no data |
| [x] | PASS | panel | Schedule Latency | B | Cluster Prometheus | `histogram_quantile(0.99, sum(rate(scheduler_scheduling_attempt_duration_seconds_bucket{}[5m])) by (le, container))` | query executed and returned data |
| [x] | PASS | panel | Pod Start Latency | B | Cluster Prometheus | `histogram_quantile(0.99, sum(rate(kubelet_pod_start_duration_seconds_bucket{}[5m])) by (instance, le)) > 0` | query executed and returned data |
| [ ] | EMPTY | panel | Memory | A | Cluster Prometheus | `sum(process_resident_memory_bytes{job=~".*kubevirt.*", instance=~"$instance"}) by (instance, container)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | CPU usage | A | Cluster Prometheus | `sum(rate(process_cpu_seconds_total{job=~".*kubevirt.*", instance=~"$instance"}[5m])) by (instance, container)` | query executed successfully but returned no data |
| [x] | PASS | panel | Open Files | A | Cluster Prometheus | `sum(rate(process_open_fds{container!=""}[10m])) by (container)` | query executed and returned data |
| [ ] | EMPTY | panel | Network | A | Cluster Prometheus | `sum(rate(container_network_receive_bytes_total{namespace=~".*kubevirt.*\|openshift-cnv", instance=~"$instance"}[5m])) by (node, pod) + sum(rate(container_network_transmit_bytes_total{namespace=~".*kubevirt.*\|openshift-cnv", instance=~"$instance"}[5m])) by (node, pod)` | query executed successfully but returned no data |
| [x] | PASS | panel | GC Duration Mean | A | Cluster Prometheus | `sum(rate(go_gc_duration_seconds_sum{}[10m])) by (container) / sum(rate(go_gc_duration_seconds_count{}[10m])) by (container)` | query executed and returned data |
| [ ] | EMPTY | panel | Goroutines | A | Cluster Prometheus | `go_goroutines{job=~".*kubevirt.*", instance=~"$instance"}` | query executed successfully but returned no data |
| [x] | PASS | panel | Threads | A | Cluster Prometheus | `sum(go_threads{container!=""}) by(container)` | query executed and returned data |
| [ ] | EMPTY | panel | Storage Operation Rate | A | Cluster Prometheus | `sum(rate(storage_operation_duration_seconds_count{metrics_path="/metrics", instance=~"$instance"}[5m])) by (instance, operation_name, volume_plugin)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Storage Operation Error Rate | A | Cluster Prometheus | `sum(rate(storage_operation_errors_total{metrics_path="/metrics", instance=~"$instance"}[5m])) by (instance, operation_name, volume_plugin)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | 99th %ile all Etcd Request Duration | B | Cluster Prometheus | `histogram_quantile(0.99,sum(rate(etcd_request_duration_seconds_bucket{instance=~"$instance"}[2m])) by (le,operation,apiserver)) > 0` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Etcd DB Size | A | Cluster Prometheus | `sum(etcd_mvcc_db_total_size_in_bytes{instance=~"$instance"}) by (instance)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | 99th %ile all Etcd Wal Fsync Duration | B | Cluster Prometheus | `histogram_quantile(0.99, rate(etcd_disk_wal_fsync_duration_seconds_bucket{instance=~"$instance"}[2m])) > 0` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | 99th %ile all Etcd RTT Duration | A | Cluster Prometheus | `histogram_quantile(0.99, rate(etcd_network_peer_round_trip_time_seconds_bucket{instance=~"$instance"}[2m])) > 0` | query executed successfully but returned no data |

### KubeVirt VM Info (`kubevirt-vm-info`)

Folder: Virtualization · Panels: 22 · Queries: 29

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [ ] | EMPTY | variable | Variable: vm | vm | ${datasource} | `label_values(kubevirt_vmi_info, name)` | query executed successfully but returned no data |
| [x] | PASS | panel | Running VMs | A | ${datasource} | `count(kubevirt_vmi_info) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | Total vCPUs | A | ${datasource} | `count(kubevirt_vmi_vcpu_seconds_total) or vector(0)` | query executed and returned data |
| [ ] | EMPTY | panel | Avg Memory Usage | A | ${datasource} | `avg(kubevirt_vmi_memory_used_ratio)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | VM Inventory | A | ${datasource} | `kubevirt_vmi_info` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | CPU Usage (rate) | A | ${datasource} | `rate(kubevirt_vmi_cpu_usage_seconds_total{name=~"$vm"}[$__rate_interval])` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | vCPU Wait Time | A | ${datasource} | `rate(kubevirt_vmi_vcpu_wait_seconds_total{name=~"$vm"}[$__rate_interval])` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Memory Usage (Resident) | A | ${datasource} | `kubevirt_vmi_memory_resident_bytes{name=~"$vm"}` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Memory Usage (Resident) | B | ${datasource} | `kubevirt_vmi_memory_available_bytes{name=~"$vm"}` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Memory Used Ratio | A | ${datasource} | `kubevirt_vmi_memory_used_ratio{name=~"$vm"}` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Memory Swap Traffic | A | ${datasource} | `rate(kubevirt_vmi_memory_swap_in_traffic_bytes{name=~"$vm"}[$__rate_interval])` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Memory Swap Traffic | B | ${datasource} | `rate(kubevirt_vmi_memory_swap_out_traffic_bytes{name=~"$vm"}[$__rate_interval])` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Page Faults | A | ${datasource} | `rate(kubevirt_vmi_memory_pgmajfault_total{name=~"$vm"}[$__rate_interval])` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Page Faults | B | ${datasource} | `rate(kubevirt_vmi_memory_pgminfault_total{name=~"$vm"}[$__rate_interval])` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Network Throughput | A | ${datasource} | `rate(kubevirt_vmi_network_receive_bytes_total{name=~"$vm"}[$__rate_interval])` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Network Throughput | B | ${datasource} | `-rate(kubevirt_vmi_network_transmit_bytes_total{name=~"$vm"}[$__rate_interval])` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Network Packets | A | ${datasource} | `rate(kubevirt_vmi_network_receive_packets_total{name=~"$vm"}[$__rate_interval])` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Network Packets | B | ${datasource} | `-rate(kubevirt_vmi_network_transmit_packets_total{name=~"$vm"}[$__rate_interval])` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Network Errors & Drops | A | ${datasource} | `rate(kubevirt_vmi_network_receive_errors_total{name=~"$vm"}[$__rate_interval])` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Network Errors & Drops | B | ${datasource} | `rate(kubevirt_vmi_network_transmit_errors_total{name=~"$vm"}[$__rate_interval])` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Network Errors & Drops | C | ${datasource} | `rate(kubevirt_vmi_network_receive_packets_dropped_total{name=~"$vm"}[$__rate_interval])` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Network Errors & Drops | D | ${datasource} | `rate(kubevirt_vmi_network_transmit_packets_dropped_total{name=~"$vm"}[$__rate_interval])` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Storage IOPS | A | ${datasource} | `rate(kubevirt_vmi_storage_iops_read_total{name=~"$vm"}[$__rate_interval])` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Storage IOPS | B | ${datasource} | `rate(kubevirt_vmi_storage_iops_write_total{name=~"$vm"}[$__rate_interval])` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Storage Throughput | A | ${datasource} | `rate(kubevirt_vmi_storage_read_traffic_bytes_total{name=~"$vm"}[$__rate_interval])` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Storage Throughput | B | ${datasource} | `rate(kubevirt_vmi_storage_write_traffic_bytes_total{name=~"$vm"}[$__rate_interval])` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Storage Latency | A | ${datasource} | `rate(kubevirt_vmi_storage_read_times_seconds_total{name=~"$vm"}[$__rate_interval]) / rate(kubevirt_vmi_storage_iops_read_total{name=~"$vm"}[$__rate_interval])` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Storage Latency | B | ${datasource} | `rate(kubevirt_vmi_storage_write_times_seconds_total{name=~"$vm"}[$__rate_interval]) / rate(kubevirt_vmi_storage_iops_write_total{name=~"$vm"}[$__rate_interval])` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Storage Flush Operations | A | ${datasource} | `rate(kubevirt_vmi_storage_flush_requests_total{name=~"$vm"}[$__rate_interval])` | query executed successfully but returned no data |

### KubeVirt VM Ops (`kubevirt-vm-ops`)

Folder: Virtualization · Panels: 22 · Queries: 38

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [ ] | EMPTY | variable | Variable: namespace | namespace | mimir | `label_values(kubevirt_vmi_info, namespace)` | query executed successfully but returned no data |
| [ ] | EMPTY | variable | Variable: vm | vm | mimir | `label_values(kubevirt_vmi_info{namespace=~"$namespace"}, name)` | query executed successfully but returned no data |
| [x] | PASS | panel | Total VMs | A | mimir | `count(kubevirt_vm_info{namespace=~"$namespace", name=~"$vm"})` | query executed and returned data |
| [ ] | EMPTY | panel | Running | A | mimir | `count(kubevirt_vm_info{status_group="running", namespace=~"$namespace", name=~"$vm"})` | query executed successfully but returned no data |
| [x] | PASS | panel | Not Running | A | mimir | `count(kubevirt_vm_info{status_group!="running", namespace=~"$namespace", name=~"$vm"})` | query executed and returned data |
| [ ] | EMPTY | panel | Total vCPUs | A | mimir | `sum(count by (namespace, name) (kubevirt_vmi_vcpu_seconds_total{namespace=~"$namespace", name=~"$vm"}))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Allocated Memory | A | mimir | `sum(kubevirt_vmi_memory_domain_bytes{namespace=~"$namespace", name=~"$vm"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | VM Inventory | A | mimir | `max by (namespace, name, node, phase, guest_os_machine) (kubevirt_vmi_info{namespace=~"$namespace", name=~"$vm"})` | query executed successfully but returned no data |
| [x] | PASS | panel | VM Inventory | B | mimir | `max by (namespace, name, machine_type, status) (kubevirt_vm_info{namespace=~"$namespace", name=~"$vm"})` | query executed and returned data |
| [ ] | EMPTY | panel | VM Inventory | C | mimir | `max by (namespace, name, address) (kubevirt_vmi_status_addresses{type="InternalIP", namespace=~"$namespace", name=~"$vm"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | VM Inventory | D | mimir | `count by (namespace, name) (kubevirt_vmi_vcpu_seconds_total{namespace=~"$namespace", name=~"$vm"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | VM Inventory | E | mimir | `max by (namespace, name) (kubevirt_vmi_memory_domain_bytes{namespace=~"$namespace", name=~"$vm"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | VM Inventory | F | mimir | `100 * (1 - sum by (namespace, name) (kubevirt_vmi_memory_unused_bytes{namespace=~"$namespace", name=~"$vm"}) / sum by (namespace, name) (kubevirt_vmi_memory_available_bytes{namespace=~"$namespace", name=~"$vm"}))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | CPU Usage | A | mimir | `sum by (namespace, name) (rate(kubevirt_vmi_cpu_usage_seconds_total{namespace=~"$namespace", name=~"$vm"}[5m]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | vCPU Wait & Delay | A | mimir | `sum by (namespace, name) (rate(kubevirt_vmi_vcpu_wait_seconds_total{namespace=~"$namespace", name=~"$vm"}[5m]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | vCPU Wait & Delay | B | mimir | `sum by (namespace, name) (rate(kubevirt_vmi_vcpu_delay_seconds_total{namespace=~"$namespace", name=~"$vm"}[5m]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Memory: Used vs Allocated | A | mimir | `sum by (namespace, name) (kubevirt_vmi_memory_available_bytes{namespace=~"$namespace", name=~"$vm"} - kubevirt_vmi_memory_unused_bytes{namespace=~"$namespace", name=~"$vm"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Memory: Used vs Allocated | B | mimir | `sum by (namespace, name) (kubevirt_vmi_memory_resident_bytes{namespace=~"$namespace", name=~"$vm"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Memory: Used vs Allocated | C | mimir | `sum by (namespace, name) (kubevirt_vmi_memory_domain_bytes{namespace=~"$namespace", name=~"$vm"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Memory Pressure: Swap & Page Faults | A | mimir | `sum by (namespace, name) (rate(kubevirt_vmi_memory_swap_in_traffic_bytes{namespace=~"$namespace", name=~"$vm"}[5m]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Memory Pressure: Swap & Page Faults | B | mimir | `sum by (namespace, name) (rate(kubevirt_vmi_memory_swap_out_traffic_bytes{namespace=~"$namespace", name=~"$vm"}[5m]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Memory Pressure: Swap & Page Faults | C | mimir | `sum by (namespace, name) (rate(kubevirt_vmi_memory_pgmajfault_total{namespace=~"$namespace", name=~"$vm"}[5m]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Network Throughput (RX / TX) | A | mimir | `sum by (namespace, name) (rate(kubevirt_vmi_network_receive_bytes_total{namespace=~"$namespace", name=~"$vm"}[5m]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Network Throughput (RX / TX) | B | mimir | `sum by (namespace, name) (rate(kubevirt_vmi_network_transmit_bytes_total{namespace=~"$namespace", name=~"$vm"}[5m]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Network Packets & Drops | A | mimir | `sum by (namespace, name) (rate(kubevirt_vmi_network_receive_packets_total{namespace=~"$namespace", name=~"$vm"}[5m]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Network Packets & Drops | B | mimir | `sum by (namespace, name) (rate(kubevirt_vmi_network_transmit_packets_total{namespace=~"$namespace", name=~"$vm"}[5m]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Network Packets & Drops | C | mimir | `sum by (namespace, name) (rate(kubevirt_vmi_network_receive_packets_dropped_total{namespace=~"$namespace", name=~"$vm"}[5m]) + rate(kubevirt_vmi_network_transmit_packets_dropped_total{namespace=~"$namespace", name=~"$vm"}[5m]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Storage Throughput (Read / Write) | A | mimir | `sum by (namespace, name, drive) (rate(kubevirt_vmi_storage_read_traffic_bytes_total{namespace=~"$namespace", name=~"$vm"}[5m]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Storage Throughput (Read / Write) | B | mimir | `sum by (namespace, name, drive) (rate(kubevirt_vmi_storage_write_traffic_bytes_total{namespace=~"$namespace", name=~"$vm"}[5m]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Storage IOPS (Read / Write) | A | mimir | `sum by (namespace, name, drive) (rate(kubevirt_vmi_storage_iops_read_total{namespace=~"$namespace", name=~"$vm"}[5m]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Storage IOPS (Read / Write) | B | mimir | `sum by (namespace, name, drive) (rate(kubevirt_vmi_storage_iops_write_total{namespace=~"$namespace", name=~"$vm"}[5m]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Storage Latency (avg per op) | A | mimir | `sum by (namespace, name, drive) (rate(kubevirt_vmi_storage_read_times_seconds_total{namespace=~"$namespace", name=~"$vm"}[5m])) / clamp_min(sum by (namespace, name, drive) (rate(kubevirt_vmi_storage_iops_read_total{namespace=~"$namespace", name=~"$vm"}[5m])), 1)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Storage Latency (avg per op) | B | mimir | `sum by (namespace, name, drive) (rate(kubevirt_vmi_storage_write_times_seconds_total{namespace=~"$namespace", name=~"$vm"}[5m])) / clamp_min(sum by (namespace, name, drive) (rate(kubevirt_vmi_storage_iops_write_total{namespace=~"$namespace", name=~"$vm"}[5m])), 1)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Guest & Virt Parameters | A | mimir | `max by (namespace, name, node, phase, guest_os_machine, os, instance_type, evictable, outdated) (kubevirt_vmi_info{namespace=~"$namespace", name=~"$vm"})` | query executed successfully but returned no data |
| [x] | PASS | panel | Guest & Virt Parameters | B | mimir | `max by (namespace, name, machine_type) (kubevirt_vm_info{namespace=~"$namespace", name=~"$vm"})` | query executed and returned data |
| [x] | PASS | panel | VM Migrations by Phase | A | mimir | `sum(kubevirt_vmi_migrations_in_pending_phase)` | query executed and returned data |
| [x] | PASS | panel | VM Migrations by Phase | B | mimir | `sum(kubevirt_vmi_migrations_in_scheduling_phase)` | query executed and returned data |
| [x] | PASS | panel | VM Migrations by Phase | C | mimir | `sum(kubevirt_vmi_migrations_in_running_phase)` | query executed and returned data |

### Logging Dashboard via Loki v2 (`5rnLQdJVk`)

Folder: Observability · Panels: 10 · Queries: 12

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [ ] | REVIEW | variable | Variable: container | container | Loki | `label_values({container=~".+"}, container)` | Loki variable helper requires Grafana UI evaluation |
| [ ] | REVIEW | variable | Variable: pod | pod | Loki | `label_values({container="$container"}, pod)` | Loki variable helper requires Grafana UI evaluation |
| [ ] | REVIEW | variable | Variable: stream | stream | Loki | `label_values({container="$container"}, stream)` | Loki variable helper requires Grafana UI evaluation |
| [ ] | EMPTY | panel | Total  Count of logs | A | Loki | `sum(count_over_time(({container="$container", stream=~"$stream", pod=~"$pod"})[$__interval]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Total Count: of $searchable_pattern | A | Loki | `sum(count_over_time(({container="$container", stream=~"$stream", pod=~"$pod"} \|~ "(?i)$searchable_pattern")[$__interval]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Live logs | A | Loki | `{container="$container", pod=~"$pod", stream=~"$stream"} \|~ "(?i)$searchable_pattern"` | query executed successfully but returned no data |
| [x] | PASS | panel | Total count of stderr / stdout pie | A | Loki | `sum(count_over_time(({container="$container", pod=~"$pod"})[$__interval])) by (stream)` | query executed and returned data |
| [ ] | EMPTY | panel | Matched word: "$searchable_pattern" donut | A | Loki | `sum(count_over_time(({container="$container", pod=~"$pod", stream=~"$stream"} \|~ "(?i)$searchable_pattern")[$__interval])) by (pod)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | "$searchable_pattern" Percentage for specified time | A | Loki | `sum(count_over_time(({container="$container", stream=~"$stream", pod=~"$pod"} \|~ "(?i)$searchable_pattern")[$__interval])) * 100 / sum(count_over_time(({container="$container", stream=~"$stream", pod=~"$pod"})[$__interval]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Matched word: "$searchable_pattern" historical | A | Loki | `sum(count_over_time(({container="$container", pod=~"$pod", stream=~"$stream"} \|~ "(?i)$searchable_pattern")[$__interval])) by (pod)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | "$searchable_pattern" Rate per Pod | A | Loki | `sum(rate(({container="$container", stream=~"$stream", pod=~"$pod"} \|~ "(?i)$searchable_pattern")[30s])) by (pod)` | query executed successfully but returned no data |
| [x] | PASS | panel | Count of stderr / stdout historical | A | Loki | `sum(count_over_time(({container="$container", pod=~"$pod"})[$__interval])) by (stream)` | query executed and returned data |

### Monitoring Ops (`monitoring-ops`)

Folder: Observability · Panels: 37 · Queries: 38

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: job | job | mimir | `label_values(up, job)` | query executed and returned data |
| [x] | PASS | panel | Total Targets | A | mimir | `count(up)` | query executed and returned data |
| [x] | PASS | panel | Targets Up | A | mimir | `count(up==1)` | query executed and returned data |
| [x] | PASS | panel | Targets Down | A | mimir | `count(up==0)` | query executed and returned data |
| [x] | PASS | panel | Scrape Jobs | A | mimir | `count(count by (job)(up))` | query executed and returned data |
| [x] | PASS | panel | Targets Up / Down over time | A | mimir | `count(up==1)` | query executed and returned data |
| [x] | PASS | panel | Targets Up / Down over time | B | mimir | `count(up==0)` | query executed and returned data |
| [x] | PASS | panel | Down Targets (up == 0) | A | mimir | `up==0` | query executed and returned data |
| [x] | PASS | panel | Mimir Active Series | A | mimir | `sum(cortex_ingester_memory_series)` | query executed and returned data |
| [x] | PASS | panel | Alloy WAL Active Series | A | mimir | `sum(prometheus_remote_write_wal_storage_active_series)` | query executed and returned data |
| [x] | PASS | panel | Mimir Ingestion Rate | A | mimir | `sum(rate(cortex_distributor_received_samples_total[5m]))` | query executed and returned data |
| [x] | PASS | panel | Samples / Scrape (total) | A | mimir | `sum(scrape_samples_post_metric_relabeling)` | query executed and returned data |
| [x] | PASS | panel | Top 20 Jobs by Series (samples post-relabel) | A | mimir | `topk(20, sum by (job)(scrape_samples_post_metric_relabeling))` | query executed and returned data |
| [x] | PASS | panel | Mimir Ingestion Rate (samples/s) | A | mimir | `sum(rate(cortex_distributor_received_samples_total[5m]))` | query executed and returned data |
| [x] | PASS | panel | Mimir Ingestion Rate (samples/s) | B | mimir | `sum(rate(cortex_ingester_ingested_samples_failures_total[5m]))` | query executed and returned data |
| [x] | PASS | panel | Max Scrape Duration by Job | A | mimir | `max by (job)(scrape_duration_seconds)` | query executed and returned data |
| [x] | PASS | panel | Scrape Duration & Target Count by Job | A | mimir | `max by (job)(scrape_duration_seconds)` | query executed and returned data |
| [x] | PASS | panel | Alloy -> Mimir (samples/s) | A | mimir | `sum(rate(prometheus_remote_write_wal_samples_appended_total[5m]))` | query executed and returned data |
| [x] | PASS | panel | Alloy -> Loki (lines/s) | A | mimir | `sum(rate(loki_write_sent_entries_total[5m]))` | query executed and returned data |
| [x] | PASS | panel | Dropped Log Entries/s | A | mimir | `sum(rate(loki_write_dropped_entries_total[5m]))` | query executed and returned data |
| [x] | PASS | panel | Tempo Instances Up | A | mimir | `count(tempo_build_info)` | query executed and returned data |
| [x] | PASS | panel | Alloy -> Mimir Remote-Write (samples/s appended) | A | mimir | `sum(rate(prometheus_remote_write_wal_samples_appended_total[5m]))` | query executed and returned data |
| [x] | PASS | panel | Alloy -> Mimir Remote-Write (samples/s appended) | B | mimir | `sum(rate(prometheus_remote_write_wal_out_of_order_samples_total[5m]))` | query executed and returned data |
| [x] | PASS | panel | Alloy -> Loki Write Client (lines/s) | A | mimir | `sum(rate(loki_write_sent_entries_total[5m]))` | query executed and returned data |
| [x] | PASS | panel | Alloy -> Loki Write Client (lines/s) | B | mimir | `sum(rate(loki_write_dropped_entries_total[5m]))` | query executed and returned data |
| [x] | PASS | panel | Alloy WAL Active Series by instance | A | mimir | `sum by (instance)(prometheus_remote_write_wal_storage_active_series)` | query executed and returned data |
| [x] | PASS | panel | Mimir Ingester Active Series | A | mimir | `sum(cortex_ingester_memory_series)` | query executed and returned data |
| [x] | PASS | panel | kube_pod_info series count by job | A | mimir | `count by (job)(kube_pod_info)` | query executed and returned data |
| [x] | PASS | panel | kube_pod_info series by job (double-scrape) | A | mimir | `count by (job)(kube_pod_info)` | query executed and returned data |
| [x] | PASS | panel | Ruler → AM errors (15m) | A | mimir | `sum(increase(cortex_prometheus_notifications_errors_total[15m]))` | query executed and returned data |
| [x] | PASS | panel | Discord/Slack notify failures (15m) | A | mimir | `sum(increase(cortex_alertmanager_notifications_failed_total[15m]))` | query executed and returned data |
| [x] | PASS | panel | Delivery success % | A | mimir | `100 * (1 - sum(increase(cortex_alertmanager_notifications_failed_total[1h])) / clamp_min(sum(increase(cortex_alertmanager_notifications_total[1h])),1))` | query executed and returned data |
| [x] | PASS | panel | Alerts received by AM (15m) | A | mimir | `sum(increase(cortex_alertmanager_alerts_received_total[15m]))` | query executed and returned data |
| [x] | PASS | panel | Ruler → Alertmanager (per sec) | A | mimir | `sum(rate(cortex_prometheus_notifications_sent_total[5m]))` | query executed and returned data |
| [x] | PASS | panel | Ruler → Alertmanager (per sec) | B | mimir | `sum(rate(cortex_prometheus_notifications_errors_total[5m]))` | query executed and returned data |
| [x] | PASS | panel | Ruler → Alertmanager (per sec) | C | mimir | `sum(rate(cortex_prometheus_notifications_dropped_total[5m]))` | query executed and returned data |
| [x] | PASS | panel | Alertmanager → receivers (per sec, by integration) | A | mimir | `sum by (integration) (rate(cortex_alertmanager_notifications_total[5m]))` | query executed and returned data |
| [x] | PASS | panel | Alertmanager → receivers (per sec, by integration) | B | mimir | `sum by (integration) (rate(cortex_alertmanager_notifications_failed_total[5m]))` | query executed and returned data |

### Network Ops — Cilium & Hubble (`network-ops`)

Folder: Network · Panels: 44 · Queries: 42

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | panel | Cilium Agents Up | A | mimir | `count(cilium_version{container="cilium-agent"})` | query executed and returned data |
| [x] | PASS | panel | Endpoints Ready | A | mimir | `sum(cilium_endpoint_state{container="cilium-agent",endpoint_state="ready"})` | query executed and returned data |
| [x] | PASS | panel | Endpoints Not-Ready | A | mimir | `sum(cilium_endpoint_state{container="cilium-agent",endpoint_state!="ready"})` | query executed and returned data |
| [x] | PASS | panel | Unreachable Nodes | A | mimir | `max(cilium_unreachable_nodes{container="cilium-agent"})` | query executed and returned data |
| [x] | PASS | panel | Controllers Failing | A | mimir | `sum(cilium_controllers_failing{container="cilium-agent"})` | query executed and returned data |
| [x] | PASS | panel | Cilium Identities | A | mimir | `max(sum by (node) (cilium_identity{container="cilium-agent"}))` | query executed and returned data |
| [x] | PASS | panel | Datapath Drop Rate | A | mimir | `sum(rate(cilium_drop_count_total{container="cilium-agent"}[5m]))` | query executed and returned data |
| [ ] | EMPTY | panel | Unhealthy Node Links | A | mimir | `sum(cilium_node_connectivity_status{container="cilium-agent"} == bool 0)` | query executed successfully but returned no data |
| [x] | PASS | panel | Flow Rate by Verdict | A | mimir | `sum by (verdict) (rate(hubble_flows_processed_total[5m]))` | query executed and returned data |
| [x] | PASS | panel | Drops by Reason (Hubble) | A | mimir | `sum by (reason) (rate(hubble_drop_total[5m]))` | query executed and returned data |
| [x] | PASS | panel | Forwarded Traffic by Protocol | A | mimir | `sum by (protocol) (rate(hubble_flows_processed_total{verdict="FORWARDED"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | TCP Flags Rate | A | mimir | `sum by (flag) (rate(hubble_tcp_flags_total[5m]))` | query executed and returned data |
| [x] | PASS | panel | Forwarded vs Dropped (Datapath) | A | mimir | `sum(rate(cilium_forward_count_total{container="cilium-agent"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Forwarded vs Dropped (Datapath) | B | mimir | `sum(rate(cilium_drop_count_total{container="cilium-agent"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Datapath Drops by Reason | A | mimir | `sum by (reason) (rate(cilium_drop_count_total{container="cilium-agent"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Datapath Drops by Direction | A | mimir | `sum by (direction) (rate(cilium_drop_count_total{container="cilium-agent"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Policy-Denied Drop Rate | A | mimir | `sum(rate(cilium_drop_count_total{container="cilium-agent",reason="Policy denied"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Hubble Policy Verdicts | A | mimir | `sum by (action) (rate(hubble_policy_verdicts_total[5m]))` | query executed and returned data |
| [x] | PASS | panel | BPF Map Pressure (summary) | A | mimir | `topk(10, max by (map_name) (cilium_bpf_map_pressure{container="cilium-agent"}))` | query executed and returned data |
| [x] | PASS | panel | Endpoint Regeneration Rate | A | mimir | `sum(rate(cilium_endpoint_regenerations_total{container="cilium-agent",outcome="success"}[5m]))` | query executed and returned data |
| [ ] | EMPTY | panel | Endpoint Regeneration Rate | B | mimir | `sum(rate(cilium_endpoint_regenerations_total{container="cilium-agent",outcome="failure"}[5m]))` | query executed successfully but returned no data |
| [x] | PASS | panel | Identity Count Trend | A | mimir | `max(sum by (node) (cilium_identity{container="cilium-agent"}))` | query executed and returned data |
| [x] | PASS | panel | Identity Count Trend | B | mimir | `max by (type) (cilium_identity{container="cilium-agent"})` | query executed and returned data |
| [x] | PASS | panel | Endpoint State Distribution | A | mimir | `sum by (endpoint_state) (cilium_endpoint_state{container="cilium-agent"})` | query executed and returned data |
| [ ] | EMPTY | panel | Node Connectivity Latency | A | mimir | `avg by (target_node_name) (cilium_node_connectivity_latency_seconds{container="cilium-agent",type="node"})` | query executed successfully but returned no data |
| [x] | PASS | panel | Hubble Lost Events | A | mimir | `sum by (source) (rate(hubble_lost_events_total[5m]))` | query executed and returned data |
| [x] | PASS | panel | Soonest cert expiry | A | mimir | `min((certmanager_certificate_expiration_timestamp_seconds - time()) / 86400)` | query executed and returned data |
| [x] | PASS | panel | Certs not Ready | A | mimir | `count(certmanager_certificate_ready_status{condition="True"} == 0) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | Days to expiry per certificate | A | mimir | `(certmanager_certificate_expiration_timestamp_seconds - time()) / 86400` | query executed and returned data |
| [x] | PASS | panel | CrowdSec Active Bans | A | mimir | `sum(cs_active_decisions{action="ban"})` | query executed and returned data |
| [x] | PASS | panel | AppSec Requests/s | A | mimir | `sum(rate(cs_appsec_reqs_total[$__rate_interval]))` | query executed and returned data |
| [ ] | EMPTY | panel | LB-IPAM IPs Available | A | mimir | `sum(cilium_operator_lbipam_ips_available_total)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | LB-IPAM IPs Used | A | mimir | `sum(cilium_operator_lbipam_ips_used_total)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | LB Services Unsatisfied | A | mimir | `sum(cilium_operator_lbipam_services_unsatisfied_total)` | query executed successfully but returned no data |
| [x] | PASS | panel | Edge 403s/s | A | mimir | `sum(rate(traefik_entrypoint_requests_total{code="403"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Active Decisions by Reason (top 10) | A | mimir | `topk(10, sum by(reason)(cs_active_decisions))` | query executed and returned data |
| [x] | PASS | panel | Active Decisions by Origin | A | mimir | `sum by(origin)(cs_active_decisions)` | query executed and returned data |
| [ ] | EMPTY | panel | Bucket Overflows/s | A | mimir | `sum by(name)(rate(cs_bucket_overflowed_total[$__rate_interval]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | LB-IPAM Pool Utilization | A | mimir | `sum by(pool)(cilium_operator_lbipam_ips_available_total)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | LB-IPAM Pool Utilization | B | mimir | `sum by(pool)(cilium_operator_lbipam_ips_used_total)` | query executed successfully but returned no data |
| [x] | PASS | panel | cert-manager Sync Errors/s | A | mimir | `sum by(controller)(rate(certmanager_controller_sync_error_count[$__rate_interval])) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | Edge 403s/s (bouncer drops) | A | mimir | `sum by(entrypoint)(rate(traefik_entrypoint_requests_total{code="403"}[$__rate_interval]))` | query executed and returned data |

### Pi-hole — Cluster Aggregate (`pihole-cluster-aggregate`)

Folder: Network · Panels: 42 · Queries: 42

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | panel | DNS Queries (today) |  | mimir | `sum(pihole_dns_queries_today)` | query executed and returned data |
| [x] | PASS | panel | Ads Blocked (today) |  | mimir | `sum(pihole_ads_blocked_today)` | query executed and returned data |
| [x] | PASS | panel | Block % (aggregate) |  | mimir | `sum(pihole_ads_blocked_today) / clamp_min(sum(pihole_dns_queries_today), 1) * 100` | query executed and returned data |
| [x] | PASS | panel | Live Query Rate |  | mimir | `sum(pihole_request_rate)` | query executed and returned data |
| [x] | PASS | panel | Queries Cached (today) |  | mimir | `sum(pihole_queries_cached)` | query executed and returned data |
| [x] | PASS | panel | Queries Forwarded (today) |  | mimir | `sum(pihole_queries_forwarded)` | query executed and returned data |
| [x] | PASS | panel | Unique Clients (active) |  | mimir | `max(pihole_unique_clients)` | query executed and returned data |
| [x] | PASS | panel | Domains on Blocklist |  | mimir | `max(pihole_domains_being_blocked)` | query executed and returned data |
| [x] | PASS | panel | Block Rate |  | mimir | `sum(pihole_ads_blocked_today) / clamp_min(sum(pihole_dns_queries_today), 1) * 100` | query executed and returned data |
| [x] | PASS | panel | Cache Hit Rate |  | mimir | `sum(pihole_queries_cached) / clamp_min(sum(pihole_dns_queries_today), 1) * 100` | query executed and returned data |
| [x] | PASS | panel | Instances Reporting |  | mimir | `count(pihole_domains_being_blocked)` | query executed and returned data |
| [x] | PASS | panel | Active Instance — Queries Served Today (by pod) |  | mimir | `sum by (pod) (pihole_dns_queries_today)` | query executed and returned data |
| [x] | PASS | panel | DNS Query Rate (queries/sec) |  | mimir | `sum(pihole_request_rate)` | query executed and returned data |
| [x] | PASS | panel | DNS Query Rate (queries/sec) |  | mimir | `sum by (pod) (pihole_request_rate)` | query executed and returned data |
| [x] | PASS | panel | Unique Domains (today) |  | mimir | `max(pihole_unique_domains)` | query executed and returned data |
| [x] | PASS | panel | Clients Ever Seen |  | mimir | `max(pihole_clients_ever_seen)` | query executed and returned data |
| [x] | PASS | panel | Upstream Response Time (by resolver) |  | mimir | `avg by (destination_name) (pihole_forward_destinations_responsetime{destination_name!~"cache\|blocklist"})` | query executed and returned data |
| [x] | PASS | panel | Upstream Response Variance (jitter) |  | mimir | `avg by (destination_name) (pihole_forward_destinations_responsevariance{destination_name!~"cache\|blocklist"})` | query executed and returned data |
| [x] | PASS | panel | Query Types (aggregate) |  | mimir | `sum by (type) (pihole_querytypes)` | query executed and returned data |
| [x] | PASS | panel | Reply Types (aggregate) |  | mimir | `sum by (type) (pihole_reply)` | query executed and returned data |
| [x] | PASS | panel | Resolution Breakdown (aggregate) |  | mimir | `sum(pihole_ads_blocked_today)` | query executed and returned data |
| [x] | PASS | panel | Resolution Breakdown (aggregate) |  | mimir | `sum(pihole_queries_cached)` | query executed and returned data |
| [x] | PASS | panel | Resolution Breakdown (aggregate) |  | mimir | `sum(pihole_queries_forwarded)` | query executed and returned data |
| [x] | PASS | panel | Top Permitted Domains |  | mimir | `topk(15, sum by (domain) (pihole_top_queries{domain=~"(?i).*${search}.*"}))` | query executed and returned data |
| [x] | PASS | panel | Top Blocked Domains |  | mimir | `topk(15, sum by (domain) (pihole_top_ads{domain=~"(?i).*${search}.*"}))` | query executed and returned data |
| [x] | PASS | panel | Top Clients |  | mimir | `topk(15, sum by (source, source_name) (pihole_top_sources))` | query executed and returned data |
| [x] | PASS | panel | Forward Destinations |  | mimir | `topk(15, sum by (destination, destination_name) (pihole_forward_destinations))` | query executed and returned data |
| [x] | PASS | panel | Cluster Query Totals Over Time |  | mimir | `sum(pihole_dns_queries_today)` | query executed and returned data |
| [x] | PASS | panel | Cluster Query Totals Over Time |  | mimir | `sum(pihole_ads_blocked_today)` | query executed and returned data |
| [x] | PASS | panel | Cluster Query Totals Over Time |  | mimir | `sum(pihole_queries_cached)` | query executed and returned data |
| [x] | PASS | panel | Cluster Query Totals Over Time |  | mimir | `sum(pihole_queries_forwarded)` | query executed and returned data |
| [x] | PASS | panel | Per-Instance Blocking Status (1 = enabled) |  | mimir | `pihole_status` | query executed and returned data |
| [x] | PASS | panel | DNS Served per Instance (q/s, by pod) — spot handoffs & split-brain |  | mimir | `sum by (pod) (rate(pihole_dns_queries_today[10m]))` | query executed and returned data |
| [x] | PASS | panel | Last Sync Age |  | mimir | `time() - nebula_sync_last_success_timestamp_seconds` | query executed and returned data |
| [x] | PASS | panel | Last Sync Duration |  | mimir | `nebula_sync_duration_seconds` | query executed and returned data |
| [x] | PASS | panel | Replicas Synced (last) |  | mimir | `nebula_sync_replicas_synced` | query executed and returned data |
| [x] | PASS | panel | Replicas Failed (last) |  | mimir | `nebula_sync_replicas_failed` | query executed and returned data |
| [x] | PASS | panel | Sync Success Rate (1h) |  | mimir | `sum(rate(nebula_sync_runs_total{result="success"}[1h])) / clamp_min(sum(rate(nebula_sync_runs_total[1h])), 0.0001) * 100` | query executed and returned data |
| [x] | PASS | panel | Sync Runs (24h) |  | mimir | `sum(increase(nebula_sync_runs_total[24h]))` | query executed and returned data |
| [x] | PASS | panel | Sync Runs (success / failure) |  | mimir | `sum by (result) (increase(nebula_sync_runs_total[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Sync Duration & Failed Replicas |  | mimir | `nebula_sync_duration_seconds` | query executed and returned data |
| [x] | PASS | panel | Sync Duration & Failed Replicas |  | mimir | `nebula_sync_replicas_failed` | query executed and returned data |

### Ping Exporter (`pv02xrZWz`)

Folder: GitOps · Panels: 3 · Queries: 11

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [ ] | EMPTY | variable | Variable: job | job | $Datasource | `label_values(ping_loss_ratio,job)` | query executed successfully but returned no data |
| [ ] | EMPTY | variable | Variable: instance | instance | $Datasource | `label_values(ping_loss_ratio{job=~"$job"},instance)` | query executed successfully but returned no data |
| [ ] | EMPTY | variable | Variable: target | target | $Datasource | `label_values(ping_loss_ratio{job=~"$job",instance=~"$instance"},target)` | query executed successfully but returned no data |
| [ ] | EMPTY | variable | Variable: ip_version | ip_version | $Datasource | `label_values(ping_loss_ratio{job=~"$job",instance=~"$instance"},ip_version)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Ping Success | A | default | `sum(ping_loss_ratio{job=~"$job",instance=~"$instance",target=~"$target",ip_version=~"$ip_version"}) by (instance,target) / count(ping_loss_ratio{job=~"$job",instance=~"$instance",target=~"$target",ip_version=~"$ip_version"}) by (instance,target)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Ping Success | B | default | `sum(label_replace(ping_loss_ratio{job=~"$job",instance=~"$instance",target=~"$target",ip_version=~"$ip_version",ip_version="4"}, "ipv4", "$1", "ip", "(.*)")) by (instance,target,ipv4)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Ping Success | C | default | `sum(label_replace(ping_loss_ratio{job=~"$job",instance=~"$instance",target=~"$target",ip_version=~"$ip_version",ip_version="6"}, "ipv6", "$1", "ip", "(.*)")) by (instance,target,ipv6)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Target $target | A | default | `avg(ping_rtt_best_seconds{job=~"$job",instance=~"$instance",target=~"$target",ip_version=~"$ip_version"}) by (ip_version)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Target $target | B | default | `avg(ping_rtt_mean_seconds{job=~"$job",instance=~"$instance",target=~"$target",ip_version=~"$ip_version"}) by (ip_version)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Target $target | C | default | `avg(ping_rtt_worst_seconds{job=~"$job",instance=~"$instance",target=~"$target",ip_version=~"$ip_version"}) by (ip_version)` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Target $target | D | default | `avg(ping_loss_ratio{job=~"$job",instance=~"$instance",target=~"$target",ip_version=~"$ip_version"}) by (ip_version)` | query executed successfully but returned no data |

### Pod Cleanup Job (`pod-cleanup-dashboard`)

Folder: Cluster · Panels: 21 · Queries: 35

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | panel | Last Run Status | A | mimir | `last_over_time(pod_cleanup_job_success{job="pod_cleanup"}[3h])` | query executed and returned data |
| [x] | PASS | panel | Mode | A | mimir | `last_over_time(pod_cleanup_dry_run{job="pod_cleanup"}[3h])` | query executed and returned data |
| [x] | PASS | panel | Last Run | A | mimir | `timestamp(last_over_time(pod_cleanup_job_success{job="pod_cleanup"}[3h])) * 1000` | query executed and returned data |
| [x] | PASS | panel | Duration | A | mimir | `last_over_time(pod_cleanup_duration_seconds{job="pod_cleanup"}[3h])` | query executed and returned data |
| [x] | PASS | panel | Total Resources Cleaned | A | mimir | `last_over_time(pod_cleanup_resources_total{job="pod_cleanup"}[3h])` | query executed and returned data |
| [x] | PASS | panel | Resources by Category (Last Run) | A | mimir | `last_over_time(pod_cleanup_succeeded_pods{job="pod_cleanup"}[2h])` | query executed and returned data |
| [x] | PASS | panel | Resources by Category (Last Run) | B | mimir | `last_over_time(pod_cleanup_failed_pods{job="pod_cleanup"}[2h])` | query executed and returned data |
| [x] | PASS | panel | Resources by Category (Last Run) | C | mimir | `last_over_time(pod_cleanup_evicted_pods{job="pod_cleanup"}[2h])` | query executed and returned data |
| [x] | PASS | panel | Resources by Category (Last Run) | D | mimir | `last_over_time(pod_cleanup_imagepull_pods{job="pod_cleanup"}[2h])` | query executed and returned data |
| [x] | PASS | panel | Resources by Category (Last Run) | E | mimir | `last_over_time(pod_cleanup_crashloop_pods{job="pod_cleanup"}[2h])` | query executed and returned data |
| [x] | PASS | panel | Resources by Category (Last Run) | F | mimir | `last_over_time(pod_cleanup_completed_jobs{job="pod_cleanup"}[2h])` | query executed and returned data |
| [x] | PASS | panel | Resources by Category (Last Run) | G | mimir | `last_over_time(pod_cleanup_orphan_replicasets{job="pod_cleanup"}[2h])` | query executed and returned data |
| [x] | PASS | panel | Category Breakdown (Last Run) | A | mimir | `last_over_time(pod_cleanup_succeeded_pods{job="pod_cleanup"}[2h])` | query executed and returned data |
| [x] | PASS | panel | Category Breakdown (Last Run) | B | mimir | `last_over_time(pod_cleanup_failed_pods{job="pod_cleanup"}[2h])` | query executed and returned data |
| [x] | PASS | panel | Category Breakdown (Last Run) | C | mimir | `last_over_time(pod_cleanup_evicted_pods{job="pod_cleanup"}[2h])` | query executed and returned data |
| [x] | PASS | panel | Category Breakdown (Last Run) | D | mimir | `last_over_time(pod_cleanup_imagepull_pods{job="pod_cleanup"}[2h])` | query executed and returned data |
| [x] | PASS | panel | Category Breakdown (Last Run) | E | mimir | `last_over_time(pod_cleanup_crashloop_pods{job="pod_cleanup"}[2h])` | query executed and returned data |
| [x] | PASS | panel | Category Breakdown (Last Run) | F | mimir | `last_over_time(pod_cleanup_completed_jobs{job="pod_cleanup"}[2h])` | query executed and returned data |
| [x] | PASS | panel | Category Breakdown (Last Run) | G | mimir | `last_over_time(pod_cleanup_orphan_replicasets{job="pod_cleanup"}[2h])` | query executed and returned data |
| [ ] | EMPTY | panel | Resources Cleaned Over Time (Stacked) | A | mimir | `pod_cleanup_succeeded_pods{job="pod_cleanup"}` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Resources Cleaned Over Time (Stacked) | B | mimir | `pod_cleanup_failed_pods{job="pod_cleanup"}` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Resources Cleaned Over Time (Stacked) | C | mimir | `pod_cleanup_evicted_pods{job="pod_cleanup"}` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Resources Cleaned Over Time (Stacked) | D | mimir | `pod_cleanup_imagepull_pods{job="pod_cleanup"}` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Resources Cleaned Over Time (Stacked) | E | mimir | `pod_cleanup_crashloop_pods{job="pod_cleanup"}` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Resources Cleaned Over Time (Stacked) | F | mimir | `pod_cleanup_completed_jobs{job="pod_cleanup"}` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Resources Cleaned Over Time (Stacked) | G | mimir | `pod_cleanup_orphan_replicasets{job="pod_cleanup"}` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Job Duration Over Time | A | mimir | `pod_cleanup_duration_seconds{job="pod_cleanup"}` | query executed successfully but returned no data |
| [x] | PASS | panel | Job Success History | A | mimir | `last_over_time(pod_cleanup_job_success{job="pod_cleanup"}[2h])` | query executed and returned data |
| [x] | PASS | panel | Identity Cleanup Status | A | mimir | `last_over_time(pod_cleanup_cilium_identity_status{job="pod_cleanup"}[3h])` | query executed and returned data |
| [x] | PASS | panel | Total CiliumIdentities | A | mimir | `last_over_time(pod_cleanup_cilium_identities_total{job="pod_cleanup"}[3h])` | query executed and returned data |
| [x] | PASS | panel | Deleted Last Run | A | mimir | `last_over_time(pod_cleanup_cilium_identities_deleted{job="pod_cleanup"}[3h])` | query executed and returned data |
| [ ] | EMPTY | panel | Cilium Identity Trend | A | mimir | `pod_cleanup_cilium_identities_total{job="pod_cleanup"}` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Cilium Identity Trend | B | mimir | `pod_cleanup_cilium_identities_deleted{job="pod_cleanup"}` | query executed successfully but returned no data |
| [x] | PASS | panel | Deleted Identities (per-run detail) | A | loki-v2 | `{app_kubernetes_io_name="pod-cleanup", namespace="kube-system"} \| json \| event="cilium_id_delete"` | query executed and returned data |
| [x] | PASS | panel | Deleted Resources (Pods / Jobs / ReplicaSets) | A | loki-v2 | `{app_kubernetes_io_name="pod-cleanup", namespace="kube-system"} \| json \| event="resource_delete"` | query executed and returned data |

### RabbitMQ Messaging (`rabbitmq-messaging`)

Folder: Databases · Panels: 21 · Queries: 34

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: namespace | namespace | mimir | `label_values(rabbitmq_build_info, namespace)` | query executed and returned data |
| [x] | PASS | variable | Variable: pod | pod | mimir | `label_values(rabbitmq_build_info{namespace=~"$namespace"}, pod)` | query executed and returned data |
| [x] | PASS | panel | Nodes up | A | mimir | `count(count by (namespace, pod) (rabbitmq_build_info{namespace=~"$namespace", pod=~"$pod"}))` | query executed and returned data |
| [x] | PASS | panel | Ready messages | A | mimir | `sum(max by (namespace, pod) (rabbitmq_queue_messages_ready{namespace=~"$namespace", pod=~"$pod"}))` | query executed and returned data |
| [x] | PASS | panel | Unacked messages | A | mimir | `sum(max by (namespace, pod) (rabbitmq_queue_messages_unacked{namespace=~"$namespace", pod=~"$pod"}))` | query executed and returned data |
| [x] | PASS | panel | Queues | A | mimir | `sum(max by (namespace, pod) (rabbitmq_queues{namespace=~"$namespace", pod=~"$pod"}))` | query executed and returned data |
| [x] | PASS | panel | Consumers | A | mimir | `sum(max by (namespace, pod) (rabbitmq_consumers{namespace=~"$namespace", pod=~"$pod"}))` | query executed and returned data |
| [x] | PASS | panel | Connections | A | mimir | `sum(max by (namespace, pod) (rabbitmq_connections{namespace=~"$namespace", pod=~"$pod"}))` | query executed and returned data |
| [x] | PASS | panel | Nodes | Info | mimir | `max by (namespace, pod, rabbitmq_version, erlang_version) (rabbitmq_build_info{namespace=~"$namespace", pod=~"$pod"})` | query executed and returned data |
| [x] | PASS | panel | Nodes | Mem | mimir | `max by (namespace, pod) (rabbitmq_process_resident_memory_bytes{namespace=~"$namespace", pod=~"$pod"})` | query executed and returned data |
| [x] | PASS | panel | Nodes | Fd | mimir | `max by (namespace, pod) (rabbitmq_process_open_fds{namespace=~"$namespace", pod=~"$pod"})` | query executed and returned data |
| [x] | PASS | panel | Nodes | FdMax | mimir | `max by (namespace, pod) (rabbitmq_process_max_fds{namespace=~"$namespace", pod=~"$pod"})` | query executed and returned data |
| [x] | PASS | panel | Nodes | Disk | mimir | `max by (namespace, pod) (rabbitmq_disk_space_available_bytes{namespace=~"$namespace", pod=~"$pod"})` | query executed and returned data |
| [x] | PASS | panel | Queue depth — ready vs unacked | A | mimir | `max by (namespace, pod) (rabbitmq_queue_messages_ready{namespace=~"$namespace", pod=~"$pod"})` | query executed and returned data |
| [x] | PASS | panel | Queue depth — ready vs unacked | B | mimir | `max by (namespace, pod) (rabbitmq_queue_messages_unacked{namespace=~"$namespace", pod=~"$pod"})` | query executed and returned data |
| [x] | PASS | panel | Total messages & queues | A | mimir | `sum(max by (namespace, pod) (rabbitmq_queue_messages{namespace=~"$namespace", pod=~"$pod"}))` | query executed and returned data |
| [x] | PASS | panel | Total messages & queues | B | mimir | `sum(max by (namespace, pod) (rabbitmq_queues{namespace=~"$namespace", pod=~"$pod"}))` | query executed and returned data |
| [x] | PASS | panel | Message rates — publish / deliver / ack [5m] | A | mimir | `max by (namespace, pod) (rate(rabbitmq_global_messages_received_total{namespace=~"$namespace", pod=~"$pod"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Message rates — publish / deliver / ack [5m] | B | mimir | `max by (namespace, pod) (rate(rabbitmq_global_messages_delivered_total{namespace=~"$namespace", pod=~"$pod"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Message rates — publish / deliver / ack [5m] | C | mimir | `max by (namespace, pod) (rate(rabbitmq_global_messages_acknowledged_total{namespace=~"$namespace", pod=~"$pod"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Redelivered & unroutable [5m] | A | mimir | `max by (namespace, pod) (rate(rabbitmq_global_messages_redelivered_total{namespace=~"$namespace", pod=~"$pod"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Redelivered & unroutable [5m] | B | mimir | `max by (namespace, pod) (rate(rabbitmq_global_messages_unroutable_dropped_total{namespace=~"$namespace", pod=~"$pod"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Connections & channels | A | mimir | `max by (namespace, pod) (rabbitmq_connections{namespace=~"$namespace", pod=~"$pod"})` | query executed and returned data |
| [x] | PASS | panel | Connections & channels | B | mimir | `max by (namespace, pod) (rabbitmq_channels{namespace=~"$namespace", pod=~"$pod"})` | query executed and returned data |
| [x] | PASS | panel | Consumers | A | mimir | `max by (namespace, pod) (rabbitmq_consumers{namespace=~"$namespace", pod=~"$pod"})` | query executed and returned data |
| [x] | PASS | panel | Resident memory vs high watermark | A | mimir | `max by (namespace, pod) (rabbitmq_process_resident_memory_bytes{namespace=~"$namespace", pod=~"$pod"})` | query executed and returned data |
| [x] | PASS | panel | Resident memory vs high watermark | B | mimir | `max by (namespace, pod) (rabbitmq_resident_memory_limit_bytes{namespace=~"$namespace", pod=~"$pod"})` | query executed and returned data |
| [x] | PASS | panel | Disk space available vs limit | A | mimir | `max by (namespace, pod) (rabbitmq_disk_space_available_bytes{namespace=~"$namespace", pod=~"$pod"})` | query executed and returned data |
| [x] | PASS | panel | Disk space available vs limit | B | mimir | `max by (namespace, pod) (rabbitmq_disk_space_available_limit_bytes{namespace=~"$namespace", pod=~"$pod"})` | query executed and returned data |
| [x] | PASS | panel | File descriptors — open vs max | A | mimir | `max by (namespace, pod) (rabbitmq_process_open_fds{namespace=~"$namespace", pod=~"$pod"})` | query executed and returned data |
| [x] | PASS | panel | File descriptors — open vs max | B | mimir | `max by (namespace, pod) (rabbitmq_process_max_fds{namespace=~"$namespace", pod=~"$pod"})` | query executed and returned data |
| [x] | PASS | panel | Active resource alarms (0 = OK) | A | mimir | `sum(rabbitmq_alarms_memory_used_watermark{namespace=~"$namespace", pod=~"$pod"})` | query executed and returned data |
| [x] | PASS | panel | Active resource alarms (0 = OK) | B | mimir | `sum(rabbitmq_alarms_free_disk_space_watermark{namespace=~"$namespace", pod=~"$pod"})` | query executed and returned data |
| [x] | PASS | panel | Active resource alarms (0 = OK) | C | mimir | `sum(rabbitmq_alarms_file_descriptor_limit{namespace=~"$namespace", pod=~"$pod"})` | query executed and returned data |

### Resource Efficiency (`resource-efficiency`)

Folder: Cluster · Panels: 18 · Queries: 18

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: namespace | namespace | mimir | `label_values(kube_pod_info, namespace)` | query executed and returned data |
| [x] | PASS | panel | Cluster CPU Efficiency | A | mimir | `sum(rate(container_cpu_usage_seconds_total{container!="", container!="POD"}[5m])) / sum(kube_pod_container_resource_requests{resource="cpu"}) * 100` | query executed and returned data |
| [x] | PASS | panel | Cluster Memory Efficiency | A | mimir | `sum(container_memory_working_set_bytes{container!="", container!="POD"}) / sum(kube_pod_container_resource_requests{resource="memory"}) * 100` | query executed and returned data |
| [x] | PASS | panel | Over-Provisioned Pods | A | mimir | `count(((sum(rate(container_cpu_usage_seconds_total{container!="", container!="POD"}[5m])) by (namespace, pod) / sum(kube_pod_container_resource_requests{resource="cpu"}) by (namespace, pod)) < 0.2) and (sum(kube_pod_container_resource_requests{resource="cpu"}) by (namespace, pod) > $min_cpu))` | query executed and returned data |
| [x] | PASS | panel | Under-Provisioned Pods | A | mimir | `count((sum(rate(container_cpu_usage_seconds_total{container!="", container!="POD"}[5m])) by (namespace, pod) / sum(kube_pod_container_resource_requests{resource="cpu"}) by (namespace, pod)) > 0.9)` | query executed and returned data |
| [x] | PASS | panel | OOM Risk Pods | A | mimir | `count((sum(container_memory_working_set_bytes{container!="", container!="POD"}) by (namespace, pod) / sum(kube_pod_container_resource_limits{resource="memory"}) by (namespace, pod)) > 0.8)` | query executed and returned data |
| [x] | PASS | panel | CPU Efficiency by Namespace | A | mimir | `sum(rate(container_cpu_usage_seconds_total{container!="", container!="POD"}[5m])) by (namespace) / sum(kube_pod_container_resource_requests{resource="cpu"}) by (namespace) * 100` | query executed and returned data |
| [x] | PASS | panel | Cluster CPU Efficiency Over Time | A | mimir | `sum(rate(container_cpu_usage_seconds_total{container!="", container!="POD"}[5m])) / sum(kube_pod_container_resource_requests{resource="cpu"}) * 100` | query executed and returned data |
| [x] | PASS | panel | Memory Efficiency by Namespace (vs Requests) | A | mimir | `sum(container_memory_working_set_bytes{container!="", container!="POD"}) by (namespace) / sum(kube_pod_container_resource_requests{resource="memory"}) by (namespace) * 100` | query executed and returned data |
| [x] | PASS | panel | Memory Usage vs Limits by Namespace | A | mimir | `sum(container_memory_working_set_bytes{container!="", container!="POD"}) by (namespace) / sum(kube_pod_container_resource_limits{resource="memory"}) by (namespace) * 100` | query executed and returned data |
| [x] | PASS | panel | CPU Efficiency by Pod (Lowest First) | A | mimir | `sort_desc(sum(rate(container_cpu_usage_seconds_total{container!="", container!="POD"}[5m])) by (namespace, pod) / sum(kube_pod_container_resource_requests{resource="cpu"}) by (namespace, pod) * 100)` | query executed and returned data |
| [x] | PASS | panel | Memory Usage vs Limit by Pod (Highest First) | A | mimir | `sort_desc(sum(container_memory_working_set_bytes{container!="", container!="POD"}) by (namespace, pod) / sum(kube_pod_container_resource_limits{resource="memory"}) by (namespace, pod) * 100)` | query executed and returned data |
| [x] | PASS | panel | Resource Right-Sizing Recommendations | A | mimir | `quantile_over_time(0.95, sum(rate(container_cpu_usage_seconds_total{container!="", container!="POD"}[5m])) by (namespace, container)[24h:5m]) * 1.2` | query executed and returned data |
| [x] | PASS | panel | Resource Right-Sizing Recommendations | B | mimir | `sum(kube_pod_container_resource_requests{resource="cpu", container!=""}) by (namespace, container)` | query executed and returned data |
| [x] | PASS | panel | Resource Right-Sizing Recommendations | C | mimir | `(quantile_over_time(0.95, sum(rate(container_cpu_usage_seconds_total{container!="", container!="POD"}[5m])) by (namespace, container)[24h:5m]) * 1.2) / sum(kube_pod_container_resource_requests{resource="cpu", container!=""}) by (namespace, container) * 100` | query executed and returned data |
| [x] | PASS | panel | Resource Right-Sizing Recommendations | D | mimir | `quantile_over_time(0.95, sum(container_memory_working_set_bytes{container!="", container!="POD"}) by (namespace, container)[24h:5m]) * 1.2` | query executed and returned data |
| [x] | PASS | panel | Resource Right-Sizing Recommendations | E | mimir | `sum(kube_pod_container_resource_requests{resource="memory", container!=""}) by (namespace, container)` | query executed and returned data |
| [x] | PASS | panel | Resource Right-Sizing Recommendations | F | mimir | `(quantile_over_time(0.95, sum(container_memory_working_set_bytes{container!="", container!="POD"}) by (namespace, container)[24h:5m]) * 1.2) / sum(kube_pod_container_resource_requests{resource="memory", container!=""}) by (namespace, container) * 100` | query executed and returned data |

### Security Ops — CrowdSec (`crowdsec-ops`)

Folder: Security · Panels: 41 · Queries: 40

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: origin | origin | mimir | `label_values(cs_active_decisions, origin)` | query executed and returned data |
| [ ] | EMPTY | variable | Variable: scenario | scenario | mimir | `label_values(cs_bucket_overflowed_total, name)` | query executed successfully but returned no data |
| [x] | PASS | variable | Variable: bouncer | bouncer | mimir | `label_values(cs_lapi_bouncer_requests_total, bouncer)` | query executed and returned data |
| [x] | PASS | panel | Active Decisions (bans) |  | mimir | `sum(cs_active_decisions{origin=~"$origin"})` | query executed and returned data |
| [ ] | EMPTY | panel | Decisions Added (24h, local) |  | mimir | `sum(increase(cs_bucket_overflowed_total{name=~"$scenario"}[24h]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Alerts (24h) |  | mimir | `sum(increase(cs_bucket_overflowed_total[24h]))` | query executed successfully but returned no data |
| [x] | PASS | panel | LAPI / Engine Up |  | mimir | `max(up{namespace="crowdsec",pod=~"crowdsec-lapi.*"})` | query executed and returned data |
| [x] | PASS | panel | Agents Reporting |  | mimir | `count(cs_info{namespace="crowdsec",pod=~"crowdsec-agent.*"})` | query executed and returned data |
| [x] | PASS | panel | AppSec Engines Up |  | mimir | `max(up{namespace="crowdsec",pod=~"crowdsec-appsec.*"})` | query executed and returned data |
| [ ] | EMPTY | panel | Bans / Decisions Added Over Time (overflows/s) |  | mimir | `sum(rate(cs_bucket_overflowed_total[$__rate_interval]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Bans / Decisions Added Over Time (overflows/s) |  | mimir | `sum by (name) (rate(cs_bucket_overflowed_total[$__rate_interval]))` | query executed successfully but returned no data |
| [x] | PASS | panel | Active Decisions by Origin |  | mimir | `sum by (origin) (cs_active_decisions{origin=~"$origin"})` | query executed and returned data |
| [x] | PASS | panel | Active Decisions by Scenario |  | mimir | `topk(12, sum by (reason) (cs_active_decisions{origin=~"$origin"}))` | query executed and returned data |
| [x] | PASS | panel | Active Decisions by Origin (share) |  | mimir | `sum by (origin) (cs_active_decisions)` | query executed and returned data |
| [x] | PASS | panel | Decisions by Action |  | mimir | `sum by (action) (cs_active_decisions{origin=~"$origin"})` | query executed and returned data |
| [x] | PASS | panel | Top Scenarios (active decisions) |  | mimir | `topk(20, sum by (reason) (cs_active_decisions{origin=~"$origin"}))` | query executed and returned data |
| [ ] | EMPTY | panel | Top Bucket Overflows (24h) |  | mimir | `topk(20, sum by (name) (increase(cs_bucket_overflowed_total{name=~"$scenario"}[24h])))` | query executed successfully but returned no data |
| [x] | PASS | panel | Lines Parsed/s (by acquisition source) |  | mimir | `sum(rate(cs_parser_hits_total[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Lines Parsed/s (by acquisition source) |  | mimir | `sum by (source) (rate(cs_parser_hits_total[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Parse Failures/s (unmatched) |  | mimir | `sum by (source) (rate(cs_parser_hits_ko_total[$__rate_interval]))` | query executed and returned data |
| [ ] | EMPTY | panel | Buckets Overflowing (by scenario) |  | mimir | `sum by (name) (rate(cs_bucket_overflowed_total{name=~"$scenario"}[$__rate_interval]))` | query executed successfully but returned no data |
| [x] | PASS | panel | Events Poured to Buckets/s (by source) |  | mimir | `topk(15, sum by (source) (rate(cs_bucket_poured_total[$__rate_interval])))` | query executed and returned data |
| [x] | PASS | panel | AppSec Requests Inspected/s |  | mimir | `sum(rate(cs_appsec_reqs_total[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | AppSec Requests by Engine |  | mimir | `topk(10, sum by (appsec_engine) (rate(cs_appsec_reqs_total[$__rate_interval])))` | query executed and returned data |
| [x] | PASS | panel | LAPI Requests from Bouncer/s |  | mimir | `sum by (bouncer) (rate(cs_lapi_bouncer_requests_total{bouncer=~"$bouncer"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | LAPI Requests/s by route |  | mimir | `sum by (route) (rate(cs_lapi_route_requests_total{pod=~"crowdsec-lapi.*"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Active Decisions Served |  | mimir | `sum(cs_active_decisions)` | query executed and returned data |
| [x] | PASS | panel | LAPI Requests/s (total) |  | mimir | `sum(rate(cs_lapi_route_requests_total{pod=~"crowdsec-lapi.*"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Components Up |  | mimir | `count(cs_info{namespace="crowdsec"})` | query executed and returned data |
| [x] | PASS | panel | Engine Version |  | mimir | `cs_info{namespace="crowdsec",pod=~"crowdsec-lapi.*"}` | query executed and returned data |
| [x] | PASS | panel | Scrape Duration |  | mimir | `max(scrape_duration_seconds{namespace="crowdsec"})` | query executed and returned data |
| [x] | PASS | panel | Series Scraped |  | mimir | `max(scrape_samples_scraped{namespace="crowdsec"})` | query executed and returned data |
| [x] | PASS | panel | Scrape Duration Over Time |  | mimir | `scrape_duration_seconds{namespace="crowdsec"}` | query executed and returned data |
| [x] | PASS | panel | Whitelist Hits/s (by source) |  | mimir | `sum(rate(cs_node_wl_hits_ok_total[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Whitelist Hits/s (by source) |  | mimir | `sum by (source) (rate(cs_node_wl_hits_ok_total[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | Avg Parse Time/event |  | mimir | `sum(rate(cs_parsing_time_seconds_sum[$__rate_interval])) / sum(rate(cs_parsing_time_seconds_count[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | LAPI Requests/s (by route) |  | mimir | `sum(rate(cs_lapi_route_requests_total{pod=~"crowdsec-lapi.*"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | LAPI Requests/s (by route) |  | mimir | `sum by (route) (rate(cs_lapi_route_requests_total{pod=~"crowdsec-lapi.*"}[$__rate_interval]))` | query executed and returned data |
| [x] | PASS | panel | LAPI Request Latency (p95 / p50) |  | mimir | `histogram_quantile(0.95, sum by (le) (rate(cs_lapi_request_duration_seconds_bucket{pod=~"crowdsec-lapi.*"}[$__rate_interval])))` | query executed and returned data |
| [x] | PASS | panel | LAPI Request Latency (p95 / p50) |  | mimir | `histogram_quantile(0.50, sum by (le) (rate(cs_lapi_request_duration_seconds_bucket{pod=~"crowdsec-lapi.*"}[$__rate_interval])))` | query executed and returned data |

### SPIRE Health & Mesh-Auth Correlation (`spire-health`)

Folder: Cluster · Panels: 13 · Queries: 9

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | panel | SPIRE Server Ready |  | mimir | `kube_statefulset_status_replicas_ready{statefulset="spire-server",namespace="cilium-spire"}` | query executed and returned data |
| [x] | PASS | panel | SPIRE Agents Ready (per node) |  | mimir | `kube_daemonset_status_number_ready{daemonset="spire-agent",namespace="cilium-spire"}` | query executed and returned data |
| [x] | PASS | panel | SPIRE Agent Coverage Gap |  | mimir | `kube_daemonset_status_desired_number_scheduled{daemonset="spire-agent",namespace="cilium-spire"} - kube_daemonset_status_number_ready{daemonset="spire-agent",namespace="cilium-spire"}` | query executed and returned data |
| [ ] | EMPTY | panel | Cilium SPIRE Warnings (1h) |  | loki-v2 | `sum(count_over_time({namespace="kube-system",app="cilium"} \|~ "SPIRE.*failed to init" [1h]))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Cilium SPIRE Init-Watcher Warning Rate (per pod) |  | loki-v2 | `sum by (pod) (rate({namespace="kube-system",app="cilium"} \|~ "SPIRE.*failed to init" [5m]))` | query executed successfully but returned no data |
| [x] | PASS | panel | Cilium mesh-auth Metric Rates |  | mimir | `max(cilium_feature_network_policies_mutual_auth_enabled)` | query executed and returned data |
| [x] | PASS | panel | Cilium Agent Restart Rate (overlay with SPIRE warnings) |  | mimir | `rate(kube_pod_container_status_restarts_total{namespace="kube-system",container="cilium-agent"}[5m]) * 60` | query executed and returned data |
| [ ] | EMPTY | panel | Cilium Agent SPIRE/Auth Logs |  | loki-v2 | `{namespace="kube-system",app="cilium"} \|~ "(?i)(spire\|mesh-auth\|mutual.*auth)"` | query executed successfully but returned no data |
| [x] | PASS | panel | SPIRE Namespace Logs (server + agents) |  | loki-v2 | `{namespace="cilium-spire"}` | query executed and returned data |

### Talos Cluster Debug (`talos-cluster-debug`)

Folder: Cluster · Panels: 19 · Queries: 16

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: node | node | mimir | `label_values(node_uname_info, nodename)` | query executed and returned data |
| [x] | PASS | panel | Nodes Ready |  | mimir | `sum(kube_node_status_condition{condition="Ready",status="true"})` | query executed and returned data |
| [x] | PASS | panel | Cilium Agents Ready |  | mimir | `kube_daemonset_status_number_ready{daemonset="cilium",namespace="kube-system"}` | query executed and returned data |
| [x] | PASS | panel | Cilium Agent Restarts (24h) |  | mimir | `sum(increase(kube_pod_container_status_restarts_total{namespace="kube-system",container="cilium-agent"}[24h]))` | query executed and returned data |
| [ ] | EMPTY | panel | Kernel Panic Events (24h) |  | loki-v2 | `sum(count_over_time({job="kernel-capture"} \|~ "(?i)(Kernel panic - not syncing\|Oops:\|general protection fault\|soft lockup\|BUG: unable to handle)" [24h]))` | query executed successfully but returned no data |
| [x] | PASS | panel | Cilium Agent Restart Rate (per pod, restarts/min) |  | mimir | `rate(kube_pod_container_status_restarts_total{namespace="kube-system",container="cilium-agent"}[5m]) * 60` | query executed and returned data |
| [x] | PASS | panel | Per-Node Health (uptime, cilium restarts, load, memory) | A | mimir | `time() - node_boot_time_seconds` | query executed and returned data |
| [x] | PASS | panel | Per-Node Health (uptime, cilium restarts, load, memory) | B | mimir | `sum by (node) (kube_pod_container_status_restarts_total{namespace="kube-system",container="cilium-agent"})` | query executed and returned data |
| [x] | PASS | panel | Per-Node Health (uptime, cilium restarts, load, memory) | C | mimir | `node_load1` | query executed and returned data |
| [x] | PASS | panel | Per-Node Health (uptime, cilium restarts, load, memory) | D | mimir | `(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100` | query executed and returned data |
| [x] | PASS | panel | Cilium Agent Memory (per pod) vs 2Gi limit |  | mimir | `container_memory_working_set_bytes{namespace="kube-system",container="cilium-agent"}` | query executed and returned data |
| [x] | PASS | panel | Cilium Agent Memory (per pod) vs 2Gi limit |  | mimir | `kube_pod_container_resource_limits{namespace="kube-system",container="cilium-agent",resource="memory"}` | query executed and returned data |
| [x] | PASS | panel | Cilium Agent Cumulative Restart Count |  | mimir | `kube_pod_container_status_restarts_total{namespace="kube-system",container="cilium-agent"}` | query executed and returned data |
| [x] | PASS | panel | Top 15 Operator Pods by Restart Count | A | mimir | `topk(15, sum by (namespace, pod, container) (kube_pod_container_status_restarts_total{namespace=~"databases\|kubevirt\|monitoring\|kube-system\|cert-manager\|external-secrets\|flux-system\|argocd",container!=""}))` | query executed and returned data |
| [ ] | EMPTY | panel | Recent Kernel Panic / BUG / Oops Events (all nodes) | A | loki-v2 | `{job="kernel-capture"} \|~ "(?i)(Kernel panic - not syncing\|Oops:\|general protection fault\|soft lockup\|BUG: unable to handle)"` | query executed successfully but returned no data |
| [x] | PASS | panel | Live Kernel Stream — ${node} | A | loki-v2 | `{job="kernel-capture", filename=~".*${node}.*"}` | query executed and returned data |

### Talos00 Memory Deep-Dive (`talos00-memory-deepdive`)

Folder: Cluster · Panels: 16 · Queries: 11

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | panel | OOM Kills (24h) |  | mimir | `sum(increase(container_oom_events_total[24h]))` | query executed and returned data |
| [x] | PASS | panel | Nodes in MemoryPressure |  | mimir | `sum(kube_node_status_condition{condition="MemoryPressure",status="true"})` | query executed and returned data |
| [x] | PASS | panel | cilium-agent on talos00 vs 2Gi limit |  | mimir | `100 * container_memory_working_set_bytes{container="cilium-agent",node=~"talos00.*"} / on(namespace,pod) kube_pod_container_resource_limits{container="cilium-agent",resource="memory",node=~"talos00.*"}` | query executed and returned data |
| [x] | PASS | panel | talos00 host memory % |  | mimir | `100 * (1 - (node_memory_MemAvailable_bytes{instance=~"talos00.*",job="kubernetes-service-endpoints"} / node_memory_MemTotal_bytes{instance=~"talos00.*",job="kubernetes-service-endpoints"}))` | query executed and returned data |
| [x] | PASS | panel | cilium-agent working_set + memory.limit per node |  | mimir | `container_memory_working_set_bytes{container="cilium-agent"}` | query executed and returned data |
| [x] | PASS | panel | cilium-agent working_set + memory.limit per node |  | mimir | `kube_pod_container_resource_limits{container="cilium-agent",resource="memory"}` | query executed and returned data |
| [ ] | EMPTY | panel | Go GC pause (p99) per cilium-agent — high = GOMEMLIMIT pressure |  | mimir | `max by (pod) (go_gc_duration_seconds{quantile="1",namespace="kube-system",pod=~"cilium-.*",job="kubernetes-pods"})` | query executed successfully but returned no data |
| [x] | PASS | panel | Host memory % per node |  | mimir | `100 * (1 - (node_memory_MemAvailable_bytes{job="kubernetes-service-endpoints"} / node_memory_MemTotal_bytes{job="kubernetes-service-endpoints"}))` | query executed and returned data |
| [x] | PASS | panel | PSI memory pressure (some) per node |  | mimir | `rate(node_pressure_memory_waiting_seconds_total[5m])` | query executed and returned data |
| [x] | PASS | panel | talos00 — top 10 pods by working_set_bytes |  | mimir | `topk(10, sum by (pod, namespace) (container_memory_working_set_bytes{node=~"talos00.*",container!="",container!="POD"}))` | query executed and returned data |
| [x] | PASS | panel | Per-pod memory heatmap (by node) |  | mimir | `sum by (node, pod) (container_memory_working_set_bytes{container!="",container!="POD"})` | query executed and returned data |

### Tdarr Transcoding (`tdarr-transcoding`)

Folder: Media · Panels: 22 · Queries: 30

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | panel | Overall Progress | A | mimir | `(max(tdarr_queue_transcode_success) + max(tdarr_queue_transcode_error)) / clamp_min(max(tdarr_total_files), 1) * 100` | query executed and returned data |
| [x] | PASS | panel | Health Score | A | mimir | `max(tdarr_health_check_score)` | query executed and returned data |
| [x] | PASS | panel | Total Files | A | mimir | `max(tdarr_total_files)` | query executed and returned data |
| [x] | PASS | panel | Transcoded | A | mimir | `max(tdarr_queue_transcode_success)` | query executed and returned data |
| [x] | PASS | panel | Remaining | A | mimir | `max(tdarr_total_files) - max(tdarr_queue_transcode_success) - max(tdarr_queue_transcode_error)` | query executed and returned data |
| [x] | PASS | panel | Errors | A | mimir | `max(tdarr_queue_transcode_error)` | query executed and returned data |
| [x] | PASS | panel | Space Saved | A | mimir | `max(tdarr_size_diff_gb)` | query executed and returned data |
| [x] | PASS | panel | ETA to Complete | A | mimir | `(max(tdarr_total_files) - max(tdarr_queue_transcode_success) - max(tdarr_queue_transcode_error)) / clamp_min(max(delta(tdarr_queue_transcode_success[1h])), 0.1)` | query executed and returned data |
| [x] | PASS | panel | Transcodes/Hour | A | mimir | `clamp_min(delta(tdarr_queue_transcode_success[1h]), 0)` | query executed and returned data |
| [x] | PASS | panel | Worker Status | A | mimir | `tdarr_node_paused` | query executed and returned data |
| [x] | PASS | panel | Worker Status | B | mimir | `tdarr_node_gpu_workers` | query executed and returned data |
| [x] | PASS | panel | Active Workers | A | mimir | `count(tdarr_node_paused == 0)` | query executed and returned data |
| [x] | PASS | panel | In Progress | A | mimir | `max(tdarr_queue_staged)` | query executed and returned data |
| [x] | PASS | panel | Queued | A | mimir | `max(tdarr_queue_transcode)` | query executed and returned data |
| [x] | PASS | panel | GPU Workers | A | mimir | `sum(tdarr_node_gpu_workers)` | query executed and returned data |
| [x] | PASS | panel | Transcode Queue | A | mimir | `sum(tdarr_queue_transcode_success)` | query executed and returned data |
| [x] | PASS | panel | Transcode Queue | B | mimir | `sum(tdarr_queue_transcode_error)` | query executed and returned data |
| [x] | PASS | panel | Transcode Queue | C | mimir | `sum(tdarr_queue_staged)` | query executed and returned data |
| [x] | PASS | panel | Transcode Queue | D | mimir | `sum(tdarr_queue_transcode)` | query executed and returned data |
| [x] | PASS | panel | Health Checks | A | mimir | `sum(tdarr_queue_health_check_success)` | query executed and returned data |
| [x] | PASS | panel | Health Checks | B | mimir | `sum(tdarr_queue_health_check_error)` | query executed and returned data |
| [x] | PASS | panel | Health Checks | C | mimir | `sum(tdarr_queue_health_check)` | query executed and returned data |
| [x] | PASS | panel | Processing Rate | A | mimir | `clamp_min(increase(tdarr_queue_transcode_success[5m]), 0)` | query executed and returned data |
| [x] | PASS | panel | Processing Rate | B | mimir | `clamp_min(increase(tdarr_queue_health_check_success[5m]), 0)` | query executed and returned data |
| [x] | PASS | panel | Processing Rate | C | mimir | `clamp_min(increase(tdarr_queue_transcode_error[5m]), 0)` | query executed and returned data |
| [x] | PASS | panel | Space Savings | A | mimir | `max(tdarr_size_diff_gb)` | query executed and returned data |
| [x] | PASS | panel | Space Savings | B | mimir | `clamp_min(deriv(tdarr_size_diff_gb[10m]), 0) * 3600` | query executed and returned data |
| [x] | PASS | panel | Queue Status Over Time | A | mimir | `max(tdarr_queue_transcode_success)` | query executed and returned data |
| [x] | PASS | panel | Queue Status Over Time | B | mimir | `max(tdarr_queue_transcode)` | query executed and returned data |
| [x] | PASS | panel | Queue Status Over Time | C | mimir | `max(tdarr_queue_staged)` | query executed and returned data |

### Traefik Ops (`traefik-ops`)

Folder: Network · Panels: 25 · Queries: 31

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: entrypoint | entrypoint | mimir | `label_values(traefik_entrypoint_requests_total, entrypoint)` | query executed and returned data |
| [x] | PASS | variable | Variable: service | service | mimir | `label_values(traefik_service_requests_total, service)` | query executed and returned data |
| [x] | PASS | variable | Variable: router | router | mimir | `label_values(traefik_router_requests_total, router)` | query executed and returned data |
| [x] | PASS | panel | Total Requests | A | mimir | `sum(rate(traefik_entrypoint_requests_total{entrypoint=~"$entrypoint"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | 5xx Error Ratio | A | mimir | `sum(rate(traefik_entrypoint_requests_total{entrypoint=~"$entrypoint",code=~"5.."}[5m])) / sum(rate(traefik_entrypoint_requests_total{entrypoint=~"$entrypoint"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | 4xx Ratio | A | mimir | `sum(rate(traefik_entrypoint_requests_total{entrypoint=~"$entrypoint",code=~"4.."}[5m])) / sum(rate(traefik_entrypoint_requests_total{entrypoint=~"$entrypoint"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | p99 Latency | A | mimir | `histogram_quantile(0.99, sum by (le) (rate(traefik_entrypoint_request_duration_seconds_bucket{entrypoint=~"$entrypoint"}[5m])))` | query executed and returned data |
| [x] | PASS | panel | Open Connections | A | mimir | `sum(traefik_open_connections{entrypoint!~"metrics\|traefik"})` | query executed and returned data |
| [x] | PASS | panel | Nearest TLS Expiry | A | mimir | `min(traefik_tls_certs_not_after - time())` | query executed and returned data |
| [x] | PASS | panel | Request Rate per Entrypoint | A | mimir | `sum by (entrypoint) (rate(traefik_entrypoint_requests_total{entrypoint=~"$entrypoint"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | p99 Latency per Entrypoint | A | mimir | `histogram_quantile(0.99, sum by (le, entrypoint) (rate(traefik_entrypoint_request_duration_seconds_bucket{entrypoint=~"$entrypoint"}[5m])))` | query executed and returned data |
| [x] | PASS | panel | Open Connections per Entrypoint | A | mimir | `sum by (entrypoint) (traefik_open_connections{entrypoint=~"$entrypoint"})` | query executed and returned data |
| [x] | PASS | panel | Ingress Throughput (in/out) | A | mimir | `sum(rate(traefik_entrypoint_requests_bytes_total{entrypoint=~"$entrypoint"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Ingress Throughput (in/out) | B | mimir | `sum(rate(traefik_entrypoint_responses_bytes_total{entrypoint=~"$entrypoint"}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Top Routers by Request Rate | A | mimir | `topk(10, sum by (router) (rate(traefik_router_requests_total{router=~"$router"}[5m])))` | query executed and returned data |
| [x] | PASS | panel | Top Services by Request Rate | A | mimir | `topk(10, sum by (service) (rate(traefik_service_requests_total{service=~"$service"}[5m])))` | query executed and returned data |
| [x] | PASS | panel | Service Latency (p50 / p90 / p99) | A | mimir | `histogram_quantile(0.50, sum by (le) (rate(traefik_service_request_duration_seconds_bucket{service=~"$service"}[5m])))` | query executed and returned data |
| [x] | PASS | panel | Service Latency (p50 / p90 / p99) | B | mimir | `histogram_quantile(0.90, sum by (le) (rate(traefik_service_request_duration_seconds_bucket{service=~"$service"}[5m])))` | query executed and returned data |
| [x] | PASS | panel | Service Latency (p50 / p90 / p99) | C | mimir | `histogram_quantile(0.99, sum by (le) (rate(traefik_service_request_duration_seconds_bucket{service=~"$service"}[5m])))` | query executed and returned data |
| [x] | PASS | panel | Top Services by 5xx Rate | A | mimir | `topk(10, sum by (service) (rate(traefik_service_requests_total{service=~"$service",code=~"5.."}[5m])))` | query executed and returned data |
| [x] | PASS | panel | Request Rate by Status Class | A | mimir | `sum(rate(traefik_entrypoint_requests_total{entrypoint=~"$entrypoint",code=~"2.."}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Request Rate by Status Class | B | mimir | `sum(rate(traefik_entrypoint_requests_total{entrypoint=~"$entrypoint",code=~"3.."}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Request Rate by Status Class | C | mimir | `sum(rate(traefik_entrypoint_requests_total{entrypoint=~"$entrypoint",code=~"4.."}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Request Rate by Status Class | D | mimir | `sum(rate(traefik_entrypoint_requests_total{entrypoint=~"$entrypoint",code=~"5.."}[5m]))` | query executed and returned data |
| [x] | PASS | panel | 4xx & 5xx Rate | A | mimir | `sum(rate(traefik_entrypoint_requests_total{entrypoint=~"$entrypoint",code=~"4.."}[5m]))` | query executed and returned data |
| [x] | PASS | panel | 4xx & 5xx Rate | B | mimir | `sum(rate(traefik_entrypoint_requests_total{entrypoint=~"$entrypoint",code=~"5.."}[5m]))` | query executed and returned data |
| [x] | PASS | panel | Top Erroring Routers (4xx+5xx) | A | mimir | `topk(15, sum by (router) (rate(traefik_router_requests_total{router=~"$router",code=~"[45].."}[5m])))` | query executed and returned data |
| [x] | PASS | panel | Top Erroring Services (5xx) | A | mimir | `topk(15, sum by (service) (rate(traefik_service_requests_total{service=~"$service",code=~"5.."}[5m])))` | query executed and returned data |
| [x] | PASS | panel | TLS Certificates — Time to Expiry | A | mimir | `min by (cn) (traefik_tls_certs_not_after) - time()` | query executed and returned data |
| [x] | PASS | panel | Config Reloads | A | mimir | `sum(rate(traefik_config_reloads_total[5m]))` | query executed and returned data |
| [x] | PASS | panel | Config Reloads | B | mimir | `time() - max(traefik_config_last_reload_success)` | query executed and returned data |

### Uptime / SLO (`uptime-slo`)

Folder: Observability · Panels: 9 · Queries: 9

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: instance | instance | mimir | `label_values(probe_success, instance)` | query executed and returned data |
| [x] | PASS | panel | Overall Availability |  | mimir | `avg(probe_success{instance=~"$instance"}) * 100` | query executed and returned data |
| [x] | PASS | panel | Targets Up |  | mimir | `count(probe_success{instance=~"$instance"} == 1)` | query executed and returned data |
| [ ] | EMPTY | panel | Targets Down |  | mimir | `count(probe_success{instance=~"$instance"} == 0)` | query executed successfully but returned no data |
| [x] | PASS | panel | Endpoint status | A | mimir | `probe_success{instance=~"$instance"}` | query executed and returned data |
| [x] | PASS | panel | Endpoint status | B | mimir | `probe_http_status_code{instance=~"$instance"}` | query executed and returned data |
| [x] | PASS | panel | Endpoint status | C | mimir | `probe_duration_seconds{instance=~"$instance"}` | query executed and returned data |
| [x] | PASS | panel | Probe Success (up/down) per Endpoint |  | mimir | `probe_success{instance=~"$instance"}` | query executed and returned data |
| [x] | PASS | panel | Probe Duration per Endpoint |  | mimir | `probe_duration_seconds{instance=~"$instance"}` | query executed and returned data |

### VPN Gateway (`vpn-gateway`)

Folder: Network · Panels: 34 · Queries: 45

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: service | service | ${datasource} | `label_values(container_network_receive_bytes_total{namespace=~"vpn-gateway\|media", interface="tun0"}, pod)` | query executed and returned data |
| [ ] | EMPTY | panel | VPN Status |  | ${datasource} | `count(kube_pod_container_status_ready{namespace=~"vpn-gateway\|media", container="gluetun", pod=~"$service.*"} == 1)` | query executed successfully but returned no data |
| [x] | PASS | panel | VPN Containers |  | ${datasource} | `count(kube_pod_container_status_running{namespace=~"vpn-gateway\|media", pod=~"(gluetun\|securexng\|qbittorrent\|secure-chrome).*"})` | query executed and returned data |
| [x] | PASS | panel | Downloaded (Interval) |  | ${datasource} | `sum(increase(container_network_receive_bytes_total{namespace=~"vpn-gateway\|media", interface="tun0", pod=~"(gluetun\|securexng\|qbittorrent\|secure-chrome).*"}[$__range]))` | query executed and returned data |
| [x] | PASS | panel | Uploaded (Interval) |  | ${datasource} | `sum(increase(container_network_transmit_bytes_total{namespace=~"vpn-gateway\|media", interface="tun0", pod=~"(gluetun\|securexng\|qbittorrent\|secure-chrome).*"}[$__range]))` | query executed and returned data |
| [x] | PASS | panel | Restarts (Interval) |  | ${datasource} | `sum(increase(kube_pod_container_status_restarts_total{namespace=~"vpn-gateway\|media", container="gluetun", pod=~"(gluetun\|securexng\|qbittorrent\|secure-chrome).*"}[$__range]))` | query executed and returned data |
| [x] | PASS | panel | VPN Pod Uptime |  | ${datasource} | `min(time() - kube_pod_start_time{namespace=~"vpn-gateway\|media", pod=~"(gluetun\|securexng\|qbittorrent\|secure-chrome).*"})` | query executed and returned data |
| [x] | PASS | panel | Total Downloaded |  | ${datasource} | `sum(container_network_receive_bytes_total{namespace=~"vpn-gateway\|media", interface="tun0", pod=~"(gluetun\|securexng\|qbittorrent\|secure-chrome).*"})` | query executed and returned data |
| [x] | PASS | panel | Total Uploaded |  | ${datasource} | `sum(container_network_transmit_bytes_total{namespace=~"vpn-gateway\|media", interface="tun0", pod=~"(gluetun\|securexng\|qbittorrent\|secure-chrome).*"})` | query executed and returned data |
| [x] | PASS | panel | Total Restarts |  | ${datasource} | `sum(kube_pod_container_status_restarts_total{namespace=~"vpn-gateway\|media", container="gluetun", pod=~"(gluetun\|securexng\|qbittorrent\|secure-chrome).*"})` | query executed and returned data |
| [ ] | EMPTY | panel | VPN Tunnel Bandwidth by Service |  | ${datasource} | `sum by (service) (label_replace(rate(container_network_receive_bytes_total{namespace=~"vpn-gateway\|media", interface="tun0", pod=~"$service.*"}[$smoothing]), "service", "$1", "pod", "^([^-]+-?[^-]*)-[^-]+-[^-]+$"))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | VPN Tunnel Bandwidth by Service |  | ${datasource} | `sum by (service) (label_replace(rate(container_network_transmit_bytes_total{namespace=~"vpn-gateway\|media", interface="tun0", pod=~"$service.*"}[$smoothing]), "service", "$1", "pod", "^([^-]+-?[^-]*)-[^-]+-[^-]+$"))` | query executed successfully but returned no data |
| [x] | PASS | panel | Pod Network (Cluster Traffic) |  | ${datasource} | `sum by (service) (label_replace(rate(container_network_receive_bytes_total{namespace=~"vpn-gateway\|media", interface="eth0", pod=~"(gluetun\|securexng\|qbittorrent\|secure-chrome).*"}[$smoothing]), "service", "$1", "pod", "^([^-]+-?[^-]*)-[^-]+-[^-]+$"))` | query executed and returned data |
| [x] | PASS | panel | Pod Network (Cluster Traffic) |  | ${datasource} | `sum by (service) (label_replace(rate(container_network_transmit_bytes_total{namespace=~"vpn-gateway\|media", interface="eth0", pod=~"(gluetun\|securexng\|qbittorrent\|secure-chrome).*"}[$smoothing]), "service", "$1", "pod", "^([^-]+-?[^-]*)-[^-]+-[^-]+$"))` | query executed and returned data |
| [ ] | EMPTY | panel | VPN Packet Rate |  | ${datasource} | `sum by (service) (label_replace(rate(container_network_receive_packets_total{namespace=~"vpn-gateway\|media", interface="tun0", pod=~"$service.*"}[$smoothing]), "service", "$1", "pod", "^([^-]+-?[^-]*)-[^-]+-[^-]+$"))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | VPN Packet Rate |  | ${datasource} | `sum by (service) (label_replace(rate(container_network_transmit_packets_total{namespace=~"vpn-gateway\|media", interface="tun0", pod=~"$service.*"}[$smoothing]), "service", "$1", "pod", "^([^-]+-?[^-]*)-[^-]+-[^-]+$"))` | query executed successfully but returned no data |
| [x] | PASS | panel | CPU Usage (millicores) |  | ${datasource} | `sum by (service, container) (label_replace(rate(container_cpu_usage_seconds_total{namespace=~"vpn-gateway\|media", pod=~"(gluetun\|securexng\|qbittorrent\|secure-chrome).*", container!=""}[$smoothing]) * 1000, "service", "$1", "pod", "^([^-]+-?[^-]*)-[^-]+-[^-]+$"))` | query executed and returned data |
| [x] | PASS | panel | Memory Usage |  | ${datasource} | `sum by (service, container) (label_replace(container_memory_working_set_bytes{namespace=~"vpn-gateway\|media", pod=~"(gluetun\|securexng\|qbittorrent\|secure-chrome).*", container!=""}, "service", "$1", "pod", "^([^-]+-?[^-]*)-[^-]+-[^-]+$"))` | query executed and returned data |
| [ ] | EMPTY | panel | VPN Tunnel Errors |  | ${datasource} | `sum by (service) (label_replace(rate(container_network_receive_errors_total{namespace=~"vpn-gateway\|media", interface="tun0", pod=~"$service.*"}[$smoothing]), "service", "$1", "pod", "^([^-]+-?[^-]*)-[^-]+-[^-]+$"))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | VPN Tunnel Errors |  | ${datasource} | `sum by (service) (label_replace(rate(container_network_transmit_errors_total{namespace=~"vpn-gateway\|media", interface="tun0", pod=~"$service.*"}[$smoothing]), "service", "$1", "pod", "^([^-]+-?[^-]*)-[^-]+-[^-]+$"))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | VPN Dropped Packets |  | ${datasource} | `sum by (service) (label_replace(rate(container_network_receive_packets_dropped_total{namespace=~"vpn-gateway\|media", interface="tun0", pod=~"$service.*"}[$smoothing]), "service", "$1", "pod", "^([^-]+-?[^-]*)-[^-]+-[^-]+$"))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | VPN Dropped Packets |  | ${datasource} | `sum by (service) (label_replace(rate(container_network_transmit_packets_dropped_total{namespace=~"vpn-gateway\|media", interface="tun0", pod=~"$service.*"}[$smoothing]), "service", "$1", "pod", "^([^-]+-?[^-]*)-[^-]+-[^-]+$"))` | query executed successfully but returned no data |
| [x] | PASS | panel | All VPN Services Summary | Status | ${datasource} | `max by (service) (label_replace(gluetun_up{namespace=~"vpn-gateway\|media"}, "service", "$1", "app_kubernetes_io_name", "(.*)"))` | query executed and returned data |
| [x] | PASS | panel | All VPN Services Summary | Exit_IP | ${datasource} | `max by (service, public_ip) (label_replace(gluetun_info{namespace=~"vpn-gateway\|media"}, "service", "$1", "app_kubernetes_io_name", "(.*)"))` | query executed and returned data |
| [x] | PASS | panel | All VPN Services Summary | Country | ${datasource} | `max by (service, country) (label_replace(gluetun_info{namespace=~"vpn-gateway\|media"}, "service", "$1", "app_kubernetes_io_name", "(.*)"))` | query executed and returned data |
| [x] | PASS | panel | All VPN Services Summary | City | ${datasource} | `max by (service, city) (label_replace(gluetun_info{namespace=~"vpn-gateway\|media"}, "service", "$1", "app_kubernetes_io_name", "(.*)"))` | query executed and returned data |
| [x] | PASS | panel | All VPN Services Summary | RX_Rate | ${datasource} | `sum by (service) (label_replace(rate(container_network_receive_bytes_total{namespace=~"vpn-gateway\|media", interface="tun0"}[$smoothing]), "service", "$1", "pod", "^([^-]+-?[^-]*)-[^-]+-[^-]+$"))` | query executed and returned data |
| [x] | PASS | panel | All VPN Services Summary | TX_Rate | ${datasource} | `sum by (service) (label_replace(rate(container_network_transmit_bytes_total{namespace=~"vpn-gateway\|media", interface="tun0"}[$smoothing]), "service", "$1", "pod", "^([^-]+-?[^-]*)-[^-]+-[^-]+$"))` | query executed and returned data |
| [x] | PASS | panel | All VPN Services Summary | Total_RX | ${datasource} | `sum by (service) (label_replace(container_network_receive_bytes_total{namespace=~"vpn-gateway\|media", interface="tun0"}, "service", "$1", "pod", "^([^-]+-?[^-]*)-[^-]+-[^-]+$"))` | query executed and returned data |
| [x] | PASS | panel | All VPN Services Summary | Total_TX | ${datasource} | `sum by (service) (label_replace(container_network_transmit_bytes_total{namespace=~"vpn-gateway\|media", interface="tun0"}, "service", "$1", "pod", "^([^-]+-?[^-]*)-[^-]+-[^-]+$"))` | query executed and returned data |
| [x] | PASS | panel | VPN Bandwidth by Exit Location |  | ${datasource} | `sum by (service) (label_replace(rate(container_network_receive_bytes_total{namespace=~"vpn-gateway\|media", interface="tun0"}[$smoothing]), "service", "$1", "pod", "^([^-]+-?[^-]*)-[^-]+-[^-]+$"))` | query executed and returned data |
| [x] | PASS | panel | VPN Bandwidth by Exit Location |  | ${datasource} | `sum by (service) (label_replace(rate(container_network_transmit_bytes_total{namespace=~"vpn-gateway\|media", interface="tun0"}[$smoothing]), "service", "$1", "pod", "^([^-]+-?[^-]*)-[^-]+-[^-]+$"))` | query executed and returned data |
| [x] | PASS | panel | Traffic Summary by Exit Location | Location | ${datasource} | `max by (service, country, city, public_ip) (label_replace(gluetun_info{namespace=~"vpn-gateway\|media"}, "service", "$1", "app_kubernetes_io_name", "(.*)"))` | query executed and returned data |
| [x] | PASS | panel | Traffic Summary by Exit Location | RX_Rate | ${datasource} | `sum by (service) (label_replace(rate(container_network_receive_bytes_total{namespace=~"vpn-gateway\|media", interface="tun0"}[$smoothing]), "service", "$1", "pod", "^([^-]+-?[^-]*)-[^-]+-[^-]+$"))` | query executed and returned data |
| [x] | PASS | panel | Traffic Summary by Exit Location | TX_Rate | ${datasource} | `sum by (service) (label_replace(rate(container_network_transmit_bytes_total{namespace=~"vpn-gateway\|media", interface="tun0"}[$smoothing]), "service", "$1", "pod", "^([^-]+-?[^-]*)-[^-]+-[^-]+$"))` | query executed and returned data |
| [x] | PASS | panel | Traffic Summary by Exit Location | Total_RX | ${datasource} | `sum by (service) (label_replace(container_network_receive_bytes_total{namespace=~"vpn-gateway\|media", interface="tun0"}, "service", "$1", "pod", "^([^-]+-?[^-]*)-[^-]+-[^-]+$"))` | query executed and returned data |
| [x] | PASS | panel | Traffic Summary by Exit Location | Total_TX | ${datasource} | `sum by (service) (label_replace(container_network_transmit_bytes_total{namespace=~"vpn-gateway\|media", interface="tun0"}, "service", "$1", "pod", "^([^-]+-?[^-]*)-[^-]+-[^-]+$"))` | query executed and returned data |
| [x] | PASS | panel | Total Rotations | A | ${datasource} | `max(vpn_rotation_total_all)` | query executed and returned data |
| [x] | PASS | panel | Active VPN Pods | A | ${datasource} | `count(vpn_rotation_current)` | query executed and returned data |
| [x] | PASS | panel | Available Servers | A | ${datasource} | `count(vpn_rotation_total)` | query executed and returned data |
| [x] | PASS | panel | Last Rotation | A | ${datasource} | `max(vpn_rotation_last_timestamp) * 1000` | query executed and returned data |
| [x] | PASS | panel | Server Distribution | A | ${datasource} | `vpn_rotation_total{job="vpn-rotator-exporter"}` | query executed and returned data |
| [x] | PASS | panel | Current Pod Assignments | A | ${datasource} | `vpn_rotation_current{job="vpn-rotator-exporter"}` | query executed and returned data |
| [x] | PASS | panel | Rotation History by Server | A | ${datasource} | `vpn_rotation_total{job="vpn-rotator-exporter"}` | query executed and returned data |
| [x] | PASS | panel | Server Balance (Target: 25% each for 4 servers) | A | ${datasource} | `vpn_rotation_server_distribution{job="vpn-rotator-exporter"}` | query executed and returned data |

### Web monitoring (`xtkCtBkiz`)

Folder: GitOps · Panels: 9 · Queries: 9

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: targets | targets | Mimir | `label_values(probe_success, instance)` | query executed and returned data |
| [x] | PASS | panel | $targets | A | Mimir | `probe_success{instance=~"$targets"}` | query executed and returned data |
| [x] | PASS | panel | SSL | A | Mimir | `probe_http_ssl{instance=~"$targets"}` | query executed and returned data |
| [x] | PASS | panel | Probe Duration | A | Mimir | `probe_duration_seconds{instance=~"$targets"}` | query executed and returned data |
| [x] | PASS | panel | DNS Lookup | A | Mimir | `probe_dns_lookup_time_seconds{instance=~"$targets"}` | query executed and returned data |
| [ ] | EMPTY | panel | SSL Cert Expiry | A | Mimir | `probe_ssl_earliest_cert_expiry{instance=~"$targets"}-time()` | query executed successfully but returned no data |
| [x] | PASS | panel | HTTP Status Code | A | Mimir | `probe_http_status_code{target=~"$targets"}` | query executed and returned data |
| [x] | PASS | panel | Average Probe Duration | A | Mimir | `avg(probe_duration_seconds{target=~"$targets"})` | query executed and returned data |
| [x] | PASS | panel | Average DNS Lookup | A | Mimir | `avg(probe_dns_lookup_time_seconds{target=~"$targets"})` | query executed and returned data |

### Workload Ops - Namespace & App Drill-down (`workload-ops`)

Folder: Cluster · Panels: 25 · Queries: 26

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: namespace | namespace | mimir | `label_values(kube_pod_info, namespace)` | query executed and returned data |
| [x] | PASS | variable | Variable: workload | workload | mimir | `query_result(group by (workload) (label_replace(kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet"},"workload","$1","owner_name","(.+)-[^-]+$") or label_replace(kube_pod_owner{namespace=~"$namespace",owner_kind="Job"},"workload","$1","owner_name","(.+?)(?:-[0-9]{6,})?$") or label_replace(kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job"},"workload","$1","owner_name","(.+)")))` | query executed and returned data |
| [x] | PASS | panel | Pods Running | A | mimir | `count(group by (namespace,pod) (kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"} or kube_pod_owner{namespace=~"$namespace",owner_kind="Job",owner_name=~"$workload(-[0-9]{6,})?"} or kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job",owner_name=~"$workload"}) and on(namespace,pod) group by (namespace,pod) (kube_pod_status_phase{namespace=~"$namespace",phase="Running"} == 1))` | query executed and returned data |
| [ ] | EMPTY | panel | Pods NOT Running | A | mimir | `count(group by (namespace,pod) (kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"} or kube_pod_owner{namespace=~"$namespace",owner_kind="Job",owner_name=~"$workload(-[0-9]{6,})?"} or kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job",owner_name=~"$workload"}) and on(namespace,pod) group by (namespace,pod) (kube_pod_status_phase{namespace=~"$namespace",phase!="Running",phase!="Succeeded"} == 1))` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | Containers Not Ready | A | mimir | `count(kube_pod_container_status_ready{namespace=~"$namespace"} == 0 and on(namespace,pod) group by (namespace,pod) (kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"} or kube_pod_owner{namespace=~"$namespace",owner_kind="Job",owner_name=~"$workload(-[0-9]{6,})?"} or kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job",owner_name=~"$workload"}))` | query executed successfully but returned no data |
| [x] | PASS | panel | Restarts (window) | A | mimir | `clamp_min(sum((max_over_time(kube_pod_container_status_restarts_total{namespace=~"$namespace"}[$__range]) - min_over_time(kube_pod_container_status_restarts_total{namespace=~"$namespace"}[$__range])) * on(namespace,pod) group_left() group by (namespace,pod) (kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"} or kube_pod_owner{namespace=~"$namespace",owner_kind="Job",owner_name=~"$workload(-[0-9]{6,})?"} or kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job",owner_name=~"$workload"})), 0) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | Peak CPU Throttling (window) | A | mimir | `max(100 * sum by (namespace,pod) (rate(container_cpu_cfs_throttled_periods_total{namespace=~"$namespace",container!=""}[$__rate_interval]) * on(namespace,pod) group_left() group by (namespace,pod) (kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"} or kube_pod_owner{namespace=~"$namespace",owner_kind="Job",owner_name=~"$workload(-[0-9]{6,})?"} or kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job",owner_name=~"$workload"})) / sum by (namespace,pod) (rate(container_cpu_cfs_periods_total{namespace=~"$namespace",container!=""}[$__rate_interval]) * on(namespace,pod) group_left() group by (namespace,pod) (kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"} or kube_pod_owner{namespace=~"$namespace",owner_kind="Job",owner_name=~"$workload(-[0-9]{6,})?"} or kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job",owner_name=~"$workload"})))` | query executed and returned data |
| [x] | PASS | panel | Peak Memory vs Limit (window) | A | mimir | `max(100 * max by (namespace,pod,container) (container_memory_working_set_bytes{namespace=~"$namespace",container!=""}) / on(namespace,pod,container) max by (namespace,pod,container) (kube_pod_container_resource_limits{namespace=~"$namespace",resource="memory"}) * on(namespace,pod) group_left() group by (namespace,pod) (kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"} or kube_pod_owner{namespace=~"$namespace",owner_kind="Job",owner_name=~"$workload(-[0-9]{6,})?"} or kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job",owner_name=~"$workload"}))` | query executed and returned data |
| [x] | PASS | panel | OOM Kills (24h) | A | mimir | `sum(increase(container_oom_events_total{namespace=~"$namespace",container!=""}[24h]) * on(namespace,pod) group_left() group by (namespace,pod) (kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"} or kube_pod_owner{namespace=~"$namespace",owner_kind="Job",owner_name=~"$workload(-[0-9]{6,})?"} or kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job",owner_name=~"$workload"})) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | Replica Availability | A | mimir | `100 * ( (sum(kube_deployment_status_replicas_ready{namespace=~"$namespace",deployment=~"$workload"}) or sum(kube_statefulset_status_replicas_ready{namespace=~"$namespace",statefulset=~"$workload"})) / (sum(kube_deployment_spec_replicas{namespace=~"$namespace",deployment=~"$workload"}) or sum(kube_statefulset_replicas{namespace=~"$namespace",statefulset=~"$workload"})) )` | query executed and returned data |
| [x] | PASS | panel | CPU usage per container (cores) | A | mimir | `topk(20, sum by (namespace,pod,container) (rate(container_cpu_usage_seconds_total{namespace=~"$namespace",container!=""}[$__rate_interval]) * on(namespace,pod) group_left() group by (namespace,pod) (kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"} or kube_pod_owner{namespace=~"$namespace",owner_kind="Job",owner_name=~"$workload(-[0-9]{6,})?"} or kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job",owner_name=~"$workload"})))` | query executed and returned data |
| [x] | PASS | panel | CPU usage per container (cores) | B | mimir | `sum by (namespace,pod) (kube_pod_container_resource_requests{namespace=~"$namespace",resource="cpu"} * on(namespace,pod) group_left() group by (namespace,pod) (kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"} or kube_pod_owner{namespace=~"$namespace",owner_kind="Job",owner_name=~"$workload(-[0-9]{6,})?"} or kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job",owner_name=~"$workload"}))` | query executed and returned data |
| [x] | PASS | panel | CPU usage per container (cores) | C | mimir | `sum by (namespace,pod) (kube_pod_container_resource_limits{namespace=~"$namespace",resource="cpu"} * on(namespace,pod) group_left() group by (namespace,pod) (kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"} or kube_pod_owner{namespace=~"$namespace",owner_kind="Job",owner_name=~"$workload(-[0-9]{6,})?"} or kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job",owner_name=~"$workload"}))` | query executed and returned data |
| [x] | PASS | panel | CPU throttling % per pod | A | mimir | `topk(20, 100 * sum by (namespace,pod) (rate(container_cpu_cfs_throttled_periods_total{namespace=~"$namespace",container!=""}[$__rate_interval]) * on(namespace,pod) group_left() group by (namespace,pod) (kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"} or kube_pod_owner{namespace=~"$namespace",owner_kind="Job",owner_name=~"$workload(-[0-9]{6,})?"} or kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job",owner_name=~"$workload"})) / sum by (namespace,pod) (rate(container_cpu_cfs_periods_total{namespace=~"$namespace",container!=""}[$__rate_interval]) * on(namespace,pod) group_left() group by (namespace,pod) (kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"} or kube_pod_owner{namespace=~"$namespace",owner_kind="Job",owner_name=~"$workload(-[0-9]{6,})?"} or kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job",owner_name=~"$workload"})))` | query executed and returned data |
| [x] | PASS | panel | Memory working set per container | A | mimir | `topk(20, sum by (namespace,pod,container) (container_memory_working_set_bytes{namespace=~"$namespace",container!=""} * on(namespace,pod) group_left() group by (namespace,pod) (kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"} or kube_pod_owner{namespace=~"$namespace",owner_kind="Job",owner_name=~"$workload(-[0-9]{6,})?"} or kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job",owner_name=~"$workload"})))` | query executed and returned data |
| [x] | PASS | panel | Memory working set per container | B | mimir | `sum by (namespace,pod) (kube_pod_container_resource_requests{namespace=~"$namespace",resource="memory"} * on(namespace,pod) group_left() group by (namespace,pod) (kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"} or kube_pod_owner{namespace=~"$namespace",owner_kind="Job",owner_name=~"$workload(-[0-9]{6,})?"} or kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job",owner_name=~"$workload"}))` | query executed and returned data |
| [x] | PASS | panel | Memory working set per container | C | mimir | `sum by (namespace,pod) (kube_pod_container_resource_limits{namespace=~"$namespace",resource="memory"} * on(namespace,pod) group_left() group by (namespace,pod) (kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"} or kube_pod_owner{namespace=~"$namespace",owner_kind="Job",owner_name=~"$workload(-[0-9]{6,})?"} or kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job",owner_name=~"$workload"}))` | query executed and returned data |
| [x] | PASS | panel | Memory % of limit per container | A | mimir | `topk(20, 100 * max by (namespace,pod,container) (container_memory_working_set_bytes{namespace=~"$namespace",container!=""}) / on(namespace,pod,container) max by (namespace,pod,container) (kube_pod_container_resource_limits{namespace=~"$namespace",resource="memory"}) * on(namespace,pod) group_left() group by (namespace,pod) (kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"} or kube_pod_owner{namespace=~"$namespace",owner_kind="Job",owner_name=~"$workload(-[0-9]{6,})?"} or kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job",owner_name=~"$workload"}))` | query executed and returned data |
| [x] | PASS | panel | Memory composition — RSS vs page cache | A | mimir | `topk(20, sum by (namespace,pod,container) (container_memory_rss{namespace=~"$namespace",container!=""} * on(namespace,pod) group_left() group by (namespace,pod) (kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"} or kube_pod_owner{namespace=~"$namespace",owner_kind="Job",owner_name=~"$workload(-[0-9]{6,})?"} or kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job",owner_name=~"$workload"})))` | query executed and returned data |
| [x] | PASS | panel | Memory composition — RSS vs page cache | B | mimir | `topk(20, sum by (namespace,pod,container) (container_memory_cache{namespace=~"$namespace",container!=""} * on(namespace,pod) group_left() group by (namespace,pod) (kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"} or kube_pod_owner{namespace=~"$namespace",owner_kind="Job",owner_name=~"$workload(-[0-9]{6,})?"} or kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job",owner_name=~"$workload"})))` | query executed and returned data |
| [x] | PASS | panel | Restarts over time | A | mimir | `clamp_min(sum by (namespace,pod,container) ((max_over_time(kube_pod_container_status_restarts_total{namespace=~"$namespace"}[$__interval]) - min_over_time(kube_pod_container_status_restarts_total{namespace=~"$namespace"}[$__interval])) * on(namespace,pod) group_left() group by (namespace,pod) (kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"} or kube_pod_owner{namespace=~"$namespace",owner_kind="Job",owner_name=~"$workload(-[0-9]{6,})?"} or kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job",owner_name=~"$workload"})), 0)` | query executed and returned data |
| [x] | PASS | panel | Last termination reason | A | mimir | `sum by (pod, container, reason) (kube_pod_container_status_last_terminated_reason{namespace=~"$namespace"} * on(namespace,pod) group_left() group by (namespace,pod) (kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"} or kube_pod_owner{namespace=~"$namespace",owner_kind="Job",owner_name=~"$workload(-[0-9]{6,})?"} or kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job",owner_name=~"$workload"})) > 0` | query executed and returned data |
| [ ] | EMPTY | panel | Containers waiting (CrashLoopBackOff etc.) | A | mimir | `sum by (pod, container, reason) (kube_pod_container_status_waiting_reason{namespace=~"$namespace"} * on(namespace,pod) group_left() group by (namespace,pod) (kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"} or kube_pod_owner{namespace=~"$namespace",owner_kind="Job",owner_name=~"$workload(-[0-9]{6,})?"} or kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job",owner_name=~"$workload"})) > 0` | query executed successfully but returned no data |
| [x] | PASS | panel | Network receive per pod | A | mimir | `topk(20, sum by (namespace,pod) (rate(container_network_receive_bytes_total{namespace=~"$namespace",interface=~"eth0\|tun0"}[$__rate_interval]) * on(namespace,pod) group_left() group by (namespace,pod) (kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"} or kube_pod_owner{namespace=~"$namespace",owner_kind="Job",owner_name=~"$workload(-[0-9]{6,})?"} or kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job",owner_name=~"$workload"})))` | query executed and returned data |
| [x] | PASS | panel | Network transmit per pod | A | mimir | `topk(20, sum by (namespace,pod) (rate(container_network_transmit_bytes_total{namespace=~"$namespace",interface=~"eth0\|tun0"}[$__rate_interval]) * on(namespace,pod) group_left() group by (namespace,pod) (kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"} or kube_pod_owner{namespace=~"$namespace",owner_kind="Job",owner_name=~"$workload(-[0-9]{6,})?"} or kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job",owner_name=~"$workload"})))` | query executed and returned data |
| [x] | PASS | panel | Pods in selection — node, QoS, age | A | mimir | `(time() - kube_pod_start_time{namespace=~"$namespace"}) * on(namespace,pod) group_left(node, qos_class) (kube_pod_info{namespace=~"$namespace"} * on(namespace,pod) group_left(qos_class) (kube_pod_status_qos_class{namespace=~"$namespace"} == 1)) * on(namespace,pod) group_left() group by (namespace,pod) (kube_pod_owner{namespace=~"$namespace",owner_kind="ReplicaSet",owner_name=~"$workload-[^-]+"} or kube_pod_owner{namespace=~"$namespace",owner_kind="Job",owner_name=~"$workload(-[0-9]{6,})?"} or kube_pod_owner{namespace=~"$namespace",owner_kind!~"ReplicaSet\|Job",owner_name=~"$workload"})` | query executed and returned data |

### ⚡ TOU Cost Optimization (`kasa-tou-opt-v2`)

Folder: Kasa · Panels: 18 · Queries: 27

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: version | version | mimir | `label_values(consumption_cost, version)` | query executed and returned data |
| [x] | PASS | panel | 🌟 Current Rate Class | A | mimir | `label_replace(max(current_energy_rate{version=~"$version"}), "rate_class", "$1", "rate_class", "(.*)")` | query executed and returned data |
| [x] | PASS | panel | ⚡ Power by Rate Class | A | mimir | `avg by (rate_class) (   current_consumption{version=~"$version"}   * on(device_id) group_left(rate_class, season)   current_energy_rate{version=~"$version"} )` | query executed and returned data |
| [x] | PASS | panel | 🎯 Optimal Usage Recommendations | A | mimir | `(   sum(increase(consumption_cost_with_rate_class{rate_class="super_off_peak", version=~"$version"}[$__range]))   /   sum(increase(consumption_cost_with_rate_class{version=~"$version"}[$__range])) ) * 100` | query executed and returned data |
| [x] | PASS | panel | 📊 Super Off-Peak Utilization | A | mimir | `(   sum(increase(consumption_cost_with_rate_class{rate_class="super_off_peak", version=~"$version"}[$__range]))   /   sum(increase(consumption_cost_with_rate_class{version=~"$version"}[$__range])) ) * 100` | query executed and returned data |
| [x] | PASS | panel | 💡 What-If: All Super Off-Peak ($0.314/kWh) | A | mimir | `(current_consumption:total{version=~"$version"} / 1000) * 0.314 * 730` | query executed and returned data |
| [x] | PASS | panel | 💡 What-If: All Off-Peak ($0.351/kWh) | A | mimir | `(current_consumption:total{version=~"$version"} / 1000) * 0.351 * 730` | query executed and returned data |
| [x] | PASS | panel | 💡 What-If: All On-Peak ($0.634/kWh) | A | mimir | `(current_consumption:total{version=~"$version"} / 1000) * 0.634 * 730` | query executed and returned data |
| [x] | PASS | panel | 📊 Scenario Comparison - Monthly Cost Projection | A | mimir | `(current_consumption:total{version=~"$version"} / 1000) * 0.314 * 730` | query executed and returned data |
| [x] | PASS | panel | 📊 Scenario Comparison - Monthly Cost Projection | B | mimir | `(current_consumption:total{version=~"$version"} / 1000) * 0.351 * 730` | query executed and returned data |
| [x] | PASS | panel | 📊 Scenario Comparison - Monthly Cost Projection | C | mimir | `(current_consumption:total{version=~"$version"} / 1000) * 0.634 * 730` | query executed and returned data |
| [x] | PASS | panel | 📊 Scenario Comparison - Monthly Cost Projection | D | mimir | `consumption_cost:projected_month{version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | 📋 Key Optimization Metrics | A | mimir | `consumption_cost:total{version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | 📋 Key Optimization Metrics | B | mimir | `consumption_cost:projected_day{version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | 📋 Key Optimization Metrics | C | mimir | `consumption_cost:projected_month{version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | 📋 Key Optimization Metrics | D | mimir | `consumption_cost:potential_savings_super_off_peak{version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | 📋 Key Optimization Metrics | E | mimir | `current_consumption:total{version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | 🔌 Current Power Distribution by Device | A | mimir | `max by (alias) (current_consumption{version=~"$version"})` | query executed and returned data |
| [x] | PASS | panel | 💲 Current Rate ($/kWh) | A | mimir | `current_energy_rate:current` | query executed and returned data |
| [x] | PASS | panel | ⏰ Rate Class Timeline | A | mimir | `rate_class:numeric` | query executed and returned data |
| [x] | PASS | panel | 🥧 Cost by Rate Class | A | mimir | `sum by (rate_class) (increase(consumption_cost_with_rate_class{version=~"$version"}[$__range]))` | query executed and returned data |
| [x] | PASS | panel | 📊 Cost Distribution Table | A | mimir | `sum by (rate_class) (increase(consumption_cost_with_rate_class{version=~"$version"}[$__range]))` | query executed and returned data |
| [x] | PASS | panel | 💵 Hourly Cost Trends by Rate Class | A | mimir | `sum by (rate_class) (increase(consumption_cost_with_rate_class{version=~"$version"}[1h]))` | query executed and returned data |
| [x] | PASS | panel | 💰 Potential Savings - Super Off-Peak | A | mimir | `consumption_cost:potential_savings_super_off_peak{version=~"$version"}` | query executed and returned data |
| [ ] | EMPTY | panel | 💰 Potential Savings - Off-Peak | A | mimir | `consumption_cost:potential_savings_off_peak{version=~"$version"}` | query executed successfully but returned no data |
| [x] | PASS | panel | 📈 Savings Over Time | A | mimir | `consumption_cost:potential_savings_super_off_peak{version=~"$version"}` | query executed and returned data |
| [ ] | EMPTY | panel | 📈 Savings Over Time | B | mimir | `consumption_cost:potential_savings_off_peak{version=~"$version"}` | query executed successfully but returned no data |

### 🌊 Real-Time Monitoring (`kasa-realtime-v2`)

Folder: Kasa · Panels: 9 · Queries: 18

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: version | version | mimir | `label_values(current_consumption, version)` | query executed and returned data |
| [x] | PASS | panel | ⚡ Total Power Draw | A | mimir | `current_consumption:total` | query executed and returned data |
| [x] | PASS | panel | 💰 Current Cost Rate (per hour) | A | mimir | `consumption_cost:total` | query executed and returned data |
| [x] | PASS | panel | ⚡ Energy Rate ($/kWh) | A | mimir | `max(current_energy_rate) by (season, rate_class)` | query executed and returned data |
| [x] | PASS | panel | 📊 Projected Daily Cost | A | mimir | `consumption_cost:projected_day` | query executed and returned data |
| [x] | PASS | panel | 🌊 Power Consumption Over Time | A | mimir | `current_consumption:by_device` | query executed and returned data |
| [x] | PASS | panel | 🥧 Power Distribution | A | mimir | `current_consumption:by_device` | query executed and returned data |
| [x] | PASS | panel | 💵 Cost Rate History ($/hr by Device) | A | mimir | `consumption_cost:by_device` | query executed and returned data |
| [x] | PASS | panel | 📈 Projected Costs (Hour/Day/Month) | A | mimir | `consumption_cost:projected_hour` | query executed and returned data |
| [x] | PASS | panel | 📈 Projected Costs (Hour/Day/Month) | B | mimir | `consumption_cost:projected_day` | query executed and returned data |
| [x] | PASS | panel | 📈 Projected Costs (Hour/Day/Month) | C | mimir | `consumption_cost:projected_month` | query executed and returned data |
| [ ] | EMPTY | panel | 📊 Device Status Table | State | mimir | `max without (state) (state{version="$version"})` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | 📊 Device Status Table | Power | mimir | `current_consumption{version="$version"}` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | 📊 Device Status Table | Cost | mimir | `consumption_cost{version="$version"}` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | 📊 Device Status Table | EnergyToday | mimir | `consumption_today{version="$version"}` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | 📊 Device Status Table | EnergyMonth | mimir | `consumption_this_month{version="$version"}` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | 📊 Device Status Table | Uptime | mimir | `on_since{version="$version"}` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | 📊 Device Status Table | RSSI | mimir | `rssi{version="$version"}` | query executed successfully but returned no data |

### 📊 Comparative Analytics (`kasa-compare-v2`)

Folder: Kasa · Panels: 28 · Queries: 48

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: version | version | mimir | `label_values(consumption_cost, version)` | query executed and returned data |
| [x] | PASS | variable | Variable: device | device | mimir | `label_values(current_consumption, alias)` | query executed and returned data |
| [x] | PASS | variable | Variable: baseline_device | baseline_device | mimir | `label_values(current_consumption, alias)` | query executed and returned data |
| [x] | PASS | panel | 👑 Highest Power Consumer | A | mimir | `topk(1, current_consumption:by_device{version=~"$version", alias=~"$device"})` | query executed and returned data |
| [x] | PASS | panel | 💰 Most Expensive Device | A | mimir | `topk(1, consumption_cost:by_device{version=~"$version", alias=~"$device"})` | query executed and returned data |
| [x] | PASS | panel | ⚡ Most Efficient | A | mimir | `bottomk(1, cost_efficiency:by_device{version=~"$version", alias=~"$device"})` | query executed and returned data |
| [x] | PASS | panel | 📊 Device Count | A | mimir | `count(current_consumption:by_device{version=~"$version", alias=~"$device"})` | query executed and returned data |
| [x] | PASS | panel | 📊 Power by Device | A | mimir | `sort_desc(current_consumption:by_device{version=~"$version", alias=~"$device"})` | query executed and returned data |
| [x] | PASS | panel | 🥧 Power Share % | A | mimir | `current_consumption:by_device{version=~"$version", alias=~"$device"}` | query executed and returned data |
| [x] | PASS | panel | 📈 Power Comparison Timeline | A | mimir | `current_consumption:by_device{version=~"$version", alias=~"$device"}` | query executed and returned data |
| [x] | PASS | panel | 📊 Power Ranking Table | A | mimir | `current_consumption:by_device{version=~"$version", alias=~"$device"}` | query executed and returned data |
| [x] | PASS | panel | 📊 Power Ranking Table | B | mimir | `(current_consumption:by_device{version=~"$version", alias=~"$device"} / ignoring(alias) group_left sum(current_consumption:by_device{version=~"$version", alias=~"$device"})) * 100` | query executed and returned data |
| [x] | PASS | panel | 💰 Cost by Device | A | mimir | `sort_desc(consumption_cost:by_device{version=~"$version", alias=~"$device"})` | query executed and returned data |
| [x] | PASS | panel | 🥧 Cost Share % | A | mimir | `consumption_cost:by_device{version=~"$version", alias=~"$device"}` | query executed and returned data |
| [x] | PASS | panel | 📈 Cost Comparison Timeline | A | mimir | `consumption_cost:by_device{version=~"$version", alias=~"$device"}` | query executed and returned data |
| [x] | PASS | panel | 💵 Cost Efficiency Ranking | A | mimir | `consumption_cost:by_device{version=~"$version", alias=~"$device"}` | query executed and returned data |
| [x] | PASS | panel | 💵 Cost Efficiency Ranking | B | mimir | `current_consumption:by_device{version=~"$version", alias=~"$device"}` | query executed and returned data |
| [x] | PASS | panel | 💵 Cost Efficiency Ranking | C | mimir | `cost_efficiency:by_device{version=~"$version", alias=~"$device"}` | query executed and returned data |
| [x] | PASS | panel | ⚡ Cost Efficiency ($/W) - Lower is Better | A | mimir | `sort(cost_efficiency:by_device{version=~"$version", alias=~"$device"})` | query executed and returned data |
| [x] | PASS | panel | 📊 Efficiency Heatmap | A | mimir | `cost_efficiency:by_device{version=~"$version", alias=~"$device"}` | query executed and returned data |
| [x] | PASS | panel | 🎯 Baseline Comparison (vs $baseline_device) | A | mimir | `current_consumption:by_device{version=~"$version", alias=~"$device"}` | query executed and returned data |
| [x] | PASS | panel | 🎯 Baseline Comparison (vs $baseline_device) | B | mimir | `current_consumption:by_device{version=~"$version", alias="$baseline_device"}` | query executed and returned data |
| [x] | PASS | panel | 🎯 Baseline Comparison (vs $baseline_device) | C | mimir | `consumption_cost:by_device{version=~"$version", alias=~"$device"}` | query executed and returned data |
| [x] | PASS | panel | 🎯 Baseline Comparison (vs $baseline_device) | D | mimir | `consumption_cost:by_device{version=~"$version", alias="$baseline_device"}` | query executed and returned data |
| [x] | PASS | panel | 🎯 Baseline Comparison (vs $baseline_device) | E | mimir | `cost_efficiency:by_device{version=~"$version", alias=~"$device"}` | query executed and returned data |
| [x] | PASS | panel | 🎯 Baseline Comparison (vs $baseline_device) | F | mimir | `cost_efficiency:by_device{version=~"$version", alias="$baseline_device"}` | query executed and returned data |
| [x] | PASS | panel | 📈 Efficiency Trend ($/W over time) | A | mimir | `cost_efficiency:by_device{version=~"$version", alias=~"$device"}` | query executed and returned data |
| [x] | PASS | panel | 📅 Daily Energy Comparison (kWh) | A | mimir | `increase(consumption_today{version=~"$version", alias=~"$device"}[24h])` | query executed and returned data |
| [x] | PASS | panel | 📅 Monthly Energy Comparison (kWh) | A | mimir | `increase(consumption_today{version=~"$version", alias=~"$device"}[30d])` | query executed and returned data |
| [x] | PASS | panel | 📊 Cost Over Time (Stacked) | A | mimir | `consumption_cost:by_device{version=~"$version", alias=~"$device"}` | query executed and returned data |
| [x] | PASS | panel | 💰 Period Cost Table | A | mimir | `consumption_cost:by_device{version=~"$version", alias=~"$device"}` | query executed and returned data |
| [x] | PASS | panel | 📊 💵 Total Cost Today ($) | A | mimir | `increase(consumption_today{version=~"$version", alias=~"$device"}[24h])` | query executed and returned data |
| [x] | PASS | panel | 📊 💵 Total Cost Today ($) | B | mimir | `avg_over_time(consumption_cost:by_device{version=~"$version", alias=~"$device"}[24h]) * 24` | query executed and returned data |
| [x] | PASS | panel | 📊 Average Power | A | mimir | `avg_over_time(current_consumption:by_device{version=~"$version", alias=~"$device"}[$__range])` | query executed and returned data |
| [x] | PASS | panel | 📊 Peak Power | A | mimir | `max_over_time(current_consumption:by_device{version=~"$version", alias=~"$device"}[$__range])` | query executed and returned data |
| [ ] | EMPTY | panel | 📊 Utilization % | A | mimir | `power_utilization:by_device{version=~"$version", alias=~"$device"}` | query executed successfully but returned no data |
| [x] | PASS | panel | 📈 Power Statistics | A | mimir | `avg_over_time(current_consumption:by_device{version=~"$version", alias=~"$device"}[$__range])` | query executed and returned data |
| [x] | PASS | panel | 📈 Power Statistics | B | mimir | `quantile_over_time(0.5, current_consumption:by_device{version=~"$version", alias=~"$device"}[$__range])` | query executed and returned data |
| [x] | PASS | panel | 📈 Power Statistics | C | mimir | `stddev_over_time(current_consumption:by_device{version=~"$version", alias=~"$device"}[$__range])` | query executed and returned data |
| [x] | PASS | panel | 📈 Power Statistics | D | mimir | `min_over_time(current_consumption:by_device{version=~"$version", alias=~"$device"}[$__range])` | query executed and returned data |
| [x] | PASS | panel | 📈 Power Statistics | E | mimir | `max_over_time(current_consumption:by_device{version=~"$version", alias=~"$device"}[$__range])` | query executed and returned data |
| [x] | PASS | panel | 💰 Cost Statistics | A | mimir | `avg_over_time(consumption_cost:by_device{version=~"$version", alias=~"$device"}[$__range])` | query executed and returned data |
| [x] | PASS | panel | 💰 Cost Statistics | B | mimir | `quantile_over_time(0.5, consumption_cost:by_device{version=~"$version", alias=~"$device"}[$__range])` | query executed and returned data |
| [x] | PASS | panel | 💰 Cost Statistics | C | mimir | `stddev_over_time(consumption_cost:by_device{version=~"$version", alias=~"$device"}[$__range])` | query executed and returned data |
| [x] | PASS | panel | 💰 Cost Statistics | D | mimir | `min_over_time(consumption_cost:by_device{version=~"$version", alias=~"$device"}[$__range])` | query executed and returned data |
| [x] | PASS | panel | 💰 Cost Statistics | E | mimir | `max_over_time(consumption_cost:by_device{version=~"$version", alias=~"$device"}[$__range])` | query executed and returned data |
| [x] | PASS | panel | 📊 Correlation Matrix (Devices with Similar Usage Patterns) | A | mimir | `current_consumption:by_device{version=~"$version", alias=~"$device"}` | query executed and returned data |
| [ ] | EMPTY | panel | 🎯 Outlier Devices (High Variance) | A | mimir | `count by (alias) (stddev_over_time(current_consumption:by_device{version=~"$version", alias=~"$device"}[$__range]) > avg(stddev_over_time(current_consumption:by_device{version=~"$version", alias=~"$device"}[$__range])))` | query executed successfully but returned no data |

### 🔋 Battery Sizing & Analysis (`kasa-battery-v2`)

Folder: Kasa · Panels: 33 · Queries: 56

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [ ] | REVIEW | variable | Variable: version | version | mimir | `label_values(version)` | Grafana variable helper requires UI evaluation |
| [ ] | REVIEW | variable | Variable: device | device | mimir | `label_values(alias)` | Grafana variable helper requires UI evaluation |
| [x] | PASS | panel | ⚡ Total Load | A | mimir | `sum(current_consumption{alias=~"$device", version=~"$version"})` | query executed and returned data |
| [x] | PASS | panel | 🔌 Average Load (1h) | A | mimir | `sum(avg_over_time(current_consumption{alias=~"$device", version=~"$version"}[1h]))` | query executed and returned data |
| [x] | PASS | panel | 📊 Peak Load (24h) | A | mimir | `sum(max_over_time(current_consumption{alias=~"$device", version=~"$version"}[24h]))` | query executed and returned data |
| [x] | PASS | panel | 📉 Min Load (24h) | A | mimir | `sum(min_over_time(current_consumption{alias=~"$device", version=~"$version"}[24h]))` | query executed and returned data |
| [x] | PASS | panel | ⏱️ Runtime @ Current Load | A | mimir | `(($battery_voltage * $battery_capacity_ah * $depth_of_discharge * $inverter_efficiency) / sum(current_consumption{alias=~"$device", version=~"$version"}))` | query executed and returned data |
| [x] | PASS | panel | ⏱️ Runtime @ Average Load | A | mimir | `(($battery_voltage * $battery_capacity_ah * $depth_of_discharge * $inverter_efficiency) / sum(avg_over_time(current_consumption{alias=~"$device", version=~"$version"}[1h])))` | query executed and returned data |
| [x] | PASS | panel | ⏱️ Runtime @ Peak Load | A | mimir | `(($battery_voltage * $battery_capacity_ah * $depth_of_discharge * $inverter_efficiency) / sum(max_over_time(current_consumption{alias=~"$device", version=~"$version"}[24h])))` | query executed and returned data |
| [x] | PASS | panel | 🎯 Recommended Capacity | A | mimir | `((sum(max_over_time(current_consumption{alias=~"$device", version=~"$version"}[24h])) * 8) / ($battery_voltage * $depth_of_discharge * $inverter_efficiency))` | query executed and returned data |
| [x] | PASS | panel | 🎯 Recommended Capacity | B | mimir | `((sum(max_over_time(current_consumption{alias=~"$device", version=~"$version"}[24h])) * 12) / ($battery_voltage * $depth_of_discharge * $inverter_efficiency))` | query executed and returned data |
| [x] | PASS | panel | 🎯 Recommended Capacity | C | mimir | `((sum(max_over_time(current_consumption{alias=~"$device", version=~"$version"}[24h])) * 24) / ($battery_voltage * $depth_of_discharge * $inverter_efficiency))` | query executed and returned data |
| [x] | PASS | panel | 📊 Runtime Comparison Table | A | mimir | `((12 * 100 * $depth_of_discharge * $inverter_efficiency) / sum(current_consumption{alias=~"$device", version=~"$version"}))` | query executed and returned data |
| [x] | PASS | panel | 📊 Runtime Comparison Table | B | mimir | `((12 * 200 * $depth_of_discharge * $inverter_efficiency) / sum(current_consumption{alias=~"$device", version=~"$version"}))` | query executed and returned data |
| [x] | PASS | panel | 📊 Runtime Comparison Table | C | mimir | `((12 * 400 * $depth_of_discharge * $inverter_efficiency) / sum(current_consumption{alias=~"$device", version=~"$version"}))` | query executed and returned data |
| [x] | PASS | panel | 📊 Runtime Comparison Table | D | mimir | `((24 * 100 * $depth_of_discharge * $inverter_efficiency) / sum(current_consumption{alias=~"$device", version=~"$version"}))` | query executed and returned data |
| [x] | PASS | panel | 📊 Runtime Comparison Table | E | mimir | `((24 * 200 * $depth_of_discharge * $inverter_efficiency) / sum(current_consumption{alias=~"$device", version=~"$version"}))` | query executed and returned data |
| [x] | PASS | panel | 📊 Runtime Comparison Table | F | mimir | `((24 * 400 * $depth_of_discharge * $inverter_efficiency) / sum(current_consumption{alias=~"$device", version=~"$version"}))` | query executed and returned data |
| [x] | PASS | panel | 📊 Runtime Comparison Table | G | mimir | `((48 * 100 * $depth_of_discharge * $inverter_efficiency) / sum(current_consumption{alias=~"$device", version=~"$version"}))` | query executed and returned data |
| [x] | PASS | panel | 📊 Runtime Comparison Table | H | mimir | `((48 * 200 * $depth_of_discharge * $inverter_efficiency) / sum(current_consumption{alias=~"$device", version=~"$version"}))` | query executed and returned data |
| [x] | PASS | panel | 📊 Runtime Comparison Table | I | mimir | `((48 * 400 * $depth_of_discharge * $inverter_efficiency) / sum(current_consumption{alias=~"$device", version=~"$version"}))` | query executed and returned data |
| [x] | PASS | panel | 📊 Runtime Comparison Table | J | mimir | `((48 * 800 * $depth_of_discharge * $inverter_efficiency) / sum(current_consumption{alias=~"$device", version=~"$version"}))` | query executed and returned data |
| [x] | PASS | panel | 🔋 Capacity Heatmap | A | mimir | `((12 * 100 * $depth_of_discharge * $inverter_efficiency) / sum(current_consumption{alias=~"$device", version=~"$version"}))` | query executed and returned data |
| [x] | PASS | panel | 🔋 Capacity Heatmap | B | mimir | `((12 * 200 * $depth_of_discharge * $inverter_efficiency) / sum(current_consumption{alias=~"$device", version=~"$version"}))` | query executed and returned data |
| [x] | PASS | panel | 🔋 Capacity Heatmap | C | mimir | `((24 * 100 * $depth_of_discharge * $inverter_efficiency) / sum(current_consumption{alias=~"$device", version=~"$version"}))` | query executed and returned data |
| [x] | PASS | panel | 🔋 Capacity Heatmap | D | mimir | `((24 * 200 * $depth_of_discharge * $inverter_efficiency) / sum(current_consumption{alias=~"$device", version=~"$version"}))` | query executed and returned data |
| [x] | PASS | panel | 🔋 Capacity Heatmap | E | mimir | `((48 * 100 * $depth_of_discharge * $inverter_efficiency) / sum(current_consumption{alias=~"$device", version=~"$version"}))` | query executed and returned data |
| [x] | PASS | panel | 🔋 Capacity Heatmap | F | mimir | `((48 * 200 * $depth_of_discharge * $inverter_efficiency) / sum(current_consumption{alias=~"$device", version=~"$version"}))` | query executed and returned data |
| [x] | PASS | panel | 📈 Power Consumption Timeline | A | mimir | `current_consumption{alias=~"$device", version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | 🌊 Cumulative Energy Draw | A | mimir | `sum by(alias) (avg_over_time(current_consumption{alias=~"$device", version=~"$version"}[1h])) * $__range_s / 3600` | query executed and returned data |
| [x] | PASS | panel | ⚡ Load Duration Curve | A | mimir | `sort_desc(sum(current_consumption{alias=~"$device", version=~"$version"}))` | query executed and returned data |
| [x] | PASS | panel | 💡 Minimum Battery Size (8h @ Peak) | A | mimir | `((sum(max_over_time(current_consumption{alias=~"$device", version=~"$version"}[24h])) * 8) / ($battery_voltage * $depth_of_discharge * $inverter_efficiency))` | query executed and returned data |
| [x] | PASS | panel | 💡 Recommended Battery Size (1.5x) | A | mimir | `((sum(max_over_time(current_consumption{alias=~"$device", version=~"$version"}[24h])) * 8 * 1.5) / ($battery_voltage * $depth_of_discharge * $inverter_efficiency))` | query executed and returned data |
| [x] | PASS | panel | 💡 Optimal Battery Size (2x degradation) | A | mimir | `((sum(max_over_time(current_consumption{alias=~"$device", version=~"$version"}[24h])) * 8 * 2.0) / ($battery_voltage * $depth_of_discharge * $inverter_efficiency))` | query executed and returned data |
| [x] | PASS | panel | 🔌 Required Inverter Size (1.25x peak) | A | mimir | `sum(max_over_time(current_consumption{alias=~"$device", version=~"$version"}[24h])) * 1.25` | query executed and returned data |
| [x] | PASS | panel | 💰 Daily Energy Cost | A | mimir | `sum(increase(consumption_cost{alias=~"$device", version=~"$version"}[24h]))` | query executed and returned data |
| [x] | PASS | panel | 💰 Potential Battery Savings (30% on-peak) | A | mimir | `sum(increase(consumption_cost{alias=~"$device", version=~"$version"}[24h])) * 0.3` | query executed and returned data |
| [x] | PASS | panel | 📊 ROI Payback Period | A | mimir | `(($battery_voltage * $battery_capacity_ah * 0.50) / (sum(consumption_cost{alias=~"$device", version=~"$version"}) * 8760))` | query executed and returned data |
| [x] | PASS | panel | 📉 Load Factor (avg/peak - higher is better) | A | mimir | `sum(avg_over_time(current_consumption{alias=~"$device", version=~"$version"}[24h])) / sum(max_over_time(current_consumption{alias=~"$device", version=~"$version"}[24h]))` | query executed and returned data |
| [x] | PASS | panel | ⚡ Capacity Factor (usage vs battery) | A | mimir | `($battery_voltage * $battery_capacity_ah * $inverter_efficiency) / sum(current_consumption{alias=~"$device", version=~"$version"})` | query executed and returned data |
| [x] | PASS | panel | 🎯 Autonomy Time @ Current Settings | A | mimir | `(($battery_voltage * $battery_capacity_ah * $depth_of_discharge * $inverter_efficiency) / sum(current_consumption{alias=~"$device", version=~"$version"}))` | query executed and returned data |
| [x] | PASS | panel | ☀️ Solar Charge Rate | A | mimir | `$solar_panel_watts * $inverter_efficiency` | query executed and returned data |
| [x] | PASS | panel | ⏱️ Time to Full Charge (Empty → Full) | A | mimir | `($battery_voltage * $battery_capacity_ah) / ($solar_panel_watts * $inverter_efficiency)` | query executed and returned data |
| [x] | PASS | panel | ⏱️ Time to Usable (0% → 80%) | A | mimir | `($battery_voltage * $battery_capacity_ah * 0.8) / ($solar_panel_watts * $inverter_efficiency)` | query executed and returned data |
| [x] | PASS | panel | ⚡ Net Energy Balance | A | mimir | `($solar_panel_watts * $inverter_efficiency) - sum(current_consumption{alias=~"$device", version=~"$version"})` | query executed and returned data |
| [x] | PASS | panel | ☀️ Daily Solar Production (5 sun hours) | A | mimir | `($solar_panel_watts * 5) / 1000` | query executed and returned data |
| [x] | PASS | panel | 📊 Daily Load Coverage % | A | mimir | `(($solar_panel_watts * 5) / (sum(current_consumption{alias=~"$device", version=~"$version"}) * 24)) * 100` | query executed and returned data |
| [x] | PASS | panel | 🔋 Runtime with Solar Recharge | A | mimir | `($battery_voltage * $battery_capacity_ah * $depth_of_discharge * $inverter_efficiency) / clamp_min(sum(current_consumption{alias=~"$device", version=~"$version"}) - ($solar_panel_watts * $inverter_efficiency * 0.5), 1)` | query executed and returned data |
| [x] | PASS | panel | 📈 Battery State of Charge Timeline | A | mimir | `100 - ((sum(current_consumption{alias=~"$device", version=~"$version"}) / ($battery_voltage * $battery_capacity_ah * $inverter_efficiency)) * 100 * (time() % 86400) / 3600)` | query executed and returned data |
| [ ] | FAIL | panel | 📈 Battery State of Charge Timeline | B | mimir | `clamp_max((($solar_panel_watts * $inverter_efficiency) / ($battery_voltage * $battery_capacity_ah)) * 100 * (time() % 86400) / 3600, 100)` | command failed (1): kubectl -n monitoring exec deploy/grafana-deployment -- wget --timeout=45 -qO- http://mimir-gateway.monitoring.svc/prometheus/api/v1/query?query=clamp_max%28%28%28400%20%2A%200.90%29%20%2F%20%2848%20%2A%20200%29%29%20%2A%20100%20%2A%20%28time%28%29%20%25%2086400%29%20%2F%203600%2C%20100%29 wget: server returned error: HTTP/1.1 400 Bad Request command terminated with exit code 1  |
| [x] | PASS | panel | 📈 Battery State of Charge Timeline | C | mimir | `clamp_max(clamp_min(100 + ((($solar_panel_watts * $inverter_efficiency) - sum(current_consumption{alias=~"$device", version=~"$version"})) / ($battery_voltage * $battery_capacity_ah * $inverter_efficiency)) * 100 * (time() % 86400) / 3600, 0), 100)` | query executed and returned data |
| [x] | PASS | panel | ☀️ Recommended Solar Panel Sizes | A | mimir | `sum(current_consumption{alias=~"$device", version=~"$version"})` | query executed and returned data |
| [x] | PASS | panel | ☀️ Recommended Solar Panel Sizes | B | mimir | `(sum(current_consumption{alias=~"$device", version=~"$version"}) * 24) / 5` | query executed and returned data |
| [x] | PASS | panel | ☀️ Recommended Solar Panel Sizes | C | mimir | `(sum(current_consumption{alias=~"$device", version=~"$version"}) * 24 * 1.5) / 5` | query executed and returned data |
| [x] | PASS | panel | ☀️ Recommended Solar Panel Sizes | D | mimir | `(sum(current_consumption{alias=~"$device", version=~"$version"}) * 24 * 2) / 5` | query executed and returned data |
| [x] | PASS | panel | 📅 Days of Autonomy (No Sun) | A | mimir | `(($battery_voltage * $battery_capacity_ah * $depth_of_discharge * $inverter_efficiency) / sum(current_consumption{alias=~"$device", version=~"$version"})) / 24` | query executed and returned data |

### 🔮 Forecasting & Predictions (`kasa-forecast-v2`)

Folder: Kasa · Panels: 27 · Queries: 41

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: version | version | mimir | `label_values(current_consumption, version)` | query executed and returned data |
| [x] | PASS | panel | 💰 Projected Monthly Cost | A | mimir | `consumption_cost:projected_month{version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | 📊 Month Progress | A | mimir | `(day_of_month() / 30.44) * 100` | query executed and returned data |
| [x] | PASS | panel | 🎯 Budget Status (vs $100) | A | mimir | `100 - (consumption_cost:projected_month{version=~"$version"})` | query executed and returned data |
| [x] | PASS | panel | 📈 Cost Trend (24h with Prediction) | A | mimir | `consumption_cost:avg_24h{version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | 📈 Cost Trend (24h with Prediction) | B | mimir | `predict_linear(consumption_cost:avg_24h{version=~"$version"}[6h], 3600)` | query executed and returned data |
| [x] | PASS | panel | 📈 Power Consumption Trend | A | mimir | `current_consumption:total{version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | 📈 Power Consumption Trend | B | mimir | `predict_linear(current_consumption:total{version=~"$version"}[1h], 3600)` | query executed and returned data |
| [x] | PASS | panel | 📈 Power Consumption Trend | C | mimir | `predict_linear(current_consumption:total{version=~"$version"}[6h], 21600)` | query executed and returned data |
| [x] | PASS | panel | 💵 Cost Rate Trend | A | mimir | `consumption_cost:total{version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | 💵 Cost Rate Trend | B | mimir | `predict_linear(consumption_cost:total{version=~"$version"}[1h], 3600)` | query executed and returned data |
| [x] | PASS | panel | 💵 Cost Rate Trend | C | mimir | `predict_linear(consumption_cost:total{version=~"$version"}[6h], 21600)` | query executed and returned data |
| [x] | PASS | panel | 📊 Week-over-Week Comparison | A | mimir | `consumption_cost:total{version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | 📊 Week-over-Week Comparison | B | mimir | `consumption_cost:total{version=~"$version"} offset 7d` | query executed and returned data |
| [x] | PASS | panel | 📊 Month-over-Month Comparison | A | mimir | `consumption_cost:total{version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | 📊 Month-over-Month Comparison | B | mimir | `consumption_cost:total{version=~"$version"} offset 30d` | query executed and returned data |
| [ ] | EMPTY | panel | 🚨 Anomaly Indicator | A | mimir | `consumption_cost:anomaly{version=~"$version"}` | query executed successfully but returned no data |
| [x] | PASS | panel | 📊 Z-Score (Anomaly Detection) | A | mimir | `consumption_cost:zscore{version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | ⚠️ Standard Deviation | A | mimir | `consumption_cost:stddev_1h{version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | 🔍 Outlier Detection (2σ Bounds) | A | mimir | `consumption_cost:total{version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | 🔍 Outlier Detection (2σ Bounds) | B | mimir | `consumption_cost:avg_1h{version=~"$version"} + (2 * consumption_cost:stddev_1h{version=~"$version"})` | query executed and returned data |
| [x] | PASS | panel | 🔍 Outlier Detection (2σ Bounds) | C | mimir | `consumption_cost:avg_1h{version=~"$version"} - (2 * consumption_cost:stddev_1h{version=~"$version"})` | query executed and returned data |
| [x] | PASS | panel | 🌡️ Cost by Hour of Day | A | mimir | `avg_over_time(consumption_cost:total{version=~"$version"}[1h])` | query executed and returned data |
| [x] | PASS | panel | 📅 Cost by Day of Week | A | mimir | `avg_over_time(consumption_cost:total{version=~"$version"}[1d])` | query executed and returned data |
| [x] | PASS | panel | 🌊 Weekly Pattern Overlay | A | mimir | `consumption_cost:total{version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | 🌊 Weekly Pattern Overlay | B | mimir | `consumption_cost:total{version=~"$version"} offset 7d` | query executed and returned data |
| [x] | PASS | panel | 🌊 Weekly Pattern Overlay | C | mimir | `consumption_cost:total{version=~"$version"} offset 14d` | query executed and returned data |
| [x] | PASS | panel | 🌊 Weekly Pattern Overlay | D | mimir | `consumption_cost:total{version=~"$version"} offset 21d` | query executed and returned data |
| [x] | PASS | panel | 📊 Monthly Pattern | A | mimir | `avg_over_time(consumption_cost:total{version=~"$version"}[30d])` | query executed and returned data |
| [x] | PASS | panel | 🔮 Next Hour Prediction | A | mimir | `predict_linear(consumption_cost:avg_1h{version=~"$version"}[1h], 3600)` | query executed and returned data |
| [x] | PASS | panel | 🔮 Next Day Prediction | A | mimir | `predict_linear(consumption_cost:avg_24h{version=~"$version"}[24h], 86400)` | query executed and returned data |
| [x] | PASS | panel | 🔮 End of Month Projection | A | mimir | `consumption_cost:projected_month{version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | 📈 Confidence Interval (±2σ) | A | mimir | `2 * consumption_cost:stddev_1h{version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | 📊 Power Derivative (Rate of Change) | A | mimir | `current_consumption:total{version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | 📊 Power Derivative (Rate of Change) | B | mimir | `deriv(current_consumption:total{version=~"$version"}[5m])` | query executed and returned data |
| [x] | PASS | panel | 📊 Cost History Table | A | mimir | `sum_over_time(consumption_cost:total{version=~"$version"}[24h])` | query executed and returned data |
| [x] | PASS | panel | 📈 YTD Cost Trend | A | mimir | `sum_over_time(consumption_cost:total{version=~"$version"}[1d])` | query executed and returned data |
| [x] | PASS | panel | 🏆 Record: Highest Day | A | mimir | `max_over_time(sum_over_time(consumption_cost:total{version=~"$version"}[1d])[30d:1d])` | query executed and returned data |
| [x] | PASS | panel | 🏅 Record: Lowest Day | A | mimir | `min_over_time(sum_over_time(consumption_cost:total{version=~"$version"}[1d])[30d:1d])` | query executed and returned data |
| [x] | PASS | panel | 🏆 Record: Highest Week | A | mimir | `max_over_time(sum_over_time(consumption_cost:total{version=~"$version"}[7d])[30d:7d])` | query executed and returned data |
| [x] | PASS | panel | 🏆 Record: Highest Month | A | mimir | `max_over_time(sum_over_time(consumption_cost:total{version=~"$version"}[30d])[365d:30d])` | query executed and returned data |

### 🚨 Alerts & Thresholds (`kasa-alerts-v2`)

Folder: Kasa · Panels: 31 · Queries: 45

| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |
|---|---|---|---|---|---|---|---|
| [x] | PASS | variable | Variable: version | version | ${DS_PROMETHEUS} | `label_values(current_consumption, version)` | query executed and returned data |
| [x] | PASS | panel | ⚡ Power Alert Status | A | prometheus | `current_consumption:total{version=~"$version"} > bool $power_alert_threshold` | query executed and returned data |
| [x] | PASS | panel | 📈 Power vs Threshold | A | prometheus | `current_consumption:total{version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | 📈 Power vs Threshold | B | prometheus | `vector($power_alert_threshold)` | query executed and returned data |
| [x] | PASS | panel | 🔥 Peak Power Alert (% of Threshold) | A | prometheus | `max_over_time(current_consumption:total{version=~"$version"}[1h]) / $power_alert_threshold` | query executed and returned data |
| [ ] | EMPTY | panel | 📊 Power Threshold Breaches | A | prometheus | `current_consumption:total{version=~"$version"} > $power_alert_threshold` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | 🔍 Anomaly Detection | A | prometheus | `consumption_cost:anomaly{version=~"$version"}` | query executed successfully but returned no data |
| [x] | PASS | panel | 📊 Z-Score Monitor | A | prometheus | `consumption_cost:zscore{version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | 📈 Anomaly Timeline | A | prometheus | `consumption_cost:total{version=~"$version"}` | query executed and returned data |
| [ ] | EMPTY | panel | 📈 Anomaly Timeline | B | prometheus | `consumption_cost:anomaly{version=~"$version"} * consumption_cost:total{version=~"$version"}` | query executed successfully but returned no data |
| [ ] | FAIL | panel | 🚨 Anomaly Count (Time Range) | A | prometheus | `count_over_time((consumption_cost:anomaly{version=~"$version"} == 1)[$__range])` | command failed (1): kubectl -n monitoring exec deploy/grafana-deployment -- wget --timeout=45 -qO- http://mimir-gateway.monitoring.svc/prometheus/api/v1/query?query=count_over_time%28%28consumption_cost%3Aanomaly%7Bversion%3D~%22.%2A%22%7D%20%3D%3D%201%29%5B6h%5D%29 wget: server returned error: HTTP/1.1 400 Bad Request command terminated with exit code 1  |
| [ ] | EMPTY | panel | ⚡ Current Rate Class | A | prometheus | `rate_class{version=~"$version"}` | query executed successfully but returned no data |
| [x] | PASS | panel | ⏰ Time to Next Rate Change | A | prometheus | `# Placeholder - calculate seconds to next TOU boundary # This would require custom recording rules based on your TOU schedule vector(1800)` | query executed and returned data |
| [ ] | FAIL | panel | 🚨 Active Alerts | A | prometheus | `(   count(current_consumption:total{version=~"$version"} > $power_alert_threshold) or vector(0) ) + (   count(consumption_cost:total{version=~"$version"} > $cost_alert_threshold) or vector(0) ) + (   count(consumption_cost:anomaly{version=~"$version"} == 1) or vector(0) ) + (   count(rate_class{version=~"$version"} == "on_peak") or vector(0) ) + (   count(state{version=~"$version"} != 1) or vector(0) )` | command failed (1): kubectl -n monitoring exec deploy/grafana-deployment -- wget --timeout=45 -qO- http://mimir-gateway.monitoring.svc/prometheus/api/v1/query?query=%28%0A%20%20count%28current_consumption%3Atotal%7Bversion%3D~%22.%2A%22%7D%20%3E%20500%29%20or%20vector%280%29%0A%29%20%2B%20%28%0A%20%20count%28consumption_cost%3Atotal%7Bversion%3D~%22.%2A%22%7D%20%3E%201.0%29%20or%20vector%280%29%0A%29%20%2B%20%28%0A%20%20count%28consumption_cost%3Aanomaly%7Bversion%3D~%22.%2A%22%7D%20%3D%3D%201%29%20or%20vector%280%29%0A%29%20%2B%20%28%0A%20%20count%28rate_class%7Bversion%3D~%22.%2A%22%7D%20%3D%3D%20%22on_peak%22%29%20or%20vector%280%29%0A%29%20%2B%20%28%0A%20%20count%28state%7Bversion%3D~%22.%2A%22%7D%20%21%3D%201%29%20or%20vector%280%29%0A%29 wget: server returned error: HTTP/1.1 400 Bad Request command terminated with exit code 1  |
| [ ] | EMPTY | panel | 🔔 High Rate Alert | A | prometheus | `rate_class{version=~"$version"} == bool 2` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | 📊 Rate Class Timeline | A | prometheus | `rate_class{version=~"$version"}` | query executed successfully but returned no data |
| [x] | PASS | panel | 📊 Device Alert Table | A | prometheus | `state{version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | 📊 Device Alert Table | B | prometheus | `current_consumption{version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | 📊 Device Alert Table | C | prometheus | `rssi{version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | 🚨 Device Alerts Summary | A | prometheus | `count(state{version=~"$version"} == 0) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | 🚨 Device Alerts Summary | B | prometheus | `count(rssi{version=~"$version"} < -70) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | 🚨 Device Alerts Summary | C | prometheus | `count(current_consumption{version=~"$version"} > $power_alert_threshold) or vector(0)` | query executed and returned data |
| [x] | PASS | panel | 💰 Projected Monthly Cost | A | prometheus | `# Projected monthly cost based on current daily average sum_over_time(consumption_cost:total{version=~"$version"}[24h]) / 24 * 730` | query executed and returned data |
| [x] | PASS | panel | 📈 Budget Utilization | A | prometheus | `# Budget utilization (assuming $100 monthly budget) (sum_over_time(consumption_cost:total{version=~"$version"}[30d]) / 100) * 100` | query executed and returned data |
| [x] | PASS | panel | 🚨 Days Until Budget Exceeded | A | prometheus | `# Days until budget breach (assuming $100 monthly budget) (100 - sum_over_time(consumption_cost:total{version=~"$version"}[30d])) / (sum_over_time(consumption_cost:total{version=~"$version"}[24h]) / 24 / 3600)` | query executed and returned data |
| [x] | PASS | panel | 📊 Budget Timeline (30d) | A | prometheus | `sum_over_time(consumption_cost:total{version=~"$version"}[30d])` | query executed and returned data |
| [x] | PASS | panel | 📊 Budget Timeline (30d) | B | prometheus | `vector(100)` | query executed and returned data |
| [ ] | EMPTY | panel | 📜 Alert Log | A | prometheus | `current_consumption:total{version=~"$version"} > $power_alert_threshold` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | 📜 Alert Log | B | prometheus | `consumption_cost:total{version=~"$version"} > $cost_alert_threshold` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | 📜 Alert Log | C | prometheus | `consumption_cost:anomaly{version=~"$version"} == 1` | query executed successfully but returned no data |
| [x] | PASS | panel | 📊 Alert Frequency | A | prometheus | `count_over_time((current_consumption:total{version=~"$version"} > bool $power_alert_threshold)[7d:])` | query executed and returned data |
| [x] | PASS | panel | 📊 Alert Frequency | B | prometheus | `count_over_time((consumption_cost:anomaly{version=~"$version"} == bool 1)[7d:])` | query executed and returned data |
| [x] | PASS | panel | 📊 Alert Frequency | C | prometheus | `count_over_time((state{version=~"$version"} == bool 0)[7d:])` | query executed and returned data |
| [x] | PASS | panel | ⚠️ Warnings | A | prometheus | `(   count(current_consumption:total{version=~"$version"} > ($power_alert_threshold * 0.8)) or vector(0) ) + (   count(consumption_cost:total{version=~"$version"} > ($cost_alert_threshold * 0.8)) or vector(0) ) + (   count(rssi{version=~"$version"} < -70) or vector(0) )` | query executed and returned data |
| [x] | PASS | panel | 📈 Alert Trend (Hourly) | A | prometheus | `count_over_time((current_consumption:total{version=~"$version"} > bool $power_alert_threshold)[1h:])` | query executed and returned data |
| [x] | PASS | panel | 📈 Alert Trend (Hourly) | B | prometheus | `count_over_time((consumption_cost:total{version=~"$version"} > bool $cost_alert_threshold)[1h:])` | query executed and returned data |
| [ ] | EMPTY | panel | 📈 Alert Trend (Hourly) | C | prometheus | `count_over_time((consumption_cost:anomaly{version=~"$version"} == bool 1)[1h:])` | query executed successfully but returned no data |
| [ ] | EMPTY | panel | 🎯 Most Problematic Device | A | prometheus | `topk(1,    sum by (alias) (     count_over_time((current_consumption{version=~"$version"} > $power_alert_threshold)[7d:])   ) )` | query executed successfully but returned no data |
| [x] | PASS | panel | ✅ System Status | A | prometheus | `clamp_max(   (     count(current_consumption:total{version=~"$version"} > $power_alert_threshold) or vector(0)   ) + (     count(consumption_cost:total{version=~"$version"} > $cost_alert_threshold) or vector(0)   ) + (     count(consumption_cost:anomaly{version=~"$version"} == 1) or vector(0)   ),   1 )` | query executed and returned data |
| [ ] | FAIL | panel | 🔔 Last Alert Time | A | prometheus | `time() - max(   max_over_time((current_consumption:total{version=~"$version"} > $power_alert_threshold)[1h:]) > bool $power_alert_threshold   * on() group_left() timestamp(current_consumption:total{version=~"$version"}) ) or time() - 86400` | command failed (1): kubectl -n monitoring exec deploy/grafana-deployment -- wget --timeout=45 -qO- http://mimir-gateway.monitoring.svc/prometheus/api/v1/query?query=time%28%29%20-%20max%28%0A%20%20max_over_time%28%28current_consumption%3Atotal%7Bversion%3D~%22.%2A%22%7D%20%3E%20500%29%5B1h%3A%5D%29%20%3E%20bool%20500%0A%20%20%2A%20on%28%29%20group_left%28%29%20timestamp%28current_consumption%3Atotal%7Bversion%3D~%22.%2A%22%7D%29%0A%29%20or%20time%28%29%20-%2086400 wget: server returned error: HTTP/1.1 400 Bad Request command terminated with exit code 1  |
| [x] | PASS | panel | 💰 Cost Alert Status | A | prometheus | `consumption_cost:total{version=~"$version"} > bool $cost_alert_threshold` | query executed and returned data |
| [x] | PASS | panel | 📈 Cost vs Threshold | A | prometheus | `consumption_cost:total{version=~"$version"}` | query executed and returned data |
| [x] | PASS | panel | 📈 Cost vs Threshold | B | prometheus | `vector($cost_alert_threshold)` | query executed and returned data |
| [ ] | EMPTY | panel | 🚨 Cost Spike Detection | A | prometheus | `consumption_cost:anomaly{version=~"$version"}` | query executed successfully but returned no data |
| [x] | PASS | panel | 📊 Cost Threshold History | A | prometheus | `consumption_cost:total{version=~"$version"} > bool $cost_alert_threshold` | query executed and returned data |
