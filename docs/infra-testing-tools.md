# Infrastructure Testing UI Tools

This document describes the Kubernetes UI and visualization tools deployed in the `infra-testing` namespace for cluster management and monitoring.

## Overview

The infra-testing stack provides a collection of web-based tools for visualizing, managing, and optimizing your Kubernetes cluster. These tools complement the existing monitoring stack (Prometheus/Grafana) with additional perspectives on cluster resources.

## Deployed Tools

### 1. Headlamp - Modern Kubernetes UI

**Purpose**: General-purpose web UI for cluster management
**Access**: http://headlamp.talos00
**Container Image**: ghcr.io/headlamp-k8s/headlamp:latest

**Features**:

- Clean, modern interface
- Multi-cluster support
- CRD support
- Log streaming and terminal access
- Resource editing with YAML validation
- Plugin system for extensibility

**Best for**: Daily cluster management, users who want a modern alternative to the Kubernetes Dashboard

**Usage**:

1. Navigate to http://headlamp.talos00
2. Headlamp uses in-cluster authentication (cluster-admin ServiceAccount)
3. Browse resources, view logs, edit manifests

---

### 2. Kubeview - Resource Relationship Visualizer

**Purpose**: Interactive visual graph of Kubernetes resources
**Access**: http://kubeview.talos00
**Container Image**: ghcr.io/benc-uk/kubeview:latest

**Features**:

- Visual graph showing resource relationships
- Interactive navigation
- Namespace filtering
- Shows connections between Deployments, Pods, Services, etc.
- Lightweight and fast

**Best for**: Understanding application architecture, visualizing resource dependencies, documentation

**Usage**:

1. Navigate to http://kubeview.talos00
2. Select namespace from dropdown
3. Explore the visual graph showing relationships between resources
4. Click on resources to see details

---

### 3. Kube-ops-view - Real-time Cluster View

**Purpose**: Read-only real-time cluster visualization
**Access**: http://kube-ops-view.talos00
**Container Image**: hjacobs/kube-ops-view:latest

**Features**:

- Real-time cluster state display
- Node and pod visualization
- Resource utilization metrics
- Read-only (safe for NOC displays)
- Clean, simple interface

**Best for**: NOC displays, presentations, real-time monitoring dashboards, status boards

**Usage**:

1. Navigate to http://kube-ops-view.talos00
2. View real-time cluster state
3. See nodes, pods, and resource utilization at a glance
4. Perfect for display on monitors/TVs

---

### 4. Goldilocks - Resource Recommendation Engine

**Purpose**: Right-sizing recommendations for CPU/memory requests and limits
**Access**: http://goldilocks.talos00
**Container Image**: us-Docker.pkg.dev/fairwinds-ops/oss/goldilocks:v4.11.0

**Features**:

- Analyzes actual resource usage
- Provides recommendations for requests/limits
- Integrates with Vertical Pod Autoscaler (VPA)
- Per-namespace analysis
- Shows current vs. recommended values

**Best for**: Cost optimization, resource right-sizing, preventing over/under-provisioning

**Dependencies**:

- Vertical Pod Autoscaler (VPA) - automatically installed with Goldilocks

**Usage**:

1. **Enable Goldilocks for a namespace**:

   ```bash
   # Label a namespace to enable Goldilocks analysis
   kubectl label namespace <namespace> goldilocks.fairwinds.com/enabled=true

   # Example: Enable for infra-testing namespace
   kubectl label namespace infra-testing goldilocks.fairwinds.com/enabled=true
   ```

2. **Access the dashboard**:

   ```bash
   open http://goldilocks.talos00
   ```

3. **View recommendations**:
   - Select namespace from the list
   - View current resource settings vs. recommendations
   - See three recommendation types:
     - **Lower Bound**: Minimum resources needed
     - **Target**: Recommended optimal setting
     - **Upper Bound**: Maximum observed usage

4. **Apply recommendations**:

   ```bash
   # Copy recommended values from dashboard
   # Update deployment manifests with new requests/limits
   kubectl edit deployment <deployment-name> -n <namespace>
   ```

**Important Notes**:

- Goldilocks needs time to gather data (allow 24-48 hours for accurate recommendations)
- Only analyzes namespaces with the `goldilocks.fairwinds.com/enabled=true` label
- Recommendations are based on VPA analysis of actual usage
- Does not automatically apply changes - manual review required

---

## Deployment

### Quick Start

Deploy all infra-testing tools:

```bash
# Using task automation
task infra:deploy-infra-testing

# Or using the script directly
./scripts/deploy-infra-testing.sh
```

### Prerequisites

1. **Cluster Access**: Kubeconfig must be configured

   ```bash
   task kubeconfig-merge
   ```

2. **DNS/Hosts Configuration**: Add to `/etc/hosts`

   ```bash
   192.168.1.54  headlamp.talos00 kubeview.talos00 kube-ops-view.talos00 goldilocks.talos00
   ```

   Or use the update-hosts script:

   ```bash
   sudo ./scripts/update-hosts.sh
   ```

3. **Traefik**: Must be deployed (provides ingress routing)

   ```bash
   # Check Traefik is running
   kubectl get pods -n traefik
   ```

### Manual Deployment

Deploy components individually:

```bash
# Deploy namespace
kubectl apply -k infrastructure/base/infra-testing/namespace/

# Deploy individual tools
kubectl apply -k infrastructure/base/infra-testing/headlamp/
kubectl apply -k infrastructure/base/infra-testing/kubeview/
kubectl apply -k infrastructure/base/infra-testing/kube-ops-view/
kubectl apply -k infrastructure/base/infra-testing/goldilocks/

# Or deploy everything at once
kubectl apply -k infrastructure/base/infra-testing/
```

---

## Management

### Check Status

View status of all infra-testing tools:

```bash
# Using task
task infra:infra-testing-status

# Or manually
kubectl get pods -n infra-testing
kubectl get svc -n infra-testing
kubectl get ingressroute -n infra-testing
```

Expected output:

```
NAME                                    READY   STATUS    RESTARTS   AGE
goldilocks-controller-xxx               1/1     Running   0          5m
goldilocks-dashboard-xxx                1/1     Running   0          5m
headlamp-xxx                            1/1     Running   0          5m
kube-ops-view-xxx                       1/1     Running   0          5m
kubeview-xxx                            1/1     Running   0          5m
```

### View Logs

View logs for a specific tool:

```bash
# Using task (follow logs)
task infra:infra-testing-logs TOOL=headlamp
task infra:infra-testing-logs TOOL=kubeview
task infra:infra-testing-logs TOOL=kube-ops-view
task infra:infra-testing-logs TOOL=goldilocks

# Or manually
kubectl logs -n infra-testing -l app=headlamp --tail=50 -f
kubectl logs -n infra-testing -l app=kubeview --tail=50 -f
```

### Delete/Uninstall

Remove all infra-testing tools:

```bash
# Using task (with confirmation prompt)
task infra:infra-testing-delete

# Or manually
kubectl delete -k infrastructure/base/infra-testing/
```

This will remove:

- All deployed UI tools
- The infra-testing namespace
- VPA components (in kube-system namespace)

---

## Architecture

### Directory Structure

```
infrastructure/base/infra-testing/
├── namespace/
│   ├── namespace.yaml
│   └── kustomization.yaml
├── headlamp/
│   ├── helmrelease.yaml      # Deployment, Service, ServiceAccount, RBAC
│   ├── ingressroute.yaml      # Traefik routing
│   └── kustomization.yaml
├── kubeview/
│   ├── deployment.yaml
│   ├── ingressroute.yaml
│   └── kustomization.yaml
├── kube-ops-view/
│   ├── deployment.yaml
│   ├── ingressroute.yaml
│   └── kustomization.yaml
├── goldilocks/
│   ├── vpa-crd.yaml          # VPA CustomResourceDefinition
│   ├── vpa-install.yaml      # VPA Recommender
│   ├── deployment.yaml       # Goldilocks controller + dashboard
│   ├── ingressroute.yaml
│   └── kustomization.yaml
└── kustomization.yaml         # Main kustomization
```

### RBAC Permissions

**Headlamp**: cluster-admin (full cluster access)
**Kubeview**: Read-only cluster role (get, list, watch on all resources)
**Kube-ops-view**: Read-only for nodes and pods
**Goldilocks**: Can read deployments/pods, manage VPAs
**VPA**: Can read pods/nodes, update VPAs

### Resource Limits

| Tool                  | Memory Request | Memory Limit | CPU Request | CPU Limit |
| --------------------- | -------------- | ------------ | ----------- | --------- |
| Headlamp              | 128Mi          | 512Mi        | 100m        | 500m      |
| Kubeview              | 64Mi           | 256Mi        | 50m         | 200m      |
| Kube-ops-view         | 64Mi           | 256Mi        | 50m         | 200m      |
| Goldilocks Controller | 32Mi           | 32Mi         | 25m         | 25m       |
| Goldilocks Dashboard  | 32Mi           | 32Mi         | 25m         | 25m       |
| VPA Recommender       | 500Mi          | 1000Mi       | 50m         | 200m      |

---

## Integration with Existing Stack

These tools complement the existing monitoring infrastructure:

| Tool Stack               | Purpose                       | Access                       |
| ------------------------ | ----------------------------- | ---------------------------- |
| **Prometheus + Grafana** | Metrics, dashboards, alerting | http://grafana.talos00       |
| **Graylog**              | Log aggregation and analysis  | http://graylog.talos00       |
| **Kubernetes Dashboard** | Official K8s UI               | kubectl proxy                |
| **Headlamp**             | Modern K8s management UI      | http://headlamp.talos00      |
| **Kubeview**             | Resource visualization        | http://kubeview.talos00      |
| **Kube-ops-view**        | Real-time cluster view        | http://kube-ops-view.talos00 |
| **Goldilocks**           | Resource optimization         | http://goldilocks.talos00    |

**Workflow Integration**:

1. **Daily Operations**: Use Headlamp for general management
2. **Performance Monitoring**: Use Grafana for metrics and dashboards
3. **Log Analysis**: Use Graylog for debugging and audit trails
4. **Architecture Understanding**: Use Kubeview to visualize relationships
5. **Resource Optimization**: Use Goldilocks to right-size workloads
6. **Status Display**: Use Kube-ops-view for NOC/status boards

---

## Troubleshooting

### Tools not accessible via hostname

**Symptom**: Cannot access http://headlamp.talos00

**Solution**:

1. Check `/etc/hosts` configuration:

   ```bash
   cat /etc/hosts | grep talos00
   ```

2. Add missing entries:

   ```bash
   sudo ./scripts/update-hosts.sh
   # Or manually:
   echo "192.168.1.54  headlamp.talos00 kubeview.talos00 kube-ops-view.talos00 goldilocks.talos00" | sudo tee -a /etc/hosts
   ```

3. Verify Traefik IngressRoutes:

   ```bash
   kubectl get ingressroute -n infra-testing
   ```

### Pods not starting

**Symptom**: Pods in CrashLoopBackOff or Pending state

**Solution**:

1. Check pod status and events:

   ```bash
   kubectl describe pod -n infra-testing <pod-name>
   ```

2. View logs:

   ```bash
   task infra:infra-testing-logs TOOL=<tool-name>
   ```

3. Check resource availability (single-node cluster):

   ```bash
   kubectl top nodes
   kubectl top pods -A
   ```

### Goldilocks shows no data

**Symptom**: Goldilocks dashboard is empty or shows no namespaces

**Solution**:

1. Verify namespace is labeled:

   ```bash
   kubectl get namespace -L goldilocks.fairwinds.com/enabled
   ```

2. Add label if missing:

   ```bash
   kubectl label namespace <namespace> goldilocks.fairwinds.com/enabled=true
   ```

3. Check VPA is running:

   ```bash
   kubectl get pods -n kube-system -l app=vpa-recommender
   ```

4. Wait for data collection (24-48 hours for accurate recommendations)

### VPA not working

**Symptom**: VPA recommender pod failing

**Solution**:

1. Check VPA CRD is installed:

   ```bash
   kubectl get crd verticalpodautoscalers.autoscaling.k8s.io
   ```

2. Reinstall VPA if needed:

   ```bash
   kubectl apply -k infrastructure/base/infra-testing/goldilocks/
   ```

---

## Additional Resources

- [Headlamp Documentation](https://headlamp.dev/docs/)
- [Kubeview GitHub](https://github.com/benc-uk/kubeview)
- [Kube-ops-view GitHub](https://github.com/hjacobs/kube-ops-view)
- [Goldilocks Documentation](https://goldilocks.docs.fairwinds.com/)
- [Vertical Pod Autoscaler](https://github.com/kubernetes/autoscaler/tree/master/vertical-pod-autoscaler)

---

## Quick Reference Commands

```bash
# Deploy all tools
task infra:deploy-infra-testing

# Check status
task infra:infra-testing-status

# View logs
task infra:infra-testing-logs TOOL=headlamp

# Enable Goldilocks for a namespace
kubectl label namespace <namespace> goldilocks.fairwinds.com/enabled=true

# Delete all tools
task infra:infra-testing-delete

# Access URLs
open http://headlamp.talos00
open http://kubeview.talos00
open http://kube-ops-view.talos00
open http://goldilocks.talos00
```
