// Package integration_test drives the real `docsgen` binary as a subprocess.
//
// BLACK BOX ON PURPOSE. Nothing here imports the `main` package or reaches for an unexported
// function. What is asserted is argv in, stdout/stderr/exit-code/bytes-on-disk out — because
// that quadruple is exactly the contract CI depends on, and it is the only part of the tool a
// refactor is not free to change. The unit layer beside this one covers the internals.
//
// EVERY SPEC RUNS AGAINST A SYNTHESISED FIXTURE, never against this repository. Asserting on
// the live cluster's component set would make the suite fail the next time somebody adds a
// Kustomization, which trains everyone to ignore it. The fixtures are hand-written sample
// repositories under testdata/samples/, copied into a temp dir and turned into a real git
// repository at suite start — see fixture_test.go for why the git part is not optional.
package integration_test

import (
	"flag"
	"os"
	"path/filepath"
	"testing"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	"github.com/onsi/gomega/gexec"
)

const modulePath = "github.com/TheBranchDriftCatalyst/talos-homelab/dev/docs-generator"

// updateGolden rewrites testdata/golden/** instead of comparing against it.
//
//	go test ./integration -update-golden
//	go run github.com/onsi/ginkgo/v2/ginkgo ./integration -- -update-golden
//
// Regenerating is one command so that nobody is ever tempted to hand-edit a golden until the
// spec goes green, which is how a snapshot test quietly stops meaning anything.
var updateGolden = flag.Bool("update-golden", false,
	"rewrite testdata/golden/** from the current output instead of comparing against it")

// binPath is the gexec-built docsgen, shared by every parallel process.
var binPath string

func TestIntegration(t *testing.T) {
	RegisterFailHandler(Fail)
	RunSpecs(t, "docsgen integration suite")
}

var _ = SynchronizedBeforeSuite(func() []byte {
	// GOWORK=off before the build, not in the shell that launched the test: gexec shells out
	// to `go build` with THIS process's environment, and a parent go.work otherwise drags
	// sibling modules in and the build fails. Setting it here means the suite builds the same
	// way however it was invoked.
	Expect(os.Setenv("GOWORK", "off")).To(Succeed())
	resetArtifactsRoot()

	path, err := gexec.Build(modulePath)
	Expect(err).NotTo(HaveOccurred(), "building %s", modulePath)
	return []byte(path)
}, func(data []byte) {
	binPath = string(data)
	assertSamplesAreReal()
})

var _ = SynchronizedAfterSuite(func() {}, func() {
	gexec.CleanupBuildArtifacts()
})

// assertSamplesAreReal is the anti-vacuity gate, and it runs before any spec.
//
// docsgen's walker is `git ls-files` and its dates come from one `git log --name-only` pass. A
// fixture that is merely a directory of files therefore yields ZERO docs, ZERO dates and — for
// the flux samples — components whose staleness can never be computed. Every spec downstream
// would then pass while asserting nothing at all, which is by far the most likely way this
// suite ends up green and worthless.
//
// So: prove out loud that each sample enumerates components AND sees its docs, before the first
// spec is allowed to draw a conclusion from either.
func assertSamplesAreReal() {
	for _, s := range samples {
		// Always a temp dir, even under -preserve-artifacts: this runs outside any spec, so
		// there is no spec name to file it under, and an empty Base would write transcripts
		// into the package directory.
		base := mustTempDir()
		root := filepath.Join(base, "repo")
		buildFixtureAt(root, s, !skipCommit())
		fx := &fixture{Root: root, Base: base, Sample: s}

		comps := fx.run("components")
		Expect(comps.Code).To(Equal(0), "sample %s: `components` failed:\n%s", s.Name, comps.Err)
		// Parse the count; do NOT substring-match "0 components". "10 components" CONTAINS
		// "0 components", so the substring form would have fired a false alarm the first time a
		// sample reached ten — and this failure message reads exactly like the real failure it
		// exists to detect, which is the worst possible way for a guard to be wrong.
		Expect(componentCount(comps.Out)).To(BeNumerically(">", 0),
			"sample %s enumerated NO components — the fixture is not real, and every spec "+
				"downstream would pass vacuously", s.Name)

		// `stale` is the one report that silently empties when the doc and its subject land in
		// the same commit second, so assert it is populated rather than trusting it.
		st := fx.run("stale")
		Expect(st.Code).To(Equal(0), "sample %s: `stale` failed:\n%s", s.Name, st.Err)
		Expect(st.Out).NotTo(ContainSubstring("no docs report stale"),
			"sample %s: `stale` found nothing — the fixture's commit timestamps collapsed and "+
				"every staleness assertion downstream would pass vacuously", s.Name)

		// The scoped artifact is table-driven like everything else, so an empty slot in the
		// table would make every scoping spec iterate over nothing and pass. Refuse the sample
		// instead, here, before any spec is allowed to draw a conclusion.
		Expect(s.ScopeRel).NotTo(BeEmpty(),
			"sample %s declares no scoped artifact, so every scoping spec would run against "+
				"nothing and report green", s.Name)
		Expect(s.ScopePrefix).NotTo(BeEmpty(), "sample %s declares no scope prefix", s.Name)
		Expect(s.ScopeSlugs).NotTo(BeEmpty(),
			"sample %s: a scope covering no component cannot show that scoping includes anything", s.Name)
		Expect(s.ScopeExcludes).NotTo(BeEmpty(),
			"sample %s: a scope excluding no component cannot show that scoping excludes anything — "+
				"an artifact ignoring the filter entirely would satisfy every remaining assertion", s.Name)

		front := fx.run("frontmatter")
		Expect(front.Code).To(Equal(0), "sample %s: `frontmatter` failed:\n%s", s.Name, front.Err)
		for _, doc := range s.Worklist {
			Expect(front.Out).To(ContainSubstring(doc),
				"sample %s: `frontmatter` cannot see %s — `git ls-files` returned nothing, so "+
					"the fixture was never committed and no doc rule can fire", s.Name, doc)
		}

		Expect(os.RemoveAll(base)).To(Succeed())
	}
}

func mustTempDir() string {
	dir, err := os.MkdirTemp("", "docsgen-bootstrap-*")
	Expect(err).NotTo(HaveOccurred())
	// macOS hands out /var/folders/..., a symlink to /private/var/folders/.... git reports the
	// resolved path, so leaving it unresolved makes every path comparison subtly wrong.
	resolved, err := filepath.EvalSymlinks(dir)
	Expect(err).NotTo(HaveOccurred())
	return resolved
}
