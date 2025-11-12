# Traefik v3 Ingress Controller - Helm Setup

## Overview

Traefik v3.5.3 is deployed via **Helm** with full CRD support, listening on ports 80 and 443 on the node.

## Quick Setup

```bash
# Install everything
./scripts/setup-traefik.sh

# Or manually:
helm install traefik traefik/traefik \
  --namespace traefik \
  --values kubernetes/traefik-values.yaml \
  --kubeconfig ./.output/kubeconfig
```

## Deployed Services

### 1. Traefik Dashboard
Traefik's own dashboard for monitoring routes and services.

**Access:** `http://traefik.talos00`

### 2. whoami Service
Test service that echoes request information.

**Access:**
- Via hostname: `http://whoami.talos00`
- Via path: `http://192.168.1.54/whoami`

### 3. Kubernetes Dashboard
K8s admin dashboard via Traefik.

**Access:**
- Via hostname: `http://dashboard.talos00`
- Login token: `task dashboard-token`

## DNS/Hosts Configuration

Add to `/etc/hosts` on your Mac:

```bash
192.168.1.54  traefik.talos00 whoami.talos00 dashboard.talos00
```

Or configure your router/DNS to point `*.talos00` to `192.168.1.54`.

## Traefik CRDs & Features

### Available CRDs

Traefik Helm chart installs all CRDs automatically:

- **IngressRoute** - HTTP routing (replaces Ingress)
- **IngressRouteTCP** - TCP routing
- **IngressRouteUDP** - UDP routing
- **Middleware** - Request/response modification
- **TraefikService** - Advanced load balancing
- **TLSOption** - TLS configuration
- **TLSStore** - TLS certificate storage
- **ServersTransport** - Backend server settings

List all installed CRDs:
```bash
kubectl get crd | grep traefik
```

### IngressRoute Example

Instead of traditional Kubernetes Ingress, Traefik uses IngressRoute:

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: my-app
  namespace: default
spec:
  entryPoints:
    - web
  routes:
    - match: Host(`myapp.talos00`)
      kind: Rule
      services:
        - name: my-app
          port: 80
```

### Middleware Example

Strip path prefixes:

```yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: strip-prefix
  namespace: default
spec:
  stripPrefix:
    prefixes:
      - /api
```

Then use in IngressRoute:

```yaml
routes:
  - match: PathPrefix(`/api`)
    middlewares:
      - name: strip-prefix
    services:
      - name: api-service
        port: 8080
```

## Architecture

```
Internet/LAN (192.168.1.54)
     |
     v
[Traefik DaemonSet] ← hostPort: 80, 443
     |
     +--→ traefik.talos00 → Traefik Dashboard
     |
     +--→ whoami.talos00 → whoami Service
     |
     +--→ dashboard.talos00 → kubernetes-dashboard (HTTPS backend)
     |
     +--→ /whoami → whoami Service (with path strip)
```

## Configuration Files

- `kubernetes/traefik-values.yaml` - Helm values
- `kubernetes/whoami-ingressroute.yaml` - whoami + IngressRoutes
- `kubernetes/dashboard-ingressroute.yaml` - Dashboard IngressRoute
- `scripts/setup-traefik.sh` - Automated setup script

## Helm Management

### Install/Upgrade
```bash
helm upgrade --install traefik traefik/traefik \
  --namespace traefik \
  --values kubernetes/traefik-values.yaml \
  --kubeconfig ./.output/kubeconfig
```

### View Current Values
```bash
helm get values traefik -n traefik --kubeconfig ./.output/kubeconfig
```

### Uninstall
```bash
helm uninstall traefik -n traefik --kubeconfig ./.output/kubeconfig
```

## Adding New Services

### Simple HTTP Service

1. Deploy your app
2. Create IngressRoute:

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: my-app
  namespace: default
spec:
  entryPoints:
    - web
  routes:
    - match: Host(`myapp.talos00`)
      kind: Rule
      services:
        - name: my-app-service
          port: 80
```

### With Middleware (Auth, Rate Limit, etc.)

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: my-app
spec:
  entryPoints:
    - web
  routes:
    - match: Host(`myapp.talos00`)
      middlewares:
        - name: rate-limit
        - name: auth
      services:
        - name: my-app-service
          port: 80
```

## Monitoring

### Traefik Dashboard
Access at `http://traefik.lab` to see:
- Active routes
- Services status
- Middleware chains
- Real-time metrics

### Prometheus Metrics
Traefik exposes Prometheus metrics on the `metrics` entrypoint.

```bash
# Get metrics
curl http://192.168.1.54:9000/metrics
```

## Troubleshooting

### Check Traefik Status
```bash
kubectl --kubeconfig ./.output/kubeconfig get pods -n traefik
kubectl --kubeconfig ./.output/kubeconfig logs -n traefik -l app.kubernetes.io/name=traefik
```

### List IngressRoutes
```bash
kubectl --kubeconfig ./.output/kubeconfig get ingressroute -A
```

### Describe IngressRoute
```bash
kubectl --kubeconfig ./.output/kubeconfig describe ingressroute <name> -n <namespace>
```

### Check Middleware
```bash
kubectl --kubeconfig ./.output/kubeconfig get middleware -A
```

### Port 80/443 Not Working
- Ensure Traefik pod is running: `kubectl get pods -n traefik`
- Check namespace has privileged security: `kubectl get ns traefik -o yaml | grep pod-security`
- Verify hostPort is bound: `kubectl describe pod -n traefik -l app.kubernetes.io/name=traefik`

## Security Notes

- `traefik` namespace uses **privileged** pod security for hostPort binding
- Traefik dashboard is accessible without auth (homelab setup)
- Backend TLS verification is disabled for self-signed certs
- For production: Enable authentication, HTTPS, and proper TLS

## Useful Resources

- [Traefik Kubernetes CRD Docs](https://doc.traefik.io/traefik/routing/providers/kubernetes-crd/)
- [Traefik Middleware Reference](https://doc.traefik.io/traefik/middlewares/overview/)
- [Helm Chart Values](https://github.com/traefik/traefik-helm-chart/blob/master/traefik/values.yaml)

## Next Steps

1. **Enable HTTPS:**
   - Configure Let's Encrypt or self-signed certs
   - Update IngressRoutes to use `websecure` entrypoint

2. **Add Authentication:**
   - Use BasicAuth or ForwardAuth middleware
   - Integrate with OAuth2 providers

3. **Advanced Routing:**
   - Path-based routing
   - Header-based routing
   - Weighted load balancing

4. **Monitoring:**
   - Deploy Prometheus + Grafana
   - Import Traefik dashboards
