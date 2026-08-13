# Image Updates — TALOS-9dt (2026-08-13 → )

Source: 2026-06-05 cluster audit (epic TALOS-9dt, 24 children tiered T1/T2/T3).
Audit numbers were two months stale at execution start — every "latest" re-verified live.

## Summary (2026-08-13 execution)

- Updated: 9 (wave1 ×6, cert-manager, ESO ×2-step) | Already-done/obsolete closed: 14 | Rescoped: 4
- Deferred: k8s campaign (c0g→haq→0it, Talos-first landmine), KubeVirt 6-hop chain (4gyq→…→aqzs, after k8s)
- Breaking changes encountered: 1 (ESO CRD SSA wedge — see below); 2 audit targets never existed (grafana-operator v6, pushgateway 4.x)

## Pre-closed (already satisfied by live cluster at campaign start)

- **TALOS-r8e** cloudnative-pg chart 0.22.1→0.25+ — exceeded: laddered to 0.29.0
  (operator 1.30.0) during the barman-plugin migration (TALOS-iuig, 2026-08-12/13).
- **TALOS-png** argocd-image-updater v1.0.1→v1.2+ — done in TALOS-zadf (v1.2.2 +
  `IMAGE_UPDATER_WATCH_NAMESPACES='*'` watch-scope fix, commit d129421).

## Decision matrix (Phase 0/1)

<!-- populated from the research pass, then decision column filled from operator answers -->

| image/group | current | real latest | where | chart Δ | risk | decision | notes |
|---|---|---|---|---|---|---|---|

## Changes

### Wave 1 — six drop-in bumps (commit a272f33)
- pod-cleanup python 3.11→3.13-slim [TALOS-haj]; busybox pinned 1.37.0 [TALOS-s8n];
  nebula 1.9.5→1.11.0 (dormant manifest — mesh NOT deployed) [TALOS-job];
  pushgateway chart 2.17.0→3.8.0 (no 4.x exists; StatefulSet break inert) [TALOS-4vc];
  grafana-operator v5.20.0→v5.24.0 (no v6 exists; 4 cross-ns dashboards verified post-roll) [TALOS-hqc];
  velero chart 11.2.0→12.1.0 (major = 1 cosmetic PR; app v1.18.1 VolumeGroupSnapshot fix) [TALOS-6b4].

### cert-manager v1.16.2 → v1.21.1 (commit 1ad7208) [TALOS-xsx]
- Was OUT of supported range (v1.16 caps k8s 1.32; cluster on 1.34). Direct jump operator-approved;
  CRDs 100% additive. Avoided v1.21.0 (ACME Secret wedge) and v1.19.0 (re-issuance bug).
- GA defaults now active: rotationPolicy=Always, revisionHistoryLimit=1. installCRDs→crds.{enabled,keep}.
- Verified: 4/4 ClusterIssuers Ready, 17/17 Certificates Ready. Rollback: git revert 1ad7208.

### external-secrets 0.11.0 → 2.6.0 (commits bae5a87, 66992a1, 824f99d) [TALOS-8q0]
- ⚠️ BREAKING/incident: first 0.16.2 upgrade wedged — controller crashlooped (3 of 4 CRDs missing v1),
  helm rollback IMPOSSIBLE (v1 already stored on clusterexternalsecrets; 0.11 CRD can't drop it),
  re-apply blocked by SSA hybrid conversion stanza (webhookClientConfig without strategy).
  Fix-forward: patched 3 CRDs to conversion strategy:None, deleted pending-rollback helm record,
  clean re-upgrade. FORWARD-ONLY from here — no rollback path to 0.11 exists.
- v1beta1→v1 rewrite: 1556 occurrences (45 files talos-homelab incl. 2 kyverno-nested, 13 boomtime,
  4 catalyst-data) — required before v0.17+ which stops serving v1beta1.
- Capped at 2.6.0 (k8s-1.34 tested ceiling; 2.7+ waits for k8s 1.35/1.36).
- Verified: onepassword ClusterSecretStore Ready, 123/123 ExternalSecrets Ready on v1 API.

### Deferred campaigns (ticketed, sequenced)
- Kubernetes: TALOS-c0g (Talos v1.13.2→v1.13.8, HARD prereq — v1.13.2 scheduler CrashLoop bug
  siderolabs/talos#13350) → TALOS-haq (k8s 1.35.7) → TALOS-0it (1.36.3). talosctl rejects minor-skips.
- KubeVirt: TALOS-l19s (CDI into Flux) → TALOS-4gyq→ug8k→gadc→xolm→lrrh→aqzs (v1.4.1→…→v1.9.0
  mandated N-1 chain). After the k8s campaign.
