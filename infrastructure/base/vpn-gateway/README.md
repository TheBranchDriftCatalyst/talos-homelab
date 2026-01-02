# VPN Gateway

Pod-based VPN gateway using gluetun with ProtonVPN WireGuard. Provides anonymous egress for pods and external clients via multiple proxy protocols.

## TODO:

Change this dir structure a bit:

vpn-gateway/
  ├── README.md
  ├── apps/


## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                          VPN Gateway Pod                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────────┐   │
│  │   gluetun   │  │ socks5-proxy│  │        tun0 interface       │   │
│  │ (WireGuard) │──│  (SOCKS5)   │──│   → ProtonVPN Netherlands   │   │
│  │             │  └─────────────┘  │      Exit IP: 212.92.x.x    │   │
│  │ HTTP Proxy  │                   └─────────────────────────────┘   │
│  │ Shadowsocks │                                                      │
│  └─────────────┘                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

## Connection Methods

### 1. HTTP Proxy (Port 8080)

Standard HTTP/HTTPS proxy. Most compatible option.

**From within cluster:**
```bash
export http_proxy=http://gluetun.vpn-gateway.svc.cluster.local:8080
export https_proxy=http://gluetun.vpn-gateway.svc.cluster.local:8080
curl ifconfig.me  # Returns VPN exit IP
```

**From external network (via Traefik):**
```bash
export http_proxy=http://192.168.1.54:8080
export https_proxy=http://192.168.1.54:8080
curl ifconfig.me
```

**Configure applications:**
```yaml
env:
  - name: HTTP_PROXY
    value: "http://gluetun.vpn-gateway.svc.cluster.local:8080"
  - name: HTTPS_PROXY
    value: "http://gluetun.vpn-gateway.svc.cluster.local:8080"
```

### 2. SOCKS5 Proxy (Port 1080)

Native SOCKS5 protocol. Better for applications that support it.

**From within cluster:**
```bash
curl --socks5 gluetun.vpn-gateway.svc.cluster.local:1080 ifconfig.me
```

**From external network (via Traefik):**
```bash
curl --socks5 192.168.1.54:1080 ifconfig.me
```

**Firefox/Browser configuration:**
- Settings → Network Settings → Manual proxy configuration
- SOCKS Host: `192.168.1.54`, Port: `1080`
- SOCKS v5: checked
- Proxy DNS when using SOCKS v5: checked

### 3. Shadowsocks (Port 8388)

Encrypted SOCKS proxy. Use when you need encryption between client and proxy.

**Password:** Configured in gluetun deployment (default: auto-generated)

**Get password:**
```bash
kubectl logs -n vpn-gateway deploy/gluetun -c gluetun | grep -i shadowsocks
```

**Client configuration:**
- Server: `192.168.1.54`
- Port: `8388`
- Encryption: `chacha20-ietf-poly1305`
- Password: (from logs above)

### 4. Sidecar Pattern (Recommended for Pods)

Deploy gluetun as a sidecar container. All pod traffic routes through VPN automatically.

See `securexng.yaml` for a complete example.

**Key configuration:**
```yaml
spec:
  containers:
    - name: gluetun
      image: qmcgaw/gluetun:latest
      securityContext:
        capabilities:
          add: [NET_ADMIN]
      env:
        - name: VPN_SERVICE_PROVIDER
          value: "protonvpn"
        - name: VPN_TYPE
          value: "wireguard"
        - name: WIREGUARD_PRIVATE_KEY
          valueFrom:
            secretKeyRef:
              name: protonvpn-credentials
              key: nl-free-176  # Or other server
        - name: FIREWALL_INPUT_PORTS
          value: "8080"  # Ports your app needs

    - name: your-app
      image: your-app:latest
      # No network config needed - uses gluetun's network
```

## VPN Servers

Multiple ProtonVPN servers configured for different use cases:

| Key | Location | Use Case |
|-----|----------|----------|
| `nl-free-176` | Netherlands | Default gateway (primary) |
| `se-de-1` | Germany | SecureXNG (different exit) |

## Services

| Service | Internal URL | External URL | Protocol |
|---------|--------------|--------------|----------|
| HTTP Proxy | `gluetun.vpn-gateway:8080` | `192.168.1.54:8080` | HTTP |
| SOCKS5 | `gluetun.vpn-gateway:1080` | `192.168.1.54:1080` | SOCKS5 |
| Shadowsocks | `gluetun.vpn-gateway:8388` | `192.168.1.54:8388` | Shadowsocks |
| Health | `gluetun.vpn-gateway:9999` | - | HTTP |
| Control API | `gluetun.vpn-gateway:8000` | - | HTTP |

## SecureXNG

VPN-protected SearXNG instance with mTLS client authentication.

**Architecture:** Uses gluetun sidecar for transparent VPN routing. All SearXNG traffic exits through the VPN automatically.

**Exit IP:** Germany (different from main gateway for geographic diversity)

**Access:** `https://securexng.talos00` (requires client certificate)

**Client certificates location:** `configs/securexng-mtls/`

**Using with curl:**
```bash
curl --cert configs/securexng-mtls/client.crt \
     --key configs/securexng-mtls/client.key \
     https://securexng.talos00/
```

**Browser setup:**
1. Create PKCS12 bundle: `openssl pkcs12 -export -in client.crt -inkey client.key -out client.p12`
2. Import `client.p12` into browser certificate store
3. Navigate to `https://securexng.talos00`
4. Select the imported certificate when prompted

**Known Limitation:** Search engine timeouts may occur due to VPN latency. SearXNG's default 3s timeout can be increased in the settings.yml configuration.

## Control API

Gluetun exposes a control API for runtime management.

**Get VPN status:**
```bash
kubectl exec -n vpn-gateway deploy/gluetun -c gluetun -- wget -qO- http://localhost:8000/v1/vpn/status
```

**Get public IP:**
```bash
kubectl exec -n vpn-gateway deploy/gluetun -c gluetun -- wget -qO- http://localhost:8000/v1/publicip/ip
```

## Monitoring

A Grafana dashboard is available at `grafana.talos00` → "VPN Gateway" showing:
- VPN tunnel bandwidth (tun0 interface)
- Pod network traffic
- Container resource usage
- Network errors

## Troubleshooting

**Check VPN connection:**
```bash
kubectl exec -n vpn-gateway deploy/gluetun -c gluetun -- wget -qO- https://ifconfig.me
```

**View gluetun logs:**
```bash
kubectl logs -n vpn-gateway deploy/gluetun -c gluetun
```

**Check proxy accessibility from test pod:**
```bash
kubectl run test --rm -it --restart=Never --image=curlimages/curl -- \
  curl -x http://gluetun.vpn-gateway.svc.cluster.local:8080 ifconfig.me
```

**Verify Traefik entrypoints:**
```bash
kubectl get ingressroutetcp -n vpn-gateway
```

## Security Notes

- HTTP Proxy and SOCKS5 are unencrypted between client and proxy (VPN encrypts beyond proxy)
- Use Shadowsocks when client-to-proxy encryption is needed
- SecureXNG uses mTLS - only clients with valid certificates can connect
- Private keys in `configs/securexng-mtls/` are gitignored - keep safe!
- VPN credentials stored in 1Password, synced via ExternalSecrets
