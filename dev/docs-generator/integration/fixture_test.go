package integration_test

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"time"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	"github.com/onsi/gomega/gexec"
)

// The fixture: a hand-written sample repo, copied into a temp dir and turned into a REAL git
// repository.
//
// The git part is the single most important line in this file. docsgen's file walker is
// `git ls-files` and its dates come from one `git log --name-only` pass, so a fixture that is
// merely a directory of files produces zero docs and zero dates. Every doc rule then finds
// nothing, `stale` prints nothing, and the whole suite passes while testing nothing. Set
// DOCSGEN_FIXTURE_SKIP_COMMIT=1 to reproduce exactly that and watch the suite go red — that is
// the vacuity check, and it is a one-command run rather than a code edit on purpose.

const (
	// Fixed commit timestamps. `stale` compares a doc's last commit against the last commit
	// touching the code it covers, and two commits landing inside one second compare EQUAL —
	// which empties the report and looks like a pass. Pinning both dates also keeps the `stale`
	// golden from changing every day.
	importDate = "2024-01-15T10:00:00+00:00"
	bumpDate   = "2024-06-20T09:30:00+00:00"

	// rootPlaceholder replaces the temp root in anything compared against a golden, so a path
	// leaking into output shows up as a readable diff instead of a golden that can never match.
	rootPlaceholder = "<ROOT>"
)

// gitEnv neutralises the developer's global git configuration so the fixture behaves the same
// here and on a CI box that has none. core.excludesFile matters most: a global gitignore would
// quietly hide files from `git ls-files`, which IS docsgen's walker.
var gitEnv = []string{
	"GIT_CONFIG_GLOBAL=/dev/null",
	"GIT_CONFIG_SYSTEM=/dev/null",
}

func skipCommit() bool { return os.Getenv("DOCSGEN_FIXTURE_SKIP_COMMIT") == "1" }

type fixture struct {
	Root   string
	Base   string // parent of Root; holds the sentinel tree and, when preserving, the transcripts
	Sample *sample
	runSeq int
}

// newFixture builds a private, throwaway copy of one sample for a single spec.
//
// The repo is placed at <tmp>/repo, leaving <tmp>/outside free as a sentinel: a command that
// writes above its own root shows up as a changed hash there.
func newFixture(s *sample) *fixture {
	GinkgoHelper()
	tmp := specWorkDir(s)

	root := filepath.Join(tmp, "repo")
	buildFixtureAt(root, s, !skipCommit())

	// git leaves loose objects and their parent directories read-only; RemoveAll cannot unlink
	// a file out of a directory it may not write. Restore write permission before Ginkgo's own
	// TempDir cleanup runs — registered here, so it runs first (cleanups are LIFO).
	DeferCleanup(func() { makeWritable(tmp) })

	outside := filepath.Join(tmp, "outside")
	Expect(os.MkdirAll(outside, 0o755)).To(Succeed())
	Expect(os.WriteFile(filepath.Join(outside, "sentinel.txt"),
		[]byte("nothing docsgen runs may touch this\n"), 0o644)).To(Succeed())

	return &fixture{Root: root, Base: tmp, Sample: s}
}

func (f *fixture) outsideDir() string { return filepath.Join(f.Base, "outside") }

func buildFixtureAt(root string, s *sample, commit bool) {
	GinkgoHelper()
	Expect(os.MkdirAll(root, 0o755)).To(Succeed())
	Expect(copyTree(sampleDir(s.Name), root)).To(Succeed(), "copying sample %s", s.Name)

	runGit(root, nil, "init", "-q", "-b", "main")
	// Set locally, because CI has no global identity and `git commit` refuses without one.
	runGit(root, nil, "config", "user.email", "fixture@example.invalid")
	runGit(root, nil, "config", "user.name", "docsgen fixture")
	// `git commit` fires `gc --auto` / `maintenance run --auto` in the BACKGROUND. That process
	// outlives the spec and is still writing into .git while Ginkgo's TempDir cleanup is
	// unlinking it, which surfaces as an intermittent "directory not empty" failure attributed
	// to whichever spec happened to be running. Turning both off makes the fixture's lifetime
	// entirely ours.
	runGit(root, nil, "config", "gc.auto", "0")
	runGit(root, nil, "config", "maintenance.auto", "false")

	if !commit {
		return // the vacuity switch — see the file comment
	}

	runGit(root, nil, "add", "-A")
	runGit(root, dateEnv(importDate), "commit", "-q", "-m", "import the sample repository")

	// A SECOND, later commit touching exactly one file. This is what moves the code ahead of
	// the docs and gives `stale` something true to find.
	subject := filepath.Join(root, s.StaleSubject)
	Expect(appendLine(subject, "\n# the code moved ahead of its documentation\n")).To(Succeed())
	runGit(root, nil, "add", "-A")
	runGit(root, dateEnv(bumpDate), "commit", "-q", "-m", "move the code ahead of the docs")
}

// makeWritable restores write permission across a tree so it can be deleted. Best effort by
// design: a cleanup failure must never be reported as a spec failure.
func makeWritable(root string) {
	_ = filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		info, statErr := d.Info()
		if statErr != nil {
			return nil
		}
		_ = os.Chmod(p, info.Mode().Perm()|0o200)
		return nil
	})
}

func dateEnv(d string) []string {
	return []string{"GIT_AUTHOR_DATE=" + d, "GIT_COMMITTER_DATE=" + d}
}

func runGit(dir string, extraEnv []string, args ...string) {
	GinkgoHelper()
	cmd := exec.Command("git", args...)
	cmd.Dir = dir
	cmd.Env = append(append(os.Environ(), gitEnv...), extraEnv...)
	out, err := cmd.CombinedOutput()
	Expect(err).NotTo(HaveOccurred(), "git %v in %s:\n%s", args, dir, out)
}

func copyTree(src, dst string) error {
	return filepath.WalkDir(src, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(src, p)
		if err != nil {
			return err
		}
		target := filepath.Join(dst, rel)
		if d.IsDir() {
			return os.MkdirAll(target, 0o755)
		}
		info, err := d.Info()
		if err != nil {
			return err
		}
		b, err := os.ReadFile(p)
		if err != nil {
			return err
		}
		return os.WriteFile(target, b, info.Mode().Perm())
	})
}

func appendLine(path, line string) error {
	fh, err := os.OpenFile(path, os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	defer fh.Close()
	_, err = fh.WriteString(line)
	return err
}

// --- driving the binary ----------------------------------------------------------------------

type result struct {
	Out     string
	Err     string
	Code    int
	Session *gexec.Session
}

// run invokes `docsgen <cmd> -root <fixture> -config <fixture> [extra…]`.
//
// -config is passed EVERY time and is not optional. main.go's defaultConfigDir resolves
// config.yaml from runtime.Caller, which for a gexec-built binary is the real source tree — so
// a run without -config silently lints the fixture against talos-homelab's taxonomy.
func (f *fixture) run(args ...string) result {
	GinkgoHelper()
	Expect(args).NotTo(BeEmpty())
	full := append([]string{args[0], "-root", f.Root, "-config", f.Root}, args[1:]...)
	return f.runRaw(full...)
}

// runRaw passes argv through untouched, for the specs that are about argv itself.
func (f *fixture) runRaw(args ...string) result {
	GinkgoHelper()
	cmd := exec.Command(binPath, args...)
	cmd.Dir = f.Root
	cmd.Env = append(os.Environ(), gitEnv...)

	var out, errb bytes.Buffer
	session, err := gexec.Start(cmd,
		io.MultiWriter(GinkgoWriter, &out),
		io.MultiWriter(GinkgoWriter, &errb))
	Expect(err).NotTo(HaveOccurred(), "starting docsgen %v", args)
	Eventually(session, 60*time.Second).Should(gexec.Exit())

	res := result{Out: out.String(), Err: errb.String(), Code: session.ExitCode(), Session: session}
	f.recordRun(args, res)
	return res
}

// --- observing the fixture ---------------------------------------------------------------------

const artifactRel = "docs/07-reference/component-inventory.md"

func (f *fixture) path(rel string) string { return filepath.Join(f.Root, rel) }

func (f *fixture) artifact() string { return f.path(artifactRel) }

func (f *fixture) read(rel string) string {
	GinkgoHelper()
	b, err := os.ReadFile(f.path(rel))
	Expect(err).NotTo(HaveOccurred(), "reading %s", rel)
	return string(b)
}

func (f *fixture) write(rel, content string) {
	GinkgoHelper()
	Expect(os.MkdirAll(filepath.Dir(f.path(rel)), 0o755)).To(Succeed())
	Expect(os.WriteFile(f.path(rel), []byte(content), 0o644)).To(Succeed())
}

func (f *fixture) exists(rel string) bool {
	_, err := os.Stat(f.path(rel))
	return err == nil
}

// scrub replaces the temp root with a fixed placeholder. Golden files must be reproducible from
// any temp directory on any machine, so an absolute path may never reach one.
func (f *fixture) scrub(s string) string {
	return strings.ReplaceAll(s, f.Root, rootPlaceholder)
}

// treeHash fingerprints the whole working tree: every path, its permissions and its content.
//
// .git is skipped because git itself rewrites index stat data as a side effect of the `ls-files`
// and `log` calls docsgen makes, which has nothing to do with whether docsgen wrote anything.
func (f *fixture) treeHash() string { return hashTree(f.Root) }

func hashTree(root string) string {
	GinkgoHelper()
	var entries []string
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
		rel, err := filepath.Rel(root, p)
		if err != nil {
			return err
		}
		info, err := d.Info()
		if err != nil {
			return err
		}
		b, err := os.ReadFile(p)
		if err != nil {
			return err
		}
		entries = append(entries, fmt.Sprintf("%s\x00%04o\x00%x", rel, info.Mode().Perm(), sha256.Sum256(b)))
		return nil
	})).To(Succeed())

	sort.Strings(entries)
	h := sha256.New()
	for _, e := range entries {
		h.Write([]byte(e))
		h.Write([]byte{'\n'})
	}
	return hex.EncodeToString(h.Sum(nil))
}

// tempArtifacts finds any surviving .docsgen-*.tmp. writeAtomic creates one in the target
// directory and renames it away; a survivor means a run died mid-write or leaked.
func (f *fixture) tempArtifacts() []string {
	GinkgoHelper()
	var found []string
	Expect(filepath.WalkDir(f.Root, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			if d.Name() == ".git" {
				return fs.SkipDir
			}
			return nil
		}
		if strings.HasPrefix(d.Name(), ".docsgen-") && strings.HasSuffix(d.Name(), ".tmp") {
			rel, _ := filepath.Rel(f.Root, p)
			found = append(found, rel)
		}
		return nil
	})).To(Succeed())
	return found
}

func (f *fixture) modTime(rel string) time.Time {
	GinkgoHelper()
	info, err := os.Stat(f.path(rel))
	Expect(err).NotTo(HaveOccurred())
	return info.ModTime()
}

func (f *fixture) mode(rel string) os.FileMode {
	GinkgoHelper()
	info, err := os.Stat(f.path(rel))
	Expect(err).NotTo(HaveOccurred())
	return info.Mode().Perm()
}

// backdate pushes a file's mtime into the past so that "did the second run rewrite it?" is
// answerable. Without this a rewrite landing inside the same filesystem timestamp tick is
// indistinguishable from no write at all, and the idempotency spec passes either way.
func (f *fixture) backdate(rel string) time.Time {
	GinkgoHelper()
	past := time.Now().Add(-72 * time.Hour).Truncate(time.Second)
	Expect(os.Chtimes(f.path(rel), past, past)).To(Succeed())
	return f.modTime(rel)
}

// componentRow returns the `docsgen components` row for one slug, or "" when absent.
func componentRow(out, slug string) string {
	for _, line := range strings.Split(out, "\n") {
		if fields := strings.Fields(line); len(fields) > 0 && fields[0] == slug {
			return line
		}
	}
	return ""
}

// findingsFor extracts the reported lines for one rule out of `docsgen lint` stdout.
func findingsFor(out, rule string) []string {
	var lines []string
	inRule := false
	for _, line := range strings.Split(out, "\n") {
		if strings.HasPrefix(line, rule+"  [") {
			inRule = true
			continue
		}
		if inRule {
			if !strings.HasPrefix(line, "  ") || strings.TrimSpace(line) == "" {
				break
			}
			lines = append(lines, strings.TrimSpace(line))
		}
	}
	return lines
}
