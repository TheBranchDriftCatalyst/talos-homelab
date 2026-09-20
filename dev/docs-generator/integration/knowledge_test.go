package integration_test

import (
	"os"
	"path/filepath"
	"strings"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

// The knowledge system, driven end to end through the real binary against the sample repos.
//
// Every assertion here is written against a DECLARED answer — the claims and blocks seeded into
// testdata/samples are known content with known properties — rather than against whatever the
// tool currently prints. A spec that reads the tool's output and asserts the tool produced it
// follows the tool into any answer it gives, which is how a suite stays green while covering
// nothing.
//
// WHAT "THE WHOLE SYSTEM" MEANS HERE, and each of these is a distinct failure mode this repo
// actually hit:
//
//	parse       four modalities across two carriers, including the wrapped-field case that
//	            silently dropped `scope` and made decay impossible
//	validate    every rule reachable, and each one proven able to fire
//	decay       a verified claim whose scope changed after its stamp is demoted
//	project     a claim written in YAML appears in the README with its falsifier
//	scaffold    a folder with no README acquires one; a folder with one keeps its prose
//	extract     prose in a README resolves to the code line its subject is defined at
//	idempotent  a second run changes nothing, which is what makes `check` a usable gate

var _ = Describe("the knowledge system", Label("integration"), func() {

	// ---- parse ------------------------------------------------------------------------

	Describe("parsing claims from code and config", func() {
		It("finds every modality the flux sample declares", func() {
			f := newFixture(fluxCluster)
			res := f.run("claims")

			// Declared content: four claims, one per modality, all in deployment.yaml. Exit
			// code is deliberately NOT asserted here: the sample seeds a claim that must decay,
			// so a clean parse still exits 1. Asserting 0 would force the sample to drop its
			// only decay case to keep this spec green.
			for _, want := range []string{
				"gateway-replica-floor", "gateway-port-is-8080",
				"gateway-no-tls-here", "gateway-uses-nodeport",
			} {
				Expect(res.Out).To(ContainSubstring(want), "claim %q was not parsed", want)
			}
			Expect(res.Out).To(ContainSubstring("enforced 1"))
			Expect(res.Out).To(ContainSubstring("superseded 1"))
		})

		It("keeps a claim's scope when an earlier field WRAPPED across lines", func() {
			// The parser once broke at a wrapped field and dropped every field after it. Losing
			// `scope` is invisible twice over: the claim can never decay AND never projects, and
			// the engine reports "no claim findings" either way. Asserting on the projection is
			// the cheapest proof the field survived.
			f := newFixture(fluxCluster)
			f.run("generate")
			readme := f.read("platform/gateway/README.md")
			Expect(readme).To(ContainSubstring("gateway-replica-floor"),
				"a scoped claim must reach the region; absence means scope was dropped in parsing")
		})
	})

	// ---- validate ---------------------------------------------------------------------

	Describe("claim rules", func() {
		It("has a clean baseline apart from the deliberate decay, so mutations below are isolated", func() {
			// The sample seeds ONE claim stamped 2020-01-01 whose scope the fixture builder
			// commits far later, so decay is expected content rather than a defect. Every other
			// rule must be silent, or a mutation spec could pass on a pre-existing finding.
			f := newFixture(fluxCluster)
			out := f.run("claims").Out
			for _, rule := range []string{
				"claim-falsifier", "claim-justification", "claim-enforced-resolves",
				"claim-contradiction", "claim-superseded", "claim-scope",
			} {
				Expect(out).NotTo(ContainSubstring(rule),
					"baseline is dirty for %s — mutation specs below would prove nothing", rule)
			}
		})

		It("reports a claim above asserted with no falsifier", func() {
			f := newFixture(fluxCluster)
			writeTracked(f, "platform/gateway/extra.yaml",
				"# claim(verified@2026-01-01) no-falsifier: something is true\n"+
					"#   j: some command\n#   scope: path:platform/gateway\n")
			res := f.run("claims")
			Expect(res.Code).To(Equal(1))
			Expect(res.Out).To(ContainSubstring("claim-falsifier"))
			Expect(res.Out).To(ContainSubstring("no-falsifier"))
		})

		It("reports an enforced claim whose gate does not exist", func() {
			// The 18-dead-entries defect generalised: config that reads as coverage and executes
			// never. `enforced` is the strongest label the vocabulary offers, so a deleted gate
			// behind one is the most misleading state in the system.
			f := newFixture(fluxCluster)
			writeTracked(f, "platform/gateway/extra.yaml",
				"# claim(enforced) ghost-gate: guarded by a test that was deleted\n"+
					"#   j: TestThatNoLongerExists\n#   f: the gate is removed\n"+
					"#   scope: path:platform/gateway\n")
			res := f.run("claims")
			Expect(res.Code).To(Equal(1))
			Expect(res.Out).To(ContainSubstring("claim-enforced-resolves"))
		})

		It("reports a superseded claim with no successor", func() {
			f := newFixture(fluxCluster)
			writeTracked(f, "platform/gateway/extra.yaml",
				"# claim(superseded) orphan: this was believed and is false\n"+
					"#   scope: path:platform/gateway\n")
			res := f.run("claims")
			Expect(res.Code).To(Equal(1))
			Expect(res.Out).To(ContainSubstring("claim-superseded"))
		})

		It("reports two claims sharing an id but saying different things", func() {
			f := newFixture(fluxCluster)
			writeTracked(f, "platform/gateway/extra.yaml",
				"# claim(asserted) gateway-no-tls-here: TLS actually terminates right here\n")
			res := f.run("claims")
			Expect(res.Code).To(Equal(1))
			Expect(res.Out).To(ContainSubstring("claim-contradiction"))
		})

		It("reports a claim with no scope, which can neither decay nor project", func() {
			f := newFixture(fluxCluster)
			writeTracked(f, "platform/gateway/extra.yaml",
				"# claim(verified@2026-01-01) unscoped: a fact about nothing in particular\n"+
					"#   j: a command\n#   f: a falsifier\n")
			res := f.run("claims")
			Expect(res.Code).To(Equal(1))
			Expect(res.Out).To(ContainSubstring("claim-scope"))
		})
	})

	// ---- decay ------------------------------------------------------------------------

	Describe("decay", func() {
		It("demotes a verified claim whose scope changed after the stamp", func() {
			// gateway-port-is-8080 is stamped 2020-01-01 and scoped to deployment.yaml, which
			// the fixture builder commits far later. The date is deliberately absurd so the
			// spec cannot pass by accident of clock or commit ordering.
			f := newFixture(fluxCluster)
			res := f.run("claims")
			Expect(res.Out).To(ContainSubstring("claim-decayed"))
			Expect(res.Out).To(ContainSubstring("gateway-port-is-8080"))
			Expect(res.Out).To(ContainSubstring("re-run"),
				"a decay finding must name the command to re-run, or it is a complaint rather than a task")
		})

		It("does NOT decay the enforced claim on the same file", func() {
			// Enforced is continuous, not point-in-time. Both claims sit in the same file with
			// the same scope, so only the modality can explain a difference — which is what
			// makes this pair worth having.
			f := newFixture(fluxCluster)
			out := f.run("claims").Out
			decayLines := []string{}
			for _, l := range strings.Split(out, "\n") {
				if strings.Contains(l, "claim-decayed") || strings.Contains(l, "was verified@") {
					decayLines = append(decayLines, l)
				}
			}
			Expect(strings.Join(decayLines, "\n")).NotTo(ContainSubstring("gateway-replica-floor"))
		})
	})

	// ---- project ----------------------------------------------------------------------

	Describe("projection into an existing README", func() {
		It("renders a YAML-comment claim into the region with its falsifier", func() {
			f := newFixture(fluxCluster)
			Expect(f.run("generate").Code).To(Equal(0))
			readme := f.read("platform/gateway/README.md")

			Expect(readme).To(ContainSubstring("gateway-replica-floor"))
			Expect(readme).To(ContainSubstring("anti-affinity"),
				"the falsifier column is the one a reader checks first and must be rendered")
			Expect(readme).To(ContainSubstring("deployment.yaml"),
				"a projected claim must link back to the source it is maintained in")
		})

		It("leaves the prose outside the markers byte-identical", func() {
			// The rule that makes this adoptable. If generation could touch surrounding prose,
			// turning it on for a folder with a good README would be a rewrite rather than an
			// addition.
			f := newFixture(fluxCluster)
			before := f.read("platform/gateway/README.md")
			outsideBefore := before[:strings.Index(before, "<!-- docs:gen:knowledge -->")]
			f.run("generate")
			after := f.read("platform/gateway/README.md")
			Expect(after).To(HavePrefix(outsideBefore))
		})

		It("supports TWO independent regions in one document", func() {
			f := newFixture(fluxCluster)
			f.run("generate")
			readme := f.read("platform/gateway/README.md")
			Expect(readme).To(ContainSubstring("<!-- docs:gen:knowledge -->"))
			Expect(readme).To(ContainSubstring("<!-- docs:gen:inline-docs -->"))
			Expect(readme).To(ContainSubstring("Request path"), "the diagram block's title")
			Expect(readme).To(ContainSubstring("```mermaid"), "a diagram must be fenced as mermaid")
		})

		It("restores a clobbered region exactly, without touching the prose", func() {
			f := newFixture(fluxCluster)
			f.run("generate")
			good := f.read("platform/gateway/README.md")

			clobbered := strings.Replace(good,
				"<!-- docs:gen:knowledge -->", "<!-- docs:gen:knowledge -->\nGARBAGE\n", 1)
			f.write("platform/gateway/README.md", clobbered)
			Expect(f.run("check").Code).To(Equal(1), "check must notice a hand-edited region")

			f.run("generate")
			Expect(f.read("platform/gateway/README.md")).To(Equal(good))
		})
	})

	// ---- scaffold ---------------------------------------------------------------------

	Describe("scaffolding a folder with no README", func() {
		It("creates the document, with a banner saying what is generated", func() {
			f := newFixture(plainDirs)
			target := f.path("lib/httpx/README.md")
			_, err := os.Stat(target)
			Expect(os.IsNotExist(err)).To(BeTrue(), "the sample must start with NO README here")

			Expect(f.run("generate").Code).To(Equal(0))
			out := f.read("lib/httpx/README.md")

			Expect(out).To(HavePrefix("# httpx"))
			Expect(out).To(ContainSubstring("generated from inline"),
				"a scaffolded file must announce its own origin — that is the objection the "+
					"no-create rule was protecting, answered rather than bypassed")
			Expect(out).To(ContainSubstring("<!-- docs:gen:inline-docs -->"),
				"markers must be present so the NEXT person can add prose and keep regenerating")
		})

		It("builds headings from the DSL's section and order, not from config", func() {
			f := newFixture(plainDirs)
			f.run("generate")
			out := f.read("lib/httpx/README.md")

			Expect(out).To(ContainSubstring("### Behaviour"))
			Expect(strings.Index(out, "Retry policy")).To(BeNumerically("<", strings.Index(out, "Call path")),
				"order: 10 must render before order: 20")
		})

		It("preserves relative indentation inside the mermaid block", func() {
			// mermaid nests by indentation. Flattening it produces a diagram that renders as a
			// list, which is worse than no diagram because it looks deliberate.
			f := newFixture(plainDirs)
			f.run("generate")
			out := f.read("lib/httpx/README.md")
			Expect(out).To(ContainSubstring("flowchart TD"))
			Expect(out).To(ContainSubstring("  call[caller]"), "the two-space nesting must survive")
		})

		It("refuses to create the file when scaffold is NOT set", func() {
			// The default must stay a refusal: a generated document wearing a hand-written
			// document's name is what marker ownership exists to prevent.
			f := newFixture(plainDirs)
			cfg := f.read("config.yaml")
			f.write("config.yaml", strings.Replace(cfg, "    scaffold: true\n", "", 1))
			mustRemove(f.path("lib/httpx/README.md"))

			res := f.run("generate")
			Expect(res.Code).NotTo(Equal(0))
			Expect(res.Err).To(ContainSubstring("does not exist"))
		})
	})

	// ---- extract ----------------------------------------------------------------------

	Describe("extracting claims from prose", func() {
		It("resolves a sentence to the line its subject is DEFINED at", func() {
			f := newFixture(fluxCluster)
			writeTracked(f, "platform/gateway/NOTES.md",
				"---\ntype: note\nstatus: current\ncovers:\n  - repo\n---\n\n"+
					"# Notes\n\nThe gateway must never expose `containerPort` directly to the internet.\n")
			res := f.run("extract", "platform/gateway/NOTES.md")
			Expect(res.Code).To(Equal(0))
			Expect(res.Out).To(ContainSubstring("deployment.yaml"),
				"the anchor `containerPort` is defined in deployment.yaml and nowhere else here")
			Expect(res.Out).To(ContainSubstring("claim(verified@YYYY-MM-DD)"),
				"the output must be a fillable skeleton, not just a location")
		})

		It("says so when an assertion names nothing resolvable, instead of guessing", func() {
			// A confidently wrong destination is worse than an unfiled claim: it puts the
			// knowledge somewhere nobody will look and marks the job done.
			f := newFixture(fluxCluster)
			writeTracked(f, "platform/gateway/NOTES.md",
				"---\ntype: note\nstatus: current\ncovers:\n  - repo\n---\n\n"+
					"# Notes\n\nThe `nonexistent-token-xyz` must always be set because it matters.\n")
			res := f.run("extract", "platform/gateway/NOTES.md")
			Expect(res.Out).To(ContainSubstring("DESTINATION: none"))
		})
	})

	// ---- idempotence ------------------------------------------------------------------

	Describe("idempotence", func() {
		for _, s := range samples {
			s := s
			It("is a fixed point after one generate ("+s.Name+")", func() {
				f := newFixture(s)
				Expect(f.run("generate").Code).To(Equal(0))
				first := snapshotTree(f.Root)

				Expect(f.run("generate").Code).To(Equal(0))
				Expect(snapshotTree(f.Root)).To(Equal(first),
					"a second generate changed bytes — `check` cannot be a gate if generate is unstable")

				Expect(f.run("check").Code).To(Equal(0))
			})
		}
	})
})

// writeTracked writes a file AND stages it.
//
// Claim sources come from `git ls-files`, the same corpus the doc loader uses, so a file merely
// written into the fixture is invisible to `docsgen claims`. That is correct behaviour — an
// uncommitted file documents nothing for anyone else — but it means a spec that writes a claim
// and expects a finding must track it, or it asserts against a file the tool cannot see and
// fails for a reason unrelated to the rule under test.
func writeTracked(f *fixture, rel, content string) {
	GinkgoHelper()
	f.write(rel, content)
	if !skipCommit() {
		runGit(f.Root, nil, "add", rel)
	}
}

// snapshotTree hashes every markdown file so an idempotence spec compares the whole tree rather
// than the one artifact a spec happened to name.
func snapshotTree(root string) map[string]string {
	out := map[string]string{}
	_ = filepath.Walk(root, func(p string, info os.FileInfo, err error) error {
		if err != nil || info == nil || info.IsDir() || !strings.HasSuffix(p, ".md") {
			return nil
		}
		b, rerr := os.ReadFile(p)
		if rerr == nil {
			rel, _ := filepath.Rel(root, p)
			out[rel] = string(b)
		}
		return nil
	})
	return out
}
