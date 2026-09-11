# TLS / Encryption-in-Transit Posture Audit

> **Audit date:** 2026-09-10 · **Scope:** read-only, no changes made
> **Cluster:** catalyst-cluster — 5 nodes, Talos v1.13.9, Kubernetes v1.36.4, Cilium 1.20.0

---

## TL;DR

The cluster has **strong TLS at its two edges and none in its middle.** Talos hardens the
control plane by default (mTLS everywhere), and Traefik terminates real certificates at :443.
Between those two points, essentially every byte moves in plaintext.

- **East-west pod traffic is unencrypted.** `Encryption: Disabled` on every Cilium agent. Any
  workload with host network access, or anyone tapping the LAN switch, reads all pod-to-pod
  traffic.
- **The single worst offender is the secrets broker.** All 124 `ExternalSecret`s fetch from
  1Password Connect over `http://onepassword-connect...:8080`. Every secret in the cluster —
  and the Connect bearer token authorizing the fetch — crosses the pod network in cleartext.
- **The repo's stated reason for not enabling Cilium WireGuard is factually wrong.** The
  `values.yaml` comment says "WireGuard + VXLAN causes 100% cross-node packet loss." Cilium has
  supported WireGuard over VXLAN since v1.10, and the MTU arithmetic that probably caused the
  original failure works out correctly at the cluster's current `MTU: 1250`. See
  [§1.3](#13-re-examining-the-wireguard-failure).
- **37 IngressRoutes serve plaintext HTTP on :80** with no redirect — including MinIO's S3 API
  and console, Grafana, Forgejo, the zot registry, and Ollama. There is no global
  HTTP→HTTPS redirect.
- **A cluster-internal CA already exists and is barely used.** `homelab-ca-issuer` signs 4
  certificates. It is the obvious foundation for internal service TLS.

**One change dominates the fix list:** enabling Cilium WireGuard encrypts all node-to-node pod
traffic and thereby retroactively covers most of §4, §5, and §6 at once, without touching a
single application manifest.

---

## Quick Reference — posture at a glance

| Layer | Encrypted? | Authenticated? | Verdict |
|---|---|---|---|
| 1. East-west (pod↔pod) | **No** | No | **Largest gap.** One Helm flag away |
| 2. Ingress edge (client→Traefik :443) | Yes (LE + internal CA) | Server-side | Good |
| 2b. Ingress edge :80 | **No** — 37 routes, no redirect | — | Gap |
| 2c. Traefik→backend | **No** — all 251 backends plain http | **No** — `insecureSkipVerify=true` | Gap (masked by §1 fix) |
| 3. Control plane / node | Yes | **mTLS** | **Excellent** — Talos defaults |
| 4. Service-to-service | **No** — near-universally plain http | No | Broad gap |
| 5. Databases | Partial — CNPG serves TLS, not enforced | Replication only | Mixed |
| 6. Secrets in transit | **No** — ESO→1Password over http | Bearer token in cleartext | **Highest value per byte** |
| 7. Service mesh | None present | — | By design (see §7) |

---

## 1. East-West: Pod-to-Pod Traffic

### 1.1 Current state — confirmed unencrypted

```console
$ kubectl -n kube-system exec ds/cilium -c cilium-agent -- cilium-dbg status
Encryption:              Disabled
Routing:                 Network: Tunnel [vxlan]   Host: BPF
KubeProxyReplacement:    True
Cilium:                  Ok   1.20.0 (v1.20.0-450c5314)

$ kubectl -n kube-system get cm cilium-config -o jsonpath='{.data.enable-wireguard}'
        # empty — key absent
$ kubectl -n kube-system get cm cilium-config -o jsonpath='{.data.mtu}'
1250
$ kubectl -n kube-system get cm cilium-config -o jsonpath='{.data.enable-ipv6}'
false
```

Mutual authentication is likewise off, in `infrastructure/base/cilium/values.yaml:281`:

```yaml
authentication:
  enabled: false
  mutual:
    spire:
      enabled: false
```

**Gap.** All pod-to-pod traffic crossing between the 5 nodes transits the LAN as cleartext
VXLAN. That includes every item catalogued in §4 (metrics, logs, object storage, secrets).
Anyone with a span port on the switch, a compromised host-network pod, or physical access to
the network reads all of it.

### 1.2 What Cilium WireGuard would and would not cover

Per the [v1.20 encryption docs](https://docs.cilium.io/en/v1.20/security/network/encryption-wireguard/),
anything absent from the support table is *not* encrypted.

**Covered by `encryption.enabled: true` alone (default mode):**

- Pod → remote Pod (direct, and via ClusterIP Service)
- Pod → remote Pod via NodePort, given socket-LB — which this cluster has
  (`KubeProxyReplacement: True`)
- Pod → remote Pod through the L7 proxy / Envoy
- External client → Pod via Service, in overlay routing without DSR/XDP — this cluster's config

**NOT covered:**

- **Same-node pod-to-pod.** Intentional and permanent: "Encryption would provide no benefits in
  that case, given that the raw traffic can be observed on the node anyway." With 5 nodes and
  default scheduling, a meaningful share of traffic stays on-node and remains cleartext.
- **Host-network pods and node→node host traffic.** Requires `encryption.nodeEncryption: true`
  (still **beta** in 1.20) — see the warning in [§1.4](#14-recommended-rollout).
- **kube-apiserver traffic.** Control-plane-labelled nodes automatically opt out of node
  encryption to avoid a key-rotation bootstrap deadlock. Already mTLS'd by Talos anyway (§3).
- **Traffic to the outside world.** The external-client→first-node hop is never encrypted.

**Crucially, WireGuard is transport encryption, not identity.** It authenticates *nodes* to each
other, not *workloads*. A compromised pod on node A can still reach any service on node B; the
traffic is merely encrypted on the wire. Closing that requires network policy (already partly in
place) or mutual auth (§7).

### 1.3 Re-examining the WireGuard failure

`infrastructure/base/cilium/values.yaml:333` records a prior attempt:

```yaml
# ISSUE: WireGuard + VXLAN causes 100% cross-node packet loss
# Tested: MTU=1370, devices="en+" - still broken
# Next: Try native routing mode instead of VXLAN tunnel
#
# encryption:
#   enabled: true
#   type: wireguard
#   nodeEncryption: false
```

**The stated diagnosis does not hold up, and the proposed next step is unnecessary.**

1. **VXLAN + WireGuard has always been supported.** I checked the Limitations section of the
   WireGuard doc across v1.10 through v1.20; "requires native routing" was never among them.
   Switching to native routing was never the fix. What *did* change: v1.14 added node-to-node
   encryption and L7 support; **v1.16 changed the datapath to encapsulate twice** (VXLAN, then
   WireGuard), so the two overheads now stack.

2. **The MTU arithmetic works at 1250 — and would not have worked at 1370.** Cilium does *not*
   take an explicit Helm `MTU` as the final pod MTU. It treats it as the **underlay** MTU and
   subtracts overhead to derive the route MTU
   ([`pkg/mtu/cell.go`](https://github.com/cilium/cilium/blob/v1.20.1/pkg/mtu/cell.go)):

   ```go
   } else {
       p.Log.Info("Using configured MTU", logfields.MTU, configuredMTU)
       rmtu := c.Calculate(configuredMTU)   // overhead applied even when explicit
   ```

   With `WireguardOverhead = 95` (raised from 80 in PR #45940 to fix exactly this class of
   fragmentation bug) and `TunnelOverheadIPv4 = 50`:

   | Value | Result | Derivation |
   |---|---|---|
   | Pod `eth0` device MTU | 1250 | verbatim |
   | Pod default-route MTU | **1105** | `1250 − (95 + 50)` |
   | `cilium_wg0` MTU | 1155 | `1250 − 95` |
   | **Max on-wire frame** | **1250** | `1105 + 50 + 95` |

   1250 fits the Nebula overlay budget exactly. **No MTU change is needed.** By contrast, the
   failed attempt at `MTU=1370` would have produced 1370-byte frames against a Nebula TUN of
   1300 — which is a precise explanation for "100% cross-node packet loss" that has nothing to do
   with VXLAN.

3. **The old attempt also predates the overhead fix.** `WireguardOverhead` was 80 until
   2026-05-19; at 80, a 1500-MTU link produced 1504-byte frames (cilium#23917). The cluster now
   runs 1.20.0, which includes the corrected constant.

**Caveat that keeps this safe:** the arithmetic depends on `enable-ipv6: false`, confirmed above.
`IPv6MinMTU = 1280` would force `cilium_wg0` to clamp *upward* past the Nebula budget. **Do not
enable IPv6 and WireGuard simultaneously at `MTU: 1250`.**

### 1.4 Recommended rollout

**Change** (`infrastructure/base/cilium/values.yaml` — replace the commented block):

```yaml
encryption:
  enabled: true
  type: wireguard
  nodeEncryption: false   # leave OFF — see warning below
```

> **Do not set `nodeEncryption: true`.** It is beta in 1.20, it exempts control-plane nodes
> anyway, and cilium#46100 (open, filed 2026-05-21, `area/mtu` + `feature/wireguard`) reports
> fragment drops on *exactly* this VXLAN + WireGuard + node-encryption topology, because
> host-network traffic originates on the host NIC and never benefits from Cilium's MTU
> reduction.

**Rollout hazard.** Peering keys off the `network.cilium.io/wg-pub-key` annotation on each
`CiliumNode`. A node that has not yet rolled has no pubkey and is simply not added as a peer —
so during the DaemonSet rollout, traffic to un-upgraded nodes **silently falls back to
plaintext**. Availability is preserved; security is not, and nothing surfaces an error. This is
fine for a maintenance window, but means "partially rolled out" is indistinguishable from
"working" without checking peer counts.

**Verification:**

```bash
# Expect: Encryption: Wireguard, Peers == (node count - 1) == 4
kubectl -n kube-system exec ds/cilium -c cilium-agent -- cilium-dbg status | grep -i encryption

# Hunt for leaks — anything still cleartext between nodes
hubble observe --unencrypted

# Confirm the derived MTUs match the table in §1.3
kubectl -n kube-system exec ds/cilium -c cilium-agent -- ip link show cilium_wg0
```

Agent restart only — **no node reboot**, and running pods do not need restarting (1.20's
`endpoint-mtu-updater` rewrites the route MTU inside each endpoint netns).

**`encryption.strictMode`** converts the plaintext-fallback window into a hard-drop window. Do
**not** enable it during the initial rollout. Consider it only after WireGuard is confirmed
fleet-wide, and note it is IPv4-only — which happens to suit this cluster.

**Effort:** Low — one values change, one Flux reconcile.
**Risk:** Medium — datapath change across all 5 nodes; reversible by reverting the values block.
**Value:** Very high — retroactively encrypts nearly everything in §4/§5/§6.

---

## 2. Ingress Edge and Backend

### 2.1 Edge TLS — good, with real certificates

Traefik runs as a 5-replica DaemonSet behind LoadBalancer `192.168.1.251`, with TLS enabled on
`websecure`:

```console
$ kubectl -n traefik get ds traefik -o json | ... # args
--entryPoints.websecure.address=:443/tcp
--entryPoints.websecure.http.tls=true
```

Certificates are genuine, not self-signed, for public zones — `letsencrypt-production` uses
DNS-01 via Cloudflare for `knowledgedump.space` and `amberdark.net`. Internal `*.talos00` hosts
are signed by the `homelab-ca-issuer` internal CA. Both are legitimate approaches for their
respective zones.

### 2.2 Gap — 37 routes serve plaintext on :80

There is **no global HTTP→HTTPS redirect**; no `--entrypoints.web.http.redirections.*` argument
exists. Redirection is instead done per-route by middleware, and 37 routes skip it:

```console
$ kubectl get ingressroute -A -o json | ...
entryPoints:
  ('web',):               128
  ('websecure',):          97
  ('web', 'websecure'):     2
backend scheme:
  <none = http>:          251

web-only WITH redirect middleware : 91
web-only SERVING PLAINTEXT        : 37
```

Of those 37, only 7 carry the `lan-only` middleware
(`ipAllowList: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.1/32`). The
remainder have no source restriction. Notable plaintext-serving routes with **no** `lan-only`:

| Route | Why it matters |
|---|---|
| `minio/minio-api`, `minio/minio-console` | S3 credentials + all object data |
| `monitoring/grafana` | session cookies, admin login |
| `forgejo/forgejo` | git credentials, source code |
| `registry/zot` | image push/pull credentials |
| `catalyst-llm/litellm`, `catalyst-llm/open-webui`, `gpu-inference/ollama` | API keys, prompt content |
| `home-automation/homeassistant` | home automation control |
| `monitoring/mimir`, `monitoring/loki-v2`, `monitoring/tempo`, `monitoring/hyperdx` | telemetry read APIs |
| `media-private/immich`, `media/plex`, `media/jellyfin` | media + user sessions |

Most match `*.talos00` hostnames resolvable only on the LAN, so practical exposure is
LAN-scoped rather than internet-scoped. That is a mitigation, not a fix — it still means
credentials cross the WiFi in cleartext.

> The 2 combined `web`+`websecure` routes (`media-private/amber-legacy-5`,
> `media-private/amber-legacy-private`) are a separate known hazard: Kyverno injects `tls: {}`,
> making the router TLS-only, so the HTTP route silently 404s without showing as Flux drift.

**Fix:** add the two redirection arguments to the `web` entrypoint so redirect is the default
rather than opt-in, then delete the 91 now-redundant redirect middlewares. Handle the 7
`lan-only` routes and any non-HTTP consumers (the registry mirror, OTLP ingest) as explicit
exceptions first.

**Effort:** Medium — 37 routes to triage. **Risk:** Medium — a global redirect breaks any
non-browser client hardcoded to `http://`.

### 2.3 Gap — Traefik→backend is unverified and unencrypted

```console
--serversTransport.insecureSkipVerify=true
```

Confirmed live, and in `infrastructure/base/traefik/helmrelease.yaml:205` (comment: "For
self-signed certs"). Combined with the scheme census above — **all 251 backend service
references use the default `http` scheme, zero use `https`** — the practical position is:

- Traefik → backend traffic is **plaintext**, so `insecureSkipVerify` is currently moot: there
  is no TLS session to verify.
- The flag becomes actively dangerous the moment any backend *is* switched to `https`, because
  it will silently accept any certificate, making the new TLS hop trivially MITM-able.

**Fix:** this gap is largely **subsumed by the §1 WireGuard fix** for the cross-node case.
Traefik pods are not host-network, so Traefik→backend hops that cross nodes get encrypted for
free. The residual exposure is same-node hops. Longer term, replace the global flag with
per-backend `ServersTransport` resources carrying the `homelab-ca` bundle — but only *after*
backends actually speak TLS, and it should not be prioritized above §1.

---

## 3. Control Plane and Node — Already Excellent

This layer needs no work. Documented for completeness.

```console
$ kubectl -n kube-system get pod -l k8s-app=kube-apiserver -o json | ...
--client-ca-file=/system/secrets/kubernetes/kube-apiserver/ca.crt
--etcd-cafile=/system/secrets/kubernetes/kube-apiserver/etcd-client-ca.crt
--etcd-certfile=/system/secrets/kubernetes/kube-apiserver/etcd-client.crt
--etcd-keyfile=/system/secrets/kubernetes/kube-apiserver/etcd-client.key
--etcd-servers=https://127.0.0.1:2379
--secure-port=6443
--tls-min-version=VersionTLS12
--tls-cipher-suites=TLS_AES_128_GCM_SHA256,...,TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305_SHA256
--requestheader-client-ca-file=.../aggregator-ca.crt
--service-account-issuer=https://192.168.1.54:6443
```

| Channel | Status |
|---|---|
| Talos API (:50000) | mTLS, client-cert only. No SSH exists to misconfigure. |
| etcd (:2379) | mTLS — apiserver presents a client cert against a dedicated etcd CA |
| kube-apiserver (:6443) | TLS ≥1.2, modern AEAD-only cipher suites, separate aggregator CA |
| kubelet | TLS with `--client-ca-file`; serving certs rotated by Talos |

All are Talos defaults and all are correct. TLS 1.2 is the floor rather than 1.3, which is the
right call for client compatibility given the cipher list is AEAD-only.

**No action.**

---

## 4. In-Cluster Service-to-Service

Near-universally plaintext. Evidence is client-side configuration (the consumer's URL is what
determines the scheme on the wire).

### 4.1 Monitoring pipeline — all plaintext

| Hop | Scheme | Evidence |
|---|---|---|
| Alloy → Mimir `remote_write` | http | `infrastructure/base/monitoring/v2-otel/alloy/helmrelease.yaml:1019` |
| alloy-node → Mimir | http | `.../alloy-node/helmrelease.yaml:190` |
| Alloy → Mimir OTLP | http + `tls{insecure=true}` | `.../alloy/helmrelease.yaml:164-167` |
| Alloy → Loki `loki.write` | http | `.../alloy/helmrelease.yaml:108` |
| Alloy → Tempo OTLP gRPC | grpc + `tls{insecure=true}` | `.../alloy/helmrelease.yaml:152-158` |
| Tempo metrics-gen → Mimir | http | `.../tempo/helmrelease.yaml:82,114` |
| Grafana → Mimir / Loki / Tempo | http ×3 | `.../grafana-datasources/datasources.yaml:17,38,59` |

Service ports corroborate: `mimir-*` on `8080/9095`, `loki` on `3100/9095`, `tempo` OTLP on
`4317/4318` — all plaintext ports.

### 4.2 MinIO / object storage — plaintext, uniformly `insecure: true`

Every consumer reaches MinIO over `http://`, and the service itself listens on port 80:

```console
$ kubectl -n minio get svc
minio           80/TCP
minio-console   9090/TCP
minio-hl        9000/TCP
```

| Consumer | Evidence |
|---|---|
| Loki → S3 | `.../loki/helmrelease.yaml:127,133,134` (`insecure: true`, `s3ForcePathStyle`) |
| Mimir → S3 (blocks/alertmanager/ruler/common) | `.../mimir/helmrelease.yaml:116,125,136,146` — `insecure: true` ×4 |
| Tempo → S3 | `.../tempo/helmrelease.yaml:62,121` |
| Velero → MinIO | `infrastructure/base/backup/velero.yaml:58` |
| etcd-backup → MinIO | `infrastructure/base/backup/etcd-backup.yaml:28` |
| CNPG barman → MinIO | `infrastructure/base/catalyst-cnpg-appdb/composition.yaml:223` |

**This is the second-largest concentration of exposed credentials after §6.** SigV4 signs
requests but does not encrypt them: access key IDs, request bodies, and every stored object —
including **etcd backups and Velero cluster backups** — traverse the pod network in cleartext.

### 4.3 Identity, cache, messaging, registry

| Service | Scheme | Evidence / note |
|---|---|---|
| Traefik forward-auth → Authentik | **http :80** | `infrastructure/base/authentik/middleware.yaml:11` — carries session cookies + identity headers |
| Grafana OIDC → Authentik | http | `.../grafana-instances/grafana-instance.yaml:74-75` |
| ArgoCD → Dragonfly | plaintext RESP :6379, **no AUTH** | `infrastructure/base/argocd/dragonfly.yaml:18` |
| Authentik → `authentik-cache` | plaintext, **no password** | `.../authentik/dragonfly-network-policy.yaml:4` |
| Celery → RabbitMQ | `amqp://` (not amqps) | `applications/crossplane-demo/celery/deployment.yaml:34` |
| HyperDX → MongoDB | `mongodb://`, no `tls=true` | `.../operators/clickstack-mongodb-secret.yaml:64` |
| ClickStack → ClickHouse | `tcp://...:9000` plaintext | `.../clickstack/helmrelease.yaml:133` |
| HyperDX / Plausible → ClickHouse | http :8123 | `.../clickstack/helmrelease.yaml:246` |
| containerd → zot | plain http mirror | `infrastructure/base/registry/zot/ingressroute.yaml:56,88` |
| argocd-server | `--insecure` (TLS at Traefik) | `infrastructure/base/argocd/helmrelease.yaml:64` — defensible given edge termination |
| dbgate UI | http :3000, **`LOGINS=""` — no auth** | `infrastructure/base/databases/dbgate/deployment.yaml:66` |

The Dragonfly instances deserve a callout independent of TLS: **both run with no authentication
at all**, so the only thing standing between any pod and ArgoCD's or Authentik's cache is
network policy.

### 4.4 The good example — CrowdSec

CrowdSec is the one component doing internal TLS properly, and is the template to copy:

| Hop | Scheme | Evidence |
|---|---|---|
| agents/appsec → LAPI | **mTLS client cert** | `infrastructure/base/crowdsec/helmrelease.yaml:32-33,54,61` |
| Traefik bouncer → LAPI | **https** + client-cert CA | `infrastructure/base/crowdsec/bouncer-middleware.yaml:18-20` |
| web-ui → LAPI | **https** | `infrastructure/base/crowdsec/webui.yaml:55` |
| CrowdSec → CNPG | **`sslmode: require`** | `infrastructure/base/crowdsec/helmrelease.yaml:310` |

It uses a dedicated cert-manager CA chain (`crowdsec-root-issuer` → `crowdsec-ca` →
`crowdsec-ca-issuer` → 5 leaf certs), all `Ready`. This proves the pattern works in this cluster.

**Two blemishes worth a follow-up ticket:**

1. `crowdsecLapiTLSInsecureVerify: "true"` (`bouncer-middleware.yaml:19`) — encryption without
   server-identity verification. The CA is already mounted; this should be removable.
2. **`crowdsec/decision-exporter.yaml:35` still points at `http://...:8080`** while the rest of
   the stack migrated to TLS. It sends `BOUNCER_KEY_traefik` in cleartext to a LAPI that is now
   TLS-only — this looks like a **missed step in the TLS migration** and may be silently
   failing. Worth verifying regardless of the broader audit.

---

## 5. Databases

### 5.1 CNPG Postgres — serves TLS, does not require it

20+ CNPG clusters run with the operator's default per-cluster CA. TLS is genuinely on:

```console
$ kubectl -n crowdsec exec crowdsec-postgres-1 -c postgres -- psql -U postgres -tAc \
    "show ssl; select name,setting from pg_settings where name in ('ssl_cert_file','ssl_ca_file');"
on
ssl_ca_file|/controller/certificates/client-ca.crt
ssl_cert_file|/controller/certificates/server.crt
```

But `pg_hba.conf` tells the real story:

```
hostssl postgres    streaming_replica all cert map=cnpg_streaming_replica
hostssl replication streaming_replica all cert map=cnpg_streaming_replica
hostssl all         cnpg_pooler_pgbouncer all cert map=cnpg_pooler_pgbouncer
host    all         all               all scram-sha-256      <-- accepts plaintext
```

- **Replication is properly mTLS'd** (`hostssl ... cert`). Good, and it is the operator default.
- **Application connections are not.** `host` matches *both* SSL and non-SSL connections, so
  every app can — and mostly does — connect in cleartext. Password exchange is at least
  SCRAM-SHA-256, so credentials are not directly recoverable, but all query traffic and result
  data is cleartext.
- **Clients do not verify.** Only CrowdSec sets `sslmode` (`require`). `require` encrypts but
  does **not** validate the server certificate — it is not `verify-full`. Everything else sets
  no `sslmode` at all; note that libpq defaults to `prefer` (opportunistic) but **Go `pgx`,
  Node `pg`, and JDBC default to no TLS whatsoever**, so the effective default here is plaintext.
- `dbgate-connection-sync` connects with no `sslmode` at all
  (`.../dbgate-connection-sync/configmap-script.yaml:82-85`).

Two clusters additionally widen `pg_hba` to the whole LAN with `md5` (weaker than SCRAM):
`boomtime/books-postgres` and `boomtime/boomtime-postgres` carry
`host all all 192.168.0.0/16 md5`.

**Note:** `books-postgres`, `dagster-postgres`, `postgres-knowledge`, `guacamole-postgres`, and
`manyfold-postgres` run `instances: 1`, which conflicts with the standing rule that CNPG on
local-path must be scaled to 3. Out of scope here, but flagging it since the inventory surfaced it.

### 5.2 Other datastores

MongoDB, ClickHouse, Dragonfly, and RabbitMQ all speak plaintext (§4.3), and Dragonfly has no
authentication at all. None of these has TLS configured.

---

## 6. Secrets in Transit — The Highest-Value Gap

### 6.1 ESO → 1Password Connect over plain HTTP

```console
$ kubectl get clustersecretstore onepassword -o json | ...
provider=onepassword -> {
  "connectHost": "http://onepassword-connect.external-secrets.svc.cluster.local:8080",
  "auth": {"secretRef": {"connectTokenSecretRef": {"name": "onepassword-connect-token", ...}}},
  "vaults": {"catalyst-eso": 1}
}

$ kubectl get externalsecret -A --no-headers | wc -l
154
  store onepassword:        124
  store cnpg-backup-source:  15

$ kubectl -n external-secrets get deploy onepassword-connect -o json | ...
  connect-api   1password/connect-api:1.8.2   ports: [8080]
  connect-sync  1password/connect-sync:1.8.2  ports: [8081]
```

Source: `infrastructure/base/external-secrets/secretstores/onepassword-secretstore.yaml:11`
(ClusterSecretStore) and `:33` (namespaced SecretStore).

**This is the single highest-value plaintext channel in the cluster.** On every refresh of all
124 ExternalSecrets:

- The **1Password Connect bearer token** goes out in an `Authorization` header in cleartext.
  That token grants read access to the entire `catalyst-eso` vault.
- The **decrypted secret material** comes back in the response body in cleartext.

Because §1 is also unencrypted, any host-network pod or LAN observer can harvest both the
broker token and the secrets it brokers. The token is the more serious loss: it is a master key,
and it is replayed continuously rather than once.

**Fix options, in order of preference:**

1. **Enable Cilium WireGuard (§1).** Encrypts this channel wherever ESO and Connect land on
   different nodes — zero changes to ESO or Connect. Does *not* cover the same-node case, which
   is a real gap here since both run in `external-secrets`.
2. **Terminate TLS at Connect.** `connect-api` supports serving TLS; issue a cert from
   `homelab-ca-issuer` and flip `connectHost` to `https://...:8443` with the CA in
   `caProvider`. This is the complete fix and is scoped to two files. **Recommended.**
3. **NetworkPolicy** restricting who can reach `:8080` — defense in depth, worth doing
   regardless, but does not address the LAN-observer path.

**Effort:** Low-Medium. **Risk:** Low — blast radius is ESO; failure is loud and immediately
visible via `ExternalSecret` status.

### 6.2 cert-manager inventory — an internal CA already exists

```console
$ kubectl get clusterissuer
NAME                     READY   AGE
crowdsec-root-issuer     True    157m
homelab-ca-issuer        True    124d
letsencrypt-production   True    124d
letsencrypt-staging      True    124d
selfsigned-issuer        True    124d

$ kubectl get clusterissuer homelab-ca-issuer -o yaml
spec:
  ca:
    secretName: homelab-ca-secret
status:
  conditions:
  - message: Signing CA verified
    reason: KeyPairVerified
    status: "True"
```

26 Certificates exist across 10 namespaces, all `Ready`. Breakdown by issuer:

| Issuer | Certs | Used for |
|---|---|---|
| `letsencrypt-production` | 3 | public wildcards (`amberdark`, `knowledgedump`, `priv-knowledgedump`) |
| **`homelab-ca-issuer`** | **4** | `talos00-wildcard`, `priv-talos00-wildcard`, `homepage-talos00-wildcard`, `teak-wildcard` |
| `crowdsec-ca-issuer` | 5 | the mTLS chain in §4.4 |
| operator self-signed issuers | 14 | webhook serving certs (tempo, rabbitmq, opensearch, intel, barman) — normal |

**`homelab-ca-issuer` is exactly the cluster-internal CA needed for service mTLS, and it is
already trusted for ingress.** Standing it up for internal services is mostly a matter of
issuing leaf certs and distributing the CA bundle.

**Gap:** `kubectl get bundle` returns **no resources** — trust-manager is installed (its Issuer
and Certificate exist in `cert-manager`) but **distributes nothing**. Creating a single `Bundle`
that publishes `homelab-ca-secret`'s CA into every namespace is the prerequisite for any
per-service TLS work, and is a small, low-risk change worth doing early.

---

## 7. Service Mesh — None Present

```console
$ kubectl get ns | grep -iE 'istio|linkerd|consul|kuma'    # no output
$ kubectl get crd | grep -icE 'istio|linkerd|consul.hashicorp|kuma'
0
$ kubectl get pods -A | grep -icE 'spire|istio|linkerd'
0
```

Confirmed: no mesh, and no SPIRE remnants.

**This is a deliberate, well-reasoned removal, not an oversight.** Per
`infrastructure/base/cilium/values.yaml:251-280` and
`docs/02-architecture/cilium-spire-disposition.md`, Cilium's SPIRE-based mutual auth was removed
on 2026-08-22 (TALOS-1d4o) because: nothing referenced `authentication.mode` in any of the 6
CiliumNetworkPolicies (so it was enforcing nothing); it is **deprecated as of Cilium 1.20 and
slated for removal in 1.21**; and spire-agent's projected-token CrashLoopBackOff recurred even
after the supposed durable fix, because agents re-attest every ~30 minutes indefinitely.

**Recommendation: do not reintroduce a mesh for encryption's sake.** WireGuard delivers the
encryption at a fraction of the operational cost, and the mutual-auth feature that a mesh would
add is precisely the thing that was just removed for being both unused and deprecated. Revisit
only if a concrete requirement for **workload identity** (not encryption) appears — and if so,
evaluate a current option rather than resurrecting Cilium SPIRE.

> Note: Cilium's own feature matrix lists "Integrate mutual authentication with WireGuard" as
> **TODO**, so the two are independent — enabling WireGuard neither provides nor precludes
> workload identity.

---

## Prioritized Shore-Up List

Ranked by security value ÷ effort.

| # | Action | Value | Effort | Risk | Covers |
|---|---|---|---|---|---|
| **1** | **Enable Cilium WireGuard** (`encryption.enabled: true`, `type: wireguard`, `nodeEncryption: false`) | **Very High** | **Low** | Med | All cross-node pod traffic — most of §1, §2.3, §4, §5, §6 at once |
| **2** | **TLS on onepassword-connect**; flip `connectHost` to `https` | **Very High** | Low-Med | Low | §6.1 — the broker token + all 124 secrets, incl. same-node |
| **3** | **Fix `crowdsec/decision-exporter.yaml:35`** → https | Med | **Trivial** | Low | §4.4 — likely an outright bug, not just a hardening item |
| **4** | **Create a trust-manager `Bundle`** distributing `homelab-ca` | Med | **Low** | Low | Unblocks #6, #7 — prerequisite, do early |
| **5** | **Add AUTH to both Dragonfly instances** | Med-High | Low | Low | §4.3 — unauthenticated caches for ArgoCD + Authentik |
| **6** | **TLS on MinIO** + flip the 6 `insecure: true` consumers | High | **High** | Med-High | §4.2 — S3 creds, etcd + Velero backups. Coordinated cutover across 6 consumers |
| **7** | **Global HTTP→HTTPS redirect**, triage the 37 plaintext routes | Med-High | Med | Med | §2.2 — may break hardcoded `http://` clients |
| **8** | **CNPG: `sslmode=verify-full`** on clients; then `hostssl` in `pg_hba` | Med | Med | Med | §5.1 — needs CA distribution (#4) first |
| **9** | **Authentik forward-auth over TLS** | Med | Med | Med | §4.3 — session cookies + identity headers |
| **10** | **Per-backend `ServersTransport`**, drop the global `insecureSkipVerify` | Low-Med | High | Med | §2.3 — only meaningful *after* backends speak TLS |
| — | ~~Service mesh / SPIFFE~~ | — | Very High | High | **Not recommended** — see §7 |

### Reading the table

**Items 1–5 are the campaign.** Together they are perhaps a day of work, carry low-to-medium
risk, and close the large majority of the exposed surface. Item 1 alone changes the cluster's
posture more than items 6–10 combined.

**Items 6–10 are the long tail.** They address the *same-node* residue that WireGuard cannot
cover, plus identity/verification rather than pure confidentiality. They are worth doing, but
each costs more than the entire top-five bundle. Sequence them after #1 lands and stays stable.

### The distinction that should drive sequencing

- **Encryption in transit** — confidentiality against a network observer. WireGuard buys nearly
  all of it for one flag and no application changes. **This is the cheap win; take it first.**
- **Mutual authentication / workload identity** — proving *which workload* is calling. Requires
  per-service certificates (#6, #8, #9) or a mesh (#7 in §7, not recommended). Fundamentally
  more expensive, and the mesh-shaped version of it was deliberately removed 3 weeks ago for
  good reasons.

Do not let the second category's cost delay the first category's benefit. They are independent.

---

## Related Issues

<!-- Beads tracking for this doc -->
- Pending: file tickets for shore-up items 1–5.
- Prior art: TALOS-1d4o (Cilium SPIRE removal), TALOS-3pdz (CrowdSec LAPI TLS migration).
