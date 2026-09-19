package main

// Unit specs for the DEMAND side of the fact vocabulary: what each rule declares it measures,
// what Run does when the strategy cannot supply it, and what the skip says.
//
// Provides() alone changes no behaviour — a capability nobody consults is documentation. These
// specs are about the pairing: Requires on the check, Provides on the strategy, and the one
// decision that falls out of comparing them.
//
// None of these touch the registry. The facts come off Ctx, so a spec builds the world it wants
// by setting a field — see the TEST HAZARD note in strategy_registry.go for why reaching into
// `strategies` from a test would be the wrong way to get the same thing.

import (
	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

// skipCtx is a Ctx whose strategy supplies exactly the named facts and nothing else. Components
// are non-empty and point at paths that do not exist, so a fact-dependent rule that DID run
// would produce findings — which is what makes "no findings" here mean "it did not run" rather
// than "it ran and the tree was clean".
func skipCtx(supplied ...Fact) *Ctx {
	facts := FactSet{}
	for _, f := range supplied {
		facts[f] = true
	}
	return &Ctx{
		Root: "/nonexistent-root",
		Cfg:  &Config{Components: ComponentSource{Kind: "dirs"}},
		Components: []Component{
			{Slug: "one", Path: "services/one", Source: "services/one", Nested: 9},
		},
		BySlug: map[string]Component{},
		Facts:  facts,
	}
}

func skipRules(skips []RuleSkip) []string {
	out := make([]string, 0, len(skips))
	for _, s := range skips {
		out = append(out, s.Rule)
	}
	return out
}

var _ = Describe("Rules declare the facts they measure", Label("unit"), func() {
	It("makes `component-path` depend on the path being a DECLARATION, which is the only reason "+
		"a path that does not exist is a defect rather than a typo in the walker", func() {
		Expect(Rules["component-path"].Requires).To(Equal([]Fact{FactPathIsDeclared}))
	})

	It("makes `component-shape` depend on sub-unit counting, which is the measurement the whole "+
		"rule is", func() {
		Expect(Rules["component-shape"].Requires).To(Equal([]Fact{FactSubUnits}))
	})

	// The negative half, and the more important one. Requires names what a rule MEASURES, never
	// every field it happens to read — every rule touches Component.Path, and a rule that
	// declared a fact it does not actually need would disappear from repos that can still
	// answer its question perfectly well.
	It("leaves every other rule requiring nothing, so a narrower strategy loses exactly the two "+
		"checks it cannot answer and not one more", func() {
		for name, check := range Rules {
			if name == "component-path" || name == "component-shape" {
				continue
			}
			Expect(check.Requires).To(BeEmpty(),
				"rule %q declares a fact requirement; it will vanish under any strategy that "+
					"does not supply it, and nothing about %q needs the component model at all", name, name)
		}
	})

	It("gives every registered rule a function, because a check with a nil Fn is a rule that "+
		"never runs and never says so", func() {
		for name, check := range Rules {
			Expect(check.Fn).NotTo(BeNil(), "rule %q has no implementation", name)
		}
	})
})

var _ = Describe("Run and unavailable facts", Label("unit"), func() {
	It("skips a rule whose measurement the strategy cannot supply, instead of running it and "+
		"reporting the silence as a pass", func() {
		findings, skipped := Run(skipCtx(), "")

		Expect(skipRules(skipped)).To(ContainElements("component-path", "component-shape"))
		Expect(unitRules(findings)).NotTo(ContainElement("component-path"))
		Expect(unitRules(findings)).NotTo(ContainElement("component-shape"))
	})

	// The proof that the skip is a skip and not merely a rule finding nothing: with the fact
	// supplied, this exact Ctx produces findings. Without that half, an implementation that
	// deleted the two rules entirely would pass the spec above.
	It("runs the same rule against the same tree once the fact is supplied", func() {
		findings, skipped := Run(skipCtx(FactPathIsDeclared, FactSubUnits), "")

		Expect(skipped).To(BeEmpty())
		Expect(unitRules(findings)).To(ContainElements("component-path", "component-shape"))
	})

	It("reports each skip once, in rule-name order, so the report is diffable", func() {
		_, skipped := Run(skipCtx(), "")

		Expect(skipRules(skipped)).To(Equal([]string{"component-path", "component-shape"}))
	})

	It("carries the missing facts alongside the sentence, so a caller can act on them without "+
		"re-parsing prose", func() {
		_, skipped := Run(skipCtx(), "component-shape")

		Expect(skipped).To(HaveLen(1))
		Expect(skipped[0].Rule).To(Equal("component-shape"))
		Expect(skipped[0].Missing).To(Equal([]Fact{FactSubUnits}))
	})

	It("names the missing fact and the configured kind in the reason, because the remedy is a "+
		"config decision rather than a bug to hunt", func() {
		_, skipped := Run(skipCtx(), "component-path")

		Expect(skipped).To(HaveLen(1))
		Expect(skipped[0].Why).To(Equal(
			"needs component.path_is_declared, which components.kind `dirs` does not report"))
	})

	// The three gates in order: `only` is the operator's choice, `enabled` is the repo's, and
	// Requires is the tool's. Only the last is a surprise, so only the last is announced.
	It("says nothing about a rule the operator did not select", func() {
		_, skipped := Run(skipCtx(), "broken-links")

		Expect(skipped).To(BeEmpty(),
			"a rule nobody asked for is a deliberate absence, not an unavailable measurement")
	})

	It("says nothing about a rule the repo switched off, because that absence is already "+
		"recorded in config where somebody chose it", func() {
		ctx := skipCtx()
		ctx.Cfg.Rules = map[string]Rule{"component-shape": {Enabled: false}}

		_, skipped := Run(ctx, "")

		Expect(skipRules(skipped)).NotTo(ContainElement("component-shape"))
		Expect(skipRules(skipped)).To(ContainElement("component-path"))
	})

	It("supplies no facts for a Ctx nobody filled in, so a hand-built world reports its rules as "+
		"unable to run rather than running them against empty fields", func() {
		ctx := skipCtx()
		ctx.Facts = nil

		_, skipped := Run(ctx, "")

		Expect(skipRules(skipped)).To(Equal([]string{"component-path", "component-shape"}))
	})
})

var _ = Describe("FactsFor", Label("unit"), func() {
	It("hands back what the configured strategy declares", func() {
		facts := FactsFor(&Config{Components: ComponentSource{Kind: "flux"}})

		Expect(facts.Has(FactSubUnits)).To(BeTrue())
		Expect(facts.Has(FactPathIsDeclared)).To(BeTrue())
	})

	It("hands back the empty set for `dirs`, which is the honest answer and the whole reason the "+
		"two component rules now announce themselves", func() {
		facts := FactsFor(&Config{Components: ComponentSource{Kind: "dirs"}})

		Expect(facts.Has(FactSubUnits)).To(BeFalse())
		Expect(facts.Has(FactPathIsDeclared)).To(BeFalse())
	})

	// An unknown kind has already been reported by EnumerateComponents and loaded no components
	// at all. Claiming capabilities on its behalf would let every rule run against an empty
	// world and report a clean pass — the precise failure the vocabulary exists to remove.
	It("supplies nothing for an unknown kind rather than guessing, because a run with no "+
		"components must not also claim to have measured them", func() {
		facts := FactsFor(&Config{Components: ComponentSource{Kind: "no-such-kind"}})

		Expect(facts).NotTo(BeNil())
		for _, f := range []Fact{FactDeclaredName, FactSubUnits, FactInactive, FactDependsOn, FactPathIsDeclared} {
			Expect(facts.Has(f)).To(BeFalse(), "claimed %s on behalf of a strategy that does not exist", f)
		}
	})
})
