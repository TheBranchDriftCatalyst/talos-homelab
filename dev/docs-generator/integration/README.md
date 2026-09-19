# docsgen integration suite

Black-box specs that build the real `docsgen` binary and drive it as a subprocess: argv in,
stdout/stderr/exit-code/bytes-on-disk out. That quadruple is the contract CI depends on, and it
is the only part of the tool a refactor is not free to change. The unit layer beside this one
covers the internals; nothing here imports `main` or touches an unexported function.

Every spec runs against a synthesised fixture. Nothing here reads or writes the real repository.

## Running it

```bash
cd dev/docs-generator

# everything, including the specs that assert invariants the tool does not yet satisfy
GOWORK=off go test ./integration

# the promotable gate: green today
GOWORK=off go run github.com/onsi/ginkgo/v2/ginkgo \
  --label-filter='integration && !known-gap' ./integration

# regenerate the golden files after an intended change
GOWORK=off go test ./integration -update-golden

# keep the fixtures for review (see "Review mode")
GOWORK=off go test ./integration -args -preserve-artifacts

# the anti-vacuity check: this MUST fail, loudly, before any spec runs
DOCSGEN_FIXTURE_SKIP_COMMIT=1 GOWORK=off go test ./integration
```

`GOWORK=off` is not optional. A parent `go.work` drags sibling modules into the build and it
fails; the suite also sets it internally before `gexec.Build` so the binary builds the same way
however the suite was invoked.

## Why the fixture is a real git repository

`docsgen`'s file walker is `git ls-files` and its dates come from a single `git log --name-only`
pass. A fixture that is merely a directory of files therefore produces **zero docs and zero
dates**, every doc rule finds nothing, `stale` prints nothing, and the whole suite passes while
asserting nothing at all. That is by far the most likely way a suite like this ends up green and
worthless.

So each sample is copied into a temp directory, `git init`-ed, and committed **twice**:

| commit | date         | contents                                    |
| ------ | ------------ | ------------------------------------------- |
| 1      | `2024-01-15` | the whole sample                            |
| 2      | `2024-06-20` | one file under one component, touched again |

The second commit is what moves code ahead of its docs and gives `stale` something true to find.
Both dates are pinned: two commits landing inside one second compare equal, which empties the
report and looks exactly like a pass — and a floating date would change the `stale` golden daily.

`user.email` / `user.name` are set locally because CI has no global identity, and
`GIT_CONFIG_GLOBAL` / `GIT_CONFIG_SYSTEM` are pointed at `/dev/null` so a developer's global
`core.excludesFile` cannot quietly hide files from the walker.

`assertSamplesAreReal` in the suite bootstrap proves all of this **before the first spec runs**.
Set `DOCSGEN_FIXTURE_SKIP_COMMIT=1` to watch it refuse.

## Layout

```
integration/
    integration_suite_test.go   bootstrap, gexec build, anti-vacuity gate
    samples_test.go             the sample table — every known answer lives here
    fixture_test.go             copy + git init + commit, the runner, tree hashing
    invariants_test.go          strategy-agnostic invariants, run against EVERY sample
    lint_test.go                the ruleset and component enumeration, pinned per finding
                                + the per-rule truncation cap and the `-all` flag that lifts it
    nav_test.go                 marker-region ownership: derived rows, the description key,
                                byte-identical prose, and a refusal for every broken marker state
    declarations_test.go        declared-vs-actual reconciliation, per sample
    cli_test.go                 exit-code contract, usage, path leaks, prettier agreement
    golden_test.go              byte-exact comparison, and -update-golden
    known_gaps_test.go          invariants the tool does NOT satisfy yet
    preserve_test.go            review mode
    testdata/
        samples/<name>/         hand-written sample repositories
        golden/<name>/          expected output, namespaced per sample
```

The invariant specs are table-driven over `samples`, so a new sample costs one directory plus one
entry in `samples_test.go` and **no new spec code**. Component enumeration is becoming a strategy
pattern (TALOS-f0sd.1); when a third kind lands, the whole invariant set should apply to it on
day one.

## The samples

Both are deliberately unlike talos-homelab in every dimension the Go reads from config. That is
the point: the tool's own package documentation claims you can copy `dev/docs-generator/` into
another repo, edit the YAML, and it works with no Go changes. These samples are the test of that
claim.

### `flux-cluster` — a GitOps repo (`components.kind: flux`)

Cluster in `fleet/prod-west`, components in `platform/` and `workloads/`, prose in `handbook/`
(`docs_root: handbook` — there is no `docs/` here at all), tickets `ORCH-nnn`, footer
`## Tracking`, and a doc-type vocabulary (`overview`, `design`, `adr`,
`table`, `journal`) that shares only the words any repo would use.

Eight components across seven manifests. The interesting ones:

| manifest       | pins                                                                                |
| -------------- | ----------------------------------------------------------------------------------- |
| `secrets.yaml` | TWO Kustomizations in ONE file — both must survive with **distinct** slugs           |
| `legacy-cache` | a `spec.path` that is not on disk — reported, and generation does not crash          |
| `storage`      | one slug wrapping 5 nested kustomizations — the directory-shape smell, measured      |
| `telemetry`    | the only suspended component                                                         |
| `broken.yaml`  | not valid YAML — the run must survive it and still report everything else            |
| `pathless.yaml`| a Kustomization with no `spec.path` — warned about, never turned into a component    |
| `namespace.yaml`| not a Kustomization — ignored silently                                              |
| `orchard-web`  | the far end of a three-level `dependsOn` chain                                       |

Each doc under `handbook/` trips **exactly one** rule and says so in its own prose. The negative
cases matter as much: `handbook/reference/dead-links.md` carries a dead link inside a fenced block
and another inside an inline span, and neither may ever be reported; `handbook/_attic/` is a
deliberate minefield that must produce **zero** findings because the config excludes it.

Two artifacts are configured, and the second one is why: `component-inventory` is UNSCOPED and
covers all eight components, while `platform-inventory` is scoped to `path_prefix: platform` and
covers six — so the same run asserts both that the filter includes what it should and that the
default still includes everything. It keeps the default root (`handbook/`) because `platform` is
a `grouping_root` here, which is where the `colocation` rule sends a doc covering it.

> A fixture can defeat itself, and this one has three times — see
> [Declarations](#declarations-what-a-fixture-says-it-produces) below, which is what now stops it.

### `plain-dirs` — no GitOps at all (`components.kind: dirs`)

Services in `services/`, prose in `notes/` (`docs_root: notes` — there is no `docs/` here at
all), tickets `PD-nn`, footer `## Follow-up`, types `note`/`spec`/`howto`/`log`. `loadDirs` had **zero** coverage before this sample, and it is the
fallback for every repo that is not a Flux repo — simultaneously the least-tested and the most
load-bearing path for portability.

This is the sample that exercises `root:`. Its `search-inventory` artifact is scoped to
`services/search` and rooted there too, so it lands at `services/search/components.md` —
**outside** `docs_root`, which is the whole reason `root:` exists: a section inventory belongs
beside the thing it describes, and `path` may not escape its own root.

## Declarations: what a fixture says it produces

### The defect class

Every sample doc is written to trip exactly one rule. docsgen's rules are **substring searches
over the document body**, so a fixture that NAMES the thing it is supposed to omit silently
**cures itself**: the rule falls silent, the fixture still reads as intentional, and the golden
gets regenerated against the silence. Nothing about the resulting report looks wrong — that is
what makes this class so durable.

It has happened three times:

| #   | fixture                                                   | what it named                                |
| --- | --------------------------------------------------------- | -------------------------------------------- |
| 1   | `flux-cluster/handbook/getting-started/missing-footer.md`  | its own required footer heading              |
| 2   | `flux-cluster/handbook/process/ticket-drift.md`            | the very ticket id it exists to omit         |
| 3   | `plain-dirs/notes/no-footer.md`                            | the literal footer heading, inside backticks |

The third was the worst: it cost `taxonomy-structure` its **only** coverage in that sample, and
an **undeclared** `tickets-in-body` finding on the same path kept the page looking covered in
`lint.txt`, so the golden was regenerated against the silence and nothing complained.

All three are fixed. The convention that was supposed to prevent them — each doc stating its
expectation in prose — was enforced by nothing, so a fourth was a matter of time.

### The format

A declaration is a line of its own, in the file the finding is attributed to:

```text
EXPECT: <rule-id>              # this file trips <rule-id> once
EXPECT: <rule-id> x<N>         # …N times
EXPECT: <rule-id> on <path>    # …attributed to <path> rather than to this file
EXPECT: none                   # this file produces no findings at all
```

Leading `#`, `//` and `<!-- … -->` are peeled off, so the same grammar works in markdown prose,
in a YAML manifest and in Go — which is why `component-path` is declared in
`fleet/prod-west/legacy-cache.yaml` and `component-shape` in `platform/storage/kustomization.yaml`
rather than in a side table nobody reads.

**A declaration names the RULE ID and nothing else.** It cannot contain the literal the rule
searches for — no footer heading, no ticket id, no link target — because the grammar has nowhere
to put one: anything after the rule id other than `x<N>` / `on <path>` is a hard parse failure
and the spec rejects the file. Explanatory prose still belongs in the fixture, on its **own**
lines, where it is not part of the declaration. The rule ids themselves are inert — no rule
searches for its own name, and no rule id is a substring of any trigger text.

That last claim is not left as a claim. One spec **deletes every declaration line** from a built
fixture, re-lints it, and requires byte-identical findings. If a declaration ever starts
satisfying — or provoking — a rule, it goes red and names the path.

### What is asserted, per sample, with no per-sample code

1. **Every declaration parses**, names a rule the sample's own `config.yaml` declares, and
   carries no free text. The old prose form (`EXPECTED FINDING: …`) is banned outright: two
   conventions means the unenforced one keeps getting used.
2. **Every `.md` in the sample declares something**, `EXPECT: none` included. This is the half
   that catches occurrences 1-3 — a fixture that cures itself produces nothing, so only a
   standing declaration can notice the silence.
3. **Declared and reported findings are the same multiset**, keyed on `(path, rule)`. Failure
   prints two explicit lists: *declared but missing* and *found but undeclared*. The second is
   what would have caught the accidental finding that masked occurrence 3.
4. **A file declaring `EXPECT: none` produces nothing** — an over-reporting rule gets switched
   off just as fast as one that misses.

## Marker-region ownership, and why its negative specs are the valuable half

`nav_test.go` covers artifacts that write **one span inside a hand-written document** rather than
the whole file. Each sample declares one (`NavRel`, `NavRegion`, `NavRows`, `NavExcludes`,
`NavDescribed`, `NavFallback`); `assertSamplesAreReal` refuses a sample that does not, for the
same reason it refuses one with no scoped artifact — a table-driven suite whose table has an
empty slot runs those specs against nothing and reports them green.

The positive specs assert the obvious things: rows come from the tree, a deleted target stops
producing a row, the description column is the target's own frontmatter key with an H1 fallback.

The **negative** specs are the ones that justify the feature existing. docsgen writes into files
carrying editorial prose no generator can reproduce, so every way the markers can be wrong —
absent, unbalanced, nested, inverted, file missing — is asserted to be a refusal (exit 2) that
names the file, writes nothing, and leaves the tree hash unchanged. Each carries an explicit
anti-append assertion, because the failure being refused is not "docsgen errored", it is "docsgen
helpfully appended the table to the end of somebody's prose". A nav that renders beautifully and
eats a paragraph on a bad marker is strictly worse than no nav at all.

One spec clobbers the region body with garbage, regenerates, and asserts that everything
*outside* the markers comes back byte-for-byte. That is the invariant the whole design rests on.

## What the goldens pin

Goldens are a tripwire, not a definition of correct: one tells you something changed, never that
the new thing is right. The invariants beside them are the truth. **A golden that disagrees with
an invariant means the golden is stale.**

| file                    | pins                                                                          |
| ----------------------- | ----------------------------------------------------------------------------- |
| `component-inventory.md`| the generated artifact's exact bytes — also the prettier fixed-point guarantee, and the proof that its frontmatter, footer and banner come from THIS sample's `artifacts:` stanza rather than from Go |
| `lint.txt`              | every finding, its rule, its severity and the stable order they print in       |
| `components.txt`        | slug, README presence, nested count, suspend flag and path for every component |
| `frontmatter.txt`       | the migration worklist, exactly                                                |
| `stale.txt`             | which docs are stale, reported as dates rather than a churning day count       |

Goldens are path- and time-stable: the temp root is scrubbed to `<ROOT>` before comparison, and
`matchGolden` fails if the placeholder ever appears, because that means an absolute path reached
output that is supposed to be portable. Two runs from two different temp roots produce the same
bytes — there is a spec that asserts exactly that, by building a second root in reverse file
order and diffing the results.

Regenerate with `-update-golden`. **Never hand-edit one to make a spec pass.**

## Review mode

`GinkgoT().TempDir()` deletes everything on exit, which is right for CI and useless for a human.
With `-preserve-artifacts` (or `DOCSGEN_PRESERVE_ARTIFACTS=1`), each spec's fixture is
materialised at a stable path under `.artifacts/` and kept:

```
.artifacts/<sample>/<spec>/repo/      the fixture as the spec left it, generated files included
.artifacts/<sample>/<spec>/outside/   a sentinel tree no command may write to
.artifacts/<sample>/<spec>/_runs/     NN-<command>.argv / .exit / .stdout / .stderr
.artifacts/<sample>/<spec>/_golden/   both sides of each comparison, plus a .diff when they differ
```

`.artifacts/` is wiped at the start of every preserved run and is gitignored. The spec directory
name is the spec's own text, slugified, with a short hash of the full text appended so two
similarly-worded specs cannot collide — stable across runs, so `diff -r` between two preserved
runs is meaningful.

**Preservation changes where files live and nothing else.** No assertion reads the flag; both
modes report identical pass/fail counts. A difference between them is a harness bug.

## Known gaps

These are real assertions carrying an extra `known-gap` label, not specs blessing broken
behaviour — a spec that documents a defect as correct is how a defect becomes a requirement.
Drop a spec's label the moment its defect is fixed; that is the ratchet.

**There are none right now.** The container in `known_gaps_test.go` is deliberately empty rather
than deleted, so the convention and its instructions stay in front of whoever finds the next
one. The full suite and the promotable gate
(`--label-filter='integration && !known-gap'`) are currently the same set.

### Closed gaps

Recorded rather than deleted, because each closure changed how the suite is read.

- **`component-shape` and `component-path` could not fire under `dirs`** (closed 2026-09-19).
  One spec delabelled: *measures component shape in terms the strategy actually supplies*.

  `Nested` counts `kustomization.yaml` files, so it is structurally always zero in a repo with
  no kustomize; and the `dirs` strategy only ever emits directories that exist, so the path
  check had nothing to catch. Both rules ran, found nothing, and were reported as a clean pass —
  a rule that silently never fires is worse than an absent one, because the report reads as
  coverage.

  The fix is not a better measurement; there is no honest number to print. Each rule now
  declares the facts it MEASURES (`Check.Requires`) against what the strategy declares it can
  SUPPLY (`ComponentStrategy.Provides`), and `Run` returns the rules it could not run alongside
  the findings. `docsgen lint` prints them on stdout with a leading `skipped` token — not as
  `component-shape  [skipped]`, which `findingsFor()` would read as a rule block and swallow,
  recreating the exact ambiguity being removed. `docsgen components` prints `n/a` in the
  unavailable columns rather than a `0` that would claim a measurement nobody made.

  Skips contribute nothing to the exit code and there is no `-strict` flag: a repo whose
  strategy is narrower than Flux's must be able to adopt the tool without landing red, and a
  flag nobody sets is a feature nobody tests.

  The `plain-dirs` goldens `lint.txt` and `components.txt` moved; `flux-cluster` is
  byte-identical, because that strategy supplies every fact.

- **docsgen generated a document docsgen itself rejects** (closed 2026-09-19). One cause with
  three faces, and three specs delabelled at once:

  - *generates an artifact that passes the tool's own lint*
  - *writes the artifact's frontmatter and footer from the host repo's configured vocabulary*
  - *places the artifact under the host repo's own documentation root*

  `Artifacts()` returned a hardcoded `docs/07-reference/component-inventory.md`, and
  `artifact_inventory.go` held the frontmatter type, freshness, footer heading and ticket ids as
  Go string constants. Against `plain-dirs` — doc root `notes/`, vocabulary
  `[note spec howto log]`, freshness `[live frozen]`, footer `## Follow-up` — that produced an
  out-of-enum `type`, an out-of-enum `freshness`, a missing footer and an invented `docs/` tree.
  The sample's findings went **5 → 8** the moment the artifact was committed.

  It hid because the artifact is normally UNTRACKED and the walker is `git ls-files`, so the tool
  had never once linted its own output. The first of the three specs `git add`s the artifact
  deliberately for exactly that reason, and now also asserts the file really is tracked before
  concluding anything from a clean report — otherwise "no findings" means "nothing was examined".

  What changed:

  | before                                            | after                                                              |
  | ------------------------------------------------- | ------------------------------------------------------------------ |
  | `Artifacts()` returns one hardcoded `Rel`          | `Artifacts(cfg)` resolves `docs_root` + `artifacts.<name>.path`     |
  | `const inventoryFrontMatter`                       | `artifacts.<name>.front` rendered by `renderFrontMatter`            |
  | `const inventoryRelatedIssues`                     | `cfg.RequiredFooter` + the ticket list from `front.tickets`         |
  | banner names `clusters/catalyst-cluster`           | banner composed from `cfg.Components.Path`                          |
  | colocation's cross-cutting target is `docs/`       | it is `cfg.DocsRootOr() + "/"`                                      |

  The fix that makes these STAY closed is not the config keys — a configurable constant can still
  be configured wrong, and the wrong value would again be discovered only if somebody happened to
  commit the artifact. It is the **pre-write gate**: `Generate` runs each artifact's rendered
  bytes through `MakeDoc` + `ruleFrontmatterSchema` + `ruleTaxonomyStructure` against the live
  config and refuses to write on any finding, in `check` mode as well as `generate`. The wrong
  bytes cannot reach the disk at all, tracked or not, linted or not.

  Both samples now carry their own `artifacts:` stanza in their own vocabulary, so
  `testdata/golden/*/component-inventory.md` moved — frontmatter, banner source path and footer.
  No other golden moved, which is itself the evidence that `docs_root` changed no lint verdict.

- **`tickets-in-body` could never fire** (closed 2026-09-19). It tested
  `strings.Contains(d.Text, ticket)`, and `d.Text` is the whole file *including the frontmatter
  the ticket was read from*, so every ticket trivially matched itself. It now searches `d.Body`
  and fires on `handbook/process/ticket-drift.md`. Two defects had to be fixed for the spec to
  mean anything, and the second — the fixture naming the ticket it was supposed to omit — only
  became visible once the first was fixed. That is occurrence 2 of the self-curing class above.

- **Reading `Component.Source` as a file under `kind: dirs`** (closed). The function this entry
  used to name, `kustomizationNames`, no longer exists, and `generate` on `plain-dirs` emits no
  `is a directory` warning. The spec asserting it — *"does not try to read a directory as a YAML
  manifest under `components.kind: dirs`"* in `known_gaps_test.go` — is **green today but still
  carries its `known-gap` label**, so it sits outside the promotable gate for no reason. Dropping
  that one label is the ratchet this section describes; it is left here rather than done silently
  because it moves the gate's spec count.

### Dead keys and unobservable state

- `ticket_pattern` is read only by `tickets-exist`, and neither sample configures a ticket
  backend — so in these fixtures it is parsed and used by nothing.
- The generated artifact's PROSE is still Flux-specific under `components.kind: dirs`: it says
  "Every row is one Flux Kustomization" and the `nested` column counts `kustomization.yaml`
  files. `plain-dirs`' inventory therefore describes itself in terms its repo has none of. The
  frontmatter, footer, destination and banner source path are now config; the body copy is not,
  and fixing it is the same architecture call as known gap 1.
- `Component.DependsOn` is collected from every manifest and surfaced by no command, so the
  dependency graph — including the sample's three-level chain — cannot be asserted through the
  CLI at all.
- A manifest that fails to parse is skipped **without any warning**: the decoder loop cannot tell
  a parse error from EOF, so it `break`s either way. That contradicts the documented warn-and-skip
  posture. `fleet/prod-west/broken.yaml` pins that the run survives; nothing can yet pin that it
  complained.

### One caveat about this directory

`testdata/samples/**` contains real `.md` files with deliberate defects — dead links, banned keys,
a `superseded` with no `superseded_by`. The host repo's `dev/docs-generator/config.yaml` does not
exclude them, so running `docsgen lint` on talos-homelab itself will now attribute those findings
to this directory. The host lint gate is already red on its own backlog so this changes no
red/green state, but the fix is one line in a file this suite does not own:

```yaml
exclude:
  - dev/docs-generator/integration/testdata/**
```
