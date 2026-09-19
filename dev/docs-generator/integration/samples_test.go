package integration_test

import (
	"os"
	"path/filepath"
)

// sample describes one hand-written fixture repository under testdata/samples/.
//
// The invariant specs are table-driven over this list, so a new sample costs one directory plus
// one entry here and no new spec code. That is the property that makes the layout worth having:
// component enumeration is becoming a strategy pattern (TALOS-f0sd.1), and when a third kind
// lands — packages, modules, services, whatever the repo's unit turns out to be — the whole
// invariant set should apply to it on day one without anybody writing a spec.
//
// Everything in here is a KNOWN ANSWER, hand-derived from the sample tree. If a field disagrees
// with the sample, fix whichever one is wrong; do not "adjust the expectation until it passes".
type sample struct {
	// Name is the directory under testdata/samples/ and testdata/golden/.
	Name string

	// Kind is the value of components.kind in the sample's config.yaml. Recorded so a spec can
	// say WHY it is skipping rather than silently not running.
	Kind string

	// Slugs is every component the sample declares, in `docsgen components` order (slug, then
	// path). This is the DOCUMENTED-CORRECT answer, not a transcript of current behaviour.
	Slugs []string

	// Worklist is every doc `docsgen frontmatter` must name, sorted.
	Worklist []string

	// StaleSubject is the one file the fixture builder's second commit touches, and StaleDocs
	// is every doc that must therefore be reported stale. Without a second commit every path
	// shares one timestamp and `stale` is empty — which reads exactly like a pass.
	StaleSubject string
	StaleDocs    []string

	// ReadmeFile is a colocated README belonging to ReadmeOwner: deleting it must flip that
	// component's readme column.
	ReadmeOwner string
	ReadmeFile  string

	// NestedDir belongs to NestedOwner: dropping a kustomization.yaml in it must raise that
	// component's nested count by exactly one.
	NestedOwner string
	NestedDir   string

	// CleanDoc has valid frontmatter and produces no findings, so a mutation applied to it
	// produces exactly one new finding and nothing else moves.
	CleanDoc string

	// CoversDoc carries `covers: [CoversToken]`, a token that resolves today.
	CoversDoc   string
	CoversToken string

	// ExcludedDir matches an `exclude` pattern in the sample's config.
	ExcludedDir string

	// ArtifactRel is where THIS sample's config sends the generated inventory: docs_root joined
	// with artifacts.component-inventory.path. It is per-sample and not a constant because the
	// destination is per-repo — neither sample has a docs/ directory, and a shared constant is
	// how the hardcoded `docs/07-reference/component-inventory.md` survived as long as it did.
	ArtifactRel string

	// --- the scoped artifact ------------------------------------------------------------
	//
	// Every sample declares one, and assertSamplesAreReal refuses a sample that does not: a
	// table-driven suite whose table has an empty slot runs the scoping specs against nothing
	// and reports them green, which is the exact vacuity this feature was written to refuse in
	// the tool itself.

	// ScopeRel is where the scoped artifact lands: the artifact's own `root` (or docs_root)
	// joined with its path.
	ScopeRel string

	// ScopePrefix is the sample's configured `scope.path_prefix`, spelled exactly as it appears
	// in the sample's config.yaml so a spec can edit that line.
	ScopePrefix string

	// ScopeSlugs is every component inside the scope and ScopeExcludes is every component
	// outside it. Both are required and both are checked: asserting only that the included rows
	// are present would pass for an artifact that ignored the filter entirely.
	ScopeSlugs    []string
	ScopeExcludes []string

	// WarnOnlyRule fires in this sample at warn severity; ErrorRule fires at error severity.
	// Together they pin the half of the exit-code contract that severity drives.
	WarnOnlyRule string
	ErrorRule    string

	// AddComponent / RemoveComponent make one component appear or disappear, and return its
	// slug. How a component comes into being is the one genuinely strategy-specific thing in
	// this table — under flux it is a manifest, under dirs it is a directory.
	AddComponent    func(root string) string
	RemoveComponent func(root string) string
}

func sampleDir(name string) string { return filepath.Join("testdata", "samples", name) }

var samples = []*sample{fluxCluster, plainDirs}

// ---------------------------------------------------------------------------------------------
// flux-cluster — a GitOps repo whose unit is a Flux Kustomization.
// ---------------------------------------------------------------------------------------------

var fluxCluster = &sample{
	Name: "flux-cluster",
	Kind: "flux",

	// Eight components across seven manifest files. `secrets.yaml` declares TWO of them, and
	// they MUST keep distinct slugs — see the spec "two Kustomizations in one manifest".
	// `namespace.yaml` is not a Kustomization, `pathless.yaml` has no spec.path and `broken.yaml`
	// is not valid YAML, so none of the three contributes a component.
	Slugs: []string{
		"gateway",          // platform/gateway          (flux name gateway-controller)
		"legacy-cache",     // platform/legacy-cache     — declared, NOT on disk
		"orchard-api",      // workloads/orchard-api
		"orchard-web",      // workloads/orchard-web
		"secrets-operator", // platform/secrets-operator ) both declared in
		"secrets-store",    // platform/secrets-store    ) fleet/prod-west/secrets.yaml
		"storage",          // platform/storage          (flux name storage-stack, 5 nested)
		"telemetry",        // platform/telemetry        (suspended)
	},

	Worklist: []string{
		"README.md",
		"handbook/reference/no-frontmatter.md",
		"workloads/orchard-web/README.md",
	},

	StaleSubject: "platform/gateway/deployment.yaml",
	// Four docs cover `gateway`, and all four go stale together when its code moves.
	StaleDocs: []string{
		"platform/gateway/README.md",
		"handbook/getting-started/first-deploy.md",
		"handbook/reference/scalar-covers.md",
		"handbook/reference/unknown-covers.md",
	},

	ReadmeOwner: "gateway",
	ReadmeFile:  "platform/gateway/README.md",

	NestedOwner: "telemetry",
	NestedDir:   "platform/telemetry",

	CleanDoc: "handbook/README.md",

	CoversDoc:   "workloads/orchard-api/README.md",
	CoversToken: "orchard-api",

	ExcludedDir: "handbook/_attic",

	ArtifactRel: "handbook/reference/component-inventory.md",

	// Six of the eight components live under platform/; the two orchard workloads do not.
	ScopeRel:      "handbook/reference/platform-inventory.md",
	ScopePrefix:   "platform",
	ScopeSlugs:    []string{"gateway", "legacy-cache", "secrets-operator", "secrets-store", "storage", "telemetry"},
	ScopeExcludes: []string{"orchard-api", "orchard-web"},

	WarnOnlyRule: "component-shape", // platform/storage wraps 5 nested kustomizations
	ErrorRule:    "broken-links",    // handbook/reference/dead-links.md has exactly two

	AddComponent: func(root string) string {
		const slug = "zzz-new"
		mustMkdirAll(filepath.Join(root, "platform", slug))
		mustWrite(filepath.Join(root, "platform", slug, "kustomization.yaml"),
			"apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: []\n")
		mustWrite(filepath.Join(root, "fleet", "prod-west", slug+".yaml"),
			"apiVersion: kustomize.toolkit.fluxcd.io/v1\n"+
				"kind: Kustomization\n"+
				"metadata:\n  name: "+slug+"\nspec:\n  interval: 10m\n  path: ./platform/"+slug+"\n")
		return slug
	},
	RemoveComponent: func(root string) string {
		mustRemove(filepath.Join(root, "fleet", "prod-west", "telemetry.yaml"))
		return "telemetry"
	},
}

// ---------------------------------------------------------------------------------------------
// plain-dirs — a repo with no GitOps controller at all, whose unit is simply a directory.
// ---------------------------------------------------------------------------------------------

var plainDirs = &sample{
	Name: "plain-dirs",
	Kind: "dirs",

	Slugs: []string{"billing", "catalog", "identity", "notifications", "search"},

	Worklist: []string{"README.md"},

	StaleSubject: "services/billing/main.go",
	StaleDocs:    []string{"services/billing/README.md"},

	ReadmeOwner: "billing",
	ReadmeFile:  "services/billing/README.md",

	NestedOwner: "catalog",
	NestedDir:   "services/catalog",

	CleanDoc: "notes/README.md",

	CoversDoc:   "services/identity/README.md",
	CoversToken: "identity",

	ExcludedDir: "notes/archive",

	ArtifactRel: "notes/reference/component-inventory.md",

	// One of five, and its `root:` puts the artifact OUTSIDE the documentation root — which is
	// the whole reason `root:` exists.
	ScopeRel:      "services/search/components.md",
	ScopePrefix:   "services/search",
	ScopeSlugs:    []string{"search"},
	ScopeExcludes: []string{"billing", "catalog", "identity", "notifications"},

	WarnOnlyRule: "colocation",   // notes/deploying.md covers catalog but lives in notes/
	ErrorRule:    "broken-links", // notes/rule-sweep.md links at ./vanished.md

	AddComponent: func(root string) string {
		const slug = "zzz-new"
		mustMkdirAll(filepath.Join(root, "services", slug))
		mustWrite(filepath.Join(root, "services", slug, "main.go"), "package main\n\nfunc main() {}\n")
		return slug
	},
	RemoveComponent: func(root string) string {
		mustRemove(filepath.Join(root, "services", "notifications"))
		return "notifications"
	},
}

// --- tiny filesystem helpers, panicking so the sample table stays declarative ----------------

func mustMkdirAll(p string) {
	if err := os.MkdirAll(p, 0o755); err != nil {
		panic(err)
	}
}

func mustWrite(p, content string) {
	if err := os.WriteFile(p, []byte(content), 0o644); err != nil {
		panic(err)
	}
}

func mustRemove(p string) {
	if err := os.RemoveAll(p); err != nil {
		panic(err)
	}
}
