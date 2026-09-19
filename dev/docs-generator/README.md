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
| `docs_root` | the repo's documentation root (default `docs`) — where artifacts are written, and what `colocation` calls "central" |
| `artifacts` | the generated document set: destination, scope, frontmatter and footer tickets, per artifact |

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
