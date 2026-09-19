package integration_test

import (
	"regexp"
	"strings"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

// A rule that cannot run says so, out loud, on stdout.
//
// THE DEFECT THIS PINS. `component-shape` measures nested kustomizations and `component-path`
// measures whether a DECLARED path exists. Under `components.kind: dirs` neither measurement
// exists — the count is structurally zero without kustomize, and a directory the walker found
// is on disk by construction. Both rules ran, found nothing, and were reported as a clean pass.
// The report therefore read as coverage of two checks that had never once been able to fire.
//
// THE FORMAT, AND WHY THE LEADING TOKEN MATTERS. A skip is announced as
//
//	skipped  component-shape  needs component.sub_units, which components.kind `dirs` does not report
//
// and NOT as `component-shape  [skipped]`. The second shape is indistinguishable from a rule
// block to anything reading this output by rule name — findingsFor() in fixture_test.go matches
// `rule + "  ["` — so a spec asserting "no component-shape findings" would pass identically
// whether the rule ran clean or never ran at all. That ambiguity is the defect; the format that
// announces its removal must not smuggle it back in. The leading token makes the line
// unmistakably a skip, and `(?m)^skipped\s+<rule>\b` an unambiguous assertion.
var _ = Describe("rules that cannot run", Label("integration"), func() {

	// The facts are declared per strategy, so the pairing is per sample: flux supplies
	// everything and must skip nothing, dirs supplies neither measurement and must skip exactly
	// these two. Both halves are asserted — a suite that only checked the dirs half would pass
	// for an implementation that skipped every rule everywhere.
	It("announces the two rules `dirs` cannot support, naming the missing fact and the kind", func() {
		fx := newFixture(plainDirs)
		out := fx.run("lint").Out

		Expect(out).To(MatchRegexp(`(?m)^skipped\s+component-path\b`),
			"component-path never fires under `dirs` and must say so rather than pass")
		Expect(out).To(MatchRegexp(`(?m)^skipped\s+component-shape\b`),
			"component-shape never fires under `dirs` and must say so rather than pass")

		Expect(out).To(ContainSubstring(
			"skipped  component-path   needs component.path_is_declared, which components.kind `dirs` does not report"))
		Expect(out).To(ContainSubstring(
			"skipped  component-shape  needs component.sub_units, which components.kind `dirs` does not report"))
	})

	It("does not dress a skip up as a rule block, because the harness reads rule blocks by name "+
		"and would swallow it", func() {
		out := newFixture(plainDirs).run("lint").Out

		for _, rule := range []string{"component-path", "component-shape"} {
			Expect(out).NotTo(ContainSubstring(rule+"  ["),
				"`%s` was printed in the `<rule>  [...]` shape; findingsFor() then reads it as a "+
					"rule block, and `no %s findings` means the same thing whether the rule ran "+
					"clean or never ran", rule, rule)
			Expect(findingsFor(out, rule)).To(BeEmpty(),
				"a skipped rule must contribute no findings at all")
		}
	})

	It("counts the skips on their own line AFTER the summary, whose bytes are what CI greps for", func() {
		out := newFixture(plainDirs).run("lint").Out

		// The summary itself is untouched: same count, same split, same spelling.
		Expect(out).To(ContainSubstring("\n6 finding(s): 4 error, 2 warn\n"))
		Expect(out).To(MatchRegexp(`\n\d+ finding\(s\): \d+ error, \d+ warn\n`))
		// …and the skip count follows it rather than being folded into it, so a skip can never
		// be mistaken for a finding by anything counting them.
		Expect(out).To(ContainSubstring(
			"\n6 finding(s): 4 error, 2 warn\n2 rule(s) could not run — see the `skipped` lines above\n"))
	})

	It("stays silent under a strategy that supplies every fact, so the announcement means "+
		"something when it appears", func() {
		out := newFixture(fluxCluster).run("lint").Out

		Expect(out).NotTo(ContainSubstring("skipped"))
		Expect(out).NotTo(ContainSubstring("could not run"))
		// And the two rules genuinely ran there — otherwise silence would prove nothing.
		Expect(findingsFor(out, "component-path")).NotTo(BeEmpty())
		Expect(findingsFor(out, "component-shape")).NotTo(BeEmpty())
	})

	It("keeps a skipped rule out of the exit code, so a repo whose strategy is narrower than "+
		"Flux's does not land red on the day it adopts the tool", func() {
		fx := newFixture(plainDirs)

		// -rule isolates the question: this run produces NO findings at all, so the exit code
		// is a statement about the skip and nothing else. Against the full lint the three
		// error-severity findings would mask a skip that had been counted.
		res := fx.run("lint", "-rule", "component-shape")

		Expect(res.Out).To(MatchRegexp(`(?m)^skipped\s+component-shape\b`))
		Expect(res.Out).To(ContainSubstring("0 finding(s): 0 error, 0 warn"))
		Expect(res.Out).To(ContainSubstring("1 rule(s) could not run"))
		Expect(res.Code).To(Equal(0),
			"a rule that could not run failed the gate; a red gate nobody can turn green is a "+
				"gate people learn to bypass")
	})

	It("reports a skip exactly once per rule, in rule-name order", func() {
		out := newFixture(plainDirs).run("lint").Out

		var skips []string
		for _, line := range strings.Split(out, "\n") {
			if strings.HasPrefix(line, "skipped") {
				skips = append(skips, strings.Fields(line)[1])
			}
		}
		Expect(skips).To(Equal([]string{"component-path", "component-shape"}),
			"skips must be listed once each and in a stable order, or the report is not diffable")
	})

	// The skip block sits between the last rule block and the summary, separated by blank lines
	// on both sides. Asserted because the two parsers in this suite — findingsFor() and
	// parseLintFindings() — both end a rule block on a line that is blank or unindented, and a
	// skip line landing INSIDE a block would be read as a truncated finding.
	It("prints the skips as their own block, outside every rule block", func() {
		out := newFixture(plainDirs).run("lint").Out

		Expect(out).To(MatchRegexp(`(?m)^\n?skipped`))
		for _, line := range strings.Split(out, "\n") {
			if strings.HasPrefix(strings.TrimSpace(line), "skipped ") {
				Expect(line).NotTo(HavePrefix("  "),
					"a skip line is indented like a finding: %q", line)
			}
		}
		// The reconciliation in declarations_test.go reads this same output; if a skip line
		// were ever parsed as a finding it would show up there as an undeclared one.
		Expect(parseLintFindings(out)).NotTo(BeEmpty())
		for _, f := range parseLintFindings(out) {
			Expect(f.Rule).NotTo(Equal("skipped"))
		}
	})
})

// skipLineRe is the shape a skip line must keep: leading token, rule id, then the reason. Used
// by the golden-adjacent spec above and kept here so the two cannot drift apart.
var skipLineRe = regexp.MustCompile(`(?m)^skipped\s{2}(\S+)\s{2,}needs .+, which components\.kind ` + "`" + `\S+` + "`" + ` does not report$`)

var _ = Describe("the skip line's shape", Label("integration"), func() {
	It("names the missing fact and the kind that cannot report it, because the remedy is a "+
		"config decision and `component-shape was skipped` sends the reader hunting for a bug", func() {
		out := newFixture(plainDirs).run("lint").Out

		matches := skipLineRe.FindAllStringSubmatch(out, -1)
		Expect(matches).To(HaveLen(2), "the skip lines do not match the documented shape:\n%s", out)
		Expect(matches[0][1]).To(Equal("component-path"))
		Expect(matches[1][1]).To(Equal("component-shape"))
	})
})
