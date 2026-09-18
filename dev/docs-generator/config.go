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
