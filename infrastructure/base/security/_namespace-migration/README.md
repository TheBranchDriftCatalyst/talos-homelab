---
type: decision
status: current
covers:
  - crowdsec
  - falco
  - iocaine
freshness: tracks-code
tickets:
  - TALOS-ic20
bluf: The shared `security` namespace is scaffolded but deliberately unwired. Why the folder move was safe and the namespace move is not.
---

# `security` namespace migration — inert scaffold

`namespace.yaml` here is the **target** `security` Namespace. It is deliberately referenced
by no `kustomization.yaml`, so neither `kustomize build` nor Flux will ever create it. That
is the whole point of this directory: the intent is recorded in the repo, and executing it
requires a deliberate act rather than an accident.

## What is already done, and what is not

The **folder** consolidation is complete: `crowdsec`, `falco` and `iocaine` moved under
`infrastructure/base/security/` in `e6aeba5b`, and the honeypots followed. That was safe
because it was a pure set of file renames — every namespace, Service name and cross-reference
was unchanged, so nothing in the cluster moved at all.

The **namespace** move is a different operation entirely, and each of the couplings below is
a way for it to fail quietly rather than loudly.

- **The CrowdSec decisions database.** It is a CNPG cluster with its own volumes. Moving a
  namespace is a data migration with rolling, prune-disabled discipline — never a delete and
  recreate. This is the single largest reason the move is gated.
- **Machine and bouncer registrations.** Engines and bouncers register to the LAPI by name.
  Changing the namespace invalidates those registrations and the externally-managed bouncer
  keys along with them.
- **Traefik's cross-references.** The bouncer Middleware and the AppSec service DNS name are
  consumed from the Traefik namespace and have to be repointed in step.
- **Secret plumbing.** The externally-sourced secrets and their mirrors are namespace-scoped
  and must be re-scoped.
- **Everything selector-shaped.** Flux Kustomizations, default-deny network policies and the
  Pod/ServiceMonitor selectors are all namespace-scoped.

There is also an admission-control question with no default answer: Falco needs `privileged`
for its eBPF driver, so a single shared namespace would have to be privileged-enforced for
everything in it — or the plan keeps Pod Security Standards per workload. Today each
component enforces the weakest standard it actually needs, and collapsing them would give the
honeypot namespace Falco's privileges. That trade has to be decided, not inherited.

Falco and iocaine are the stateless pair, so they are the low-risk proof if this ever starts.

## To proceed

1. Write the migration plan on TALOS-ic20 and get it approved.
2. Wire `namespace.yaml` into the relevant kustomization.
3. Migrate one service at a time — Falco and iocaine first, CrowdSec last and with the
   database handled as a migration in its own right.

## Related Issues

- TALOS-ic20 — consolidate the security components into one `security` namespace
