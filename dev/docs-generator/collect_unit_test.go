package main

// Unit specs for collect.go and the two enumeration strategies — slug identity, exclusion
// matching, and the loaders.
//
// The loader specs stayed here when loadFlux/loadDirs moved into strategy_flux.go and
// strategy_dirs.go; only the call form changed, from a free function to the strategy's
// Enumerate. Specs for the SEAM itself — the registry, the fact vocabulary, the per-strategy
// glob defaults — are in strategy_unit_test.go, which also carries the registry-pollution
// warning anyone adding a strategy spec needs to read first.
//
// Nothing here reads the real repo. Filesystem cases build a throwaway tree under
// GinkgoT().TempDir(); the two git-backed cases initialise a scratch repository in that temp
// dir with pinned commit timestamps, so they assert exact values without baking in today's
// date or any real SHA.

import (
	"bytes"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

// --- helpers ---------------------------------------------------------------------------------

func unitWrite(root, rel, content string) {
	GinkgoHelper()
	full := filepath.Join(root, rel)
	Expect(os.MkdirAll(filepath.Dir(full), 0o755)).To(Succeed())
	Expect(os.WriteFile(full, []byte(content), 0o644)).To(Succeed())
}

func unitRunGit(dir string, env []string, args ...string) error {
	cmd := exec.Command("git", args...)
	cmd.Dir = dir
	cmd.Env = append(os.Environ(), env...)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("git %v: %w: %s", args, err, stderr.String())
	}
	return nil
}

// unitInitRepo makes a throwaway repository. The developer's global git config (commit signing,
// hook paths, init templates) is neutralised so these specs assert the tool's behaviour rather
// than the machine's configuration; if git is missing entirely the spec skips instead of failing.
func unitInitRepo(dir string) {
	GinkgoHelper()
	if _, err := exec.LookPath("git"); err != nil {
		Skip("git is not on PATH; LastCommitDates/TrackedMarkdown specs need a scratch repo")
	}
	if err := unitRunGit(dir, nil, "init", "-q", "--template=", "-b", "main"); err != nil {
		Skip("could not create a scratch git repo: " + err.Error())
	}
	for _, kv := range [][2]string{
		{"user.email", "spec@example.test"},
		{"user.name", "docsgen spec"},
		{"commit.gpgsign", "false"},
		{"core.hooksPath", filepath.Join(dir, "no-such-hooks")},
	} {
		Expect(unitRunGit(dir, nil, "config", kv[0], kv[1])).To(Succeed())
	}
}

func unitCommit(dir, message, isoDate string) {
	GinkgoHelper()
	env := []string{"GIT_AUTHOR_DATE=" + isoDate, "GIT_COMMITTER_DATE=" + isoDate}
	Expect(unitRunGit(dir, nil, "add", "-A")).To(Succeed())
	Expect(unitRunGit(dir, env, "commit", "-q", "--no-verify", "-m", message)).To(Succeed())
}

// unitEnumerate runs one strategy and returns just its components, so a spec that is about
// enumeration is not also about error handling. Warnings are asserted separately, in
// strategy_unit_test.go, which is the point of returning them instead of printing them.
func unitEnumerate(s ComponentStrategy, root string, cfg *Config) []Component {
	GinkgoHelper()
	enum, err := s.Enumerate(root, cfg)
	Expect(err).NotTo(HaveOccurred())
	return enum.Components
}

func unitFlux(name, path string) string {
	return "apiVersion: kustomize.toolkit.fluxcd.io/v1\nkind: Kustomization\nmetadata:\n  name: " +
		name + "\nspec:\n  path: " + path + "\n"
}

// --- slugFor ---------------------------------------------------------------------------------

var _ = Describe("slugFor", Label("unit"), func() {
	newFluxDoc := func(name string) fluxDoc {
		var fd fluxDoc
		fd.Kind = "Kustomization"
		fd.Metadata.Name = name
		return fd
	}

	DescribeTable("picks a handle that is STABLE and UNIQUE, because BySlug keeps the last writer and a collapsed slug silently redirects every covers/colocation/staleness verdict to the wrong component",
		func(slugFrom, base, metaName string, inFile int, want string) {
			cfg := &Config{Components: ComponentSource{SlugFrom: slugFrom}}

			Expect(slugFor(cfg, base, newFluxDoc(metaName), inFile)).To(Equal(want))
		},
		Entry("a file declaring one Kustomization slugs by FILENAME, because metadata.name drifts from it and a handle that moves when a field is edited is not a handle",
			"", "external-secrets", "external-secrets-operator", 1, "external-secrets"),
		Entry("a file declaring TWO Kustomizations slugs by metadata.name — this is the real bug: under filename-slugging both rows collapsed onto one key and covers: resolved to an arbitrary one of two different paths",
			"", "external-secrets", "external-secrets-operator", 2, "external-secrets-operator"),
		Entry("a three-document file also slugs by metadata.name, since the filename identifies three things",
			"", "security", "kyverno", 3, "kyverno"),
		Entry("slug_from: metadata.name overrides the filename preference even for a single-document file",
			"metadata.name", "external-secrets", "external-secrets-operator", 1, "external-secrets-operator"),
		Entry("an empty metadata.name falls back to the filename rather than producing an empty slug that matches nothing",
			"", "kube-system", "", 1, "kube-system"),
		Entry("an empty metadata.name in a multi-document file also falls back, because a usable duplicate beats an unusable blank",
			"", "kube-system", "", 3, "kube-system"),
		Entry("slug_from: metadata.name with no name falls back to the filename",
			"metadata.name", "kube-system", "", 1, "kube-system"),
	)
})

// --- matchAny --------------------------------------------------------------------------------

var _ = Describe("matchAny", Label("unit"), func() {
	DescribeTable("decides exclusion by glob OR by bare-prefix-as-directory, so a ported config spelling `docs/_archive` and one spelling `docs/_archive/**` behave identically",
		func(path string, patterns []string, want bool) {
			Expect(matchAny(path, patterns)).To(Equal(want))
		},
		Entry("a plain glob matches within one path segment",
			"README.md", []string{"*.md"}, true),
		Entry("a glob does not cross a separator, which is why the prefix branch exists at all",
			"docs/a.md", []string{"*.md"}, false),
		Entry("a `dir/**` pattern excludes a direct child",
			"docs/_archive/old.md", []string{"docs/_archive/**"}, true),
		Entry("a `dir/**` pattern also excludes a DEEP descendant, which filepath.Match alone would miss",
			"docs/_archive/2024/old.md", []string{"docs/_archive/**"}, true),
		Entry("the same directory spelled bare excludes the same deep descendant",
			"docs/_archive/2024/old.md", []string{"docs/_archive"}, true),
		Entry("a bare directory pattern matches the directory path itself",
			"docs/_archive", []string{"docs/_archive"}, true),
		Entry("a sibling sharing a textual prefix is NOT excluded, because the prefix branch appends a separator",
			"docs/_archived-notes/x.md", []string{"docs/_archive"}, false),
		Entry("an unrelated path is kept",
			"docs/01-getting-started/quickstart.md", []string{"docs/_archive/**"}, false),
		Entry("an empty pattern list excludes nothing",
			"docs/a.md", nil, false),
		Entry("the first matching pattern wins out of several",
			"node_modules/pkg/README.md", []string{"docs/_archive", "node_modules"}, true),
	)
})

// --- countNested -----------------------------------------------------------------------------

var _ = Describe("countNested", Label("unit"), func() {
	// The two spellings are asserted SEPARATELY on purpose. A single mixed fixture with one
	// decoy cancels its own mutation: flipping the `.yml` test to `!=` stops the .yml file
	// counting and starts the README counting, and the total is 3 either way — so the combined
	// assertion below is real coverage only because each spelling is also pinned alone.
	It("counts .yaml kustomizations at every depth and nothing else", func() {
		root := GinkgoT().TempDir()
		unitWrite(root, "infrastructure/base/monitoring/kustomization.yaml", "resources: []\n")
		unitWrite(root, "infrastructure/base/monitoring/loki/kustomization.yaml", "resources: []\n")
		unitWrite(root, "infrastructure/base/monitoring/README.md", "# not a kustomization\n")
		unitWrite(root, "infrastructure/base/monitoring/loki/values.yaml", "replicas: 1\n")

		Expect(countNested(root, "infrastructure/base/monitoring")).To(Equal(2),
			"a decoy .md and a decoy .yaml that is not a kustomization must both be ignored")
	})

	// TWO decoys, not one. With a single decoy this fixture cancels its own mutation for the
	// second time: flipping the `.yml` test to `!=` stops the manifest counting and starts the
	// decoy counting, and the total is 1 either way. Two decoys make the mutated count 2.
	It("counts the .yml spelling too, because a repo that uses it would otherwise report zero nested units", func() {
		root := GinkgoT().TempDir()
		unitWrite(root, "infrastructure/base/monitoring/mimir/deep/kustomization.yml", "resources: []\n")
		unitWrite(root, "infrastructure/base/monitoring/README.md", "# not a kustomization\n")
		unitWrite(root, "infrastructure/base/monitoring/mimir/values.yaml", "replicas: 1\n")

		Expect(countNested(root, "infrastructure/base/monitoring")).To(Equal(1))
	})

	It("counts kustomization manifests at every depth under a component path, which is the measurement behind the directory-shape smell", func() {
		root := GinkgoT().TempDir()
		unitWrite(root, "infrastructure/base/monitoring/kustomization.yaml", "resources: []\n")
		unitWrite(root, "infrastructure/base/monitoring/loki/kustomization.yaml", "resources: []\n")
		unitWrite(root, "infrastructure/base/monitoring/mimir/deep/kustomization.yml", "resources: []\n")
		unitWrite(root, "infrastructure/base/monitoring/README.md", "# not a kustomization\n")

		Expect(countNested(root, "infrastructure/base/monitoring")).To(Equal(3))
	})

	It("returns zero for a path that does not exist instead of failing the whole scan, because a dangling spec.path is reported by its own rule", func() {
		Expect(countNested(GinkgoT().TempDir(), "infrastructure/base/gone")).To(Equal(0))
	})
})

// --- fluxStrategy / dirsStrategy ---------------------------------------------------------------------

var _ = Describe("fluxStrategy.Enumerate", Label("unit"), func() {
	var root string
	var cfg *Config

	BeforeEach(func() {
		root = GinkgoT().TempDir()
		cfg = &Config{Components: ComponentSource{Kind: "flux", Path: "clusters/test", Glob: "*.yaml"}}
	})

	It("decodes EVERY document in a multi-document manifest and gives each its own slug, so two Kustomizations in one file stay two components", func() {
		unitWrite(root, "clusters/test/external-secrets.yaml",
			unitFlux("external-secrets-operator", "./infrastructure/base/external-secrets/operator")+
				"---\n"+unitFlux("external-secrets", "./infrastructure/base/external-secrets/stores"))

		comps := unitEnumerate(fluxStrategy{}, root, cfg)

		Expect(comps).To(HaveLen(2), "decoding only the first document would silently drop a deployed unit")
		Expect([]string{comps[0].Slug, comps[1].Slug}).To(ConsistOf("external-secrets-operator", "external-secrets"))
		Expect([]string{comps[0].Path, comps[1].Path}).To(ConsistOf(
			"infrastructure/base/external-secrets/operator",
			"infrastructure/base/external-secrets/stores"))
	})

	It("strips the leading ./ from spec.path so the stored path is repo-relative and joinable with Root", func() {
		unitWrite(root, "clusters/test/cilium.yaml", unitFlux("cilium-cni", "./infrastructure/base/cilium"))

		comps := unitEnumerate(fluxStrategy{}, root, cfg)

		Expect(comps).To(HaveLen(1))
		Expect(comps[0].Path).To(Equal("infrastructure/base/cilium"))
		Expect(comps[0].Slug).To(Equal("cilium"), "a single-document file slugs by filename")
		Expect(comps[0].Name).To(Equal("cilium-cni"), "metadata.name is kept alongside the slug because the two drift")
		Expect(comps[0].Source).To(Equal(filepath.Join("clusters", "test", "cilium.yaml")))
	})

	It("counts only Kustomization documents when deciding whether a file declares more than one, so a Kustomization sharing a file with a HelmRelease still slugs by filename", func() {
		unitWrite(root, "clusters/test/traefik.yaml",
			unitFlux("traefik-ingress", "./infrastructure/base/traefik")+
				"---\napiVersion: helm.toolkit.fluxcd.io/v2\nkind: HelmRelease\nmetadata:\n  name: traefik\n")

		comps := unitEnumerate(fluxStrategy{}, root, cfg)

		Expect(comps).To(HaveLen(1))
		Expect(comps[0].Slug).To(Equal("traefik"))
	})

	It("skips a Kustomization with no usable spec.path rather than inventing a component rooted at the repo, which would make every colocation verdict meaningless", func() {
		unitWrite(root, "clusters/test/broken.yaml",
			"kind: Kustomization\nmetadata:\n  name: broken\nspec:\n  path: ./\n"+
				"---\n"+unitFlux("good", "./infrastructure/base/good"))

		comps := unitEnumerate(fluxStrategy{}, root, cfg)

		Expect(comps).To(HaveLen(1))
		Expect(comps[0].Name).To(Equal("good"))
	})

	It("records dependsOn names, dropping unnamed entries, because those names are the only cross-component edges the model has", func() {
		unitWrite(root, "clusters/test/apps.yaml",
			unitFlux("apps", "./applications")+"  dependsOn:\n    - name: cilium\n    - name: \"\"\n    - name: traefik\n")

		comps := unitEnumerate(fluxStrategy{}, root, cfg)

		Expect(comps).To(HaveLen(1))
		Expect(comps[0].DependsOn).To(Equal([]string{"cilium", "traefik"}))
	})

	It("reads spec.suspend so a suspended component is distinguishable from a live one", func() {
		unitWrite(root, "clusters/test/paused.yaml",
			unitFlux("paused", "./infrastructure/base/paused")+"  suspend: true\n")

		comps := unitEnumerate(fluxStrategy{}, root, cfg)

		Expect(comps).To(HaveLen(1))
		Expect(comps[0].Suspend).To(BeTrue())
	})

	// Nested is the ONLY input to component-shape, and nothing else in this suite observed it
	// coming out of the flux strategy — the rule's own specs build Component{Nested: n} by hand. That
	// left the wiring untested: dropping the countNested call here silently disabled the rule
	// for every Flux component in the repo while every shape spec stayed green.
	It("counts the nested kustomizations under spec.path, which is the only thing that feeds component-shape", func() {
		unitWrite(root, "clusters/test/monitoring.yaml", unitFlux("monitoring", "./infrastructure/base/monitoring"))
		unitWrite(root, "infrastructure/base/monitoring/kustomization.yaml", "resources: []\n")
		unitWrite(root, "infrastructure/base/monitoring/loki/kustomization.yaml", "resources: []\n")
		unitWrite(root, "infrastructure/base/monitoring/mimir/kustomization.yaml", "resources: []\n")
		unitWrite(root, "infrastructure/base/monitoring/mimir/deep/kustomization.yml", "resources: []\n")
		unitWrite(root, "infrastructure/base/monitoring/README.md", "# not a kustomization\n")

		comps := unitEnumerate(fluxStrategy{}, root, cfg)

		Expect(comps).To(HaveLen(1))
		Expect(comps[0].Nested).To(Equal(4),
			"a zero here would switch component-shape off for every Flux component without failing anything else")
	})

	It("records zero nested kustomizations for a component whose directory holds none, so the shape rule is not tripped by an absent count", func() {
		unitWrite(root, "clusters/test/cilium.yaml", unitFlux("cilium", "./infrastructure/base/cilium"))
		unitWrite(root, "infrastructure/base/cilium/README.md", "# no kustomization here\n")

		comps := unitEnumerate(fluxStrategy{}, root, cfg)

		Expect(comps).To(HaveLen(1))
		Expect(comps[0].Nested).To(Equal(0))
	})

	It("counts each document's OWN spec.path in a multi-document file, rather than sharing one count across both", func() {
		unitWrite(root, "clusters/test/external-secrets.yaml",
			unitFlux("external-secrets-operator", "./infrastructure/base/external-secrets/operator")+
				"---\n"+unitFlux("external-secrets", "./infrastructure/base/external-secrets/stores"))
		unitWrite(root, "infrastructure/base/external-secrets/operator/kustomization.yaml", "resources: []\n")
		unitWrite(root, "infrastructure/base/external-secrets/stores/kustomization.yaml", "resources: []\n")
		unitWrite(root, "infrastructure/base/external-secrets/stores/a/kustomization.yaml", "resources: []\n")
		unitWrite(root, "infrastructure/base/external-secrets/stores/b/kustomization.yaml", "resources: []\n")

		byName := map[string]int{}
		for _, c := range unitEnumerate(fluxStrategy{}, root, cfg) {
			byName[c.Name] = c.Nested
		}

		Expect(byName).To(HaveKeyWithValue("external-secrets-operator", 1))
		Expect(byName).To(HaveKeyWithValue("external-secrets", 3))
	})

	It("warns and returns nothing when no manifest matches, instead of aborting — an unadopted repo must still get a usable lint run", func() {
		Expect(unitEnumerate(fluxStrategy{}, root, cfg)).To(BeEmpty())
	})

	It("returns components in a deterministic filename order, so report output does not churn between runs", func() {
		unitWrite(root, "clusters/test/zeta.yaml", unitFlux("zeta", "./z"))
		unitWrite(root, "clusters/test/alpha.yaml", unitFlux("alpha", "./a"))

		comps := unitEnumerate(fluxStrategy{}, root, cfg)

		Expect([]string{comps[0].Slug, comps[1].Slug}).To(Equal([]string{"alpha", "zeta"}))
	})
})

var _ = Describe("dirsStrategy.Enumerate and EnumerateComponents", Label("unit"), func() {
	It("treats each directory as a component and ignores loose files, which is the fallback for a repo with no GitOps controller", func() {
		root := GinkgoT().TempDir()
		unitWrite(root, "infrastructure/base/alpha/kustomization.yaml", "resources: []\n")
		unitWrite(root, "infrastructure/base/beta/kustomization.yaml", "resources: []\n")
		unitWrite(root, "infrastructure/base/notes.md", "# loose file\n")
		cfg := &Config{Components: ComponentSource{Kind: "dirs", Path: "infrastructure/base", Glob: "*"}}

		comps := unitEnumerate(dirsStrategy{}, root, cfg)

		Expect(comps).To(HaveLen(2))
		Expect([]string{comps[0].Slug, comps[1].Slug}).To(Equal([]string{"alpha", "beta"}))
		Expect(comps[0].Path).To(Equal(filepath.Join("infrastructure", "base", "alpha")))
		Expect(comps[0].Nested).To(Equal(1))
	})

	// The tree is POPULATED on purpose. Against an empty TempDir every possible implementation
	// returns nil — falling through to loadDirs, falling through to loadFlux, or returning nil
	// deliberately — so the assertion held no matter what the switch did. Two component
	// directories make the dirs fallback observable: it would return two, and nil is then a
	// statement about the lookup rather than about the fixture.
	It("errors and loads nothing for an unknown components.kind, so a config typo degrades to an empty model rather than a panic", func() {
		root := GinkgoT().TempDir()
		unitWrite(root, "infrastructure/base/alpha/kustomization.yaml", "resources: []\n")
		unitWrite(root, "infrastructure/base/beta/kustomization.yaml", "resources: []\n")
		cfg := &Config{Components: ComponentSource{Kind: "helmfile", Path: "infrastructure/base", Glob: "*"}}

		enum, err := EnumerateComponents(root, cfg)

		Expect(err).To(HaveOccurred())
		Expect(enum.Components).To(BeNil(),
			"an unrecognised kind must not quietly fall through to the dirs strategy, which would "+
				"report two components a config typo never asked for")

		// Proof the fixture can actually produce a non-nil answer, which is what makes the
		// assertion above mean something.
		dirsCfg := &Config{Components: ComponentSource{Kind: "dirs", Path: "infrastructure/base", Glob: "*"}}
		ok, err := EnumerateComponents(root, dirsCfg)
		Expect(err).NotTo(HaveOccurred())
		Expect(ok.Components).To(HaveLen(2))
	})
})

// --- git-backed collection --------------------------------------------------------------------

var _ = Describe("git-backed collection", Label("unit"), func() {
	It("returns the start directory when it is not inside a repository, so the tool degrades instead of erroring out", func() {
		dir := GinkgoT().TempDir()

		Expect(git(dir, "rev-parse", "--show-toplevel")).To(BeEmpty())
		Expect(RepoRoot(dir)).To(Equal(dir))
	})

	It("walks up to the repository root from a nested directory, because every path in the model is stored relative to that root", func() {
		dir := GinkgoT().TempDir()
		unitInitRepo(dir)
		nested := filepath.Join(dir, "docs", "01-getting-started")
		Expect(os.MkdirAll(nested, 0o755)).To(Succeed())

		Expect(filepath.Base(RepoRoot(nested))).To(Equal(filepath.Base(dir)))
	})

	It("lists only TRACKED markdown, sorted and minus exclusions, because a raw filesystem walk also finds worktrees and gitignored copies", func() {
		dir := GinkgoT().TempDir()
		unitInitRepo(dir)
		unitWrite(dir, "README.md", "# Readme\n")
		unitWrite(dir, "docs/a.md", "# A\n")
		unitWrite(dir, "docs/_archive/old.md", "# Old\n")
		unitCommit(dir, "seed", "2020-01-02T03:04:05+00:00")
		unitWrite(dir, "untracked.md", "# Untracked\n")
		cfg := &Config{Exclude: []string{"docs/_archive/**"}}

		Expect(TrackedMarkdown(dir, cfg)).To(Equal([]string{"README.md", "docs/a.md"}))
	})

	It("parses every doc it lists, so LoadDocs and TrackedMarkdown can never disagree about the corpus", func() {
		dir := GinkgoT().TempDir()
		unitInitRepo(dir)
		unitWrite(dir, "docs/a.md", "---\ntype: reference\n---\n\n# A\n")
		unitCommit(dir, "seed", "2020-01-02T03:04:05+00:00")

		docs := LoadDocs(dir, &Config{})

		Expect(docs).To(HaveLen(1))
		Expect(docs[0].Path).To(Equal("docs/a.md"))
		Expect(docs[0].H1).To(Equal("A"))
	})

	It("records each file's MOST RECENT commit date from one git log pass, because per-file `git log -1` is one process per file", func() {
		dir := GinkgoT().TempDir()
		unitInitRepo(dir)
		// git --format=%cI renders a UTC offset as `Z`, so the committed input and the expected
		// output are spelled separately rather than assumed identical.
		const firstIn, firstOut = "2020-01-02T03:04:05+00:00", "2020-01-02T03:04:05Z"
		const secondIn, secondOut = "2021-06-07T08:09:10+00:00", "2021-06-07T08:09:10Z"
		unitWrite(dir, "docs/a.md", "# A\n")
		unitWrite(dir, "docs/b.md", "# B\n")
		unitCommit(dir, "first", firstIn)
		unitWrite(dir, "docs/a.md", "# A revised\n")
		unitCommit(dir, "second", secondIn)

		dates := LastCommitDates(dir)

		Expect(dates).To(HaveKeyWithValue("docs/a.md", secondOut), "git log is newest-first, so the first sighting is the latest touch")
		Expect(dates).To(HaveKeyWithValue("docs/b.md", firstOut), "a file untouched by the newer commit keeps its own date")
	})

	It("returns an empty map outside a repository rather than nil-panicking downstream", func() {
		Expect(LastCommitDates(GinkgoT().TempDir())).To(BeEmpty())
	})
})
