package main

// Unit specs for config.go — the portability boundary.
//
// Two behaviours here are deliberate and easy to "fix" into something worse: an unknown rule
// name defaults to ENABLED (a config typo must surface as unexpected findings, never as a check
// that quietly never runs), and a missing config file is a warning rather than a fatal error
// (the tool has to be usable in the repo where someone is adopting it for the first time).

import (
	"os"
	"path/filepath"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

var _ = Describe("Config.RuleFor", Label("unit"), func() {
	It("enables an unknown rule name at warn, because a typo in config must surface as unexpected findings rather than a silently dead check", func() {
		cfg := &Config{Rules: map[string]Rule{"broken-links": {Enabled: true, Severity: "error"}}}

		got := cfg.RuleFor("covers-resolves")

		Expect(got.Enabled).To(BeTrue(), "defaulting to disabled would let a misspelt rule name switch a check off invisibly")
		Expect(got.Severity).To(Equal("warn"))
	})

	It("enables every rule when the config carries no rules block at all, so a bare config still lints", func() {
		got := (&Config{}).RuleFor("taxonomy-structure")

		Expect(got).To(Equal(Rule{Enabled: true, Severity: "warn"}))
	})

	It("returns the configured severity unchanged, because severity is data and a repo must be able to land a rule as an error", func() {
		cfg := &Config{Rules: map[string]Rule{"broken-links": {Enabled: true, Severity: "error"}}}

		Expect(cfg.RuleFor("broken-links").Severity).To(Equal("error"))
	})

	It("fills in warn for a rule listed with no severity, so an omitted field never produces an empty severity in a finding", func() {
		cfg := &Config{Rules: map[string]Rule{"colocation": {Enabled: true}}}

		Expect(cfg.RuleFor("colocation").Severity).To(Equal("warn"))
	})

	It("respects an explicit disable, which is the only way a rule stops running", func() {
		cfg := &Config{Rules: map[string]Rule{"colocation": {Enabled: false, Severity: "error"}}}

		got := cfg.RuleFor("colocation")

		Expect(got.Enabled).To(BeFalse())
		Expect(got.Severity).To(Equal("error"))
	})

	It("fills in warn even for a disabled rule, so promoting it later is a one-field edit", func() {
		cfg := &Config{Rules: map[string]Rule{"colocation": {Enabled: false}}}

		Expect(cfg.RuleFor("colocation").Severity).To(Equal("warn"))
	})
})

var _ = Describe("Config.Has", Label("unit"), func() {
	DescribeTable("answers vocabulary membership exactly, since it backs both the enum checks and the grouping-root test",
		func(list []string, want string, expected bool) {
			Expect((&Config{}).Has(list, want)).To(Equal(expected))
		},
		Entry("a present value", []string{"reference", "runbook"}, "reference", true),
		Entry("an absent value", []string{"reference", "runbook"}, "guide", false),
		Entry("an empty list contains nothing", nil, "reference", false),
		Entry("the empty string is a real grouping-root entry and must match when listed",
			[]string{"", "infrastructure"}, "", true),
		Entry("the empty string does not match a list without it", []string{"infrastructure"}, "", false),
		Entry("matching is case sensitive, because the vocabularies are lowercase by convention",
			[]string{"reference"}, "Reference", false),
	)
})

var _ = Describe("LoadConfig", Label("unit"), func() {
	It("warns and returns usable defaults when config.yaml is missing, because a hard failure would make the tool unusable in exactly the repo where someone is adopting it", func() {
		cfg, err := LoadConfig(GinkgoT().TempDir())

		Expect(err).NotTo(HaveOccurred(), "a missing config must never be fatal")
		Expect(cfg).NotTo(BeNil())
		Expect(cfg.Components.Kind).To(Equal("dirs"), "the default enumerator works without a GitOps controller")
		Expect(cfg.Components.Glob).To(BeEmpty(),
			"the glob default belongs to the STRATEGY, not to LoadConfig; an empty value here means "+
				"`not configured` and is resolved by ComponentStrategy.DefaultGlob at enumeration time")
		Expect(cfg.TicketPattern).NotTo(BeEmpty())
	})

	It("returns an error for malformed YAML, and still hands back a non-nil config so the caller cannot nil-panic while reporting the failure", func() {
		dir := GinkgoT().TempDir()
		Expect(os.WriteFile(filepath.Join(dir, "config.yaml"), []byte("exclude: [unclosed\n"), 0o644)).To(Succeed())

		cfg, err := LoadConfig(dir)

		Expect(err).To(HaveOccurred())
		Expect(err.Error()).To(ContainSubstring("config.yaml"), "the message must name the file to fix")
		Expect(cfg).NotTo(BeNil())
	})

	It("parses a real config into every field the rules read, which is what keeps the Go free of any repo-specific knowledge", func() {
		dir := GinkgoT().TempDir()
		Expect(os.WriteFile(filepath.Join(dir, "config.yaml"), []byte(
			"exclude:\n  - docs/_archive/**\n"+
				"components:\n  kind: flux\n  path: clusters/test\n  glob: \"*.yaml\"\n  slug_from: metadata.name\n"+
				"doc_types: [reference, runbook]\n"+
				"key_order: [type, status]\n"+
				"grouping_roots: [\"\", infrastructure]\n"+
				"banned_keys:\n  title: markdownlint reads it as the document title\n"+
				"type_requires:\n  runbook: [\"## TL;DR\"]\n"+
				"required_footer: \"## Related Issues\"\n"+
				"rules:\n  broken-links: { enabled: true, severity: error }\n"), 0o644)).To(Succeed())

		cfg, err := LoadConfig(dir)

		Expect(err).NotTo(HaveOccurred())
		Expect(cfg.Exclude).To(Equal([]string{"docs/_archive/**"}))
		Expect(cfg.Components).To(Equal(ComponentSource{Kind: "flux", Path: "clusters/test", Glob: "*.yaml", SlugFrom: "metadata.name"}))
		Expect(cfg.DocTypes).To(Equal([]string{"reference", "runbook"}))
		Expect(cfg.KeyOrder).To(Equal([]string{"type", "status"}))
		Expect(cfg.GroupingRoots).To(Equal([]string{"", "infrastructure"}))
		Expect(cfg.BannedKeys).To(HaveKey("title"))
		Expect(cfg.TypeRequires).To(HaveKeyWithValue("runbook", []string{"## TL;DR"}))
		Expect(cfg.RequiredFooter).To(Equal("## Related Issues"))
		Expect(cfg.RuleFor("broken-links")).To(Equal(Rule{Enabled: true, Severity: "error"}))
	})

	// LoadConfig used to backfill `*` for EVERY kind, which is `dirs`' default wearing a
	// global: a flux repo omitting `glob:` then handed README.md to a Kustomization decoder.
	// The backfill is per-strategy now (ComponentStrategy.DefaultGlob, asserted for both kinds
	// in strategy_unit_test.go), so what LoadConfig must do is leave the field alone.
	//
	// Both kinds are spelled out, because an assertion on `dirs` alone would still pass if the
	// old global `*` came back — `*` is what dirs wants.
	DescribeTable("leaves an omitted components.glob empty rather than backfilling one default across every kind",
		func(kind string) {
			dir := GinkgoT().TempDir()
			Expect(os.WriteFile(filepath.Join(dir, "config.yaml"),
				[]byte("components:\n  kind: "+kind+"\n  path: infrastructure/base\n"), 0o644)).To(Succeed())

			cfg, err := LoadConfig(dir)

			Expect(err).NotTo(HaveOccurred())
			Expect(cfg.Components.Glob).To(BeEmpty())
		},
		Entry("dirs", "dirs"),
		Entry("flux", "flux"),
	)

	It("lets an empty config file fall through to the defaults rather than zeroing the ticket pattern", func() {
		dir := GinkgoT().TempDir()
		Expect(os.WriteFile(filepath.Join(dir, "config.yaml"), []byte("# nothing here\n"), 0o644)).To(Succeed())

		cfg, err := LoadConfig(dir)

		Expect(err).NotTo(HaveOccurred())
		Expect(cfg.TicketPattern).NotTo(BeEmpty())
		Expect(cfg.Components.Kind).To(Equal("dirs"))
	})
})
