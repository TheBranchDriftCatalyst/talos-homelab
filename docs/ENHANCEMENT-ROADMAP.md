# Talos Homelab Enhancement Roadmap

**Date:** 2025-11-25
**Status:** Planning Phase
**Tracking:** Two parallel implementation streams

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

**Repository:** [containers/kubernetes-mcp-server](https://github.com/containers/kubernetes-mcp-server)
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

**Repository:** [grafana/mcp-grafana](https://github.com/grafana/mcp-grafana)
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

**Repository:** [pab1it0/prometheus-mcp-server](https://github.com/pab1it0/prometheus-mcp-server)
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
- We use Helm extensively (kube-prometheus-stack, Graylog, Fluent Bit, etc.)
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

#### 4. coreos_prometheus

**Repository:** [tilt-dev/tilt-extensions/coreos_prometheus](https://github.com/tilt-dev/tilt-extensions)
**Priority:** **MEDIUM**

**Why:**
- We use kube-prometheus-stack (CoreOS Prometheus Operator)
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

#### Phase 1: Setup & Foundation (Week 1)
- [ ] Install Tilt locally (`brew install tilt`)
- [ ] Create initial `Tiltfile` in repo root
- [ ] Load `helm_resource` extension
- [ ] Configure basic Helm chart (fluent-bit as test)
- [ ] Verify Tilt UI access

#### Phase 2: Core Extensions (Week 2)
- [ ] Add `k8s_attach` for monitoring existing resources
- [ ] Implement `secret` extension for dev secrets
- [ ] Configure `dotenv` for environment variables
- [ ] Add `namespace` utilities
- [ ] Test workflow end-to-end

#### Phase 3: Advanced Features (Week 3)
- [ ] Configure `coreos_prometheus` for monitoring stack
- [ ] Add `uibutton` for common operations
- [ ] Create Tilt resources for all Helm charts
- [ ] Document Tilt workflows

#### Phase 4: Integration & Optimization (Week 4)
- [ ] Integrate with existing deployment scripts
- [ ] Optimize build/deploy cycles
- [ ] Create developer documentation
- [ ] Team training (if applicable)

---

### Example Tiltfile Structure

```python
# Tiltfile for Talos Homelab Infrastructure

# Load extensions
load('ext://helm_resource', 'helm_resource', 'helm_repo')
load('ext://k8s_attach', 'k8s_attach')
load('ext://dotenv', 'dotenv')
load('ext://secret', 'secret_from_dict', 'secret_create_generic')
load('ext://namespace', 'namespace_create')
load('ext://uibutton', 'cmd_button', 'location')

# Load environment variables
dotenv()

# Configure kubectl context
allow_k8s_contexts('talos-homelab')

# Helm repositories
helm_repo('fluent', 'https://fluent.github.io/helm-charts')
helm_repo('grafana', 'https://grafana.github.io/helm-charts')
helm_repo('prometheus-community', 'https://prometheus-community.github.io/helm-charts')

# Monitoring Stack
helm_resource(
    'kube-prometheus-stack',
    'prometheus-community/kube-prometheus-stack',
    namespace='monitoring',
    flags=[
        '--values=infrastructure/base/monitoring/kube-prometheus-stack/values.yaml',
        '--set', 'grafana.adminPassword=' + os.getenv('GRAFANA_PASSWORD', 'admin')
    ],
    resource_deps=['monitoring-namespace']
)

# Observability Stack
helm_resource(
    'fluent-bit',
    'fluent/fluent-bit',
    namespace='observability',
    flags=['--values=infrastructure/base/observability/fluent-bit/values.yaml'],
    resource_deps=['observability-namespace']
)

# Attach to existing pods for monitoring
k8s_attach('graylog-0', namespace='observability', resource_name='graylog')
k8s_attach('prometheus-kube-prometheus-stack-prometheus-0', namespace='monitoring', resource_name='prometheus')

# Custom buttons
cmd_button(
    'flux:reconcile-all',
    argv=['flux', 'reconcile', 'kustomization', 'flux-system', '--with-source'],
    location=location.NAV,
    text='🔄 Reconcile Flux'
)

cmd_button(
    'dashboard:token',
    argv=['./scripts/dashboard-token.sh'],
    location=location.NAV,
    text='🔑 K8s Dashboard Token'
)
```

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

1. Review this roadmap with team/stakeholders
2. Prioritize streams based on current needs
3. Begin Phase 1 implementation for both streams
4. Schedule weekly sync to track progress
5. Adjust timeline based on learning and blockers

---

**Last Updated:** 2025-11-25
**Owner:** Infrastructure Team
**Review Cycle:** Weekly
