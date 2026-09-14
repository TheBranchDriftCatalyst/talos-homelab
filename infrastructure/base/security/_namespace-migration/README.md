# `security` namespace migration — INERT scaffold (TALOS-ic20)

**Status:** scaffold only. **Nothing here is wired into Flux or any `kustomization.yaml`.** `namespace.yaml`
is the *target* `security` Namespace; it is deliberately un-referenced so `kustomize build` and Flux never
apply it until a migration plan exists and is approved.

## Why this is gated
The folder consolidation (`crowdsec`/`falco`/`iocaine` → `infrastructure/base/security/`) is **done**
(commit e6aeba5b) and was safe — pure file renames, namespaces unchanged. The **namespace** move is not:

- **CrowdSec CNPG Postgres (`crowdsec-postgres`)** — the decisions DB + LAPI machine registrations live in
  a CNPG Cluster + PVCs. A namespace move is a **data migration** (rolling / prune-disabled discipline),
  never a delete+recreate.
- **CrowdSec machine + bouncer re-registration** — agents/bouncers register to LAPI by name; moving the ns
  invalidates registrations and the ESO-managed bouncer API keys.
- **Traefik bouncer cross-refs** — the bouncer middleware + AppSec/WAF service DNS are referenced from
  Traefik and must be repointed.
- **ESO ExternalSecrets + reflector mirrors** — abuseipdb key, bouncer keys — re-scope to `security`.
- **Flux Kustomization + default-deny CNP + Pod/ServiceMonitor selectors** — all re-scoped.

**Falco + iocaine** are largely stateless and can move first as a low-risk proof.

## To proceed
Write the migration plan on **TALOS-ic20**, get it approved, then wire `namespace.yaml` into the relevant
kustomization and migrate one service at a time (falco/iocaine first, crowdsec last with CNPG care).
