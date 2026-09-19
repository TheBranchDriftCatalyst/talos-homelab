package integration_test

// Artifact scoping, driven through the real binary.
//
// THE BEHAVIOUR THAT MATTERS MOST HERE IS THE REFUSAL. A `scope:` that matches no component
// does not render an empty table — it is an exit-2 error naming the config key. An inventory
// with a heading, the prose promising a row per component, and no rows reads as "this section
// has nothing in it"; it means "the filter is wrong". Those two are indistinguishable to every
// reader afterwards, which is why the generator must never produce the first one.
//
// The second thing being pinned is the ABSENT scope. Every artifact that existed before this
// feature omits `scope:`, and their bytes must not have moved by one character — so the
// unscoped inventory is compared against the golden recorded before scoping landed. A feature
// whose default changes existing output is a feature nobody can adopt.

import (
	"os"
	"regexp"
	"strconv"
	"strings"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	"github.com/onsi/gomega/gexec"
)

// slugCell matches a rendered inventory row for one slug: backticked, in the first column, and
// PADDED — the normaliser reproduces prettier's column widths, so the cell is followed by a run
// of spaces whose length depends on the widest slug in that particular table.
//
// A regexp anchored on the whole cell rather than a substring search for the slug: `storage` is
// a substring of `storage-stack`, a flux name in the flux-cluster sample, so a bare search
// would report a component present on the strength of a different component's name — and the
// exclusion half of the spec would then be the one asserting nothing.
func slugCell(slug string) string {
	return `(?m)^\| ` + regexp.QuoteMeta("`"+slug+"`") + `\s*\|`
}

var _ = Describe("artifact scoping", Label("integration"), func() {
	for _, s := range samples {
		s := s

		Context("sample "+s.Name, func() {
			var fx *fixture

			BeforeEach(func() { fx = newFixture(s) })

			It("renders every component inside the scope and NOT ONE outside it", func() {
				Expect(fx.run("generate").Code).To(Equal(0))
				content := fx.read(s.ScopeRel)

				for _, slug := range s.ScopeSlugs {
					Expect(content).To(MatchRegexp(slugCell(slug)),
						"scoped inventory is missing `%s`, which is inside %s", slug, s.ScopePrefix)
				}
				for _, slug := range s.ScopeExcludes {
					Expect(content).NotTo(MatchRegexp(slugCell(slug)),
						"scoped inventory contains `%s`, which is OUTSIDE %s — the filter did "+
							"not run, and a members table that quietly includes a neighbour is "+
							"worse than one that is obviously wrong", slug, s.ScopePrefix)
				}
			})

			It("says in the document itself that the table is a subset, because a members table "+
				"whose reader cannot tell rows are missing by design lies by omission", func() {
				Expect(fx.run("generate").Code).To(Equal(0))
				content := fx.read(s.ScopeRel)

				Expect(content).To(ContainSubstring("SCOPED"))
				Expect(content).To(ContainSubstring("`" + s.ScopePrefix + "/`"))
				// The H1 carries it too: a search result showing only the heading must not be
				// mistakable for the whole-repo inventory.
				Expect(content).To(ContainSubstring("# Component Inventory — `" + s.ScopePrefix + "`"))
			})

			It("counts the scoped rows, not every component, so the prose above the table "+
				"describes the table below it", func() {
				Expect(fx.run("generate").Code).To(Equal(0))

				Expect(fx.read(s.ScopeRel)).To(ContainSubstring(
					strconv.Itoa(len(s.ScopeSlugs)) + " components are declared"))
				// And the unscoped artifact still counts everything, which is what makes the
				// line above a filter rather than a constant.
				Expect(fx.read(fx.artifactRel())).To(ContainSubstring(
					strconv.Itoa(len(s.Slugs)) + " components are declared"))
			})

			It("leaves the UNSCOPED artifact byte-identical, which is the only thing `scope "+
				"absent means every component` can mean", func() {
				Expect(fx.run("generate").Code).To(Equal(0))
				// Compared against the golden recorded before scoping existed. If this moved,
				// the default changed and every repo already using the tool got a diff.
				fx.matchGolden("component-inventory.md", fx.read(fx.artifactRel()))
			})

			It("writes the scoped artifact at root/path — outside the documentation root when "+
				"`root:` says so, because a section inventory belongs beside its manifests", func() {
				Expect(fx.run("generate").Code).To(Equal(0))

				Expect(fx.exists(s.ScopeRel)).To(BeTrue())
				Expect(fx.run("generate").Out).To(ContainSubstring(s.ScopeRel))
				Expect(fx.mode(s.ScopeRel)).To(Equal(os.FileMode(0o644)))
			})

			It("exits 2 naming the key when the scope matches nothing, rather than writing an "+
				"empty table that reads as `nothing to report`", func() {
				// Truncate the prefix by three characters. Under a naive substring match this
				// still selects the same components; under the segment-aware match it selects
				// none — so this is simultaneously the empty-scope refusal and the proof that
				// `platform` does not match `platformer`.
				truncated := s.ScopePrefix[:len(s.ScopePrefix)-3]
				fx.editConfig("path_prefix: "+s.ScopePrefix, "path_prefix: "+truncated)
				before := fx.treeHash()

				res := fx.run("generate")

				Expect(res.Session).To(gexec.Exit(2))
				Expect(res.Err).To(ContainSubstring("scope.path_prefix"))
				Expect(res.Err).To(ContainSubstring(truncated))
				Expect(fx.treeHash()).To(Equal(before),
					"an artifact whose scope matched nothing still reached the disk")
				Expect(fx.exists(s.ScopeRel)).To(BeFalse())
			})

			It("refuses a `scope:` block with no filter in it, because a half-written filter "+
				"read as `cover everything` is a whole-repo inventory in a file named after a "+
				"section", func() {
				fx.editConfig("path_prefix: "+s.ScopePrefix, `path_prefix: ""`)
				before := fx.treeHash()

				res := fx.run("generate")

				Expect(res.Session).To(gexec.Exit(2))
				Expect(res.Err).To(ContainSubstring("scope.path_prefix"))
				Expect(fx.treeHash()).To(Equal(before))
			})

			It("refuses a `root:` that escapes the repository, which is the one bound `root:` "+
				"must keep", func() {
				// Declared on the UNSCOPED artifact, which has no root of its own, so the edit
				// is an addition rather than a substitution and cannot be confused with the
				// scoped artifact's legitimate root.
				fx.editConfig("    path: reference/component-inventory.md",
					"    root: ../../etc\n    path: reference/component-inventory.md")
				before := fx.treeHash()

				res := fx.run("generate")

				Expect(res.Session).To(gexec.Exit(2))
				Expect(res.Err).To(ContainSubstring("artifacts.component-inventory.root"))
				Expect(res.Err).To(ContainSubstring("escapes the repository"))
				Expect(fx.treeHash()).To(Equal(before))
			})

			It("keeps the scoped artifact lint-clean once it is on disk, so the generator is "+
				"not writing a document its own ruleset would report", func() {
				Expect(fx.run("generate").Code).To(Equal(0))
				// Track it: the walker is `git ls-files`, so an untracked artifact is invisible
				// to every rule and a clean report would mean "nothing was examined".
				runGit(fx.Root, nil, "add", "-A")
				Expect(fx.isTracked(s.ScopeRel)).To(BeTrue(),
					"the scoped artifact is untracked, so lint never saw it and this spec asserts nothing")

				var attributed []string
				for _, f := range parseLintFindings(fx.run("lint").Out) {
					if f.Path == s.ScopeRel {
						attributed = append(attributed, "  "+f.Rule+": "+f.Message)
					}
				}
				Expect(attributed).To(BeEmpty(),
					"sample %s: the scoped artifact violates this repo's own rules:\n%s",
					s.Name, strings.Join(attributed, "\n"))
			})
		})
	}
})
