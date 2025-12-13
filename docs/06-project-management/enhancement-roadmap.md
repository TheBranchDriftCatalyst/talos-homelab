# Talos Homelab Enhancement Roadmap

**Date:** 2025-11-25
**Last Updated:** 2025-12-12
**Status:** Stream 2 In Progress, Stream 1 Planning
**Tracking:** Beads issue tracker (see below)

> **Beads Migration**: Active tasks from this roadmap are now tracked in beads:
> - `TALOS-7fu` - MCP Server Integration (Stream 1)
> - `TALOS-w1k` - Tilt Development Workflow (Stream 2)
>
> Run `bd ready` to see available work.

---

## Quick Status Summary

| Stream                        | Status         | Progress |
| ----------------------------- | -------------- | -------- |
| **Stream 1: MCP Servers**     | 🔴 Not Started | 0%       |
| **Stream 2: Tilt Extensions** | 🟡 In Progress | ~60%     |

### Stream 2 Extension Status

| Extension           | Priority | Status         | Notes                                   |
| ------------------- | -------- | -------------- | --------------------------------------- |
| `helm_resource`     | HIGH     | ✅ Implemented | Loaded in root Tiltfile                 |
| `k8s_attach`        | HIGH     | ✅ Implemented | Attaches to all Flux-managed resources  |
| `uibutton`          | HIGH     | ✅ Implemented | Nav buttons + resource-specific buttons |
| `dotenv`            | MEDIUM   | ✅ Implemented | `.env.example` created                  |
| `secret`            | LOW      | ⏭️ Skipped     | ESO/1Password handles secrets           |
| `namespace`         | MEDIUM   | 🔴 Not Started | Optional for dev isolation              |
| `coreos_prometheus` | LOW      | ⏭️ Skipped     | Already have kube-Prometheus-stack      |

---

## Overview

This document tracks enhancement opportunities for the Talos Kubernetes homelab infrastructure through two parallel streams:

1. **Stream 1: MCP Server Integration** - AI-powered infrastructure management and monitoring
2. **Stream 2: Tilt Development Extensions** - Enhanced local development workflow

---

## Stream 1: MCP Server Integration

### What is MCP?

Model Context Protocol (MCP) is an open protocol released by Anthropic in late 2024 that enables AI models to securely interact with local and remote resources through standardized server implementations. It allows AI agents and LLMs to interact with third-party APIs to work with real data and make actions on your behalf.

### High Priority MCP Servers

#### 1. Kubernetes MCP Server

**Repository:** [containers/Kubernetes-mcp-server](https://github.com/containers/kubernetes-mcp-server)
**Type:** Native Go implementation
**Deployment:** Binary, npm, Python, Docker

**Features:**

- Multi-cluster support (reads from kubeconfig)
- Direct Kubernetes API server interaction
- Resource management (pods, services, deployments, namespaces, nodes, cronjobs)
- Pod log retrieval
- Helm v3 chart management

**Use Case for Our Cluster:**

- Natural language queries for pod status across all namespaces
- Quick debugging without remembering kubectl commands
- Helm chart management through AI assistant
- Multi-environment management (if we expand beyond single node)

**Installation Priority:** **HIGH**
**Implementation Effort:** Medium (Docker deployment available)

---

#### 2. Grafana MCP Server

**Repository:** [Grafana/mcp-Grafana](https://github.com/grafana/mcp-grafana)
**Type:** Official Grafana integration
**Deployment:** Docker, stdio, SSE transport

**Features:**

- Search dashboards
- Fetch datasource information
- Execute PromQL queries (instant and range)
- Retrieve metric metadata, names, label names/values
- Run LogQL queries against Loki datasources
- Manage incidents

**Use Case for Our Cluster:**

- Natural language queries to Prometheus metrics
- Dashboard navigation without UI
- Quick metric analysis during troubleshooting
- Log query generation for Graylog/Loki integration

**Installation Priority:** **HIGH**
**Implementation Effort:** Low (official Docker image available)

**Docker Command:**

```bash
docker run --rm -p 8000:8000 \
  -e GRAFANA_URL=http://grafana.talos00 \
  -e GRAFANA_SERVICE_ACCOUNT_TOKEN=<token> \
  mcp/grafana -t streamable-http
```

---

#### 3. Prometheus MCP Server

**Repository:** [pab1it0/Prometheus-mcp-server](https://github.com/pab1it0/prometheus-mcp-server)
**Type:** Community-built Prometheus integration
**Deployment:** Docker (`ghcr.io/pab1it0/prometheus-mcp-server:latest`)

**Features:**

- Query and analyze Prometheus metrics
- Standardized AI assistant interfaces
- Performance and health insights
- Custom metric queries

**Use Case for Our Cluster:**

- Direct Prometheus metric queries via AI
- Performance trend analysis
- Alert investigation
- Resource usage optimization recommendations

**Installation Priority:** **MEDIUM**
**Implementation Effort:** Low (Docker deployment)

---

#### 4. FluxCD/ArgoCD MCP Server

**Status:** Research phase - may need custom development

**Potential Features:**

- GitOps status queries
- Reconciliation monitoring
- Helm release management
- Application sync status

**Use Case for Our Cluster:**

- Natural language queries for Flux/ArgoCD status
- Troubleshoot deployment issues
- Monitor reconciliation loops
- GitOps workflow automation

**Installation Priority:** **MEDIUM**
**Implementation Effort:** HIGH (may require custom development)

---

#### 5. Tekton CI/CD MCP Server (Optional)

**Source:** [OpenShift Pipelines - Tekton MCP Server](https://www.pulsemcp.com/servers/openshift-pipelines-tekton)

**Features:**

- Start and monitor Tekton CI/CD pipelines
- Natural language pipeline management
- No direct cluster access required

**Use Case for Our Cluster:**

- Only if we adopt Tekton for CI/CD
- Currently using Flux for GitOps (may not be needed)

**Installation Priority:** **LOW**
**Implementation Effort:** Medium

---

### MCP Deployment Architecture

**Recommended Deployment Pattern:**

```yaml
# Kubernetes deployment approach
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-servers
  namespace: observability
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mcp-servers
  template:
    metadata:
      labels:
        app: mcp-servers
    spec:
      containers:
        - name: kubernetes-mcp
          image: ghcr.io/containers/kubernetes-mcp-server:latest
          env:
            - name: KUBECONFIG
              value: /etc/kubernetes/config
          volumeMounts:
            - name: kubeconfig
              mountPath: /etc/kubernetes
              readOnly: true

        - name: grafana-mcp
          image: mcp/grafana:latest
          env:
            - name: GRAFANA_URL
              value: http://grafana.talos00
            - name: GRAFANA_SERVICE_ACCOUNT_TOKEN
              valueFrom:
                secretKeyRef:
                  name: grafana-mcp-token
                  key: token

        - name: prometheus-mcp
          image: ghcr.io/pab1it0/prometheus-mcp-server:latest
          env:
            - name: PROMETHEUS_URL
              value: http://prometheus-kube-prometheus-stack-prometheus.monitoring:9090

      volumes:
        - name: kubeconfig
          secret:
            secretName: mcp-kubeconfig
```

**Benefits:**

- Centralized MCP server management
- Kubernetes-native deployment
- Easy to manage with Flux GitOps
- Consistent with current infrastructure patterns

---

### MCP Integration Milestones

#### Phase 1: Foundation (Week 1-2)

- [ ] Create `infrastructure/base/mcp/` directory structure
- [ ] Deploy Kubernetes MCP server (containerized)
- [ ] Test basic cluster queries via MCP
- [ ] Document MCP server endpoints

#### Phase 2: Monitoring Integration (Week 3-4)

- [ ] Deploy Grafana MCP server
- [ ] Configure Grafana service account token
- [ ] Deploy Prometheus MCP server
- [ ] Test PromQL queries via MCP
- [ ] Create example query documentation

#### Phase 3: Advanced Integration (Week 5-6)

- [ ] Investigate FluxCD MCP integration
- [ ] Custom MCP server development (if needed)
- [ ] Create unified MCP dashboard
- [ ] Integration testing with Claude Desktop

#### Phase 4: Documentation & Optimization (Week 7-8)

- [ ] Complete MCP usage documentation
- [ ] Create troubleshooting guides
- [ ] Optimize resource usage
- [ ] Security review and hardening

---

## Stream 2: Tilt Development Extensions

### What is Tilt?

Tilt powers microservice development and automates the steps from code change to running process. It watches files, builds container images, and brings your environment up-to-date with live_update deploying code to running containers in seconds.

### Why Tilt for This Project?

**Current State:**

- Manual deployment scripts (`./scripts/deploy-stack.sh`)
- Flux handles GitOps for applications
- No rapid inner dev loop for infrastructure testing

**Tilt Benefits:**

- Fast iteration on infrastructure manifests
- Live reload for Kubernetes resources
- Integrated Helm chart development
- Unified development dashboard
- File sync without full rebuilds

---

### High Priority Tilt Extensions

#### 1. helm_resource

**Repository:** [tilt-dev/tilt-extensions/helm_resource](https://github.com/tilt-dev/tilt-extensions)
**Priority:** **HIGH**

**Why:**

- We use Helm extensively (kube-Prometheus-stack, Graylog, Fluent Bit, etc.)
- Enables rapid Helm chart development
- Values file hot-reload
- Chart validation before commit

**Use Case:**

```python
# Tiltfile example
load('ext://helm_resource', 'helm_resource', 'helm_repo')

helm_repo('fluent', 'https://fluent.github.io/helm-charts')

helm_resource(
    'fluent-bit',
    'fluent/fluent-bit',
    namespace='observability',
    flags=['--values=infrastructure/base/observability/fluent-bit/values.yaml']
)
```

**Implementation Effort:** Low

---

#### 2. k8s_attach

**Repository:** [tilt-dev/tilt-extensions/k8s_attach](https://github.com/tilt-dev/tilt-extensions)
**Priority:** **HIGH**

**Why:**

- Monitor existing cluster resources
- Attach to Flux-managed resources
- View logs in unified Tilt UI
- Health monitoring

**Use Case:**

```python
# Monitor existing deployments
load('ext://k8s_attach', 'k8s_attach')

k8s_attach('graylog-0', namespace='observability')
k8s_attach('prometheus-kube-prometheus-stack-prometheus-0', namespace='monitoring')
```

**Implementation Effort:** Low

---

#### 3. namespace

**Repository:** [tilt-dev/tilt-extensions/namespace](https://github.com/tilt-dev/tilt-extensions)
**Priority:** **MEDIUM**

**Why:**

- Namespace management utilities
- Create temporary test namespaces
- Clean up after development
- Isolation for testing

**Use Case:**

- Testing infrastructure changes in isolated namespace
- Preventing conflicts with production workloads
- Clean dev/test separation

**Implementation Effort:** Low

---

#### 4. coreos_Prometheus

**Repository:** [tilt-dev/tilt-extensions/coreos_prometheus](https://github.com/tilt-dev/tilt-extensions)
**Priority:** **MEDIUM**

**Why:**

- We use kube-Prometheus-stack (CoreOS Prometheus Operator)
- Simplified Prometheus development workflow
- ServiceMonitor/PodMonitor hot-reload
- Quick metric testing

**Implementation Effort:** Low

---

#### 5. dotenv

**Repository:** [tilt-dev/tilt-extensions/dotenv](https://github.com/tilt-dev/tilt-extensions)
**Priority:** **MEDIUM**

**Why:**

- Load environment variables from `.env` files
- Consistent with existing scripts
- Secrets management in development
- Configuration flexibility

**Use Case:**

```python
load('ext://dotenv', 'dotenv')
dotenv()  # Loads .env file in repo root
```

**Implementation Effort:** Low

---

#### 6. secret

**Repository:** [tilt-dev/tilt-extensions/secret](https://github.com/tilt-dev/tilt-extensions)
**Priority:** **HIGH**

**Why:**

- Kubernetes secret creation helpers
- Development secret management
- External Secrets Operator integration
- Simplified secret testing

**Implementation Effort:** Low

---

#### 7. kubectl_build

**Repository:** [tilt-dev/tilt-extensions/kubectl_build](https://github.com/tilt-dev/tilt-extensions)
**Priority:** **LOW** (we have local Docker registry)

**Why:**

- In-cluster image building with BuildKit
- Faster builds for remote clusters
- Alternative to local Docker builds

**Use Case:**

- Only if we move away from local registry
- Could be useful for multi-node cluster

**Implementation Effort:** Medium

---

#### 8. uibutton

**Repository:** [tilt-dev/tilt-extensions/uibutton](https://github.com/tilt-dev/tilt-extensions)
**Priority:** **MEDIUM**

**Why:**

- Custom dashboard buttons
- Quick access to common tasks
- Unified workflow triggers
- Better UX for operations

**Use Case:**

```python
load('ext://uibutton', 'cmd_button', 'location')

cmd_button(
    'flux:reconcile',
    resource='fluent-bit',
    argv=['flux', 'reconcile', 'helmrelease', 'fluent-bit', '-n', 'observability'],
    location=location.RESOURCE,
    text='Force Reconcile'
)
```

**Implementation Effort:** Low

---

#### 9. restart_process

**Repository:** [tilt-dev/tilt-extensions/restart_process](https://github.com/tilt-dev/tilt-extensions)
**Priority:** **LOW**

**Why:**

- Auto-restart after live updates
- Useful for development containers
- Not critical for infrastructure work

**Implementation Effort:** Low

---

### Tilt Implementation Roadmap

#### Phase 1: Setup & Foundation (Week 1) ✅ COMPLETE

- [x] Install Tilt locally (`brew install tilt`)
- [x] Create initial `Tiltfile` in repo root
- [x] Load `helm_resource` extension
- [x] Create infrastructure `Tiltfile` with storage, monitoring, observability
- [x] Create arr-stack `Tiltfile` for media automation
- [x] Verify Tilt UI access

#### Phase 2: Core Extensions (Week 2) ✅ COMPLETE

- [x] Add `k8s_attach` for monitoring existing Flux-managed resources
  - Monitoring: Prometheus, Grafana, Alertmanager
  - Observability: Graylog, OpenSearch, MongoDB, Fluent Bit
  - GitOps: ArgoCD server, repo-server, app-controller
  - Networking: Traefik
  - Registry: Docker Registry
  - Secrets: External Secrets Operator, 1Password Connect
- [x] Configure `dotenv` for environment variables
- [x] Create `.env.example` with documented configuration options
- [x] Skip `secret` extension (ESO/1Password handles secrets - see notes below)
- [ ] Add `namespace` utilities (optional - for dev isolation)

#### Phase 3: Advanced Features (Week 3) ✅ MOSTLY COMPLETE

- [x] Add `uibutton` for common operations
  - Global nav: Flux Sync, K8s Token, Health Check, Infra Dashboard, Deploy Stack
  - Resource-specific: Get Password (Grafana, ArgoCD), Restart (Graylog), List Images (Registry), Get Token (Headlamp), Refresh VPAs (Goldilocks), Scale (Sonarr)
- [x] Create Tilt resources for infra-testing tools (Headlamp, Kubeview, Kube-ops-view, Goldilocks)
- [ ] Skip `coreos_prometheus` (already have kube-Prometheus-stack via Flux)
- [x] Document Tilt workflows (`docs/tilt-development-workflow.md`)

#### Phase 4: Integration & Optimization (Week 4) 🔶 IN PROGRESS

- [x] Integrate with existing deployment scripts (deploy-stack.sh, deploy-observability.sh)
- [x] File watching for hot-reload on manifest changes
- [ ] Optimize build/deploy cycles
- [x] Create developer documentation
- [ ] Team training (if applicable)

#### Notes on Skipped Extensions

**`secret` extension skipped:**

- Our secret management uses External Secrets Operator (ESO) with 1Password
- Pattern: `1Password → ESO ClusterSecretStore → ExternalSecret → K8s Secret`
- Tilt `secret` would only be useful for:
  - Bootstrapping ESO itself (chicken-egg problem)
  - Quick throwaway test secrets during development
- Decision: Not worth the complexity, ESO handles all production secrets

**`coreos_prometheus` extension skipped:**

- We already have `kube-prometheus-stack` deployed via Flux/Helm
- Extension would deploy a separate Prometheus instance
- Using `k8s_attach` instead to view logs of existing Prometheus

---

### Current Tiltfile Implementation

The root `Tiltfile` now includes the following implemented features:

```python
# Load Tilt extensions
load('ext://helm_resource', 'helm_resource', 'helm_repo')
load('ext://dotenv', 'dotenv')
load('ext://uibutton', 'cmd_button', 'location', 'text_input', 'bool_input')
load('ext://k8s_attach', 'k8s_attach')

# Load environment variables from .env file (if exists)
dotenv()

# Configure kubectl context
allow_k8s_contexts('admin@catalyst-cluster')

# ============================================
# k8s_attach - View logs for Flux-managed resources
# ============================================

# Monitoring Stack
k8s_attach('monitoring:prometheus', 'statefulset/prometheus-kube-prometheus-stack-prometheus', namespace='monitoring')
k8s_attach('monitoring:grafana', 'deployment/kube-prometheus-stack-grafana', namespace='monitoring')
k8s_attach('monitoring:alertmanager', 'statefulset/alertmanager-kube-prometheus-stack-alertmanager', namespace='monitoring')

# Observability Stack
k8s_attach('observability:graylog', 'statefulset/graylog', namespace='observability')
k8s_attach('observability:opensearch', 'statefulset/opensearch', namespace='observability')
k8s_attach('observability:mongodb', 'deployment/mongodb', namespace='observability')
k8s_attach('observability:fluent-bit', 'daemonset/fluent-bit', namespace='observability')

# GitOps - ArgoCD
k8s_attach('gitops:argocd-server', 'deployment/argocd-server', namespace='argocd')

# Networking & Infrastructure
k8s_attach('networking:traefik', 'deployment/traefik', namespace='traefik')
k8s_attach('registry:docker-registry', 'deployment/docker-registry', namespace='registry')
k8s_attach('secrets:external-secrets', 'deployment/external-secrets', namespace='external-secrets')
k8s_attach('secrets:onepassword-connect', 'deployment/onepassword-connect', namespace='external-secrets')

# ============================================
# uibutton - Global Navigation Buttons
# ============================================

cmd_button(name='btn-flux-sync', argv=['flux', 'reconcile', 'kustomization', 'flux-system', '--with-source'],
    location=location.NAV, text='🔄 Flux Sync', icon_name='sync')

cmd_button(name='btn-dashboard-token', argv=['./scripts/dashboard-token.sh'],
    location=location.NAV, text='🔑 K8s Token', icon_name='key')

cmd_button(name='btn-cluster-health', argv=['sh', '-c', 'kubectl get nodes && kubectl get pods -A | grep -v Running'],
    location=location.NAV, text='💚 Health', icon_name='favorite')

cmd_button(name='btn-infrastructure-dashboard', argv=['./infrastructure/dashboard.sh'],
    location=location.NAV, text='📊 Infra Dashboard', icon_name='dashboard')

cmd_button(name='btn-deploy-full-stack', argv=['./scripts/deploy-stack.sh'],
    location=location.NAV, text='🚀 Deploy Stack', icon_name='rocket_launch', requires_confirmation=True)

# ============================================
# uibutton - Resource-specific Buttons
# ============================================

# Get credentials for services
cmd_button(name='btn-grafana-password', resource='monitoring:grafana',
    argv=['sh', '-c', 'kubectl get secret -n monitoring kube-prometheus-stack-grafana -o jsonpath="{.data.admin-password}" | base64 -d'],
    text='Get Password', icon_name='password')

cmd_button(name='btn-argocd-password', resource='gitops:argocd-server',
    argv=['sh', '-c', 'kubectl get secret -n argocd argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d'],
    text='Get Password', icon_name='password')

# Restart services
cmd_button(name='btn-graylog-restart', resource='observability:graylog',
    argv=['kubectl', 'rollout', 'restart', 'statefulset/graylog', '-n', 'observability'],
    text='Restart', icon_name='refresh', requires_confirmation=True)

# Scale with input
cmd_button(name='btn-scale-sonarr', resource='media:sonarr',
    argv=['sh', '-c', 'kubectl scale deployment/sonarr -n media --replicas=$REPLICAS'],
    text='Scale', icon_name='tune', inputs=[text_input('REPLICAS', default='1')])
```

**Files created/modified:**

- `Tiltfile` - Root orchestrator with all extensions
- `infrastructure/Tiltfile` - Infrastructure-specific resources
- `applications/arr-stack/Tiltfile` - Media automation resources
- `.env.example` - Template for local environment configuration

---

## Implementation Strategy

### Parallel Development Approach

**Week 1-2:**

- Stream 1: Deploy Kubernetes MCP server
- Stream 2: Setup Tilt + basic extensions

**Week 3-4:**

- Stream 1: Add Grafana/Prometheus MCP servers
- Stream 2: Configure Helm + attach extensions

**Week 5-6:**

- Stream 1: Custom MCP development (if needed)
- Stream 2: Add monitoring + UI extensions

**Week 7-8:**

- Stream 1: Documentation + optimization
- Stream 2: Integration + team training

---

## Success Metrics

### Stream 1: MCP Servers

- [ ] AI can query cluster status via natural language
- [ ] Grafana dashboards accessible via AI
- [ ] Prometheus metrics queryable via AI
- [ ] Response time < 2 seconds for common queries
- [ ] Zero security issues in deployment

### Stream 2: Tilt Extensions

- [ ] Infrastructure change deploy time < 30 seconds
- [ ] Helm chart validation before commit
- [ ] Unified development dashboard
- [ ] Live reload for configuration changes
- [ ] Developer documentation complete

---

## Resource Requirements

### Stream 1: MCP Servers

- **CPU:** ~200m per MCP server (3 servers = 600m)
- **Memory:** ~256Mi per MCP server (3 servers = 768Mi)
- **Storage:** Minimal (< 1Gi for logs)
- **Network:** Ingress for external access (optional)

### Stream 2: Tilt Extensions

- **Local:** Tilt runs on development machine
- **Cluster:** No additional cluster resources required
- **Network:** Port-forward access to cluster

---

## Security Considerations

### MCP Servers

- [ ] Service account with minimal RBAC permissions
- [ ] TLS encryption for external access
- [ ] Authentication tokens stored in Kubernetes secrets
- [ ] Network policies to restrict access
- [ ] Audit logging for MCP queries

### Tilt Development

- [ ] Separate kubeconfig for development
- [ ] Read-only access where possible
- [ ] `.env` files in `.gitignore`
- [ ] No production secrets in Tiltfile
- [ ] Namespace isolation for testing

---

## Documentation Deliverables

### Stream 1: MCP Servers

- [ ] `docs/MCP-SETUP.md` - Installation guide
- [ ] `docs/MCP-USAGE.md` - Query examples
- [ ] `docs/MCP-TROUBLESHOOTING.md` - Common issues
- [ ] Update `README.md` with MCP references

### Stream 2: Tilt Extensions

- [ ] `docs/TILT-SETUP.md` - Installation guide
- [ ] `docs/TILT-WORKFLOW.md` - Development workflows
- [ ] `Tiltfile` - Fully commented configuration
- [ ] Update `LOCAL-TESTING.md` with Tilt integration

---

## References

### MCP Resources

- [Kubernetes MCP Server](https://github.com/containers/kubernetes-mcp-server)
- [Grafana MCP Server](https://github.com/grafana/mcp-grafana)
- [Prometheus MCP Server](https://github.com/pab1it0/prometheus-mcp-server)
- [Awesome DevOps MCP Servers](https://github.com/rohitg00/awesome-devops-mcp-servers)
- [MCP Server Monitoring with Prometheus & Grafana](https://medium.com/@vishaly650/monitoring-mcp-servers-with-prometheus-and-grafana-8671292e6351)
- [What is MCP and Why DevOps Engineers Should Use It](https://medium.com/@DynamoDevOps/what-is-mcp-and-why-devops-engineers-should-start-using-it-2507d51a692e)

### Tilt Resources

- [Tilt Official Site](https://tilt.dev/)
- [Tilt Extensions Repository](https://github.com/tilt-dev/tilt-extensions)
- [Tilt Extensions README](https://github.com/tilt-dev/tilt-extensions/blob/master/README.md)
- [Rapid Kubernetes Controller Development with Tilt](https://skarlso.github.io/2023/02/25/rapid-controller-development-with-tilt/)
- [Local Development Workflow with Tilt and Carvel](https://carvel.dev/blog/tilt-carvel-local-workflow/)
- [Tilt Tutorial 2025](https://github.com/robert-at-pretension-io/Tilt_Tutorial)

### General Resources

- [Model Context Protocol Official](https://model-context-protocol.com/servers/kubernetes-management-platform-server-mcp)
- [Top 10 Best MCP Servers in 2025](https://cyberpress.org/best-mcp-servers/)
- [Tilt Alternatives for Kubernetes Development](https://northflank.com/blog/tilt-alternatives)

---

## Next Steps

### Stream 2 (Tilt) - Remaining Work

1. ~~Implement `k8s_attach` for Flux-managed resources~~ ✅
2. ~~Implement `uibutton` for quick actions~~ ✅
3. ~~Implement `dotenv` for configuration~~ ✅
4. [ ] Consider `namespace` extension for dev isolation (optional)
5. [ ] Test Tilt workflow end-to-end with `tilt up`

### Stream 1 (MCP) - Ready to Start

1. Review MCP server options and choose deployment pattern
2. Create `infrastructure/base/mcp/` directory structure
3. Deploy Kubernetes MCP server first (highest value)
4. Test basic cluster queries via MCP
5. Add Grafana/Prometheus MCP servers

### Validation

- Run `tilt up` to verify all extensions load correctly
- Verify `k8s_attach` shows logs for Flux-managed resources
- Test UI buttons in Tilt dashboard
- Confirm `.env` file loading works

---

**Last Updated:** 2025-11-26
**Owner:** Infrastructure Team
**Review Cycle:** Weekly

---

## Changelog

### 2025-11-26

- Implemented `k8s_attach` extension - attaches to all Flux-managed resources
- Implemented `uibutton` extension - global nav + resource-specific buttons
- Implemented `dotenv` extension - loads `.env` for local configuration
- Created `.env.example` with documented configuration options
- Updated extension priority: `secret` → LOW (ESO handles secrets), `uibutton` → HIGH
- Marked Phases 1-3 as complete for Stream 2

### 2025-11-25

- Initial roadmap created
- Documented MCP servers and Tilt extensions
- Created implementation timeline
