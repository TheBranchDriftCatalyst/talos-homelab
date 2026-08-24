# SECURITY_ops.md — the cluster's security-ops stack

## TL;DR

Layered, deception-driven defense for the Traefik ingress. Three cooperating systems:

- **CrowdSec** — the brain: an IPS that reads logs, detects attacks, and (via a bouncer) bans IPs.
- **Cowrie** — an SSH/Telnet **honeypot** (bait) that traps SSH attackers and feeds them to CrowdSec.
- **iocaine** — an AI-crawler **tarpit** (`trap.knowledgedump.space`) that poisons/wastes bad bots, plus
  **Bot Wrangler** (a Traefik plugin) that transparently proxies detected bots into it.

```
                                   ┌─────────────────── CrowdSec (IPS) ───────────────────┐
  Traefik access logs ───────────▶│ agent (parse) → LAPI (Postgres DB) → bouncer (ban)   │
  App auth logs (Authentik+) ────▶│                     ↑                                 │
  k8s API audit log ─────────────▶│         AppSec/WAF (:7422, detect-only)               │
  Cowrie honeypot logs ──────────▶│                                                       │
  iocaine tarpit hits (detect) ──▶└───────────────────────────────────────────────────────┘
        ▲                                              │ decisions
  Bot Wrangler proxies bots → iocaine maze            ▼
                                              Traefik bouncer plugin  →  403 to banned IPs
```

**Status:** fully live. The bouncer is bound globally on the `web` and `websecure` entrypoints
(`--entrypoints.<ep>.http.middlewares=traefik-bouncer@kubernetescrd`), the instance is Console-enrolled
(CAPI signal sharing + community blocklist pull — tens of thousands of active CAPI decisions), and
the LAPI datastore is CNPG Postgres. Tarpit + AppSec still run **detect-only**, as do the wave-1/2
app brute-force scenarios (TALOS-wdwm).

---

## The layers

| Layer | Namespace | Role | Feeds CrowdSec? |
|---|---|---|---|
| **CrowdSec LAPI + agent + AppSec** | `crowdsec` | Detection engine + CNPG Postgres decisions DB + WAF | — (it *is* the engine) |
| **crowdsec-bouncer-traefik-plugin** | `traefik` (plugin) | Enforcement — blocks banned IPs at L7 | — |
| **Cowrie honeypot** | `honeypot` | SSH/Telnet trap (bait) | ✅ (`homelab/cowrie-logs` → `homelab/cowrie-activity`) |
| **iocaine** tarpit + **Bot Wrangler** | `iocaine` / `traefik` | AI-crawler maze (`trap.knowledgedump.space`) + bot detection | ✅ detect-only (`homelab/iocaine-tarpit`) |

### CrowdSec (the brain)
- **agent** (DaemonSet, all nodes): reads logs, runs parsers + scenarios. Data sources:
  - Traefik JSON access logs (`crowdsecurity/traefik` + base-http scenarios + http-cve)
  - **App auth logs** — pod-log acquisition straight from the apps, so a brute-force that gets *past*
    the proxy is still seen: Authentik, Jellyfin, Plex, Grafana, Sonarr/Radarr/Prowlarr, SABnzbd,
    qBittorrent, Audiobookshelf, Immich, Home Assistant, LiteLLM, MongoDB. The `program:` value in
    each acquisition must match the hub parser's filter exactly or it silently never fires.
    (Forgejo is deliberately absent — its router lines don't match `LePresidente/gitea-logs`.
    Plex/Immich/LiteLLM ship parsers only, no scenarios — `crowdsecurity/plex` is an *allowlist*.)
  - **k8s API-server audit log** (`crowdsecurity/k8s-audit`, talos00 `/var/log/audit/kube/…`) — detects
    secret reads, exec, RBAC/priv-esc, anonymous API access
  - Cowrie honeypot logs (`homelab/cowrie-logs` parser → `homelab/cowrie-activity` scenario)
  - `homelab/iocaine-tarpit` scenario (tarpit-host hits) — **detect-only**
- **LAPI** (Deployment, on a worker — kept OFF talos00): the API bouncers query. Its datastore is the
  `crowdsec-postgres` CNPG cluster (3 instances on `fatboy-nfs-appdata`, barman-cloud backups to MinIO),
  **not** SQLite — the old SQLite-on-local-path was node-pinned and wiped every registered machine on
  any LAPI reschedule. LAPI is now stateless and reschedules freely.
- **AppSec/WAF** (`:7422`, detect-only): virtual-patching + OWASP CRS via the bouncer plugin.
- **Whitelist** (`homelab/whitelist` parser): RFC1918 + Cloudflare ranges are NEVER banned (anti-self-ban).
  Backed by a **dynamic allowlist** (`homelab-operator`, `dynamic-allowlist.yaml`): a CronJob every
  30 min re-adds the operator's current public IP to a LAPI-side `cscli allowlist` with a 3h TTL,
  because the static entry is a dynamic residential address that rotates (it caused a 32h SSO lockout
  — TALOS-y260). The same file also ships `crowdsec-bouncer-pruner` (daily) — each Traefik pod
  auto-registers its own bouncer, so stale entries accumulate live API keys; it prunes anything
  idle >24h.
- **Bouncer** (`crowdsec-bouncer-traefik-plugin` in Traefik): **fail-open** (a CrowdSec outage can't take
  ingress down); real client IP resolved via Traefik `forwardedHeaders.trustedIPs` (Cloudflare).

### Cowrie (SSH honeypot / bait)
A fake, fully-emulated SSH/Telnet server. Any connection = a confirmed attacker (nobody legit SSHes a
decoy). It logs every login + command. There is no `crowdsecurity/cowrie` hub item, so the loop is
custom: the `logship` sidecar tails `cowrie.json` to stdout → `homelab/cowrie-logs` parser →
`homelab/cowrie-activity` trigger scenario (bans on the first event; `share_custom: true` forwards it
to CAPI as a max-confidence CTI signal). It is **not** in `simulation.yaml`, so it enforces.
Reached on hostPort 2222/2223 on talos03 (bypasses Traefik), so a ban never stops engagement.
Still internal-only, so in practice its RFC1918 sources are whitelisted and nothing gets banned until
it's exposed publicly (TALOS-ik9o).

### iocaine (AI-crawler tarpit) + Bot Wrangler
`trap.knowledgedump.space` serves an **infinite procedurally-generated garbage maze** that wastes crawler
compute + poisons AI training scrapes. Two entry paths:
1. Direct hits on `trap.knowledgedump.space` (plus `http://trap.talos00` for viewing it from the LAN).
2. **Bot Wrangler** (Traefik middleware `bot-wrangler` in ns `traefik`,
   `botProxyUrl: http://iocaine.iocaine.svc.cluster.local:8080`) detects bad bots and transparently
   proxies them into the maze (no redirect). Attached **per-route**, not on an entrypoint — today only
   the Forgejo and whoami IngressRoutes.

The `homelab/iocaine-tarpit` CrowdSec scenario turns any tarpit-host hit into an **alert** (detect-only
today; delete the `simulation.yaml` exclusion in `infrastructure/base/crowdsec/helmrelease.yaml` to ban).

---

## Enforcement status (what bans vs. logs)

| Signal | Detected | Enforced (bans) |
|---|---|---|
| Traefik HTTP scenarios (scanning, CVE probes, brute-force) | ✅ | ✅ bouncer bound on `web` + `websecure` |
| AppSec/WAF (virtual patching, CRS) | ✅ | ❌ detect-only (`default_remediation: allow`) — TALOS-t1w/db26 |
| k8s API audit | ✅ | ✅ (bouncer) |
| App brute-force scenarios (Authentik, *arr, Jellyfin, Grafana, …) | ✅ | ❌ **detect-only** on arrival — promotion review TALOS-wdwm |
| `LePresidente/http-generic-403-bf` | ✅ | ❌ **demoted to detect-only** — self-reinforcing, only ever caught the operator (TALOS-y260) |
| Cowrie honeypot | ✅ `homelab/cowrie-activity` | ✅ enforcing, but sources are RFC1918-whitelisted until public exposure (TALOS-ik9o) |
| iocaine tarpit hits | ✅ | ❌ **detect-only** (simulation) — by design for now |
| Crowd blocklists (CAPI) | ✅ enrolled (COMMUNITY) | ✅ pulled + enforced (tens of thousands of live CAPI decisions) |

Fail-safe: LAPI stream cache + `updateMaxFailure: -1` → a CrowdSec/AppSec outage **never** blocks ingress.

Bans escalate: `profiles.yaml` sets `duration_expr` to `(prior decisions + 1) * 4h`, and every ban is
POSTed to Discord via the built-in `notification-http` plugin (`discord_default`).

---

## Operations

- **Web UI**: `https://crowdsec.talos00` — LAN-only + Authentik forward-auth (`talos-admin`). Expect a
  double login: the web-ui has its own LAPI machine account on top of SSO.
- **Grafana**: "Security Ops — CrowdSec" and "Cowrie Ops" in the *Ops / Security* folder
- **Console** (hosted, enrolled as `talos-homelab`): app.crowdsec.net — the richest ops view (CTI,
  attacker map). Context + custom + tainted alerts are shared; manual decisions are not.
- **CLI** — `task security:*` wraps `cscli` in the LAPI pod (`Taskfile.security.yaml`):
  - `task security:alerts` · `task security:decisions` · `task security:bouncers` · `task security:metrics`
  - `task security:ban -- IP=1.2.3.4 [DURATION=4h]` / `task security:unban -- IP=1.2.3.4`
  - `task security:hub` (`cscli hub list`) · `task security:honeypot-events` / `honeypot-follow`
  - Direct in-pod equivalents: `cscli alerts list`, `cscli decisions list`, `cscli simulation status`,
    `cscli allowlists list`, `cscli console status`, `cscli capi status`

## Repo layout (today — see the consolidation note)

```
infrastructure/base/crowdsec/   # LAPI+agent+AppSec, bouncer middleware, whitelist, scenarios, web-ui,
                                #   CNPG postgres.yaml + objectstore.yaml + scheduledbackup.yaml,
                                #   dynamic-allowlist.yaml, machine-registrar.yaml, podmonitor.yaml
infrastructure/base/honeypot/   # Cowrie honeypot (+ logship sidecar)
infrastructure/base/iocaine/    # iocaine tarpit + trap.knowledgedump.space maze
infrastructure/base/traefik/    # bouncer plugin + Bot Wrangler middleware + forwardedHeaders
Taskfile.security.yaml          # task security:* — cscli wrappers + honeypot log helpers
```

> **Consolidation** (deferred, TALOS-c4q): folding crowdsec/honeypot/iocaine into a shared
> `security` namespace + `infrastructure/base/security/` folder is planned but disruptive (workload moves,
> ref updates) and overlaps active honeypot work — do it as one coordinated pass, not piecemeal.
> Less-disruptive alternative on the ticket: keep the namespaces, just regroup the repo folder.

---

## Related Issues

- TALOS-hg7 — [epic] Security Ops: LLM tarpit + Cowrie honeypot + CrowdSec loop + dashboard
- TALOS-pbn — CrowdSec IPS (bouncer + AppSec + Console + k8s-audit) — in progress
- TALOS-e9h — CrowdSec full loop: Cowrie parser + bind bouncer — **closed**
- TALOS-mko — iocaine tarpit + Bot Wrangler — **closed**
- TALOS-5of — Console enrollment — **closed**
- TALOS-c4q — consolidate crowdsec/cowrie/iocaine into one `security` namespace + folder
- TALOS-y260 — `http-generic-403-bf` self-reinforcing operator lockout (drove the dynamic allowlist)
- TALOS-t1w / TALOS-db26 — flip AppSec `default_remediation` allow → ban
- TALOS-wdwm — promote the wave-1/2 simulated app scenarios out of detect-only
- TALOS-ik9o — [epic] publicly expose Cowrie · TALOS-0ru — Cowrie → `ssh-bf` auto-ban when public
- TALOS-mjaj — [epic] CrowdSec hardening · TALOS-2bz — Cilium L3/L4 network bouncer (idea)
- TALOS-frqi — Cloudflare Worker bouncer (edge enforcement) · TALOS-p6h1 — 3rd-party blocklists
