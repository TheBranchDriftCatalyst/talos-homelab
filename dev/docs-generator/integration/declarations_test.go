package integration_test

// Declared-vs-actual reconciliation: the spec that makes the fixtures' own convention executable.
//
// THE DEFECT CLASS THIS CLOSES. Every sample doc is written to trip exactly one rule and says so
// in its own prose. docsgen's rules are substring searches over the document body, so a fixture
// that NAMES the thing it is supposed to omit silently CURES ITSELF: the rule falls silent, the
// fixture still reads as intentional, and the golden gets regenerated against the silence. It
// happened three times —
//
//  1. flux-cluster/handbook/getting-started/missing-footer.md named its own footer heading;
//  2. flux-cluster/handbook/process/ticket-drift.md named the very ticket it must omit;
//  3. plain-dirs/notes/no-footer.md carried the literal footer heading inside backticks, which
//     cost `taxonomy-structure` its ONLY coverage in that sample — and an UNDECLARED
//     `tickets-in-body` finding on the same path kept it looking covered in the golden.
//
// Nothing enforced the convention, so a fourth was a matter of time.
//
// THE FORMAT, AND WHY IT CANNOT CURE WHAT IT DECLARES. A declaration is a line of its own:
//
//	EXPECT: <rule-id>              # this file trips <rule-id> once
//	EXPECT: <rule-id> x<N>         # …N times
//	EXPECT: <rule-id> on <path>    # …attributed to <path> rather than to this file
//	EXPECT: none                   # this file produces no findings at all
//
// It names the RULE ID and nothing else. It never contains the literal the rule searches for —
// no footer heading, no ticket id, no link target — because the grammar has nowhere to put one:
// anything after the rule id other than `x<N>` / `on <path>` is a hard parse failure, and the
// spec below rejects the file. Explanatory prose still belongs in the fixture, on its OWN lines,
// where it is not part of the declaration. The rule ids themselves (`taxonomy-structure`,
// `tickets-in-body`, …) are inert: no rule searches for its own name, and no rule id is a
// substring of any trigger text.
//
// That argument is not left as an argument. "declarations are inert" below DELETES every
// declaration line from a built fixture, re-lints it, and requires byte-identical findings — so
// if a declaration ever starts satisfying (or provoking) a rule, that spec goes red.
//
// THE FOUR ASSERTIONS. Per sample, with no per-sample code:
//
//   - every declaration parses, names a rule the sample's config knows, and carries no prose;
//   - every .md in the sample declares something, `EXPECT: none` included;
//   - the findings docsgen reports and the findings the fixtures declare are the SAME multiset,
//     keyed on (path, rule) — "declared but missing" catches occurrences 1-3, and "found but
//     undeclared" catches the accidental finding that masked occurrence 3;
//   - a file declaring `EXPECT: none` produces nothing.

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	"gopkg.in/yaml.v3"
)

// --- the declaration grammar ------------------------------------------------------------

const (
	declMarker = "EXPECT:"
	declNone   = "none"

	// declLegacy is the prose convention this file replaces. It is banned outright rather than
	// tolerated alongside: two conventions means the unenforced one keeps getting used, which is
	// how the defect class survived three times.
	declLegacy = "EXPECTED FINDING"
)

// declBodyRe is deliberately total. A declaration is a rule id, an optional count and an
// optional subject path — there is NO free-text slot, because free text beside a rule name is
// exactly where the triggering literal creeps back in.
var declBodyRe = regexp.MustCompile(`^([a-z][a-z0-9-]*)(?:\s+x([0-9]+))?(?:\s+on\s+(\S+))?$`)

// declaration is one expected finding: N occurrences of Rule attributed to Path.
type declaration struct {
	Rule  string
	Path  string // repo-relative subject; the declaring file unless `on <path>` says otherwise
	Count int

	File string // repo-relative path of the file that carries the declaration
	Line int
}

func (d declaration) where() string { return fmt.Sprintf("%s:%d", d.File, d.Line) }

// declarationBody returns the text after the marker, having peeled off whichever comment
// syntax the host file uses: `#` for YAML, `//` for Go, `<!-- -->` for markdown, or nothing at
// all for markdown prose. One grammar, every file type — so a finding attributed to a manifest
// is declared in that manifest rather than in a side table nobody reads.
func declarationBody(line string) (string, bool) {
	t := strings.TrimSpace(line)
	t = strings.TrimSpace(strings.TrimPrefix(t, "<!--"))
	t = strings.TrimSpace(strings.TrimSuffix(t, "-->"))
	t = strings.TrimSpace(strings.TrimLeft(t, "#/"))
	if !strings.HasPrefix(t, declMarker) {
		return "", false
	}
	return strings.TrimSpace(strings.TrimPrefix(t, declMarker)), true
}

// declarationSet is everything one sample's own files say about what docsgen should report.
type declarationSet struct {
	Expected []declaration
	Silent   []string // repo-relative files declaring `EXPECT: none`
	Declared []string // every file carrying at least one declaration, silent ones included
	Problems []string // malformed declarations, ready to print
}

// scanDeclarations reads the sample SOURCE tree, never a built fixture. The source is what a
// human edits and what a reviewer reads, so that is what must be self-describing.
func scanDeclarations(s *sample) declarationSet {
	GinkgoHelper()
	root := sampleDir(s.Name)
	known := configuredRules(s)

	var set declarationSet
	declaring := map[string]bool{}

	Expect(filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return err
		}
		rel, err := filepath.Rel(root, p)
		if err != nil {
			return err
		}
		rel = filepath.ToSlash(rel)
		b, err := os.ReadFile(p)
		if err != nil {
			return err
		}
		for i, line := range strings.Split(string(b), "\n") {
			lineNo := i + 1
			if strings.Contains(line, declLegacy) {
				set.Problems = append(set.Problems, fmt.Sprintf(
					"%s:%d: the prose form %q is no longer a declaration and is enforced by "+
						"nothing — replace it with a `%s <rule>` line and keep the explanation "+
						"on its own lines", rel, lineNo, declLegacy, declMarker))
				continue
			}
			body, ok := declarationBody(line)
			if !ok {
				continue
			}
			declaring[rel] = true

			if body == declNone {
				set.Silent = append(set.Silent, rel)
				continue
			}
			m := declBodyRe.FindStringSubmatch(body)
			if m == nil {
				set.Problems = append(set.Problems, fmt.Sprintf(
					"%s:%d: cannot parse %q. A declaration is `%s <rule> [x<N>] [on <path>]` or "+
						"`%s %s`, and carries NO other text — prose beside a rule name is where "+
						"the literal that cures the defect creeps back in",
					rel, lineNo, body, declMarker, declMarker, declNone))
				continue
			}
			decl := declaration{Rule: m[1], Path: rel, Count: 1, File: rel, Line: lineNo}
			if m[2] != "" {
				n, convErr := strconv.Atoi(m[2])
				if convErr != nil || n < 1 {
					set.Problems = append(set.Problems, fmt.Sprintf(
						"%s:%d: count %q must be a positive integer", rel, lineNo, m[2]))
					continue
				}
				decl.Count = n
			}
			if m[3] != "" {
				decl.Path = m[3]
				if _, statErr := os.Stat(filepath.Join(root, decl.Path)); statErr != nil {
					set.Problems = append(set.Problems, fmt.Sprintf(
						"%s:%d: `on %s` names a path that is not in this sample", rel, lineNo, decl.Path))
					continue
				}
			}
			if !known[decl.Rule] {
				set.Problems = append(set.Problems, fmt.Sprintf(
					"%s:%d: `%s` is not a rule this sample's config.yaml declares (known: %s)",
					rel, lineNo, decl.Rule, strings.Join(sortedKeys(known), " ")))
				continue
			}
			set.Expected = append(set.Expected, decl)
		}
		return nil
	})).To(Succeed())

	set.Declared = sortedKeys(declaring)
	sort.Strings(set.Silent)
	return set
}

// configuredRules reads the rule ids out of the sample's own config.yaml, so a sample that
// enables a rule this suite has never heard of still gets its declarations validated.
func configuredRules(s *sample) map[string]bool {
	GinkgoHelper()
	b, err := os.ReadFile(filepath.Join(sampleDir(s.Name), "config.yaml"))
	Expect(err).NotTo(HaveOccurred())

	var doc struct {
		Rules map[string]yaml.Node `yaml:"rules"`
	}
	Expect(yaml.Unmarshal(b, &doc)).To(Succeed())
	Expect(doc.Rules).NotTo(BeEmpty(), "sample %s declares no rules at all", s.Name)

	out := map[string]bool{}
	for name := range doc.Rules {
		out[name] = true
	}
	return out
}

// markdownDocs lists every .md file in a sample, which is the set required to declare.
func markdownDocs(s *sample) []string {
	GinkgoHelper()
	root := sampleDir(s.Name)
	var out []string
	Expect(filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() || !strings.HasSuffix(d.Name(), ".md") {
			return err
		}
		rel, err := filepath.Rel(root, p)
		if err != nil {
			return err
		}
		out = append(out, filepath.ToSlash(rel))
		return nil
	})).To(Succeed())
	sort.Strings(out)
	return out
}

// --- reading what docsgen actually reported ----------------------------------------------

var lintHeaderRe = regexp.MustCompile(`^(\S+)\s{2}\[(error|warn)\]\s{2}(\d+) finding\(s\)$`)

// lintFinding is one reported line, reduced to the pair the reconciliation is keyed on plus the
// message, which is carried only so a failure is readable.
type lintFinding struct {
	Rule    string
	Path    string
	Message string
}

// parseLintFindings turns `docsgen lint` stdout back into structured findings.
//
// findingsFor() beside this reads ONE rule's block as raw strings, which is right for a spec
// that already knows which rule it cares about. Reconciliation needs the whole report keyed by
// (path, rule), and it must notice the truncation marker: reportLint prints at most 20 lines per
// rule, and a silently truncated block would make "found but undeclared" under-report — a gap in
// exactly the half of this spec that exists to catch a masking finding.
func parseLintFindings(out string) []lintFinding {
	GinkgoHelper()
	var found []lintFinding
	rule := ""
	for _, line := range strings.Split(out, "\n") {
		if m := lintHeaderRe.FindStringSubmatch(strings.TrimRight(line, "\r")); m != nil {
			rule = m[1]
			continue
		}
		if !strings.HasPrefix(line, "  ") {
			rule = "" // a blank line or the summary closes the current block
			continue
		}
		item := strings.TrimSpace(line)
		Expect(item).NotTo(HavePrefix("... and "),
			"`docsgen lint` truncated a rule block at 20 findings, so the report no longer "+
				"lists every finding and an undeclared one could hide past the cut: %q", item)
		Expect(rule).NotTo(BeEmpty(), "indented line outside any rule block: %q", line)

		path, message, ok := strings.Cut(item, ": ")
		Expect(ok).To(BeTrue(), "cannot split a finding into path and message: %q", item)
		found = append(found, lintFinding{Rule: rule, Path: path, Message: message})
	}
	return found
}

// --- the reconciliation -------------------------------------------------------------------

func findingKey(path, rule string) string { return path + "\x00" + rule }

func keyParts(k string) (path, rule string) {
	path, rule, _ = strings.Cut(k, "\x00")
	return
}

func tallyDeclared(set declarationSet) map[string]int {
	out := map[string]int{}
	for _, d := range set.Expected {
		out[findingKey(d.Path, d.Rule)] += d.Count
	}
	return out
}

func tallyActual(found []lintFinding) map[string]int {
	out := map[string]int{}
	for _, f := range found {
		out[findingKey(f.Path, f.Rule)]++
	}
	return out
}

// reconcile returns the two lists a human needs, already formatted. Two explicit lists rather
// than one opaque "sets differ": a failure nobody can act on gets deleted, and this spec is
// worth more than the fixtures it guards.
//
// leftLabel/rightLabel name the two tallies in every row, because this same comparison serves
// two questions — declared vs reported, and reported-with-declarations vs reported-without —
// and a row reading "declared 0" under the second question would be a lie.
func reconcile(left, right map[string]int, leftLabel, rightLabel string) (onlyLeft, onlyRight []string) {
	for _, k := range sortedKeys(unionKeys(left, right)) {
		path, rule := keyParts(k)
		l, r := left[k], right[k]
		switch {
		case l > r:
			onlyLeft = append(onlyLeft, fmt.Sprintf("  %-52s %-20s %s %d, %s %d", path, rule, leftLabel, l, rightLabel, r))
		case r > l:
			onlyRight = append(onlyRight, fmt.Sprintf("  %-52s %-20s %s %d, %s %d", path, rule, rightLabel, r, leftLabel, l))
		}
	}
	return onlyLeft, onlyRight
}

func reconcileReport(sampleName string, missing, undeclared []string) string {
	var b strings.Builder
	fmt.Fprintf(&b, "sample %s: `docsgen lint` and the fixtures' own declarations disagree.\n", sampleName)
	if len(missing) > 0 {
		b.WriteString("\nDECLARED but MISSING from the lint output — the fixture stopped tripping the rule " +
			"it was written to demonstrate. The usual cause is that the doc now NAMES the literal " +
			"the rule searches for (its footer heading, its ticket id, its link target), which " +
			"cures the defect and silences the rule:\n")
		b.WriteString(strings.Join(missing, "\n") + "\n")
	}
	if len(undeclared) > 0 {
		b.WriteString("\nFOUND but UNDECLARED — a real finding no fixture claims. Either the fixture that " +
			"produced it has not declared it, or a rule started over-reporting. An undeclared " +
			"finding is also how a fixture that has gone silent keeps looking covered in the golden:\n")
		b.WriteString(strings.Join(undeclared, "\n") + "\n")
	}
	b.WriteString("\nDeclarations live in the fixtures themselves as `" + declMarker +
		" <rule>` lines. Fix whichever side is wrong — never delete a declaration to make this pass.\n")
	return b.String()
}

func unionKeys(a, b map[string]int) map[string]bool {
	out := map[string]bool{}
	for k := range a {
		out[k] = true
	}
	for k := range b {
		out[k] = true
	}
	return out
}

func sortedKeys[V any](m map[string]V) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// stripDeclarations deletes every declaration line from a built fixture, in place. Used by the
// inertness spec; `git ls-files` still lists the files, and docsgen reads their content from
// disk, so no commit is needed.
func stripDeclarations(root string) int {
	GinkgoHelper()
	removed := 0
	Expect(filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			if d.Name() == ".git" {
				return fs.SkipDir
			}
			return nil
		}
		b, err := os.ReadFile(p)
		if err != nil {
			return err
		}
		lines := strings.Split(string(b), "\n")
		kept := make([]string, 0, len(lines))
		hit := false
		for _, line := range lines {
			if _, ok := declarationBody(line); ok {
				hit, removed = true, removed+1
				continue
			}
			kept = append(kept, line)
		}
		if !hit {
			return nil
		}
		info, err := d.Info()
		if err != nil {
			return err
		}
		return os.WriteFile(p, []byte(strings.Join(kept, "\n")), info.Mode().Perm())
	})).To(Succeed())
	return removed
}

// --- the specs ------------------------------------------------------------------------------

var _ = Describe("declared vs actual findings", Label("integration"), func() {
	for _, s := range samples {
		s := s

		Context("sample "+s.Name, func() {

			It("accepts only declarations that name a rule and nothing else, because a "+
				"free-text slot beside a rule name is where the curing literal creeps back in", func() {
				set := scanDeclarations(s)
				Expect(set.Problems).To(BeEmpty(),
					"sample %s: malformed declarations:\n%s", s.Name, strings.Join(set.Problems, "\n"))
				Expect(set.Expected).NotTo(BeEmpty(),
					"sample %s declares no findings at all, so the reconciliation below would "+
						"pass by having nothing to reconcile", s.Name)
			})

			It("requires every doc in the sample to declare what it produces, so a fixture "+
				"cannot be added — or go silent — without saying so", func() {
				declared := map[string]bool{}
				for _, f := range scanDeclarations(s).Declared {
					declared[f] = true
				}
				var undeclaredDocs []string
				for _, doc := range markdownDocs(s) {
					if !declared[doc] {
						undeclaredDocs = append(undeclaredDocs, "  "+doc)
					}
				}
				Expect(undeclaredDocs).To(BeEmpty(),
					"sample %s: these docs declare nothing. Every doc states its own expectation, "+
						"`%s %s` included — a doc with no declaration is a doc whose silence "+
						"nobody will ever notice:\n%s",
					s.Name, declMarker, declNone, strings.Join(undeclaredDocs, "\n"))
			})

			It("reports exactly the findings the fixtures declare, and no others", func() {
				fx := newFixture(s)
				set := scanDeclarations(s)
				Expect(set.Problems).To(BeEmpty(), strings.Join(set.Problems, "\n"))

				actual := tallyActual(parseLintFindings(fx.run("lint").Out))
				missing, undeclared := reconcile(tallyDeclared(set), actual, "declared", "found")

				Expect(append(missing, undeclared...)).To(BeEmpty(),
					"%s", reconcileReport(s.Name, missing, undeclared))
			})

			It("stays silent on every file that declares it produces nothing", func() {
				fx := newFixture(s)
				set := scanDeclarations(s)
				Expect(set.Silent).NotTo(BeEmpty(),
					"sample %s has no `%s %s` fixture, so the negative half is untested",
					s.Name, declMarker, declNone)

				silent := map[string]bool{}
				for _, f := range set.Silent {
					silent[f] = true
				}
				var noisy []string
				for _, f := range parseLintFindings(fx.run("lint").Out) {
					if silent[f.Path] {
						noisy = append(noisy, fmt.Sprintf("  %s  %s: %s", f.Path, f.Rule, f.Message))
					}
				}
				Expect(noisy).To(BeEmpty(),
					"sample %s: these files declare `%s %s` and produced findings anyway. Either "+
						"the file rotted or a rule started over-reporting; an over-reporting rule "+
						"gets switched off just as fast as one that misses:\n%s",
					s.Name, declMarker, declNone, strings.Join(noisy, "\n"))
			})

			It("reports the same findings with every declaration deleted, which is the proof "+
				"that a declaration cannot satisfy — or provoke — the rule it declares", func() {
				fx := newFixture(s)
				before := tallyActual(parseLintFindings(fx.run("lint").Out))

				removed := stripDeclarations(fx.Root)
				Expect(removed).To(BeNumerically(">", 0),
					"no declaration lines were found in the built fixture, so this spec proved nothing")

				after := tallyActual(parseLintFindings(fx.run("lint").Out))
				gone, appeared := reconcile(before, after, "with declarations", "without them")

				Expect(append(gone, appeared...)).To(BeEmpty(),
					"sample %s: deleting %d declaration lines changed what docsgen reports, so the "+
						"declarations are part of the thing they claim to describe. A declaration "+
						"that can satisfy its own rule cures the defect it documents — that is the "+
						"exact failure this whole file exists to make impossible.\n\n"+
						"PRESENT WITH DECLARATIONS, ABSENT WITHOUT (a declaration was PROVOKING a "+
						"finding):\n%s\n"+
						"ABSENT WITH DECLARATIONS, PRESENT WITHOUT (a declaration was SUPPRESSING a "+
						"finding — this is the self-curing fixture, caught in the act):\n%s",
					s.Name, removed, strings.Join(gone, "\n"), strings.Join(appeared, "\n"))
			})
		})
	}
})
