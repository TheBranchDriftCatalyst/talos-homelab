# gpu-inference — ephemeral GPU inference (TALOS-t3ic)

## TL;DR

An always-addressable Ollama-compatible endpoint at `http://ollama.talos00`. Requests
arriving while no GPU exists are **held**, an AWS GPU box is provisioned, and the request
is released once it is genuinely serving. Idle traffic ⇒ the GPU is destroyed.

**Nothing here bills anything today.** The gateway is at 0 replicas, `gpu-broker` is at 0
with an unbuilt image, and both reapers exit cleanly while the AWS XR CRDs are absent.
Scaling `gpu-broker` to 1 is the single switch that arms real AWS spend.

## Cost tiers

| Tier | State | Cost | Wake |
|------|-------|------|------|
| HOT | EC2 instance running | ~$0.16/hr (spot g5.xlarge) | — |
| WARM | instance gone, EBS cache parked | ~$16/mo (200GB gp3) | ~2 min |
| COLD | cache reaped, S3 library only | ~$4-13/mo (~1TB) | +10-40s |

Tier 1 reaper does HOT→WARM, tier 2 does WARM→COLD. Both TTLs are fields on the
`gpu-profile` ConfigMap, so they are tuned by PR.

## Request path

```
client → Traefik (ollama.talos00) → KEDA HTTP interceptor  ← HOLDS the request
       → ollama-gateway (KEDA scales 0↔1)                  ← the demand signal
            readiness = GPU backend answers /health        ← THE critical detail
       → gpu-backend Service (selectorless) → EndpointSlice ← written by gpu-broker
       → tunnel → vLLM :8000 on EC2
```

**Why readiness gates on the backend:** the interceptor releases buffered requests the
moment the target Deployment reports Ready. If the gateway reported Ready as soon as its
own pod started, every buffered request would be released into a backend still minutes
from existing. `nginx.conf`'s `/ready` proxies to the backend's `/health` precisely so
that cannot happen.

## Timeout budget — keep these IDENTICAL

Cold start is **2-5 min realistic** (EC2 start → boot → `s5cmd sync` → weights into VRAM).
The **shortest hop in the chain decides the real ceiling**, so every hop uses **600s**:

| Hop | Setting | Value |
|-----|---------|-------|
| Traefik entrypoint | `--entryPoints.web.transport.respondingTimeouts.readTimeout` etc. | **600s — NOT YET SET, see below** |
| KEDA interceptor | `KEDA_RESPONSE_HEADER_TIMEOUT`, `KEDA_CONDITION_WAIT_TIMEOUT` | 600s |
| nginx gateway | `proxy_read_timeout`, `proxy_send_timeout` | 600s |
| gateway readiness | `periodSeconds 5 × failureThreshold 120` | ~600s |

⚠️ **Outstanding gap:** the Traefik side is a **static entrypoint** setting and cannot be
raised from an IngressRoute. Until it is raised in the Traefik HelmRelease, Traefik will
cut held requests early no matter how patient the interceptor is — cold starts will fail
at the default responding timeout. This is the first thing to fix when testing end-to-end
(EPIC C6).

## Scope: HTTP + SSE only, no WebSockets (v1)

Ollama's own API is HTTP with SSE streaming, which `proxy_buffering off` handles. WS is
deliberately unsupported because an idle-but-open WebSocket would count as demand and pin
a ~$0.16/hr GPU up for as long as a browser tab stays open. Revisit only alongside
message-based (not connection-based) idle tracking.

## What is git-owned vs controller-owned

| Object | Owner | Why |
|--------|-------|-----|
| XRD, Composition | Flux (git) | the template — always declarative |
| `gpu-profile` ConfigMap | Flux (git) | the machine + cache SPEC, PR-reviewed |
| gateway, KEDA objects, reapers, RBAC | Flux (git) | ordinary infra |
| **XGPUInstance / XGPUCache existence** | **gpu-broker** | see below |
| EndpointSlice contents | gpu-broker | follows the instance's IP |

The two XRs are **not committed**. TALOS-455u documents three zombie modes that make any
other arrangement lose: instance self-terminates → Crossplane resurrects it; XR deleted →
Flux reapplies it; `running:false` patched → Flux reverts it. Flux never asserting XR
*existence* removes all three. Same principle as keeping `replicas` out of git when an HPA
owns them — the spec stays declarative, the count does not.

**The trade-off, stated plainly:** `kubectl get xgpuinstance,xgpucache` is the only source
of truth for what is currently billing. That is exactly why the tier-1 reaper is
independent of the broker and why `alerts.yaml` exists.

## Blocked on

- **TALOS-3g8f** (human gate) — 1Password `aws-crossplane` item. Its recorded policy is
  S3-only and needs EC2 + IAM PassRole added.
- **TALOS-t88y** — crossplane-core memory, **before** re-adding the ec2 provider. The
  2026-08-15 incident that removed those providers was CRD-load driven (~250 CRDs).
- `vpcId` / `subnetId` in `gpuprofile.yaml` are still `REPLACE-ME`.

## Related

`TALOS-t3ic` (root epic) · `TALOS-tzr5` (A: AWS chain) · `TALOS-3hjh` (B: XGPUInstance
correctness) · `TALOS-o3jn` (C: demand plane) · `TALOS-7p3v` (D: cost & safety) ·
`TALOS-455u` (XGPUInstance POC + the spin-down decision record)
