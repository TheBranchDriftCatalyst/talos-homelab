package main

// The `dirs` strategy: one component per directory.
//
// This is the fallback for a repo with no GitOps controller, and it is the strategy the
// portability claim actually rests on — every repo that is not a Flux repo lands here.
//
// Nothing outside this file mentions `dirs`. It is reachable only through the registry, via the
// init() below.

import (
	"os"
	"path/filepath"
	"sort"
)

func init() { register(dirsStrategy{}) }

type dirsStrategy struct{}

func (dirsStrategy) Name() string { return "dirs" }

// Provides: NOTHING beyond a slug and a path, and the empty set is the honest answer rather
// than an oversight.
//
// A directory has no declared name (the basename IS the path), no suspend flag and no
// dependency edges. Its path is discovered by listing the filesystem, so it exists by
// construction and "this path does not exist" can never fire. And sub-units are counted by
// looking for kustomization.yaml, which in a repo with no kustomize is structurally always
// zero — the collector still runs the count, but a rule cannot honestly read a number that is
// zero for reasons having nothing to do with the component.
//
// Recording the emptiness here is the point: today those rules silently never fire under
// `dirs`, and a check that quietly never runs is worse than an absent one because you believe
// you are covered.
func (dirsStrategy) Provides() FactSet { return FactSet{} }

// DefaultGlob is `*` — every entry under the configured path, filtered to directories below.
func (dirsStrategy) DefaultGlob() string { return "*" }

func (dirsStrategy) UnitNoun() string { return "service directory" }

// Enumerate never returns an error, and never warns: a non-directory entry is not a defect,
// it is a loose file that simply is not a component.
func (s dirsStrategy) Enumerate(root string, cfg *Config) (Enumeration, error) {
	var enum Enumeration
	entries, _ := filepath.Glob(filepath.Join(root, cfg.Components.Path, globFor(s, cfg)))
	sort.Strings(entries)
	for _, e := range entries {
		if fi, err := os.Stat(e); err == nil && fi.IsDir() {
			rel := mustRel(root, e)
			enum.Components = append(enum.Components,
				Component{Slug: filepath.Base(e), Path: rel, Source: rel, Nested: countNested(root, rel)})
		}
	}
	return enum, nil
}
