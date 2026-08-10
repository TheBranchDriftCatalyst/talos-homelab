# Cluster Audit — 2026-08-09 (layer 0 → −1000)

Full comprehensive audit run immediately after the **Cilium 1.16.6 → 1.20.0** campaign + PKI rotation.
Six parallel deep-audit agents, one per domain, each returning severity-ranked findings **with evidence**
(live query/log data, not pod-status). Remediation tracked under epic **TALOS-xgrl**.

## TL;DR

- **The cluster is fundamentally healthy** — 0 non-running pods, all nodes Ready, etcd sound, all 34
  HelmReleases Ready, ESO 115/115, cert-manager 14/14, the cilium 1.20 upgrade landed **clean**.
- **5 quick-wins fixed inline** during the audit (see below).
- **3 genuine SEV-1s remain** — all either pre-existing or a design decision, none from the upgrades:
  KubeView secret exposure, no Postgres PITR, alerts not reaching Discord.
- **k8s 1.36 upgrade = GO** after 3 pre-flight fixes; a **Talos patch off 1.13.2 is now a prerequisite**.

---

## Fixed inline (quick-wins) ✅

| Fix | Domain | Commit |
|---|---|---|
| **virt-api expired-cert** — deleted pods to reload fresh on-disk cert → unblocked `gaming` Flux ks | workloads | (live) |
| **Mimir AM `external_url` path** — `/alertmanager` prefix so ruler stops 404ing → **AM now receiving alerts (10, was 0)** | observability | `a36fe41` |
| **arr-stack envsubst** — escaped runtime shell vars in `migrate.sh`+`backup.sh` → unblocked `arr-stack` ks | workloads | `a36fe41` |
| **OOM limits** — version-checker 256→512Mi (was staling the Image-Versions dashboard), reflector 128→256Mi, KSM 256→512Mi | multi | `f103be5` |

---

## SEV-1 (remediation: TALOS-xgrl.1–.3)

### 1. KubeView — unauthenticated cluster-secrets exfil `[TALOS-xgrl.1]`
`infra-control/kubeview` has a `*/*` get/list/watch ClusterRole (**includes Secret data cluster-wide**) and
its IngressRoute is plain-HTTP with **no auth middleware**. Anyone resolving `kubeview.talos00` on the LAN
reads every Secret with zero login. LAN-only is the sole reason it isn't Critical.
**Fix:** drop `secrets` from the ClusterRole + front with auth.

### 2. CNPG → MinIO Postgres backups non-functional — zero PITR `[TALOS-xgrl.2]`
The `cnpg-minio-backup` credential Secret **doesn't exist**, so authentik + forgejo WAL archiving fails
("cache miss"), the `cnpg-backups` bucket is empty, and there is **no PITR**. Pre-existing incomplete
rollout (`TALOS-fijt` phase 1), **not** the minio-v7 upgrade. ⚠️ Working-tree landmine: uncommitted
`forgejo/kustomization.yaml` references a `backup-credentials.yaml` that doesn't exist — committing as-is
breaks the forgejo ks. **Fix:** create the ESO-backed secret in both namespaces.

### 3. Alertmanager → Discord delivery failing — alerts don't page `[TALOS-xgrl.3]`
Ruler→AM is **fixed** (inline). But AM→Discord uses `webhook_configs` which posts native AM JSON that
Discord rejects (`notifications_failed_total` 5/5 `clientError`). Alerts reach the AM, never reach Discord.
Pre-existing (masked by the 404). **Fix (decision):** `slack_configs` + Discord `/slack` endpoint, or an
alertmanager-discord bridge.

---

## SEV-2 (TALOS-xgrl.4–.9)

- **6 of 8 CNPG clusters have no object backup** (boomtime + homeassistant hold real data) — Velero PVC
  snapshots only, no PITR. `[.4]`
- **whisparr CrashLoop** (2657 restarts) — broken root-folder + too-tight liveness + unpinned `:latest`;
  ties to gluetun/vpn-rotator churn. `[.5]`
- **Guacamole `admin/admin`** in the public repo + RDP NodePort 30389. `[.6]`
- **Headlamp cluster-admin/`:latest`/plain-HTTP** + **ArgoCD served plaintext** (session tokens cleartext). `[.7]`
- **No pod-security guardrail** (only the reflect Kyverno policy) + **missing PSA `enforce` labels** on many
  app namespaces + privileged init-containers on plex/jellyfin/homeassistant. `[.8]`
- **ArgoCD**: `immich-video-faces` repo missing/private (sync=Unknown); `arr-stack-private` zipline
  Deployment sets both `value`+`valueFrom` (OutOfSync) + Flux/ArgoCD both now claim zipline. `[.9]`

## SEV-3 (TALOS-xgrl.10–.11)

- **argocd NetworkPolicies black-hole 2 monitoring exporters** (dragonfly + repo-server metrics missing) —
  recent argocd hardening, not the CNI upgrade. `[.10]`
- **Hygiene:** 21 orphaned Released PVs; `AlloyPushesStopped` chronic false-positive; 25 phantom traefik
  scrape targets inflating `ServiceDown`; clickhouse error-string metric-name pollution; cilium
  `upgradeCompatibility` still pinned `1.19`. `[.11]`

## Deferred / already-tracked

- **Mimir Kafka ingest-storage SPOF** — single broker on a talos01-pinned PVC; ingestion halts cluster-wide
  if it fails. Prioritize the classic-arch migration → **TALOS-iuig**.
- **Git history purge** (dead `minio123` + Nebula key) → **TALOS-tmqq**.
- **Single control-plane / etcd SPOF** → HA epic **TALOS-arx** (homelab design; mitigated by hourly etcd backup).

---

## Upgrade readiness & sequence

The audit revised the upgrade order. A **Talos patch is now a k8s prerequisite**:

```
fix findings  →  Talos patch 1.13.2 → 1.13.8  →  k8s 1.34 → 1.35 → 1.36  →  Talos major (LAST)
                 (talos#13350 scheduler bug)      (TALOS-y7q1)                (TALOS-7126)
```

**k8s 1.36 verdict: GO after 3 pre-flight fixes** (deprecated-API scan clean):
1. Patch Talos server off v1.13.2 (kube-scheduler regression [#13350](https://github.com/siderolabs/talos/issues/13350) breaks version transitions).
2. Handle the 9 zero-disruption CNPG `*-primary` PDBs (they hang node drains).
3. Bump PodSecurity admission config `v1alpha1` → `v1`.

Warnings: metrics-server absent (resource-HPA can't work); Fail-policy webhooks need drain sequencing;
etcd defrag worth doing (166 MB reclaimable).

---

## What's confirmed healthy (with proof)

Cilium 1.20 datapath (kube-proxy-replacement Full, identities stable 269, pihole L2 DNS answered) ·
DNS/ingress (whoami 200 in 18ms) · MinIO v7 upgrade clean · CNPG streaming replication · Velero (recent
backups Complete) · Mimir metrics end-to-end (distributor==ingester, historical continuity across the
upgrade) · Loki ingesting · ESO 115/115 · cert-manager 14/14 · CrowdSec/Cowrie/iocaine stack · Kyverno
reflect policy · RBAC baseline deny-by-default · argocd-image-updater (all 3 CRs, errors=0).

> Cilium PKI was **never actually leaked** (the key file was always gitignored) — the rotation I ran was
> pure hygiene. Traces (Tempo) are **idle** (0 spans/7d) — no app emits OTLP; the path is unproven, not broken.

---

## Related Issues

- Epic: **TALOS-xgrl** (this audit's remediation, .1–.11)
- Upgrades: TALOS-y7q1 (k8s), TALOS-7126 (Talos), TALOS-iuig (mimir kafka)
- Security: TALOS-031k (secret sweep), TALOS-tmqq (git history purge)
