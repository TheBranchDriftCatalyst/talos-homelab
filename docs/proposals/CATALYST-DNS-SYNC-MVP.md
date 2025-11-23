# Catalyst DNS Sync - MVP Definition

**Version:** 1.0
**Status:** In Progress
**Target:** Phase 1 Complete

---

## MVP Scope Definition

### Phase 1 MVP (Current Focus)

**Goal:** Production-ready DNS sync daemon with core functionality and observability.

#### ✅ Must Have (Phase 1)

1. **Full CRUD DNS Sync**
   - Watch Ingress resources (networking.k8s.io/v1)
   - Watch IngressRoute resources (traefik.io/v1alpha1)
   - Extract hostnames matching DNS zone
   - Create DNS A records in Technitium
   - Update DNS records on Ingress changes
   - Delete DNS records when Ingress deleted
   - Incremental sync (only change what's needed)

2. **Prometheus Metrics**
   - `catalyst_dns_sync_records_total{zone,status}` - Counter for created/updated/deleted
   - `catalyst_dns_sync_api_requests_total{endpoint,method,status_code}` - API call tracking
   - `catalyst_dns_sync_api_request_duration_seconds{endpoint,method}` - Latency histogram
   - `catalyst_dns_sync_reconcile_duration_seconds{resource_type}` - Reconciliation time
   - `catalyst_dns_sync_reconcile_errors_total{resource_type,error_type}` - Error tracking
   - `catalyst_dns_sync_ingress_resources{namespace,type}` - Current resource count
   - Metrics exposed on `:8080/metrics`

3. **Health Endpoints**
   - `/healthz` - Liveness probe (process running)
   - `/readyz` - Readiness probe (K8s API + DNS API reachable)
   - Health endpoints on `:8081`

4. **Dev Mode (Local /etc/hosts updater)**
   - `--dev-mode` flag to update `/etc/hosts` instead of DNS
   - Air hot reload support (`.air.toml`)
   - Idempotent managed block (same as `update-hosts.sh`)
   - Watch cluster, update local hosts file
   - Full metrics/health endpoints in dev mode

5. **Production Deployment**
   - Dockerfile with multi-stage build
   - Kubernetes Deployment manifest
   - RBAC (ServiceAccount, ClusterRole, ClusterRoleBinding)
   - Service for metrics
   - ServiceMonitor for Prometheus
   - ConfigMap for configuration
   - Secret for API token

6. **Structured Logging**
   - JSON logs using Go `log/slog`
   - Log levels: debug, info, warn, error
   - Structured fields (hostname, namespace, resource, etc.)

7. **Configuration**
   - Environment variables for all config
   - Sensible defaults
   - Support for ConfigMap overrides

8. **Documentation**
   - README with quick start
   - Architecture diagram
   - API documentation
   - Deployment guide

#### ❌ Not in Phase 1 MVP

- Web UI Dashboard (Phase 2)
- HTTPRoute (Gateway API) support
- Certificate management integration
- Preview environment auto-DNS
- DNS drift detection
- Multi-zone support
- Slack/Discord notifications
- Export/Import CLI
- Auto-wildcard SSL

---

### Phase 2 MVP (Future)

**Goal:** Web UI for visibility and manual operations.

#### Must Have (Phase 2)

1. **Web UI Dashboard** (`/ui` endpoint)
   - DNS records table (hostname, IP, TTL, source)
   - Sync status panel (last sync, success rate, pending ops)
   - Real-time event stream (SSE/WebSocket)
   - Manual override panel (force resync, delete record)
   - Built with HTMX + Alpine.js (no build step)
   - Exposed via IngressRoute at `dns.talos00`

2. **DNS Test Endpoint**
   - `/api/v1/test-dns?hostname=X` - Test DNS resolution
   - Returns DNS status, Ingress status, sync health

3. **Enhanced Metrics**
   - Certificate expiration tracking
   - Preview environment metrics
   - Drift detection metrics

---

## Phase 1 Implementation Checklist

### Core Components

- [ ] **Project Setup**
  - [ ] Initialize Go module (`go mod init`)
  - [ ] Create directory structure
  - [ ] Setup Air config (`.air.toml`)
  - [ ] Create Makefile

- [ ] **DNS Client (Technitium)**
  - [ ] `internal/dns/client.go` - HTTP client wrapper
  - [ ] `internal/dns/types.go` - API request/response types
  - [ ] `internal/dns/records.go` - CRUD operations
    - [ ] `AddARecord(zone, name, ip, ttl)` - Create DNS record
    - [ ] `DeleteARecord(zone, name)` - Delete DNS record
    - [ ] Error handling & retries
  - [ ] API authentication (token in header)

- [ ] **Hosts File Manager (Dev Mode)**
  - [ ] `internal/dns/hosts.go` - /etc/hosts updater
  - [ ] `UpdateHostsFile(hostnames)` - Idempotent block updates
  - [ ] Managed block with markers
  - [ ] Atomic file writes with sudo

- [ ] **Configuration**
  - [ ] `internal/config/config.go` - Load from env vars
  - [ ] DNS server URL, zone, IP, TTL defaults
  - [ ] Kubernetes config (KUBECONFIG)
  - [ ] Log level, log format

- [ ] **Kubernetes Controllers**
  - [ ] `internal/controller/ingress.go` - Watch Ingress resources
  - [ ] `internal/controller/ingressroute.go` - Watch IngressRoute resources
  - [ ] Hostname extraction logic
  - [ ] Zone filtering (only `*.talos00`)
  - [ ] Reconciliation loop
  - [ ] Event handlers (Add, Update, Delete)

- [ ] **Metrics**
  - [ ] `internal/metrics/metrics.go` - Prometheus setup
  - [ ] Register all Phase 1 metrics
  - [ ] Metrics HTTP server (`:8080/metrics`)

- [ ] **Health Checks**
  - [ ] Liveness handler (`/healthz`)
  - [ ] Readiness handler (`/readyz`)
    - [ ] Test K8s API connection
    - [ ] Test DNS API connection (or /etc/hosts write in dev mode)
  - [ ] Health HTTP server (`:8081`)

- [ ] **Main Application**
  - [ ] `cmd/controller/main.go` - Entry point
  - [ ] Parse `--dev-mode` flag
  - [ ] Initialize DNS client (Technitium or HostsFileManager)
  - [ ] Setup Kubernetes client
  - [ ] Start controllers
  - [ ] Start metrics server
  - [ ] Start health server
  - [ ] Graceful shutdown

- [ ] **Structured Logging**
  - [ ] Setup slog with JSON formatter
  - [ ] Log all DNS operations (create, update, delete)
  - [ ] Log reconciliation events
  - [ ] Log errors with context

### Kubernetes Deployment

- [ ] **Docker**
  - [ ] `Dockerfile` - Multi-stage build
  - [ ] Base: `golang:1.23-alpine`
  - [ ] Final: `alpine:latest` with ca-certificates
  - [ ] Non-root user

- [ ] **Manifests** (`k8s/base/`)
  - [ ] `deployment.yaml` - Deployment spec
    - [ ] Single replica
    - [ ] Resource limits (64Mi-128Mi, 50m-200m CPU)
    - [ ] Liveness/readiness probes
    - [ ] Env vars from ConfigMap/Secret
  - [ ] `rbac.yaml` - ServiceAccount, ClusterRole, ClusterRoleBinding
    - [ ] Read Ingress, IngressRoute
  - [ ] `service.yaml` - Service for metrics/health
  - [ ] `servicemonitor.yaml` - Prometheus ServiceMonitor
  - [ ] `configmap.yaml` - DNS configuration
  - [ ] `secret.yaml.example` - API token template
  - [ ] `kustomization.yaml` - Kustomize config

- [ ] **Scripts**
  - [ ] Update existing `scripts/update-hosts.sh` reference to new daemon
  - [ ] Add deployment script if needed

### Testing & Validation

- [ ] **Unit Tests**
  - [ ] DNS client mock tests
  - [ ] Hostname extraction tests
  - [ ] Hosts file manager tests

- [ ] **Integration Tests**
  - [ ] Dev mode: Create Ingress → verify /etc/hosts updated
  - [ ] Prod mode: Create Ingress → verify DNS record in Technitium
  - [ ] Delete Ingress → verify cleanup
  - [ ] Update Ingress hostname → verify DNS updated

- [ ] **Manual Testing**
  - [ ] Deploy to cluster
  - [ ] Verify metrics endpoint works
  - [ ] Verify health endpoints work
  - [ ] Create test Ingress, check DNS resolution
  - [ ] Delete test Ingress, verify DNS removed
  - [ ] Check Prometheus scraping

### Documentation

- [ ] **README.md**
  - [ ] Project overview
  - [ ] Quick start (dev mode)
  - [ ] Quick start (production)
  - [ ] Configuration reference
  - [ ] Metrics reference
  - [ ] Troubleshooting

- [ ] **Architecture Diagram**
  - [ ] Component diagram
  - [ ] Data flow diagram

---

## Success Criteria (Phase 1)

### Functional

- [x] Dev mode: `task dev` starts watcher, updates /etc/hosts
- [ ] Dev mode: Create IngressRoute → /etc/hosts updated within 5s
- [ ] Dev mode: Delete IngressRoute → /etc/hosts entry removed within 5s
- [ ] Prod mode: Deploy to cluster successfully
- [ ] Prod mode: All 16 existing IngressRoutes get DNS records
- [ ] Prod mode: New IngressRoute → DNS record created within 30s
- [ ] Prod mode: Delete IngressRoute → DNS record removed within 30s
- [ ] Prod mode: Update IngressRoute hostname → DNS updated correctly

### Observability

- [ ] Prometheus metrics endpoint returns valid metrics
- [ ] All 6 Phase 1 metrics are present
- [ ] ServiceMonitor successfully scraped by Prometheus
- [ ] Logs are valid JSON and parseable by Graylog
- [ ] Health endpoints return correct status
- [ ] Grafana dashboard shows metrics (manual import for Phase 1)

### Performance

- [ ] Memory usage < 50MB under normal load
- [ ] CPU usage < 0.1 core under normal load
- [ ] Reconciliation time < 5s for single Ingress
- [ ] Handles 16+ IngressRoutes without errors

### Reliability

- [ ] Runs for 24 hours without crashes
- [ ] Survives Kubernetes API temporary unavailability
- [ ] Survives DNS API temporary unavailability (with retries)
- [ ] Graceful shutdown on SIGTERM
- [ ] No DNS record duplication
- [ ] No orphaned DNS records after controller restart

---

## Development Timeline

### Week 1: Core Implementation

**Days 1-2:** Project setup & DNS client
- Initialize project structure
- Implement Technitium DNS client
- Implement hosts file manager
- Unit tests for DNS operations

**Days 3-4:** Kubernetes controllers
- Ingress controller
- IngressRoute controller
- Reconciliation logic
- Hostname extraction

**Days 5-6:** Metrics & health
- Prometheus metrics setup
- Health check endpoints
- Structured logging

**Day 7:** Testing & fixes
- Integration testing
- Bug fixes
- Dev mode validation

### Week 2: Deployment & Production

**Days 1-2:** Containerization
- Dockerfile
- Build & push to local registry
- Test container locally

**Days 3-4:** Kubernetes deployment
- Manifests (Deployment, RBAC, Service, etc.)
- Deploy to cluster
- ServiceMonitor setup

**Days 5-6:** Production validation
- Test with real IngressRoutes
- Monitor metrics in Prometheus
- Test edge cases (updates, deletes)

**Day 7:** Documentation & polish
- README documentation
- Troubleshooting guide
- Code cleanup

---

## Command Reference

### Development Commands

```bash
# Start dev mode with hot reload
task dev

# Build binary locally
task build

# Run unit tests
task test

# Manual dev mode run
task run-dev
# OR
go run ./cmd/controller --dev-mode
```

### Production Commands

```bash
# Build Docker image
task docker

# Push to local registry
task push

# Deploy to cluster
task deploy

# Full build + deploy
task deploy

# Check deployment status
kubectl get deploy -n infrastructure catalyst-dns-sync

# View logs
kubectl logs -n infrastructure -l app=catalyst-dns-sync -f

# Check metrics
kubectl port-forward -n infrastructure svc/catalyst-dns-sync 8080:8080
curl http://localhost:8080/metrics

# Check health
kubectl port-forward -n infrastructure svc/catalyst-dns-sync 8081:8081
curl http://localhost:8081/healthz
curl http://localhost:8081/readyz
```

### Testing Commands

```bash
# Create test IngressRoute
kubectl apply -f - <<EOF
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: test-app
  namespace: default
spec:
  routes:
  - match: Host(\`test.talos00\`)
    services:
    - name: whoami
      port: 80
EOF

# Verify DNS record created
dig @192.168.1.54 test.talos00

# Delete test IngressRoute
kubectl delete ingressroute test-app -n default

# Verify DNS record deleted
dig @192.168.1.54 test.talos00
```

---

## Metrics Reference (Phase 1)

```promql
# Total DNS records managed
catalyst_dns_sync_records_total{zone="talos00",status="created"}
catalyst_dns_sync_records_total{zone="talos00",status="updated"}
catalyst_dns_sync_records_total{zone="talos00",status="deleted"}

# API request tracking
rate(catalyst_dns_sync_api_requests_total[5m])

# API latency (p95)
histogram_quantile(0.95,
  rate(catalyst_dns_sync_api_request_duration_seconds_bucket[5m])
)

# Reconciliation errors
rate(catalyst_dns_sync_reconcile_errors_total[5m])

# Current resources watched
catalyst_dns_sync_ingress_resources{namespace="monitoring",type="IngressRoute"}
```

---

## Configuration Reference

### Environment Variables

```bash
# DNS Server (Production Mode)
DNS_SERVER_URL=https://dns.talos00:5380
DNS_API_TOKEN=<from-secret>
DNS_ZONE=talos00
DNS_IP_ADDRESS=192.168.1.54
DNS_TTL_DEFAULT=300

# Kubernetes
KUBECONFIG=/path/to/kubeconfig  # Only for local dev
WATCH_NAMESPACE=                # Empty = all namespaces

# Logging
LOG_LEVEL=info                  # debug, info, warn, error
LOG_FORMAT=json                 # json or text

# Servers
METRICS_BIND_ADDRESS=:8080
HEALTH_PROBE_ADDRESS=:8081

# Dev Mode
# Use --dev-mode flag instead of env var
```

### Kubernetes Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: technitium-api-token
  namespace: infrastructure
type: Opaque
stringData:
  token: "YOUR_TECHNITIUM_API_TOKEN_HERE"
```

---

## Phase 2 Preview

Once Phase 1 MVP is complete and stable, Phase 2 will add:

1. **Web UI Dashboard** at `dns.talos00/ui`
   - Real-time DNS records table
   - Event stream
   - Manual operations panel

2. **Enhanced Features**
   - HTTPRoute (Gateway API) support
   - Certificate expiration tracking
   - DNS drift detection
   - Preview environment auto-DNS

3. **Advanced Capabilities**
   - Multi-zone support
   - Export/Import CLI
   - Slack/Discord notifications
   - Auto-wildcard SSL management

---

## Current Status

**Last Updated:** 2025-11-11

### Completed
- ✅ Technical proposal (CATALYST-DNS-SYNC-PROPOSAL.md)
- ✅ MVP definition (this document)
- ✅ Architecture design
- ✅ API research (Technitium)

### In Progress
- ⏳ Phase 1 implementation (starting now)

### Next Steps
1. Initialize Go project structure
2. Implement Technitium DNS client
3. Implement hosts file manager
4. Build Kubernetes controllers

---

**Ready to start implementation!** 🚀
