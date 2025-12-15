# Traefik Ingress Controller

## TL;DR

Traefik is our cluster's HTTP router and ingress controller, managing all external access to services. Currently deployed as a DaemonSet with HTTP-only access (no TLS). All services are accessible via `*.talos00` hostname pattern.

**Quick Facts:**

- Dashboard: http://traefik.talos00
- 45+ IngressRoutes active across 15+ namespaces
- EntryPoints: web (80), websecure (443), traefik (9000), metrics (9100)
- Security: HTTP only - suitable for isolated homelab networks
- Status: Healthy, 2 pods running in DaemonSet

## Quick Reference

### Common Commands

```bash
# Access dashboard
open http://traefik.talos00

# List all IngressRoutes
kubectl get ingressroute -A

# Check Traefik pod status
kubectl get pods -n traefik

# View logs
kubectl logs -n traefik -l app.kubernetes.io/name=traefik

# Port-forward dashboard (alternative access)
kubectl port-forward -n traefik svc/traefik 9000:9000
# Access: http://localhost:9000/dashboard/
```

### Common Service URLs

```bash
# Infrastructure
http://argocd.talos00           # ArgoCD GitOps controller
http://grafana.talos00          # Grafana dashboards
http://prometheus.talos00       # Prometheus metrics
http://graylog.talos00          # Log management
http://registry.talos00         # Docker registry (read-only via Traefik)
http://hubble.talos00           # Cilium observability

# Testing
http://whoami.talos00           # Whoami test service
http://homepage.talos00         # Homepage dashboard

# LLM Stack
http://open-webui.talos00       # Open WebUI
http://ollama.talos00           # Ollama API
http://sillytavern.talos00      # SillyTavern chat

# Infrastructure Control
http://headlamp.talos00         # Kubernetes dashboard
http://goldilocks.talos00       # Resource recommendations
http://kube-ops-view.talos00    # Cluster operations view
```

## Adding a New Service

### Basic IngressRoute Template

```yaml
---
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: my-app
  namespace: my-namespace
spec:
  entryPoints:
    - web # HTTP (use 'websecure' when TLS is enabled)
  routes:
    - match: Host(`my-app.talos00`)
      kind: Rule
      services:
        - name: my-app-service
          port: 8080
```

### Apply IngressRoute

```bash
# Apply manifest
kubectl apply -f my-app-ingressroute.yaml

# Verify creation
kubectl get ingressroute -n my-namespace

# Test access
curl -I http://my-app.talos00

# Check Traefik dashboard for route
open http://traefik.talos00
# Navigate to: HTTP -> Routers
```

### IngressRoute with Path Prefix

```yaml
---
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: my-app-api
  namespace: my-namespace
spec:
  entryPoints:
    - web
  routes:
    - match: Host(`my-app.talos00`) && PathPrefix(`/api`)
      kind: Rule
      services:
        - name: my-app-api-service
          port: 8080
```

## Hostnames & DNS

### Hostname Pattern

All cluster services use the **`*.talos00`** hostname pattern:

- Pattern: `<service-name>.talos00`
- Examples: `grafana.talos00`, `argocd.talos00`, `ollama.talos00`

### /etc/hosts Configuration

Since this is a homelab setup without external DNS, add entries to `/etc/hosts`:

```bash
# Control plane IP (update to match your cluster)
192.168.1.54  argocd.talos00 grafana.talos00 prometheus.talos00 \
              alertmanager.talos00 graylog.talos00 registry.talos00 \
              whoami.talos00 homepage.talos00 headlamp.talos00 \
              open-webui.talos00 ollama.talos00 catalyst-ui.talos00 \
              hubble.talos00 goldilocks.talos00 kube-ops-view.talos00
```

**Tip:** Use wildcard DNS via dnsmasq for cleaner management:

```bash
# Install dnsmasq (macOS)
brew install dnsmasq

# Configure wildcard
echo "address=/.talos00/192.168.1.54" >> /opt/homebrew/etc/dnsmasq.conf

# Start service
sudo brew services start dnsmasq
```

### EntryPoints

| EntryPoint  | Port | Protocol | Purpose              |
| ----------- | ---- | -------- | -------------------- |
| `web`       | 80   | HTTP     | Primary HTTP traffic |
| `websecure` | 443  | HTTPS    | TLS (not active yet) |
| `traefik`   | 9000 | HTTP     | Dashboard            |
| `metrics`   | 9100 | HTTP     | Prometheus metrics   |

## Troubleshooting

### 1. Service Returns 404

**Symptoms:** `curl http://my-app.talos00` returns 404 Not Found

**Causes & Solutions:**

```bash
# Check if IngressRoute exists
kubectl get ingressroute -n my-namespace

# Verify match rule
kubectl get ingressroute my-app -n my-namespace -o yaml

# Check if backend service exists
kubectl get svc -n my-namespace

# Test service directly (bypass Traefik)
kubectl port-forward -n my-namespace svc/my-app-service 8080:8080
curl http://localhost:8080

# Check Traefik logs for routing errors
kubectl logs -n traefik -l app.kubernetes.io/name=traefik | grep -i "my-app"

# Verify in dashboard
open http://traefik.talos00
# Navigate: HTTP -> Routers -> Search for "my-app"
```

### 2. Dashboard Not Accessible

**Symptoms:** Cannot access http://traefik.talos00

**Solutions:**

```bash
# Check Traefik pod status
kubectl get pods -n traefik

# Check pod logs
kubectl logs -n traefik -l app.kubernetes.io/name=traefik

# Verify /etc/hosts entry
grep "traefik.talos00" /etc/hosts

# Access via port-forward
kubectl port-forward -n traefik svc/traefik 9000:9000
open http://localhost:9000/dashboard/
```

### 3. Docker Registry Push Fails (registry.talos00)

**Symptoms:** `docker push registry.talos00/image:tag` fails with 404 on blob upload

**Workaround:**

```bash
# Use kubectl port-forward instead of IngressRoute
kubectl port-forward -n registry svc/nexus-docker 5000:5000 &

# Push to localhost
docker tag my-image:latest localhost:5000/my-image:latest
docker push localhost:5000/my-image:latest
```

**Note:** This is a known issue with HTTP blob uploads via Traefik. See [infrastructure/base/traefik/STATUS.md](infrastructure/base/traefik/STATUS.md#2-docker-registry-http-push-issues) for details.

### 4. Metrics Not in Prometheus

**Symptoms:** Traefik metrics not appearing in Prometheus

**Solutions:**

```bash
# Verify metrics endpoint
curl http://traefik.talos00:9100/metrics

# Check ServiceMonitor exists
kubectl get servicemonitor -n monitoring | grep traefik

# Verify Prometheus targets
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090
open http://localhost:9090/targets
# Search for "traefik"
```

### 5. IngressRoute Works on One Node, Not Others

**Symptoms:** Service accessible from control plane but not workers

**Cause:** Traefik runs as DaemonSet - should be on all nodes

**Solutions:**

```bash
# Check Traefik pods on all nodes
kubectl get pods -n traefik -o wide

# Verify DaemonSet status
kubectl get daemonset -n traefik

# Check node taints (might prevent scheduling)
kubectl describe nodes | grep Taints
```

## Deep Dive

For comprehensive documentation including:

- Full deployment configuration and Helm values
- Security considerations and hardening recommendations
- Middleware examples (auth, rate limiting, redirects)
- Performance tuning and load testing
- Maintenance procedures and update workflow
- Integration with cert-manager for TLS
- Advanced routing patterns and TCP/UDP services

→ See **[infrastructure/base/traefik/STATUS.md](infrastructure/base/traefik/STATUS.md)** (720 lines of detailed documentation)

### Additional Resources

- [Traefik Official Documentation](https://doc.traefik.io/traefik/)
- [IngressRoute CRD Reference](https://doc.traefik.io/traefik/routing/providers/kubernetes-crd/)
- [Middleware Reference](https://doc.traefik.io/traefik/middlewares/overview/)
- [Dual GitOps Architecture](docs/02-architecture/gitops-responsibilities.md)

---

## Related Issues

<!-- Beads tracking for this documentation domain -->

- [CILIUM-7w6] - Initial creation of root-level TRAEFIK.md

**Last Updated:** 2025-12-06
**Status:** Active - HTTP Only (TLS deployment pending)
**Owner:** Infrastructure Team
