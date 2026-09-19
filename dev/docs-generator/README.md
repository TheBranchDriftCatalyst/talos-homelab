# docsgen — documentation linter and generator

A self-contained Go module. Lints a repository's markdown against its code, and (from
`TALOS-kll3`) generates the parts of the doc tree that are facts rather than judgment.

## TL;DR

```sh
task docs:lint          # every enabled rule
task docs:links         # broken internal links only
task docs:components    # component inventory: slug, README presence, nested-kustomization count (`n/a` where the strategy cannot measure it)
task docs:frontmatter   # docs with no frontmatter — the migration worklist
task docs:stale         # docs whose covered code has moved ahead of them
task docs:rule -- component-shape   # a single rule
docsgen lint -all       # every finding, not the first 20 per rule
```

Each rule prints at most 20 findings by default and then says how many it withheld. `-all` lifts
that cap completely. Both halves matter: the cap is what keeps a fresh adoption's 154-finding
wall readable, and `-all` is what makes a 120-finding rule triageable at all — you cannot act on
what the tool will not print.

Inside the dev shell the binary is on `PATH`, so `docsgen lint` works from anywhere in the repo
without a path prefix. `task docs:build` compiles it; the flake's `shellHook` adds
`dev/docs-generator/bin` to `PATH`.

## Why this exists

Docs are the only projection of a codebase that nothing keeps honest. Code graphs get reindexed,
session logs are derived from git, decision records are superseded rather than edited — but a
hand-written doc has no regeneration path and no verification step, so nothing ever forces it
back into agreement with the code it describes.

This is that verification step. It does not make docs correct; it makes their incorrectness
**fail loudly** instead of accumulating silently.

## Porting it to another repo

Copy `dev/docs-generator/` and edit `config.yaml`. That is the whole procedure — no Go changes.

The Go knows nothing about Talos, Flux or beads by name. It knows there is *a* way to enumerate
components and *a* ticket shape, and reads both from config. If a repo enumerates components
some other way, add one `strategy_<kind>.go` that registers itself from `init()`; no existing
file needs editing, and never special-case inside a rule.

| Config key | What it controls |
| --- | --- |
| `components.kind` | `flux` (read Kustomization CRs, take `spec.path`) or `dirs` (glob directories) |
| `exclude` | tracked paths to skip — the walker is `git ls-files`, so ignored files are already out |
| `doc_types`, `statuses`, `freshness` | the closed frontmatter vocabulary |
| `banned_keys` | keys that must never appear, each with the reason |
| `grouping_roots` | paths that mean "cross-cutting", so a doc covering them belongs centrally |
| `type_requires` | per-type structural expectations — what makes `type:` more than a label |
| `rules` | enable/disable and severity per rule |
| `docs_root` | the repo's documentation root (default `docs`) — where artifacts are written, and what `colocation` calls "central" |
| `artifacts` | the generated document set: destination, scope, frontmatter and footer tickets, per artifact |
| `artifacts.<name>.region` | marker-region ownership: the artifact writes only the span between that region's markers |
| `artifacts.<name>.nav` | the nav renderer's enumeration: `entries`, `dir`, `description_key` |

### The generated artifact set

```yaml
docs_root: docs

artifacts:
  component-inventory: # the key names the renderer unless `renderer:` says otherwise
    path: 07-reference/component-inventory.md # relative to the artifact's root
    front: # rendered in key_order; no key here is special to the Go
      type: reference
      status: current
      covers: [cluster]
      freshness: tracks-code
      tickets: [TALOS-kll3, TALOS-f0sd]
      bluf: ...
    ticket_notes: # annotations for the footer's ticket list
      TALOS-kll3: the generator and its whole-file artifacts

  security-inventory: # the SAME renderer, over a SUBSET, beside the manifests it describes
    renderer: component-inventory
    root: infrastructure/base/security # overrides docs_root for this artifact
    path: components.md # relative to `root`
    scope:
      path_prefix: infrastructure/base/security
    front: { ... }
```

### `scope:` — a members table for one section

An artifact with no `scope:` renders **every** component, which is what every artifact written
before scoping does, so their bytes did not move by one character when the key landed. A
`scope.path_prefix` narrows it to the components whose path is inside that directory.

Matching is **segment-aware**: `infrastructure/base/security` covers that directory and anything
under it, and does **not** cover `infrastructure/base/security-extras`. A substring prefix would
pull the neighbour into a members table and nothing would ever report it.

**A scope that matches no component is exit 2, naming the key.** Never a silently empty table —
"this section has nothing in it" and "your filter is wrong" render identically, and only the
first one is a document anybody can act on. The error carries the component COUNT as well as the
prefix, because "matched nothing" has two causes (a typo, or a collector that found nothing at
all) and the count is what tells them apart.

### `root:` — an artifact outside the documentation tree

`path` is resolved against `root`, and `root` defaults to `docs_root`. It exists because a
section inventory belongs beside its manifests, and those are outside the documentation root —
which `path` may not escape, and that guard is worth keeping. So the escape is DECLARED rather
than smuggled through `../..`, and it is still bounded: `root` must resolve inside the repo.

### `renderer:` — one renderer, several artifacts

`renderers` is keyed by name, so before scoping there was exactly one way to spell "render a
component inventory" and therefore exactly one per repo. A per-section inventory is the same
renderer over a subset; `renderer:` lets the second one be a YAML stanza rather than a Go edit,
which is the whole portability claim.

Behaviour when the block is incomplete, which is the part that is easy to get wrong:

| situation | behaviour |
| --- | --- |
| `artifacts:` absent entirely | write nothing, say `no artifacts configured`, **exit 0** — generating nothing is a normal adoption state |
| `artifacts.<name>.path` missing | **exit 2**, naming the key |
| `front.type` / `status` / `freshness` outside the configured enum | **exit 2**, naming the key and printing the allowed values |
| `docs_root` absent | default `docs` |
| `root` absent | default `docs_root` |
| `root` escaping the repository | **exit 2**, naming the key |
| `scope` absent | every component |
| `scope:` present with no `path_prefix` | **exit 2** — a half-written filter is not "cover everything"; omit the block for that |
| `scope.path_prefix` matching no component | **exit 2**, naming the key and the component count |
| `renderer` naming no renderer | **exit 2**, naming `artifacts.<name>.renderer` |

**There is no default `type`, `status` or `freshness`.** A default is a Go constant wearing a
config key — silently wrong in every repo that does not share this one's vocabulary, which is
exactly the defect the block exists to remove. A wrong `docs_root` is different in kind: it is a
PATH, and a wrong path is visible the first time anybody looks at the tree.

### `region:` — marker ownership, for a file docsgen must not own outright

`INDEX.md` and the section READMEs carry editorial prose a generator cannot reproduce: a
grounding-pass note, a "Key Concepts" block, a list of known contradictions between documents. A
whole-file artifact pointed at one of those deletes it on the first run. So those files are
**marker-owned**: docsgen writes one span and copies every other byte through untouched.

```markdown
<!-- docs:gen:nav -->

| Doc | What it covers |
| --- | --- |
| [quickstart.md](quickstart.md) | Fast-track cluster setup and common commands. |

<!-- /docs:gen:nav -->
```

```yaml
nav-getting-started:
  renderer: nav
  path: 01-getting-started/README.md
  region: nav # the marker name; presence of this key switches on marker ownership
  nav:
    entries: siblings # or `sections`
    description_key: bluf # NO DEFAULT — see below
```

Three properties are load-bearing.

**The blank lines around the table are part of the convention.** Verified against this repo's
pinned prettier 3.9.6: a table butted directly against an HTML comment gets a blank line inserted
on either side, so the unframed form is not a fixed point and `docsgen check` would report drift
on the first unrelated `prettier --write`.

**Only the region body is normalised.** Running the normaliser over the merged document would be
the obvious implementation and is wrong: these files are not prettier fixed points — this repo
has a 611-file formatting backlog — so normalising the whole thing silently reformats prose the
artifact does not own, and the diff is indistinguishable from a content change.

**A broken marker state is a hard error naming the file.** Missing, unbalanced, nested, inverted,
or a file that does not exist: every one of them refuses to write, in both `generate` and
`check`, with exit 2. Never an append, never a fall back to whole-file ownership. Both of those
alternatives are silent, both destroy or duplicate prose, and neither is recoverable from
anything but somebody's memory.

`front:` and `ticket_notes:` are **refused** on a marker-owned artifact. It writes no frontmatter
and no footer — the file it writes into owns both — so such a block would render nowhere while
appearing to have been validated.

Two artifacts may own two different regions in one file (`INDEX.md` has a sections table and a
root-documents table). Two artifacts owning the *same* region, or any whole-file artifact sharing
a destination, is a config error: the first never reaches a fixed point and the second erases the
other's work.

### `nav` — a link table derived from the tree

A hand-written link table is a claim about the tree that nothing revalidates. When
`docs/_archive/` was deleted from this repo, 58 rows across nine nav files kept pointing at
documents that no longer existed anywhere — not moved, **deleted**, with nothing to repoint them
at — and `broken-links` reported all 58 forever. Rows derived from the corpus cannot reach that
state.

| `nav` key | Meaning |
| --- | --- |
| `entries: siblings` | the markdown documents directly in `dir`, skipping the artifact itself and any `README.md` (a section's README is indexed by the parent's sections table) |
| `entries: sections` | `<subdir>/README.md` for each subdirectory of `dir` |
| `dir` | the directory to enumerate; defaults to the artifact's own directory |
| `description_key` | the frontmatter key carrying each target's one-liner |

Rows come from `ctx.Docs` — `git ls-files` filtered by `exclude:` — so an untracked scratch file
never appears and a deliberately excluded tree never leaks into a published index. They are
**sorted by repo-relative target path**, bytewise ascending. That key is total (two rows cannot
share it, which the link text can) and it makes numeric section prefixes order naturally without
the generator knowing about them.

The description column is the **target's own** `description_key` value, falling back to its H1
and then to an em dash. Reading it from the target rather than generating it is what keeps the
curated one-liners — the only reason anybody reads a nav table instead of running `ls` — alive
across a regeneration. There is deliberately **no default** for `description_key`: against a repo
whose key is spelled `summary`, a hardcoded `bluf` would make every description silently degrade
to the H1 while looking like it worked. It must also appear in `key_order`, or no document in the
repo is expected to carry it.

A target whose frontmatter says `status: superseded` is skipped **unless** it declares
`superseded_by`. A dead end says "do not trust me" and offers nowhere to go; a forwarded one is
worth an entry, because following it is how a reader reaches the replacement.

A nav whose enumeration matches nothing is an error naming the key, for the same reason an empty
scoped inventory is: a header, a separator and no rows reads as "this section is empty" when it
means "the enumeration is wrong".

### The pre-write gate

After rendering and **before writing**, `Generate` runs each artifact's own bytes back through
`MakeDoc` + `ruleFrontmatterSchema` + `ruleTaxonomyStructure` against the live config, and
refuses to write on **any** finding — in `check` mode as well as `generate`, and regardless of
severity (`warn` grandfathers documents that predate the taxonomy; a file being written right now
has no history to grandfather). The error names the config key at fault.

This is stronger than making the constants configurable. Configurable constants can still be
configured wrong, and the wrong value is then discovered only if somebody commits the artifact
and runs the linter — which, because the walker is `git ls-files` and a generated artifact is
usually untracked, had never happened once. The gate means docsgen cannot emit a document its own
ruleset rejects, whether or not the file is ever tracked.

## The rules

| Rule | What it catches | Requires |
| --- | --- | --- |
| `broken-links` | relative links to files that do not exist | — |
| `frontmatter-schema` | unknown enum values, missing required keys, banned keys, key order | — |
| `covers-resolves` | a doc claiming to cover a component that does not exist | — |
| `component-path` | a component whose declared path is missing on disk | `component.path_is_declared` |
| `component-shape` | **one component slug wrapping many nested units** — see below | `component.sub_units` |
| `colocation` | a doc that is not where its declared scope says it should live | — |
| `tickets-in-body` | a ticket in frontmatter that the body never mentions | — |
| `taxonomy-structure` | a doc that does not match the shape its `type:` claims | — |

### A rule that cannot run says so

`Requires` is the demand side of the fact vocabulary a component strategy declares with
`Provides()`. A rule whose measurement the configured `components.kind` cannot supply is **not
run**, and is reported:

```text
skipped  component-path   needs component.path_is_declared, which components.kind `dirs` does not report
skipped  component-shape  needs component.sub_units, which components.kind `dirs` does not report

5 finding(s): 3 error, 2 warn
2 rule(s) could not run — see the `skipped` lines above
```

Why it exists: `component-shape` counts nested `kustomization.yaml` files and `component-path`
asks whether a *declared* path exists. Under `components.kind: dirs` neither measurement is
available — the count is structurally zero without kustomize, and a directory the walker found
is on disk by construction. Both rules used to run, find nothing, and be reported as a clean
pass. **A rule that silently never fires is worse than an absent one, because the report reads
as coverage.**

Four properties are deliberate:

- **On stdout, with the report.** A skip is part of the lint *answer*, not a diagnostic about
  the run. On stderr it is invisible to `docsgen lint | tee report.txt` and to any CI log that
  keeps only stdout — which is exactly where somebody reads "no `component-shape` findings".
- **Leading token `skipped`, never `component-shape  [skipped]`.** The second shape is
  indistinguishable from a rule block to anything reading the report by rule name, so a check
  for "no `component-shape` findings" would pass identically whether the rule ran clean or never
  ran. That ambiguity *is* the defect being removed.
- **The summary line is untouched.** `N finding(s): E error, W warn` keeps its exact bytes; the
  skip count is appended as its own line, so a skip can never be counted as a finding.
- **Skips do not affect the exit code, and there is no `-strict` flag.** A repo whose strategy
  is narrower than Flux's must be able to adopt the tool without landing red on day one. A flag
  nobody sets is a feature nobody tests.

`docsgen components` follows the same rule with **fixed columns and `n/a`**, never a dropped
column and never a zero: `nested 0` and `nested n/a` are different claims, and printing the
first for the second is the same lie in a different place.

```text
slug       readme  nested   suspend path
billing    yes     n/a      n/a     services/billing
```

### On `component-shape`

A grouping directory whose **children are each their own component** is the *correct* pattern
and is never reported — each child has its own slug and its own doc home.

What is reported is the opposite: one slug wrapping many deployable units. That makes
"component = directory = doc home" untrue and forces every downstream consumer to special-case
it. The threshold is deliberately low, because the finding is a prompt to look, not a defect.

### On severity

Everything starts at `warn` except link integrity. Findings on a pre-existing tree are a
migration worklist, not a regression — and a linter that lands red on an existing codebase gets
switched off within a day. Promote rules to `error` in `config.yaml` as each is burned down.

## Design notes worth keeping

- **`git ls-files` is the walker, never a filesystem walk.** It excludes gitignored paths for
  free. In this repo a raw walk finds 1065 markdown files; git finds 161 — the difference is
  ~10 full repo copies under `.claude/worktrees/`.
- **Dates come from one `git log --name-only` pass**, not one `git log -1` per file.
- **Loaders warn and skip.** One malformed manifest must never abort a whole-tree scan,
  otherwise a single typo makes the tool useless exactly when you want it.
- **`GOWORK=off`.** A parent `go.work` in the surrounding workspace otherwise drags sibling
  modules into the build. This module must stay self-contained to remain portable.
- **`unset GOROOT`.** `mise` exports a global `GOROOT`; inherited into the flake shell it makes
  the flake's `go` drive a different toolchain and fail with a `compile: version ... does not
  match` error.

## Known limitations

The normaliser's fixed-point claim — run prettier over generated output and nothing changes —
holds for the constructs this generator emits, all of which are verified against real prettier
by `TestPrettierFixedPoint`. It is **not** a claim about arbitrary markdown. Everything below
was measured against prettier 3.9.6, not reasoned about.

Where the two disagree, the normaliser declines to touch the block rather than rewriting it into
a shape prettier will undo. An unformatted block is merely untidy; a block the two tools format
differently is rewritten back and forth forever, with `task dev:lint:prettier` and
`task docs:check` taking turns failing.

| Construct | Behaviour | Consequence |
| --- | --- | --- |
| Table inside a blockquote (`> \| a \|`) | not matched, not normalised | prettier **will** reformat it: such a doc is not a fixed point |
| Table inside a `` ```md `` / `` ```markdown `` fence | skipped with the rest of the fence | prettier formats embedded markdown, so it is not a fixed point |
| `~~~` fence delimiters | left as written | prettier rewrites them to `` ``` ``; unrelated to tables, never normalised here |
| Table indented 4+ columns | left alone as an indented code block | also declines tables nested two list levels deep, which is the price of having no block parser |
| Cell containing ZWJ, a variation selector, ZWSP, ZWNJ or BOM | `Generate` **fails**, naming the artifact and the cell | deliberate: prettier's width for these is grapheme- and version-dependent, so any guess oscillates |
| Trailing whitespace inside a line | always stripped | destroys a two-space markdown hard line break |
| Generated file reached through a symlink | `os.Rename` replaces the link; `check` reads through it | the two can disagree about which file the artifact is |

Three of those deserve more than a row.

**Hard line breaks.** Two trailing spaces are a markdown hard line break and this normaliser
strips them. That is invisible today because every artifact is generated from tables and
headings, but it becomes real the moment the marker-region artifacts start normalising human
prose. Matching prettier here is not a one-line change: it keeps exactly two trailing spaces
when the next line continues the same paragraph, collapses three or more to two, and strips them
at a paragraph end — so reproducing it needs the block context this line-based scanner does not
have. Guessing wrong in the *other* direction (preserving a trailing run prettier would strip)
is the worse failure, because it is the oscillation this whole design exists to avoid. Left as
is, on purpose, until there is a prose artifact to test it against.

**Blockquoted tables.** Out of scope. `tableLineRe` anchors on a leading `|`, so a `>`-prefixed
row never reaches `renderTable`. Handling them means stripping and restoring the quote prefix
much the way the indent is handled now — tractable, just not done, and no current artifact emits
one.

**Symlinked artifacts.** `check` reads the artifact with `os.ReadFile`, which follows a symlink;
`generate` finishes with `os.Rename`, which replaces the link itself rather than writing through
it. A symlinked artifact therefore reports drift forever after the first write, because check
keeps reading the old target. No artifact is symlinked today and nothing detects it if one
becomes so.

## Related Issues

- `TALOS-hadr` — this tool (linter + read-only reports)
- `TALOS-kll3` — the generation half
- `TALOS-f0sd` — parent epic
