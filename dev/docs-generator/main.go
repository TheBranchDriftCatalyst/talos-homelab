// Command docsgen lints and (later) generates repository documentation.
//
// READ AND WRITE. `lint` and the report commands never touch the repository; `generate` writes
// the whole-file artifacts and `check` verifies them without writing. The marker-region half —
// nav tables interleaved with human prose in INDEX.md and the section READMEs — is deliberately
// still absent, because whole-file and marker ownership must never be mixed in one file.
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
	"path/filepath"
	"runtime"
	"sort"
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
		os.Exit(reportLint(ctx, *rule))
	case "links":
		os.Exit(reportLint(ctx, "broken-links"))
	case "components":
		os.Exit(reportComponents(ctx))
	case "frontmatter":
		os.Exit(reportFrontmatter(ctx))
	case "stale":
		os.Exit(reportStale(ctx))
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

func reportLint(ctx *Ctx, only string) int {
	findings := Run(ctx, only)
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
		if len(shown) > 20 {
			shown = shown[:20]
		}
		for _, f := range shown {
			fmt.Printf("  %s: %s\n", f.Path, f.Message)
		}
		if len(items) > 20 {
			fmt.Printf("  ... and %d more\n", len(items)-20)
		}
	}
	fmt.Printf("\n%d finding(s): %d error, %d warn\n", len(findings), errors, len(findings)-errors)
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
		if fileExists(filepath.Join(ctx.Root, c.Path, "README.md")) {
			readme = "yes"
			withReadme++
		}
		suspend := "-"
		if c.Suspend {
			suspend = "YES"
		}
		fmt.Printf("%-32s %-7s %-8d %-7s %s\n", c.Slug, readme, c.Nested, suspend, c.Path)
	}
	fmt.Printf("\n%d components, %d with a README (%d without)\n",
		len(comps), withReadme, len(comps)-withReadme)
	return 0
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
		var subj string
		for _, c := range covers {
			p, ok := resolveCover(ctx, c)
			if !ok {
				continue
			}
			for path, date := range ctx.Dates {
				if strings.HasPrefix(path, p+"/") && date > subj {
					subj = date
				}
			}
		}
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
