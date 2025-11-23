# Catalyst DNS Sync - Technical Proposal

**Version:** 1.0
**Status:** Approved - Implementation in Progress
**Author:** System Architecture
**Date:** 2025-11-11
**MVP Definition:** See [CATALYST-DNS-SYNC-MVP.md](proposals/CATALYST-DNS-SYNC-MVP.md)

## Executive Summary

A lightweight Kubernetes-native Go daemon that automatically synchronizes Traefik IngressRoute and standard Ingress resources to Technitium DNS server, eliminating manual `/etc/hosts` management and providing homelab-wide DNS resolution for all services.

**Current Focus:** Phase 1 MVP - Core CRUD sync, Prometheus metrics, health endpoints, and dev mode with local hosts file watcher.

---

## 1. Overview

### 1.1 Purpose

The `catalyst-dns-sync` daemon continuously monitors Kubernetes Ingress resources and maintains corresponding DNS A records in a Technitium DNS server, ensuring that all services are accessible cluster-wide and from external clients using human-readable hostnames.

### 1.2 Problem Statement

Currently, accessing services requires either:

- Manual `/etc/hosts` updates on each client (not scalable)
- Running scripts to sync DNS entries (manual, error-prone)
- Remembering IP addresses and ports (poor UX)

### 1.3 Solution

A Kubernetes controller that:

- Watches Ingress/IngressRoute/HTTPRoute resources
- Creates DNS A records pointing to the Traefik load balancer IP
- Updates records when hostnames change
- Deletes records when Ingresses are removed
- Provides observability through logs and metrics

---

## 2. Architecture

### 2.1 Component Design

```
┌─────────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                        │
│                                                              │
│  ┌────────────────┐         ┌──────────────────────┐        │
│  │ IngressRoute   │◄────────┤  catalyst-dns-sync   │        │
│  │   Resources    │  Watch  │      Deployment      │        │
│  └────────────────┘         │                      │        │
│                             │  - Controller Loop   │        │
│  ┌────────────────┐         │  - Reconciler        │        │
│  │    Ingress     │◄────────┤  - DNS Client        │        │
│  │   Resources    │  Watch  │  - Metrics Server    │        │
│  └────────────────┘         └──────────┬───────────┘        │
│                                        │                     │
│  ┌────────────────┐                    │                     │
│  │   HTTPRoute    │◄───────────────────┘                     │
│  │   Resources    │         Watch                           │
│  └────────────────┘                                          │
│                                                              │
│  ┌────────────────┐         ┌──────────────────────┐        │
│  │  Prometheus    │◄────────┤  ServiceMonitor      │        │
│  │                │  Scrape │  (catalyst-dns-sync) │        │
│  └────────────────┘         └──────────────────────┘        │
│                                                              │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTPS API Calls
                               │ (Create/Update/Delete DNS)
                               ▼
                    ┌──────────────────────┐
                    │  Technitium DNS      │
                    │      Server          │
                    │  (192.168.1.x:5380)  │
                    └──────────────────────┘
```

### 2.2 Technology Stack

- **Language:** Go 1.23+
- **Framework:** controller-runtime (Kubernetes controller framework)
- **Logging:** slog (Go structured logging)
- **Metrics:** Prometheus/client_golang
- **DNS Client:** net/http (Technitium REST API)
- **Dependencies:**
  - `k8s.io/client-go` - Kubernetes client
  - `k8s.io/apimachinery` - Kubernetes types
  - `sigs.k8s.io/controller-runtime` - Controller framework
  - `github.com/prometheus/client_golang` - Prometheus metrics

### 2.3 Deployment Model

- **Type:** Kubernetes Deployment (single replica)
- **Namespace:** `infrastructure`
- **ServiceAccount:** `catalyst-dns-sync` with RBAC for Ingress resources
- **ConfigMap:** DNS server configuration, zone name, TTL defaults
- **Secret:** Technitium API token

---

## 3. Functional Requirements

### 3.1 Resource Watching

The daemon MUST watch the following Kubernetes resources:

| Resource Type | API Group                 | Version  | Watch Scope    |
| ------------- | ------------------------- | -------- | -------------- |
| Ingress       | networking.k8s.io         | v1       | All namespaces |
| IngressRoute  | traefik.io                | v1alpha1 | All namespaces |
| HTTPRoute     | gateway.networking.k8s.io | v1beta1  | All namespaces |

### 3.2 DNS Record Management

#### 3.2.1 Record Creation

When an Ingress/IngressRoute is created:

1. Extract all hostnames from `spec.rules[].host` or `spec.routes[].match`
2. Filter hostnames matching configured DNS zone (e.g., `*.talos00`)
3. Call Technitium API `/api/zones/records/add` for each hostname
4. Create A record pointing to Traefik load balancer IP (192.168.1.54)
5. Set TTL from annotation or default configuration

**Example:**

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: grafana
  namespace: monitoring
  annotations:
    catalyst-dns-sync.io/ttl: '300' # Optional TTL override
spec:
  routes:
    - match: Host(`grafana.talos00`)
      services:
        - name: grafana
          port: 3000
```

Creates DNS record:

```
grafana.talos00 A 192.168.1.54 (TTL: 300)
```

#### 3.2.2 Record Updates

When an Ingress/IngressRoute is updated:

1. Compare old and new hostnames
2. Delete removed hostnames via `/api/zones/records/delete`
3. Add new hostnames via `/api/zones/records/add`
4. Update TTL if annotation changed

**Incremental Sync Strategy:**

- Only modify DNS records that have changed
- Preserve existing records not managed by this controller
- Use metadata labels to track managed resources

#### 3.2.3 Record Deletion

When an Ingress/IngressRoute is deleted:

1. Extract all hostnames from deleted resource
2. Call `/api/zones/records/delete` for each hostname
3. Log deletion operation

### 3.3 Configuration

#### 3.3.1 Environment Variables

```bash
# DNS Server Configuration
DNS_SERVER_URL=https://dns.talos00:5380
DNS_ZONE=talos00
DNS_IP_ADDRESS=192.168.1.54  # Traefik LB IP
DNS_TTL_DEFAULT=300          # 5 minutes

# Kubernetes Configuration
WATCH_NAMESPACE=             # Empty = all namespaces
LEADER_ELECTION=false        # Enable for HA (future)

# Logging Configuration
LOG_LEVEL=info               # debug, info, warn, error
LOG_FORMAT=json              # json or text

# Metrics Configuration
METRICS_BIND_ADDRESS=:8080
HEALTH_PROBE_ADDRESS=:8081
```

#### 3.3.2 Kubernetes Secret (API Token)

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: technitium-api-token
  namespace: infrastructure
type: Opaque
stringData:
  token: 'your-technitium-api-token-here'
```

#### 3.3.3 ConfigMap (Optional Overrides)

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: catalyst-dns-sync-config
  namespace: infrastructure
data:
  dns-server-url: 'https://dns.talos00:5380'
  dns-zone: 'talos00'
  dns-ip-address: '192.168.1.54'
  ttl-default: '300'
```

---

## 4. Non-Functional Requirements

### 4.1 Observability

#### 4.1.1 Structured Logging (slog)

All logs MUST use Go's `log/slog` package with structured fields:

```go
logger.Info("DNS record created",
    slog.String("hostname", "grafana.talos00"),
    slog.String("ip", "192.168.1.54"),
    slog.Int("ttl", 300),
    slog.String("namespace", "monitoring"),
    slog.String("resource", "IngressRoute/grafana"))
```

**Log Levels:**

- **DEBUG:** Controller loop iterations, API request/response details
- **INFO:** Record creation, updates, deletions (default)
- **WARN:** Retryable errors, DNS API failures
- **ERROR:** Unrecoverable errors, panics

**Log Format:**

- **JSON:** Default for machine parsing (Graylog)
- **Text:** Optional for local development

#### 4.1.2 Prometheus Metrics

Expose metrics on `:8080/metrics` for Prometheus scraping:

| Metric Name                                      | Type      | Description                       | Labels                                     |
| ------------------------------------------------ | --------- | --------------------------------- | ------------------------------------------ |
| `catalyst_dns_sync_records_total`                | Counter   | Total DNS records managed         | `zone`, `status` (created/updated/deleted) |
| `catalyst_dns_sync_api_requests_total`           | Counter   | Technitium API calls              | `endpoint`, `method`, `status_code`        |
| `catalyst_dns_sync_api_request_duration_seconds` | Histogram | API request latency               | `endpoint`, `method`                       |
| `catalyst_dns_sync_reconcile_duration_seconds`   | Histogram | Controller reconciliation time    | `resource_type`                            |
| `catalyst_dns_sync_reconcile_errors_total`       | Counter   | Reconciliation errors             | `resource_type`, `error_type`              |
| `catalyst_dns_sync_ingress_resources`            | Gauge     | Current Ingress resources watched | `namespace`, `type`                        |
| `catalyst_dns_sync_build_info`                   | Gauge     | Build version info                | `version`, `commit`, `go_version`          |

**ServiceMonitor for Prometheus:**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: catalyst-dns-sync
  namespace: infrastructure
spec:
  selector:
    matchLabels:
      app: catalyst-dns-sync
  endpoints:
    - port: metrics
      interval: 30s
      path: /metrics
```

#### 4.1.3 Graylog Integration

Send structured JSON logs to Graylog via GELF UDP/TCP:

**Option 1: Fluent Bit Sidecar**

- Fluent Bit reads container logs
- Parses JSON and forwards to Graylog

**Option 2: Direct GELF Logging** (future enhancement)

- Use Go GELF library
- Send logs directly to Graylog GELF input

**Log Fields for Graylog:**

```json
{
  "timestamp": "2025-11-11T20:00:00Z",
  "level": "info",
  "msg": "DNS record created",
  "hostname": "grafana.talos00",
  "ip": "192.168.1.54",
  "ttl": 300,
  "namespace": "monitoring",
  "resource": "IngressRoute/grafana",
  "app": "catalyst-dns-sync",
  "version": "v1.0.0"
}
```

### 4.2 Performance

- **Reconciliation Interval:** Event-driven (immediate) with 5-minute resync
- **API Rate Limiting:** Max 10 req/sec to Technitium DNS
- **Memory Footprint:** < 50MB under normal load
- **CPU Usage:** < 0.1 core under normal load

### 4.3 Reliability

- **Retry Logic:** Exponential backoff for failed DNS API calls (1s, 2s, 4s, 8s, max 30s)
- **Error Handling:** Graceful degradation, log errors but continue processing
- **Health Checks:**
  - `/healthz` - Liveness probe (process running)
  - `/readyz` - Readiness probe (Kubernetes API reachable + DNS API reachable)

### 4.4 Security

- **RBAC:** Least-privilege ServiceAccount (read Ingress/IngressRoute only)
- **API Token:** Stored in Kubernetes Secret, mounted as env var
- **TLS:** Use HTTPS for Technitium API calls
- **Network Policy:** Allow egress to DNS server only

---

## 5. Implementation Plan

### 5.1 Project Structure

**Location:** `catalyst-dns-sync/` (in this repository, can be extracted to separate repo later)

```
catalyst-dns-sync/
├── cmd/
│   └── controller/
│       └── main.go              # Entry point (supports --dev-mode flag)
├── internal/
│   ├── controller/
│   │   ├── ingress.go           # Ingress controller
│   │   ├── ingressroute.go      # IngressRoute controller
│   │   └── httproute.go         # HTTPRoute controller
│   ├── dns/
│   │   ├── client.go            # Technitium DNS client
│   │   ├── records.go           # Record CRUD operations
│   │   ├── types.go             # DNS API types
│   │   └── hosts.go             # /etc/hosts file manager (dev mode)
│   ├── config/
│   │   └── config.go            # Configuration loading
│   └── metrics/
│       └── metrics.go           # Prometheus metrics setup
├── k8s/
│   ├── base/
│   │   ├── deployment.yaml      # Deployment manifest
│   │   ├── rbac.yaml            # ServiceAccount, Role, RoleBinding
│   │   ├── service.yaml         # Service for metrics
│   │   ├── servicemonitor.yaml  # Prometheus ServiceMonitor
│   │   └── kustomization.yaml
│   └── overlays/
│       └── production/
│           └── kustomization.yaml
├── .air.toml                    # Air live reload config for dev mode
├── go.mod
├── go.sum
├── Dockerfile
├── Makefile
└── README.md
```

### 5.2 Development Modes

#### 5.2.1 Production Mode (Default)

Runs as Kubernetes controller, updates Technitium DNS server:

```bash
# In cluster
./catalyst-dns-sync

# Local testing (pointing to cluster)
KUBECONFIG=~/.kube/config \
DNS_SERVER_URL=https://dns.talos00:5380 \
DNS_API_TOKEN=xxx \
./catalyst-dns-sync
```

#### 5.2.2 Dev Mode (Local Development)

**Purpose:** Local development without Technitium DNS server - updates `/etc/hosts` instead.

**Activation:**

```bash
# Use Air for hot reload during development
air

# Or run directly with dev mode flag
./catalyst-dns-sync --dev-mode
```

**Behavior:**

- Watches Kubernetes Ingress/IngressRoute resources
- Extracts hostnames matching `DNS_ZONE` (default: `talos00`)
- **Updates `/etc/hosts` idempotently** using managed block (same as `update-hosts.sh`)
- Hot reloads on code changes (via Air)
- Logs to console in human-readable format

**Example `/etc/hosts` output:**

```bash
# BEGIN CATALYST-DNS-SYNC MANAGED BLOCK
# Auto-generated by catalyst-dns-sync (dev mode)
# Managed by catalyst-dns-sync - DO NOT EDIT MANUALLY
#
192.168.1.54  alertmanager.talos00
192.168.1.54  argocd.talos00
192.168.1.54  grafana.talos00
# ... all 16 hostnames
# Total entries: 16
# END CATALYST-DNS-SYNC MANAGED BLOCK
```

**Dev Mode Features:**

- No Technitium API calls (offline development)
- Immediate feedback via Air hot reload
- Uses same reconciliation logic as production
- Metrics still exposed on `:8080/metrics`
- `/etc/hosts` updates are atomic and safe

#### 5.2.3 Air Configuration (`.air.toml`)

```toml
root = "."
testdata_dir = "testdata"
tmp_dir = "tmp"

[build]
  args_bin = ["--dev-mode"]
  bin = "./tmp/main"
  cmd = "go build -o ./tmp/main ./cmd/controller"
  delay = 1000
  exclude_dir = ["assets", "tmp", "vendor", "testdata", "k8s"]
  exclude_file = []
  exclude_regex = ["_test.go"]
  exclude_unchanged = false
  follow_symlink = false
  full_bin = ""
  include_dir = []
  include_ext = ["go", "tpl", "tmpl", "html"]
  include_file = []
  kill_delay = "0s"
  log = "build-errors.log"
  poll = false
  poll_interval = 0
  rerun = false
  rerun_delay = 500
  send_interrupt = false
  stop_on_error = false

[color]
  app = ""
  build = "yellow"
  main = "magenta"
  runner = "green"
  watcher = "cyan"

[log]
  main_only = false
  time = false

[misc]
  clean_on_exit = false

[screen]
  clear_on_rebuild = false
  keep_scroll = true
```

**Usage:**

```bash
# Install Air
go install github.com/cosmtrek/air@latest

# Start dev mode with hot reload
cd catalyst-dns-sync
air

# Make code changes, Air auto-rebuilds and restarts
# /etc/hosts updates automatically
```

#### 5.2.4 Dev Mode Implementation

**File:** `internal/dns/hosts.go`

```go
package dns

import (
    "bufio"
    "fmt"
    "os"
    "os/exec"
    "strings"
    "time"
)

const (
    startMarker = "# BEGIN CATALYST-DNS-SYNC MANAGED BLOCK"
    endMarker   = "# END CATALYST-DNS-SYNC MANAGED BLOCK"
    hostsFile   = "/etc/hosts"
)

type HostsFileManager struct {
    nodeIP string
    zone   string
}

func NewHostsFileManager(nodeIP, zone string) *HostsFileManager {
    return &HostsFileManager{
        nodeIP: nodeIP,
        zone:   zone,
    }
}

// UpdateHostsFile idempotently updates /etc/hosts with DNS entries
func (h *HostsFileManager) UpdateHostsFile(hostnames []string) error {
    // Generate managed block content
    var block strings.Builder
    block.WriteString(startMarker + "\n")
    block.WriteString(fmt.Sprintf("# Auto-generated by catalyst-dns-sync (dev mode) on %s\n", time.Now().Format(time.RFC3339)))
    block.WriteString("# Managed by catalyst-dns-sync - DO NOT EDIT MANUALLY\n")
    block.WriteString("#\n")

    if len(hostnames) == 0 {
        block.WriteString("# No Ingress resources found\n")
    } else {
        for _, hostname := range hostnames {
            block.WriteString(fmt.Sprintf("%s  %s\n", h.nodeIP, hostname))
        }
        block.WriteString(fmt.Sprintf("\n# Total entries: %d\n", len(hostnames)))
    }

    block.WriteString(endMarker + "\n")

    // Read current /etc/hosts
    content, err := os.ReadFile(hostsFile)
    if err != nil {
        return fmt.Errorf("failed to read %s: %w", hostsFile, err)
    }

    // Remove existing managed block
    var newContent strings.Builder
    inBlock := false
    scanner := bufio.NewScanner(strings.NewReader(string(content)))
    for scanner.Scan() {
        line := scanner.Text()
        if strings.Contains(line, startMarker) {
            inBlock = true
            continue
        }
        if strings.Contains(line, endMarker) {
            inBlock = false
            continue
        }
        if !inBlock {
            newContent.WriteString(line + "\n")
        }
    }

    // Append new managed block
    newContent.WriteString(block.String())

    // Write to temporary file
    tmpFile, err := os.CreateTemp("", "hosts-*")
    if err != nil {
        return fmt.Errorf("failed to create temp file: %w", err)
    }
    defer os.Remove(tmpFile.Name())

    if _, err := tmpFile.WriteString(newContent.String()); err != nil {
        return fmt.Errorf("failed to write temp file: %w", err)
    }
    tmpFile.Close()

    // Copy to /etc/hosts using sudo
    cmd := exec.Command("sudo", "cp", tmpFile.Name(), hostsFile)
    if output, err := cmd.CombinedOutput(); err != nil {
        return fmt.Errorf("failed to update %s: %w (output: %s)", hostsFile, err, string(output))
    }

    return nil
}
```

**File:** `cmd/controller/main.go` (excerpt)

```go
var (
    devMode = flag.Bool("dev-mode", false, "Run in dev mode (update /etc/hosts instead of DNS server)")
)

func main() {
    flag.Parse()

    cfg := loadConfig()

    var dnsClient DNSClient
    if *devMode {
        log.Info("Running in DEV MODE - will update /etc/hosts")
        dnsClient = dns.NewHostsFileManager(cfg.NodeIP, cfg.Zone)
    } else {
        log.Info("Running in PRODUCTION MODE - will update Technitium DNS")
        dnsClient = dns.NewTechnitiumClient(cfg.DNSServerURL, cfg.APIToken)
    }

    // ... rest of controller setup
}
```

### 5.3 Development Workflow

```bash
# 1. Clone repo and navigate to project
cd ~/talos-fix/catalyst-dns-sync

# 2. Install dependencies
go mod download

# 3. Start dev mode with hot reload
air

# Terminal output:
#   [INFO] Running in DEV MODE - will update /etc/hosts
#   [INFO] Watching Ingress resources in all namespaces
#   [INFO] Found 16 IngressRoute resources
#   [INFO] Updated /etc/hosts with 16 hostnames
#   [INFO] Metrics server listening on :8080
#
# 4. Make code changes, Air auto-rebuilds
# 5. /etc/hosts automatically updated
# 6. Check logs and metrics:
#    - curl localhost:8080/metrics
#    - curl localhost:8080/ui (Web dashboard)
```

### 5.4 Task Commands

Using [Task](https://taskfile.dev) for task automation:

```bash
# Show all available tasks
task

# Development
task dev          # Start dev mode with hot reload
task build        # Build binary
task test         # Run tests
task check        # Run fmt, vet, test

# Production
task docker       # Build Docker image
task push         # Push to local registry
task deploy       # Deploy to cluster
task prod:deploy  # Full pipeline (build, push, deploy, status)

# Utilities
task logs         # View pod logs
task status       # Check deployment status
task metrics      # Port-forward metrics endpoint
task health       # Port-forward health endpoint
task debug:pod    # Exec into pod
```

**Quick Start:**

```bash
# Development with hot reload
task dev:setup  # One-time setup
task dev        # Start dev mode

# Build and deploy to cluster
task prod:deploy
```

---

### 5.5 Development Phases

#### Phase 1: Core Controller (Week 1)

- [x] Project scaffolding with Go modules
- [ ] Kubernetes controller-runtime setup
- [ ] Ingress resource watcher
- [ ] IngressRoute resource watcher
- [ ] Basic reconciliation loop

#### Phase 2: DNS Integration (Week 2)

- [ ] Technitium DNS client implementation
- [ ] A record creation via `/api/zones/records/add`
- [ ] A record deletion via `/api/zones/records/delete`
- [ ] Error handling and retries

#### Phase 3: Observability (Week 3)

- [ ] Structured logging with slog
- [ ] Prometheus metrics implementation
- [ ] Health/readiness probes
- [ ] ServiceMonitor for Prometheus

#### Phase 4: Kubernetes Deployment (Week 4)

- [ ] Dockerfile with multi-stage build
- [ ] Kubernetes manifests (Deployment, RBAC, ConfigMap, Secret)
- [ ] Kustomize overlays
- [ ] Integration testing in cluster

#### Phase 5: Advanced Features (Future)

- [ ] HTTPRoute (Gateway API) support
- [ ] Leader election for HA
- [ ] GELF logging to Graylog
- [ ] Annotation-based TTL overrides
- [ ] Webhook validation for Ingress resources

---

## 6. API Integration Details

### 6.1 Technitium DNS API

**Base URL:** `https://dns.talos00:5380`

#### 6.1.1 Add A Record

```http
POST /api/zones/records/add
Content-Type: application/x-www-form-urlencoded

token=YOUR_API_TOKEN
&zone=talos00
&type=A
&name=grafana
&ipAddress=192.168.1.54
&ttl=300
```

**Response:**

```json
{
  "status": "ok"
}
```

#### 6.1.2 Delete A Record

```http
POST /api/zones/records/delete
Content-Type: application/x-www-form-urlencoded

token=YOUR_API_TOKEN
&zone=talos00
&type=A
&name=grafana
```

**Response:**

```json
{
  "status": "ok"
}
```

#### 6.1.3 Error Handling

```json
{
  "status": "error",
  "errorMessage": "Zone not found: talos00"
}
```

**Common Error Codes:**

- `401` - Invalid API token
- `404` - Zone or record not found
- `500` - Internal DNS server error

### 6.2 Go DNS Client Example

```go
type DNSClient struct {
    baseURL    string
    token      string
    httpClient *http.Client
    logger     *slog.Logger
    metrics    *Metrics
}

func (c *DNSClient) AddARecord(ctx context.Context, zone, name, ip string, ttl int) error {
    start := time.Now()
    defer func() {
        c.metrics.APIRequestDuration.WithLabelValues("/api/zones/records/add", "POST").Observe(time.Since(start).Seconds())
    }()

    data := url.Values{
        "token":     {c.token},
        "zone":      {zone},
        "type":      {"A"},
        "name":      {name},
        "ipAddress": {ip},
        "ttl":       {fmt.Sprintf("%d", ttl)},
    }

    resp, err := c.httpClient.PostForm(c.baseURL+"/api/zones/records/add", data)
    if err != nil {
        c.metrics.APIRequestsTotal.WithLabelValues("/api/zones/records/add", "POST", "error").Inc()
        return fmt.Errorf("failed to add DNS record: %w", err)
    }
    defer resp.Body.Close()

    if resp.StatusCode != http.StatusOK {
        c.metrics.APIRequestsTotal.WithLabelValues("/api/zones/records/add", "POST", fmt.Sprintf("%d", resp.StatusCode)).Inc()
        return fmt.Errorf("DNS API returned status %d", resp.StatusCode)
    }

    c.metrics.APIRequestsTotal.WithLabelValues("/api/zones/records/add", "POST", "200").Inc()
    c.metrics.RecordsTotal.WithLabelValues(zone, "created").Inc()

    c.logger.Info("DNS A record created",
        slog.String("zone", zone),
        slog.String("name", name),
        slog.String("ip", ip),
        slog.Int("ttl", ttl))

    return nil
}
```

---

## 7. Deployment Configuration

### 7.1 RBAC Manifest

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: catalyst-dns-sync
  namespace: infrastructure
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: catalyst-dns-sync
rules:
  - apiGroups: ['networking.k8s.io']
    resources: ['ingresses']
    verbs: ['get', 'list', 'watch']
  - apiGroups: ['traefik.io']
    resources: ['ingressroutes']
    verbs: ['get', 'list', 'watch']
  - apiGroups: ['gateway.networking.k8s.io']
    resources: ['httproutes']
    verbs: ['get', 'list', 'watch']
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: catalyst-dns-sync
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: catalyst-dns-sync
subjects:
  - kind: ServiceAccount
    name: catalyst-dns-sync
    namespace: infrastructure
```

### 7.2 Deployment Manifest

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: catalyst-dns-sync
  namespace: infrastructure
  labels:
    app: catalyst-dns-sync
spec:
  replicas: 1
  selector:
    matchLabels:
      app: catalyst-dns-sync
  template:
    metadata:
      labels:
        app: catalyst-dns-sync
      annotations:
        prometheus.io/scrape: 'true'
        prometheus.io/port: '8080'
        prometheus.io/path: '/metrics'
    spec:
      serviceAccountName: catalyst-dns-sync
      containers:
        - name: controller
          image: localhost:5000/catalyst-dns-sync:latest
          imagePullPolicy: Always
          env:
            - name: DNS_SERVER_URL
              value: 'https://dns.talos00:5380'
            - name: DNS_ZONE
              value: 'talos00'
            - name: DNS_IP_ADDRESS
              value: '192.168.1.54'
            - name: DNS_TTL_DEFAULT
              value: '300'
            - name: DNS_API_TOKEN
              valueFrom:
                secretKeyRef:
                  name: technitium-api-token
                  key: token
            - name: LOG_LEVEL
              value: 'info'
            - name: LOG_FORMAT
              value: 'json'
          ports:
            - containerPort: 8080
              name: metrics
              protocol: TCP
            - containerPort: 8081
              name: health
              protocol: TCP
          livenessProbe:
            httpGet:
              path: /healthz
              port: health
            initialDelaySeconds: 15
            periodSeconds: 20
          readinessProbe:
            httpGet:
              path: /readyz
              port: health
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 200m
              memory: 128Mi
```

### 7.3 Service Manifest

```yaml
apiVersion: v1
kind: Service
metadata:
  name: catalyst-dns-sync
  namespace: infrastructure
  labels:
    app: catalyst-dns-sync
spec:
  selector:
    app: catalyst-dns-sync
  ports:
    - name: metrics
      port: 8080
      targetPort: metrics
    - name: health
      port: 8081
      targetPort: health
```

---

## 8. Testing Strategy

### 8.1 Unit Tests

- DNS client mock testing
- Controller reconciliation logic
- Hostname extraction from Ingress specs

### 8.2 Integration Tests

- Deploy test Ingress/IngressRoute
- Verify DNS record creation
- Delete Ingress, verify DNS cleanup
- Update Ingress hostname, verify DNS update

### 8.3 Load Testing

- Create 100 Ingress resources
- Measure reconciliation time
- Monitor memory/CPU usage
- Verify all DNS records created

---

## 9. Monitoring & Alerting

### 9.1 Prometheus Alerts

```yaml
groups:
  - name: catalyst-dns-sync
    rules:
      - alert: DNSSyncHighErrorRate
        expr: rate(catalyst_dns_sync_reconcile_errors_total[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: 'DNS sync experiencing high error rate'
          description: '{{ $value }} errors/sec in namespace {{ $labels.namespace }}'

      - alert: DNSSyncAPIFailures
        expr: rate(catalyst_dns_sync_api_requests_total{status_code!="200"}[5m]) > 0.5
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: 'Technitium DNS API failures detected'
          description: '{{ $value }} failed API calls/sec to {{ $labels.endpoint }}'

      - alert: DNSSyncControllerDown
        expr: up{job="catalyst-dns-sync"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: 'DNS sync controller is down'
```

### 9.2 Grafana Dashboard

Create dashboard with:

- DNS records managed (gauge)
- API request rate (graph)
- Reconciliation latency (heatmap)
- Error rate (graph)
- Top namespaces by Ingress count (table)

---

## 10. Migration Path

### 10.1 From Manual /etc/hosts

1. Deploy `catalyst-dns-sync` with dry-run mode (log only, no DNS changes)
2. Verify logs show correct hostnames extracted
3. Enable DNS writes
4. Verify DNS records created in Technitium
5. Test DNS resolution from client machines
6. Remove manual `/etc/hosts` entries

### 10.2 Rollback Plan

If DNS sync fails:

1. Scale deployment to 0 replicas
2. Manually delete DNS records via Technitium web UI
3. Revert to `/etc/hosts` management scripts
4. Debug and fix issues
5. Redeploy with fixes

---

## 11. OP Features 🚀

### 11.1 Auto-Wildcard SSL Certificate Management

**Problem:** Managing individual certificates for 16+ services is tedious and error-prone.

**Solution:** Automatically create and maintain a wildcard certificate (`*.talos00`) shared across all Ingresses.

**Implementation:**

```yaml
# Auto-created by catalyst-dns-sync on first IngressRoute detection
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: wildcard-talos00
  namespace: traefik
spec:
  secretName: wildcard-talos00-tls
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
    - '*.talos00'
    - 'talos00'
```

**Features:**

- Detect first Ingress creation, auto-create wildcard cert if missing
- Monitor cert expiration via cert-manager
- Export cert expiration metrics to Prometheus
- Auto-update Traefik default certificate to use wildcard

**Metrics:**

```go
catalyst_dns_sync_certificate_expiry_seconds{cert="wildcard-talos00"} 2592000
catalyst_dns_sync_certificate_status{cert="wildcard-talos00",status="ready"} 1
```

### 11.2 DNS Preview Environments (GitOps Integration)

**Problem:** Testing PRs requires manual DNS setup or port-forwarding.

**Solution:** Automatically create preview DNS entries for ephemeral environments.

**Use Case:**

```yaml
# ArgoCD ApplicationSet creates preview app
apiVersion: v1
kind: Namespace
metadata:
  name: app-pr-123
  annotations:
    catalyst-dns-sync.io/preview: 'true'
    catalyst-dns-sync.io/base-hostname: 'myapp'
---
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: myapp-preview
  namespace: app-pr-123
  labels:
    preview: 'pr-123'
spec:
  routes:
    - match: Host(`pr-123.myapp.talos00`) # Auto-generated!
```

**DNS Pattern:**

- `pr-123.myapp.talos00` → 192.168.1.54
- `pr-456.api.talos00` → 192.168.1.54
- `staging.grafana.talos00` → 192.168.1.54

**Auto-Cleanup:**

- Namespace deleted → DNS record removed within 30s
- TTL set to 60s for preview envs (fast updates)

**Metrics:**

```go
catalyst_dns_sync_preview_environments_total{namespace="app-pr-123",status="active"} 1
```

### 11.3 Web UI Dashboard (Embedded in Controller)

**Problem:** Need visibility into DNS sync status without querying Prometheus.

**Solution:** Lightweight web UI served from controller on `:8080/ui`.

**Features:**

1. **DNS Records Table:**

   ```
   ┌──────────────────────────────────────────────────────────────────┐
   │ Hostname              │ IP            │ TTL │ Source            │
   ├──────────────────────────────────────────────────────────────────┤
   │ grafana.talos00       │ 192.168.1.54  │ 300 │ IngressRoute/...  │
   │ argocd.talos00        │ 192.168.1.54  │ 300 │ IngressRoute/...  │
   │ pr-123.myapp.talos00  │ 192.168.1.54  │ 60  │ IngressRoute/...  │
   └──────────────────────────────────────────────────────────────────┘
   ```

2. **Sync Status:**
   - Last reconciliation time
   - API success/failure rate (last 5 min)
   - Pending operations queue

3. **Manual Override Panel:**
   - Force resync all DNS records
   - Delete specific DNS record
   - Create custom DNS entry (not managed by Ingress)

4. **Real-time Event Stream (WebSocket):**

   ```
   [20:45:32] ✅ Created DNS record: grafana.talos00
   [20:45:35] ⚠️  API retry (attempt 2/5): prometheus.talos00
   [20:45:40] 🗑️  Deleted DNS record: old-app.talos00
   ```

**Tech Stack:**

- Backend: Go `net/http` + `gorilla/mux`
- Frontend: Single HTML file with HTMX + Alpine.js (no build step!)
- Styling: Tailwind CSS via CDN
- Real-time: Server-Sent Events (SSE) for log streaming

**Deployment:**

```yaml
# Expose UI via Traefik
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: dns-sync-ui
  namespace: infrastructure
spec:
  routes:
    - match: Host(`dns.talos00`)
      services:
        - name: catalyst-dns-sync
          port: 8080
```

**Access:** https://dns.talos00/ui

### 11.4 Certificate Status Metrics (cert-manager Integration)

**Problem:** Need to know when certs will expire and if renewals are failing.

**Solution:** Watch `Certificate` resources and export expiration/status metrics.

**Metrics:**

```promql
# Days until certificate expires
catalyst_dns_sync_certificate_expiry_days{
  name="wildcard-talos00",
  namespace="traefik",
  issuer="letsencrypt-prod"
} 89

# Certificate ready status (1 = ready, 0 = not ready)
catalyst_dns_sync_certificate_ready{
  name="wildcard-talos00",
  namespace="traefik"
} 1

# Certificate renewal failures
catalyst_dns_sync_certificate_renewal_failures_total{
  name="wildcard-talos00",
  reason="dns01_challenge_failed"
} 0
```

**Prometheus Alerts:**

```yaml
- alert: CertificateExpiringSoon
  expr: catalyst_dns_sync_certificate_expiry_days < 14
  labels:
    severity: warning
  annotations:
    summary: 'Certificate {{ $labels.name }} expires in {{ $value }} days'

- alert: CertificateNotReady
  expr: catalyst_dns_sync_certificate_ready == 0
  for: 10m
  labels:
    severity: critical
  annotations:
    summary: 'Certificate {{ $labels.name }} is not ready'
```

**RBAC Addition:**

```yaml
# Add to ClusterRole
- apiGroups: ['cert-manager.io']
  resources: ['certificates']
  verbs: ['get', 'list', 'watch']
```

### 11.5 Additional OP Enhancements

#### 11.5.1 Smart Reconciliation

**Adaptive Sync Interval:**

- High activity (>10 changes/min): 15s reconciliation
- Normal activity: 5min reconciliation
- No changes for 1hr: 30min reconciliation

**Reduces:**

- API calls to Technitium by 80%
- CPU usage during idle periods
- Network traffic

#### 11.5.2 DNS Record Annotations

Support rich metadata on Ingresses:

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: grafana
  annotations:
    catalyst-dns-sync.io/ttl: '60' # Override TTL
    catalyst-dns-sync.io/priority: 'high' # Sync priority
    catalyst-dns-sync.io/description: 'Grafana Monitoring Dashboard'
    catalyst-dns-sync.io/owner: 'platform-team'
    catalyst-dns-sync.io/slack-notify: 'true' # Notify on DNS changes
```

#### 11.5.3 DNS Drift Detection

**Problem:** Someone manually edits DNS records in Technitium UI.

**Solution:** Periodic drift detection comparing cluster state vs DNS state.

**Process:**

1. Every 15 minutes, query all A records in `talos00` zone
2. Compare with expected state from Ingresses
3. Report drift in metrics and logs

**Metrics:**

```promql
catalyst_dns_sync_drift_detected_total{
  zone="talos00",
  hostname="grafana.talos00",
  drift_type="unexpected_ip"  # or "unexpected_record", "missing_record"
} 1
```

**Auto-Remediation:**

- Annotation: `catalyst-dns-sync.io/auto-remediate: "true"`
- Deletes unexpected records, recreates missing ones

#### 11.5.4 Multi-Zone Support

Manage multiple DNS zones from one controller:

```yaml
env:
  - name: DNS_ZONES
    value: 'talos00,home.lab,internal.dev'
```

**Hostname Matching:**

- `grafana.talos00` → Zone: `talos00`
- `api.home.lab` → Zone: `home.lab`
- `jenkins.internal.dev` → Zone: `internal.dev`

#### 11.5.5 DNS Record Export/Import

**CLI Tool:**

```bash
# Export all managed DNS records to YAML
kubectl exec -n infrastructure deploy/catalyst-dns-sync -- \
  /app/catalyst-dns-sync export > dns-backup.yaml

# Import records (useful for disaster recovery)
kubectl exec -n infrastructure deploy/catalyst-dns-sync -- \
  /app/catalyst-dns-sync import < dns-backup.yaml
```

**Format:**

```yaml
apiVersion: catalyst-dns-sync.io/v1alpha1
kind: DNSRecordBackup
metadata:
  timestamp: '2025-11-11T20:00:00Z'
  zone: talos00
records:
  - hostname: grafana.talos00
    ip: 192.168.1.54
    ttl: 300
    source:
      kind: IngressRoute
      namespace: monitoring
      name: grafana
```

### 11.6 Developer Experience Enhancements

#### 11.6.1 DNS Record Status in kubectl

Add status subresource to show DNS sync state:

```bash
kubectl get ingressroute grafana -n monitoring -o yaml
```

```yaml
status:
  catalyst-dns-sync:
    hostname: grafana.talos00
    dnsRecordCreated: true
    lastSyncTime: '2025-11-11T20:00:00Z'
    technitiumRecordId: 'abc123'
    message: 'DNS record synced successfully'
```

#### 11.6.2 DNS Test Endpoint

**Endpoint:** `/api/v1/test-dns?hostname=grafana.talos00`

**Response:**

```json
{
  "hostname": "grafana.talos00",
  "dnsResolution": {
    "resolved": true,
    "ip": "192.168.1.54",
    "ttl": 300,
    "source": "technitium"
  },
  "ingressExists": true,
  "ingressDetails": {
    "namespace": "monitoring",
    "name": "grafana",
    "kind": "IngressRoute"
  },
  "syncStatus": "healthy",
  "lastUpdate": "2025-11-11T20:00:00Z"
}
```

**Use Case:**

- CI/CD validation: Ensure DNS propagated before running tests
- Debugging: Quick check if DNS sync is working

#### 11.6.3 Grafana Dashboard Template

Ship pre-built Grafana dashboard via ConfigMap:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: catalyst-dns-sync-dashboard
  namespace: monitoring
  labels:
    grafana_dashboard: '1'
data:
  catalyst-dns-sync.json: |
    {
      "dashboard": {
        "title": "Catalyst DNS Sync",
        "panels": [
          {
            "title": "DNS Records Managed",
            "targets": [{"expr": "catalyst_dns_sync_records_total"}]
          },
          {
            "title": "API Latency (p95)",
            "targets": [{"expr": "histogram_quantile(0.95, catalyst_dns_sync_api_request_duration_seconds_bucket)"}]
          }
        ]
      }
    }
```

**Auto-import:** Grafana sidecar detects label, auto-imports dashboard.

---

## 12. Future Enhancements (Phase 2)

### 12.1 High Availability

- Leader election for multi-replica deployments
- Distributed locking for DNS updates

### 12.2 Advanced Integrations

- Support for CNAME records (Service aliases)
- External DNS provider fallback (Cloudflare, Route53)
- Service Mesh SRV record creation
- Webhook admission controller for Ingress validation

### 12.3 Operational Improvements

- Dry-run mode with diff output
- Chaos engineering mode (random DNS failures)
- DNS-based health checking (remove records for failing pods)

---

## 12. Success Criteria

The implementation is considered successful when:

1. **Functional:**
   - All IngressRoute hostnames automatically get DNS A records
   - DNS records update within 30 seconds of Ingress changes
   - Deleted Ingresses remove DNS records

2. **Observability:**
   - Prometheus metrics scraped successfully
   - JSON logs visible in Graylog
   - Grafana dashboard shows real-time status

3. **Reliability:**
   - Zero manual DNS interventions for 7 days
   - < 1% API error rate under normal operation
   - Controller restarts without data loss

4. **Performance:**
   - < 5s reconciliation time for single Ingress
   - < 50MB memory footprint
   - Handles 100+ Ingress resources

---

## 13. References

- [Technitium DNS Server API Docs](https://github.com/TechnitiumSoftware/DnsServer/blob/master/APIDOCS.md)
- [Kubernetes controller-runtime](https://github.com/kubernetes-sigs/controller-runtime)
- [Prometheus Client Go](https://github.com/prometheus/client_golang)
- [Go slog Documentation](https://pkg.go.dev/log/slog)
- [Traefik IngressRoute CRD](https://doc.traefik.io/traefik/routing/providers/kubernetes-crd/)
- [Gateway API HTTPRoute](https://gateway-api.sigs.k8s.io/reference/spec/#gateway.networking.k8s.io/v1.HTTPRoute)

---

## 14. Approval & Sign-off

| Stakeholder         | Role           | Status     | Date |
| ------------------- | -------------- | ---------- | ---- |
| Architecture Review | Technical Lead | ⏳ Pending | -    |
| Security Review     | SecOps         | ⏳ Pending | -    |
| Implementation      | Engineering    | ⏳ Pending | -    |

---

**Document Status:** Ready for Review
**Next Steps:** Architecture review, gather feedback, begin Phase 1 implementation
