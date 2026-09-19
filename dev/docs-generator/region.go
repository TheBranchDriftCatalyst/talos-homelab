package main

// Marker-region ownership: the half of an artifact that lives INSIDE a hand-written document.
//
// Whole-file ownership (artifact_inventory.go + Generate) is for documents the generator wrote
// end to end. It cannot be used for INDEX.md or a section README, because those carry editorial
// prose — a grounding-pass note, a "Key Concepts" block, a list of known contradictions — that
// no generator can reproduce and that nobody can reconstruct once it is gone.
//
// So a marker-owned artifact writes ONLY the bytes between its two markers, and everything
// outside them passes through untouched, byte for byte.
//
//	<!-- docs:gen:nav -->
//
//	| Doc | What it covers |
//	| --- | --- |
//	| [quickstart.md](quickstart.md) | ... |
//
//	<!-- /docs:gen:nav -->
//
// THE BLANK LINES ARE PART OF THE CONVENTION, not formatting taste. Verified against this
// repo's pinned prettier 3.9.6: a table butted directly against an HTML comment gets a blank
// line inserted on either side, so the form without them is not a fixed point and `docsgen
// check` would report drift on the first unrelated `prettier --write`.
//
// THE HARD SAFETY RULE lives in findRegion, and it is the single thing that makes marker
// ownership survivable: a marker-owned file whose markers are missing, unbalanced or nested is
// an ERROR NAMING THE FILE. Never an append, never a fall back to whole-file ownership. Both of
// those alternatives are silent, both of them destroy or duplicate prose, and neither is
// recoverable from anything but a human's memory. Refusing to write is the only answer that
// keeps a bad marker state a five-second fix rather than a loss.

import (
	"fmt"
	"regexp"
	"strings"
)

// regionNameRe constrains a region name to a conservative token.
//
// The name is interpolated straight into an HTML comment that is then SEARCHED FOR in an
// existing document, so an unconstrained name is a way to make the generator match — and
// therefore overwrite — an arbitrary span of somebody's prose. Rejecting the name in config
// validation is cheaper than reasoning about what `-->` inside one would do.
var regionNameRe = regexp.MustCompile(`^[a-z0-9]+(?:-[a-z0-9]+)*$`)

// regionMarkers returns the opening and closing marker lines for a region name.
//
// One definition, called by both the writer and the reader, because two spellings of the same
// marker is exactly the bug that ends with the closing marker never found and the rest of the
// document treated as generated content.
func regionMarkers(name string) (open, close string) {
	return "<!-- docs:gen:" + name + " -->", "<!-- /docs:gen:" + name + " -->"
}

// regionBounds is the line span a region owns: the marker lines themselves are NOT owned, only
// what sits between them.
type regionBounds struct {
	openLine  int // index of the opening marker line
	closeLine int // index of the closing marker line
}

// findRegion locates the one region named `name` in content, or explains why it cannot.
//
// Every error names `rel`, because the only actionable form of "the markers are wrong" is the
// path of the file whose markers they are. The counts are reported too: "0 open, 1 close" and
// "2 open, 2 close" are different mistakes with different fixes, and a single "markers are
// broken" message sends the reader to look at the wrong half.
func findRegion(rel, content, name string) (regionBounds, error) {
	open, close := regionMarkers(name)
	lines := strings.Split(content, "\n")

	var opens, closes []int
	for i, ln := range lines {
		switch strings.TrimSpace(ln) {
		case open:
			opens = append(opens, i)
		case close:
			closes = append(closes, i)
		}
	}

	switch {
	case len(opens) == 0 && len(closes) == 0:
		return regionBounds{}, fmt.Errorf(
			"%s: no `%s` region — this file is marker-owned, so docsgen writes only between\n"+
				"  %s\n  %s\n"+
				"and it will not append the table, invent the markers, or fall back to owning the\n"+
				"whole file: every one of those silently destroys or duplicates the prose around them.\n"+
				"Add the two marker lines where the table belongs",
			rel, name, open, close)
	case len(opens) != 1 || len(closes) != 1:
		// Nesting is reported as nesting rather than folded into "unbalanced": a second opener
		// before the first closer means somebody put a region inside a region, and the fix
		// (delete the inner pair) is not the fix for a missing closer.
		if len(opens) > 1 && (len(closes) == 0 || opens[1] < closes[0]) {
			return regionBounds{}, fmt.Errorf(
				"%s: nested `%s` regions — a second `%s` opens at line %d before the first one "+
					"closes. A region inside a region has no single span to own, so docsgen refuses "+
					"to write rather than guess which pair is the real one",
				rel, name, open, opens[1]+1)
		}
		return regionBounds{}, fmt.Errorf(
			"%s: unbalanced `%s` markers — %d opening and %d closing. Exactly one of each is "+
				"required; docsgen refuses to write rather than guess at the span, because every "+
				"guess here overwrites prose that is not in any generator",
			rel, name, len(opens), len(closes))
	case closes[0] < opens[0]:
		return regionBounds{}, fmt.Errorf(
			"%s: `%s` markers are inverted — the closing marker is at line %d, above the opening "+
				"marker at line %d, so the region spans nothing and everything outside it would be "+
				"the content",
			rel, name, closes[0]+1, opens[0]+1)
	}
	return regionBounds{openLine: opens[0], closeLine: closes[0]}, nil
}

// spliceRegion returns content with the region's body replaced by `body`.
//
// Everything outside the two marker lines is copied through UNTOUCHED — no normalisation, no
// trailing-whitespace trim, nothing. That is the whole promise of marker ownership: the
// editorial prose in these files must be byte-identical across a regeneration, and the only way
// to guarantee that is to never look at it. `body` is normalised by the caller, which is also
// what keeps the generated table a prettier fixed point.
func spliceRegion(rel, content, name, body string) (string, error) {
	at, err := findRegion(rel, content, name)
	if err != nil {
		return "", err
	}
	lines := strings.Split(content, "\n")

	out := make([]string, 0, len(lines)+8)
	out = append(out, lines[:at.openLine+1]...)
	// The blank lines are emitted here rather than baked into `body` so that the renderer stays
	// bytes-in-bytes-out and the region's framing has exactly one definition.
	out = append(out, "")
	out = append(out, strings.Split(strings.TrimRight(body, "\n"), "\n")...)
	out = append(out, "")
	out = append(out, lines[at.closeLine:]...)
	return strings.Join(out, "\n"), nil
}
