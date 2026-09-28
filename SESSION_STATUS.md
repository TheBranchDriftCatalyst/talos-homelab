# Session Status — talos-homelab

<!-- closeout:header -->

**Kind:** Talos Kubernetes homelab · infra + GitOps · **Tracker:** beads (`bd`) · **Updated:** 2026-09-27
**Pick up here:** `TALOS-iymy` (SOTA GPU node — resume from the `_SEED_COMPLETE` marker; the g6e.12xlarge launch is held for an explicit go) · **Deadline item:** none outstanding
<!-- /closeout:header -->

> Maintained by `/closeout-session`. Newest session first. The index keeps the **last 10**;
> older entries move to [`docs/session-archive.md`](docs/session-archive.md).
> See [How this file is maintained](#how-this-file-is-maintained) before editing by hand.

---

## 30-second orientation

Multi-node Talos cluster, dual GitOps (Flux for infra, ArgoCD for apps). Everything under
`infrastructure/` and `applications/` deploys by committing to git; there is no deploy script.

**The live effort is the SOTA GPU node; two older efforts remain open.**

1. **SOTA GPU inference node** (`TALOS-iymy`) — _the live one_. A us-east-2 `g6e.12xlarge` (4× L40S)
   serving Qwen3-235B + ComfyUI on a self-hosted Headscale mesh, model cached from S3. Phases 0–1
   (mesh + AWS prereqs) and the pytest acceptance suite are in; the model is seeding to S3. See Now/next.
2. **Docs as projection** (`TALOS-f0sd`) — open; was the live effort on 2026-09-19. The tree is pruned
   from 105 to 37 files and `docsgen` (a portable Go linter at `dev/docs-generator/`) reports drift; the
   generator half remains.
3. **Security campaign** (`TALOS-a13n`) — paused deliberately after a principal review. `a8vo.4` (P0) is
   the one live thread — partly remediated this session, entrypoint-default finish outstanding.

If you are here to do something else entirely, that is fine and probably correct. Read
[Standing gotchas](#standing-gotchas) first — most of them cost real outages to learn.

<!-- closeout:next -->

## Now / next

### Active — `TALOS-iymy`, SOTA GPU inference node (mesh + 235B + ComfyUI)

|                       |                                                                                                                                                                                                       |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Resume here**       | A seeder EC2 is streaming Qwen3-235B-A22B-GPTQ-Int4 (~123GB) into `s3://catalyst-tbdc-models-use2/`. Check the `_SEED_COMPLETE` marker (an aws Job in `crossplane-system`, region `us-east-2`), then continue. |
| Next, in order        | Build `runpod-ollama`+`runpod-mac-bundle` → GHCR; rewrite the XGPUInstance userData (mesh-join from secret `mesh/headscale-join-key` + `s5cmd` S3→`/cache` + `docker run` **upstream** `vllm/vllm-openai` 235B TP4 `gptq_marlin` + ComfyUI); add the `us-east-2` `g6e.12xlarge` claim. |
| Held for explicit go  | The `g6e.12xlarge` **launch** (~$5–10/hr) — the only real spend. Confirm quota+capacity with `scripts/aws-gpu-report.sh` first. Full plan: `~/.claude/plans/…-snazzy-starlight.md`; state in `bd remember sota-gpu-node-state` + `qwen-seeder-inflight`. |

### Still P0 — `TALOS-a8vo.4`, host-spoof reaches everything (partly remediated)

|             |                                                                                                                                                                                                       |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| What moved  | The deferred **off-net cold pass** ran from a real AWS vantage and confirmed the live exposures; the concurrent session landed `lan-only` on the worst surfaces (`a8vo.7` **closed**; 6 admin/AI surfaces in `9e464b32`). |
| Still to do | The full **exemption inventory** + the Traefik entrypoint-default inversion are the careful finish. `a8vo.4` is still open (P0).                                                                       |

### Explicitly not next

|                                       |                                                                                                                                                                      |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Launching the `g6e.12xlarge` unprompted | It's the only real spend in the GPU effort. Confirm `_SEED_COMPLETE` + capacity + an explicit go first.                                                            |
| Flipping the Traefik entrypoint default | Not before the exemption inventory exists — a wrong list locks out your own SSO.                                                                                   |
| `TALOS-lq5y` provider-cred cutover      | The scoped IAM user is created (phase 1), but repointing the live ProviderConfig off the root keys can break the whole AWS stack — do it tested + deliberately, not casually. |
| `TALOS-f0sd` (docs) · `TALOS-a13n` (security campaign) | Both still open + worthwhile, but the GPU effort and the a8vo.4 P0 outrank them right now.                                                          |

<!-- /closeout:next -->

---

<!-- closeout:sessions -->

## Sessions

### 2026-09-26/27 — SOTA GPU inference node: mesh, the quota fight, interactive SSM

**Commits:** ~15 (this session; a concurrent session added ~10 more) · **Scope:** `infrastructure/base/{aws,aws-redteam,aws-providers,mesh,namespaces}`, `scripts/`, `tests/gpu-inference/`, `clusters/catalyst-cluster/`

**Filed:** `TALOS-iymy` (epic), `TALOS-x9db` (epic), `TALOS-nxt4`
**Closed:** none by this session (the concurrent session closed `TALOS-a8vo.7`)
**Carried:** `TALOS-iymy` (pick up here — 235B model seeding to S3 in-flight at close), `TALOS-x9db` (images→Zot), `TALOS-nxt4` (GPU quota), `TALOS-3hjh` (XGPUInstance correctness), `TALOS-lq5y` (scoped IAM: phase-1 user created, cutover carried), `TALOS-a8vo.4` (P0, partly remediated)

Shipped **interactive SSM access** for the AWS boxes (`ee67bd57`): `instanceProfileName` on XInstance/XGPUInstance + a `catalyst-ssm` profile + an `ssm-jump` picker pod — a real off-net shell, no inbound, no key. Also ran the deferred **true-cold external pentest** from a real AWS vantage; it confirmed the host-spoof exposures were live (argocd apex→200, tautulli `/api`→200, `:8443` WAN-forwarded). The concurrent session remediated from that evidence — `a8vo.7` closed, `a8vo.4` `lan-only` fixes landed; `a8vo.4` stays P0-open for the entrypoint-default finish.

Opened the big effort **`TALOS-iymy`**: a SOTA GPU node — Qwen3-235B-A22B-GPTQ-Int4 (official, ungated) on vLLM TP4 + ComfyUI sharing a us-east-2 `g6e.12xlarge` (4× L40S, 192GB), on a self-hosted Headscale mesh. Landed Phase 0 (`dd92f4c7`: XGPUInstance `ami`/`cacheSnapshotId` fields, `catalyst-gpu-seeder` IAM, us-east-2 model bucket), Phase 1 (`29f0a5e8`: Headscale live + WAN-reachable at `headscale.knowledgedump.space`, join key in secret `mesh/headscale-join-key`), and a pytest acceptance suite (`150f7d0d`: `tests/gpu-inference/`). A seeder EC2 is streaming the ~123GB model into us-east-2 S3 at close.

**The quota+capacity fight was the hidden cost.** g6e/L40S spot is dry in us-west-2 (placement score 1/10): the 32B/14B test-rig launches (`874f1a91`, `014bb205`) died on `InsufficientInstanceCapacity`, and only g5.xlarge/A10G + Qwen3-14B actually served (verified over SSM before teardown). The new `scripts/aws-gpu-report.sh` (`2dbb143f`) found us-east-2 is the one region with both quota and g6e.12xlarge spot capacity — which moved the whole plan there. `TALOS-nxt4` tracks the ask; on-demand G/VT went 0→48, spot to 32/48.

**Found, not built (the costly lessons):** upjet provider-aws rejects `resolve:ssm:` AMI aliases (needs a concrete region ami-id) and the DL GPU AMI needs a ≥75GB root; the dual-layer **S3→EBS cache never actually worked** (instance role had no S3 read → `s5cmd` AccessDenied → `set -eu` aborted before vLLM; the "successful" 14B run had silently bypassed S3 via HF-direct); and bulk HF→S3 must run on an in-AWS EC2, never the on-prem cluster (123GB over the home uplink = hours). Caught pre-build: `mac-sdlc-node` had no `.dockerignore`, so the ComfyUI image would have baked a 32M host-venv into public GHCR — added one. Cost: several short EC2 launches (~a few dollars), all torn down/self-terminating; only the ~$0.34 seeder + ~$3/mo S3 remain. No GPU is billing. Mid-effort reversal: dropped the EBS-snapshot pre-seed from the MVP (same-region S3→EBS at boot is ~1-2 min) — snapshot is now Phase 4.

### 2026-09-25/26 — Three silent failures found by reading the alert list

**Commits:** 22 · **Scope:** `infrastructure/base/{security,aws,analytics,traefik,forgejo-runner,themepark,monitoring}`

**Filed:** `TALOS-uy6a`, `TALOS-eecg`, `TALOS-soub`, `TALOS-cdec`, `TALOS-z16b`, `TALOS-c4l1`
**Closed:** `TALOS-a8vo.1` (P0), `TALOS-kb2f` (P1), `TALOS-1gp`, `TALOS-a83x`, `TALOS-3g8f`, `TALOS-2o6e`, `TALOS-y7qg`, `TALOS-0jx`
**Carried:** `TALOS-a8vo.4` (P0 — Host-spoof reaches everything; the exemption inventory is the safe first half), `TALOS-uy6a` (analytics injects nothing), `TALOS-eecg` (the class behind two of today's outages)

Three things had been broken for days while every dashboard looked fine, and all three were
sitting in the firing-criticals list unread. **CrowdSec had ingested no cowrie logs for 94
hours** — the tail does not survive kubelet log rotation without `poll_without_inotify`, and it
was the only container source missing it, so the honeypot contributed zero bans while attacks
landed and were written to disk unparsed. **boomtime served a bare 404 for five days** because
two Traefik plugin keys differed by one capital letter (`rewritebody` vs `rewriteBody`); Traefik
logged `Plugins loaded.` with five plugins, silently dropped the sixth, and disabled every router
referencing it. **falcosidekick-ui errored every few seconds for five days** showing `1/1 Running,
0 restarts` — its redis OOMed, and with no persistence the RediSearch index went with it, which
the UI only creates at startup.

The AWS work produced the sharpest lesson. An ExternalSecret named a 1Password item that never
existed (`aws-crossplane`; the credentials are `aws-credentials`), so the ProviderConfig had no
credentials for 33 days and every AWS managed resource sat `SYNCED=False`. **That broken
credential was acting as an undeclared brake.** Repointing it — a one-string fix — immediately
began creating real infrastructure nobody had reviewed: caught before either `g5.xlarge` launched
(`vllm-8b` is on-demand, ~$1/hr), after a 200 GB gp3 volume had already been created. The POC GPU
stack is now switched off via the kustomization's own "file = on-switch" idiom, and both claims
still carry `vpc-REPLACE-ME`, so they could never have come up anyway.

Costs, stated plainly. Two tickets' premises were wrong and so was my own advice: `TALOS-a83x`
claimed the 7 d TTL was unreachable (it is applied — measured 7.0 d) and I recommended setting
`allkeys-lru` before checking that it was already set. Deleting the "orphaned" PVC in
`TALOS-y7qg` **re-broke the UI minutes after I documented that exact failure class** — no pod
mounted it, but the StatefulSet still owned it via `volumeClaimTemplates`. And the new Falco
test false-passed on its first run, matching a pre-existing breach event and reporting "fired in
0s", then failed for a second reason that was also mine: a 63 ms node-vs-workstation clock skew.

`TALOS-a8vo.1` (P0) turned out to be already remediated and was closed with live proof rather
than on the ticket's word. Its sibling `TALOS-a8vo.4` is the carried P0 and the surface has grown
since it was written — a broader sweep now counts 182 of 263 routes without `lan-only`/auth.

### 2026-09-19 — Docs as projection: the tool, the sections, and what grounding found

**Commits:** 25 (+98 files uncommitted for one review pass) · **Scope:** `dev/docs-generator/`, `docs/**`, `infrastructure/base/security/**`, lint config

**Filed:** `TALOS-f0sd.1`–`.11`, `TALOS-0n61`, `TALOS-0l0m`, plus the `websecurelan` and honeypot-test bugs
**Closed:** `TALOS-hadr` (E1 linter), `TALOS-f0sd.2` (config-driven artifacts)
**Docs touched:** every section — frontmatter 12/91 → 42/91; 8 nav tables now generated; `pihole-ha-pattern.md` → `infrastructure/base/pihole/README.md`
**Carried:** `TALOS-f0sd.1` slice 4 (model renames), `.9` (derive grouping_roots), `.11` spec landed but corpus split open

**Broken links 120 → 0.** 93 of the original 120 were in six hand-maintained nav tables whose
targets had been _deleted_, not moved — so generation was the only correct fix. The rest were
one-offs. `docsgen` grew from a linter into a generator: config-driven artifacts, scoping,
marker regions, a strategy registry, and a pre-write gate that makes it structurally impossible
to emit a document its own linter rejects.

**What grounding found was worth more than what got built.** Verified, not inferred:
`websecurelan :8443` is WAN-forwarded while its manifest states the opposite (one of two
isolation layers gone); `svc/traefik` is ClusterIP, so six docs asserted a VIP it cannot hold;
`arr-stack` claimed no shared Postgres while running a 3-instance CNPG cluster; a Velero restore
command that matches nothing and _reports success_; two Taskfile tasks invoking a deleted
script; a honeypot security suite that had been globbing a path that stopped existing — its
`assert cnps` guard is the only reason it failed loudly instead of passing green.

**Four instances of one pattern: a reference validated for shape but never existence.** Bare
`covers:` slugs were checked; `path:` covers were trusted unconditionally; ticket IDs were
regex-only; and file-valued `path:` covers were _half-wired_ — moving the colocation verdict
while contributing nothing to staleness. That last one punished precision: nine covers naming
the exact file that invalidates a doc, four of them `configs/talconfig.yaml`, all inert.

**Cost.** Three fixtures cured their own defects by naming the literal they were meant to omit.
Two rules were tautologies. The anti-vacuity gate contained the bug it existed to catch
(`"10 components"` contains `"0 components"`). Eight golden files were silently untracked behind
a blanket `*.txt` gitignore. None of it was visible as failure — everything reported success.

### 2026-09-18 (part 2) — Docs as projection: prune, then build the machinery

**Commits:** ~10 · **Scope:** `docs/**`, `dev/docs-generator/`, `flake.nix`, `Taskfile.yaml`

**Filed:** `TALOS-f0sd` (parent epic) + `TALOS-hadr` `TALOS-kll3` `TALOS-0hlo` `TALOS-c0hj`
`TALOS-osdj` `TALOS-05xr` `TALOS-mpbu` (E1–E7)
**Closed:** `TALOS-4ca6` (W3 doc drift — superseded: this epic fixes the cause, not instances)
**Carried:** `TALOS-kll3` is the next action

**Pruned `docs/` 105 → 37 files, 33k → 7.3k lines.** Nothing deleted; 67 files `git mv`'d to
`docs/_archive/`. Two distinct removals, and conflating them is how the tree got that big:
_episodic_ material (audits, retros, completed migration plans — true on their date, not
drifted) and _actively misleading_ docs (`networking.md` told you to `helm install traefik`,
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
_measures_ that rather than working around it.

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
passes, each of which found the _previous_ round's fix hadn't worked.

**Landed:** Falco least-privilege (`privileged` → 4 caps, hostPaths 12→8); every CrowdSec LAPI
hop now verifies TLS (PKI moved onto the shared homelab CA trust-manager already distributes);
special-use IP filtering rewritten to CIDR _overlap_ matching; decision exporter given its own
credential and made rotation-proof; CNPG 17.0 → 17.6 across all seven clusters; honeypot breach
tripwire made **continuously self-testing** (canary CronJob + `HoneypotTripwireNotFiring`).

**Found only by validation:** the novelty bouncer was pulling 9.9 MB of decisions every 30 s
against its own 8 MB cap and had **stopped enforcing entirely**; the honeypot breach rules were
blind for most of the day (gotcha #1).

**Cost:** the campaign drifted into repairing controls that exist to watch other controls. The
two worst self-inflicted outages were _optional tidying nothing asked for_, done mid-campaign
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
   `container.name` resolving to a 12-hex container ID is a _broken_ state and is **not null**,
   so a null-check sails past it. Fire the rule; see the alert arrive.
2. **`kustomize build` passing is not validation for a HelmRelease.** It never reads the
   chart's `values.schema.json`. Use `helm template`. Two separate bugs shipped through that gap.
3. **A kustomization's `namespace:` silently rewrites the namespace in your manifest.** No
   error, green reconcile, resource in the wrong place.
4. **The honeypot namespace has a strict egress quarantine** that blocks the apiserver. That is
   correct — move your pod, don't widen the policy.
5. **The Traefik CrowdSec bouncer is fail-closed.** Breaking its TLS or LAPI reachability takes
   down _every_ HTTP route, and Traefik pods stay Ready while it rejects traffic.
6. **`cscli decisions list --scope range` silently returns nothing**, and a negative duration
   means _expired_, not active. Parse `-a -o json`.
7. **`title:` must never appear in markdown frontmatter here.** Verified against the repo's
   pinned markdownlint 0.41.1: it silently disables MD041 _and_ turns every existing H1 into an
   MD025 duplicate-heading error. Frontmatter itself is fine — front matter is stripped before
   parsing, so `---` before the H1 does not trip MD041.
8. **`task lint` is already red** — `prettier --check .` fails on 611 files. Any new gate wired
   into `dev:ci` is born ignored. Scope new checks to their own regions and land enforcement
   separately.
9. **`mise` exports a global `GOROOT`.** Inherited into the flake shell it makes the flake's `go`
   drive a _different_ toolchain: `compile: version "go1.22.1" does not match go tool version
"go1.26.7"`. The flake's shellHook now `unset GOROOT`; also `GOWORK=off`, or a parent
   `go.work` drags sibling workspace modules into the build.
10. **A grouping directory with no `kustomization.yaml` is the CORRECT pattern**, not a defect —
    its children are each their own component. The actual smell is the inverse: one slug wrapping
    many nested kustomizations, which makes "component = directory = doc home" untrue.
11. **A check that reports success is not a check that ran.** Every significant defect this
    session reported green: a dead glob with 4 collected tests, an untracked golden, a rule
    searching text containing its own needle. Verify the check _fires_, not that it passes.
    `[enforced: mutation proofs required on every new spec]`
12. **`git ls-files` and the filesystem disagree, and docsgen uses both.** `components` stats
    the disk; `lint` walks git. An untracked README is documented in one command and
    non-existent in the other. `[unenforced — TALOS-f0sd filed]`
13. **Prettier dedents YAML inside fences.** Running it repo-wide breaks snippets deliberately
    indented to show where they slot into a parent manifest. Scope it to files you edited.
    `[unenforced]`
14. **The pre-commit chain did not block until 2026-09-19.** The beads wrapper discarded
    lefthook's exit code, so every failing job passed silently — `markdownlint` had never once
    run. `[enforced: exit code now propagated; proven both directions]`

15. **A "plugins loaded" line is not proof your plugin loaded.** Traefik cannot hold two
    plugin keys differing only by case: it loaded five, silently dropped `rewritebody` in favour
    of `rewriteBody`, and disabled every router referencing the loser. The only symptom was a
    404 on a healthy app. Check the loaded list against what your middlewares reference.
16. **A dependency restarting under a live consumer leaves the consumer Running and broken.**
    falcosidekick-ui creates its RediSearch index only at startup, so a redis restart orphans it
    permanently while both pods stay `1/1 Ready, 0 restarts`. Compare pod ages before trusting
    health. (`TALOS-eecg`)
17. **"No pod mounts it" does not make a StatefulSet PVC safe to delete.** The StatefulSet still
    owns it through `volumeClaimTemplates`; deleting the claim forces a pod replacement. Check
    ownership, not just mounts.
18. **A broken credential is an undeclared brake.** While an ExternalSecret was unresolvable,
    every AWS resource in git sat `SYNCED=False` — not because anyone decided against them, but
    because they could not act. Fixing the credential starts creating them. Review intent before
    restoring credentials that have been broken a long time.
19. **CrowdSec file tails do not survive kubelet log rotation** without
    `force_inotify` + `poll_without_inotify`. The agent stays Running and its metric stays
    frozen at the last pre-rotation value, which reads as "quiet", not "broken".
20. **Event timestamps come from the node's clock, `t0` from yours.** A genuinely fresh event
    can timestamp _before_ the action that caused it (measured: 63 ms). Any test comparing the
    two needs a skew tolerance, or it will report a working control as blind.

21. **`quota` is not `capacity`, and GPU spot capacity is region-specific.** us-west-2 g6e/L40S
    spot is dry (placement score 1/10) even with quota granted — launches fail
    `InsufficientInstanceCapacity`. Check `scripts/aws-gpu-report.sh` (score **and** quota per
    region) before choosing a region or launching; as of 2026-09 us-east-2 is the one with both.
22. **upjet provider-aws rejects `resolve:ssm:` AMI aliases** — pass a concrete region-specific
    `ami-` id (make it a spec field, since it changes per region). Separately, the AWS Deep
    Learning GPU AMI's root snapshot is 75GB, so the root volume must be ≥75GB or the instance
    fails `InvalidBlockDeviceMapping`.
23. **Bulk model staging (HF→S3) must run on an in-AWS EC2, never the on-prem cluster.** The
    download is fast anywhere, but uploading ~123GB to S3 over the home uplink takes hours. An
    EC2 in the target region does HF→S3 (and S3→EBS) on the AWS backbone in minutes.

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
  debugging. Health belongs in alerts. _(This rule exists because a doc in this repo made
  exactly that mistake and had to be corrected.)_
- **Link to beads, don't duplicate it.** Ticket bodies are the source of truth; this is
  orientation and a pointer.
- **Keep the `<!-- closeout:* -->` anchors.** The command edits between them; the header block
  is deliberately identical across repos so siblings can be scanned side by side.
