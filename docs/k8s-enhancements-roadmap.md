# Kubernetes Enhancements Roadmap

Tracking document for future cluster improvements and tooling additions.

## Priority: High

### Velero - Cluster Backup
- **Purpose:** Backup/restore/migration of cluster resources and PVs
- **Why:** Critical for disaster recovery, no backup solution currently
- **Helm Chart:** `vmware-tanzu/velero`
- **Status:** Not Started
- [ ] Install Velero
- [ ] Configure S3-compatible backend (MinIO or Synology)
- [ ] Set up scheduled backups
- [ ] Test restore procedure

### Kyverno - Policy Engine
- **Purpose:** Validate, mutate, and generate Kubernetes resources
- **Why:** Enforce best practices (labels, resource limits, security contexts)
- **Helm Chart:** `kyverno/kyverno`
- **Status:** Not Started
- [ ] Install Kyverno
- [ ] Create baseline policies (require labels, resource limits)
- [ ] Add security policies (no privileged containers, etc.)

## Priority: Medium

### Reloader - Config Reload Sidecar
- **Purpose:** Auto-restart pods when ConfigMaps/Secrets change
- **Why:** Eliminates manual restarts after config updates
- **Helm Chart:** `stakater/reloader`
- **Status:** Not Started
- [ ] Install Reloader
- [ ] Annotate deployments that need auto-reload

### Loki - Log Aggregation
- **Purpose:** Lightweight log aggregation with Grafana integration
- **Why:** Simpler alternative to Graylog, native Grafana datasource
- **Helm Chart:** `grafana/loki-stack`
- **Status:** Not Started
- [ ] Evaluate vs current Graylog setup
- [ ] Install Loki + Promtail
- [ ] Configure Grafana datasource
- [ ] Create log dashboards

### Trivy Operator - Security Scanning
- **Purpose:** Vulnerability scanning for container images and configs
- **Why:** Identify security issues in running workloads
- **Helm Chart:** `aquasecurity/trivy-operator`
- **Status:** Not Started
- [ ] Install Trivy Operator
- [ ] Configure scan policies
- [ ] Set up alerts for critical vulnerabilities

### cert-manager - TLS Certificates
- **Purpose:** Automated TLS certificate management
- **Why:** Auto-provision and renew certificates (Let's Encrypt)
- **Helm Chart:** `jetstack/cert-manager`
- **Status:** Not Started
- [ ] Install cert-manager
- [ ] Configure ClusterIssuer (Let's Encrypt)
- [ ] Migrate IngressRoutes to use cert-manager

## Priority: Low

### Tempo - Distributed Tracing
- **Purpose:** Trace requests across services
- **Why:** Debug latency issues, understand request flow
- **Helm Chart:** `grafana/tempo`
- **Status:** Not Started

### OpenTelemetry Collector
- **Purpose:** Unified telemetry collection (metrics, logs, traces)
- **Why:** Single collector for all observability data
- **Helm Chart:** `open-telemetry/opentelemetry-collector`
- **Status:** Not Started

### Descheduler
- **Purpose:** Rebalance pods across nodes
- **Why:** Optimize resource distribution (useful when adding nodes)
- **Helm Chart:** `kubernetes-sigs/descheduler`
- **Status:** Not Started

### Keda - Event-Driven Autoscaling
- **Purpose:** Scale based on external metrics/events
- **Why:** Scale on queue depth, cron schedules, custom metrics
- **Helm Chart:** `kedacore/keda`
- **Status:** Not Started

### Kubecost - Cost Analysis
- **Purpose:** Resource cost tracking and optimization
- **Why:** Understand resource usage patterns
- **Helm Chart:** `kubecost/cost-analyzer`
- **Status:** Not Started

### Longhorn - Distributed Storage
- **Purpose:** Cloud-native distributed block storage
- **Why:** HA storage across nodes, built-in backups
- **Helm Chart:** `longhorn/longhorn`
- **Status:** Not Started

### MinIO - Object Storage
- **Purpose:** S3-compatible object storage
- **Why:** Backend for Velero, Loki, artifact storage
- **Helm Chart:** `minio/minio`
- **Status:** Not Started

### Falco - Runtime Security
- **Purpose:** Runtime threat detection
- **Why:** Detect suspicious activity in containers
- **Helm Chart:** `falcosecurity/falco`
- **Status:** Not Started

### Renovate - Dependency Updates
- **Purpose:** Automated dependency/image updates via PRs
- **Why:** Keep helm charts and images up to date
- **Deployment:** GitHub App or self-hosted
- **Status:** Not Started

## Already Implemented

- [x] Flux CD - GitOps
- [x] ArgoCD - GitOps (for specific apps)
- [x] kube-prometheus-stack - Monitoring
- [x] Traefik - Ingress
- [x] External Secrets Operator - Secret management
- [x] Goldilocks/VPA - Resource recommendations
- [x] Graylog/OpenSearch - Logging
- [x] Fluent Bit - Log collection
- [x] Linkerd - Service mesh
- [x] Headlamp, Kubeview, Kube-ops-view - Cluster visualization

## Notes

- Consider MinIO as prerequisite for Velero and Loki
- Loki could potentially replace Graylog for simpler setup
- cert-manager enables automatic HTTPS for all services
- Kyverno policies should be audit-mode first before enforce
