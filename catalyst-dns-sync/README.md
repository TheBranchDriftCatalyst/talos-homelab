# Catalyst DNS Sync

> Kubernetes-native DNS automation for Technitium DNS Server

Automatically sync Traefik IngressRoute and standard Ingress hostnames to DNS records, eliminating manual `/etc/hosts` management.

---

## Quick Start

### Status

Untested entirely, need debug sesh.

- [ ] Need to move this to the dev repo as well at some point

### Development Mode (Local /etc/hosts)

```bash
# One-time setup (install Air + init Go module)
task dev:setup

# Start dev mode - updates your /etc/hosts file
task dev
```

Your `/etc/hosts` will be updated automatically as you create/delete Ingress resources in the cluster.

### Production Mode (Technitium DNS)

```bash
# Build and deploy to cluster
task prod:deploy

# Check status
task status
task logs
```

---

## Features

### Phase 1 MVP (Current)

- ✅ **Full CRUD DNS Sync** - Create, update, delete DNS records automatically
- ✅ **Multi-resource Support** - Ingress & IngressRoute (Traefik)
- ✅ **Prometheus Metrics** - 6 core metrics for observability
- ✅ **Health Endpoints** - `/healthz` and `/readyz` probes
- ✅ **Dev Mode** - Update local `/etc/hosts` with Air hot reload
- ✅ **Structured Logging** - JSON logs via Go slog
- ✅ **Production Ready** - Kubernetes Deployment with RBAC

### Phase 2 (Planned)

- 🔜 **Web UI Dashboard** - View and manage DNS records at `dns.talos00/ui`
- 🔜 **Certificate Tracking** - Monitor cert-manager certificate expiration
- 🔜 **Preview Environments** - Auto DNS for `pr-123.app.talos00`
- 🔜 **DNS Drift Detection** - Detect and remediate manual DNS changes

See [full proposal](../docs/proposals/CATALYST-DNS-SYNC-PROPOSAL.md) and [MVP definition](../docs/proposals/CATALYST-DNS-SYNC-MVP.md) for details.

---

## Architecture

```
┌─────────────────────────────────────────────┐
│         Kubernetes Cluster                   │
│                                              │
│  ┌──────────────┐   ┌──────────────────┐    │
│  │ IngressRoute │──▶│ catalyst-dns-sync│    │
│  │  Resources   │   │   (controller)   │    │
│  └──────────────┘   └────────┬─────────┘    │
│                              │               │
│  ┌──────────────┐            │               │
│  │   Ingress    │────────────┘               │
│  │  Resources   │                            │
│  └──────────────┘                            │
└──────────────────────────┬───────────────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │  Technitium DNS Server │
              │   (192.168.1.x:5380)   │
              └────────────────────────┘
```

**Dev Mode:**

```
Kubernetes Cluster ──▶ catalyst-dns-sync ──▶ /etc/hosts (local)
```

---

## Configuration

### Environment Variables

```bash
# DNS Server (Production)
DNS_SERVER_URL=https://dns.talos00:5380
DNS_API_TOKEN=<secret>
DNS_ZONE=talos00
DNS_IP_ADDRESS=192.168.1.54
DNS_TTL_DEFAULT=300

# Logging
LOG_LEVEL=info          # debug, info, warn, error
LOG_FORMAT=json         # json or text

# Servers
METRICS_BIND_ADDRESS=:8080
HEALTH_PROBE_ADDRESS=:8081
```

### Kubernetes Secret

Create a secret with your Technitium API token:

```bash
kubectl create secret generic technitium-api-token \
  --from-literal=token=YOUR_TOKEN_HERE \
  -n infrastructure
```

---

## Development

### Project Structure

```
catalyst-dns-sync/
├── cmd/
│   └── controller/
│       └── main.go              # Entry point
├── internal/
│   ├── controller/              # K8s controllers
│   ├── dns/                     # DNS clients (Technitium + hosts)
│   ├── config/                  # Configuration
│   └── metrics/                 # Prometheus metrics
├── k8s/                         # Kubernetes manifests
├── .air.toml                    # Hot reload config
├── Dockerfile
├── Taskfile.yml                 # Task automation
└── README.md
```

### Task Commands

```bash
task              # Show all available tasks
task dev          # Start dev mode with hot reload
task build        # Build binary
task test         # Run tests
task docker       # Build Docker image
task push         # Push to local registry
task deploy       # Deploy to cluster
task logs         # View logs
task status       # Check deployment status
task metrics      # Port-forward metrics endpoint
```

### Dev Mode Details

When running `task dev` or `--dev-mode`:

- Watches Ingress/IngressRoute resources from cluster
- Extracts hostnames matching `DNS_ZONE` (e.g., `*.talos00`)
- Updates `/etc/hosts` with idempotent managed block:

```
# BEGIN CATALYST-DNS-SYNC MANAGED BLOCK
# Auto-generated by catalyst-dns-sync (dev mode)
192.168.1.54  grafana.talos00
192.168.1.54  argocd.talos00
# ... all hostnames
# END CATALYST-DNS-SYNC MANAGED BLOCK
```

- Air watches for code changes and auto-rebuilds
- Same metrics/health endpoints as production mode

---

## Metrics

All metrics exposed at `:8080/metrics` for Prometheus scraping.

### Core Metrics

| Metric                                           | Type      | Description                         |
| ------------------------------------------------ | --------- | ----------------------------------- |
| `catalyst_dns_sync_records_total`                | Counter   | DNS records created/updated/deleted |
| `catalyst_dns_sync_api_requests_total`           | Counter   | DNS API calls by endpoint/status    |
| `catalyst_dns_sync_api_request_duration_seconds` | Histogram | API request latency                 |
| `catalyst_dns_sync_reconcile_duration_seconds`   | Histogram | Controller reconciliation time      |
| `catalyst_dns_sync_reconcile_errors_total`       | Counter   | Reconciliation errors by type       |
| `catalyst_dns_sync_ingress_resources`            | Gauge     | Current Ingress resources watched   |

### Example Queries

```promql
# Total DNS records managed
sum(catalyst_dns_sync_records_total)

# API error rate (last 5min)
rate(catalyst_dns_sync_api_requests_total{status_code!="200"}[5m])

# P95 API latency
histogram_quantile(0.95,
  rate(catalyst_dns_sync_api_request_duration_seconds_bucket[5m])
)
```

---

## Health Checks

### Liveness Probe

```bash
curl http://localhost:8081/healthz
# Response: {"status":"ok"}
```

Returns 200 if process is running.

### Readiness Probe

```bash
curl http://localhost:8081/readyz
# Response: {"status":"ok","checks":{"kubernetes":"ok","dns":"ok"}}
```

Returns 200 if:

- Kubernetes API is reachable
- DNS API is reachable (or /etc/hosts is writable in dev mode)

---

## Testing

### Manual Test (Dev Mode)

```bash
# 1. Start dev mode
task dev

# 2. Create test Ingress (or use helper task)
task test-ingress

# Or manually:
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

# 3. Check /etc/hosts updated
grep "test.talos00" /etc/hosts

# 4. Delete Ingress
task test-ingress:delete

# 5. Verify entry removed
grep "test.talos00" /etc/hosts || echo "Removed successfully"
```

### Manual Test (Production)

```bash
# 1. Deploy to cluster
task prod:deploy

# 2. Create test Ingress
task test-ingress

# 3. Check DNS resolution
dig @192.168.1.54 test.talos00
# Should return A record: 192.168.1.54

# 4. Check metrics
task metrics
# Then in another terminal: curl http://localhost:8080/metrics | grep catalyst_dns_sync

# 5. Delete and verify cleanup
task test-ingress:delete
dig @192.168.1.54 test.talos00
# Should return NXDOMAIN
```

---

## Deployment

### Prerequisites

- Kubernetes cluster with Traefik Ingress Controller
- Technitium DNS Server (for production mode)
- Prometheus Operator (for metrics scraping)

### Deploy to Cluster

```bash
# 1. Create API token secret
kubectl create secret generic technitium-api-token \
  --from-literal=token=YOUR_TOKEN \
  -n infrastructure

# 2. Build and deploy
task prod:deploy

# 3. Verify deployment
task status

# 4. Check logs
task logs
```

### Verify Prometheus Scraping

```bash
# Check ServiceMonitor
kubectl get servicemonitor -n infrastructure catalyst-dns-sync -o yaml

# In Prometheus UI, query:
up{job="catalyst-dns-sync"}
```

---

## Troubleshooting

### Dev Mode: /etc/hosts not updating

```bash
# Check logs
# Should see: "Running in DEV MODE - will update /etc/hosts"

# Verify sudo access (required for /etc/hosts updates)
sudo -v

# Check Air is running
ps aux | grep air
```

### Production: DNS records not created

```bash
# Check pod logs
task logs

# Describe deployment for issues
task debug:describe

# Check recent events
task debug:events

# Common issues:
# 1. Invalid API token
kubectl get secret technitium-api-token -n infrastructure -o yaml

# 2. DNS server unreachable
task debug:pod
# Inside pod: curl -k https://dns.talos00:5380

# 3. RBAC permissions
kubectl auth can-i get ingressroutes --as=system:serviceaccount:infrastructure:catalyst-dns-sync
```

### Metrics not showing in Prometheus

```bash
# Check ServiceMonitor exists
task status

# Verify metrics endpoint
task metrics
# In another terminal:
curl http://localhost:8080/metrics | grep catalyst_dns_sync
```

---

## Documentation

- [Full Technical Proposal](../docs/proposals/CATALYST-DNS-SYNC-PROPOSAL.md) - Complete design and OP features
- [MVP Definition](../docs/proposals/CATALYST-DNS-SYNC-MVP.md) - Phase 1 & 2 scope and checklist
- [Technitium DNS API Docs](https://github.com/TechnitiumSoftware/DnsServer/blob/master/APIDOCS.md)

---

## Contributing

This project lives in the main `talos-fix` repository and may be extracted to a separate repo later.

### Development Workflow

1. Make changes to code
2. Air auto-rebuilds (in dev mode)
3. Test with local cluster
4. Run checks: `task check` (fmt, vet, test)
5. Build and deploy: `task prod:deploy`
6. View logs: `task logs`

---

## License

MIT

---

## Status

**Phase 1 MVP:** 🚧 In Progress

- [ ] Core CRUD implementation
- [ ] Prometheus metrics
- [ ] Health endpoints
- [ ] Dev mode with Air

**Phase 2:** 📅 Planned

- [ ] Web UI Dashboard
- [ ] Certificate tracking
- [ ] Advanced features

See [MVP checklist](../docs/proposals/CATALYST-DNS-SYNC-MVP.md) for detailed progress.
