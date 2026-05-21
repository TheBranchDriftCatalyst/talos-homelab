# System Analysis Report: Talos Homelab Kubernetes Platform

**Date:** 2026-03-14
**Repository:** `talos-homelab` at commit `9163fc7` (main branch)
**Scope:** 257 infrastructure manifests, 30+ Flux Kustomizations, 6 ArgoCD Applications, 7 nodes

---

## Executive Summary

This report consolidates independent analyses from three senior engineering perspectives -- Data Pipeline Engineering, Machine Learning Engineering, and Enterprise Software Architecture -- to provide a comprehensive assessment of the talos-homelab Kubernetes platform.

**Overall Assessment: Advanced Homelab / Entry-level Production**

The platform demonstrates remarkable sophistication for a personal infrastructure project. Key highlights:

- **Modern observability stack** (Mimir/Loki/Tempo/Alloy) with production-grade telemetry collection, cross-signal correlation, and tiered retention (7d traces / 30d logs / 1y metrics)
- **Mature dual GitOps pattern** with clear Flux (infrastructure) / ArgoCD (applications) separation and explicit dependency chains
- **ML-ready infrastructure** with heterogeneous GPU fleet (Intel Arc, NVIDIA Quadro, AMD Vega), 64GB RAM inference node, and scaffolded LLM serving stack
- **Strong secrets management** via 1Password + External Secrets Operator (with one critical exception: MinIO credentials)
- **Comprehensive automation** with 90+ Taskfile tasks, Lefthook git hooks, and Tilt ops dashboard
- **Outstanding documentation** with 5-level progressive summarization and AI-optimized CLAUDE.md

**Top 5 Risks (cross-cutting):**

1. **Backup circular dependency** -- Velero backs up to MinIO on the same NAS; a NAS failure loses both data and backups
2. **Hardcoded MinIO credentials** -- `minio`/`minio123` in 6+ manifest files; immediate risk if repo becomes public
3. **Single control plane** -- no etcd quorum, no API server redundancy
4. **No network policies** on most namespaces -- lateral movement risk from any compromised pod
5. **No alerting rules defined** -- Mimir rules directory is empty; no alerts for pipeline failures, disk space, or backup failures

---

## Section 1: Data Pipeline Engineering Analysis

### Current Data Architecture

The cluster operates a modern Grafana LGTM telemetry stack unified through Grafana Alloy as the sole collection agent:

```
Applications/Pods
    │
    ├─ Logs ──> Alloy (K8s API + OTLP) ──> Loki (SingleBinary) ──> MinIO S3
    │
    ├─ Metrics ──> Alloy (Prometheus scrape + OTLP) ──> Mimir (Distributed) ──> MinIO S3
    │
    └─ Traces ──> Alloy (OTLP gRPC/HTTP) ──> Tempo (SingleBinary) ──> MinIO S3
                                                      │
                                                      └──> Metrics Generator ──> Mimir
```

**Metrics Collection Coverage:**

| Scrape Target | Interval | Method |
|---------------|----------|--------|
| Kubelet / cAdvisor | 60s | K8s API proxy (HTTPS) |
| Pod annotations (`prometheus.io/scrape`) | 60s | HTTP |
| Kube-State-Metrics | 60s | HTTP |
| Node Exporter | 60s | HTTP |
| Hubble (Cilium) | 30s | HTTP |
| ArgoCD | 30s | HTTP |
| Blackbox Probes (7 targets) | 60s | HTTP |
| Traefik | 30s | HTTP |
| MinIO | 60s | HTTP |
| ServiceMonitors / PodMonitors | varies | Operator CRDs |

**Custom Exporters:** Tdarr (transcoding metrics), Kasa (smart plug power), Exportarr (Sonarr/Radarr/Prowlarr/Readarr -- currently broken with placeholder API keys).

### Storage Tiers & Retention

| Tier | Backend | Use Case | Capacity |
|------|---------|----------|----------|
| `local-path` (SSD) | Rancher provisioner | Databases, WAL, caches | ~85Gi allocated |
| `fatboy-nfs-appdata` | Synology NAS (192.168.1.36) | App configs, MinIO, Nexus | ~200Gi+ |
| `synology-nfs` (static PVs) | Synology NAS | Media libraries | ~62Ti |
| MinIO S3 | Object storage on NFS | Telemetry, backups, Dagster | 100Gi pool |

| Data Type | Retention | Storage Backend |
|-----------|-----------|-----------------|
| Metrics (Mimir) | 1 year | MinIO `mimir` bucket |
| Logs (Loki) | 30 days | MinIO `loki` bucket |
| Traces (Tempo) | 7 days | MinIO `tempo` bucket |
| Velero daily backups | 30 days | MinIO `velero` bucket |
| Velero weekly backups | 90 days | MinIO `velero` bucket |
| etcd snapshots | 7 days | MinIO `backups/etcd` |
| Nexus artifacts | Unbounded | NFS 100Gi PVC |

### Key Data Pipeline Findings

**Strengths:**
- Unified collection agent (Alloy) eliminates multi-agent sprawl
- Comprehensive Kubernetes discovery with proper label propagation
- Cross-signal correlation configured (trace-to-log, trace-to-metric, service graphs)
- S3-backed telemetry enables independent scaling of compute and storage
- Mimir rules sync from PrometheusRule CRDs enables app-repo-defined alerting
- Label consistency (`cluster=talos-homelab`) prepares for multi-cluster scenarios

**Critical Gaps:**
- Tempo WAL persistence disabled -- pod restart loses in-flight traces
- Single replica everything -- any pod restart causes complete pipeline outage
- MinIO single-server with no erasure coding or replication
- Loki has ingestion rate limits but no documented backpressure mechanism
- Nexus has no lifecycle policies -- will fill 100Gi over time
- RabbitMQ dashboard exists but no RabbitMQ deployment

### Data Pipeline Recommendations

| Priority | Recommendation | Effort |
|----------|---------------|--------|
| P0 | Implement off-site backup (Backblaze B2 or second NAS) | Medium |
| P0 | Enable Tempo WAL persistence (5-10Gi PVC) | Low |
| P1 | Create alerting rules in Mimir (pod health, pipeline health, backups, storage) | Medium |
| P1 | Migrate MinIO credentials to ExternalSecrets | Low |
| P1 | Fix Exportarr API keys or remove non-functional deployments | Low |
| P1 | Bake `mc` into etcd-backup image (remove runtime `wget`) | Low |
| P2 | Add Alloy OTLP retry/backoff configuration | Low |
| P2 | Configure Nexus cleanup policies | Low |

---

## Section 2: Machine Learning Engineering Analysis

### Compute Resources

| Node | CPU | RAM | GPU/Accelerator | ML Capability |
|------|-----|-----|-----------------|---------------|
| talos00 | Control Plane | - | None | Scheduling only |
| talos01 | Intel 12th Gen | - | None | General compute |
| talos02 | Intel Core Ultra 5 225H | - | Intel Arc 130T (GPU WEDGED) | Unavailable |
| talos03 | AMD Ryzen 7 5800U (8c/16t) | 16GB | AMD Radeon Vega (ROCm) | Light inference |
| talos04 | 8 vCPU (VM) | 16GB | NVIDIA Quadro P2000 (5GB VRAM) | Small model inference, transcoding |
| talos05 | VM (QEMU/KVM) | - | NVIDIA (passthrough) | GPU compute |
| **talos06** | **Intel Core Ultra 9 285H (24c/24t)** | **64GB** | **Intel Arc 140T (8 Xe cores)** + **NPU (13 TOPS)** | **Primary ML node** |

### ML Infrastructure Status

| Component | Status | Details |
|-----------|--------|---------|
| Ollama | Archived/scaffolded | Full deployment spec exists targeting talos06 with Intel GPU |
| LiteLLM | Active (external repo) | ArgoCD-managed from `catalyst-llm` repo, multi-provider proxy |
| Intel GPU Plugin | Deployed | NFD + Intel Device Plugins Operator, `sharedDevNum: 4` |
| NVIDIA Device Plugin | Documented only | Not codified as infrastructure manifests |
| Model Registry | Missing | No MLflow, W&B, or equivalent |
| Experiment Tracking | Missing | No dedicated tooling |
| Feature Store | Missing | Not present |
| Training Infrastructure | Not present | No Kubeflow, Ray, or distributed training |
| Knowledge Graph (The Corpus) | In development | Neo4j + embeddings + NER via Dagster |
| Hybrid Cloud GPU Burst | Commented out | Nebula + Liqo architecture designed but inactive |

### ML Integration Opportunities

The cluster has strong foundations that ML workloads can leverage:

- **MinIO S3** -- model artifacts, datasets, Dagster IO (versioning enabled)
- **CloudNativePG** -- PostgreSQL with pgvector support for embedding storage
- **Dagster** (catalyst-data repo) -- workflow orchestration for training/inference pipelines
- **ArgoCD Image Updater** -- "push model container, auto-deploy" workflow
- **OTEL stack** -- inference latency, throughput, and accuracy monitoring ready
- **Pushgateway** -- training jobs can push epoch loss and validation metrics
- **External Secrets** -- API keys for Anthropic, OpenAI, RunPod, HuggingFace
- **Authentik SSO** -- already integrated with LiteLLM for user management

### ML Engineering Recommendations

| Phase | Recommendation | Timeline |
|-------|---------------|----------|
| **Phase 1: Foundation** | Activate catalyst-llm stack (ArgoCD app exists) | Week 1-2 |
| | Codify NVIDIA device plugin as Kustomize manifests | Week 1-2 |
| | Add GPU resource quotas for catalyst-llm namespace | Week 1-2 |
| | Create GPU monitoring Grafana dashboard | Week 1-2 |
| | Fix talos02 GPU wedge (cold boot) | Week 1-2 |
| **Phase 2: MLOps** | Deploy MLflow (MinIO artifacts + CloudNativePG metadata) | Week 3-6 |
| | Add pgvector to CloudNativePG for embedding storage | Week 3-6 |
| | Integrate ML pipelines into Dagster code locations | Week 3-6 |
| | Deploy KEDA for autoscaling on inference queue depth | Week 3-6 |
| | Create ML PriorityClass (inference: high, training: medium) | Week 3-6 |
| **Phase 3: Advanced** | Activate hybrid cloud GPU burst (Nebula + Liqo + AWS) | Month 2-3 |
| | Deploy OpenVINO Model Server for Intel Arc optimization | Month 2-3 |
| | Build RAG pipeline (The Corpus + Neo4j + pgvector + Ollama) | Month 2-3 |

---

## Section 3: Enterprise Software Architecture Analysis

### Architecture Overview

```
                    ┌─────────────────────┐
                    │    Internet/WAN      │
                    │  knowledgedump.space  │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  Cloudflare (DDNS)   │
                    │  + Let's Encrypt     │
                    └──────────┬──────────┘
                               │
               ┌───────────────▼───────────────┐
               │     Home Router / NAT          │
               │     192.168.1.0/24             │
               └───────────────┬───────────────┘
                               │
    ┌──────────────────────────┼──────────────────────────┐
    │                          │                          │
 Synology NAS          talos00 (CP)              talos01-06
 .1.36                 192.168.1.54              (Workers)
 NFS exports           Traefik:80/443           GPU nodes
                       Cilium CNI
                               │
                      ┌────────▼────────┐
                      │  Nebula Overlay  │
                      │  10.100.0.0/16   │
                      └────────┬────────┘
                               │
                      ┌────────▼────────┐
                      │  AWS K3s (opt)   │
                      │  g4dn.xlarge     │
                      └─────────────────┘
```

### Dual GitOps Deployment Model

```
Git Push to main
    │
    ├──> Flux (1m poll) ──> Reconciles infrastructure/*
    │       │
    │       ├── Namespaces (prune: false)
    │       ├── Storage ──> Databases ──> MinIO ──> Monitoring
    │       ├── External Secrets Operator ──> External Secrets
    │       │       ├── ArgoCD
    │       │       ├── Cloudflare DDNS
    │       │       ├── VPN Gateway
    │       │       └── Authentik
    │       ├── Traefik ──> cert-manager ──> cert-manager-issuers
    │       └── Intel GPU ──> arr-stack
    │
    └──> ArgoCD (auto-sync) ──> External repos
            ├── catalyst-ui (React UI)
            ├── catalyst-llm (LLM platform)
            ├── catalyst-data (Dagster pipelines)
            ├── gateway-arr (API gateway)
            └── kasa-exporter (IoT metrics)
```

### Infrastructure-as-Code Maturity

| Aspect | Rating | Evidence |
|--------|--------|---------|
| Declarative config | Excellent | 257 YAML manifests, all Kustomize-managed |
| Version pinning | Good | Helm charts use semver ranges, cert-manager pinned |
| Modular structure | Excellent | 29 component directories in `infrastructure/base/` |
| Overlay pattern | Good | arr-stack uses base/gpu/themepark chain |
| Dependency management | Excellent | Flux Kustomization `dependsOn` DAG |
| Environment separation | Partial | Docker-based local cluster, no staging |
| Reproducibility | Good | Fully automated provisioning scripts |

### Security Assessment

**Secrets Management:**
- 1Password + ESO for ArgoCD, Cloudflare, Authentik, VPN, External DNS, Kasa
- **CRITICAL GAP:** MinIO `minio`/`minio123` hardcoded in 6+ manifests

**Network Security:**
- Cilium eBPF with kube-proxy replacement and SPIRE mTLS (enabled, not enforced)
- Hubble flow observability with rich metrics
- **GAP:** Only honeypot namespace has CiliumNetworkPolicy (default-deny)
- **GAP:** WireGuard node encryption broken (VXLAN tunnel mode issue)

**Access Control:**
- Talos: No SSH, API-only access with PKI auth
- ArgoCD: Default `role:readonly`, explicit admin escalation
- Authentik: SSO/OIDC deployed, LiteLLM integrated
- **GAP:** No PodSecurityAdmission enforcement, no admission controller

**Supply Chain:**
- Some services use `:latest` tags (Cowrie, Gluetun, DDNS)
- No image scanning (Trivy/Snyk)
- ArgoCD Image Updater provides controlled updates for ArgoCD apps

### Technical Debt Register

| Item | Severity | Effort |
|------|----------|--------|
| Hardcoded MinIO credentials | HIGH | Low |
| Missing network policies on most namespaces | HIGH | Medium |
| Backup storage co-located with workloads | HIGH | High |
| Single control plane (no HA) | HIGH | High |
| No CI/CD pipeline (GitHub Actions) | MEDIUM | Medium |
| `:latest` image tags on multiple services | MEDIUM | Low |
| No admission controller (Kyverno/OPA) | MEDIUM | Medium |
| No PodSecurity enforcement | MEDIUM | Medium |
| Traefik API insecure + running as root | MEDIUM | Medium |
| WireGuard node encryption broken | MEDIUM | High |
| Suspended/deprecated configs not cleaned | LOW | Trivial |
| cluster-settings ConfigMap incomplete | LOW | Low |
| Documentation references 2-node cluster | LOW | Low |

### Enterprise Architecture Recommendations

**Quick Wins (1-2 hours each):**

1. Migrate MinIO credentials to 1Password/ESO
2. Pin image tags (replace `:latest`)
3. Clean up deprecated/suspended configs
4. Complete cluster-settings ConfigMap with all node IPs
5. Add PSA labels to namespaces

**Medium-term (1-2 days each):**

6. Implement namespace-level CiliumNetworkPolicies (extend honeypot pattern)
7. Set up GitHub Actions CI (yamllint, shellcheck, kustomize build, gitleaks)
8. Add offsite backup target (Backblaze B2 or Wasabi)
9. Deploy Kyverno for policy enforcement
10. Bake `mc` into etcd-backup image

**Strategic (1+ weeks):**

11. Add second control plane node for HA
12. Enforce Cilium mTLS on sensitive services
13. Complete Authentik SSO rollout across all services
14. GitOps for Talos configs (SOPS-encrypted in git)
15. Build staging environment with Docker-based Talos

---

## Cross-Cutting Themes

### Theme 1: Single Points of Failure

All three analyses independently identified the concentration of risk around single-instance components:

- **MinIO** -- sole S3 backend for telemetry, backups, and Dagster data (1 server, 1 volume, no replication)
- **Control plane** -- single etcd node means total cluster loss on failure
- **Synology NAS** -- all NFS storage (media + app configs + MinIO data) on one device
- **Every service** -- single replica deployments throughout the stack

**Recommendation:** Prioritize off-site backup (eliminates catastrophic data loss risk with moderate effort) over HA deployments (high effort, lower probability).

### Theme 2: Security Posture Gap

The platform has excellent secrets management (1Password/ESO) but inconsistent application:

- MinIO credentials bypass the established ESO pattern
- Network policies exist only for the honeypot
- No admission controller enforces security baselines
- Traefik runs as root with insecure API

**Recommendation:** The 1Password/ESO pattern is proven and well-understood. Extending it to MinIO is a quick win. Network policies should follow the honeypot's default-deny pattern.

### Theme 3: Monitoring Without Alerting

The observability stack is production-grade, but it's passive:

- No PrometheusRule CRDs defined (Mimir rules directory empty)
- No alerts for pipeline failures, storage capacity, backup failures, or pod health
- Blackbox probes check health but don't trigger alerts
- No SLA/SLO definitions

**Recommendation:** Define a minimal alerting ruleset covering the top failure modes: pod crash loops, storage capacity, backup failures, and ingestion errors.

### Theme 4: ML Infrastructure at Crossroads

The ML infrastructure exists as a compelling prototype that needs activation:

- Ollama + LiteLLM stack fully designed but archived/extracted
- Intel GPU plugin deployed and working
- NVIDIA GPU support documented but not codified
- Knowledge graph pipeline (The Corpus) shows clear ML/NLP direction
- Hybrid cloud GPU burst architecture designed but commented out

**Recommendation:** The `catalyst-llm` ArgoCD Application already exists. Ensuring the external repo has working manifests is the fastest path to a functioning ML inference platform.

---

## Prioritized Action Plan

### Immediate (This Week)

| # | Action | Impact | Effort | Source |
|---|--------|--------|--------|--------|
| 1 | Implement off-site backup | Eliminates catastrophic data loss | Medium | All three |
| 2 | Enable Tempo WAL persistence | Prevents trace data loss | Low | Data Pipeline |
| 3 | Migrate MinIO creds to ESO | Fixes critical security gap | Low | Enterprise Arch |
| 4 | Fix Exportarr API keys | Restores media stack metrics | Low | Data Pipeline |

### Short-term (Next 2 Weeks)

| # | Action | Impact | Effort | Source |
|---|--------|--------|--------|--------|
| 5 | Create alerting rules (Mimir) | Enables proactive monitoring | Medium | Data Pipeline + Enterprise |
| 6 | Add namespace CiliumNetworkPolicies | Reduces lateral movement risk | Medium | Enterprise Arch |
| 7 | Pin `:latest` image tags | Reproducible deployments | Low | Enterprise Arch |
| 8 | Activate catalyst-llm stack | ML inference capability | Low | ML Engineer |
| 9 | Codify NVIDIA device plugin | Completes GPU infra | Low | ML Engineer |
| 10 | Set up GitHub Actions CI | Quality gates in CI | Medium | Enterprise Arch |

### Medium-term (Next 1-2 Months)

| # | Action | Impact | Effort | Source |
|---|--------|--------|--------|--------|
| 11 | Deploy MLflow | ML experiment tracking | Medium | ML Engineer |
| 12 | Add second control plane node | Eliminates biggest SPOF | High | Enterprise Arch |
| 13 | Deploy Kyverno admission controller | Policy enforcement | Medium | Enterprise Arch |
| 14 | Add pgvector to CloudNativePG | Embedding storage for RAG | Medium | ML Engineer |
| 15 | Configure Nexus lifecycle policies | Prevents storage exhaustion | Low | Data Pipeline |

### Strategic (Next Quarter)

| # | Action | Impact | Effort | Source |
|---|--------|--------|--------|--------|
| 16 | Activate hybrid cloud GPU burst | Scale ML beyond homelab | High | ML Engineer |
| 17 | Build RAG pipeline (Corpus + pgvector + Ollama) | Knowledge-grounded inference | High | ML Engineer |
| 18 | Complete Authentik SSO rollout | Unified access control | Medium | Enterprise Arch |
| 19 | Enforce Cilium mTLS | Zero-trust networking | High | Enterprise Arch |
| 20 | GitOps for Talos configs (SOPS) | Fully reproducible provisioning | Medium | Enterprise Arch |

---

*Analysis performed on 2026-03-14 by three specialized AI agents (Data Pipeline Engineer, ML Engineer, Enterprise Software Architect) against the talos-homelab repository at commit 9163fc7.*

*Full individual analyses available at:*
- `.output/analysis-data-pipeline.md`
- `.output/analysis-ml-engineer.md`
- `.output/analysis-enterprise-architect.md`
