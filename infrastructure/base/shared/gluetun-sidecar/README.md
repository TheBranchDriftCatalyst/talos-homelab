# Gluetun Sidecar Shared Components

This directory contains shared patterns for deploying gluetun VPN sidecars in Kubernetes.

## IPv6 Cleanup Init Container

**Required for ALL deployments using gluetun with WireGuard.**

### Problem

Gluetun with WireGuard creates IPv6 routing rules for table 51820. When pods restart,
stale rules may persist in the node's network namespace, causing gluetun to fail with:

```
ERROR [vpn] adding IPv6 rule: adding ip rule 101: from all to all table 51820: file exists
```

This causes endless restart loops (257+ restarts observed in production).

### Solution

Add this init container to clean up stale rules before gluetun starts:

```yaml
initContainers:
  - name: cleanup-routes
    image: busybox:1.36
    securityContext:
      capabilities:
        add:
          - NET_ADMIN
    command:
      - /bin/sh
      - -c
      - |
        echo "Cleaning up stale IPv6 routing rules..."
        ip -6 rule del table 51820 2>/dev/null || true
        ip -6 rule del table 51820 2>/dev/null || true
        ip -6 rule del table 51820 2>/dev/null || true
        echo "Cleanup complete"
```

### Deployments Using This Pattern

All of these files MUST include the cleanup-routes init container:

| File | Status |
|------|--------|
| `infrastructure/base/vpn-gateway/deployment.yaml` | ✅ Has fix |
| `infrastructure/base/vpn-gateway/securexng.yaml` | ✅ Has fix |
| `infrastructure/base/vpn-gateway/secure-chrome.yaml` | ✅ Has fix |
| `infrastructure/base/vpn-gateway/secure-webtop.yaml` | ✅ Has fix |
| `applications/arr-stack/base/qbittorrent/deployment.yaml` | ✅ Has fix |

### Checklist for New Gluetun Sidecars

When adding a new deployment with gluetun:

1. [ ] Add `cleanup-routes` init container (copy snippet above)
2. [ ] Set `DOT: "off"` in gluetun env (disables DNS-over-TLS)
3. [ ] Set `DOT_IPV6: "off"` in gluetun env (recommended)
4. [ ] Add `vpn-gateway.io/rotation: enabled` label if rotation is needed
5. [ ] Use internal liveness probe (`/v1/vpn/status` port 8000) not external IPs

### Additional Resources

- [Gluetun Wiki - IPv6](https://github.com/qdm12/gluetun-wiki/blob/main/faq/ipv6.md)
- [WireGuard Table 51820](https://github.com/qdm12/gluetun/issues/1234)
