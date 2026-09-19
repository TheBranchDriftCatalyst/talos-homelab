package main

// Configuration is the portability boundary.
//
// Everything repo-specific lives in config.yaml next to the binary. The Go below knows nothing
// about Talos, Flux or beads by name — it knows there is *a* way to enumerate components and
// *a* ticket pattern, and reads both from config. Porting to another repo should mean copying
// dev/docs-generator/ and editing one YAML file, never editing Go.

import (
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"gopkg.in/yaml.v3"
)

// ComponentSource describes how a repo enumerates its deployable units.
//
// kind: flux reads Kustomization CRs and takes spec.path. That is right for a Flux repo because
// the directory tree alone is ambiguous — some directories are grouping dirs whose CHILDREN are
// the real units (which is the correct pattern), while others are a single Kustomization
// wrapping many nested ones (which is not). Flux names the real deployable boundary; the
// filesystem does not.
//
// kind: dirs is the fallback for repos with no GitOps controller. Add a new kind in collect.go
// when a repo needs one — never special-case inside a rule.
type ComponentSource struct {
	Kind     string `yaml:"kind"`      // flux | dirs
	Path     string `yaml:"path"`      // where to look
	Glob     string `yaml:"glob"`      // what to match
	SlugFrom string `yaml:"slug_from"` // filename | metadata.name
}

// Rule toggles one check. Severity is data, not code, so a repo can adopt the tool in warn-only
// mode and promote rules as it cleans up — which is the only way a linter lands on an existing
// codebase without being switched off on day one.
type Rule struct {
	Enabled  bool   `yaml:"enabled"`
	Severity string `yaml:"severity"` // warn | error
}

// TicketSource says whether ticket IDs can be checked for EXISTENCE, not merely for shape.
//
// ticket_pattern is a regex, so it validates spelling and nothing else: `TALOS-kll8` is a
// one-character typo of a real ticket, matches the pattern perfectly, and refers to nothing.
// Backend "" (the default) means no checking, which is right for a repo with no tracker — the
// rule then skips WITH A REASON rather than silently passing, because a check that quietly
// never runs is worse than an absent one.
type TicketSource struct {
	Backend string `yaml:"backend"` // "" (off) | "beads"
	Command string `yaml:"command"` // override the binary; defaults per backend
}

// ArtifactSpec is one generated document, declared entirely in config.
//
// The frontmatter is DATA. Every value the generator stamps into an artifact — its type, its
// status, its freshness, the tickets it cites — used to be a Go string constant, which meant
// docsgen emitted `type: reference` into a repo whose vocabulary has no such type and then
// reported its own output as a schema violation. A generator that emits documents its own
// ruleset rejects cannot be trusted to keep any other document honest.
//
// There is deliberately NO default for `type`, `status` or `freshness`. A default is the same
// constant wearing a config key: it would be silently wrong in every repo that does not happen
// to share this one's vocabulary, which is precisely the defect. An artifact whose front is
// incomplete is a config error, reported by name.
type ArtifactSpec struct {
	// Renderer names the Go renderer to run, defaulting to the artifact's own config key.
	//
	// It exists because SCOPING made one renderer serve several artifacts. `renderers` is keyed
	// by name, so before scope there was exactly one way to spell "render a component
	// inventory" and therefore exactly one component inventory per repo. A per-section
	// inventory is the SAME renderer over a SUBSET, and without this key adding the second one
	// would mean registering `security-inventory: renderComponentInventory` in Go — which is
	// precisely the "adding an artifact costs a Go edit" defect config.yaml exists to remove.
	Renderer string `yaml:"renderer"`

	// Root is the repo-relative directory Path is resolved against, defaulting to
	// Config.DocsRoot.
	//
	// The default is right for prose: a repo moving its documentation tree moves every artifact
	// with it. It is wrong for a SECTION inventory, whose whole point is to sit beside the
	// manifests it describes — and those live outside the documentation root, which the path
	// guard correctly refuses to let `path:` escape. So the escape is declared here instead of
	// smuggled through `../..`, and it is still bounded: Root must resolve inside the repo.
	Root string `yaml:"root"`

	// Path is relative to Root (hence to Config.DocsRoot by default), so no artifact has to
	// repeat its root.
	Path string `yaml:"path"`

	// Scope narrows the artifact to a subset of the component set. ABSENT MEANS EVERY
	// COMPONENT, which is what keeps every pre-scope artifact byte-identical.
	//
	// A pointer, not a value: `scope: {}` and no `scope:` at all are different intentions, and
	// only a pointer can tell them apart. The first is a filter somebody forgot to fill in and
	// is reported; the second is "cover everything" and is the default.
	Scope *ArtifactScope `yaml:"scope"`

	// Front is rendered by renderFrontMatter in Config.KeyOrder. It is map[string]any and NOT a
	// struct: the moment one key is special to Go, that key is a constant again.
	Front map[string]any `yaml:"front"`

	// TicketNotes annotates the footer's ticket list. The list itself comes from
	// Front["tickets"], which is what makes the `tickets-in-body` rule self-satisfying; a note
	// is prose, and prose belongs in config rather than in Go. A note for an id that is not in
	// Front["tickets"] is a config error rather than a line nobody ever sees.
	TicketNotes map[string]string `yaml:"ticket_notes"`
}

// ArtifactScope narrows an artifact to a subset of the components docsgen enumerated.
//
// path_prefix rather than a label, because docsgen already thinks in paths: ExpectedLocation
// computes a doc's home from the longest common ancestor of its covers, so a path prefix is the
// primitive already in the model and needs no new parsing. Scoping by a Kubernetes label would
// require reading Namespace manifests, which is a genuinely new fact for the collector to
// gather and does not belong behind a rendering key.
//
// Matching is SEGMENT-AWARE (see Matches). A substring prefix would quietly pull
// `infrastructure/base/security-extras` into a scope meant for `infrastructure/base/security`,
// and an inventory silently containing a neighbour is worse than one that is obviously wrong.
type ArtifactScope struct {
	PathPrefix string `yaml:"path_prefix"`
}

// Matches reports whether a component falls inside the scope. A nil scope matches everything,
// which is the "scope absent => all components" rule expressed once rather than at each caller.
func (s *ArtifactScope) Matches(c Component) bool {
	if s == nil {
		return true
	}
	prefix := strings.Trim(strings.TrimSpace(s.PathPrefix), "/")
	if prefix == "" {
		// Unreachable through Generate — validateArtifacts rejects an empty prefix by name
		// first. Matching everything here rather than nothing keeps a direct caller honest: a
		// filter that silently excluded every row is the vacuity this feature exists to refuse.
		return true
	}
	p := strings.TrimSuffix(c.Path, "/")
	return p == prefix || strings.HasPrefix(p, prefix+"/")
}

type Config struct {
	Exclude          []string            `yaml:"exclude"`
	TicketPattern    string              `yaml:"ticket_pattern"`
	Components       ComponentSource     `yaml:"components"`
	Rules            map[string]Rule     `yaml:"rules"`
	DocTypes         []string            `yaml:"doc_types"`
	Statuses         []string            `yaml:"statuses"`
	Freshness        []string            `yaml:"freshness"`
	FreshnessDefault map[string]string   `yaml:"freshness_default"`
	BannedKeys       map[string]string   `yaml:"banned_keys"` // key -> why it is banned
	KeyOrder         []string            `yaml:"key_order"`
	GroupingRoots    []string            `yaml:"grouping_roots"`
	TypeRequires     map[string][]string `yaml:"type_requires"`
	RequiredFooter   string              `yaml:"required_footer"`
	Tickets          TicketSource        `yaml:"tickets"`

	// DocsRoot is the repo's documentation root. It defaults to `docs` via DocsRootOr, which is
	// safe in a way that a default `type:` would not be: a root is a PATH, not a vocabulary
	// term, so a wrong one is visible the first time anybody looks at the tree. A wrong
	// vocabulary term is invisible until someone runs the linter over the generated file.
	DocsRoot string `yaml:"docs_root"`

	// Artifacts is the generated document set, keyed by renderer name. Absent means this repo
	// generates nothing — which is a legitimate configuration and must not fall back to some
	// artifact compiled into Go.
	Artifacts map[string]ArtifactSpec `yaml:"artifacts"`
}

// DocsRootOr returns the configured documentation root without a trailing slash, defaulting to
// `docs`. Callers go through this rather than reading the field so that a Config built in a test
// — or a repo with no config file at all — behaves the same as one loaded from YAML.
func (c *Config) DocsRootOr() string {
	if c.DocsRoot == "" {
		return "docs"
	}
	return strings.TrimSuffix(c.DocsRoot, "/")
}

// RootFor returns the repo-relative directory an artifact's `path` is resolved against: the
// artifact's own `root` when it declares one, and the documentation root otherwise.
//
// Callers go through this rather than reading the field, so an artifact built in a test behaves
// exactly like one loaded from YAML — the same reason DocsRootOr exists.
func (c *Config) RootFor(spec ArtifactSpec) string {
	if r := strings.Trim(strings.TrimSpace(spec.Root), "/"); r != "" {
		return r
	}
	return c.DocsRootOr()
}

// RendererFor returns the renderer name an artifact asks for: its own `renderer` key when it
// declares one, and its config key otherwise.
func (c *Config) RendererFor(name string, spec ArtifactSpec) string {
	if r := strings.TrimSpace(spec.Renderer); r != "" {
		return r
	}
	return name
}

// RuleFor returns the configured rule, defaulting to enabled/warn. An unknown rule name is
// enabled rather than silently skipped: a typo in config should surface as unexpected findings,
// not as a check that quietly never runs.
func (c *Config) RuleFor(name string) Rule {
	if r, ok := c.Rules[name]; ok {
		if r.Severity == "" {
			r.Severity = "warn"
		}
		return r
	}
	return Rule{Enabled: true, Severity: "warn"}
}

func (c *Config) Has(list []string, want string) bool {
	return slices.Contains(list, want)
}

// LoadConfig reads config.yaml beside the executable's source directory.
//
// A missing or malformed config is NOT fatal. The linter still has value on defaults, and a hard
// failure here would make the tool unusable in exactly the repo where someone is trying to adopt
// it for the first time.
func LoadConfig(dir string) (*Config, error) {
	cfg := &Config{
		TicketPattern: `\b[A-Z]{2,10}-[0-9a-z]{2,6}(?:\.\d+)*\b`,
		Components:    ComponentSource{Kind: "dirs", Glob: "*"},
	}
	path := filepath.Join(dir, "config.yaml")
	raw, err := os.ReadFile(path)
	if err != nil {
		warnf("%s: %v; using defaults", filepath.Base(path), err)
		return cfg, nil
	}
	if err := yaml.Unmarshal(raw, cfg); err != nil {
		return cfg, fmt.Errorf("%s: %w", filepath.Base(path), err)
	}
	if cfg.Components.Glob == "" {
		cfg.Components.Glob = "*"
	}
	return cfg, nil
}
