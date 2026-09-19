package integration_test

import (
	"os"
	"regexp"
	"strings"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	"github.com/onsi/gomega/gexec"
)

// Marker-region ownership, driven through the real binary.
//
// Two things are being pinned here, and only one of them is "the table has the right rows".
//
// The other is the SAFETY PROPERTY, and it is the reason this feature is allowed to exist at
// all: docsgen writes into files that carry editorial prose no generator can reproduce. Every
// way the markers can be wrong — absent, unbalanced, nested, inverted, file missing — has to be
// a refusal that names the file. An append, a silent whole-file rewrite, or a "best effort"
// splice is unrecoverable damage discovered weeks later by somebody looking for a paragraph
// that used to be there.
//
// So the negative specs below are the valuable half. A nav that renders beautifully and eats a
// paragraph on a bad marker is strictly worse than no nav at all.

// regionBodyRe captures what a region currently holds, for the specs that need to reason about
// the span rather than the whole file.
func regionBody(content, name string) string {
	re := regexp.MustCompile(`(?s)<!-- docs:gen:` + regexp.QuoteMeta(name) + ` -->(.*?)<!-- /docs:gen:` + regexp.QuoteMeta(name) + ` -->`)
	m := re.FindStringSubmatch(content)
	if m == nil {
		return ""
	}
	return m[1]
}

// outsideRegion returns everything that is NOT inside the named region, which is exactly the
// text a regeneration must never move.
func outsideRegion(content, name string) string {
	open := "<!-- docs:gen:" + name + " -->"
	close := "<!-- /docs:gen:" + name + " -->"
	i := strings.Index(content, open)
	j := strings.Index(content, close)
	if i < 0 || j < 0 {
		return content
	}
	return content[:i+len(open)] + content[j:]
}

var _ = Describe("marker-region navigation tables", Label("integration"), func() {

	DescribeTable("the generated table is derived from the tree",
		func(s *sample) {
			fx := newFixture(s)
			Expect(fx.run("generate").Code).To(Equal(0))
			body := regionBody(fx.read(s.NavRel), s.NavRegion)
			Expect(body).NotTo(BeEmpty(), "the region rendered nothing")

			for _, want := range s.NavRows {
				Expect(body).To(ContainSubstring("("+want+")"),
					"%s is in the tree but produced no row", want)
			}
			for _, unwanted := range s.NavExcludes {
				Expect(body).NotTo(ContainSubstring("("+unwanted+")"),
					"%s must not appear in the nav", unwanted)
			}
		},
		Entry("flux-cluster", fluxCluster),
		Entry("plain-dirs", plainDirs),
	)

	DescribeTable("the description column is the target's own frontmatter key, and falls back "+
		"to its H1 — not silently to nothing",
		func(s *sample) {
			fx := newFixture(s)
			Expect(fx.run("generate").Code).To(Equal(0))
			body := regionBody(fx.read(s.NavRel), s.NavRegion)

			// The curated one-liner survives regeneration. This is the whole reason the column
			// is read from the target rather than generated: without it, regenerating a nav
			// throws away every description anybody ever wrote.
			Expect(rowFor(body, s.NavDescribed)).To(ContainSubstring(s.NavDescribedText),
				"the `%s` key was ignored and the description came from somewhere else",
				s.NavDescKey)

			// And a document with no such key falls back to its H1 rather than to an empty cell.
			Expect(rowFor(body, s.NavFallback)).To(ContainSubstring(s.NavFallbackH1))
		},
		Entry("flux-cluster", fluxCluster),
		Entry("plain-dirs", plainDirs),
	)

	DescribeTable("a row whose target leaves the tree disappears, which is the entire point",
		func(s *sample) {
			fx := newFixture(s)
			Expect(fx.run("generate").Code).To(Equal(0))

			doomed := s.NavRows[0]
			Expect(regionBody(fx.read(s.NavRel), s.NavRegion)).To(ContainSubstring("(" + doomed + ")"))

			// Delete the target the way `docs/_archive/` was deleted: gone, with nothing to
			// repoint at. A hand-written table keeps the row and `broken-links` reports it
			// forever; a derived one simply stops producing it.
			dir := s.NavRel[:strings.LastIndex(s.NavRel, "/")+1]
			Expect(os.Remove(fx.path(dir + doomed))).To(Succeed())
			runGit(fx.Root, nil, "add", "-A")
			runGit(fx.Root, dateEnv(bumpDate), "commit", "-q", "-m", "delete "+doomed)

			Expect(fx.run("generate").Code).To(Equal(0))
			Expect(regionBody(fx.read(s.NavRel), s.NavRegion)).NotTo(ContainSubstring("("+doomed+")"),
				"a dead row survived regeneration — the table is not derived from the tree")
		},
		Entry("flux-cluster", fluxCluster),
		Entry("plain-dirs", plainDirs),
	)

	DescribeTable("prose outside the markers is byte-identical across a regeneration",
		func(s *sample) {
			fx := newFixture(s)
			Expect(fx.run("generate").Code).To(Equal(0))
			before := fx.read(s.NavRel)

			// Destroy the region body and regenerate. Everything outside must come back
			// byte-for-byte, and the garbage inside must be gone.
			fx.write(s.NavRel, strings.Replace(before,
				regionBody(before, s.NavRegion),
				"\n\n| GARBAGE | THIS ROW MUST NOT SURVIVE |\n\n", 1))

			Expect(fx.run("check").Code).To(Equal(1), "a clobbered region must read as drift")
			Expect(fx.run("generate").Code).To(Equal(0))

			after := fx.read(s.NavRel)
			Expect(after).NotTo(ContainSubstring("GARBAGE"))
			Expect(outsideRegion(after, s.NavRegion)).To(Equal(outsideRegion(before, s.NavRegion)),
				"regenerating moved bytes OUTSIDE the markers — marker ownership is broken and "+
					"editorial prose is being rewritten")
			Expect(after).To(Equal(before))
		},
		Entry("flux-cluster", fluxCluster),
		Entry("plain-dirs", plainDirs),
	)

	DescribeTable("regenerating twice is a byte no-op",
		func(s *sample) {
			fx := newFixture(s)
			Expect(fx.run("generate").Code).To(Equal(0))
			first := fx.read(s.NavRel)
			was := fx.backdate(s.NavRel)

			Expect(fx.run("generate").Code).To(Equal(0))
			Expect(fx.read(s.NavRel)).To(Equal(first))
			Expect(fx.modTime(s.NavRel)).To(Equal(was),
				"the second run rewrote an unchanged file; `git status` and every mtime-based "+
					"cache now churn on every run")
			Expect(fx.run("check").Code).To(Equal(0))
			Expect(fx.tempArtifacts()).To(BeEmpty())
		},
		Entry("flux-cluster", fluxCluster),
		Entry("plain-dirs", plainDirs),
	)

	// --- the hard safety rule -------------------------------------------------------------
	//
	// Every entry below is a way the markers can be wrong. Every one of them must be a REFUSAL
	// that names the file, must write nothing at all, and must leave the document exactly as it
	// found it. The `NotTo(ContainSubstring("| Doc |"))` on each is the anti-append assertion:
	// the failure being refused is not "docsgen errored", it is "docsgen helpfully appended the
	// table to the end of somebody's prose".

	DescribeTable("a broken marker state is a hard error naming the file, never an append and "+
		"never a whole-file rewrite",
		func(s *sample, mutate func(before string) string, wantErr string) {
			fx := newFixture(s)
			Expect(fx.run("generate").Code).To(Equal(0), "the fixture must generate cleanly first")

			before := fx.read(s.NavRel)
			fx.write(s.NavRel, mutate(before))
			broken := fx.read(s.NavRel)
			hash := fx.treeHash()

			for _, cmd := range []string{"generate", "check"} {
				res := fx.run(cmd)
				Expect(res.Session).To(gexec.Exit(2),
					"`%s`: a broken marker state is the tool refusing to answer (2), not ordinary "+
						"drift (1) — drift gets regenerated over\nstdout:\n%s\nstderr:\n%s",
					cmd, res.Out, res.Err)
				Expect(res.Err).To(ContainSubstring(s.NavRel),
					"`%s`: the error must name the file whose markers are wrong", cmd)
				Expect(res.Err).To(ContainSubstring(wantErr))
			}

			Expect(fx.read(s.NavRel)).To(Equal(broken),
				"docsgen wrote to a file whose markers it could not trust")
			Expect(fx.read(s.NavRel)).NotTo(ContainSubstring("| Doc | What it covers |"),
				"the table was APPENDED — the one outcome marker ownership exists to make "+
					"impossible, because it duplicates or displaces prose nobody can reconstruct")
			Expect(fx.treeHash()).To(Equal(hash), "a refusing run still changed the tree")
			Expect(fx.tempArtifacts()).To(BeEmpty())
		},

		Entry("both markers missing", fluxCluster,
			func(b string) string { return stripMarkers(b, "nav") },
			"no `nav` region"),
		Entry("both markers missing (plain-dirs)", plainDirs,
			func(b string) string { return stripMarkers(b, "nav") },
			"no `nav` region"),

		Entry("the closing marker is missing", fluxCluster,
			func(b string) string { return strings.Replace(b, "<!-- /docs:gen:nav -->", "", 1) },
			"unbalanced `nav` markers — 1 opening and 0 closing"),
		Entry("the opening marker is missing", fluxCluster,
			func(b string) string { return strings.Replace(b, "<!-- docs:gen:nav -->", "", 1) },
			"unbalanced `nav` markers — 0 opening and 1 closing"),

		Entry("a second pair of markers", fluxCluster,
			func(b string) string {
				return b + "\n<!-- docs:gen:nav -->\n\n<!-- /docs:gen:nav -->\n"
			},
			"unbalanced `nav` markers — 2 opening and 2 closing"),

		Entry("nested markers", fluxCluster,
			func(b string) string {
				return strings.Replace(b, "<!-- docs:gen:nav -->",
					"<!-- docs:gen:nav -->\n<!-- docs:gen:nav -->", 1)
			},
			"nested `nav` regions"),

		Entry("the markers are inverted", fluxCluster,
			func(b string) string {
				b = strings.Replace(b, "<!-- docs:gen:nav -->", "@@OPEN@@", 1)
				b = strings.Replace(b, "<!-- /docs:gen:nav -->", "<!-- docs:gen:nav -->", 1)
				return strings.Replace(b, "@@OPEN@@", "<!-- /docs:gen:nav -->", 1)
			},
			"markers are inverted"),
	)

	It("refuses to CREATE a marker-owned file, because a generated file wearing a hand-written "+
		"document's name has no prose to preserve and never will", func() {
		fx := newFixture(fluxCluster)
		Expect(os.Remove(fx.path(fluxCluster.NavRel))).To(Succeed())

		res := fx.run("generate")
		Expect(res.Session).To(gexec.Exit(2), res.Out)
		Expect(res.Err).To(ContainSubstring(fluxCluster.NavRel))
		Expect(res.Err).To(ContainSubstring("the file does not exist"))
		Expect(fx.exists(fluxCluster.NavRel)).To(BeFalse(),
			"docsgen created the document it said it would not create")
	})

	It("keeps the pre-existing whole-file artifacts byte-identical, so adding region ownership "+
		"did not quietly change the other half of the generator", func() {
		fx := newFixture(fluxCluster)
		Expect(fx.run("generate").Code).To(Equal(0))
		fx.matchGolden("component-inventory.md", fx.read(fx.artifactRel()))
		fx.matchGolden("scoped-inventory.md", fx.read(fluxCluster.ScopeRel))
	})
})

// rowFor returns the table row whose link target is `target`.
func rowFor(body, target string) string {
	for _, line := range strings.Split(body, "\n") {
		if strings.Contains(line, "("+target+")") {
			return line
		}
	}
	return ""
}

// stripMarkers removes both marker lines, leaving the prose around them intact. This is the
// state a careless `prettier`-adjacent tool or a hand edit produces, and it is the one that
// MUST NOT be answered by appending.
func stripMarkers(content, name string) string {
	var out []string
	for _, line := range strings.Split(content, "\n") {
		t := strings.TrimSpace(line)
		if t == "<!-- docs:gen:"+name+" -->" || t == "<!-- /docs:gen:"+name+" -->" {
			continue
		}
		out = append(out, line)
	}
	return strings.Join(out, "\n")
}
