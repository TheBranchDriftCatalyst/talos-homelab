package main

// Unit specs for the component-enumeration seam: the fact vocabulary, the registry, and the
// two strategies' declared capabilities.
//
// ---------------------------------------------------------------------------------------------
// READ THIS BEFORE ADDING A SPEC THAT INVOLVES A STRATEGY.
//
// These specs are IN-PACKAGE (package main), so they share one process and one `strategies`
// map with the production code. A `_test.go` file whose `init()` calls `register` therefore
// installs a fake into the REAL registry for every other spec in the binary, in an order
// determined by filenames. The symptom is not a failure in the file that did it: it is an
// unrelated spec — `strategyFor names the registered kinds` is the usual victim — failing
// because of a strategy it never mentions.
//
// So: never call `register` from a test `init()`, and never mutate `strategies` by hand. Use
// `withStrategies` below, which swaps the whole map for one spec and restores it in Cleanup.
//
// This is a CONVENTION, not a mechanism. Nothing enforces it — Go offers the package no way to
// distinguish a test `init()` from a production one, and an unexported map is writable from any
// file in the package. The comment above `strategies` in strategy_registry.go says the same
// thing, so whichever file someone opens first, they see it.
// ---------------------------------------------------------------------------------------------

import (
	"os"
	"path/filepath"
	"strings"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

// --- test-only registry isolation --------------------------------------------------------------

// withStrategies replaces the registry for the duration of one spec and restores it afterwards.
//
// Restoring the whole map rather than deleting the keys it added is deliberate: a spec that
// registers a fake named `flux` would otherwise delete the real one on the way out, and the
// next spec in the file order would enumerate nothing for reasons nowhere in its own text.
func withStrategies(t interface{ Cleanup(func()) }, list ...ComponentStrategy) {
	GinkgoHelper()
	saved := strategies
	t.Cleanup(func() { strategies = saved })
	strategies = make(map[string]ComponentStrategy, len(list))
	for _, s := range list {
		register(s)
	}
}

// fakeStrategy is a stand-in with no init() of its own — it reaches the registry only through
// withStrategies, which is the whole convention in one type.
type fakeStrategy struct {
	name     string
	glob     string
	noun     string
	provides FactSet
	comps    []Component
	warnings []string
}

func (f fakeStrategy) Name() string        { return f.name }
func (f fakeStrategy) Provides() FactSet   { return f.provides }
func (f fakeStrategy) DefaultGlob() string { return f.glob }
func (f fakeStrategy) UnitNoun() string    { return f.noun }
func (f fakeStrategy) Enumerate(string, *Config) (Enumeration, error) {
	return Enumeration{Components: f.comps, Warnings: f.warnings}, nil
}

// --- the fact vocabulary -----------------------------------------------------------------------

var _ = Describe("FactSet", Label("unit"), func() {
	It("treats an absent key and an explicit false as the same answer, so a strategy cannot half-declare a capability", func() {
		set := FactSet{FactDependsOn: true, FactInactive: false}

		Expect(set.Has(FactDependsOn)).To(BeTrue())
		Expect(set.Has(FactInactive)).To(BeFalse())
		Expect(set.Has(FactSubUnits)).To(BeFalse(), "a fact nobody listed is a fact nobody supplies")
	})

	It("reports the wanted facts it cannot supply", func() {
		set := FactSet{FactSubUnits: true}

		Expect(set.Missing([]Fact{FactSubUnits, FactDependsOn, FactInactive})).To(
			Equal([]Fact{FactDependsOn, FactInactive}))
	})

	It("returns nothing when every wanted fact is supplied, so a satisfied caller gets an empty slice rather than a sentinel", func() {
		Expect(FactSet{FactSubUnits: true}.Missing([]Fact{FactSubUnits})).To(BeEmpty())
	})

	It("returns nothing for an empty want list even from an empty set, because wanting nothing is always satisfiable", func() {
		Expect(FactSet{}.Missing(nil)).To(BeEmpty())
	})

	// SORTED is the point, not a nicety. The result goes into a skip message; a message whose
	// contents reorder between runs cannot be asserted on and cannot be diffed. The input here
	// is in the opposite order to the output, so an implementation that merely preserved the
	// caller's order would fail.
	It("sorts what it returns, so a skip message built from it is stable across runs", func() {
		want := []Fact{FactSubUnits, FactPathIsDeclared, FactInactive, FactDependsOn, FactDeclaredName}

		Expect(FactSet{}.Missing(want)).To(Equal([]Fact{
			FactDeclaredName, FactDependsOn, FactInactive, FactPathIsDeclared, FactSubUnits,
		}))
	})
})

// --- the registry --------------------------------------------------------------------------------

var _ = Describe("the strategy registry", Label("unit"), func() {
	It("holds exactly the strategies that register themselves from their own file, which is what makes `adding a kind is adding one file` checkable", func() {
		Expect(strategyNames()).To(Equal([]string{"dirs", "flux"}),
			"a kind reachable through config must be reachable only by having registered itself")
	})

	It("panics on a duplicate name rather than letting link order decide which enumerator a repo gets", func() {
		withStrategies(GinkgoT(), fakeStrategy{name: "twin"})

		Expect(func() { register(fakeStrategy{name: "twin"}) }).To(PanicWith(
			ContainSubstring(`duplicate component strategy "twin"`)))
	})

	It("keeps the first registration when a duplicate panics, so the failure cannot half-apply", func() {
		first := fakeStrategy{name: "twin", noun: "original"}
		withStrategies(GinkgoT(), first)

		Expect(func() { register(fakeStrategy{name: "twin", noun: "impostor"}) }).To(Panic())

		got, err := strategyFor(&Config{Components: ComponentSource{Kind: "twin"}})
		Expect(err).NotTo(HaveOccurred())
		Expect(got.UnitNoun()).To(Equal("original"))
	})

	DescribeTable("resolves a configured kind to the strategy that registered under that name",
		func(kind string, want ComponentStrategy) {
			got, err := strategyFor(&Config{Components: ComponentSource{Kind: kind}})

			Expect(err).NotTo(HaveOccurred())
			Expect(got).To(Equal(want))
		},
		Entry("flux", "flux", fluxStrategy{}),
		Entry("dirs", "dirs", dirsStrategy{}),
	)

	// The registered kinds are NAMED in the message because the whole failure class here is a
	// typo or a kind copied out of another repo's config, and "unknown components.kind" alone
	// leaves the reader guessing which spellings exist.
	It("errors for an unknown kind and names every registered kind, so the message answers the question it raises", func() {
		_, err := strategyFor(&Config{Components: ComponentSource{Kind: "helmfile"}})

		Expect(err).To(HaveOccurred())
		Expect(err.Error()).To(ContainSubstring(`unknown components.kind "helmfile"`))
		Expect(err.Error()).To(ContainSubstring("dirs"))
		Expect(err.Error()).To(ContainSubstring("flux"))
	})

	It("errors for an EMPTY kind too, because a components block with no kind is the same mistake spelled shorter", func() {
		_, err := strategyFor(&Config{})

		Expect(err).To(HaveOccurred())
		Expect(err.Error()).To(ContainSubstring(`unknown components.kind ""`))
	})

	It("lists the registered kinds in sorted order, since the list exists to be printed in that error", func() {
		withStrategies(GinkgoT(), fakeStrategy{name: "zeta"}, fakeStrategy{name: "alpha"}, fakeStrategy{name: "mid"})

		Expect(strategyNames()).To(Equal([]string{"alpha", "mid", "zeta"}))
	})

	It("restores the real registry after a spec swapped it, which is the property the whole withStrategies convention rests on", func() {
		// Runs AFTER the swapping specs above in file order. If Cleanup did not restore, the
		// registry would still hold `alpha/mid/zeta` and this would fail — which is exactly the
		// pollution the header comment warns about, made visible.
		Expect(strategyNames()).To(Equal([]string{"dirs", "flux"}))
	})

	It("passes the enumeration straight through EnumerateComponents, so Build sees the strategy's own warnings", func() {
		withStrategies(GinkgoT(), fakeStrategy{
			name:     "fake",
			comps:    []Component{{Slug: "one"}},
			warnings: []string{"something was skipped"},
		})

		enum, err := EnumerateComponents("/nowhere", &Config{Components: ComponentSource{Kind: "fake"}})

		Expect(err).NotTo(HaveOccurred())
		Expect(enum.Components).To(HaveLen(1))
		Expect(enum.Warnings).To(Equal([]string{"something was skipped"}))
	})
})

// --- what each strategy declares about itself ----------------------------------------------------

var _ = Describe("strategy capabilities", Label("unit"), func() {
	DescribeTable("answers to the kind it is selected by",
		func(s ComponentStrategy, name string) {
			Expect(s.Name()).To(Equal(name))
		},
		Entry("flux", fluxStrategy{}, "flux"),
		Entry("dirs", dirsStrategy{}, "dirs"),
	)

	// The default glob is strategy-specific because `*` — the old global default — is right for
	// dirs and actively wrong for flux, where it feeds README.md to a Kustomization decoder.
	DescribeTable("declares the glob it assumes when config omits one",
		func(s ComponentStrategy, want string) {
			Expect(s.DefaultGlob()).To(Equal(want))
		},
		Entry("flux matches only YAML, because every entry is handed to a Kustomization decoder",
			fluxStrategy{}, "*.yaml"),
		Entry("dirs matches everything and filters to directories itself", dirsStrategy{}, "*"),
	)

	DescribeTable("names its unit the way prose should, so a generated document is not obliged to say `Flux Kustomization` in a repo that has no Flux",
		func(s ComponentStrategy, want string) {
			Expect(s.UnitNoun()).To(Equal(want))
		},
		Entry("flux", fluxStrategy{}, "Flux Kustomization"),
		Entry("dirs", dirsStrategy{}, "service directory"),
	)

	It("declares every fact for flux, because a Kustomization carries a name, a path, a suspend flag and dependency edges", func() {
		got := fluxStrategy{}.Provides()

		for _, f := range []Fact{FactDeclaredName, FactSubUnits, FactInactive, FactDependsOn, FactPathIsDeclared} {
			Expect(got.Has(f)).To(BeTrue(), "flux supplies %s", f)
		}
	})

	// The EMPTY set is the assertion. A directory has no declared name, no suspend flag and no
	// dependency edges; its path exists by construction because it was found by listing the
	// filesystem; and its nested-kustomization count is structurally zero in a repo with no
	// kustomize. Every rule reading those today silently never fires under `dirs`.
	It("declares no facts at all for dirs, which is the honest answer and the reason those rules silently never fire there", func() {
		got := dirsStrategy{}.Provides()

		Expect(got.Missing([]Fact{FactDeclaredName, FactSubUnits, FactInactive, FactDependsOn, FactPathIsDeclared})).
			To(HaveLen(5))
	})

	// Provides takes no *Config, so it cannot vary per repo. That is a signature property, not
	// something a spec can assert directly — what is asserted is the consequence: two calls are
	// the same answer, and a capability can never become "it worked yesterday".
	DescribeTable("answers the same on every call, because capability is a property of the strategy and not of a repo's config",
		func(s ComponentStrategy) {
			Expect(s.Provides()).To(Equal(s.Provides()))
		},
		Entry("flux", fluxStrategy{}),
		Entry("dirs", dirsStrategy{}),
	)
})

// --- the glob default, observed through enumeration ----------------------------------------------

var _ = Describe("globFor", Label("unit"), func() {
	It("prefers the configured glob over the strategy's default, because config is the portability boundary", func() {
		Expect(globFor(fluxStrategy{}, &Config{Components: ComponentSource{Glob: "*.yml"}})).To(Equal("*.yml"))
	})

	DescribeTable("falls back to the strategy's own default when config omits one",
		func(s ComponentStrategy, want string) {
			Expect(globFor(s, &Config{})).To(Equal(want))
		},
		Entry("flux", fluxStrategy{}, "*.yaml"),
		Entry("dirs", dirsStrategy{}, "*"),
	)

	// The decoy is the spec. Under the OLD global `*` backfill this file list produced a
	// `README.md` decode attempt, which is the defect that moving the default per-strategy
	// exists to remove.
	It("keeps a flux repo that omits components.glob away from files that are not manifests", func() {
		root := GinkgoT().TempDir()
		unitWrite(root, "clusters/test/cilium.yaml", unitFlux("cilium", "./infrastructure/base/cilium"))
		unitWrite(root, "clusters/test/README.md", "# not a manifest\n")

		enum, err := fluxStrategy{}.Enumerate(root, &Config{Components: ComponentSource{Kind: "flux", Path: "clusters/test"}})

		Expect(err).NotTo(HaveOccurred())
		Expect(enum.Components).To(HaveLen(1))
		Expect(enum.Warnings).To(BeEmpty(), "README.md must never reach the Kustomization decoder")
	})

	It("still enumerates directories for a dirs repo that omits components.glob", func() {
		root := GinkgoT().TempDir()
		unitWrite(root, "services/alpha/main.go", "package main\n")
		unitWrite(root, "services/beta/main.go", "package main\n")

		enum, err := dirsStrategy{}.Enumerate(root, &Config{Components: ComponentSource{Kind: "dirs", Path: "services"}})

		Expect(err).NotTo(HaveOccurred())
		Expect(enum.Components).To(HaveLen(2))
	})
})

// --- warnings are returned, not printed ------------------------------------------------------------

var _ = Describe("Enumeration.Warnings", Label("unit"), func() {
	It("reports a Kustomization with no spec.path through the return value, where a spec can assert on it, rather than on package-level stderr", func() {
		root := GinkgoT().TempDir()
		unitWrite(root, "clusters/test/broken.yaml",
			"kind: Kustomization\nmetadata:\n  name: broken\nspec:\n  path: ./\n"+
				"---\n"+unitFlux("good", "./infrastructure/base/good"))
		cfg := &Config{Components: ComponentSource{Kind: "flux", Path: "clusters/test", Glob: "*.yaml"}}

		enum, err := fluxStrategy{}.Enumerate(root, cfg)

		Expect(err).NotTo(HaveOccurred())
		Expect(enum.Components).To(HaveLen(1), "the bad document is skipped, the good one is kept")
		Expect(enum.Warnings).To(ConsistOf(ContainSubstring("broken.yaml: Kustomization with no spec.path")))
	})

	It("reports an empty match as a warning rather than an error, because an unadopted repo must still get a usable lint run", func() {
		cfg := &Config{Components: ComponentSource{Kind: "flux", Path: "clusters/test", Glob: "*.yaml"}}

		enum, err := fluxStrategy{}.Enumerate(GinkgoT().TempDir(), cfg)

		Expect(err).NotTo(HaveOccurred())
		Expect(enum.Components).To(BeEmpty())
		Expect(enum.Warnings).To(ConsistOf(ContainSubstring(`no component manifests matched "*.yaml"`)))
	})

	// Repo-relative BY CONSTRUCTION is the claim on the Warnings field, and it takes two moves
	// to keep: name the file with mustRel, and drop the absolute path os errors repeat inside
	// their own text. The last time a loader wrote warnings itself it leaked the absolute repo
	// root onto stderr for every component in the tree.
	It("names an unreadable manifest repo-relatively and never leaks the absolute repo root", func() {
		root := GinkgoT().TempDir()
		// A DIRECTORY named like a manifest: the glob matches it, os.ReadFile refuses it, and
		// the resulting *fs.PathError renders with the absolute path unless it is stripped.
		Expect(os.MkdirAll(filepath.Join(root, "clusters", "test", "broken.yaml"), 0o755)).To(Succeed())
		unitWrite(root, "clusters/test/good.yaml", unitFlux("good", "./infrastructure/base/good"))
		cfg := &Config{Components: ComponentSource{Kind: "flux", Path: "clusters/test", Glob: "*.yaml"}}

		enum, err := fluxStrategy{}.Enumerate(root, cfg)

		Expect(err).NotTo(HaveOccurred())
		Expect(enum.Components).To(HaveLen(1), "one unreadable manifest must not abort the scan")
		Expect(enum.Warnings).To(HaveLen(1))
		Expect(enum.Warnings[0]).To(HavePrefix(filepath.Join("clusters", "test", "broken.yaml") + ":"))
		Expect(enum.Warnings[0]).NotTo(ContainSubstring(root),
			"a warning carrying this machine's repo root is not portable output")
	})

	It("returns no warnings for a clean dirs tree, so an empty Warnings slice means what it says", func() {
		root := GinkgoT().TempDir()
		unitWrite(root, "services/alpha/main.go", "package main\n")
		unitWrite(root, "services/alpha/notes.md", "# loose file\n")
		cfg := &Config{Components: ComponentSource{Kind: "dirs", Path: "services", Glob: "*"}}

		enum, err := dirsStrategy{}.Enumerate(root, cfg)

		Expect(err).NotTo(HaveOccurred())
		Expect(enum.Warnings).To(BeEmpty(), "a non-directory entry is not a defect, just not a component")
	})
})

var _ = Describe("pathErrorCause", Label("unit"), func() {
	It("keeps only the cause of a *fs.PathError, since its text repeats the absolute filename the caller already spelled relatively", func() {
		_, err := os.ReadFile(filepath.Join(GinkgoT().TempDir(), "absent.yaml"))

		Expect(err).To(HaveOccurred())
		Expect(err.Error()).To(ContainSubstring("absent.yaml"), "the raw error does carry the path")
		Expect(pathErrorCause(err).Error()).NotTo(ContainSubstring("absent.yaml"))
	})

	It("passes any other error through unchanged rather than swallowing it", func() {
		err := os.ErrClosed

		Expect(pathErrorCause(err)).To(Equal(err))
	})
})

var _ = Describe("strategy file independence", Label("unit"), func() {
	// The property that makes "adding a repo shape is adding ONE file" true: no file other than
	// strategy_flux.go / strategy_dirs.go (and their own specs) may mention those types, or
	// adding the third one silently becomes "one new file AND an edit somewhere else".
	It("is not mentioned by any production file other than its own", func() {
		sources, err := filepath.Glob("*.go")
		Expect(err).NotTo(HaveOccurred())

		for _, src := range sources {
			if strings.HasSuffix(src, "_test.go") || src == "strategy_flux.go" || src == "strategy_dirs.go" {
				continue
			}
			body, err := os.ReadFile(src)
			Expect(err).NotTo(HaveOccurred())
			Expect(string(body)).NotTo(ContainSubstring("fluxStrategy"), "%s names a strategy type", src)
			Expect(string(body)).NotTo(ContainSubstring("dirsStrategy"), "%s names a strategy type", src)
		}
	})
})
