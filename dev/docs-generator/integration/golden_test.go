package integration_test

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

// Golden files record EXACT bytes for one exact sample.
//
// Read them as a tripwire, never as a definition of correct. A golden tells you something
// changed; it cannot tell you the new thing is wrong, and it cannot tell you the old thing was
// right. That is why the invariant specs beside them assert properties instead, and why a
// golden that disagrees with an invariant means the golden is stale — not the invariant.
//
// Regenerate with `go test ./integration -update-golden`. Never hand-edit one until a spec goes
// green: a golden nobody understands gets regenerated blindly the first time it fails, and from
// then on it blesses whatever the tool happens to do.

func goldenPath(sampleName, name string) string {
	return filepath.Join("testdata", "golden", sampleName, name)
}

// matchGolden compares scrubbed output against the recorded bytes, or rewrites them under
// -update-golden. The scrub is what keeps a golden reproducible from any temp directory.
func (f *fixture) matchGolden(name, actual string) {
	GinkgoHelper()
	path := goldenPath(f.Sample.Name, name)
	scrubbed := f.scrub(actual)

	Expect(scrubbed).NotTo(ContainSubstring(rootPlaceholder),
		"%s leaked an absolute path into output that is meant to be path-independent; "+
			"the golden could never match from a second temp directory", name)

	if *updateGolden {
		Expect(os.MkdirAll(filepath.Dir(path), 0o755)).To(Succeed())
		Expect(os.WriteFile(path, []byte(scrubbed), 0o644)).To(Succeed())
		return
	}

	want, err := os.ReadFile(path)
	Expect(err).NotTo(HaveOccurred(),
		"no golden at %s — regenerate with `go test ./integration -update-golden`", path)

	// Both sides land in the review area whether or not they agree, so a mismatch is readable
	// without re-running anything.
	f.record("_golden", name+".expected", string(want))
	f.record("_golden", name+".actual", scrubbed)
	if string(want) != scrubbed {
		f.record("_golden", name+".diff", lineDiff(string(want), scrubbed))
	}

	if string(want) != scrubbed {
		Fail(fmt.Sprintf(
			"golden %s does not match.\n\n%s\n\n"+
				"If this change is intended, regenerate with:\n"+
				"    go test ./integration -update-golden\n"+
				"If it is not, the tool changed behaviour — read the diff before regenerating.",
			path, lineDiff(string(want), scrubbed)))
	}
}

// lineDiff renders a readable line-by-line comparison. A golden failure that only says "bytes
// differ" is a golden that gets regenerated without being read.
func lineDiff(want, got string) string {
	wl := strings.Split(want, "\n")
	gl := strings.Split(got, "\n")
	var b strings.Builder
	b.WriteString("--- golden (expected)\n+++ actual\n")

	n := len(wl)
	if len(gl) > n {
		n = len(gl)
	}
	shown := 0
	for i := 0; i < n; i++ {
		var w, g string
		if i < len(wl) {
			w = wl[i]
		}
		if i < len(gl) {
			g = gl[i]
		}
		if w == g {
			continue
		}
		if shown >= 40 {
			fmt.Fprintf(&b, "… further differences suppressed\n")
			break
		}
		if i < len(wl) {
			fmt.Fprintf(&b, "-%4d %s\n", i+1, w)
		}
		if i < len(gl) {
			fmt.Fprintf(&b, "+%4d %s\n", i+1, g)
		}
		shown++
	}
	return b.String()
}

var _ = Describe("golden output", Label("integration"), func() {
	for _, s := range samples {
		s := s

		Context("sample "+s.Name, func() {
			var fx *fixture

			BeforeEach(func() {
				fx = newFixture(s)
			})

			It("generates an inventory whose exact bytes are recorded, because those bytes are "+
				"also the prettier fixed-point guarantee", func() {
				res := fx.run("generate")
				Expect(res.Code).To(Equal(0), res.Err)
				fx.matchGolden("component-inventory.md", fx.read(artifactRel))
			})

			It("reports the same findings, in the same order, with the same severities", func() {
				fx.matchGolden("lint.txt", fx.run("lint").Out)
			})

			It("enumerates the same components with the same shape measurements", func() {
				fx.matchGolden("components.txt", fx.run("components").Out)
			})

			It("names the same migration worklist", func() {
				fx.matchGolden("frontmatter.txt", fx.run("frontmatter").Out)
			})

			It("reports the same docs as stale, with dates rather than day counts", func() {
				fx.matchGolden("stale.txt", fx.run("stale").Out)
			})
		})
	}
})
