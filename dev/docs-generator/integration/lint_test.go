package integration_test

import (
	"strings"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

// The ruleset, pinned against the flux-cluster sample's KNOWN answers.
//
// Every doc in that sample was written to trip exactly one rule and to state which one, so a
// finding here is either the one the doc advertises or a regression. The negative assertions —
// the links that must NOT be reported, the archive that must produce nothing — are the more
// valuable half: a rule that over-reports gets switched off just as fast as one that misses.

var _ = Describe("the ruleset", Label("integration"), func() {
	var fx *fixture

	BeforeEach(func() { fx = newFixture(fluxCluster) })

	It("reports a dead relative link and nothing else on that page", func() {
		found := findingsFor(fx.run("lint").Out, "broken-links")
		Expect(found).To(ConsistOf(
			"handbook/reference/dead-links.md: dead link -> ./no-such-file.md",
			"handbook/reference/dead-links.md: dead link -> ../design/deleted-doc.md",
		))
	})

	It("ignores links that are not repository paths, and links that are only examples", func() {
		found := strings.Join(findingsFor(fx.run("lint").Out, "broken-links"), "\n")

		// A resolvable target.
		Expect(found).NotTo(ContainSubstring("../README.md"))
		// Off-repo and in-page targets are out of scope by construction.
		Expect(found).NotTo(ContainSubstring("https://example.com"))
		Expect(found).NotTo(ContainSubstring("mailto:"))
		Expect(found).NotTo(ContainSubstring("#link-reference"))
		// Inside a fenced block and inside an inline span. If either is ever reported, every
		// code sample in the repo becomes a liability and the rule gets switched off.
		Expect(found).NotTo(ContainSubstring("this-path-never-existed.md"))
		Expect(found).NotTo(ContainSubstring("also-never-existed.md"))
	})

	It("reports each frontmatter defect exactly once, naming the key at fault", func() {
		found := findingsFor(fx.run("lint").Out, "frontmatter-schema")
		Expect(found).To(ConsistOf(
			ContainSubstring("handbook/design/bad-enum.md: type `architecture` not in"),
			ContainSubstring("handbook/design/legacy-title.md: banned key `title`"),
			ContainSubstring("handbook/design/out-of-order.md: key `type` should come before `status`"),
			Equal("handbook/design/storage-layout.md: status: superseded requires superseded_by"),
			Equal("handbook/process/missing-covers.md: missing required `covers`"),
			ContainSubstring("handbook/reference/scalar-covers.md: covers must be a block sequence"),
			Equal("handbook/reference/unterminated.md: unterminated frontmatter block"),
		))
	})

	It("names this sample's own key order in the ordering message, not the host repo's", func() {
		found := strings.Join(findingsFor(fx.run("lint").Out, "frontmatter-schema"), "\n")
		// `summary` is this sample's key; `bluf` is talos-homelab's. Seeing `summary` here is
		// the evidence that key_order is read from config rather than compiled in.
		Expect(found).To(ContainSubstring("[type status covers freshness tickets summary superseded_by pinned]"))
		Expect(found).NotTo(ContainSubstring("bluf"))
	})

	It("reports a covers: token that matches no component", func() {
		Expect(findingsFor(fx.run("lint").Out, "covers-resolves")).To(ContainElement(
			Equal("handbook/reference/unknown-covers.md: `nonesuch` matches no known component")))
	})

	It("reports a Kustomization whose spec.path is not on disk, which Flux itself hides behind "+
		"a still-running last-applied revision", func() {
		Expect(findingsFor(fx.run("lint").Out, "component-path")).To(ConsistOf(
			"fleet/prod-west/legacy-cache.yaml: path `platform/legacy-cache` does not exist on disk"))
	})

	It("reports one slug wrapping many nested kustomizations, and does not report a grouping "+
		"directory whose children are each their own component", func() {
		found := findingsFor(fx.run("lint").Out, "component-shape")
		Expect(found).To(ConsistOf(ContainSubstring(
			"platform/storage: one component slug (`storage`) wraps 5 nested kustomizations")))
	})

	It("reports a doc that should move, and stays silent about one that is already in the "+
		"right place or that records why it is not", func() {
		found := findingsFor(fx.run("lint").Out, "colocation")
		Expect(found).To(ContainElement(
			"handbook/getting-started/first-deploy.md: should colocate at platform/gateway/"))

		joined := strings.Join(found, "\n")
		// Correctly colocated.
		Expect(joined).NotTo(ContainSubstring("workloads/orchard-api/README.md"))
		// Suppressed WITH a recorded reason, which is the migration mechanism.
		Expect(joined).NotTo(ContainSubstring("handbook/runbooks/rotate-secrets.md"))
		Expect(joined).NotTo(ContainSubstring("handbook/design/storage-layout.md"))
	})

	It("reports a doc that declares a structure it does not have", func() {
		Expect(findingsFor(fx.run("lint").Out, "taxonomy-structure")).To(ContainElements(
			"handbook/process/no-h1.md: no H1 — every doc leads with one",
			"handbook/runbooks/no-steps.md: runbook has no ordered procedure",
		))
	})

	It("demands the footer this sample's config names, not the one the host repo names", func() {
		found := strings.Join(findingsFor(fx.run("lint").Out, "taxonomy-structure"), "\n")
		Expect(found).To(ContainSubstring("handbook/getting-started/missing-footer.md"))
		Expect(found).To(ContainSubstring("missing `## Tracking` footer"))
		Expect(found).NotTo(ContainSubstring("Related Issues"))
	})

	It("attributes nothing at all to an excluded path, however many rules that path breaks", func() {
		out := fx.run("lint").Out
		Expect(out).NotTo(ContainSubstring("handbook/_attic"),
			"the excluded archive produced a finding; in a real repo that is ~67 permanent "+
				"findings nobody will action, which is how a linter gets switched off")
	})

	It("runs a single rule on demand without running the others", func() {
		res := fx.run("lint", "-rule", "component-path")
		Expect(res.Code).To(Equal(0), "component-path is warn severity in this sample")
		Expect(res.Out).To(ContainSubstring("component-path"))
		Expect(res.Out).NotTo(ContainSubstring("broken-links"))
		Expect(res.Out).To(ContainSubstring("1 finding(s): 0 error, 1 warn"))
	})

	It("summarises findings split by severity, which is what the exit code is computed from", func() {
		out := fx.run("lint").Out
		Expect(out).To(MatchRegexp(`\n\d+ finding\(s\): \d+ error, \d+ warn\n`))
	})
})

var _ = Describe("component enumeration", Label("integration"), func() {
	var fx *fixture

	BeforeEach(func() { fx = newFixture(fluxCluster) })

	It("keeps two Kustomizations declared in ONE manifest as two components with DISTINCT "+
		"slugs, because a collapsed slug silently resolves `covers:` to an arbitrary one of "+
		"two paths", func() {
		res := fx.run("components")
		Expect(res.Code).To(Equal(0))

		operator := componentRow(res.Out, "secrets-operator")
		store := componentRow(res.Out, "secrets-store")
		Expect(operator).NotTo(BeEmpty(),
			"secrets-operator is missing. Both Kustomizations in fleet/prod-west/secrets.yaml "+
				"collapsed to one slug, so Ctx.BySlug kept whichever decoded last.")
		Expect(store).NotTo(BeEmpty(), "secrets-store is missing for the same reason")
		Expect(operator).To(ContainSubstring("platform/secrets-operator"))
		Expect(store).To(ContainSubstring("platform/secrets-store"))

		Expect(res.Err).NotTo(ContainSubstring("duplicate component slug"),
			"the duplicate-slug guard fired, which means resolution is ambiguous again")

		// And the consequence, which is the part that actually hurt: both tokens must resolve.
		lint := fx.run("lint")
		Expect(strings.Join(findingsFor(lint.Out, "covers-resolves"), "\n")).
			NotTo(ContainSubstring("secrets-"))
	})

	It("enumerates every declared component and nothing that merely looks like one", func() {
		res := fx.run("components")
		for _, slug := range fluxCluster.Slugs {
			Expect(componentRow(res.Out, slug)).NotTo(BeEmpty(), "missing component %s", slug)
		}
		// A Namespace is not a deployable unit Flux reconciles.
		Expect(componentRow(res.Out, "orchard-system")).To(BeEmpty())
		// A Kustomization with no spec.path has no directory for a doc to live beside.
		Expect(componentRow(res.Out, "no-path")).To(BeEmpty())
		Expect(componentRow(res.Out, "pathless")).To(BeEmpty())
	})

	It("warns about a Kustomization with no spec.path rather than inventing a component for it", func() {
		Expect(fx.run("components").Err).To(ContainSubstring("pathless.yaml: Kustomization with no spec.path"))
	})

	It("survives a manifest that is not valid YAML and still reports every other component", func() {
		res := fx.run("components")
		Expect(res.Code).To(Equal(0))
		Expect(componentRow(res.Out, "broken")).To(BeEmpty())
		// The rest of the enumeration is unaffected — that is the whole point of warn-and-skip.
		Expect(componentRow(res.Out, "gateway")).NotTo(BeEmpty())
		Expect(componentRow(res.Out, "telemetry")).NotTo(BeEmpty())
	})

	It("records the measurements the inventory is built from: README presence, nested count "+
		"and suspension", func() {
		out := fx.run("components").Out
		Expect(componentRow(out, "gateway")).To(MatchRegexp(`^gateway\s+yes\s+1\s+-\s+platform/gateway$`))
		Expect(componentRow(out, "storage")).To(MatchRegexp(`^storage\s+-\s+5\s+-\s+platform/storage$`))
		Expect(componentRow(out, "telemetry")).To(MatchRegexp(`^telemetry\s+-\s+1\s+YES\s+platform/telemetry$`))
		Expect(componentRow(out, "legacy-cache")).To(MatchRegexp(`^legacy-cache\s+-\s+0\s+-\s+platform/legacy-cache$`))
	})

	It("lists the components in a total order, so two runs of a diffable report cannot swap rows", func() {
		out := fx.run("components").Out
		var rows []string
		for _, line := range strings.Split(out, "\n") {
			f := strings.Fields(line)
			if len(f) == 5 && f[0] != "slug" {
				rows = append(rows, f[0]+" "+f[4])
			}
		}
		Expect(rows).NotTo(BeEmpty())
		Expect(sortedCopy(rows)).To(Equal(rows), "rows are not in (slug, path) order")
	})
})

func sortedCopy(in []string) []string {
	out := append([]string(nil), in...)
	for i := 1; i < len(out); i++ {
		for j := i; j > 0 && out[j] < out[j-1]; j-- {
			out[j], out[j-1] = out[j-1], out[j]
		}
	}
	return out
}
