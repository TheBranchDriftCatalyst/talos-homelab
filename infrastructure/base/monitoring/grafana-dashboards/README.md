# Grafana Dashboards

## TL;DR

Grafana dashboards are managed as **GrafanaDashboard CRDs** via the grafana-operator with **bidirectional sync** - edit in Grafana UI or code, changes sync both ways.

**Key Facts:**

- **Deployment:** `kubectl apply -k infrastructure/base/monitoring/grafana-dashboards/`
- **Access:** http://grafana.talos00
- **Tilt:** Buttons in `3-infra-observe` group for pull/push/list

## Development Workflow (Bidirectional Sync)

Edit dashboards in **Grafana UI** or **JSON files** - your choice. Changes sync both ways.

### Directory Structure

```
grafana-dashboards/
├── json/                    # Editable JSON files (custom dashboards)
│   ├── tdarr-transcoding.json
│   ├── vpn-gateway.json
│   └── ...
├── resources/               # GrafanaDashboard CRs (reference ConfigMaps)
├── external/                # Community dashboards (Grafana.com IDs)
├── scripts/
│   └── extract-dashboards.py
└── kustomization.yaml       # ConfigMapGenerator for JSON files
```

### Option A: Edit in Grafana UI

```bash
# 1. Make changes in Grafana UI at http://grafana.talos00
# 2. Export changes to JSON files

# 3. Commit to git
git add json/ && git commit -m "Update dashboard from UI"
git push  # Flux applies automatically
```

### Option B: Edit JSON Directly

```bash
# 1. Edit json/tdarr-transcoding.json in VSCode/vim
# 2. Apply to cluster

# Or just commit - Flux applies automatically
git add json/ && git commit -m "Update dashboard"
git push
```

### Sync Commands

```bash
```

### Tilt Integration

Run `tilt up` and find **grafana-dashboards** in the `3-infra-observe` group:

| Button | Action |
|--------|--------|
| **Pull from Grafana** | Export UI changes to JSON files |
| **Push to Cluster** | Apply JSON files via kustomize |
| **List Dashboards** | Show all dashboards in Grafana |

### How It Works

1. **JSON files** in `json/` are standalone dashboard definitions
2. **Kustomize configMapGenerator** creates ConfigMaps from JSON files
3. **GrafanaDashboard CRs** in `resources/` reference ConfigMaps via `configMapRef`
4. **Grafana Operator** syncs ConfigMap content to Grafana instance
5. **Flux** watches git and applies changes automatically

Benefits:
- Clean git diffs (JSON files vs embedded YAML strings)
- Edit in Grafana UI when visual editing is easier
- Edit in code when bulk changes or version control is needed
- No more losing UI changes to GitOps overwrites

## Quick Reference

### Access Grafana

```bash
# Via IngressRoute (add to /etc/hosts)
echo "192.168.1.54 grafana.talos00" >> /etc/hosts
open http://grafana.talos00

# Default credentials
# Username: admin
# Password: prom-operator

# Or port-forward
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80
open http://localhost:3000
```

### View Deployed Dashboards

```bash
# List all GrafanaDashboard CRDs
kubectl get grafanadashboard -n monitoring

# Check dashboard sync status
kubectl get grafanadashboard -n monitoring -o wide

# Describe specific dashboard
kubectl describe grafanadashboard -n monitoring cilium-agent
```

## Dashboard Inventory

### Cilium CNI & Hubble

The current cluster is covered by the custom Network Ops and Cilium BPF Map
Pressure dashboards. Retired legacy imports: cilium-agent (16611),
cilium-operator (16612), cilium-hubble (16613), cilium-policy-verdicts (18015),
and cilium-hubble-flows (23862). The 23862 import
requires a `hubble-observer` log container that is not part of this deployment.
They are replaced by the custom "Network Ops — Cilium & Hubble" dashboard
(`json/network-ops.json`) and cilium-bpf-pressure in Ops/Network.

### Kubernetes Core

`kubernetes-dashboards.yaml` was removed entirely (Legacy cleanup). Its last two
entries — k8s-pvc (13646) and k8s-volumes (11454) — are replaced by the custom
"Central Cluster Storage" dashboard (`json/central-cluster-storage.json`) in
Ops/Storage. Earlier entries (315, 15661, 15760, 14623) were removed before that;
cluster health lives in the custom "Catalyst K8s — Full System Ops" dashboard.

### Infrastructure (2 dashboards)

| Dashboard           | File                           | Grafana.com ID | Description                                        |
| ------------------- | ------------------------------ | -------------- | -------------------------------------------------- |
| node-exporter-full  | infrastructure-dashboards.yaml | 1860           | Node hardware metrics (CPU, memory, disk, network) |
| postgresql-database | infrastructure-dashboards.yaml | 9628           | PostgreSQL database metrics                        |

### Traefik Ingress

`traefik-dashboards.yaml` was removed entirely (Legacy cleanup). Its entries —
traefik-v2-alt (4475, "Traefik") and traefik-services (12250, "Traefik 2.2") —
are replaced by the custom "Traefik Ops" dashboard (`json/traefik-ops.json`)
in Ops/Network.

### GitOps & ArgoCD (2 dashboards)

Retired: `flux-control-plane` (Grafana.com 19761). That ID currently resolves
to the unrelated "Ping Exporter" dashboard, not a Flux control-plane dashboard.
Flux telemetry remains covered by the custom Flux Ops dashboard.

Retired after live query validation: `flux-cluster-stats` (Grafana.com 16714)
expects the obsolete `kind` label, while current kube-state-metrics telemetry
uses `customresource_kind`. The custom Flux Ops dashboard is the supported Flux
view. `argocd-overview` (Grafana.com 14584) is also retired because its fixed
scrape-job names no longer match the deployed ArgoCD services; Argo Ops plus the
Application and Operational dashboards provide the current coverage.

| Dashboard            | File                   | Grafana.com ID | Description                                   |
| -------------------- | ---------------------- | -------------- | --------------------------------------------- |
| argocd-notifications | argocd-dashboards.yaml | 19975          | ArgoCD notification delivery status           |
| goldilocks-vpa       | gitops-dashboards.yaml | Custom         | VPA recommendations for resource optimization |

### Observability Stack (3 dashboards)

| Dashboard                | File                          | Grafana.com ID | Description                               |
| ------------------------ | ----------------------------- | -------------- | ----------------------------------------- |
| graylog-metrics          | observability-dashboards.yaml | 12642          | Graylog log ingestion, processing metrics |
| mongodb-cluster-summary  | observability-dashboards.yaml | 2583           | MongoDB cluster health (Graylog backend)  |
| mongodb-instance-summary | observability-dashboards.yaml | 2584           | MongoDB instance-level metrics            |
| opensearch-exporter      | observability-dashboards.yaml | 14086          | OpenSearch cluster metrics                |

### Hybrid Cluster (3 dashboards)

| Dashboard               | File                           | Grafana.com ID | Description                           |
| ----------------------- | ------------------------------ | -------------- | ------------------------------------- |
| hybrid-cluster-overview | hybrid-cluster-dashboards.yaml | Custom         | Multi-cluster overview (Liqo peering) |
| aws-ec2-instances       | hybrid-cluster-dashboards.yaml | 15310          | AWS EC2 instance monitoring           |

### Custom Application Dashboards (8 dashboards)

| Dashboard                  | File                          | Grafana.com ID | Description                               |
| -------------------------- | ----------------------------- | -------------- | ----------------------------------------- |
| llm-scaler                 | llm-scaler-dashboard.yaml     | Custom         | LLM workload scale-to-zero monitoring     |
| kasa-real-time-monitoring  | observability-dashboards.yaml | Custom         | Kasa smart plug real-time metrics         |
| kasa-alerts-monitoring     | observability-dashboards.yaml | Custom         | Kasa alert and anomaly detection          |
| kasa-battery-sizing        | observability-dashboards.yaml | Custom         | Battery sizing calculations               |
| kasa-comparative-analytics | observability-dashboards.yaml | Custom         | Multi-device comparison                   |
| kasa-forecasting-analytics | observability-dashboards.yaml | Custom         | Power usage forecasting                   |
| kasa-tou-cost-optimization | observability-dashboards.yaml | Custom         | Time-of-use cost optimization             |
| pod-cleanup                | pod-cleanup.yaml              | Custom         | Pod eviction and cleanup monitoring       |
| resource-efficiency        | resource-efficiency.yaml      | Custom         | Cluster-wide resource efficiency analysis |

## Adding a New Dashboard

### Method 1: Create in Grafana UI (Recommended for Custom Dashboards)

The easiest way to create custom dashboards with full visual editing:

```bash
# 1. Create dashboard in Grafana UI at http://grafana.talos00
#    - Use the visual editor, add panels, configure queries
#    - Save the dashboard (give it a meaningful UID)

# 2. Export to JSON file

# 3. Create GrafanaDashboard CR in resources/
cat > resources/my-dashboard.yaml <<EOF
---
apiVersion: grafana.integreatly.org/v1beta1
kind: GrafanaDashboard
metadata:
  name: my-dashboard
  namespace: monitoring
spec:
  instanceSelector:
    matchLabels:
      dashboards: grafana
  configMapRef:
    name: dashboard-my-dashboard
    key: my-dashboard.json
  folder: Custom
EOF

# 4. Add to kustomization.yaml
#    - Add configMapGenerator entry for the JSON file
#    - Add resource entry for the CR

# 5. Commit and push
git add json/ resources/ kustomization.yaml
git commit -m "Add my-dashboard"
git push
```

### Method 2: From Grafana.com (Community Dashboards)

For dashboards from the Grafana community gallery:

```yaml
# Add to external/<category>-dashboards.yaml
---
apiVersion: grafana.integreatly.org/v1beta1
kind: GrafanaDashboard
metadata:
  name: my-dashboard
  namespace: monitoring
  labels:
    app.kubernetes.io/component: dashboard
    dashboard-category: custom
spec:
  instanceSelector:
    matchLabels:
      dashboards: 'grafana'
  grafanaCom:
    id: 12345  # Dashboard ID from grafana.com URL
  datasources:
    - inputName: 'DS_PROMETHEUS'
      datasourceName: 'Mimir'
```

**Steps:**

1. Find dashboard on https://grafana.com/grafana/dashboards/
2. Copy the dashboard ID from the URL
3. Add to appropriate file in `external/`
4. Add resource to `kustomization.yaml`
5. Apply: `kubectl apply -k .` or `git push`

### Method 3: JSON File Directly (For Programmatic Dashboards)

When generating dashboards from code (Grafonnet, grafanalib, etc.):

```bash
# 1. Generate/write JSON to json/my-dashboard.json

# 2. Create GrafanaDashboard CR in resources/my-dashboard.yaml
#    (same as Method 1, step 3)

# 3. Update kustomization.yaml:
#    configMapGenerator:
#      - name: dashboard-my-dashboard
#        files:
#          - json/my-dashboard.json
#    resources:
#      - resources/my-dashboard.yaml

# 4. Apply
```

### Dashboard Organization Best Practices

**File Naming:**

- Group related dashboards in a single file (e.g., `cilium-dashboards.yaml`)
- Use descriptive names: `<category>-dashboards.yaml`
- Custom dashboards: Use specific names (e.g., `llm-scaler-dashboard.yaml`)

**Label Standards:**

- `dashboard-category`: Use consistent categories (cilium, kubernetes, infrastructure, traefik, argocd, observability, hybrid-cluster, custom)
- `app.kubernetes.io/component: dashboard`: Required for all dashboards

**kustomization.yaml:**

- Add comments for each resource group
- Organize by category (see current file for reference)

## Troubleshooting

### Dashboard Shows "No Data"

**Diagnosis:**

```bash
# 1. Check if dashboard CRD is synced
kubectl get grafanadashboard -n monitoring <dashboard-name> -o yaml | grep -A5 status

# 2. Check ServiceMonitor exists (provides metrics to Prometheus)
kubectl get servicemonitor -A | grep <service>

# 3. Check Prometheus targets
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090
# Open http://localhost:9090/targets in browser

# 4. Query specific metric
curl "http://localhost:9090/api/v1/query?query=<metric_name>"

# 5. Check Prometheus jobs
kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -- \
  wget -qO- 'http://localhost:9090/api/v1/targets' | \
  python3 -c "import sys,json; d=json.load(sys.stdin); \
    print('\n'.join(sorted(set(t['labels'].get('job','') \
    for t in d.get('data',{}).get('activeTargets',[])))))"
```

**Common Causes:**

- ServiceMonitor not created for the service
- Metrics not exposed by the service
- Incorrect Prometheus datasource mapping
- Service not running or not labeled correctly

**Fix:**

1. Create ServiceMonitor for the service (see monitoring stack docs)
2. Verify service exposes metrics endpoint
3. Check datasource mapping in GrafanaDashboard spec
4. Ensure Prometheus is scraping the service

### Dashboard Not Appearing in Grafana

**Diagnosis:**

```bash
# Check GrafanaDashboard status
kubectl describe grafanadashboard -n monitoring <dashboard-name>

# Check grafana-operator logs
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana-operator --tail=50

# Verify instanceSelector matches Grafana instance
kubectl get grafana -n monitoring -o yaml | grep -A3 labels
```

**Common Causes:**

- `instanceSelector` doesn't match Grafana instance labels
- Grafana-operator not running
- Invalid JSON in dashboard spec
- Namespace mismatch

**Fix:**

1. Ensure `instanceSelector.matchLabels.dashboards: "grafana"` is set
2. Check grafana-operator deployment status
3. Validate dashboard JSON with a JSON linter
4. Ensure dashboard is in `monitoring` namespace

### Dashboard Shows Wrong Data or Errors

**Diagnosis:**

```bash
# Check datasource configuration
kubectl get grafanadatasource -n monitoring

# Test Prometheus query directly
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090
# Query: http://localhost:9090/graph?g0.expr=<your_query>

# Check Grafana logs
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana --tail=100
```

**Common Causes:**

- Datasource name mismatch (`DS_PROMETHEUS` vs actual datasource name)
- PromQL query errors
- Time range issues
- Variable configuration problems

**Fix:**

1. Verify datasource mapping in GrafanaDashboard spec
2. Test PromQL queries in Prometheus UI
3. Check dashboard variables configuration
4. Update `resyncPeriod` if dashboard needs frequent updates

### Dashboard Syncing Too Frequently

**Issue:** Dashboard updates constantly, causing performance issues.

**Fix:**

```yaml
spec:
  resyncPeriod: 30m # Increase from default 10m
```

### Deleting Dashboards

```bash
# Remove dashboard CRD
kubectl delete grafanadashboard -n monitoring <dashboard-name>

# Dashboard automatically removed from Grafana UI
# To preserve in Grafana but remove CRD: Export JSON first
```

## Deployment Workflow

### Initial Deployment

```bash
# Apply all dashboards
kubectl apply -k infrastructure/base/monitoring/grafana-dashboards/

# Wait for operator to sync (10-60 seconds)
kubectl get grafanadashboard -n monitoring

# Access Grafana
open http://grafana.talos00
```

### Adding New Dashboards

1. Create YAML file: `infrastructure/base/monitoring/grafana-dashboards/new-dashboard.yaml`
2. Add to `kustomization.yaml`: `- new-dashboard.yaml`
3. Apply: `kubectl apply -k infrastructure/base/monitoring/grafana-dashboards/`
4. Verify: `kubectl get grafanadashboard -n monitoring new-dashboard`
5. Check Grafana UI for new dashboard

### Updating Existing Dashboards

```bash
# Edit dashboard YAML
vim infrastructure/base/monitoring/grafana-dashboards/<dashboard-file>.yaml

# Apply changes
kubectl apply -k infrastructure/base/monitoring/grafana-dashboards/

# Force resync (if needed)
kubectl annotate grafanadashboard -n monitoring <dashboard-name> \
  grafana.integreatly.org/force-update="$(date +%s)"
```

### Stack Deployment

Dashboards are reconciled by Flux from `clusters/catalyst-cluster/monitoring.yaml`. Commit the
dashboard change and let Flux apply it, or force a sync:

```bash
task infra:flux-reconcile
```

The former `./scripts/deploy-observability.sh` and `./scripts/deploy-stack.sh` no longer exist.

## Related Documentation

- **Full Dashboard Reference:** [docs/GRAFANA-DASHBOARDS.md](/Users/panda/catalyst-devspace/workspace/talos-homelab/docs/GRAFANA-DASHBOARDS.md)
- **Monitoring Stack:** [infrastructure/base/monitoring/kube-prometheus-stack/README.md](/Users/panda/catalyst-devspace/workspace/talos-homelab/infrastructure/base/monitoring/kube-prometheus-stack/README.md)
- **Grafana Operator:** https://grafana.github.io/grafana-operator/
- **Dashboard Gallery:** https://grafana.com/grafana/dashboards/

---

## Related Issues

<!-- Beads tracking -->

- [CILIUM-01c] - Initial restructure with progressive summarization
