package main

// The strategy registry.
//
// This file must never name a strategy. Strategies register THEMSELVES from `init()` in their
// own file, so `strategy_flux.go` and `strategy_dirs.go` are referenced by nothing else in the
// package — which is the only way "adding a repo shape costs one new file and no edits" can be
// a property rather than a promise. A literal `map[string]ComponentStrategy{"flux": ...}` here
// would quietly turn it back into "one new file AND an edit to this one".
//
// TEST HAZARD, please read before adding a spec.
//
// The unit specs are in-package (package main), so a `_test.go` file with its own `init()`
// registering a fake strategy POLLUTES THE PRODUCTION REGISTRY for every other spec in the
// binary, in a file-order-dependent way. This is not theoretical: a leaked fake is how you get
// a spec asserting `strategyFor` names the registered kinds to start failing because of a file
// it never mentions.
//
// The convention is: never call `register` from a test `init()`. Use the `withStrategies`
// helper in strategy_unit_test.go, which swaps the map for the duration of one spec and
// restores it afterwards. That is a CONVENTION, not a mechanism — nothing here can stop a test
// file from calling `register` at init time, and Go gives the package no way to tell a test
// init from a production one. If it is ever broken the symptom is an unrelated spec failing,
// so the comment above `withStrategies` says what to look for.

import (
	"fmt"
	"sort"
	"strings"
)

// strategies is populated only by register, only from strategy files' init(). Built with make
// rather than a literal so that no entry can be added here by hand without it looking wrong.
var strategies = make(map[string]ComponentStrategy)

// register adds one strategy, PANICKING on a duplicate name.
//
// A duplicate is a programming error discovered at process start, and the alternatives are both
// worse than a panic: silently overwriting means whichever file the linker initialised last
// wins, so the enumerator a repo gets depends on filenames; silently keeping the first means a
// newly added strategy does nothing at all and reports no reason. Neither is discoverable from
// the tool's output.
func register(s ComponentStrategy) {
	name := s.Name()
	if prev, dup := strategies[name]; dup {
		panic(fmt.Sprintf("duplicate component strategy %q: %T and %T", name, prev, s))
	}
	strategies[name] = s
}

// strategyNames lists the registered kinds, sorted — it exists to be printed in an error, and
// an error message whose contents reorder between runs is not assertable.
func strategyNames() []string {
	out := make([]string, 0, len(strategies))
	for name := range strategies {
		out = append(out, name)
	}
	sort.Strings(out)
	return out
}

// strategyFor resolves `components.kind`.
//
// The error NAMES the registered kinds, because the whole class of failure here is a typo or a
// kind copied from another repo's config, and "unknown components.kind" on its own leaves the
// reader guessing which spellings exist. It is an error rather than a fall back to `dirs`: a
// silent fallback would report components a config typo never asked for, which looks like a
// working run.
func strategyFor(cfg *Config) (ComponentStrategy, error) {
	kind := cfg.Components.Kind
	if s, ok := strategies[kind]; ok {
		return s, nil
	}
	return nil, fmt.Errorf("unknown components.kind %q; registered kinds: %s",
		kind, strings.Join(strategyNames(), ", "))
}

// FactsFor is the supply side as the rest of the tool sees it: what the CONFIGURED strategy can
// actually say about a component.
//
// An unknown kind yields the EMPTY set rather than an error. EnumerateComponents has already
// failed and Build has already warned, so the run continues with no components at all —
// claiming capabilities on behalf of a strategy that does not exist would let every rule run
// against an empty world and report a clean pass, which is the exact failure this vocabulary
// exists to remove. Nothing to enumerate with means nothing can be measured.
func FactsFor(cfg *Config) FactSet {
	s, err := strategyFor(cfg)
	if err != nil {
		return FactSet{}
	}
	return s.Provides()
}

// EnumerateComponents is the one production entry point into the seam: resolve the kind, run
// the strategy, hand back both the components and whatever it could not make sense of.
//
// It does not write the warnings anywhere. Build does that, to the same stderr it always used.
func EnumerateComponents(root string, cfg *Config) (Enumeration, error) {
	s, err := strategyFor(cfg)
	if err != nil {
		return Enumeration{}, err
	}
	return s.Enumerate(root, cfg)
}
