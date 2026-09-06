# `infrastructure/archived/`

Manifests kept for reference but **not deployed**. Nothing here is referenced by any Flux
Kustomization in `clusters/catalyst-cluster/`, and nothing here should be.

This directory exists so that retiring a component does not mean losing its manifests to
git history. Restoring one is a `git mv` back under `infrastructure/base/` plus a Flux
Kustomization — not an archaeology exercise.

| Directory              | Retired    | Why                                                                                                      |
| ---------------------- | ---------- | -------------------------------------------------------------------------------------------------------- |
| `nebula/`              | 2026-09-06 | Nebula mesh VPN lighthouse. Never wired into Flux; no `nebula` namespace has ever existed in the cluster. |
| `hybrid-llm-nebula/`   | 2026-09-06 | The `nebula/` component of the unwired `hybrid-llm` effort — commented out in its kustomization, never implemented. |

> **Not to be confused with `infrastructure/base/pihole/nebula-sync/`**, which is live and
> unrelated — it is the Pi-hole config-sync worker (TALOS-0nt), named after the `nebula-sync`
> project, not the Nebula mesh.

Certificates for the mesh live in `configs/nebula-certs/` (gitignored) and a copy is parked
in `.scratch/__configs/nebula-certs/`. Those are **private keys** — they stay untracked.

---

## Related Issues

<!-- Beads tracking for this doc -->
