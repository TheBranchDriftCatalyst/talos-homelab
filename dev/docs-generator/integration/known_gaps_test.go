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

// THE RATCHET IS AT ZERO. There is deliberately no spec in here right now.
//
// An empty container is the honest state, not an oversight: the last entry — "measures
// component shape in terms the strategy actually supplies" — was delabelled below on
// 2026-09-19 and now counts toward the promotable gate. Leaving the container standing keeps
// the convention and its instructions in front of whoever finds the next gap.
var _ = Describe("known gaps", Label("integration", "known-gap"), func() {
})

// CLOSED 2026-09-19 — delabelled, so it counts toward the promotable gate.
//
// `nested` counts kustomization.yaml files, which is a kustomize-specific measurement: in a
// repo with no kustomize it was structurally always zero, so `component-shape` could never fire
// — and `component-path` could never fire either, because the `dirs` strategy only ever emits
// directories that exist. Both rules ran, found nothing, and reported a clean pass. A rule that
// silently never fires is worse than an absent one, because the report reads as coverage.
//
// The fix is not a better measurement; there is no honest number to print. It is that the
// strategy now DECLARES what it can supply, each rule DECLARES what it measures, and the two
// unmeasurable rules announce themselves instead of passing. The report says `n/a` rather than
// `0` for the same reason: those are different claims, and printing the first for the second
// was the same lie in a different column.
var _ = Describe("measurements the strategy cannot make", Label("integration"), func() {

	It("measures component shape in terms the strategy actually supplies", func() {
		fx := newFixture(plainDirs)
		out := fx.run("components").Out

		Expect(out).NotTo(MatchRegexp(`(?m)^\S+\s+\S+\s+0\s+`),
			"a component reports nested=0, but the measurement is kustomize-specific and this "+
				"sample has no kustomize — the zero is invented")
		// The positive half, which the negative one cannot give: the column must still be
		// THERE, saying it has no answer.
		Expect(componentRow(out, "billing")).To(
			MatchRegexp(`^billing\s+yes\s+n/a\s+n/a\s+services/billing$`),
			"the unavailable measurements must read `n/a` in their own fixed columns; dropping "+
				"a column instead breaks every positional reader of this report")
	})

})

// CLOSED 2026-09-19 — the generated artifact is config-driven, so these three carry no
// `known-gap` label and count toward the promotable gate.
//
// The defect was one cause with three faces: `Artifacts()` returned a hardcoded
// `docs/07-reference/component-inventory.md`, and `artifact_inventory.go` held the frontmatter
// type, freshness, footer heading and ticket ids as Go string constants. Against any config but
// this repo's own that is an out-of-enum type, an out-of-enum freshness, the wrong footer,
// another project's tickets and a docs/ tree the host repo does not have.
//
// It survived because the artifact was untracked in the host repo and the walker is
// `git ls-files`, so docsgen had never once linted its own output. The first spec below tracks
// the file deliberately for exactly that reason — without the `git add`, it asserts nothing.
//
// The fix that makes these STAY closed is not the config keys; it is the pre-write gate in
// generate.go, which runs the rendered bytes through the repo's own frontmatter and taxonomy
// rules and refuses to write on any finding. Configurable constants can still be configured
// wrong. A gate cannot let the wrong bytes reach the disk at all.
var _ = Describe("generated artifacts obey the host repo's config", Label("integration"), func() {

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
			// Prove the artifact was actually in scope before concluding anything from a clean
			// report: if `git add` or the walker missed it, "no findings" means "nothing was
			// linted" and this spec is back to asserting nothing.
			Expect(fx.run("frontmatter").Code).To(Equal(0))
			Expect(strings.Contains(res.Out, fx.artifactRel()) ||
				strings.Contains(fx.run("stale").Out, fx.artifactRel()) ||
				fx.isTracked(fx.artifactRel())).To(BeTrue(),
				"sample %s: the artifact is not tracked, so lint never saw it", s.Name)

			var attributed []string
			for _, line := range strings.Split(res.Out, "\n") {
				if strings.Contains(line, fx.artifactRel()) {
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
		content := fx.read(fx.artifactRel())

		Expect(content).NotTo(ContainSubstring("TALOS-"),
			"the generated doc cites another repository's ticket IDs")
		Expect(content).NotTo(ContainSubstring("clusters/catalyst-cluster"),
			"the generated doc names another repository's cluster path")
		Expect(content).To(ContainSubstring("## Tracking"),
			"the generated doc uses a footer this repo's config does not ask for")
		Expect(content).NotTo(ContainSubstring("## Related Issues"))
		Expect(content).To(ContainSubstring("type: table"),
			"the generated doc declares a `type` outside this repo's doc_types")

		// The footer's BODY is the frontmatter's ticket list, which is what makes
		// `tickets-in-body` self-satisfying rather than merely satisfied today.
		Expect(content).To(ContainSubstring("## Tracking\n\n- ORCH-201"))
		Expect(content).To(ContainSubstring("- ORCH-204"))
		// And the banner names THIS repo's component source, composed from components.path.
		Expect(content).To(ContainSubstring("Flux Kustomizations in `fleet/prod-west/`"))
	})

	It("places the artifact under the host repo's own documentation root", func() {
		fx := newFixture(fluxCluster)
		Expect(fx.run("generate").Code).To(Equal(0))
		// This sample's prose lives in handbook/, and the repo has no docs/ directory at all.
		Expect(fx.exists("docs/07-reference/component-inventory.md")).To(BeFalse(),
			"the artifact path is hardcoded to another repository's docs tree")
		Expect(fx.exists("handbook/reference/component-inventory.md")).To(BeTrue(),
			"docs_root + artifacts.component-inventory.path is where the artifact belongs")
	})

})

// CLOSED 2026-09-19 — no longer a known gap, so it carries no `known-gap` label and counts
// toward the promotable gate.
//
// Two defects had to be fixed for this one spec to mean anything, and the second was hiding
// behind the first:
//
//  1. the rule searched d.Text, which still contains the frontmatter it read the ticket out of,
//     so every ticket trivially matched itself and the rule could never fire;
//  2. the fixture defeated itself — ticket-drift.md's own explanatory prose NAMED the ticket it
//     was supposed to omit, so once the rule was fixed it correctly stayed silent.
//
// The second only became visible after the first was fixed, because a spec asserting broken
// behaviour passes for either reason. That is the argument for asserting the behaviour you
// WANT and labelling it, rather than pinning the behaviour you have.
var _ = Describe("tickets-in-body", Label("integration"), func() {
	It("reports a ticket listed in frontmatter but never mentioned in the prose", func() {
		fx := newFixture(fluxCluster)
		// ticket-drift.md lists ORCH-109 and ORCH-110 and cites only ORCH-109 in its body.
		Expect(findingsFor(fx.run("lint").Out, "tickets-in-body")).To(ContainElement(
			ContainSubstring("ORCH-110")))
	})

	It("stays silent for a ticket the prose does cite, so a correct doc is not nagged", func() {
		fx := newFixture(fluxCluster)
		Expect(findingsFor(fx.run("lint").Out, "tickets-in-body")).NotTo(ContainElement(
			ContainSubstring("ORCH-109")))
	})
})

// CLOSED 2026-09-19 — delabelled, so it counts toward the promotable gate.
//
// The renderer used to re-open every Component.Source and re-decode it to recover the Flux
// metadata.name. Under components.kind: dirs the Source IS the component directory, so each
// component produced one `is a directory` warning that also leaked the absolute repo root onto
// stderr. The fix was a deletion, not a strategy: loadFlux already computes that value and
// stores it on Component.Name, so ~45 lines and an entire second parse pass over every manifest
// went away. Kept as a live spec because the cheap regression is someone reintroducing a
// filesystem read keyed on Source.
var _ = Describe("dirs strategy", Label("integration"), func() {
	It("never reads a component's Source as a file, because under `dirs` the Source is a directory", func() {
		fx := newFixture(plainDirs)
		res := fx.run("generate")
		Expect(res.Code).To(Equal(0))
		Expect(res.Err).NotTo(ContainSubstring("is a directory"))
		Expect(res.Err).NotTo(ContainSubstring(fx.Root),
			"a per-component warning would also leak the absolute repo root onto stderr")
	})
})
