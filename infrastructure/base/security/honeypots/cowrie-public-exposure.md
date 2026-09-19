---
type: runbook
status: current
covers:
  - honeypots
freshness: tracks-code
tickets:
  - TALOS-ik9o
  - TALOS-b6ky
  - TALOS-rr8b
  - TALOS-qmj9
  - TALOS-1m1n
blurb: Taking the honeypot on and off the internet, and the containment analysis that makes a successful attacker login a non-event.
---

# Cowrie honeypot — public exposure

The premise of an SSH honeypot is that attackers reach it and succeed at logging in. A set of
individually quiet controls is what stands between "useful sensor" and "beachhead inside the
LAN". This runbook is how to put the trap on the internet, how to confirm it is working, how
to take it back off, and — the long half — what an attacker who fully compromises it can
actually reach.

Read [README.md](README.md) first for the topology; this file assumes it.

## TL;DR

- **The WAN path is declared in the repo**, not configured by hand. The honeypot VIP Service
  carries a port-forward annotation that the UniFi port-forward operator reconciles onto the
  router. Going live and rolling back are both manifest changes.
- **The container can reach nothing of ours.** Its one outbound allowance is 80/443 to
  **public** addresses, with every private range excluded. That exclusion is the control that
  makes "attacker logs in successfully" a non-event.
- **Never add an egress rule to `cilium-network-policy.yaml`** without treating it as the
  security decision it is.
- Loki is the durable record for log lines; samples and session recordings are binary and
  live on the capture volume.

## Quick reference

### Going live

1. Confirm the forward the repo declares. `vip.yaml` carries the
   `unifi-port-forward.fiskhe.st/mapping` annotation; the operator adopts a matching live
   forward by WAN port and applies it. There is no manual router step, and the standalone
   rule that used to carry this forward was deliberately removed in favour of the owning
   Service declaring it.
2. Confirm the VIP has its address and that the announcing node holds a backend. The
   announcement is pinned to the node the honeypots run on because the Service is
   `externalTrafficPolicy: Local` and a Local service refuses to announce without a local
   endpoint.

   ```bash
   kubectl -n honeypot get svc honeypot-vip -o wide
   kubectl -n honeypot get pods -l app=honeypot-lb -o wide
   ```

3. Confirm from **off-network** — a phone hotspot, not the LAN. LAN sources are exempt from
   every guard in the front, so a test from the LAN proves nothing about the WAN path.

   ```bash
   ssh -p 22 root@<your-wan-ip>     # expect a password prompt; any password is accepted
   ```

4. Confirm capture in Grafana's honeypot dashboard.

### Confirming it actually works

The failure mode of this system is **silence**, and silence is also what success looks like
before anyone has found you. Distinguish them explicitly — filter out the probe noise that
originates inside the cluster:

```logql
{namespace="honeypot", container="logship"} | json
  | src_ip!="" | src_ip!~`10.244..*` | src_ip!~`192.168.1..*`
```

If that returns nothing an hour after the forward is live, the forward is not working. A
public SSH port is normally found by mass scanners within minutes.

Remember that **beelzebub cannot see past the proxy** — attribute its attackers from the
front's tcplog, never from its own source field.

### Rolling back

Remove the mapping annotation from `vip.yaml` and let Flux reconcile. The
`fromEntities: [world]` rule in the network policy is inert without an inbound path, so no
policy change is needed or wanted.

## Blast-radius assessment

> The reachability results below were established by **probing from inside the pod's network
> namespace on 2026-08-24**, not by reading manifests. The policy they describe is still the
> policy in `cilium-network-policy.yaml`. Re-probe before widening anything.

### What an attacker who fully compromises the container can reach

Cowrie is a _fake_ shell: commands are emulated, so an ordinary honeypot session involves no
code execution at all. This section assumes the stronger case — genuine remote code execution
in the Cowrie process, so the attacker has real network access from inside the pod.

| Target                                                                   | Result                                      |
| ------------------------------------------------------------------------ | ------------------------------------------- |
| Its own node's apid, kubelet and apiserver ports                         | **blocked**                                 |
| Every other node                                                         | **blocked**                                 |
| The in-cluster `kubernetes` Service                                      | **blocked**                                 |
| The LAN gateway                                                          | **blocked**                                 |
| The open internet on an arbitrary port — a C2 callback on a non-web port | **blocked**                                 |
| The open internet on **80/443**, public addresses only                   | **reachable — this is the sample fetch**    |
| Any private range on 80/443                                              | **blocked** — excluded from the egress rule |
| kube-dns resolution                                                      | **reachable**                               |

Cilium blocks pod-to-own-node egress here even with the host firewall disabled, which is
worth knowing because it is not the behaviour that flag's name suggests.

There is no lateral movement into our networks, no outbound scanning of arbitrary ports, no
command-and-control on a non-web port, and no using this box against our own estate. Egress
is deliberately **not** zero — the honeypot is far more useful if the malware an attacker
fetches actually arrives — but every private range, the pod CIDR and link-local are excluded,
so its outbound reach stops at the public internet.

**That exclusion list is the load-bearing control and it is mutation-tested. It must not be
relaxed.**

### Deliberate egress, and its residual channels

Two channels are knowingly accepted rather than closed.

**DNS is not confined to cluster names.** CoreDNS performs full internet recursion, so a
compromised container can exfiltrate at low bandwidth by encoding data into subdomain labels
of an attacker-controlled zone. Cluster service names also resolve, which gives a
guess-and-confirm topology oracle — an attacker can confirm that a given service exists
without being able to connect to it. Bulk enumeration is not available; the wildcard SRV
trick returns NXDOMAIN here.

**Web egress to public hosts.** An attacker with code execution can use the same 80/443
allowance to fetch second-stage tooling or beacon over HTTP to a public host. This is the
price of sample capture, and it is bounded to two ports and public addresses.

Both are **accepted risks, not oversights.** Tightening either — an L7 DNS policy, or
dropping web egress and giving up sample capture — is a change to the egress rule and
therefore an operator decision. Do not make it as a side effect of other work. Moving the
honeypot to physically isolated hardware retires the trade entirely, and is tracked
separately.

### Container security posture

| Control                             | State                                                  |
| ----------------------------------- | ------------------------------------------------------ |
| `runAsNonRoot`                      | true, for every container in the namespace             |
| `allowPrivilegeEscalation`          | false                                                  |
| Capabilities                        | all dropped                                            |
| Seccomp                             | `RuntimeDefault`, set pod-level so sidecars inherit it |
| Service-account token               | not projected — see [README.md](README.md#the-cage)    |
| `readOnlyRootFilesystem` (cowrie)   | **false** — see below                                  |
| `readOnlyRootFilesystem` (sidecars) | true                                                   |
| Namespace Pod Security Standard     | `baseline` enforced                                    |

`readOnlyRootFilesystem: false` on the cowrie container is the weakest control here. Cowrie
writes SSH host keys and a PID file into its working tree, so a read-only root needs extra
writable mounts. That is worth doing, but it was deliberately not done immediately before
go-live: destabilising a working honeypot to gain a control that only matters _after_ remote
code execution is a bad trade on the day of exposure. Tracked as follow-up work.

### Does the honeypot leak the real estate?

No — checked specifically, because a honeypot that advertises your real infrastructure is a
liability rather than an asset.

- The advertised hostname is a generic invention that matches nothing in this estate.
- The SSH banner is a plausible mainstream Linux distribution. The real nodes run Talos,
  which has no SSH daemon at all, so the banner cannot correlate with anything.
- The fake filesystem and credential database come from the stock upstream image. The
  fingerprint-hardening overrides replace dated hardware details with a generic modern
  profile; none of them name anything local.
- No real secret, token or internal DNS name is mounted into the pod.

## Sample capture and archival

The honeypot **keeps** what it captures. This exists because egress was once DNS-only, so
attacker downloads silently failed and no sample was ever collected — and because the capture
directory was ephemeral, so anything that did arrive was destroyed on the next restart.

Downloads are named by their content hash; session recordings are replayable with
`cowrie playlog`. Neither is a log line, so the Loki pipeline does not carry them. The full
storage design — why node-local rather than NFS, why the archive job mounts the source
read-only, and why the archive volume is `noexec` — is in
[README.md](README.md#captured-artifacts-never-touch-shared-storage-directly).

> **Handling rule:** every archive is live malware. Analyse only in an isolated VM. Never
> extract or execute one on a workstation. The `noexec` mount and the restrictive permissions
> are a safety net, not permission to be careless. Extract with
> `--no-same-permissions --no-same-owner`.

## Log volume and retention

Checked rather than assumed; **no sizing change is needed** before go-live. Measured at
roughly 360 bytes per event on the live pod, a busy honeypot is a rounding error against
Loki's ingestion cap and contributes a single stream. The node has hundreds of gigabytes of
ephemeral storage, so the in-pod log volume could not realistically fill it.

In-pod logs still live on an unbounded ephemeral volume and are lost whenever the pod
reschedules. **Loki is the durable record** — do not treat the in-pod files as an archive.
Adding a size limit to those volumes remains cheap insurance: it would convert a hypothetical
node-wide eviction cascade into "the honeypot pod alone is evicted". It introduces a new
eviction behaviour, so it is left as an operator decision rather than changed unrequested.

## Open decisions

1. **Telnet.** Exposing it roughly doubles the attack surface and the log volume for a
   protocol whose scanner traffic is overwhelmingly IoT-botnet credential stuffing that the
   SSH side already characterises. The repo currently declares forwards for both protocols;
   narrowing to SSH alone is an edit to the mapping annotation in `vip.yaml`.
2. **First-contact alerting.** There is no alert on honeypot data. Every working alert in this
   cluster is a `PrometheusRule` reconciled into Mimir, and Mimir cannot query logs. The
   recommended approach is to derive a counter from the log stream in Alloy and alert on the
   metric — not to stand up a second ruler. — TALOS-qmj9
3. **DNS confinement.** See the residual channels above. — TALOS-b6ky
4. **`readOnlyRootFilesystem: true`** on the cowrie container, and size limits on the
   ephemeral log volumes. — TALOS-rr8b

## Verifying before and after any change here

```bash
task test:security     # the whole security-posture marker, every co-located suite

# or scope it to this component's suite, from the repo root:
python3 -m pytest -m security_posture infrastructure/base/security/honeypots/tests
```

The honeypot suite is co-located at `tests/` in this directory. Every check is read-only, and
checks **skip** rather than silently pass when the cluster is unreachable. Read the assertion
rationale at the top of `tests/test_honeypot_security.py` before "fixing" a failure by
relaxing a test.

## Related Issues

- TALOS-ik9o — public-exposure epic
- TALOS-qmj9 — first-contact alerting on honeypot data (proposed, not built)
- TALOS-b6ky — DNS-tunnelling exfiltration assessment; CoreDNS does recurse to the internet
- TALOS-rr8b — deferred hardening: read-only root, ephemeral volume size limits
- TALOS-1m1n — move the honeypot to physically isolated hardware, retiring the egress trade
