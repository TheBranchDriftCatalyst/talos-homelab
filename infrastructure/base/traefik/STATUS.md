# Traefik Subsystem Status

**Component:** Traefik - Ingress Controller & Reverse Proxy
**Owner:** Infrastructure Team
**Last Updated:** 2025-11-11

---

## 📊 Current Status

| Metric | Value | Health |
|--------|-------|--------|
| **Deployment Status** | ✅ Deployed | 🟢 Healthy |
| **Version** | v3.5.x (Helm v37.x) | 🟢 Current |
| **Uptime** | >99% | 🟢 Stable |
| **IngressRoutes Managed** | 12+ | 🟢 Active |
| **TLS/HTTPS** | ❌ Not Configured | 🔴 HTTP Only |
| **Metrics Endpoint** | ✅ Prometheus | 🟢 Enabled |

**Health Legend:** 🟢 Healthy | 🟡 Degraded | 🔴 Down | 🔵 Development

---

## 🎯 Purpose

Traefik serves as the **Ingress Controller and HTTP router** in our dual-GitOps architecture:
- **Manages:** All HTTP/HTTPS traffic routing to cluster services
- **Method:** Kubernetes IngressRoute CRDs (Traefik-native)
- **Role:** Infrastructure component (manual deployment, not ArgoCD-managed)
- **Philosophy:** Single point of entry for all cluster services

See: [docs/02-architecture/dual-gitops.md](../../../docs/02-architecture/dual-gitops.md)

---

## 📦 Deployed Resources

### Namespace
- `traefik` - Traefik control plane (privileged security context)

### Core Components
- **Deployment Type:** DaemonSet (for hostPort binding)
- **Replicas:** 1 (single-node cluster)
- **Service Type:** ClusterIP
- **Host Ports:** 80 (HTTP), 443 (HTTPS), 9000 (Dashboard)

### EntryPoints
| EntryPoint | Port | Protocol | Status |
|------------|------|----------|--------|
| `web` | 80 | HTTP | ✅ Active |
| `websecure` | 443 | HTTPS | 🟡 Configured but unused |
| `traefik` | 9000 | HTTP | ✅ Dashboard |
| `metrics` | 9100 | HTTP | ✅ Prometheus |

### Access
- **Dashboard:** http://traefik.talos00
- **Metrics:** http://traefik.talos00:9100/metrics
- **Auth:** Insecure (dashboard accessible without auth - homelab only)

---

## 🌐 IngressRoutes Deployed

### Infrastructure Services
| Service | Host | Namespace | Port | Status |
|---------|------|-----------|------|--------|
| ArgoCD | argocd.talos00 | argocd | 80 | ✅ Active |
| Grafana | grafana.talos00 | monitoring | 80 | ✅ Active |
| Prometheus | prometheus.talos00 | monitoring | 9090 | ✅ Active |
| Alertmanager | alertmanager.talos00 | monitoring | 9093 | ✅ Active |
| Graylog | graylog.talos00 | observability | 9000 | ✅ Active |
| Docker Registry | registry.talos00 | registry | 5000 | 🟡 Read-only |

### Application Services (Defined, Not Deployed)
| Service | Host | Namespace | Port | Status |
|---------|------|-----------|------|--------|
| Prowlarr | prowlarr.talos00 | media | 9696 | 🔴 Not Deployed |
| Sonarr | sonarr.talos00 | media | 8989 | 🔴 Not Deployed |
| Radarr | radarr.talos00 | media | 7878 | 🔴 Not Deployed |
| Readarr | readarr.talos00 | media | 8787 | 🔴 Not Deployed |
| Overseerr | overseerr.talos00 | media | 5055 | 🔴 Not Deployed |
| Plex | plex.talos00 | media | 32400 | 🔴 Not Deployed |
| Jellyfin | jellyfin.talos00 | media | 8096 | 🔴 Not Deployed |
| Homepage | homepage.talos00 | media | 3000 | 🔴 Not Deployed |

---

## 🔧 Configuration

### Deployment Method
- **Tool:** Helm (via manual kubectl/script)
- **Chart:** `traefik/traefik` v37.x (Traefik v3.5.x)
- **Repository:** https://traefik.github.io/charts
- **Values File:** `kubernetes/traefik-values.yaml`

### Helm Values Overview
```yaml
deployment:
  kind: DaemonSet  # Single-node hostPort binding
  replicas: 1

service:
  type: ClusterIP

ports:
  web:
    hostPort: 80     # Direct host binding
  websecure:
    hostPort: 443
  traefik:
    port: 9000       # Dashboard
  metrics:
    port: 9100       # Prometheus

ingressRoute:
  dashboard:
    enabled: true
    matchRule: Host(`traefik.${DOMAIN}`)

providers:
  kubernetesCRD:
    enabled: true
    allowCrossNamespace: true
    allowExternalNameServices: true
  kubernetesIngress:
    enabled: true

additionalArguments:
  - --serversTransport.insecureSkipVerify=true  # Self-signed certs
  - --api.insecure=true                          # Homelab only
  - --api.dashboard=true

metrics:
  prometheus:
    enabled: true
    serviceMonitor:
      enabled: true
      namespace: monitoring

securityContext:
  runAsUser: 0       # Required for hostPort binding
  runAsNonRoot: false
```

### Files Structure
```
infrastructure/base/traefik/
├── STATUS.md (this file)
├── helmrelease.yaml (FluxCD HelmRelease - not active)
├── namespace.yaml
└── kustomization.yaml

kubernetes/
└── traefik-values.yaml (Helm values)

scripts/
└── setup-infrastructure.sh (Traefik bootstrap script)
```

---

## ✅ What's Working

- ✅ Traefik pods running and healthy
- ✅ Dashboard accessible at http://traefik.talos00
- ✅ All IngressRoutes routing correctly (HTTP)
- ✅ Prometheus metrics exposed and scraped
- ✅ ServiceMonitor integrated with kube-prometheus-stack
- ✅ Cross-namespace routing enabled
- ✅ Access logs enabled (INFO level)
- ✅ hostPort binding for direct node access

---

## 🔴 Known Issues

### 1. HTTP Only - No HTTPS/TLS
- **Status:** 🔴 Critical Security Gap
- **Impact:** All traffic unencrypted, credentials transmitted in plaintext
- **Cause:** cert-manager not deployed, no TLS certificates
- **Security Risk:**
  - Credentials (ArgoCD, Grafana, Graylog) transmitted unencrypted
  - Session tokens exposed
  - Suitable for trusted networks ONLY
- **Workaround:** Use only on isolated homelab network
- **Fix ETA:** Medium priority (see TODOs)

### 2. Docker Registry HTTP Push Issues
- **Status:** 🟡 Partial Service
- **Impact:** Cannot push images via Traefik ingress (registry.talos00)
- **Cause:** HTTP blob upload returns 404 via Traefik proxy
- **Workaround:** Use kubectl port-forward to localhost:5000
- **Related Issue:** See [infrastructure/base/registry/STATUS.md](../registry/STATUS.md)
- **Fix ETA:** Under investigation

### 3. Insecure Dashboard Access
- **Status:** 🟡 Low Priority (homelab)
- **Impact:** Dashboard accessible without authentication
- **Cause:** `--api.insecure=true` flag set
- **Workaround:** Acceptable for homelab, restrict network access
- **Fix ETA:** Add basic auth middleware (see TODOs)

### 4. Domain Naming Inconsistency
- **Status:** 🟡 Low Priority
- **Impact:** Mixed usage of `.lab` (values.yaml) vs `.talos00` (IngressRoutes)
- **Cause:** Migration from initial setup
- **Current:** All IngressRoutes use `.talos00`
- **Fix ETA:** Standardize to `.talos00` (see TODO.md)

---

## 📋 TODOs

### High Priority
- [ ] Deploy cert-manager for TLS certificate management
- [ ] Configure Let's Encrypt certificate issuer
- [ ] Update all IngressRoutes to use `websecure` entrypoint
- [ ] Test HTTPS access for all services
- [ ] Debug Docker Registry HTTP push failures

### Medium Priority
- [ ] Add basic auth middleware for Traefik dashboard
- [ ] Configure rate limiting middleware for public services
- [ ] Add redirect middleware (HTTP -> HTTPS) after TLS enabled
- [ ] Integrate Traefik access logs with Graylog/OpenSearch
- [ ] Document IngressRoute creation patterns
- [ ] Standardize domain naming (.talos00)

### Low Priority
- [ ] Add request tracing with Jaeger/Zipkin
- [ ] Configure circuit breaker middleware
- [ ] Add retry middleware for flaky services
- [ ] Implement IP whitelist middleware for sensitive services
- [ ] Create custom error pages
- [ ] Add TCP/UDP routing for non-HTTP services

---

## 🚀 Deployment Commands

### Initial Deployment
```bash
# Deploy Traefik via bootstrap script
./scripts/setup-infrastructure.sh

# Or manually via Helm
helm repo add traefik https://traefik.github.io/charts
helm repo update

kubectl create namespace traefik
kubectl label namespace traefik \
  pod-security.kubernetes.io/enforce=privileged \
  pod-security.kubernetes.io/audit=privileged \
  pod-security.kubernetes.io/warn=privileged

helm install traefik traefik/traefik \
  --namespace traefik \
  --values kubernetes/traefik-values.yaml
```

### Upgrade Traefik
```bash
# Update Helm repo
helm repo update

# Upgrade to latest version
helm upgrade traefik traefik/traefik \
  --namespace traefik \
  --values kubernetes/traefik-values.yaml
```

### Create IngressRoute
```bash
# Example IngressRoute manifest
cat <<EOF | kubectl apply -f -
---
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: my-app
  namespace: my-namespace
spec:
  entryPoints:
    - web
  routes:
    - match: Host(\`my-app.talos00\`)
      kind: Rule
      services:
        - name: my-app-service
          port: 8080
EOF
```

### Verify Deployment
```bash
# Check Traefik pod status
kubectl get pods -n traefik

# Check IngressRoutes
kubectl get ingressroute -A

# Test dashboard access
curl -I http://traefik.talos00

# Check metrics endpoint
curl http://traefik.talos00:9100/metrics
```

---

## 🔍 Troubleshooting

### Traefik Pod Not Starting

```bash
# Check pod status
kubectl get pods -n traefik -o wide

# Check pod logs
kubectl logs -n traefik -l app.kubernetes.io/name=traefik

# Check events
kubectl get events -n traefik --sort-by='.lastTimestamp'

# Verify namespace security labels
kubectl get namespace traefik -o yaml | grep pod-security
```

### IngressRoute Not Working

```bash
# Check IngressRoute status
kubectl get ingressroute -n <namespace> <name> -o yaml

# Check Traefik logs for routing errors
kubectl logs -n traefik -l app.kubernetes.io/name=traefik | grep -i error

# Verify service exists
kubectl get svc -n <namespace>

# Test service directly (bypass Traefik)
kubectl port-forward -n <namespace> svc/<service-name> 8080:<port>

# Check Traefik dashboard for routes
# Navigate to: http://traefik.talos00 -> HTTP -> Routers
```

### Dashboard Not Accessible

```bash
# Verify Traefik pod is running
kubectl get pods -n traefik

# Check if dashboard is enabled
kubectl get pod -n traefik -o yaml | grep -A2 "api.dashboard"

# Port-forward for direct access
kubectl port-forward -n traefik svc/traefik 9000:9000
# Access: http://localhost:9000/dashboard/
```

### Service Returns 404

**Possible Causes:**
1. IngressRoute match rule incorrect
2. Service name/port mismatch
3. Service not running
4. Namespace mismatch

**Debug Steps:**
```bash
# Check IngressRoute match rule
kubectl get ingressroute -n <namespace> <name> -o yaml

# Verify service selector matches pods
kubectl get svc -n <namespace> <service> -o yaml
kubectl get pods -n <namespace> -l <selector>

# Check Traefik routing table in dashboard
# http://traefik.talos00 -> HTTP -> Routers -> Services
```

### Metrics Not Scraped by Prometheus

```bash
# Verify metrics endpoint
curl http://traefik.talos00:9100/metrics

# Check ServiceMonitor
kubectl get servicemonitor -n monitoring

# Verify Prometheus targets
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090
# Navigate to: http://localhost:9090/targets
# Search for "traefik"
```

---

## 📊 Metrics & Monitoring

### Prometheus Metrics Exposed
- **Endpoint:** `:9100/metrics`
- **ServiceMonitor:** Enabled (namespace: monitoring)
- **Labels:** `prometheus: kube-prometheus`

### Key Metrics
```promql
# Request rate per service
rate(traefik_service_requests_total[5m])

# Request duration
histogram_quantile(0.95, traefik_service_request_duration_seconds_bucket)

# Error rate
rate(traefik_service_requests_total{code=~"5.."}[5m])

# Active connections
traefik_entrypoint_open_connections

# TLS certificates (when enabled)
traefik_tls_certs_not_after
```

### Grafana Dashboards
- **Dashboard ID:** 17346 (Traefik Official)
- **Access:** http://grafana.talos00
- **Import:** Dashboards -> Import -> 17346

### Access Logs
- **Enabled:** Yes (INFO level)
- **Format:** JSON
- **Destination:** stdout (collected by Fluent Bit)
- **Integration:** Forwarded to Graylog/OpenSearch (pending configuration)

---

## 🔗 Related Documentation

- [Dual GitOps Architecture](../../../docs/02-architecture/dual-gitops.md)
- [Traefik Official Documentation](https://doc.traefik.io/traefik/)
- [IngressRoute CRD Reference](https://doc.traefik.io/traefik/routing/providers/kubernetes-crd/)
- [Middleware Reference](https://doc.traefik.io/traefik/middlewares/overview/)
- [cert-manager Integration](https://cert-manager.io/docs/usage/traefik/)
- [TODO.md - Traefik Section](../../../TODO.md#traefik)

---

## 📈 Performance

### Resource Usage (Current)
- **CPU:** ~100m (low, single-node)
- **Memory:** ~50Mi (minimal)
- **Storage:** None (stateless)

### Resource Limits
```yaml
resources:
  requests:
    cpu: 100m
    memory: 50Mi
  limits:
    cpu: 300m
    memory: 150Mi
```

### Scalability
- **Current:** 1 replica (DaemonSet on single node)
- **Target:** 1 replica (single-node cluster)
- **Multi-node:** Switch to Deployment with multiple replicas

### Load Testing
```bash
# Install hey (HTTP load generator)
go install github.com/rakyll/hey@latest

# Test IngressRoute performance
hey -n 1000 -c 10 http://whoami.talos00

# Monitor metrics during load
watch -n 1 'kubectl top pods -n traefik'
```

---

## 🎓 Best Practices

### IngressRoute Structure
```yaml
---
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: my-app
  namespace: my-namespace
  labels:
    app: my-app
    team: platform
spec:
  entryPoints:
    - web              # HTTP (or websecure for HTTPS)
  routes:
    - match: Host(`my-app.talos00`)
      kind: Rule
      services:
        - name: my-app-service
          port: 8080
      middlewares:     # Optional
        - name: rate-limit
```

### Middleware Examples

**Basic Auth:**
```yaml
---
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: basic-auth
  namespace: traefik
spec:
  basicAuth:
    secret: auth-secret  # htpasswd format
```

**Rate Limiting:**
```yaml
---
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: rate-limit
  namespace: traefik
spec:
  rateLimit:
    average: 100
    burst: 50
```

**HTTP to HTTPS Redirect:**
```yaml
---
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: redirect-https
  namespace: traefik
spec:
  redirectScheme:
    scheme: https
    permanent: true
```

### Security Best Practices
1. **Enable TLS/HTTPS** - Use cert-manager for automated certificate management
2. **Restrict Dashboard Access** - Use basic auth or IP whitelist middleware
3. **Rate Limiting** - Protect services from abuse
4. **Request Timeouts** - Configure reasonable timeouts
5. **Network Policies** - Restrict traffic flow between namespaces
6. **Regular Updates** - Keep Traefik updated for security patches

### IngressRoute Naming Convention
- Use lowercase with hyphens
- Match service name when possible
- Include namespace prefix for shared middlewares
- Example: `my-app`, `auth-middleware`, `platform-rate-limit`

---

## 🔄 Maintenance

### Regular Tasks
- **Weekly:** Review access logs for errors
- **Monthly:** Update Traefik Helm chart version
- **Quarterly:** Audit IngressRoutes and middlewares
- **Annually:** Review TLS certificate expiration (automated with cert-manager)

### Update Procedure
```bash
# 1. Check current version
helm list -n traefik

# 2. Review changelog
# https://github.com/traefik/traefik/releases

# 3. Update Helm repo
helm repo update

# 4. Upgrade with values
helm upgrade traefik traefik/traefik \
  --namespace traefik \
  --values kubernetes/traefik-values.yaml

# 5. Verify upgrade
kubectl rollout status daemonset/traefik -n traefik
kubectl get pods -n traefik

# 6. Test IngressRoutes
curl -I http://argocd.talos00
curl -I http://grafana.talos00
```

### Backup Strategy
**Note:** Traefik is stateless - configuration lives in Kubernetes manifests

```bash
# Backup IngressRoutes
kubectl get ingressroute -A -o yaml > traefik-ingressroutes-backup.yaml

# Backup Middlewares
kubectl get middleware -A -o yaml > traefik-middlewares-backup.yaml

# Backup Helm values
cp kubernetes/traefik-values.yaml backups/traefik-values-$(date +%Y%m%d).yaml
```

### Rollback Procedure
```bash
# Rollback to previous Helm release
helm rollback traefik -n traefik

# Or rollback to specific revision
helm history traefik -n traefik
helm rollback traefik <revision> -n traefik
```

---

## 🚨 Security Considerations

### Current Security Posture
- ✅ Runs in isolated namespace
- ✅ Prometheus metrics secured (internal only)
- ✅ Pod security context configured (privileged for hostPort)
- ❌ **HTTP only - no TLS encryption**
- ❌ **Dashboard accessible without authentication**
- ❌ **No rate limiting configured**
- ❌ **No IP whitelisting**

### Recommended Hardening (Priority Order)
1. **Enable HTTPS/TLS** - Deploy cert-manager, configure TLS certificates
2. **Secure Dashboard** - Add basic auth or disable external access
3. **Rate Limiting** - Protect against DoS attacks
4. **IP Whitelisting** - Restrict access to sensitive services
5. **Network Policies** - Limit ingress/egress traffic
6. **Header Security** - Add security headers middleware

### Threat Model
- **Threat:** Unencrypted credential transmission (HTTP)
  - **Mitigation:** Deploy HTTPS/TLS (HIGH PRIORITY)
- **Threat:** Unauthorized dashboard access
  - **Mitigation:** Add authentication middleware
- **Threat:** DoS via excessive requests
  - **Mitigation:** Rate limiting middleware
- **Threat:** Internal service exposure
  - **Mitigation:** IP whitelist for admin services

---

## 📅 Maintenance Schedule

| Task | Frequency | Last Completed | Next Due |
|------|-----------|----------------|----------|
| Review access logs | Weekly | 2025-11-11 | 2025-11-18 |
| Update Helm chart | Monthly | 2025-11-11 | 2025-12-11 |
| Audit IngressRoutes | Quarterly | 2025-11-11 | 2026-02-11 |
| Security review | Quarterly | - | 2026-02-11 |
| Performance testing | Semi-annually | - | 2026-05-11 |

---

**Next Review Date:** 2025-11-18
**Status Owner:** Infrastructure Team
**Escalation Contact:** Platform Team
