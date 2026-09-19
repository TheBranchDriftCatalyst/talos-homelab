package integration_test

import (
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

// Behavioural invariants: properties that must hold for ANY input, asserted against the samples
// rather than derived from them.
//
// This is the half of the suite with a shelf life. A golden says "these bytes changed"; an
// invariant says "generate must always produce output it would itself accept", and that keeps
// its meaning through every refactor — including the strategy-pattern rework of component
// enumeration that this suite exists to be the safety net for. Everything in this file is
// written to be strategy-agnostic and runs against every sample in the table.

var componentCountRe = regexp.MustCompile(`(\d+) components,`)

func componentCount(out string) int {
	GinkgoHelper()
	m := componentCountRe.FindStringSubmatch(out)
	Expect(m).To(HaveLen(2), "could not find the component count in:\n%s", out)
	n, err := strconv.Atoi(m[1])
	Expect(err).NotTo(HaveOccurred())
	return n
}

func nestedCount(row string) int {
	GinkgoHelper()
	fields := strings.Fields(row)
	Expect(len(fields)).To(BeNumerically(">=", 5), "unexpected components row: %q", row)
	n, err := strconv.Atoi(fields[2])
	Expect(err).NotTo(HaveOccurred())
	return n
}

func readmeCell(row string) string {
	GinkgoHelper()
	fields := strings.Fields(row)
	Expect(len(fields)).To(BeNumerically(">=", 5), "unexpected components row: %q", row)
	return fields[1]
}

var _ = Describe("docsgen invariants", Label("integration"), func() {
	for _, s := range samples {
		s := s

		Context("sample "+s.Name+" ("+s.Kind+")", func() {
			var fx *fixture

			BeforeEach(func() { fx = newFixture(s) })

			// -------------------------------------------------------------------------------
			// Generation and convergence
			// -------------------------------------------------------------------------------

			It("creates the artifact on the first run and leaves it readable by everything that "+
				"has to read it", func() {
				Expect(fx.exists(fx.artifactRel())).To(BeFalse(), "the sample must not ship a generated artifact")

				res := fx.run("generate")
				Expect(res.Code).To(Equal(0), res.Err)
				Expect(res.Out).To(ContainSubstring(fx.artifactRel()))

				Expect(fx.exists(fx.artifactRel())).To(BeTrue())
				Expect(fx.read(fx.artifactRel())).NotTo(BeEmpty())
				// CreateTemp makes 0600; a generated doc every tool in the repo reads must not
				// inherit that.
				Expect(fx.mode(fx.artifactRel())).To(Equal(os.FileMode(0o644)))
			})

			It("reports `unchanged` on a second run and does not rewrite the file, so mtime and "+
				"`git status` stay clean", func() {
				Expect(fx.run("generate").Code).To(Equal(0))

				// Backdate first: a rewrite landing inside one filesystem timestamp tick is
				// indistinguishable from no write at all, and a naive comparison would pass.
				before := fx.backdate(fx.artifactRel())

				res := fx.run("generate")
				Expect(res.Code).To(Equal(0), res.Err)
				Expect(res.Out).To(ContainSubstring("unchanged"))
				Expect(fx.modTime(fx.artifactRel())).To(Equal(before),
					"the artifact was rewritten despite being byte-identical")
			})

			It("always passes its own check straight after generating — the tool must never "+
				"emit output it would itself reject", func() {
				Expect(fx.run("generate").Code).To(Equal(0))

				res := fx.run("check")
				Expect(res.Code).To(Equal(0),
					"check rejected the bytes generate had just written:\n%s\n%s", res.Out, res.Err)
				Expect(res.Out).To(ContainSubstring("unchanged"))
			})

			It("produces byte-identical output from two clean starts, because a generator with "+
				"volatile content makes its own drift gate noise", func() {
				Expect(fx.run("generate").Code).To(Equal(0))
				first := fx.read(fx.artifactRel())

				Expect(os.Remove(fx.artifact())).To(Succeed())
				Expect(fx.run("generate").Code).To(Equal(0))
				Expect(fx.read(fx.artifactRel())).To(Equal(first))
			})

			It("produces identical bytes from a different temp root built in reverse file order, "+
				"so neither the absolute path nor directory enumeration order reaches the output", func() {
				Expect(fx.run("generate").Code).To(Equal(0))
				mine := fx.read(fx.artifactRel())

				other := filepath.Join(mustTempDir(), "repo")
				defer os.RemoveAll(filepath.Dir(other))
				Expect(os.MkdirAll(other, 0o755)).To(Succeed())
				Expect(copyTreeReversed(sampleDir(s.Name), other)).To(Succeed())
				runGit(other, nil, "init", "-q", "-b", "main")
				runGit(other, nil, "config", "user.email", "fixture@example.invalid")
				runGit(other, nil, "config", "user.name", "docsgen fixture")
				runGit(other, nil, "add", "-A")
				runGit(other, dateEnv(importDate), "commit", "-q", "-m", "import")

				twin := &fixture{Root: other, Base: filepath.Dir(other), Sample: s}
				Expect(twin.run("generate").Code).To(Equal(0))

				Expect(twin.read(fx.artifactRel())).To(Equal(mine))
				Expect(mine).NotTo(ContainSubstring(fx.Root))
				Expect(mine).NotTo(ContainSubstring(other))
			})

			It("ignores an untracked file, because the walker is `git ls-files` and not the "+
				"filesystem", func() {
				before := fx.run("lint").Out

				fx.write("untracked-note.md", "# Untracked\n\nA [dead link](./nope.md) nothing may see.\n")
				Expect(fx.exists("untracked-note.md")).To(BeTrue())

				Expect(fx.run("lint").Out).To(Equal(before),
					"an untracked file changed the output — the walker is reading the filesystem, "+
						"which in a real repo means worktrees and vendored copies")
			})

			It("ignores a tracked file that matches an `exclude` pattern, which is the mechanism "+
				"that keeps a frozen archive from producing findings nobody will action", func() {
				before := fx.run("lint").Out

				noisy := filepath.Join(s.ExcludedDir, "injected-noise.md")
				fx.write(noisy, "---\ntitle: banned\n---\n\nA [dead link](./nowhere.md).\n")
				runGit(fx.Root, nil, "add", "-A")

				after := fx.run("lint").Out
				Expect(after).To(Equal(before))
				Expect(after).NotTo(ContainSubstring(noisy))
			})

			// -------------------------------------------------------------------------------
			// Safety — what must never happen
			// -------------------------------------------------------------------------------

			It("never writes anything during `check`, in any of its three outcomes", func() {
				// absent
				before := fx.treeHash()
				Expect(fx.run("check").Code).To(Equal(1))
				Expect(fx.treeHash()).To(Equal(before), "check wrote to the tree when the artifact was absent")

				// current
				Expect(fx.run("generate").Code).To(Equal(0))
				before = fx.treeHash()
				Expect(fx.run("check").Code).To(Equal(0))
				Expect(fx.treeHash()).To(Equal(before), "check wrote to the tree when the artifact was current")

				// drifted
				fx.write(fx.artifactRel(), fx.read(fx.artifactRel())+"\nhand-edited\n")
				before = fx.treeHash()
				Expect(fx.run("check").Code).To(Equal(1))
				Expect(fx.treeHash()).To(Equal(before), "check wrote to the tree when the artifact had drifted")
			})

			It("never writes outside the root it was given", func() {
				outside := fx.outsideDir()
				before := hashTree(outside)
				for _, cmd := range []string{"generate", "check", "lint", "links", "components", "frontmatter", "stale"} {
					fx.run(cmd)
				}
				Expect(hashTree(outside)).To(Equal(before))
			})

			It("leaves no .docsgen-*.tmp behind, including after a run that failed", func() {
				for _, cmd := range []string{"generate", "check", "lint", "components", "frontmatter", "stale"} {
					fx.run(cmd)
				}
				// Force a write failure: a directory where the artifact belongs is a read error
				// that is NOT "not exist", which is the case that used to be misreported.
				Expect(os.RemoveAll(fx.artifact())).To(Succeed())
				Expect(os.MkdirAll(fx.artifact(), 0o755)).To(Succeed())
				fx.run("generate")

				Expect(fx.tempArtifacts()).To(BeEmpty(),
					"a temp file survived; an interrupted run can leave a half-written doc")
			})

			It("survives an unparseable doc rather than aborting the scan, because a linter that "+
				"dies on one bad file is useless exactly when you need it", func() {
				// No closing fence on the frontmatter block.
				fx.write(s.CleanDoc, "---\ntype: broken\nstatus: [unclosed\n\n# Still A Document\n")

				lint := fx.run("lint")
				Expect(lint.Code).To(BeNumerically("<=", 1), "the run aborted:\n%s", lint.Err)
				Expect(lint.Out).To(ContainSubstring("finding(s):"), "the summary line never printed")

				comps := fx.run("components")
				Expect(comps.Code).To(Equal(0))
				for _, slug := range s.Slugs {
					if slug == "secrets-operator" || slug == "secrets-store" {
						continue // see the two-Kustomizations spec; tracked separately
					}
					Expect(componentRow(comps.Out, slug)).NotTo(BeEmpty(),
						"component %s vanished because one doc failed to parse", slug)
				}
			})

			// -------------------------------------------------------------------------------
			// Monotonicity — proof the tool is actually looking
			// -------------------------------------------------------------------------------

			It("notices a component appearing", func() {
				before := fx.run("components")
				Expect(before.Code).To(Equal(0))

				slug := s.AddComponent(fx.Root)

				after := fx.run("components")
				Expect(componentRow(after.Out, slug)).NotTo(BeEmpty(), "the new component never appeared")
				Expect(componentCount(after.Out)).To(Equal(componentCount(before.Out) + 1))
			})

			It("notices a component disappearing", func() {
				before := fx.run("components")
				slug := s.RemoveComponent(fx.Root)

				after := fx.run("components")
				Expect(componentRow(after.Out, slug)).To(BeEmpty(), "the removed component is still reported")
				Expect(componentCount(after.Out)).To(Equal(componentCount(before.Out) - 1))
			})

			It("notices a component losing its colocated README, which is the question the "+
				"inventory really asks", func() {
				before := fx.run("components")
				Expect(readmeCell(componentRow(before.Out, s.ReadmeOwner))).To(Equal("yes"))

				Expect(os.Remove(fx.path(s.ReadmeFile))).To(Succeed())

				after := fx.run("components")
				Expect(readmeCell(componentRow(after.Out, s.ReadmeOwner))).To(Equal("-"))
			})

			It("notices one more nested kustomization under a component", func() {
				before := nestedCount(componentRow(fx.run("components").Out, s.NestedOwner))

				fx.write(filepath.Join(s.NestedDir, "extra", "kustomization.yaml"),
					"apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: []\n")

				after := nestedCount(componentRow(fx.run("components").Out, s.NestedOwner))
				Expect(after).To(Equal(before + 1))
			})

			It("notices a link breaking, and notices it being fixed again", func() {
				clean := fx.read(s.CleanDoc)
				Expect(findingsFor(fx.run("lint").Out, "broken-links")).NotTo(
					ContainElement(ContainSubstring(s.CleanDoc)))

				fx.write(s.CleanDoc, clean+"\nA [newly dead link](./definitely-not-here.md).\n")
				broken := fx.run("lint")
				Expect(broken.Code).To(Equal(1), "an error-severity finding did not fail the gate")
				Expect(findingsFor(broken.Out, "broken-links")).To(
					ContainElement(ContainSubstring("./definitely-not-here.md")))

				fx.write(s.CleanDoc, clean)
				Expect(findingsFor(fx.run("lint").Out, "broken-links")).NotTo(
					ContainElement(ContainSubstring("./definitely-not-here.md")))
			})

			It("notices a banned key appearing in frontmatter, and names the key", func() {
				clean := fx.read(s.CleanDoc)
				Expect(strings.HasPrefix(clean, "---\n")).To(BeTrue(), "%s has no frontmatter", s.CleanDoc)
				fx.write(s.CleanDoc, strings.Replace(clean, "---\n", "---\ntitle: injected by a spec\n", 1))

				res := fx.run("lint")
				Expect(res.Code).To(Equal(1))
				Expect(findingsFor(res.Out, "frontmatter-schema")).To(ContainElement(
					And(ContainSubstring(s.CleanDoc), ContainSubstring("`title`"))))
			})

			It("notices a covers: token that stops resolving", func() {
				doc := fx.read(s.CoversDoc)
				bogus := s.CoversToken + "-does-not-exist"
				updated := strings.Replace(doc, "\n  - "+s.CoversToken+"\n", "\n  - "+bogus+"\n", 1)
				Expect(updated).NotTo(Equal(doc), "could not find `- %s` in %s", s.CoversToken, s.CoversDoc)
				fx.write(s.CoversDoc, updated)

				res := fx.run("lint")
				Expect(res.Code).To(Equal(1))
				Expect(findingsFor(res.Out, "covers-resolves")).To(ContainElement(ContainSubstring(bogus)))
			})

			// -------------------------------------------------------------------------------
			// Report commands
			// -------------------------------------------------------------------------------

			It("names the migration worklist and nothing else", func() {
				res := fx.run("frontmatter")
				Expect(res.Code).To(Equal(0))

				var listed []string
				for _, line := range strings.Split(res.Out, "\n") {
					if t := strings.TrimSpace(line); strings.HasSuffix(t, ".md") {
						listed = append(listed, t)
					}
				}
				sort.Strings(listed)
				Expect(listed).To(Equal(s.Worklist))
			})

			It("reports a doc as stale only once its subject has actually moved ahead of it, and "+
				"reports dates rather than a day count that would churn daily", func() {
				res := fx.run("stale")
				Expect(res.Code).To(Equal(0))
				for _, doc := range s.StaleDocs {
					Expect(res.Out).To(ContainSubstring(doc))
				}
				Expect(res.Out).To(ContainSubstring(importDate[:10]), "the doc date is missing")
				Expect(res.Out).To(ContainSubstring(bumpDate[:10]), "the subject date is missing")
			})
		})
	}
})

// copyTreeReversed writes the same tree in reverse lexical order, so that a second root is
// genuinely built differently rather than being a byte copy of the first.
func copyTreeReversed(src, dst string) error {
	var files []string
	var dirs []string
	if err := filepath.WalkDir(src, func(p string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(src, p)
		if err != nil {
			return err
		}
		if d.IsDir() {
			dirs = append(dirs, rel)
		} else {
			files = append(files, rel)
		}
		return nil
	}); err != nil {
		return err
	}
	sort.Sort(sort.Reverse(sort.StringSlice(dirs)))
	sort.Sort(sort.Reverse(sort.StringSlice(files)))

	for _, d := range dirs {
		if err := os.MkdirAll(filepath.Join(dst, d), 0o755); err != nil {
			return err
		}
	}
	for _, f := range files {
		b, err := os.ReadFile(filepath.Join(src, f))
		if err != nil {
			return err
		}
		if err := os.WriteFile(filepath.Join(dst, f), b, 0o644); err != nil {
			return err
		}
	}
	return nil
}
