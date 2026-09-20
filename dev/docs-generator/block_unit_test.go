package main

import (
	"strings"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

// Specs for the inline-documentation DSL.
//
// The first two pin a bug the parser shipped: a doc() block swallowed the diagram() header that
// followed it, because a bare `#` is still a comment line and the body kept consuming. That one
// greedy continuation produced two visible defects — a lost diagram AND a doc block rendered
// with its comment indentation intact, since the swallowed header sat at indent 0 and made
// dedent compute a common indent of 0.

var _ = Describe("block parsing", Label("unit"), func() {
	src := strings.Join([]string{
		"# doc() first: The first block",
		"#   section: Overview",
		"#   order: 10",
		"#   Body line one.",
		"#   Body line two.",
		"#",
		"# diagram() second: A picture",
		"#   section: Overview",
		"#   flowchart LR",
		"#     a --> b",
		"key: value",
	}, "\n")

	It("does not let one block swallow the next", func() {
		bs := ParseBlocks("x.yaml", src)
		Expect(bs).To(HaveLen(2), "a following block header must terminate the previous body")
		Expect(bs[0].ID).To(Equal("first"))
		Expect(bs[1].ID).To(Equal("second"))
	})

	It("keeps the body free of the following block's header", func() {
		bs := ParseBlocks("x.yaml", src)
		Expect(strings.Join(bs[0].Body, "\n")).NotTo(ContainSubstring("diagram()"))
	})

	It("dedents the body, which the swallowed header silently prevented", func() {
		bs := ParseBlocks("x.yaml", src)
		Expect(bs[0].Body[0]).To(Equal("Body line one."),
			"a leading indent here becomes a markdown code block")
	})

	It("preserves RELATIVE indentation inside a diagram", func() {
		// mermaid uses indentation for nesting, so dedent must remove the common prefix only.
		bs := ParseBlocks("x.yaml", src)
		Expect(bs[1].Body).To(Equal([]string{"flowchart LR", "  a --> b"}))
	})

	It("stops at a non-comment line", func() {
		bs := ParseBlocks("x.yaml", src)
		Expect(strings.Join(bs[1].Body, "\n")).NotTo(ContainSubstring("key: value"))
	})

	It("ignores a block inside a backtick span", func() {
		Expect(ParseBlocks("x.go", "// write `# doc() demo: like this` to document a value\n")).To(BeEmpty())
	})
})

var _ = Describe("DSL-controlled structure", Label("unit"), func() {
	It("nests headings from the declared section path", func() {
		blocks := []Block{
			{Kind: KindDoc, ID: "a", Title: "A", Section: "Architecture/Ingress", File: "f.yaml", Line: 1},
			{Kind: KindDoc, ID: "b", Title: "B", Section: "Architecture", File: "f.yaml", Line: 9},
		}
		var sb strings.Builder
		buildSections(blocks).render(3, "", &sb)
		out := sb.String()
		Expect(out).To(ContainSubstring("### Architecture"))
		Expect(out).To(ContainSubstring("#### Ingress"))
	})

	It("falls back to one heading per FILE when no section is declared", func() {
		// The default the whole feature rests on: a folder with zero structural annotation
		// still produces a readable document.
		var sb strings.Builder
		buildSections([]Block{{Kind: KindDoc, ID: "a", Title: "A", File: "dir/bouncer.py", Line: 3}}).render(3, "", &sb)
		Expect(sb.String()).To(ContainSubstring("### bouncer.py"))
	})

	It("orders by explicit `order` before falling back to file and line", func() {
		blocks := []Block{
			{ID: "late", Title: "Late", Section: "S", Order: 20, File: "a.yaml", Line: 1},
			{ID: "early", Title: "Early", Section: "S", Order: 10, File: "z.yaml", Line: 99},
		}
		var sb strings.Builder
		buildSections(blocks).render(3, "", &sb)
		Expect(strings.Index(sb.String(), "Early")).To(BeNumerically("<", strings.Index(sb.String(), "Late")))
	})

	It("sorts unordered blocks AFTER ordered ones rather than interleaving", func() {
		// Adding an `order:` to one block must not silently reshuffle its unannotated
		// neighbours into the middle of the sequence.
		blocks := []Block{
			{ID: "none", Title: "Unordered", Section: "S", File: "a.yaml", Line: 1},
			{ID: "ten", Title: "Ordered", Section: "S", Order: 10, File: "z.yaml", Line: 9},
		}
		var sb strings.Builder
		buildSections(blocks).render(3, "", &sb)
		Expect(strings.Index(sb.String(), "Ordered")).To(BeNumerically("<", strings.Index(sb.String(), "Unordered")))
	})

	It("makes the source link relative to the host document, not repo-relative", func() {
		// Every source link 404'd on the first generate: a repo-relative path is resolved
		// against the README's own folder. docsgen's own broken-links rule caught it, which is
		// the closest thing to a self-test this tool has.
		out := Block{Kind: KindDoc, ID: "x", Title: "T", File: "a/b/c.py", Line: 3}.Render(4, "a/b")
		Expect(out).To(ContainSubstring("](c.py)"))
		Expect(out).NotTo(ContainSubstring("](a/b/c.py)"))
	})

	It("walks up when the source is outside the document's folder", func() {
		out := Block{Kind: KindDoc, ID: "x", Title: "T", File: "other/z.py", Line: 1}.Render(4, "a/b")
		Expect(out).To(ContainSubstring("](../../other/z.py)"))
	})

	It("emits a stable anchor so links survive a retitle", func() {
		out := Block{Kind: KindDoc, ID: "bouncer-role", Title: "What this does", File: "f.py", Line: 3}.Render(4, "")
		Expect(out).To(ContainSubstring(`<a id="bouncer-role"></a>`))
	})

	It("fences a diagram as mermaid", func() {
		out := Block{Kind: KindDiagram, ID: "d", Title: "D", Body: []string{"flowchart LR"}, File: "f.py", Line: 1}.Render(4, "")
		Expect(out).To(ContainSubstring("```mermaid\nflowchart LR\n```"))
	})
})
