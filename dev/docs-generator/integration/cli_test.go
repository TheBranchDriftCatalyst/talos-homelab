package integration_test

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	"github.com/onsi/gomega/gexec"
)

// The command-line surface: argv in, exit code out.
//
// Exit codes are the whole reason a CI gate can exist, so they are asserted as a table rather
// than scattered through the behavioural specs. 0 means "nothing to do", 1 means "the repo is
// out of date and a human must act", 2 means "the tool could not answer" — and conflating the
// last two is the failure that turns a gate into noise, because an I/O fault then reads as
// ordinary drift and gets regenerated over.

var _ = Describe("the command-line contract", Label("integration"), func() {

	DescribeTable("exit codes",
		func(setup func(fx *fixture), raw bool, args []string, want int) {
			fx := newFixture(fluxCluster)
			if setup != nil {
				setup(fx)
			}
			var res result
			if raw {
				res = fx.runRaw(args...)
			} else {
				res = fx.run(args...)
			}
			Expect(res.Session).To(gexec.Exit(want), "stdout:\n%s\nstderr:\n%s", res.Out, res.Err)
		},

		Entry("generate succeeds when it has work to do",
			nil, false, []string{"generate"}, 0),

		Entry("generate still succeeds when it wrote nothing — the steady state must not read as failure",
			func(fx *fixture) { Expect(fx.run("generate").Code).To(Equal(0)) },
			false, []string{"generate"}, 0),

		Entry("check passes once the artifact is current",
			func(fx *fixture) { Expect(fx.run("generate").Code).To(Equal(0)) },
			false, []string{"check"}, 0),

		Entry("check fails when the artifact was never generated",
			nil, false, []string{"check"}, 1),

		Entry("check fails after a hand-edit",
			func(fx *fixture) {
				Expect(fx.run("generate").Code).To(Equal(0))
				fx.write(artifactRel, fx.read(artifactRel)+"\nedited by hand\n")
			},
			false, []string{"check"}, 1),

		Entry("lint fails when an error-severity rule fires",
			nil, false, []string{"lint", "-rule", fluxCluster.ErrorRule}, 1),

		Entry("lint passes when only warn-severity findings exist",
			nil, false, []string{"lint", "-rule", fluxCluster.WarnOnlyRule}, 0),

		Entry("lint passes when an enabled rule finds nothing at all",
			nil, false, []string{"lint", "-rule", "tickets-in-body"}, 0),

		Entry("links is lint restricted to broken-links, and fails the same way",
			nil, false, []string{"links"}, 1),

		Entry("an unknown subcommand is a usage error, not a lint failure",
			nil, true, []string{"definitely-not-a-command"}, 2),

		Entry("no arguments at all is a usage error",
			nil, true, []string{}, 2),
	)

	It("prints usage on stderr for an unknown subcommand, so the exit code is explainable", func() {
		fx := newFixture(fluxCluster)
		res := fx.runRaw("definitely-not-a-command")
		Expect(res.Code).To(Equal(2))
		Expect(res.Err).To(ContainSubstring("docsgen — documentation linter"))
		Expect(res.Err).To(ContainSubstring("usage: docsgen <command>"))
		Expect(res.Out).To(BeEmpty(), "usage belongs on stderr; stdout is for report content")
	})

	It("prints usage on stderr when invoked with no arguments", func() {
		fx := newFixture(fluxCluster)
		res := fx.runRaw()
		Expect(res.Code).To(Equal(2))
		Expect(res.Err).To(ContainSubstring("usage: docsgen <command>"))
	})

	It("distinguishes a genuine I/O fault from an out-of-date artifact, because a permission "+
		"error that reads as `missing` gets regenerated over", func() {
		fx := newFixture(fluxCluster)
		// A directory where the artifact belongs: os.ReadFile fails with something that is NOT
		// fs.ErrNotExist, which is precisely the case that used to be reported as `missing`.
		Expect(os.MkdirAll(fx.artifact(), 0o755)).To(Succeed())

		res := fx.run("check")
		Expect(res.Session).To(gexec.Exit(2), "an I/O fault must not share an exit code with drift")
		Expect(res.Err).To(ContainSubstring("generate:"))
		Expect(res.Out).NotTo(ContainSubstring("missing"))
		Expect(res.Out).NotTo(ContainSubstring("drift"))

		gen := fx.run("generate")
		Expect(gen.Session).To(gexec.Exit(2))
		Expect(gen.Err).To(ContainSubstring("generate:"))
	})

	It("keeps every report on stdout and every diagnostic on stderr, so a report can be piped", func() {
		fx := newFixture(fluxCluster)
		res := fx.run("components")
		Expect(res.Code).To(Equal(0))
		Expect(res.Out).To(ContainSubstring("slug"))
		// The sample deliberately contains a Kustomization with no spec.path.
		Expect(res.Err).To(ContainSubstring("WARN"))
		Expect(res.Out).NotTo(ContainSubstring("WARN"))
	})

	DescribeTable("no absolute path from the machine it ran on reaches stdout",
		func(s *sample) {
			fx := newFixture(s)
			for _, cmd := range []string{"generate", "check", "lint", "links", "components", "frontmatter", "stale"} {
				res := fx.run(cmd)
				Expect(res.Out).NotTo(ContainSubstring(fx.Root),
					"`%s` leaked the repo root into stdout; its output is not portable and a "+
						"golden could never match from a second machine", cmd)
			}
			Expect(fx.read(artifactRel)).NotTo(ContainSubstring(fx.Root),
				"the generated artifact embeds the absolute path it was generated from")
		},
		Entry("flux-cluster", fluxCluster),
		Entry("plain-dirs", plainDirs),
	)
})

var _ = Describe("prettier agreement", Label("integration"), func() {
	// The normaliser reimplements prettier's markdown table layout so generated output is a
	// prettier FIXED POINT. If it is not, `dev:lint:prettier` and `docs:check` rewrite the file
	// past each other forever, with two CI gates taking turns failing.
	It("leaves generated output untouched, so the formatter and the docs gate cannot fight", func() {
		prettier := findPrettier()
		if prettier == nil {
			Skip("prettier is not on PATH and there is no vendored copy; this invariant is " +
				"unverified in this environment")
		}
		fx := newFixture(fluxCluster)
		Expect(fx.run("generate").Code).To(Equal(0))
		before := fx.read(artifactRel)

		cmd := exec.Command(prettier[0], append(append([]string{}, prettier[1:]...),
			"--write", artifactRel)...)
		cmd.Dir = fx.Root
		out, err := cmd.CombinedOutput()
		Expect(err).NotTo(HaveOccurred(), "prettier failed: %s", out)

		Expect(fx.read(artifactRel)).To(Equal(before), "prettier rewrote generated output")
		Expect(fx.run("check").Code).To(Equal(0), "check rejects the file after prettier touched it")
	})
})

// findPrettier locates a runnable prettier without reaching for the network. `npx prettier`
// would try to install one, which is not something a test suite may do.
func findPrettier() []string {
	if p, err := exec.LookPath("prettier"); err == nil {
		return []string{p}
	}
	for _, dir := range []string{"..", "../..", "../../.."} {
		candidate := filepath.Join(dir, "node_modules", ".bin", "prettier")
		if abs, err := filepath.Abs(candidate); err == nil {
			if info, statErr := os.Stat(abs); statErr == nil && !info.IsDir() {
				return []string{abs}
			}
		}
	}
	return nil
}

// trimmedLines is a small readability helper for specs that compare report bodies.
func trimmedLines(s string) []string {
	var out []string
	for _, line := range strings.Split(s, "\n") {
		if t := strings.TrimSpace(line); t != "" {
			out = append(out, t)
		}
	}
	return out
}
