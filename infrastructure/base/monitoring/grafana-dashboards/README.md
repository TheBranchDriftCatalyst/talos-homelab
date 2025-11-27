# Grafana Dashboards

## Auto-Import Script

### Option 1: Direct access (requires /etc/hosts entry for Grafana.talos00)

```bash
./scripts/import-grafana-dashboards.sh
```

### Option 2: Via kubectl port-forward

```bash
# Terminal 1: Port-forward Grafana
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80

# Terminal 2: Run import script
GRAFANA_URL=http://localhost:3000 ./scripts/import-grafana-dashboards.sh
```

## Manual Import

If you prefer to import manually:

1. Access Grafana: `http://grafana.talos00`
2. Navigate to Dashboards → Import
3. Enter dashboard ID and select Prometheus datasource
4. Click Import

## Recommended Dashboards

- **315** - Kubernetes Cluster Monitoring
- **17347** - Traefik Official Kubernetes Dashboard
- **1860** - Node Exporter Full
- **9628** - PostgreSQL Database
