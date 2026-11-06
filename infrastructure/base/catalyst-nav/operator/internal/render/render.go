// Package render is the one-shot parity mode: stdin/stdout/stderr, byte-identical to
// `python3 build_nav.py`.
//
// THIS WAS THE AUDIT GATE THAT JUSTIFIED THE DELETION, and it still is the gate — but the
// other half of the diff is now data, not a process. infrastructure/base/themepark/server/nav/
// was deleted only once the operator's model provably agreed with the script's for the whole
// cluster, byte for byte; the script's output for every fixture is frozen in
// testdata/golden/build_nav_oracle.json and internal/render's tests diff against it.
//
// The old two-process recipe no longer runs, because build_nav.py is gone:
//
//	python3 infrastructure/base/themepark/server/nav/build_nav.py < /tmp/ir.json > /tmp/a.json   # DELETED
//
// What to run instead:
//
//	task nav:parity                                  # the committed corpus, both scopes
//	kubectl get ingressroutes.traefik.io -A -o json > /tmp/ir.json
//	catalyst-nav-operator render < /tmp/ir.json      # the LIVE cluster's manifest
//
// This mode deliberately takes the SAME input the sidecar did — a document on stdin — rather
// than talking to the apiserver itself. Reading the cluster twice would make a difference in
// the two reads look like a difference in the two models, and the whole value of the gate is
// that an empty diff means something. It is also what makes the frozen oracle meaningful: the
// recorded bytes are keyed by the exact stdin they were produced from.
package render

import (
	"encoding/json"
	"fmt"
	"io"
	"os"

	"github.com/TheBranchDriftCatalyst/talos-homelab/infrastructure/base/catalyst-nav/operator/internal/navmodel"
)

// Env is the environment the sidecar runs build_nav.py with, as a parameter so the
// differential test can vary it without touching the process environment.
type Env struct {
	Scope    string // NAV_SCOPE
	Defaults string // NAV_DEFAULTS
}

// EnvFromOS reads the two variables build_nav.py reads.
func EnvFromOS() Env {
	return Env{Scope: os.Getenv("NAV_SCOPE"), Defaults: os.Getenv("NAV_DEFAULTS")}
}

// Run reads a kubectl IngressRoute list from in, writes the manifest to out and refusal lines
// to logw. The return value is the process exit status; build_nav.py returns 0 for every input
// it can decode and raises for malformed JSON, which the supervision loop in discover.sh
// treats as "keep serving the previous manifest".
func Run(in io.Reader, out, logw io.Writer, env Env) error {
	raw, err := io.ReadAll(in)
	if err != nil {
		return fmt.Errorf("reading input: %w", err)
	}
	var doc navmodel.Doc
	if err := json.Unmarshal(raw, &doc); err != nil {
		// Matches the script's posture: a decode failure is fatal to THIS run and
		// discover.sh keeps the last good manifest in place. Silently emitting an empty
		// nav would be far worse — it would blank the bar on every app.
		return fmt.Errorf("input is not valid JSON: %w", err)
	}

	opts := navmodel.Options{
		// `os.environ.get("NAV_SCOPE", "themed").lower() != "all"` — anything other
		// than "all" (case-insensitively) keeps the derived filter, including nonsense.
		ScopeAll: lower(env.Scope) == "all",
		Defaults: navmodel.ParseNavDefaultsEnv(env.Defaults, logw),
		Log:      logw,
	}
	m := navmodel.Build(&doc, opts)
	if _, err := out.Write(navmodel.Encode(m)); err != nil {
		return fmt.Errorf("writing manifest: %w", err)
	}
	return nil
}

func lower(s string) string {
	b := []byte(s)
	for i := range b {
		if b[i] >= 'A' && b[i] <= 'Z' {
			b[i] += 'a' - 'A'
		}
	}
	return string(b)
}
