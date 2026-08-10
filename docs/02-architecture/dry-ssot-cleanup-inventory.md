# DRY / Single-Source-of-Truth Cleanup Inventory

> Epic: **TALOS-vo0i**. Generated 2026-08-10 from a 5-agent codebase audit (reflector, Kyverno,
> cluster-settings substitution, structural DRY, declarative credentials). Each row links a bead.

## TL;DR

The homepage restructure proved three patterns worth spreading: **Kyverno mutate/generate from
namespace**, **emberstack/reflector cross-ns mirroring**, and **cluster-settings `${VAR}`
substitution**. An audit found ~40 places doing the same work by hand. It also surfaced **three live
problems that are not cleanup**:

1. **6 of 8 CNPG Postgres DBs have no backups** (only forgejo + authentik) — DR hole (**TALOS-i06y**, P0).
2. **qBittorrent WebUI password lost 2026-05-31** → port-sync sidecar (hardcoded admin/admin) silently
   failing → forwarded VPN port never applied (**TALOS-ekmt**, P1).
3. **Home Assistant never onboarded** (0 users/tokens) → HA widget can't work until first-run setup
   (**TALOS-ahqs**, P1).

## A · Reflector — kill duplicate 1Password pulls (TALOS-huqi)

| Item | Where | Fix |
|---|---|---|
| minio root creds ×4 ES / 3 ns | `minio/tenant.yaml`, `backup/minio-credentials.yaml`+`etcd-backup.yaml`, `crossplane-demo/flex/` | reflect `minio-root-credentials` |
| authentik OIDC secrets re-pulled per app | `authentik/externalsecret.yaml` ↔ 5 app ns | reflect each `authentik-<app>-oidc` (differing bundled keys — careful, later pass) |
| discord webhook ×3 ns | flux-system / monitoring / argocd | reflect flux→monitoring (identical drop-in) |
| cloudflare token ×3 ns | ddns / external-dns / cert-manager | one source + reflect (keys differ — later pass) |
| **ghcr-secret ownership conflict** 🐛 | `scratch/grpc-example/k8s/ghcr-secret.yaml` vs the ClusterExternalSecret | **delete the file** (TALOS-57tm) |
| wildcard TLS cert issued twice | `cert-manager-issuers/` + `home-automation/` byte-identical | reflect `talos00-wildcard-tls` |

## B · Kyverno — mutate/generate defaults

| Item | Count | Bead |
|---|---|---|
| default ES `secretStoreRef`+`refreshInterval` (add-if-absent) | 58 | TALOS-8crt |
| **generate CNPG `ScheduledBackup`+backup stanza** (or explicit per-cluster) | 6/8 | TALOS-i06y |
| derive gethomepage `siteMonitor`/`href`/`enabled` from route | ~50 | TALOS-kjcn |
| generate `allow-monitoring` NetworkPolicy per Dragonfly (crossplane-demo blackholed) | 2+1 | TALOS-jhk5 |
| HTTP→HTTPS: Traefik entrypoint redirect **or** generate twin routes | 12 | TALOS-h8l0 |

## C · cluster-settings substitution (TALOS-pdca)

- **`talos00`** hardcoded in ~100 files, only 50 use `${CLUSTER_DOMAIN}` — biggest SSoT violation.
  ~25 already-wired files (arr-stack, homepage incl. our fresh hardcodes) are free swaps.
- Add **`EXTERNAL_DOMAIN`** for `knowledgedump.space` (78× / 30 files, no var today).
- One-liners in already-wired Kustomizations: `storage/nfs-provisioner/helmrelease.yaml:40`,
  `control-plane-scrape/*` — trivial (done in TALOS-57tm's batch).
- ⚠️ Wiring `substituteFrom` onto unwired Kustomizations needs a `$${...}` escaping audit first
  (dashboard JSON / shell scripts) or Flux blanks them.

## D · Structural (kustomize base/component)

| Item | Size | Bead |
|---|---|---|
| arr-stack 15 per-app dirs (identical modulo name) — pilot on media-experimental first | ~3,700 lines | TALOS-937u |
| gluetun VPN sidecar copy-pasted 5× w/ healthcheck drift | ~480 lines | TALOS-0spw |
| HelmRelease remediation boilerplate → Flux-Kustomization patch | 41 files | TALOS-z5pf |
| delete diverged `scratch/vision/{frigate,scrypted}` dupes | — | TALOS-myec |

## E · Declarative widget credentials (TALOS-19v2)

Resolves the k59e GitOps inversion (app-UI mint → 1P copy). Verdicts:

| Cred | Path | Effort |
|---|---|---|
| authentik | blueprint with fixed `key:` (documented; 11 blueprints already mounted) | low |
| tautulli | `sed` init-container seeds config.ini | low |
| qbittorrent | PBKDF2 init-container — **also fixes TALOS-ekmt** | med |
| argocd | `accounts.homepage: apiKey` + idempotent mint-Job (token not choosable) | med |
| homeassistant | manual — no declarative token model + not onboarded (TALOS-ahqs) | — |

**Value-distribution decision:** PushSecret→1Password is off the table (onepassword store is
ReadOnly). Either **Pattern A** (mint once, store in 1P, both ends read — matches the grafana-OIDC
precedent, zero new infra) or **Pattern B** (ESO `Password` generator, 1P-free, needs a
kubernetes-provider ClusterSecretStore). **Pattern A is the default.**

## Execution sequence

1. 🔴 CNPG backups (TALOS-i06y) — risk, not nicety.
2. 🐛 live bugs — qbit (TALOS-ekmt), HA onboarding (TALOS-ahqs).
3. Free wins — ghcr delete (TALOS-57tm), discord/wildcard reflect (TALOS-huqi), one-liner IPs, dead dupes (TALOS-myec).
4. High-leverage — ES-default mutate (TALOS-8crt), `talos00` wired swaps (TALOS-pdca), authentik+tautulli creds (TALOS-19v2).
5. Bigger lifts — arr-stack DRY (TALOS-937u), gluetun (TALOS-0spw), substitution wiring campaign (TALOS-pdca).

---

## Related Issues

- **TALOS-vo0i** — [EPIC] Homelab DRY/SSoT cleanup
- Children: TALOS-i06y, ekmt, ahqs (critical) · huqi, 57tm, 8crt, kjcn, jhk5, h8l0 (Kyverno/reflector)
  · pdca (substitution) · 937u, 0spw, z5pf, myec (structural) · 19v2 (declarative creds)
