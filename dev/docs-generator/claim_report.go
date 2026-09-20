package main

// The `claims` command: inventory, validation, and extraction.
//
// EXTRACTION IS THE PART THAT CANNOT BE DONE BY HAND. The inventory and the rules mechanise
// distinctions a human could in principle apply; the proposer addresses the fact that they
// demonstrably do not. One day of work in this repo produced ~25KB of commit-message prose and
// ~1,200 lines of comments, dense with sentences like "Verified 2026-09-19: all 9 pods carry
// k8s-app: crowdsec" — claims in everything but form, with real justifications attached,
// invisible to any tool.
//
// What `--propose` does is deliberately modest and deliberately NOT an LLM: it finds
// assertion-shaped prose that is not yet a claim and prints it as a skeleton to be completed.
// The judgement calls it leaves open are exactly the ones worth a human or a model:
//   - is this one claim or three?
//   - what is the falsifier?
//   - is the justification it cites actually bearing on the assertion? (the `cscli config show`
//     failure was a real command that could not have returned anything else)
// A regex cannot answer those. It can stop them from never being asked.

import (
	"fmt"
	"regexp"
	"sort"
	"strings"
)

// assertionRe matches prose that asserts a checked fact. Tuned from this repo's own comments:
// the verbs are the ones people actually reach for when they have just looked at something.
var (
	assertionRe = regexp.MustCompile(`(?i)\b(verified|measured|confirmed|proved|proven|tested|observed|reproduced)\b`)
	datedRe     = regexp.MustCompile(`\b20[0-9]{2}-[0-9]{2}-[0-9]{2}\b`)
	commentLine = regexp.MustCompile(`^\s*(?://+|#+)\s?(.*)$`)
)

func reportClaims(ctx *Ctx, propose bool, all bool) int {
	claims := CollectClaims(ctx)

	if propose {
		return reportProposals(ctx, claims, all)
	}

	findings := RunClaimRules(ctx, claims)

	byMode := map[Modality]int{}
	for _, c := range claims {
		byMode[c.Mode]++
	}
	fmt.Printf("%d claim(s) across %d carrier file(s)\n", len(claims), len(ctx.ClaimSources))
	fmt.Printf("  enforced %d · verified %d · asserted %d · superseded %d\n\n",
		byMode[Enforced], byMode[Verified], byMode[Asserted], byMode[Superseded])

	sort.Slice(claims, func(i, j int) bool {
		if claims[i].File != claims[j].File {
			return claims[i].File < claims[j].File
		}
		return claims[i].Line < claims[j].Line
	})
	for _, c := range claims {
		mode := string(c.Mode)
		if c.At != "" {
			mode += "@" + c.At
		}
		fmt.Printf("  %-22s %-16s %s\n", c.ID, mode, truncate(c.Says, 74))
		fmt.Printf("  %-22s %-16s %s\n", "", "", "  "+c.Ref())
	}

	if len(findings) == 0 {
		fmt.Printf("\nno claim findings\n")
		return 0
	}
	fmt.Printf("\n%d claim finding(s):\n", len(findings))
	for _, f := range findings {
		fmt.Printf("  %-24s %s\n      %s\n", f.Rule, f.Path, f.Message)
	}
	return 1
}

// Proposal is assertion-shaped prose that is not yet a claim.
type Proposal struct {
	File string
	Line int
	Text string
	Why  string // which signal fired, so the output is auditable rather than magic
}

func reportProposals(ctx *Ctx, existing []Claim, all bool) int {
	claimed := map[string]bool{}
	for _, c := range existing {
		claimed[fmt.Sprintf("%s:%d", c.File, c.Line)] = true
	}

	var props []Proposal
	for _, f := range ctx.ClaimSources {
		props = append(props, proposeFrom(f.Path, f.Text, claimed)...)
	}
	for _, d := range ctx.Docs {
		props = append(props, proposeFrom(d.Path, d.Body, claimed)...)
	}

	sort.Slice(props, func(i, j int) bool {
		if props[i].File != props[j].File {
			return props[i].File < props[j].File
		}
		return props[i].Line < props[j].Line
	})

	limit := len(props)
	if !all && limit > lintTruncateAt {
		limit = lintTruncateAt
	}
	fmt.Printf("%d candidate assertion(s) not yet recorded as claims\n\n", len(props))
	for _, p := range props[:limit] {
		fmt.Printf("  %s:%d  [%s]\n", p.File, p.Line, p.Why)
		fmt.Printf("      %s\n", truncate(p.Text, 96))
		fmt.Printf("      claim(verified@YYYY-MM-DD) <id>: %s\n", truncate(p.Text, 60))
		fmt.Printf("        j: <the command or test that showed this>\n")
		fmt.Printf("        f: <what would make it false>          <- if you cannot write this,\n")
		fmt.Printf("                                                  it is asserted, not verified\n\n")
	}
	if n := len(props) - limit; n > 0 {
		fmt.Printf("  … and %d more (re-run with -all to see every candidate)\n", n)
	}
	return 0
}

func proposeFrom(path, text string, claimed map[string]bool) []Proposal {
	var out []Proposal
	// A claim already present suppresses proposals for the lines around it, so completing one
	// does not leave the source nagging about the prose that motivated it.
	for i, line := range strings.Split(text, "\n") {
		m := commentLine.FindStringSubmatch(line)
		body := line
		inComment := false
		if m != nil {
			body, inComment = m[1], true
		}
		if strings.Contains(body, "claim(") {
			continue
		}
		hasVerb := assertionRe.MatchString(body)
		hasDate := datedRe.MatchString(body)
		if !hasVerb && !hasDate {
			continue
		}
		// Prose, not a one-word fragment: an assertion worth recording has a subject.
		if len(strings.Fields(body)) < 6 {
			continue
		}
		// Only comments in code/config; in markdown any prose line qualifies.
		if !inComment && !strings.HasSuffix(path, ".md") {
			continue
		}
		if claimed[fmt.Sprintf("%s:%d", path, i+1)] {
			continue
		}
		why := "verb"
		switch {
		case hasVerb && hasDate:
			why = "verb+date"
		case hasDate:
			why = "date"
		}
		out = append(out, Proposal{File: path, Line: i + 1, Text: strings.TrimSpace(body), Why: why})
	}
	return out
}
