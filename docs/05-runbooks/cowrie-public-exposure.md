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
| Open internet, arbitrary port (e.g. `1.1.1.1:22`, C2 on `:4444`) | **blocked** |
| Open internet **:80 / :443** (public IPs only) | **REACHABLE — sample-fetch egress** |
| Any RFC1918 / LAN / pod-CIDR on :80/:443 | **blocked** (excluded from the egress rule) |
| kube-dns resolution | **REACHABLE** |

Cilium blocks pod→own-node egress here even though `enable-host-firewall=false`, which is
worth knowing because it is not the behaviour people assume from that flag.

There is no lateral movement into our networks, no outbound scanning of arbitrary
ports, no C2 callback on a non-web port, and no using this box against our own estate.
Egress is deliberately NOT zero — it permits 80/443 to **public** IPs so cowrie can fetch
the malware an attacker `wget`s (see *Sample Capture* below) — but every RFC1918 range,
the pod CIDR and link-local are excluded, so outbound reach stops at the public internet
and never touches anything of ours. That exclusion is the load-bearing control and is
mutation-tested; it must not be relaxed.

### Deliberate egress, and its residual channels

kube-DNS is the one permitted egress and it is **not** confined to cluster names:

- `github.com` resolves — CoreDNS performs **full internet recursion**. A compromised
  container can therefore exfiltrate data at low bandwidth by encoding it into subdomain
  labels of an attacker-controlled zone. This is a real, if slow, channel.
- Cluster-service names resolve, so the attacker gets a **guess-and-confirm topology
  oracle**: `argocd-server.argocd`, `nexus.registry` and `postgres.cnpg-system` all
  resolve. They cannot *connect* to any of them, but they can confirm what exists.
- Bulk enumeration is not available — the `any.any.svc.cluster.local` wildcard SRV trick
  returns NXDOMAIN on this CoreDNS.

Egress now also permits **80/443 to public IPs** so cowrie can retrieve the payloads
attackers instruct it to download — this is how malware SAMPLES are captured (see below).
The residual channels are therefore:

- **DNS exfil** (as above) — unchanged, still an accepted low-bandwidth channel.
- **Web egress to public hosts** — an attacker with RCE could use cowrie's outbound
  80/443 to fetch second-stage tooling or beacon over HTTP to a public C2. This is the
  cost of sample capture and is bounded to two ports and public IPs only; it can reach
  the internet but nothing of ours.

**These are accepted risks, not oversights.** Tightening either — an L7 DNS policy
restricting `matchPattern`, or dropping the web egress to give up sample capture — is a
change to the egress rule and therefore an operator decision. Do not implement as a side
effect of other work. Note the whole honeypot is slated to move to a physically isolated
Raspberry Pi (TALOS-1m1n), which retires this trade entirely.

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
| `var/lib/cowrie` storage | **retained PVC** (was emptyDir) — holds captured samples + tty logs |

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

## Sample Capture and Archival

The honeypot **keeps** what it captures. This was added after observing that egress was
DNS-only (so attacker `wget`s silently failed and no samples were ever collected) and that
`var/lib/cowrie` was an `emptyDir` (so downloads and session recordings were lost on every
pod restart).

**What is captured.** `var/lib/cowrie/downloads/` holds the actual malware samples an
attacker fetched, named by their **SHA-256**. `var/lib/cowrie/tty/` holds full interactive
session recordings, replayable with `cowrie playlog`. Neither is a log line, so the
`jsonlog` → Loki pipeline does not carry them — they need real storage.

**Where it lives, and why local.** `cowrie-var-lib` is a `honeypot-samples-retain`
StorageClass PVC — node-local (`local-path`), `Retain` reclaim. It is deliberately **not**
on the shared NFS export: this volume holds live malware, and NFS is mounted by a dozen
unrelated workloads. Node-local keeps the samples on one node, reachable from nothing else.
The old objection to a PVC (node-pinning vs the hostPort nodeSelector) no longer applies —
the deployment is hard-pinned to its node because the router forwards WAN:22 there.

**Off-node durability, via a job — the separation is the point.** A daily `cowrie-archive`
CronJob (`35 4 * * *`) tars the samples to NFS. cowrie itself has NO route to shared
storage; the job mounts the honeypot volume **read-only** and is the only thing that writes
to NFS. A cowrie RCE therefore stops at the local PVC instead of gaining write access to
storage other services read. The job carries no service-account token and is pinned to the
same node as the RWO capture volume.

**Nothing executes from the archive.** The archive PVC uses a dedicated
`honeypot-archive-nfs` StorageClass mounted `noexec,nosuid,nodev`; archives are written
`0400` under `umask 0077`; a `README.txt` lands beside them warning that the contents are
live malware and to extract with `--no-same-permissions --no-same-owner`. The job also
reports any captured sample that carries an exec bit (it cannot fix one — the source is
read-only by design — but the condition means cowrie's download path changed).

> **Handling rule:** every archive is live malware. Analyse only in an isolated VM. Never
> extract or execute on a workstation. The `noexec` mount and `0400` perms are a safety net,
> not permission to be careless.

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
