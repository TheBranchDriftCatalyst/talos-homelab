package main

import (
	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
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
