# Kubernetes Ecosystem Ideas

Cool K8s tools, operators, and integrations to consider for the catalyst-cluster.

## Workload Management

### Descheduler
**What**: Evicts pods to rebalance cluster based on policies
**Why**: K8s scheduler only acts at pod creation - descheduler handles drift
**Use cases**:
- Rebalance after adding new nodes (talos01, future nodes)
- Evict pods violating affinity rules
- Remove pods from overutilized nodes

```bash
helm repo add descheduler https://kubernetes-sigs.github.io/descheduler/
helm install descheduler descheduler/descheduler -n kube-system
```

**Policies to consider**:
- `RemoveDuplicates` - spread replicas across nodes
- `LowNodeUtilization` - move pods from busy to idle nodes
- `RemovePodsViolatingNodeAffinity` - enforce affinity rules
- `RemovePodsViolatingTopologySpreadConstraint` - enforce spread

---

### Keda (Kubernetes Event-Driven Autoscaling)
**What**: Scale workloads based on external metrics (not just CPU/memory)
**Why**: HPA is limited to basic metrics; KEDA scales on queues, cron, custom metrics

**Scale triggers**:
- Prometheus metrics
- Cron schedules
- Message queues (RabbitMQ, Kafka)
- HTTP request rate
- Custom metrics

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: llm-scaler
spec:
  scaleTargetRef:
    name: llm-worker
  triggers:
  - type: prometheus
    metadata:
      serverAddress: http://prometheus.monitoring:9090
      metricName: pending_llm_requests
      threshold: '5'
```

**Relevant for**: LLM scaler could use KEDA instead of custom Go code

---

### Karpenter
**What**: Just-in-time node provisioning based on pod requirements
**Why**: Cluster Autoscaler is reactive; Karpenter is proactive and faster

**Note**: Primarily for cloud providers (AWS, Azure). For bare-metal/hybrid:
- Could work with AWS GPU nodes in hybrid-llm setup
- Not directly applicable to Talos bare-metal nodes

---

## Networking & Service Mesh

### Cilium
**What**: eBPF-based CNI with advanced networking features
**Why**: Better performance, network policies, observability

**Features**:
- Network policies with L7 filtering
- Transparent encryption (WireGuard)
- Hubble for network observability
- Service mesh without sidecars

**Status**: Could replace default Talos CNI (Flannel)

---

### Linkerd
**What**: Lightweight service mesh
**Why**: mTLS, traffic splitting, retries, observability

**Lighter than Istio**, good for:
- Secure service-to-service communication
- Traffic mirroring for testing
- Canary deployments
- Golden metrics (latency, success rate, throughput)

**See**: `docs/SERVICE-MESH.md` for detailed comparison

---

## GitOps & Deployment

### Argo Rollouts
**What**: Progressive delivery controller
**Why**: Blue-green, canary deployments with analysis

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
spec:
  strategy:
    canary:
      steps:
      - setWeight: 20
      - pause: {duration: 1h}
      - setWeight: 50
      - pause: {duration: 1h}
      - setWeight: 100
      analysis:
        templates:
        - templateName: success-rate
```

**Integrates with**: ArgoCD (already deployed)

---

### Argo Workflows
**What**: Kubernetes-native workflow engine
**Why**: CI/CD pipelines, data processing, ML pipelines

**Use cases**:
- Build pipelines (alternative to GitHub Actions)
- Data ETL jobs
- ML training workflows
- Batch processing

---

### Argo Events
**What**: Event-driven workflow automation
**Why**: Trigger workflows from external events

**Event sources**: Webhooks, S3, Kafka, GitHub, Cron, NATS
**Triggers**: Workflows, K8s resources, HTTP requests

---

## Observability & Debugging

### Pixie (by New Relic)
**What**: eBPF-powered observability without instrumentation
**Why**: Auto-telemetry for services, no code changes needed

**Features**:
- Automatic request tracing
- CPU/memory flamegraphs
- Network traffic analysis
- Service maps

---

### OpenTelemetry Operator
**What**: Auto-instrument applications for tracing
**Why**: Unified observability (traces + metrics + logs)

```yaml
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: auto-instrumentation
spec:
  exporter:
    endpoint: http://jaeger-collector:14268
  propagators:
    - tracecontext
    - baggage
  sampler:
    type: parentbased_traceidratio
    argument: "0.1"
```

---

### Robusta
**What**: Kubernetes troubleshooting and automation platform
**Why**: Auto-remediation, enriched alerts, ChatOps

**Features**:
- Enriched Prometheus alerts (adds pod logs, events)
- Automated runbooks
- Slack/Teams integration
- AI-powered troubleshooting

---

## Security

### Falco
**What**: Runtime security and threat detection
**Why**: Detect anomalous behavior in containers

**Detects**:
- Shell spawned in container
- Sensitive file access
- Network anomalies
- Privilege escalation attempts

```bash
helm repo add falcosecurity https://falcosecurity.github.io/charts
helm install falco falcosecurity/falco -n falco-system
```

---

### Trivy Operator
**What**: Continuous vulnerability scanning
**Why**: Scan images, configs, secrets in-cluster

**Scans**:
- Container images (CVEs)
- Kubernetes manifests (misconfigs)
- Secrets (exposed credentials)
- RBAC (excessive permissions)

---

### Kyverno
**What**: Policy engine for Kubernetes
**Why**: Enforce standards, mutate resources, generate configs

**Example policies**:
- Require resource limits
- Enforce image registry whitelist
- Add default labels
- Require non-root containers

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-labels
spec:
  validationFailureAction: Enforce
  rules:
  - name: require-team-label
    match:
      resources:
        kinds:
        - Pod
    validate:
      message: "label 'team' is required"
      pattern:
        metadata:
          labels:
            team: "?*"
```

---

### External Secrets Operator
**What**: Sync secrets from external providers
**Why**: Keep secrets out of git, centralize secret management

**Status**: ✅ Already deployed (1Password integration)

---

## Storage & Data

### Velero
**What**: Backup and disaster recovery
**Why**: Backup cluster state, PVs, migrate between clusters

```bash
# Backup entire cluster
velero backup create full-backup

# Restore to new cluster
velero restore create --from-backup full-backup
```

**Integrates with**: S3, MinIO, NFS

---

### Longhorn
**What**: Distributed block storage
**Why**: Replicated storage across nodes, snapshots, backups

**Features**:
- Storage replication (2-3 replicas)
- Scheduled backups to S3
- Volume snapshots
- DR across clusters

**Consideration**: Good for multi-node clusters like catalyst-cluster

---

### MinIO
**What**: S3-compatible object storage
**Why**: Local S3 for backups, artifacts, ML models

**Use cases**:
- Velero backup target
- ML model storage
- Artifact repository
- Loki/Tempo storage backend

---

## Cost & Resource Optimization

### Goldilocks
**What**: VPA recommendations dashboard
**Why**: Right-size resource requests/limits

**Status**: ✅ Already deployed in infra-testing

---

### Kubecost
**What**: Cost monitoring and optimization
**Why**: Track resource costs, identify waste

**Features**:
- Cost allocation by namespace/label
- Idle resource detection
- Right-sizing recommendations
- Budget alerts

---

### Kube-green
**What**: Automatic scale-down during off-hours
**Why**: Save resources on dev/test workloads

```yaml
apiVersion: kube-green.com/v1alpha1
kind: SleepInfo
metadata:
  name: dev-sleep
spec:
  weekdays: "1-5"
  sleepAt: "20:00"
  wakeUpAt: "08:00"
  timeZone: "America/New_York"
  suspendCronJobs: true
```

---

## ML/AI Infrastructure

### KubeRay
**What**: Ray cluster operator for distributed computing
**Why**: Distributed ML training, hyperparameter tuning

**Relevant for**: LLM inference scaling, batch processing

---

### Nvidia GPU Operator
**What**: Automate GPU driver and runtime setup
**Why**: Simplify GPU node management

**Status**: Relevant for hybrid-llm AWS GPU nodes

---

### vLLM / Text Generation Inference
**What**: Optimized LLM serving
**Why**: Better throughput than naive inference

**Relevant for**: LLM worker deployments

---

## Developer Experience

### Telepresence
**What**: Local-to-cluster development
**Why**: Debug services locally while connected to cluster

```bash
# Intercept traffic to a service
telepresence intercept my-service --port 8080
```

---

### Skaffold
**What**: Continuous development for Kubernetes
**Why**: Fast build-deploy-test loop

**Similar to**: Tilt (already explored)

---

### Garden
**What**: Development and testing orchestration
**Why**: Define development workflows as code

---

## Priority Implementation List

### High Priority (Immediate Value)
1. **Descheduler** - Essential for multi-node balancing (talos00 + talos01)
2. **Velero** - Backup solution (currently no DR)
3. **Kyverno** - Policy enforcement (security baseline)

### Medium Priority (Nice to Have)
4. **KEDA** - Could simplify LLM scaler
5. **Argo Rollouts** - Better deployments
6. **Longhorn** - Distributed storage for resilience

### Lower Priority (Future Exploration)
7. **Cilium** - CNI upgrade (complex migration)
8. **Linkerd** - Service mesh (adds complexity)
9. **Falco** - Runtime security

---

## Quick Install Commands

```bash
# Descheduler
helm repo add descheduler https://kubernetes-sigs.github.io/descheduler/
helm install descheduler descheduler/descheduler -n kube-system

# KEDA
helm repo add kedacore https://kedacore.github.io/charts
helm install keda kedacore/keda -n keda --create-namespace

# Velero (with MinIO)
helm repo add vmware-tanzu https://vmware-tanzu.github.io/helm-charts
helm install velero vmware-tanzu/velero -n velero --create-namespace

# Kyverno
helm repo add kyverno https://kyverno.github.io/kyverno/
helm install kyverno kyverno/kyverno -n kyverno --create-namespace

# Falco
helm repo add falcosecurity https://falcosecurity.github.io/charts
helm install falco falcosecurity/falco -n falco-system --create-namespace

# Trivy Operator
helm repo add aqua https://aquasecurity.github.io/helm-charts/
helm install trivy-operator aqua/trivy-operator -n trivy-system --create-namespace
```

---

## References

- [CNCF Landscape](https://landscape.cncf.io/) - Full ecosystem overview
- [Awesome Kubernetes](https://github.com/ramitsurana/awesome-kubernetes)
- [Kubernetes SIGs](https://github.com/kubernetes-sigs) - Official extensions
