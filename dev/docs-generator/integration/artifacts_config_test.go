package integration_test

// The `artifacts:` block, driven through the real binary.
//
// THE BEHAVIOUR THAT MATTERS MOST HERE IS THE ABSENT ONE. `Artifacts()` used to return a
// hardcoded `docs/07-reference/component-inventory.md` no matter what config said, so every repo
// that adopted the tool got an artifact it never asked for, in a `docs/` tree it may not have,
// written in a vocabulary it does not use. The fix is only a fix if "no artifacts configured"
// means NOTHING IS WRITTEN — a fallback to the old constant would restore the defect exactly
// while looking like a kindness.
//
// And it must exit 0. A repo that lints but generates nothing is a normal adoption state, and a
// non-zero exit there turns `docsgen check` into a gate every such repo has to switch off.

import (
	"strings"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	"github.com/onsi/gomega/gexec"
)

var _ = Describe("the artifacts: block", Label("integration"), func() {

	Context("when it is absent entirely", func() {
		for _, s := range samples {
			s := s

			It("writes nothing and exits 0 for sample "+s.Name+", because a fallback to a "+
				"hardcoded artifact is the defect this block exists to remove", func() {
				fx := newFixture(s)
				fx.dropArtifacts()
				before := fx.treeHash()

				res := fx.run("generate")

				Expect(res.Session).To(gexec.Exit(0))
				Expect(res.Out).To(ContainSubstring("no artifacts configured (see artifacts: in config.yaml)"))
				Expect(fx.treeHash()).To(Equal(before), "generate wrote something with nothing configured")
				Expect(fx.exists(fx.artifactRel())).To(BeFalse())
				Expect(fx.exists("docs/07-reference/component-inventory.md")).To(BeFalse(),
					"an absent artifacts: block fell back to the hardcoded artifact")
			})
		}

		It("says the same thing under `check`, so a linter-only repo has a green gate rather "+
			"than a silent one", func() {
			fx := newFixture(fluxCluster)
			fx.dropArtifacts()

			res := fx.run("check")

			Expect(res.Session).To(gexec.Exit(0))
			Expect(res.Out).To(ContainSubstring("no artifacts configured"))
		})

		It("still lints, because the artifact set and the ruleset are independent", func() {
			fx := newFixture(fluxCluster)
			fx.dropArtifacts()

			Expect(findingsFor(fx.run("lint").Out, "broken-links")).NotTo(BeEmpty())
		})
	})

	Context("when it is present but wrong", func() {
		It("exits 2 naming the key when `path` is missing", func() {
			fx := newFixture(fluxCluster)
			fx.editConfig("    path: reference/component-inventory.md\n", "")
			before := fx.treeHash()

			res := fx.run("generate")

			Expect(res.Session).To(gexec.Exit(2))
			Expect(res.Err).To(ContainSubstring("artifacts.component-inventory.path"))
			Expect(fx.treeHash()).To(Equal(before))
		})

		It("exits 2 naming the key AND the allowed values when `front.type` is outside this "+
			"repo's doc_types — `reference` being precisely the value that used to be compiled in", func() {
			fx := newFixture(fluxCluster)
			fx.editConfig("      type: table", "      type: reference")
			before := fx.treeHash()

			res := fx.run("generate")

			Expect(res.Session).To(gexec.Exit(2))
			Expect(res.Err).To(ContainSubstring("artifacts.component-inventory.front.type"))
			Expect(res.Err).To(ContainSubstring("overview guide runbook design adr table journal"))
			Expect(fx.treeHash()).To(Equal(before), "a rejected artifact must not reach the disk")
		})

		It("exits 2 when `front.freshness` is outside this repo's vocabulary", func() {
			fx := newFixture(fluxCluster)
			fx.editConfig("      freshness: follows-cluster", "      freshness: tracks-code")

			res := fx.run("generate")

			Expect(res.Session).To(gexec.Exit(2))
			Expect(res.Err).To(ContainSubstring("artifacts.component-inventory.front.freshness"))
		})
	})

	// The gate is the part config validation cannot do: these front matters are all INSIDE the
	// configured enums, and the repo's own ruleset rejects them anyway.
	Context("when the front matter is in-enum but the ruleset still rejects the document", func() {
		It("refuses to write a banned key and names it, rather than emitting a document the "+
			"next `docsgen lint` would report", func() {
			fx := newFixture(fluxCluster)
			fx.editConfig("      type: table", "      type: table\n      title: Component Inventory")
			before := fx.treeHash()

			res := fx.run("generate")

			Expect(res.Session).To(gexec.Exit(2))
			Expect(res.Err).To(ContainSubstring("refusing to write"))
			Expect(res.Err).To(ContainSubstring("artifacts.component-inventory.front.title"))
			Expect(fx.treeHash()).To(Equal(before))
			Expect(fx.exists(fx.artifactRel())).To(BeFalse())
		})

		It("refuses a `status: superseded` with no superseded_by", func() {
			fx := newFixture(fluxCluster)
			fx.editConfig("      status: current", "      status: superseded")

			res := fx.run("generate")

			Expect(res.Session).To(gexec.Exit(2))
			Expect(res.Err).To(ContainSubstring("superseded_by"))
			Expect(fx.exists(fx.artifactRel())).To(BeFalse())
		})

		It("refuses under `check` too, so a rejected document already on disk cannot be "+
			"reported as `unchanged`", func() {
			fx := newFixture(fluxCluster)
			fx.editConfig("      type: table", "      type: table\n      title: Component Inventory")

			res := fx.run("check")

			Expect(res.Session).To(gexec.Exit(2))
			Expect(res.Err).To(ContainSubstring("refusing to write"))
			Expect(res.Out).NotTo(ContainSubstring("unchanged"))
		})
	})

	// The self-check the whole change is for, stated per sample: the bytes docsgen writes pass
	// the rules docsgen enforces, in whatever vocabulary the host repo declares.
	Context("the generated document against its own host config", func() {
		for _, s := range samples {
			s := s

			It("carries the sample's own type, footer and tickets for "+s.Name, func() {
				fx := newFixture(s)
				Expect(fx.run("generate").Code).To(Equal(0))
				content := fx.read(fx.artifactRel())

				cfg := fx.read("config.yaml")
				footer := configScalar(cfg, "required_footer")
				Expect(content).To(ContainSubstring(footer + "\n\n"))
				Expect(content).To(HavePrefix("---\ntype: "))
				// Not one value from the tool's former constants.
				for _, constant := range []string{
					"type: reference", "freshness: tracks-code", "TALOS-", "## Related Issues",
					"clusters/catalyst-cluster",
				} {
					Expect(content).NotTo(ContainSubstring(constant),
						"sample %s: the generator emitted a value compiled into Go", s.Name)
				}
			})
		}
	})
})

// configScalar pulls a top-level quoted scalar out of a sample config, so a spec can assert
// against what the sample DECLARES rather than against a value copied into the spec — a copy
// would agree with the tool's constants and with the config alike, which is the one thing these
// specs must not do.
func configScalar(cfg, key string) string {
	for _, line := range strings.Split(cfg, "\n") {
		rest, ok := strings.CutPrefix(line, key+":")
		if !ok {
			continue
		}
		return strings.Trim(strings.TrimSpace(rest), `"'`)
	}
	return ""
}
