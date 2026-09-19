package main

// The ruleset.
//
// Adding a rule means writing a func and registering it in Rules — that is the whole extension
// contract. Severity comes from config, never from code, so a repo can adopt in warn-only mode
// and promote rules as it cleans up. A linter that lands red on an existing codebase gets
// switched off; one that lands yellow and is promoted deliberately survives.

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

type Finding struct {
	Rule     string
	Severity string
	Path     string
	Message  string
}

type RuleFunc func(*Ctx) []Finding

var Rules = map[string]RuleFunc{
	"broken-links":       ruleBrokenLinks,
	"frontmatter-schema": ruleFrontmatterSchema,
	"covers-resolves":    ruleCoversResolves,
	"component-path":     ruleComponentPath,
	"component-shape":    ruleComponentShape,
	"colocation":         ruleColocation,
	"tickets-in-body":    ruleTicketsInBody,
	"taxonomy-structure": ruleTaxonomyStructure,
}

func find(ctx *Ctx, rule, path, msg string) Finding {
	return Finding{Rule: rule, Severity: ctx.Cfg.RuleFor(rule).Severity, Path: path, Message: msg}
}

// --- link integrity ---------------------------------------------------------------------

func ruleBrokenLinks(ctx *Ctx) []Finding {
	var out []Finding
	for _, d := range ctx.Docs {
		base := filepath.Dir(filepath.Join(ctx.Root, d.Path))
		for _, l := range d.Links {
			target := l
			if i := strings.Index(target, "#"); i >= 0 {
				target = target[:i]
			}
			if target == "" {
				continue
			}
			if _, err := os.Stat(filepath.Join(base, target)); err != nil {
				out = append(out, find(ctx, "broken-links", d.Path, "dead link -> "+l))
			}
		}
	}
	return out
}

// --- frontmatter schema -----------------------------------------------------------------

func ruleFrontmatterSchema(ctx *Ctx) []Finding {
	var out []Finding
	cfg := ctx.Cfg
	for _, d := range ctx.Docs {
		if d.FrontError != "" {
			out = append(out, find(ctx, "frontmatter-schema", d.Path, d.FrontError))
			continue
		}
		if d.Front == nil {
			continue // absent frontmatter is the migration worklist, not a schema error
		}
		for key, why := range cfg.BannedKeys {
			if _, bad := d.Front[key]; bad {
				out = append(out, find(ctx, "frontmatter-schema", d.Path, fmt.Sprintf("banned key `%s` — %s", key, why)))
			}
		}
		for _, req := range []string{"type", "status", "covers"} {
			if _, ok := d.Front[req]; !ok {
				out = append(out, find(ctx, "frontmatter-schema", d.Path, "missing required `"+req+"`"))
			}
		}
		checkEnum(ctx, &out, d, "type", cfg.DocTypes)
		checkEnum(ctx, &out, d, "status", cfg.Statuses)
		checkEnum(ctx, &out, d, "freshness", cfg.Freshness)

		if v, ok := d.Front["covers"]; ok {
			if _, clean := StringSlice(v); !clean {
				out = append(out, find(ctx, "frontmatter-schema", d.Path,
					"covers must be a block sequence of strings (prettier explodes flow sequences)"))
			}
		}
		if s, _ := d.Front["status"].(string); s == "superseded" {
			if v, ok := d.Front["superseded_by"].(string); !ok || v == "" {
				out = append(out, find(ctx, "frontmatter-schema", d.Path, "status: superseded requires superseded_by"))
			}
		}
		if len(cfg.KeyOrder) > 0 {
			if msg := keyOrderViolation(d.FrontKeys, cfg.KeyOrder); msg != "" {
				out = append(out, find(ctx, "frontmatter-schema", d.Path, msg))
			}
		}
	}
	return out
}

func checkEnum(ctx *Ctx, out *[]Finding, d Doc, key string, allowed []string) {
	if len(allowed) == 0 {
		return
	}
	v, ok := d.Front[key].(string)
	if !ok || v == "" {
		return
	}
	if !ctx.Cfg.Has(allowed, v) {
		*out = append(*out, find(ctx, "frontmatter-schema", d.Path,
			fmt.Sprintf("%s `%s` not in %v", key, v, allowed)))
	}
}

func keyOrderViolation(actual, want []string) string {
	rank := map[string]int{}
	for i, k := range want {
		rank[k] = i
	}
	last, lastKey := -1, ""
	for _, k := range actual {
		r, known := rank[k]
		if !known {
			continue
		}
		if r < last {
			return fmt.Sprintf("key `%s` should come before `%s` (canonical order: %v)", k, lastKey, want)
		}
		last, lastKey = r, k
	}
	return ""
}

// --- component scope --------------------------------------------------------------------

func ruleCoversResolves(ctx *Ctx) []Finding {
	var out []Finding
	for _, d := range ctx.Docs {
		if d.Front == nil {
			continue
		}
		covers, _ := StringSlice(d.Front["covers"])
		for _, tok := range covers {
			if tok == "cluster" || tok == "repo" || strings.HasPrefix(tok, "path:") {
				continue
			}
			if _, ok := ctx.BySlug[tok]; !ok {
				out = append(out, find(ctx, "covers-resolves", d.Path,
					fmt.Sprintf("`%s` matches no known component", tok)))
			}
		}
	}
	return out
}

// ruleComponentPath catches a component whose declared path does not exist — a Kustomization
// pointing at nothing. Flux reports this as a failed reconcile while the last-applied state
// keeps running, so the cluster looks healthy and nothing surfaces it.
func ruleComponentPath(ctx *Ctx) []Finding {
	var out []Finding
	for _, c := range ctx.Components {
		if _, err := os.Stat(filepath.Join(ctx.Root, c.Path)); err != nil {
			out = append(out, find(ctx, "component-path", c.Source,
				fmt.Sprintf("path `%s` does not exist on disk", c.Path)))
		}
	}
	return out
}

// ruleComponentShape reports a single component slug that contains many nested kustomizations.
//
// This is the directory-shape smell, made measurable. A grouping directory whose CHILDREN are
// each their own component is the CORRECT pattern — it is not reported here, because each child
// has its own slug. What is reported is one slug wrapping many deployable units, which makes
// "component = directory = doc home" untrue and forces the doc layer to special-case it.
func ruleComponentShape(ctx *Ctx) []Finding {
	var out []Finding
	const threshold = 3
	for _, c := range ctx.Components {
		if c.Nested > threshold {
			out = append(out, find(ctx, "component-shape", c.Path,
				fmt.Sprintf("one component slug (`%s`) wraps %d nested kustomizations — consider splitting", c.Slug, c.Nested)))
		}
	}
	return out
}

// --- placement --------------------------------------------------------------------------

func resolveCover(ctx *Ctx, tok string) (string, bool) {
	if tok == "cluster" || tok == "repo" {
		return "", false // reserved: forces cross-cutting
	}
	if p, ok := strings.CutPrefix(tok, "path:"); ok {
		return strings.TrimSuffix(p, "/"), true
	}
	if c, ok := ctx.BySlug[tok]; ok {
		return strings.TrimSuffix(c.Path, "/"), true
	}
	return "", false
}

func longestCommonAncestor(paths []string) string {
	if len(paths) == 0 {
		return ""
	}
	parts := strings.Split(paths[0], "/")
	for _, p := range paths[1:] {
		q := strings.Split(p, "/")
		i := 0
		for i < len(parts) && i < len(q) && parts[i] == q[i] {
			i++
		}
		parts = parts[:i]
	}
	return strings.Join(parts, "/")
}

// ExpectedLocation computes where a doc SHOULD live. Computed, never declared — a declared
// location invites disagreement with reality, which is the whole failure mode being removed.
//
// LCA rather than a count of slugs: a README covering four sibling components is correctly
// colocated at their shared parent, while a count would wrongly exile it to docs/.
func ExpectedLocation(ctx *Ctx, covers []string) string {
	for _, c := range covers {
		if c == "cluster" || c == "repo" {
			return "docs/"
		}
	}
	var resolved []string
	for _, c := range covers {
		if p, ok := resolveCover(ctx, c); ok && p != "" {
			resolved = append(resolved, p)
		}
	}
	if len(resolved) == 0 {
		return "docs/"
	}
	lca := longestCommonAncestor(resolved)
	if lca == "" || ctx.Cfg.Has(ctx.Cfg.GroupingRoots, lca) {
		return "docs/"
	}
	return lca
}

func ruleColocation(ctx *Ctx) []Finding {
	var out []Finding
	for _, d := range ctx.Docs {
		if d.Front == nil {
			continue
		}
		if pin, ok := d.Front["pinned"].(string); ok && pin != "" {
			continue // suppressed WITH a recorded reason, which is the migration mechanism
		}
		covers, _ := StringSlice(d.Front["covers"])
		if len(covers) == 0 {
			continue
		}
		want := ExpectedLocation(ctx, covers)
		here := filepath.Dir(d.Path)
		if want == "docs/" {
			if !strings.HasPrefix(d.Path, "docs/") {
				out = append(out, find(ctx, "colocation", d.Path, "cross-cutting scope — belongs under docs/"))
			}
			continue
		}
		if !strings.HasPrefix(here, want) {
			out = append(out, find(ctx, "colocation", d.Path, "should colocate at "+want+"/"))
		}
	}
	return out
}

func ruleTicketsInBody(ctx *Ctx) []Finding {
	var out []Finding
	for _, d := range ctx.Docs {
		if d.Front == nil {
			continue
		}
		tickets, _ := StringSlice(d.Front["tickets"])
		for _, t := range tickets {
			// Doc.Body, never Doc.Text. Text still contains the frontmatter block these ticket
			// IDs were just parsed OUT of, so scanning it made the check a tautology that could
			// never fire — a rule that silently never runs is worse than an absent one, because
			// the report reads as a clean pass.
			if !strings.Contains(d.Body, t) {
				out = append(out, find(ctx, "tickets-in-body", d.Path, t+" in frontmatter but not in body"))
			}
		}
	}
	return out
}

// --- taxonomy structure -----------------------------------------------------------------
//
// Without these, `type:` is a decorative label. These assert that a doc actually IS what it
// declares. Day-one failures on pre-existing docs are expected — they are the migration
// worklist, which is why severity defaults to warn.

var orderedStepRe = regexp.MustCompile(`(?m)^\s*1\.\s`)
var regenRe = regexp.MustCompile(`(?i)regenerat|generated by|how this was`)

// Every scan below reads d.Body, never d.Text.
//
// d.Text still contains the frontmatter block, and frontmatter is metadata ABOUT a doc rather
// than content OF it — so a `blurb:` mentioning "## TL;DR", or a tickets list, satisfied these
// checks for a doc whose body had none of them. A runbook with an empty body and the right words
// in its frontmatter produced zero findings. This is the same defect that made ruleTicketsInBody
// a tautology; it was fixed there first and these four sites were missed, which is the actual
// lesson: when a field-choice bug is found, sweep every sibling that reads the same field.
func ruleTaxonomyStructure(ctx *Ctx) []Finding {
	var out []Finding
	for _, d := range ctx.Docs {
		if d.Front == nil {
			continue
		}
		dtype, _ := d.Front["type"].(string)
		if dtype == "" {
			continue
		}
		if d.H1 == "" {
			out = append(out, find(ctx, "taxonomy-structure", d.Path, "no H1 — every doc leads with one"))
		}
		for _, heading := range ctx.Cfg.TypeRequires[dtype] {
			if !strings.Contains(strings.ToLower(d.Body), strings.ToLower(heading)) {
				out = append(out, find(ctx, "taxonomy-structure", d.Path,
					fmt.Sprintf("type `%s` expects a `%s` section", dtype, heading)))
			}
		}
		switch dtype {
		case "runbook":
			if !orderedStepRe.MatchString(d.Body) {
				out = append(out, find(ctx, "taxonomy-structure", d.Path, "runbook has no ordered procedure"))
			}
		case "reference":
			if !regenRe.MatchString(d.Body) {
				out = append(out, find(ctx, "taxonomy-structure", d.Path, "reference should state how it is regenerated"))
			}
		case "nav":
			// A nav doc carrying substantial prose is misfiled, and regenerating it as a link
			// table would destroy that prose. Catching this BEFORE the generator runs is the
			// entire reason this check exists.
			if w := proseWords(d.Body); w > 250 {
				out = append(out, find(ctx, "taxonomy-structure", d.Path,
					fmt.Sprintf("type `nav` but carries ~%d words of prose — misfiled?", w)))
			}
		}
		if ctx.Cfg.RequiredFooter != "" && dtype != "nav" && !strings.Contains(d.Body, ctx.Cfg.RequiredFooter) {
			out = append(out, find(ctx, "taxonomy-structure", d.Path, "missing `"+ctx.Cfg.RequiredFooter+"` footer"))
		}
	}
	return out
}

var tableRowRe = regexp.MustCompile(`(?m)^\s*\|.*\|\s*$`)
var headingRe = regexp.MustCompile(`(?m)^#+ .*$`)

func proseWords(body string) int {
	s := tableRowRe.ReplaceAllString(body, "")
	s = headingRe.ReplaceAllString(s, "")
	s = StripCode(s)
	return len(strings.Fields(s))
}

// Run executes the enabled rules in a stable order.
func Run(ctx *Ctx, only string) []Finding {
	names := make([]string, 0, len(Rules))
	for n := range Rules {
		names = append(names, n)
	}
	sort.Strings(names)

	var all []Finding
	for _, n := range names {
		if only != "" && n != only {
			continue
		}
		if !ctx.Cfg.RuleFor(n).Enabled {
			continue
		}
		all = append(all, Rules[n](ctx)...)
	}
	return all
}
