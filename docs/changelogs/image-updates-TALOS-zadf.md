# Image Updates — TALOS-zadf (2026-08-09 →)

Source report: `.output/image-version-report.json` · Skill: `image-update-implement`
Order: low-blast-radius first (P3 → P2 → P1), majors elevated to operator, k8s upgrade last.

## Summary
- Updated: 6 · Elevated/answered: chart-strategy, local-path, safe-batch(auto), 4 greenlit (ext-dns/virt-operator/meilisearch/1password) · Deferred: 54 chart-managed
- Breaking changes encountered: 0 so far
- Strategy (operator): raw `image:` bumps in this epic; chart/operator-managed images deferred to per-chart work.
- Skipped (mis-parse, tracked TALOS-zpoa): alpine→20260805, gluetun→1243, socat→1.0.5. Digest-pinned (14) = pinned-on-purpose, held.

### Clean utility batch (commit 7e3cae1) — all verified latest, rolled, pod-confirmed
| Image | Bump | Ticket |
|---|---|---|
| us-docker.pkg.dev/fairwinds-ops/oss/goldilocks | v4.14.7 → v4.15.1 | zadf.32 ✅ |
| registry.k8s.io/autoscaling/vpa-recommender | 1.0.0 → 1.7.1 | zadf.59 ✅ |
| ekofr/pihole-exporter | v1.0.0 → v1.2.0 | zadf.20 ✅ |
| intel/intel-gpu-plugin | 0.30.0 → 0.36.0 | zadf.26 ✅ |
| velero/velero-plugin-for-aws | v1.11.1 → v1.14.2 | zadf.62 ✅ |

### vpn-gateway utility batch (commit 0130604) — zero-downtime
| Image | Bump | Ticket |
|---|---|---|
| busybox (securexng init/cleanup) | 1.36 → 1.38.0 | zadf.15 ✅ |
| kasmweb/chrome (secure-chrome) | 1.16.0 → 1.19.0 | zadf.43 ✅ |

**Component tests (all 6 of the first batch, functionally verified):** goldilocks→creates VPAs · vpa-recommender→recommendations populated · intel-gpu-plugin→`i915=10` on talos02-gpu+talos06 · velero→BSL Available · pihole-exporter→started · local-path v0.0.37→live PVC provision test passed.

**Skipped (report stale/pinned):** curl (novnc) digest-pinned; alpine/k8s (rotation cronjob) already at 1.34.9.

### external-dns v0.14.2 → v0.21.0   [zadf.60] ✅ — BREAKING (resolved)
- ⚠️ **BREAKING:** v0.21 **removed the `--traefik-disable-legacy` flag** (legacy `traefik.containo.us` API support dropped entirely; `traefik.io`-only is now the default). New pod went `fatal: unknown long flag`. **Resolved:** removed the flag from args (commit cdc5df9); its behavior is now the built-in default (`TraefikEnableLegacy:false`). v0.21's other breaking changes (DigitalOcean/CloudFoundry provider removal) don't apply — we use Cloudflare.
- Gotcha: the Flux ks health-gate stalled on the crashing pod (didn't advance to the fix commit) — applied git directly (`kubectl apply -k`) to unstick; ks then recovered to Ready.
- Zero DNS impact: `--policy=upsert-only` + records persist in Cloudflare; old pod served until the fix.
- Verified: pod 1/1, "All records are already up to date", sources `[ingress traefik-proxy crd]` intact.
- Manifest: `infrastructure/base/external-dns/deployment.yaml` · Rollback: `git revert 2c77f34..799a106`.

### 1password-connect (connect-api + connect-sync) 1.7.3 → 1.8.2   [zadf.33/.34] ✅
- Both containers in lockstep; minor API-compatible bump.
- Verified functionally: **all 97 ExternalSecrets `SecretSynced=True`** — ESO resolves secrets through the new Connect fine.
- Manifest: `infrastructure/base/external-secrets/onepassword-connect/deployment.yaml` · Rollback: `git revert 2c77f34`.

### meilisearch v1.12.8 → v1.52.0 (linkwarden)   [zadf.40] ✅ — DB migration
- ⚠️ **Migration required:** v1.52 engine refused the v1.12.8 on-disk DB (incompatible format). Fix = added `MEILI_UPGRADE_DB=true` env → in-place dumpless migration on startup (commit 426be94). Idempotent (no-op once current). No dump/import or reindex needed.
- Verified: `/health {"status":"available"}`, linkwarden pod 3/3, index scheduler processing tasks.
- Manifest: `applications/home-automation/base/linkwarden/deployment.yaml` · Rollback: `git revert 426be94 c62092e`.

### virt-operator v1.4.0 → v1.9.0 (KubeVirt)   [zadf.31] ⏸ ATTEMPTED → ROLLED BACK
- ⚠️ **Approach failed:** the ref-bump stepped upgrade (bumping only the operator image/version in `operator.yaml`) drove the operator to v1.5.0 but component deployment **failed** — v1.5.0 operator tried to create ClusterRole `kubevirt.io:admin` with new subresource perms (`virtualmachineinstances/reset`, …) it doesn't hold → RBAC escalation block → `DeploymentFailed`/`Degraded`.
- **Root lesson:** KubeVirt minor upgrades need the **full per-version release manifest** (updated operator RBAC + CRDs), not just an image tag. Recorded in beads memory.
- **Resolved:** rolled back to v1.4.0 (commit 9b53e76) → healthy (`Available=True, Degraded=False`). Zero impact (VM halted, components never left v1.4.0).
- Ticket zadf.31 kept OPEN for a proper redo (replace operator.yaml with each version's release YAML, one minor at a time).

## Changes
### rancher/local-path-provisioner v0.0.28 → v0.0.37   [TALOS-zadf.63]
- Namespace: local-path-storage (default storage-class provisioner).
- No breaking change: verified v0.0.37 is latest (gh, 2026-08-05); only governs NEW PVC provisioning, existing hostPath volumes unaffected.
- Decision (operator): storage golden-rule → "Proceed (recommended)".
- Manifest: `infrastructure/base/storage/local-path-provisioner.yaml` · Rollback: `git revert 74b27ab` · Verified: deploy rolled, pod 1/1 Running v0.0.37.

## Triage notes

### P3 patch batch (TALOS-zadf.63) — mostly NOT individually actionable
| Image | Reported | Reality | Action |
|---|---|---|---|
| altinity/clickhouse-operator | 0.27.2→0.27.3 | chart/operator-managed | moves with the altinity operator chart bump |
| altinity/metrics-exporter | 0.27.2→0.27.3 | chart/operator-managed | ditto |
| kubernetesui/metrics-scraper | v1.0.8→v1.0.9 | dashboard chart-managed | moves with the k8s-dashboard chart |
| memcached | 1.6.32→1.6.45 | kube-prometheus-stack/mimir dep | moves with the parent chart |
| quay.io/cilium/hubble-ui(+backend) | v0.13.1→v0.13.5 | **cilium chart** | moves with the cilium chart bump (high blast radius) |
| mongodb-kubernetes-readinessprobe | 1.0.20→1.0.24 | mongodb-operator managed | moves with the operator |
| quay.io/prometheus/pushgateway | v1.11.0→v1.11.3 | kube-prometheus-stack dep | moves with the parent chart |
| registry.k8s.io/coredns/coredns | v1.14.2→v1.14.6 | chart/Talos-managed | verify owner |
| dagster/dagster-k8s | 1.13.0→1.13.17 | `:latest` in **undeployed** dev manifest | no-op (the-corpus/…/dev) |
| soupbowl/opensimulator | 0.9.3.0→**0.9.3** | version-checker **mis-parse (downgrade)** | SKIP — current is newer |
| rancher/local-path-provisioner | v0.0.28→v0.0.37 | in-repo, **storage provisioner** | ⏸ ELEVATED — see decision |

## Changes
_(none applied yet — awaiting operator direction on strategy + local-path-provisioner)_

### argocd-image-updater + python tool images (commit d129421) ✅
| Image | Bump | Ticket |
|---|---|---|
| quay.io/argoprojlabs/argocd-image-updater | v1.0.1 → v1.2.2 | zadf.46 (argocd-image-updater-system, ready) |
| python (vpn-gateway maintenance + exporter) | 3.11-alpine → 3.14-alpine | zadf.22/.44/.45 |
- python kept on `-alpine` variant; both pods `1/1 Running 0-restarts` — `exporter.py` runs clean on 3.14 (no removed-stdlib breakage). Reported 3.11-slim/3.12-alpine were stale pod images, not in manifests.

### dbgate 5.5.6 → 7.2.4 + namespace move (commit bd56285) ✅
- Promoted scratch → **databases** ns (`infrastructure/base/databases/dbgate/`, alongside CNPG/MongoDB/MinIO operators) + major image bump. New pod ready ("DbGate API listening on port 3000"); old scratch copy pruned. Fresh NFS data volume (saved connections not carried; re-add). Removed the dbgate healthCheck from scratch.yaml.
