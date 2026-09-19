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

Cluster in `fleet/prod-west`, components in `platform/` and `workloads/`, prose in `handbook/`,
tickets `ORCH-nnn`, footer `## Tracking`, and a doc-type vocabulary (`overview`, `design`, `adr`,
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

> A fixture can defeat itself. `handbook/getting-started/missing-footer.md` must never write its
> own footer heading anywhere, not even inside backticks — the rule is a substring search over
> the whole file, so one mention silently repairs the fixture and the spec then passes while
> testing nothing. This happened once during authoring.

### `plain-dirs` — no GitOps at all (`components.kind: dirs`)

Services in `services/`, prose in `notes/`, tickets `PD-nn`, footer `## Follow-up`, types
`note`/`spec`/`howto`/`log`. `loadDirs` had **zero** coverage before this sample, and it is the
fallback for every repo that is not a Flux repo — simultaneously the least-tested and the most
load-bearing path for portability.

## What the goldens pin

Goldens are a tripwire, not a definition of correct: one tells you something changed, never that
the new thing is right. The invariants beside them are the truth. **A golden that disagrees with
an invariant means the golden is stale.**

| file                    | pins                                                                          |
| ----------------------- | ----------------------------------------------------------------------------- |
| `component-inventory.md`| the generated artifact's exact bytes — also the prettier fixed-point guarantee |
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

1. **The generated artifact violates the tool's own ruleset.** Its frontmatter, footer and ticket
   IDs are string constants in `artifact_inventory.go`: `type: reference`, `covers: cluster`,
   `## Related Issues`, `TALOS-kll3`, and prose naming `clusters/catalyst-cluster`. Against any
   other repo's config those are an out-of-enum type, a wrong footer and another project's
   tickets. It goes unnoticed in normal use only because the artifact is usually untracked, and
   an untracked file is never linted.

2. **The artifact's destination is hardcoded.** `Artifacts()` returns
   `docs/07-reference/component-inventory.md` with no config input, so a repo whose docs live
   anywhere else cannot be served without editing Go.

3. **`kustomizationNames` reads `Component.Source` as a file.** Under `kind: dirs` the Source *is*
   the component directory, so every `generate` emits one `is a directory` warning per component
   — and those warnings carry the absolute repo root onto stderr.

4. **`component-shape` and `component-path` cannot fire under `dirs`.** `Nested` counts
   `kustomization.yaml` files, so it is structurally always zero in a repo with no kustomize; and
   `loadDirs` only ever emits directories that exist, so the path check has nothing to catch. A
   rule that silently never fires is worse than an absent one, because you believe you are
   covered. Whether these should skip-with-a-reason or be strategy-gated is an architecture call.

5. **`tickets-in-body` can never fire.** It tests `strings.Contains(d.Text, ticket)`, and `d.Text`
   is the whole file *including the frontmatter the ticket was read from*, so every ticket
   trivially matches itself. It should search `d.Body`. `handbook/process/ticket-drift.md` is the
   fixture waiting for the fix.

### Dead keys and unobservable state

- `ticket_pattern` is parsed into `Config.TicketPattern` and read by nothing.
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
