package navmodel

// Python semantics that the parity target depends on.
//
// build_nav.py reaches for four Python builtins whose behaviour is NOT what the obvious Go
// equivalent does. Each one shows up in the manifest bytes, so each one is reproduced here
// rather than approximated:
//
//	str.title()  ->  pyTitle      strings.Title is deprecated AND wrong here (it only
//	                              uppercases after spaces; Python uppercases after every
//	                              non-letter, so "grafana-main".title() == "Grafana-Main"
//	                              and strconv-flavoured guesses give "Grafana-main").
//	int(str)     ->  pyInt        accepts surrounding whitespace, a leading sign, and
//	                              PEP-515 underscores; rejects "50.0". strconv.Atoi
//	                              rejects " 50" and accepts nothing with underscores.
//	float(str)   ->  pyFloat64    accepts "inf"/"nan"/"Infinity" spellings that
//	                              _as_intensity then rejects — so the spelling has to
//	                              parse before it can be refused, or `intensity: inf`
//	                              would be dropped with the wrong log line.
//	repr(str)    ->  pyRepr       the refusal log lines are asserted by
//	                              tests/nav/test_build_nav.py; Go's %q uses double quotes
//	                              where Python uses single.

import (
	"math"
	"strconv"
	"strings"
	"unicode"
)

// pyTitle reproduces Python's str.title(): the first cased character of every run of letters
// is uppercased, the rest lowercased. Word boundaries are "any non-letter", which is why
// "grafana-main" becomes "Grafana-Main" and not "Grafana-main".
func pyTitle(s string) string {
	var b strings.Builder
	b.Grow(len(s))
	prevIsCased := false
	for _, r := range s {
		switch {
		case !unicode.IsLetter(r):
			b.WriteRune(r)
			prevIsCased = false
		case prevIsCased:
			b.WriteRune(unicode.ToLower(r))
		default:
			b.WriteRune(unicode.ToUpper(r))
			prevIsCased = true
		}
	}
	return b.String()
}

// pyInt reproduces int(s) for a base-10 string: optional surrounding whitespace, optional
// sign, then digits optionally separated by single underscores. ok=false is Python's
// ValueError, which build_nav.py catches.
func pyInt(s string) (int, bool) {
	t := strings.TrimSpace(s)
	if t == "" {
		return 0, false
	}
	sign := ""
	if t[0] == '+' || t[0] == '-' {
		if t[0] == '-' {
			sign = "-"
		}
		t = t[1:]
	}
	// Underscores must sit between digits: "1_0" is 10, but "_1", "1_" and "1__0" are all
	// ValueError in Python.
	if strings.Contains(t, "_") {
		parts := strings.Split(t, "_")
		for _, p := range parts {
			if p == "" {
				return 0, false
			}
		}
		t = strings.Join(parts, "")
	}
	if t == "" {
		return 0, false
	}
	for _, r := range t {
		if r < '0' || r > '9' {
			return 0, false
		}
	}
	n, err := strconv.Atoi(sign + t)
	if err != nil {
		return 0, false
	}
	return n, true
}

// pyFloat64 reproduces float(s). It must ACCEPT the infinity and NaN spellings so that
// _as_intensity can reject them for the documented reason ("layer 45 multiplies translate
// distances by it"); refusing them at parse time instead would log "ignoring" either way but
// would diverge the moment that distinction is given different handling.
func pyFloat64(s string) (float64, bool) {
	t := strings.TrimSpace(s)
	if t == "" {
		return 0, false
	}
	// strconv.ParseFloat already accepts Python's "inf", "infinity", "nan" spellings
	// case-insensitively with an optional sign, and rejects underscore-free junk the same
	// way. It additionally accepts hex floats ("0x1p-2"), which Python's float() rejects.
	if strings.Contains(strings.ToLower(t), "x") {
		return 0, false
	}
	// Python allows PEP-515 underscores in float literals too.
	if strings.Contains(t, "_") {
		parts := strings.Split(t, "_")
		for _, p := range parts {
			if p == "" {
				return 0, false
			}
		}
		t = strings.Join(parts, "")
	}
	f, err := strconv.ParseFloat(t, 64)
	if err != nil {
		return 0, false
	}
	return f, true
}

// pyRepr renders a Go string the way Python's repr() would, because the refusal log lines are
// part of the contract: tests/nav/test_build_nav.py asserts on stderr content, and an operator
// grepping the sidecar log for a quoted annotation value should find the same shape.
func pyRepr(s string) string {
	quote := byte('\'')
	if strings.Contains(s, "'") && !strings.Contains(s, `"`) {
		quote = '"'
	}
	var b strings.Builder
	b.WriteByte(quote)
	for _, r := range s {
		switch r {
		case '\\':
			b.WriteString(`\\`)
		case '\n':
			b.WriteString(`\n`)
		case '\r':
			b.WriteString(`\r`)
		case '\t':
			b.WriteString(`\t`)
		case rune(quote):
			b.WriteByte('\\')
			b.WriteByte(quote)
		default:
			if r < 0x20 || r == 0x7f {
				b.WriteString(`\x`)
				const digits = "0123456789abcdef"
				b.WriteByte(digits[(r>>4)&0xf])
				b.WriteByte(digits[r&0xf])
			} else {
				b.WriteRune(r)
			}
		}
	}
	b.WriteByte(quote)
	return b.String()
}

// isFiniteNonNegative is _as_intensity's rejection test, split out so the reason reads.
func isFiniteNonNegative(f float64) bool {
	return !math.IsNaN(f) && !math.IsInf(f, 0) && f >= 0
}
