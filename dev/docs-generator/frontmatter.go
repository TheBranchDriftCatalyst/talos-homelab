package main

// The frontmatter writer for generated artifacts.
//
// NOT yaml.Marshal. Three properties this file guarantees are ones the library does not:
//
//  1. KEY ORDER IS cfg.KeyOrder. yaml.Marshal on a map sorts keys alphabetically, which is a
//     different order from every repo's declared canonical order — so the generator would emit
//     a file its own `frontmatter-schema` rule reports as out of order.
//
//  2. SEQUENCES ARE BLOCK SEQUENCES. yaml.Marshal is free to emit `covers: [cluster]`, and
//     prettier explodes a flow sequence into a block one. The generated file would then stop
//     being a prettier fixed point on the first unrelated format run, and `docsgen check` would
//     report drift it did not cause. The `frontmatter-schema` rule says the same thing in
//     prose; this is the half that makes the generator obey it.
//
//  3. THE OUTPUT IS BYTE-STABLE ACROSS Go AND yaml.v3 VERSIONS. A generated artifact is
//     compared byte-for-byte by `docsgen check`; a library that changes its line-wrapping
//     heuristic in a point release would turn every artifact in the repo into drift.
//
// Scalars are emitted plain wherever YAML allows it and double-quoted otherwise. The test for
// "wherever YAML allows it" is deliberately conservative: over-quoting is ugly, under-quoting
// changes what the value parses back as, and the artifact is re-parsed by the pre-write gate.

import (
	"fmt"
	"sort"
	"strconv"
	"strings"
)

// frontKeyOrder returns front's keys in emission order: the keys named in cfg.KeyOrder first, in
// that order, then everything else sorted.
//
// Sorted rather than "whatever order the map yielded" for the obvious reason — a map iteration
// is randomised per run, and a generated file whose key order moves between runs is drift the
// generator invented. Unknown keys go LAST because keyOrderViolation only ranks the keys it
// knows: placing an unranked key between two ranked ones would be invisible to the rule today
// and a violation the moment somebody adds that key to key_order.
func frontKeyOrder(cfg *Config, front map[string]any) []string {
	rank := make(map[string]int, len(cfg.KeyOrder))
	for i, k := range cfg.KeyOrder {
		rank[k] = i
	}
	var known, unknown []string
	for k := range front {
		if _, ok := rank[k]; ok {
			known = append(known, k)
			continue
		}
		unknown = append(unknown, k)
	}
	sort.Slice(known, func(i, j int) bool { return rank[known[i]] < rank[known[j]] })
	sort.Strings(unknown)
	return append(known, unknown...)
}

// renderFrontMatter renders front as a `---` delimited block, including both delimiters and the
// trailing newline.
//
// It returns an error rather than a best-effort rendering for any value it cannot write
// deterministically. The caller turns that into a config error naming the key: a frontmatter
// block that silently dropped a key would produce an artifact missing a field its own schema
// rule requires, which is the defect this whole file exists to remove.
func renderFrontMatter(cfg *Config, front map[string]any) (string, error) {
	var b strings.Builder
	b.WriteString("---\n")
	for _, k := range frontKeyOrder(cfg, front) {
		items, isSeq, err := yamlSequence(front[k])
		if err != nil {
			return "", fmt.Errorf("`%s`: %w", k, err)
		}
		if isSeq {
			// An empty sequence has no block form at all — `key:` alone parses as null and
			// `key: []` is the flow form prettier explodes. Neither is writable, so say so.
			if len(items) == 0 {
				return "", fmt.Errorf("`%s`: an empty sequence has no block form; omit the key instead", k)
			}
			b.WriteString(k + ":\n")
			for _, it := range items {
				b.WriteString("  - " + it + "\n")
			}
			continue
		}
		s, err := yamlScalar(front[k])
		if err != nil {
			return "", fmt.Errorf("`%s`: %w", k, err)
		}
		b.WriteString(k + ": " + s + "\n")
	}
	b.WriteString("---\n")
	return b.String(), nil
}

// yamlSequence renders a sequence value's elements, or reports that the value is not a sequence.
// Both []any (what yaml.v3 hands back) and []string (what Go-built configs use in tests) count.
func yamlSequence(v any) ([]string, bool, error) {
	var raw []any
	switch t := v.(type) {
	case []any:
		raw = t
	case []string:
		for _, e := range t {
			raw = append(raw, e)
		}
	default:
		return nil, false, nil
	}
	out := make([]string, 0, len(raw))
	for _, e := range raw {
		s, err := yamlScalar(e)
		if err != nil {
			return nil, true, err
		}
		out = append(out, s)
	}
	return out, true, nil
}

// yamlScalar renders one scalar. A nested map, a nested sequence or a nil is refused rather than
// guessed at: each has several plausible renderings and the wrong one is silent.
func yamlScalar(v any) (string, error) {
	switch t := v.(type) {
	case string:
		return yamlString(t), nil
	case bool:
		return strconv.FormatBool(t), nil
	case int:
		return strconv.Itoa(t), nil
	case int64:
		return strconv.FormatInt(t, 10), nil
	case float64:
		return strconv.FormatFloat(t, 'g', -1, 64), nil
	case nil:
		return "", fmt.Errorf("has no value; a null frontmatter key is indistinguishable from an absent one")
	}
	return "", fmt.Errorf("value of type %T cannot be written as a frontmatter scalar", v)
}

func yamlString(s string) string {
	if needsQuote(s) {
		// Go's quoting and YAML's double-quoted style agree on the escapes that matter here
		// (\" \\ \n \t \uXXXX) and both leave printable non-ASCII — em dashes, accents — alone.
		return strconv.Quote(s)
	}
	return s
}

// yamlIndicators are the characters that mean something OTHER than themselves when they open a
// plain scalar. A value starting with one of them has to be quoted or it parses as a different
// node kind entirely.
const yamlIndicators = "-?:,[]{}#&*!|>'\"%@`"

func needsQuote(s string) bool {
	if s == "" {
		return true
	}
	// Leading or trailing whitespace does not survive a plain scalar round trip.
	if strings.TrimSpace(s) != s {
		return true
	}
	if strings.ContainsAny(s, "\n\r\t") {
		return true
	}
	// A multi-byte first rune is never an indicator, and indexing the byte is safe because
	// every indicator is ASCII.
	if strings.IndexByte(yamlIndicators, s[0]) >= 0 {
		return true
	}
	// `: ` opens a mapping and ` #` opens a comment, anywhere in the line. A trailing colon is
	// the same problem at end of line.
	if strings.Contains(s, ": ") || strings.Contains(s, " #") || strings.HasSuffix(s, ":") {
		return true
	}
	// Anything YAML would parse back as a non-string. Quoting these is the difference between
	// `status: no` meaning the word and meaning false.
	switch strings.ToLower(s) {
	case "true", "false", "yes", "no", "on", "off", "null", "~", "y", "n":
		return true
	}
	if _, err := strconv.ParseFloat(s, 64); err == nil {
		return true
	}
	return false
}
