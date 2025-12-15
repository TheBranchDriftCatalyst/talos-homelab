# Infrastructure Architecture Diagrams

This document provides comprehensive visual documentation of the talos-homelab cluster architecture using Mermaid diagrams.

## Table of Contents

1. [High-Level System Overview](#high-level-system-overview)
2. [Network Topology](#network-topology)
3. [Network Layer Stack](#network-layer-stack)
4. [Kubernetes Architecture](#kubernetes-architecture)
5. [GitOps Workflow](#gitops-workflow)
6. [Storage Architecture](#storage-architecture)
7. [Observability Stack](#observability-stack)
8. [Service Mesh Integration](#service-mesh-integration)

---

## High-Level System Overview

```mermaid
flowchart TB
    subgraph Internet["Internet"]
        User[User/Client]
    end

    subgraph Homelab["Homelab Network (192.168.1.0/24)"]
        subgraph TalosCluster["Talos K8s Cluster"]
            CP[Control Plane<br/>192.168.1.54]
        end

        subgraph NAS["Storage Layer"]
            TrueNAS[TrueNAS<br/>192.168.1.200<br/>Media Storage]
            Synology[Synology NAS<br/>192.168.1.234<br/>App Configs]
        end
    end

    subgraph AWS["AWS Cloud"]
        Lighthouse[Nebula Lighthouse<br/>t3.micro<br/>10.42.0.1]

        subgraph GPUCluster["GPU Worker (On-Demand)"]
            GPUNode[k3s GPU Node<br/>g4dn.xlarge<br/>NVIDIA T4]
        end
    end

    User -->|HTTPS| CP
    CP <-->|NFS| TrueNAS
    CP <-->|NFS| Synology
    CP <-.->|Nebula VPN<br/>10.42.0.0/16| Lighthouse
    GPUNode <-.->|Nebula VPN| Lighthouse
    CP <-.->|Liqo<br/>Pod Offloading| GPUNode

    style CP fill:#326CE5,color:#fff
    style GPUNode fill:#FF9900,color:#fff
    style Lighthouse fill:#FF9900,color:#fff
    style TrueNAS fill:#0095D5,color:#fff
    style Synology fill:#4a4a4a,color:#fff
```

---

## Network Topology

### Physical + Overlay Network

```mermaid
flowchart TB
    subgraph PhysicalNet["Physical Network Layer"]
        direction LR
        subgraph HomeLAN["Home LAN (192.168.1.0/24)"]
            TalosNode[Talos Node<br/>192.168.1.54]
            Router[Router/Gateway<br/>192.168.1.1]
            NAS1[TrueNAS<br/>192.168.1.200]
            NAS2[Synology<br/>192.168.1.234]
        end

        subgraph AWSVPC["AWS VPC"]
            LH[Lighthouse<br/>Public IP]
            GPU[GPU Instance<br/>Private IP]
        end
    end

    subgraph NebulaOverlay["Nebula Overlay Network (10.42.0.0/16)"]
        direction LR
        LH_N[Lighthouse<br/>10.42.0.1]
        Talos_N[Talos Node<br/>10.42.1.1]
        GPU_N[GPU Node<br/>10.42.2.1]

        LH_N <-->|UDP Hole Punch| Talos_N
        LH_N <-->|UDP Hole Punch| GPU_N
        Talos_N <-.->|P2P Tunnel| GPU_N
    end

    subgraph PodNet["Pod Network (10.244.0.0/16)"]
        direction LR
        Pod1[Pod A<br/>10.244.0.x]
        Pod2[Pod B<br/>10.244.0.y]
        VirtualPod[Offloaded Pod<br/>via Liqo]
    end

    TalosNode --> Talos_N
    LH --> LH_N
    GPU --> GPU_N
    Talos_N --> Pod1
    Talos_N --> Pod2
    GPU_N --> VirtualPod

    style TalosNode fill:#326CE5,color:#fff
    style GPU fill:#FF9900,color:#fff
    style Talos_N fill:#7B68EE,color:#fff
    style GPU_N fill:#7B68EE,color:#fff
    style LH_N fill:#7B68EE,color:#fff
```

---

## Network Layer Stack

```mermaid
flowchart TB
    subgraph L7["Layer 7 - Application"]
        Linkerd[Linkerd Service Mesh<br/>mTLS, Observability]
        Traefik[Traefik Ingress<br/>IngressRoutes, TLS Term]
    end

    subgraph L4["Layer 4 - Multi-Cluster"]
        Liqo[Liqo Federation<br/>Virtual Nodes<br/>Pod Offloading]
    end

    subgraph L3Pod["Layer 3 - Pod Network"]
        Flannel[Flannel CNI<br/>VXLAN<br/>10.244.0.0/16]
    end

    subgraph L3Node["Layer 3 - Node Overlay"]
        Nebula[Nebula VPN<br/>AES-256-GCM<br/>10.42.0.0/16]
    end

    subgraph L2["Layer 2/3 - Physical"]
        Physical[Physical Network<br/>Ethernet/WiFi<br/>192.168.1.0/24 + AWS VPC]
    end

    External[External Traffic] --> Traefik
    Traefik --> Linkerd
    Linkerd --> Flannel
    Flannel --> Liqo
    Liqo --> Nebula
    Nebula --> Physical

    style Linkerd fill:#2beda7,color:#000
    style Traefik fill:#24a1c1,color:#fff
    style Liqo fill:#6366F1,color:#fff
    style Flannel fill:#1e3a5f,color:#fff
    style Nebula fill:#7B68EE,color:#fff
```

### Network Layer Details

| Layer        | Component | CIDR/Protocol   | Purpose                                                             |
| ------------ | --------- | --------------- | ------------------------------------------------------------------- |
| L7 (Mesh)    | Linkerd   | mTLS            | Service-to-service encryption, observability (active on scratch ns) |
| L7 (Ingress) | Traefik   | HTTP/HTTPS      | External access, routing, TLS termination                           |
| L4-L7        | Liqo      | Virtual Kubelet | Multi-cluster federation, pod offloading                            |
| L3 (Pod)     | Flannel   | 10.244.0.0/16   | Intra-cluster pod networking                                        |
| L3 (Overlay) | Nebula    | 10.42.0.0/16    | Encrypted inter-node tunnels                                        |
| L2-L3        | Physical  | 192.168.1.0/24  | Home network                                                        |

---

## Kubernetes Architecture

### Cluster Components

```mermaid
flowchart TB
    subgraph ControlPlane["Control Plane (192.168.1.54)"]
        API[kube-apiserver<br/>Port 6443]
        ETCD[etcd<br/>Cluster State]
        Scheduler[kube-scheduler]
        Controller[controller-manager]
        Talos[Talos API<br/>Port 50000]
    end

    subgraph CoreServices["Core Platform Services"]
        direction TB
        ArgoCD[ArgoCD<br/>GitOps Controller]
        Traefik2[Traefik<br/>Ingress Controller]
        Registry[Nexus Registry<br/>Docker/npm/PyPI]
        ESO[External Secrets<br/>Operator]
        LocalPath[Local Path<br/>Provisioner]
    end

    subgraph Observability["Observability Stack"]
        Prometheus[Prometheus<br/>Metrics]
        Grafana[Grafana<br/>Dashboards]
        Graylog[Graylog<br/>Log Management]
        FluentBit[Fluent Bit<br/>Log Collection]
        OpenSearch[OpenSearch<br/>Log Storage]
    end

    subgraph HybridComponents["Hybrid Cluster Components"]
        NebulaAgent[Nebula Agent<br/>DaemonSet]
        LiqoCtrl[Liqo Controller<br/>Federation]
        LinkerdCP[Linkerd<br/>Control Plane]
        VirtualNode[Virtual Node<br/>liqo-aws-gpu]
    end

    subgraph Applications["Application Workloads"]
        ArrStack[*arr Stack<br/>Media Automation]
        CatalystUI[Catalyst UI<br/>Dashboard]
        Homepage[Homepage<br/>Homelab Dashboard]
        Scratch[Scratch Projects<br/>gRPC Examples]
    end

    API --> CoreServices
    API --> Observability
    API --> HybridComponents
    API --> Applications

    style API fill:#326CE5,color:#fff
    style ArgoCD fill:#EF7B4D,color:#fff
    style Traefik2 fill:#24a1c1,color:#fff
    style Prometheus fill:#E6522C,color:#fff
    style Grafana fill:#F46800,color:#fff
    style VirtualNode fill:#6366F1,color:#fff
```

### Namespace Organization

```mermaid
flowchart LR
    subgraph Platform["Platform Namespaces"]
        argocd[argocd]
        traefik[traefik]
        registry[registry]
        monitoring[monitoring]
        observability[observability]
        linkerd[linkerd]
        nebula[nebula-system]
        liqo[liqo-system]
        eso[external-secrets]
    end

    subgraph Apps["Application Namespaces"]
        media[media-prod]
        catalyst[catalyst]
        scratch[scratch]
        homepage[homepage]
    end

    subgraph System["System Namespaces"]
        kube[kube-system]
        local[local-path-storage]
    end

    Platform --> |Managed by| InfraRepo[talos-homelab repo<br/>Manual Deploy]
    Apps --> |Managed by| ArgoApp[ArgoCD<br/>Auto-sync]
    System --> |Managed by| TalosOS[Talos OS]

    style InfraRepo fill:#326CE5,color:#fff
    style ArgoApp fill:#EF7B4D,color:#fff
    style TalosOS fill:#FF6B00,color:#fff
```

---

## GitOps Workflow

### Dual GitOps Pattern

```mermaid
flowchart TB
    subgraph Developer["Developer Workflow"]
        Dev[Developer]
    end

    subgraph InfraGitOps["Infrastructure GitOps"]
        InfraRepo[(talos-homelab<br/>GitHub Repo)]
        Scripts[Deploy Scripts<br/>./scripts/*.sh]
        Kubectl[kubectl apply -k]
    end

    subgraph AppGitOps["Application GitOps"]
        AppRepo[(catalyst-ui<br/>GitHub Repo)]
        ArgoCDCtrl[ArgoCD Controller]
        AutoSync[Auto-sync<br/>every 3 min]
    end

    subgraph Cluster["Kubernetes Cluster"]
        Platform[Platform Services<br/>ArgoCD, Traefik, etc.]
        Apps[Applications<br/>Catalyst UI, *arr, etc.]
    end

    Dev -->|1. Edit manifests| InfraRepo
    Dev -->|2. Run script| Scripts
    Scripts -->|3. Apply| Kubectl
    Kubectl -->|4. Deploy| Platform

    Dev -->|1. Push code| AppRepo
    AppRepo -->|2. Webhook/Poll| ArgoCDCtrl
    ArgoCDCtrl -->|3. Detect change| AutoSync
    AutoSync -->|4. Apply| Apps

    style InfraRepo fill:#24292e,color:#fff
    style AppRepo fill:#24292e,color:#fff
    style ArgoCDCtrl fill:#EF7B4D,color:#fff
    style Platform fill:#326CE5,color:#fff
    style Apps fill:#2beda7,color:#000
```

### Infrastructure Deployment Flow

```mermaid
sequenceDiagram
    participant Dev as Developer
    participant Git as talos-homelab
    participant Script as deploy-stack.sh
    participant K8s as Kubernetes API

    Dev->>Git: 1. Modify manifests
    Dev->>Git: 2. git commit & push
    Dev->>Script: 3. ./scripts/deploy-stack.sh
    Script->>Script: 4. Check cluster health
    Script->>K8s: 5. kubectl apply -k namespaces/
    Script->>K8s: 6. kubectl apply -k infrastructure/
    Script->>K8s: 7. Wait for pods ready
    K8s-->>Dev: 8. Deployment complete
```

### Application Deployment Flow

```mermaid
sequenceDiagram
    participant Dev as Developer
    participant AppGit as catalyst-ui repo
    participant ArgoCD as ArgoCD
    participant K8s as Kubernetes

    Dev->>AppGit: 1. Push to main branch
    Note over ArgoCD: Polls every 3 min
    ArgoCD->>AppGit: 2. Detect new commit
    ArgoCD->>ArgoCD: 3. Compare desired vs actual
    ArgoCD->>K8s: 4. Apply manifests
    K8s->>K8s: 5. Rolling update
    ArgoCD-->>Dev: 6. Sync status: Healthy
```

---

## Storage Architecture

### Storage Topology

```mermaid
flowchart TB
    subgraph Cluster["Kubernetes Cluster"]
        subgraph LocalStorage["Local Storage"]
            LocalPath[local-path-provisioner<br/>Default StorageClass]
            DBs[(Databases<br/>PostgreSQL, MongoDB)]
        end

        subgraph NFSClients["NFS Mounts"]
            MediaPV[Media PVs]
            ConfigPV[Config PVs]
            DownloadPV[Download PVs]
        end
    end

    subgraph TrueNAS["TrueNAS (192.168.1.200)"]
        MegaPool[/mnt/megapool/]
        Movies[(movies/)]
        TV[(tv/)]
        Music[(music/)]
        Books[(books/)]
        Downloads[(downloads/)]
    end

    subgraph Synology["Synology (192.168.1.234)"]
        Volume1[/volume1/]
        AppData[(appdata/<br/>Dynamic Provisioner)]
        SynoMedia[(media/)]
        SynoDownloads[(downloads/)]
    end

    LocalPath --> DBs
    MediaPV -->|NFS| Movies
    MediaPV -->|NFS| TV
    MediaPV -->|NFS| Music
    MediaPV -->|NFS| Books
    ConfigPV -->|NFS Dynamic| AppData
    DownloadPV -->|NFS| Downloads
    DownloadPV -->|NFS| SynoDownloads

    style TrueNAS fill:#0095D5,color:#fff
    style Synology fill:#4a4a4a,color:#fff
    style LocalPath fill:#326CE5,color:#fff
```

### Storage Classes

```mermaid
flowchart LR
    subgraph StorageClasses["Storage Classes"]
        LP[local-path<br/>DEFAULT]
        TN[truenas-nfs<br/>Static]
        SN[synology-nfs<br/>Static]
        FB[fatboy-nfs-appdata<br/>Dynamic]
    end

    subgraph UseCases["Use Cases"]
        DB[Databases<br/>Fast I/O Required]
        Media[Media Libraries<br/>Large Files]
        Config[App Configs<br/>Dynamic Provisioning]
    end

    LP --> DB
    TN --> Media
    SN --> Media
    FB --> Config

    style LP fill:#326CE5,color:#fff
    style TN fill:#0095D5,color:#fff
    style FB fill:#4a4a4a,color:#fff
```

---

## Observability Stack

### Monitoring & Logging Architecture

```mermaid
flowchart TB
    subgraph DataSources["Data Sources"]
        Apps[Application Pods]
        K8s[Kubernetes Components]
        Nodes[Node Metrics]
        Exporters[Service Exporters<br/>exportarr, etc.]
    end

    subgraph Collection["Collection Layer"]
        FluentBit2[Fluent Bit<br/>DaemonSet]
        PodMonitor[PodMonitor/<br/>ServiceMonitor]
    end

    subgraph Storage2["Storage Layer"]
        Prometheus2[Prometheus<br/>50Gi, 30d retention]
        OpenSearch2[OpenSearch<br/>30Gi]
        MongoDB2[MongoDB<br/>20Gi - Graylog meta]
    end

    subgraph Visualization["Visualization Layer"]
        Grafana2[Grafana<br/>Dashboards]
        Graylog2[Graylog<br/>Log Search]
        AlertManager[AlertManager<br/>Alerts]
    end

    Apps -->|stdout/stderr| FluentBit2
    K8s -->|metrics| PodMonitor
    Nodes -->|node_exporter| PodMonitor
    Exporters -->|custom metrics| PodMonitor

    FluentBit2 -->|GELF| Graylog2
    FluentBit2 -->|JSON| OpenSearch2
    PodMonitor -->|scrape| Prometheus2

    Prometheus2 --> Grafana2
    Prometheus2 --> AlertManager
    OpenSearch2 --> Graylog2

    style Prometheus2 fill:#E6522C,color:#fff
    style Grafana2 fill:#F46800,color:#fff
    style Graylog2 fill:#FF3366,color:#fff
    style OpenSearch2 fill:#005EB8,color:#fff
    style FluentBit2 fill:#49BDA5,color:#fff
```

### Metrics Flow

```mermaid
flowchart LR
    subgraph Targets["Scrape Targets"]
        SM1[ServiceMonitor<br/>kube-prometheus-stack]
        SM2[ServiceMonitor<br/>exportarr]
        SM3[ServiceMonitor<br/>traefik]
        PM[PodMonitor<br/>app metrics]
    end

    subgraph Prom["Prometheus"]
        Scraper[Prometheus<br/>Scraper]
        TSDB[(TSDB<br/>50Gi)]
        Rules[Recording &<br/>Alerting Rules]
    end

    subgraph Consumers["Consumers"]
        Graf[Grafana<br/>Dashboards]
        AM[AlertManager<br/>Routing]
        API[Prometheus API<br/>Queries]
    end

    SM1 --> Scraper
    SM2 --> Scraper
    SM3 --> Scraper
    PM --> Scraper
    Scraper --> TSDB
    TSDB --> Rules
    TSDB --> Graf
    Rules --> AM
    TSDB --> API

    style Scraper fill:#E6522C,color:#fff
    style Graf fill:#F46800,color:#fff
```

---

## Service Mesh Integration

### Linkerd + Nebula + Liqo Stack

```mermaid
flowchart TB
    subgraph HomelabCluster["Homelab Cluster"]
        subgraph MeshedPods["Meshed Pods (scratch ns)"]
            PodA[Pod A<br/>+ Linkerd Proxy]
            PodB[Pod B<br/>+ Linkerd Proxy]
        end

        LinkerdCP2[Linkerd<br/>Control Plane]
        LiqoVK[Liqo<br/>Virtual Kubelet]
        NebulaD[Nebula<br/>DaemonSet]
    end

    subgraph AWSCluster["AWS GPU Cluster"]
        subgraph OffloadedPods["Offloaded Pods"]
            GPUPod[Ollama Pod<br/>+ Linkerd Proxy]
        end

        LiqoProvider[Liqo<br/>Provider]
        NebulaD2[Nebula<br/>Agent]
    end

    PodA <-->|mTLS| PodB
    PodA <-->|mTLS via Liqo| GPUPod

    LinkerdCP2 -.->|Inject| MeshedPods
    LiqoVK <-->|Peering| LiqoProvider
    NebulaD <-->|Encrypted Tunnel| NebulaD2

    style PodA fill:#2beda7,color:#000
    style PodB fill:#2beda7,color:#000
    style GPUPod fill:#FF9900,color:#fff
    style LinkerdCP2 fill:#2beda7,color:#000
    style LiqoVK fill:#6366F1,color:#fff
    style NebulaD fill:#7B68EE,color:#fff
```

### Security Layers

```mermaid
flowchart TB
    subgraph Encryption["Encryption Layers"]
        L1[Layer 1: Nebula<br/>Node-to-Node<br/>AES-256-GCM]
        L2[Layer 2: Linkerd<br/>Pod-to-Pod<br/>mTLS]
        L3[Layer 3: Traefik<br/>Client-to-Ingress<br/>TLS 1.3]
    end

    External[External Client] -->|TLS| L3
    L3 -->|mTLS| L2
    L2 -->|AES-256| L1
    L1 --> Pod[Target Pod]

    style L1 fill:#7B68EE,color:#fff
    style L2 fill:#2beda7,color:#000
    style L3 fill:#24a1c1,color:#fff
```

---

## Quick Reference

### Key IPs and Ports

| Service         | Address       | Port     |
| --------------- | ------------- | -------- |
| Talos API       | 192.168.1.54  | 50000    |
| Kubernetes API  | 192.168.1.54  | 6443     |
| Nebula Overlay  | 10.42.x.x     | UDP 4242 |
| Pod Network     | 10.244.x.x    | -        |
| Service Network | 10.96.x.x     | -        |
| TrueNAS NFS     | 192.168.1.200 | 2049     |
| Synology NFS    | 192.168.1.234 | 2049     |

### Service URLs

| Service    | URL                          |
| ---------- | ---------------------------- |
| ArgoCD     | http://argocd.talos00        |
| Grafana    | http://grafana.talos00       |
| Prometheus | http://prometheus.talos00    |
| Graylog    | http://graylog.talos00       |
| Nexus      | http://nexus.talos00         |
| Registry   | http://registry.talos00:5000 |
| Homepage   | http://homepage.talos00      |

---

**Last Updated**: 2025-11-30
**Maintained By**: Infrastructure Team
