# gpu-inference — ephemeral GPU inference (TALOS-t3ic)

## TL;DR

An always-addressable Ollama-compatible endpoint at `http://ollama.talos00`. Requests
arriving while no GPU exists are **held**, an AWS GPU box is provisioned, and the request
is released once it is genuinely serving. Idle traffic ⇒ the GPU is destroyed.

**Nothing here bills anything today** — but the reasons given here were stale and are
corrected (verified live 2026-10-20, TALOS-outpost):

* the nginx `ollama-gateway` was **DELETED** 2026-10-01, and `gpu-broker` was **DELETED**
  2026-10-02. Neither exists, so "at 0 replicas" / "unbuilt image" no longer describe
  anything, and **scaling `gpu-broker` is no longer the switch that arms spend.**
* **the AWS XR CRDs are PRESENT, not absent.** All five providers are Installed+Healthy
  (`provider-aws-{s3,ec2,iam,ecs,cloudwatchlogs}:v2.7.0`), and `aws/apps/kustomization.yaml`
  records a successful end-to-end GPU run on 2026-10-02.
* the reapers now guard on the RESOURCE rather than `kubectl get crd` (fixed 2026-10-02).

**What actually arms spend: an uncommented claim line in `../aws/apps/kustomization.yaml`.**
That is the only switch. All GPU claims there are currently commented OFF.

**Already live and worth knowing**: the `gpu-relay` Pod is armed (17d, 1/2 Ready — the SSM
tunnel is up, socat is idle because no rig exists), along with IAM user `catalyst-gpu-relay`
and secret `gpu-relay-creds`. Free, but it is a static AWS key with `ssm:StartSession`.

## Cost tiers

| Tier | State | Cost | Wake |
|------|-------|------|------|
| HOT | EC2 instance running | ~$0.16/hr (spot g5.xlarge) | — |
| WARM | instance gone, EBS cache parked | ~$16/mo (200GB gp3) | ~2 min |
| COLD | cache reaped, S3 library only | ~$4-13/mo (~1TB) | +10-40s |

Tier 1 reaper does HOT→WARM, tier 2 does WARM→COLD. Both TTLs are fields on the
`gpu-profile` ConfigMap, so they are tuned by PR.

## Request path

```text
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

**Nothing. This section was stale and is cleared (verified 2026-10-20, TALOS-outpost).**

All three former blockers are resolved, and leaving them listed cost real debugging time:

* ~~**TALOS-3g8f** — 1Password `aws-crossplane` policy is S3-only~~ → **RESOLVED.** The
  credential was restored in `bef5dddd`; EC2+IAM work. Evidence: all five AWS providers
  Installed+Healthy, three `xbuckets` Synced+Ready, four `users.iam` Synced+Ready, and a
  logged end-to-end GPU run on 2026-10-02 that placed `i-009d3f4bb019620e2`.
* ~~**TALOS-t88y** — crossplane-core memory, before re-adding the ec2 provider~~ →
  **RESOLVED.** `provider-aws-ec2:v2.7.0` has been installed and healthy for 58 days.
  The 2026-08-15 incident was CRD-load driven (~250 CRDs from the monolithic
  `provider-aws`); the fix was per-service providers plus the
  `ManagedResourceActivationPolicy` allowlist in `../aws-providers/activation-policy.yaml`,
  under which non-activated MRDs are never installed as CRDs at all. Keep it that way and
  **never use `*`**.
* ~~`vpcId` / `subnetId` in `gpuprofile.yaml` are still `REPLACE-ME`~~ → **MOOT.** Those
  keys no longer exist in `gpuprofile.yaml` (removed with the AZ pin, TALOS-rkg0 — the
  fleet picks its own subnet). The remaining `REPLACE-ME` surface is only
  `../aws/apps/vllm-8b.yaml`, which is OFF and whose spec also predates the
  `models`→`hfModel` rename. For the record, the real us-west-2 ids are
  `vpc-3536d651` / `subnet-36191741`.

## Related

`TALOS-t3ic` (root epic) · `TALOS-tzr5` (A: AWS chain) · `TALOS-3hjh` (B: XGPUInstance
correctness) · `TALOS-o3jn` (C: demand plane) · `TALOS-7p3v` (D: cost & safety) ·
`TALOS-455u` (XGPUInstance POC + the spin-down decision record)
