# Repo Restructure Plan — grouping `infrastructure/base/`, `applications/`, and the test tree

> **Status:** **Phase 1 EXECUTED** (§9.3) — the test-tree consolidation has landed in the
> working tree and is verified. Everything else is still a PROPOSAL; no manifest has moved.
> This document is the complete enumeration, the before/after, and the validation harness.
> Sign off on §7 (mapping) and §13 (open questions) before any further `git mv` happens.
>
> **Not committed.** Phase 1's changes sit in the working tree alongside unrelated pre-existing
> dirty state. See F13 for an index/worktree conflict that must be resolved before committing.
>
> **Hard constraint:** **no namespace changes.** Every proposed move is a directory move only.
> §8 proves namespace invariance.

---

## 1. TL;DR

- `infrastructure/base/` is **46 flat directories**. That is past the point where `ls` is useful.
- Proposal: insert **one** grouping layer of **9 dependency-ordered groups**, and drop the
  vestigial `base/` level (there are no `overlays/` siblings — it buys nothing).
- **4 directories are dead or misfiled** (`shared/`, `talos-dr/`, `nebula/`, `nvidia-cdi/`)
  and 1 more is unwired (`hybrid-llm/`). Enumerated in §5.
- **10 test suites carry their own `package.json` + `package-lock.json` + `node_modules`** —
  all redundant. The root `jest.config.js` already aggregates them as Jest projects. Deleting
  the per-suite manifests leaves exactly one `node_modules`, zero behaviour change.
- `applications/` (12 dirs) is not yet painful, but the same grouping applies cheaply. §10.
- Validation: `kustomize build` fingerprint per Flux path, before vs after. Baseline captured
  in §3 — **59 OK / 3 pre-existing failures** (all from uncommitted working-tree deletions).

---

## 2. Scope and constraints

|                  |                                                                                   |
| ---------------- | --------------------------------------------------------------------------------- |
| **In scope**     | directory layout under `infrastructure/`, `applications/`, and the Jest test tree |
| **In scope**     | `path:` fields in `clusters/catalyst-cluster/*.yaml`, doc/script path references  |
| **Out of scope** | **namespaces** — not one changes                                                  |
| **Out of scope** | Flux Kustomization _names_, `dependsOn` edges, `targetNamespace`, `prune`, `wait` |
| **Out of scope** | any manifest content (`spec:` bodies are byte-identical after the move)           |
| **Out of scope** | ArgoCD-managed app repos (this repo only holds their `Application` CRs)           |

Both `infrastructure/` and `applications/` are **Flux**-managed from
`clusters/catalyst-cluster/`. ArgoCD manages _app repos_, not these trees — so this
restructure is entirely a Flux `path:` rewrite. It does not cross the GitOps demarcation.

---

## 3. Validation method and baseline

A directory move is correct if and only if **the rendered output of every Flux Kustomization
path is byte-identical before and after**. `kustomize build` output contains no filesystem
paths, so the SHA is path-independent — it is a sound equality test.

Harness (`scripts/kustomize-baseline.sh`, to be promoted from scratch on approval):

```bash
# for every `path:` in clusters/catalyst-cluster/*.yaml
kustomize build --load-restrictor LoadRestrictionsNone "$ROOT/$p" | shasum -a 256
```

### Baseline captured on the current working tree

| Result                           | Count  |
| -------------------------------- | ------ |
| `OK` (built clean, SHA recorded) | **59** |
| `MISSING-DIR`                    | 2      |
| `BUILD-FAIL`                     | 1      |

The 3 non-OK entries are **pre-existing** and unrelated to this restructure:

| Path                           | Cause                                                         |
| ------------------------------ | ------------------------------------------------------------- |
| `applications/catalyst-llm`    | absent at `HEAD` too — dangling Flux Kustomization, real bug  |
| `applications/poisonarr/base`  | exists at `HEAD`; deleted in the **uncommitted** working tree |
| `applications/crossplane-demo` | `flex/` subdir deleted in the **uncommitted** working tree    |

> **Acceptance criterion for the migration:** all 59 currently-OK paths must produce the
> **same SHA** after the move. The 3 failures must not grow to 4.
>
> **Note:** `applications/catalyst-llm` is a genuine dangling reference that predates this
> work. It should be fixed or deleted independently — do not let it hide inside this diff.

---

## 4. BEFORE — complete enumeration

### 4.1 `infrastructure/base/` — all 46 directories

`files` = YAML count (excl. `node_modules`). `refs` = mentions of the path across `*.md`,
`*.sh`, `*.yaml`. `flux ks` = which `clusters/catalyst-cluster/*.yaml` reference it.

| #   | Directory              | files   | flux ks                                                                            | refs | namespaces touched                                                                                                                          |
| --- | ---------------------- | ------- | ---------------------------------------------------------------------------------- | ---- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `analytics`            | 3       | `analytics`                                                                        | 6    | traefik                                                                                                                                     |
| 2   | `argocd`               | 26      | `argocd`, `bt-radar`                                                               | 50   | argocd, argocd-image-updater-system, boomtime, catalyst, catalyst-data, catalyst-llm, dungeon-library, media, monitoring, openscad, traefik |
| 3   | `authentik`            | 36      | `authentik`                                                                        | 19   | authentik, traefik                                                                                                                          |
| 4   | `aws`                  | 18      | `aws`, `aws-apps`, `aws-buckets`, `aws-providers`                                  | 16   | crossplane-system                                                                                                                           |
| 5   | `aws-providers`        | 4       | `aws-providers`                                                                    | 4    | —                                                                                                                                           |
| 6   | `backup`               | 9       | `backup`                                                                           | 8    | backup, velero-dr-canary                                                                                                                    |
| 7   | `bootstrap-crds`       | 16      | `bootstrap-crds`                                                                   | 4    | —                                                                                                                                           |
| 8   | `catalyst-cnpg-appdb`  | 5       | `catalyst-cnpg-appdb`                                                              | 3    | crossplane-system, minio                                                                                                                    |
| 9   | `cert-manager`         | 4       | `cert-manager`, `cert-manager-issuers`                                             | 6    | cert-manager                                                                                                                                |
| 10  | `cert-manager-issuers` | 9       | `cert-manager-issuers`                                                             | 2    | cert-manager, traefik                                                                                                                       |
| 11  | `cilium`               | 16      | `cilium`                                                                           | 31   | authentik, kube-system, lbipam-dr, traefik                                                                                                  |
| 12  | `cloudflare-ddns`      | 3       | `cloudflare-ddns`                                                                  | 1    | kube-system                                                                                                                                 |
| 13  | `crowdsec`             | 11      | `crowdsec`                                                                         | 5    | authentik, crowdsec, traefik                                                                                                                |
| 14  | `databases`            | 19      | `databases`                                                                        | 15   | authentik, databases, monitoring, traefik                                                                                                   |
| 15  | `descheduler`          | 4       | `descheduler`                                                                      | 2    | descheduler                                                                                                                                 |
| 16  | `external-dns`         | 10      | `external-dns`                                                                     | 5    | external-dns                                                                                                                                |
| 17  | `external-secrets`     | 15      | `external-secrets` (×2 paths)                                                      | 33   | default, external-secrets                                                                                                                   |
| 18  | `flux-notifications`   | 5       | `flux-notifications`                                                               | 10   | flux-system                                                                                                                                 |
| 19  | `forgejo`              | 6       | `forgejo`                                                                          | 2    | forgejo, traefik                                                                                                                            |
| 20  | `gpu-inference`        | 14      | `gpu-inference`                                                                    | 4    | gpu-inference, keda                                                                                                                         |
| 21  | `honeypot`             | 7       | `honeypot`                                                                         | 6    | default, honeypot                                                                                                                           |
| 22  | `hybrid-llm`           | 8       | **none**                                                                           | 14   | flux-system, hybrid-llm, liqo-system                                                                                                        |
| 23  | `infra-control`        | 17      | `infra-control`                                                                    | 8    | authentik, infra-control, kube-system, traefik                                                                                              |
| 24  | `intel-gpu`            | 6       | `intel-gpu`                                                                        | 16   | flux-system, intel-device-plugins, node-feature-discovery                                                                                   |
| 25  | `iocaine`              | 8       | `iocaine`                                                                          | 2    | iocaine, traefik                                                                                                                            |
| 26  | `kube-system`          | 11      | `kube-system`                                                                      | 6    | kube-system                                                                                                                                 |
| 27  | `kubevirt`             | 12      | `kubevirt`                                                                         | 4    | cdi, kube-system, kubevirt, monitoring                                                                                                      |
| 28  | `kyverno`              | 4       | `kyverno`, `kyverno-policies`                                                      | 22   | kyverno                                                                                                                                     |
| 29  | `kyverno-policies`     | 11      | `kyverno-policies`                                                                 | 16   | —                                                                                                                                           |
| 30  | `mail`                 | 3       | `mail`                                                                             | 1    | mail                                                                                                                                        |
| 31  | `metrics-server`       | 3       | `metrics-server`                                                                   | 1    | kube-system                                                                                                                                 |
| 32  | `minio`                | 11      | `minio`                                                                            | 10   | minio                                                                                                                                       |
| 33  | `monitoring`           | **133** | `monitoring`, `monitoring-v2-operators`, `control-plane-scrape`, `version-checker` | 99   | argocd, authentik, kube-system, monitoring                                                                                                  |
| 34  | `namespaces`           | 14      | `namespaces`                                                                       | 13   | —                                                                                                                                           |
| 35  | `nebula`               | 5       | **none**                                                                           | 10   | nebula                                                                                                                                      |
| 36  | `nvidia-cdi`           | 1       | **comment only**                                                                   | 6    | kube-system                                                                                                                                 |
| 37  | `operators`            | 23      | `operators`                                                                        | 19   | argo, clickhouse, crossplane-system, dragonfly-operator-system, keda, opensearch-operator-system, rabbitmq-system                           |
| 38  | `pihole`               | 11      | `pihole`                                                                           | 10   | pihole                                                                                                                                      |
| 39  | `reflector`            | 3       | `reflector`                                                                        | 6    | kube-system                                                                                                                                 |
| 40  | `registry`             | 6       | `zot` (subpath only)                                                               | 10   | registry, traefik                                                                                                                           |
| 41  | `shared`               | 1       | **none**                                                                           | 2    | —                                                                                                                                           |
| 42  | `storage`              | 7       | `storage`                                                                          | 13   | kube-system, local-path-storage, media, nfs-dr-canary                                                                                       |
| 43  | `talos-dr`             | **0**   | **none**                                                                           | 0    | —                                                                                                                                           |
| 44  | `traefik`              | 8       | `traefik`                                                                          | 26   | traefik                                                                                                                                     |
| 45  | `vpn-gateway`          | 22      | `vpn-gateway`                                                                      | 12   | authentik, traefik, vpn-gateway                                                                                                             |
| 46  | `whoami`               | 3       | `whoami`                                                                           | 1    | authentik, default, traefik                                                                                                                 |

**Sub-structure worth noting** (already grouped, stays as-is):

- `operators/` → `argo-workflows`, `clickhouse-operator`, `crossplane`, `dragonfly-operator`,
  `keda`, `opensearch-operator`, `rabbitmq-operator` (self-service catalog, own aggregator
  kustomization + per-operator Flux `healthChecks`)
- `monitoring/` → 17 subdirs incl. `v2-otel` (the live stack), `grafana-*`, `*-monitoring`,
  `version-checker`, `control-plane-scrape`
- `databases/` → `cloudnative-pg`, `dbgate`, `dbgate-connection-sync`, `minio-operator`,
  `mongodb-operator`, `plugin-barman-cloud`
- `infra-control/` → `goldilocks`, `headlamp`, `kube-ops-view`, `kubeview`
- `aws/` → Crossplane XRDs/Compositions + `apps/` + `buckets/`
- `kube-system/` → `coredns`, `pod-cleanup`, `wedge-buster`

### 4.2 `applications/` — all 12 directories

| Directory            | shape                                        | flux ks                                     | namespaces touched                                     |
| -------------------- | -------------------------------------------- | ------------------------------------------- | ------------------------------------------------------ |
| `arr-stack`          | `base` + `overlays` + scripts + Tiltfile     | `arr-stack`                                 | authentik, media, traefik                              |
| `bt-radar`           | `base`                                       | `bt-radar`                                  | bt-radar                                               |
| `crossplane-demo`    | flat + `celery`/`object`/`plausible`/`tests` | `crossplane-demo`, `crossplane-demo-object` | authentik, crossplane-demo, crossplane-system, traefik |
| `gaming`             | `base` + Tiltfile                            | `gaming` (+ ref'd by `kubevirt`)            | authentik, gaming, traefik                             |
| `home-automation`    | `base` + Tiltfile                            | `home-automation`                           | authentik, home-automation, traefik                    |
| `homepage`           | `base` + `overlays`                          | `homepage`                                  | authentik, homepage, traefik                           |
| `media-experimental` | `base`                                       | `media-experimental` (+ `cluster-settings`) | authentik, media-experimental, traefik                 |
| `metube`             | flat manifests                               | `metube`                                    | authentik, downloads, traefik                          |
| `scratch`            | 6 sub-projects + Tiltfile                    | `scratch`                                   | authentik, catalyst-llm, scratch, traefik, vpn-service |
| `tdarr`              | `base` + scripts + Tiltfile                  | `tdarr`                                     | authentik, tdarr, traefik                              |
| `tubesync`           | flat manifests                               | `tubesync`                                  | authentik, downloads, traefik                          |
| `zipline`            | flat manifests + Tiltfile                    | `zipline`                                   | authentik, media-private, traefik                      |

Layout is **inconsistent**: 6 use `base/`, 4 are flat, 2 are ad-hoc. Two have `overlays/`.

### 4.3 Flux Kustomization inventory — 62 `path:` entries

`clusters/catalyst-cluster/` holds **62 YAML files**, of which **61 are `Kustomization`s**
(`cluster-settings.yaml` is a ConfigMap and declares no path). Those 61 produce **62 distinct
`path:` values** — `external-secrets.yaml` declares two (the operator, then the ClusterStores).
Every one of the 62 is rewritten by this restructure. Full list is machine-derivable:

```bash
grep -h "path: \./" clusters/catalyst-cluster/*.yaml | sed 's/.*path: \.\///' | sort -u
```

Two Kustomizations point at directories that do not exist (see §3).

### 4.4 Test suites — 14 Jest projects

Root `jest.config.js` already declares all 14 as Jest `projects`. Root `package.json` already
carries `jest`, and `scripts/jest-select.js` reads the project list to build its picker.

| Suite dir                                      | `jest.config.js` | `package.json` | `package-lock.json` | `node_modules` |
| ---------------------------------------------- | ---------------- | -------------- | ------------------- | -------------- |
| `infrastructure/base/authentik/tests`          | ✅               | ❌ redundant   | ❌ redundant        | ❌ redundant   |
| `infrastructure/base/backup/tests`             | ✅               | ❌             | ❌                  | ❌             |
| `infrastructure/base/cilium/tests`             | ✅               | ❌             | ❌                  | ❌             |
| `infrastructure/base/databases/tests`          | ✅               | ❌             | ❌                  | ❌             |
| `infrastructure/base/minio/tests`              | ✅               | ❌             | ❌                  | ❌             |
| `infrastructure/base/pihole/tests`             | ✅               | ❌             | ❌                  | ❌             |
| `infrastructure/base/storage/tests`            | ✅               | ❌             | ❌                  | ❌             |
| `infrastructure/base/talos-dr/tests`           | ✅               | ❌             | ❌                  | ❌             |
| `infrastructure/base/traefik/tests`            | ✅               | ❌             | ❌                  | ❌             |
| `infrastructure/base/honeypot/tests`           | ✅               | ❌             | —                   | —              |
| `infrastructure/base/flux-notifications/tests` | ✅               | —              | —                   | —              |
| `infrastructure/base/mail/tests`               | ✅               | —              | —                   | —              |
| `infrastructure/base/vpn-gateway/tests`        | ✅               | —              | —                   | —              |
| `applications/crossplane-demo/tests`           | ✅               | —              | —                   | —              |

**10 stray `package.json`, 9 stray `package-lock.json`, 9 stray `node_modules`.**
The last 4 rows prove the clean shape already works — those suites run today with
`jest.config.js` alone. `node_modules/` and lockfiles are `.gitignore`d, so this is a
working-tree cleanup, not a git diff, except for the 10 `package.json` deletions.

---

## 5. Findings — what is actually mis-grouped

| ID      | Finding                                                                                                                                                                                                                                                                                                               | Evidence                                                  |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| **F1**  | `infrastructure/base/talos-dr/` contains **zero manifests** — only `tests/`. It is a test suite masquerading as an infra component.                                                                                                                                                                                   | `files=0`, `refs=0`                                       |
| **F2**  | `infrastructure/base/shared/` holds one file (`gluetun-sidecar/ipv6-cleanup-init.yaml`) referenced by **no kustomization**. Dead or aspirational.                                                                                                                                                                     | no Flux ks, no `resources:` entry anywhere                |
| **F3**  | `nebula` exists **twice**: `infrastructure/base/nebula/` and `infrastructure/base/hybrid-llm/nebula/`. Neither is Flux-wired.                                                                                                                                                                                         | both unreferenced                                         |
| **F4**  | `infrastructure/base/nvidia-cdi/` is referenced **only in a YAML comment** in `clusters/catalyst-cluster/kubevirt.yaml:8`. It never deploys.                                                                                                                                                                          | comment-only match                                        |
| **F5**  | `infrastructure/base/hybrid-llm/` (8 files, incl. `liqo`, `ollama`, `_scripts`) has **no Flux Kustomization** — but 14 doc references. Docs describe infra that is not deployed.                                                                                                                                      | `ks=[]`, `refs=14`                                        |
| **F6**  | `infrastructure/base/registry/` is a single-child wrapper (`zot/` only), and the Flux ks points at the **subpath**, not the wrapper.                                                                                                                                                                                  | `path: ./infrastructure/base/registry/zot`                |
| **F7**  | Split pairs that should be parent/child, not siblings: `cert-manager` + `cert-manager-issuers`; `kyverno` + `kyverno-policies`; `aws` + `aws-providers`. The `aws/buckets` + `aws/apps` subpath pattern already proves Flux handles nested paths fine.                                                                | 3 pairs                                                   |
| **F8**  | `infrastructure/base/` — the `base/` level is **vestigial**. There is no `infrastructure/overlays/`. It adds a path segment for nothing.                                                                                                                                                                              | `ls infrastructure/` → `_scripts`, `base`, `dashboard.sh` |
| **F9**  | 10 test suites duplicate `jest` as a devDependency and ship their own lockfile + `node_modules`, despite the root config already aggregating them.                                                                                                                                                                    | §4.4                                                      |
| **F10** | 2 Flux Kustomizations point at non-existent paths; 1 of them (`applications/catalyst-llm`) is broken at `HEAD`.                                                                                                                                                                                                       | §3                                                        |
| **F11** | `applications/` layout is inconsistent — 6× `base/`, 4× flat, 2× ad-hoc.                                                                                                                                                                                                                                              | §4.2                                                      |
| **F12** | `infrastructure/_scripts/deploy-stack.sh` is documented in `CLAUDE.md` as legacy pre-Flux "should not be run" — it still sits next to live config.                                                                                                                                                                    | `CLAUDE.md`                                               |
| **F13** | **Index/worktree conflict in `jest.config.js`.** A _staged_ change removes the `honeypot/tests` project (13 projects) and restores cilium's mangled comment; the worktree keeps honeypot (14 projects). `honeypot-security.test.js` is a real suite, so committing the staged version orphans it. Predates this work. | `git diff --cached` vs `git diff`                         |
| **F14** | SPIRE is embedded in `cilium/values.yaml` + `helmrelease.yaml` (mutual auth) with `wedge-buster` RBAC and alerts around it, against a history of recurring expired-token CrashLoops. Not a grouping problem — needs its own decision.                                                                                 | §16.5                                                     |
| **F15** | 7 Taskfiles sit at the repo root (`Taskfile.yaml` + 6 domain files). Same flat-namespace problem as `infrastructure/base/`, just smaller.                                                                                                                                                                             | `ls Taskfile*.yaml`                                       |

---

## 6. AFTER — proposed tree

Groups are **dependency-ordered by numeric prefix**, so `ls` reads bottom-up like the Flux
`dependsOn` DAG.

> **Rule (important):** group directories are **pure namespacing** — they contain **no
> `kustomization.yaml`**. This keeps kustomize from ever accidentally sweeping siblings, and
> keeps every Flux `path:` pointing at a real component, exactly as today.

```
infrastructure/
├── 00-bootstrap/          # everything depends on these
│   ├── namespaces/
│   └── crds/                          ← bootstrap-crds/
├── 10-cluster/            # node + kube-system level plumbing
│   ├── cilium/
│   ├── kube-system/                   (coredns, pod-cleanup, wedge-buster)
│   ├── metrics-server/
│   ├── descheduler/
│   ├── reflector/
│   ├── kyverno/
│   │   └── policies/                  ← kyverno-policies/
│   ├── intel-gpu/
│   └── nvidia-cdi/                    (F4 — unwired, see §12)
├── 20-storage/
│   ├── provisioners/                  ← storage/
│   ├── minio/
│   └── backup/
├── 30-security/
│   ├── external-secrets/
│   ├── cert-manager/
│   │   └── issuers/                   ← cert-manager-issuers/
│   ├── authentik/
│   ├── crowdsec/
│   ├── iocaine/
│   └── honeypot/
├── 40-network/
│   ├── traefik/
│   ├── analytics/                     (traefik middlewares only)
│   ├── external-dns/
│   ├── cloudflare-ddns/
│   ├── pihole/
│   ├── vpn-gateway/
│   └── nebula/                        (F3 — unwired, see §12)
├── 50-data/
│   ├── databases/
│   └── catalyst-cnpg-appdb/
├── 60-controllers/
│   ├── operators/                     (the 7-operator self-service catalog, unchanged)
│   ├── kubevirt/
│   └── aws/
│       ├── providers/                 ← aws-providers/
│       ├── apps/
│       └── buckets/
├── 70-observability/
│   ├── monitoring/                    (133 files — own subtree, unchanged internally)
│   └── flux-notifications/
└── 80-platform/
    ├── argocd/
    ├── registry/                      (F6 — flatten zot/ up one level)
    ├── forgejo/
    ├── infra-control/
    ├── mail/
    ├── gpu-inference/
    ├── hybrid-llm/                    (F5 — unwired, see §12)
    └── whoami/
```

> **See §15 first.** Six of the components placed below are reclassified as _applications_
> after review, which shrinks `80-platform/` from 8 entries to 3.

**Group sizes** (top-level entries): 2, 8, 3, 6, 7, 2, 3, 2, 8 = **41 entries**.
Plus 3 nested (`kyverno/policies`, `cert-manager/issuers`, `aws/providers`) = **44**, plus
`talos-dr` → `tests/` and `shared` → deleted = **46**. Nothing over 8 per group — scannable.

---

## 7. Complete before → after mapping

**All 46 directories accounted for. Nothing is dropped without an explicit line.**

| #   | Before                                       | After                                                | Flux `path:` change   |
| --- | -------------------------------------------- | ---------------------------------------------------- | --------------------- |
| 34  | `infrastructure/base/namespaces`             | `infrastructure/00-bootstrap/namespaces`             | yes                   |
| 7   | `infrastructure/base/bootstrap-crds`         | `infrastructure/00-bootstrap/crds`                   | yes                   |
| 11  | `infrastructure/base/cilium`                 | `infrastructure/10-cluster/cilium`                   | yes                   |
| 26  | `infrastructure/base/kube-system`            | `infrastructure/10-cluster/kube-system`              | yes                   |
| 31  | `infrastructure/base/metrics-server`         | `infrastructure/10-cluster/metrics-server`           | yes                   |
| 15  | `infrastructure/base/descheduler`            | `infrastructure/10-cluster/descheduler`              | yes                   |
| 39  | `infrastructure/base/reflector`              | `infrastructure/10-cluster/reflector`                | yes                   |
| 28  | `infrastructure/base/kyverno`                | `infrastructure/10-cluster/kyverno`                  | yes                   |
| 29  | `infrastructure/base/kyverno-policies`       | `infrastructure/10-cluster/kyverno/policies`         | yes                   |
| 24  | `infrastructure/base/intel-gpu`              | `infrastructure/10-cluster/intel-gpu`                | yes                   |
| 36  | `infrastructure/base/nvidia-cdi`             | `infrastructure/10-cluster/nvidia-cdi`               | n/a (unwired)         |
| 42  | `infrastructure/base/storage`                | `infrastructure/20-storage/provisioners`             | yes                   |
| 32  | `infrastructure/base/minio`                  | `infrastructure/20-storage/minio`                    | yes                   |
| 6   | `infrastructure/base/backup`                 | `infrastructure/20-storage/backup`                   | yes                   |
| 17  | `infrastructure/base/external-secrets`       | `infrastructure/30-security/external-secrets`        | yes (×2)              |
| 9   | `infrastructure/base/cert-manager`           | `infrastructure/30-security/cert-manager`            | yes                   |
| 10  | `infrastructure/base/cert-manager-issuers`   | `infrastructure/30-security/cert-manager/issuers`    | yes                   |
| 3   | `infrastructure/base/authentik`              | `infrastructure/30-security/authentik`               | yes                   |
| 13  | `infrastructure/base/crowdsec`               | `infrastructure/30-security/crowdsec`                | yes                   |
| 25  | `infrastructure/base/iocaine`                | `infrastructure/30-security/iocaine`                 | yes                   |
| 21  | `infrastructure/base/honeypot`               | `infrastructure/30-security/honeypot`                | yes                   |
| 44  | `infrastructure/base/traefik`                | `infrastructure/40-network/traefik`                  | yes                   |
| 1   | `infrastructure/base/analytics`              | `infrastructure/40-network/analytics`                | yes                   |
| 16  | `infrastructure/base/external-dns`           | `infrastructure/40-network/external-dns`             | yes                   |
| 12  | `infrastructure/base/cloudflare-ddns`        | `infrastructure/40-network/cloudflare-ddns`          | yes                   |
| 38  | `infrastructure/base/pihole`                 | `infrastructure/40-network/pihole`                   | yes                   |
| 45  | `infrastructure/base/vpn-gateway`            | `infrastructure/40-network/vpn-gateway`              | yes                   |
| 35  | `infrastructure/base/nebula`                 | `infrastructure/40-network/nebula`                   | n/a (unwired)         |
| 14  | `infrastructure/base/databases`              | `infrastructure/50-data/databases`                   | yes                   |
| 8   | `infrastructure/base/catalyst-cnpg-appdb`    | `infrastructure/50-data/catalyst-cnpg-appdb`         | yes                   |
| 37  | `infrastructure/base/operators`              | `infrastructure/60-controllers/operators`            | yes                   |
| 27  | `infrastructure/base/kubevirt`               | `infrastructure/60-controllers/kubevirt`             | yes                   |
| 4   | `infrastructure/base/aws`                    | `infrastructure/60-controllers/aws`                  | yes (×3)              |
| 5   | `infrastructure/base/aws-providers`          | `infrastructure/60-controllers/aws/providers`        | yes                   |
| 33  | `infrastructure/base/monitoring`             | `infrastructure/70-observability/monitoring`         | yes (×4)              |
| 18  | `infrastructure/base/flux-notifications`     | `infrastructure/70-observability/flux-notifications` | yes                   |
| 2   | `infrastructure/base/argocd`                 | `infrastructure/80-platform/argocd`                  | yes                   |
| 40  | `infrastructure/base/registry/zot`           | `infrastructure/80-platform/registry`                | yes (F6 flatten)      |
| 19  | `infrastructure/base/forgejo`                | `infrastructure/80-platform/forgejo`                 | yes                   |
| 23  | `infrastructure/base/infra-control`          | `infrastructure/80-platform/infra-control`           | yes                   |
| 30  | `infrastructure/base/mail`                   | `infrastructure/80-platform/mail`                    | yes                   |
| 20  | `infrastructure/base/gpu-inference`          | `infrastructure/80-platform/gpu-inference`           | yes                   |
| 22  | `infrastructure/base/hybrid-llm`             | `infrastructure/80-platform/hybrid-llm`              | n/a (unwired)         |
| 46  | `infrastructure/base/whoami`                 | `infrastructure/80-platform/whoami`                  | yes                   |
| 43  | `infrastructure/base/talos-dr/tests`         | `tests/etcd-dr/`                                     | root `jest.config.js` |
| 41  | `infrastructure/base/shared/gluetun-sidecar` | **DELETE** (F2 — dead)                               | none                  |

**Tally:** 44 relocated + 1 relocated-to-tests + 1 deleted = **46**. ✅

Additional non-directory moves:

| Before                                                        | After      | Why                                                                |
| ------------------------------------------------------------- | ---------- | ------------------------------------------------------------------ |
| `infrastructure/_scripts/deploy-stack.sh`                     | **DELETE** | F12 — `CLAUDE.md` already says do not run it                       |
| `infrastructure/_scripts/{bootstrap-argocd,setup-traefik}.sh` | `scripts/` | consolidate; `scripts/bootstrap-argocd.sh` already exists — dedupe |
| `infrastructure/dashboard.sh`                                 | `scripts/` | same                                                               |

---

## 8. Namespace invariance — proof

Namespaces are declared **inside manifests**, never derived from directory path:

- No Flux Kustomization in `clusters/catalyst-cluster/` computes `targetNamespace` from `path`.
- No kustomization uses a path-derived `namePrefix`/`namespace` transformer.
- `kustomize build` output is path-independent (§3), so a matching SHA **is** proof that
  every `metadata.namespace` is unchanged.

The only path-sensitive constructs in the whole infra tree are cross-directory relative
`resources:` entries. There are exactly **two**, and one is commented out:

| File                                                                 | Line | Ref                                                     | Action                                                   |
| -------------------------------------------------------------------- | ---- | ------------------------------------------------------- | -------------------------------------------------------- |
| `infrastructure/base/monitoring/v2-otel/kustomization.yaml`          | 38   | `../../kubevirt/monitoring`                             | rewrite to `../../../60-controllers/kubevirt/monitoring` |
| `infrastructure/base/traefik/components/lan-only/kustomization.yaml` | 8    | `../../infrastructure/base/traefik/components/lan-only` | comment — update text                                    |

That is the entire path-coupling surface. Everything else is self-contained.

---

## 9. Test tree — before / after

### Before

```
infrastructure/base/authentik/tests/{jest.config.js,package.json,package-lock.json,node_modules/,*.test.js}
infrastructure/base/backup/tests/{...same...}
infrastructure/base/cilium/tests/{...}
infrastructure/base/databases/tests/{...}
infrastructure/base/minio/tests/{...}
infrastructure/base/pihole/tests/{...}
infrastructure/base/storage/tests/{...}
infrastructure/base/talos-dr/tests/{...}        ← parent dir has NO manifests (F1)
infrastructure/base/traefik/tests/{...}
infrastructure/base/honeypot/tests/{jest.config.js,package.json,*.test.js}
infrastructure/base/flux-notifications/tests/{jest.config.js,*.test.js}   ← already clean
infrastructure/base/mail/tests/{jest.config.js,*.test.js}                 ← already clean
infrastructure/base/vpn-gateway/tests/{jest.config.js,*.test.js}          ← already clean
applications/crossplane-demo/tests/{jest.config.js,*.test.js}             ← already clean
```

→ **10 `package.json`, 9 `package-lock.json`, 9 `node_modules`**, plus the root one.

### After

Two shapes are viable. **Option A is the minimum change and my recommendation.**

**Option A — keep co-location, delete the redundant manifests.**

```
infrastructure/30-security/authentik/tests/{jest.config.js,authentik-dr.test.js}
infrastructure/20-storage/backup/tests/{jest.config.js,velero-dr.test.js,canary.yaml}
...                                     (every suite: jest.config.js + *.test.js + fixtures)
tests/etcd-dr/{jest.config.js,etcd-dr.test.js}          ← F1: had no component to live in
node_modules/                                            ← the ONLY one
package.json                                             ← the ONLY one
jest.config.js                                           ← projects[] updated to new paths
```

Tests stay next to the thing they test (which is why they were written that way), and there
is exactly one dependency root. Deleting a suite's `package.json` changes nothing at runtime —
`flux-notifications`, `mail`, `vpn-gateway`, and `crossplane-demo` already run this way.

**Option B — move every suite to a top-level `tests/` tree.**

```
tests/{authentik-dr,velero-dr,lbipam-dr,cnpg-dr,minio-dr,pihole-dr,nfs-lifecycle-dr,
       etcd-dr,traefik-dr,honeypot-security,discord-webhook,mail-relay,vpn-dr,
       crossplane-provisioning}/
```

Cleaner `ls` per component; costs co-location and makes "is this component tested?" a
second lookup. Both options need the same `jest.config.js` `projects[]` edit.

**Validation:** `npm run test:all` must list the same 14 suites and produce the same
pass/skip counts before and after. Destructive tiers stay gated behind their env vars.

---

### 9.3 EXECUTED — 2026-08-28

Phase 1 landed via Option A. Verified against the filesystem, not against the executor's report.

| Action                                                        | Result                                                                                                 |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Deleted per-suite `package.json`                              | 10 → **0**                                                                                             |
| Deleted per-suite `package-lock.json`                         | 9 → **0**                                                                                              |
| Deleted per-suite `node_modules/`                             | 9 → **0**                                                                                              |
| `git mv infrastructure/base/talos-dr/tests` → `tests/etcd-dr` | 3 tracked files renamed (`.gitignore`, `etcd-dr.test.js`, `jest.config.js`); empty `talos-dr/` removed |
| Root `jest.config.js` `projects[]`                            | 1 line repointed to `<rootDir>/tests/etcd-dr`                                                          |

Post-conditions, all confirmed:

- **14** `*.test.js` and **14** suite `jest.config.js` still present — none lost
- **6** YAML fixtures intact (`canary.yaml`, `canary-lb.yaml`, `canary-pod.yaml` ×2, `canary-pvc.yaml`, `pentest-job.yaml`)
- `jest --listTests` finds **14**; all 14 projects load and every `displayName` resolves
- **No suite `jest.config.js` was modified** — only the root one
- One `node_modules/`, one `package.json`, at the repo root

**Not committed** — the tree carries unrelated pre-existing changes. Two things to know before
committing:

1. **F13** — the staged-vs-worktree `jest.config.js` conflict over the honeypot project. Resolve
   the honeypot question first; committing blind picks one answer arbitrarily.
2. `infrastructure/base/backup/tests/canary.yaml` shows as modified. **This is not Phase 1's
   doing** — its mtime predates the work by ~35 min and the diff is a hand-written note about
   CNPG/barman vs Velero backup demarcation. Pre-existing.

## 10. `applications/` — before / after

Same grouping rule, lighter touch (12 dirs is not yet painful — this is optional).

| Before                            | Proposed after                     |
| --------------------------------- | ---------------------------------- |
| `applications/arr-stack`          | `applications/media/arr-stack`     |
| `applications/tdarr`              | `applications/media/tdarr`         |
| `applications/tubesync`           | `applications/media/tubesync`      |
| `applications/metube`             | `applications/media/metube`        |
| `applications/media-experimental` | `applications/media/experimental`  |
| `applications/home-automation`    | `applications/home/automation`     |
| `applications/homepage`           | `applications/home/homepage`       |
| `applications/gaming`             | `applications/home/gaming`         |
| `applications/zipline`            | `applications/tools/zipline`       |
| `applications/bt-radar`           | `applications/tools/bt-radar`      |
| `applications/crossplane-demo`    | `applications/lab/crossplane-demo` |
| `applications/scratch`            | `applications/lab/scratch`         |

Same rule as infra: **group dirs carry no `kustomization.yaml`.**

Separately, and independent of grouping: **normalise the shape.** Pick `base/` (+ optional
`overlays/`) for every app, or flat for every app. Right now it is 6 / 4 / 2. My
recommendation is `base/` everywhere, because `arr-stack` and `homepage` already need
`overlays/` and mixed shapes make the Flux `path:` unpredictable.

---

## 11. Blast radius

| Surface                                                   | Count                    | Mechanical?                          |
| --------------------------------------------------------- | ------------------------ | ------------------------------------ |
| Flux `path:` in `clusters/catalyst-cluster/*.yaml`        | 62                       | ✅ sed                               |
| Cross-dir kustomize `resources:` refs                     | 1 (+1 comment)           | ✅ manual, trivial                   |
| `*.md` files mentioning `infrastructure/base/`            | **68** (excl. this plan) | ✅ sed, but review the high-ref docs |
| Shell scripts / Taskfiles                                 | 12 files                 | ⚠️ review — some `cd` into paths     |
| Root `jest.config.js` `projects[]`                        | 14 entries               | ✅ manual                            |
| `.gitignore`, `lefthook.yml`, prettier/markdownlint globs | check                    | ⚠️ review                            |

Highest-churn docs (by reference count): `monitoring` 99, `argocd` 50, `external-secrets` 33,
`cilium` 31, `traefik` 26, `kyverno` 22.

**Mechanics:**

1. `git mv` only — preserves history; `git log --follow` still works.
2. One commit per group (9 commits), each independently `kustomize build`-validated.
3. Flux is **suspended** for the duration, then resumed with `--with-source`
   (per the "fetch source before ks reconcile" rule — a bare `flux reconcile kustomization`
   would apply the _already-fetched_ revision and validate stale state).
4. Because `prune: true` is set on most Kustomizations, the path rewrite and the `git mv`
   **must land in the same commit**. A commit where the ks still points at the old path
   would make Flux see an empty source and prune live resources.

> ⚠️ **This is the single biggest risk in the whole plan.** Never split "move the dir" and
> "update the `path:`" across commits.

---

## 12. Phasing

| Phase  | Work                                                                                                                                                                                              | Risk       | Cluster impact                     |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | ---------------------------------- |
| **0**  | Capture baseline SHAs; promote `scripts/kustomize-baseline.sh`                                                                                                                                    | none       | none                               |
| **1**  | ✅ **DONE** (§9.3) — deleted 10 `package.json`, 9 lockfiles, 9 `node_modules`; moved `talos-dr/tests` → `tests/etcd-dr`. Verified, **uncommitted**; blocked on F13 before commit.                 | low        | **none** — no manifests touched    |
| **2**  | Dead-code removal — `shared/` (F2); resolve `nebula` duplication (F3), `nvidia-cdi` (F4), `hybrid-llm` (F5); fix/delete dangling `catalyst-llm` ks (F10); retire `_scripts/deploy-stack.sh` (F12) | low        | none                               |
| **3**  | Infra grouping — 9 commits, one per group, each SHA-validated                                                                                                                                     | **medium** | Flux suspended → resumed per group |
| **4**  | Split-pair nesting (F7) + `registry` flatten (F6)                                                                                                                                                 | low        | small                              |
| **4b** | Taskfile consolidation (§17) — `git mv` 6 files into `taskfiles/`, rewrite the root `includes:` block, verify `task --list-all` is byte-identical                                                 | low        | none                               |
| **5**  | Doc sweep — 68 markdown files (+46 Taskfile refs, §17)                                                                                                                                            | low        | none                               |
| **6**  | _(optional)_ `applications/` grouping + shape normalisation (§10)                                                                                                                                 | low        | Flux suspended                     |

Phase 1 is complete. Phase 2 likewise touches no live manifests and can land without a
maintenance window. Phase 3 onward needs Q1/Q2 and Q10–Q15 answered first.

---

## 13. Open questions — need your call before Phase 3

| #      | Question                                                                                                       | My recommendation                                                                                                                         |
| ------ | -------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| **Q1** | Numeric prefixes (`00-bootstrap`, `10-cluster`, …) or plain names (`bootstrap/`, `cluster/`, …)?               | **Numeric.** In a repo whose whole correctness model is a `dependsOn` DAG, having `ls` render that order is worth the ugliness.           |
| **Q2** | Drop the vestigial `base/` level (F8)?                                                                         | **Yes.** Every path is being rewritten anyway, so it is free.                                                                             |
| **Q3** | `hybrid-llm/` (F5) — wire it up, archive it, or delete it? It has 14 doc references but has never deployed.    | **Archive** to `docs/05-projects/` — it is a design, not infra.                                                                           |
| **Q4** | `nebula/` duplication (F3) — which copy is canonical?                                                          | Keep `40-network/nebula/`, delete `hybrid-llm/nebula/` with Q3.                                                                           |
| **Q5** | `nvidia-cdi/` (F4) — wire, or delete? It is one file that never deploys but GPU-passthrough docs reference it. | **Wire it** into the `kubevirt` ks (the comment says that was the intent) — or delete. Your call, it is a real functional gap either way. |
| **Q6** | `gpu-inference/` — infra or application? It is a KEDA-scaled Ollama gateway in its own namespace.              | Leave in `80-platform/` for now; it is a platform capability other apps consume.                                                          |
| **Q7** | Tests: §9 Option A (co-located) or Option B (top-level `tests/`)?                                              | **Option A** — least change, keeps tests next to what they test.                                                                          |
| **Q8** | Do `applications/` (Phase 6) at all, or defer?                                                                 | **Defer.** 12 dirs is fine; revisit at ~20. Normalising the `base/` shape (§10) is worth doing on its own though.                         |
| **Q9** | `analytics/` is 3 Traefik middleware files — fold into `40-network/traefik/`?                                  | Fold it. It is not a component, it is part of Traefik's config. But it has its own Flux ks, so this is a ks deletion too.                 |

---

## 14. Validation log

Every factual claim in this document was checked against the filesystem, not asserted.
Re-runnable; results as of the working tree at time of writing.

| ID  | Check                                                                                | Result                                                                          |
| --- | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------- |
| V1  | Every one of the 46 real dirs under `infrastructure/base/` appears in the §7 mapping | ✅ 46/46                                                                        |
| V2  | Every `before` path in the §7 mapping actually exists on disk                        | ✅ no bogus paths                                                               |
| V3  | §7 table row count                                                                   | ✅ 46 data rows                                                                 |
| V4  | §7 index column is exactly `1..46`, each used once                                   | ✅ count=46, distinct=46                                                        |
| V5  | §4.1 per-directory YAML file counts match `find`                                     | ✅ 46/46 match                                                                  |
| V6  | Flux inventory: files / Kustomizations / distinct paths                              | ✅ 62 / 61 / 62 (§4.3 corrected)                                                |
| V7  | Cross-directory relative `resources:` refs — the only path-coupling                  | ✅ exactly 2, one commented                                                     |
| V8  | Stray test manifests: `package.json` / lockfiles / `node_modules`                    | ✅ 10 / 9 / 9                                                                   |
| V8b | Root `jest.config.js` project count                                                  | ✅ 14                                                                           |
| V9  | Blast radius: markdown files / shell+Taskfiles                                       | ✅ 68 / 12                                                                      |
| V10 | F2 — `shared/gluetun-sidecar` referenced by no `kustomization.yaml`                  | ✅ confirmed dead                                                               |
| V11 | F6 — `zot.yaml` points at `.../registry/zot`, not the wrapper                        | ✅ confirmed                                                                    |
| V12 | F8 — no `infrastructure/overlays/` exists                                            | ✅ confirmed vestigial                                                          |
| V13 | §6 group-size arithmetic reconciles to 46                                            | ✅ 41 + 3 nested + 2 relocated/deleted                                          |
| V14 | `kustomize build` baseline over all Flux paths                                       | ✅ 59 OK / 2 MISSING-DIR / 1 BUILD-FAIL — all 3 pre-existing (§3)               |
| V15 | §15.2 — `registry.talos00` image pulls by in-cluster workloads                       | ✅ 4 (bt-radar ×3, crossplane-demo ×1)                                          |
| V16 | §15.3 — no in-cluster git source resolves to forgejo                                 | ✅ 0; sole `GitRepository` targets github.com                                   |
| V17 | §15.4 — `applications/` dirs touching the `authentik` namespace                      | ✅ 11 of 12                                                                     |
| V18 | §15.5 — the three vpn-gateway app manifests exist as separable files                 | ✅ `secure-chrome`, `secure-webtop`, `securexng`                                |
| V19 | §15.6 — no `applications/` dir provides CRDs / classes / cross-family `dependsOn`    | ✅ boundary is clean one-way                                                    |
| V20 | §9.3 — stray test `package.json` / lockfiles / `node_modules` after Phase 1          | ✅ 0 / 0 / 0                                                                    |
| V21 | §9.3 — `*.test.js` and suite `jest.config.js` survivors                              | ✅ 14 and 14                                                                    |
| V22 | §9.3 — `jest --listTests` count and project `displayName` resolution                 | ✅ 14 found, 14/14 names resolve                                                |
| V23 | §9.3 — no suite `jest.config.js` modified (only the root)                            | ✅ confirmed via `git status`                                                   |
| V24 | §9.3 — YAML fixtures preserved                                                       | ✅ 6 (my "expect 5" was wrong — `vpn-gateway/tests/canary-pod.yaml` was missed) |
| V25 | F13 — `jest.config.js` index vs worktree                                             | ⚠️ **divergent**: staged=13 projects, worktree=14                               |
| V26 | §16.1 — CrowdSec consumes the honeypot as a detection source                         | ✅ `honeypot/deployment.yaml:123`                                               |

### Corrections made during validation

1. §4.3 originally said "60 files producing 62 distinct paths". Actual: **62 YAML files, 61
   of them `Kustomization`s, 62 distinct paths** (`cluster-settings.yaml` is a ConfigMap with
   no path; `external-secrets.yaml` declares two).
2. §6 group sizes originally read `2, 9, 3, 7, 7, 2, 3, 2, 8` and did not sum to 46. Restated
   as 41 top-level entries + 3 nested + 2 relocated/deleted.
3. §6/§7 placed `forgejo`, `infra-control`, `whoami`, `gpu-inference`, `honeypot`, and
   `iocaine` inside `infrastructure/`. §15 reclassifies all six as **applications**; §15.9
   records the supersession. `registry` was checked for the same reason and **stays** in
   infrastructure — see the §15.2 trap.
4. §15.3 asserted "nothing consumes" `honeypot` and `iocaine`. **False** — CrowdSec tails
   Cowrie's stdout and Traefik's Bot Wrangler feeds iocaine. Both retracted in §16.1; they stay
   in `infrastructure/30-security/edge/`. Root cause: I read Flux `dependsOn` as a dependency
   graph, but it encodes **apply ordering, not runtime data flow**.
5. §9 predicted 5 YAML fixtures under `tests/`; there are **6**. `vpn-gateway/tests/canary-pod.yaml`
   was missed when the suite list was first sampled.

### Re-running the validation

```bash
# baseline / parity harness (promote to scripts/ at Phase 0)
kustomize-baseline.sh before.txt      # on main, pre-move
kustomize-baseline.sh after.txt       # post-move
diff <(awk '{print $1,$4}' before.txt) <(awk '{print $1,$4}' after.txt)   # paths change, SHAs must not
```

Because paths are the thing being changed, compare **SHA sets**, not path→SHA pairs:

```bash
diff <(awk '/ OK /{print $NF}' before.txt | sort) <(awk '/ OK /{print $NF}' after.txt | sort)
# must be empty — same 59 rendered outputs, different locations
```

---

## 15. Infra ↔ application reclassification

Added after review: several things in `infrastructure/` are applications wearing an infra
costume, and at least one thing that _looks_ like an application is genuinely infrastructure.

### 15.1 The test

> **If this vanished at 3am, would another _workload_ break — or would only its own users notice?**

Supporting signals, in decreasing strength:

1. Is it a `dependsOn` target for another Flux Kustomization?
2. Does another workload reference its Service DNS, or **pull images from it**?
3. Does it install CRDs / admission webhooks / device plugins / CNI / CSI / StorageClasses?
4. Is a browsable UI its _primary_ purpose? (weak signal — see the `registry` trap below)

**Signal 4 alone is a trap.** Grafana, MinIO, ArgoCD, and Zot all have UIs and all are
infrastructure. Presence of an `IngressRoute` proves nothing.

### 15.2 The `registry` trap — why signal 2 decides it

`infrastructure/base/registry/zot` has a web UI and zero `dependsOn` dependents. By UI-and-
dependents reasoning it is an application. It is not:

```
applications/bt-radar/base/20-collector.yaml:46   image: registry.talos00/talos00-registry/bt-collector:latest
applications/bt-radar/base/30-wifi-agent.yaml:62  image: registry.talos00/talos00-registry/wifi-agent:latest
applications/bt-radar/base/40-bt-agent.yaml:57    image: registry.talos00/talos00-registry/bt-agent:latest
applications/crossplane-demo/plausible/exporter/deployment.yaml:46
                                                  image: registry.talos00/.../plausible-stats-exporter:latest
```

and `registry.talos00` is served by Zot's own IngressRoute (`zot/ingressroute.yaml:72`).
**4 in-cluster workloads cannot start if Zot is down.** It stays in infrastructure.

### 15.3 Verdicts — move `infrastructure/` → `applications/`

| Component       | Evidence                                                                                                                                                                                                                                                                                                                               | Verdict                                          |
| --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| `forgejo`       | 0 dependents; the cluster's **only** `GitRepository` points at `github.com/onzack/hubble-observer`, not forgejo; self-contained with its own CNPG postgres. The single in-repo reference to `forge.talos00` is `authentik/forgejo-blueprint.yaml:58` — an OAuth **callback**, i.e. forgejo is an SSO _client_, which is app behaviour. | **APP** — confident                              |
| `infra-control` | goldilocks + headlamp + kube-ops-view + kubeview = 4 admin UIs, 4 IngressRoutes, 0 dependents. They **observe** infra, they don't **provide** it.                                                                                                                                                                                      | **APP** — confident                              |
| `whoami`        | 5 hostnames, diagnostic echo server. A test fixture for authentik/TLS, not a capability.                                                                                                                                                                                                                                               | **APP** — confident                              |
| `honeypot`      | ~~Nothing consumes it~~ **RETRACTED — see §16.** CrowdSec's agent tails Cowrie's stdout (`honeypot/deployment.yaml:123`). It is an IPS _input_.                                                                                                                                                                                        | **INFRA** — `30-security/edge/`                  |
| `iocaine`       | ~~Nothing consumes it~~ **RETRACTED — see §16.** Traefik's Bot Wrangler middleware proxies detected bots _into_ it, and its hits feed CrowdSec.                                                                                                                                                                                        | **INFRA** — `30-security/edge/`                  |
| `gpu-inference` | `ollama.talos00` + KEDA `HTTPScaledObject`. **Nothing in-cluster calls it today** — the only Ollama consumer is `applications/scratch/llm-proxy-archive`, which points at a _different_, archived service.                                                                                                                             | **APP today, platform if apps start calling it** |

### 15.4 Verdicts — stays in `infrastructure/` despite the app smell

| Component        | Why it is genuinely infra                                                                                                                           |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `registry` (zot) | §15.2 — image source for 4 workloads                                                                                                                |
| `authentik`      | Every app's Traefik forward-auth middleware. **11 of 12** `applications/` dirs touch the `authentik` namespace.                                     |
| `minio`          | S3 backing for `backup` and `monitoring` (both `dependsOn` it)                                                                                      |
| `monitoring`     | Grafana has a UI; the stack is the observability capability. 2 dependents.                                                                          |
| `databases`      | `dbgate` is a UI, but the dir provides the CNPG/Mongo/MinIO **operators**. 6 dependents.                                                            |
| `mail`           | Stalwart outbound relay. Nothing consumes it **yet** — it is a scaffold, and its intent (alert email) is a platform capability. Revisit once wired. |

### 15.5 The `vpn-gateway` split

`vpn-gateway` is two things in one directory:

| Stays (capability)                      | Moves (end-user apps)                                         |
| --------------------------------------- | ------------------------------------------------------------- |
| `deployment.yaml` (gluetun)             | `secure-chrome.yaml` → `securechrome.talos00`                 |
| `service.yaml`, `ingressroute-tcp.yaml` | `secure-webtop.yaml` → `webtop.talos00`                       |
| `mtls-ca.yaml`, `gluetun-exporter.yaml` | `securexng.yaml` (+ its ExternalSecret) → `securexng.talos00` |
| `rotation/`, `externalsecret.yaml`      |                                                               |

The three browser/search apps consume the gateway's egress; they are not the gateway.
Splitting them makes the dependency explicit instead of implicit-by-colocation.

> ⚠️ This is the **only** reclassification that moves manifests between namespaces'
> _directories_ while keeping the namespace itself (`vpn-gateway`) unchanged. Verify the
> resulting two kustomizations still render the union of today's objects.

### 15.6 Reverse direction — nothing needs to move `applications/` → `infrastructure/`

Checked every app dir for CRDs, DaemonSets, StorageClasses/IngressClasses, and inbound
`dependsOn` edges:

- `bt-radar` and `tdarr` each ship a DaemonSet, but they are **self-scoped node agents**, not
  cluster capabilities.
- `crossplane-demo` and `homepage` show inbound edges only from **within their own family**
  (`crossplane-demo-object` → `crossplane-demo`).

**The boundary is already clean one-way.** No app provides a capability infra consumes.

### 15.7 Resulting `applications/` shape

Folding §10's grouping together with these moves:

```
applications/
├── media/      arr-stack, tdarr, tubesync, metube, experimental
├── home/       automation, homepage, gaming
├── tools/      zipline, bt-radar, forgejo ←NEW
├── ops/        infra-control ←NEW  (goldilocks, headlamp, kube-ops-view, kubeview)
├── security/   honeypot ←NEW, iocaine ←NEW
├── vpn/        secure-chrome ←NEW, secure-webtop ←NEW, securexng ←NEW
└── lab/        crossplane-demo, scratch, whoami ←NEW, gpu-inference ←NEW?
```

`infrastructure/80-platform/` shrinks from 8 entries to **3** (`argocd`, `registry`, `mail`),
which is the strongest evidence the original group was doing too much work. Consider folding
those three into `70-observability` → rename to `70-services`, and dropping `80-platform`
entirely.

### 15.8 The three-tier alternative

If `80-platform` shrinking to 3 feels like a smell, the honest alternative is **three top-level
tiers** instead of two:

```
infrastructure/   cluster capabilities   (cilium, storage, cert-manager, traefik, kyverno …)
platform/         shared services        (authentik, databases, minio, registry, monitoring, argocd, mail)
applications/     end-user workloads     (media, home, tools, ops, security, lab)
```

**Trade-off:** it is the more honest model and makes the "who may depend on whom" rule
directional and enforceable (apps→platform→infra, never upward). It also **doubles the Flux
`path:` churn** and adds a third boundary to argue about at 2am. My recommendation is to do
the two-tier version now (§15.3–15.5), live with it, and only split out `platform/` if the
`infrastructure/` groups start feeling mixed again.

### 15.9 Impact on the §7 mapping

These moves supersede §7 for **4** entries (§16 pulls `honeypot` and `iocaine` back). Net effect on the infra tree: **44 → 40** components.

| §7 said                     | §15 says                                            |
| --------------------------- | --------------------------------------------------- |
| `80-platform/forgejo`       | `applications/tools/forgejo`                        |
| `80-platform/infra-control` | `applications/ops/infra-control`                    |
| `80-platform/whoami`        | `applications/lab/whoami`                           |
| `80-platform/gpu-inference` | `applications/lab/gpu-inference` _(pending Q11)_    |
| `30-security/honeypot`      | `30-security/edge/honeypot` — **not** an app (§16)  |
| `30-security/iocaine`       | `30-security/edge/iocaine` — **not** an app (§16)   |
| `40-network/vpn-gateway`    | split — gateway stays, 3 apps → `applications/vpn/` |

### 15.10 New open questions

| #       | Question                                                                                                                                | Recommendation                                                                 |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| **Q10** | Two-tier (move apps out) or three-tier (`infrastructure/` + `platform/` + `applications/`)?                                             | **Two-tier now.** §15.8.                                                       |
| **Q11** | `gpu-inference` — app or platform? Nothing calls it today, but it is built to be called.                                                | Leave in infra until a second consumer appears; moving it back later is cheap. |
| **Q12** | ~~`iocaine` + `honeypot` — apps or edge posture?~~ **RESOLVED — §16.** Both stay in infra, in `30-security/edge/` alongside `crowdsec`. | Resolved by evidence; supersedes §15.3.                                        |
| **Q13** | Split `vpn-gateway` (§15.5), or leave the 3 browser apps colocated?                                                                     | Split. The colocation hides a real dependency.                                 |
| **Q14** | `mail` — leave in infra as an unwired platform scaffold, or move to apps until something uses it?                                       | Leave. Moving a scaffold twice is churn.                                       |

---

## 16. The security domain — correcting §15

Raised in review: _"can we create a security group where honeypot / iocaine and crowdsec are?"_

**Yes — and §15 was wrong about two of them.** The correction matters, so it is recorded rather
than quietly patched.

### 16.1 What §15 got wrong

§15.3 classified `honeypot` and `iocaine` as applications on the grounds that _"nothing consumes
them."_ That is false:

```
infrastructure/base/honeypot/deployment.yaml:123
  # (b) the CrowdSec agent (CRI stdout tail -> crowdsecurity/cowrie parser
```

CrowdSec's agent **tails Cowrie's stdout as a detection source.** Per `SECURITY_ops.md`, iocaine
is wired the same way — Traefik's Bot Wrangler middleware proxies detected bots _into_ the maze,
and the hits feed CrowdSec. These are not standalone workloads that happen to be security-themed;
they are **sensors feeding an IPS.** Removing either degrades CrowdSec's detection.

The signal I applied too literally was "0 `dependsOn` dependents." Flux `dependsOn` encodes
_apply ordering_, not _runtime data flow_. A log-shipping relationship is invisible to it.

### 16.2 The repo already decided this — TALOS-c4q

`SECURITY_ops.md` documents all three as **one cooperating system** ("Layered, deception-driven
defense... Three cooperating systems"), and it already carries the ticket:

> **Consolidation** (deferred, TALOS-c4q): folding crowdsec/honeypot/iocaine into a shared
> `security` namespace + `infrastructure/base/security/` folder is planned but disruptive
> (workload moves, ref updates)... **Less-disruptive alternative on the ticket: keep the
> namespaces, just regroup the repo folder.**

That alternative is _exactly_ this restructure's constraint (§2: no namespace changes). **This
plan is the natural home for TALOS-c4q** — link them.

Further corroboration that "security" is already a first-class domain here:
`Taskfile.security.yaml` exists (`task security:*`), and `honeypot` and `iocaine` each ship a
`cilium-network-policy.yaml` in the identical sibling pattern.

### 16.3 Proposed `30-security/`

```
infrastructure/30-security/
├── external-secrets/          # secrets management — 14 dependents
├── cert-manager/              # PKI / TLS
│   └── issuers/
├── authentik/                 # identity — 11 of 12 apps use its forward-auth
└── edge/                      # ← TALOS-c4q: the deception-driven edge defense stack
    ├── crowdsec/              #   the brain (LAPI + agent + AppSec + bouncer middleware)
    ├── honeypot/              #   Cowrie — bait, feeds crowdsec
    └── iocaine/               #   tarpit — Bot Wrangler proxies into it, feeds crowdsec
```

The `edge/` nesting makes the repo mirror `SECURITY_ops.md`'s "The layers" section 1:1, and
separates _security capabilities other things depend on_ (secrets, PKI, identity) from _the
cooperating detection/response stack_.

### 16.4 Stays put — with reasons

| Component                                            | Why it does **not** move into `30-security/`                                                                                                                                                                                                                                                             |
| ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Traefik's `bouncer` plugin + Bot Wrangler middleware | They are Traefik **entrypoint config**, bound globally via `--entrypoints.*.http.middlewares`. They must ship with Traefik or the ingress breaks.                                                                                                                                                        |
| `kyverno` + `kyverno-policies`                       | Tempting, but the policy set is **mixed-purpose**: `pod-security-baseline.yaml` and `ingressroute-tls-default.yaml` are security; `homepage-annotation-derivation.yaml` and `helmrelease-remediation-defaults.yaml` are plain automation. Kyverno is a _mechanism_, not a domain. Keep in `10-cluster/`. |
| `vpn-gateway/mtls-ca.yaml`                           | Belongs with the gateway it issues certs for.                                                                                                                                                                                                                                                            |
| The 4 scattered `CiliumNetworkPolicy` files          | Network policy belongs **next to the workload it protects**. Centralising them would be worse.                                                                                                                                                                                                           |

I checked `kyverno-policies/dragonfly-allow-monitoring.yaml` on suspicion of being a misfiled
NetworkPolicy — it is a genuine Kyverno `ClusterPolicy` that _generates_ one. **Not a misfile.**

### 16.5 Unrelated finding — SPIRE

The sweep surfaced SPIRE embedded in `cilium/values.yaml` + `helmrelease.yaml` (Cilium mutual
auth), with `wedge-buster` RBAC and memory-pressure alerts referencing it. Prior operational
history on this component is bad — recurring expired-token CrashLoops that survived two
attempted fixes.

**Not a grouping problem, so out of scope here** — but it deserves its own ticket: decide whether
Cilium mutual auth is earning its keep, rather than continuing to patch the agent.

### 16.6 Revised open question

| #       | Question                                                                                                    | Recommendation                                                                                                                                        |
| ------- | ----------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Q15** | Nest the stack as `30-security/edge/{crowdsec,honeypot,iocaine}`, or keep the three flat in `30-security/`? | **Nest.** It mirrors `SECURITY_ops.md` and keeps capabilities visually distinct from the detection stack. Flat is fine if the extra level annoys you. |

---

## 17. Taskfile consolidation

Small, self-contained, zero cluster risk — the same flat-namespace problem as
`infrastructure/base/`, at 1/7th the scale.

### Before

```
Taskfile.yaml            # root orchestrator — STAYS
Taskfile.certs.yaml
Taskfile.dev.yaml
Taskfile.infra.yaml
Taskfile.k8s.yaml
Taskfile.security.yaml
Taskfile.talos.yaml
```

### After

```
Taskfile.yaml            # root orchestrator — unchanged location
taskfiles/
├── certs.yaml
├── dev.yaml
├── infra.yaml
├── k8s.yaml
├── security.yaml
└── talos.yaml
```

### Mechanics

The only functional edit is the root `includes:` block — 6 lines:

```yaml
includes:
  talos: taskfiles/talos.yaml
  k8s: taskfiles/k8s.yaml
  dev: taskfiles/dev.yaml
  infra: taskfiles/infra.yaml
  security: taskfiles/security.yaml
  certs: taskfiles/certs.yaml
```

**Namespaces are preserved** — `task talos:health`, `task dev:lint`, `task security:*` all keep
working, because the include _key_ (not the filename) defines the namespace.

### Blast radius

**46 references** across the repo, concentrated in docs. `docs/07-reference/taskfile-organization.md`
is the canonical description of this layout and must be rewritten, not sed'd. `Taskfile.security.yaml`
references a sibling and needs checking after the move.

### Validation

```bash
task --list-all > /tmp/tasks-before.txt      # BEFORE
task --list-all > /tmp/tasks-after.txt       # AFTER
diff /tmp/tasks-before.txt /tmp/tasks-after.txt   # MUST be empty
```

An empty diff proves every task in every namespace still resolves. Drop the `taskfiles/` name if
you prefer `.taskfiles/` (hidden) — purely cosmetic; the include paths change either way.

---

## 18. Worktree hygiene — the nested-checkout hazard

Surfaced while auditing `node_modules` sprawl. Not part of the restructure, but it shares a root
cause with it and it bites Phase 5.

### 18.1 What was there

21 worktrees under `.claude/worktrees/`, **358 MB** — 13 from `isolation: "worktree"` agent runs
(the Authentik SSO campaign) and 8 from one Workflow fan-out (`wf_e69817ae`, the Jest DR suites).

> **Not a discrepancy:** `git worktree list` shows **22** rows for **21** worktrees. The extra row
> is the main checkout. `n+1` is correct output, not a leak.

### 18.2 Why they never auto-cleaned

Worktrees auto-remove only when left pristine. All 21 showed the **same 45 modified files** —
byte-identical across every one, all `ExternalSecret` manifests, all `v1beta1` → `v1`.

That migration is **already committed in main** (0 `v1beta1` left, 50 files on `v1`). The branch
tips predate it. So: a repo-wide `sed` during the ESO migration **walked into `.claude/worktrees/`
and rewrote all 21 stale copies.** That permanent dirtiness is precisely what defeated cleanup.

**The worktrees are full repo checkouts nested inside the repo.** Any recursive tool run from the
root — `sed`, `find`, `prettier`, a doc sweep — hits all of them.

> ⚠️ **This directly threatens Phase 5** (§12), which sed's ~68 markdown files plus 46 Taskfile
> references. Unscoped, it would rewrite every live worktree the same way.

### 18.3 Merge validation — all 21 merged, zero unique work

`git cherry` reported `+` (unique) for 17 of 21 and was **wrong** — patch-id does not survive
squash/rebase. Two stronger tests:

| Test                                                 | Result               |
| ---------------------------------------------------- | -------------------- |
| Files touched by the branch but **absent from main** | **0**, across all 21 |
| Branch's added lines still present in main           | 83–100% on 20 of 21  |

The one outlier, `agent-a79b9679bd604b187` at 70%, was chased to ground: main's
`discord-bridge.yaml` is **174 lines vs the branch's 102**. The branch shipped
`image: ghcr.io/rogerrum/alertmanager-discord:1.0.7`; main **replaced** it with a self-hosted
`python:3.12-alpine` inline bridge — same Service name, same port 9094, and `config-template.yaml`
wires `webhook_configs` to it. The work landed and was then rewritten. Literal line-matching
undercounts a rewrite; it does not mean work was lost.

### 18.4 The fix

| Change                                       | Purpose                                                                                                 |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `.prettierignore` += `.claude/`              | **Was the only gap.** `.gitignore` and `.markdownlint-cli2.yaml` already excluded it; prettier did not. |
| `scripts/worktree-audit.sh`                  | Read-only merge check; non-zero exit if any worktree holds files absent from main                       |
| `scripts/worktree-cleanup.sh`                | Prints recoverable branch SHAs, then removes worktrees + branches                                       |
| `task dev:worktree:{list,audit,clean,guard}` | `guard` re-checks that every repo-wide tool config still excludes `.claude/`                            |

**Habit for ad-hoc sweeps** — scope them, always:

```bash
grep -r ... --exclude-dir=.claude --exclude-dir=node_modules
find . -path ./.claude -prune -o -name '*.yaml' -print
```

### 18.5 Scale note

The 21 worktree `node_modules` copies were **~340 MB** — roughly 20× the ~15 MB freed by the
Phase 1 test-suite consolidation (§9.3). The visible mess was not where the disk actually went.

---

## Related Issues

<!-- Beads tracking for this doc -->

- **TALOS-scrp** (epic, P1) — tracks this document and the implementation of the directory-structure
  refactor. **Deliberately has no child tickets yet** — phases are not broken out until this document
  has been reviewed and the open questions (§13, §15.10, §16.6) are answered.

- **TALOS-c4q** — crowdsec/honeypot/iocaine consolidation. §16 implements the ticket's
  "less-disruptive alternative" (regroup the repo folder, keep namespaces).
