package integration_test

import (
	"strings"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

// Invariants that SHOULD hold and currently do not.
//
// These are written as real assertions, not as specs blessing the broken behaviour, because a
// spec that documents a defect as correct is how a defect becomes a requirement. They carry the
// extra label `known-gap` so the suite can be gated today without pretending the gaps are not
// there:
//
//	task docs:test                                   # everything, including these
//	ginkgo --label-filter='integration && !known-gap' # the promotable gate
//
// Every entry below is explained in integration/README.md under "Known gaps". Delete a spec's
// `known-gap` label the moment the underlying defect is fixed — that is the whole ratchet.

var _ = Describe("known gaps", Label("integration", "known-gap"), func() {

	It("generates an artifact that passes the tool's own lint — a generator that emits docs its "+
		"own ruleset rejects cannot be trusted to keep any other doc honest", func() {
		for _, s := range samples {
			fx := newFixture(s)
			Expect(fx.run("generate").Code).To(Equal(0))

			// Track it, so the `git ls-files` walker can actually see it. An untracked artifact
			// is never linted, which makes this invariant vacuously true in normal use — the
			// reason the gap survived this long.
			runGit(fx.Root, nil, "add", "-A")

			res := fx.run("lint")
			var attributed []string
			for _, line := range strings.Split(res.Out, "\n") {
				if strings.Contains(line, artifactRel) {
					attributed = append(attributed, strings.TrimSpace(line))
				}
			}
			Expect(attributed).To(BeEmpty(),
				"sample %s: docsgen's own output violates docsgen's own rules:\n  %s",
				s.Name, strings.Join(attributed, "\n  "))
		}
	})

	It("writes the artifact's frontmatter and footer from the host repo's configured vocabulary, "+
		"not from values compiled into Go", func() {
		fx := newFixture(fluxCluster)
		Expect(fx.run("generate").Code).To(Equal(0))
		content := fx.read(artifactRel)

		Expect(content).NotTo(ContainSubstring("TALOS-"),
			"the generated doc cites another repository's ticket IDs")
		Expect(content).NotTo(ContainSubstring("clusters/catalyst-cluster"),
			"the generated doc names another repository's cluster path")
		Expect(content).To(ContainSubstring("## Tracking"),
			"the generated doc uses a footer this repo's config does not ask for")
		Expect(content).NotTo(ContainSubstring("## Related Issues"))
		Expect(content).To(ContainSubstring("type: table"),
			"the generated doc declares a `type` outside this repo's doc_types")
	})

	It("places the artifact under the host repo's own documentation root", func() {
		fx := newFixture(fluxCluster)
		Expect(fx.run("generate").Code).To(Equal(0))
		// This sample's prose lives in handbook/, not docs/. The destination is a Go constant,
		// so porting the tool means editing Go — which is exactly what the package doc promises
		// is unnecessary.
		Expect(fx.exists("docs/07-reference/component-inventory.md")).To(BeFalse(),
			"the artifact path is hardcoded to another repository's docs tree")
	})

	It("does not try to read a directory as a YAML manifest under components.kind: dirs", func() {
		fx := newFixture(plainDirs)
		res := fx.run("generate")
		Expect(res.Code).To(Equal(0))
		Expect(res.Err).NotTo(ContainSubstring("is a directory"),
			"the inventory renderer reads Component.Source as a file, but under `dirs` the "+
				"Source IS the component directory — one spurious warning per component")
		Expect(res.Err).NotTo(ContainSubstring(fx.Root),
			"those warnings also leak the absolute repo root onto stderr")
	})

	It("measures component shape in terms the strategy actually supplies", func() {
		fx := newFixture(plainDirs)
		out := fx.run("components").Out
		// `nested` counts kustomization.yaml files. In a repo with no kustomize it is
		// structurally always zero, so `component-shape` can never fire and `component-path`
		// can never fire either (loadDirs only ever emits directories that exist). A rule that
		// silently never fires is worse than an absent one: you believe you are covered.
		Expect(out).NotTo(MatchRegexp(`(?m)^\S+\s+\S+\s+0\s+`),
			"every component reports nested=0 because the measurement is kustomize-specific")
	})

	It("reports a ticket that is listed in frontmatter but never mentioned in the prose", func() {
		fx := newFixture(fluxCluster)
		// handbook/process/ticket-drift.md lists ORCH-109 and ORCH-110 and names only ORCH-109.
		// The rule searches d.Text, which INCLUDES the frontmatter it read the ticket from, so
		// every ticket trivially matches itself and the rule can never fire.
		Expect(findingsFor(fx.run("lint").Out, "tickets-in-body")).To(ContainElement(
			ContainSubstring("ORCH-110")))
	})
})
