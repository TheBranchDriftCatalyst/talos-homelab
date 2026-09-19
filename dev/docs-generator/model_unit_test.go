package main

// Unit specs for model.go — the markdown parsing primitives every rule reads through.
//
// These are pure functions over strings, so nothing here touches the filesystem or the repo.

import (
	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

var _ = Describe("SplitFrontMatter", Label("unit"), func() {
	It("treats a document with no frontmatter as valid and returns the text unchanged as the body, because most of the repo predates the taxonomy and absent frontmatter is the migration worklist rather than an error", func() {
		front, order, ferr, body := SplitFrontMatter("# Title\n\nprose\n")

		Expect(ferr).To(BeEmpty())
		Expect(front).To(BeNil())
		Expect(order).To(BeNil())
		Expect(body).To(Equal("# Title\n\nprose\n"))
	})

	It("only recognises a block that starts at byte zero, so a stray --- further down the file is never mistaken for frontmatter", func() {
		text := "\n---\ntype: reference\n---\n# Title\n"

		front, _, ferr, body := SplitFrontMatter(text)

		Expect(ferr).To(BeEmpty())
		Expect(front).To(BeNil())
		Expect(body).To(Equal(text))
	})

	It("parses a well-formed block and strips it from the body, leaving the H1 as the first token so markdownlint MD041 stays satisfied", func() {
		front, _, ferr, body := SplitFrontMatter("---\ntype: reference\nstatus: current\n---\n\n# Title\n")

		Expect(ferr).To(BeEmpty())
		Expect(front).To(HaveKeyWithValue("type", "reference"))
		Expect(front).To(HaveKeyWithValue("status", "current"))
		Expect(body).To(Equal("# Title\n"))
	})

	It("captures the source order of top-level keys, which is the only reason key-order can be checked at all — the parsed map is unordered by construction", func() {
		_, order, ferr, _ := SplitFrontMatter("---\nstatus: current\ntype: reference\ncovers:\n  - alpha\n  - beta\ntickets: []\n---\nbody\n")

		Expect(ferr).To(BeEmpty())
		Expect(order).To(Equal([]string{"status", "type", "covers", "tickets"}))
	})

	It("records only unindented keys in the order list, so nested mapping keys and list items never masquerade as top-level keys", func() {
		_, order, ferr, _ := SplitFrontMatter("---\ncomponents:\n  nested: true\nowners:\n  - name: platform\nstatus: current\n---\nbody\n")

		Expect(ferr).To(BeEmpty())
		Expect(order).To(Equal([]string{"components", "owners", "status"}))
	})

	It("reports an unterminated block and hands back the whole text as the body, so a truncated file is flagged rather than silently swallowing the document", func() {
		text := "---\ntype: reference\nstatus: current\n"

		front, order, ferr, body := SplitFrontMatter(text)

		Expect(ferr).To(Equal("unterminated frontmatter block"))
		Expect(front).To(BeNil())
		Expect(order).To(BeNil())
		Expect(body).To(Equal(text))
	})

	It("reports invalid YAML as a one-line message and still returns the body, so one broken file cannot abort the scan of the tree around it", func() {
		front, order, ferr, body := SplitFrontMatter("---\ncovers: [unclosed\n---\n# Title\n")

		Expect(ferr).To(HavePrefix("invalid YAML in frontmatter: "))
		Expect(front).To(BeNil())
		Expect(order).To(BeNil())
		Expect(body).To(Equal("# Title\n"))
	})

	// The one-line claim above could never fire: a scanner error like `[unclosed` is already a
	// single line, so deleting oneLine entirely left it green. gopkg.in/yaml.v3 emits a
	// genuinely MULTI-line error the moment the YAML parses but does not fit the target type —
	// a header line plus one indented line per problem — and that is the shape that has to be
	// flattened, because a rule message is printed one finding per line and an embedded newline
	// splits one finding into two that the report cannot attribute.
	It("flattens a multi-line YAML error into one line, which is the only shape that survives the one-finding-per-line report", func() {
		// A sequence where a mapping is required: valid YAML, wrong type, multi-line error.
		const text = "---\n- type: reference\n- status: current\n---\n# Title\n"

		_, _, ferr, body := SplitFrontMatter(text)

		Expect(ferr).To(HavePrefix("invalid YAML in frontmatter: "))
		Expect(ferr).NotTo(ContainSubstring("\n"),
			"an embedded newline splits one finding into two unattributed report lines")
		Expect(ferr).To(ContainSubstring("yaml: unmarshal errors:"),
			"the multi-line header must survive flattening, not be truncated away")
		Expect(ferr).To(ContainSubstring("cannot unmarshal"),
			"and so must the detail line that follows it")
		Expect(body).To(Equal("# Title\n"))
	})

	// Guards the flattening itself rather than one caller of it: runs of whitespace collapse to
	// a single space, so the indented continuation lines do not arrive as a ragged run-on.
	It("collapses every run of whitespace, so a flattened error reads as one sentence rather than a column of indentation", func() {
		Expect(oneLine("a\n  b\tc\n\n   d")).To(Equal("a b c d"))
		Expect(oneLine("already one line")).To(Equal("already one line"))
		Expect(oneLine("")).To(BeEmpty())
	})

	It("returns an empty body when the document is nothing but frontmatter, rather than leaking the delimiter line into the body", func() {
		_, _, ferr, body := SplitFrontMatter("---\ntype: reference\n---\n")

		Expect(ferr).To(BeEmpty())
		Expect(body).To(BeEmpty())
	})

	It("returns a non-nil empty map for an empty frontmatter block, because Front==nil is the sentinel for 'no frontmatter at all' and an empty block is a different thing", func() {
		front, _, ferr, _ := SplitFrontMatter("---\n\n---\nbody\n")

		Expect(ferr).To(BeEmpty())
		Expect(front).NotTo(BeNil())
		Expect(front).To(BeEmpty())
	})
})

var _ = Describe("StripCode", Label("unit"), func() {
	DescribeTable("removes code so examples are never linted as if they were prose",
		func(in, want string) {
			Expect(StripCode(in)).To(Equal(want))
		},
		Entry("a backtick fence disappears whole, including its delimiters",
			"before\n```\n[link](./nope.md)\n```\nafter", "before\n\nafter"),
		Entry("a tilde fence disappears whole, because markdown allows either delimiter",
			"before\n~~~\n[link](./nope.md)\n~~~\nafter", "before\n\nafter"),
		Entry("an inline span disappears, so `kubectl -n foo` never reads as a link target",
			"run `kubectl get pods` now", "run  now"),
		Entry("an inline span is removed only within one line, so a lone backtick cannot swallow the rest of the file",
			"a ` b\nc ` d", "a ` b\nc ` d"),
		Entry("prose with no code is returned untouched", "just prose", "just prose"),
		Entry("a language-tagged fence is removed along with its info string",
			"x\n```yaml\nkey: value\n```\ny", "x\n\ny"),
	)

	It("strips fences before inline spans, so the backticks that delimit a fence are never re-interpreted as an inline span boundary", func() {
		in := "```\nfirst\n```\ntext `inline` text\n```\nsecond\n```"

		Expect(StripCode(in)).To(Equal("\ntext  text\n"))
	})
})

var _ = Describe("ExtractLinks", Label("unit"), func() {
	DescribeTable("collects only the links that can actually be checked against the filesystem",
		func(body string, want []string) {
			got := ExtractLinks(body)
			if len(want) == 0 {
				Expect(got).To(BeEmpty())
				return
			}
			Expect(got).To(Equal(want))
		},
		Entry("a relative link is kept, because that is the only kind this tool can verify",
			"see [docs](./quickstart.md)", []string{"./quickstart.md"}),
		Entry("a parent-relative link keeps its anchor for reporting; the rule trims it when stat-ing",
			"see [up](../02-architecture/traefik.md#tls)", []string{"../02-architecture/traefik.md#tls"}),
		Entry("an https link is skipped, because network reachability is not this tool's job",
			"see [site](https://example.com/x)", nil),
		Entry("an http link is skipped for the same reason",
			"see [site](http://grafana.talos00)", nil),
		Entry("a mailto link is skipped", "mail [me](mailto:a@b.test)", nil),
		Entry("a pure anchor is skipped, because the target is this same document",
			"jump [down](#related-issues)", nil),
		Entry("an angle-bracketed target is skipped rather than stat-ed as a path beginning with '<'",
			"see [x](<./has space.md>)", nil),
		Entry("several links on one line are all collected in source order",
			"[a](./a.md) and [b](./b.md)", []string{"./a.md", "./b.md"}),
		Entry("an image reference is collected too, since a missing image is just as dead as a missing doc",
			"![diagram](./img/arch.png)", []string{"./img/arch.png"}),
		Entry("a title after the target is not swallowed into the path",
			`[a](./a.md "Title")`, []string{"./a.md"}),
		Entry("a link inside a fenced example is not collected, because examples deliberately name paths that do not exist",
			"```\n[x](./made-up.md)\n```", nil),
		Entry("a link inside an inline span is not collected either",
			"run `[x](./made-up.md)` here", nil),
		Entry("an empty link text still yields its target", "[](./a.md)", []string{"./a.md"}),
	)
})

var _ = Describe("FirstH1", Label("unit"), func() {
	DescribeTable("finds the document title the same way markdownlint does",
		func(body, want string) {
			Expect(FirstH1(body)).To(Equal(want))
		},
		Entry("returns the first H1 and trims it", "# Traefik  \n\nprose", "Traefik"),
		Entry("returns the FIRST of several, because MD025 makes any later one a duplicate anyway",
			"# One\n\n# Two\n", "One"),
		Entry("ignores an H2", "## Section\n\nprose", ""),
		Entry("ignores a hash with no following space, which is not a heading in CommonMark",
			"#NotAHeading\n", ""),
		Entry("returns empty when there is no heading at all, which the taxonomy rule reports",
			"just prose\n", ""),
		Entry("finds an H1 that is not the first line", "intro\n\n# Title\n", "Title"),
	)
})

var _ = Describe("MakeDoc", Label("unit"), func() {
	It("assembles every derived field from one pass over the text, so rules never re-parse and never disagree with each other about what a doc says", func() {
		text := "---\ntype: reference\nstatus: current\n---\n\n# Inventory\n\nSee [config](./config.yaml) and [web](https://example.test).\n"

		d := MakeDoc("docs/07-reference/inventory.md", text)

		Expect(d.Path).To(Equal("docs/07-reference/inventory.md"))
		Expect(d.Text).To(Equal(text), "Text must stay the raw bytes: the tickets rule scans it")
		Expect(d.Body).To(HavePrefix("# Inventory"))
		Expect(d.FrontError).To(BeEmpty())
		Expect(d.Front).To(HaveKeyWithValue("type", "reference"))
		Expect(d.FrontKeys).To(Equal([]string{"type", "status"}))
		Expect(d.H1).To(Equal("Inventory"))
		Expect(d.Links).To(Equal([]string{"./config.yaml"}))
	})

	It("carries the frontmatter error through instead of panicking, so a malformed doc becomes one finding rather than a crashed run", func() {
		d := MakeDoc("docs/bad.md", "---\ncovers: [unclosed\n---\n# Bad\n")

		Expect(d.FrontError).NotTo(BeEmpty())
		Expect(d.Front).To(BeNil())
		Expect(d.H1).To(Equal("Bad"), "the body is still usable even when the frontmatter is not")
	})
})

var _ = Describe("StringSlice", Label("unit"), func() {
	It("reports a missing value as clean, because an absent optional key is not a schema violation", func() {
		got, clean := StringSlice(nil)

		Expect(got).To(BeNil())
		Expect(clean).To(BeTrue())
	})

	It("coerces a bare scalar to a one-element slice but reports it as UNCLEAN, because prettier rewrites flow/scalar forms and the frontmatter must already be a block sequence", func() {
		got, clean := StringSlice("cilium")

		Expect(got).To(Equal([]string{"cilium"}))
		Expect(clean).To(BeFalse(), "a scalar covers value must surface as a schema finding, not pass silently")
	})

	It("accepts a list of strings as clean", func() {
		got, clean := StringSlice([]any{"cilium", "traefik"})

		Expect(got).To(Equal([]string{"cilium", "traefik"}))
		Expect(clean).To(BeTrue())
	})

	It("reports a list containing a non-string as unclean and stops at the offender, so `covers: [- 1]` cannot be read as a component handle", func() {
		got, clean := StringSlice([]any{"cilium", 7})

		Expect(clean).To(BeFalse())
		Expect(got).To(Equal([]string{"cilium"}))
	})

	It("treats an empty list as clean, since an explicitly empty sequence is well-formed", func() {
		got, clean := StringSlice([]any{})

		Expect(got).To(BeEmpty())
		Expect(clean).To(BeTrue())
	})

	DescribeTable("reports any other YAML shape as unclean rather than silently ignoring it",
		func(v any) {
			got, clean := StringSlice(v)

			Expect(got).To(BeNil())
			Expect(clean).To(BeFalse())
		},
		Entry("an integer", 7),
		Entry("a boolean", true),
		Entry("a mapping", map[string]any{"name": "cilium"}),
	)
})
