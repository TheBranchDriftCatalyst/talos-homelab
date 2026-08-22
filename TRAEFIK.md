# Traefik Ingress Controller

## TL;DR

Traefik is our cluster's HTTP router and ingress controller, managing all external access to services. Deployed as a DaemonSet (one pod per node) via a Flux HelmRelease, binding hostPorts 80/443 on every node and additionally fronted by a Cilium LB-IPAM VIP. TLS is active: a default `TLSStore` serves wildcard certs by SNI, so `websecure` routes need only `tls: {}`. Internal services use the `*.talos00` hostname pattern; public services use `*.knowledgedump.space`.

**Quick Facts:**

- Dashboard: http://traefik.talos00 (no auth — `--api.insecure=true`, homelab only)
- ~190 IngressRoutes + 4 IngressRouteTCP across 32 namespaces
- EntryPoints: web (80), websecure (443), traefik (9000), metrics (9100), httpproxy (8080), socks (1080), bolt (7687)
- Chart `traefik/traefik` v41.x (pinned `>=41.0.0 <42.0.0`), image `traefik:v3.7.x`
- Security: TLS terminated on `websecure` (wildcard certs via cert-manager); CrowdSec bouncer bound globally to both `web` and `websecure`
- Status: Healthy, 5 pods in DaemonSet (talos00, talos01, talos02-gpu, talos03, talos06)
- `svc/traefik` carries LoadBalancer VIP **192.168.1.251** (Cilium LB-IPAM + L2 announcement, TALOS-sa0n)

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
# NOTE: svc/traefik does NOT expose 9000 — use svc/traefik-internal
kubectl port-forward -n traefik svc/traefik-internal 9000:9000
# Access: http://localhost:9000/dashboard/

# Port-forward the metrics endpoint (9100 has no hostPort)
kubectl port-forward -n traefik svc/traefik-metrics 9100:9100
```

### Common Service URLs

Many of these also have a `websecure` twin, so `https://<host>` works too (wildcard cert
from the default `TLSStore`). Hosts under `*.priv.talos00` are the LAN-only / SSO hierarchy.

```bash
# Infrastructure
http://argocd.talos00           # ArgoCD GitOps controller
http://grafana.talos00          # Grafana dashboards
http://mimir.talos00            # Mimir (metrics — replaced Prometheus/kube-prometheus-stack)
http://loki.talos00             # Loki (logs)
http://hyperdx.talos00          # ClickStack / HyperDX (logs + traces — replaced Graylog)
http://registry.talos00         # Zot OCI registry (replaced Nexus)
http://hubble.talos00           # Cilium observability
http://crowdsec.talos00         # CrowdSec IPS

# Testing
http://whoami.talos00           # Whoami test service
https://whoami-tls.talos00      # Whoami over TLS
https://whoami-auth.talos00     # Whoami behind Authentik forward-auth
http://homepage.talos00         # Homepage dashboard (also apps/arrs/data/home/infra/llm/obs.homepage.talos00)

# LLM Stack
http://openwebui.talos00        # Open WebUI
http://ollama.talos00           # Ollama API
http://sillytavern.talos00      # SillyTavern chat

# Infrastructure Control
http://headlamp.priv.talos00    # Kubernetes dashboard (LAN-only hierarchy)
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
  annotations:
    # Optional — only the genuinely-unique Homepage keys. siteMonitor / href /
    # widget.url are DERIVED from this spec by the Kyverno ClusterPolicy
    # `homepage-annotation-derivation` (add-if-absent; hand-set values win).
    gethomepage.dev/enabled: 'true'
    gethomepage.dev/name: 'My App'
    gethomepage.dev/group: 'Infrastructure'
spec:
  entryPoints:
    - websecure # or 'web' for plain HTTP
  routes:
    - match: Host(`my-app.talos00`)
      kind: Rule
      services:
        - name: my-app-service
          port: 8080
  # tls: {} is NOT hand-written — the Kyverno ClusterPolicy
  # `ingressroute-tls-default` adds it to every websecure IngressRoute, which
  # makes Traefik terminate with the default TLSStore wildcard cert. Only set
  # `tls` yourself if you need a non-default secretName/options/certResolver.
```

Note: an IngressRoute must list **exactly one** of `web` or `websecure` — the whole fleet
follows that rule and the Kyverno policies use it as a discriminator. If you need both, ship
two routes (see `infrastructure/base/registry/zot/ingressroute.yaml`, which pairs an HTTP
route with the `redirect-https` middleware against an HTTPS route).

### Apply IngressRoute

This repo is **Flux-managed**. Commit the manifest into the owning
`infrastructure/base/<component>/` (or `applications/`) kustomization — a bare
`kubectl apply` gets reconciled away.

```bash
# Validate locally first
kubectl apply -f my-app-ingressroute.yaml --dry-run=client

# Commit + push, then reconcile (fetch the source, or you verify stale state)
flux reconcile kustomization <ks-name> --with-source

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

### Hostname Patterns

Four hierarchies are in use:

| Pattern                  | Purpose                                       | Cert                            |
| ------------------------ | --------------------------------------------- | ------------------------------- |
| `*.talos00`              | LAN-internal services                         | `talos00-wildcard-tls` (homelab-CA) |
| `*.priv.talos00`         | LAN-only / SSO cookie domain                  | `priv-talos00-wildcard-tls` (homelab-CA) |
| `*.homepage.talos00`     | Multi-instance Homepage boards (2-label hosts) | `homepage-talos00-wildcard-tls` (homelab-CA) |
| `*.knowledgedump.space`  | Publicly reachable services                   | `knowledgedump-wildcard-tls` (Let's Encrypt) |

All four are registered in the default `TLSStore`
(`infrastructure/base/traefik/tlsstore.yaml`) and served by SNI, so an IngressRoute never
needs an explicit `secretName`.

### DNS

**Pi-hole is the resolver** for the LAN and already serves both wildcards, so `/etc/hosts`
entries are only needed for clients that do not use it. From
`infrastructure/base/pihole/statefulset.yaml`:

```text
address=/talos00/192.168.1.54            # wildcard *.talos00 -> Traefik
address=/pihole.talos00/192.168.1.240    # more-specific: Pi-hole VIP directly
address=/knowledgedump.space/192.168.1.54 # split-horizon *.knowledgedump.space -> Traefik
```

> **Note:** `svc/traefik` also holds a dedicated LoadBalancer VIP **192.168.1.251** (Cilium
> LB-IPAM + L2/ARP announcement) which fails over automatically between nodes. The Pi-hole
> wildcards still point at the talos00 node IP (`192.168.1.54`); repointing them at the VIP
> is the pending half of TALOS-sa0n. Until then, LAN ingress depends on the talos00 node.

### /etc/hosts Fallback

For a machine not using Pi-hole as its resolver:

```bash
# Traefik ingress target (node IP today; 192.168.1.251 once the VIP cutover lands)
192.168.1.54  traefik.talos00 argocd.talos00 grafana.talos00 mimir.talos00 \
              loki.talos00 hyperdx.talos00 registry.talos00 crowdsec.talos00 \
              whoami.talos00 homepage.talos00 headlamp.priv.talos00 \
              openwebui.talos00 ollama.talos00 catalyst.talos00 \
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

Defined in `infrastructure/base/traefik/helmrelease.yaml`.

| EntryPoint  | Port | hostPort | Protocol  | Purpose                                      |
| ----------- | ---- | -------- | --------- | -------------------------------------------- |
| `web`       | 80   | 80       | HTTP      | Primary HTTP traffic                         |
| `websecure` | 443  | 443      | HTTPS     | TLS termination (active — 79 live routes)    |
| `traefik`   | 9000 | —        | HTTP      | Dashboard / API (cluster-internal only)      |
| `metrics`   | 9100 | —        | HTTP      | Prometheus metrics (cluster-internal only)   |
| `httpproxy` | 8080 | 8080     | TCP       | VPN gateway HTTP proxy (gluetun)             |
| `socks`     | 1080 | 1080     | TCP       | VPN gateway SOCKS proxy (gluetun)            |
| `bolt`      | 7687 | 7687     | TCP       | Neo4j Bolt for catalyst-data (IngressRouteTCP) |

`web` and `websecure` both trust Cloudflare + pod CIDRs via `forwardedHeaders.trustedIPs`
so `ClientHost` is the real visitor IP (feeds CrowdSec), and both carry the
`traefik-bouncer@kubernetescrd` middleware globally via `additionalArguments`.

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

# Access via port-forward (9000 lives on svc/traefik-internal, not svc/traefik)
kubectl port-forward -n traefik svc/traefik-internal 9000:9000
open http://localhost:9000/dashboard/
```

### 3. Docker Registry Push Fails (registry.talos00)

> **RESOLVED / obsolete.** The old workaround was `kubectl port-forward -n registry
> svc/nexus-docker 5000:5000`. **Nexus has been removed** — the registry is now **Zot**
> (`infrastructure/base/registry/zot/`, `svc/zot:5000`), and the 404-on-push was root-caused
> and fixed: Docker and containerd both probe `https://` first and never fall back, so a
> `websecure` route (`zot-talos00-tls`) was added alongside the `web` one. Push over
> `registry.talos00` works directly. (TALOS-6vf / TALOS-2je)

**Symptoms:** `docker push registry.talos00/image:tag` fails

**Check:**

```bash
# Both routes must exist — the https probe 404s without zot-talos00-tls
kubectl get ingressroute -n registry
# expect: zot (web), zot-talos00-tls (websecure), zot-public, zot-public-http

# Registry health
kubectl get pods -n registry
```

**Docker daemon config** — `registry.talos00` uses a homelab-CA cert whose SAN does not
cover it, so LAN daemons must list it as insecure:

```json
{ "insecure-registries": ["registry.talos00"] }
```

For the OIDC/SSO web UI use the public HTTPS host `https://registry.knowledgedump.space` —
the OAuth state cookie is `SameSite=None; Secure` and is dropped over plain HTTP.

### 4. Metrics Missing

**Symptoms:** Traefik metrics not appearing in Grafana

**Note:** there is no kube-prometheus-stack Prometheus and no Traefik ServiceMonitor —
`metrics.prometheus.serviceMonitor.enabled: false` in the HelmRelease. **Alloy** scrapes
Traefik directly (`prometheus.scrape "traefik"`, 30s, in
`infrastructure/base/monitoring/v2-otel/alloy/helmrelease.yaml`) and remote-writes to
**Mimir**.

**Solutions:**

```bash
# Verify metrics endpoint (9100 has NO hostPort — port-forward, don't curl the host)
kubectl port-forward -n traefik svc/traefik-metrics 9100:9100
curl -s http://localhost:9100/metrics | head

# Check Alloy is healthy and its traefik scrape target is up
kubectl get pods -n monitoring -l app.kubernetes.io/name=alloy
kubectl port-forward -n monitoring svc/alloy 12345:12345
open http://localhost:12345   # Alloy UI -> Components -> prometheus.scrape "traefik"

# Query Mimir via Grafana
open http://grafana.talos00
# Explore -> Mimir -> up{job="traefik"}
```

### 5. IngressRoute Works on One Node, Not Others

**Symptoms:** Service accessible from control plane but not workers

**Cause:** Traefik runs as a DaemonSet — it should be on all 5 nodes (talos00, talos01,
talos02-gpu, talos03, talos06). talos00 carries the control-plane `NoSchedule` taint, which
the HelmRelease tolerates explicitly.

**Solutions:**

```bash
# Check Traefik pods on all nodes (expect 5/5)
kubectl get pods -n traefik -o wide

# Verify DaemonSet status
kubectl get daemonset -n traefik

# Check node taints (might prevent scheduling)
kubectl describe nodes | grep Taints
```

**Note:** rollouts use `maxSurge: 0` / `maxUnavailable: 1` deliberately — the chart default
`maxSurge: 1` schedules the new pod alongside the old one on the same node and deadlocks on
the hostPort 80/443 collision.

**Prefer the VIP:** hitting an individual node IP is a single point of failure — that is
exactly the failure TALOS-sa0n was opened for (a talos00 reboot left its Traefik pod with no
routes, 404ing every `.talos00` host while talos01/talos06 served 200). Use
`192.168.1.251`.

## Deep Dive

The **manifests are the source of truth** — they carry extensive inline rationale:

| File                                                              | Contains                                                                     |
| ----------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `infrastructure/base/traefik/helmrelease.yaml`                     | Chart pin, all entrypoints, hostPort/rollout strategy, CrowdSec + Yaegi plugins |
| `infrastructure/base/traefik/tlsstore.yaml`                        | Default TLSStore + the four wildcard certs served by SNI                      |
| `infrastructure/base/traefik/middlewares.yaml`                     | `redirect-https`, `security-headers`, `lan-only`, `bot-wrangler`              |
| `infrastructure/base/traefik/service-internal.yaml`                | `svc/traefik-internal` (dashboard/API on 9000)                                |
| `infrastructure/base/cilium/lb-ipam.yaml`                          | The 192.168.1.251 VIP pool + L2 announcement policy                           |
| `infrastructure/base/kyverno-policies/ingressroute-tls-default.yaml` | Auto-`tls: {}` on websecure routes (TALOS-a38d)                             |
| `infrastructure/base/kyverno-policies/homepage-annotation-derivation.yaml` | Derived `siteMonitor` / `href` / `widget.url`                        |
| `clusters/catalyst-cluster/traefik.yaml`                           | Flux Kustomization + `${DOMAIN}` postBuild substitution                       |

Traefik plugins are Yaegi-loaded **from GitHub at pod startup** — a rollout needs egress to
github.com. Enabled: `rewritebody` + `rewriteHeaders` (analytics injection, TALOS-4gg),
`bouncer` (CrowdSec IPS, TALOS-pbn), `botWrangler` (LLM-scraper tarpit, TALOS-mko).

> **⚠️ Stale:** [infrastructure/base/traefik/STATUS.md](infrastructure/base/traefik/STATUS.md)
> (719 lines) was last updated 2025-11-11 and has **not** been kept current. It still
> describes chart 37.x / Traefik v3.5.x, "HTTP only, no TLS", Nexus as the registry,
> Prometheus + Graylog, "12+ IngressRoutes", and a manual-Helm deployment method — all of
> which are wrong today. Treat it as historical until it is rewritten or retired.

### Additional Resources

- [Traefik Official Documentation](https://doc.traefik.io/traefik/)
- [IngressRoute CRD Reference](https://doc.traefik.io/traefik/routing/providers/kubernetes-crd/)
- [Middleware Reference](https://doc.traefik.io/traefik/middlewares/overview/)
- [Dual GitOps Architecture](docs/02-architecture/gitops-responsibilities.md)

---

## Related Issues

<!-- Beads tracking for this documentation domain -->

- [CILIUM-7w6] - Initial creation of root-level TRAEFIK.md (pre-`TALOS-` prefix rename)
- [TALOS-sa0n] - Traefik ingress VIP via Cilium LB-IPAM (open — DNS cutover pending)
- [TALOS-pbn] - CrowdSec IPS for Traefik ingress (bouncer + AppSec + Console)
- [TALOS-h8l0] - HTTP→HTTPS: entrypoint redirect OR Kyverno generate twin (retire 12 dup routes)
- [TALOS-zadf.19] - Traefik v3.6.2 → v3.7.10 / chart 41.x (closed)
- [TALOS-a38d] - DRY-up audit: Kyverno `ingressroute-tls-default` (auto `tls: {}`)
- [TALOS-6vf] - Replace Nexus with Zot (registry.talos00 routing)
- [TALOS-mko] - Bot Wrangler + iocaine tarpit middleware (closed)

**Last Updated:** 2026-08-22
**Status:** Active - TLS terminated on `websecure`; CrowdSec bouncer bound globally
**Owner:** Infrastructure Team
