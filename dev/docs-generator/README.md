# docsgen — documentation linter and generator

A self-contained Go module. Lints a repository's markdown against its code, and (from
`TALOS-kll3`) generates the parts of the doc tree that are facts rather than judgment.

## TL;DR

```sh
task docs:lint          # every enabled rule
task docs:links         # broken internal links only
task docs:components    # component inventory: slug, README presence, nested-kustomization count
task docs:frontmatter   # docs with no frontmatter — the migration worklist
task docs:stale         # docs whose covered code has moved ahead of them
task docs:rule -- component-shape   # a single rule
```

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
some other way, add a `kind` in `collect.go`; never special-case inside a rule.

| Config key | What it controls |
| --- | --- |
| `components.kind` | `flux` (read Kustomization CRs, take `spec.path`) or `dirs` (glob directories) |
| `exclude` | tracked paths to skip — the walker is `git ls-files`, so ignored files are already out |
| `doc_types`, `statuses`, `freshness` | the closed frontmatter vocabulary |
| `banned_keys` | keys that must never appear, each with the reason |
| `grouping_roots` | paths that mean "cross-cutting", so a doc covering them belongs centrally |
| `type_requires` | per-type structural expectations — what makes `type:` more than a label |
| `rules` | enable/disable and severity per rule |

## The rules

| Rule | What it catches |
| --- | --- |
| `broken-links` | relative links to files that do not exist |
| `frontmatter-schema` | unknown enum values, missing required keys, banned keys, key order |
| `covers-resolves` | a doc claiming to cover a component that does not exist |
| `component-path` | a component whose declared path is missing on disk |
| `component-shape` | **one component slug wrapping many nested units** — see below |
| `colocation` | a doc that is not where its declared scope says it should live |
| `tickets-in-body` | a ticket in frontmatter that the body never mentions |
| `taxonomy-structure` | a doc that does not match the shape its `type:` claims |

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
