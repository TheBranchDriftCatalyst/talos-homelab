# Resource Optimization Analysis

**Generated:** 2025-12-02
**Data Period:** 12-24 hours of metrics collection
**Cluster:** talos00 (single-node)

## Executive Summary

| Metric                  | Before Optimization   | After Optimization (2025-12-02) |
| ----------------------- | --------------------- | ------------------------------- |
| **Node Capacity**       | 6 CPU cores, 16GB RAM | 6 CPU cores, 16GB RAM           |
| **Allocatable**         | 5950m CPU, 15.4GB RAM | 5950m CPU, 15.4GB RAM           |
| **CPU Requests**        | 5120m (86%)           | 4065m (68%)                     |
| **Memory Requests**     | 15196Mi (98%)         | 14822Mi (96%)                   |
| **Actual CPU Usage**    | 31% (1856m)           | 53% (3164m)                     |
| **Actual Memory Usage** | 70% (10.9GB)          | 71% (11.0GB)                    |
| **Running Pods**        | ~75                   | 79                              |

### Key Findings (Post-Optimization)

1. **CPU requests reduced from 86% to 68%** - freed 1055m CPU headroom
2. **Memory requests reduced from 98% to 96%** - marginally improved scheduling capacity
3. **Efficiency improved** - CPU usage/request ratio improved from 36% to 78%
4. **All 79 pods healthy** - no scheduling failures or OOM events
5. **External repos optimized** - kasa-exporter, catalyst-ui, arr-stack-private apps right-sized

---

## Cluster Capacity Overview

### Node Resources

```
NAME      CPU   MEMORY       ALLOCATABLE_CPU   ALLOCATABLE_MEMORY
talos00   6     16350580Ki   5950m             15723892Ki (~15.4GB)
```

### Current Allocation Summary

| Resource | Requests      | Limits         | Actual Usage  |
| -------- | ------------- | -------------- | ------------- |
| CPU      | 5120m (86%)   | 37100m (623%)  | 1856m (31%)   |
| Memory   | 15196Mi (98%) | 44576Mi (290%) | 10885Mi (70%) |

**Interpretation:**

- **Requests vs Usage Gap:** We're requesting ~3x more CPU than we use, and ~1.4x more memory
- **Overcommit:** Limits exceed node capacity, meaning burst scenarios could cause OOM or throttling
- **Scheduling Risk:** At 98% memory requests, new pods may fail to schedule

---

## Resource Efficiency Analysis

### Methodology

- **P95 Usage:** 95th percentile usage over 24 hours (captures burst patterns)
- **Suggested Request:** P95 + 20% headroom for safety
- **Suggested Limit:** 2x the suggested request (allows burst capacity)

### CPU Efficiency by Workload

| Namespace                   | Pod                              | Current Request | P95 Usage | Suggested Request | Savings  |
| --------------------------- | -------------------------------- | --------------- | --------- | ----------------- | -------- |
| argocd-image-updater-system | argocd-image-updater-controller  | 250m            | 2.8m      | **10m**           | 240m     |
| argocd                      | argocd-application-controller    | 250m            | 37m       | **50m**           | 200m     |
| argocd                      | argocd-repo-server               | 100m            | 5m        | **10m**           | 90m      |
| argocd                      | argocd-server                    | 100m            | 3m        | **10m**           | 90m      |
| argocd                      | argocd-applicationset-controller | 50m             | 0.8m      | **5m**            | 45m      |
| argocd                      | argocd-redis                     | 50m             | 1m        | **5m**            | 45m      |
| bastion                     | bastion                          | 50m             | 0m        | **5m**            | 45m      |
| external-secrets            | onepassword-connect              | 20m             | 3m        | **10m**           | 10m      |
| external-secrets            | external-secrets                 | 10m             | 2.3m      | **5m**            | 5m       |
| external-secrets            | external-secrets-cert-controller | 10m             | 2.7m      | **5m**            | 5m       |
| flux-system                 | helm-controller                  | 100m            | 8.4m      | **15m**           | 85m      |
| flux-system                 | kustomize-controller             | 100m            | 30.4m     | **40m**           | 60m      |
| flux-system                 | notification-controller          | 100m            | 3.2m      | **10m**           | 90m      |
| flux-system                 | source-controller                | 50m             | 6.3m      | **10m**           | 40m      |
| infra-control               | goldilocks-controller            | 25m             | 28.5m     | **35m**           | -10m     |
| infra-control               | goldilocks-dashboard             | 25m             | 0.1m      | **5m**            | 20m      |
| infra-control               | headlamp                         | 25m             | 0.3m      | **5m**            | 20m      |
| infra-control               | kube-ops-view                    | 10m             | 48m       | **60m**           | -50m     |
| infra-control               | kubeview                         | 10m             | 1.4m      | **5m**            | 5m       |
| kube-system                 | coredns (x2)                     | 100m each       | 8m        | **15m**           | 85m each |
| kube-system                 | kube-apiserver                   | 200m            | 295m      | **350m**          | -150m    |
| kube-system                 | kube-controller-manager          | 50m             | 45m       | **60m**           | -10m     |
| kube-system                 | kube-flannel                     | 100m            | 25m       | **35m**           | 65m      |
| kube-system                 | kube-scheduler                   | 10m             | 7m        | **10m**           | 0m       |
| kube-system                 | metrics-server                   | 100m            | 8m        | **15m**           | 85m      |
| kube-system                 | nfs-subdir-external-provisioner  | 25m             | 3m        | **10m**           | 15m      |
| kube-system                 | vpa-recommender                  | 50m             | 5m        | **10m**           | 40m      |
| media                       | homepage                         | 25m             | 1.2m      | **5m**            | 20m      |
| media                       | jellyfin                         | 50m             | 1.4m      | **5m**            | 45m      |
| media                       | overseerr                        | 25m             | 2.6m      | **5m**            | 20m      |
| media                       | plex                             | 50m             | 2m        | **5m**            | 45m      |
| media                       | prowlarr                         | 25m             | 2m        | **5m**            | 20m      |
| media                       | radarr                           | 25m             | 2m        | **5m**            | 20m      |
| media                       | sonarr                           | 25m             | 2m        | **5m**            | 20m      |
| media                       | tdarr                            | 100m            | 5m        | **10m**           | 90m      |
| media                       | postgresql                       | 60m             | 5m        | **10m**           | 50m      |
| media-private               | stash-hardcore                   | 50m             | 2m        | **5m**            | 45m      |
| media-private               | stash-softcore                   | 50m             | 2m        | **5m**            | 45m      |
| media-private               | whisparr                         | 25m             | 2m        | **5m**            | 20m      |
| monitoring                  | alertmanager                     | 25m             | 1.2m      | **5m**            | 20m      |
| monitoring                  | grafana                          | 50m             | 25m       | **35m**           | 15m      |
| monitoring                  | grafana-operator                 | 100m            | 10.3m     | **15m**           | 85m      |
| monitoring                  | kasa-exporter                    | 50m             | 10.4m     | **15m**           | 35m      |
| monitoring                  | kube-prometheus-stack-operator   | 25m             | 2.3m      | **5m**            | 20m      |
| monitoring                  | kube-state-metrics               | 25m             | 4m        | **10m**           | 15m      |
| monitoring                  | prometheus                       | 250m            | 213m      | **260m**          | -10m     |
| monitoring                  | prometheus-blackbox-exporter     | 50m             | 2.6m      | **5m**            | 45m      |
| observability               | fluent-bit                       | 50m             | 30m       | **40m**           | 10m      |
| observability               | graylog                          | 100m            | 359m      | **450m**          | -350m    |
| observability               | mongodb                          | 200m            | 221m      | **270m**          | -70m     |
| observability               | mongodb-exporter                 | 10m             | 40m       | **50m**           | -40m     |
| observability               | opensearch                       | 50m             | 36m       | **45m**           | 5m       |
| registry                    | docker-registry                  | 100m            | 2m        | **10m**           | 90m      |
| registry                    | docker-registry-ui               | 50m             | 1m        | **5m**            | 45m      |
| registry                    | nexus                            | 500m            | 9m        | **15m**           | 485m     |
| traefik                     | traefik                          | 100m            | 3m        | **10m**           | 90m      |

### Memory Efficiency by Workload

| Namespace                   | Pod                              | Current Request | P95 Usage | Suggested Request | Savings   |
| --------------------------- | -------------------------------- | --------------- | --------- | ----------------- | --------- |
| argocd-image-updater-system | argocd-image-updater-controller  | 512Mi           | 29Mi      | **40Mi**          | 472Mi     |
| argocd                      | argocd-application-controller    | 512Mi           | 377Mi     | **450Mi**         | 62Mi      |
| argocd                      | argocd-repo-server               | 256Mi           | 40Mi      | **50Mi**          | 206Mi     |
| argocd                      | argocd-server                    | 128Mi           | 45Mi      | **60Mi**          | 68Mi      |
| argocd                      | argocd-applicationset-controller | 64Mi            | 29Mi      | **40Mi**          | 24Mi      |
| argocd                      | argocd-redis                     | 64Mi            | 5Mi       | **10Mi**          | 54Mi      |
| bastion                     | bastion                          | 64Mi            | 2Mi       | **10Mi**          | 54Mi      |
| catalyst                    | catalyst-ui (x2)                 | 64Mi each       | 8Mi       | **15Mi**          | 49Mi each |
| external-secrets            | onepassword-connect              | 128Mi           | 40Mi      | **50Mi**          | 78Mi      |
| external-secrets            | external-secrets                 | 64Mi            | 35Mi      | **45Mi**          | 19Mi      |
| external-secrets            | external-secrets-cert-controller | 64Mi            | 46Mi      | **60Mi**          | 4Mi       |
| flux-system                 | helm-controller                  | 64Mi            | 94Mi      | **120Mi**         | -56Mi     |
| flux-system                 | kustomize-controller             | 64Mi            | 68Mi      | **85Mi**          | -21Mi     |
| flux-system                 | notification-controller          | 64Mi            | 34Mi      | **45Mi**          | 19Mi      |
| flux-system                 | source-controller                | 64Mi            | 52Mi      | **65Mi**          | -1Mi      |
| infra-control               | goldilocks-controller            | 32Mi            | 27Mi      | **35Mi**          | -3Mi      |
| infra-control               | goldilocks-dashboard             | 32Mi            | 23Mi      | **30Mi**          | 2Mi       |
| infra-control               | headlamp                         | 64Mi            | 15Mi      | **20Mi**          | 44Mi      |
| infra-control               | kube-ops-view                    | 32Mi            | 67Mi      | **85Mi**          | -53Mi     |
| infra-control               | kubeview                         | 32Mi            | 33Mi      | **40Mi**          | -8Mi      |
| kube-system                 | coredns (x2)                     | 70Mi each       | 26Mi      | **35Mi**          | 35Mi each |
| kube-system                 | kube-apiserver                   | 512Mi           | 1545Mi    | **1850Mi**        | -1338Mi   |
| kube-system                 | kube-controller-manager          | 256Mi           | 134Mi     | **165Mi**         | 91Mi      |
| kube-system                 | kube-flannel                     | 50Mi            | 21Mi      | **30Mi**          | 20Mi      |
| kube-system                 | kube-scheduler                   | 64Mi            | 33Mi      | **45Mi**          | 19Mi      |
| kube-system                 | metrics-server                   | 200Mi           | 45Mi      | **60Mi**          | 140Mi     |
| kube-system                 | vpa-recommender                  | 256Mi           | 45Mi      | **60Mi**          | 196Mi     |
| media                       | homepage                         | 64Mi            | 104Mi     | **130Mi**         | -66Mi     |
| media                       | jellyfin                         | 256Mi           | 221Mi     | **270Mi**         | -14Mi     |
| media                       | plex                             | 256Mi           | 80Mi      | **100Mi**         | 156Mi     |
| media                       | tdarr                            | 512Mi           | 175Mi     | **215Mi**         | 297Mi     |
| monitoring                  | grafana                          | 256Mi           | 203Mi     | **250Mi**         | 6Mi       |
| monitoring                  | prometheus                       | 1024Mi          | 841Mi     | **1024Mi**        | 0Mi       |
| observability               | graylog                          | 2048Mi          | 5388Mi    | **6500Mi**        | -4452Mi   |
| observability               | mongodb                          | 256Mi           | 280Mi     | **350Mi**         | -94Mi     |
| observability               | opensearch                       | 512Mi           | 1200Mi    | **1450Mi**        | -938Mi    |
| registry                    | nexus                            | 2048Mi          | 1600Mi    | **1920Mi**        | 128Mi     |

---

## Recommended Changes

### Priority 1: Critical Under-provisioned (Increase)

These workloads are using more than their requests and may be throttled or OOM-killed:

| Workload                    | Current Request        | Suggested Request      | Notes                         |
| --------------------------- | ---------------------- | ---------------------- | ----------------------------- |
| kube-system/kube-apiserver  | CPU: 200m, Mem: 512Mi  | CPU: 350m, Mem: 1850Mi | **Critical** - Core component |
| observability/graylog       | CPU: 100m, Mem: 2048Mi | CPU: 450m, Mem: 6500Mi | Heavily undersized            |
| observability/mongodb       | CPU: 200m, Mem: 256Mi  | CPU: 270m, Mem: 350Mi  | Database needs headroom       |
| observability/opensearch    | CPU: 50m, Mem: 512Mi   | CPU: 45m, Mem: 1450Mi  | JVM heap requirements         |
| infra-control/kube-ops-view | CPU: 10m, Mem: 32Mi    | CPU: 60m, Mem: 85Mi    | Resource hungry               |
| flux-system/helm-controller | Mem: 64Mi              | Mem: 120Mi             | Needs more memory             |
| media/homepage              | Mem: 64Mi              | Mem: 130Mi             | Node.js app                   |

### Priority 2: Major Over-provisioned (Decrease)

Largest savings opportunities:

| Workload                      | Current Request        | Suggested Request     | CPU Savings | Mem Savings |
| ----------------------------- | ---------------------- | --------------------- | ----------- | ----------- |
| registry/nexus                | CPU: 500m, Mem: 2048Mi | CPU: 15m, Mem: 1920Mi | **485m**    | 128Mi       |
| argocd-image-updater          | CPU: 250m, Mem: 512Mi  | CPU: 10m, Mem: 40Mi   | **240m**    | **472Mi**   |
| argocd/application-controller | CPU: 250m, Mem: 512Mi  | CPU: 50m, Mem: 450Mi  | **200m**    | 62Mi        |
| argocd/repo-server            | CPU: 100m, Mem: 256Mi  | CPU: 10m, Mem: 50Mi   | **90m**     | **206Mi**   |
| media/tdarr                   | CPU: 100m, Mem: 512Mi  | CPU: 10m, Mem: 215Mi  | **90m**     | **297Mi**   |
| traefik                       | CPU: 100m, Mem: 50Mi   | CPU: 10m, Mem: 45Mi   | **90m**     | 5Mi         |
| docker-registry               | CPU: 100m, Mem: 128Mi  | CPU: 10m, Mem: 20Mi   | **90m**     | **108Mi**   |
| kube-system/metrics-server    | Mem: 200Mi             | Mem: 60Mi             | 0m          | **140Mi**   |
| kube-system/vpa-recommender   | CPU: 50m, Mem: 256Mi   | CPU: 10m, Mem: 60Mi   | **40m**     | **196Mi**   |

### Priority 3: Moderate Adjustments

| Workload                              | Change                                        |
| ------------------------------------- | --------------------------------------------- |
| All media apps (sonarr, radarr, etc.) | Reduce CPU from 25m to 5m                     |
| All linkerd components                | Keep as-is (low usage, low requests)          |
| coredns (x2)                          | Reduce from 100m to 15m CPU, 70Mi to 35Mi mem |
| flux controllers                      | Increase memory, decrease CPU                 |

---

## Resource Budget After Optimization

### Projected Totals (with recommended changes)

| Resource            | Before        | After          | Savings       |
| ------------------- | ------------- | -------------- | ------------- |
| **CPU Requests**    | 5120m (86%)   | ~2800m (47%)   | ~2320m freed  |
| **Memory Requests** | 15196Mi (98%) | ~12000Mi (78%) | ~3200Mi freed |

### Key Trade-offs

1. **Graylog/OpenSearch:** These require significantly more memory than allocated. Consider:
   - Reducing retention/indices
   - Moving to external logging service
   - Accepting the increased memory allocation

2. **kube-apiserver:** Talos sets minimal defaults. The 1850Mi memory recommendation may require machine config changes.

3. **Nexus:** Currently over-provisioned. Can safely reduce, but may need burst capacity for heavy Docker operations.

---

## Implementation Guide

### Phase 1: Quick Wins (Safe reductions)

```bash
# These changes free up resources immediately with minimal risk
# Apply to: argocd, registry, monitoring exporters, media apps
```

1. Reduce ArgoCD components (except application-controller)
2. Reduce registry/nexus CPU to 50m
3. Reduce all media apps to 5m CPU
4. Reduce traefik to 10m CPU

### Phase 2: Infrastructure Adjustments

1. Increase Flux controller memory limits
2. Increase Prometheus to 260m CPU (if experiencing lag)
3. Increase kube-ops-view resources

### Phase 3: Observability Stack Rebalancing

**Option A: Keep full stack**

- Increase graylog memory to 6Gi
- Increase opensearch memory to 1.5Gi
- Increase mongodb memory to 350Mi
- Total additional memory: ~5Gi

**Option B: Reduce observability**

- Disable graylog/opensearch (save ~8Gi memory)
- Use Prometheus/Loki instead

---

## Monitoring Recommendations

1. **Set up alerts for:**
   - Memory usage >80% of limit (OOM risk)
   - CPU throttling (container_cpu_cfs_throttled_periods_total)
   - Pod evictions

2. **Review this analysis monthly** or after significant workload changes

3. **VPA Recommendations:** Goldilocks/VPA is installed - check its recommendations for ongoing optimization

---

## Implementation Progress

### Phase 2: Over-provisioned Reductions (Completed 2025-12-02)

| Workload                      | Before                | After                | CPU Saved | Memory Saved |
| ----------------------------- | --------------------- | -------------------- | --------- | ------------ |
| registry/nexus                | CPU: 500m             | CPU: 50m             | **450m**  | -            |
| argocd/repo-server            | CPU: 100m, Mem: 256Mi | CPU: 10m, Mem: 64Mi  | **90m**   | **192Mi**    |
| argocd/application-controller | CPU: 250m, Mem: 512Mi | CPU: 50m, Mem: 256Mi | **200m**  | **256Mi**    |
| argocd-image-updater          | CPU: 250m, Mem: 512Mi | CPU: 10m, Mem: 64Mi  | **240m**  | **448Mi**    |
| traefik                       | CPU: 100m             | CPU: 10m             | **90m**   | -            |
| docker-registry               | CPU: 100m, Mem: 128Mi | CPU: 10m, Mem: 32Mi  | **90m**   | **96Mi**     |
| vpa-recommender               | CPU: 50m, Mem: 256Mi  | CPU: 10m, Mem: 64Mi  | **40m**   | **192Mi**    |
| media/sonarr                  | CPU: 25m              | CPU: 10m             | **15m**   | -            |
| media/radarr                  | CPU: 25m              | CPU: 10m             | **15m**   | -            |
| media/prowlarr                | CPU: 25m              | CPU: 10m             | **15m**   | -            |
| media/overseerr               | CPU: 25m              | CPU: 10m             | **15m**   | -            |
| media/tdarr                   | CPU: 100m             | CPU: 25m             | **75m**   | -            |

**Notes:**

- Media apps use 10m CPU minimum (not 5m) due to namespace LimitRange constraint
- Tdarr memory kept at 512Mi (256Mi caused startup failures)

**Total Phase 2 Savings:**

- CPU: ~1335m freed
- Memory: ~1184Mi freed

### Phase 1: Under-provisioned Increases (Completed 2025-12-02)

| Workload                    | Before                | After                 | CPU Added | Memory Added |
| --------------------------- | --------------------- | --------------------- | --------- | ------------ |
| observability/graylog       | CPU: 100m, Mem: 2Gi   | CPU: 400m, Mem: 2Gi   | **+300m** | -            |
| observability/mongodb       | CPU: 200m, Mem: 256Mi | CPU: 270m, Mem: 350Mi | **+70m**  | **+94Mi**    |
| observability/opensearch    | Mem: 512Mi, JVM: 512m | Mem: 1450Mi, JVM: 1g  | -         | **+938Mi**   |
| infra-control/kube-ops-view | CPU: 10m, Mem: 32Mi   | CPU: 60m, Mem: 85Mi   | **+50m**  | **+53Mi**    |
| media/homepage              | Mem: 64Mi             | Mem: 130Mi            | -         | **+66Mi**    |

**Notes:**

- Graylog memory kept at original 2Gi (cluster capacity constraint prevents larger allocation)
- kube-apiserver resources are Talos-managed and cannot be changed via Kubernetes
- OpenSearch JVM heap increased from 512m to 1g to match memory increase

**Total Phase 1 Increases:**

- CPU: ~420m added
- Memory: ~1151Mi added

### Net Resource Impact

| Phase                | CPU Change | Memory Change |
| -------------------- | ---------- | ------------- |
| Phase 2 (reductions) | -1335m     | -1184Mi       |
| Phase 1 (increases)  | +420m      | +1151Mi       |
| **Net Change**       | **-915m**  | **-33Mi**     |

### External Repos Optimization (Completed 2025-12-02)

Resource limits added to applications in external repositories (managed by ArgoCD):

| Repo               | App              | Before               | After                | Change           |
| ------------------ | ---------------- | -------------------- | -------------------- | ---------------- |
| **@kasa-exporter** | kasa-exporter    | CPU: 50m, Mem: 128Mi | CPU: 15m, Mem: 64Mi  | -35m, -64Mi      |
| **catalyst-ui**    | catalyst-ui (x2) | CPU: 50m, Mem: 64Mi  | CPU: 10m, Mem: 16Mi  | -40m, -48Mi each |
| **talos-private**  | stash-hardcore   | CPU: 50m, Mem: 256Mi | CPU: 10m, Mem: 192Mi | -40m, -64Mi      |
| **talos-private**  | stash-softcore   | CPU: 50m, Mem: 256Mi | CPU: 10m, Mem: 192Mi | -40m, -64Mi      |
| **talos-private**  | whisparr         | CPU: 25m, Mem: 128Mi | CPU: 10m, Mem: 128Mi | -15m, 0Mi        |

**Notes:**

- All sizing based on P95 usage analysis with 20% headroom
- stash-\* apps keep high limits (2000m CPU, 2Gi memory) for transcoding bursts
- catalyst-ui runs 2 replicas for availability

**Total External Repo Savings:**

- CPU: ~210m freed
- Memory: ~304Mi freed

### Dashboard Enhancements (Completed 2025-12-02)

Added "Efficiency %" column with color thresholds to resource recommendation tables:

| Color  | Efficiency Range   | Meaning                                         |
| ------ | ------------------ | ----------------------------------------------- |
| Red    | <20% or >200%      | Action needed (severely over/under-provisioned) |
| Orange | 20-40%             | Significant over-provisioning                   |
| Yellow | 40-60% or 120-200% | Review recommended                              |
| Green  | 60-120%            | Optimal range                                   |

Access: `http://grafana.talos00` → Infrastructure → Resource Efficiency

---

## Appendix: Raw Metrics Data

See the Resource Efficiency Grafana dashboard for real-time metrics:

- `http://grafana.talos00` → Infrastructure → Resource Efficiency

### Queries Used

```promql
# CPU efficiency
sum(rate(container_cpu_usage_seconds_total{container!="",container!="POD"}[12h])) by (namespace,pod)
/
sum(kube_pod_container_resource_requests{resource="cpu"}) by (namespace,pod)

# Memory efficiency
sum(container_memory_working_set_bytes{container!="",container!="POD"}) by (namespace,pod)
/
sum(kube_pod_container_resource_requests{resource="memory"}) by (namespace,pod)

# P95 CPU for recommendations
quantile_over_time(0.95, sum(rate(container_cpu_usage_seconds_total[5m])) by (namespace,pod)[24h:5m])
```
