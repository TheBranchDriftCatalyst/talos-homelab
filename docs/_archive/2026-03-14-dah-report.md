# System Analysis Report: Talos Homelab Kubernetes Platform

**Date:** 2026-03-14
**Last fact-checked:** 2026-08-22 (claims re-verified against the repo and the live cluster; drifted facts corrected in place and marked)
**Repository:** `talos-homelab` at commit `9163fc7` (main branch)
**Scope (as of 2026-08-22):** ~570 YAML manifests under `infrastructure/base/`, 45 component directories, 59 Flux Kustomizations, 8 ArgoCD Applications, 5 nodes

> **How to read this document.** It is a point-in-time analysis from 2026-03-14. It has since been
> re-grounded against reality. Findings that have been **resolved or materially changed** are marked
> inline (`✅ RESOLVED` / `⚠️ CHANGED`) rather than deleted, so the original assessment and its outcome
> both stay legible. Unmarked findings were re-verified and still hold.

---

## Executive Summary

This report consolidates independent analyses from three senior engineering perspectives -- Data Pipeline Engineering, Machine Learning Engineering, and Enterprise Software Architecture -- to provide a comprehensive assessment of the talos-homelab Kubernetes platform.

**Overall Assessment: Advanced Homelab / Entry-level Production**

The platform demonstrates remarkable sophistication for a personal infrastructure project. Key highlights:

- **Modern observability stack** (Mimir/Loki/Tempo/Alloy) with production-grade telemetry collection, cross-signal correlation, and tiered retention (7d traces / 30d logs / 1y metrics) — all three retention values re-verified in the HelmReleases
- **Mature dual GitOps pattern** with clear Flux (infrastructure) / ArgoCD (applications) separation and explicit dependency chains
- **ML-ready infrastructure** with an Intel Arc GPU fleet (Arc 130T on talos02-gpu, Arc 140T on talos06), two 64GB RAM nodes, and an active LiteLLM serving stack. ⚠️ **CHANGED:** the NVIDIA Quadro (talos05) and second NVIDIA VM (talos04) nodes have been decommissioned; talos03's AMD Vega is not exposed as a schedulable device.
- **Strong secrets management** via 1Password + External Secrets Operator (the former MinIO-credential exception is resolved — see below)
- **Comprehensive automation** with 147 Taskfile tasks across the modular `Taskfile.{talos,k8s,dev,infra}.yaml` split, Lefthook git hooks, and a Tilt ops dashboard
- **Outstanding documentation** with progressive summarization and AI-optimized CLAUDE.md

**Top 5 Risks (cross-cutting):**

1. **Backup circular dependency** -- Velero backs up to MinIO, whose only volume is a `fatboy-nfs-appdata` PVC on the same Synology NAS that holds app data; a NAS failure loses both data and backups. Still true: one `BackupStorageLocation` (`backup/default`), no off-site target.
2. **~~Hardcoded MinIO credentials~~ (✅ RESOLVED — TALOS-tmqq)** -- the former public MinIO root literal has been rotated and moved to 1Password (item `minio`); all S3 consumers now source it via per-namespace ExternalSecrets. No credential literal remains in git. Verified: `infrastructure/base/minio/tenant.yaml` templates `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD` from an ExternalSecret.
3. **Single control plane** -- no etcd quorum, no API server redundancy. Still true: `talos00` is the only control-plane node. HA promotion of talos01 + talos06 is tracked as an open epic (TALOS-arx).
4. **No network policies** on most namespaces -- lateral movement risk from any compromised pod. ⚠️ **PARTIALLY ADDRESSED:** default-deny `CiliumNetworkPolicy` now covers `honeypot` **and** `iocaine`, and targeted `NetworkPolicy` objects exist in `argocd`, `authentik`, `boomtime`, `openscad`, `monitoring`, `crossplane-demo`, and `argocd-image-updater-system`. Most namespaces still have no policy.
5. **~~No alerting rules defined~~ (✅ RESOLVED)** -- 16 `PrometheusRule` CRs are now live (etcd/Velero backup alerts, pipeline health, cluster baseline, memory pressure, cert-manager, cilium BPF + identity, SPIRE, KubeVirt, GPU inference, Dagster, platform regression). Alloy syncs them into the Mimir ruler, and Alertmanager routes to Discord via `alertmanager-discord`.

---

## Section 1: Data Pipeline Engineering Analysis

### Current Data Architecture

The cluster operates a modern Grafana LGTM telemetry stack. Grafana Alloy is the primary collection
agent for the LGTM path. ⚠️ **CHANGED:** it is no longer the *sole* agent — a second, independent
ClickStack/HyperDX pipeline (`clickstack-otel-collector` → ClickHouse `chi-hyperdx-logs`) now runs
alongside it in the `monitoring` namespace.

```
Applications/Pods
    │
    ├─ Logs ──> Alloy (K8s API + OTLP) ──> Loki (SingleBinary) ──> MinIO S3
    │
    ├─ Metrics ──> Alloy (Prometheus scrape + OTLP) ──> Mimir (Distributed) ──> MinIO S3
    │
    ├─ Traces ──> Alloy (OTLP gRPC/HTTP) ──> Tempo (SingleBinary) ──> MinIO S3
    │                                                 │
    │                                                 └──> Metrics Generator ──> Mimir
    │
    └─ (parallel) ──> ClickStack OTel Collector ──> ClickHouse ──> HyperDX UI
```

**Metrics Collection Coverage:**

| Scrape Target | Interval | Method |
|---------------|----------|--------|
| Kubelet / cAdvisor | 60s | K8s API proxy (HTTPS) |
| Pod annotations (`prometheus.io/scrape`) | 60s | HTTP |
| Kube-State-Metrics | 60s | HTTP |
| Node Exporter | 60s | HTTP |
| Hubble (Cilium) | 30s | HTTP |
| Cilium Operator | 30s | HTTP |
| ArgoCD | 30s | HTTP |
| Blackbox exporter (self) | 30s | HTTP |
| Blackbox Probes (7 targets: grafana, mimir, loki, tempo, traefik, argocd, hubble-ui) | 60s | HTTP |
| Traefik | 30s | HTTP |
| MinIO | 60s | HTTP |
| Pushgateway | 60s | HTTP |
| Alloy (self) | 60s | HTTP |
| ServiceMonitors / PodMonitors | varies | Operator CRDs |

**Custom Exporters:** Tdarr (transcoding metrics), Kasa (smart plug power), NFS storage exporter,
Dragonfly/Redis exporters (argocd + authentik caches), version-checker.
⚠️ **CHANGED:** Exportarr (Sonarr/Radarr/Prowlarr/Readarr) is **not deployed** — no pods exist and
`applications/arr-stack/base/exportarr/` is not referenced by any kustomization. The manifests remain
in the repo with `APIKEY: placeholder`.

### Storage Tiers & Retention

| Tier | Backend | Use Case | Capacity |
|------|---------|----------|----------|
| `local-path` (default, node NVMe) | Rancher local-path-provisioner, backed by the Talos EPHEMERAL partition at `/var` | Databases (incl. authentik/boomtime CNPG), WAL, caches, Loki, Mimir, zot | ~758Gi requested across 64 PVCs |
| `fatboy-nfs-appdata` | Synology NAS `192.168.1.36:/volume1/appdata`, nfs-subdir-external-provisioner | App configs, MinIO tenant volume, most CNPG clusters | ~732Gi requested across 52 PVCs |
| `synology-nfs` (static PVs, `no-provisioner`) | Synology NAS | Media libraries, downloads | ~69Ti |
| `tdarr-nfs` / `tdarr-appdata` (static PVs) | Synology NAS | Tdarr transcode cache + config | ~65Ti / 20Gi |
| MinIO S3 | Object storage on `fatboy-nfs-appdata` | Telemetry, backups, Dagster | 100Gi, 1 server × 1 volume |

> ⚠️ **CHANGED:** TrueNAS has been decommissioned. All NFS now comes from the Synology at
> `192.168.1.36`. `openebs-hostpath` is not present; `local-path` is the default StorageClass.

| Data Type | Retention | Storage Backend |
|-----------|-----------|-----------------|
| Metrics (Mimir) | 1 year | MinIO `mimir` bucket |
| Logs (Loki) | 30 days | MinIO `loki` bucket |
| Traces (Tempo) | 7 days | MinIO `tempo` bucket |
| Velero daily backups (`velero-daily-all`, `velero-critical-data-daily`) | 30 days (`ttl: 720h`) | MinIO `velero` bucket |
| Velero weekly backups (`velero-weekly-full`) | 90 days (`ttl: 2160h`) | MinIO `velero` bucket |
| etcd snapshots | ~7 days (`RETENTION_COUNT: 168` at hourly cadence) | MinIO `backups/etcd` |
| Container images (zot) | Unbounded | `local-path` 30Gi PVC |

### Key Data Pipeline Findings

**Strengths:**
- Single collection agent (Alloy) across the whole LGTM path — no per-signal agent sprawl (⚠️ the parallel ClickStack collector is the one exception)
- Comprehensive Kubernetes discovery with proper label propagation
- Cross-signal correlation configured (trace-to-log, trace-to-metric, service graphs)
- S3-backed telemetry enables independent scaling of compute and storage
- Mimir rules sync from PrometheusRule CRDs enables app-repo-defined alerting
- Label consistency (`cluster=talos-homelab`) prepares for multi-cluster scenarios

**Critical Gaps:**
- Tempo WAL persistence disabled -- pod restart loses in-flight traces (still true: `persistence.enabled: false` in the Tempo HelmRelease)
- ⚠️ **PARTIALLY ADDRESSED:** "single replica everything" no longer holds for Mimir (3 ingesters; 2 each of distributor, querier, query-frontend, query-scheduler). Loki, Tempo, Grafana, Alloy, and the MinIO tenant are still single-replica, so a restart there is still a pipeline outage.
- MinIO single-server with no erasure coding or replication (still true: `servers: 1`, `volumesPerServer: 1`)
- Loki has ingestion rate limits (10 MB/s, 15 MB burst, 5000 streams/tenant) but no documented backpressure mechanism
- ⚠️ **CHANGED:** Nexus has been **replaced by zot** (`infrastructure/base/registry/zot/`, 30Gi `local-path` PVC). The lifecycle-policy gap carries over — zot has no configured retention either.
- ~~RabbitMQ dashboard exists but no RabbitMQ deployment~~ (✅ RESOLVED) -- the RabbitMQ cluster operator and messaging-topology operator run in `rabbitmq-system`, with a `boomtime-rabbit` cluster.

### Data Pipeline Recommendations

| Priority | Recommendation | Effort | Status (2026-08-22) |
|----------|---------------|--------|---------------------|
| P0 | Implement off-site backup (Backblaze B2 or second NAS) | Medium | Open — still a single MinIO `BackupStorageLocation` |
| P0 | Enable Tempo WAL persistence (5-10Gi PVC) | Low | Open |
| P1 | Create alerting rules in Mimir (pod health, pipeline health, backups, storage) | Medium | ✅ Done — 16 `PrometheusRule` CRs synced to the Mimir ruler |
| P1 | Migrate MinIO credentials to ExternalSecrets | Low | ✅ Done — TALOS-tmqq |
| P1 | Fix Exportarr API keys or remove non-functional deployments | Low | Partly — deployments are no longer applied; manifests still carry placeholders |
| P1 | Bake `mc` into etcd-backup image (remove runtime `wget`) | Low | ✅ Done — the CronJob now uses pinned `ghcr.io/siderolabs/talosctl:v1.11.1` and `minio/mc:RELEASE.2024-11-21T17-21-54Z` containers; no runtime download |
| P2 | Add Alloy OTLP retry/backoff configuration | Low | Open |
| P2 | Configure registry cleanup policies (was Nexus, now zot) | Low | Open |

---

## Section 2: Machine Learning Engineering Analysis

### Compute Resources

⚠️ **CHANGED — the fleet is now 5 nodes, not 7.** `talos04` and `talos05` (the NVIDIA nodes) have
been decommissioned; the surviving GPU capacity is Intel Arc only. `maxPods` was raised from 110 to
200 on every node. Values below are from `kubectl get nodes` on 2026-08-22.

| Node | IP | CPU | RAM | GPU/Accelerator | ML Capability |
|------|----|-----|-----|-----------------|---------------|
| talos00 | 192.168.1.54 | AMD Ryzen Embedded V1500B (4c) | ~25Gi | None | Control plane only — **tainted** `node-role.kubernetes.io/control-plane` |
| talos01 | 192.168.1.177 | Intel i3-1220P (12c) | ~23Gi | Intel UHD (no device plugin) | General compute |
| talos02-gpu | 192.168.1.144 | Intel Core Ultra 5 225H (14c) | ~62Gi | **Intel Arc 130T** — advertises `gpu.intel.com/i915: 10` | Inference / transcoding (GPU healthy, no longer wedged) |
| talos03 | 192.168.1.30 | AMD Ryzen 7 5800U (8c/16t) | ~15Gi | AMD Vega 8 — **not** exposed as a schedulable device | General compute |
| **talos06** | **192.168.1.19** | **Intel Core Ultra 9 285H (16 logical CPUs reported)** | **~62Gi** | **Intel Arc 140T** — advertises `gpu.intel.com/i915: 10` | **Primary ML node** |

### ML Infrastructure Status

| Component | Status | Details |
|-----------|--------|---------|
| Ollama | Not running | Scaffolding lives in `infrastructure/base/hybrid-llm/ollama/`; no Ollama pod exists. The `ollama.talos00` IngressRoute now routes to the `gpu-inference` gateway, which is itself scaled to 0. |
| LiteLLM | **Active** | ArgoCD-managed from `catalyst-llm` repo; `litellm`, `litellm-postgresql`, `lobe-chat`, `open-webui`, and `searxng` are all Running in ns `catalyst-llm` |
| Intel GPU Plugin | Deployed | NFD + Intel Device Plugins Operator, ⚠️ `sharedDevNum: 10` (not 4) |
| NVIDIA Device Plugin | ⚠️ **N/A** | Both NVIDIA nodes were decommissioned. Only `infrastructure/base/nvidia-cdi/nvidia-cdi-init.yaml` remains. |
| Model Registry | Missing | No MLflow, W&B, or equivalent (re-verified — zero references in the repo) |
| Experiment Tracking | Missing | No dedicated tooling |
| Feature Store | Missing | Not present |
| Training Infrastructure | Not present | No Kubeflow, Ray, or distributed training |
| Knowledge Graph (The Corpus) | In development | `applications/the-corpus/` — Neo4j + embeddings + NER via Dagster |
| Hybrid Cloud GPU Burst | ⚠️ **REDESIGNED, still inactive** | The Nebula + Liqo design was superseded by `infrastructure/base/gpu-inference/` (TALOS-t3ic): KEDA HTTP interceptor holds requests while a Crossplane-managed AWS spot GPU box is provisioned, with two-tier reapers (HOT→WARM→COLD). Per its own README the gateway is at 0 replicas, `gpu-broker` is at 0 with an unbuilt image, and nothing bills today. |

### ML Integration Opportunities

The cluster has strong foundations that ML workloads can leverage:

- **MinIO S3** -- model artifacts, datasets, Dagster IO (versioning enabled)
- **CloudNativePG** -- 11 Postgres clusters across the fleet. ⚠️ pgvector is **not** installed on any of them today; enabling it is still net-new work.
- **Dagster** (catalyst-data repo) -- workflow orchestration for training/inference pipelines. ⚠️ No Dagster pods are currently running in ns `catalyst-data`.
- **ArgoCD Image Updater** -- "push model container, auto-deploy" workflow (running in ns `argocd-image-updater-system`)
- **OTEL stack** -- inference latency, throughput, and accuracy monitoring ready
- **Pushgateway** -- training jobs can push epoch loss and validation metrics (scraped by Alloy at 60s)
- **External Secrets** -- API keys for Anthropic, OpenAI, RunPod, HuggingFace
- **KEDA** -- deployed (ns `keda`) and already used by `gpu-inference` for scale-from-zero on HTTP demand
- **Authentik SSO** -- integrated with LiteLLM and many other apps for user management

### ML Engineering Recommendations

| Phase | Recommendation | Timeline | Status (2026-08-22) |
|-------|---------------|----------|---------------------|
| **Phase 1: Foundation** | Activate catalyst-llm stack (ArgoCD app exists) | Week 1-2 | ✅ Done — LiteLLM + Open WebUI + Lobe Chat running |
| | ~~Codify NVIDIA device plugin as Kustomize manifests~~ | Week 1-2 | ⚠️ Moot — NVIDIA nodes decommissioned |
| | Add GPU resource quotas for catalyst-llm namespace | Week 1-2 | Open |
| | Create GPU monitoring Grafana dashboard | Week 1-2 | Open |
| | ~~Fix talos02 GPU wedge (cold boot)~~ | Week 1-2 | ✅ Done — talos02-gpu advertises `gpu.intel.com/i915: 10` |
| **Phase 2: MLOps** | Deploy MLflow (MinIO artifacts + CloudNativePG metadata) | Week 3-6 | Open |
| | Add pgvector to CloudNativePG for embedding storage | Week 3-6 | Open |
| | Integrate ML pipelines into Dagster code locations | Week 3-6 | Open |
| | Deploy KEDA for autoscaling on inference queue depth | Week 3-6 | ✅ Done — KEDA deployed and driving `gpu-inference` scale-to-zero |
| | Create ML PriorityClass (inference: high, training: medium) | Week 3-6 | Open |
| **Phase 3: Advanced** | Activate hybrid cloud GPU burst (now KEDA + Crossplane/AWS, not Nebula + Liqo) | Month 2-3 | Built but disarmed — broker at 0 replicas, image unbuilt |
| | Deploy OpenVINO Model Server for Intel Arc optimization | Month 2-3 | Open |
| | Build RAG pipeline (The Corpus + Neo4j + pgvector + Ollama) | Month 2-3 | Open |

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
 Synology NAS      Traefik VIP 192.168.1.251     Talos nodes
 .1.36             (Cilium LB-IPAM + L2/ARP)     talos00 .54 (CP, tainted)
 NFS exports       :80 :443 :8080 :1080 :7687   talos01 .177
 (all NFS;         DaemonSet on every node       talos02-gpu .144 (Arc 130T)
  TrueNAS gone)    CrowdSec bouncer + AppSec     talos03 .30
                               │                 talos06 .19  (Arc 140T)
                               │                 Cilium CNI (ipam kubernetes,
                               │                 VXLAN tunnel, kube-proxy repl.)
                               │
                      ┌────────▼────────────────┐
                      │  gpu-inference (KEDA)    │  ← disarmed: 0 replicas
                      │  Crossplane → AWS spot   │
                      │  g5.xlarge vLLM          │
                      └─────────────────────────┘
```

> ⚠️ **CHANGED:** ingress no longer depends on `talos00`'s node IP. As of 2026-08-15 (TALOS-sa0n)
> `svc/traefik` is a LoadBalancer holding VIP **192.168.1.251** from the `lan-traefik-pool`
> `CiliumLoadBalancerIPPool`, announced over L2/ARP from whichever node holds the lease. Pi-hole
> holds a separate VIP from `192.168.1.240-250`. The Nebula overlay + AWS K3s burst path shown in the
> original diagram was superseded by the `gpu-inference` design.

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
    │       ├── Kyverno ──> kyverno-policies (10 ClusterPolicies)
    │       └── Intel GPU ──> arr-stack
    │
    └──> ArgoCD (auto-sync) ──> External repos
            ├── catalyst-ui (React UI)
            ├── catalyst-llm (LLM platform)
            ├── catalyst-data (Dagster pipelines)
            ├── boomtime (coding analytics)
            ├── openscad (Manyfold)
            ├── dungeon-library
            ├── arr-stack-private
            └── kasa-exporter (IoT metrics)
```

> ⚠️ **CHANGED:** there are now **8** ArgoCD Applications (`infrastructure/base/argocd/applications/`),
> not 6, and there is no `gateway-arr` app. Flux manages **59** Kustomizations.

**Kyverno now derives configuration that used to be hand-written.** Ten `ClusterPolicy` objects are
live, and manifests deliberately omit what they mutate in:

| ClusterPolicy | What it derives |
|---------------|-----------------|
| `homepage-annotation-derivation` | homepage `href` / `widget.url` annotations from the IngressRoute |
| `homepage-instance-assignment` | homepage `instance` annotation |
| `ingressroute-tls-default` | `tls: {}` on `websecure` IngressRoutes |
| `cnpg-velero-exclude` | `velero.io/exclude-from-backup` on CNPG clusters |
| `helmrelease-remediation-defaults` | `remediation.retries` on HelmReleases |
| `oidc-hostalias` | the Authentik OIDC hostAlias for pods labelled `catalyst.io/oidc=true` |
| `dragonfly-allow-monitoring` | NetworkPolicy allowing monitoring to scrape Dragonfly |
| `reflect-cnpg-app-secrets` | emberstack reflector annotations on CNPG app secrets |
| `externalsecret-defaults` | ExternalSecret defaults |
| `pod-security-baseline` | Pod Security baseline enforcement |

Cross-namespace secret mirroring is handled by **emberstack reflector**
(`infrastructure/base/reflector/`).

### Infrastructure-as-Code Maturity

| Aspect | Rating | Evidence |
|--------|--------|---------|
| Declarative config | Excellent | ~570 YAML manifests under `infrastructure/base/`, all Kustomize-managed |
| Version pinning | Good | Helm charts mostly pinned to exact versions with upgrade rationale in comments (e.g. Mimir chart `6.1.0`, Loki `6.23.0`, Tempo `1.24.4`, Alloy `1.11.1`) |
| Modular structure | Excellent | 45 component directories in `infrastructure/base/` |
| Overlay pattern | Good | arr-stack uses base/gpu/themepark chain |
| Dependency management | Excellent | Flux Kustomization `dependsOn` DAG |
| Environment separation | Partial | Docker-based local cluster, no staging |
| Reproducibility | Good | Fully automated provisioning scripts |

### Security Assessment

**Secrets Management:**
- 1Password + ESO for ArgoCD, Cloudflare, Authentik, VPN, External DNS, Kasa
- **RESOLVED (TALOS-tmqq):** MinIO root credential rotated and sourced from 1Password (item `minio`) via ExternalSecrets in every consumer namespace; no credential literal remains in git.

**Network Security:**
- Cilium eBPF with `kubeProxyReplacement: true`, `ipam: kubernetes`, VXLAN tunnel routing (MTU 1250), and SPIRE mTLS capability enabled but opt-in per-policy (`authentication.mutual.spire`, TALOS-p2g3.3)
- Hubble flow observability with rich metrics
- **CrowdSec** IPS + AppSec running as a DaemonSet with its own LAPI and CNPG-backed store, bouncing at Traefik
- ⚠️ **PARTIAL:** default-deny `CiliumNetworkPolicy` now covers **honeypot and iocaine**; targeted `NetworkPolicy` objects exist in `argocd`, `authentik`, `boomtime`, `openscad`, `monitoring`, `crossplane-demo`, and `argocd-image-updater-system`. Most namespaces still have none.
- **GAP:** WireGuard node encryption still disabled — the `encryption:` block in `infrastructure/base/cilium/values.yaml` remains commented out with a note to try native routing instead of VXLAN

**Access Control:**
- Talos: No SSH, API-only access with PKI auth
- ArgoCD: Default `role:readonly`, explicit admin escalation (`policy.default: role:readonly`)
- Authentik: ⚠️ **SSO/OIDC rollout is now broad**, not just LiteLLM — blueprints exist for Forgejo, Immich, Homepage, Boomtime, Linkwarden, media OIDC, media-experimental, and a "gap apps" catch-all, plus Traefik forward-auth on the infra-control tools (Headlamp, Goldilocks, kube-ops-view, kubeview, dbgate)
- ✅ **RESOLVED:** PodSecurityAdmission labels are now applied across namespaces (`privileged` for platform namespaces, `baseline` for app namespaces, `restricted` for `descheduler`)
- ✅ **RESOLVED:** Kyverno **is** deployed as the admission controller (10 ClusterPolicies, incl. `pod-security-baseline`)

**Supply Chain:**
- Some services still use `:latest` tags (Cowrie, cloudflare-ddns, kube-ops-view, kubeview, whoami, searxng, crowdsec-web-ui, `minio/mc`). Gluetun is now pinned to `v3.41.3` and Headlamp to `v0.44.0`.
- No image scanning (Trivy/Snyk) — re-verified, zero references in the repo
- `version-checker` is deployed in `monitoring`, giving visibility into out-of-date images
- ArgoCD Image Updater provides controlled updates for ArgoCD apps

### Technical Debt Register

| Item | Severity | Effort | Status (2026-08-22) |
|------|----------|--------|---------------------|
| ~~Hardcoded MinIO credentials~~ | HIGH | Low | ✅ Resolved (TALOS-tmqq) |
| Missing network policies on most namespaces | HIGH | Medium | Open (partial — see Network Security) |
| Backup storage co-located with workloads | HIGH | High | Open — MinIO's only volume is a PVC on the same NAS |
| Single control plane (no HA) | HIGH | High | Open — epic TALOS-arx (promote talos01 + talos06) |
| No repo-wide CI quality gates | MEDIUM | Medium | Partial — two image-build workflows exist (`beads-manager`, `llm-proxy`); no yamllint / kustomize-build / gitleaks gate. Lefthook covers local hooks only. |
| `:latest` image tags on multiple services | MEDIUM | Low | Open (reduced — Gluetun and Headlamp now pinned) |
| ~~No admission controller (Kyverno/OPA)~~ | MEDIUM | Medium | ✅ Resolved — Kyverno + 10 ClusterPolicies |
| ~~No PodSecurity enforcement~~ | MEDIUM | Medium | ✅ Resolved — PSA labels cluster-wide + `pod-security-baseline` ClusterPolicy |
| Traefik API insecure + running as root | MEDIUM | Medium | Open — `--api.insecure=true`, `runAsUser: 0`, `runAsNonRoot: false` in the HelmRelease |
| WireGuard node encryption broken | MEDIUM | High | Open — encryption block still commented out |
| Suspended/deprecated configs not cleaned | LOW | Trivial | Open |
| cluster-settings ConfigMap incomplete | LOW | Low | Open — only `TALOS_NODE_IP` and `TALOS02_GPU_NODE_IP` are set; an in-file TODO calls out the missing nodes |
| Documentation references stale node counts | LOW | Low | Open — several docs still describe a 4-node fleet or reference the removed talos04/talos05 |

### Enterprise Architecture Recommendations

**Quick Wins (1-2 hours each):**

1. ~~Migrate MinIO credentials to 1Password/ESO~~ — ✅ done (TALOS-tmqq)
2. Pin image tags (replace `:latest`) — partially done
3. Clean up deprecated/suspended configs — open
4. Complete cluster-settings ConfigMap with all node IPs — open (still only 2 of 5 nodes)
5. ~~Add PSA labels to namespaces~~ — ✅ done

   **Medium-term (1-2 days each):**

6. Implement namespace-level CiliumNetworkPolicies (extend the honeypot/iocaine pattern) — open
7. Set up GitHub Actions CI (yamllint, shellcheck, kustomize build, gitleaks) — open
8. Add offsite backup target (Backblaze B2 or Wasabi) — open
9. ~~Deploy Kyverno for policy enforcement~~ — ✅ done, and already used for derivation as well as enforcement
10. ~~Bake `mc` into etcd-backup image~~ — ✅ done (pinned `minio/mc` container, no runtime download)

    **Strategic (1+ weeks):**

11. Add second (and third) control plane node for HA — open, epic TALOS-arx
12. Enforce Cilium mTLS on sensitive services — open (capability enabled, no policy opts in)
13. Complete Authentik SSO rollout across all services — largely done; remaining apps tracked per-repo
14. GitOps for Talos configs (SOPS-encrypted in git) — open
15. Build staging environment with Docker-based Talos — open

---

## Cross-Cutting Themes

### Theme 1: Single Points of Failure

All three analyses independently identified the concentration of risk around single-instance components:

- **MinIO** -- sole S3 backend for telemetry, backups, and Dagster data (1 server, 1 volume, no replication) — re-verified, unchanged
- **Control plane** -- single etcd node means total cluster loss on failure — re-verified, unchanged
- **Synology NAS** -- all NFS storage (media + app configs + MinIO data) on one device at `192.168.1.36`; with TrueNAS decommissioned this is now the *only* NAS, so the concentration is higher than at the time of the original analysis
- **Most services** -- ⚠️ softened: Mimir now runs 3 ingesters and 2 of each stateless component; Traefik is a 5/5 DaemonSet and Pi-hole a 5-replica StatefulSet (one per node), both behind failover VIPs. Loki, Tempo, Grafana, Alloy, and MinIO remain single-replica.

**Recommendation:** Prioritize off-site backup (eliminates catastrophic data loss risk with moderate effort) over HA deployments (high effort, lower probability).

### Theme 2: Security Posture Gap

⚠️ **Substantially closed since the original analysis.** Two of the four bullets below are fully
resolved, one is partial, and one is untouched:

- ~~MinIO credentials bypass the established ESO pattern~~ — ✅ resolved (TALOS-tmqq)
- Network policies exist only for the honeypot — **partially** resolved (iocaine added, plus targeted NetworkPolicies in seven namespaces); most namespaces still uncovered
- ~~No admission controller enforces security baselines~~ — ✅ resolved (Kyverno + PSA labels)
- Traefik runs as root with insecure API — **still open**

**Recommendation (updated):** the remaining work is namespace-level default-deny. Kyverno is now
available to *generate* those policies rather than hand-writing one per namespace, which is a
cheaper path than the original per-namespace estimate. Traefik hardening is independent and still
outstanding.

### Theme 3: Monitoring Without Alerting

⚠️ **Largely resolved.** The stack is no longer passive:

- ~~No PrometheusRule CRDs defined (Mimir rules directory empty)~~ — ✅ 16 `PrometheusRule` CRs exist, sourced from `infrastructure/base/monitoring/v2-otel/baseline-alerts/` and app namespaces, synced into the Mimir ruler by Alloy
- ~~No alerts for pipeline failures, storage capacity, backup failures, or pod health~~ — ✅ `pipeline-health-alerts`, `cluster-baseline-alerts`, `memory-pressure-alerts`, `etcd-backup-alerts`, `velero-backup-alerts`, and more are live, and Alertmanager routes to Discord via the `alertmanager-discord` bridge
- Blackbox probes check health but don't trigger alerts — **still open**: no rule matches on `probe_success`. There is now an `uptime-slo` Grafana dashboard built on it, but a dashboard is not an alert.
- No SLA/SLO definitions — **still open** (the `uptime-slo` dashboard visualises availability; no SLO objects or burn-rate alerts exist)

**Recommendation (updated):** the alerting baseline exists. The remaining gap is an alert on
`probe_success` and formal SLO/burn-rate definition, not net-new rule infrastructure.

### Theme 4: ML Infrastructure at Crossroads

⚠️ **Partially resolved.** The serving layer landed; the MLOps layer did not.

- ~~Ollama + LiteLLM stack fully designed but archived/extracted~~ — LiteLLM, Open WebUI, Lobe Chat, and SearXNG are all running in `catalyst-llm`. Ollama itself is still not deployed.
- Intel GPU plugin deployed and working — now on **two** nodes (talos02-gpu and talos06), `sharedDevNum: 10`
- ~~NVIDIA GPU support documented but not codified~~ — moot; both NVIDIA nodes were decommissioned
- Knowledge graph pipeline (The Corpus) shows clear ML/NLP direction — `applications/the-corpus/`
- Hybrid cloud GPU burst architecture designed but inactive — **redesigned** as `gpu-inference` (KEDA + Crossplane/AWS spot vLLM) and deliberately disarmed at 0 replicas
- **Still missing:** model registry, experiment tracking, feature store, pgvector, training infrastructure

**Recommendation (updated):** inference serving is solved. The next marginal gain is the MLOps
substrate — pgvector on an existing CNPG cluster, then a model/experiment registry — rather than
more serving capacity.

---

## Prioritized Action Plan

> Status column added 2026-08-22. Items marked ✅ were verified complete against the live cluster.

### Immediate (This Week)

| # | Action | Impact | Effort | Source | Status |
|---|--------|--------|--------|--------|--------|
| 1 | Implement off-site backup | Eliminates catastrophic data loss | Medium | All three | Open |
| 2 | Enable Tempo WAL persistence | Prevents trace data loss | Low | Data Pipeline | Open |
| 3 | Migrate MinIO creds to ESO | Fixes critical security gap | Low | Enterprise Arch | ✅ Done |
| 4 | Fix Exportarr API keys | Restores media stack metrics | Low | Data Pipeline | Moot — deployments no longer applied |

### Short-term (Next 2 Weeks)

| # | Action | Impact | Effort | Source | Status |
|---|--------|--------|--------|--------|--------|
| 5 | Create alerting rules (Mimir) | Enables proactive monitoring | Medium | Data Pipeline + Enterprise | ✅ Done |
| 6 | Add namespace CiliumNetworkPolicies | Reduces lateral movement risk | Medium | Enterprise Arch | Partial |
| 7 | Pin `:latest` image tags | Reproducible deployments | Low | Enterprise Arch | Partial |
| 8 | Activate catalyst-llm stack | ML inference capability | Low | ML Engineer | ✅ Done |
| 9 | Codify NVIDIA device plugin | Completes GPU infra | Low | ML Engineer | Moot — NVIDIA nodes removed |
| 10 | Set up GitHub Actions CI | Quality gates in CI | Medium | Enterprise Arch | Open (only image-build workflows exist) |

### Medium-term (Next 1-2 Months)

| # | Action | Impact | Effort | Source | Status |
|---|--------|--------|--------|--------|--------|
| 11 | Deploy MLflow | ML experiment tracking | Medium | ML Engineer | Open |
| 12 | Add second control plane node | Eliminates biggest SPOF | High | Enterprise Arch | Open — epic TALOS-arx |
| 13 | Deploy Kyverno admission controller | Policy enforcement | Medium | Enterprise Arch | ✅ Done |
| 14 | Add pgvector to CloudNativePG | Embedding storage for RAG | Medium | ML Engineer | Open |
| 15 | Configure registry lifecycle policies (was Nexus, now zot) | Prevents storage exhaustion | Low | Data Pipeline | Open |

### Strategic (Next Quarter)

| # | Action | Impact | Effort | Source | Status |
|---|--------|--------|--------|--------|--------|
| 16 | Activate hybrid cloud GPU burst (now KEDA + Crossplane/AWS) | Scale ML beyond homelab | High | ML Engineer | Built, deliberately disarmed |
| 17 | Build RAG pipeline (Corpus + pgvector + Ollama) | Knowledge-grounded inference | High | ML Engineer | Open |
| 18 | Complete Authentik SSO rollout | Unified access control | Medium | Enterprise Arch | Largely done |
| 19 | Enforce Cilium mTLS | Zero-trust networking | High | Enterprise Arch | Open — capability enabled, unenforced |
| 20 | GitOps for Talos configs (SOPS) | Fully reproducible provisioning | Medium | Enterprise Arch | Open |

---

*Analysis performed on 2026-03-14 by three specialized AI agents (Data Pipeline Engineer, ML Engineer, Enterprise Software Architect) against the talos-homelab repository at commit 9163fc7.*

*Re-grounded against the repository and the live cluster on 2026-08-22. Corrections applied in place; superseded findings marked rather than removed.*

*Full individual analyses were written to `.output/analysis-data-pipeline.md`,
`.output/analysis-ml-engineer.md`, and `.output/analysis-enterprise-architect.md`. ⚠️ **These files no
longer exist** — `.output/` is gitignored scratch space and was cleared. This report is the only
surviving record of that analysis.*

---

## Related Issues

<!-- Beads tracking for this doc -->

- **TALOS-tmqq** — MinIO root password exposed in git (risk #2 above). Bead is still **OPEN** even though the manifests show the credential rotated and sourced from 1Password — needs a close or a note explaining what remains.
- **TALOS-arx** — EPIC: HA control plane, promote talos01 + talos06 to stacked etcd (P0, OPEN; risk #3 above)
- **TALOS-t3ic** — EPIC: ephemeral GPU inference, KEDA-buffered Ollama endpoint on AWS (P2, OPEN; built but disarmed)
- **TALOS-sa0n** — Traefik ingress VIP via Cilium LB-IPAM (OPEN; the VIP `192.168.1.251` is live as of 2026-08-15, so this may be closeable)
- **TALOS-p2g3** — Cilium staged upgrade epic (CLOSED); sub-item `.3` left SPIRE mutual-auth enabled as a capability, opt-in per CiliumNetworkPolicy
