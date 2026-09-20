// Command docsgen lints and (later) generates repository documentation.
//
// READ AND WRITE. `lint` and the report commands never touch the repository; `generate` writes
// the artifacts and `check` verifies them without writing.
//
// TWO OWNERSHIP MODELS, never mixed in one file. A whole-file artifact owns its destination end
// to end. A marker-owned one (`region:` in config) writes only the span between its markers and
// copies every other byte through untouched — which is what lets the nav tables in INDEX.md and
// the section READMEs be generated at all, since those files also carry editorial prose no
// generator can reproduce. A marker-owned file whose markers are missing, unbalanced or nested
// is a hard error naming the file; see region.go.
//
// WHY THIS EXISTS. Docs are the only projection of a codebase that nothing keeps honest: code
// graphs are reindexed, session logs are derived from git, decision records are superseded
// rather than edited. A hand-written doc has no regeneration path and no verification step, so
// nothing ever forces it back into agreement with the code. This is that verification step.
//
// PORTABILITY. Everything repo-specific lives in config.yaml beside the binary. Copy
// dev/docs-generator/ into another repo, edit the YAML, and it works — no Go changes.
package main

import (
	"flag"
	"fmt"
	"os"
	"path"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
)

const usage = `docsgen — documentation linter

usage: docsgen <command> [flags]

commands:
  generate     write the generated artifacts
  check        verify generated artifacts are current (writes nothing)
  lint         run every enabled rule
  links        broken links only
  components   component inventory (slug, README presence, shape)
  frontmatter  docs with no frontmatter — the migration worklist
  stale        docs older than the code they describe

flags:
  -root   repo root (default: git rev-parse --show-toplevel)
  -config directory holding config.yaml (default: alongside this source)
  -rule   run a single rule by name
  -all    print every finding instead of the first 20 per rule
`

func main() {
	if len(os.Args) < 2 {
		fmt.Fprint(os.Stderr, usage)
		os.Exit(2)
	}
	cmd := os.Args[1]
	fs := flag.NewFlagSet(cmd, flag.ExitOnError)
	root := fs.String("root", "", "repo root")
	confDir := fs.String("config", "", "directory holding config.yaml")
	rule := fs.String("rule", "", "run a single rule")
	propose := fs.Bool("propose", false, "claims: print assertion-shaped prose not yet recorded as a claim")
	all := fs.Bool("all", false, "print every finding instead of the first 20 per rule")
	_ = fs.Parse(os.Args[2:])

	if *root == "" {
		wd, _ := os.Getwd()
		*root = RepoRoot(wd)
	}
	if *confDir == "" {
		*confDir = defaultConfigDir(*root)
	}

	cfg, err := LoadConfig(*confDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "config: %v\n", err)
		os.Exit(2)
	}
	ctx := Build(*root, cfg)

	switch cmd {
	case "generate":
		os.Exit(reportGenerate(ctx, false))
	case "check":
		os.Exit(reportGenerate(ctx, true))
	case "lint":
		os.Exit(reportLint(ctx, *rule, *all))
	case "links":
		os.Exit(reportLint(ctx, "broken-links", *all))
	case "components":
		os.Exit(reportComponents(ctx))
	case "frontmatter":
		os.Exit(reportFrontmatter(ctx))
	case "stale":
		os.Exit(reportStale(ctx))
	case "claims":
		os.Exit(reportClaims(ctx, *propose, *all))
	case "extract":
		// os.Args[2:] is what fs parsed, so the document is Arg(0) — the subcommand was
		// already consumed at os.Args[1] and never reaches the flag set.
		if fs.NArg() < 1 {
			fmt.Fprintln(os.Stderr, "extract needs a document path")
			os.Exit(2)
		}
		os.Exit(reportExtract(ctx, fs.Arg(0), *all))
	default:
		fmt.Fprint(os.Stderr, usage)
		os.Exit(2)
	}
}

// defaultConfigDir finds config.yaml relative to this source file when run via `go run`, and
// falls back to the conventional location so a prebuilt binary works from anywhere in the repo.
func defaultConfigDir(root string) string {
	if _, file, _, ok := runtime.Caller(0); ok {
		if dir := filepath.Dir(file); fileExists(filepath.Join(dir, "config.yaml")) {
			return dir
		}
	}
	return filepath.Join(root, "dev", "docs-generator")
}

func fileExists(p string) bool {
	_, err := os.Stat(p)
	return err == nil
}

// skipRuleWidth pads the rule name in a `skipped` line so the reasons line up.
//
// FIXED, not computed from the skipped set: a width that shrank when one rule started running
// again would rewrite every other skip line, turning a one-line change into a whole-block diff
// in output whose whole job is being diffable.
const skipRuleWidth = 15

// lintTruncateAt caps how many findings each rule prints by DEFAULT.
//
// The cap exists because the first thing a fresh adoption produces is a wall — this repo's own
// broken-links rule was 154 findings on day one — and a report nobody can read is a report
// nobody runs. The cap is also how a rule with 120 findings became untriageable: you cannot act
// on what the tool will not print. `-all` is the escape hatch, and it is a FLAG rather than a
// new default because both failure modes are real and only the operator knows which one they
// are in.
const lintTruncateAt = 20

// reportLint prints the findings, grouped by rule.
//
// `all` lifts the per-rule cap. It must lift it COMPLETELY: a flag that raised the ceiling to
// some larger number would reintroduce the same defect at a different scale, and — worse — the
// `... and N more` line would still be there to say so in a mode whose whole promise is that
// nothing was withheld.
func reportLint(ctx *Ctx, only string, all bool) int {
	findings, skipped := Run(ctx, only)
	byRule := map[string][]Finding{}
	for _, f := range findings {
		byRule[f.Rule] = append(byRule[f.Rule], f)
	}
	names := make([]string, 0, len(byRule))
	for n := range byRule {
		names = append(names, n)
	}
	sort.Strings(names)

	errors := 0
	for _, n := range names {
		items := byRule[n]
		sev := "warn"
		for _, i := range items {
			if i.Severity == "error" {
				sev = "error"
			}
		}
		if sev == "error" {
			errors += len(items)
		}
		fmt.Printf("\n%s  [%s]  %d finding(s)\n", n, sev, len(items))
		sort.Slice(items, func(i, j int) bool { return items[i].Path < items[j].Path })
		shown := items
		if !all && len(shown) > lintTruncateAt {
			shown = shown[:lintTruncateAt]
		}
		for _, f := range shown {
			fmt.Printf("  %s: %s\n", f.Path, f.Message)
		}
		// The elision notice is derived from what was ACTUALLY withheld, never from a second
		// comparison against the cap. Deriving it independently is how `-all` would end up
		// printing every finding and then claiming some were hidden.
		if hidden := len(items) - len(shown); hidden > 0 {
			fmt.Printf("  ... and %d more (re-run with -all to see every finding)\n", hidden)
		}
	}
	// Skips go to STDOUT, with the report, because a rule that could not run is part of the
	// lint ANSWER and not a diagnostic about the run. On stderr it would be invisible to
	// `docsgen lint | tee report.txt` and to every CI log that keeps only stdout — which is
	// exactly where somebody reads "no component-shape findings" and concludes they are covered.
	//
	// The leading token is `skipped`, deliberately NOT the `<rule>  [skipped]` shape the rule
	// blocks above use. That shape is indistinguishable from a rule block to anything parsing
	// this output by rule name — the integration harness's own findingsFor matches `rule + "  ["`
	// — so a spec asserting "no component-shape findings" would pass identically whether the
	// rule ran clean or never ran at all. That ambiguity IS the defect being removed here; it
	// must not be reintroduced by the format that announces its removal.
	if len(skipped) > 0 {
		fmt.Println()
		for _, s := range skipped {
			fmt.Printf("skipped  %-*s  %s\n", skipRuleWidth, s.Rule, s.Why)
		}
	}
	// The summary line's bytes are unchanged, and must stay that way: it is the line CI gates
	// and specs grep for. The skip count is APPENDED as its own line rather than folded into
	// it, so a skip can never be mistaken for a finding or move a count somebody is asserting
	// on.
	fmt.Printf("\n%d finding(s): %d error, %d warn\n", len(findings), errors, len(findings)-errors)
	if len(skipped) > 0 {
		fmt.Printf("%d rule(s) could not run — see the `skipped` lines above\n", len(skipped))
	}
	// Skips contribute ZERO to the exit code. A repo whose strategy is narrower than Flux's
	// must be able to adopt this tool without landing red on day one, or it simply will not
	// adopt it — and a red gate nobody can turn green teaches people to pass -k. The report
	// says what could not be measured; the exit code stays a statement about defects found.
	if errors > 0 {
		return 1
	}
	return 0
}

func reportComponents(ctx *Ctx) int {
	fmt.Printf("%-32s %-7s %-8s %-7s %s\n", "slug", "readme", "nested", "suspend", "path")
	withReadme := 0
	// Sort a COPY on a TOTAL key. Sorting ctx.Components in place mutated the model every other
	// consumer reads, and slug alone is not a total order once two components can share one, so
	// equal-slug rows could swap between runs of a command whose whole job is being diffable.
	comps := append([]Component(nil), ctx.Components...)
	sort.Slice(comps, func(i, j int) bool {
		if comps[i].Slug != comps[j].Slug {
			return comps[i].Slug < comps[j].Slug
		}
		return comps[i].Path < comps[j].Path
	})
	for _, c := range comps {
		readme := "-"
		if ctx.HasDoc(path.Join(c.Path, "README.md")) {
			readme = "yes"
			withReadme++
		}
		// FIXED COLUMNS, with `n/a` where the strategy cannot supply the measurement — never a
		// dropped column and never a zero.
		//
		// A zero is the worse of the two failures: `nested 0` and `nested n/a` are different
		// claims — "this component wraps no sub-units" versus "this repo shape cannot count
		// sub-units" — and printing the first for the second is the same lie the silent rule
		// told. Dropping the column instead would keep the honesty and lose the arity, which
		// breaks every positional reader of this report; a spec filtering rows on field count
		// would then see zero rows and pass vacuously.
		fmt.Printf("%-32s %-7s %-8s %-7s %s\n",
			c.Slug, readme, factCell(ctx, FactSubUnits, strconv.Itoa(c.Nested)),
			factCell(ctx, FactInactive, suspendCell(c)), c.Path)
	}
	fmt.Printf("\n%d components, %d with a README (%d without)\n",
		len(comps), withReadme, len(comps)-withReadme)
	return 0
}

// factCell renders a measurement, or `n/a` when the strategy cannot make it.
func factCell(ctx *Ctx, f Fact, value string) string {
	if !ctx.Facts.Has(f) {
		return "n/a"
	}
	return value
}

func suspendCell(c Component) string {
	if c.Suspend {
		return "YES"
	}
	return "-"
}

func reportFrontmatter(ctx *Ctx) int {
	var missing []string
	for _, d := range ctx.Docs {
		if d.Front == nil && d.FrontError == "" {
			missing = append(missing, d.Path)
		}
	}
	sort.Strings(missing)
	fmt.Printf("%d doc(s) without frontmatter — this is the migration worklist:\n\n", len(missing))
	for _, p := range missing {
		fmt.Println("  " + p)
	}
	return 0
}

// reportStale compares a doc's last commit against the last commit touching the code it says it
// covers. Deliberately reports DATES, never "N days old": a day count changes every day, which
// would churn the output and make any drift gate built on it permanently noisy.
func reportStale(ctx *Ctx) int {
	type row struct{ path, docDate, subjDate string }
	var rows []row
	for _, d := range ctx.Docs {
		if d.Front == nil {
			continue
		}
		dtype, _ := d.Front["type"].(string)
		fresh, _ := d.Front["freshness"].(string)
		if fresh == "" {
			fresh = ctx.Cfg.FreshnessDefault[dtype]
		}
		if fresh == "frozen" {
			continue
		}
		covers, _ := StringSlice(d.Front["covers"])
		subj := staleSubject(ctx, covers)
		docDate := ctx.Dates[d.Path]
		if subj != "" && docDate != "" && subj > docDate {
			rows = append(rows, row{d.Path, docDate[:10], subj[:10]})
		}
	}
	if len(rows) == 0 {
		fmt.Println("no docs report stale (populate `covers:` to widen coverage)")
		return 0
	}
	sort.Slice(rows, func(i, j int) bool { return rows[i].subjDate > rows[j].subjDate })
	fmt.Printf("%-60s %-12s %s\n", "doc", "doc@", "subject@")
	for _, r := range rows {
		fmt.Printf("%-60s %-12s %s\n", r.path, r.docDate, r.subjDate)
	}
	return 0
}

// reportGenerate runs the artifact set in write or verify mode.
//
// Exit codes are the contract a CI gate depends on: check mode returns 1 on any difference,
// generate mode returns 0 whenever it succeeded — including when it wrote nothing, which is the
// expected steady state and must not read as failure.
func reportGenerate(ctx *Ctx, check bool) int {
	mode := "generate"
	if check {
		mode = "check"
	}
	// An empty artifact set is a legitimate configuration, not a failure: most repos adopting
	// this tool start as linter-only. Exit 0 and SAY SO, because the alternative failure mode —
	// a silent zero-line report — reads exactly like a clean gate, and the alternative to that
	// (falling back to some artifact compiled into Go) is the defect this whole change removes.
	if len(ctx.Cfg.Artifacts) == 0 {
		fmt.Println("no artifacts configured (see artifacts: in config.yaml)")
		return 0
	}
	results, err := Generate(ctx, check)
	if err != nil {
		fmt.Fprintf(os.Stderr, "%s: %v\n", mode, err)
		return 2
	}
	stale := 0
	for _, r := range results {
		if r.Status == StatusDrift || r.Status == StatusMissing {
			stale++
		}
		fmt.Printf("%-10s %s\n", r.Status, r.Rel)
	}
	if check && stale > 0 {
		fmt.Fprintf(os.Stderr, "\n%d artifact(s) out of date — run `task docs:generate`\n", stale)
		return 1
	}
	return 0
}

// staleSubject returns the newest commit date across everything the covers resolve to, or "".
//
// The match is prefix OR EQUAL, and the "or equal" half is the whole point. ctx.Dates comes
// from `git log --name-only`, which lists FILE paths only — so a prefix-only match needed a
// dated path beginning "<the covered file>/", which cannot exist. Every cover naming a FILE was
// therefore silently inert here while still moving the colocation verdict: half-wired, with the
// working half disguising the dead half.
//
// It punished precision. Nine covers named the exact file whose change invalidates their doc —
// four of them configs/talconfig.yaml, which would invalidate half the runbooks — and every one
// contributed nothing. The vaguer directory-shaped declaration worked; the careful one did not.
func staleSubject(ctx *Ctx, covers []string) string {
	var subj string
	for _, c := range covers {
		p, ok := resolveCover(ctx, c)
		if !ok {
			continue
		}
		for path, date := range ctx.Dates {
			if (path == p || strings.HasPrefix(path, p+"/")) && date > subj {
				subj = date
			}
		}
	}
	return subj
}
