package main

// The `knowledge` renderer: project claims written as inline comments into a document region.
//
// This is the JSDoc idea with three deliberate differences, each of which exists because the
// JSDoc shape does not survive contact with infrastructure code.
//
//  1. THE UNIT IS A DECISION, NOT A SYMBOL. JSDoc documents a function: the comment attaches to
//     a declaration and the output is an API reference. Most knowledge in this repo attaches to
//     nothing declarable — `bouncers_autodelete: 48h` is a YAML scalar, and the thing worth
//     recording is a three-way interaction between a GC query, a CLI that cascades, and an index
//     that makes a future upstream change dangerous. There is no symbol to hang that on.
//
//  2. THE DESTINATION IS DERIVED, NOT DECLARED. The obvious design is an `into: path#anchor`
//     directive in the comment. That is a hand-maintained list of destinations, and this repo
//     spent a day proving that a hand-maintained list of generated things rots exactly like the
//     hand-maintained list of links it replaced — docs/05-runbooks was omitted from the nav
//     config and quietly decayed to six dead links. So projection reuses `scope`, the field the
//     claim already carries: a claim lands in the document whose root contains its scope. Same
//     computed-location principle as colocation, no second vocabulary, nothing to forget.
//
//  3. THE PROSE DOES NOT MOVE. The region renders an INDEX — what is known, on what basis, what
//     would falsify it, and where to read the reasoning. The reasoning itself stays in the
//     comment beside the code it constrains, because that is where someone changing the code
//     will actually see it. Moving prose into generated documents would recreate the drift this
//     whole effort exists to remove: the document would be maintained and the code comment would
//     rot, or vice versa. One source, one projection, no duplication.
//
// The falsifier column is the one a reader should look at first. A claim whose falsifier can no
// longer occur is no longer telling you anything, and putting it in the table makes that visible
// without opening the source.

import (
	"fmt"
	"sort"
	"strings"
)

func renderKnowledge(ctx *Ctx, spec ArtifactSpec) string {
	root := strings.Trim(strings.TrimSpace(spec.Root), "/")
	claims := claimsUnder(CollectClaims(ctx), root, spec.Scope)

	var b strings.Builder
	if len(claims) == 0 {
		// An empty region says so rather than rendering an empty table. A table with headers and
		// no rows reads as "nothing is known here", which is indistinguishable from "the scope
		// filter is wrong" — the failure mode that kept 18 curated entries pointing at a
		// dashboard nothing could see.
		fmt.Fprintf(&b, "_No claims are recorded under `%s` yet._ Write one as a comment beside the\n", rootLabel(root))
		fmt.Fprintf(&b, "code it constrains — see `docsgen claims -propose` for candidates already in the tree.\n")
		return b.String()
	}

	sort.Slice(claims, func(i, j int) bool {
		// Enforced first, then verified, then asserted, then superseded: strongest basis at the
		// top, because a reader scanning for "what can I rely on" should not have to sort.
		oi, oj := modeOrder(claims[i].Mode), modeOrder(claims[j].Mode)
		if oi != oj {
			return oi < oj
		}
		return claims[i].ID < claims[j].ID
	})

	b.WriteString("| What is known | Basis | What would falsify it | Source |\n")
	b.WriteString("| --- | --- | --- | --- |\n")
	for _, c := range claims {
		basis := string(c.Mode)
		if c.At != "" {
			basis += " " + c.At
		}
		f := c.F
		if strings.TrimSpace(f) == "" {
			// asserted and superseded legitimately have none. Naming WHICH is the point:
			// an empty cell reads as an omission rather than a property of the claim, and
			// labelling a superseded claim "asserted" is simply wrong.
			f = fmt.Sprintf("_n/a — %s_", c.Mode)
		}
		fmt.Fprintf(&b, "| **%s** — %s | %s | %s | [%s](%s) |\n",
			c.ID, cellEscape(c.Says), basis, cellEscape(f),
			shortRef(c.File, c.Line), relLink(spec, c.File, c.Line))
	}
	return b.String()
}

// claimsUnder selects claims whose scope falls inside the artifact's root.
//
// A claim with NO scope is deliberately excluded rather than shown everywhere. A scopeless claim
// is also one that can never decay, and surfacing it in every document would spread a permanently
// fresh-looking assertion across the tree — the opposite of what the modality system is for.
func claimsUnder(all []Claim, root string, scope *ArtifactScope) []Claim {
	prefix := root
	if scope != nil && strings.TrimSpace(scope.PathPrefix) != "" {
		prefix = strings.Trim(strings.TrimSpace(scope.PathPrefix), "/")
	}
	var out []Claim
	for _, c := range all {
		for _, s := range c.Scope {
			p := strings.TrimPrefix(s, "path:")
			p = strings.Trim(p, "/")
			if prefix == "" || p == prefix || strings.HasPrefix(p, prefix+"/") {
				out = append(out, c)
				break
			}
		}
	}
	return out
}

func modeOrder(m Modality) int {
	switch m {
	case Enforced:
		return 0
	case Verified:
		return 1
	case Asserted:
		return 2
	default:
		return 3
	}
}

func rootLabel(root string) string {
	if root == "" {
		return "."
	}
	return root
}

func shortRef(file string, line int) string {
	base := file
	if i := strings.LastIndex(file, "/"); i >= 0 {
		base = file[i+1:]
	}
	if line > 1 {
		return fmt.Sprintf("%s:%d", base, line)
	}
	return base
}

// relLink builds a path from the artifact back to the claim's source file.
//
// Deliberately repo-relative-with-../ rather than a bare repo path: these land in READMEs that
// are read on disk and on a forge, and only a relative link works in both.
func relLink(spec ArtifactSpec, file string, line int) string {
	from := strings.Trim(strings.TrimSpace(spec.Root), "/")
	rel := file
	if from != "" && strings.HasPrefix(file, from+"/") {
		rel = strings.TrimPrefix(file, from+"/")
	} else if from != "" {
		up := strings.Count(from, "/") + 1
		rel = strings.Repeat("../", up) + file
	}
	if line > 1 {
		return fmt.Sprintf("%s#L%d", rel, line)
	}
	return rel
}

// cellEscape keeps a claim's prose from breaking the table it lands in.
func cellEscape(s string) string {
	s = strings.ReplaceAll(s, "|", "\\|")
	return strings.Join(strings.Fields(s), " ")
}
