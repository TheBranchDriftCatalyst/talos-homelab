package main

// Rules over claims. Each one mechanises a distinction that a human reviewer demonstrably does
// not make reliably — every rule here corresponds to a real defect this repo shipped.

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// ruleClaimFalsifier: any claim above `asserted` must say what would make it false.
//
// THE MOST IMPORTANT RULE IN THE ENGINE. A justification J for φ is only valid if ¬φ is
// representable. The soak criterion "every alerted IP is in the <=8-distinct set" had a real
// procedure, real output, and a green result — and the scenario's own condition was
// `distinct <= 8`, so no possible run could have failed it. Passing conveyed zero bits.
//
// Requiring the falsifier does not prove the claim is non-vacuous; a determined author can write
// a falsifier that cannot occur. It forces the author to ATTEMPT the sentence, which is where
// vacuity usually becomes obvious to them. `asserted` is exempt by design: design rationale has
// no falsifier and needs none.
func ruleClaimFalsifier(ctx *Ctx, claims []Claim) []Finding {
	var out []Finding
	for _, c := range claims {
		if c.Mode == Asserted || c.Mode == Superseded {
			continue
		}
		if strings.TrimSpace(c.F) == "" {
			out = append(out, Finding{
				Rule: "claim-falsifier", Path: c.Ref(),
				Message: fmt.Sprintf("claim %q is %s but has no falsifier — say what would make it false, "+
					"or demote it to asserted", c.ID, c.Mode),
			})
		}
	}
	return out
}

// ruleClaimJustification: enforced and verified claims must name HOW anyone knows.
func ruleClaimJustification(ctx *Ctx, claims []Claim) []Finding {
	var out []Finding
	for _, c := range claims {
		if c.Mode != Enforced && c.Mode != Verified {
			continue
		}
		if strings.TrimSpace(c.J) == "" {
			out = append(out, Finding{
				Rule: "claim-justification", Path: c.Ref(),
				Message: fmt.Sprintf("claim %q is %s with no justification — an unjustified claim is "+
					"asserted, whatever it is labelled", c.ID, c.Mode),
			})
		}
	}
	return out
}

// ruleClaimEnforcedResolves: an `enforced` claim's gate must actually exist.
//
// This is the 18-dead-entries defect, generalised. tests/telemetry/dashboards.py carried 18
// curated EXPECTED_EMPTY entries for a dashboard its own discovery could never see: config that
// read as coverage, executed never, and kept a suite green at 713 passing while auditing zero
// panels. An `enforced` claim naming a deleted test is the same shape and worse, because
// `enforced` is the strongest label the vocabulary offers.
//
// The check is deliberately a plain substring search across the tracked corpus rather than a
// language-aware symbol lookup. It cannot confirm the gate RUNS — only that the name it invokes
// is not a ghost. Cheap, and it catches deletion, which is the common case.
func ruleClaimEnforcedResolves(ctx *Ctx, claims []Claim) []Finding {
	var out []Finding
	for _, c := range claims {
		if c.Mode != Enforced || strings.TrimSpace(c.J) == "" {
			continue
		}
		tok := enforcementToken(c.J)
		if tok == "" {
			continue // not a name-shaped justification; nothing to resolve
		}
		if !ctx.corpusContains(tok, c.File) {
			out = append(out, Finding{
				Rule: "claim-enforced-resolves", Path: c.Ref(),
				Message: fmt.Sprintf("claim %q is enforced by %q, which appears nowhere in the repo — "+
					"the gate was probably deleted, and the claim now reads as the strongest "+
					"guarantee while providing none", c.ID, tok),
			})
		}
	}
	return out
}

// ruleClaimDecayed: a verified claim whose scope changed after the verification date.
//
// The modality transition that makes this an engine rather than a linter. docsgen already had
// both ingredients — cover resolution and per-path git dates — and used them only to print a
// staleness warning next to the doc. Here the same signal says the CLAIM is no longer knowledge.
func ruleClaimDecayed(ctx *Ctx, claims []Claim) []Finding {
	var out []Finding
	for _, c := range claims {
		if dec, why := c.Decayed(ctx); dec {
			out = append(out, Finding{
				Rule: "claim-decayed", Path: c.Ref(),
				Message: fmt.Sprintf("claim %q was verified@%s but %s — re-run `%s` and restamp, or "+
					"demote to asserted", c.ID, c.At, why, truncate(c.J, 60)),
			})
		}
	}
	return out
}

// ruleClaimContradiction: one id, two different statements.
//
// Not a style rule. Two comments asserting opposite things about the same subject is exactly
// what happened with agents_autodelete — one note said `login_password` was ignored, the source
// said `api_key` was — and the contradiction sat unnoticed because the two never appeared on
// screen together. Sharing an id is what makes it visible.
func ruleClaimContradiction(ctx *Ctx, claims []Claim) []Finding {
	byID := map[string][]Claim{}
	for _, c := range claims {
		byID[c.ID] = append(byID[c.ID], c)
	}
	var out []Finding
	for id, group := range byID {
		if len(group) < 2 {
			continue
		}
		first := normalizeSays(group[0].Says)
		for _, c := range group[1:] {
			if normalizeSays(c.Says) != first {
				out = append(out, Finding{
					Rule: "claim-contradiction", Path: c.Ref(),
					Message: fmt.Sprintf("claim %q says something different here than at %s — "+
						"%q vs %q", id, group[0].Ref(), truncate(c.Says, 48), truncate(group[0].Says, 48)),
				})
				break
			}
		}
	}
	return out
}

// ruleClaimSuperseded: a superseded claim must name what replaced it.
//
// A claim marked false with no successor tells the next reader that the obvious answer is wrong
// without telling them which answer to use, which is how the same wrong path gets retried.
func ruleClaimSuperseded(ctx *Ctx, claims []Claim) []Finding {
	var out []Finding
	for _, c := range claims {
		if c.Mode == Superseded && strings.TrimSpace(c.Successor) == "" {
			out = append(out, Finding{
				Rule: "claim-superseded", Path: c.Ref(),
				Message: fmt.Sprintf("claim %q is superseded but names no successor — record what "+
					"replaced it, or the next reader retries the same wrong path", c.ID),
			})
		}
	}
	return out
}

// RunClaimRules evaluates every rule and returns findings in a stable order.
func RunClaimRules(ctx *Ctx, claims []Claim) []Finding {
	var out []Finding
	for _, r := range []func(*Ctx, []Claim) []Finding{
		ruleClaimFalsifier,
		ruleClaimJustification,
		ruleClaimEnforcedResolves,
		ruleClaimDecayed,
		ruleClaimContradiction,
		ruleClaimSuperseded,
	} {
		out = append(out, r(ctx, claims)...)
	}
	return out
}

// ---- helpers --------------------------------------------------------------------------------

// enforcementToken pulls the name-shaped part out of a justification, so `TestFoo` and
// `docsgen lint -rule broken-links` both yield something resolvable. Returns "" when the
// justification is a shell pipeline or prose, which cannot be resolved this way.
func enforcementToken(j string) string {
	j = strings.TrimSpace(j)
	// A bare identifier: test name, rule id, alert name.
	if !strings.ContainsAny(j, " |$<>") {
		return j
	}
	// `-rule <id>` is this repo's own convention for naming a lint gate.
	if i := strings.Index(j, "-rule "); i >= 0 {
		rest := strings.Fields(j[i+len("-rule "):])
		if len(rest) > 0 {
			return rest[0]
		}
	}
	for _, f := range strings.Fields(j) {
		if strings.HasPrefix(f, "Test") || strings.HasPrefix(f, "test_") {
			return f
		}
	}
	return ""
}

func (c *Ctx) corpusContains(tok, except string) bool {
	for _, d := range c.Docs {
		if d.Path != except && strings.Contains(d.Text, tok) {
			return true
		}
	}
	for _, f := range c.ClaimSources {
		if f.Path != except && strings.Contains(f.Text, tok) {
			return true
		}
	}
	// ClaimSources is prefiltered to files containing "claim(", so a test file with no claim in
	// it is invisible above. Fall back to a direct read of the tracked tree for the token.
	return grepTracked(c.Root, tok, except)
}

func grepTracked(root, tok, except string) bool {
	for _, line := range strings.Split(git(root, "ls-files"), "\n") {
		rel := strings.TrimSpace(line)
		if rel == "" || rel == except {
			continue
		}
		switch filepath.Ext(rel) {
		case ".go", ".py", ".yaml", ".yml", ".sh", ".md":
		default:
			continue
		}
		b, err := os.ReadFile(filepath.Join(root, rel))
		if err == nil && strings.Contains(string(b), tok) {
			return true
		}
	}
	return false
}

func normalizeSays(s string) string {
	return strings.Join(strings.Fields(strings.ToLower(s)), " ")
}

func truncate(s string, n int) string {
	s = strings.Join(strings.Fields(s), " ")
	if len(s) <= n {
		return s
	}
	return s[:n-1] + "…"
}
