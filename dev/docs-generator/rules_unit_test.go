package main

// Unit specs for rules.go — placement maths and every rule function.
//
// Ctx values are built literally in memory. The two rules that stat the filesystem
// (broken-links, component-path) get a Ctx.Root pointing at a temp tree populated by the spec;
// no spec reads the real repository, so no assertion here can be invalidated by an unrelated
// commit to docs/ or to the cluster manifests.

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

// --- helpers ---------------------------------------------------------------------------------

// unitRulesCtx builds a Ctx with the component graph the placement specs share. Paths are
// plausible but entirely synthetic.
func unitRulesCtx(cfg *Config, docs ...Doc) *Ctx {
	comps := []Component{
		{Slug: "cilium", Path: "infrastructure/base/cilium"},
		{Slug: "traefik", Path: "infrastructure/base/traefik"},
		{Slug: "kyverno", Path: "infrastructure/base/security/kyverno"},
		{Slug: "falco", Path: "infrastructure/base/security/falco"},
		{Slug: "arr-stack", Path: "applications/arr-stack"},
	}
	bySlug := map[string]Component{}
	for _, c := range comps {
		bySlug[c.Slug] = c
	}
	if cfg == nil {
		cfg = &Config{}
	}
	return &Ctx{Root: "/nonexistent-root", Cfg: cfg, Docs: docs, Components: comps, BySlug: bySlug}
}

func unitMessages(fs []Finding) []string {
	out := make([]string, 0, len(fs))
	for _, f := range fs {
		out = append(out, f.Message)
	}
	return out
}

func unitRules(fs []Finding) []string {
	out := make([]string, 0, len(fs))
	for _, f := range fs {
		out = append(out, f.Rule)
	}
	return out
}

// --- resolveCover ------------------------------------------------------------------------------

var _ = Describe("resolveCover", Label("unit"), func() {
	It("refuses to resolve the reserved token `cluster`, which is how a cross-cutting doc is forced into docs/ instead of being colocated somewhere arbitrary", func() {
		p, ok := resolveCover(unitRulesCtx(nil), "cluster")

		Expect(ok).To(BeFalse())
		Expect(p).To(BeEmpty())
	})

	It("refuses the reserved token `repo` for the same reason", func() {
		_, ok := resolveCover(unitRulesCtx(nil), "repo")

		Expect(ok).To(BeFalse())
	})

	It("accepts a literal `path:` escape hatch and trims its trailing slash, so `path:docs/` and `path:docs` cannot disagree about the expected location", func() {
		p, ok := resolveCover(unitRulesCtx(nil), "path:infrastructure/base/registry/")

		Expect(ok).To(BeTrue())
		Expect(p).To(Equal("infrastructure/base/registry"))
	})

	It("resolves a known slug to that component's path, which is the whole point of slug stability", func() {
		p, ok := resolveCover(unitRulesCtx(nil), "cilium")

		Expect(ok).To(BeTrue())
		Expect(p).To(Equal("infrastructure/base/cilium"))
	})

	It("does not resolve an unknown slug, so a typo cannot quietly pull a doc toward some other component's directory", func() {
		p, ok := resolveCover(unitRulesCtx(nil), "cillium")

		Expect(ok).To(BeFalse())
		Expect(p).To(BeEmpty())
	})

	// The two specs above are indistinguishable from "unknown slug" while no component is
	// actually named `cluster` or `repo`: deleting the reserved-token guard outright leaves
	// both green, because the lookup that replaces it also misses. Registering a component
	// whose slug IS the reserved word is the only fixture that separates RESERVED from
	// UNKNOWN, and reserved has to win — a doc scoped to the whole cluster belongs in docs/
	// even in a repo that happens to deploy something called `cluster`.
	DescribeTable("keeps a reserved token reserved even when a real component claims that exact slug",
		func(token string) {
			ctx := unitRulesCtx(nil)
			claimed := Component{Slug: token, Path: "infrastructure/base/" + token}
			ctx.Components = append(ctx.Components, claimed)
			ctx.BySlug[token] = claimed

			p, ok := resolveCover(ctx, token)

			Expect(ok).To(BeFalse(),
				"resolving it would colocate every cross-cutting doc into that component's directory")
			Expect(p).To(BeEmpty())
		},
		Entry("cluster", "cluster"),
		Entry("repo", "repo"),
	)

	It("keeps ExpectedLocation on docs/ for a reserved token a component has claimed, because the reservation has to survive the whole placement path and not just resolveCover", func() {
		ctx := unitRulesCtx(&Config{GroupingRoots: []string{"infrastructure", "infrastructure/base"}})
		claimed := Component{Slug: "cluster", Path: "infrastructure/base/cluster"}
		ctx.Components = append(ctx.Components, claimed)
		ctx.BySlug["cluster"] = claimed

		Expect(ExpectedLocation(ctx, []string{"cluster"})).To(Equal("docs/"))
	})
})

// --- longestCommonAncestor -----------------------------------------------------------------

var _ = Describe("longestCommonAncestor", Label("unit"), func() {
	DescribeTable("finds the shared directory a multi-component doc belongs in",
		func(paths []string, want string) {
			Expect(longestCommonAncestor(paths)).To(Equal(want))
		},
		Entry("no paths yields an empty ancestor, which the caller reads as cross-cutting", nil, ""),
		Entry("a single path is its own ancestor, so a one-component doc colocates exactly",
			[]string{"infrastructure/base/cilium"}, "infrastructure/base/cilium"),
		Entry("two siblings share their parent — a README covering both belongs there, not in docs/",
			[]string{"infrastructure/base/security/kyverno", "infrastructure/base/security/falco"},
			"infrastructure/base/security"),
		Entry("three paths at different depths share the deepest common prefix",
			[]string{"infrastructure/base/a/b", "infrastructure/base/a", "infrastructure/base/a/c"},
			"infrastructure/base/a"),
		Entry("paths in different top-level trees share nothing at all",
			[]string{"infrastructure/base/cilium", "applications/arr-stack"}, ""),
		Entry("identical paths return that path unchanged",
			[]string{"applications/arr-stack", "applications/arr-stack"}, "applications/arr-stack"),
		Entry("comparison is per SEGMENT, so `base` and `baseline` do not share a partial segment",
			[]string{"infra/base", "infra/baseline"}, "infra"),
	)
})

// --- ExpectedLocation --------------------------------------------------------------------------

var _ = Describe("ExpectedLocation", Label("unit"), func() {
	groupingCfg := func() *Config {
		return &Config{GroupingRoots: []string{"", ".", "infrastructure", "infrastructure/base", "applications"}}
	}

	It("sends a doc covering exactly one component to that component's directory — collapsing this to docs/ would switch colocation off entirely", func() {
		ctx := unitRulesCtx(groupingCfg())

		Expect(ExpectedLocation(ctx, []string{"cilium"})).To(Equal("infrastructure/base/cilium"))
	})

	It("sends a doc covering two siblings to their shared parent, because a count of slugs would wrongly exile it to docs/", func() {
		ctx := unitRulesCtx(groupingCfg())

		Expect(ExpectedLocation(ctx, []string{"kyverno", "falco"})).To(Equal("infrastructure/base/security"))
	})

	It("sends a doc to docs/ when any covered token is reserved, even alongside a real component, because a cross-cutting scope wins", func() {
		ctx := unitRulesCtx(groupingCfg())

		Expect(ExpectedLocation(ctx, []string{"cilium", "cluster"})).To(Equal("docs/"))
		Expect(ExpectedLocation(ctx, []string{"repo"})).To(Equal("docs/"))
	})

	It("sends a doc to docs/ when the ancestor is a configured grouping root, because `infrastructure/base` is a container rather than a home", func() {
		ctx := unitRulesCtx(groupingCfg())

		Expect(ExpectedLocation(ctx, []string{"cilium", "traefik"})).To(Equal("docs/"))
	})

	It("sends a doc to docs/ when its components share no ancestor at all", func() {
		ctx := unitRulesCtx(groupingCfg())

		Expect(ExpectedLocation(ctx, []string{"cilium", "arr-stack"})).To(Equal("docs/"))
	})

	It("sends a doc to docs/ when nothing resolves, so a doc full of typos is never colocated by accident", func() {
		ctx := unitRulesCtx(groupingCfg())

		Expect(ExpectedLocation(ctx, []string{"cillium", "treafik"})).To(Equal("docs/"))
	})

	It("ignores unresolvable tokens alongside resolvable ones rather than letting one typo drag the ancestor up to the repo root", func() {
		ctx := unitRulesCtx(groupingCfg())

		Expect(ExpectedLocation(ctx, []string{"kyverno", "nope", "falco"})).To(Equal("infrastructure/base/security"))
	})

	It("honours a `path:` token as a location on its own terms", func() {
		ctx := unitRulesCtx(groupingCfg())

		Expect(ExpectedLocation(ctx, []string{"path:bootstrap/argocd"})).To(Equal("bootstrap/argocd"))
	})

	It("does not treat an unconfigured directory as a grouping root, so removing an entry from grouping_roots genuinely changes the verdict", func() {
		ctx := unitRulesCtx(&Config{GroupingRoots: []string{"infrastructure"}})

		Expect(ExpectedLocation(ctx, []string{"cilium", "traefik"})).To(Equal("infrastructure/base"))
	})
})

// --- keyOrderViolation -------------------------------------------------------------------------

var _ = Describe("keyOrderViolation", Label("unit"), func() {
	canonical := []string{"type", "status", "covers", "freshness", "tickets"}

	It("accepts keys already in canonical order", func() {
		Expect(keyOrderViolation([]string{"type", "status", "covers"}, canonical)).To(BeEmpty())
	})

	It("accepts a subset in canonical order, because not every doc carries every optional key", func() {
		Expect(keyOrderViolation([]string{"type", "tickets"}, canonical)).To(BeEmpty())
	})

	It("REJECTS keys out of canonical order and names both the offender and the key it should precede, so the fix is mechanical", func() {
		msg := keyOrderViolation([]string{"status", "type", "covers"}, canonical)

		Expect(msg).NotTo(BeEmpty(), "accepting out-of-order keys would make key_order decorative")
		Expect(msg).To(ContainSubstring("`type`"))
		Expect(msg).To(ContainSubstring("`status`"))
	})

	It("rejects a key that jumps backwards past several canonical keys", func() {
		Expect(keyOrderViolation([]string{"tickets", "type"}, canonical)).NotTo(BeEmpty())
	})

	It("ignores keys absent from the canonical list, so a repo-specific extra key is not forced into a position nobody defined", func() {
		Expect(keyOrderViolation([]string{"type", "owner", "status", "blurb", "covers"}, canonical)).To(BeEmpty())
	})

	It("accepts an empty key list, since a doc with no frontmatter keys violates nothing", func() {
		Expect(keyOrderViolation(nil, canonical)).To(BeEmpty())
	})

	It("accepts a repeated key, because a duplicate is a YAML problem rather than an ordering one", func() {
		Expect(keyOrderViolation([]string{"type", "type", "status"}, canonical)).To(BeEmpty())
	})
})

// --- ruleBrokenLinks ---------------------------------------------------------------------------

var _ = Describe("ruleBrokenLinks", Label("unit"), func() {
	var root string

	BeforeEach(func() {
		root = GinkgoT().TempDir()
		unitWrite(root, "docs/exists.md", "# Exists\n")
		unitWrite(root, "docs/sub/nested.md", "# Nested\n")
	})

	It("resolves link targets relative to the LINKING document, not the repo root, which is the only interpretation markdown viewers use", func() {
		doc := MakeDoc("docs/index.md", "[ok](./exists.md) and [nested](./sub/nested.md)\n")
		ctx := unitRulesCtx(nil, doc)
		ctx.Root = root

		Expect(ruleBrokenLinks(ctx)).To(BeEmpty())
	})

	It("reports a target that is not on disk, quoting the link exactly as written so it can be grepped", func() {
		doc := MakeDoc("docs/index.md", "[gone](./missing.md)\n")
		ctx := unitRulesCtx(nil, doc)
		ctx.Root = root

		findings := ruleBrokenLinks(ctx)

		Expect(findings).To(HaveLen(1))
		Expect(findings[0].Rule).To(Equal("broken-links"))
		Expect(findings[0].Path).To(Equal("docs/index.md"))
		Expect(findings[0].Message).To(Equal("dead link -> ./missing.md"))
	})

	It("checks only the file part of a target with a fragment, because the anchor cannot be stat-ed", func() {
		ctx := unitRulesCtx(nil, MakeDoc("docs/index.md", "[ok](./exists.md#a-heading)\n"))
		ctx.Root = root

		Expect(ruleBrokenLinks(ctx)).To(BeEmpty())
	})

	It("still reports a dead target that carries a fragment, rather than letting `#` act as an exemption", func() {
		ctx := unitRulesCtx(nil, MakeDoc("docs/index.md", "[gone](./missing.md#a-heading)\n"))
		ctx.Root = root

		Expect(ruleBrokenLinks(ctx)).To(HaveLen(1))
	})

	It("takes its severity from config, because a repo adopting the tool must be able to land it yellow and promote it later", func() {
		cfg := &Config{Rules: map[string]Rule{"broken-links": {Enabled: true, Severity: "error"}}}
		ctx := unitRulesCtx(cfg, MakeDoc("docs/index.md", "[gone](./missing.md)\n"))
		ctx.Root = root

		Expect(ruleBrokenLinks(ctx)[0].Severity).To(Equal("error"))
	})

	It("accepts a link to a directory, since a directory link is how a section README is usually referenced", func() {
		ctx := unitRulesCtx(nil, MakeDoc("docs/index.md", "[section](./sub)\n"))
		ctx.Root = root

		Expect(ruleBrokenLinks(ctx)).To(BeEmpty())
	})
})

// --- ruleFrontmatterSchema ---------------------------------------------------------------------

var _ = Describe("ruleFrontmatterSchema", Label("unit"), func() {
	schemaCfg := func() *Config {
		return &Config{
			DocTypes:   []string{"reference", "runbook", "nav"},
			Statuses:   []string{"current", "superseded"},
			Freshness:  []string{"live", "review"},
			BannedKeys: map[string]string{"title": "markdownlint reads it as the document title"},
			KeyOrder:   []string{"type", "status", "covers", "freshness"},
		}
	}
	complete := "---\ntype: reference\nstatus: current\ncovers:\n  - cilium\n---\n\n# Doc\n"

	It("says nothing about a complete, well-ordered document", func() {
		ctx := unitRulesCtx(schemaCfg(), MakeDoc("docs/a.md", complete))

		Expect(ruleFrontmatterSchema(ctx)).To(BeEmpty())
	})

	It("skips a document with no frontmatter at all, because those are the migration worklist and not schema errors", func() {
		ctx := unitRulesCtx(schemaCfg(), MakeDoc("docs/a.md", "# Doc\n"))

		Expect(ruleFrontmatterSchema(ctx)).To(BeEmpty())
	})

	It("reports a parse error and stops there, so one malformed block does not also emit three misleading missing-key findings", func() {
		ctx := unitRulesCtx(schemaCfg(), MakeDoc("docs/a.md", "---\ncovers: [unclosed\n---\n# Doc\n"))

		findings := ruleFrontmatterSchema(ctx)

		Expect(findings).To(HaveLen(1))
		Expect(findings[0].Message).To(HavePrefix("invalid YAML in frontmatter"))
	})

	It("reports each missing required key separately, so the fix list is explicit", func() {
		ctx := unitRulesCtx(schemaCfg(), MakeDoc("docs/a.md", "---\nblurb: hi\n---\n# Doc\n"))

		Expect(unitMessages(ruleFrontmatterSchema(ctx))).To(ConsistOf(
			"missing required `type`",
			"missing required `status`",
			"missing required `covers`",
		))
	})

	It("reports a banned key together with the configured reason, because a bare ban invites someone to add it back", func() {
		ctx := unitRulesCtx(schemaCfg(), MakeDoc("docs/a.md",
			"---\ntitle: Doc\ntype: reference\nstatus: current\ncovers:\n  - cilium\n---\n# Doc\n"))

		Expect(unitMessages(ruleFrontmatterSchema(ctx))).To(ContainElement(
			"banned key `title` — markdownlint reads it as the document title"))
	})

	// Asserted as the WHOLE Finding, not as a substring of every message joined together.
	// Joining and substring-matching cannot tell a finding attributed to the right doc and the
	// right rule from one attributed to neither — blanking Finding.Path, which is the only
	// thing telling a reader WHICH file to edit, left the old assertion green. The `not in
	// [...]` tail is pinned too: it is the list a human reads to find the legal values, and
	// it is exactly the part a substring match throws away.
	DescribeTable("reports an enum value outside the configured vocabulary, since an unchecked enum is just a free-text field",
		func(front, wantMessage string) {
			ctx := unitRulesCtx(schemaCfg(), MakeDoc("docs/a.md", "---\n"+front+"---\n# Doc\n"))

			Expect(ruleFrontmatterSchema(ctx)).To(ConsistOf(Finding{
				Rule:     "frontmatter-schema",
				Severity: "warn",
				Path:     "docs/a.md",
				Message:  wantMessage,
			}))
		},
		Entry("an unknown type", "type: manifesto\nstatus: current\ncovers:\n  - cilium\n",
			"type `manifesto` not in [reference runbook nav]"),
		Entry("an unknown status", "type: reference\nstatus: vibes\ncovers:\n  - cilium\n",
			"status `vibes` not in [current superseded]"),
		Entry("an unknown freshness", "type: reference\nstatus: current\ncovers:\n  - cilium\nfreshness: eventually\n",
			"freshness `eventually` not in [live review]"),
	)

	It("keeps a scalar covers value usable but reports it as unclean, because prettier explodes flow sequences and the file would churn on every format run", func() {
		ctx := unitRulesCtx(schemaCfg(), MakeDoc("docs/a.md", "---\ntype: reference\nstatus: current\ncovers: cilium\n---\n# Doc\n"))

		Expect(unitMessages(ruleFrontmatterSchema(ctx))).To(ContainElement(
			"covers must be a block sequence of strings (prettier explodes flow sequences)"))
	})

	It("demands superseded_by on a superseded doc, because a tombstone with no forwarding address is worse than no tombstone", func() {
		ctx := unitRulesCtx(schemaCfg(), MakeDoc("docs/a.md", "---\ntype: reference\nstatus: superseded\ncovers:\n  - cilium\n---\n# Doc\n"))

		Expect(unitMessages(ruleFrontmatterSchema(ctx))).To(ContainElement("status: superseded requires superseded_by"))
	})

	It("accepts a superseded doc that names its successor", func() {
		ctx := unitRulesCtx(schemaCfg(), MakeDoc("docs/a.md",
			"---\ntype: reference\nstatus: superseded\ncovers:\n  - cilium\nsuperseded_by: docs/new.md\n---\n# Doc\n"))

		Expect(ruleFrontmatterSchema(ctx)).To(BeEmpty())
	})

	It("reports an empty superseded_by as no successor at all", func() {
		ctx := unitRulesCtx(schemaCfg(), MakeDoc("docs/a.md",
			"---\ntype: reference\nstatus: superseded\ncovers:\n  - cilium\nsuperseded_by: \"\"\n---\n# Doc\n"))

		Expect(unitMessages(ruleFrontmatterSchema(ctx))).To(ContainElement("status: superseded requires superseded_by"))
	})

	It("reports out-of-order keys, which is what keeps a generated frontmatter block byte-stable", func() {
		ctx := unitRulesCtx(schemaCfg(), MakeDoc("docs/a.md", "---\nstatus: current\ntype: reference\ncovers:\n  - cilium\n---\n# Doc\n"))

		// Whole finding again, and the whole message: naming BOTH keys plus the canonical order
		// is what makes the fix mechanical, and a substring match on "should come before" holds
		// even when the message names the wrong pair or the finding lands on the wrong file.
		Expect(ruleFrontmatterSchema(ctx)).To(ConsistOf(Finding{
			Rule:     "frontmatter-schema",
			Severity: "warn",
			Path:     "docs/a.md",
			Message:  "key `type` should come before `status` (canonical order: [type status covers freshness])",
		}))
	})

	It("skips the order check entirely when no canonical order is configured, so a porting repo is not forced into ours", func() {
		cfg := schemaCfg()
		cfg.KeyOrder = nil
		ctx := unitRulesCtx(cfg, MakeDoc("docs/a.md", "---\nstatus: current\ntype: reference\ncovers:\n  - cilium\n---\n# Doc\n"))

		Expect(ruleFrontmatterSchema(ctx)).To(BeEmpty())
	})

	It("skips an enum check whose vocabulary is unconfigured, rather than rejecting every value", func() {
		ctx := unitRulesCtx(&Config{}, MakeDoc("docs/a.md", "---\ntype: whatever\nstatus: whatever\ncovers:\n  - cilium\n---\n# Doc\n"))

		Expect(ruleFrontmatterSchema(ctx)).To(BeEmpty())
	})
})

// --- ruleCoversResolves ------------------------------------------------------------------------

var _ = Describe("ruleCoversResolves", Label("unit"), func() {
	It("reports a covers token that matches no component, which is how a renamed component is caught before the doc silently points at nothing", func() {
		ctx := unitRulesCtx(nil, MakeDoc("docs/a.md", "---\ncovers:\n  - cillium\n---\n# Doc\n"))

		findings := ruleCoversResolves(ctx)

		Expect(findings).To(HaveLen(1))
		Expect(findings[0].Rule).To(Equal("covers-resolves"))
		Expect(findings[0].Message).To(Equal("`cillium` matches no known component"))
	})

	DescribeTable("accepts every token form that is resolvable by design",
		func(token string) {
			// A real root, because a `path:` cover is now checked for EXISTENCE. It used to be
			// trusted unconditionally, which let a typo silently feed both the colocation
			// verdict and the staleness subject.
			root := GinkgoT().TempDir()
			Expect(os.MkdirAll(filepath.Join(root, "docs/07-reference"), 0o755)).To(Succeed())
			ctx := unitRulesCtx(nil, MakeDoc("docs/a.md", "---\ncovers:\n  - "+token+"\n---\n# Doc\n"))
			ctx.Root = root

			Expect(ruleCoversResolves(ctx)).To(BeEmpty())
		},
		Entry("a known slug", "cilium"),
		Entry("the reserved token cluster", "cluster"),
		Entry("the reserved token repo", "repo"),
		Entry("a path: escape hatch, which deliberately names a directory with no component", "path:docs/07-reference"),
	)

	DescribeTable("rejects a path: cover that names nothing real, because an unchecked path feeds the colocation verdict AND the staleness subject",
		func(token, want string) {
			root := GinkgoT().TempDir()
			ctx := unitRulesCtx(nil, MakeDoc("docs/a.md", "---\ncovers:\n  - "+token+"\n---\n# Doc\n"))
			ctx.Root = root

			Expect(unitMessages(ruleCoversResolves(ctx))).To(ContainElement(want))
		},
		Entry("a path that does not exist", "path:services/gone", "`path:services/gone` does not exist on disk"),
		Entry("a path escaping the repository", "path:../../etc/passwd", "`path:../../etc/passwd` escapes the repository"),
		// Quoted on purpose: bare `- path:` is a YAML MAP (`{path: null}`), not the string
		// "path:", so an unquoted fixture would test a different thing entirely.
		Entry("an empty path", `"path:"`, "`path:` with no path"),
	)

	It("skips a doc with no frontmatter, because an unmigrated doc has nothing to resolve", func() {
		ctx := unitRulesCtx(nil, MakeDoc("docs/a.md", "# Doc\n"))

		Expect(ruleCoversResolves(ctx)).To(BeEmpty())
	})

	It("still checks a scalar covers value, so a shape violation does not also buy an exemption from resolution", func() {
		ctx := unitRulesCtx(nil, MakeDoc("docs/a.md", "---\ncovers: cillium\n---\n# Doc\n"))

		Expect(ruleCoversResolves(ctx)).To(HaveLen(1))
	})

	It("reports every unresolvable token in one doc, not just the first", func() {
		ctx := unitRulesCtx(nil, MakeDoc("docs/a.md", "---\ncovers:\n  - cillium\n  - cilium\n  - treafik\n---\n# Doc\n"))

		Expect(unitMessages(ruleCoversResolves(ctx))).To(ConsistOf(
			"`cillium` matches no known component",
			"`treafik` matches no known component",
		))
	})
})

// --- ruleComponentPath / ruleComponentShape ----------------------------------------------------

var _ = Describe("ruleComponentPath", Label("unit"), func() {
	It("reports a Kustomization pointing at a directory that does not exist, which Flux fails quietly while the last-applied state keeps running", func() {
		root := GinkgoT().TempDir()
		unitWrite(root, "infrastructure/base/cilium/kustomization.yaml", "resources: []\n")
		ctx := unitRulesCtx(nil)
		ctx.Root = root
		ctx.Components = []Component{
			{Slug: "cilium", Path: "infrastructure/base/cilium", Source: "clusters/test/cilium.yaml"},
			{Slug: "ghost", Path: "infrastructure/base/ghost", Source: "clusters/test/ghost.yaml"},
		}

		findings := ruleComponentPath(ctx)

		Expect(findings).To(HaveLen(1))
		Expect(findings[0].Message).To(Equal("path `infrastructure/base/ghost` does not exist on disk"))
		Expect(findings[0].Path).To(Equal("clusters/test/ghost.yaml"),
			"the finding must point at the manifest to edit, not at the directory that is missing")
	})

	It("says nothing when every component path exists", func() {
		root := GinkgoT().TempDir()
		Expect(os.MkdirAll(filepath.Join(root, "applications/arr-stack"), 0o755)).To(Succeed())
		ctx := unitRulesCtx(nil)
		ctx.Root = root
		ctx.Components = []Component{{Slug: "arr-stack", Path: "applications/arr-stack", Source: "clusters/test/apps.yaml"}}

		Expect(ruleComponentPath(ctx)).To(BeEmpty())
	})
})

var _ = Describe("ruleComponentShape", Label("unit"), func() {
	DescribeTable("reports one slug wrapping many deployable units, while leaving a legitimate grouping directory alone — its children each have their own slug and are counted separately",
		func(nested int, wantFinding bool) {
			ctx := unitRulesCtx(nil)
			ctx.Components = []Component{{Slug: "monitoring", Path: "infrastructure/base/monitoring", Nested: nested}}

			findings := ruleComponentShape(ctx)

			if !wantFinding {
				Expect(findings).To(BeEmpty())
				return
			}
			Expect(findings).To(HaveLen(1))
			Expect(findings[0].Path).To(Equal("infrastructure/base/monitoring"))
			Expect(findings[0].Message).To(ContainSubstring("wraps"))
		},
		Entry("one nested kustomization is the normal case", 1, false),
		Entry("three is still at the threshold and is not reported", 3, false),
		Entry("four exceeds the threshold and is reported", 4, true),
		Entry("seven is the shape this check was written for", 7, true),
	)
})

// --- ruleColocation ----------------------------------------------------------------------------

var _ = Describe("ruleColocation", Label("unit"), func() {
	colocationCfg := func() *Config {
		return &Config{GroupingRoots: []string{"", ".", "infrastructure", "infrastructure/base"}}
	}
	covers := func(tokens ...string) string {
		s := "---\ncovers:\n"
		for _, t := range tokens {
			s += "  - " + t + "\n"
		}
		return s + "---\n\n# Doc\n"
	}

	It("says nothing about a doc already sitting in its component directory", func() {
		ctx := unitRulesCtx(colocationCfg(), MakeDoc("infrastructure/base/cilium/README.md", covers("cilium")))

		Expect(ruleColocation(ctx)).To(BeEmpty())
	})

	It("reports a component-scoped doc parked in docs/, naming the directory it belongs in", func() {
		ctx := unitRulesCtx(colocationCfg(), MakeDoc("docs/02-architecture/cilium.md", covers("cilium")))

		findings := ruleColocation(ctx)

		Expect(findings).To(HaveLen(1))
		Expect(findings[0].Rule).To(Equal("colocation"))
		Expect(findings[0].Message).To(Equal("should colocate at infrastructure/base/cilium/"))
	})

	It("accepts a doc nested deeper than the expected directory, because a subdirectory of the component is still inside it", func() {
		ctx := unitRulesCtx(colocationCfg(), MakeDoc("infrastructure/base/cilium/docs/tuning.md", covers("cilium")))

		Expect(ruleColocation(ctx)).To(BeEmpty())
	})

	It("reports a cross-cutting doc that lives outside docs/, since `cluster` scope has no component home", func() {
		ctx := unitRulesCtx(colocationCfg(), MakeDoc("infrastructure/base/cilium/OVERVIEW.md", covers("cluster")))

		Expect(unitMessages(ruleColocation(ctx))).To(ConsistOf("cross-cutting scope — belongs under docs/"))
	})

	It("accepts a cross-cutting doc that already lives under docs/", func() {
		ctx := unitRulesCtx(colocationCfg(), MakeDoc("docs/02-architecture/dual-gitops.md", covers("cluster")))

		Expect(ruleColocation(ctx)).To(BeEmpty())
	})

	It("suppresses the finding when `pinned` carries a reason, which is the migration mechanism — an exemption that records WHY", func() {
		doc := MakeDoc("docs/02-architecture/cilium.md",
			"---\npinned: linked from the public README\ncovers:\n  - cilium\n---\n\n# Doc\n")
		ctx := unitRulesCtx(colocationCfg(), doc)

		Expect(ruleColocation(ctx)).To(BeEmpty())
	})

	It("does NOT suppress on an empty pinned value, so `pinned: \"\"` cannot be used as a silent opt-out", func() {
		doc := MakeDoc("docs/02-architecture/cilium.md",
			"---\npinned: \"\"\ncovers:\n  - cilium\n---\n\n# Doc\n")
		ctx := unitRulesCtx(colocationCfg(), doc)

		Expect(ruleColocation(ctx)).To(HaveLen(1))
	})

	It("skips a doc with no covers, because placement is undecidable without a declared scope", func() {
		ctx := unitRulesCtx(colocationCfg(), MakeDoc("README.md", "---\ntype: nav\n---\n\n# Doc\n"))

		Expect(ruleColocation(ctx)).To(BeEmpty())
	})

	It("colocates a doc covering two siblings at their shared parent rather than exiling it to docs/", func() {
		ctx := unitRulesCtx(colocationCfg(), MakeDoc("docs/security.md", covers("kyverno", "falco")))

		Expect(unitMessages(ruleColocation(ctx))).To(ConsistOf("should colocate at infrastructure/base/security/"))
	})
})

// --- ruleTicketsInBody -------------------------------------------------------------------------

var _ = Describe("ruleTicketsInBody", Label("unit"), func() {
	It("reports a ticket declared in frontmatter that appears nowhere in the document text, so the Related Issues footer cannot drift from the metadata", func() {
		doc := MakeDoc("docs/a.md",
			"---\ntickets:\n  - TALOS-9dt\n---\n\n# Doc\n\nprose with no ticket reference\n")
		ctx := unitRulesCtx(nil, doc)

		findings := ruleTicketsInBody(ctx)

		Expect(findings).To(HaveLen(1))
		Expect(findings[0].Rule).To(Equal("tickets-in-body"))
		Expect(findings[0].Message).To(Equal("TALOS-9dt in frontmatter but not in body"))
	})

	// Built through MakeDoc rather than as a Doc literal on purpose. A hand-built literal can set
	// Text without Body — a state the real parser can never produce — and a rule reading the other
	// field then passes or fails for reasons the production path would never reproduce. Both of
	// these specs were originally literals and both silently encoded the tautology above.
	It("says nothing when the body cites the ticket, so a correctly cross-referenced doc is not nagged", func() {
		doc := MakeDoc("docs/a.md", "---\ntickets:\n  - TALOS-9dt\n---\n\n# Doc\n\n## Related Issues\n\n- TALOS-9dt\n")

		Expect(ruleTicketsInBody(unitRulesCtx(nil, doc))).To(BeEmpty())
	})

	It("reports each missing ticket independently, so one cited ticket does not mask an uncited one", func() {
		doc := MakeDoc("docs/a.md", "---\ntickets:\n  - TALOS-9dt\n  - CILIUM-h2b\n---\n\n# Doc\n\n- TALOS-9dt\n")

		Expect(unitMessages(ruleTicketsInBody(unitRulesCtx(nil, doc)))).To(ConsistOf(
			"CILIUM-h2b in frontmatter but not in body"))
	})

	It("skips a doc with no frontmatter and a doc with no tickets key", func() {
		ctx := unitRulesCtx(nil,
			MakeDoc("docs/a.md", "# Doc\n"),
			MakeDoc("docs/b.md", "---\ntype: reference\n---\n\n# Doc\n"))

		Expect(ruleTicketsInBody(ctx)).To(BeEmpty())
	})

	// This spec exists because the rule was a TAUTOLOGY until it was fixed: it scanned Doc.Text,
	// which still contains the frontmatter block the ticket IDs were parsed out of, so every
	// ticket always looked present and the rule could never fire. It was found by writing this
	// suite, not by reading the code. Keep the assertion pointed at the frontmatter-only case —
	// that is the single case the whole rule exists to catch.
	It("fires for a ticket that appears ONLY in frontmatter, which is the case the rule exists for", func() {
		doc := MakeDoc("docs/a.md", "---\ntickets:\n  - TALOS-9dt\n---\n\n# Doc\n\nprose with no ticket reference\n")

		Expect(unitMessages(ruleTicketsInBody(unitRulesCtx(nil, doc)))).To(
			ContainElement("TALOS-9dt in frontmatter but not in body"))
	})

	It("stays silent when the body does mention the ticket, so a correctly cross-referenced doc is not nagged", func() {
		doc := MakeDoc("docs/a.md", "---\ntickets:\n  - TALOS-9dt\n---\n\n# Doc\n\nTracked as TALOS-9dt.\n")

		Expect(ruleTicketsInBody(unitRulesCtx(nil, doc))).To(BeEmpty())
	})
})

// These four specs exist because ruleTaxonomyStructure scanned Doc.Text — which still contains
// the frontmatter — so every structural marker could be satisfied by metadata rather than by the
// document's actual content. A runbook with an EMPTY body and the right words in its frontmatter
// produced zero findings. A mutation audit found it; no spec did, because every existing fixture
// put the markers in the body where Text and Body agree.
//
// The shape to copy when adding a structural check: put the marker ONLY in the frontmatter and
// assert the finding still fires. A check that cannot distinguish metadata from content is not
// checking the document.
var _ = Describe("ruleTaxonomyStructure frontmatter leak", Label("unit"), func() {
	leakCfg := func() *Config {
		return &Config{
			TypeRequires:   map[string][]string{"runbook": {"## TL;DR"}},
			RequiredFooter: "## Related Issues",
		}
	}

	It("still requires a type-mandated section when only the frontmatter mentions it", func() {
		ctx := unitRulesCtx(leakCfg(), MakeDoc("docs/a.md",
			"---\ntype: runbook\nblurb: \"see ## TL;DR for the summary\"\n---\n\n# Runbook\n\n1. step\n\n## Related Issues\n"))

		Expect(unitMessages(ruleTaxonomyStructure(ctx))).To(
			ContainElement("type `runbook` expects a `## TL;DR` section"))
	})

	It("still requires the footer when only the frontmatter mentions it", func() {
		ctx := unitRulesCtx(leakCfg(), MakeDoc("docs/a.md",
			"---\ntype: reference\nblurb: \"tracked under ## Related Issues\"\n---\n\n# Ref\n\nregenerated by docsgen\n"))

		Expect(unitMessages(ruleTaxonomyStructure(ctx))).To(
			ContainElement("missing `## Related Issues` footer"))
	})

	It("still requires an ordered procedure when only the frontmatter contains one", func() {
		ctx := unitRulesCtx(leakCfg(), MakeDoc("docs/a.md",
			"---\ntype: runbook\nblurb: |\n  1. this is metadata, not a procedure\n---\n\n# Runbook\n\n## TL;DR\n\nprose\n\n## Related Issues\n"))

		Expect(unitMessages(ruleTaxonomyStructure(ctx))).To(
			ContainElement("runbook has no ordered procedure"))
	})

	It("still requires a reference to say how it regenerates when only the frontmatter says so", func() {
		ctx := unitRulesCtx(leakCfg(), MakeDoc("docs/a.md",
			"---\ntype: reference\nblurb: \"generated by docsgen\"\n---\n\n# Ref\n\nplain prose\n\n## Related Issues\n"))

		Expect(unitMessages(ruleTaxonomyStructure(ctx))).To(
			ContainElement("reference should state how it is regenerated"))
	})
})

// --- ruleTaxonomyStructure ---------------------------------------------------------------------

var _ = Describe("ruleTaxonomyStructure", Label("unit"), func() {
	taxonomyCfg := func() *Config {
		return &Config{
			TypeRequires:   map[string][]string{"runbook": {"## TL;DR"}, "architecture": {"## TL;DR"}},
			RequiredFooter: "## Related Issues",
		}
	}

	It("skips a doc with no type, because an untyped doc makes no structural promise", func() {
		ctx := unitRulesCtx(taxonomyCfg(), MakeDoc("docs/a.md", "---\nstatus: current\n---\n\nprose\n"))

		Expect(ruleTaxonomyStructure(ctx)).To(BeEmpty())
	})

	It("reports a typed doc with no H1, because every doc leads with one and markdownlint MD041 agrees", func() {
		ctx := unitRulesCtx(taxonomyCfg(), MakeDoc("docs/a.md",
			"---\ntype: reference\n---\n\n## Section\n\nregenerated by docsgen\n\n## Related Issues\n"))

		Expect(unitMessages(ruleTaxonomyStructure(ctx))).To(ContainElement("no H1 — every doc leads with one"))
	})

	It("reports a missing type-required section, which is what stops `type:` being a decorative label", func() {
		ctx := unitRulesCtx(taxonomyCfg(), MakeDoc("docs/a.md",
			"---\ntype: runbook\n---\n\n# Runbook\n\n1. do the thing\n\n## Related Issues\n"))

		Expect(unitMessages(ruleTaxonomyStructure(ctx))).To(ContainElement("type `runbook` expects a `## TL;DR` section"))
	})

	It("matches a required section case-insensitively, so `## tl;dr` is not reported as missing", func() {
		ctx := unitRulesCtx(taxonomyCfg(), MakeDoc("docs/a.md",
			"---\ntype: runbook\n---\n\n# Runbook\n\n## tl;dr\n\n1. do the thing\n\n## Related Issues\n"))

		Expect(ruleTaxonomyStructure(ctx)).To(BeEmpty())
	})

	It("reports a runbook with no ordered procedure, because a runbook without numbered steps is a description rather than a procedure", func() {
		ctx := unitRulesCtx(taxonomyCfg(), MakeDoc("docs/a.md",
			"---\ntype: runbook\n---\n\n# Runbook\n\n## TL;DR\n\n- do the thing\n\n## Related Issues\n"))

		Expect(unitMessages(ruleTaxonomyStructure(ctx))).To(ContainElement("runbook has no ordered procedure"))
	})

	It("reports a reference that does not say how it is regenerated, because a stale generated table with no provenance is actively misleading", func() {
		ctx := unitRulesCtx(taxonomyCfg(), MakeDoc("docs/a.md",
			"---\ntype: reference\n---\n\n# Reference\n\n| a | b |\n\n## Related Issues\n"))

		Expect(unitMessages(ruleTaxonomyStructure(ctx))).To(ContainElement("reference should state how it is regenerated"))
	})

	It("accepts a reference that names its generator", func() {
		ctx := unitRulesCtx(taxonomyCfg(), MakeDoc("docs/a.md",
			"---\ntype: reference\n---\n\n# Reference\n\nRegenerate with `task docs:generate`.\n\n## Related Issues\n"))

		Expect(ruleTaxonomyStructure(ctx)).To(BeEmpty())
	})

	// navDoc builds a nav document whose body is EXACTLY n prose words. Nothing else in the
	// fixture counts: the H1 is stripped by headingRe before proseWords runs, and nav is exempt
	// from the footer, so the whole rule's output is a function of n alone.
	navDoc := func(n int) Doc {
		words := make([]string, n)
		for i := range words {
			words[i] = "word"
		}
		return MakeDoc("docs/README.md", "---\ntype: nav\n---\n\n# Index\n\n"+strings.Join(words, " ")+"\n")
	}

	It("counts exactly the words the threshold is measured against, so the boundary specs below are about the threshold and not about the fixture", func() {
		Expect(proseWords(navDoc(250).Body)).To(Equal(250))
		Expect(proseWords(navDoc(251).Body)).To(Equal(251))
	})

	// The threshold is `> 250` and both neighbours are pinned. A fixture far above the boundary
	// proves only that SOME threshold exists — shifting it to 249 or 251 left the old spec
	// green, and either shift changes which real docs the check fires on.
	It("does NOT report a nav doc at exactly 250 words, the largest prose budget a nav doc is allowed", func() {
		Expect(ruleTaxonomyStructure(unitRulesCtx(taxonomyCfg(), navDoc(250)))).To(BeEmpty())
	})

	It("reports a nav doc at 251 words — one past the budget — and does so BEFORE the generator would overwrite it with a link table", func() {
		ctx := unitRulesCtx(taxonomyCfg(), navDoc(251))

		// The full message, count included. The count is the entire diagnostic: it tells the
		// reader how far past the budget the doc is and therefore whether it is a retype or a
		// retyping, and a `ContainSubstring("carries ~")` match discards precisely that.
		Expect(ruleTaxonomyStructure(ctx)).To(ConsistOf(Finding{
			Rule:     "taxonomy-structure",
			Severity: "warn",
			Path:     "docs/README.md",
			Message:  "type `nav` but carries ~251 words of prose — misfiled?",
		}))
	})

	It("reports a nav doc far past the budget with its own count, so the number tracks the document rather than being a constant", func() {
		ctx := unitRulesCtx(taxonomyCfg(), navDoc(600))

		Expect(unitMessages(ruleTaxonomyStructure(ctx))).To(ConsistOf(
			"type `nav` but carries ~600 words of prose — misfiled?"))
	})

	It("accepts a short nav doc and exempts it from the footer, because a generated link table has no issues of its own", func() {
		ctx := unitRulesCtx(taxonomyCfg(), MakeDoc("docs/README.md",
			"---\ntype: nav\n---\n\n# Index\n\n| Doc | Purpose |\n| --- | --- |\n| [a](./a.md) | thing |\n"))

		Expect(ruleTaxonomyStructure(ctx)).To(BeEmpty())
	})

	It("REQUIRES the configured footer on every non-nav typed doc, which is the hook the whole beads-tracking convention hangs on", func() {
		ctx := unitRulesCtx(taxonomyCfg(), MakeDoc("docs/a.md",
			"---\ntype: reference\n---\n\n# Reference\n\nRegenerate with `task docs:generate`.\n"))

		Expect(unitMessages(ruleTaxonomyStructure(ctx))).To(ContainElement("missing `## Related Issues` footer"),
			"dropping this check would let the Related Issues convention rot silently")
	})

	It("skips the footer check when no footer is configured, so a porting repo is not forced into our convention", func() {
		cfg := taxonomyCfg()
		cfg.RequiredFooter = ""
		ctx := unitRulesCtx(cfg, MakeDoc("docs/a.md",
			"---\ntype: reference\n---\n\n# Reference\n\nRegenerate with `task docs:generate`.\n"))

		Expect(ruleTaxonomyStructure(ctx)).To(BeEmpty())
	})
})

var _ = Describe("proseWords", Label("unit"), func() {
	It("ignores tables, headings and code so a nav doc built of link tables is not mistaken for prose", func() {
		body := "# Heading\n\n| Doc | Purpose |\n| --- | --- |\n| [a](./a.md) | thing |\n\n```\ncode words here\n```\n"

		Expect(proseWords(body)).To(Equal(0))
	})

	It("counts actual prose", func() {
		Expect(proseWords("# Heading\n\nfour words of prose\n")).To(Equal(4))
	})
})

// --- Run ---------------------------------------------------------------------------------------

var _ = Describe("Run", Label("unit"), func() {
	// One doc that trips several rules: an unresolvable covers token, a missing required key, and
	// a typed doc with no H1 and no footer. Components are cleared so the filesystem-stat rules
	// contribute nothing and the assertions are about dispatch, not about any real tree.
	runCtx := func(cfg *Config) *Ctx {
		ctx := unitRulesCtx(cfg, MakeDoc("docs/a.md", "---\ntype: reference\ncovers:\n  - cillium\n---\n\nregenerated by docsgen\n"))
		ctx.Components = nil
		return ctx
	}
	footerCfg := func() *Config { return &Config{RequiredFooter: "## Related Issues"} }

	It("runs every rule by default, because an unknown or unlisted rule name defaults to enabled", func() {
		Expect(unitRules(Run(runCtx(footerCfg()), ""))).To(ContainElements(
			"covers-resolves", "frontmatter-schema", "taxonomy-structure"))
	})

	It("emits findings grouped in stable rule-name order, so report output diffs cleanly between runs", func() {
		rules := unitRules(Run(runCtx(footerCfg()), ""))
		sorted := append([]string(nil), rules...)
		sort.Strings(sorted)

		Expect(rules).To(Equal(sorted), "map iteration order must not leak into the report")
		Expect(rules[0]).To(Equal("covers-resolves"))
	})

	It("honours the only-filter by running exactly one rule, which is what makes `--only` usable for burning a rule down", func() {
		findings := Run(runCtx(footerCfg()), "covers-resolves")

		Expect(findings).NotTo(BeEmpty())
		Expect(unitRules(findings)).To(HaveEach("covers-resolves"))
	})

	It("returns nothing for an only-filter naming no real rule, rather than falling back to running everything", func() {
		Expect(Run(runCtx(footerCfg()), "no-such-rule")).To(BeEmpty())
	})

	It("skips a rule explicitly disabled in config while still running the others, because adoption means promoting rules one at a time", func() {
		cfg := footerCfg()
		cfg.Rules = map[string]Rule{"covers-resolves": {Enabled: false}}

		rules := unitRules(Run(runCtx(cfg), ""))

		Expect(rules).NotTo(ContainElement("covers-resolves"))
		Expect(rules).To(ContainElement("taxonomy-structure"))
	})

	It("still runs a rule that config disables under a MISSPELLED name, so a config typo surfaces as unexpected findings rather than a silently dead check", func() {
		cfg := footerCfg()
		cfg.Rules = map[string]Rule{"covers-resolve": {Enabled: false}}

		Expect(unitRules(Run(runCtx(cfg), ""))).To(ContainElement("covers-resolves"))
	})
})

// --- ruleTicketsExist ---------------------------------------------------------------------
//
// These specs exist because ticket IDs were the THIRD reference kind in this tool validated for
// shape but never for existence — after bare `covers:` slugs (always checked) and `path:` covers
// (trusted unconditionally until they were caught feeding a wrong colocation verdict). A regex
// cannot distinguish a real ticket from a one-character typo of one.
//
// The backend is faked through cfg.Tickets.Command so the specs never shell out to the real
// tracker: a test whose result depends on the current backlog would change answer as tickets are
// opened and closed, which is the definition of a test nobody can trust.
var _ = Describe("ruleTicketsExist", Label("unit"), func() {
	// fakeBackend writes a script that prints the given JSON, and returns its path.
	fakeBackend := func(stdout string, exitCode int) string {
		dir := GinkgoT().TempDir()
		path := filepath.Join(dir, "fake-tracker")
		script := "#!/bin/sh\ncat <<'JSON'\n" + stdout + "\nJSON\nexit " + fmt.Sprint(exitCode) + "\n"
		Expect(os.WriteFile(path, []byte(script), 0o755)).To(Succeed())
		return path
	}

	ticketCfg := func(cmd string) *Config {
		return &Config{
			TicketPattern: `\bTALOS-[0-9a-z]{2,6}\b`,
			Tickets:       TicketSource{Backend: "beads", Command: cmd},
		}
	}

	doc := func(ids ...string) Doc {
		body := "---\ntickets:\n"
		for _, id := range ids {
			body += "  - " + id + "\n"
		}
		return MakeDoc("docs/a.md", body+"---\n\n# Doc\n")
	}

	It("reports a ticket that matches the pattern but does not exist in the tracker", func() {
		cfg := ticketCfg(fakeBackend(`[{"id":"TALOS-kll3"}]`, 0))
		ctx := unitRulesCtx(cfg, doc("TALOS-kll8"))
		ctx.Root = GinkgoT().TempDir()

		Expect(unitMessages(ruleTicketsExist(ctx))).To(ContainElement(
			"`TALOS-kll8` matches the ticket pattern but no such ticket exists"))
	})

	It("stays silent for a ticket the tracker knows, including a closed one", func() {
		cfg := ticketCfg(fakeBackend(`[{"id":"TALOS-kll3"},{"id":"TALOS-done"}]`, 0))
		ctx := unitRulesCtx(cfg, doc("TALOS-kll3", "TALOS-done"))
		ctx.Root = GinkgoT().TempDir()

		Expect(ruleTicketsExist(ctx)).To(BeEmpty())
	})

	It("ignores an id from another project, so a legitimate cross-repo reference is not nagged", func() {
		cfg := ticketCfg(fakeBackend(`[{"id":"TALOS-kll3"}]`, 0))
		ctx := unitRulesCtx(cfg, doc("CILIUM-h2b"))
		ctx.Root = GinkgoT().TempDir()

		Expect(ruleTicketsExist(ctx)).To(BeEmpty())
	})

	It("reports itself as SKIPPED when the backend is unreachable, instead of passing quietly", func() {
		cfg := ticketCfg(filepath.Join(GinkgoT().TempDir(), "does-not-exist"))
		ctx := unitRulesCtx(cfg, doc("TALOS-kll8"))
		ctx.Root = GinkgoT().TempDir()

		msgs := unitMessages(ruleTicketsExist(ctx))
		Expect(msgs).To(HaveLen(1))
		Expect(msgs[0]).To(HavePrefix("SKIPPED"))
		Expect(msgs[0]).To(ContainSubstring("were NOT verified"))
	})

	It("treats an empty tracker as unreachable rather than as `no ticket exists`", func() {
		// The difference matters: an empty result would otherwise condemn EVERY ticket in the
		// repo at once, which reads as catastrophic drift when the real cause is a broken query.
		cfg := ticketCfg(fakeBackend(`[]`, 0))
		ctx := unitRulesCtx(cfg, doc("TALOS-kll3"))
		ctx.Root = GinkgoT().TempDir()

		Expect(unitMessages(ruleTicketsExist(ctx))[0]).To(HavePrefix("SKIPPED"))
	})

	It("does nothing at all when no backend is configured, so a repo without a tracker is unaffected", func() {
		ctx := unitRulesCtx(&Config{TicketPattern: `\bTALOS-[0-9a-z]{2,6}\b`}, doc("TALOS-nope"))
		ctx.Root = GinkgoT().TempDir()

		Expect(ruleTicketsExist(ctx)).To(BeEmpty())
	})
})
