# Security stack — architecture

How detection, decision and enforcement fit together in this cluster. Read this before
changing a scenario, a profile, or anything that bans.

## TL;DR

- **CrowdSec** is the brain: it parses logs, decides, and stores decisions. It enforces nothing.
- **Bouncers** are the muscle. There are two enforcement planes, and they are separated by
  **decision type**, not by scenario.
- `type: ban` → Traefik plugin bouncers → HTTP services answer **429**.
- `type: silentdrop` → `haproxy-novelty-bouncer` → honeypot TCP connections are **silently dropped**.
- The honeypot is **deliberately left open** to attackers a `ban` applies to. That is the point of it.

## The components

| Component | Path | Role |
| --- | --- | --- |
| CrowdSec agents | `crowdsec/` | DaemonSet; parse logs, run scenarios, emit alerts |
| CrowdSec LAPI | `crowdsec/` | 2 replicas; holds decisions in CNPG Postgres |
| AppSec | `crowdsec/` | WAF, detect-only (`default_remediation: allow`) |
| Traefik bouncer | `../traefik/` | Plugin; enforces `ban` on HTTP routes |
| **haproxy-novelty-bouncer** | `honeypots/haproxy-novelty-bouncer/` | Sidecar; enforces `silentdrop` at the honeypot front |
| cowrie / beelzebub | `honeypots/` | SSH/telnet honeypots behind an haproxy VIP |
| iocaine | `iocaine/` | LLM-scraper tarpit; bot-wrangler proxies matched bots into it |

## Flow: log line → decision → enforcement

```
logs ──► CrowdSec agent ──► parser (s01) ──► whitelist (s02) ──► scenario ──► alert
                                                                               │
                                                                     profiles.yaml (ORDERED)
                                                                               │
                                                                        LAPI decision store
                                                                               │
                        ┌──────────────────────────────────────────────────────┴───────────┐
                        ▼                                                                  ▼
                 type: ban                                                        type: silentdrop
          Traefik plugin bouncers                                           haproxy-novelty-bouncer
          → 429 on every HTTP route                                    → haproxy map → silent-drop :2222/:2223
```

The whitelist (`homelab/whitelist`, s02-enrich) cancels events from RFC1918, the operator's
home IP and Cloudflare edges **before any scenario sees them**. It is the first line of
defence against banning yourself.

## Honeypot ingress

```
WAN :22/:23 ──► Cilium L2 VIP 192.168.1.238 ──► haproxy (honeypot-lb) ──┬── cowrie   (80% ssh, all telnet)
                                                                        └── beelzebub (20% ssh)
```

- haproxy speaks **PROXY v2 to cowrie** so cowrie logs the real attacker IP. It deliberately
  does **not** to beelzebub, which has no proxy-protocol support — so attribute beelzebub
  attackers from the haproxy tcplog, never from its own `event_SourceIp`.
- `stick on src` keeps each attacker on one honeypot across reconnects.
- The haproxy tcplog is what CrowdSec reads for `homelab/honeypot-vip-activity` — **the single
  ban source** for honeypot traffic.

## Why two enforcement planes

A `ban` from touching the honeypot is meant to protect *everything else*. It intentionally
does not close the honeypot, because an attacker who keeps interacting keeps producing
intelligence. That is why a banned IP could still run 1,432 cowrie sessions.

`silentdrop` exists for the opposite case: an attacker who has stopped producing intelligence.
Measured 2026-09-17 over 8,379 command events from 45 IPs, 14 IPs replaying near-identical
payloads produced **94% of all command volume** while contributing almost nothing new.

| | commands | distinct | sessions |
| --- | --- | --- | --- |
| replay bot | 1,432 | **1** | 1,432 |
| real explorer | 31 | **24** | **1** |

`homelab/cowrie-replay-drop` catches the first shape and not the second: ≥30 commands with
≤8 distinct. Its decision is `silentdrop`, so only the honeypot front acts on it — what
Traefik blocks is unchanged.

## Scenarios and their remediation

| Scenario | Fires on | Decision | Enforced by |
| --- | --- | --- | --- |
| `homelab/honeypot-vip-activity` | any honeypot connection | `ban` 4h escalating | Traefik bouncers |
| `homelab/cowrie-replay-drop` | ≥30 cmds, ≤8 distinct | `silentdrop` 168h | haproxy-novelty-bouncer |
| `homelab/iocaine-tarpit` | reached the tarpit host | — (simulated) | nothing yet |

`profiles.yaml` is **ordered** and every profile uses `on_success: break`. The
`cowrie_replay_drop` profile sits *above* `default_ip_remediation`, which is the only reason
the replay scenario produces a drop instead of a second ban. **Order is load-bearing — do not
reorder it.**

## Rolling out a new scenario safely

1. Add it under `config.scenarios` in the CrowdSec HelmRelease.
2. **Add its runtime `name:` to `simulation.yaml` exclusions in the same commit.** `simulation:
   false` makes that list *inverted* — being listed means alert-only.
3. Soak. Simulated decisions are flagged `simulated: true`; both bouncers skip them, and no
   Discord message is sent. Watch with `cscli alerts list --scenario <name>` and the
   `crowdsec-ops` dashboard (its trigger panel **includes** simulation — an overflow is not
   proof of a ban).
4. Promote by deleting the exclusion line, once it has alerted on an IP that is not yours and
   produced no operator false positives.

## Hard-won constraints

- **Never make a scenario that matches HTTP 403.** Nine installed scenarios count 403 as
  evidence, so a 403 remediation manufactures its own confirming evidence. That is the
  2026-08-20 incident: a 32-hour SSO lockout. The bouncer answers **429** for this reason;
  changing it back re-opens the loop.
- **Never let a honeypot scenario issue a second ban.** Cowrie acquisition was removed once
  already (`35ade7f5`) because two scenarios were banning the same IP.
- **Never silent-drop RFC1918.** The haproxy ACL carries an explicit `!is_private` guard,
  independent of the CrowdSec whitelist, because LAN is the recovery path.
- **subPath ConfigMap mounts are frozen at pod start.** All honeypot configs are generated via
  `configMapGenerator` so the hash changes and the pod rolls. Never convert them to static
  ConfigMaps.
- **The operator allowlist is fragile.** `homelab/whitelist` pins a *residential* IP that
  rotates; `crowdsec-allowlist-refresher` tracks it. If you are locked out, check that value
  first.
  (This bullet previously asserted the refresher "is currently failing". It was Complete and
  refreshing normally within a day of that being written. Do not record live state in an
  architecture doc -- it rots silently and then misleads exactly the person debugging an
  outage. Health belongs in alerts; these files should carry only invariants.)

## Falco rule provenance — the upstream ruleset is NOT in git

Falco's detections come from two places, and only one of them is version-controlled.

| | Where | Pinned? |
| --- | --- | --- |
| Our rules (`Honeypot Container Breach`, …) | `customRules` in the Falco HelmRelease | yes, in git |
| Upstream base ruleset (~100 rules, 64KB) | `ghcr.io/falcosecurity/rules/falco-rules:5` | **no** |

A `falcoctl-artifact-follow` sidecar runs in every Falco pod and polls that ref **every 168h**.
`:5` is a *floating major tag*, so any upstream 5.x release lands here and Falco hot-reloads
it — no commit, no PR, no review, no rollback path. This is the chart default; we configure
nothing.

This is a deliberate choice, not an oversight: rules are threat detection, and pinning them
means detections go stale until a human remembers to bump. The trade is that detection
behaviour can change underneath you — and since CRITICAL now routes to Discord, **that
includes what pages you at 4am**.

So the change is made *attributable* instead of silent. The `falco-ops` dashboard has a
**Rule provenance** row showing exactly when the upstream ruleset moved:

```logql
{namespace="falco", container="falcoctl-artifact-follow"}
  |~ "Found new artifact version|Artifact correctly installed"
```

**If Falco suddenly starts paging with a new false positive, or a detection goes quiet, check
that panel first.** Empty is the normal state. falcoctl logs `Nothing to do, artifact already
up to date.` on every no-op check including at pod start, so only real changes show up.

There is no *alert* on this yet, only a panel — see the beads issue. Alerting on it needs a
log-based rule, and this cluster has no path for one today: Grafana-managed alerting has only
the stub `email receiver` contact point, and Loki's ruler has a bucket but no ruler config.
Every working alert here is `PrometheusRule → Mimir → Alertmanager → Discord`, which cannot
query logs.

## Operations

```sh
# who is enforcing, and is it alive?
cscli bouncers list          # expect traefik@* rows AND haproxy-novelty-bouncer

# what has fired, and is it simulated?
cscli alerts list --scenario homelab/cowrie-replay-drop
cscli decisions list --type silentdrop

# what is actually being dropped at the honeypot right now
kubectl -n honeypot exec deploy/honeypot-lb -c haproxy -- \
  sh -c 'echo "show map /usr/local/etc/haproxy/replay.map" | socat stdio /var/run/haproxy/admin.sock'

# honeypot command volume (should collapse ~94% once the replay scenario is promoted)
kubectl -n honeypot exec deploy/cowrie -c logship -- \
  sh -c 'grep -c cowrie.command.input /var/log/cowrie/cowrie.json'
```

## Related

- `docs/02-architecture/security-ops.md` — operational detail: CrowdSec + bouncer, honeypot,
  iocaine, allowlists, ban escalation
- `traefik/middlewares.yaml` — bot-wrangler, lan-only, rate-limit, header stripping
- `docs/05-runbooks/crowdsec-verification.md` — how to read the dashboards without fooling yourself
