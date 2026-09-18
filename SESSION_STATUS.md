# Session Status — talos-homelab

<!-- closeout:header -->
**Kind:** Talos Kubernetes homelab · infra + GitOps  ·  **Tracker:** beads (`bd`)  ·  **Updated:** 2026-09-18
**Pick up here:** `TALOS-a13n` (RESUME HERE epic) · **Deadline item:** `TALOS-sahd` (~2026-09-20 03:35 UTC)
<!-- /closeout:header -->

> Maintained by `/closeout-session`. Newest session first. The index keeps the **last 10**;
> older entries move to [`docs/session-archive.md`](docs/session-archive.md).
> See [How this file is maintained](#how-this-file-is-maintained) before editing by hand.

---

## 30-second orientation

Multi-node Talos cluster, dual GitOps (Flux for infra, ArgoCD for apps). Everything under
`infrastructure/` and `applications/` deploys by committing to git; there is no deploy script.

Recent sessions have been a security campaign on `infrastructure/base/security/**` (CrowdSec,
Falco, honeypots, iocaine). That campaign is **paused deliberately, not finished** — a
principal review recommended stopping rather than continuing into cosmetic work.

If you are here to do something else entirely, that is fine and probably correct. Read
[Standing gotchas](#standing-gotchas) before touching the security tree; otherwise skip ahead.

<!-- closeout:next -->
## Now / next

| | |
|---|---|
| **Deadline** | `TALOS-sahd` (P1) — a CrowdSec GC reap fires **unattended ~09-20 03:35 UTC** against a key-holding bouncer row. Whether enforcement survives it was *reasoned about, never tested*. ~15 min in a watched window. |
| **Same weekend** | `TALOS-a83x` (P3) — falcosidekick redis reaches its 512 MB ceiling ~09-20. Accept ~2 days of history, or raise it. The config advertises 7 days, which is unreachable. |
| **Highest leverage** | `TALOS-kb2f` (P1) — pytest half of the tripwire canary: assert `container.name` is a *name*, not a 12-hex ID, **per node**. |
| **Then** | `TALOS-cp18` (schema-validate HelmRelease values in CI) · `TALOS-9vb9` (three alerts that cannot fire) |
| **Explicitly not next** | Wave 3 (`TALOS-4ca6`) — cosmetic drift/dead code. The review said stop adding to this tree. |
<!-- /closeout:next -->

---

<!-- closeout:sessions -->
## Sessions

### 2026-09-18 — Security campaign + three adversarial validation passes
**Commits:** 43 · **Scope:** `infrastructure/base/security/**`, traefik, monitoring, CNPG fleet

**Filed:** `TALOS-a13n` (resume epic), `TALOS-sahd`, `TALOS-kb2f`, `TALOS-9vb9`, `TALOS-d811`,
`TALOS-cp18`, `TALOS-j6th`, `TALOS-66c7`, `TALOS-r0qe`, `TALOS-a83x`, `TALOS-lvec`,
`TALOS-fksn`, `TALOS-y7qg`, `TALOS-5r0k`
**Closed:** `TALOS-k5vm`, `TALOS-pnyo`, `TALOS-vy8s`, `TALOS-wn69`, `TALOS-ybtm`,
`TALOS-yy3x`, `TALOS-5yrf`, `TALOS-yrq5`, `TALOS-urty`
**Carried:** `TALOS-cscw` (Wave 2 remainder), `TALOS-4ca6` (Wave 3, deferred on purpose)

Three isolated auditors swept the security tree; remediation ran all day; then three review
passes, each of which found the *previous* round's fix hadn't worked.

**Landed:** Falco least-privilege (`privileged` → 4 caps, hostPaths 12→8); every CrowdSec LAPI
hop now verifies TLS (PKI moved onto the shared homelab CA trust-manager already distributes);
special-use IP filtering rewritten to CIDR *overlap* matching; decision exporter given its own
credential and made rotation-proof; CNPG 17.0 → 17.6 across all seven clusters; honeypot breach
tripwire made **continuously self-testing** (canary CronJob + `HoneypotTripwireNotFiring`).

**Found only by validation:** the novelty bouncer was pulling 9.9 MB of decisions every 30 s
against its own 8 MB cap and had **stopped enforcing entirely**; the honeypot breach rules were
blind for most of the day (gotcha #1).

**Cost:** the campaign drifted into repairing controls that exist to watch other controls. The
two worst self-inflicted outages were *optional tidying nothing asked for*, done mid-campaign
on the enforcement path.

### 2026-09-17/18 (overnight) — Flake + direnv migration, root cleanup
**Filed:** `TALOS-pmbi`, `TALOS-ewlf`, `TALOS-p4qu`, `TALOS-pmnc`, `TALOS-90pl`
**Closed:** `TALOS-hdw8`, `TALOS-9vtw`

Converted the repo to `use flake` + direnv; consolidated devx; moved Taskfiles under `dev/`;
1Password secret materialisation with biometric caching. Added the cowrie replay-bot
suppression scenario (`homelab/cowrie-replay-drop`), still in simulation.
<!-- /closeout:sessions -->

---

<!-- closeout:gotchas -->
## Standing gotchas

Durable lessons. These **survive archival** — when a session entry is archived, any lesson
worth keeping is distilled up into this list first. Fuller detail lives in
`infrastructure/base/security/README.md` and in file-level comments.

1. **Never verify a detection control by checking an intermediate field.** The honeypot
   tripwire was blind three times in 24 h; each fix checked the field it had just changed.
   `container.name` resolving to a 12-hex container ID is a *broken* state and is **not null**,
   so a null-check sails past it. Fire the rule; see the alert arrive.
2. **`kustomize build` passing is not validation for a HelmRelease.** It never reads the
   chart's `values.schema.json`. Use `helm template`. Two separate bugs shipped through that gap.
3. **A kustomization's `namespace:` silently rewrites the namespace in your manifest.** No
   error, green reconcile, resource in the wrong place.
4. **The honeypot namespace has a strict egress quarantine** that blocks the apiserver. That is
   correct — move your pod, don't widen the policy.
5. **The Traefik CrowdSec bouncer is fail-closed.** Breaking its TLS or LAPI reachability takes
   down *every* HTTP route, and Traefik pods stay Ready while it rejects traffic.
6. **`cscli decisions list --scope range` silently returns nothing**, and a negative duration
   means *expired*, not active. Parse `-a -o json`.
<!-- /closeout:gotchas -->

---

## How this file is maintained

Run `/closeout-session` at the end of a working session. It appends a new entry and rolls the
oldest out to the archive. Editing by hand is fine; keep the shape.

**Rules that make it stay useful:**

- **Newest session first.** Index keeps the **last 10**; older entries append to
  `docs/session-archive.md` (moved, never deleted).
- **Every entry carries a ticket ledger** — Filed / Closed / Carried. That ledger is the point:
  it answers "what came out of that session" without reading the prose.
- **Distil before you archive.** A session entry ages out, but a lesson it taught should be
  lifted into [Standing gotchas](#standing-gotchas) first. Episodes decay; invariants persist.
- **Record decisions and direction, never live health.** "We chose X because Y" ages well;
  "component Z is currently failing" is wrong within a day and misleads the next person
  debugging. Health belongs in alerts. *(This rule exists because a doc in this repo made
  exactly that mistake and had to be corrected.)*
- **Link to beads, don't duplicate it.** Ticket bodies are the source of truth; this is
  orientation and a pointer.
- **Keep the `<!-- closeout:* -->` anchors.** The command edits between them; the header block
  is deliberately identical across repos so siblings can be scanned side by side.
