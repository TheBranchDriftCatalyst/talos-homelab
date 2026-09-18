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

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"
)

type Ctx struct {
	Root       string
	Cfg        *Config
	Docs       []Doc
	Components []Component
	BySlug     map[string]Component
	Dates      map[string]string
}

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

type fluxDoc struct {
	Kind     string `yaml:"kind"`
	Metadata struct {
		Name string `yaml:"name"`
	} `yaml:"metadata"`
	Spec struct {
		Path      string `yaml:"path"`
		Suspend   bool   `yaml:"suspend"`
		DependsOn []struct {
			Name string `yaml:"name"`
		} `yaml:"dependsOn"`
	} `yaml:"spec"`
}

func loadFlux(root string, cfg *Config) []Component {
	var out []Component
	dir := filepath.Join(root, cfg.Components.Path)
	entries, err := filepath.Glob(filepath.Join(dir, cfg.Components.Glob))
	if err != nil || len(entries) == 0 {
		warnf("%s: no component manifests matched %q", cfg.Components.Path, cfg.Components.Glob)
		return out
	}
	sort.Strings(entries)
	for _, f := range entries {
		raw, err := os.ReadFile(f)
		if err != nil {
			warnf("%s: %v", f, err)
			continue
		}
		// A single file may hold several documents; decoding only the first would silently
		// drop components. At least one file in this repo does exactly that.
		dec := yaml.NewDecoder(strings.NewReader(string(raw)))
		var inFile []fluxDoc
		for {
			var fd fluxDoc
			if err := dec.Decode(&fd); err != nil {
				break
			}
			if fd.Kind != "Kustomization" {
				continue
			}
			if strings.TrimPrefix(strings.TrimPrefix(fd.Spec.Path, "."), "/") == "" {
				warnf("%s: Kustomization with no spec.path", filepath.Base(f))
				continue
			}
			inFile = append(inFile, fd)
		}
		base := strings.TrimSuffix(filepath.Base(f), filepath.Ext(f))
		for _, fd := range inFile {
			var deps []string
			for _, d := range fd.Spec.DependsOn {
				if d.Name != "" {
					deps = append(deps, d.Name)
				}
			}
			rel := strings.TrimPrefix(strings.TrimPrefix(fd.Spec.Path, "."), "/")
			out = append(out, Component{
				Slug:      slugFor(cfg, base, fd, len(inFile)),
				Name:      fd.Metadata.Name,
				Path:      rel,
				DependsOn: deps,
				Suspend:   fd.Spec.Suspend,
				Source:    mustRel(root, f),
				Nested:    countNested(root, rel),
			})
		}
	}
	return out
}

// slugFor picks the stable handle for one component.
//
// The filename is preferred, because metadata.name drifts from it in this repo and a slug that
// changes when someone renames a field is not a slug. But the filename is only a handle while it
// identifies ONE thing: external-secrets.yaml declares both `external-secrets-operator` and
// `external-secrets`, so under filename-slugging both collapsed to `external-secrets` and
// Ctx.BySlug silently kept whichever decoded last. That made `covers: external-secrets` resolve
// to an arbitrary one of two different paths — and therefore produced an arbitrary colocation
// verdict — with nothing reporting it.
//
// So: filename while the file declares exactly one Kustomization, metadata.name the moment it
// declares more. Uniqueness is the property that matters; the filename is just the usual way to
// get it.
func slugFor(cfg *Config, base string, fd fluxDoc, inFile int) string {
	if cfg.Components.SlugFrom == "metadata.name" && fd.Metadata.Name != "" {
		return fd.Metadata.Name
	}
	if inFile > 1 && fd.Metadata.Name != "" {
		return fd.Metadata.Name
	}
	return base
}

func loadDirs(root string, cfg *Config) []Component {
	var out []Component
	entries, _ := filepath.Glob(filepath.Join(root, cfg.Components.Path, cfg.Components.Glob))
	sort.Strings(entries)
	for _, e := range entries {
		if fi, err := os.Stat(e); err == nil && fi.IsDir() {
			rel := mustRel(root, e)
			out = append(out, Component{Slug: filepath.Base(e), Path: rel, Source: rel, Nested: countNested(root, rel)})
		}
	}
	return out
}

func LoadComponents(root string, cfg *Config) []Component {
	switch cfg.Components.Kind {
	case "flux":
		return loadFlux(root, cfg)
	case "dirs":
		return loadDirs(root, cfg)
	}
	warnf("unknown components.kind %q; no components loaded", cfg.Components.Kind)
	return nil
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
	comps := LoadComponents(root, cfg)
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
	return &Ctx{
		Root:       root,
		Cfg:        cfg,
		Docs:       LoadDocs(root, cfg),
		Components: comps,
		BySlug:     bySlug,
		Dates:      LastCommitDates(root),
	}
}

func mustRel(root, p string) string {
	if r, err := filepath.Rel(root, p); err == nil {
		return r
	}
	return p
}
