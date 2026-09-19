package main

// Collection: walk the repo once, build the model every rule reads.
//
// Two decisions here are load-bearing and easy to get wrong when porting:
//
//  1. `git ls-files` is the walker, never filepath.Walk. It excludes worktrees, .direnv,
//     .scratch and anything else gitignored for free. In this repo a raw filesystem walk finds
//     1065 markdown files and git finds 161 — the difference is ~10 full repo copies under
//     .claude/worktrees/.
//
//  2. Dates come from ONE `git log --name-only` pass. Per-file `git log -1` is one process per
//     file, which is the difference between instant and several seconds here and much worse in
//     a larger repo.
//
// Loaders warn and skip. One malformed manifest must never abort a whole-tree scan — otherwise
// a typo in one file makes the linter useless in exactly the moment you want it.
//
// Component ENUMERATION no longer lives here. It is a registry of strategies — strategy.go for
// the contract, strategy_registry.go for the lookup, strategy_flux.go and strategy_dirs.go for
// the two implementations — because a switch over `components.kind` in this file made "porting
// is a config edit" true only for another Flux repo. What stays here is everything shared: the
// git walker, the markdown corpus, countNested, and Build.

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
)

type Ctx struct {
	Root       string
	Cfg        *Config
	Docs       []Doc
	Components []Component
	BySlug     map[string]Component
	Dates      map[string]string

	// Facts is what this repo's component strategy can actually SAY about a component, carried
	// on the model rather than re-derived, so the rule runner and the `components` report
	// cannot disagree about it.
	//
	// The zero value — a nil FactSet — supplies nothing, which is the honest default for a Ctx
	// assembled by hand: it reports every fact-dependent rule as unable to run rather than
	// running it against fields nobody populated. Build always fills this in.
	Facts FactSet

	// tracked is the set of doc paths LoadDocs actually admitted, so that "does this component
	// have a README" is answered from the SAME corpus the linter reads.
	//
	// It used to be an os.Stat. That made the two halves of this tool disagree about reality:
	// `components` stated the filesystem while `lint` walked `git ls-files`, so an UNTRACKED
	// README counted as documentation in one command and did not exist in the other. It nearly
	// shipped a false clean — a doc was moved, lint reported no findings, and the file was
	// simply invisible to it. An uncommitted README documents nothing for anybody else, so
	// "tracked" is also the honest answer, not merely the consistent one.
	tracked map[string]bool
}

// HasDoc reports whether a repo-relative markdown path is in the tracked corpus.
func (c *Ctx) HasDoc(rel string) bool { return c.tracked[rel] }

func warnf(format string, a ...any) {
	fmt.Fprintf(os.Stderr, "WARN "+format+"\n", a...)
}

func git(root string, args ...string) string {
	cmd := exec.Command("git", args...)
	cmd.Dir = root
	out, err := cmd.Output()
	if err != nil {
		return ""
	}
	return string(out)
}

func RepoRoot(start string) string {
	if out := strings.TrimSpace(git(start, "rev-parse", "--show-toplevel")); out != "" {
		return out
	}
	return start
}

func matchAny(path string, patterns []string) bool {
	for _, p := range patterns {
		if ok, _ := filepath.Match(p, path); ok {
			return true
		}
		// Also treat a bare prefix as a directory exclusion, so `docs/_archive/**` and
		// `docs/_archive` behave the same way. Porting configs get this wrong constantly.
		if strings.HasPrefix(path, strings.TrimSuffix(strings.TrimSuffix(p, "**"), "/")+"/") {
			return true
		}
	}
	return false
}

func TrackedMarkdown(root string, cfg *Config) []string {
	var out []string
	for _, line := range strings.Split(git(root, "ls-files", "*.md"), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || matchAny(line, cfg.Exclude) {
			continue
		}
		out = append(out, line)
	}
	sort.Strings(out)
	return out
}

func LoadDocs(root string, cfg *Config) []Doc {
	// NOTE: any change to what this admits must stay in lockstep with Ctx.tracked below —
	// they are two views of one corpus and divergence is exactly the bug this fixed.
	var docs []Doc
	for _, rel := range TrackedMarkdown(root, cfg) {
		b, err := os.ReadFile(filepath.Join(root, rel))
		if err != nil {
			warnf("%s: unreadable (%v)", rel, err)
			continue
		}
		docs = append(docs, MakeDoc(rel, string(b)))
	}
	return docs
}

// countNested reports how many kustomization.yaml files live under a component path.
//
// This is the measurement behind the directory-shape smell: a component whose slug maps to one
// Flux Kustomization but which contains seven nested ones is a single deployable name hiding
// seven real units, which makes "component = directory = doc home" untrue.
func countNested(root, rel string) int {
	n := 0
	_ = filepath.Walk(filepath.Join(root, rel), func(p string, info os.FileInfo, err error) error {
		if err != nil || info == nil || info.IsDir() {
			return nil
		}
		if info.Name() == "kustomization.yaml" || info.Name() == "kustomization.yml" {
			n++
		}
		return nil
	})
	return n
}

func LastCommitDates(root string) map[string]string {
	dates := map[string]string{}
	current := ""
	for _, line := range strings.Split(git(root, "log", "--name-only", "--format=%x00%cI"), "\n") {
		if strings.HasPrefix(line, "\x00") {
			current = strings.TrimSpace(line[1:])
			continue
		}
		line = strings.TrimSpace(line)
		if line != "" && current != "" {
			if _, seen := dates[line]; !seen {
				dates[line] = current
			}
		}
	}
	return dates
}

func Build(root string, cfg *Config) *Ctx {
	// The strategy returns its warnings rather than printing them, so Build drains them here —
	// to the same stderr the loaders always wrote to, in the same order, before the duplicate
	// slug check below adds its own.
	enum, err := EnumerateComponents(root, cfg)
	if err != nil {
		warnf("%v; no components loaded", err)
	}
	for _, w := range enum.Warnings {
		warnf("%s", w)
	}
	comps := enum.Components
	// A collapsed slug is invisible corruption rather than a missing feature: BySlug keeps the
	// last writer, so every cover/colocation/staleness answer for that slug silently describes
	// the wrong component. slugFor removes the known cause; this catches the rest loudly.
	bySlug := make(map[string]Component, len(comps))
	for _, c := range comps {
		if prev, dup := bySlug[c.Slug]; dup {
			warnf("duplicate component slug %q: %s and %s — resolution is ambiguous",
				c.Slug, prev.Path, c.Path)
		}
		bySlug[c.Slug] = c
	}
	docs := LoadDocs(root, cfg)
	tracked := make(map[string]bool, len(docs))
	for _, d := range docs {
		tracked[d.Path] = true
	}
	return &Ctx{
		Root:       root,
		Cfg:        cfg,
		Docs:       docs,
		tracked:    tracked,
		Components: comps,
		BySlug:     bySlug,
		Dates:      LastCommitDates(root),
		Facts:      FactsFor(cfg),
	}
}

func mustRel(root, p string) string {
	if r, err := filepath.Rel(root, p); err == nil {
		return r
	}
	return p
}
