# Talos Homelab - Executive Summary

> **A production-grade Kubernetes homelab infrastructure demonstrating enterprise patterns at scale: GitOps, hybrid cloud AI, multi-cluster networking, and comprehensive observability.**

## TL;DR

This repository represents a **complete platform engineering implementation** featuring:

- **Dual GitOps** architecture (Flux for infrastructure, ArgoCD for applications)
- **Hybrid cloud AI** with scale-to-zero GPU workers (local Talos + AWS EC2)
- **Multi-cluster networking** via Cilium ClusterMesh + Nebula mesh VPN
- **Full observability stack** (Mimir, Loki, Tempo, Alloy - OTEL-native)
- **Privacy-focused VPN gateway** with automated key rotation
- **Media automation** with GPU-accelerated transcoding across heterogeneous hardware
- **Enterprise DevEx** with Tilt, Taskfiles, and comprehensive automation

---

## Architecture Overview

```mermaid
graph TB
    subgraph "Catalyst DevSpace Workspace"
        direction TB
        DEVSPACE["catalyst-devspace/workspace/"]
        UI["catalyst-ui<br/>(React Components)"]
        LLM["catalyst-llm<br/>(LLM Proxy)"]
        KASA["@kasa-exporter<br/>(IoT Metrics)"]
        MEMEX["@memeX<br/>(Knowledge Graph)"]
        HOMELAB["talos-homelab<br/>(Infrastructure)"]

        DEVSPACE --> UI
        DEVSPACE --> LLM
        DEVSPACE --> KASA
        DEVSPACE --> MEMEX
        DEVSPACE --> HOMELAB
    end

    subgraph "Talos Homelab Cluster"
        direction TB

        subgraph "Control Plane"
            FLUX["Flux CD<br/>(Infrastructure)"]
            ARGOCD["ArgoCD<br/>(Applications)"]
            TRAEFIK["Traefik<br/>(Ingress)"]
            CILIUM["Cilium CNI<br/>(eBPF Networking)"]
        end

        subgraph "Observability"
            MIMIR["Mimir<br/>(Metrics)"]
            LOKI["Loki<br/>(Logs)"]
            TEMPO["Tempo<br/>(Traces)"]
            ALLOY["Alloy<br/>(Collector)"]
            GRAFANA["Grafana<br/>(Visualization)"]
        end

        subgraph "Applications"
            ARR["arr-stack<br/>(Media Automation)"]
            HOME["home-stack<br/>(Smart Home)"]
            TDARR["Tdarr<br/>(GPU Transcoding)"]
            VPN["VPN Gateway<br/>(Privacy)"]
        end

        subgraph "AI Platform"
            OLLAMA["Ollama<br/>(Local LLM)"]
            RABBITMQ["RabbitMQ<br/>(Message Bus)"]
            PROXY["LLM Proxy<br/>(Orchestrator)"]
        end
    end

    subgraph "AWS Cloud"
        direction TB
        LIGHTHOUSE["k3s Lighthouse<br/>(Control Node)"]
        GPUWORKER["GPU Workers<br/>(Scale-to-Zero)"]
        S3["S3<br/>(Model Storage)"]
    end

    HOMELAB --> FLUX
    FLUX --> ARGOCD
    CILIUM -.->|ClusterMesh| LIGHTHOUSE
    NEBULA["Nebula Mesh VPN"] --> LIGHTHOUSE
    NEBULA --> GPUWORKER
    PROXY --> GPUWORKER
    GPUWORKER --> S3

    style HOMELAB fill:#ff6b6b,stroke:#333,stroke-width:3px
    style DEVSPACE fill:#4ecdc4,stroke:#333,stroke-width:2px
```

---

## Key Technical Achievements

### 1. Dual GitOps Architecture

A clear separation of concerns between infrastructure and application management:

```mermaid
flowchart LR
    subgraph "Git Repository"
        INFRA["infrastructure/base/"]
        APPS["applications/"]
        CLUSTERS["clusters/catalyst-cluster/"]
    end

    subgraph "Flux CD (Infrastructure)"
        FK["Flux Kustomizations"]
        HR["HelmReleases"]
    end

    subgraph "ArgoCD (Applications)"
        AA["Application CRDs"]
        AS["Auto-Sync"]
    end

    CLUSTERS --> FK
    INFRA --> FK
    FK --> HR

    APPS --> AA
    AA --> AS

    style FK fill:#326ce5,color:#fff
    style AA fill:#ef7b4d,color:#fff
```

| Layer | Tool | Manages | Philosophy |
|-------|------|---------|------------|
| Infrastructure | Flux CD | Namespaces, Storage, Monitoring, Ingress, CNI | Explicit execution, controlled changes |
| Applications | ArgoCD | User workloads, Media apps, Home automation | Auto-sync, continuous deployment |

### 2. Hybrid Cloud AI Platform

Scale-to-zero GPU infrastructure spanning local and cloud resources:

```mermaid
sequenceDiagram
    participant User
    participant Proxy as LLM Proxy
    participant Local as Ollama (talos06)
    participant EC2 as EC2 GPU Worker
    participant RMQ as RabbitMQ

    User->>Proxy: Inference Request

    alt Local GPU Available
        Proxy->>Local: Route to Arc 140T
        Local-->>Proxy: Response (fast)
    else Need More Power
        Proxy->>EC2: Check Status
        alt EC2 Running
            EC2-->>Proxy: Ready
            Proxy->>EC2: Forward Request
        else EC2 Stopped
            Proxy->>EC2: Start Instance
            EC2->>RMQ: Register (self-discovery)
            RMQ-->>Proxy: Worker Available
            Proxy->>EC2: Forward Request
        end
        EC2-->>Proxy: Response
    end

    Proxy-->>User: Inference Result

    Note over EC2: Auto-shutdown after<br/>15min idle (cost: ~$0)
```

**Cost Optimization:**
- **On-demand**: ~$4.26/day (8 hours active)
- **Spot instances**: ~$1.30/day (80% savings)
- **Stopped state**: ~$0.001/hour (EBS only)
- **Model persistence**: No re-download on restart

### 3. Multi-Cluster Networking

Three-layer networking stack for secure cross-cluster communication:

```mermaid
graph TB
    subgraph "Layer 1: Physical/Cloud"
        HOME["Home Network<br/>192.168.1.0/24"]
        AWS["AWS VPC<br/>172.31.0.0/16"]
    end

    subgraph "Layer 2: Nebula Mesh VPN"
        N1["talos00 → 10.42.0.1"]
        N2["k3s-lighthouse → 10.42.1.1"]
        N3["gpu-worker → 10.42.2.x"]

        N1 <-->|Encrypted UDP| N2
        N2 <-->|Encrypted UDP| N3
    end

    subgraph "Layer 3: Cilium ClusterMesh"
        CM1["Talos Cluster<br/>(cluster-id: 1)"]
        CM2["k3s Cluster<br/>(cluster-id: 2)"]

        CM1 <-->|etcd sync| CM2
    end

    HOME --> N1
    AWS --> N2
    AWS --> N3

    N1 --> CM1
    N2 --> CM2

    style N1 fill:#7c3aed,color:#fff
    style N2 fill:#7c3aed,color:#fff
    style N3 fill:#7c3aed,color:#fff
```

**Key Features:**
- **NAT Traversal**: UDP hole-punching via Nebula lighthouse
- **mTLS**: Mutual authentication with SPIRE identity
- **Service Discovery**: Cross-cluster DNS resolution
- **Pod Mobility**: Transparent workload scheduling via Liqo

### 4. VPN Gateway with Rotation

Privacy-focused gateway with automated key rotation:

```mermaid
flowchart TB
    subgraph "VPN Gateway Pod"
        direction TB
        GLUETUN["gluetun<br/>(WireGuard Client)"]
        SOCKS["SOCKS5 Proxy<br/>(port 1080)"]
        EXPORTER["Metrics Exporter<br/>(port 9091)"]

        GLUETUN --> SOCKS
        GLUETUN --> EXPORTER
    end

    subgraph "Rotation System"
        CRON["CronJob<br/>(every 35min + jitter)"]
        SCRIPT["rotate.py"]
        STATE["rotation-state.json"]

        CRON --> SCRIPT
        SCRIPT --> STATE
    end

    subgraph "Exit Nodes"
        NL["Netherlands"]
        DE["Germany"]
        CH["Switzerland"]
        SE["Sweden"]
    end

    subgraph "Privacy Apps"
        SEARX["SecureXNG<br/>(Meta-Search)"]
        CHROME["Secure Chrome<br/>(VPN Browser)"]
        WEBTOP["Secure Webtop<br/>(Linux Desktop)"]
    end

    SCRIPT -->|API Call| GLUETUN
    GLUETUN --> NL
    GLUETUN --> DE
    GLUETUN --> CH
    GLUETUN --> SE

    SEARX --> GLUETUN
    CHROME --> GLUETUN
    WEBTOP --> GLUETUN

    style GLUETUN fill:#10b981,color:#fff
    style SCRIPT fill:#f59e0b,color:#fff
```

**Rotation Features:**
- Weighted random selection (least-used server preferred)
- Failed server cooldown (1-hour exclusion)
- Parallel or staggered rotation modes
- mTLS client authentication for external access
- Prometheus metrics for all rotation events

### 5. Observability Stack (OTEL-Native)

Modern telemetry pipeline built on OpenTelemetry standards:

```mermaid
flowchart LR
    subgraph "Sources"
        PODS["Kubernetes Pods"]
        NODES["Node Exporter"]
        KSM["kube-state-metrics"]
        APPS["Applications<br/>(OTLP)"]
    end

    subgraph "Collection (Alloy)"
        SCRAPE["Prometheus Scraping"]
        OTLP["OTLP Receivers<br/>(4317/4318)"]
        BATCH["Batch Processor"]
    end

    subgraph "Storage"
        MIMIR["Mimir<br/>(Metrics)"]
        LOKI["Loki<br/>(Logs)"]
        TEMPO["Tempo<br/>(Traces)"]
        MINIO["MinIO<br/>(S3 Backend)"]
    end

    subgraph "Visualization"
        GRAFANA["Grafana"]
        DASH["25+ Dashboards"]
    end

    PODS --> SCRAPE
    NODES --> SCRAPE
    KSM --> SCRAPE
    APPS --> OTLP

    SCRAPE --> BATCH
    OTLP --> BATCH

    BATCH --> MIMIR
    BATCH --> LOKI
    BATCH --> TEMPO

    MIMIR --> MINIO
    LOKI --> MINIO
    TEMPO --> MINIO

    MIMIR --> GRAFANA
    LOKI --> GRAFANA
    TEMPO --> GRAFANA
    GRAFANA --> DASH

    style ALLOY fill:#ff6b35,color:#fff
    style GRAFANA fill:#f46800,color:#fff
```

**Capabilities:**
- **Metrics**: 1-year retention, 100k series/sec ingestion
- **Logs**: 30-day retention, structured with Kubernetes labels
- **Traces**: 7-day retention, service dependency mapping
- **Correlation**: Trace → Log → Metric linking in Grafana

### 6. GPU-Accelerated Media Processing

Heterogeneous GPU scheduling across cluster nodes:

```mermaid
graph TB
    subgraph "Tdarr Orchestrator"
        SERVER["Tdarr Server<br/>(talos06)"]
    end

    subgraph "Worker Fleet (DaemonSet)"
        W1["talos01<br/>Intel QSV"]
        W2["talos02<br/>Intel Arc 130T"]
        W3["talos03<br/>AMD VAAPI"]
        W4["talos06<br/>Intel Arc 140T"]
    end

    subgraph "GPU Auto-Detection"
        DETECT["Init Container"]
        VENDOR["Check /sys/class/drm"]
        NAME["Set NODE-GPU name"]
    end

    subgraph "Media Storage"
        TRUENAS["TrueNAS<br/>(Movies, TV)"]
        SYNOLOGY["Synology<br/>(Archive)"]
    end

    SERVER -->|RPC| W1
    SERVER -->|RPC| W2
    SERVER -->|RPC| W3
    SERVER -->|RPC| W4

    DETECT --> VENDOR
    VENDOR --> NAME

    W1 --> TRUENAS
    W2 --> TRUENAS
    W3 --> SYNOLOGY
    W4 --> SYNOLOGY

    style SERVER fill:#6366f1,color:#fff
    style W4 fill:#10b981,color:#fff
```

**GPU Support:**
| Node | GPU | Codec Support | Use Case |
|------|-----|---------------|----------|
| talos01 | Intel QSV | H.264, HEVC | Standard transcoding |
| talos02 | Intel Arc 130T | H.264, HEVC, AV1 | Next-gen codecs |
| talos03 | AMD VAAPI | H.264, HEVC | Parallel processing |
| talos06 | Intel Arc 140T | H.264, HEVC, AV1 | Highest performance |

---

## Developer Experience

### Task Automation

Modular Taskfile structure with 90+ automated tasks:

```
Taskfile.yaml           # Root orchestrator
├── Taskfile.talos.yaml  # 33 Talos operations
├── Taskfile.k8s.yaml    # 18 Kubernetes tasks
├── Taskfile.dev.yaml    # 17 DevEx tools
└── Taskfile.infra.yaml  # 22 Infrastructure tasks
```

**Common Operations:**
```bash
task health          # Cluster health check
task lint            # Full code quality scan
task deploy-stack    # Infrastructure deployment
task dashboard       # Real-time cluster status
```

### Local Development with Tilt

```mermaid
flowchart LR
    subgraph "Developer Machine"
        CODE["Code Changes"]
        TILT["Tilt UI<br/>:10350"]
    end

    subgraph "Tilt Features"
        WATCH["File Watcher"]
        APPLY["kubectl apply"]
        LOGS["Log Streaming"]
        BUTTONS["UI Buttons"]
    end

    subgraph "Cluster"
        PODS["Workloads"]
        FLUX["Flux Sync"]
    end

    CODE --> WATCH
    WATCH --> APPLY
    APPLY --> PODS
    PODS --> LOGS
    LOGS --> TILT
    BUTTONS --> FLUX

    style TILT fill:#00add8,color:#fff
```

### Git Hooks (Lefthook)

Pre-commit quality gates:
- **gitleaks**: Secret scanning
- **yamllint**: YAML validation
- **shellcheck**: Shell script linting
- **kustomize build**: Manifest validation
- **kubectl dry-run**: Kubernetes API validation

---

## Beads: AI-Native Issue Tracking

This repository uses **Beads** for issue tracking - a CLI-first tool designed for AI-assisted development workflows.

```mermaid
flowchart TB
    subgraph "Beads Workflow"
        CREATE["bd create<br/>'New feature'"]
        LIST["bd list<br/>--status=open"]
        WORK["bd update<br/>--status=in_progress"]
        CLOSE["bd close<br/>TALOS-xxx"]
        SYNC["bd sync<br/>(git commit)"]
    end

    subgraph "Storage"
        JSONL[".beads/issues.jsonl"]
        GIT["Git Repository"]
    end

    subgraph "Integration"
        CLAUDE["Claude Code<br/>(MCP Tools)"]
        HOOKS["Git Hooks"]
    end

    CREATE --> JSONL
    LIST --> JSONL
    WORK --> JSONL
    CLOSE --> JSONL
    JSONL --> SYNC
    SYNC --> GIT

    CLAUDE -->|"mcp__beads__*"| JSONL
    HOOKS -->|"auto-sync"| GIT

    style CLAUDE fill:#cc785c,color:#fff
    style JSONL fill:#22c55e,color:#fff
```

**Why Beads?**
- **Git-native**: Issues stored alongside code, synced with commits
- **AI-friendly**: CLI-first interface works seamlessly with Claude Code
- **MCP Integration**: Full CRUD via Model Context Protocol tools
- **Dependency Tracking**: `bd dep add` for issue relationships
- **No Context Switching**: No web UI required

**Current Roadmap (from Beads):**
| Issue | Type | Status | Description |
|-------|------|--------|-------------|
| TALOS-w5e0 | Epic | In Progress | Carrierarr base image system |
| TALOS-rrnk | Task | In Progress | Cilium ClusterMesh configuration |
| TALOS-700h | Feature | Open | Nebula mesh with home lighthouse |
| TALOS-wlu | Epic | Open | Security hardening (layered defense) |
| TALOS-n8an | Epic | Open | Arr-stack PostgreSQL migration |

---

## Technology Stack

### Infrastructure Layer
| Component | Technology | Purpose |
|-----------|-----------|---------|
| OS | Talos Linux | Immutable, minimal Kubernetes OS |
| CNI | Cilium | eBPF networking, ClusterMesh |
| GitOps | Flux CD + ArgoCD | Dual-pattern deployment |
| Ingress | Traefik | HTTP routing, mTLS |
| Secrets | External Secrets + 1Password | Secure secret management |
| Certificates | cert-manager | Let's Encrypt automation |

### Observability Layer
| Component | Technology | Purpose |
|-----------|-----------|---------|
| Metrics | Grafana Mimir | Long-term metrics storage |
| Logs | Grafana Loki | Log aggregation |
| Traces | Grafana Tempo | Distributed tracing |
| Collection | Grafana Alloy | Unified telemetry collector |
| Visualization | Grafana | Dashboards and alerting |

### Application Layer
| Component | Technology | Purpose |
|-----------|-----------|---------|
| Media | Sonarr, Radarr, Plex, Jellyfin | Media automation |
| Transcoding | Tdarr | GPU-accelerated encoding |
| Smart Home | Home Assistant | Home automation |
| AI/LLM | Ollama + LLM Proxy | Local and cloud inference |
| VPN | gluetun + ProtonVPN | Privacy gateway |

### Hybrid Cloud Layer
| Component | Technology | Purpose |
|-----------|-----------|---------|
| Mesh VPN | Nebula | P2P encrypted overlay |
| Federation | Liqo | Transparent cluster offloading |
| Fleet Mgmt | Carrierarr | gRPC + RabbitMQ agent control |
| GPU Compute | AWS EC2 (g4dn/g5) | Scale-to-zero GPU workers |
| Storage | AWS S3 | Model persistence |

---

## Repository Structure

```
talos-homelab/
├── infrastructure/base/          # Platform infrastructure
│   ├── argocd/                  # Application GitOps
│   ├── cilium/                  # CNI + ClusterMesh
│   ├── traefik/                 # Ingress controller
│   ├── monitoring/              # OTEL observability stack
│   ├── vpn-gateway/             # Privacy gateway + rotation
│   ├── external-secrets/        # 1Password integration
│   ├── hybrid-llm/              # AWS + Nebula + Liqo
│   └── databases/               # Operator-managed DBs
│
├── applications/                 # User workloads
│   ├── arr-stack/               # Media automation (15+ services)
│   ├── catalyst-llm/            # Hybrid AI platform
│   ├── home-stack/              # Smart home
│   └── scratch/                 # Experimental apps
│
├── clusters/catalyst-cluster/    # Flux cluster configuration
│   ├── flux-system/             # Flux bootstrap
│   └── *.yaml                   # Kustomization resources
│
├── tools/                        # Custom tooling
│   ├── ec2-agent/               # GPU worker orchestration
│   ├── carrierarr/              # Fleet management (gRPC)
│   └── beads-manager/           # Issue tracking UI
│
├── scripts/                      # Automation
│   ├── hybrid-llm/              # AWS provisioning
│   ├── lib/                     # Shared shell libraries
│   └── *.sh                     # Deployment scripts
│
├── configs/                      # Machine configurations (gitignored)
├── docs/                         # Documentation
└── .beads/                       # Issue tracking database
```

---

## Quick Start

```bash
# 1. Clone and setup
git clone https://github.com/TheBranchDriftCatalyst/talos-homelab.git
cd talos-homelab
task deps                    # Install tooling

# 2. Configure cluster access
export TALOS_NODE=192.168.1.54
task kubeconfig-merge        # Enable kubectl

# 3. Verify health
task health                  # Cluster health
task get-pods               # All workloads

# 4. Check current work
bd ready                     # Available issues
bd stats                     # Project health
```

---

## Key Differentiators

1. **Production Patterns at Homelab Scale**: Enterprise-grade architecture (GitOps, observability, multi-cluster) sized for personal infrastructure

2. **Hybrid Cloud Without Vendor Lock-in**: AWS GPU bursting via Nebula mesh - no proprietary peering required

3. **AI-First Development Workflow**: Beads issue tracking + Claude Code integration for seamless AI-assisted development

4. **Cost-Optimized GPU Compute**: Scale-to-zero with ~$1.30/day for on-demand GPU access

5. **Privacy by Design**: VPN gateway with rotation, mTLS, no logs by default

6. **Heterogeneous GPU Fleet**: Automatic detection and scheduling across Intel/AMD/NVIDIA hardware

---

## Contact

**Repository**: [github.com/TheBranchDriftCatalyst/talos-homelab](https://github.com/TheBranchDriftCatalyst/talos-homelab)

**Part of**: [catalyst-devspace](https://github.com/TheBranchDriftCatalyst) - Integrated development workspace

---

## Related Issues

<!-- Beads tracking for this doc -->
- TALOS-w5e0 - Carrierarr base image system (in_progress)
- TALOS-rrnk - Cilium ClusterMesh configuration (in_progress)
- TALOS-wlu - Security hardening epic (open)
