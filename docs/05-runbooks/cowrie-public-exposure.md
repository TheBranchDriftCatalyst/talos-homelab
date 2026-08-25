# Cowrie Honeypot — Public Exposure Runbook

## TL;DR

The Cowrie SSH honeypot is **staged for internet exposure but not yet exposed**. Every
manifest change is done; the only remaining step is a router port-forward the operator
performs by hand.

- **Go live:** forward `WAN:22 → 192.168.1.19:2222` (talos06). Nothing else.
- **Do NOT forward telnet (2223).** Rationale below.
- **The container can reach nothing** except kube-DNS — verified by probing, not by reading
  the policy file. This is the control that makes "attacker logs in successfully" a
  non-event.
- **Never add an egress rule** to `infrastructure/base/honeypot/cilium-network-policy.yaml`.
- Durable record is Loki (30d). In-pod logs are emptyDir and are lost on reschedule.

---

## Quick Reference

### Going live

```bash
# 1. Confirm the pod is where you think it is. hostPort binds on the NODE, so if
#    cowrie reschedules, the forward target IP is wrong and capture goes silent.
kubectl get pod -n honeypot -l app=cowrie -o wide

# 2. Forward on the router:   WAN:22  ->  192.168.1.19:2222
#    (no manifest in this repo creates this path — that is deliberate)

# 3. Confirm from OFF-network (phone hotspot, not the LAN):
ssh -p 22 root@<your-wan-ip>          # expect a password prompt, any password works

# 4. Confirm capture, filtering out probe noise:
#    Grafana -> ops-security -> "Cowrie Ops"
```

### Confirming it actually works

The failure mode of this system is **silence**, and silence is also what success looks
like before anyone finds you. Distinguish them explicitly:

```logql
# Real external traffic only — pod-CIDR probe noise removed
{namespace="honeypot", container="logship"} | json
  | src_ip!="" | src_ip!~`10.244..*` | src_ip!~`192.168.1..*`
```

If that returns nothing an hour after the forward is live, the forward is not working —
a public SSH port is normally found by mass scanners within minutes.

### Rolling back

Remove the port-forward at the router. No manifest change is required; the
`fromEntities: [world]` policy rule is inert without an inbound path.

---

## Blast-Radius Assessment

> Re-verify this section before widening anything. Measured 2026-08-24 against the live
> pod, by probing from inside the pod's network namespace — not by reading manifests.

### What an attacker who fully compromises the container can reach

Cowrie is a *fake* shell: commands are emulated, so ordinary honeypot "sessions" have no
code execution at all. This section assumes the stronger case — genuine RCE in the Cowrie
Python process, i.e. the attacker has real network access from inside the pod.

| Target | Result |
| --- | --- |
| talos06 apid `:50000` (its own node) | **blocked** |
| talos06 kubelet `:10250` | **blocked** |
| talos06 kube-apiserver `:6443` | **blocked** |
| Every other node (talos00/01/02/03) | **blocked** |
| `kubernetes.default` `10.96.0.1:443` | **blocked** |
| LAN gateway `192.168.1.1:80/443` | **blocked** |
| Open internet (`1.1.1.1:443`, `8.8.8.8:53`) | **blocked** |
| kube-dns resolution | **REACHABLE — the only egress** |

Cilium blocks pod→own-node egress here even though `enable-host-firewall=false`, which is
worth knowing because it is not the behaviour people assume from that flag.

There is no lateral movement, no outbound scanning, no C2 callback, no bulk exfil and no
using this box as a DDoS reflector. That is the entire point of the default-deny egress
policy and it is why it must not be relaxed.

### The residual hole: DNS

kube-DNS is the one permitted egress and it is **not** confined to cluster names:

- `github.com` resolves — CoreDNS performs **full internet recursion**. A compromised
  container can therefore exfiltrate data at low bandwidth by encoding it into subdomain
  labels of an attacker-controlled zone. This is a real, if slow, channel.
- Cluster-service names resolve, so the attacker gets a **guess-and-confirm topology
  oracle**: `argocd-server.argocd`, `nexus.registry` and `postgres.cnpg-system` all
  resolve. They cannot *connect* to any of them, but they can confirm what exists.
- Bulk enumeration is not available — the `any.any.svc.cluster.local` wildcard SRV trick
  returns NXDOMAIN on this CoreDNS.

**This is an accepted risk, not an oversight.** Closing it means an L7 DNS policy
restricting `matchPattern` to `*.cluster.local`, which is a change to the egress rule and
therefore an operator decision. Tracked separately; do not implement it as a side effect
of other work.

### hostPort exposure

`hostPort: 2222/2223` binds the port on **talos06 itself**, bypassing Service routing.
Consequences:

- Anyone who can reach `192.168.1.19:2222` reaches Cowrie. After the forward, that is the
  internet.
- Only the two honeypot ports are bound. hostPort does **not** grant the container access
  to the node's other services — verified above, all blocked.
- Talos runs **no SSH daemon**, and port 22 is closed on all five nodes. Forwarding
  `WAN:22` cannot collide with real administrative SSH because there is none.
- One cowrie per node is implied by the port binding.

### Container security posture

| Control | State |
| --- | --- |
| `runAsNonRoot` / `runAsUser` | true / 1000 |
| `allowPrivilegeEscalation` | false |
| Capabilities | **all dropped** |
| `readOnlyRootFilesystem` (cowrie) | **false** — see below |
| `readOnlyRootFilesystem` (logship) | true |
| Namespace PSS | `enforce: privileged` (required for hostPort) |

`readOnlyRootFilesystem: false` on the cowrie container is the weakest control here.
Cowrie writes SSH host keys and a PID file into its working tree, so making the root
filesystem read-only requires additional emptyDir mounts for `var/run` and `etc/ssh`.
That is worth doing but was **deliberately not changed immediately before go-live** —
destabilising a working honeypot to gain a control that only matters post-RCE is a bad
trade on the day of exposure. Tracked as a follow-up.

### Does the honeypot leak the real estate?

No. Checked specifically, because a honeypot that advertises your real infrastructure is
a liability:

- Advertised hostname is `srv01` — a generic invention that matches nothing in this
  estate (real nodes are `talos00`–`talos06`).
- SSH banner is `SSH-2.0-OpenSSH_8.9p1 Ubuntu-3ubuntu0.1` — a plausible fake; the nodes
  run Talos, which has no SSH daemon at all.
- The fake filesystem and credential database are stock upstream images; nothing in
  `configmap.yaml` overrides them with local usernames, hostnames or paths.
- No real secret, token or internal DNS name is mounted into the pod.

---

## Log Volume and Retention

Checked rather than assumed; **no sizing change is needed** before go-live.

Measured on the live pod: ~360 bytes per event.

| Concern | Headroom |
| --- | --- |
| Loki retention | 720h (30d), global |
| Loki ingestion cap | 10 MB/s ≈ 864 GB/day. A busy honeypot at 50k events/day is ~18 MB/day — about 0.002% of the cap. |
| Loki streams | `max_streams_per_user: 5000`; cowrie contributes **1**. |
| talos06 ephemeral storage | ~836 GiB allocatable. |

In-pod logs live on an **unbounded emptyDir** and are lost whenever the pod reschedules.
Given 836 GiB of node disk, filling it would take years even at heavy honeypot volume, so
this is not a go-live blocker. Adding `sizeLimit` to the two emptyDirs remains cheap
insurance — it would convert a hypothetical node-wide eviction cascade into "the honeypot
pod alone is evicted" — but it introduces a new eviction behaviour and was left as an
operator decision rather than changed unrequested.

**Loki is the durable record.** Do not treat the in-pod files as an archive.

---

## Open Decisions (not implemented — operator's call)

1. **Telnet on 2223 — recommend NOT exposing.** It roughly doubles the attack surface and
   the log volume for a protocol whose scanner traffic is overwhelmingly IoT-botnet
   credential stuffing that Cowrie's SSH side already characterises. Expose it later if
   you specifically want telnet-botnet data; there is no reason to take it on day one.
2. **First-contact alerting.** There is no path today to alert on Cowrie data: alerts in
   this cluster are `PrometheusRule` CRDs synced by Alloy's `mimir.rules.kubernetes` into
   the **Mimir** ruler, and Cowrie's data is **log** data in Loki. No Loki ruler and no
   `loki.rules.kubernetes` component exists. See the follow-up ticket for the recommended
   approach (derive a counter from the log stream in Alloy, then alert on the metric in
   Mimir) and for why simply adding a Loki ruler is hazardous here. — **TALOS-qmj9**
3. **DNS confinement.** See "The residual hole" above. — **TALOS-b6ky**
4. **`readOnlyRootFilesystem: true`** on the cowrie container, and `sizeLimit` on the two
   emptyDirs. — **TALOS-rr8b**

---

## Related Issues

- **TALOS-ezcu** — the port-forward itself. OPERATOR ACTION, deliberately not automated.
  Its hardening gate is now met: all 14 `honeypot-security` tests pass.
- **TALOS-ik9o** — public-exposure epic (its description was stale on the node/IP and on
  whether the netpol admitted external traffic; corrected in comments).
- **TALOS-qmj9** — first-contact alerting (proposed, not built).
- **TALOS-b6ky** — DNS-tunnelling exfil pentest. The pivotal question is answered:
  CoreDNS *does* recurse to the internet.
- **TALOS-rr8b** — deferred hardening (readOnlyRootFilesystem, emptyDir sizeLimit).
- TALOS-u3l — honeypot deployment and its exposure posture
- TALOS-hg7 — honeypot epic
- TALOS-l05 / TALOS-e9h — log shipping and CrowdSec acquisition

## Verification State

Everything in this runbook was measured against the live cluster on 2026-08-24, not
inferred from manifests. Re-run the acceptance suite before and after any change here:

```bash
cd infrastructure/base/honeypot/tests && npx jest --runInBand   # expect 14/14
```
