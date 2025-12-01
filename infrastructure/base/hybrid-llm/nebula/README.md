# Nebula Mesh VPN

> Encrypted P2P overlay network connecting homelab and AWS clusters

## Overview

Nebula is a scalable overlay networking tool created by Slack. It provides:
- Mutual authentication via certificates
- Encrypted P2P tunnels (AES-256-GCM)
- NAT traversal via UDP hole punching
- Firewall rules based on certificate groups

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Lighthouse    │     │  Homelab Node   │     │  AWS GPU Node   │
│   10.42.0.1     │◄───►│   10.42.1.1     │◄───►│   10.42.2.1     │
│   (Discovery)   │     │   (Talos)       │     │   (k3s)         │
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │                      │                       │
         └──────────────────────┼───────────────────────┘
                                │
                      Nebula Overlay Network
                         10.42.0.0/16
```

## Components

| File | Description |
|------|-------------|
| `kustomization.yaml` | Kustomize entrypoint |
| `namespace.yaml` | nebula-system namespace |
| `configmap.yaml` | Nebula configuration (non-sensitive) |
| `daemonset.yaml` | Nebula agent running on each node |
| `external-secret.yaml` | CA cert and node certificates from 1Password |

## Prerequisites

1. **Nebula CA** - Generate offline, store securely
2. **Lighthouse** - Always-on node with public IP
3. **Node Certificates** - Signed by CA for each node

## Certificate Generation

```bash
# Initialize CA (do once, store ca.key securely!)
nebula-cert ca -name "talos-homelab"

# Sign lighthouse certificate
nebula-cert sign \
  -name "lighthouse" \
  -ip "10.42.0.1/16" \
  -groups "lighthouse,infrastructure"

# Sign homelab node certificate
nebula-cert sign \
  -name "talos-homelab" \
  -ip "10.42.1.1/16" \
  -groups "homelab,kubernetes,control-plane"

# Sign AWS GPU node certificate
nebula-cert sign \
  -name "aws-gpu-worker" \
  -ip "10.42.2.1/16" \
  -groups "aws,kubernetes,worker,gpu"
```

## Configuration

See `configmap.yaml` for the Nebula configuration template.

Key settings:
- `static_host_map`: Lighthouse public IP
- `lighthouse.am_lighthouse`: true for lighthouse, false for others
- `firewall`: Allow traffic based on groups

## Deployment on Talos

Nebula can run as:
1. **DaemonSet** - Preferred for Kubernetes integration
2. **Talos Extension** - Native Talos integration (requires image rebuild)

We use the DaemonSet approach for flexibility.

## Troubleshooting

```bash
# Check Nebula pod status
kubectl get pods -n nebula-system

# View Nebula logs
kubectl logs -n nebula-system -l app=nebula

# Test connectivity
kubectl exec -n nebula-system <pod> -- nebula-cert print -json
kubectl exec -n nebula-system <pod> -- ping 10.42.0.1
```

## Security Notes

- **CA Key**: Keep offline, never on cluster
- **Node Keys**: Stored in 1Password, synced via External Secrets
- **Firewall**: Default deny, explicit allow for services
- **Groups**: Used for role-based network access

## References

- [Nebula GitHub](https://github.com/slackhq/nebula)
- [Nebula Documentation](https://nebula.defined.net/docs/)
- [Slack Engineering Blog](https://slack.engineering/introducing-nebula-the-open-source-global-overlay-network-from-slack/)
