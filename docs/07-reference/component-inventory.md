---
type: reference
status: current
covers:
  - cluster
freshness: tracks-code
tickets:
  - TALOS-kll3
  - TALOS-f0sd
blurb: Every Flux Kustomization in clusters/catalyst-cluster, with the manifest that declares it, whether it has a colocated README, and how many nested kustomizations it wraps.
---

# Component Inventory

> Generated file — do not edit by hand. Regenerate with `task docs:generate`.
> The source of truth is the Flux Kustomizations in `clusters/catalyst-cluster/`,
> so a wrong row here is a wrong manifest there.

Every row is one Flux Kustomization — the unit Flux reconciles, and therefore the unit a
doc can honestly claim to cover. The directory tree is not that unit: some directories group
children that are each their own component, others are a single Kustomization wrapping many
nested ones, and nothing in the tree tells the two apart. So this table is built from the
Kustomizations, never from the filesystem.

65 components are declared across 64 manifest files. 14 have a colocated `README.md`,
which is the question this table really asks: a component with no README has no doc home,
and whatever documents it lives somewhere that nothing keeps pointed at it.

| slug                         | flux name                    | path                                                  | on disk | readme | nested | suspended |
| ---------------------------- | ---------------------------- | ----------------------------------------------------- | ------- | ------ | ------ | --------- |
| `analytics`                  | `analytics`                  | `infrastructure/base/analytics`                       | yes     | yes    | 1      | -         |
| `argocd`                     | `argocd`                     | `infrastructure/base/argocd`                          | yes     | yes    | 3      | -         |
| `arr-stack`                  | `arr-stack`                  | `applications/arr-stack/overlays/themepark`           | yes     | yes    | 1      | -         |
| `authentik`                  | `authentik`                  | `infrastructure/base/authentik`                       | yes     | -      | 2      | -         |
| `aws`                        | `aws`                        | `infrastructure/base/aws`                             | yes     | yes    | 3      | -         |
| `aws-apps`                   | `aws-apps`                   | `infrastructure/base/aws/apps`                        | yes     | -      | 1      | -         |
| `aws-buckets`                | `aws-buckets`                | `infrastructure/base/aws/buckets`                     | yes     | -      | 1      | -         |
| `aws-providers`              | `aws-providers`              | `infrastructure/base/aws-providers`                   | yes     | -      | 1      | -         |
| `backup`                     | `backup`                     | `infrastructure/base/backup`                          | yes     | -      | 1      | -         |
| `bootstrap-crds`             | `bootstrap-crds`             | `infrastructure/base/bootstrap-crds`                  | yes     | -      | 1      | -         |
| `bt-radar`                   | `bt-radar`                   | `applications/bt-radar/base`                          | yes     | -      | 1      | -         |
| `catalyst-cnpg-appdb`        | `catalyst-cnpg-appdb`        | `infrastructure/base/catalyst-cnpg-appdb`             | yes     | -      | 2      | -         |
| `catalyst-llm`               | `catalyst-llm`               | `applications/catalyst-llm`                           | MISSING | -      | 0      | yes       |
| `catalyst-websecure-ingress` | `catalyst-websecure-ingress` | `infrastructure/base/catalyst-websecure-ingress`      | yes     | -      | 2      | -         |
| `cert-manager`               | `cert-manager`               | `infrastructure/base/cert-manager`                    | yes     | -      | 1      | -         |
| `cert-manager-issuers`       | `cert-manager-issuers`       | `infrastructure/base/cert-manager-issuers`            | yes     | -      | 1      | -         |
| `cilium`                     | `cilium`                     | `infrastructure/base/cilium`                          | yes     | -      | 4      | -         |
| `cloudflare-ddns`            | `cloudflare-ddns`            | `infrastructure/base/cloudflare-ddns`                 | yes     | -      | 4      | -         |
| `control-plane-scrape`       | `control-plane-scrape`       | `infrastructure/base/monitoring/control-plane-scrape` | yes     | -      | 1      | -         |
| `crossplane-demo`            | `crossplane-demo`            | `applications/crossplane-demo`                        | yes     | yes    | 5      | -         |
| `crossplane-demo-object`     | `crossplane-demo-object`     | `applications/crossplane-demo/object`                 | yes     | -      | 1      | -         |
| `crowdsec`                   | `crowdsec`                   | `infrastructure/base/security/crowdsec`               | yes     | -      | 2      | -         |
| `databases`                  | `databases`                  | `infrastructure/base/databases`                       | yes     | yes    | 7      | -         |
| `descheduler`                | `descheduler`                | `infrastructure/base/descheduler`                     | yes     | -      | 1      | -         |
| `external-dns`               | `external-dns`               | `infrastructure/base/external-dns`                    | yes     | yes    | 4      | -         |
| `external-secrets`           | `external-secrets`           | `infrastructure/base/external-secrets`                | yes     | yes    | 6      | -         |
| `external-secrets-operator`  | `external-secrets-operator`  | `infrastructure/base/external-secrets/operator`       | yes     | -      | 1      | -         |
| `falco`                      | `falco`                      | `infrastructure/base/security/falco`                  | yes     | -      | 1      | -         |
| `flux-notifications`         | `flux-notifications`         | `infrastructure/base/flux-notifications`              | yes     | yes    | 1      | -         |
| `forgejo`                    | `forgejo`                    | `infrastructure/base/forgejo`                         | yes     | -      | 1      | -         |
| `gaming`                     | `gaming`                     | `applications/gaming/base`                            | yes     | -      | 3      | -         |
| `gpu-inference`              | `gpu-inference`              | `infrastructure/base/gpu-inference`                   | yes     | yes    | 1      | -         |
| `home-automation`            | `home-automation`            | `applications/home-automation/base`                   | yes     | -      | 4      | -         |
| `homepage`                   | `homepage`                   | `applications/homepage`                               | yes     | -      | 11     | -         |
| `honeypots`                  | `honeypots`                  | `infrastructure/base/security/honeypots`              | yes     | -      | 1      | -         |
| `infra-control`              | `infra-control`              | `infrastructure/base/infra-control`                   | yes     | yes    | 6      | -         |
| `intel-gpu`                  | `intel-gpu`                  | `infrastructure/base/intel-gpu`                       | yes     | yes    | 1      | -         |
| `iocaine`                    | `iocaine`                    | `infrastructure/base/security/iocaine`                | yes     | -      | 1      | -         |
| `kube-system`                | `kube-system-utils`          | `infrastructure/base/kube-system`                     | yes     | -      | 4      | -         |
| `kubevirt`                   | `kubevirt`                   | `infrastructure/base/kubevirt`                        | yes     | -      | 3      | -         |
| `kyverno`                    | `kyverno`                    | `infrastructure/base/kyverno`                         | yes     | -      | 1      | -         |
| `kyverno-policies`           | `kyverno-policies`           | `infrastructure/base/kyverno-policies`                | yes     | -      | 1      | -         |
| `mail`                       | `mail`                       | `infrastructure/base/mail`                            | yes     | -      | 1      | -         |
| `media-experimental`         | `media-experimental`         | `applications/media-experimental/base`                | yes     | -      | 15     | -         |
| `metrics-server`             | `metrics-server`             | `infrastructure/base/metrics-server`                  | yes     | -      | 1      | -         |
| `metube`                     | `metube`                     | `applications/metube`                                 | yes     | -      | 1      | -         |
| `minio`                      | `minio`                      | `infrastructure/base/minio`                           | yes     | -      | 3      | -         |
| `monitoring`                 | `monitoring`                 | `infrastructure/base/monitoring/v2-otel`              | yes     | -      | 16     | -         |
| `monitoring-v2-operators`    | `monitoring-v2-operators`    | `infrastructure/base/monitoring/v2-otel/operators`    | yes     | -      | 3      | -         |
| `namespaces`                 | `namespaces`                 | `infrastructure/base/namespaces`                      | yes     | -      | 1      | -         |
| `operators`                  | `operators`                  | `infrastructure/base/operators`                       | yes     | -      | 8      | -         |
| `pihole`                     | `pihole`                     | `infrastructure/base/pihole`                          | yes     | -      | 1      | -         |
| `reflector`                  | `reflector`                  | `infrastructure/base/reflector`                       | yes     | -      | 1      | -         |
| `scratch`                    | `scratch`                    | `applications/scratch`                                | yes     | -      | 7      | -         |
| `storage`                    | `storage`                    | `infrastructure/base/storage`                         | yes     | -      | 2      | -         |
| `tdarr`                      | `tdarr`                      | `applications/tdarr/base`                             | yes     | -      | 1      | -         |
| `teak-talos-dev`             | `teak-talos-dev`             | `infrastructure/base/teak-talos-dev`                  | yes     | yes    | 3      | -         |
| `traefik`                    | `traefik`                    | `infrastructure/base/traefik`                         | yes     | -      | 2      | -         |
| `tubesync`                   | `tubesync`                   | `applications/tubesync`                               | yes     | -      | 1      | -         |
| `unifi-port-forward`         | `unifi-port-forward`         | `infrastructure/base/unifi-port-forward`              | yes     | -      | 1      | -         |
| `version-checker`            | `version-checker`            | `infrastructure/base/monitoring/version-checker`      | yes     | -      | 1      | -         |
| `vpn-gateway`                | `vpn-gateway`                | `infrastructure/base/vpn-gateway`                     | yes     | yes    | 2      | -         |
| `whoami`                     | `whoami`                     | `infrastructure/base/whoami`                          | yes     | -      | 1      | -         |
| `zipline`                    | `zipline`                    | `applications/zipline`                                | yes     | -      | 1      | -         |
| `zot`                        | `zot`                        | `infrastructure/base/registry/zot`                    | yes     | -      | 1      | -         |

`slug` is the manifest filename; `flux name` is its `metadata.name`. They differ on 1
rows. The filename is the handle this tool uses, because a name that moves when someone
edits a field is not a handle — but `dependsOn` in every other Kustomization refers to the
flux name, so both belong here.

## Reading the nested column

`nested` counts the `kustomization.yaml` files underneath the component's path.

A grouping directory whose children are each their own Flux Kustomization is the CORRECT
pattern and is not what this counts: those children are not inside one component, they are
several components, each with its own row, its own slug and its own doc home.

A high count is the other shape — ONE slug whose single Kustomization applies many nested
kustomizations. All of those nested units deploy, but only the wrapper has a name, so
"component = directory = doc home" is untrue for it: there is no single thing the directory
documents and no one README that could cover it. Run `task docs:rule -- component-shape` for
the outliers.

## Paths that do not exist

These components point at a path that is not in the repo. Flux reports this as a failed
reconcile while the last successfully applied revision keeps running, so the cluster looks
healthy and nothing surfaces it.

- `catalyst-llm` (declared in `clusters/catalyst-cluster/catalyst-llm.yaml`) points at `applications/catalyst-llm`

## Related Issues

- TALOS-f0sd — docs as a projection: frontmatter, linting, generation
- TALOS-kll3 — the generator and its whole-file artifacts
