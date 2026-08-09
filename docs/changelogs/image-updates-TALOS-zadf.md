# Image Updates — TALOS-zadf (2026-08-09 →)

Source report: `.output/image-version-report.json` · Skill: `image-update-implement`
Order: low-blast-radius first (P3 → P2 → P1), majors elevated to operator, k8s upgrade last.

## Summary
- Updated: 0 · Elevated to operator: (pending) · Deferred/blocked: (see below)
- Breaking changes encountered: 0 so far

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
