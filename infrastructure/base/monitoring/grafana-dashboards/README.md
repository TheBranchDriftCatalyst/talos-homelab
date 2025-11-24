# Grafana Dashboards

This directory contains Grafana dashboard ConfigMaps that are automatically discovered by the Grafana sidecar.

## Available Dashboards

### Kubernetes Monitoring
1. **Kubernetes Cluster Monitoring** (ID: 315)
   - Overall cluster CPU/Memory/Filesystem usage
   - Pod and container statistics
   - https://grafana.com/grafana/dashboards/315

2. **Kubernetes Monitoring** (ID: 12740)
   - Comprehensive Kubernetes monitoring
   - https://grafana.com/grafana/dashboards/12740

3. **dotdc Kubernetes Dashboards** (GitHub: dotdc/grafana-dashboards-kubernetes)
   - Modern set of Kubernetes dashboards
   - https://github.com/dotdc/grafana-dashboards-kubernetes

### Traefik Monitoring
1. **Traefik Official Kubernetes Dashboard** (ID: 17347)
   - Official Traefik dashboard for Kubernetes
   - https://grafana.com/grafana/dashboards/17347

2. **RT Traefik Kubernetes Dashboard** (ID: 18111)
   - Router Traefik monitoring
   - https://grafana.com/grafana/dashboards/18111

### Node/System Monitoring
1. **Node Exporter Full** (ID: 1860)
   - Comprehensive node metrics
   - https://grafana.com/grafana/dashboards/1860

### Application Monitoring
1. **PostgreSQL Database** (ID: 9628)
   - PostgreSQL metrics via postgres_exporter
   - https://grafana.com/grafana/dashboards/9628

## Manual Import

To import dashboards manually in Grafana:
1. Navigate to Dashboards → Import
2. Enter the dashboard ID from above
3. Select the Prometheus datasource
4. Click Import

## Automatic Import

Dashboards with the label `grafana_dashboard: "1"` are automatically discovered by Grafana's sidecar and imported on startup.
