package main

// The writing half: render artifacts, normalise them, write them atomically, and verify.
//
// Three properties make generated docs survivable rather than a new source of churn, and all
// three are enforced here rather than left to each renderer:
//
//  1. NO VOLATILE CONTENT. No timestamps, commit SHAs or summary counts in banners. Both
//     pre-existing generators in this repo get that wrong (audit-grafana-dashboards.py writes
//     `Generated: <ISO now>`), which means every run produces a diff, which means the drift
//     gate built on it is noise from day one. Two consecutive runs here are byte-identical.
//
//  2. ONE NORMALISER, SHARED BY generate AND check. If generation and verification format
//     independently they will eventually disagree, and the gate starts failing on files it
//     just wrote. normalizeMarkdown is the single definition of "correct bytes".
//
//  3. WRITE ONLY IF CHANGED, ATOMICALLY. An unchanged artifact leaves the file untouched, so
//     mtime and `git status` stay clean. A changed one goes through a temp file in the SAME
//     directory and a rename, so an interrupted run can never leave a half-written doc.
//     "Unchanged" is decided from bytes actually read: a read that fails for any reason other
//     than "no such file" is an error, never a silent "treat it as absent and write anyway".
//
// The normaliser reimplements prettier's markdown table layout so generated output is a
// prettier FIXED POINT — running prettier over it changes nothing. That keeps generated files
// out of the repo's 611-file prettier backlog instead of adding to it. Equivalence is proven by
// a test that shells out to the real prettier when it is available.
//
// The fixed point holds for the constructs this generator emits, not for every construct a
// human could write; the exceptions are listed under "Known limitations" in README.md. Each is
// handled by declining to touch the block rather than by rewriting it into a shape prettier
// disagrees with, because an untouched block is merely unformatted while a disagreeing one
// oscillates between the two tools forever.

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"slices"
	"sort"
	"strings"
	"unicode"
)

// Artifact is one generated file, resolved from one `artifacts:` entry in config. Whole-file
// ownership only — the marker-region artifacts (INDEX.md and the section navs, which interleave
// generated tables with human prose) land separately, because mixing both ownership models in
// one file is how a generator deletes editorial work.
type Artifact struct {
	Name   string // the config key under `artifacts:`, used to name the key at fault
	Rel    string // repo-relative destination: docs_root + spec.path
	Spec   ArtifactSpec
	Render func(*Ctx) string
}

// renderers is the extension point: a renderer is Go, an artifact is config. Adding a generated
// document to a repo that already has a renderer for it costs a YAML stanza and no Go at all;
// adding a new KIND of document costs a function here plus that stanza.
var renderers = map[string]func(*Ctx, ArtifactSpec) string{
	"component-inventory": renderComponentInventory,
}

func rendererNames() []string {
	names := make([]string, 0, len(renderers))
	for n := range renderers {
		names = append(names, n)
	}
	sort.Strings(names)
	return names
}

// Artifacts resolves the configured artifact set.
//
// AN ABSENT `artifacts:` BLOCK YIELDS AN EMPTY SET, and that is the whole point. The previous
// version returned one hardcoded `docs/07-reference/component-inventory.md` regardless of
// config, so porting the tool meant editing Go and every port silently invented a `docs/` tree
// the host repo did not have. A default here would be that bug wearing a config key.
//
// Sorted by name so the result — and therefore `docsgen generate`'s output — does not depend on
// Go's randomised map iteration.
//
// Entries this cannot resolve are SKIPPED rather than guessed at; validateArtifacts turns each
// one into an exit-2 error naming the key, and Generate calls it first.
func Artifacts(cfg *Config) []Artifact {
	names := make([]string, 0, len(cfg.Artifacts))
	for n := range cfg.Artifacts {
		names = append(names, n)
	}
	sort.Strings(names)

	var out []Artifact
	for _, name := range names {
		spec := cfg.Artifacts[name]
		render, known := renderers[name]
		if !known || strings.TrimSpace(spec.Path) == "" {
			continue
		}
		out = append(out, Artifact{
			Name:   name,
			Rel:    path.Join(cfg.DocsRootOr(), spec.Path),
			Spec:   spec,
			Render: func(ctx *Ctx) string { return render(ctx, spec) },
		})
	}
	return out
}

// validateArtifacts reports every way the `artifacts:` block is unusable, in one pass.
//
// Every problem names the config key at fault, because the only actionable form of "this
// artifact is misconfigured" is the YAML path a human can go and edit. Reporting them all at
// once rather than stopping at the first matters for a block that is usually written in one
// sitting: fix-run-fix-run over five keys is five builds.
//
// What is NOT here is any defaulting. `type`, `status` and `freshness` have no fallback value;
// an artifact that omits one is caught by the pre-write gate against the repo's own schema rule.
func validateArtifacts(cfg *Config) error {
	names := make([]string, 0, len(cfg.Artifacts))
	for n := range cfg.Artifacts {
		names = append(names, n)
	}
	sort.Strings(names)

	var problems []string
	for _, name := range names {
		spec := cfg.Artifacts[name]
		key := "artifacts." + name
		if _, known := renderers[name]; !known {
			problems = append(problems, fmt.Sprintf(
				"%s: no renderer is named %q; this repo can generate %v", key, name, rendererNames()))
			continue
		}
		if strings.TrimSpace(spec.Path) == "" {
			problems = append(problems, key+".path: missing — an artifact with no path has nowhere to go")
			continue
		}
		// A path is joined onto docs_root and then onto the repo root. One that escapes either
		// would write outside the documentation tree, or outside the repository entirely.
		if clean := path.Clean(spec.Path); path.IsAbs(spec.Path) || clean == ".." ||
			strings.HasPrefix(clean, "../") {
			problems = append(problems, fmt.Sprintf(
				"%s.path: %q escapes the documentation root", key, spec.Path))
		}
		for _, e := range []struct {
			field   string
			allowed []string
		}{
			{"type", cfg.DocTypes},
			{"status", cfg.Statuses},
			{"freshness", cfg.Freshness},
		} {
			v, present := spec.Front[e.field]
			if !present {
				continue
			}
			s, isString := v.(string)
			if !isString {
				problems = append(problems, fmt.Sprintf(
					"%s.front.%s: must be one of %v, not a %T", key, e.field, e.allowed, v))
				continue
			}
			if len(e.allowed) > 0 && !slices.Contains(e.allowed, s) {
				problems = append(problems, fmt.Sprintf(
					"%s.front.%s: %q is not one of %v", key, e.field, s, e.allowed))
			}
		}
		// A note for a ticket the frontmatter does not list would render nowhere, and dead
		// config is indistinguishable from config that stopped working.
		tickets, _ := StringSlice(spec.Front["tickets"])
		noteIDs := make([]string, 0, len(spec.TicketNotes))
		for id := range spec.TicketNotes {
			noteIDs = append(noteIDs, id)
		}
		sort.Strings(noteIDs)
		for _, id := range noteIDs {
			if !slices.Contains(tickets, id) {
				problems = append(problems, fmt.Sprintf(
					"%s.ticket_notes.%s: not listed in %s.front.tickets, so the note renders nowhere",
					key, id, key))
			}
		}
		if _, err := renderFrontMatter(cfg, spec.Front); err != nil {
			problems = append(problems, fmt.Sprintf("%s.front.%v", key, err))
		}
	}
	if len(problems) == 0 {
		return nil
	}
	return errors.New("config:\n  " + strings.Join(problems, "\n  "))
}

// gate runs the artifact's own bytes through the repo's own frontmatter and taxonomy rules
// BEFORE anything is written, and refuses to write on any finding.
//
// This is what actually closes the defect, and it is strictly stronger than making the
// constants configurable. Configurable constants can still be configured wrong — a repo that
// sets `front.type: reference` against a vocabulary of [note spec howto log] gets the identical
// bug back, discovered whenever somebody happens to commit the artifact and run the linter.
// Checking in memory at generation time means the wrong value cannot reach the disk at all,
// whether or not the file is ever tracked, and whether or not anyone ever lints it.
//
// Severity is ignored on purpose. `warn` is a migration affordance for documents that PREDATE
// the taxonomy; a file this tool is writing right now has no history to be grandfathered for.
//
// Only the two rules that judge a document's own bytes are run. broken-links, colocation and
// covers-resolves need the surrounding repository, and the artifact is not on disk yet.
func gate(ctx *Ctx, a Artifact, content string) error {
	doc := MakeDoc(a.Rel, content)
	scratch := &Ctx{Root: ctx.Root, Cfg: ctx.Cfg, Docs: []Doc{doc}, BySlug: map[string]Component{}}
	findings := append(ruleFrontmatterSchema(scratch), ruleTaxonomyStructure(scratch)...)
	if len(findings) == 0 {
		return nil
	}
	lines := make([]string, 0, len(findings))
	for _, f := range findings {
		lines = append(lines, fmt.Sprintf("%s: %s [%s]", blameKey(ctx.Cfg, a, f.Message), f.Message, f.Rule))
	}
	sort.Strings(lines)
	return fmt.Errorf(
		"refusing to write %s — docsgen would be emitting a document its own ruleset rejects:\n  %s\n"+
			"fix the named config key(s), or the repo vocabulary they are checked against",
		a.Rel, strings.Join(lines, "\n  "))
}

// blameKey maps a finding back to the config key that produced it, so the error a human reads
// names something they can edit rather than a rule they cannot.
//
// A finding nothing can be blamed on lands on the artifact itself, which is the honest answer:
// "no H1" is a renderer bug, not a config one, and pretending otherwise would send the reader
// to edit YAML that is already correct.
func blameKey(cfg *Config, a Artifact, msg string) string {
	candidates := make([]string, 0, len(a.Spec.Front)+len(cfg.KeyOrder))
	for k := range a.Spec.Front {
		candidates = append(candidates, k)
	}
	candidates = append(candidates, cfg.KeyOrder...)
	candidates = append(candidates, "type", "status", "covers")
	for k := range cfg.BannedKeys {
		candidates = append(candidates, k)
	}
	sort.Strings(candidates)

	for _, k := range candidates {
		if strings.Contains(msg, "`"+k+"`") ||
			strings.HasPrefix(msg, k+" ") || strings.HasPrefix(msg, k+":") {
			return fmt.Sprintf("artifacts.%s.front.%s", a.Name, k)
		}
	}
	if cfg.RequiredFooter != "" && strings.Contains(msg, cfg.RequiredFooter) {
		return "required_footer + artifacts." + a.Name + ".front.tickets"
	}
	return "artifacts." + a.Name
}

type GenStatus string

const (
	StatusUnchanged GenStatus = "unchanged"
	StatusWritten   GenStatus = "written"
	StatusCreated   GenStatus = "created"
	StatusDrift     GenStatus = "drift"   // check mode: on-disk content differs
	StatusMissing   GenStatus = "missing" // check mode: never generated
)

type GenResult struct {
	Rel    string
	Status GenStatus
}

// Generate renders every artifact. In check mode nothing is written and any difference is
// reported, which is what makes `docsgen check` usable as a CI gate.
func Generate(ctx *Ctx, check bool) ([]GenResult, error) {
	if err := validateArtifacts(ctx.Cfg); err != nil {
		return nil, err
	}
	var out []GenResult
	for _, a := range Artifacts(ctx.Cfg) {
		content, err := normalizeMarkdownChecked(a.Render(ctx))
		if err != nil {
			return out, fmt.Errorf("%s: %w", a.Rel, err)
		}
		// Before the write, and before the comparison check mode makes: an artifact whose bytes
		// the repo's own rules reject is refused in BOTH modes. check writes nothing, so it
		// cannot emit the bad document — but it would otherwise report `unchanged` for a file
		// that is only unchanged because the same rejected bytes are already on disk.
		if err := gate(ctx, a, content); err != nil {
			return out, err
		}
		abs := filepath.Join(ctx.Root, a.Rel)

		// Only a genuine not-exist means "never generated". Treating every read failure as
		// absence made a mode-000 but byte-identical artifact report `missing` under check and
		// get REWRITTEN under generate — silently relaxing it to 0644 and breaking invariant 3.
		// A target that is a directory, or one whose parent is unwritable, misreported the same
		// way and then failed later with an error about the wrong thing.
		old, rerr := os.ReadFile(abs)
		absent := rerr != nil && errors.Is(rerr, fs.ErrNotExist)
		if rerr != nil && !absent {
			return out, fmt.Errorf("%s: reading the existing artifact: %w", a.Rel, rerr)
		}

		switch {
		case rerr == nil && string(old) == content:
			out = append(out, GenResult{a.Rel, StatusUnchanged})
		case check && absent:
			out = append(out, GenResult{a.Rel, StatusMissing})
		case check:
			out = append(out, GenResult{a.Rel, StatusDrift})
		default:
			status := StatusWritten
			if absent {
				status = StatusCreated
			}
			if werr := writeAtomic(abs, content); werr != nil {
				return out, fmt.Errorf("%s: %w", a.Rel, werr)
			}
			out = append(out, GenResult{a.Rel, status})
		}
	}
	return out, nil
}

// writeAtomic writes through a temp file in the TARGET directory, then renames. Same directory
// matters: a rename across filesystems is not atomic, so /tmp would silently lose the guarantee.
func writeAtomic(abs, content string) error {
	dir := filepath.Dir(abs)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(dir, ".docsgen-*.tmp")
	if err != nil {
		return err
	}
	name := tmp.Name()
	defer os.Remove(name) // no-op once the rename below succeeds
	if _, err := tmp.WriteString(content); err != nil {
		tmp.Close()
		return err
	}
	// Push the bytes to the device before the name starts pointing at them. This is NOT
	// durability: without also fsyncing the parent directory the rename itself can still be
	// lost to power failure, and claiming otherwise would be worse than not syncing. What it
	// does buy is the failure mode — "the old doc, or the new doc", never "the new name over a
	// zero-length file", which is the one state a regenerable artifact cannot be told apart
	// from a legitimately empty one.
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Chmod(name, 0o644); err != nil { // CreateTemp makes 0600
		return err
	}
	return os.Rename(name, abs)
}

// --- normalisation ----------------------------------------------------------------------

var tableLineRe = regexp.MustCompile(`^\s*\|.*\|\s*$`)
var sepCellRe = regexp.MustCompile(`^:?-{1,}:?$`)

// ASCII-only by design: NBSP and the other Unicode spaces are content to prettier, and
// collapsing them would change bytes it intends to keep.
var innerSpaceRe = regexp.MustCompile(`[\t\n\f\r ]+`)

// normalizeMarkdown produces the canonical bytes for a generated file: LF endings, no trailing
// whitespace, exactly one trailing newline, and prettier-formatted tables.
//
// It drops the refusal that normalizeMarkdownChecked reports, because the callers that want
// bytes alone — the layout tests — have nothing to do with it. Generate uses the checked form;
// refusing to write is the only place the distinction buys anything.
func normalizeMarkdown(s string) string {
	out, _ := normalizeMarkdownChecked(s)
	return out
}

// normalizeMarkdownChecked is normalizeMarkdown plus the refusal described on unstableWidth: a
// document holding a cell whose width prettier computes inconsistently is an error, not
// something to render best-effort and hope about.
func normalizeMarkdownChecked(s string) (string, error) {
	s = strings.ReplaceAll(s, "\r\n", "\n")
	lines := strings.Split(s, "\n")
	for i := range lines {
		lines[i] = strings.TrimRight(lines[i], " \t")
	}
	formatted, err := formatTablesChecked(lines)
	if err != nil {
		return "", err
	}
	body := strings.TrimRight(strings.Join(formatted, "\n"), "\n")
	if body == "" {
		// An empty document stays empty. The unconditional `+ "\n"` tail turned "" into "\n",
		// which prettier deletes again on sight — a one-byte file the two tools can never agree
		// on, and the only shape `docsgen check` can report drift on with nothing to show.
		return "", nil
	}
	return body + "\n", nil
}

// fence tracks fenced-code-block state across a line scan. Without it, a markdown table shown
// as an EXAMPLE inside a fence is reformatted as though it were real content. That damage hides
// from a fixed-point test — prettier leaves fences alone, so both sides are individually stable
// — and only a norm(x) vs prettier(x) comparison exposes it. The worst case is a fence inside a
// list item, where the rewrite also flattened the indent and tore the block out of its list.
type fence struct {
	open  bool
	char  byte
	count int
}

// delim reports whether line is a fence delimiter, updating state. Indentation is deliberately
// ignored when detecting one: over-detecting a fence only suppresses table formatting, while
// under-detecting one resumes rewriting code, so the conservative error is the safe one.
func (f *fence) delim(line string) bool {
	t := strings.TrimLeft(line, " \t")
	var c byte
	switch {
	case strings.HasPrefix(t, "```"):
		c = '`'
	case strings.HasPrefix(t, "~~~"):
		c = '~'
	default:
		return false
	}
	n := 0
	for n < len(t) && t[n] == c {
		n++
	}
	if !f.open {
		f.open, f.char, f.count = true, c, n
		return true
	}
	// A closer repeats the OPENER's character at least as many times and carries no info
	// string. Both halves earn their keep: ```` wrapping an inner ``` would otherwise close
	// three lines early, and a ```go line inside a plain fence would close it immediately.
	if c != f.char || n < f.count || strings.TrimRight(t[n:], " \t") != "" {
		return false
	}
	f.open = false
	return true
}

// formatTables rewrites every GFM table in the line slice to prettier's layout. Lines that are
// not part of a table pass through untouched.
func formatTables(lines []string) []string {
	out, _ := formatTablesChecked(lines)
	return out
}

func formatTablesChecked(lines []string) ([]string, error) {
	out := make([]string, 0, len(lines))
	var firstErr error
	var f fence
	for i := 0; i < len(lines); {
		if f.delim(lines[i]) || f.open || !startsTable(lines, i) {
			out = append(out, lines[i])
			i++
			continue
		}
		j := i
		for j < len(lines) && tableLineRe.MatchString(lines[j]) && indentColumns(lines[j]) < 4 {
			j++
		}
		rendered, err := renderTable(lines[i:j])
		if err != nil && firstErr == nil {
			firstErr = err
		}
		// Appended even on error: the caller that discards the error still needs a complete
		// slice back, and every row but the offending cell is correct.
		out = append(out, rendered...)
		i = j
	}
	return out, firstErr
}

// startsTable wants a header row followed by a separator row, neither indented into a code
// block. Four columns of indent IS an indented code block in markdown, so reformatting one
// changes what the reader sees rather than how it is laid out. That rule also declines tables
// nested two list levels deep, which is the price of not having a block parser here.
func startsTable(lines []string, i int) bool {
	return tableLineRe.MatchString(lines[i]) && indentColumns(lines[i]) < 4 &&
		i+1 < len(lines) && isSeparatorRow(lines[i+1]) && indentColumns(lines[i+1]) < 4
}

// indentColumns measures leading whitespace in columns, a tab advancing to the next multiple of
// four, which is how markdown itself decides where an indented code block begins.
func indentColumns(line string) int {
	n := 0
	for _, r := range line {
		switch r {
		case ' ':
			n++
		case '\t':
			n += 4 - n%4
		default:
			return n
		}
	}
	return n
}

func leadingWhitespace(line string) string {
	return line[:len(line)-len(strings.TrimLeft(line, " \t"))]
}

func isSeparatorRow(line string) bool {
	if !tableLineRe.MatchString(line) {
		return false
	}
	cells := splitRow(line)
	if len(cells) == 0 {
		return false
	}
	for _, c := range cells {
		if !sepCellRe.MatchString(strings.TrimSpace(c)) {
			return false
		}
	}
	return true
}

// splitRow splits a table row on unescaped pipes. `\|` inside a cell is content, not a
// delimiter — getting this wrong silently shreds any row containing a pipe.
//
// Runs of whitespace INSIDE a cell collapse to one space because prettier does the same. A tab
// or a double space left standing is both a diff prettier will make and, since it changes the
// cell's measured width, a column width prettier will disagree with on the same pass.
func splitRow(line string) []string {
	s := strings.TrimSpace(line)
	s = strings.TrimSuffix(strings.TrimPrefix(s, "|"), "|")

	var cells []string
	var cur strings.Builder
	escaped := false
	flush := func() {
		cells = append(cells, innerSpaceRe.ReplaceAllString(strings.TrimSpace(cur.String()), " "))
		cur.Reset()
	}
	for _, r := range s {
		switch {
		case escaped:
			cur.WriteRune(r)
			escaped = false
		case r == '\\':
			cur.WriteRune(r)
			escaped = true
		case r == '|':
			flush()
		default:
			cur.WriteRune(r)
		}
	}
	flush()
	return cells
}

type align int

const (
	alignDefault align = iota
	alignLeft
	alignRight
	alignCenter
)

// renderTable lays out one table block. It returns its rows even alongside an error, so a
// caller that only wants bytes still gets a complete document back.
//
// The block's own indent is preserved: tableLineRe accepts a leading indent, so a table nested
// in a list item reaches here, and emitting it at column zero lifts it out of the list item and
// destroys the surrounding document. A block whose rows disagree about their indent is left
// untouched, because there is no single indent that could be correct for all of them.
func renderTable(rows []string) ([]string, error) {
	indent := leadingWhitespace(rows[0])
	for _, r := range rows {
		if leadingWhitespace(r) != indent {
			return append([]string(nil), rows...), nil
		}
	}

	parsed := make([][]string, len(rows))
	width := 0
	for i, r := range rows {
		parsed[i] = splitRow(r)
		if len(parsed[i]) > width {
			width = len(parsed[i])
		}
	}

	aligns := make([]align, width)
	for c, cell := range parsed[1] {
		left := strings.HasPrefix(cell, ":")
		right := strings.HasSuffix(cell, ":")
		switch {
		case left && right:
			aligns[c] = alignCenter
		case left:
			aligns[c] = alignLeft
		case right:
			aligns[c] = alignRight
		}
	}

	// Column width is the widest cell, floored at 3 so the separator row always has room for
	// `---`. Measured in DISPLAY columns, not bytes: prettier measures the same way, and an em
	// dash (3 bytes, 1 column) had this padding to 24 where prettier pads to 22 — after which
	// `task dev:lint:prettier` and `task docs:check` rewrite the file past each other forever.
	widths := make([]int, width)
	for c := range widths {
		widths[c] = 3
		for r := range parsed {
			if r == 1 || c >= len(parsed[r]) {
				continue // the separator is generated, not measured; a short row has no cell here
			}
			if n := displayWidth(parsed[r][c]); n > widths[c] {
				widths[c] = n
			}
		}
	}

	var unstable error
	out := make([]string, 0, len(rows))
	for r := range parsed {
		// A ragged row keeps its OWN cell count. Widening it to the widest row invents header
		// and separator columns nobody wrote; prettier pads such a row to the shared column
		// widths but never grows it a cell.
		cells := make([]string, len(parsed[r]))
		for c := range cells {
			if r == 1 {
				cells[c] = separatorCell(widths[c], aligns[c])
				continue
			}
			if unstable == nil {
				if bad := unstableWidth(parsed[r][c]); bad != 0 {
					unstable = fmt.Errorf(
						"table cell %q contains %U, whose display width prettier computes "+
							"inconsistently; refusing to emit a table prettier would repad on "+
							"every run", parsed[r][c], bad)
				}
			}
			cells[c] = padCell(parsed[r][c], widths[c], aligns[c])
		}
		out = append(out, indent+"| "+strings.Join(cells, " | ")+" |")
	}
	return out, unstable
}

func separatorCell(w int, a align) string {
	switch a {
	case alignLeft:
		return ":" + strings.Repeat("-", w-1)
	case alignRight:
		return strings.Repeat("-", w-1) + ":"
	case alignCenter:
		return ":" + strings.Repeat("-", w-2) + ":"
	}
	return strings.Repeat("-", w)
}

// padCell matches prettier exactly, including that a centred cell sends the odd space RIGHT.
func padCell(s string, w int, a align) string {
	pad := w - displayWidth(s)
	if pad < 0 {
		pad = 0
	}
	switch a {
	case alignRight:
		return strings.Repeat(" ", pad) + s
	case alignCenter:
		l := pad / 2
		return strings.Repeat(" ", l) + s + strings.Repeat(" ", pad-l)
	}
	return s + strings.Repeat(" ", pad)
}

// --- display width ----------------------------------------------------------------------

// unstableWidth returns the first rune in s whose contribution to prettier's width depends on
// the runes around it, or 0 when there is none.
//
// Prettier measures a cell with a grapheme-aware width library, so U+FE0F turns a one-column
// heart into a two-column emoji and a ZWJ collapses five code points into one two-column glyph.
// Matching that needs the emoji sequence tables, and even with them prettier's answer moves as
// those tables are revised. Measured against 3.9.6: a lone ZWJ, ZWNJ, ZWSP or BOM counts ONE
// column there, while the "zero-width means zero columns" model below counts none — so those
// four are refused too, not just the sequences they appear in.
//
// Refusing is the only safe answer. A wrong guess is not cosmetic: it is a file prettier repads
// and docsgen pads back, forever, with two CI gates taking turns failing. A hard error names
// the cell and a human rewrites it; an oscillating artifact has no such exit.
func unstableWidth(s string) rune {
	for _, r := range s {
		if r == 0x200B || r == 0x200C || r == 0x200D || r == 0xFEFF ||
			(r >= 0xFE00 && r <= 0xFE0F) {
			return r
		}
	}
	return 0
}

// displayWidth is the column count prettier lays a string out in: combining marks and
// zero-width code points add nothing, East Asian Wide and Fullwidth characters take two
// columns, everything else takes one. For anything outside ASCII that is not len(), and the
// table layout above is built on the difference.
func displayWidth(s string) int {
	w := 0
	for _, r := range s {
		switch {
		case r == 0x200B, r == 0x200C, r == 0x200D, r == 0xFEFF:
			// Zero width by name. renderTable never reaches this arm — unstableWidth rejects
			// the cell first — but a width function that reported 1 here would be a trap laid
			// for the next caller.
		case unicode.In(r, unicode.Mn, unicode.Me):
			// Combining marks (variation selectors among them) hang off the preceding glyph.
			// This is what makes NFD "e"+U+0301 one column wide rather than two.
		case wide(r):
			w += 2
		default:
			w++
		}
	}
	return w
}

// eastAsianWide is the Wide and Fullwidth ranges of UAX #11, coalesced across the unassigned
// gaps inside CJK blocks — those default to Wide anyway — to keep the table short enough that a
// human can check it. Sorted and non-overlapping, which is what the binary search below needs.
var eastAsianWide = [][2]rune{
	{0x1100, 0x115F}, {0x231A, 0x231B}, {0x2329, 0x232A}, {0x23E9, 0x23EC},
	{0x23F0, 0x23F0}, {0x23F3, 0x23F3}, {0x25FD, 0x25FE}, {0x2614, 0x2615},
	{0x2648, 0x2653}, {0x267F, 0x267F}, {0x2693, 0x2693}, {0x26A1, 0x26A1},
	{0x26AA, 0x26AB}, {0x26BD, 0x26BE}, {0x26C4, 0x26C5}, {0x26CE, 0x26CE},
	{0x26D4, 0x26D4}, {0x26EA, 0x26EA}, {0x26F2, 0x26F3}, {0x26F5, 0x26F5},
	{0x26FA, 0x26FA}, {0x26FD, 0x26FD}, {0x2705, 0x2705}, {0x270A, 0x270B},
	{0x2728, 0x2728}, {0x274C, 0x274C}, {0x274E, 0x274E}, {0x2753, 0x2755},
	{0x2757, 0x2757}, {0x2795, 0x2797}, {0x27B0, 0x27B0}, {0x27BF, 0x27BF},
	{0x2B1B, 0x2B1C}, {0x2B50, 0x2B50}, {0x2B55, 0x2B55}, {0x2E80, 0x303E},
	{0x3041, 0x33FF}, {0x3400, 0x4DBF}, {0x4E00, 0xA4CF}, {0xA960, 0xA97F},
	{0xAC00, 0xD7A3}, {0xF900, 0xFAFF}, {0xFE10, 0xFE19}, {0xFE30, 0xFE52},
	{0xFE54, 0xFE66}, {0xFE68, 0xFE6B}, {0xFF01, 0xFF60}, {0xFFE0, 0xFFE6},
	{0x16FE0, 0x16FE4}, {0x16FF0, 0x16FF1}, {0x17000, 0x187F7},
	{0x18800, 0x18CD5}, {0x18D00, 0x18D08}, {0x1AFF0, 0x1AFFE},
	{0x1B000, 0x1B152}, {0x1B164, 0x1B167}, {0x1B170, 0x1B2FB},
	{0x1F004, 0x1F004}, {0x1F0CF, 0x1F0CF}, {0x1F18E, 0x1F18E},
	{0x1F191, 0x1F19A}, {0x1F200, 0x1F320}, {0x1F32D, 0x1F335},
	{0x1F337, 0x1F37C}, {0x1F37E, 0x1F393}, {0x1F3A0, 0x1F3CA},
	{0x1F3CF, 0x1F3D3}, {0x1F3E0, 0x1F3F0}, {0x1F3F4, 0x1F3F4},
	{0x1F3F8, 0x1F43E}, {0x1F440, 0x1F440}, {0x1F442, 0x1F4FC},
	{0x1F4FF, 0x1F53D}, {0x1F54B, 0x1F54E}, {0x1F550, 0x1F567},
	{0x1F57A, 0x1F57A}, {0x1F595, 0x1F596}, {0x1F5A4, 0x1F5A4},
	{0x1F5FB, 0x1F64F}, {0x1F680, 0x1F6C5}, {0x1F6CC, 0x1F6CC},
	{0x1F6D0, 0x1F6D2}, {0x1F6D5, 0x1F6D7}, {0x1F6DC, 0x1F6DF},
	{0x1F6EB, 0x1F6EC}, {0x1F6F4, 0x1F6FC}, {0x1F7E0, 0x1F7EB},
	{0x1F7F0, 0x1F7F0}, {0x1F90C, 0x1F93A}, {0x1F93C, 0x1F945},
	{0x1F947, 0x1F9FF}, {0x1FA70, 0x1FA7C}, {0x1FA80, 0x1FA89},
	{0x1FA8F, 0x1FAC6}, {0x1FACE, 0x1FADC}, {0x1FADF, 0x1FAE9},
	{0x1FAF0, 0x1FAF8}, {0x20000, 0x2FFFD}, {0x30000, 0x3FFFD},
}

func wide(r rune) bool {
	i := sort.Search(len(eastAsianWide), func(i int) bool { return eastAsianWide[i][1] >= r })
	return i < len(eastAsianWide) && r >= eastAsianWide[i][0]
}
