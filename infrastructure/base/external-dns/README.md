# External-DNS for Cloudflare

Automatically creates DNS records in Cloudflare from Kubernetes Ingress/IngressRoute resources.

## How It Works

External-DNS watches for Ingress resources with specific annotations and creates corresponding DNS records in Cloudflare.

```
Annotated IngressRoute → External-DNS → Cloudflare CNAME
```

Works alongside the existing `cloudflare-ddns` deployment:
- **cloudflare-ddns**: Updates root A record with dynamic public IP
- **external-dns**: Creates CNAMEs pointing to root domain

## Usage

Add annotations to any IngressRoute that needs a public DNS record:

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: my-service
  annotations:
    # Required: hostname to create in Cloudflare
    external-dns.alpha.kubernetes.io/hostname: myservice.knowledgedump.space
    # Required: CNAME target (use root domain)
    external-dns.alpha.kubernetes.io/target: knowledgedump.space
    # Optional: Enable Cloudflare proxy (default: false/DNS-only)
    external-dns.alpha.kubernetes.io/cloudflare-proxied: "true"
spec:
  routes:
    - match: Host(`myservice.knowledgedump.space`)
      # ...
```

## Annotations Reference

| Annotation | Required | Default | Description |
|------------|----------|---------|-------------|
| `external-dns.alpha.kubernetes.io/hostname` | Yes | - | DNS hostname to create |
| `external-dns.alpha.kubernetes.io/target` | Yes | - | CNAME target (use `knowledgedump.space`) |
| `external-dns.alpha.kubernetes.io/cloudflare-proxied` | No | `false` | Enable Cloudflare proxy (orange cloud) |
| `external-dns.alpha.kubernetes.io/ttl` | No | `auto` | TTL for the record (1 = auto) |

## Cloudflare Proxy Decision Guide

| Use Case | Proxy? | Why |
|----------|--------|-----|
| Public web apps | Yes | CDN caching, DDoS protection |
| APIs with auth | Yes | DDoS protection, Traefik auth still works |
| WebSockets | Test | May add latency |
| Non-HTTP services | No | Cloudflare only proxies HTTP(S) |

## Verification

Check External-DNS logs:
```bash
kubectl logs -n external-dns deploy/external-dns -f
```

Verify DNS record:
```bash
dig myservice.knowledgedump.space
```

Check Cloudflare dashboard for the CNAME record.

## Configuration

- **Domain filter**: Only manages `knowledgedump.space`
- **Policy**: `sync` (full reconciliation - deletes records when Ingress removed)
- **Owner ID**: `talos-homelab` (prevents conflicts with other sources)
- **Sync interval**: 1 minute

## Secrets

Uses the same Cloudflare API token as cert-manager and cloudflare-ddns, pulled from 1Password via ExternalSecret.
