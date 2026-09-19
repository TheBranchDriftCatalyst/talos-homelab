package main

// Unit specs for marker-region ownership.
//
// findRegion is the whole safety story of this feature in one function, so it is specified
// error-shape by error-shape rather than through the generator. Each of these states is a real
// thing that happens to a marker-owned file — somebody deletes a line, a merge duplicates a
// block, a copy-paste nests one region in another — and the only acceptable answer to every one
// of them is a refusal that names the file.
//
// The assertion that matters most in this file is the NEGATIVE one on spliceRegion: bytes
// outside the markers must come back identical, including the ones the normaliser would
// otherwise "fix". Trailing whitespace, a tab-indented paragraph and a badly padded table are
// all present in the fixtures below on purpose — they are the shapes a well-meaning normaliser
// rewrites, and rewriting them here would mean docsgen silently reformatting prose it does not
// own.

import (
	"strings"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

const markedDoc = "# Title\n" +
	"\n" +
	"Prose above the region.   \n" + // trailing spaces: the normaliser would strip them
	"\n" +
	"\t- a tab-indented line the normaliser has opinions about\n" +
	"\n" +
	"| badly | padded |\n" +
	"| --- | --- |\n" +
	"| hand | written |\n" +
	"\n" +
	"<!-- docs:gen:nav -->\n" +
	"\n" +
	"| Doc | What it covers |\n" +
	"| --- | --- |\n" +
	"| [old.md](old.md) | stale row |\n" +
	"\n" +
	"<!-- /docs:gen:nav -->\n" +
	"\n" +
	"Prose below the region.\n"

var _ = Describe("regionMarkers", Label("unit"), func() {
	It("has ONE definition of each marker, because two spellings of the closing one means the "+
		"reader never finds it and treats the rest of the document as generated content", func() {
		open, close := regionMarkers("nav")
		Expect(open).To(Equal("<!-- docs:gen:nav -->"))
		Expect(close).To(Equal("<!-- /docs:gen:nav -->"))
	})
})

var _ = Describe("findRegion", Label("unit"), func() {
	It("locates the one region", func() {
		at, err := findRegion("docs/README.md", markedDoc, "nav")
		Expect(err).NotTo(HaveOccurred())
		lines := strings.Split(markedDoc, "\n")
		Expect(lines[at.openLine]).To(Equal("<!-- docs:gen:nav -->"))
		Expect(lines[at.closeLine]).To(Equal("<!-- /docs:gen:nav -->"))
	})

	It("tolerates indented markers, because prettier and every list-aware editor may indent an "+
		"HTML comment and a failure there would be a refusal nobody caused", func() {
		doc := strings.Replace(markedDoc, "<!-- docs:gen:nav -->", "  <!-- docs:gen:nav -->", 1)
		_, err := findRegion("docs/README.md", doc, "nav")
		Expect(err).NotTo(HaveOccurred())
	})

	DescribeTable("every broken marker state is an error NAMING THE FILE",
		func(mutate func(string) string, wantSubstrings ...string) {
			_, err := findRegion("docs/02-architecture/README.md", mutate(markedDoc), "nav")
			Expect(err).To(HaveOccurred())
			Expect(err.Error()).To(ContainSubstring("docs/02-architecture/README.md"),
				"the only actionable form of `the markers are wrong` is the path of the file "+
					"whose markers they are")
			for _, want := range wantSubstrings {
				Expect(err.Error()).To(ContainSubstring(want))
			}
		},

		Entry("no markers at all",
			func(s string) string {
				s = strings.Replace(s, "<!-- docs:gen:nav -->\n", "", 1)
				return strings.Replace(s, "<!-- /docs:gen:nav -->\n", "", 1)
			},
			"no `nav` region", "will not append"),

		Entry("closing marker deleted",
			func(s string) string { return strings.Replace(s, "<!-- /docs:gen:nav -->\n", "", 1) },
			"unbalanced", "1 opening and 0 closing"),

		Entry("opening marker deleted",
			func(s string) string { return strings.Replace(s, "<!-- docs:gen:nav -->\n", "", 1) },
			"unbalanced", "0 opening and 1 closing"),

		Entry("a duplicated region",
			func(s string) string { return s + "\n<!-- docs:gen:nav -->\n\n<!-- /docs:gen:nav -->\n" },
			"unbalanced", "2 opening and 2 closing"),

		Entry("a nested region reports NESTING, because deleting the inner pair is not the same "+
			"fix as adding a missing closer",
			func(s string) string {
				return strings.Replace(s, "<!-- docs:gen:nav -->",
					"<!-- docs:gen:nav -->\n<!-- docs:gen:nav -->", 1)
			},
			"nested `nav` regions"),

		Entry("inverted markers",
			func(s string) string {
				s = strings.Replace(s, "<!-- docs:gen:nav -->", "@@O@@", 1)
				s = strings.Replace(s, "<!-- /docs:gen:nav -->", "<!-- docs:gen:nav -->", 1)
				return strings.Replace(s, "@@O@@", "<!-- /docs:gen:nav -->", 1)
			},
			"inverted"),

		Entry("a region that belongs to a DIFFERENT name is not this one's",
			func(s string) string { return strings.ReplaceAll(s, "docs:gen:nav", "docs:gen:other") },
			"no `nav` region"),
	)
})

var _ = Describe("spliceRegion", Label("unit"), func() {
	const fresh = "| Doc | What it covers |\n| --- | --- |\n| [new.md](new.md) | a live row |\n"

	It("replaces the region body and NOTHING else — every byte outside the markers survives, "+
		"including the ones a normaliser would happily 'fix'", func() {
		out, err := spliceRegion("docs/README.md", markedDoc, "nav", fresh)
		Expect(err).NotTo(HaveOccurred())

		Expect(out).To(ContainSubstring("[new.md](new.md)"))
		Expect(out).NotTo(ContainSubstring("[old.md](old.md)"))

		// The prose, byte for byte. These three are the shapes that prove the normaliser did
		// not run over the whole document: trailing whitespace, a tab indent, and a table that
		// is not a prettier fixed point.
		Expect(out).To(ContainSubstring("Prose above the region.   \n"))
		Expect(out).To(ContainSubstring("\t- a tab-indented line"))
		Expect(out).To(ContainSubstring("| badly | padded |\n| --- | --- |\n| hand | written |"))
		Expect(out).To(HaveSuffix("Prose below the region.\n"))
	})

	It("frames the body with blank lines, which is not taste: prettier inserts them around a "+
		"table butted against an HTML comment, so the unframed form is not a fixed point", func() {
		out, err := spliceRegion("docs/README.md", markedDoc, "nav", fresh)
		Expect(err).NotTo(HaveOccurred())
		Expect(out).To(ContainSubstring("<!-- docs:gen:nav -->\n\n| Doc |"))
		Expect(out).To(ContainSubstring("| a live row |\n\n<!-- /docs:gen:nav -->"))
	})

	It("is idempotent: splicing the same body twice produces identical bytes, so a second "+
		"`generate` cannot drift the framing", func() {
		once, err := spliceRegion("docs/README.md", markedDoc, "nav", fresh)
		Expect(err).NotTo(HaveOccurred())
		twice, err := spliceRegion("docs/README.md", once, "nav", fresh)
		Expect(err).NotTo(HaveOccurred())
		Expect(twice).To(Equal(once))
	})

	It("returns EMPTY output alongside an error, so a caller that ignored the error would write "+
		"nothing rather than half a document", func() {
		out, err := spliceRegion("docs/README.md", "# No markers here\n", "nav", fresh)
		Expect(err).To(HaveOccurred())
		Expect(out).To(BeEmpty())
	})

	It("does not append when the markers are absent — the failure this whole file exists to "+
		"make impossible", func() {
		prose := "# Hand-written\n\nA paragraph nobody can reconstruct.\n"
		out, err := spliceRegion("docs/INDEX.md", prose, "nav", fresh)
		Expect(err).To(HaveOccurred())
		Expect(out).NotTo(ContainSubstring("Doc"))
		Expect(out).NotTo(ContainSubstring("A paragraph nobody can reconstruct"))
	})
})
