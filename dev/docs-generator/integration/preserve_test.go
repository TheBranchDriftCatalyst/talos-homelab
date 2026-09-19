package integration_test

import (
	"crypto/sha256"
	"encoding/hex"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

// Review mode.
//
// By default every fixture lives in a temp dir that Ginkgo deletes on exit, which is right for
// CI and useless for a human: after a green run there is nothing left to read, and a suite
// nobody can inspect is one nobody trusts enough to act on when it goes red.
//
// With preservation on, each spec's fixture is materialised at a STABLE path under
// integration/.artifacts/ and kept, alongside a transcript of every command the spec ran and
// both sides of every golden comparison. The path is deliberately not randomised or
// timestamped: the point is that it can be bookmarked, opened in an editor, and diffed against
// the previous run.
//
//	go test ./integration -args -preserve-artifacts
//	DOCSGEN_PRESERVE_ARTIFACTS=1 go run github.com/onsi/ginkgo/v2/ginkgo --label-filter=integration ./...
//
// PRESERVATION CHANGES WHERE FILES LIVE AND NOTHING ELSE. No assertion reads this flag. A spec
// that passes in one mode and fails in the other is a harness bug, not a tolerable difference.

var preserveFlag = flag.Bool("preserve-artifacts", false,
	"materialise fixtures under integration/.artifacts/ and keep them after the run, for review")

func preserving() bool {
	return *preserveFlag || os.Getenv("DOCSGEN_PRESERVE_ARTIFACTS") == "1"
}

// artifactsRoot is an absolute path so the line printed at the end of the run can be pasted
// straight into an editor. Specs run with the package directory as their working directory.
func artifactsRoot() string {
	abs, err := filepath.Abs(".artifacts")
	Expect(err).NotTo(HaveOccurred())
	return abs
}

// resetArtifactsRoot wipes the directory once, at the start of the run.
//
// Preserve means "survives this run", never "accumulates across runs". A file left over from a
// previous run quietly contaminating the next one is worse than not preserving at all, because
// it looks like evidence.
func resetArtifactsRoot() {
	if !preserving() {
		return
	}
	root := artifactsRoot()
	Expect(os.RemoveAll(root)).To(Succeed())
	Expect(os.MkdirAll(root, 0o755)).To(Succeed())
	Expect(os.WriteFile(filepath.Join(root, "README.md"), []byte(artifactsReadme), 0o644)).To(Succeed())
}

const artifactsReadme = "# docsgen integration artifacts\n" + `
Generated, gitignored, and wiped at the start of every preserved run. Nothing here is a source
file and nothing here should ever be committed.

## What produced it

    cd dev/docs-generator
    GOWORK=off go test ./integration -args -preserve-artifacts

or, through ginkgo:

    GOWORK=off DOCSGEN_PRESERVE_ARTIFACTS=1 \
      go run github.com/onsi/ginkgo/v2/ginkgo --label-filter=integration ./...

## Layout

    <sample>/<spec>/repo/        the fixture repository as the spec left it, including
                                 everything docsgen generated into it
    <sample>/<spec>/outside/     a sentinel tree no command is allowed to write to
    <sample>/<spec>/_runs/       one numbered transcript per docsgen invocation:
                                 NN-<command>.argv / .exit / .stdout / .stderr
    <sample>/<spec>/_golden/     both sides of every golden comparison, plus a .diff
                                 when they disagreed

The spec directory name is the spec's own text, slugified, with a short hash of the full text
appended so two similarly-worded specs cannot collide. It is stable across runs, so
` + "`diff -r`" + ` between two preserved runs is meaningful.

## Reading a failure

Start at ` + "`_runs/`" + `: the argv, exit code and both streams are all there, so a failure can be
reproduced by hand without re-running the suite. For a golden mismatch, read
` + "`_golden/<name>.diff`" + ` — it is written whenever the two sides differ, whether or not the
spec failed for another reason.
`

// specWorkDir returns the directory a fixture is built in: a throwaway temp dir normally, a
// stable reviewable path under .artifacts/ when preserving.
func specWorkDir(s *sample) string {
	GinkgoHelper()
	if !preserving() {
		tmp, err := filepath.EvalSymlinks(GinkgoT().TempDir())
		Expect(err).NotTo(HaveOccurred())
		return tmp
	}
	dir := filepath.Join(artifactsRoot(), s.Name, specSlug())
	Expect(os.RemoveAll(dir)).To(Succeed())
	Expect(os.MkdirAll(dir, 0o755)).To(Succeed())
	resolved, err := filepath.EvalSymlinks(dir)
	Expect(err).NotTo(HaveOccurred())
	return resolved
}

// specSlug names a directory after the spec that owns it. The hash suffix is a function of the
// spec text alone, so the name is identical on every run — which is what makes two preserved
// runs comparable with `diff -r`.
func specSlug() string {
	full := CurrentSpecReport().FullText()
	sum := sha256.Sum256([]byte(full))

	var b strings.Builder
	lastDash := false
	for _, r := range strings.ToLower(full) {
		switch {
		case (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9'):
			b.WriteRune(r)
			lastDash = false
		case !lastDash:
			b.WriteByte('-')
			lastDash = true
		}
	}
	slug := strings.Trim(b.String(), "-")
	if len(slug) > 72 {
		slug = strings.Trim(slug[:72], "-")
	}
	if slug == "" {
		slug = "spec"
	}
	return slug + "-" + hex.EncodeToString(sum[:])[:8]
}

// record writes one file into the fixture's review area. A no-op unless preserving.
func (f *fixture) record(sub, name, content string) {
	if !preserving() {
		return
	}
	dir := filepath.Join(f.Base, sub)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return // review material is never worth failing a spec over
	}
	_ = os.WriteFile(filepath.Join(dir, name), []byte(content), 0o644)
}

// recordRun transcribes one docsgen invocation so a failure can be reproduced by hand.
func (f *fixture) recordRun(args []string, res result) {
	if !preserving() {
		return
	}
	f.runSeq++
	cmd := "none"
	if len(args) > 0 {
		cmd = strings.TrimLeft(args[0], "-")
	}
	stem := fmt.Sprintf("%02d-%s", f.runSeq, cmd)
	f.record("_runs", stem+".argv", "docsgen "+strings.Join(args, " ")+"\n")
	f.record("_runs", stem+".exit", fmt.Sprintf("%d\n", res.Code))
	f.record("_runs", stem+".stdout", res.Out)
	f.record("_runs", stem+".stderr", res.Err)
}

var _ = ReportAfterSuite("preserved artifacts", func(Report) {
	if !preserving() {
		return
	}
	AddReportEntry("preserved artifacts", artifactsRoot())
	fmt.Fprintf(GinkgoWriter, "\n\nPreserved fixtures, transcripts and golden diffs:\n  %s\n\n",
		artifactsRoot())
})
