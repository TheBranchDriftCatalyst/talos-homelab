# Ingress / Network Accessibility Audit — 2026-09-12 (ALPHA)

> Epic **TALOS-a8vo**. Full L3→L7 audit of the ingress + network surface, diffed against the
> 2026-09-09 pentest (**TALOS-lxz5**, findings 001–019). 4 parallel auditors + live in-cluster
> probing. Companion: the new **ingress-accessibility test layer** (`tests/ingress-accessibility/test_ingress_accessibility.py`) turns this audit into a standing regression net.

## TL;DR

- **The application/auth plane is materially hardened since the pentest** — 8 of 19 findings fully
  fixed (dashboard, frigate off-LAN, qBittorrent, header-injection, XFF-forge, OIDC, combined-EP),
  5 partial, and a global inbound `X-authentik-*` strip + global CrowdSec bouncer now run at both
  entrypoints. Live-verified: `traefik/api/rawdata`→302-to-auth (was 200/368KB), qBittorrent→302.
- **The perimeter plane is untouched — zero perimeter findings closed.** The **Host-spoof-reaches-
  everything** exposure is fully open: the origin WAN IP is published at the *primary* zone apex
  (`knowledgedump.space A → 108.64.138.156`, grey-cloud), and **66 of 136 hostnames have no
  IP-allowlist or forward-auth** — reachable from the internet by `Host:`-spoofing the origin.
- **Cluster status: healthy** (5 nodes, all Flux/HelmReleases Ready). Fixed a self-inflicted
  `etcd-backup` ImagePullBackOff (quay.io repoint) found during the sweep.

## The 4 P0s (live- or manifest-confirmed)

| # | Finding | Evidence | Fix |
|---|---|---|---|
| **1** | **gluetun SOCKS/HTTP proxy = open unauth cluster pivot** | LAN client → `authentik-postgres:5432` + argocd/authentik backends, bypassing forward-auth. Escalates pentest 008. | Drop the `socks`/`httpproxy` entrypoints (consume gluetun in-cluster) or source-restrict + tighten killswitch to drop pod/svc CIDR. |
| **2** | **maintainerr `/api` leaked a live API key** (no app auth + carve-out) | `GET /api/settings`→200, 84-char key + tmdb/tvdb/tautulli slots | **DONE** — added `lan-only` (frigate-002 pattern); off-LAN blocked. Pod-CIDR residue → P1. |
| **3** | **Observability plane (Loki/Mimir/Tempo) unauth on `:80`** | Loki `GET /loki/api/v1/delete`→200 + `/config` dump; Mimir `/prometheus/config/v1/rules` dumps all rules; ruler/alertmanager reachable; OTLP push open | `lan-only` on `monitoring/v2-otel/ingressroutes.yaml` (4 lines); ideally forward-auth the UIs. |
| **4** | **Host-spoof reaches everything** — origin IP at the `knowledgedump.space` apex, 66/136 hosts unguarded | `PROXIED=false` on the apex; default LE cert self-identifies origin on any :443 scan; Traefik routes on Host regardless of entrypoint | **Invert the Traefik entrypoint default from allow-all to `lan-only`**, exempt the ~8 genuinely-public routes. Collapses ~66 hosts → ~8 in one change. |

## By layer

### L3/L4 — network segmentation (`netseg`)
- **Open-by-default east-west.** Cilium `enable-policy: default` (allow-all); only **3 of 64
  namespaces** enforce default-deny — and they're the *sandboxes* (honeypot, iocaine, teak). The
  crown-jewel datastores (minio, mongo, registry, forgejo, kubevirt, dashboard, mail) are wide open.
- **20 CNPG Postgres clusters have no ingress restriction** — reachable `:5432` from any pod. The
  "consumers + monitoring:9187" convention is documented but **not implemented** on the ingress side.
- WireGuard encryption **is** on (all cross-node pod traffic encrypted) — the one bright spot.
- **hostPort/hostNetwork bypass all NetworkPolicy**: plex, homeassistant, traefik, bt-agent; plus
  `clustermesh-apiserver` NodePort **:2379** and `windows-gameserver-rdp` **:3389** open to the whole LAN.

### L7 — ingress + auth (`ingress-l7`)
- **59 no-middleware routes / 130 plaintext-`web` / no global HTTP→HTTPS redirect** (39 terminal
  plaintext incl. Grafana/Authentik/MinIO/Forgejo/zot logins in cleartext).
- **maintainerr** (fixed) was the surviving qBittorrent-class leak; the 6 arr `/api`+`/feed`
  carve-outs remain (arrs enforce own API-key → lower risk; restore `lan-only` as defense-in-depth).
- **Inference plane unauth** (ollama/ollama-mac/whisper-mac/webui-mac/litellm).
- Forward-auth **header-injection is fixed at the entrypoint** (global `strip-authentik-headers`),
  residual gap: `X-authentik-entitlements` + an `ApiKey` header aren't in the strip set.
- Rate-limit/bot-wrangler exist but cover only ~4 / ~3 routes.

### External / TLS edge (`exposure`)
- Host-spoof + origin-IP-at-apex (P0 #4). No Cloudflare Tunnel; 17 hosts deliberately bypass CF.
- `--serversTransport.insecureSkipVerify=true` still set (harmless today, arms a silent future
  failure). No default `TLSOption`; HSTS on 14/121 routes. `cam-ingest.knowledgedump.space` is a
  dangling pre-trusted public hostname; the Kyverno hostname-claim policy covers only `amberdark.net`.

## Pentest diff: 8 fixed · 5 partial · 3 open

**Fixed:** 001 dashboard · 002 frigate (off-LAN) · 005 qBittorrent · 010 header-injection · 011
XFF-forge · 013/015/016/018 OIDC · 014 combined-EP. **Partial:** 005 (6 arrs) · 007 zipline
(rate-limited, still no auth) · 009 rate-limit (4 routes) · 012 (amberdark only). **Open:** 006
origin/Host-spoof · 008 open proxy (**escalated to cluster pivot**) · 019 CrowdSec stream-mode.

## Remediation roadmap

**P0 (do now):** invert entrypoint default to `lan-only` (#4, web-first, exempt the ~8 public) ·
gate the obs plane (#3) · restrict/remove the gluetun proxy entrypoints + confirm router WAN-forward
(#1). maintainerr (#2) **done**.
**P1:** exclude pod CIDR from `lan-only` (frigate/maintainerr residue) · Kyverno default-deny floor
per namespace + CNPG ingress allowlists · restore `lan-only` to the 6 arr carve-outs · global
HTTP→HTTPS redirect · gate the inference plane · header-strip allowlist gap · restrict :2379/:3389.
**P2:** drop `insecureSkipVerify` · extend hostname-claim policy to `knowledgedump.space` + reap
`cam-ingest` · default `TLSOption` + HSTS · CrowdSec live-mode on public routes · dead Flux path.

## The standing regression net (Layer 3)

This audit is now codified in `tests/ingress-accessibility/test_ingress_accessibility.py` — the third test
layer (alongside DR + security-posture, see [TESTING.md](../../TESTING.md)). It renders the whole
Flux tree and asserts fleet-wide ingress invariants offline (middleware-ref-resolves, no-combined-EP,
`/api`-carveouts-gated, `lan-only`-not-pod-CIDR, tcp-proxy-restricted, flux-paths-exist), with a
`--live` read-only probe (admin-not-open, forged-identity-stripped). Accepted risks are reviewed
entries in `tests/ingress-accessibility/ingress_allowlists.py`, each carrying a rationale + a `TALOS-` id — so relaxing a
contract is a visible PR diff. Two fixes fell out of building it: maintainerr (P0) and a dangling
`redirect-to-https` middleware ref that was silently dropping 2 routes.

---

## Related Issues

- **TALOS-a8vo** — this audit + the accessibility test layer (4 P0, 7 P1, 5 P2 children)
- **TALOS-lxz5** — the 2026-09-09 pentest baseline (findings 001–019)
