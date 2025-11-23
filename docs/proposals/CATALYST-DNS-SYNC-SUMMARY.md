# Catalyst DNS Sync - Project Summary

**Created:** 2025-11-11
**Status:** Ready for Phase 1 Implementation

---

## What We Built

### 1. Complete Technical Proposal ✅

- **File:** `docs/CATALYST-DNS-SYNC-PROPOSAL.md` (1,200+ lines)
- Architecture design with diagrams
- Full API integration details (Technitium DNS)
- Complete feature set including OP features
- Prometheus metrics (7 metrics)
- Structured logging with slog
- Health check endpoints
- Development and production deployment guides

### 2. MVP Definition ✅

- **File:** `docs/CATALYST-DNS-SYNC-MVP.md`
- Clear Phase 1 scope (core features)
- Phase 2 scope (web UI)
- Complete implementation checklist
- Success criteria
- 2-week development timeline
- Command reference guide

### 3. Project Scaffolding ✅

- **Directory:** `catalyst-dns-sync/`
- Project structure created
- `Makefile` with all dev/prod commands
- `.air.toml` for hot reload
- `.gitignore` configured
- `README.md` with quick start guide

---

## Phase 1 MVP Features

### Must Have (Week 1-2)

1. **Full CRUD DNS Sync**
   - Watch Ingress (networking.k8s.io/v1)
   - Watch IngressRoute (traefik.io/v1alpha1)
   - Create DNS A records in Technitium
   - Update records on changes
   - Delete records when Ingress deleted
   - Incremental sync (only change what's needed)

2. **Prometheus Metrics** (`:8080/metrics`)
   - `catalyst_dns_sync_records_total{zone,status}`
   - `catalyst_dns_sync_api_requests_total{endpoint,method,status_code}`
   - `catalyst_dns_sync_api_request_duration_seconds{endpoint,method}`
   - `catalyst_dns_sync_reconcile_duration_seconds{resource_type}`
   - `catalyst_dns_sync_reconcile_errors_total{resource_type,error_type}`
   - `catalyst_dns_sync_ingress_resources{namespace,type}`

3. **Health Endpoints** (`:8081`)
   - `/healthz` - Liveness probe
   - `/readyz` - Readiness probe (K8s + DNS API checks)

4. **Dev Mode with Air**
   - `task dev` → hot reload
   - Updates `/etc/hosts` idempotently
   - Same managed block as `update-hosts.sh`
   - Full metrics/health endpoints
   - No Technitium dependency

5. **Production Deployment**
   - Dockerfile (multi-stage)
   - Kubernetes manifests (Deployment, RBAC, Service, ServiceMonitor)
   - ConfigMap & Secret support
   - Namespace: `infrastructure`

6. **Structured Logging**
   - JSON logs via Go `log/slog`
   - Graylog-ready
   - Contextual fields

---

## Phase 2 Features (Future)

### Web UI Dashboard

- Live DNS records table at `dns.talos00/ui`
- Real-time event stream (SSE)
- Manual override panel (force resync, delete records)
- Built with HTMX + Alpine.js (no build step)

### OP Features

- Auto-wildcard SSL certificate management
- DNS preview environments (`pr-123.app.talos00`)
- Certificate expiration metrics
- DNS drift detection & auto-remediation
- Multi-zone support
- Export/Import CLI
- Grafana dashboard template

---

## Project Structure

```
catalyst-dns-sync/
├── cmd/
│   └── controller/
│       └── main.go              # Entry point (--dev-mode flag)
├── internal/
│   ├── controller/              # Kubernetes controllers
│   │   ├── ingress.go
│   │   └── ingressroute.go
│   ├── dns/                     # DNS clients
│   │   ├── client.go            # Technitium DNS client
│   │   ├── records.go           # CRUD operations
│   │   ├── types.go             # API types
│   │   └── hosts.go             # /etc/hosts manager (dev mode)
│   ├── config/
│   │   └── config.go            # Configuration loading
│   └── metrics/
│       └── metrics.go           # Prometheus metrics
├── k8s/
│   └── base/
│       ├── deployment.yaml
│       ├── rbac.yaml
│       ├── service.yaml
│       ├── servicemonitor.yaml
│       └── kustomization.yaml
├── .air.toml                    # Hot reload config
├── .gitignore
├── Dockerfile
├── Makefile
└── README.md
```

---

## Quick Start Commands

### Development (Local)

```bash
cd catalyst-dns-sync

# First time setup
make install-air
task init

# Start dev mode (updates /etc/hosts)
task dev
```

### Production (Cluster)

```bash
# Build and deploy
task deploy

# Check status
kubectl get deploy -n infrastructure catalyst-dns-sync
kubectl logs -n infrastructure -l app=catalyst-dns-sync -f
```

---

## Key Design Decisions

### 1. Single Repository Initially

- Lives in `talos-fix/catalyst-dns-sync/`
- Can be extracted to separate repo later
- Easier to iterate during development

### 2. Dual Mode Architecture

- **Production:** Updates Technitium DNS via REST API
- **Dev Mode:** Updates `/etc/hosts` for local development
- Same controller logic, different DNS backend

### 3. Air Hot Reload

- Fast iteration during development
- Auto-rebuilds on code changes
- Immediate `/etc/hosts` updates
- No manual restart needed

### 4. Incremental Sync Strategy

- Only modify DNS records that changed
- Preserve non-managed records
- Reduces API calls to DNS server
- Safer than full replacement

### 5. Prometheus-First Observability

- 6 core metrics covering all operations
- ServiceMonitor for auto-scraping
- Ready for Grafana dashboards
- Structured JSON logs for Graylog

---

## Implementation Checklist

See [CATALYST-DNS-SYNC-MVP.md](./CATALYST-DNS-SYNC-MVP.md) for the complete checklist.

### Week 1: Core Implementation

- [ ] Go module initialization
- [ ] Technitium DNS client
- [ ] Hosts file manager (dev mode)
- [ ] Kubernetes controllers (Ingress, IngressRoute)
- [ ] Prometheus metrics
- [ ] Health endpoints
- [ ] Structured logging

### Week 2: Deployment & Production

- [ ] Dockerfile
- [ ] Kubernetes manifests
- [ ] RBAC setup
- [ ] ServiceMonitor
- [ ] Integration testing
- [ ] Documentation
- [ ] Production validation

---

## Success Criteria

### Functional

- [x] Dev mode: `task dev` works
- [ ] Dev mode: Creates/deletes /etc/hosts entries within 5s
- [ ] Prod mode: Deploys successfully to cluster
- [ ] Prod mode: All 16 IngressRoutes get DNS records
- [ ] Prod mode: New/updated/deleted Ingress syncs within 30s

### Observability

- [ ] Prometheus scrapes metrics successfully
- [ ] All 6 metrics present and accurate
- [ ] JSON logs parseable by Graylog
- [ ] Health probes work correctly

### Performance

- [ ] Memory < 50MB
- [ ] CPU < 0.1 core
- [ ] Reconciliation < 5s per Ingress

### Reliability

- [ ] Runs 24hrs without crashes
- [ ] Handles API failures gracefully
- [ ] No orphaned DNS records
- [ ] No duplicate DNS records

---

## Documentation Created

1. ✅ **CATALYST-DNS-SYNC-PROPOSAL.md** - Full technical design (1,200+ lines)
2. ✅ **CATALYST-DNS-SYNC-MVP.md** - Phase 1 & 2 scope with checklist
3. ✅ **CATALYST-DNS-SYNC-SUMMARY.md** - This document
4. ✅ **catalyst-dns-sync/README.md** - Quick start guide

---

## Next Steps

1. **Initialize Go Module**

   ```bash
   cd catalyst-dns-sync
   task init
   ```

2. **Start Implementation**
   - Begin with `internal/dns/client.go` (Technitium client)
   - Then `internal/dns/hosts.go` (dev mode)
   - Then controllers

3. **Test Early**

   ```bash
   task dev  # Test dev mode
   ```

4. **Build & Deploy**

   ```bash
   task deploy  # When ready for cluster testing
   ```

---

## Related Files

- Fixed: `scripts/update-hosts.sh` - Now macOS compatible with `--dry-run` flag
- Docs: Architecture diagrams in proposal
- Docs: Complete API integration guide (Technitium)
- Docs: Prometheus metrics reference
- Docs: Deployment manifests (ready to create)

---

## Questions Answered

### Q: Why not use external-dns?

A: external-dns doesn't support Technitium DNS. This is custom-built for homelab Technitium integration.

### Q: Why two modes (dev/prod)?

A: Dev mode allows local development without DNS server, using /etc/hosts. Same controller logic, different backend.

### Q: Why not cert-manager webhook?

A: Phase 1 focuses on DNS sync only. Certificate integration is Phase 2/3 feature.

### Q: Why Technitium instead of CoreDNS?

A: Existing infrastructure choice. Technitium provides web UI and advanced features.

### Q: Can this be extracted to separate repo?

A: Yes! Designed to be portable. Lives in `talos-fix` initially for rapid iteration.

---

## Resources

- [Technitium DNS API Docs](https://github.com/TechnitiumSoftware/DnsServer/blob/master/APIDOCS.md)
- [Kubernetes controller-runtime](https://github.com/kubernetes-sigs/controller-runtime)
- [Prometheus Go Client](https://github.com/prometheus/client_golang)
- [Go slog Package](https://pkg.go.dev/log/slog)
- [Air - Live Reload](https://github.com/cosmtrek/air)

---

**Status:** 🚀 Ready to start Phase 1 implementation!

**Timeline:** 2 weeks to MVP

**Next Command:** `cd catalyst-dns-sync && task init && task dev`
