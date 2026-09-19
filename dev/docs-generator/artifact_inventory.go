package main

// The component inventory artifact.
//
// One row per Flux Kustomization, because that is the unit Flux reconciles and therefore the
// only unit a doc can honestly claim to cover. The filesystem is NOT that unit: some
// directories group children that are each their own component, others are a single
// Kustomization wrapping many nested ones, and nothing in the tree distinguishes the two.
//
// This file renders and RETURNS a string; it never writes. Writing, normalisation and the
// byte-identical guarantee belong to Generate in generate.go. A renderer that wrote its own
// file would need its own copy of the normaliser, and two normalisers eventually disagree —
// at which point the drift gate starts failing on files it just produced.

import (
	"fmt"
	"path/filepath"
	"sort"
	"strings"
)

// The frontmatter, the banner and the footer are all CONFIG, not constants.
//
// They used to be the Go string literal below this comment: `type: reference`, `covers:
// cluster`, `freshness: tracks-code`, two TALOS ticket ids and a `## Related Issues` footer.
// Against any other repo's config that is an out-of-enum type, an out-of-enum freshness, the
// wrong footer and another project's tickets — so docsgen generated a document docsgen itself
// rejects. It went unnoticed here only because the artifact was never linted.
//
// What the Go still owns is the SHAPE: which columns the table has, what the prose says about
// them, and the ordering guarantees below. What it must never own again is any value that only
// makes sense in one repository.
//
// Two constraints on the rendered frontmatter survive the move into config and are enforced by
// renderFrontMatter rather than by a comment:
//
//   - No `title:` key. Verified against this repo's pinned markdownlint: a title key both
//     suppresses MD041 and turns the H1 below into an MD025 duplicate-heading error. It is in
//     `banned_keys`, and the pre-write gate refuses an artifact that carries one.
//   - `covers:` is a BLOCK sequence. A flow sequence (`[cluster]`) is exploded by prettier, so
//     the generated file would stop being a prettier fixed point on the first unrelated format
//     run and `docsgen check` would report drift it did not cause.

func yesOr(b bool, no string) string {
	if b {
		return "yes"
	}
	return no
}

// scopeNote returns the sentence that tells a reader the table in front of them is a SUBSET,
// or "" for an unscoped artifact.
//
// The empty string for an unscoped artifact is load-bearing, not tidiness: every artifact that
// existed before scoping omits `scope:`, and their bytes must not move by one character. An
// unconditional "scoped to: everything" line would have rewritten every inventory in every repo
// that adopted the tool, and the diff would have been indistinguishable from a real change.
func scopeNote(scope *ArtifactScope) string {
	prefix := scopePrefix(scope)
	if prefix == "" {
		return ""
	}
	// The prefix CLOSES its line, with the shortest possible lead-in. It is the only
	// variable-length run in this paragraph, so putting it mid-line would push that line past
	// the width every other paragraph here wraps at, by an amount nobody can predict from the
	// Go — it depends entirely on how deep the host repo's directory tree is.
	return fmt.Sprintf(
		"SCOPED inventory — only components whose path is inside `%s/`\n"+
			"appear below. That is what makes this a members table rather than a hand-written list:\n"+
			"a component added to or removed from the folder changes this file, and one that moves\n"+
			"out of it leaves.\n\n", prefix)
}

// scopePrefix is the scope's directory in its canonical spelling, or "" when the artifact
// covers every component. One definition, so the heading and the prose can never disagree about
// whether a table is scoped.
func scopePrefix(scope *ArtifactScope) string {
	if scope == nil {
		return ""
	}
	return strings.Trim(strings.TrimSpace(scope.PathPrefix), "/")
}

// scopeHeadingSuffix qualifies the H1 with the scoped directory, or "" when unscoped.
func scopeHeadingSuffix(scope *ArtifactScope) string {
	prefix := scopePrefix(scope)
	if prefix == "" {
		return ""
	}
	return " \u2014 `" + prefix + "`"
}

func renderComponentInventory(ctx *Ctx, spec ArtifactSpec) string {
	cfg := ctx.Cfg
	// Filtered FIRST, so every count, every column and the missing-paths list below all describe
	// the same set of rows. A renderer that scoped only its table would report "12 components
	// are declared" above a table showing four.
	comps := append([]Component(nil), scopeComponents(ctx.Components, spec.Scope)...)
	// Slug alone is NOT a total order here: `external-secrets.yaml` declares two Kustomizations,
	// so two rows share a slug, and sort.Slice is not stable. Without the path/source tiebreaks
	// those two rows could swap between runs and the artifact would stop being byte-identical.
	sort.Slice(comps, func(i, j int) bool {
		a, b := comps[i], comps[j]
		if a.Slug != b.Slug {
			return a.Slug < b.Slug
		}
		if a.Path != b.Path {
			return a.Path < b.Path
		}
		return a.Source < b.Source
	})

	var b strings.Builder
	// A render error cannot be returned from here — the renderer signature is bytes-in-bytes-out
	// so that Generate owns writing, normalisation and the byte-identical guarantee alone. It
	// does not need to be: validateArtifacts has already rejected an unrenderable `front:` with
	// an exit-2 error naming the key, so reaching this branch means config validation and the
	// writer disagree, and an artifact with no frontmatter at all is exactly what the pre-write
	// gate refuses a moment later.
	front, err := renderFrontMatter(cfg, spec.Front)
	if err != nil {
		warnf("front matter: %v", err)
	}
	b.WriteString(front)
	// The H1 names the scope, because a members table whose title is indistinguishable from the
	// whole-repo inventory lies by omission: the reader who lands on it from a search result has
	// no way to know rows are missing by design. Unscoped artifacts keep the bare heading, so
	// their bytes do not move.
	fmt.Fprintf(&b, "\n# Component Inventory%s\n\n", scopeHeadingSuffix(spec.Scope))

	// A blockquote, not *emphasis*: prettier rewrites `*em*` to `_em_`, so an emphasised banner
	// is not a fixed point and would make this file churn. The wording also has to match the
	// `reference` taxonomy rule, which requires a generated doc to say how it is regenerated.
	b.WriteString("> Generated file — do not edit by hand. Regenerate with `task docs:generate`.\n")
	// The source path is read from config, never named here. A banner that hardcodes one repo's
	// cluster directory tells every other repo to go look somewhere that does not exist.
	fmt.Fprintf(&b, "> The source of truth is the Flux Kustomizations in `%s/`,\n",
		strings.TrimSuffix(cfg.Components.Path, "/"))
	b.WriteString("> so a wrong row here is a wrong manifest there.\n\n")
	b.WriteString(scopeNote(spec.Scope))

	b.WriteString("Every row is one Flux Kustomization — the unit Flux reconciles, and therefore the unit a\n")
	b.WriteString("doc can honestly claim to cover. The directory tree is not that unit: some directories group\n")
	b.WriteString("children that are each their own component, others are a single Kustomization wrapping many\n")
	b.WriteString("nested ones, and nothing in the tree tells the two apart. So this table is built from the\n")
	b.WriteString("Kustomizations, never from the filesystem.\n\n")

	// Unreachable for a SCOPED artifact: validateArtifactScopes refuses to generate one whose
	// filter matches nothing, so an empty scoped table cannot reach a renderer at all. What
	// survives here is the unscoped case — a repo whose collector found nothing — where an
	// empty file is the honest answer and the text says where to go looking.
	if len(comps) == 0 {
		b.WriteString("No components were found. Check `components.path` and `components.glob` in\n")
		b.WriteString("`dev/docs-generator/config.yaml`.\n\n")
		b.WriteString(renderFooter(cfg, spec))
		return b.String()
	}

	var withReadme, renamed, missing int
	var missingRows []Component
	files := map[string]bool{}
	for _, c := range comps {
		files[c.Source] = true
		if fileExists(filepath.Join(ctx.Root, c.Path, "README.md")) {
			withReadme++
		}
		if c.Name != "" && c.Name != c.Slug {
			renamed++
		}
		if !fileExists(filepath.Join(ctx.Root, c.Path)) {
			missing++
			missingRows = append(missingRows, c)
		}
	}

	// Counts, not dates or SHAs. A count is a pure function of the tree, so two consecutive runs
	// are byte-identical and an unrelated commit does not produce a diff here.
	fmt.Fprintf(&b, "%d components are declared across %d manifest files. %d have a colocated `README.md`,\n",
		len(comps), len(files), withReadme)
	b.WriteString("which is the question this table really asks: a component with no README has no doc home,\n")
	b.WriteString("and whatever documents it lives somewhere that nothing keeps pointed at it.\n\n")

	// Cells are ASCII by construction. The normaliser pads to BYTE length to match prettier's
	// display-width padding, and an emoji is one byte-length but two columns wide — one ✅ in
	// this table and the file stops being a prettier fixed point.
	b.WriteString("| slug | flux name | path | on disk | readme | nested | suspended |\n")
	b.WriteString("| --- | --- | --- | --- | --- | --- | --- |\n")
	for _, c := range comps {
		name := c.Name
		if name == "" {
			name = "-"
		}
		fmt.Fprintf(&b, "| `%s` | `%s` | `%s` | %s | %s | %d | %s |\n",
			c.Slug,
			name,
			c.Path,
			yesOr(fileExists(filepath.Join(ctx.Root, c.Path)), "MISSING"),
			yesOr(fileExists(filepath.Join(ctx.Root, c.Path, "README.md")), "-"),
			c.Nested,
			yesOr(c.Suspend, "-"),
		)
	}
	b.WriteString("\n")

	fmt.Fprintf(&b, "`slug` is the manifest filename; `flux name` is its `metadata.name`. They differ on %d\n", renamed)
	b.WriteString("rows. The filename is the handle this tool uses, because a name that moves when someone\n")
	b.WriteString("edits a field is not a handle — but `dependsOn` in every other Kustomization refers to the\n")
	b.WriteString("flux name, so both belong here.\n\n")

	b.WriteString("## Reading the nested column\n\n")
	b.WriteString("`nested` counts the `kustomization.yaml` files underneath the component's path.\n\n")
	b.WriteString("A grouping directory whose children are each their own Flux Kustomization is the CORRECT\n")
	b.WriteString("pattern and is not what this counts: those children are not inside one component, they are\n")
	b.WriteString("several components, each with its own row, its own slug and its own doc home.\n\n")
	b.WriteString("A high count is the other shape — ONE slug whose single Kustomization applies many nested\n")
	b.WriteString("kustomizations. All of those nested units deploy, but only the wrapper has a name, so\n")
	b.WriteString("\"component = directory = doc home\" is untrue for it: there is no single thing the directory\n")
	b.WriteString("documents and no one README that could cover it. Run `task docs:rule -- component-shape` for\n")
	b.WriteString("the outliers.\n\n")

	b.WriteString("## Paths that do not exist\n\n")
	if missing == 0 {
		b.WriteString("Every declared `spec.path` resolves to a directory in this repo.\n\n")
	} else {
		b.WriteString("These components point at a path that is not in the repo. Flux reports this as a failed\n")
		b.WriteString("reconcile while the last successfully applied revision keeps running, so the cluster looks\n")
		b.WriteString("healthy and nothing surfaces it.\n\n")
		for _, c := range missingRows {
			fmt.Fprintf(&b, "- `%s` (declared in `%s`) points at `%s`\n", c.Slug, c.Source, c.Path)
		}
		b.WriteString("\n")
	}

	b.WriteString(renderFooter(cfg, spec))
	return b.String()
}

// renderFooter writes the footer the taxonomy rule requires of every non-nav type — a generated
// file being exactly the kind that would otherwise ship without one.
//
// The heading is cfg.RequiredFooter, so the artifact satisfies whatever the host repo asks for
// rather than whatever this repo asked for. The body is the ticket list from `front.tickets`,
// which is what makes `tickets-in-body` SELF-SATISFYING: that rule fires when a frontmatter
// ticket never appears in the prose, and here the prose is derived from the frontmatter, so the
// two cannot disagree by construction.
//
// Sorted, because the two lists are independent inputs and a footer ordered by however the
// config happened to list its tickets would churn the moment somebody reorders them.
func renderFooter(cfg *Config, spec ArtifactSpec) string {
	if cfg.RequiredFooter == "" {
		return ""
	}
	var b strings.Builder
	b.WriteString(cfg.RequiredFooter + "\n\n")
	tickets, _ := StringSlice(spec.Front["tickets"])
	sorted := append([]string(nil), tickets...)
	sort.Strings(sorted)
	for _, id := range sorted {
		if note := spec.TicketNotes[id]; note != "" {
			fmt.Fprintf(&b, "- %s — %s\n", id, note)
			continue
		}
		fmt.Fprintf(&b, "- %s\n", id)
	}
	return b.String()
}
