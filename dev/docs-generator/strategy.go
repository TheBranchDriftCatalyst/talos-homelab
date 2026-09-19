package main

// The component-enumeration seam.
//
// `LoadComponents` used to be a switch over `components.kind` with two arms, which made the
// tool's portability claim — copy dev/docs-generator/, edit config.yaml, no Go changes — true
// only for another Flux repo. Everything else had to edit the switch, and the model leaked Flux
// vocabulary into rules that had no business knowing what a Kustomization is.
//
// A strategy owns THREE things a rule should never hardcode: how the units are enumerated, what
// a unit is CALLED in prose, and — the part that matters most — WHICH FACTS about a unit the
// strategy can actually supply. `dirs` cannot report a dependency edge or a suspended flag
// because a directory has neither; today a rule reading Component.DependsOn under `dirs` simply
// sees an empty slice and silently never fires, which is worse than an absent check because you
// believe you are covered.
//
// This file declares the vocabulary. It does not yet make any rule consult it — rules declaring
// the facts they need, and being reported as skipped rather than silently passing, is the next
// slice. What lands here is only the seam.

import (
	"errors"
	"io/fs"
	"sort"
)

// Fact names one thing a strategy may or may not be able to say about a component.
//
// The constants deliberately name the CONCEPT rather than today's struct field: `sub_units`
// rather than `Nested`, `inactive` rather than `Suspend`, `declared_name` rather than `Name`.
// The fields keep their current spelling for now; naming the concepts here first means the
// later rename is a field rename and not also a vocabulary change.
type Fact string

const (
	// FactDeclaredName — the unit carries a name declared somewhere other than its path, which
	// can therefore DRIFT from the path. Flux's metadata.name does; a directory's basename
	// cannot, because it is the path.
	FactDeclaredName Fact = "component.declared_name"

	// FactSubUnits — the strategy can count deployable units nested INSIDE one component. This
	// is the measurement behind the directory-shape smell, and it is kustomize-specific: in a
	// repo with no kustomize the count is structurally always zero.
	FactSubUnits Fact = "component.sub_units"

	// FactInactive — the unit can be declared present but switched off (Flux's spec.suspend). A
	// directory is never suspended; it is either there or not.
	FactInactive Fact = "component.inactive"

	// FactDependsOn — the strategy supplies edges between components. Flux's dependsOn is the
	// only such edge in the model; a filesystem walk supplies none.
	FactDependsOn Fact = "component.depends_on"

	// FactPathIsDeclared — the component's path is a DECLARATION that may not match reality, so
	// "this path does not exist" is a finding. Under `dirs` the path is discovered by listing
	// the filesystem, so it exists by construction and the check can never fire.
	FactPathIsDeclared Fact = "component.path_is_declared"
)

// FactSet is the set of facts one strategy can supply.
type FactSet map[Fact]bool

// Has reports whether the fact is supplied. A missing key and an explicit false are the same
// answer on purpose: there is no third state, and a strategy that wants to document a fact it
// cannot supply should simply leave it out.
func (s FactSet) Has(f Fact) bool {
	return s[f]
}

// Missing returns the wanted facts this set does not supply, SORTED — because the caller's next
// move is to put them in a message, and a message whose contents reorder between runs cannot be
// asserted on or diffed.
func (s FactSet) Missing(want []Fact) []Fact {
	var out []Fact
	for _, f := range want {
		if !s.Has(f) {
			out = append(out, f)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i] < out[j] })
	return out
}

// Enumeration is one strategy's answer: the components it found, plus what it could not make
// sense of on the way.
//
// Warnings are RETURNED rather than written to package-level stderr, for two reasons. The first
// is testability: a warning written to a global is observable only by capturing a process's
// stderr, so in practice nothing asserts on it and the warnings rot. The second is portability
// — the last time a loader wrote its own warnings it leaked this machine's absolute repo root
// into output that a golden file is supposed to match from any machine.
//
// Warnings are repo-relative by construction: a strategy names paths with mustRel, and strips
// the absolute filename that os errors repeat inside their own text (see pathErrorCause).
type Enumeration struct {
	Components []Component
	Warnings   []string
}

// ComponentStrategy is one way of enumerating a repo's deployable units.
//
// Adding a repo shape is adding ONE file: a type with these five methods plus an `init()` that
// registers it. No existing file mentions the new strategy, which is the property that makes
// the portability claim checkable rather than aspirational.
type ComponentStrategy interface {
	// Name is the `components.kind` value that selects this strategy.
	Name() string

	// Provides is the set of facts this strategy can supply. It takes NO *Config, and that is
	// the whole point: a capability that varied per repo would make "it worked yesterday" a
	// legitimate explanation for a rule quietly disappearing, which is exactly the failure mode
	// the fact vocabulary exists to remove. Capability is a property of the strategy; whether a
	// particular repo's config is any good is a separate question with a separate answer.
	Provides() FactSet

	// DefaultGlob is the `components.glob` this strategy assumes when the config omits one.
	//
	// It lives here rather than in LoadConfig because the right default is strategy-specific:
	// `*` is correct for `dirs` and actively wrong for `flux`, where it hands README.md to a
	// YAML decoder expecting a Kustomization.
	DefaultGlob() string

	// UnitNoun is what a component is CALLED in generated prose — "Flux Kustomization" for a
	// GitOps repo, "service directory" for a plain one.
	//
	// Nothing reads it yet. The inventory renderer still says "Flux Kustomization" in both
	// samples, which is wrong for `dirs` and is tracked as its own change: rewording it here
	// would move generated bytes, and this slice is a pure refactor.
	UnitNoun() string

	// Enumerate finds the components under root. It returns an error only when it cannot run at
	// all; one malformed manifest is a Warning and a skipped unit, because a typo in one file
	// must never abort a whole-tree scan.
	Enumerate(root string, cfg *Config) (Enumeration, error)
}

// globFor is the configured glob, or the strategy's own default when the config omits one. One
// definition, so two strategies can never disagree about what "omitted" means.
func globFor(s ComponentStrategy, cfg *Config) string {
	if g := cfg.Components.Glob; g != "" {
		return g
	}
	return s.DefaultGlob()
}

// pathErrorCause strips the filename an os error repeats inside its own text.
//
// os.ReadFile returns a *fs.PathError rendering as `open /abs/path/x.yaml: permission denied`,
// so formatting it after a repo-relative name reintroduces the absolute path the relative name
// was chosen to avoid. Keeping only the cause is what makes Enumeration.Warnings repo-relative
// by construction rather than by care.
func pathErrorCause(err error) error {
	var pe *fs.PathError
	if errors.As(err, &pe) {
		return pe.Err
	}
	return err
}
