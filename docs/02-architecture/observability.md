# Observability Stack

This document describes the complete observability stack for the Talos Kubernetes homelab, including monitoring (metrics) and logging infrastructure.

## Architecture Overview

The observability stack is split into two namespaces:

### `monitoring` namespace

- **Prometheus**: Metrics collection, storage, and alerting
- **Grafana**: Visualization and dashboards
- **Alertmanager**: Alert routing and management
- **Prometheus Operator**: Manages Prometheus instances using CRDs

### `observability` namespace

- **Graylog**: Centralized log management and analysis
- **MongoDB**: Graylog's metadata database
- **OpenSearch**: Log storage and search engine
- **Fluent Bit**: Log collection agent (DaemonSet on all nodes)

## Components

### Prometheus Stack (kube-Prometheus-stack)

**Deployment Method**: Helm chart from Prometheus-community

**Resources**:

- Prometheus: 50Gi storage, 30-day retention, 45GB size limit
- Grafana: 10Gi storage
- Alertmanager: 10Gi storage
- All using `local-path` storage class

**Configuration**: `infrastructure/base/monitoring/kube-prometheus-stack/values.yaml`

**Access**:

- Grafana: http://grafana.talos00 (admin / prom-operator)
- Prometheus: http://prometheus.talos00
- Alertmanager: http://alertmanager.talos00

**Features**:

- ServiceMonitor CRDs for automatic target discovery
- Monitors all namespaces by default
- Includes node-exporter, kube-state-metrics
- Pre-configured Grafana dashboards

### Graylog Stack

**Deployment Method**:

- MongoDB: Helm chart from Bitnami
- OpenSearch: Helm chart from opensearch-project
- Graylog: Native Kubernetes manifests

**Resources**:

- MongoDB: 20Gi storage, standalone architecture, no authentication
- OpenSearch: 30Gi storage, 1 replica, 512m heap
- Graylog: 20Gi storage, 1Gi-2Gi memory

**Configuration**:

- MongoDB values: `infrastructure/base/observability/mongodb/values.yaml`
- OpenSearch values: `infrastructure/base/observability/opensearch/values.yaml`
- Graylog manifests: `infrastructure/base/observability/graylog/deployment.yaml`

**Access**:

- Graylog: http://graylog.talos00 (admin / admin)

**Default Credentials**:

- Admin username: `admin`
- Admin password: `admin` (SHA2 hash stored in Secret)
- Password secret: 96-character random string (placeholder in repo)

**Ports**:

- 9000/TCP: Graylog web interface
- 12201/TCP: GELF input (for Fluent Bit)
- 12201/UDP: GELF input (alternative)

### Fluent Bit

**Deployment Method**: Helm chart from fluent

**Configuration**: `infrastructure/base/observability/fluent-bit/values.yaml`

**Functionality**:

- Runs as DaemonSet (one pod per node)
- Collects all container logs from `/var/log/containers/*.log`
- Enriches logs with Kubernetes metadata (pod, namespace, labels, etc.)
- Sends logs to Graylog via GELF TCP (port 12201)
- Adds cluster name tag: `talos-homelab`

**Resources**:

- Requests: 100m CPU, 128Mi memory
- Limits: 500m CPU, 512Mi memory

### Exportarr

**Deployment Method**: Native Kubernetes manifests

**Configuration**: `applications/arr-stack/base/exportarr/`

**Components**:

- Separate deployment for each \*arr app:
  - exportarr-prowlarr (port 9707)
  - exportarr-sonarr (port 9707)
  - exportarr-radarr (port 9707)
  - exportarr-readarr (port 9707)

**ServiceMonitors**:

- Automatic Prometheus scraping via ServiceMonitor CRDs
- Scrape interval: 60 seconds
- Path: `/metrics`

**Note**: API keys are set to `"placeholder"` by default. Update with real API keys after \*arr apps are configured:

```bash
# Get API key from each app's settings
# Then update the deployment:
kubectl set env deployment/exportarr-sonarr -n media-dev APIKEY="<actual-api-key>"
```

## Deployment

### Automated Deployment (Recommended)

Deploy the complete observability stack:

```bash
./scripts/deploy-observability.sh
```

This script will:

1. Add all required Helm repositories
2. Create namespaces
3. Deploy MongoDB
4. Deploy OpenSearch
5. Deploy Graylog
6. Deploy kube-Prometheus-stack
7. Deploy Fluent Bit
8. Apply IngressRoutes

### Manual Deployment

#### 1. Deploy Monitoring Stack

```bash
# Add Helm repos
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Create namespace
kubectl create namespace monitoring

# Deploy kube-prometheus-stack
helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --values infrastructure/base/monitoring/kube-prometheus-stack/values.yaml
```

#### 2. Deploy Graylog Dependencies

```bash
# Add Helm repos
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo add opensearch https://opensearch-project.github.io/helm-charts
helm repo update

# Create namespace
kubectl create namespace observability

# Deploy MongoDB
helm install mongodb bitnami/mongodb \
  --namespace observability \
  --values infrastructure/base/observability/mongodb/values.yaml

# Deploy OpenSearch
helm install opensearch opensearch/opensearch \
  --namespace observability \
  --values infrastructure/base/observability/opensearch/values.yaml
```

#### 3. Deploy Graylog

```bash
# Deploy Graylog (includes Secret, ConfigMap, Deployment, PVC, Service)
kubectl apply -f infrastructure/base/observability/graylog/deployment.yaml
```

#### 4. Deploy Fluent Bit

```bash
# Add Helm repo
helm repo add fluent https://fluent.github.io/helm-charts
helm repo update

# Deploy Fluent Bit
helm install fluent-bit fluent/fluent-bit \
  --namespace observability \
  --values infrastructure/base/observability/fluent-bit/values.yaml
```

#### 5. Deploy IngressRoutes

```bash
# Apply IngressRoutes for web access
kubectl apply -f infrastructure/base/observability/ingressroutes.yaml
```

#### 6. Deploy Exportarr (with arr stack)

```bash
# Deploy arr stack including exportarr
kubectl apply -k applications/arr-stack/overlays/dev
```

## Post-Deployment Configuration

### Graylog Setup

1. **Access Graylog**: http://graylog.talos00
2. **Login**: admin / admin
3. **Create GELF Input**:
   - System → Inputs
   - Select "GELF TCP" from dropdown
   - Click "Launch new input"
   - Title: "Fluent Bit Logs"
   - Port: 12201 (already exposed)
   - Save

4. **Create Streams** (optional):
   - Organize logs by namespace or application
   - Set up routing rules
   - Configure retention policies

5. **Change Admin Password**:
   - Generate new password hash: `echo -n "your_password" | sha256sum`
   - Update Secret: `kubectl edit secret graylog-secret -n observability`

### Grafana Setup

1. **Access Grafana**: http://grafana.talos00
2. **Login**: admin / prom-operator
3. **Add Graylog as Data Source** (optional):
   - Configuration → Data Sources → Add data source
   - Select "Loki" or use Graylog's HTTP API
   - URL: http://graylog.observability.svc.cluster.local:9000

4. **Import Dashboards**:
   - Many dashboards are pre-installed with kube-Prometheus-stack
   - Import additional dashboards from Grafana.com:
     - Node Exporter Full: Dashboard ID 1860
     - Kubernetes Cluster Monitoring: Dashboard ID 7249
     - \*arr apps: Custom dashboards using Exportarr metrics

### Exportarr API Keys

Update Exportarr with real API keys:

```bash
# 1. Get API keys from each *arr app
# Navigate to Settings → General in each app's web UI

# 2. Update deployments
kubectl set env deployment/exportarr-prowlarr -n media-dev APIKEY="<prowlarr-api-key>"
kubectl set env deployment/exportarr-sonarr -n media-dev APIKEY="<sonarr-api-key>"
kubectl set env deployment/exportarr-radarr -n media-dev APIKEY="<radarr-api-key>"
kubectl set env deployment/exportarr-readarr -n media-dev APIKEY="<readarr-api-key>"

# 3. Verify metrics are being scraped
kubectl port-forward -n media-dev svc/exportarr-sonarr 9707:9707
curl http://localhost:9707/metrics
```

## Monitoring

### Check Component Status

```bash
# Monitoring namespace
kubectl get pods -n monitoring
kubectl get pvc -n monitoring

# Observability namespace
kubectl get pods -n observability
kubectl get pvc -n observability

# Check services
kubectl get svc -n monitoring
kubectl get svc -n observability

# Check IngressRoutes
kubectl get ingressroute -n monitoring
kubectl get ingressroute -n observability
```

### View Logs

```bash
# Prometheus
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus

# Grafana
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana

# Graylog
kubectl logs -n observability -l app=graylog

# OpenSearch
kubectl logs -n observability -l app.kubernetes.io/name=opensearch

# Fluent Bit
kubectl logs -n observability -l app.kubernetes.io/name=fluent-bit

# Exportarr
kubectl logs -n media-dev -l app=exportarr-sonarr
```

### Verify Metrics Collection

```bash
# Check Prometheus targets
# Access: http://prometheus.talos00/targets

# Check ServiceMonitors
kubectl get servicemonitor -A

# Test Exportarr metrics
kubectl port-forward -n media-dev svc/exportarr-sonarr 9707:9707
curl http://localhost:9707/metrics
```

### Verify Log Collection

```bash
# Check Fluent Bit is collecting logs
kubectl logs -n observability -l app.kubernetes.io/name=fluent-bit --tail=50

# Check Graylog is receiving logs
# Access: http://graylog.talos00 → System → Inputs
# Should show messages being received

# Search logs in Graylog
# Navigate to Search page
# Try query: namespace:media-dev
```

## Troubleshooting

### Prometheus Issues

**Pod crash looping with permission errors**:

```bash
# Label namespace as privileged
kubectl label namespace monitoring pod-security.kubernetes.io/enforce=privileged

# Delete and recreate StatefulSet
kubectl delete sts -n monitoring prometheus-kube-prometheus-stack-prometheus
# Prometheus Operator will recreate it
```

**No metrics from Exportarr**:

```bash
# Check ServiceMonitor exists
kubectl get servicemonitor -n media-dev

# Check Prometheus configuration
kubectl get prometheus -n monitoring kube-prometheus-stack-prometheus -o yaml | grep serviceMonitorSelector

# Verify endpoints are discovered
# Access: http://prometheus.talos00/targets
```

### Graylog Issues

**Graylog not starting - config file not found**:

```bash
# Check ConfigMap is mounted
kubectl describe pod -n observability -l app=graylog | grep -A 10 "Mounts:"

# Verify ConfigMap exists
kubectl get configmap -n observability graylog-config

# Check logs
kubectl logs -n observability -l app=graylog
```

**OpenSearch not connecting**:

```bash
# Check OpenSearch is running
kubectl get pods -n observability -l app.kubernetes.io/name=opensearch

# Test connectivity from Graylog pod
kubectl exec -n observability -it <graylog-pod> -- curl http://opensearch-cluster-master:9200

# Check OpenSearch logs
kubectl logs -n observability -l app.kubernetes.io/name=opensearch
```

**MongoDB not connecting**:

```bash
# Check MongoDB is running
kubectl get pods -n observability -l app.kubernetes.io/name=mongodb

# Test connectivity
kubectl exec -n observability -it <graylog-pod> -- curl http://mongodb:27017

# Check MongoDB logs
kubectl logs -n observability -l app.kubernetes.io/name=mongodb
```

### Fluent Bit Issues

**Logs not appearing in Graylog**:

```bash
# Check Fluent Bit is running
kubectl get pods -n observability -l app.kubernetes.io/name=fluent-bit

# Check Fluent Bit logs
kubectl logs -n observability -l app.kubernetes.io/name=fluent-bit --tail=100

# Verify GELF input is configured in Graylog
# Access: http://graylog.talos00 → System → Inputs

# Test GELF connectivity
kubectl exec -n observability -it <fluent-bit-pod> -- nc -zv graylog.observability.svc.cluster.local 12201
```

**Fluent Bit consuming too much memory**:

```bash
# Edit values.yaml and increase limits
# Restart Fluent Bit
helm upgrade fluent-bit fluent/fluent-bit \
  --namespace observability \
  --values infrastructure/base/observability/fluent-bit/values.yaml
```

## Storage Requirements

Total storage required for observability stack:

- Prometheus: 50Gi
- Grafana: 10Gi
- Alertmanager: 10Gi
- MongoDB: 20Gi
- OpenSearch: 30Gi
- Graylog: 20Gi

**Total: ~140Gi**

All using `local-path` storage class (node-local storage).

## Security Considerations

### Production Recommendations

1. **Graylog Password**: Change default admin password
2. **MongoDB Authentication**: Enable authentication for production
3. **OpenSearch Security**: Enable security plugin for production
4. **TLS/HTTPS**: Add TLS to IngressRoutes
5. **RBAC**: Restrict Fluent Bit service account permissions
6. **Secrets**: Use external secret management (e.g., Sealed Secrets, Vault)
7. **Network Policies**: Restrict traffic between components

### Current Security Posture (Homelab)

- Graylog uses default credentials (change after first login)
- MongoDB has authentication disabled (local-only access)
- OpenSearch security plugin is disabled
- All access is HTTP (no TLS)
- Fluent Bit has cluster-wide read access to logs
- Services are exposed via Traefik IngressRoutes (no authentication)

## Backup and Recovery

### Critical Data to Backup

1. **Prometheus Data**: PVC `prometheus-kube-prometheus-stack-prometheus-db-prometheus-kube-prometheus-stack-prometheus-0`
2. **Grafana Data**: PVC `kube-prometheus-stack-grafana`
3. **Graylog Data**: PVC `graylog-data`
4. **MongoDB Data**: PVC `data-mongodb-0`
5. **OpenSearch Data**: PVC `opensearch-cluster-master-opensearch-cluster-master-0`

### Backup Commands

```bash
# Snapshot PVCs using Velero or similar
velero backup create observability-backup \
  --include-namespaces monitoring,observability \
  --default-volumes-to-restic

# Or use kubectl cp for small datasets
kubectl cp monitoring/<pod>:/prometheus /backup/prometheus
```

## Integration with Applications

### arr Stack Integration

The arr stack includes Exportarr deployments that expose Prometheus metrics:

- **Prowlarr metrics**: http://exportarr-prowlarr.media-dev:9707/metrics
- **Sonarr metrics**: http://exportarr-sonarr.media-dev:9707/metrics
- **Radarr metrics**: http://exportarr-radarr.media-dev:9707/metrics
- **Readarr metrics**: http://exportarr-readarr.media-dev:9707/metrics

Metrics include:

- Download queue statistics
- Library item counts
- Indexer statistics
- System health

### Log Routing

All container logs are automatically collected by Fluent Bit and sent to Graylog.

Filter logs in Graylog by:

- Namespace: `namespace:media-dev`
- Pod: `pod_name:sonarr-*`
- Container: `container_name:sonarr`
- Cluster: `cluster:talos-homelab`

## Resources

- [Prometheus Operator Documentation](https://prometheus-operator.dev/)
- [Grafana Documentation](https://grafana.com/docs/)
- [Graylog Documentation](https://docs.graylog.org/)
- [Fluent Bit Documentation](https://docs.fluentbit.io/)
- [Exportarr GitHub](https://github.com/onedr0p/exportarr)
