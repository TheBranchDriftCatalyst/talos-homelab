# Catalyst DNS Sync

Automatic DNS synchronization daemon for Kubernetes Ingress resources to Technitium DNS Server.

## Overview

**catalyst-dns-sync** is an ultra-lightweight Go daemon that watches Kubernetes Ingress and Traefik IngressRoute resources and automatically creates/updates/deletes DNS A records in Technitium DNS Server.

### Features

- **Dual Mode Operation**: Watch mode (real-time) or Poll mode (periodic sync)
- **Multi-Resource Support**: Standard Ingress + Traefik IngressRoute CRDs
- **Automatic Cleanup**: Orphaned DNS records deleted when Ingress is removed
- **Production Observability**:
  - JSON structured logging → Fluent Bit → Graylog
  - Prometheus metrics (ops, records, API latency, errors)
  - Health/Readiness probes
- **Ultra-Lightweight**: ~10MB container (distroless base)
- **Developer Friendly**: Makefile, local testing, comprehensive logging

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Kubernetes Cluster                     │
│                                                         │
│  ┌──────────────┐         ┌────────────────────────┐   │
│  │ Technitium   │◄────────┤ catalyst-dns-sync      │   │
│  │ DNS Server   │  API    │ - Watches Ingress      │   │
│  │              │         │ - Creates A records    │   │
│  │ Zone:talos00 │         │ - Exposes metrics      │   │
│  └──────────────┘         └────────────────────────┘   │
│                                     ▲                   │
│                                     │                   │
│                           Kubernetes API                │
│                                     │                   │
│  ┌────────────────────────────────────────────────┐    │
│  │ IngressRoute / Ingress Resources               │    │
│  │ - Host(`grafana.talos00`)                      │    │
│  │ - Host(`prowlarr.talos00`)                     │    │
│  └────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Kubernetes cluster (Talos, k3s, etc.)
- Docker registry (localhost:5000 or similar)
- Traefik ingress controller (for IngressRoute support)

### Installation

1. **Deploy DNS Infrastructure**:
   ```bash
   ./scripts/setup-dns.sh
   ```

   This script will:
   - Deploy Technitium DNS Server
   - Configure the DNS zone
   - Build and deploy catalyst-dns-sync
   - Wait for everything to be ready

2. **Configure Your Network**:
   - Point your router/devices to use `192.168.1.54` (or your node IP) as DNS server
   - Or configure per-device DNS settings

3. **Test**:
   ```bash
   # DNS should auto-create when you deploy an Ingress
   kubectl apply -f - <<EOF
   apiVersion: traefik.io/v1alpha1
   kind: IngressRoute
   metadata:
     name: test
     namespace: default
   spec:
     entryPoints:
       - web
     routes:
       - match: Host(\`test.talos00\`)
         kind: Rule
         services:
           - name: some-service
             port: 80
   EOF

   # Check DNS record was created
   dig @192.168.1.54 test.talos00 +short
   # Should return: 192.168.1.54
   ```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MODE` | `watch` | Run mode: `watch` or `poll` |
| `TECHNITIUM_URL` | `http://technitium-dns.dns.svc.cluster.local:5380` | Technitium API URL |
| `TECHNITIUM_USERNAME` | `admin` | Technitium username |
| `TECHNITIUM_PASSWORD` | (required) | Technitium password |
| `TECHNITIUM_ZONE` | `talos00` | DNS zone to manage |
| `NODE_IP` | `192.168.1.54` | IP address for A records |
| `DNS_TTL` | `300` | TTL for DNS records (seconds) |
| `LOG_LEVEL` | `info` | Log level: debug, info, warn, error |
| `RESYNC_INTERVAL` | `5m` | Full resync interval (watch mode) |
| `POLL_INTERVAL` | `30s` | Polling interval (poll mode) |
| `METRICS_PORT` | `9090` | Prometheus metrics port |
| `HEALTH_PORT` | `8080` | Health check port |

### Watch vs Poll Mode

**Watch Mode** (Recommended):
- Real-time event-driven updates
- Uses Kubernetes informers
- Instant DNS updates when Ingress changes
- Lower latency, more efficient

**Poll Mode**:
- Periodic full reconciliation
- Simpler logic, easier to debug
- Good for testing or edge cases
- Higher latency (poll interval)

## Development

### Local Development

```bash
# Install dependencies
go mod download

# Build locally
make build

# Run locally (requires kubeconfig)
make run

# Or with custom config
KUBECONFIG=~/.kube/config \
LOG_LEVEL=debug \
MODE=watch \
TECHNITIUM_URL=http://localhost:5380 \
TECHNITIUM_PASSWORD=admin \
./bin/catalyst-dns-sync
```

### Build & Deploy

```bash
# Build Docker image
make docker-build

# Push to registry
make docker-push

# Deploy to Kubernetes
make deploy

# View logs
make logs

# Port-forward metrics
make metrics
```

### Testing

```bash
# Run tests
make test

# Check Go modules
make tidy
```

## Observability

### Prometheus Metrics

Exposed on `:9090/metrics`:

| Metric | Type | Description |
|--------|------|-------------|
| `catalyst_dns_sync_operations_total` | Counter | Total sync operations (by status) |
| `catalyst_dns_sync_records_total` | Counter | Records processed (by action: created/updated/deleted/skipped) |
| `catalyst_dns_sync_records_current` | Gauge | Current managed records (by zone) |
| `catalyst_dns_sync_duration_seconds` | Histogram | Sync operation duration |
| `catalyst_dns_sync_api_request_duration_seconds` | Histogram | Technitium API latency |
| `catalyst_dns_sync_api_errors_total` | Counter | API errors (by method/endpoint/status) |
| `catalyst_dns_sync_last_success_timestamp_seconds` | Gauge | Last successful sync timestamp |
| `catalyst_dns_sync_healthy` | Gauge | Health status (1=healthy, 0=unhealthy) |
| `catalyst_dns_sync_errors_total` | Counter | Errors by type |
| `catalyst_dns_sync_ingresses_watched` | Gauge | Number of Ingress resources watched |

### Logging

Structured JSON logs to stdout (auto-collected by Fluent Bit → Graylog):

```json
{
  "level": "info",
  "service": "catalyst-dns-sync",
  "component": "controller",
  "time": "2025-11-11T12:00:00Z",
  "message": "DNS record created",
  "zone": "talos00",
  "name": "grafana",
  "ip": "192.168.1.54",
  "ttl": 300
}
```

View logs:
```bash
# Kubernetes logs
kubectl -n dns logs -f deployment/catalyst-dns-sync

# Or via Makefile
make logs

# Or in Graylog UI
http://graylog.talos00
```

### Health Checks

- **Liveness**: `GET /healthz` - Always returns 200 if process is running
- **Readiness**: `GET /readyz` - Returns 200 if daemon is healthy

## Troubleshooting

### DNS Records Not Creating

1. **Check daemon logs**:
   ```bash
   kubectl -n dns logs deployment/catalyst-dns-sync
   ```

2. **Verify Technitium is accessible**:
   ```bash
   kubectl -n dns exec deployment/catalyst-dns-sync -- wget -O- http://technitium-dns.dns.svc.cluster.local:5380/api/ping
   ```

3. **Check zone configuration**:
   - Access Technitium UI: http://dns.talos00
   - Verify zone `talos00` exists and is enabled

4. **Verify RBAC permissions**:
   ```bash
   kubectl -n dns get clusterrolebinding catalyst-dns-sync -o yaml
   ```

### Metrics Not Appearing in Prometheus

1. **Check ServiceMonitor**:
   ```bash
   kubectl -n dns get servicemonitor catalyst-dns-sync -o yaml
   ```

2. **Verify Prometheus targets**:
   - Access Prometheus UI: http://prometheus.talos00/targets
   - Look for `dns/catalyst-dns-sync/0`

3. **Port-forward and test metrics directly**:
   ```bash
   kubectl -n dns port-forward deployment/catalyst-dns-sync 9090:9090
   curl http://localhost:9090/metrics
   ```

### Logs Not in Graylog

Fluent Bit automatically collects all pod logs. If logs are missing:

1. **Check Fluent Bit is running**:
   ```bash
   kubectl -n observability get pods -l app=fluent-bit
   ```

2. **Verify Graylog inputs**:
   - Access Graylog UI: http://graylog.talos00
   - Check System → Inputs → GELF TCP

## File Structure

```
.
├── cmd/
│   └── catalyst-dns-sync/
│       └── main.go                 # Entry point
├── internal/
│   ├── config/
│   │   └── config.go               # Configuration loading
│   ├── controller/
│   │   ├── controller.go           # Main controller
│   │   ├── watcher.go              # Watch mode (informers)
│   │   └── poller.go               # Poll mode
│   ├── k8s/
│   │   ├── ingress.go              # Ingress handler
│   │   └── ingressroute.go         # IngressRoute handler
│   ├── metrics/
│   │   └── metrics.go              # Prometheus metrics
│   └── technitium/
│       ├── client.go               # API client
│       └── types.go                # Request/response types
├── applications/catalyst-dns-sync/
│   └── base/
│       ├── rbac.yaml               # ServiceAccount, RBAC
│       ├── configmap.yaml          # Configuration
│       ├── secret.yaml             # Credentials
│       ├── deployment.yaml         # Daemon deployment
│       ├── service.yaml            # Metrics service
│       ├── servicemonitor.yaml     # Prometheus scraping
│       └── kustomization.yaml
├── infrastructure/base/dns/
│   ├── namespace.yaml
│   ├── technitium/                 # Technitium DNS manifests
│   └── kustomization.yaml
├── scripts/
│   ├── setup-dns.sh                # Full deployment script
│   └── configure-technitium.sh     # Initial DNS configuration
├── Dockerfile                      # Multi-stage build
├── Makefile                        # Development commands
├── go.mod
└── README-DNS.md                   # This file
```

## Contributing

This is part of the Talos Kubernetes homelab infrastructure. Contributions welcome!

## License

MIT
