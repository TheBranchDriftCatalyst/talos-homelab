# Kubernetes UI Tools for Cluster Visualization

This document lists various UI tools you can use to visualize and manage your Kubernetes cluster state, ranging from built-in options to third-party solutions.

## Currently Installed

### 1. Kubernetes Dashboard (Official)

**Status**: ✅ Already deployed in your cluster
**Type**: Web UI
**Access**: Via kubectl proxy

The official Kubernetes Dashboard provides a general-purpose web UI for managing cluster resources.

**How to access:**
```bash
# Get access token
task dashboard-token

# Start proxy
task dashboard-proxy

# Access at: http://localhost:8001/api/v1/namespaces/kubernetes-dashboard/services/https:kubernetes-dashboard:/proxy/
```

**Features:**
- View all resources (deployments, pods, services, etc.)
- Monitor resource usage (CPU/Memory)
- View logs and exec into containers
- Edit YAML manifests
- Scale deployments
- View events and troubleshoot

**Best for**: General cluster management, quick troubleshooting, basic operations

---

## Recommended Terminal-Based UIs

### 2. k9s (Terminal UI)

**Status**: Recommended - Install via Brewfile
**Type**: Terminal UI
**Access**: Direct via CLI

A powerful terminal-based UI for navigating and managing Kubernetes clusters.

**Installation:**
```bash
brew install k9s
# or
task dev:install-brew-deps  # Already in Brewfile
```

**Usage:**
```bash
# Launch k9s
k9s

# Launch in specific namespace
k9s -n media-dev

# Launch with specific context
k9s --context homelab-single
```

**Features:**
- Real-time resource monitoring
- Fast navigation with keyboard shortcuts
- Built-in log viewer and shell access
- Port-forwarding with a single key
- Resource editing
- Built-in benchmarking
- Plugin system
- Skin/theme customization

**Keyboard shortcuts:**
- `:` - Command mode (e.g., `:pods`, `:deploy`, `:svc`)
- `/` - Filter/search
- `l` - View logs
- `s` - Shell into container
- `d` - Describe resource
- `e` - Edit resource
- `y` - View YAML
- `ctrl-d` - Delete resource
- `?` - Help

**Best for**: Daily cluster operations, quick troubleshooting, power users who prefer terminal

---

## Web-Based Third-Party UIs

### 3. Lens (Desktop App)

**Type**: Desktop Application (Electron-based)
**License**: Free for personal use / Paid for teams
**Platform**: macOS, Linux, Windows
**Website**: https://k8slens.dev

The "Kubernetes IDE" - a powerful desktop application for cluster management.

**Installation:**
```bash
brew install --cask lens
```

**Setup:**
1. Launch Lens
2. Add cluster: File → Add Cluster → Select your kubeconfig
3. Browse resources, view metrics, access terminal

**Features:**
- Multi-cluster management
- Built-in Prometheus metrics charts
- Helm chart browser and installer
- Terminal and log streaming
- RBAC management
- Resource editor with validation
- Built-in Prometheus queries
- Extensions/plugins

**Best for**: Managing multiple clusters, Helm operations, developers who want an IDE-like experience

---

### 4. Headlamp

**Type**: Web UI / Desktop App
**License**: Open Source (Apache 2.0)
**Installation**: In-cluster or Desktop
**Website**: https://headlamp.dev

A modern, extensible Kubernetes UI designed to be user-friendly.

**Installation Options:**

**Option A: In-Cluster (Recommended)**
```bash
# Using Helm
helm repo add headlamp https://headlamp-k8s.github.io/headlamp/
helm install headlamp headlamp/headlamp -n kube-system

# Access via kubectl proxy
kubectl port-forward -n kube-system svc/headlamp 8080:80
# Visit: http://localhost:8080
```

**Option B: Desktop App**
```bash
brew install --cask headlamp
```

**Features:**
- Clean, modern interface
- Multi-cluster support
- Plugin system
- CRD support
- OIDC authentication
- Metrics integration
- Log streaming
- Terminal access

**Best for**: Users who want a modern, clean interface without the weight of Lens

---

### 5. Octant (VMware)

**Type**: Web UI
**License**: Open Source (Apache 2.0)
**Status**: ⚠️ Project archived (but still usable)
**Website**: https://octant.dev

A developer-centric web interface that runs locally and visualizes Kubernetes workloads.

**Installation:**
```bash
brew install octant
```

**Usage:**
```bash
# Launch Octant
octant

# Access at: http://localhost:7777
```

**Features:**
- Real-time updates
- Plugin system
- Resource relationship visualization
- Port-forwarding UI
- Log streaming
- YAML editor

**Note**: Project was archived by VMware in 2022, but still functional. Consider alternatives for long-term use.

**Best for**: Developers who want local web UI without cluster deployment

---

### 6. Kubeview

**Type**: Web UI
**License**: Open Source (MIT)
**Website**: https://github.com/benc-uk/kubeview

A lightweight visualization tool that shows cluster resources as an interactive diagram.

**Installation (In-Cluster):**
```bash
kubectl apply -f https://raw.githubusercontent.com/benc-uk/kubeview/main/deployments/kubernetes.yaml

# Port forward
kubectl port-forward -n kubeview svc/kubeview 8080:80
# Visit: http://localhost:8080
```

**Features:**
- Visual graph of resources
- Shows relationships between resources
- Interactive navigation
- Namespace filtering
- Lightweight and fast

**Best for**: Visualizing resource relationships, understanding application architecture

---

### 7. Portainer

**Type**: Web UI
**License**: Free (CE) / Paid (Enterprise)
**Website**: https://www.portainer.io

Container management platform with Kubernetes support.

**Installation:**
```bash
helm repo add portainer https://portainer.github.io/k8s/
helm repo update
helm install portainer portainer/portainer \
  --create-namespace \
  --namespace portainer \
  --set service.type=ClusterIP

# Port forward
kubectl port-forward -n portainer svc/portainer 9443:9443
# Visit: https://localhost:9443
```

**Features:**
- Multi-cluster management
- Team/user management
- Application templates
- Registry management
- Volume management
- GitOps integrations
- RBAC

**Best for**: Teams managing multiple clusters, users familiar with Docker

---

### 8. Grafana Kubernetes App

**Type**: Web UI (Grafana Plugin)
**License**: Open Source (Apache 2.0)
**Status**: ✅ Can use existing Grafana

Since you already have Grafana deployed, you can add the Kubernetes App plugin.

**Installation:**
```bash
# Install plugin in Grafana pod
kubectl exec -n monitoring <grafana-pod> -- grafana-cli plugins install grafana-kubernetes-app

# Restart Grafana
kubectl rollout restart -n monitoring deployment/grafana
```

**Access Grafana:**
```bash
# Your existing Grafana
open http://grafana.talos00
# Login: admin / prom-operator
```

**Features:**
- Integrated with Prometheus metrics
- Pre-built dashboards
- Cluster monitoring
- Resource usage graphs
- Alert integration

**Best for**: Existing Grafana users, metric-focused visualization

---

### 9. Kui

**Type**: Terminal/Electron Hybrid
**License**: Open Source (Apache 2.0)
**Website**: https://kui.tools

A hybrid CLI/GUI tool that enhances kubectl with visualizations.

**Installation:**
```bash
npm install -g @kui-shell/kubectl-kui

# Or download from GitHub releases
```

**Usage:**
```bash
# Launch Kui
kui

# Or use with kubectl
kubectl kui get pods
```

**Features:**
- CLI + GUI hybrid
- Live data tables
- YAML diff viewer
- Timeline views
- Built on Electron

**Best for**: Users who want CLI power with GUI convenience

---

## Monitoring & Observability UIs

### 10. Prometheus + Grafana (Already Installed)

**Status**: ✅ Already deployed in your cluster

You already have this stack installed for metrics and visualization.

**Access:**
```bash
# Prometheus
open http://prometheus.talos00

# Grafana
open http://grafana.talos00
# Login: admin / prom-operator

# Alertmanager
open http://alertmanager.talos00
```

**Best for**: Metrics, dashboards, alerting

---

### 11. Graylog (Already Installed)

**Status**: ✅ Already deployed in your cluster

For log aggregation and analysis.

**Access:**
```bash
open http://graylog.talos00
# Login: admin / admin
```

**Best for**: Log analysis, debugging, audit trails

---

## Specialized Tools

### 12. Kubecost

**Type**: Web UI
**License**: Free (limited) / Paid
**Focus**: Cost monitoring and optimization

**Installation:**
```bash
helm repo add kubecost https://kubecost.github.io/cost-analyzer/
helm install kubecost kubecost/cost-analyzer \
  --namespace kubecost \
  --create-namespace

kubectl port-forward -n kubecost svc/kubecost-cost-analyzer 9090:9090
```

**Best for**: Cost analysis, resource optimization

---

### 13. Goldilocks

**Type**: Dashboard
**Focus**: Resource recommendations (right-sizing)

**Installation:**
```bash
helm repo add fairwinds-stable https://charts.fairwinds.com/stable
helm install goldilocks fairwinds-stable/goldilocks \
  --namespace goldilocks \
  --create-namespace

kubectl port-forward -n goldilocks svc/goldilocks-dashboard 8080:80
```

**Best for**: Optimizing resource requests/limits

---

### 14. Kube-ops-view

**Type**: Read-only cluster view
**Focus**: Real-time cluster visualization

**Installation:**
```bash
kubectl apply -f https://raw.githubusercontent.com/hjacobs/kube-ops-view/main/deploy/deploy.yaml

kubectl port-forward -n kube-ops-view svc/kube-ops-view 8080:80
```

**Best for**: NOC displays, read-only dashboards, presentations

---

## Comparison Matrix

| Tool | Type | Installation | Complexity | Best For |
|------|------|--------------|------------|----------|
| **Kubernetes Dashboard** | Web | In-Cluster | Low | General purpose |
| **k9s** | Terminal | Local | Low | Daily operations, power users |
| **Lens** | Desktop | Local | Medium | Multi-cluster, developers |
| **Headlamp** | Web/Desktop | Both | Low | Modern UI, simplicity |
| **Kubeview** | Web | In-Cluster | Low | Visual relationships |
| **Portainer** | Web | In-Cluster | Medium | Teams, multi-cluster |
| **Grafana K8s** | Web | In-Cluster | Medium | Metrics integration |
| **Prometheus** | Web | In-Cluster | Low | Metrics, monitoring |
| **Graylog** | Web | In-Cluster | Medium | Logs, debugging |
| **Kubecost** | Web | In-Cluster | Medium | Cost analysis |

---

## Recommendations Based on Use Case

### For Daily Operations
1. **k9s** - Fast, keyboard-driven, terminal-based
2. **Lens** - If you prefer desktop apps

### For Beginners
1. **Kubernetes Dashboard** - Already installed
2. **Headlamp** - Modern, user-friendly

### For Multi-Cluster Management
1. **Lens**
2. **Portainer**

### For Visualization & Architecture
1. **Kubeview** - Resource relationships
2. **Kube-ops-view** - Real-time cluster view

### For Monitoring & Debugging
1. **Grafana** - Already installed, great dashboards
2. **k9s** - Built-in log viewer and shell access
3. **Graylog** - Already installed, log analysis

### For Cost Optimization
1. **Kubecost** - Cost analysis
2. **Goldilocks** - Resource right-sizing

---

## Quick Setup for k9s (Recommended)

Since k9s is lightweight and powerful, here's a quick setup:

```bash
# Install
brew install k9s

# Add to your shell config (~/.zshrc or ~/.bashrc)
alias k='kubectl'
alias kns='kubectl config set-context --current --namespace'
alias kctx='kubectl config use-context'

# Launch k9s
k9s

# Common k9s commands once inside:
# :pods        - View pods
# :deploy      - View deployments
# :svc         - View services
# :ns          - View/switch namespaces
# :ctx         - View/switch contexts
# /            - Filter
# l            - View logs
# s            - Shell
# d            - Describe
# y            - View YAML
```

---

## Quick Setup for Headlamp (Modern Web UI)

For a modern web UI that doesn't require desktop app installation:

```bash
# Install in-cluster
helm repo add headlamp https://headlamp-k8s.github.io/headlamp/
helm install headlamp headlamp/headlamp \
  --namespace kube-system \
  --set service.type=ClusterIP

# Port forward
kubectl port-forward -n kube-system svc/headlamp 8080:80

# Access at: http://localhost:8080
```

---

## Summary

**Already Have:**
- ✅ Kubernetes Dashboard
- ✅ Grafana (with Prometheus)
- ✅ Graylog
- ✅ k9s (can install via existing Brewfile)

**Recommended to Add:**
- **k9s** - For terminal-based power users (already in Brewfile)
- **Headlamp** - For modern web UI
- **Lens** - If you want a desktop IDE experience

**For Specific Needs:**
- **Kubeview** - Visual resource relationships
- **Kubecost** - Cost monitoring
- **Portainer** - Team management, multi-cluster

The best tool depends on your workflow:
- **Terminal user?** → k9s
- **Desktop app?** → Lens
- **Web UI?** → Headlamp or existing Kubernetes Dashboard
- **Visual learner?** → Kubeview
- **Cost conscious?** → Kubecost
