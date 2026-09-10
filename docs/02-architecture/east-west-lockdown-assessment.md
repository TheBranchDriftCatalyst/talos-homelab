# East-West NetworkPolicy Lockdown — Assessment

> **Status:** read-only audit, decision input for beads epic `TALOS-lxz5.3.1`.
> **Nothing in this document has been applied.** No manifest was changed.
> **Evidence date:** 2026-09-10, live cluster (`catalyst-cluster`, Cilium v1.20.0, 5 nodes).

## TL;DR

- **31 of 321 pod endpoints (9.7%) enforce ingress policy. 290 are wide open** — any pod
  in any namespace can open a TCP connection to any of them.
- **The single highest-value wide-open target is not a database.** It is
  `external-secrets/onepassword-connect:8080`, the credential broker behind **154
  ExternalSecrets**, followed by `minio/minio-pool-0:9000`, which holds the **Velero
  bucket and the barman backups of all 20 CNPG clusters**.
- **17 of 20 CNPG Postgres clusters are wide open on `:5432`**, including
  `authentik-postgres` (the SSO identity database). The 3 already known
  (stash-box / whisparr / zipline) are a subset, not the whole problem.
- **The existing canonical DB convention is actively broken in production.** The only
  policy drops anywhere in the cluster are Alloy → CNPG `:9187` on the *two* databases
  that follow it (`hot-ones`, `scene-engine`). Both have **zero** Postgres metrics;
  their three unprotected neighbours in the same namespace have full metrics. Rolling
  this convention out as written would blind monitoring on all 20 clusters.
- **Hubble flow capture works** (576 flows/s) but the ring buffer holds **~28 seconds**
  and file export is **off**. Audit-first is feasible but requires a config change first.
- **Recommendation: strategy (b) then (a).** Fix the convention's `:9187` gap, harden the
  ~12 crown-jewel targets with per-workload policies, and only then consider
  namespace default-deny. **Do not** do cluster-wide default-deny (c).

---

## 1. Method (how "restricted" was determined)

Reading manifests is not sufficient — a policy can exist and select nothing. Two of them
do: `media-private/stash-box` and `media-private/hot-ones-ingress` select `app: stash-box`
and `app: hot-ones`, and **neither app has a running pod**, so both policies are inert.

Ground truth here is Cilium's own realized state. For every endpoint on all 5 agents:

```
cilium endpoint list -o json  →  .status.policy.realized.policy-enabled
```

joined to pods by IP. `policy-enabled` is one of `none` / `ingress` / `egress` / `both`;
anything other than `ingress`/`both` means **no ingress policy selects that pod**, and
Cilium's default-allow applies.

| enforcement | endpoints |
|---|---|
| `both` (ingress + egress) | 18 |
| `ingress` only | 13 |
| **`none` (wide open)** | **290** |
| **total** | **321** |

Cluster policy posture confirms default-allow is in force:
`enable-policy = default`, `policy-cidr-match-mode` empty, `enable-k8s-networkpolicy = true`,
and **zero** `CiliumClusterwideNetworkPolicy` objects exist.

---

## 2. Existing policy inventory and ownership

18 CiliumNetworkPolicies + 39 NetworkPolicies. Ownership splits cleanly:

| owner | GitOps controller | policies |
|---|---|---|
| `talos-homelab` | **Flux** (single `GitRepository`, 62 Kustomizations) | honeypot (3 CNP), iocaine (3 CNP), teak-talos-dev (6 CNP), authentik-cache, argocd (6 netpol + 2 monitoring), crowdsec (2), gaming/guacamole, argocd-image-updater, scratch/grpc-example mTLS |
| `talos-private` | **ArgoCD** (app `arr-stack-private`) | all 11 `media-private` policies — verified via `argocd.argoproj.io/tracking-id` on `netpol/stash-box` |
| upstream chart | Flux (vendored) | `monitoring/tempo-operator-*` (4), `argocd-image-updater` |

Source files:

**talos-homelab (Flux):**
- `infrastructure/base/honeypot/cilium-network-policy.yaml`
- `infrastructure/base/iocaine/cilium-network-policy.yaml`
- `infrastructure/base/teak-talos-dev/cilium-network-policy.yaml`
- `infrastructure/base/authentik/dragonfly-network-policy.yaml`
- `infrastructure/base/argocd/netpol-allow-monitoring.yaml`
- `infrastructure/base/crowdsec/{decision-exporter,webui-network-policy}.yaml`
- `applications/gaming/base/kubevirt/guacamole-network-policy.yaml`
- `applications/scratch/grpc-example/k8s/mtls-policies.yaml`

**talos-private (ArgoCD):**
- `base/{stash,stash-ai,stash-box,stash-tagger,whisparr-eros}/networkpolicy.yaml`
- `base/hot-ones/{database-networkpolicy.yaml,cam.yaml}`
- `base/scene-engine/{networkpolicy.yaml,face-deployment.yaml,database/networkpolicy.yaml}`
- `base/auth/reconciler.yaml`

### 2.1 The three patterns in use

**Pattern A — namespace default-deny + additive allowlist** (`honeypot`, `iocaine`,
`teak-talos-dev`). A `CiliumNetworkPolicy` with `endpointSelector: {}` and empty
`ingress: [{}]` / `egress: [{}]` rules turns the whole namespace deny-by-default, then
separate CNPs add back exactly what is needed. `teak-talos-dev` is the most complete
worked example and includes the three things that are always required and always
forgotten:

- `allow-intra-namespace` — `fromEndpoints: [{}]` / `toEndpoints: [{}]` (same-namespace),
  which is what lets an app reach its own Postgres and lets CNPG instances replicate;
- `allow-cluster-plumbing-egress` — kube-dns **and** `toEntities: [kube-apiserver]`. The
  file's own comment records why the API server is non-optional: the CNPG instance manager
  calls it from inside the pod, and omitting it means the Postgres cluster never forms quorum
  "with confusing symptoms that look like storage or image problems";
- explicit ingress for probes — honeypot keeps `fromCIDR: 10.244.0.0/16` specifically
  because the kubelet liveness probe arrives from the pod CIDR.

These files are unusually well-commented and are the right template to copy.

**Pattern B — per-workload allowlist, no default-deny** (`media-private`, `argocd`,
`openscad`, `crowdsec`, `gaming`). A `NetworkPolicy` naming one workload. Because
Kubernetes NetworkPolicy is deny-by-default *for pods it selects*, this restricts that
workload without touching the rest of the namespace. This is the lower-risk pattern and
is already the majority.

**Pattern C — the CNPG DB convention**, documented at
`talos-private/base/_conventions/README-cnpg-db-networkpolicy.md`. See §4 — it has a
live defect.

---

## 3. Coverage map

`ingress-restricted?` is Cilium's realized `policy-enabled`, not the presence of a manifest.
Only pod-network workloads are listed (host-network pods are not Cilium endpoints and are
not policy-enforceable here). CNPG replica sets are collapsed as `×N`.

#### `argo`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `argo-workflows-server` | 2746 | **NO** |  |
| `argo-workflows-workflow-controller` | 6060,9090 | **NO** |  |

#### `argocd`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `argocd-application-controller` | 8082 | YES (ingress) |  |
| `argocd-applicationset-controller` | 7000,8080,8081 | **NO** |  |
| `argocd-dragonfly` | 6379,9999 | YES (ingress) |  |
| `argocd-notifications-controller` | 9001 | YES (ingress) |  |
| `argocd-repo-server` | 8081,8084 | YES (ingress) |  |
| `argocd-server` | 8080,8083 | YES (ingress) |  |

#### `argocd-image-updater-system`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `argocd-image-updater-controller` | — | YES (ingress) |  |

#### `authentik`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `amberdark-outpost` | 9000 | **NO** |  |
| `authentik-cache` | 6379,9999 | YES (ingress) | Dragonfly (Redis) |
| `authentik-postgres ×3` | 5432,8000,9187 | **NO** | **SSO identity DB** (users, tokens, app secrets) |
| `authentik-server` | 9000,9300,9443 | **NO** | SSO issuer / OIDC + proxy outposts |
| `authentik-worker` | 9000,9300 | **NO** |  |
| `catalyst-bg` | 8080 | **NO** |  |

#### `backup`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `node-agent` | 8085 | **NO** |  |
| `velero` | 8085 | **NO** |  |
| `velero-critical-data-daily-20260910023017-frtwl` | — | UNKNOWN |  |

#### `boomtime`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `books-postgres` | 5432,8000,9187 | **NO** | CNPG cluster |
| `boomtime` | 8080 | **NO** |  |
| `boomtime-cache` | 6379,9999 | YES (ingress) | Dragonfly (Redis) |
| `boomtime-postgres ×3` | 5432,8000,9187 | **NO** | CNPG cluster |
| `catalyst-books` | 8080 | **NO** |  |

#### `bt-radar`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `bt-collector` | 8080 | **NO** |  |
| `bt-radar-postgres ×2` | 5432,8000,9187 | **NO** | CNPG cluster |

#### `catalyst`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `catalyst-ui` | 80 | **NO** |  |

#### `catalyst-data`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `dagster-postgres` | 5432,8000,9187 | **NO** | CNPG cluster |
| `postgres-knowledge` | 5432,8000,9187 | **NO** |  |

#### `catalyst-llm`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `litellm` | 4000 | **NO** | LLM gateway — provider API keys |
| `litellm-postgresql` | 5432 | **NO** | LLM gateway DB (keys/usage) |
| `lobe-chat` | 3210 | **NO** |  |
| `open-webui` | 8080 | **NO** |  |
| `searxng` | 8080 | **NO** |  |

#### `cdi`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `cdi-apiserver` | — | **NO** |  |
| `cdi-deployment` | 8080 | **NO** |  |
| `cdi-operator` | 8080 | **NO** |  |
| `cdi-uploadproxy` | — | **NO** |  |

#### `cert-manager`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `cert-manager` | 9402,9403 | **NO** |  |
| `cert-manager-cainjector` | 9402 | **NO** |  |
| `cert-manager-webhook` | 6080,9402,10250 | **NO** |  |
| `trust-manager` | 6443,9402 | **NO** |  |

#### `clickhouse`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `clickhouse-operator` | 8888,9999 | **NO** |  |

#### `crossplane-demo`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `chi-plausible-plausible-0` | 8123,9000,9009 | **NO** |  |
| `plausible` | 8000 | **NO** |  |
| `plausible-db ×3` | 5432,8000,9187 | **NO** |  |
| `plausible-stats-exporter` | 8080 | **NO** |  |

#### `crossplane-system`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `crossplane` | 8081,9443 | **NO** |  |
| `crossplane-rbac-manager` | — | **NO** |  |
| `function-patch-and-transform-4d729ddc8ee1` | 8080,9443 | **NO** |  |
| `provider-aws-cloudwatchlogs-ccc877ee0e60` | 8080,9443 | **NO** |  |
| `provider-aws-ec2-1acd8c7cadf9` | 8080,9443 | **NO** |  |
| `provider-aws-ecs-978a6c1f972a` | 8080,9443 | **NO** |  |
| `provider-aws-iam-af6f729a7033` | 8080,9443 | **NO** |  |
| `provider-aws-s3-36c8e1a828a1` | 8080,9443 | **NO** |  |
| `provider-kubernetes-f6665ef36536` | 8080,9443 | **NO** |  |
| `upbound-provider-family-aws-0ecbf4952fdd` | 8080,9443 | **NO** |  |

#### `crowdsec`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `crowdsec-agent` | 6060 | **NO** |  |
| `crowdsec-appsec` | 6060,7422 | **NO** |  |
| `crowdsec-decision-exporter` | 9108 | YES (ingress+egress) |  |
| `crowdsec-lapi` | 6060,8080 | **NO** | security decisions API |
| `crowdsec-postgres ×3` | 5432,8000,9187 | **NO** | CNPG cluster |
| `crowdsec-web-ui` | 3000 | YES (ingress) |  |

#### `databases`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `cloudnative-pg` | 8080,9443 | **NO** |  |
| `dbgate` | 3000 | **NO** | DB web client (multi-DB creds) |
| `minio-operator` | — | **NO** |  |
| `mongodb-kubernetes-operator` | — | **NO** |  |
| `plugin-barman-cloud` | 9090 | **NO** |  |

#### `default`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `whoami` | 80 | **NO** |  |

#### `downloads`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `metube` | 8081 | **NO** |  |
| `tubesync` | 4848 | **NO** |  |

#### `dragonfly-operator-system`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `dragonfly-operator` | 8080,8443 | **NO** |  |

#### `dungeon-library`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `dungeon-library` | 3000 | **NO** |  |
| `postgres` | 5432 | **NO** | plain Postgres StatefulSet (no CNPG) |

#### `external-dns`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `external-dns` | — | **NO** |  |
| `external-dns-amberdark` | — | **NO** |  |
| `external-dns-cf-exporter` | 9100 | **NO** |  |

#### `external-secrets`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `external-secrets` | 8080 | **NO** |  |
| `external-secrets-cert-controller` | 8080,8081 | **NO** |  |
| `external-secrets-webhook` | 8080,8081,9443 | **NO** |  |
| `onepassword-connect` | 8080,8081 | **NO** | **secret broker — backs 154 ExternalSecrets** |

#### `flux-system`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `helm-controller` | 8080,9440 | **NO** |  |
| `kustomize-controller` | 8080,9440 | **NO** | cluster-admin reconciler |
| `notification-controller` | 8080,9090,9292,9440 | **NO** |  |
| `source-controller` | 8080,9090,9440 | **NO** | Flux artifacts (repo tarballs) |

#### `forgejo`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `forgejo` | 3000 | **NO** | self-hosted git |
| `forgejo-postgres ×3` | 5432,8000,9187 | **NO** | CNPG cluster |

#### `gaming`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `guacamole` | 8080 | YES (ingress+egress) |  |
| `guacamole-postgres` | 5432,8000,9187 | **NO** | CNPG cluster |
| `guacd` | 4822 | **NO** |  |
| `opensim` | 9000 | **NO** |  |
| `windows-novnc` | 5900,8080 | **NO** |  |

#### `home-automation`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `homeassistant-postgres ×3` | 5432,8000,9187 | **NO** | CNPG cluster |
| `linkwarden` | 3000,7700 | **NO** |  |
| `linkwarden-postgres ×3` | 5432,8000,9187 | **NO** | CNPG cluster |
| `omnitools` | 80 | **NO** |  |

#### `homepage`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `homepage-apps` | 3000 | **NO** |  |
| `homepage-arrs` | 3000 | **NO** |  |
| `homepage-data` | 3000 | **NO** |  |
| `homepage-home` | 3000 | **NO** |  |
| `homepage-infra` | 3000 | **NO** |  |
| `homepage-llm` | 3000 | **NO** |  |
| `homepage-master` | 3000 | **NO** |  |
| `homepage-obs` | 3000 | **NO** |  |

#### `honeypot`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `cowrie` | 2222,2223 | YES (ingress+egress) |  |

#### `infra-control`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `goldilocks-controller` | — | **NO** |  |
| `goldilocks-dashboard` | 8080 | **NO** |  |
| `headlamp` | 4466 | **NO** | admin UI (cluster) |
| `kube-ops-view` | 8080 | **NO** |  |
| `kubeview` | 8000 | **NO** |  |

#### `intel-device-plugins`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `intel-gpu-plugin-intel-gpu-plugin` | — | **NO** |  |
| `inteldeviceplugins-controller-manager` | 9443 | **NO** |  |

#### `iocaine`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `iocaine` | 8080 | YES (ingress+egress) |  |

#### `keda`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `keda-add-ons-http-controller-manager` | 8081,8443 | **NO** |  |
| `keda-add-ons-http-external-scaler` | 2223,9090 | **NO** |  |
| `keda-add-ons-http-interceptor` | 8080,9090 | **NO** |  |
| `keda-admission-webhooks` | 9443 | **NO** |  |
| `keda-operator` | 8080,9666 | **NO** |  |
| `keda-operator-metrics-apiserver` | 6443,8080 | **NO** |  |

#### `kube-system`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `cloudflare-ddns` | — | **NO** |  |
| `cloudflare-ddns-amberdark` | — | **NO** |  |
| `coredns` | 53,9153 | **NO** |  |
| `hubble-relay` | 4245 | **NO** |  |
| `hubble-ui` | 8081,8090 | **NO** |  |
| `kernel-panic-capture` | — | **NO** |  |
| `metrics-server` | 10250 | **NO** |  |
| `nfs-subdir-external-provisioner` | — | **NO** |  |
| `reflector` | 8080 | **NO** |  |
| `vpa-recommender` | 8942 | **NO** |  |

#### `kubernetes-dashboard`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `dashboard-metrics-scraper` | 8000 | **NO** |  |
| `kubernetes-dashboard` | 8443 | **NO** | admin UI |

#### `kubevirt`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `virt-api` | 8443 | **NO** |  |
| `virt-controller` | 8443 | **NO** |  |
| `virt-handler` | 8443 | **NO** |  |
| `virt-operator` | 8443,8444 | **NO** |  |

#### `kyverno`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `kyverno-admission-controller` | 8000,9443 | **NO** |  |
| `kyverno-background-controller` | 8000,9443 | **NO** |  |
| `kyverno-cleanup-controller` | 8000,9443 | **NO** |  |
| `kyverno-reports-controller` | 8000,9443 | **NO** |  |

#### `local-path-storage`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `local-path-provisioner` | — | **NO** |  |

#### `media`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `arr-postgres ×3` | 5432,8000,9187 | **NO** | CNPG cluster |
| `jellyfin` | 8096,8920 | **NO** |  |
| `kometa` | — | **NO** |  |
| `maintainerr` | 6246 | **NO** |  |
| `posterizarr` | 8000 | **NO** |  |
| `posterr` | 3000 | **NO** |  |
| `prowlarr` | 9696 | **NO** |  |
| `pulsarr` | 3003 | **NO** |  |
| `qbittorrent` | 8000,8080,9091 | **NO** |  |
| `radarr` | 7878 | **NO** |  |
| `sabnzbd` | 8080 | **NO** |  |
| `seerr` | 5055 | **NO** |  |
| `sonarr` | 8989 | **NO** |  |
| `tautulli` | 8181 | **NO** |  |

#### `media-experimental`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `audiobookshelf` | 80 | **NO** |  |
| `bindery` | 8787 | **NO** |  |
| `bookorbit` | 3000 | **NO** |  |
| `bookorbit-postgres ×3` | 5432,8000,9187 | **NO** | CNPG cluster |
| `booksonic` | 4040 | **NO** |  |
| `chaptarr` | 8789 | **NO** |  |
| `kavita` | 5000 | **NO** |  |
| `komga` | 25600 | **NO** |  |
| `libation` | 6080 | **NO** |  |
| `librarr` | 5050 | **NO** |  |
| `livrarr` | 8789 | **NO** |  |
| `mylar3` | 8090 | **NO** |  |
| `storyteller` | 8001 | **NO** |  |

#### `media-private`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `hot-ones-postgres ×3` | 5432,8000,9187 | YES (ingress+egress) | CNPG cluster |
| `scene-engine` | 8080 | YES (ingress+egress) |  |
| `scene-engine-face-worker` | 8090 | YES (ingress+egress) |  |
| `scene-engine-postgres ×2` | 5432,8000,9187 | YES (ingress+egress) | CNPG cluster |
| `stash` | 3000,9999 | YES (ingress) |  |
| `stash-ai` | 4153,5544 | YES (ingress) |  |
| `stash-box-postgres ×2` | 5432,8000,9187 | **NO** | CNPG cluster |
| `stash-tagger` | 8000 | YES (ingress+egress) |  |
| `whisparr-eros` | 6969 | YES (ingress) |  |
| `whisparr-postgres ×2` | 5432,8000,9187 | **NO** | CNPG cluster |
| `whoami` | 80 | **NO** |  |
| `zipline` | 3000 | **NO** |  |
| `zipline-postgres ×3` | 5432,8000,9187 | **NO** | CNPG cluster |

#### `minio`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `minio-pool` | 9000,9090 | **NO** |  |

#### `monitoring`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `alertmanager-discord` | 9094 | **NO** |  |
| `alloy` | 4317,4318,12345 | **NO** |  |
| `alloy-node` | 12345 | **NO** |  |
| `chi-hyperdx-logs-logs-0` | 8123,9000,9009 | **NO** |  |
| `clickstack-app` | 3000,4320,8000 | **NO** |  |
| `clickstack-mongodb` | 9216 | **NO** | MongoDB (observability) |
| `clickstack-otel-collector` | 4317,4318,8888,13133,24225 | **NO** |  |
| `grafana-deployment` | 3000,9094 | **NO** |  |
| `grafana-operator` | 8888,9090 | **NO** |  |
| `kube-state-metrics` | 8080,8081 | **NO** | cluster-wide object metadata |
| `loki` | 3100,7946,9095 | **NO** | log store |
| `loki-chunks-cache` | 9150,11211 | **NO** | Dragonfly (Redis) |
| `loki-results-cache` | 9150,11211 | **NO** | Dragonfly (Redis) |
| `mimir-alertmanager` | 7946,8080,9095 | **NO** |  |
| `mimir-compactor` | 7946,8080,9095 | **NO** |  |
| `mimir-distributor` | 7946,8080,9095 | **NO** | metric write path |
| `mimir-gateway` | 8080 | **NO** |  |
| `mimir-ingester` | 7946,8080,9095 | **NO** |  |
| `mimir-overrides-exporter` | 8080,9095 | **NO** |  |
| `mimir-querier` | 7946,8080,9095 | **NO** |  |
| `mimir-query-frontend` | 8080,9095 | **NO** |  |
| `mimir-query-scheduler` | 8080,9095 | **NO** |  |
| `mimir-rollout-operator` | 8001,8443 | **NO** |  |
| `mimir-ruler` | 7946,8080,9095 | **NO** |  |
| `mimir-store-gateway` | 7946,8080,9095 | **NO** |  |
| `nfs-storage-exporter` | 9092 | **NO** |  |
| `opentelemetry-operator` | 8443,9443 | **NO** |  |
| `prometheus-blackbox-exporter` | 9115 | **NO** |  |
| `prometheus-pushgateway` | 9091 | **NO** |  |
| `redis-exporter-argocd-dragonfly` | 9121 | **NO** |  |
| `redis-exporter-authentik-cache` | 9121 | **NO** | Dragonfly (Redis) |
| `tdarr-exporter` | 9092 | **NO** |  |
| `tempo` | 3200,4317,4318,6831,6832,9411,14250,14268,55678,55680,55681 | **NO** | trace store |
| `tempo-operator-controller` | 8443,9443 | YES (ingress+egress) |  |
| `version-checker` | 8080 | **NO** |  |

#### `node-feature-discovery`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `node-feature-discovery-gc` | 8080 | **NO** |  |
| `node-feature-discovery-master` | 8080 | **NO** |  |
| `node-feature-discovery-worker` | 8080 | **NO** |  |

#### `openscad`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `manyfold` | 3214 | YES (ingress+egress) |  |
| `manyfold-cache` | 6379,9999 | YES (ingress) | Dragonfly (Redis) |
| `manyfold-performance-worker` | — | YES (ingress+egress) |  |
| `manyfold-postgres` | 5432,8000,9187 | **NO** | CNPG cluster |

#### `opensearch-operator-system`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `opensearch-operator` | 8443,9443 | **NO** |  |

#### `pihole`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `nebula-sync` | 9092 | **NO** |  |
| `pihole` | 53,80,9617 | **NO** | cluster/LAN DNS — hijack surface |

#### `rabbitmq-system`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `messaging-topology-operator` | 9443 | **NO** |  |
| `rabbitmq-cluster-operator` | 8080,9443 | **NO** |  |

#### `registry`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `zot` | 5000 | **NO** | OCI registry — image supply chain |

#### `scratch`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `frigate` | 5000,8554,8555 | **NO** |  |
| `scratch-mongodb` | — | **NO** | MongoDB |
| `scrypted` | 8554,8555,10443,11080 | **NO** |  |

#### `tdarr`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `tdarr-server` | 8265,8266 | **NO** |  |
| `tdarr-worker` | — | **NO** |  |

#### `teak-talos-dev`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `dbgate` | 3000 | YES (ingress+egress) | DB web client (multi-DB creds) |

#### `traefik`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `traefik` | 80,443,1080,7687,8080,9000,9100 | **NO** | ingress; :8080 API/dashboard |

#### `vpn-gateway`

| workload | ports | ingress-restricted? | notes |
|---|---|---|---|
| `gluetun` | 1080,8000,8888,9091,9999 | **NO** | VPN egress proxy (:8888 HTTP, :1080 SOCKS) |
| `secure-chrome` | 6901 | **NO** |  |
| `securexng` | 8080,9091 | **NO** |  |
| `vpn-maintenance` | — | **NO** |  |
| `vpn-rotator-exporter` | 9091 | **NO** |  |

> The 9 namespaces absent from the table have no pod-network workloads at the time of audit
> (empty, host-network only, or scaled to zero): `cilium-secrets`, `descheduler`,
> `gpu-inference`, `immich`, `kube-node-lease`, `kube-public`, `mac-sdlc-node`, `mail`,
> `observability`. The other 54 namespaces are all enumerated above.
> `crossplane-demo/demo-rabbit`, `demo` (Dragonfly) and `chi-demo` are **scaled to 0** —
> there is **no live RabbitMQ in the cluster**, so the queue tier is moot today.

---

## 4. The existing convention is currently breaking production

This is the most important operational finding and it changes the rollout plan.

`hubble observe --verdict DROPPED` across all 5 agents returns **exactly one class of
policy drop in the entire cluster**:

```
monitoring/alloy → media-private/scene-engine-postgres-2:9187  POLICY_DENIED   (20)
monitoring/alloy → media-private/hot-ones-postgres-3:9187      POLICY_DENIED   (6)
monitoring/alloy → media-private/hot-ones-postgres-2:9187      POLICY_DENIED   (6)
monitoring/alloy → media-private/scene-engine-postgres-1:9187  POLICY_DENIED   (6)
monitoring/alloy → media-private/hot-ones-postgres-1:9187      POLICY_DENIED   (4)
```

Port `9187` is the CNPG `postgres-exporter` metrics port. The canonical convention allows
the `databases` namespace (dbgate) and the app on `:5432`, and the replication peers on
`:5432`/`:8000` — **it never mentions `monitoring` or `:9187`**.

The impact is confirmed in Mimir, not inferred:

```promql
count by (pod) (cnpg_collector_up{namespace="media-private"})
→ stash-box-postgres-1, stash-box-postgres-2,
  whisparr-postgres-1, whisparr-postgres-2,
  zipline-postgres-1,  zipline-postgres-2, zipline-postgres-3
```

Seven series. `media-private` has **twelve** CNPG instances. The five that are missing are
precisely `hot-ones-postgres-{1,2,3}` and `scene-engine-postgres-{1,2}` — the two clusters
that follow the convention. A 30-day range query for `hot-ones` returns `0` throughout.

**The correlation is perfect and inverted: in this namespace, the only databases with
working metrics are the three that are wide open.** Applying the convention as written to
the remaining 17 CNPG clusters would silently delete Postgres observability cluster-wide —
including the backup-health signals used to know whether barman is still working.

**The convention needs a fourth ingress rule before it is used again:**

```yaml
- from: [{ namespaceSelector: { matchLabels: { kubernetes.io/metadata.name: monitoring } } }]
  ports: [{ port: 9187, protocol: TCP }, { port: 8000, protocol: TCP }]
```

This is a documentation/manifest fix in `talos-private`, and it is the true prerequisite
for every option below. It also validates the convention doc's own non-negotiable #2
("verify with Hubble before restricting a currently-open DB") — the rule was right, it was
just applied to app traffic and not to scrape traffic.

A secondary consequence: because `media-private` policies are **ArgoCD**-owned and
`monitoring` is **Flux**-owned, this failure mode is invisible to both controllers. ArgoCD
reports `arr-stack-private` as `Synced`; the policy is doing exactly what it says. Nothing
alerts on "a scrape target that used to exist stopped existing".

---

## 5. High-value wide-open targets, ranked by blast radius

Ranked by what a single compromised pod — any pod, in any namespace, including a media
container running unverified images — gains by reaching it.

### Tier 0 — cluster-wide compromise

| # | target | port | why |
|---|---|---|---|
| 1 | `external-secrets/onepassword-connect` | 8080 | **The credential broker.** `ClusterSecretStore/onepassword` points every one of **154 ExternalSecrets** at `http://onepassword-connect.external-secrets.svc.cluster.local:8080`, vault `catalyst-eso`. Token-gated, but the token is a K8s secret and the API is reachable from all 321 endpoints. Compromise ≈ every credential in the cluster. |
| 2 | `minio/minio-pool-0` | 9000, 9090 | **All backups.** Velero's `BackupStorageLocation` (`bucket: velero`) *and* the barman-cloud destination for **all 20 CNPG clusters**. Read = exfiltrate every database offline; write/delete = destroy the recovery path. Also the `:9090` console. |
| 3 | `authentik/authentik-postgres` ×3 | 5432 | **SSO identity store** — users, sessions, tokens, and the client secrets of every downstream OIDC/proxy app. Directly undermines the whole authplane. |
| 4 | `authentik/authentik-server` + `authentik-worker` | 9000/9300/9443 | The issuer itself, plus the embedded outpost. |
| 5 | `flux-system/kustomize-controller`, `source-controller` | 9440, 80 | `kustomize-controller` reconciles with cluster-admin; `source-controller` serves repo artifact tarballs unauthenticated in-cluster. |
| 6 | `kubernetes-dashboard`, `infra-control/headlamp`, `kubeview`, `goldilocks-dashboard` | 8443, 4466, 8000, 8080 | Cluster admin UIs. Headlamp and the dashboard are the two that matter. |

### Tier 1 — data-tier, wide open on `:5432` / equivalent

**17 of 20 CNPG clusters have no ingress policy.** The three already tracked
(`stash-box`, `whisparr`, `zipline`) are the tail of the list, not the head:

| namespace | cluster | inst | sensitivity |
|---|---|---|---|
| `authentik` | `authentik-postgres` | 3 | **identity/SSO** (Tier 0 above) |
| `crowdsec` | `crowdsec-postgres` | 3 | security decisions / ban lists |
| `forgejo` | `forgejo-postgres` | 3 | **git server DB** — source of truth |
| `boomtime` | `boomtime-postgres`, `books-postgres` | 3+1 | personal analytics |
| `home-automation` | `homeassistant-postgres`, `linkwarden-postgres` | 3+3 | home telemetry, saved links/creds |
| `media` | `arr-postgres` | 3 | arr-stack |
| `media-experimental` | `bookorbit-postgres` | 3 | |
| `media-private` | `stash-box-postgres`, `whisparr-postgres`, `zipline-postgres` | 2+2+3 | **already tracked** |
| `bt-radar` | `bt-radar-postgres` | 2 | |
| `catalyst-data` | `dagster-postgres`, `postgres-knowledge` | 1+1 | |
| `crossplane-demo` | `plausible-db` | 3 | |
| `gaming` | `guacamole-postgres` | 1 | **remote-desktop connection creds** |
| `openscad` | `manyfold-postgres` | 1 | |

Non-CNPG data stores, also wide open:

| target | port | note |
|---|---|---|
| `dungeon-library/postgres` | 5432 | plain StatefulSet, outside CNPG conventions entirely |
| `catalyst-llm/litellm-postgresql` | 5432 | LLM gateway DB — provider keys, usage |
| `catalyst-llm/litellm` | 4000 | the gateway API itself |
| `monitoring/clickstack-mongodb` | 9216 | |
| `scratch/scratch-mongodb` | — | |
| `monitoring/chi-hyperdx-logs-logs-0-0` | 8123, 9000 | ClickHouse, no auth boundary |
| `crossplane-demo/chi-plausible-plausible-0-0` | 8123, 9000 | ClickHouse |
| `databases/dbgate` | 3000 | **web DB client holding credentials for many DBs at once** |

**Good news — the cache tier is already fully covered.** Every live Dragonfly
(`argocd-dragonfly`, `authentik-cache`, `boomtime-cache`, `manyfold-cache`) enforces
ingress. `crossplane-demo/demo` is scaled to 0. There is **no live RabbitMQ**
(`demo-rabbit` is 0/0); `rabbitmq-system` contains only operators. Those two rows on the
original worry-list are already closed.

### Tier 2 — pivot and supply-chain

| target | port | why |
|---|---|---|
| `registry/zot` | 5000 | OCI registry — image supply chain |
| `forgejo/forgejo` | 3000 | git server; push access ⇒ GitOps code execution |
| `traefik/traefik` | 8080 | API/dashboard on the LoadBalancer; `traefik-internal:9000` |
| `pihole/pihole` | 53, 80 | cluster-adjacent DNS — hijack/oracle |
| `vpn-gateway/gluetun` | 8888, 1080 | open HTTP + SOCKS proxy ⇒ egress laundering, bypasses egress policy |
| `crowdsec/crowdsec-lapi` | 8080 | poison or read security decisions |
| `monitoring/mimir-distributor`, `loki`, `tempo` | 8080, 3100, 3200 | unauthenticated write ⇒ forge or flood telemetry, destroy forensics |
| `monitoring/alertmanager` (via mimir) | 8080 | silence alerts during an intrusion |
| `argo/argo-workflows-server` | 2746 | arbitrary workflow submission |
| `kubevirt/virt-*`, `cdi-*` | 8443 | VM control plane |
| `gaming/guacd` | 4822 | remote-desktop proxy, no auth of its own |
| `scratch/frigate`, `scrypted` | 5000, 10443 | camera feeds |

---

## 6. Lockdown options

### (a) Per-namespace default-deny + allowlists, audit-first, rolled out namespace-by-namespace

The `honeypot` / `iocaine` / `teak-talos-dev` pattern, described in §2.1.

**Pros.** Complete for the namespace — closes workloads nobody enumerated, and stays closed
as new workloads land, which is the only property that survives drift. Already proven in this
cluster three times. Self-documenting. Naturally scoped to one Flux Kustomization at a time,
so blast radius per change is one namespace.

**Cons / risk.** **High per-namespace outage risk**, concentrated in the things that are
invisible until they break: kubelet probes from the pod CIDR, `kube-apiserver` egress for
CNPG's instance manager and any operator sidecar, cross-namespace scrapes from `monitoring`,
webhook callbacks from the API server to `cert-manager`/`kyverno`/`kubevirt` admission
endpoints, and Flux/ArgoCD reaching workloads. The `:9187` incident in §4 is exactly this
class of failure and it happened with a *targeted* policy — a full default-deny has strictly
more ways to go wrong. Cost is also real: 63 namespaces × an allowlist each.

**Flow data needed.** Per-namespace, a full inbound *and* outbound flow inventory over a
window long enough to catch periodic traffic — CronJobs, backup jobs, weekly wedge-buster
restarts. **At least 7 days**, for the same reason right-sizing uses 7d and not 24h.

**Audit-mode reality check.** Cilium *does* support audit mode, but only per endpoint and
only imperatively:

```
cilium endpoint config <id> PolicyAuditMode=Enabled     # currently Disabled on every endpoint
```

It is **not** expressible in a CRD, it is **not** GitOps-able, and it **resets when the pod
restarts** — so a policy landed in audit mode silently becomes enforcing on the next
reschedule. The agent-level `--policy-audit-mode` flag is not set (`cilium-config` has no
audit key). **There is no safe declarative audit-first path in this cluster today.** The
honest substitute is: capture flows first, write the allowlist from the capture, then land
the deny.

### (b) Targeted per-workload policies on the high-value wide-open targets

Pattern B from §2.1 — a `NetworkPolicy` per crown jewel, no namespace default-deny.

**Pros.** Risk is bounded to the one workload being changed and is trivially revertible.
Covers most of the actual blast radius for a small fraction of the work — the Tier 0 list is
~6 targets and Tier 1 is a repeated template. Requires flow data only for the workloads being
touched, which is a tractable capture. Matches the existing majority pattern, so it needs no
new convention. Testable one at a time against a known signal (does dbgate still connect,
does `cnpg_collector_up` still report).

**Cons.** Not complete and never becomes complete — it only protects what someone
enumerated, and a new wide-open workload is the default. It is a floor, not a ceiling.

**Flow data needed.** Per target: who currently connects. For a database that is
`app + databases/dbgate + replication peers + monitoring:9187`, and the fourth term is the
one that was missed. A short capture suffices because the consumer set of a single service
is small and mostly steady — but backup/CronJob consumers still argue for ≥24h, ideally 7d.

### (c) Cluster-wide default-deny (`CiliumClusterwideNetworkPolicy`)

**Pros.** The only option that is actually complete and default-secure.

**Cons.** **Unacceptable risk here, and I would not do it.** There are zero CCNPs today, so
there is no incremental experience with the object at this scope. It applies to
`kube-system` — CoreDNS, hubble-relay, metrics-server — and a mistake takes out DNS
cluster-wide, which takes out the ability to reach the cluster to fix it. It cannot be rolled
out gradually, the audit path in §(a) does not exist declaratively, and Cilium evaluates
CCNP alongside namespace policy in ways that are easy to get wrong on the first attempt.
There is also a specific local hazard: `enable-endpoint-lockdown-on-policy-overflow` is
`false` and `bpf-policy-map-max` is 65536 — a broad CCNP that fans out into many per-identity
entries risks policy-map pressure across ~321 endpoints × identities. Combined with the fact
that a single missed `:9187` rule already blinded five databases for days, the failure mode
at cluster scope is a cluster-wide outage with no in-cluster remediation path.

**Verdict: reject (c)** for this cluster, at least until (a) has been executed on several
namespaces without incident.

### Hubble feasibility — tested, works, with one blocker

Confirmed working from inside a cilium agent:

```
kubectl exec -n kube-system <cilium-pod> -c cilium-agent -- hubble observe --last 10
kubectl exec -n kube-system <cilium-pod> -c cilium-agent -- hubble status
  → Healthcheck: Ok   Current/Max Flows: 16,383/16,383 (100%)   Flows/s: 576.05
```

- `enable-hubble = true`, `bpf-events-policy-verdict-enabled = true`,
  `hubble-network-policy-correlation-enabled = true` — so `--type policy-verdict` and
  `--verdict DROPPED/AUDIT` all work, which is what makes any audit workflow possible.
- `hubble-relay` is up (one of two replicas; the other is in `Error` and should be cleaned
  up), so cluster-wide capture via the relay is available in addition to per-node.
- The `hubble` CLI is **not** installed on the workstation — use `kubectl exec`, or install it.

**The blocker:** the buffer is `hubble-event-buffer-capacity = 16383` and it is running at
**100% full at 576 flows/s ≈ a 28-second window**, per node. And
`hubble-export-file-path` is **not set**, so nothing is persisted — only
`hubble-export-file-max-size-mb` and `-max-backups` are configured, which do nothing
without a path.

**Therefore: a 7-day flow inventory is not possible today.** Enabling it needs one Flux
change to the Cilium Helm values — set `hubble.export.static.filePath` (plus
`allowList`/`fieldMask` to keep volume sane) and ship the file to Loki via the existing
Alloy DaemonSet. That is a prerequisite task, not part of the lockdown itself. Note the
Alloy WAL bound caveat already recorded for this cluster when adding a new high-volume
stream.

Until export exists, the workable substitutes are: (i) `hubble observe -f` piped to a file
for a bounded window against a *specific* target — sufficient for option (b); and (ii) the
Hubble Prometheus metrics already enabled (`hubble-metrics` includes `drop` and `policy`
with source/destination namespace context) which are in Mimir and *are* long-retention.
Metric-level drop counts are how you would detect a regression after landing a policy, and
they are the reason the `:9187` breakage is provable retroactively.

---

## 7. Recommendation — phased plan

Strategy **(b) first, (a) second, (c) never** (or not until (a) is boring).

The ordering below is deliberate: every phase is gated on a signal that would have caught
the `:9187` regression.

### Phase 0 — prerequisites (no policy changes)

1. **Fix the convention.** Add the `monitoring → :9187, :8000` ingress rule to
   `talos-private/base/_conventions/README-cnpg-db-networkpolicy.md`, then to the two live
   policies (`hot-ones`, `scene-engine`). Verify `cnpg_collector_up` returns 12 series in
   `media-private`, not 7. **This is the highest-value single change in this document** and
   it restores monitoring rather than restricting anything.
2. **Turn on Hubble flow export** (Cilium Helm values, Flux) → file → Alloy → Loki. Without
   it, phase 2+ is guesswork.
3. **Add a drop-rate alert** on the existing Hubble metrics, grouped by
   destination namespace/workload. This is the safety net that makes everything after it
   reversible-on-signal instead of reversible-on-complaint.
4. Clean up the failed `hubble-relay` replica and the `private-sso-reconciler` CronJob
   pods currently in `Error`.

### Phase 1 — Tier 0, per-workload (option b)

One policy per target, landed one at a time, each verified before the next:

1. `external-secrets/onepassword-connect` — allow only `external-secrets` controller pods.
   Verify: all 154 ExternalSecrets stay `SecretSynced`. **Highest blast-radius reduction
   per line of YAML in the cluster.**
2. `minio/minio-pool-0` — allow `backup` (Velero), CNPG pods cluster-wide (barman, needs a
   `cnpg.io/cluster` existence selector across namespaces), `monitoring`, and the console.
   Verify: take a Velero backup and force a CNPG base backup before *and* after.
   ⚠️ Coordinate with the ESO generator-rotation behaviour already documented for this
   cluster — MinIO scoped users regenerate on spec change; do not conflate a policy drop
   with a `SignatureDoesNotMatch`.
3. `authentik-postgres` + `authentik-server`/`worker` — the authplane. Do this after MinIO
   so a mistake does not also lock you out of fixing it.
4. `flux-system` source/kustomize-controller, `kubernetes-dashboard`, `headlamp`.

### Phase 2 — Tier 1 CNPG sweep (option b, templated)

Apply the **corrected** convention to the remaining 17 clusters, in ascending order of
consequence so mistakes are cheap: `catalyst-data` → `bt-radar` → `openscad` →
`media-experimental` → `crossplane-demo` → `boomtime` → `media` → `home-automation` →
`gaming` → `media-private` (the 3 tracked) → `crowdsec` → `forgejo`.

Per cluster the acceptance test is fixed and mechanical: app connects, dbgate connects,
replication healthy (`instances` all ready), `cnpg_collector_up` present for every instance,
barman backup succeeds. Also fold in the non-CNPG stores — `dungeon-library/postgres`,
`litellm-postgresql`, both MongoDBs, both ClickHouses — which no convention currently covers.

### Phase 3 — namespace default-deny (option a), narrow

Only after phases 1–2 are stable and Hubble export has ≥7 days of data. Start with
namespaces that are already mostly covered and have few dependencies:

`openscad` → `boomtime` → `gaming` → `media-private` → `catalyst-llm`

Copy `teak-talos-dev` verbatim as the skeleton — it already encodes intra-namespace,
kube-dns, `kube-apiserver`, and probe-CIDR allowances. **Explicitly out of scope
indefinitely:** `kube-system`, `flux-system`, `cert-manager`, `kyverno`, `external-secrets`,
`monitoring`. These carry webhook and reconciliation paths whose failure removes the
ability to repair the cluster.

### Phase 4 — reassess (c)

Revisit cluster-wide default-deny only if phase 3 completes across several namespaces
without incident. Nothing in this assessment supports doing it sooner.

### Cross-cutting notes

- **Two controllers, two repos.** Infra targets (`minio`, `external-secrets`, `authentik`,
  `flux-system`, `monitoring`) are Flux/`talos-homelab`. `media-private` is
  ArgoCD/`talos-private`. Keep each policy in the repo that owns its workload — a policy in
  the wrong repo will be reverted by the owning controller.
- **Kyverno cannot help here.** It does not mutate `kube-system`/`kyverno`/`kube-public`/
  `kube-node-lease`, so a "default-deny injector" policy would silently no-op in exactly the
  namespaces where a mistake is most dangerous.
- **`namespaceSelector` is safe to use everywhere** — all 63 namespaces carry
  `kubernetes.io/metadata.name` (verified).
- **Every policy must be verified live, not by reading the manifest.** Two of the eleven
  `media-private` policies select pods that do not exist and protect nothing. The check is
  `cilium endpoint list -o json | .status.policy.realized.policy-enabled`.

---

## Related Issues

- `TALOS-lxz5.3.1` — east-west default-deny lockdown epic (this assessment is its input)
