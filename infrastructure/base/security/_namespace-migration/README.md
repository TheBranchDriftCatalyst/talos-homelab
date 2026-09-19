---
type: decision
status: current
covers:
  - crowdsec
  - falco
  - honeypots
  - iocaine
freshness: tracks-code
tickets:
  - TALOS-ic20
bluf: The shared `security` namespace is abandoned. Grouping is a label, because merging these four would force the whole namespace to `privileged` and demote the honeypots.
---

# Security grouping is a label, not a namespace

This directory used to hold an inert `namespace.yaml` scaffolding a shared `security`
namespace for `crowdsec`, `falco` and `iocaine`. That target is **dropped**. The file is gone;
this record is what replaces it.

## Why not one namespace

Pod Security Admission is enforced **per namespace, not per pod**, so a namespace must be set
to the most permissive level any of its members needs. The four components do not agree:

| Namespace  | PSA enforce  | Why |
| ---------- | ------------ | --- |
| `crowdsec` | `privileged` | LAPI/agent needs host log access |
| `falco`    | `privileged` | eBPF driver |
| `honeypot` | `baseline`   | — |
| `iocaine`  | `baseline`   | — |

Merging them means the union namespace enforces `privileged`, which **demotes `honeypot` and
`iocaine` from `baseline`**. The honeypots are the one workload here deliberately built to be
compromised; widening what a container that escapes them may request, so that an unrelated
component's eBPF driver can share the namespace, trades real isolation for tidiness.

The original scaffold flagged the PSA question as undecided. This is the decision: the cost
lands on exactly the workload that can least afford it, so the consolidation is not worth it.

## What grouping means instead

Kubernetes namespaces are flat — there is no nesting, and no API-level parent/child. So the
grouping is expressed as a label each namespace carries:

```yaml
app.kubernetes.io/part-of: security
```

which gives the model:

- **a component directory maps to a namespace** (`security/falco` → `falco`)
- **a grouping directory maps to a label**, never to a namespace

Policy then selects the group rather than naming its members, so adding a fifth component means
labelling it, not editing every selector:

```yaml
namespaceSelector:
  matchLabels:
    app.kubernetes.io/part-of: security
```

The same label is available to RBAC aggregation, Kyverno `match` blocks and Flux `dependsOn`.

## Alternatives considered

| Option | Verdict |
| --- | --- |
| Name prefix (`security-falco`) | Greppable and sortable, but **not selectable** — Kubernetes has no prefix selectors, so policy still has to enumerate members. |
| HNC (`k8s-sigs/hierarchical-namespaces`) | Genuine parent/child with propagation of RBAC, NetworkPolicies, secrets and quotas. Rejected for now: it puts an operator and a webhook in the admission path to synthesise something the label already provides at this scale. Revisit if propagation — not grouping — becomes the need. |
| vcluster | Real isolation, far heavier than the problem. |

## What this does not change

The **folder** consolidation stands and was always safe: `crowdsec`, `falco` and `iocaine`
moved under `infrastructure/base/security/` in `e6aeba5b` and the honeypots followed, as pure
file renames with every namespace, Service name and cross-reference unchanged.

The couplings that made a namespace move expensive are still there, and are now simply never
exercised: the CrowdSec decisions database is a CNPG cluster with its own volumes (a namespace
move is a data migration, not a re-apply); engines and bouncers register to the LAPI by name;
Traefik consumes the bouncer Middleware and AppSec service DNS from its own namespace. Dropping
the consolidation retires all of that risk rather than deferring it.

## Related Issues

- TALOS-ic20 — namespace consolidation, closed by this decision
