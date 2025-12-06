# Dual Ingress Architecture

> **Epic**: CILIUM-2cf | **Status**: Planning

Add a second entry point into the hybrid cluster via AWS Traefik, enabling direct access to AWS-hosted services without routing through the Nebula mesh.

## Architecture

```
                          INTERNET
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     │                     ▼
┌───────────────┐   ┌─────────────────┐   ┌─────────────────┐
│   HOMELAB     │   │  Nebula Mesh    │   │      AWS        │
│ 192.168.1.54  │   │   (unchanged)   │   │   Elastic IP    │
├───────────────┤   │  10.42.0.0/16   │   ├─────────────────┤
│ Traefik #1    │◄──┼─────────────────┼──►│ Traefik #2      │
│ *.talos00     │   │                 │   │ *.aws.domain    │
└───────────────┘   └─────────────────┘   └─────────────────┘
```

## Traffic Patterns

| Pattern | Flow |
|---------|------|
| **AWS Direct** | User → AWS EIP → Traefik → k3s Pod |
| **Homelab via Liqo** | User → Homelab → Traefik → Liqo → Nebula → AWS Pod |
| **AWS to Homelab** | User → AWS EIP → Traefik → ExternalName → Nebula → Homelab Pod |

## Stack

- **Ingress**: Traefik (matches homelab)
- **DNS**: Cloudflare (proxied)
- **TLS**: Let's Encrypt via cert-manager (DNS-01 challenge)

## Tasks

| ID | Task | Depends On |
|----|------|------------|
| CILIUM-lug | Update AWS security group (ports 80/443) | - |
| CILIUM-3q6 | Deploy Traefik on AWS k3s | CILIUM-lug |
| CILIUM-30v | Configure Cloudflare DNS + proxy | - |
| CILIUM-7cp | Install cert-manager + Let's Encrypt | CILIUM-3q6, CILIUM-30v |
| CILIUM-ctp | Deploy whoami test service | CILIUM-7cp |
| CILIUM-e28 | Add Ollama IngressRoute | CILIUM-ctp |
| CILIUM-0hk | Update lighthouse-userdata.sh | CILIUM-ctp |

## Files

| File | Description |
|------|-------------|
| `scripts/hybrid-llm/update-sg-for-ingress.sh` | Add 80/443 to existing SG |
| `scripts/hybrid-llm/provision-lighthouse.sh` | Add 80/443 rules (new instances) |
| `infrastructure/overlays/aws-gpu/traefik/values.yaml` | AWS Traefik Helm values |
| `infrastructure/overlays/aws-gpu/cert-manager/` | ClusterIssuer + Certificate |
| `infrastructure/overlays/aws-gpu/test-services/whoami.yaml` | Test deployment |
| `infrastructure/overlays/aws-gpu/catalyst-llm/ingressroute.yaml` | Ollama IngressRoute |

## Quick Start

```bash
# 1. Security group
./scripts/hybrid-llm/update-sg-for-ingress.sh

# 2. Deploy Traefik
ssh -i .output/ssh/hybrid-llm-key.pem ec2-user@<EIP>
helm install traefik traefik/traefik -n traefik --create-namespace \
    -f infrastructure/overlays/aws-gpu/traefik/values.yaml

# 3. Cloudflare: Add A record → AWS EIP (proxied)

# 4. cert-manager
helm install cert-manager jetstack/cert-manager -n cert-manager --create-namespace --set installCRDs=true
kubectl apply -f infrastructure/overlays/aws-gpu/cert-manager/

# 5. Test
kubectl apply -f infrastructure/overlays/aws-gpu/test-services/whoami.yaml
curl https://test.aws.yourdomain.com
```

## Configuration Reference

### Traefik Values (AWS)
```yaml
deployment:
  kind: Deployment
  replicas: 1
ports:
  web:
    port: 80
    hostPort: 80
  websecure:
    port: 443
    hostPort: 443
service:
  type: ClusterIP
resources:
  requests: { cpu: 50m, memory: 64Mi }
  limits: { cpu: 200m, memory: 128Mi }
```

### ClusterIssuer (Let's Encrypt + Cloudflare)
```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-cloudflare
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    privateKeySecretRef:
      name: letsencrypt-account-key
    solvers:
      - dns01:
          cloudflare:
            apiTokenSecretRef:
              name: cloudflare-api-token
              key: api-token
```

## Cloudflare Setup

1. **DNS**: A record → AWS Elastic IP (orange cloud = proxied)
2. **SSL/TLS**: Full (strict)
3. **API Token**: Zone:DNS:Edit + Zone:Zone:Read

## Cost

- AWS Traefik: $0 (existing t3.small)
- cert-manager: $0
- Cloudflare: $0 (free tier)
- Data transfer: $0.09/GB after 100GB

## Related

- [Provisioning Recipe](./PROVISIONING-RECIPE.md)
- [Liqo README](../../infrastructure/base/hybrid-llm/liqo/README.md)
- [Traefik Status](../../infrastructure/base/traefik/STATUS.md)
