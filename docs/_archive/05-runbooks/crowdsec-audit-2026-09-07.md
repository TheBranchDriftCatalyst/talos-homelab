# CrowdSec security-stack audit — 2026-09-07

Scope: CrowdSec LAPI, agents, AppSec, Traefik bouncer, Cowrie, iocaine, decision
inventory, and monitoring. This is a configuration and operational audit with
bounded regression probes, not an assertion that every application is secure.

## Findings repaired

| Finding | Result and evidence |
|---|---|
| Inventory sent an unversioned User-Agent every 30 seconds | Now `crowdsec-decision-inventory/1.0.0`. LAPI expects exactly `name/version`. Zero matching warnings in the checked post-rollout window; inventory success remained 1. |
| Traefik retained cookies and arbitrary credential headers | Header default is now `drop`, with `User-Agent` retained for CrowdSec. Live correlated request verified synthetic Cookie, Authorization and X-Api-Key fields absent and required parser fields present. |
| Boomtime telemetry exception applied on every host | Both body-inspection and out-of-band exception predicates now require one of the actual Boomtime hosts. Positive and negative host/path cases pass; native CrowdSec config compilation passes. |
| DoS user-agent simulation entry did not match runtime name | Hub item is `http-dos-switching-ua`, but its installed v0.5 YAML declares `http-dos-swithcing-ua`. Simulation now uses that runtime name, restoring the documented detect-only intent. Cowrie remains enforcing. |
| Tarpit received an unnecessary service-account token | Automatic token projection disabled. Live pod has no service-account token projection or credential mount. |
| Immich/Home Assistant acquisition depended on ReplicaSet hash prefixes | Explicit container-specific CRI filename patterns survive pod hash changes and exclude ML/database sidecars. Immich is currently deliberately scaled to zero; it is not counted as a live ingestion success. |
| Inventory startup could produce a premature readiness warning | Added a bounded startup probe before readiness/liveness. |
| Comments contradicted deployed behavior | Corrected Cowrie parser status, 30-minute allowlist refresh description, AppSec default-remediation explanation, and iocaine's user-agent-dependent 421 behavior. |

The `traefik@<IP>` inventory entry is a bouncer identity derived from the shared
read-only key. It does not mean the exporter is a Traefik pod. Old per-pod identities
can remain visible after rescheduling; the current type/version and last-pull time
are the relevant evidence. Credentials were not rotated as part of this fix.

## Operational verification

- LAPI: two Ready replicas on distinct nodes. AppSec: two Ready replicas on distinct nodes.
- CrowdSec agents and Traefik: five Ready pods each, covering all desired nodes.
- PostgreSQL: three Ready instances; CNPG reports a healthy cluster.
- CAPI authentication/enrollment succeeds; signal sharing and community-list pulling are enabled. Real nonsimulated HTTP detections have resumed. This audit did not independently verify closure of the old cloud-console incident.
- Six CrowdSec alert rules are loaded in Mimir, healthy, and evaluated without errors.
- Cowrie: all 14 existing hardening assertions pass. Connection attempts from its actual container to the internet, LAN gateway and Kubernetes API timed out. DNS remains an explicit permitted channel.
- Unified posture suite: all 16 checks passed with `--live`, including actual log redaction, live token projections, native AppSec config validation, scenario naming, and parser fixtures. See [verification commands](crowdsec-verification.md).
- The expanded VPN test passed from `45.128.133.227`: **401 → 403 → 401**; forged X-Forwarded-For, X-Real-IP and CF-Connecting-IP headers remained blocked. One LAPI replica replacement preserved 403 across three samples; one AppSec replica replacement after unban preserved 401 across five samples. Both recovered redundancy; canary and test ban were cleaned up. Earlier attempts exposed intermittent canary DNS failures; pinning the initially verified public addresses with TLS validation made the enforcement test independent of repeated DNS resolution.

## Remaining boundaries and intentional warnings

| Item | Assessment |
|---|---|
| Public Cowrie exposure | Router forwarding is staged, not enabled by this audit. WAN detection and continued Cowrie access while other services are banned remain to be verified. A node-specific forward also needs a stable destination if Cowrie reschedules. Tracked in TALOS-gdid. |
| Cowrie storage/image hardening | Writable root filesystem, unbounded ephemeral volumes, mutable image tag, and recursive DNS egress remain pre-exposure considerations in the [Cowrie runbook](cowrie-public-exposure.md). |
| Web UI metrics coverage | Its load-balanced agent endpoint can show one agent instead of the fleet. Grafana aggregates all PodMonitor targets. Tracked in TALOS-xxio. |
| qBittorrent VPN control state | Production Gluetun still reports `stopping`; the gateway reports `running`. The disposable VPN test does not certify production VPN health. Tracked in TALOS-7tdi; no production tunnel was restarted by this audit. |
| AppSec optional CRS plugin warnings | Startup reports unmatched optional `crs-plugins/*` include patterns. No optional plugins are installed; native config loads and the engines are Ready. Do not globally suppress security logs to hide these messages. |
| Pod Security audit warnings | CrowdSec hostPath log collection and Traefik hostPorts intentionally violate baseline restrictions. These are audit-mode policy findings, not workload crashes. Keep them visible unless a narrowly scoped reviewed exception is introduced. |
| Dormant simulation entry | `LePresidente/http-generic-403-bf` is not installed. Its exclusion has no current effect but preserves the documented protection against reintroducing that known false-positive scenario in enforcement mode. |
| Full outage behavior | Bouncer retains cached decisions during bounded LAPI interruption and closes after repeated failures. This is not immediate detection of new attackers during an outage. Entire-node loss, database promotion, IPv6 WAN ingress and complete security-service loss are outside the completed test evidence. |

Source for the User-Agent contract: [CrowdSec v1.7.8 API-key middleware](https://github.com/crowdsecurity/crowdsec/blob/v1.7.8/pkg/apiserver/middlewares/v1/api_key.go).
