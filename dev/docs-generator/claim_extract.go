package main

// EXTRACTION: pull knowledge OUT of prose and propose where in the code it belongs.
//
// The projection renderer solved one direction — a claim written beside the code appears in the
// README. This is the other direction, and it is the one that matters for a repo that already
// has years of prose: most knowledge here is currently a paragraph in a README, far from the
// line it constrains, drifting because nobody editing that line ever sees it.
//
// THE HARD PART IS NOT FINDING THE SENTENCES. `claims -propose` already does that with a verb
// list. The hard part is DESTINATION: a sentence about `bouncers_autodelete` belongs at the line
// where `bouncers_autodelete` is set, and a tool that cannot say which line has only converted a
// documentation problem into a filing problem.
//
// THE ANCHOR IS THE BACKTICKED TOKEN. Prose that makes a checkable claim about a system almost
// always names the thing it is about, and in markdown that name is in backticks — a config key,
// a file, a metric, a flag. So: take the code spans out of the sentence, look for where they
// occur in the component's own tree, and propose the narrowest match as the destination. When a
// token resolves to exactly one line, that line IS the answer. When it resolves to many, the
// tool says so rather than guessing, because a confidently wrong destination is worse than an
// unfiled claim — it puts the knowledge somewhere nobody will look and marks the job done.
//
// WHAT THIS DELIBERATELY DOES NOT DO: rewrite files. It emits the claim block and the
// destination, and a human or a model moves it. The judgement it cannot make is whether the
// sentence is ONE claim or three, and splitting a claim wrongly is not recoverable by a later
// pass — the parts stop being individually falsifiable, which is the property the whole system
// rests on.

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

var (
	codeSpanRe = regexp.MustCompile("`([^`\n]{3,60})`")
	sentenceRe = regexp.MustCompile(`(?s)[^.!?]+[.!?]`)

	// EXTRACTION NEEDS A DIFFERENT SIGNAL THAN `claims -propose`, and conflating them produced
	// zero results on two prose-heavy READMEs. The proposer looks for "someone checked
	// something" — verified, measured, confirmed — which is right for finding assertions that
	// already carry a justification. Extraction is looking for something else: prose ASSERTING
	// A PROPERTY of a named thing, which is usually written in modal language and rarely uses
	// any of those verbs.
	//
	// Measured on honeypots/README.md: 101 sentences, 91 past the length and table filters, 5
	// carrying a verb or date, and ZERO of those also naming a code identifier. Requiring both
	// signals found nothing. Anchor + modal finds 5 there and 4 in falco/README.md, which
	// matches the count of genuinely filable statements on a read-through.
	modalRe = regexp.MustCompile(`(?i)\b(must|cannot|never|always|is not|does not|only|because|so that|which means)\b`)
)

// Extraction is one prose assertion plus where its subject actually lives.
type Extraction struct {
	Doc      string
	Line     int
	Sentence string
	Anchors  []string  // backticked tokens found in the sentence
	Dest     []DestHit // where those tokens occur in the tree
}

type DestHit struct {
	Token string
	File  string
	Line  int
	Count int  // occurrences of the token in that file
	Def   bool // the token appears as a KEY here, not merely mentioned
}

// ExtractFromDoc finds assertion-shaped sentences in a markdown body and resolves their anchors.
//
// `within` scopes the search for destinations. Passing the component root rather than the repo
// keeps `enabled` or `port` from resolving to four hundred unrelated lines — the scoping is what
// makes the anchor useful rather than noise.
func ExtractFromDoc(ctx *Ctx, doc Doc, within string) []Extraction {
	var out []Extraction
	lineOf := func(off int) int { return 1 + strings.Count(doc.Body[:off], "\n") }

	for _, loc := range sentenceRe.FindAllStringIndex(doc.Body, -1) {
		s := strings.TrimSpace(doc.Body[loc[0]:loc[1]])
		if len(strings.Fields(s)) < 6 {
			continue
		}
		// Skip fenced code and table rows: both are full of backticks and neither is prose
		// making a claim.
		if strings.HasPrefix(s, "|") || strings.HasPrefix(s, "    ") || strings.Contains(s, "```") {
			continue
		}
		if !modalRe.MatchString(s) && !assertionRe.MatchString(s) && !datedRe.MatchString(s) {
			continue
		}
		var anchors []string
		for _, m := range codeSpanRe.FindAllStringSubmatch(s, -1) {
			tok := strings.TrimSpace(m[1])
			// A token that is mostly prose is not an identifier; requiring no spaces keeps
			// `the GC flush` out while keeping `bouncers_autodelete` and file paths in.
			if tok != "" && !strings.Contains(tok, " ") {
				anchors = append(anchors, tok)
			}
		}
		if len(anchors) == 0 {
			continue // an assertion with no named subject cannot be filed
		}
		out = append(out, Extraction{
			Doc: doc.Path, Line: lineOf(loc[0]),
			Sentence: strings.Join(strings.Fields(s), " "),
			Anchors:  anchors,
			Dest:     locateAnchors(ctx, anchors, within),
		})
	}
	return out
}

// locateAnchors finds where each token occurs under `within`, narrowest first.
func locateAnchors(ctx *Ctx, anchors []string, within string) []DestHit {
	within = strings.Trim(within, "/")
	var hits []DestHit
	seen := map[string]bool{}
	for _, tok := range anchors {
		if seen[tok] {
			continue
		}
		seen[tok] = true
		for _, f := range trackedUnder(ctx.Root, within) {
			b, err := os.ReadFile(filepath.Join(ctx.Root, f))
			if err != nil {
				continue
			}
			text := string(b)
			n := strings.Count(text, tok)
			if n == 0 {
				continue
			}
			idx, def := definitionSite(text, tok)
			line := 1 + strings.Count(text[:idx], "\n")
			hits = append(hits, DestHit{Token: tok, File: f, Line: line, Count: n, Def: def})
		}
	}
	// DEFINITION BEFORE RARITY. The first version ranked purely by occurrence count, on the
	// theory that a token appearing once is a destination and one appearing forty times is a
	// topic. That mis-filed the first real extraction it was given: `customRules` went to a
	// dashboard JSON where it appears once, instead of the helmrelease where it is DEFINED and
	// appears several times.
	//
	// Rarity is not relevance — the canonical site usually has MORE occurrences, not fewer. So
	// a hit where the token appears as a key (`tok:` at the start of a line) outranks any
	// number of incidental mentions, and count only breaks ties among equals.
	rankHits(hits)
	return hits
}

func trackedUnder(root, within string) []string {
	var out []string
	for _, line := range strings.Split(git(root, "ls-files"), "\n") {
		rel := strings.TrimSpace(line)
		if rel == "" || strings.HasSuffix(rel, ".md") {
			continue // destinations are code and config; prose is what we are moving OUT of
		}
		if within != "" && !strings.HasPrefix(rel, within+"/") {
			continue
		}
		out = append(out, rel)
	}
	return out
}

func reportExtract(ctx *Ctx, docPath string, all bool) int {
	var target *Doc
	for i := range ctx.Docs {
		if ctx.Docs[i].Path == docPath || strings.HasSuffix(ctx.Docs[i].Path, "/"+docPath) {
			target = &ctx.Docs[i]
			break
		}
	}
	if target == nil {
		fmt.Fprintf(os.Stderr, "no tracked document matches %q\n", docPath)
		return 2
	}
	within := filepath.Dir(target.Path)

	ex := ExtractFromDoc(ctx, *target, within)
	fmt.Printf("%s — %d assertion(s) with a named subject, searched under %s/\n\n", target.Path, len(ex), within)

	limit := len(ex)
	if !all && limit > lintTruncateAt {
		limit = lintTruncateAt
	}
	for _, e := range ex[:limit] {
		fmt.Printf("  %s:%d\n    %s\n", e.Doc, e.Line, truncate(e.Sentence, 100))
		switch {
		case len(e.Dest) == 0:
			fmt.Printf("    DESTINATION: none — %v occurs nowhere under %s/. Either the subject moved,\n"+
				"                 or this belongs in a cross-cutting doc rather than beside code.\n", e.Anchors, within)
		default:
			best := e.Dest[0]
			if best.Count == 1 {
				fmt.Printf("    DESTINATION: %s:%d  (`%s` occurs exactly once — unambiguous)\n", best.File, best.Line, best.Token)
			} else {
				fmt.Printf("    DESTINATION: %s:%d  (`%s` occurs %d× here — CHECK before filing)\n", best.File, best.Line, best.Token, best.Count)
			}
			fmt.Printf("      # claim(verified@YYYY-MM-DD) <id>: %s\n", truncate(e.Sentence, 72))
			fmt.Printf("      #   j: <what showed this>\n")
			fmt.Printf("      #   f: <what would make it false>\n")
			fmt.Printf("      #   scope: path:%s\n", best.File)
		}
		fmt.Println()
	}
	if n := len(ex) - limit; n > 0 {
		fmt.Printf("  … and %d more (re-run with -all)\n", n)
	}
	return 0
}

// definitionSite returns the offset of the best occurrence of tok, preferring a line where it
// appears as a key — `tok:` with only whitespace or a list dash before it.
func definitionSite(text, tok string) (int, bool) {
	off := 0
	for _, line := range strings.Split(text, "\n") {
		trimmed := strings.TrimLeft(line, " \t-")
		if strings.HasPrefix(trimmed, tok) {
			rest := strings.TrimSpace(strings.TrimPrefix(trimmed, tok))
			if strings.HasPrefix(rest, ":") || strings.HasPrefix(rest, "=") {
				return off + strings.Index(line, tok), true
			}
		}
		off += len(line) + 1
	}
	return strings.Index(text, tok), false
}

// rankHits orders destinations: definition sites first, then by ascending occurrence count.
//
// A named function rather than an inline closure so it is directly testable. The first version
// of this ranking was inline, and the spec covering it tested definitionSite() alone — so
// deleting the ranking entirely left every test green while reintroducing the mis-filing bug.
// A spec that exercises the helper is not a spec that exercises the behaviour.
func rankHits(hits []DestHit) {
	sort.SliceStable(hits, func(i, j int) bool {
		if hits[i].Def != hits[j].Def {
			return hits[i].Def
		}
		return hits[i].Count < hits[j].Count
	})
}
