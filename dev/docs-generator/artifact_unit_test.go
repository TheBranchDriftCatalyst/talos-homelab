package main

// Unit specs for the config-driven artifact set: the resolved destination, the deterministic
// frontmatter writer, the footer, and the pre-write gate.
//
// THE DEFECT THESE CLOSE. `Artifacts()` returned a hardcoded
// `docs/07-reference/component-inventory.md` and `artifact_inventory.go` held the frontmatter
// type, freshness, footer heading and ticket ids as Go string constants. Run against a repo
// whose doc types are [note spec howto log] and whose footer is `## Follow-up`, docsgen wrote a
// document its own linter then rejected on three counts — and invented a `docs/` tree that repo
// did not have. It hid because the artifact was untracked and the walker is `git ls-files`, so
// the tool had never linted its own output.
//
// EVERY SPEC HERE IS WRITTEN AGAINST A VOCABULARY THAT IS NOT THIS REPO'S. A spec that used
// `reference` / `## Related Issues` / `TALOS-…` would pass identically against the constants and
// against the config, which is the one thing these must not do.

import (
	"os"
	"path/filepath"
	"strings"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

// foreignConfig is a host repo that shares NO vocabulary with talos-homelab: its docs live in
// notes/, its types are [note spec howto log], its freshness values are [live frozen] and its
// footer is `## Follow-up`. Every value the generator used to hardcode is wrong here.
func foreignConfig() *Config {
	return &Config{
		DocsRoot:       "notes",
		DocTypes:       []string{"note", "spec", "howto", "log"},
		Statuses:       []string{"current", "draft", "superseded"},
		Freshness:      []string{"live", "frozen"},
		KeyOrder:       []string{"type", "status", "covers", "freshness", "tickets", "superseded_by"},
		RequiredFooter: "## Follow-up",
		BannedKeys:     map[string]string{"title": "the H1 is the title"},
		Components:     ComponentSource{Kind: "dirs", Path: "services", Glob: "*"},
		Artifacts: map[string]ArtifactSpec{
			"component-inventory": {
				Path: "reference/component-inventory.md",
				Front: map[string]any{
					"type":      "note",
					"status":    "current",
					"covers":    []any{"repo"},
					"freshness": "live",
					"tickets":   []any{"PD-07"},
				},
				TicketNotes: map[string]string{"PD-07": "the component inventory artifact"},
			},
		},
	}
}

func foreignCtx() *Ctx {
	cfg := foreignConfig()
	return &Ctx{Root: GinkgoT().TempDir(), Cfg: cfg, BySlug: map[string]Component{}}
}

func onlySpec(cfg *Config) ArtifactSpec { return cfg.Artifacts["component-inventory"] }

var _ = Describe("Config.DocsRootOr", Label("unit"), func() {
	It("defaults to `docs`, which is safe in a way a default `type:` would not be: a root is a "+
		"path and a wrong one is visible the moment anyone looks at the tree", func() {
		Expect((&Config{}).DocsRootOr()).To(Equal("docs"))
	})

	It("returns the configured root, so a repo whose prose lives in handbook/ is never told to "+
		"write into a docs/ tree it does not have", func() {
		Expect((&Config{DocsRoot: "handbook"}).DocsRootOr()).To(Equal("handbook"))
	})

	It("strips a trailing slash so `notes/` and `notes` cannot produce two different destinations", func() {
		Expect((&Config{DocsRoot: "notes/"}).DocsRootOr()).To(Equal("notes"))
	})
})

var _ = Describe("Artifacts", Label("unit"), func() {
	It("returns the EMPTY set when no `artifacts:` block is configured, because a default here "+
		"is the hardcoded artifact wearing a config key", func() {
		Expect(Artifacts(&Config{})).To(BeEmpty())
	})

	It("joins the destination from docs_root and the artifact's own path, so porting the tool "+
		"costs a YAML edit rather than a Go edit", func() {
		arts := Artifacts(foreignConfig())

		Expect(arts).To(HaveLen(1))
		Expect(arts[0].Rel).To(Equal("notes/reference/component-inventory.md"))
		Expect(arts[0].Rel).NotTo(HavePrefix("docs/"))
	})

	It("names each artifact by its config key, so an error can point at something editable", func() {
		Expect(Artifacts(foreignConfig())[0].Name).To(Equal("component-inventory"))
	})

	It("orders the set by name rather than by map iteration, so `docsgen generate` output does "+
		"not reshuffle between runs", func() {
		cfg := foreignConfig()
		// A second entry under a name with no renderer is skipped here and reported by
		// validateArtifacts; ordering is asserted on what does resolve.
		Expect(Artifacts(cfg)).To(HaveLen(1))
		Expect(Artifacts(cfg)[0].Name).To(Equal("component-inventory"))
	})
})

var _ = Describe("validateArtifacts", Label("unit"), func() {
	It("accepts a well-formed block", func() {
		Expect(validateArtifacts(foreignConfig())).To(Succeed())
	})

	It("accepts an absent block, because generating nothing is a legitimate configuration", func() {
		Expect(validateArtifacts(&Config{})).To(Succeed())
	})

	It("names the key when `path` is missing, rather than inventing a destination", func() {
		cfg := foreignConfig()
		spec := onlySpec(cfg)
		spec.Path = ""
		cfg.Artifacts["component-inventory"] = spec

		err := validateArtifacts(cfg)

		Expect(err).To(HaveOccurred())
		Expect(err.Error()).To(ContainSubstring("artifacts.component-inventory.path"))
	})

	It("rejects a `type` outside the repo's own doc_types AND prints the allowed values, because "+
		"`reference` is exactly the value the generator used to hardcode", func() {
		cfg := foreignConfig()
		spec := onlySpec(cfg)
		spec.Front["type"] = "reference"
		cfg.Artifacts["component-inventory"] = spec

		err := validateArtifacts(cfg)

		Expect(err).To(HaveOccurred())
		Expect(err.Error()).To(ContainSubstring("artifacts.component-inventory.front.type"))
		Expect(err.Error()).To(ContainSubstring(`"reference"`))
		Expect(err.Error()).To(ContainSubstring("[note spec howto log]"))
	})

	It("rejects a `freshness` outside the repo's own vocabulary, the second value that used to "+
		"be a constant", func() {
		cfg := foreignConfig()
		spec := onlySpec(cfg)
		spec.Front["freshness"] = "tracks-code"
		cfg.Artifacts["component-inventory"] = spec

		err := validateArtifacts(cfg)

		Expect(err).To(HaveOccurred())
		Expect(err.Error()).To(ContainSubstring("artifacts.component-inventory.front.freshness"))
		Expect(err.Error()).To(ContainSubstring("[live frozen]"))
	})

	It("rejects a `status` outside the repo's own vocabulary", func() {
		cfg := foreignConfig()
		spec := onlySpec(cfg)
		spec.Front["status"] = "published"
		cfg.Artifacts["component-inventory"] = spec

		Expect(validateArtifacts(cfg).Error()).To(
			ContainSubstring("artifacts.component-inventory.front.status"))
	})

	It("reports an artifact name no renderer answers to, instead of silently generating nothing", func() {
		cfg := foreignConfig()
		cfg.Artifacts["dependency-graph"] = ArtifactSpec{Path: "reference/deps.md"}

		err := validateArtifacts(cfg)

		Expect(err).To(HaveOccurred())
		Expect(err.Error()).To(ContainSubstring("artifacts.dependency-graph"))
		Expect(err.Error()).To(ContainSubstring("component-inventory"), "it must say what IS available")
	})

	It("reports a path that escapes the documentation root", func() {
		cfg := foreignConfig()
		spec := onlySpec(cfg)
		spec.Path = "../../etc/passwd.md"
		cfg.Artifacts["component-inventory"] = spec

		Expect(validateArtifacts(cfg).Error()).To(ContainSubstring("escapes the documentation root"))
	})

	It("reports a ticket note for an id the frontmatter never lists, because dead config looks "+
		"exactly like config that stopped working", func() {
		cfg := foreignConfig()
		spec := onlySpec(cfg)
		spec.TicketNotes["PD-99"] = "a note nothing will ever render"
		cfg.Artifacts["component-inventory"] = spec

		Expect(validateArtifacts(cfg).Error()).To(
			ContainSubstring("artifacts.component-inventory.ticket_notes.PD-99"))
	})

	It("reports every problem in one pass, so fixing a five-key block is not five runs", func() {
		cfg := foreignConfig()
		spec := onlySpec(cfg)
		spec.Front["type"] = "reference"
		spec.Front["freshness"] = "tracks-code"
		cfg.Artifacts["component-inventory"] = spec

		msg := validateArtifacts(cfg).Error()

		Expect(msg).To(ContainSubstring("front.type"))
		Expect(msg).To(ContainSubstring("front.freshness"))
	})
})

var _ = Describe("renderFrontMatter", Label("unit"), func() {
	It("emits keys in cfg.KeyOrder rather than alphabetically, which is what yaml.Marshal would "+
		"do and what this repo's own frontmatter-schema rule then reports as a violation", func() {
		cfg := foreignConfig()

		out, err := renderFrontMatter(cfg, onlySpec(cfg).Front)

		Expect(err).NotTo(HaveOccurred())
		Expect(out).To(Equal("---\n" +
			"type: note\n" +
			"status: current\n" +
			"covers:\n  - repo\n" +
			"freshness: live\n" +
			"tickets:\n  - PD-07\n" +
			"---\n"))
	})

	It("writes a sequence as a BLOCK sequence, because prettier explodes a flow one and the "+
		"generated file would stop being a prettier fixed point", func() {
		out, _ := renderFrontMatter(foreignConfig(), map[string]any{"covers": []any{"repo", "cluster"}})

		Expect(out).To(ContainSubstring("covers:\n  - repo\n  - cluster\n"))
		Expect(out).NotTo(ContainSubstring("["))
	})

	It("sorts keys the repo's key_order does not mention AFTER the ones it does, so an unranked "+
		"key cannot sit invisibly between two ranked ones", func() {
		front := map[string]any{"zeta": "z", "alpha": "a", "type": "note", "status": "current"}

		out, _ := renderFrontMatter(foreignConfig(), front)

		Expect(out).To(Equal("---\ntype: note\nstatus: current\nalpha: a\nzeta: z\n---\n"))
	})

	It("is byte-stable across runs, because a map iteration order leaking into a generated file "+
		"is drift the generator invented", func() {
		cfg := foreignConfig()
		front := map[string]any{"a": "1x", "b": "2x", "c": "3x", "d": "4x", "e": "5x", "f": "6x"}
		first, _ := renderFrontMatter(cfg, front)
		for i := 0; i < 50; i++ {
			again, _ := renderFrontMatter(cfg, front)
			Expect(again).To(Equal(first))
		}
	})

	It("leaves an ordinary sentence unquoted, so the artifact keeps the bytes a human wrote", func() {
		out, _ := renderFrontMatter(foreignConfig(), map[string]any{
			"bluf": "Every service directory, with whether it has a colocated README.",
		})

		Expect(out).To(ContainSubstring(
			"bluf: Every service directory, with whether it has a colocated README.\n"))
	})

	DescribeTable("quotes a scalar YAML would otherwise parse back as something else",
		func(in, want string) {
			out, err := renderFrontMatter(&Config{}, map[string]any{"k": in})
			Expect(err).NotTo(HaveOccurred())
			Expect(out).To(Equal("---\nk: " + want + "\n---\n"))
		},
		Entry("a leading dash would open a sequence", "-not a list", `"-not a list"`),
		Entry("a leading brace would open a mapping", "{oops}", `"{oops}"`),
		Entry("an embedded `: ` would open a nested mapping", "a: b", `"a: b"`),
		Entry("an embedded ` #` would open a comment", "tail # end", `"tail # end"`),
		Entry("a bare `no` parses as false", "no", `"no"`),
		Entry("a bare number stops being a string", "1.5", `"1.5"`),
		Entry("an empty value is indistinguishable from an absent key", "", `""`),
		Entry("a trailing space does not survive a plain scalar", "x ", `"x "`),
	)

	It("refuses a value it cannot write deterministically rather than dropping the key, because "+
		"a silently missing key produces an artifact its own schema rule rejects", func() {
		_, err := renderFrontMatter(&Config{}, map[string]any{"covers": map[string]any{"nested": 1}})

		Expect(err).To(HaveOccurred())
		Expect(err.Error()).To(ContainSubstring("`covers`"))
	})

	It("refuses an empty sequence, which has no block form at all", func() {
		_, err := renderFrontMatter(&Config{}, map[string]any{"covers": []any{}})

		Expect(err).To(HaveOccurred())
		Expect(err.Error()).To(ContainSubstring("`covers`"))
	})
})

var _ = Describe("renderFooter", Label("unit"), func() {
	It("uses the heading the HOST repo requires, not the one this repo happens to use", func() {
		cfg := foreignConfig()

		out := renderFooter(cfg, onlySpec(cfg))

		Expect(out).To(HavePrefix("## Follow-up\n\n"))
		Expect(out).NotTo(ContainSubstring("## Related Issues"))
	})

	It("lists exactly the tickets in front.tickets, which is what makes `tickets-in-body` "+
		"self-satisfying rather than merely satisfied today", func() {
		cfg := foreignConfig()
		spec := onlySpec(cfg)
		spec.Front["tickets"] = []any{"PD-11", "PD-07"}
		spec.TicketNotes = map[string]string{"PD-07": "first", "PD-11": "second"}

		out := renderFooter(cfg, spec)

		Expect(out).To(Equal("## Follow-up\n\n- PD-07 — first\n- PD-11 — second\n"))
	})

	It("sorts the list, so reordering the config's tickets does not churn the artifact", func() {
		cfg := foreignConfig()
		spec := onlySpec(cfg)
		spec.Front["tickets"] = []any{"PD-11", "PD-07"}
		spec.TicketNotes = nil

		Expect(renderFooter(cfg, spec)).To(Equal("## Follow-up\n\n- PD-07\n- PD-11\n"))
	})
})

var _ = Describe("renderComponentInventory", Label("unit"), func() {
	It("names the component source from config, never a cluster path only one repo has", func() {
		ctx := foreignCtx()

		out := renderComponentInventory(ctx, onlySpec(ctx.Cfg))

		Expect(out).To(ContainSubstring("Flux Kustomizations in `services/`"))
		Expect(out).NotTo(ContainSubstring("clusters/catalyst-cluster"))
	})

	It("carries no value from this repository's vocabulary at all", func() {
		ctx := foreignCtx()

		out := renderComponentInventory(ctx, onlySpec(ctx.Cfg))

		Expect(out).NotTo(ContainSubstring("type: reference"))
		Expect(out).NotTo(ContainSubstring("tracks-code"))
		Expect(out).NotTo(ContainSubstring("TALOS-"))
		Expect(out).NotTo(ContainSubstring("## Related Issues"))
	})
})

// --- the pre-write gate ------------------------------------------------------------------
//
// This is what closes the defect, and it is strictly stronger than making the constants
// configurable: a configurable constant can still be configured wrong, and the wrong value is
// then discovered only if somebody commits the artifact and runs the linter. The gate runs the
// artifact's own bytes through the repo's own rules in memory, so the wrong bytes never reach
// the disk regardless of whether the file is ever tracked.
//
// Each spec below uses a front matter that validateArtifacts ACCEPTS — otherwise it would be
// proving the validator, not the gate.
var _ = Describe("the pre-write gate", Label("unit"), func() {
	generate := func(cfg *Config) (*Ctx, error) {
		ctx := &Ctx{Root: GinkgoT().TempDir(), Cfg: cfg, BySlug: map[string]Component{}}
		_, err := Generate(ctx, false)
		return ctx, err
	}

	It("writes the artifact when the repo's own rules accept it", func() {
		ctx, err := generate(foreignConfig())

		Expect(err).NotTo(HaveOccurred())
		Expect(filepath.Join(ctx.Root, "notes/reference/component-inventory.md")).To(BeAnExistingFile())
	})

	It("refuses to write when a required key is missing, and names the config key at fault", func() {
		cfg := foreignConfig()
		spec := onlySpec(cfg)
		delete(spec.Front, "covers")
		cfg.Artifacts["component-inventory"] = spec

		ctx, err := generate(cfg)

		Expect(err).To(HaveOccurred())
		Expect(err.Error()).To(ContainSubstring("artifacts.component-inventory.front.covers"))
		Expect(err.Error()).To(ContainSubstring("refusing to write"))
		Expect(filepath.Join(ctx.Root, "notes/reference/component-inventory.md")).NotTo(BeAnExistingFile())
	})

	It("refuses to write a banned key the validator has no opinion about, which is the half of "+
		"the ruleset config validation cannot reach", func() {
		cfg := foreignConfig()
		spec := onlySpec(cfg)
		spec.Front["title"] = "Component Inventory"
		cfg.Artifacts["component-inventory"] = spec

		ctx, err := generate(cfg)

		Expect(err).To(HaveOccurred())
		Expect(err.Error()).To(ContainSubstring("artifacts.component-inventory.front.title"))
		Expect(filepath.Join(ctx.Root, "notes/reference/component-inventory.md")).NotTo(BeAnExistingFile())
	})

	It("refuses `status: superseded` with no superseded_by — an in-enum value the schema rule "+
		"still rejects", func() {
		cfg := foreignConfig()
		spec := onlySpec(cfg)
		spec.Front["status"] = "superseded"
		cfg.Artifacts["component-inventory"] = spec

		_, err := generate(cfg)

		Expect(err).To(HaveOccurred())
		Expect(err.Error()).To(ContainSubstring("superseded_by"))
	})

	It("refuses a type whose structural requirement the artifact cannot meet, so `type:` is not "+
		"a decorative label on generated files either", func() {
		cfg := foreignConfig()
		cfg.TypeRequires = map[string][]string{"note": {"## Service level"}}

		_, err := generate(cfg)

		Expect(err).To(HaveOccurred())
		Expect(err.Error()).To(ContainSubstring("## Service level"))
	})

	It("leaves an existing good artifact untouched when a later config change makes the render "+
		"unacceptable, because a refusal must not be a deletion", func() {
		cfg := foreignConfig()
		ctx, err := generate(cfg)
		Expect(err).NotTo(HaveOccurred())
		abs := filepath.Join(ctx.Root, "notes/reference/component-inventory.md")
		before, rerr := os.ReadFile(abs)
		Expect(rerr).NotTo(HaveOccurred())

		cfg.Artifacts["component-inventory"] = func() ArtifactSpec {
			s := onlySpec(cfg)
			s.Front["title"] = "banned"
			return s
		}()
		_, err = Generate(&Ctx{Root: ctx.Root, Cfg: cfg, BySlug: map[string]Component{}}, false)

		Expect(err).To(HaveOccurred())
		after, rerr := os.ReadFile(abs)
		Expect(rerr).NotTo(HaveOccurred())
		Expect(string(after)).To(Equal(string(before)))
	})

	It("refuses in CHECK mode too, so a gate cannot report `unchanged` for a rejected document "+
		"that merely happens to already be on disk", func() {
		cfg := foreignConfig()
		spec := onlySpec(cfg)
		spec.Front["title"] = "banned"
		cfg.Artifacts["component-inventory"] = spec
		ctx := &Ctx{Root: GinkgoT().TempDir(), Cfg: cfg, BySlug: map[string]Component{}}

		_, err := Generate(ctx, true)

		Expect(err).To(HaveOccurred())
		Expect(err.Error()).To(ContainSubstring("refusing to write"))
	})

	It("proves the gate is the repo's OWN ruleset by going green when the vocabulary admits the "+
		"value it rejected", func() {
		cfg := foreignConfig()
		spec := onlySpec(cfg)
		spec.Front["type"] = "inventory"
		cfg.Artifacts["component-inventory"] = spec
		cfg.DocTypes = append(cfg.DocTypes, "inventory")

		_, err := generate(cfg)

		Expect(err).NotTo(HaveOccurred())
	})
})

// The end-to-end claim, stated once as a property rather than as a list of keys: whatever the
// host repo's vocabulary is, the bytes docsgen writes satisfy it. This is the spec that would
// have caught the original defect on day one, and it is deliberately written over the SAMPLE
// vocabularies rather than this repo's.
var _ = Describe("a generated artifact against a foreign vocabulary", Label("unit"), func() {
	It("produces no finding from the repo's own frontmatter and taxonomy rules", func() {
		ctx := foreignCtx()
		content := normalizeMarkdown(renderComponentInventory(ctx, onlySpec(ctx.Cfg)))
		lintCtx := &Ctx{
			Root:   ctx.Root,
			Cfg:    ctx.Cfg,
			Docs:   []Doc{MakeDoc("notes/reference/component-inventory.md", content)},
			BySlug: map[string]Component{},
		}

		findings := append(ruleFrontmatterSchema(lintCtx), ruleTaxonomyStructure(lintCtx)...)

		var msgs []string
		for _, f := range findings {
			msgs = append(msgs, f.Rule+": "+f.Message)
		}
		Expect(findings).To(BeEmpty(), "docsgen's own output violates docsgen's own rules:\n  %s",
			strings.Join(msgs, "\n  "))
	})

	It("satisfies tickets-in-body by construction, because the footer's list IS the frontmatter's", func() {
		ctx := foreignCtx()
		content := normalizeMarkdown(renderComponentInventory(ctx, onlySpec(ctx.Cfg)))
		lintCtx := &Ctx{
			Root:   ctx.Root,
			Cfg:    ctx.Cfg,
			Docs:   []Doc{MakeDoc("notes/reference/component-inventory.md", content)},
			BySlug: map[string]Component{},
		}

		Expect(ruleTicketsInBody(lintCtx)).To(BeEmpty())
	})
})
