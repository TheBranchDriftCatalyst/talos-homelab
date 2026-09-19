package main

// The ruleset.
//
// Adding a rule means writing a func and registering it in Rules with the facts it needs — that
// is the whole extension contract. Severity comes from config, never from code, so a repo can
// adopt in warn-only mode and promote rules as it cleans up. A linter that lands red on an
// existing codebase gets switched off; one that lands yellow and is promoted deliberately
// survives.
//
// The facts are the other half of that: a rule declares what it MEASURES, the repo's component
// strategy declares what it can SUPPLY, and a rule whose measurement is unavailable is reported
// as skipped rather than run against a number that is zero for reasons having nothing to do
// with the repository. Getting this wrong is not hypothetical — `component-shape` and
// `component-path` passed cleanly under `components.kind: dirs` for their whole existence,
// because neither can fire there at all.

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
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

// RuleSkip is one rule that was enabled, selected, and then NOT RUN — because the repo's
// component strategy cannot supply a fact the rule measures.
//
// The name is RuleSkip rather than the obvious `Skip` for one compiler reason: the unit specs
// are IN-PACKAGE (package main) and dot-import Ginkgo, which exports `Skip`. A package-level
// `Skip` here collides with that file-level import in every one of those files and the package
// stops compiling. The field names and the rendered output are exactly what they would be
// either way; only the type's spelling moved.
//
// A skip is part of the lint ANSWER, not a diagnostic about it. `component-shape` counts nested
// kustomizations; under `components.kind: dirs` that count is structurally always zero, so the
// rule found nothing and reported a clean pass in a repo it had never been able to examine. A
// rule that silently never fires is worse than an absent one, because the report reads as
// coverage. Missing is carried alongside the rendered Why so a caller can act on the facts
// rather than re-parse the sentence.
type RuleSkip struct {
	Rule    string
	Missing []Fact
	Why     string
}

// Check is one registered rule: what it needs, and what it does.
//
// Requires is the DEMAND side of the fact vocabulary, and it has to exist for Provides() to be
// worth anything: a capability nobody consults changes no behaviour. The alternative — a rule
// reading `cfg.Components.Kind` and returning early — is what config.go forbids by name, and
// for a good reason: it puts the knowledge of which strategies exist inside every rule that
// cares, so adding a strategy means auditing the ruleset instead of adding one file.
//
// Requires names the fact a rule MEASURES, never every field it happens to touch. Every rule
// reads Component.Path; only `component-path` treats that path as a DECLARATION that might be
// wrong, which is the fact `dirs` cannot supply.
type Check struct {
	Requires []Fact
	Fn       RuleFunc
}

var Rules = map[string]Check{
	"broken-links":       {Fn: ruleBrokenLinks},
	"frontmatter-schema": {Fn: ruleFrontmatterSchema},
	"covers-resolves":    {Fn: ruleCoversResolves},
	"component-path":     {Requires: []Fact{FactPathIsDeclared}, Fn: ruleComponentPath},
	"component-shape":    {Requires: []Fact{FactSubUnits}, Fn: ruleComponentShape},
	"colocation":         {Fn: ruleColocation},
	"tickets-in-body":    {Fn: ruleTicketsInBody},
	"tickets-exist":      {Fn: ruleTicketsExist},
	"taxonomy-structure": {Fn: ruleTaxonomyStructure},
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
			if tok == "cluster" || tok == "repo" {
				continue // reserved scope tokens; they name no entity by design
			}
			// A `path:` token was previously trusted WITHOUT any existence check, which made it
			// the one unvalidated reference kind in the vocabulary — and resolveCover returns it
			// as resolved, so an unchecked path silently fed BOTH the colocation verdict and the
			// staleness subject. A typo produced a wrong doc home and a staleness comparison
			// against a directory that cannot exist, so the doc could never be reported stale.
			// One unchecked reference, three silently wrong answers.
			if rel, ok := strings.CutPrefix(tok, "path:"); ok {
				rel = strings.TrimSuffix(rel, "/")
				if rel == "" {
					out = append(out, find(ctx, "covers-resolves", d.Path, "`path:` with no path"))
					continue
				}
				// Reject traversal before touching the filesystem: a cover must name something
				// INSIDE the repo, and `path:../../../etc/passwd` resolving cleanly would make
				// the colocation target a directory outside the tree entirely.
				clean := filepath.Clean(rel)
				if clean == ".." || strings.HasPrefix(clean, "../") || filepath.IsAbs(clean) {
					out = append(out, find(ctx, "covers-resolves", d.Path,
						fmt.Sprintf("`%s` escapes the repository", tok)))
					continue
				}
				if _, err := os.Stat(filepath.Join(ctx.Root, clean)); err != nil {
					out = append(out, find(ctx, "covers-resolves", d.Path,
						fmt.Sprintf("`%s` does not exist on disk", tok)))
				}
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
	// The documentation root is config, not the literal `docs/`. A repo whose prose lives in
	// handbook/ or notes/ was previously told by this rule that every cross-cutting doc it owns
	// is misplaced, and told by the generator to write its artifacts into a docs/ tree it does
	// not have. Those were the same hardcoded string.
	//
	// The trailing slash is load-bearing: it is how ruleColocation tells "the docs root" apart
	// from an LCA that happens to spell the same directory.
	docsRoot := ctx.Cfg.DocsRootOr() + "/"
	for _, c := range covers {
		if c == "cluster" || c == "repo" {
			return docsRoot
		}
	}
	var resolved []string
	for _, c := range covers {
		if p, ok := resolveCover(ctx, c); ok && p != "" {
			resolved = append(resolved, p)
		}
	}
	if len(resolved) == 0 {
		return docsRoot
	}
	lca := longestCommonAncestor(resolved)
	if lca == "" || ctx.Cfg.Has(ctx.Cfg.GroupingRoots, lca) {
		return docsRoot
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
		if docsRoot := ctx.Cfg.DocsRootOr() + "/"; want == docsRoot {
			if !strings.HasPrefix(d.Path, docsRoot) {
				out = append(out, find(ctx, "colocation", d.Path,
					"cross-cutting scope — belongs under "+docsRoot))
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

// ruleTicketsExist checks that a referenced ticket IS one, not merely that it looks like one.
//
// This is the third instance of a single class in this tool: a reference validated for SHAPE but
// never for EXISTENCE. Bare `covers:` slugs were checked against the component registry from the
// start; `path:` covers were trusted unconditionally until they were caught feeding a wrong
// colocation verdict AND an impossible staleness comparison; ticket IDs are the same hole again.
// A regex cannot tell a real ticket from a typo of one.
//
// Closed tickets are VALID. A doc citing completed work is correct history, not drift — this
// checks existence, never status.
//
// When the backend is unavailable the rule SKIPS AND SAYS SO. It must never hard-fail a repo
// that has no tracker installed (the tool is meant to be portable), and it must never pass
// silently, because then nobody learns the check stopped running.
func ruleTicketsExist(ctx *Ctx) []Finding {
	cfg := ctx.Cfg.Tickets
	if cfg.Backend == "" {
		return nil // not configured: not a skip, the repo opted out
	}
	known, err := knownTickets(ctx)
	if err != nil {
		return []Finding{find(ctx, "tickets-exist", ctx.Cfg.Components.Path,
			fmt.Sprintf("SKIPPED — cannot reach the %q ticket backend (%v); ticket IDs were NOT verified",
				cfg.Backend, err))}
	}

	var pat *regexp.Regexp
	if ctx.Cfg.TicketPattern != "" {
		pat, _ = regexp.Compile(ctx.Cfg.TicketPattern)
	}

	var out []Finding
	for _, d := range ctx.Docs {
		if d.Front == nil {
			continue
		}
		tickets, _ := StringSlice(d.Front["tickets"])
		for _, id := range tickets {
			// Only IDs this repo claims to own. A doc may legitimately cite a ticket from
			// another project, and flagging those would train everyone to ignore the rule.
			if pat != nil && !pat.MatchString(id) {
				continue
			}
			if !known[id] {
				out = append(out, find(ctx, "tickets-exist", d.Path,
					fmt.Sprintf("`%s` matches the ticket pattern but no such ticket exists", id)))
			}
		}
	}
	return out
}

// knownTickets returns every ticket id the backend knows, closed ones included, in ONE call.
func knownTickets(ctx *Ctx) (map[string]bool, error) {
	bin := ctx.Cfg.Tickets.Command
	if bin == "" {
		bin = "bd"
	}
	cmd := exec.Command(bin, "list", "--status=all", "--json")
	cmd.Dir = ctx.Root
	raw, err := cmd.Output()
	if err != nil {
		return nil, err
	}
	var rows []struct {
		ID string `json:"id"`
	}
	if err := json.Unmarshal(raw, &rows); err != nil {
		return nil, fmt.Errorf("unparseable backend output: %w", err)
	}
	if len(rows) == 0 {
		return nil, fmt.Errorf("backend returned no tickets at all")
	}
	known := make(map[string]bool, len(rows))
	for _, x := range rows {
		known[x.ID] = true
	}
	return known, nil
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
// than content OF it — so a `bluf:` mentioning "## TL;DR", or a tickets list, satisfied these
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

// Run executes the enabled rules in a stable order, and returns the ones that could not run
// alongside the findings.
//
// TWO RETURN VALUES, not one. A rule whose facts are unavailable contributes nothing to
// `[]Finding`, which is indistinguishable from a rule that ran and found nothing — so folding
// the two together would leave the caller unable to tell coverage from silence no matter how
// carefully it printed the result. The skip has to survive as far as the report.
//
// The order of the three gates is the order of intent. `only` is the operator saying which rule
// they want; `Enabled` is the repo saying which rules it has adopted; Requires is the tool
// saying which of those it is actually able to answer. A rule the operator did not select and a
// rule the repo switched off are both DELIBERATE absences and are not reported — only the third
// case is a surprise.
func Run(ctx *Ctx, only string) ([]Finding, []RuleSkip) {
	names := make([]string, 0, len(Rules))
	for n := range Rules {
		names = append(names, n)
	}
	sort.Strings(names)

	var all []Finding
	var skipped []RuleSkip
	for _, n := range names {
		if only != "" && n != only {
			continue
		}
		if !ctx.Cfg.RuleFor(n).Enabled {
			continue
		}
		check := Rules[n]
		// Missing() sorts, so the message is stable between runs; names is already sorted, so
		// the skips come out in rule order without a second sort.
		if missing := ctx.Facts.Missing(check.Requires); len(missing) > 0 {
			skipped = append(skipped, RuleSkip{Rule: n, Missing: missing, Why: skipReason(ctx.Cfg, missing)})
			continue
		}
		all = append(all, check.Fn(ctx)...)
	}
	return all, skipped
}

// skipReason renders the one sentence a reader needs: which measurement is unavailable, and
// whose fault that is.
//
// It names `components.kind` explicitly because the remedy is a config decision, not a code one
// — the reader's next move is either to accept that this repo shape cannot answer the question
// or to change how components are enumerated. "component-shape was skipped" on its own sends
// them looking for a bug.
func skipReason(cfg *Config, missing []Fact) string {
	names := make([]string, len(missing))
	for i, f := range missing {
		names[i] = string(f)
	}
	return fmt.Sprintf("needs %s, which components.kind `%s` does not report",
		strings.Join(names, ", "), cfg.Components.Kind)
}
