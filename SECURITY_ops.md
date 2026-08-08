# SECURITY_ops.md — the cluster's security-ops stack

## TL;DR

Layered, deception-driven defense for the Traefik ingress. Three cooperating systems:

- **CrowdSec** — the brain: an IPS that reads logs, detects attacks, and (via a bouncer) bans IPs.
- **Cowrie** — an SSH/Telnet **honeypot** (bait) that traps SSH attackers and feeds them to CrowdSec.
- **iocaine** — an AI-crawler **tarpit** (`trap.knowledgedump.space`) that poisons/wastes bad bots, plus
  **Bot Wrangler** (a Traefik plugin) that transparently proxies detected bots into it.

```
                                   ┌─────────────────── CrowdSec (IPS) ───────────────────┐
  Traefik access logs ───────────▶│ agent (parse) → LAPI (decisions DB) → bouncer (ban)  │
  k8s API audit log ─────────────▶│                     ↑                                 │
  Cowrie honeypot logs ──────────▶│         AppSec/WAF (:7422, detect-only)               │
  iocaine tarpit hits (detect) ──▶└───────────────────────────────────────────────────────┘
        ▲                                              │ decisions
  Bot Wrangler proxies bots → iocaine maze            ▼
                                              Traefik bouncer plugin  →  403 to banned IPs
```

**Status:** CrowdSec is detecting live; enforcement (the global bouncer bind) + Console enrollment are
being enabled with the 1Password `crowdsec` key (TALOS-e9h/pbn). Tarpit + AppSec run **detect-only**.

---

## The layers

| Layer | Namespace | Role | Feeds CrowdSec? |
|---|---|---|---|
| **CrowdSec LAPI + agent + AppSec** | `crowdsec` | Detection engine + decisions DB + WAF | — (it *is* the engine) |
| **crowdsec-bouncer-traefik-plugin** | `traefik` (plugin) | Enforcement — blocks banned IPs at L7 | — |
| **Cowrie honeypot** | `honeypot` | SSH/Telnet trap (bait) | ✅ (parser: TALOS-e9h) |
| **iocaine** tarpit + **Bot Wrangler** | `iocaine` / `traefik` | AI-crawler maze (`trap.knowledgedump.space`) + bot detection | ✅ detect-only (`homelab/iocaine-tarpit`) |

### CrowdSec (the brain)
- **agent** (DaemonSet, all nodes): reads logs, runs parsers + scenarios. Data sources:
  - Traefik JSON access logs (`crowdsecurity/traefik` + base-http scenarios + http-cve)
  - **k8s API-server audit log** (`crowdsecurity/k8s-audit`, talos00 `/var/log/audit/kube/…`) — detects
    secret reads, exec, RBAC/priv-esc, anonymous API access
  - Cowrie honeypot logs (parser in progress)
  - `homelab/iocaine-tarpit` scenario (tarpit-host hits) — **detect-only**
- **LAPI** (Deployment, on a worker — kept OFF talos00): the API bouncers query + the SQLite decisions DB.
- **AppSec/WAF** (`:7422`, detect-only): virtual-patching + OWASP CRS via the bouncer plugin.
- **Whitelist** (`homelab/whitelist` parser): RFC1918 + Cloudflare ranges are NEVER banned (anti-self-ban).
- **Bouncer** (`crowdsec-bouncer-traefik-plugin` in Traefik): **fail-open** (a CrowdSec outage can't take
  ingress down); real client IP resolved via Traefik `forwardedHeaders.trustedIPs` (Cloudflare).

### Cowrie (SSH honeypot / bait)
A fake, fully-emulated SSH/Telnet server. Any connection = a confirmed attacker (nobody legit SSHes a
decoy). It logs every login + command. Once its parser lands, a hit → `ssh-bf` scenario → ban.
Currently internal-only, so its RFC1918 sources are whitelisted (no bans until it's exposed publicly).

### iocaine (AI-crawler tarpit) + Bot Wrangler
`trap.knowledgedump.space` serves an **infinite procedurally-generated garbage maze** that wastes crawler
compute + poisons AI training scrapes. Two entry paths:
1. Direct hits on `trap.knowledgedump.space`.
2. **Bot Wrangler** (Traefik middleware, `botProxyUrl: http://iocaine.iocaine.svc:8080`) detects bad bots
   on protected routes and transparently proxies them into the maze (no redirect).

The `homelab/iocaine-tarpit` CrowdSec scenario turns any tarpit-host hit into an **alert** (detect-only
today; delete the `simulation.yaml` exclusion in `infrastructure/base/crowdsec/helmrelease.yaml` to ban).

---

## Enforcement status (what bans vs. logs)

| Signal | Detected | Enforced (bans) |
|---|---|---|
| Traefik HTTP scenarios (scanning, CVE probes, brute-force) | ✅ | ⏳ once the global bouncer bind is on |
| AppSec/WAF (virtual patching, CRS) | ✅ | ❌ detect-only (`default_remediation: allow`) |
| k8s API audit | ✅ | ⏳ (bouncer) |
| Cowrie honeypot | ⏳ parser (TALOS-e9h) | later (+ public exposure) |
| iocaine tarpit hits | ✅ | ❌ **detect-only** (simulation) — by design for now |
| Crowd blocklists (CAPI) | ⏳ Console enroll (TALOS-5of) | — |

Fail-safe: LAPI stream cache + `updateMaxFailure: -1` → a CrowdSec/AppSec outage **never** blocks ingress.

---

## Operations

- **Web UI**: `http://crowdsec.talos00` (Dashboard / Alerts / Decisions / Metrics — LAPI/Log-processor/AppSec)
- **Grafana**: "Security Ops — CrowdSec" (+ a Cowrie dashboard) in the *Security* folder
- **Console** (hosted, once enrolled): app.crowdsec.net — the richest ops view (CTI, attacker map)
- **CLI** (inside the LAPI/agent pod, or `Taskfile.security.yaml`):
  - `cscli alerts list` · `cscli decisions list`
  - `cscli decisions add --ip <ip> --duration 4h` / `cscli decisions delete --ip <ip>`
  - `cscli metrics` · `cscli collections list` · `cscli simulation status`

## Repo layout (today — see the consolidation note)

```
infrastructure/base/crowdsec/   # LAPI+agent+AppSec, bouncer middleware, whitelist, scenarios, web-ui
infrastructure/base/honeypot/   # Cowrie honeypot (+ logship sidecar)
infrastructure/base/iocaine/    # iocaine tarpit + trap.knowledgedump.space maze
infrastructure/base/traefik/    # bouncer plugin + Bot Wrangler middleware + forwardedHeaders
```

> **Consolidation** (deferred, TALOS-<see beads>): folding crowdsec/honeypot/iocaine into a shared
> `security` namespace + `infrastructure/base/security/` folder is planned but disruptive (workload moves,
> ref updates) and overlaps active honeypot work — do it as one coordinated pass, not piecemeal.

---

## Related Issues

- TALOS-pbn — CrowdSec IPS (bouncer + AppSec + Console + k8s-audit)
- TALOS-e9h — CrowdSec full loop: Cowrie parser + bind bouncer
- TALOS-mko — iocaine tarpit + Bot Wrangler
- TALOS-5of — Console enrollment · TALOS-2bz — Cilium L3/L4 network bouncer (idea)
