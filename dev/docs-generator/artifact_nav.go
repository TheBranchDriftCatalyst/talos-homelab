package main

// The navigation-table artifact: the link tables in INDEX.md and the section READMEs.
//
// WHY THIS IS GENERATED AT ALL. A hand-written link table is the one kind of documentation that
// is guaranteed to rot, because it is a claim about the tree rather than about the world: every
// row asserts "this file exists and is worth reading", and nothing revalidates that when a file
// moves or is deleted. When `docs/_archive/` was removed from this repo, 58 rows across these
// nine files kept pointing at documents that no longer existed anywhere — not moved, DELETED,
// so there was nothing to repoint them at. Rows derived from the tree cannot reach that state:
// a deleted file stops producing a row.
//
// WHY THE DESCRIPTION COMES FROM `bluf:` (or whatever the host repo calls it). The obvious
// alternative — generate the description too — throws away the curated one-liners that are the
// only reason anybody reads a nav table instead of `ls`. The obvious other alternative — leave
// the description column alone and regenerate only the links — cannot be done, because a table
// row is one line. Reading the description out of the TARGET's own frontmatter keeps the
// curation, moves it next to the thing it describes, and makes it survive regeneration; the
// key name is config, never a constant here, for the same reason every other vocabulary term is.
//
// WHY IT WRITES A MARKER REGION. These files carry real editorial prose. See region.go.

import (
	"fmt"
	"path"
	"sort"
	"strings"
)

// The two nav entry kinds. `entries:` is validated against this list by name, so a typo is a
// config error rather than a table that silently renders nothing.
const (
	// navSiblings lists the markdown documents sitting directly in a directory: the files a
	// section README indexes.
	navSiblings = "siblings"
	// navSections lists the subdirectories of a directory that carry a README.md: the sections
	// an INDEX indexes.
	navSections = "sections"
)

func navEntryKinds() []string { return []string{navSections, navSiblings} }

// navRow is one rendered line. Target is the repo-relative path of the document being linked
// and is also THE SORT KEY — see renderNav.
type navRow struct {
	Target string
	Text   string
	Href   string
	Desc   string
}

// navDir returns the directory an artifact's nav enumerates: its `nav.dir` when it declares
// one, and the directory the artifact itself lives in otherwise.
//
// The default is what makes the common case declaration-free: a section README indexes its own
// section, and repeating the path in config is one more thing that can disagree with reality.
func navDir(cfg *Config, spec ArtifactSpec) string {
	if spec.Nav != nil {
		if d := strings.Trim(strings.TrimSpace(spec.Nav.Dir), "/"); d != "" {
			return d
		}
	}
	return path.Dir(path.Join(cfg.RootFor(spec), spec.Path))
}

// navSelf returns the repo-relative path of the artifact itself, so a nav never lists itself.
func navSelf(cfg *Config, spec ArtifactSpec) string {
	return path.Join(cfg.RootFor(spec), spec.Path)
}

// navRows collects the rows an artifact's nav table describes, from the DOCUMENT CORPUS rather
// than from the filesystem.
//
// ctx.Docs is `git ls-files` filtered by the repo's `exclude:` patterns, which is what makes
// the rows honest in two ways a filesystem walk is not: an untracked scratch file never
// appears, and a directory the repo deliberately excludes (this one excludes `docs/_archive/**`
// and the integration fixtures) never leaks into a published index.
func navRows(ctx *Ctx, spec ArtifactSpec) []navRow {
	cfg := ctx.Cfg
	dir := navDir(cfg, spec)
	self := navSelf(cfg, spec)
	from := path.Dir(self)
	descKey := ""
	kind := ""
	if spec.Nav != nil {
		descKey = strings.TrimSpace(spec.Nav.DescriptionKey)
		kind = strings.TrimSpace(spec.Nav.Entries)
	}

	var rows []navRow
	for _, d := range ctx.Docs {
		if d.Path == self {
			continue // a nav that lists itself is a loop, not an entry
		}
		if !strings.HasPrefix(d.Path, dir+"/") {
			continue
		}
		rel := strings.TrimPrefix(d.Path, dir+"/")
		base := path.Base(rel)

		var text string
		switch kind {
		case navSiblings:
			if strings.Contains(rel, "/") {
				continue // direct children only; a subdirectory is a section, not a sibling
			}
			// A section's README is its own nav. It is indexed by the PARENT's sections table,
			// where it stands for the whole section — listing it here as well would give the
			// same document two homes with two different meanings.
			if base == "README.md" {
				continue
			}
			text = base
		case navSections:
			// `<subdir>/README.md` and nothing else: the README is the section's front door,
			// and a sections table that also listed the section's contents would be the INDEX
			// duplicating every README below it.
			if base != "README.md" || strings.Count(rel, "/") != 1 {
				continue
			}
			text = path.Dir(rel)
		default:
			continue
		}

		// A superseded document with no successor is a dead end: it says "do not trust me" and
		// offers nowhere to go. One that names its `superseded_by` is still worth an entry,
		// because following it is how a reader lands on the replacement.
		if status, _ := d.Front["status"].(string); status == "superseded" {
			if by, ok := d.Front["superseded_by"].(string); !ok || strings.TrimSpace(by) == "" {
				continue
			}
		}

		rows = append(rows, navRow{
			Target: d.Path,
			Text:   text,
			Href:   relHref(from, d.Path),
			Desc:   navDescription(d, descKey),
		})
	}

	// SORTED BY REPO-RELATIVE TARGET PATH, bytewise ascending. Documented because a generated
	// order nobody can predict is a generated order nobody can review: `01-getting-started`
	// before `02-architecture` before `patterns` is a property of the path, so the numeric
	// prefixes this repo uses keep working and a repo without them still gets a stable answer.
	// The target path is TOTAL — two rows cannot share one — which `Text` is not: two
	// directories can both contribute a `README.md`.
	sort.Slice(rows, func(i, j int) bool { return rows[i].Target < rows[j].Target })
	return rows
}

// navDescription is the row's second column: the target's own `bluf:` (or whatever the host
// repo names it), falling back to its H1.
//
// The fallback is deliberately visible rather than blank. A blank cell reads as "this document
// has nothing to say", when it means "nobody has written its one-liner yet" — and the H1 is
// already the closest thing to one the document has. `docsgen frontmatter` is the worklist for
// turning the fallbacks into real answers.
func navDescription(d Doc, key string) string {
	if key != "" {
		if s, ok := d.Front[key].(string); ok && strings.TrimSpace(s) != "" {
			return tableCell(s)
		}
	}
	if d.H1 != "" {
		return tableCell(d.H1)
	}
	// Neither a one-liner nor a heading. An em dash, because an empty cell is indistinguishable
	// from a rendering bug and a reader cannot tell which one they are looking at.
	return "—"
}

// tableCell makes a string safe to put in a GFM table cell.
//
// An unescaped pipe splits the row, which silently shifts every later cell one column left —
// the kind of damage that looks like a formatting glitch and is actually a wrong answer in the
// wrong column. Whitespace is collapsed because the normaliser collapses it anyway (prettier
// does), and a cell whose width is measured before that collapse gets a column width prettier
// disagrees with.
func tableCell(s string) string {
	s = strings.Join(strings.Fields(s), " ")
	return strings.ReplaceAll(s, "|", `\|`)
}

// relHref renders `to` as a link relative to directory `from`.
//
// Hand-rolled rather than filepath.Rel: link targets are URL paths and must use forward slashes
// on every platform, and filepath.Rel would hand back backslashes on Windows — a link that is
// broken everywhere except the machine that generated it.
func relHref(from, to string) string {
	fromParts := strings.Split(strings.Trim(from, "/"), "/")
	toParts := strings.Split(strings.Trim(to, "/"), "/")
	if from == "" || from == "." {
		fromParts = nil
	}
	i := 0
	for i < len(fromParts) && i < len(toParts)-1 && fromParts[i] == toParts[i] {
		i++
	}
	var out []string
	for range fromParts[i:] {
		out = append(out, "..")
	}
	out = append(out, toParts[i:]...)
	return strings.Join(out, "/")
}

// renderNav renders the table. Bytes in, bytes out — writing, normalisation, marker location
// and the byte-identical guarantee all belong to Generate, exactly as they do for the
// whole-file artifacts.
//
// The COLUMNS are Go and the VALUES are the repo's. That split is the same one artifact_
// inventory.go draws: the shape of a nav table is a property of what a nav table is, while
// every string a reader sees comes out of the documents themselves.
func renderNav(ctx *Ctx, spec ArtifactSpec) string {
	rows := navRows(ctx, spec)
	var b strings.Builder
	// Cells are padded to BYTE-equivalent display width by the normaliser, so the header must
	// stay ASCII for the same reason the inventory's does.
	b.WriteString("| Doc | What it covers |\n")
	b.WriteString("| --- | --- |\n")
	for _, r := range rows {
		fmt.Fprintf(&b, "| [%s](%s) | %s |\n", r.Text, r.Href, r.Desc)
	}
	return b.String()
}
