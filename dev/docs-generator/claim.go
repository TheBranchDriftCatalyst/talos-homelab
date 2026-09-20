package main

// CLAIMS: the unit of knowledge, and the thing docsgen was missing.
//
// Everything docsgen checked before this file was about WHERE a document lives and WHETHER its
// references resolve. Nothing checked whether what a document SAYS is true, or how anyone knew.
// That gap is not academic — it cost real time in this repo:
//
//   - a config comment read "verified via `cscli config show`: it left AgentsGC.Api nil". The
//     verification was real. It checked a field the thing under test CANNOT SET, so it could not
//     have returned anything else. A belief, formatted as knowledge.
//   - an EXPECTED_EMPTY entry read "empty = healthy". Inverted: a canary guaranteed data, so
//     empty meant the canary had died.
//   - a promotion criterion read "every alerted IP is in the <=8-distinct set". The scenario's
//     own condition is `distinct <= 8`, so the criterion was true BY CONSTRUCTION. The soak ran,
//     went green, and conveyed zero bits.
//
// The three failures differ, and the schema below exists to separate them:
//   the first had a justification that did not bear on the claim
//   the second had no justification at all, only assertion
//   the third had a justification that COULD NOT FAIL
//
// THE FACTIVITY RULE. Epistemic logic distinguishes K(nows) from B(elieves), and the property
// that matters is factivity: Kφ → φ. Knowledge is true by definition; belief need not be. Every
// failure above was a belief wearing a knowledge costume. A claim therefore carries its MODALITY
// explicitly, and the modality is a claim about the JUSTIFICATION, not about confidence.
//
// THE FALSIFIER IS THE LOAD-BEARING FIELD. A justification J for φ is only valid if ¬φ is
// representable — there must be some state of the world in which J fails. That is mutation
// testing stated epistemically, and it is precisely what the tautological soak lacked. If you
// cannot write the falsifier, you do not have knowledge, you have a slogan. Rules below REQUIRE
// it for any claim above `asserted`.
//
// WHY THREE SYNTAXES FOR ONE GRAMMAR. Measured on one day of work in this repo: ~1,016 lines of
// code comments, ~194 lines of YAML comments, ~25KB of commit messages, against a much smaller
// number of lines added under docs/. Knowledge here lives next to the thing that drifts, not in
// the documentation tree. A claim engine scoped to docs/ would manage the minority of it. So the
// same grammar parses from markdown frontmatter, from `#` comments, and from `//` comments.

import (
	"fmt"
	"regexp"
	"strings"
	"time"
)

// Modality is a statement about the JUSTIFICATION, not about how sure the author feels.
type Modality string

const (
	// Enforced: a gate asserts φ continuously. φ cannot be false while the gate is green.
	// J must name something that EXISTS — see ruleClaimEnforcedResolves. An `enforced` claim
	// whose gate was deleted is the most dangerous state in this file, because it reads as the
	// strongest guarantee while providing none.
	Enforced Modality = "enforced"

	// Verified at a point in time: someone ran J and φ held. This DECAYS. If the code the claim
	// is about changed after that date, the justification is stale and the claim silently drops
	// to `asserted` until re-run.
	Verified Modality = "verified"

	// Asserted: believed, with no executable justification. This is an honest and permanent
	// resting state for design rationale ("we chose X because Y"), which has no test and needs
	// none. The failure mode is never an unverified claim — it is an unverified claim PRESENTED
	// as verified.
	Asserted Modality = "asserted"

	// Superseded: known false. Retained rather than deleted, because a wrong belief that was
	// acted on is itself knowledge — it tells the next reader which plausible answer to skip.
	Superseded Modality = "superseded"
)

var modalities = map[Modality]bool{Enforced: true, Verified: true, Asserted: true, Superseded: true}

// Claim is one knowledge item, wherever it was written.
type Claim struct {
	ID        string // stable handle; duplicates with differing text are contradictions
	Says      string // φ
	Mode      Modality
	At        string   // ISO date; required for `verified`, meaningless otherwise
	J         string   // justification: a command, a test name, a rule id, a query
	F         string   // falsifier: what state of the world makes φ false
	Scope     []string // what code this is about; same vocabulary as covers:
	Successor string   // required for `superseded`

	File    string // where the claim was written
	Line    int
	Carrier string // md-frontmatter | hash-comment | slash-comment
}

func (c Claim) Ref() string { return fmt.Sprintf("%s:%d", c.File, c.Line) }

// Decayed reports whether a `verified` claim's justification predates a change to its scope.
//
// This is the modality transition that makes the engine more than a linter: knowledge is indexed
// to a world-state, and when the world moves without the justification being re-run, the claim
// is no longer knowledge. docsgen already computed the ingredients for this — `covers:` scope
// resolution and per-path git dates — and used them only to print a staleness warning. Here the
// same signal DEMOTES the claim, which is the difference between reporting drift and modelling it.
func (c Claim) Decayed(ctx *Ctx) (bool, string) {
	if c.Mode != Verified || c.At == "" {
		return false, ""
	}
	at, err := time.Parse("2006-01-02", c.At)
	if err != nil {
		return false, ""
	}
	for _, s := range c.Scope {
		p, ok := resolveCover(ctx, s)
		if !ok {
			continue
		}
		newest := staleSubject(ctx, []string{s})
		if newest == "" {
			continue
		}
		nt, err := time.Parse(time.RFC3339, newest)
		if err != nil {
			continue
		}
		// Same-day is NOT decay: verifying on the day code changed is the normal case, and
		// treating it as stale would make every fresh claim decay the moment it was written.
		if nt.Format("2006-01-02") > at.Format("2006-01-02") {
			return true, fmt.Sprintf("%s changed %s, verified %s", p, nt.Format("2006-01-02"), c.At)
		}
	}
	return false, ""
}

// ---- parsing: one grammar, three syntaxes ---------------------------------------------------
//
//	claim(<modality>[@<date>]) <id>: <what it says>
//	  j: <justification>
//	  f: <falsifier>
//	  scope: <cover>, <cover>
//	  successor: <id>            (superseded only)
//
// The header line is deliberately readable as prose, because a claim nobody reads is a claim
// nobody maintains. `# claim(verified@2026-09-20) traefik-null: the row has last_pull NULL`
// is a sentence first and a record second.

var (
	claimHeadRe  = regexp.MustCompile(`claim\(\s*(enforced|verified|asserted|superseded)\s*(?:@\s*([0-9]{4}-[0-9]{2}-[0-9]{2}))?\s*\)\s*([a-z0-9][a-z0-9._-]*)\s*:\s*(.+?)\s*$`)
	claimFieldRe = regexp.MustCompile(`^\s*(?://|#)?\s*(j|f|scope|successor)\s*:\s*(.+?)\s*$`)
	commentRe    = regexp.MustCompile(`^\s*(?://+|#+)\s?`)
)

// ParseClaims extracts claims from any text, using the comment prefix as a hint rather than a
// requirement. Markdown frontmatter is handled by the caller, which hands the body through here
// too — a claim written in prose inside a doc is still a claim.
func ParseClaims(file, text, carrier string) []Claim {
	var out []Claim
	lines := strings.Split(text, "\n")
	for i := 0; i < len(lines); i++ {
		m := claimHeadRe.FindStringSubmatch(lines[i])
		if m == nil {
			continue
		}
		// A claim inside a backtick span is an EXAMPLE, not a claim.
		//
		// Found the moment the scope rule went live: this file's own doc comment demonstrates
		// the grammar, and the parser dutifully registered the demonstration as a real claim
		// with no scope. The documentation OF the format was parsed BY the format. Test
		// fixtures did the same thing from _test.go.
		//
		// Backticks are the right discriminator rather than a path exclusion list, because
		// they already mean "a literal being shown" in both markdown and godoc, and a list of
		// excluded files is one more hand-maintained thing to forget.
		if inBacktickSpan(lines[i], strings.Index(lines[i], "claim(")) {
			continue
		}
		c := Claim{
			ID: m[3], Mode: Modality(m[1]), At: m[2], Says: m[4],
			File: file, Line: i + 1, Carrier: carrier,
		}
		// Continuation. Two things wrap in practice and both must be handled, because the
		// alternative is a parser that silently keeps half a claim:
		//
		//   1. `says` wraps across comment lines. A claim worth writing rarely fits in 90
		//      columns, and the first version of this parser stopped at the wrap — so a claim
		//      with a perfectly good j: and f: two lines below was reported as having neither.
		//      That failure is worse than not parsing at all: it accuses the author of the
		//      exact sloppiness they avoided.
		//   2. field lines follow, and once a field is seen `says` is closed.
		//
		// A line that is not a comment at all ends the claim, so it can never swallow code.
		seenField := false
		openField := ""
		for j := i + 1; j < len(lines); j++ {
			if !commentRe.MatchString(lines[j]) && strings.TrimSpace(lines[j]) != "" {
				break // left the comment block
			}
			stripped := commentRe.ReplaceAllString(lines[j], "")
			fm := claimFieldRe.FindStringSubmatch(stripped)
			if fm == nil {
				if strings.TrimSpace(stripped) == "" {
					break
				}
				// FIELD VALUES WRAP TOO, and missing this was worse than missing the `says`
				// wrap. The first version folded wrapped `says` lines but broke on a wrapped
				// FIELD, so a claim whose `f:` ran to two lines lost every field after it —
				// including `scope`, which is what drives decay. The engine then printed "no
				// claim findings": healthy-looking output produced by silently discarding the
				// input. That is precisely the failure this whole file exists to catch,
				// happening inside the tool. Continuations now append to whichever field is
				// open, and only a blank or non-comment line ends the claim.
				switch {
				case !seenField:
					c.Says = strings.TrimSpace(c.Says + " " + strings.TrimSpace(stripped))
				case openField == "j":
					c.J = strings.TrimSpace(c.J + " " + strings.TrimSpace(stripped))
				case openField == "f":
					c.F = strings.TrimSpace(c.F + " " + strings.TrimSpace(stripped))
				case openField == "successor":
					c.Successor = strings.TrimSpace(c.Successor + " " + strings.TrimSpace(stripped))
				case openField == "scope":
					for _, sc := range strings.Split(stripped, ",") {
						if sc = strings.TrimSpace(sc); sc != "" {
							c.Scope = append(c.Scope, sc)
						}
					}
				}
				i = j
				continue
			}
			seenField = true
			openField = fm[1]
			switch fm[1] {
			case "j":
				c.J = fm[2]
			case "f":
				c.F = fm[2]
			case "scope":
				for _, s := range strings.Split(fm[2], ",") {
					if s = strings.TrimSpace(s); s != "" {
						c.Scope = append(c.Scope, s)
					}
				}
			case "successor":
				c.Successor = fm[2]
			}
			i = j
		}
		out = append(out, c)
	}
	return out
}

// ClaimsFromFrontmatter reads the structured form.
//
// WHY MARKDOWN GETS A SECOND SYNTAX. The comment grammar is one line plus continuations, which
// is right where a claim is an aside next to the code it constrains. A document ABOUT a subject
// often carries several claims that are the point of the document, and burying those in prose
// makes them unlistable. So frontmatter takes a `claims:` list — same five fields, same
// vocabulary, addressable without reading the body:
//
//	claims:
//	  - id: traefik-gc-null
//	    says: the traefik bouncer row has last_pull NULL, so the GC flush skips it
//	    mode: verified
//	    at: 2026-09-20
//	    j: cscli bouncers list | awk '$1=="traefik"'
//	    f: last_pull becomes non-NULL, or crowdsec starts GC-ing by created_at
//	    scope: [path:infrastructure/base/security/crowdsec/helmrelease.yaml]
//
// `scope` intentionally reuses the `covers:` vocabulary rather than inventing a second one, so
// a claim decays off the same git dates the doc does.
func ClaimsFromFrontmatter(d Doc) []Claim {
	raw, ok := d.Front["claims"]
	if !ok {
		return nil
	}
	list, ok := raw.([]any)
	if !ok {
		return nil
	}
	var out []Claim
	for _, item := range list {
		m, ok := item.(map[string]any)
		if !ok {
			continue
		}
		str := func(k string) string {
			if v, ok := m[k].(string); ok {
				return strings.TrimSpace(v)
			}
			return ""
		}
		c := Claim{
			ID: str("id"), Says: str("says"), Mode: Modality(str("mode")),
			At: str("at"), J: str("j"), F: str("f"), Successor: str("successor"),
			File: d.Path, Line: 1, Carrier: "md-frontmatter",
		}
		if sc, ok := m["scope"].([]any); ok {
			for _, s := range sc {
				if v, ok := s.(string); ok {
					c.Scope = append(c.Scope, v)
				}
			}
		}
		out = append(out, c)
	}
	return out
}

// CollectClaims walks the tracked corpus. Deliberately NOT limited to docs/: the measurement
// that motivated this file showed most knowledge lives in code and config comments.
func CollectClaims(ctx *Ctx) []Claim {
	var out []Claim
	for _, d := range ctx.Docs {
		out = append(out, ClaimsFromFrontmatter(d)...)
		out = append(out, ParseClaims(d.Path, d.Body, "md-body")...)
	}
	for _, f := range ctx.ClaimSources {
		carrier := "hash-comment"
		if strings.HasSuffix(f.Path, ".go") {
			carrier = "slash-comment"
		}
		out = append(out, ParseClaims(f.Path, f.Text, carrier)...)
	}
	return out
}

// inBacktickSpan reports whether position pos falls inside a `...` span on the line.
func inBacktickSpan(line string, pos int) bool {
	if pos < 0 {
		return false
	}
	return strings.Count(line[:pos], "`")%2 == 1
}
