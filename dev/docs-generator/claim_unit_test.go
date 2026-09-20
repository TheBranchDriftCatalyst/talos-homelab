package main

import (
	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	"strings"
)

// Specs for the claim engine.
//
// Two of these exist because the engine shipped the bug it was written to catch. The parser
// broke on a wrapped line, dropped every field after it, and then printed "no claim findings" --
// healthy output produced by silently discarding input. Both wrap cases are pinned below, and
// the field-wrap one asserts on SCOPE specifically, because scope is what drives decay and its
// loss is what made the failure invisible rather than noisy.

var _ = Describe("claim parsing", Label("unit"), func() {
	It("parses the one-line comment form", func() {
		cs := ParseClaims("a.yaml", "# claim(verified@2026-09-20) x1: the row has last_pull NULL\n#   j: cscli bouncers list\n#   f: last_pull becomes non-NULL\n", "hash")
		Expect(cs).To(HaveLen(1))
		Expect(cs[0].ID).To(Equal("x1"))
		Expect(cs[0].Mode).To(Equal(Verified))
		Expect(cs[0].At).To(Equal("2026-09-20"))
		Expect(cs[0].J).To(Equal("cscli bouncers list"))
		Expect(cs[0].F).To(Equal("last_pull becomes non-NULL"))
	})

	It("folds a wrapped `says` across comment lines", func() {
		// First bug: the parser stopped at the wrap, so a claim with a perfectly good j: and
		// f: below was reported as having neither -- accusing the author of exactly the
		// sloppiness they had avoided.
		cs := ParseClaims("a.yaml", "# claim(asserted) x2: the first half of the sentence\n# and the second half\n#   f: n/a\n", "hash")
		Expect(cs).To(HaveLen(1))
		Expect(cs[0].Says).To(Equal("the first half of the sentence and the second half"))
	})

	It("keeps reading fields after a WRAPPED field value", func() {
		// Second bug, and the worse one: a wrapped `f:` ended the claim, so `scope:` below it
		// was lost. Decay silently became impossible and the engine reported itself clean.
		cs := ParseClaims("a.yaml", ""+
			"# claim(verified@2026-09-20) x3: a claim\n"+
			"#   j: some command\n"+
			"#   f: a long falsifier that runs on\n"+
			"#      to a second line\n"+
			"#   scope: path:infrastructure/foo\n", "hash")
		Expect(cs).To(HaveLen(1))
		Expect(cs[0].F).To(Equal("a long falsifier that runs on to a second line"))
		Expect(cs[0].Scope).To(Equal([]string{"path:infrastructure/foo"}),
			"scope must survive a wrapped field above it — losing it is what made decay silently inert")
	})

	It("stops at a non-comment line so a claim cannot swallow code", func() {
		cs := ParseClaims("a.yaml", "# claim(asserted) x4: something\nkey: value\n#   f: not mine\n", "hash")
		Expect(cs).To(HaveLen(1))
		Expect(cs[0].F).To(BeEmpty())
	})

	It("reads the structured frontmatter form", func() {
		d := MakeDoc("d.md", "---\ntype: reference\nstatus: current\ncovers:\n  - repo\nclaims:\n  - id: f1\n    says: a structured claim\n    mode: enforced\n    j: TestSomething\n    f: the gate is deleted\n    scope:\n      - path:infrastructure/foo\n---\n\n# H\n")
		cs := ClaimsFromFrontmatter(d)
		Expect(cs).To(HaveLen(1))
		Expect(cs[0].ID).To(Equal("f1"))
		Expect(cs[0].Mode).To(Equal(Enforced))
		Expect(cs[0].Scope).To(Equal([]string{"path:infrastructure/foo"}))
	})
})

var _ = Describe("claim rules", Label("unit"), func() {
	ctx := &Ctx{Cfg: &Config{}}

	It("requires a falsifier above asserted — the anti-vacuity gate", func() {
		f := ruleClaimFalsifier(ctx, []Claim{{ID: "a", Mode: Verified, J: "cmd"}})
		Expect(f).To(HaveLen(1))
		Expect(f[0].Rule).To(Equal("claim-falsifier"))
	})

	It("exempts asserted, because design rationale has no falsifier and needs none", func() {
		// The failure mode is never an unverified claim. It is an unverified claim PRESENTED
		// as verified, so `asserted` must stay a comfortable resting state or authors will
		// mislabel to silence the linter.
		Expect(ruleClaimFalsifier(ctx, []Claim{{ID: "a", Mode: Asserted}})).To(BeEmpty())
	})

	It("requires a justification for enforced and verified", func() {
		Expect(ruleClaimJustification(ctx, []Claim{{ID: "a", Mode: Enforced, F: "x"}})).To(HaveLen(1))
		Expect(ruleClaimJustification(ctx, []Claim{{ID: "a", Mode: Asserted}})).To(BeEmpty())
	})

	It("flags a superseded claim with no successor", func() {
		Expect(ruleClaimSuperseded(ctx, []Claim{{ID: "a", Mode: Superseded}})).To(HaveLen(1))
		Expect(ruleClaimSuperseded(ctx, []Claim{{ID: "a", Mode: Superseded, Successor: "b"}})).To(BeEmpty())
	})

	It("flags two claims sharing an id but saying different things", func() {
		f := ruleClaimContradiction(ctx, []Claim{
			{ID: "dup", Says: "the key is api_key", File: "a.yaml", Line: 1},
			{ID: "dup", Says: "the key is login_password", File: "b.yaml", Line: 2},
		})
		Expect(f).To(HaveLen(1))
		Expect(f[0].Rule).To(Equal("claim-contradiction"))
	})

	It("does not flag the same claim restated identically in two places", func() {
		// Restating one claim near each affected file is good practice, not a contradiction.
		// Only a DIFFERENCE under a shared id is a finding.
		Expect(ruleClaimContradiction(ctx, []Claim{
			{ID: "dup", Says: "the key is api_key", File: "a.yaml", Line: 1},
			{ID: "dup", Says: "The  key is   api_key", File: "b.yaml", Line: 2},
		})).To(BeEmpty())
	})
})

var _ = Describe("claim decay", Label("unit"), func() {
	newCtx := func(date string) *Ctx {
		return &Ctx{
			Cfg:    &Config{},
			Dates:  map[string]string{"infrastructure/foo/x.yaml": date},
			BySlug: map[string]Component{},
		}
	}

	It("decays a verified claim when its scope changed after the stamp", func() {
		c := Claim{Mode: Verified, At: "2026-01-01", Scope: []string{"path:infrastructure/foo/x.yaml"}}
		dec, why := c.Decayed(newCtx("2026-09-19T23:21:50Z"))
		Expect(dec).To(BeTrue())
		Expect(why).To(ContainSubstring("2026-09-19"))
	})

	It("does NOT decay on the same day it was verified", func() {
		// Verifying on the day the code changed is the normal case. Treating it as stale would
		// make every fresh claim decay the moment it was written, which trains people to ignore
		// the rule entirely.
		c := Claim{Mode: Verified, At: "2026-09-19", Scope: []string{"path:infrastructure/foo/x.yaml"}}
		dec, _ := c.Decayed(newCtx("2026-09-19T23:21:50Z"))
		Expect(dec).To(BeFalse())
	})

	It("never decays an enforced claim, which is continuous rather than point-in-time", func() {
		c := Claim{Mode: Enforced, At: "2026-01-01", Scope: []string{"path:infrastructure/foo/x.yaml"}}
		dec, _ := c.Decayed(newCtx("2026-09-19T23:21:50Z"))
		Expect(dec).To(BeFalse())
	})

	It("cannot decay a claim with no scope — and that is why scope loss was invisible", func() {
		// Pinning the actual failure: a scopeless claim is permanently 'fresh'. The parser bug
		// silently produced exactly this state, so the engine could never report decay.
		c := Claim{Mode: Verified, At: "2026-01-01"}
		dec, _ := c.Decayed(newCtx("2026-09-19T23:21:50Z"))
		Expect(dec).To(BeFalse())
	})
})

var _ = Describe("claim examples vs claims", Label("unit"), func() {
	It("ignores a claim inside a backtick span, because that is a demonstration", func() {
		// This file's own doc comment demonstrates the grammar. Without the guard the parser
		// registered the DEMONSTRATION as a live claim: the documentation of the format,
		// parsed by the format. Test fixtures did the same from _test.go.
		cs := ParseClaims("doc.go", "// see `# claim(verified@2026-01-01) demo: a shown example` for the shape\n", "slash")
		Expect(cs).To(BeEmpty())
	})

	It("still parses a real claim on a line that also contains backticks elsewhere", func() {
		// The guard must key on whether the CLAIM is inside a span, not on the line having
		// backticks at all — otherwise any claim quoting a command would vanish.
		cs := ParseClaims("a.yaml", "# claim(asserted) real: the value is set in `helmrelease.yaml`\n", "hash")
		Expect(cs).To(HaveLen(1))
		Expect(cs[0].ID).To(Equal("real"))
	})
})

var _ = Describe("claim scope rule", Label("unit"), func() {
	ctx := &Ctx{Cfg: &Config{}}

	It("flags a verified claim with no scope — it can neither decay nor project", func() {
		f := ruleClaimScope(ctx, []Claim{{ID: "a", Mode: Verified, J: "x", F: "y"}})
		Expect(f).To(HaveLen(1))
		Expect(f[0].Rule).To(Equal("claim-scope"))
	})

	It("exempts asserted, which legitimately concerns no particular file", func() {
		Expect(ruleClaimScope(ctx, []Claim{{ID: "a", Mode: Asserted}})).To(BeEmpty())
	})
})

var _ = Describe("knowledge projection", Label("unit"), func() {
	claims := []Claim{
		{ID: "in", Says: "inside", Mode: Verified, At: "2026-09-20", F: "x",
			Scope: []string{"path:infrastructure/base/security/crowdsec/helmrelease.yaml"}},
		{ID: "out", Says: "elsewhere", Mode: Verified, F: "x",
			Scope: []string{"path:infrastructure/base/traefik"}},
		{ID: "none", Says: "unscoped", Mode: Verified, F: "x"},
	}

	It("selects only claims whose scope is under the artifact root", func() {
		got := claimsUnder(claims, "infrastructure/base/security/crowdsec", nil)
		Expect(got).To(HaveLen(1))
		Expect(got[0].ID).To(Equal("in"))
	})

	It("excludes unscoped claims rather than showing them everywhere", func() {
		// A scopeless claim can never decay. Projecting it into every document would spread a
		// permanently fresh-looking assertion across the tree, which is the opposite of what
		// the modality system is for.
		got := claimsUnder(claims, "", nil)
		for _, c := range got {
			Expect(c.ID).NotTo(Equal("none"))
		}
	})

	It("does not treat a sibling directory with a shared prefix as inside", func() {
		// `crowdsec-extra` must not match root `crowdsec`; prefix matching has to be
		// path-segment aware or scoping silently over-selects.
		got := claimsUnder([]Claim{{ID: "sib", Mode: Verified, F: "x",
			Scope: []string{"path:infrastructure/base/security/crowdsec-extra/x.yaml"}}},
			"infrastructure/base/security/crowdsec", nil)
		Expect(got).To(BeEmpty())
	})

	It("says so when a region has no claims instead of rendering an empty table", func() {
		out := renderKnowledge(&Ctx{Cfg: &Config{}}, ArtifactSpec{Root: "nowhere"})
		Expect(out).To(ContainSubstring("No claims are recorded"))
		Expect(out).NotTo(ContainSubstring("| --- |"),
			"an empty table reads as 'nothing is known', which is indistinguishable from a broken scope filter")
	})
})

var _ = Describe("claim extraction from prose", Label("unit"), func() {
	It("ranks a DEFINITION site above a rarer incidental mention", func() {
		// The first real extraction was mis-filed: ranking purely by occurrence count sent a
		// claim about `customRules` to a dashboard JSON where it appears once, instead of the
		// helmrelease where it is defined and appears several times. Rarity is not relevance —
		// the canonical site usually has MORE occurrences.
		text := "a: 1\nb: mentions customRules once\n"
		_, def := definitionSite(text, "customRules")
		Expect(def).To(BeFalse(), "a mention is not a definition")

		text2 := "intro customRules here\ncustomRules:\n  - rule\n"
		off, def2 := definitionSite(text2, "customRules")
		Expect(def2).To(BeTrue())
		Expect(strings.Count(text2[:off], "\n")).To(Equal(1), "must point at the KEY line, not the earlier mention")
	})

	It("treats a list-dashed key as a definition too", func() {
		_, def := definitionSite("  - thing: value\n", "thing")
		Expect(def).To(BeTrue())
	})

	It("requires a named subject — an assertion with no anchor cannot be filed", func() {
		// Prose that asserts something but names nothing has no destination. Emitting it would
		// convert a documentation problem into a filing problem, which is the failure this
		// command exists to avoid.
		d := MakeDoc("x.md", "---\ntype: reference\nstatus: current\ncovers:\n  - repo\n---\n\n# H\n\nThis must never happen because it breaks things.\n")
		Expect(ExtractFromDoc(&Ctx{Cfg: &Config{}, Root: "."}, d, "nowhere")).To(BeEmpty())
	})
})

var _ = Describe("destination ranking", Label("unit"), func() {
	It("puts a definition site above a rarer mention — the actual mis-filing bug", func() {
		// Guards the BEHAVIOUR, not the helper. The previous spec tested definitionSite() only,
		// so removing the ranking left the suite green while reintroducing the bug that sent a
		// `customRules` claim to a dashboard JSON instead of the helmrelease.
		hits := []DestHit{
			{Token: "customRules", File: "dashboards/falco-ops.json", Count: 1, Def: false},
			{Token: "customRules", File: "helmrelease.yaml", Count: 4, Def: true},
		}
		rankHits(hits)
		Expect(hits[0].File).To(Equal("helmrelease.yaml"),
			"the definition must outrank a rarer incidental mention")
	})

	It("falls back to rarity when neither hit is a definition", func() {
		hits := []DestHit{{File: "a", Count: 9}, {File: "b", Count: 2}}
		rankHits(hits)
		Expect(hits[0].File).To(Equal("b"))
	})
})
