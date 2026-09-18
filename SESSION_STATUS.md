# Session Status — talos-homelab

<!-- closeout:header -->
**Kind:** Talos Kubernetes homelab · infra + GitOps  ·  **Tracker:** beads (`bd`)  ·  **Updated:** 2026-09-18
**Pick up here:** `TALOS-kll3` (docs generator, in flight) · **Deadline item:** `TALOS-sahd` (~2026-09-20 03:35 UTC)
<!-- /closeout:header -->

> Maintained by `/closeout-session`. Newest session first. The index keeps the **last 10**;
> older entries move to [`docs/session-archive.md`](docs/session-archive.md).
> See [How this file is maintained](#how-this-file-is-maintained) before editing by hand.

---

## 30-second orientation

Multi-node Talos cluster, dual GitOps (Flux for infra, ArgoCD for apps). Everything under
`infrastructure/` and `applications/` deploys by committing to git; there is no deploy script.

**Two efforts are open, and they are unrelated to each other.**

1. **Docs as projection** (`TALOS-f0sd`) — *in flight, this is the live one*. Docs were the only
   projection of the code that nothing kept honest, so they drifted: 154 broken links and a
   tree that had grown to 105 files. The tree is pruned to 37 and `docsgen` (a portable Go
   linter at `dev/docs-generator/`) now reports drift. Next step is the generator half.
2. **Security campaign** (`TALOS-a13n`) — *paused deliberately, not finished*. A principal
   review recommended stopping rather than continuing into cosmetic work. Two items have real
   dates this weekend; see Now/next.

If you are here to do something else entirely, that is fine and probably correct. Read
[Standing gotchas](#standing-gotchas) first — most of them cost real outages to learn.

<!-- closeout:next -->
## Now / next

Two independent efforts are live. The docs one is mid-flight; the security one is paused with
two dated items.

### In flight — docs as projection (`TALOS-f0sd`)

| | |
|---|---|
| **Next action** | `TALOS-kll3` (E2) — the generator half. First artifact: `docs/07-reference/component-inventory.md`. Chosen as the first thing that *writes* because it needs no frontmatter, its input is 65 machine-authored Flux CRs, and nobody depended on it yesterday — so a wrong design is wrong in exactly one file. |
| **Done** | `TALOS-hadr` (E1 phase 0) — `docsgen` builds, runs, is on `PATH` in the dev shell. First run: **108 broken links, 15 component-shape warnings**. |
| **Sequenced after** | E3 frontmatter (`TALOS-0hlo`) → E4 enforcement (`TALOS-c0hj`) → E5 folder migration (`TALOS-osdj`) → E7 namespace migration (`TALOS-mpbu`). E6 mermaid (`TALOS-05xr`) rides along. |

### Paused — security campaign (`TALOS-a13n`)

| | |
|---|---|
| **Deadline** | `TALOS-sahd` (P1) — a CrowdSec GC reap fires **unattended ~09-20 03:35 UTC** against a key-holding bouncer row. Whether enforcement survives it was *reasoned about, never tested*. ~15 min in a watched window. |
| **Same weekend** | `TALOS-a83x` (P3) — falcosidekick redis reaches its 512 MB ceiling ~09-20. |
| **Highest leverage** | `TALOS-kb2f` (P1) — pytest half of the tripwire canary: assert `container.name` is a *name*, not a 12-hex ID, **per node**. |
| **Explicitly not next** | Adding more to the security tree. A principal review said stop; three passes found the campaign's centre of gravity had drifted into repairing controls that only watch other controls. |
<!-- /closeout:next -->

---

<!-- closeout:sessions -->
## Sessions

### 2026-09-18 (part 2) — Docs as projection: prune, then build the machinery
**Commits:** ~10 · **Scope:** `docs/**`, `dev/docs-generator/`, `flake.nix`, `Taskfile.yaml`

**Filed:** `TALOS-f0sd` (parent epic) + `TALOS-hadr` `TALOS-kll3` `TALOS-0hlo` `TALOS-c0hj`
`TALOS-osdj` `TALOS-05xr` `TALOS-mpbu` (E1–E7)
**Closed:** `TALOS-4ca6` (W3 doc drift — superseded: this epic fixes the cause, not instances)
**Carried:** `TALOS-kll3` is the next action

**Pruned `docs/` 105 → 37 files, 33k → 7.3k lines.** Nothing deleted; 67 files `git mv`'d to
`docs/_archive/`. Two distinct removals, and conflating them is how the tree got that big:
*episodic* material (audits, retros, completed migration plans — true on their date, not
drifted) and *actively misleading* docs (`networking.md` told you to `helm install traefik`,
bypassing Flux; `gitops-responsibilities.md` asserted "FluxCD NOT YET DEPLOYED" for ten months;
`infrastructure-diagrams.md` had 14 authoritative diagrams of a cluster with TrueNAS and Nebula
that does not exist).

**Built `docsgen`** — a portable Go module at `dev/docs-generator/`, on `PATH` in the dev shell.
Read-only in this phase. First run: 108 broken links, 15 component-shape warnings.

**Corrected a premise of mine along the way.** I had written that grouping directories without
their own `kustomization.yaml` meant "the tree is wrong". The data says the opposite: `security/`
with `crowdsec`/`falco`/`honeypots`/`iocaine` each being their own Flux Kustomization is the
**correct** pattern. The real smell is one slug wrapping many deployable units —
`monitoring/v2-otel` (16 nested), `media-experimental` (15), `operators` (8). The tool now
*measures* that rather than working around it.

**Design record:** `docs/06-project-management/memory-knowledge-architecture.md` — the
projection model (every layer is a lossy view of the one below; drift is a projection diverging
from its source; read downward only as far as the question needs).

### 2026-09-18 (part 1) — Security campaign + three adversarial validation passes
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
7. **`title:` must never appear in markdown frontmatter here.** Verified against the repo's
   pinned markdownlint 0.41.1: it silently disables MD041 *and* turns every existing H1 into an
   MD025 duplicate-heading error. Frontmatter itself is fine — front matter is stripped before
   parsing, so `---` before the H1 does not trip MD041.
8. **`task lint` is already red** — `prettier --check .` fails on 611 files. Any new gate wired
   into `dev:ci` is born ignored. Scope new checks to their own regions and land enforcement
   separately.
9. **`mise` exports a global `GOROOT`.** Inherited into the flake shell it makes the flake's `go`
   drive a *different* toolchain: `compile: version "go1.22.1" does not match go tool version
   "go1.26.7"`. The flake's shellHook now `unset GOROOT`; also `GOWORK=off`, or a parent
   `go.work` drags sibling workspace modules into the build.
10. **A grouping directory with no `kustomization.yaml` is the CORRECT pattern**, not a defect —
    its children are each their own component. The actual smell is the inverse: one slug wrapping
    many nested kustomizations, which makes "component = directory = doc home" untrue.
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
