# Grafana Dashboards Index

Complete reference for all Grafana dashboards available in the homelab cluster.

## Quick Import

```bash
# Import all dashboards via script
./scripts/import-grafana-dashboards.sh

# Or import a single dashboard by ID
./scripts/provision-grafana-dashboard.sh <dashboard-id>
```

## Dashboard Categories

### Core Kubernetes Dashboards

| ID    | Name                           | Status | Description                                                    |
| ----- | ------------------------------ | ------ | -------------------------------------------------------------- |
| 315   | Kubernetes Cluster Monitoring  | Active | Classic cluster overview with node, pod, and container metrics |
| 15661 | K8S Dashboard (2025)           | Active | Comprehensive Kubernetes resources overview                    |
| 15760 | Kubernetes / Views / Pods      | Active | Detailed pod-level metrics and resource usage                  |
| 14623 | Kubernetes Monitoring Overview | Active | High-level cluster health with gauges and graphs               |
| 13646 | Kubernetes PVC Dashboard       | Active | Persistent Volume Claim monitoring                             |
| 11454 | Kubernetes Volumes Dashboard   | Active | Volume usage and capacity tracking                             |

**Data Sources Required:**

- kube-state-metrics (included in kube-prometheus-stack)
- prometheus-node-exporter (included in kube-prometheus-stack)
- kubelet metrics (enabled by default)

### Infrastructure Dashboards

| ID   | Name                | Status  | Description                                                   |
| ---- | ------------------- | ------- | ------------------------------------------------------------- |
| 1860 | Node Exporter Full  | Active  | Comprehensive node-level metrics (CPU, memory, disk, network) |
| 9628 | PostgreSQL Database | Planned | PostgreSQL monitoring (requires postgres-exporter)            |

**Data Sources Required:**

- prometheus-node-exporter
- postgres-exporter (for PostgreSQL dashboard)

### Traefik Ingress Dashboards

| ID    | Name                        | Status | Data Source         |
| ----- | --------------------------- | ------ | ------------------- |
| 17347 | Traefik Official Kubernetes | Active | traefik-metrics job |
| 4475  | Traefik v2                  | Active | Alternative view    |

**Data Sources Required:**

- Traefik ServiceMonitor (auto-created by Helm chart)
- Metrics exposed on port 9100

**Verification:**

```bash
# Check Traefik metrics are being scraped
kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=traefik_config_reloads_total'
```

### ArgoCD GitOps Dashboards

| ID    | Name                            | Status      | Description                                   |
| ----- | ------------------------------- | ----------- | --------------------------------------------- |
| -     | ArgoCD                          | Provisioned | Main ArgoCD overview (included in Helm chart) |
| -     | ArgoCD / Application / Overview | Provisioned | Application sync status                       |
| -     | ArgoCD / Operational / Overview | Provisioned | Operational metrics                           |
| 14584 | ArgoCD Application Overview     | Alternative | Community dashboard                           |
| 19993 | ArgoCD Operational Dashboard    | Alternative | Community dashboard                           |

**Data Sources Required:**

- argocd-server-metrics ServiceMonitor (port 8083)
- argocd-application-controller-metrics ServiceMonitor (port 8082)
- argocd-repo-server-metrics ServiceMonitor (port 8084)

### Liqo Multi-Cluster Dashboards

| ID  | Name         | Status  | Description                          |
| --- | ------------ | ------- | ------------------------------------ |
| -   | Liqo Network | Planned | Cross-cluster throughput and latency |

**Prerequisites:**

1. Liqo installed with `--enable-metrics` flag
2. ServiceMonitor/PodMonitor resources created by Liqo

**Metrics Available:**

- `liqo_peer_receive_bytes_total` - Bytes received from remote cluster
- `liqo_peer_transmit_bytes_total` - Bytes transmitted to remote cluster
- `liqo_peer_latency_us` - RTT latency in microseconds
- `liqo_peer_is_connected` - Connection status boolean

### Nebula VPN Dashboards

| ID  | Name   | Status  | Description            |
| --- | ------ | ------- | ---------------------- |
| -   | Custom | Planned | Nebula mesh monitoring |

**Prerequisites:**
Configure Nebula with Prometheus metrics:

```yaml
stats:
  type: prometheus
  listen: 0.0.0.0:9100
  path: /metrics
```

Then create a ServiceMonitor targeting the metrics endpoint.

### Observability Stack Dashboards

| ID  | Name       | Status   | Description                      |
| --- | ---------- | -------- | -------------------------------- |
| -   | OpenSearch | Built-in | Comes with kube-prometheus-stack |
| -   | Graylog    | Built-in | Graylog System Dashboard         |
| -   | MongoDB    | Built-in | MongoDB metrics                  |

## Current Prometheus Scrape Jobs

These are the metrics sources currently being scraped:

| Job Name                              | Namespace        | Status | Notes                       |
| ------------------------------------- | ---------------- | ------ | --------------------------- |
| apiserver                             | kube-system      | Active | Kubernetes API server       |
| argocd-server-metrics                 | argocd           | Active | ArgoCD server metrics       |
| argocd-application-controller-metrics | argocd           | Active | ArgoCD app controller       |
| argocd-repo-server-metrics            | argocd           | Active | ArgoCD repo server          |
| coredns                               | kube-system      | Active | DNS metrics                 |
| external-secrets-\*                   | external-secrets | Active | ESO metrics                 |
| graylog                               | observability    | Down   | Log management (check pod)  |
| kube-controller-manager               | kube-system      | Down   | Talos doesn't expose this   |
| kube-proxy                            | kube-system      | Down   | Talos doesn't expose this   |
| kube-scheduler                        | kube-system      | Down   | Talos doesn't expose this   |
| kube-state-metrics                    | monitoring       | Active | K8s resource states         |
| kubelet                               | \*               | Active | Container metrics           |
| mongodb                               | observability    | Down   | Graylog backend (check pod) |
| node-exporter                         | monitoring       | Active | Node metrics                |
| opensearch                            | observability    | Down   | Search/logging (check pod)  |
| prometheus-blackbox-exporter          | monitoring       | Active | Endpoint probing            |
| traefik-metrics                       | traefik          | Active | Ingress metrics             |

**Note:** `kube-controller-manager`, `kube-proxy`, and `kube-scheduler` are down because Talos Linux runs these as static pods that don't expose metrics externally. This is expected behavior.

### Verify Scrape Targets

```bash
# List all Prometheus jobs
kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -- \
  wget -qO- 'http://localhost:9090/api/v1/targets' | \
  python3 -c "import sys,json; data=json.load(sys.stdin); \
    jobs=set(t['labels'].get('job','') for t in data.get('data',{}).get('activeTargets',[])); \
    print('\n'.join(sorted(jobs)))"
```

## Dashboard Troubleshooting

### Dashboard Shows "No Data"

1. **Check if metrics exist:**

   ```bash
   # Query Prometheus for a metric
   kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -- \
     wget -qO- 'http://localhost:9090/api/v1/query?query=<metric_name>'
   ```

2. **Check ServiceMonitor:**

   ```bash
   kubectl get servicemonitor -A
   ```

3. **Check Prometheus targets:**

   ```bash
   # Access Prometheus UI
   kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090
   # Open http://localhost:9090/targets
   ```

4. **Verify job label matches:**
   - Some dashboards expect specific job labels
   - Edit dashboard variables to match your job names

### Common Issues

| Issue                   | Solution                                                   |
| ----------------------- | ---------------------------------------------------------- |
| Traefik metrics missing | Check `traefik-metrics` service exists with correct labels |
| Pod metrics not working | Ensure kubelet ServiceMonitor is active                    |
| Node metrics gaps       | Check node-exporter DaemonSet                              |

## Adding Custom Dashboards

### Via ConfigMap (Recommended for GitOps)

Create a ConfigMap with the `grafana_dashboard: "1"` label:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: my-custom-dashboard
  namespace: monitoring
  labels:
    grafana_dashboard: '1'
  annotations:
    grafana_folder: 'Custom'
data:
  my-dashboard.json: |
    {
      "dashboard": { ... },
      "overwrite": true
    }
```

### Via API

```bash
# Download dashboard JSON
curl -s "https://grafana.com/api/dashboards/<ID>/revisions/latest/download" > dashboard.json

# Import via API
curl -X POST \
  -H "Content-Type: application/json" \
  -u admin:admin \
  -d @dashboard.json \
  http://grafana.talos00/api/dashboards/import
```

## ServiceMonitor Reference

### Creating a New ServiceMonitor

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: my-app
  namespace: monitoring # Must be in monitoring namespace
  labels:
    prometheus: kube-prometheus # Optional but helpful
spec:
  namespaceSelector:
    matchNames:
      - my-app-namespace
  selector:
    matchLabels:
      app: my-app
  endpoints:
    - port: metrics
      interval: 30s
      path: /metrics
```

### Creating a PodMonitor (for sidecars)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: my-sidecar
  namespace: monitoring
spec:
  namespaceSelector:
    any: true
  selector:
    matchLabels:
      my-sidecar: enabled
  podMetricsEndpoints:
    - port: metrics
      interval: 30s
```

## Related Documentation

- [Observability Stack](../OBSERVABILITY.md) - Full monitoring architecture
- [Traefik Configuration](../TRAEFIK.md) - Ingress setup
- [Deploy Stack Script](../scripts/deploy-stack.sh) - Infrastructure deployment

## External Resources

- [Grafana Dashboards](https://grafana.com/grafana/dashboards/)
- [Prometheus Operator](https://prometheus-operator.dev/)
- [Liqo Metrics](https://docs.liqo.io/en/stable/usage/prometheus-metrics.html)
- [Nebula Monitoring](https://deepwiki.com/slackhq/nebula/6.2-monitoring-and-metrics)
