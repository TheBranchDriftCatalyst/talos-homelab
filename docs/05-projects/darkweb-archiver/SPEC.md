# DarkWeb Archiver - Technical Specification

> **Issue:** TALOS-3fed
> **Status:** Draft Specification
> **Classification:** SCI//EAGLE-12//HOMELAB - Internal Tool Only

## TL;DR

A self-hosted dark web spider/scraper/archiver deployed in an **isolated high-risk security zone** alongside honeypot infrastructure (TALOS-5tj). The zone uses strict Cilium NetworkPolicies to create a cordoned subnet with no lateral movement to production workloads.

**Security Model:**
- Dedicated `security-zone` namespace with default-deny policies
- Egress only to Tor network (no cluster/internet access)
- Ingress only via authenticated jump host
- Shared infrastructure with Cowrie honeypot (TALOS-5tj)

**Key Components:**
- Tor proxy sidecar (traffic routing)
- Browsertrix Crawler (browser-based crawling)
- ArchiveBox (archival storage + UI)
- Meilisearch (full-text search)
- PostgreSQL (metadata + job queue)
- Cowrie honeypot (co-located in security zone)

---

## 0. Security Zone Architecture

### High-Risk Cordoned Network Segment

This project lives in an **isolated security zone** with strict network boundaries. The zone hosts:
1. **DarkWeb Archiver** - Tor-based crawler/archiver
2. **Cowrie Honeypot** - SSH/Telnet honeypot (TALOS-5tj)
3. **Future:** Additional security research tools

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          CATALYST CLUSTER                                    │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    PRODUCTION ZONE (Normal Traffic)                     │ │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐      │ │
│  │  │  media  │  │monitoring│  │ argocd  │  │ traefik │  │registry │      │ │
│  │  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘      │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                    │                                         │
│                           ═════════╪═════════  (Cilium Network Boundary)    │
│                                    │                                         │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │             SECURITY ZONE (High-Risk / Isolated Subnet)                 │ │
│  │                     Namespace: security-zone                            │ │
│  │                                                                          │ │
│  │  ┌─────────────────────────────┐  ┌─────────────────────────────┐      │ │
│  │  │     DARKWEB ARCHIVER        │  │      COWRIE HONEYPOT        │      │ │
│  │  │  ┌───────┐  ┌───────────┐   │  │  ┌───────┐  ┌───────────┐   │      │ │
│  │  │  │Crawler│  │ArchiveBox │   │  │  │Cowrie │  │ Session   │   │      │ │
│  │  │  │  +Tor │  │    UI     │   │  │  │  SSH  │  │  Replay   │   │      │ │
│  │  │  └───┬───┘  └───────────┘   │  │  └───┬───┘  └───────────┘   │      │ │
│  │  │      │                      │  │      │                       │      │ │
│  │  │      ▼                      │  │      ▼                       │      │ │
│  │  │  ┌───────┐                  │  │  ┌───────┐                   │      │ │
│  │  │  │  Tor  │──────────────────┼──┼──│ Ext.  │                   │      │ │
│  │  │  │Network│                  │  │  │Attacker│                   │      │ │
│  │  │  └───────┘                  │  │  └───────┘                   │      │ │
│  │  └─────────────────────────────┘  └─────────────────────────────┘      │ │
│  │                                                                          │ │
│  │  NETWORK POLICIES:                                                       │ │
│  │  • DEFAULT DENY all ingress/egress                                       │ │
│  │  • ALLOW egress to Tor network (port 9050, 9001, 9030)                  │ │
│  │  • ALLOW egress to external IPs for honeypot (attacker connections)     │ │
│  │  • ALLOW ingress from jump-host only (authenticated admin access)       │ │
│  │  • DENY all traffic to/from production namespaces                       │ │
│  │  • DENY access to cluster services (API server, DNS external)           │ │
│  │                                                                          │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                    │                                         │
│                                    ▼                                         │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                         JUMP HOST / BASTION                             │ │
│  │            (Only authorized entry point to security zone)               │ │
│  │  • Authentik SSO required                                               │ │
│  │  • mTLS client certificate                                              │ │
│  │  • Audit logging of all access                                          │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Network Policy Strategy

#### Default Deny (Namespace-Level)
```yaml
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: default-deny-all
  namespace: security-zone
spec:
  endpointSelector: {}  # All pods in namespace
  ingress:
    - {}  # Deny all (no rules = deny)
  egress:
    - {}  # Deny all
```

#### Selective Allow Policies

| Policy | Direction | From/To | Ports | Purpose |
|--------|-----------|---------|-------|---------|
| `allow-tor-egress` | Egress | Tor relay IPs | 9001, 9030, 9050 | Tor network access |
| `allow-dns-internal` | Egress | kube-dns | 53/UDP | Internal name resolution only |
| `allow-honeypot-ingress` | Ingress | 0.0.0.0/0 | 22, 23 | Attacker connections to Cowrie |
| `allow-jumphost-ingress` | Ingress | jump-host pod | 8000, 443 | Admin access to UIs |
| `deny-cluster-services` | Egress | API server CIDR | * | Block k8s API access |
| `deny-production` | Both | production namespaces | * | No lateral movement |

### Node Affinity (Optional)

For physical isolation, pin security zone to dedicated node:
```yaml
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions:
            - key: node-role.kubernetes.io/security-zone
              operator: Exists
```

Or use taints/tolerations:
```yaml
# On node
taints:
  - key: security-zone
    value: "true"
    effect: NoSchedule

# On pods
tolerations:
  - key: security-zone
    operator: Equal
    value: "true"
    effect: NoSchedule
```

---

## 1. Problem Statement

### What We Want
- Crawl and archive `.onion` sites for research/OSINT purposes
- Preserve content in standard archival formats (WARC)
- Search and explore archived content through a private UI
- Maintain anonymity (all traffic through Tor)
- Run entirely on homelab infrastructure

### What We Don't Want
- Any external/public exposure
- Logging of access patterns that could identify users
- Becoming an exit node or relay
- Storing illegal content (need content filtering)

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         DARKWEB ARCHIVER STACK                          │
│                        Namespace: darkweb-archiver                      │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐   │
│  │   Job Manager   │────▶│   Crawler Pod   │────▶│  Archive Store  │   │
│  │   (Scheduler)   │     │ ┌─────────────┐ │     │   (ArchiveBox)  │   │
│  └─────────────────┘     │ │ Browsertrix │ │     └────────┬────────┘   │
│          │               │ │   Crawler   │ │              │            │
│          ▼               │ └──────┬──────┘ │              ▼            │
│  ┌─────────────────┐     │        │        │     ┌─────────────────┐   │
│  │   PostgreSQL    │     │ ┌──────▼──────┐ │     │   Meilisearch   │   │
│  │  (Job Queue +   │     │ │ Tor Proxy   │ │     │   (Full-Text    │   │
│  │   Metadata)     │     │ │  Sidecar    │ │     │    Search)      │   │
│  └─────────────────┘     │ └─────────────┘ │     └─────────────────┘   │
│                          └─────────────────┘                           │
│                                  │                                      │
│                                  ▼                                      │
│                          ┌─────────────────┐                           │
│                          │   Tor Network   │                           │
│                          │   (.onion)      │                           │
│                          └─────────────────┘                           │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                        Explorer Web UI                           │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │   │
│  │  │  Dashboard  │  │   Search    │  │   Archive Browser       │  │   │
│  │  │  (Stats)    │  │   (Query)   │  │   (View/Replay WARC)    │  │   │
│  │  └─────────────┘  └─────────────┘  └─────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │     Traefik IngressRoute      │
                    │   darkweb.talos00 (private)   │
                    │   + Authentik SSO / mTLS      │
                    └───────────────────────────────┘
```

---

## 3. Component Breakdown

### 3.1 Tor Proxy Sidecar

**Purpose:** Route all crawler traffic through Tor network

**Implementation Options:**

| Option | Image | Pros | Cons |
|--------|-------|------|------|
| [dperson/torproxy](https://hub.docker.com/r/dperson/torproxy) | Alpine-based | Lightweight, battle-tested | Less actively maintained |
| [xxradar/torproxy](https://github.com/xxradar/torproxy) | Ubuntu-based | K8s examples included | Heavier base image |
| Custom | Build our own | Full control | More work |

**Recommended:** `dperson/torproxy` - lightweight and sufficient

**Configuration:**
```yaml
containers:
  - name: tor-proxy
    image: dperson/torproxy:latest
    ports:
      - containerPort: 9050  # SOCKS5 proxy
      - containerPort: 9051  # Control port (optional)
    env:
      - name: LOCATION
        value: "US"  # Exit node preference (optional)
    resources:
      requests:
        cpu: 50m
        memory: 128Mi
```

**Network Flow:**
```
Crawler → localhost:9050 (SOCKS5) → Tor Proxy → Tor Network → .onion site
```

### 3.2 Crawler Engine

**Purpose:** Browser-based crawling that handles JavaScript, login sessions, CAPTCHAs

**Candidates Evaluated:**

| Tool | Type | Tor Support | Output Format | K8s Ready |
|------|------|-------------|---------------|-----------|
| [Browsertrix Crawler](https://github.com/webrecorder/browsertrix-crawler) | Browser-based (Puppeteer/Brave) | Via SOCKS proxy | WARC | Yes |
| [Scrapy + Splash](https://scrapy.org/) | Python + JS renderer | Via middleware | JSON/WARC | Yes |
| [TorBot](https://github.com/DedSecInside/TorBot) | Dark web OSINT | Native Tor | JSON/Tree | Manual |
| [CRATOR](https://dl.acm.org/doi/10.1007/978-3-031-70890-9_8) | Academic crawler | Native Tor | Custom | Research only |

**Recommended:** Browsertrix Crawler
- Full browser (Brave) for JS-heavy sites
- Native WARC output
- Supports proxy configuration
- Single container deployment
- Active development

**Configuration:**
```yaml
containers:
  - name: crawler
    image: webrecorder/browsertrix-crawler:latest
    env:
      - name: PROXY_SERVER
        value: "socks5://localhost:9050"
    command:
      - crawl
      - --url
      - "http://example.onion"
      - --generateWACZ
      - --behaviors
      - "autoscroll,autoplay"
      - --timeout
      - "300"
```

### 3.3 Archive Storage

**Purpose:** Store, organize, and serve archived content

**Candidates:**

| Tool | Storage Format | UI | Search | K8s Support |
|------|----------------|-----|--------|-------------|
| [ArchiveBox](https://archivebox.io/) | Multi-format (WARC, PDF, PNG, HTML) | Built-in Django UI | SQLite FTS | Helm chart |
| [pywb](https://github.com/webrecorder/pywb) | WARC replay | Basic UI | No | Docker |
| Raw MinIO + DB | WARC blobs | None | External | Native |

**Recommended:** ArchiveBox
- Comprehensive archival (HTML, PDF, screenshots, WARC, media)
- Built-in web UI for browsing
- SQLite/PostgreSQL backend
- Can integrate with external search

**Storage Layout:**
```
/data/
├── archive/
│   ├── 1703345678.123/        # Timestamp-based directories
│   │   ├── index.html
│   │   ├── screenshot.png
│   │   ├── output.warc.gz
│   │   └── ...
│   └── ...
├── index.sqlite3              # Or PostgreSQL
└── ArchiveBox.conf
```

### 3.4 Search Engine

**Purpose:** Full-text search across archived content

**Candidates:**

| Engine | Type | Memory | Features |
|--------|------|--------|----------|
| [Meilisearch](https://www.meilisearch.com/) | Full-text | ~500MB | Fast, typo-tolerant, easy |
| [OpenSearch](https://opensearch.org/) | Full-text + analytics | 2GB+ | Feature-rich, heavy |
| SQLite FTS5 | Built into ArchiveBox | Minimal | Limited but sufficient |

**Recommended:** Meilisearch (start with SQLite FTS5)
- Phase 1: Use ArchiveBox's built-in SQLite FTS5
- Phase 2: Add Meilisearch for advanced search if needed

### 3.5 Job Scheduler

**Purpose:** Schedule and manage crawl jobs

**Options:**

| Tool | Complexity | Features |
|------|------------|----------|
| Kubernetes CronJob | Low | Basic scheduling |
| [Dagster](https://dagster.io/) | Medium | Pipeline orchestration |
| Custom Python + PostgreSQL | Low-Medium | Full control |

**Recommended:** Start with CronJob + ConfigMap for URL lists
- Simple to implement
- Can evolve to Dagster if needed

### 3.6 Web UI / Explorer

**Purpose:** Browse and search archives

**Options:**
1. **ArchiveBox UI** (built-in) - Django admin interface
2. **Custom React UI** - If more features needed
3. **Grafana dashboards** - For stats/metrics only

**Recommended:** ArchiveBox UI + Grafana for stats
- ArchiveBox provides browsing/search out of box
- Add Grafana dashboard for crawl metrics

---

## 4. Data Flow

### 4.1 Crawl Pipeline

```
1. Job Trigger (CronJob or Manual)
         │
         ▼
2. Crawler Pod Spins Up
   ├── Tor Proxy Sidecar (establishes circuit)
   └── Browsertrix Crawler (waits for proxy)
         │
         ▼
3. Crawl Execution
   ├── Fetch seed URLs from ConfigMap/DB
   ├── For each URL:
   │   ├── Request via Tor SOCKS5 proxy
   │   ├── Render JS (Brave browser)
   │   ├── Extract links (depth-limited)
   │   └── Save to WARC
         │
         ▼
4. Post-Crawl Processing
   ├── Upload WARC to ArchiveBox
   ├── Index content (full-text)
   └── Update job status in DB
         │
         ▼
5. Crawl Complete
   └── Pod terminates (Job completion)
```

### 4.2 Search/Browse Flow

```
User → Authentik SSO → Traefik → ArchiveBox UI
                                      │
                        ┌─────────────┴─────────────┐
                        │                           │
                   Browse Archives            Search Content
                        │                           │
                        ▼                           ▼
                   PostgreSQL               Meilisearch/FTS5
                   (metadata)               (full-text index)
                        │                           │
                        └─────────────┬─────────────┘
                                      │
                                      ▼
                              Serve WARC/Content
                              from MinIO/NFS
```

---

## 5. Kubernetes Manifests Structure

```
infrastructure/base/security-zone/
├── namespace.yaml                    # security-zone namespace
├── network-policies/
│   ├── default-deny.yaml            # Deny all by default
│   ├── allow-tor-egress.yaml        # Tor network access
│   ├── allow-dns.yaml               # Internal DNS only
│   ├── allow-honeypot-ingress.yaml  # External attacker access
│   ├── allow-jumphost.yaml          # Admin access via bastion
│   └── kustomization.yaml
├── jump-host/
│   ├── deployment.yaml              # Bastion/proxy for admin access
│   ├── service.yaml
│   └── ingressroute.yaml            # Traefik + Authentik + mTLS
│
├── darkweb-archiver/
│   ├── tor-proxy/
│   │   ├── deployment.yaml          # Shared Tor proxy pool
│   │   └── service.yaml
│   ├── archivebox/
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   ├── pvc.yaml                 # Archive storage
│   │   └── configmap.yaml           # ArchiveBox.conf
│   ├── crawler/
│   │   ├── cronjob.yaml             # Scheduled crawls
│   │   ├── configmap.yaml           # Seed URLs, crawl config
│   │   └── job-template.yaml        # Manual/on-demand crawls
│   ├── meilisearch/
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   └── pvc.yaml
│   ├── postgresql/
│   │   └── cluster.yaml             # CloudNativePG Cluster CR
│   └── kustomization.yaml
│
├── cowrie-honeypot/                  # TALOS-5tj
│   ├── deployment.yaml              # Cowrie SSH/Telnet honeypot
│   ├── service.yaml                 # LoadBalancer or NodePort (external)
│   ├── pvc.yaml                     # Session recordings
│   ├── configmap.yaml               # cowrie.cfg
│   └── kustomization.yaml
│
├── shared/
│   ├── elasticsearch/               # Shared log storage (optional)
│   │   └── ...
│   └── grafana-dashboards/          # Security zone metrics
│       ├── honeypot-dashboard.yaml
│       └── archiver-dashboard.yaml
│
└── kustomization.yaml
```

### Namespace Configuration

```yaml
# namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: security-zone
  labels:
    # Cilium labels for policy enforcement
    security-zone: "true"
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
  annotations:
    description: "High-risk isolated security research zone"
```

---

## 6. Security Considerations

### 6.1 Complete Network Policy Set

```yaml
# 1. DEFAULT DENY ALL - Applied to entire namespace
---
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: default-deny-all
  namespace: security-zone
spec:
  endpointSelector: {}
  ingress: []   # Empty = deny all
  egress: []    # Empty = deny all

---
# 2. ALLOW TOR EGRESS - Only for darkweb-archiver pods
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: allow-tor-egress
  namespace: security-zone
spec:
  endpointSelector:
    matchLabels:
      app.kubernetes.io/part-of: darkweb-archiver
  egress:
    # Tor directory authorities and relays
    - toCIDRSet:
        - cidr: 0.0.0.0/0
      toPorts:
        - ports:
            - port: "9001"   # Tor ORPort
              protocol: TCP
            - port: "9030"   # Tor DirPort
              protocol: TCP
            - port: "443"    # Tor bridges (obfs4)
              protocol: TCP

---
# 3. ALLOW INTERNAL DNS - CoreDNS only, no external DNS
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: allow-internal-dns
  namespace: security-zone
spec:
  endpointSelector: {}  # All pods
  egress:
    - toEndpoints:
        - matchLabels:
            k8s:io.kubernetes.pod.namespace: kube-system
            k8s-app: kube-dns
      toPorts:
        - ports:
            - port: "53"
              protocol: UDP
            - port: "53"
              protocol: TCP

---
# 4. ALLOW HONEYPOT INGRESS - External attackers to Cowrie
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: allow-honeypot-ingress
  namespace: security-zone
spec:
  endpointSelector:
    matchLabels:
      app: cowrie
  ingress:
    - fromCIDRSet:
        - cidr: 0.0.0.0/0
          except:
            - 10.0.0.0/8      # Block private ranges
            - 172.16.0.0/12
            - 192.168.0.0/16
      toPorts:
        - ports:
            - port: "2222"    # Cowrie SSH
              protocol: TCP
            - port: "2223"    # Cowrie Telnet
              protocol: TCP

---
# 5. ALLOW JUMP HOST ACCESS - Admin access to UIs
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: allow-jumphost-to-services
  namespace: security-zone
spec:
  endpointSelector:
    matchExpressions:
      - key: app
        operator: In
        values: [archivebox, meilisearch, cowrie-ui]
  ingress:
    - fromEndpoints:
        - matchLabels:
            app: jump-host
      toPorts:
        - ports:
            - port: "8000"    # ArchiveBox
              protocol: TCP
            - port: "7700"    # Meilisearch
              protocol: TCP

---
# 6. INTERNAL ZONE COMMUNICATION - Services within security-zone
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: allow-internal-zone
  namespace: security-zone
spec:
  endpointSelector:
    matchLabels:
      security-zone-internal: "true"
  ingress:
    - fromEndpoints:
        - matchLabels:
            security-zone-internal: "true"
  egress:
    - toEndpoints:
        - matchLabels:
            security-zone-internal: "true"

---
# 7. DENY CLUSTER SERVICES - Block access to K8s API, etc.
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: deny-cluster-services
  namespace: security-zone
spec:
  endpointSelector: {}
  egressDeny:
    - toCIDRSet:
        - cidr: 10.96.0.1/32    # K8s API service IP
    - toEntities:
        - kube-apiserver
```

### 6.2 Authentication Stack

```
┌─────────────────────────────────────────────────────────────────┐
│                    ACCESS FLOW                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   User → Traefik → Authentik SSO → mTLS Check → Jump Host       │
│                         │                           │            │
│                    ┌────▼────┐                 ┌────▼────┐       │
│                    │ Valid   │     Yes         │ Forward │       │
│                    │ Session?│────────────────▶│ to Zone │       │
│                    └────┬────┘                 └─────────┘       │
│                         │ No                                     │
│                         ▼                                        │
│                    ┌─────────┐                                   │
│                    │ Redirect│                                   │
│                    │ to Login│                                   │
│                    └─────────┘                                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Components:**
- **Authentik SSO** - Identity provider (already deployed)
- **mTLS TLSOption** - Client certificate requirement
- **Traefik ForwardAuth** - Middleware chain
- **Audit Logging** - All access logged to Loki

```yaml
# IngressRoute for security-zone jump host
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: security-zone-entry
  namespace: security-zone
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`security.talos00`)
      kind: Rule
      middlewares:
        - name: authentik-forward-auth
          namespace: authentik
        - name: security-zone-mtls
          namespace: security-zone
      services:
        - name: jump-host
          port: 8080
  tls:
    secretName: security-zone-tls
    options:
      name: security-zone-mtls-option
      namespace: security-zone

---
apiVersion: traefik.io/v1alpha1
kind: TLSOption
metadata:
  name: security-zone-mtls-option
  namespace: security-zone
spec:
  clientAuth:
    secretNames:
      - security-zone-ca
    clientAuthType: RequireAndVerifyClientCert
  minVersion: VersionTLS13
```

### 6.3 Content Filtering

| Filter | Implementation | Purpose |
|--------|----------------|---------|
| URL Blacklist | ConfigMap + Python filter | Block known illegal domains |
| MIME Type Filter | Browsertrix config | Skip binaries, executables |
| Size Limit | Browsertrix `--sizeLimit` | Cap at 50MB per resource |
| Rate Limit | Crawler config | Max 1 req/sec per domain |
| Hash Dedup | ArchiveBox | Skip already-archived content |

### 6.4 Logging Policy

**Principle:** Log security events, NOT user activity patterns

```yaml
# What we DO log:
# - Authentication attempts (success/fail)
# - Network policy violations
# - Crawl job start/complete (not URLs)
# - Resource usage anomalies

# What we DO NOT log:
# - Individual page requests
# - Search queries
# - User browsing patterns
# - Archive access history

env:
  - name: LOG_LEVEL
    value: "WARNING"
  - name: ARCHIVEBOX_DEBUG
    value: "False"
  - name: DISABLE_ACCESS_LOG
    value: "true"
```

### 6.5 Cowrie Honeypot Security

```yaml
# Cowrie-specific security considerations
spec:
  containers:
    - name: cowrie
      image: cowrie/cowrie:latest
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        readOnlyRootFilesystem: true
        allowPrivilegeEscalation: false
        capabilities:
          drop: [ALL]
          add: [NET_BIND_SERVICE]  # For port 22/23 binding
      env:
        # Cowrie settings
        - name: COWRIE_TELNET_ENABLED
          value: "true"
        - name: COWRIE_OUTPUT_JSON
          value: "true"
        # Session recording
        - name: COWRIE_LOG_PATH
          value: "/var/log/cowrie"
      volumeMounts:
        - name: sessions
          mountPath: /var/lib/cowrie/tty
        - name: downloads
          mountPath: /var/lib/cowrie/downloads
```

---

## 7. Storage Requirements

| Component | Size Estimate | Storage Class | Notes |
|-----------|---------------|---------------|-------|
| ArchiveBox data | 100GB+ | NFS (fatboy) | Grows with archives |
| PostgreSQL | 10GB | local-path | Metadata only |
| Meilisearch index | 20GB | local-path | ~20% of content size |
| WARC staging | 50GB | emptyDir/NFS | Temporary during crawl |

**Total estimated:** 200GB initial, scales with usage

---

## 8. Implementation Phases

### Phase 1: Foundation (MVP)
- [ ] Namespace + NetworkPolicies
- [ ] Tor proxy deployment (shared pool)
- [ ] ArchiveBox deployment with SQLite
- [ ] Manual crawl job (single URL)
- [ ] Basic IngressRoute + Authentik

**Deliverable:** Can manually crawl a single .onion URL and view in ArchiveBox

### Phase 2: Automation
- [ ] CronJob for scheduled crawls
- [ ] Seed URL ConfigMap management
- [ ] PostgreSQL for job queue
- [ ] Browsertrix Crawler integration
- [ ] Depth-limited spidering

**Deliverable:** Automated daily crawls of seed list

### Phase 3: Search & Scale
- [ ] Meilisearch deployment
- [ ] Full-text indexing pipeline
- [ ] Grafana dashboard for stats
- [ ] Multiple crawler workers
- [ ] WARC deduplication

**Deliverable:** Searchable archive with monitoring

### Phase 4: Advanced Features
- [ ] Content filtering/moderation
- [ ] Link graph analysis
- [ ] Custom behaviors (CAPTCHA handling)
- [ ] API for external tools
- [ ] Backup to S3 (encrypted)

---

## 9. Resource Estimates

### Per Crawl Job
```yaml
resources:
  requests:
    cpu: 500m      # Browsertrix needs CPU for browser
    memory: 1Gi    # Browser memory
  limits:
    cpu: 2000m
    memory: 4Gi
```

### Persistent Services
| Service | CPU Request | Memory Request |
|---------|-------------|----------------|
| ArchiveBox | 100m | 256Mi |
| Tor Proxy | 50m | 128Mi |
| Meilisearch | 100m | 512Mi |
| PostgreSQL | 100m | 256Mi |

**Total idle:** ~350m CPU, ~1.2Gi memory

---

## 10. Open Questions

1. **Seed URL Management:** How to populate initial .onion URLs?
   - Manual curation?
   - OnionScan discovery?
   - External lists (ahmia.fi)?

2. **Crawl Depth:** How deep to spider from seed URLs?
   - Recommend: 2-3 levels max to control scope

3. **Frequency:** How often to recrawl?
   - Daily for active sites?
   - Weekly for stable content?

4. **Retention:** How long to keep archives?
   - Forever (append-only)?
   - Rolling window?

5. **Legal Considerations:**
   - Content responsibility policy needed
   - Geographic legal requirements

---

## 11. References

### Tools & Projects
- [ArchiveBox](https://github.com/ArchiveBox/ArchiveBox) - Self-hosted web archiving
- [Browsertrix Crawler](https://github.com/webrecorder/browsertrix-crawler) - Browser-based crawler
- [TorBot](https://github.com/DedSecInside/TorBot) - Dark Web OSINT Tool
- [CRATOR](https://dl.acm.org/doi/10.1007/978-3-031-70890-9_8) - Academic Tor crawler (ESORICS 2024)
- [xxradar/torproxy](https://github.com/xxradar/torproxy) - Kubernetes Tor proxy

### Standards & Formats
- [WARC Format Specification](https://iipc.github.io/warc-specifications/specifications/warc-format/warc-1.1/)
- [WARC Ecosystem](https://wiki.archiveteam.org/index.php/The_WARC_Ecosystem)

### Kubernetes Patterns
- [Native Sidecar Containers (K8s 1.28+)](https://kubernetes.io/blog/2023/08/25/native-sidecar-containers/)
- [Browsertrix Self-Hosting Docs](https://docs.browsertrix.com/deploy/)

---

## 12. Cowrie Honeypot Integration (TALOS-5tj)

### Overview

Cowrie is a medium-to-high interaction SSH/Telnet honeypot that captures attacker sessions for analysis. It runs alongside the darkweb archiver in the security-zone namespace.

### Session Capture & Replay

```bash
# Cowrie stores sessions in UML-compatible format
/var/lib/cowrie/tty/<session-id>

# Built-in replay utility
bin/playlog /var/lib/cowrie/tty/<session-file>

# Export to asciinema for sharing
bin/asciinema /var/lib/cowrie/tty/<session-file> > session.cast
asciinema play session.cast
```

### Captured Artifacts

| Artifact | Location | Purpose |
|----------|----------|---------|
| TTY sessions | `/var/lib/cowrie/tty/` | Full session recordings |
| Downloaded files | `/var/lib/cowrie/downloads/` | Malware samples |
| Credentials | `cowrie.json` logs | Username/password attempts |
| Commands | `cowrie.json` logs | All executed commands |

### Deployment Pattern

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cowrie
  namespace: security-zone
spec:
  replicas: 1
  selector:
    matchLabels:
      app: cowrie
  template:
    metadata:
      labels:
        app: cowrie
        security-zone-internal: "true"
    spec:
      containers:
        - name: cowrie
          image: cowrie/cowrie:latest
          ports:
            - containerPort: 2222  # SSH
              name: ssh
            - containerPort: 2223  # Telnet
              name: telnet
          volumeMounts:
            - name: tty-sessions
              mountPath: /var/lib/cowrie/tty
            - name: downloads
              mountPath: /var/lib/cowrie/downloads
            - name: config
              mountPath: /cowrie/cowrie-git/etc/cowrie.cfg
              subPath: cowrie.cfg
      volumes:
        - name: tty-sessions
          persistentVolumeClaim:
            claimName: cowrie-sessions
        - name: downloads
          persistentVolumeClaim:
            claimName: cowrie-downloads
        - name: config
          configMap:
            name: cowrie-config
---
# External access via LoadBalancer or port mapping
apiVersion: v1
kind: Service
metadata:
  name: cowrie-external
  namespace: security-zone
spec:
  type: LoadBalancer
  loadBalancerIP: 192.168.1.200  # Dedicated honeypot IP
  ports:
    - name: ssh
      port: 22        # External attackers see port 22
      targetPort: 2222
    - name: telnet
      port: 23
      targetPort: 2223
  selector:
    app: cowrie
```

### Integration with Darkweb Archiver

Both systems share:
- **Namespace:** `security-zone`
- **Network policies:** Same isolation rules
- **Jump host:** Single entry point for admin access
- **Logging backend:** Ship to Loki (security events only)
- **Grafana dashboards:** Unified security monitoring

---

## 13. Summary - What This Enables

```
┌──────────────────────────────────────────────────────────────────┐
│                    SECURITY RESEARCH PLATFORM                     │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  PASSIVE INTELLIGENCE        ACTIVE COLLECTION                   │
│  ┌─────────────────┐         ┌─────────────────┐                │
│  │ Cowrie Honeypot │         │ Darkweb Archiver│                │
│  │                 │         │                 │                │
│  │ • SSH attacks   │         │ • .onion sites  │                │
│  │ • Malware drops │         │ • WARC archives │                │
│  │ • Credentials   │         │ • Full-text idx │                │
│  │ • TTY sessions  │         │ • Screenshot    │                │
│  └────────┬────────┘         └────────┬────────┘                │
│           │                           │                          │
│           └───────────┬───────────────┘                          │
│                       │                                          │
│                       ▼                                          │
│           ┌─────────────────────┐                                │
│           │  Unified Dashboard  │                                │
│           │                     │                                │
│           │ • Attack stats      │                                │
│           │ • Archive metrics   │                                │
│           │ • Session replays   │                                │
│           │ • Search interface  │                                │
│           └─────────────────────┘                                │
│                                                                   │
│  ACCESS: https://security.talos00 (Authentik + mTLS)             │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Related Issues

- **TALOS-3fed** - TOR/Darkweb Spider/Scraper/Archiver/Explorer (this spec)
- **TALOS-5tj** - Kubernetes Honeypot Infrastructure (Cowrie deployment)
- **TALOS-wlu** - Security Hardening: Implement Layered Defense-in-Depth (network policies)
