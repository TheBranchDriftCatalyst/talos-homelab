package main

// Markdown parsing primitives and the data model. Repo-agnostic by construction.

import (
	"regexp"
	"strings"

	"gopkg.in/yaml.v3"
)

type Doc struct {
	Path       string
	Text       string
	Body       string
	Front      map[string]any
	FrontKeys  []string // source order, so key-order can be checked
	FrontError string
	H1         string
	Links      []string
}

type Component struct {
	Slug      string
	Name      string // metadata.name — drifts from Slug in this repo, so both are kept
	Path      string
	DependsOn []string
	Suspend   bool
	Source    string
	Nested    int // nested kustomizations under Path — high count means one slug hides many units
}

var (
	linkRe   = regexp.MustCompile(`\[[^\]]*\]\(([^)\s]+)`)
	fenceRe  = regexp.MustCompile("(?s)```.*?```")
	tildeRe  = regexp.MustCompile("(?s)~~~.*?~~~")
	inlineRe = regexp.MustCompile("`[^`\n]*`")
	orderRe  = regexp.MustCompile(`(?m)^([A-Za-z_][A-Za-z0-9_]*):`)
)

// SplitFrontMatter returns frontmatter, source key order, error, and body.
// Absent frontmatter is not an error.
//
// Verified against this repo's pinned markdownlint 0.41.1: a --- block before the H1 does NOT
// trip MD041, because front matter is stripped before parsing and the H1 becomes token #1. The
// corollary lives in rules.go — a `title:` key inside it is banned, because markdownlint treats
// that as the document title and then flags the real H1 as an MD025 duplicate.
func SplitFrontMatter(text string) (map[string]any, []string, string, string) {
	if !strings.HasPrefix(text, "---\n") {
		return nil, nil, "", text
	}
	end := strings.Index(text[4:], "\n---")
	if end == -1 {
		return nil, nil, "unterminated frontmatter block", text
	}
	raw := text[4 : 4+end]
	body := strings.TrimLeft(text[4+end+4:], "\n")

	var data map[string]any
	if err := yaml.Unmarshal([]byte(raw), &data); err != nil {
		return nil, nil, "invalid YAML in frontmatter: " + oneLine(err.Error()), body
	}
	var order []string
	for _, m := range orderRe.FindAllStringSubmatch(raw, -1) {
		order = append(order, m[1])
	}
	if data == nil {
		data = map[string]any{}
	}
	return data, order, "", body
}

// StripCode removes fenced blocks and inline spans so links inside examples are never linted.
func StripCode(s string) string {
	s = fenceRe.ReplaceAllString(s, "")
	s = tildeRe.ReplaceAllString(s, "")
	return inlineRe.ReplaceAllString(s, "")
}

func ExtractLinks(body string) []string {
	var out []string
	for _, m := range linkRe.FindAllStringSubmatch(StripCode(body), -1) {
		t := m[1]
		if strings.HasPrefix(t, "http://") || strings.HasPrefix(t, "https://") ||
			strings.HasPrefix(t, "mailto:") || strings.HasPrefix(t, "#") || strings.HasPrefix(t, "<") {
			continue
		}
		out = append(out, t)
	}
	return out
}

func FirstH1(body string) string {
	for _, ln := range strings.Split(body, "\n") {
		if strings.HasPrefix(ln, "# ") {
			return strings.TrimSpace(ln[2:])
		}
	}
	return ""
}

func MakeDoc(path, text string) Doc {
	front, order, ferr, body := SplitFrontMatter(text)
	return Doc{
		Path:       path,
		Text:       text,
		Body:       body,
		Front:      front,
		FrontKeys:  order,
		FrontError: ferr,
		H1:         FirstH1(body),
		Links:      ExtractLinks(body),
	}
}

// StringSlice coerces a YAML value to []string, tolerating a scalar. Returns ok=false when the
// value is present but is neither — which the schema rule reports rather than silently ignoring.
func StringSlice(v any) ([]string, bool) {
	switch t := v.(type) {
	case nil:
		return nil, true
	case string:
		return []string{t}, false
	case []any:
		out := make([]string, 0, len(t))
		for _, e := range t {
			s, ok := e.(string)
			if !ok {
				return out, false
			}
			out = append(out, s)
		}
		return out, true
	}
	return nil, false
}

func oneLine(s string) string {
	return strings.Join(strings.Fields(s), " ")
}
