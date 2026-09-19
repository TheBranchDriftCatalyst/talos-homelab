package main

// Unit specs for artifact scoping: `scope:`, `root:` and the `renderer:` key that lets one
// renderer serve several artifacts.
//
// THE DEFECT THESE CLOSE. Every artifact rendered ALL components, so there was no way to say
// "this document covers the security folder" — which is what a generated members table for a
// grouping directory is. The workaround was a hand-written list in the section README, wrong
// the moment a fifth component lands in the folder, with nothing to report it.
//
// TWO PROPERTIES ARE LOAD-BEARING AND BOTH ARE ASSERTED AS THE ABSENCE OF A CHANGE:
//
//  1. NO `scope:` MEANS EVERY COMPONENT, byte for byte. Every artifact written before this
//     feature omits the key; if the default rendered anything different, adopting the feature
//     would have produced a diff in every repo that already had an inventory.
//
//  2. NO `root:` MEANS `docs_root`. Same argument, for the destination rather than the content.
//
// And the refusal: a scope matching nothing is an ERROR naming the key, never an empty table.
// The two are indistinguishable to every later reader — "this section is empty" and "your
// filter is wrong" render identically — so the wrong one must not be writable.

import (
	"strings"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

// scopedForeignConfig is foreignConfig plus a SECOND artifact: the same renderer, scoped to one
// subdirectory, rooted outside the documentation tree. Its vocabulary is the foreign repo's, for
// the same reason foreignConfig has one — a spec written in this repo's spelling would pass
// against a constant and against config alike.
func scopedForeignConfig() *Config {
	cfg := foreignConfig()
	cfg.Artifacts["payments-inventory"] = ArtifactSpec{
		Renderer: "component-inventory",
		Root:     "services/payments",
		Path:     "components.md",
		Scope:    &ArtifactScope{PathPrefix: "services/payments"},
		Front: map[string]any{
			"type":      "note",
			"status":    "current",
			"covers":    []any{"repo"},
			"freshness": "live",
			"tickets":   []any{"PD-07"},
		},
		TicketNotes: map[string]string{"PD-07": "the component inventory artifact"},
	}
	return cfg
}

// scopedCtx is a repo with five components, two of which are inside services/payments and one
// of which — services/payments-legacy — is the neighbour a substring prefix would wrongly admit.
func scopedCtx(cfg *Config) *Ctx {
	comps := []Component{
		{Slug: "billing", Path: "services/billing", Source: "services/billing"},
		{Slug: "ledger", Path: "services/payments/ledger", Source: "services/payments/ledger"},
		{Slug: "payments", Path: "services/payments", Source: "services/payments"},
		{Slug: "payments-legacy", Path: "services/payments-legacy", Source: "services/payments-legacy"},
		{Slug: "search", Path: "services/search", Source: "services/search"},
	}
	bySlug := map[string]Component{}
	for _, c := range comps {
		bySlug[c.Slug] = c
	}
	return &Ctx{Root: GinkgoT().TempDir(), Cfg: cfg, Components: comps, BySlug: bySlug}
}

func specNamed(cfg *Config, name string) ArtifactSpec { return cfg.Artifacts[name] }

// artifactNamed finds one resolved artifact, failing loudly when the set is EMPTY rather than
// returning a zero value. A spec that iterates an empty artifact set passes by having nothing
// to assert on, which is the same vacuity the feature under test exists to refuse.
func artifactNamed(cfg *Config, name string) Artifact {
	GinkgoHelper()
	arts := Artifacts(cfg)
	Expect(arts).NotTo(BeEmpty(),
		"the artifact set is empty, so this spec would assert nothing at all")
	for _, a := range arts {
		if a.Name == name {
			return a
		}
	}
	Fail("no artifact named " + name + " resolved from " + strings.Join(artifactNames(arts), " "))
	return Artifact{}
}

func artifactNames(arts []Artifact) []string {
	out := make([]string, 0, len(arts))
	for _, a := range arts {
		out = append(out, a.Name)
	}
	return out
}

var _ = Describe("ArtifactScope.Matches", Label("unit"), func() {
	It("matches everything when the scope is absent, which is what keeps every pre-scope "+
		"artifact byte-identical", func() {
		var none *ArtifactScope
		Expect(none.Matches(Component{Path: "anywhere/at/all"})).To(BeTrue())
	})

	It("matches the scoped directory itself, because a component rooted exactly at the prefix "+
		"is inside the section it names", func() {
		s := &ArtifactScope{PathPrefix: "services/payments"}
		Expect(s.Matches(Component{Path: "services/payments"})).To(BeTrue())
	})

	It("matches a component nested under the prefix", func() {
		s := &ArtifactScope{PathPrefix: "services/payments"}
		Expect(s.Matches(Component{Path: "services/payments/ledger"})).To(BeTrue())
	})

	It("does NOT match a sibling that merely starts with the same characters — a substring "+
		"prefix would pull the neighbour into a members table and nobody would notice", func() {
		s := &ArtifactScope{PathPrefix: "services/payments"}
		Expect(s.Matches(Component{Path: "services/payments-legacy"})).To(BeFalse())
	})

	It("does not match an unrelated path", func() {
		s := &ArtifactScope{PathPrefix: "services/payments"}
		Expect(s.Matches(Component{Path: "services/search"})).To(BeFalse())
	})

	It("reads `services/payments/` and `services/payments` as the same scope, so a trailing "+
		"slash cannot silently produce a different table", func() {
		withSlash := &ArtifactScope{PathPrefix: "services/payments/"}
		Expect(withSlash.Matches(Component{Path: "services/payments/ledger"})).To(BeTrue())
		Expect(withSlash.Matches(Component{Path: "services/payments-legacy"})).To(BeFalse())
	})
})

var _ = Describe("scopeComponents", Label("unit"), func() {
	It("returns every component untouched when the scope is absent", func() {
		ctx := scopedCtx(scopedForeignConfig())
		Expect(scopeComponents(ctx.Components, nil)).To(Equal(ctx.Components))
	})

	It("returns only the components inside the scope, in the order it was given them", func() {
		ctx := scopedCtx(scopedForeignConfig())
		got := scopeComponents(ctx.Components, &ArtifactScope{PathPrefix: "services/payments"})

		var slugs []string
		for _, c := range got {
			slugs = append(slugs, c.Slug)
		}
		Expect(slugs).To(Equal([]string{"ledger", "payments"}))
	})
})

var _ = Describe("Config.RootFor", Label("unit"), func() {
	It("falls back to the documentation root, so every artifact written before `root:` existed "+
		"lands exactly where it used to", func() {
		cfg := foreignConfig()
		Expect(cfg.RootFor(onlySpec(cfg))).To(Equal("notes"))
	})

	It("returns the artifact's own root, because a section inventory belongs beside its "+
		"manifests and those are outside the documentation tree", func() {
		cfg := scopedForeignConfig()
		Expect(cfg.RootFor(specNamed(cfg, "payments-inventory"))).To(Equal("services/payments"))
	})

	It("strips slashes so `services/payments/` and `services/payments` cannot produce two "+
		"different destinations", func() {
		Expect((&Config{}).RootFor(ArtifactSpec{Root: "services/payments/"})).To(Equal("services/payments"))
	})
})

var _ = Describe("Artifacts with root and renderer", Label("unit"), func() {
	It("joins the destination from the artifact's own root, landing outside docs_root", func() {
		a := artifactNamed(scopedForeignConfig(), "payments-inventory")

		Expect(a.Rel).To(Equal("services/payments/components.md"))
		Expect(a.Rel).NotTo(HavePrefix("notes/"))
	})

	It("still joins from docs_root for an artifact with no root of its own", func() {
		Expect(artifactNamed(scopedForeignConfig(), "component-inventory").Rel).
			To(Equal("notes/reference/component-inventory.md"))
	})

	It("resolves a renderer named by `renderer:` rather than by the config key, which is what "+
		"lets one renderer serve a whole-repo inventory AND a per-section one with no Go edit", func() {
		arts := Artifacts(scopedForeignConfig())
		Expect(artifactNames(arts)).To(ConsistOf("component-inventory", "payments-inventory"))
	})
})

var _ = Describe("validateArtifacts with scope and root", Label("unit"), func() {
	It("accepts the scoped, rooted artifact", func() {
		Expect(validateArtifacts(scopedForeignConfig())).To(Succeed())
	})

	It("names the key when `root` escapes the repository, because the destination is joined "+
		"onto the repo root and then written to", func() {
		cfg := scopedForeignConfig()
		spec := specNamed(cfg, "payments-inventory")
		spec.Root = "../../etc"
		cfg.Artifacts["payments-inventory"] = spec

		Expect(validateArtifacts(cfg).Error()).To(ContainSubstring("artifacts.payments-inventory.root"))
		Expect(validateArtifacts(cfg).Error()).To(ContainSubstring("escapes the repository"))
	})

	It("names the key when `root` is absolute", func() {
		cfg := scopedForeignConfig()
		spec := specNamed(cfg, "payments-inventory")
		spec.Root = "/etc"
		cfg.Artifacts["payments-inventory"] = spec

		Expect(validateArtifacts(cfg).Error()).To(ContainSubstring("artifacts.payments-inventory.root"))
	})

	It("refuses an empty `scope:` block rather than reading it as `cover everything` — that is "+
		"what omitting the block means, and a half-written filter is not the same intention", func() {
		cfg := scopedForeignConfig()
		spec := specNamed(cfg, "payments-inventory")
		spec.Scope = &ArtifactScope{}
		cfg.Artifacts["payments-inventory"] = spec

		Expect(validateArtifacts(cfg).Error()).
			To(ContainSubstring("artifacts.payments-inventory.scope.path_prefix"))
	})

	It("names `renderer` when the renderer it asks for does not exist, so the error points at "+
		"the line a human would edit", func() {
		cfg := scopedForeignConfig()
		spec := specNamed(cfg, "payments-inventory")
		spec.Renderer = "not-a-renderer"
		cfg.Artifacts["payments-inventory"] = spec

		msg := validateArtifacts(cfg).Error()
		Expect(msg).To(ContainSubstring("artifacts.payments-inventory.renderer"))
		Expect(msg).To(ContainSubstring("not-a-renderer"))
	})
})

var _ = Describe("validateArtifactScopes", Label("unit"), func() {
	It("accepts a scope that matches at least one component", func() {
		Expect(validateArtifactScopes(scopedCtx(scopedForeignConfig()))).To(Succeed())
	})

	It("accepts an unscoped artifact set, because `no scope` is not a filter that matched "+
		"nothing", func() {
		cfg := foreignConfig()
		Expect(validateArtifactScopes(scopedCtx(cfg))).To(Succeed())
	})

	It("REFUSES a scope that matches no component, naming the key — an empty inventory that "+
		"looks intentional reads as `nothing to report` when it means `the filter is wrong`", func() {
		cfg := scopedForeignConfig()
		spec := specNamed(cfg, "payments-inventory")
		spec.Scope = &ArtifactScope{PathPrefix: "services/paym"} // a truncated, plausible typo
		cfg.Artifacts["payments-inventory"] = spec

		err := validateArtifactScopes(scopedCtx(cfg))

		Expect(err).To(HaveOccurred())
		Expect(err.Error()).To(ContainSubstring("artifacts.payments-inventory.scope.path_prefix"))
		Expect(err.Error()).To(ContainSubstring("services/paym"))
		// The component COUNT is in the message because "matched nothing" has two very
		// different causes — a typo in the prefix, and a collector that found nothing at all —
		// and the count is what tells them apart.
		Expect(err.Error()).To(ContainSubstring("5 component(s)"))
	})
})

var _ = Describe("renderComponentInventory under a scope", Label("unit"), func() {
	It("renders only the components inside the scope", func() {
		cfg := scopedForeignConfig()
		out := renderComponentInventory(scopedCtx(cfg), specNamed(cfg, "payments-inventory"))

		Expect(out).To(ContainSubstring("| `ledger` |"))
		Expect(out).To(ContainSubstring("| `payments` |"))
		Expect(out).NotTo(ContainSubstring("| `payments-legacy` |"))
		Expect(out).NotTo(ContainSubstring("| `billing` |"))
		Expect(out).NotTo(ContainSubstring("| `search` |"))
	})

	It("counts the scoped rows in its prose, so the sentence above the table describes the "+
		"table below it", func() {
		cfg := scopedForeignConfig()
		out := renderComponentInventory(scopedCtx(cfg), specNamed(cfg, "payments-inventory"))

		Expect(out).To(ContainSubstring("2 components are declared"))
		Expect(out).NotTo(ContainSubstring("5 components are declared"))
	})

	It("says in the document that the table is a subset, and says which subset", func() {
		cfg := scopedForeignConfig()
		out := renderComponentInventory(scopedCtx(cfg), specNamed(cfg, "payments-inventory"))

		Expect(out).To(ContainSubstring("# Component Inventory — `services/payments`"))
		Expect(out).To(ContainSubstring("SCOPED"))
		Expect(out).To(ContainSubstring("`services/payments/`"))
	})

	It("produces bytes IDENTICAL to the pre-scope renderer for an artifact with no `scope:`, "+
		"which is the only thing `scope absent means every component` can mean", func() {
		cfg := scopedForeignConfig()
		ctx := scopedCtx(cfg)
		out := renderComponentInventory(ctx, onlySpec(cfg))

		// No scope vocabulary anywhere in it, and every component present.
		Expect(out).To(ContainSubstring("# Component Inventory\n"))
		Expect(out).NotTo(ContainSubstring("SCOPED"))
		Expect(out).NotTo(ContainSubstring("# Component Inventory —"))
		Expect(out).To(ContainSubstring("5 components are declared"))
		for _, c := range ctx.Components {
			Expect(out).To(ContainSubstring("| `" + c.Slug + "` |"))
		}
	})
})
