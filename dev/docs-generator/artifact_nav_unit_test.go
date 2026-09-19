package main

// Unit specs for the nav renderer and its config validation.
//
// THE DEFECT THIS CLOSES. A hand-written link table is a claim about the tree that nothing
// revalidates. When `docs/_archive/` was deleted from this repo, 58 rows across nine nav files
// kept pointing at documents that no longer existed anywhere — not moved, DELETED — and
// `broken-links` reported all 58 forever because there was nothing to repoint them at. Rows
// derived from the corpus cannot reach that state.
//
// The SECOND property is the one that is easy to lose while fixing the first: regenerating a
// nav must not throw away the curated one-liners, because those are the only reason anybody
// reads a nav table instead of running `ls`. That is what the description key buys, and the
// specs below assert both that it is used AND that its name comes from config — a hardcoded
// `bluf` would pass against this repo and silently fall back to the H1 in every other.

import (
	"strings"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

// navConfig is a host repo whose description key is `summary`, not `bluf`. Everything about the
// vocabulary is foreign for the same reason foreignConfig's is.
func navConfig() *Config {
	cfg := foreignConfig()
	cfg.KeyOrder = append(cfg.KeyOrder, "summary")
	delete(cfg.Artifacts, "component-inventory")
	cfg.Artifacts["notes-nav"] = ArtifactSpec{
		Renderer: "nav",
		Path:     "README.md",
		Region:   "nav",
		Nav:      &NavSource{Entries: navSiblings, DescriptionKey: "summary"},
	}
	return cfg
}

// navCtx is a corpus with one described doc, one that falls back to its H1, one with neither,
// a dead-end superseded doc, a forwarded superseded doc, a README (which is a section's own nav
// and never a sibling row) and a document one directory deeper.
func navCtx(cfg *Config) *Ctx {
	docs := []Doc{
		MakeDoc("notes/README.md", "---\ntype: note\n---\n\n# Notes\n"),
		MakeDoc("notes/deploying.md",
			"---\ntype: howto\nstatus: current\nsummary: How a release reaches production.\n---\n\n# Deploying\n"),
		MakeDoc("notes/release-log.md", "# Release Log\n\nNo frontmatter at all.\n"),
		MakeDoc("notes/anonymous.md", "No frontmatter and no H1 either.\n"),
		MakeDoc("notes/retired.md",
			"---\ntype: note\nstatus: superseded\nsummary: Nowhere to go.\n---\n\n# Retired\n"),
		MakeDoc("notes/forwarded.md",
			"---\ntype: note\nstatus: superseded\nsummary: Points at its replacement.\nsuperseded_by: deploying.md\n---\n\n# Forwarded\n"),
		MakeDoc("notes/reference/deep.md",
			"---\ntype: note\nsummary: One directory deeper.\n---\n\n# Deep\n"),
		MakeDoc("elsewhere/other.md", "---\ntype: note\nsummary: A different tree.\n---\n\n# Other\n"),
	}
	return &Ctx{Root: GinkgoT().TempDir(), Cfg: cfg, Docs: docs, BySlug: map[string]Component{}}
}

func navSpec(cfg *Config) ArtifactSpec { return cfg.Artifacts["notes-nav"] }

var _ = Describe("navRows", Label("unit"), func() {
	var cfg *Config
	var ctx *Ctx

	BeforeEach(func() {
		cfg = navConfig()
		ctx = navCtx(cfg)
	})

	It("derives its rows from the CORPUS, in target-path order, and that order is the "+
		"documented one", func() {
		rows := navRows(ctx, navSpec(cfg))
		var targets []string
		for _, r := range rows {
			targets = append(targets, r.Target)
		}
		Expect(targets).To(Equal([]string{
			"notes/anonymous.md",
			"notes/deploying.md",
			"notes/forwarded.md",
			"notes/release-log.md",
		}))
	})

	It("never lists itself, because a nav pointing at itself is a loop rather than an entry", func() {
		for _, r := range navRows(ctx, navSpec(cfg)) {
			Expect(r.Target).NotTo(Equal("notes/README.md"))
		}
	})

	It("lists DIRECT children only under `siblings`: a document one directory deeper belongs to "+
		"that directory's own nav, and listing it here gives it two homes", func() {
		for _, r := range navRows(ctx, navSpec(cfg)) {
			Expect(r.Target).NotTo(Equal("notes/reference/deep.md"))
		}
	})

	It("ignores documents outside the directory entirely", func() {
		for _, r := range navRows(ctx, navSpec(cfg)) {
			Expect(r.Target).NotTo(HavePrefix("elsewhere/"))
		}
	})

	It("skips a superseded document with NO successor — it says `do not trust me` and offers "+
		"nowhere to go", func() {
		for _, r := range navRows(ctx, navSpec(cfg)) {
			Expect(r.Target).NotTo(Equal("notes/retired.md"))
		}
	})

	It("KEEPS a superseded document that names its successor, because following the row is how "+
		"a reader reaches the replacement", func() {
		var found bool
		for _, r := range navRows(ctx, navSpec(cfg)) {
			found = found || r.Target == "notes/forwarded.md"
		}
		Expect(found).To(BeTrue())
	})

	It("takes the description from the CONFIGURED key, so the curated one-liner survives a "+
		"regeneration", func() {
		Expect(rowNamed(navRows(ctx, navSpec(cfg)), "notes/deploying.md").Desc).
			To(Equal("How a release reaches production."))
	})

	It("falls back to the H1 when the key is absent, rather than to an empty cell nobody can "+
		"tell from a rendering bug", func() {
		Expect(rowNamed(navRows(ctx, navSpec(cfg)), "notes/release-log.md").Desc).
			To(Equal("Release Log"))
	})

	It("falls back VISIBLY when there is neither key nor H1", func() {
		Expect(rowNamed(navRows(ctx, navSpec(cfg)), "notes/anonymous.md").Desc).NotTo(BeEmpty())
	})

	It("reads the key name from config: against a repo whose key is spelled differently, every "+
		"description degrades to the H1 — which is exactly why there is no default", func() {
		spec := navSpec(cfg)
		spec.Nav = &NavSource{Entries: navSiblings, DescriptionKey: "bluf"}
		Expect(rowNamed(navRows(ctx, spec), "notes/deploying.md").Desc).To(Equal("Deploying"))
	})

	It("enumerates SECTIONS as `<subdir>/README.md`, one row per section and never its contents", func() {
		spec := navSpec(cfg)
		spec.Nav = &NavSource{Entries: navSections, Dir: "notes", DescriptionKey: "summary"}
		rows := navRows(ctx, spec)
		Expect(rows).To(HaveLen(0), "notes/reference has no README in this corpus")

		ctx.Docs = append(ctx.Docs, MakeDoc("notes/reference/README.md",
			"---\ntype: note\nsummary: The reference tables.\n---\n\n# Reference\n"))
		rows = navRows(ctx, spec)
		Expect(rows).To(HaveLen(1))
		Expect(rows[0].Text).To(Equal("reference"))
		Expect(rows[0].Href).To(Equal("reference/README.md"))
		Expect(rows[0].Desc).To(Equal("The reference tables."))
	})
})

var _ = Describe("renderNav", Label("unit"), func() {
	It("escapes a pipe in a description, because an unescaped one splits the row and shifts "+
		"every later cell one column left — damage that reads as a formatting glitch", func() {
		cfg := navConfig()
		ctx := navCtx(cfg)
		ctx.Docs = append(ctx.Docs, MakeDoc("notes/piped.md",
			"---\ntype: note\nsummary: \"a | b | c\"\n---\n\n# Piped\n"))

		out := renderNav(ctx, navSpec(cfg))
		row := ""
		for _, line := range strings.Split(out, "\n") {
			if strings.Contains(line, "piped.md") {
				row = line
			}
		}
		Expect(row).To(ContainSubstring(`a \| b \| c`))
		Expect(splitRow(row)).To(HaveLen(2), "the row was split into more than two cells")
	})

	It("renders nothing but a header when the corpus is empty, which is why validateNavRows "+
		"refuses to let that reach a file", func() {
		cfg := navConfig()
		ctx := &Ctx{Root: GinkgoT().TempDir(), Cfg: cfg, BySlug: map[string]Component{}}
		Expect(strings.Count(renderNav(ctx, navSpec(cfg)), "\n")).To(Equal(2))
	})
})

var _ = Describe("relHref", Label("unit"), func() {
	DescribeTable("renders a URL path, never a filesystem one",
		func(from, to, want string) { Expect(relHref(from, to)).To(Equal(want)) },
		Entry("same directory", "docs", "docs/quickstart.md", "quickstart.md"),
		Entry("one deeper", "docs", "docs/01-start/README.md", "01-start/README.md"),
		Entry("one up", "docs/01-start", "docs/INDEX.md", "../INDEX.md"),
		Entry("sideways", "docs/01-start", "docs/02-arch/README.md", "../02-arch/README.md"),
		Entry("out of the docs tree", "docs", "infrastructure/base/README.md", "../infrastructure/base/README.md"),
		Entry("repo root", ".", "README.md", "README.md"),
	)
})

var _ = Describe("nav and region config validation", Label("unit"), func() {
	It("accepts the well-formed artifact", func() {
		Expect(validateArtifacts(navConfig())).To(Succeed())
	})

	DescribeTable("names the key at fault",
		func(mutate func(*Config), want string) {
			cfg := navConfig()
			mutate(cfg)
			err := validateArtifacts(cfg)
			Expect(err).To(HaveOccurred())
			Expect(err.Error()).To(ContainSubstring(want))
		},

		Entry("a nav artifact with no nav block",
			func(c *Config) { s := navSpec(c); s.Nav = nil; c.Artifacts["notes-nav"] = s },
			"artifacts.notes-nav.nav: missing"),

		Entry("an unknown entries kind",
			func(c *Config) {
				s := navSpec(c)
				s.Nav = &NavSource{Entries: "everything", DescriptionKey: "summary"}
				c.Artifacts["notes-nav"] = s
			},
			"artifacts.notes-nav.nav.entries"),

		Entry("no description_key — the silent-fallback trap, refused rather than defaulted",
			func(c *Config) {
				s := navSpec(c)
				s.Nav = &NavSource{Entries: navSiblings}
				c.Artifacts["notes-nav"] = s
			},
			"artifacts.notes-nav.nav.description_key: missing"),

		Entry("a description_key no document in the repo is expected to carry",
			func(c *Config) {
				s := navSpec(c)
				s.Nav = &NavSource{Entries: navSiblings, DescriptionKey: "bluf"}
				c.Artifacts["notes-nav"] = s
			},
			"is not in key_order"),

		Entry("a nav dir that escapes the repository",
			func(c *Config) {
				s := navSpec(c)
				s.Nav = &NavSource{Entries: navSiblings, DescriptionKey: "summary", Dir: "../elsewhere"}
				c.Artifacts["notes-nav"] = s
			},
			"escapes the repository"),

		Entry("a nav block on a renderer that cannot read one",
			func(c *Config) {
				s := navSpec(c)
				s.Renderer = "component-inventory"
				s.Region = ""
				s.Front = map[string]any{"type": "note", "status": "current", "covers": []any{"repo"}}
				c.Artifacts["notes-nav"] = s
			},
			"renders nowhere"),

		Entry("a region name that could match arbitrary prose",
			func(c *Config) { s := navSpec(c); s.Region = "nav --> <!-- x"; c.Artifacts["notes-nav"] = s },
			"artifacts.notes-nav.region"),

		Entry("frontmatter on a marker-owned artifact, which would render nowhere while looking "+
			"validated",
			func(c *Config) {
				s := navSpec(c)
				s.Front = map[string]any{"type": "note"}
				c.Artifacts["notes-nav"] = s
			},
			"artifacts.notes-nav.front: a marker-owned artifact does not write frontmatter"),

		Entry("ticket notes on a marker-owned artifact, which writes no footer",
			func(c *Config) {
				s := navSpec(c)
				s.TicketNotes = map[string]string{"PD-07": "nowhere"}
				c.Artifacts["notes-nav"] = s
			},
			"artifacts.notes-nav.ticket_notes"),

		Entry("two artifacts owning the same region in the same file",
			func(c *Config) {
				s := navSpec(c)
				c.Artifacts["notes-nav-copy"] = s
			},
			"never reach a fixed point"),

		Entry("a whole-file artifact sharing a destination with a marker-owned one",
			func(c *Config) {
				c.Artifacts["notes-whole"] = ArtifactSpec{
					Renderer: "component-inventory",
					Path:     "README.md",
					Front: map[string]any{
						"type": "note", "status": "current", "covers": []any{"repo"},
						"freshness": "live",
					},
				}
			},
			"erases everything else written there"),
	)

	It("refuses a nav whose enumeration matches nothing, because an empty table reads as `this "+
		"section is empty` when it means `the enumeration is wrong`", func() {
		cfg := navConfig()
		spec := navSpec(cfg)
		spec.Nav = &NavSource{Entries: navSiblings, Dir: "no-such-directory", DescriptionKey: "summary"}
		cfg.Artifacts["notes-nav"] = spec

		err := validateNavRows(navCtx(cfg))
		Expect(err).To(HaveOccurred())
		Expect(err.Error()).To(ContainSubstring("artifacts.notes-nav.nav"))
		Expect(err.Error()).To(ContainSubstring("no-such-directory"))
	})
})

func rowNamed(rows []navRow, target string) navRow {
	GinkgoHelper()
	for _, r := range rows {
		if r.Target == target {
			return r
		}
	}
	Fail("no row for " + target)
	return navRow{}
}
