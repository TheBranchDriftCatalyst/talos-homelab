# Grafana Dashboards

For complete dashboard documentation, see [docs/GRAFANA-DASHBOARDS.md](../../../docs/GRAFANA-DASHBOARDS.md).

## Quick Import

```bash
# Import all dashboards
./scripts/import-grafana-dashboards.sh

# Import single dashboard
./scripts/provision-grafana-dashboard.sh <dashboard-id>
```

## Available Dashboard Categories

| Category | Dashboards | Status |
|----------|------------|--------|
| Kubernetes Core | 315, 15661, 15760, 14623, 13646, 11454 | Active |
| Infrastructure | 1860, 9628 | Active |
| Traefik Ingress | 17347, 4475 | Active |
| Linkerd Service Mesh | 15474, 15475, 15481, 15484, 14274 | Requires linkerd-viz |
| Liqo Multi-Cluster | Custom | Planned |

## Current Prometheus Jobs

```bash
# List active scrape jobs
kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -- \
  wget -qO- 'http://localhost:9090/api/v1/targets' | \
  python3 -c "import sys,json; d=json.load(sys.stdin); \
    print('\n'.join(sorted(set(t['labels'].get('job','') \
    for t in d.get('data',{}).get('activeTargets',[])))))"
```

## Troubleshooting

If dashboards show "No Data":
1. Check ServiceMonitor exists: `kubectl get servicemonitor -A`
2. Check Prometheus targets: `kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090`
3. Query specific metric: `curl http://localhost:9090/api/v1/query?query=<metric>`

See full troubleshooting guide in [docs/GRAFANA-DASHBOARDS.md](../../../docs/GRAFANA-DASHBOARDS.md#dashboard-troubleshooting).
