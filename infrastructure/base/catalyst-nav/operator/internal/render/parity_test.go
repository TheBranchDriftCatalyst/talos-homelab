package render

// THE PARITY PROOF. Runs the real infrastructure/base/themepark/server/nav/build_nav.py and
// this package over the same inputs and compares BYTES.
//
// Why differential rather than golden files: a golden file records what the port does today
// and would be regenerated from the port the first time it disagreed with the script. Running
// the script makes the SCRIPT the oracle, which is the only arrangement in which an empty diff
// means the migration is safe. Every "new coverage" spec in navmodel's table tests was written
// against the script's behaviour and verified here — not asserted from a reading of it.
//
// Skips cleanly when python3 is unavailable (CI runs Python, so this is about a bare dev box,
// not about letting the gate be optional). Phase 6 must not be signed off on a skipped run —
// see the t.Log in TestParityOnClusterCorpus.

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// buildNavPy locates the script relative to this file: .../infrastructure/base/catalyst-nav/
// operator/internal/render -> up five to infrastructure/base.
func buildNavPy(t *testing.T) string {
	t.Helper()
	wd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	p := filepath.Join(wd, "..", "..", "..", "..", "themepark", "server", "nav", "build_nav.py")
	abs, err := filepath.Abs(p)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(abs); err != nil {
		t.Fatalf("build_nav.py not found at %s: %v\n"+
			"If phase 6 has already deleted it, this test must be deleted in the SAME "+
			"commit, with the final diff recorded in the commit message.", abs, err)
	}
	return abs
}

func python(t *testing.T) string {
	t.Helper()
	p, err := exec.LookPath("python3")
	if err != nil {
		t.Skip("python3 not on PATH; the parity gate cannot run on this machine")
	}
	return p
}

// runPython drives the script exactly as discover.sh does.
func runPython(t *testing.T, script, input string, env Env) (stdout, stderr string) {
	t.Helper()
	cmd := exec.Command(python(t), script)
	cmd.Stdin = strings.NewReader(input)
	var out, errb bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &errb
	cmd.Env = append(os.Environ(), "NAV_SCOPE="+env.Scope, "NAV_DEFAULTS="+env.Defaults)
	if err := cmd.Run(); err != nil {
		t.Fatalf("build_nav.py failed: %v\nstderr: %s", err, errb.String())
	}
	return out.String(), errb.String()
}

func runGo(t *testing.T, input string, env Env) (stdout, stderr string) {
	t.Helper()
	var out, errb bytes.Buffer
	if err := Run(strings.NewReader(input), &out, &errb, env); err != nil {
		t.Fatalf("render.Run failed: %v", err)
	}
	return out.String(), errb.String()
}

// assertParity is the whole point: identical bytes on stdout, and the same refusal reasons on
// stderr.
func assertParity(t *testing.T, name, input string, env Env) {
	t.Helper()
	script := buildNavPy(t)
	pyOut, pyErr := runPython(t, script, input, env)
	goOut, goErr := runGo(t, input, env)
	if pyOut != goOut {
		t.Errorf("%s: MANIFEST BYTES DIFFER\n  python: %s\n      go: %s", name, pyOut, goOut)
	}
	// stderr is compared by reason, not verbatim: the script interleaves applet-name
	// progress lines with refusals and the order of the two passes is not part of the
	// contract. The REASONS are, because tests/nav/test_build_nav.py asserts on them.
	if gotPy, gotGo := reasons(pyErr), reasons(goErr); gotPy != gotGo {
		t.Errorf("%s: refusal reasons differ\n  python: %v\n      go: %v", name, gotPy, gotGo)
	}
}

func reasons(stderr string) string {
	var got []string
	for _, line := range strings.Split(stderr, "\n") {
		if line == "" || !strings.HasPrefix(line, "[nav] ") {
			continue
		}
		got = append(got, line)
	}
	// Sorted: the two implementations are free to log in a different order within a pass.
	for i := range got {
		for j := i + 1; j < len(got); j++ {
			if got[j] < got[i] {
				got[i], got[j] = got[j], got[i]
			}
		}
	}
	return strings.Join(got, "\n")
}

// TestParityOnClusterCorpus is the gate phase 6 depends on. The corpus is every IngressRoute
// object committed in this repo, captured by testdata/extract-corpus.sh.
func TestParityOnClusterCorpus(t *testing.T) {
	corpus := filepath.Join("..", "..", "testdata", "cluster-ingressroutes.json")
	b, err := os.ReadFile(corpus)
	if err != nil {
		t.Fatalf("corpus missing (%v); regenerate with testdata/extract-corpus.sh", err)
	}
	input := string(b)
	for _, env := range []Env{
		{},             // default: NAV_SCOPE=themed
		{Scope: "all"}, // the escape hatch
		{Scope: "all", Defaults: `{"revealAt":4}`}, // cluster-wide defaults
		{Defaults: `{"fx":false,"intensity":1}`},   // intensity 1 -> must render 1.0
		{Defaults: `{"notAKey":1,"mode":"push"}`},  // key filtering
		{Defaults: `[1]`},                          // non-object: ignored with a log
		{Scope: "ALL"},                             // .lower() on NAV_SCOPE
		{Scope: "themed-ish"},                      // anything != all keeps the filter
	} {
		name := "scope=" + env.Scope + " defaults=" + env.Defaults
		t.Run(name, func(t *testing.T) { assertParity(t, name, input, env) })
	}
	t.Logf("parity corpus: %d bytes of IngressRoute JSON", len(b))
}

// TestParityOnEdgeCases pins the cases a real cluster does not currently contain. Each one is
// a branch in build_nav.py that the corpus does not reach, so without these the corpus run
// could pass while the branch was wrong.
func TestParityOnEdgeCases(t *testing.T) {
	const mwNav = `[{"name":"catalyst-nav","namespace":"traefik"}]`
	cases := map[string]string{
		"empty document": `{"items":[]}`,
		"no items key":   `{}`,
		// `{"items":null}` is NOT here: it crashes build_nav.py, so there is no oracle
		// output to compare against. See TestNullItemsDivergesFromBuildNavPy, which pins
		// both the crash and this port's refusal to reproduce it.

		"metadata.name absent, host fallback titled": `{"items":[{"metadata":{"namespace":"x",
			"annotations":{"gethomepage.dev/enabled":"true"}},
			"spec":{"routes":[{"match":"Host(` + "`grafana.talos00`" + `)","middlewares":` + mwNav + `}]}}]}`,

		"metadata.name hyphenated gets both halves titled": `{"items":[{"metadata":{"name":"kube-ops-view","namespace":"x",
			"annotations":{"gethomepage.dev/enabled":"true"}},
			"spec":{"routes":[{"match":"Host(` + "`k.talos00`" + `)","middlewares":` + mwNav + `}]}}]}`,

		"metadata.name present but empty": `{"items":[{"metadata":{"name":"","namespace":"x",
			"annotations":{"gethomepage.dev/enabled":"true"}},
			"spec":{"routes":[{"match":"Host(` + "`e.talos00`" + `)","middlewares":` + mwNav + `}]}}]}`,

		"no annotations at all": `{"items":[{"metadata":{"name":"x","namespace":"x"},
			"spec":{"routes":[{"match":"Host(` + "`x.talos00`" + `)"}]}}]}`,

		"no spec.routes": `{"items":[{"metadata":{"name":"x","namespace":"x",
			"annotations":{"gethomepage.dev/enabled":"true"}},"spec":{}}]}`,

		"routes null": `{"items":[{"metadata":{"name":"x","namespace":"x",
			"annotations":{"gethomepage.dev/enabled":"true"}},"spec":{"routes":null}}]}`,

		"private hostname skipped": `{"items":[{"metadata":{"name":"x","namespace":"x",
			"annotations":{"gethomepage.dev/enabled":"true"}},
			"spec":{"routes":[{"match":"Host(` + "`a.priv.talos00`" + `)","middlewares":` + mwNav + `}]}}]}`,

		"plain route preferred over PathPrefix": `{"items":[{"metadata":{"name":"x","namespace":"x",
			"annotations":{"gethomepage.dev/enabled":"true"}},"spec":{"routes":[
			{"match":"Host(` + "`assets.talos00`" + `) && PathPrefix(` + "`/catalyst/`" + `)","middlewares":` + mwNav + `},
			{"match":"Host(` + "`app.talos00`" + `)","middlewares":` + mwNav + `}]}}]}`,

		"only a PathPrefix route": `{"items":[{"metadata":{"name":"x","namespace":"x",
			"annotations":{"gethomepage.dev/enabled":"true"}},"spec":{"routes":[
			{"match":"Host(` + "`only.talos00`" + `) && PathPrefix(` + "`/x/`" + `)","middlewares":` + mwNav + `}]}}]}`,

		"multiple Host clauses take the first": `{"items":[{"metadata":{"name":"x","namespace":"x",
			"annotations":{"gethomepage.dev/enabled":"true"}},"spec":{"routes":[
			{"match":"Host(` + "`first.talos00`" + `) || Host(` + "`second.talos00`" + `)","middlewares":` + mwNav + `}]}}]}`,

		"dedup keeps themed, themed second": `{"items":[
			{"metadata":{"name":"a","namespace":"x","annotations":{"gethomepage.dev/enabled":"true","gethomepage.dev/name":"A"}},
			 "spec":{"routes":[{"match":"Host(` + "`d.talos00`" + `)","middlewares":` + mwNav + `}]}},
			{"metadata":{"name":"b","namespace":"x","annotations":{"gethomepage.dev/enabled":"true","gethomepage.dev/name":"B"}},
			 "spec":{"routes":[{"match":"Host(` + "`d.talos00`" + `)","middlewares":[{"name":"catalyst-sonarr","namespace":"traefik"}]}]}}]}`,

		"dedup keeps themed, themed first": `{"items":[
			{"metadata":{"name":"b","namespace":"x","annotations":{"gethomepage.dev/enabled":"true","gethomepage.dev/name":"B"}},
			 "spec":{"routes":[{"match":"Host(` + "`d.talos00`" + `)","middlewares":[{"name":"catalyst-sonarr","namespace":"traefik"}]}]}},
			{"metadata":{"name":"a","namespace":"x","annotations":{"gethomepage.dev/enabled":"true","gethomepage.dev/name":"A"}},
			 "spec":{"routes":[{"match":"Host(` + "`d.talos00`" + `)","middlewares":` + mwNav + `}]}}]}`,

		// The latent staleHostConfig bug. If this case ever diverges, build_nav.py was
		// fixed and derive.go's deliberate reproduction must be revisited.
		"stale host config from the losing route": `{"items":[
			{"metadata":{"name":"a","namespace":"x","annotations":{"gethomepage.dev/enabled":"true","gethomepage.dev/name":"A","catalyst.nav/height":"40"}},
			 "spec":{"routes":[{"match":"Host(` + "`s.talos00`" + `)","middlewares":` + mwNav + `}]}},
			{"metadata":{"name":"b","namespace":"x","annotations":{"gethomepage.dev/enabled":"true","gethomepage.dev/name":"B"}},
			 "spec":{"routes":[{"match":"Host(` + "`s.talos00`" + `)","middlewares":[{"name":"catalyst-sonarr","namespace":"traefik"}]}]}}]}`,

		"all seven config keys in table order": `{"items":[{"metadata":{"name":"x","namespace":"x","annotations":{
			"gethomepage.dev/enabled":"true","gethomepage.dev/name":"X",
			"catalyst.nav/fx":"true","catalyst.nav/mode":"push","catalyst.nav/height":"60",
			"catalyst.nav/intensity":"1","catalyst.nav/reveal-at":"4",
			"catalyst.nav/hide-past":"200","catalyst.nav/scroll-reveal":"true"}},
			"spec":{"routes":[{"match":"Host(` + "`c.talos00`" + `)","middlewares":` + mwNav + `}]}}]}`,

		"fractional intensity": `{"items":[{"metadata":{"name":"x","namespace":"x","annotations":{
			"gethomepage.dev/enabled":"true","catalyst.nav/intensity":"0.25"}},
			"spec":{"routes":[{"match":"Host(` + "`i.talos00`" + `)","middlewares":` + mwNav + `}]}}]}`,

		"zero intensity": `{"items":[{"metadata":{"name":"x","namespace":"x","annotations":{
			"gethomepage.dev/enabled":"true","catalyst.nav/intensity":"0"}},
			"spec":{"routes":[{"match":"Host(` + "`z.talos00`" + `)","middlewares":` + mwNav + `}]}}]}`,

		"malformed config values are dropped": `{"items":[{"metadata":{"name":"x","namespace":"x","annotations":{
			"gethomepage.dev/enabled":"true",
			"catalyst.nav/mode":"sideways","catalyst.nav/height":"tall",
			"catalyst.nav/reveal-at":"40.5","catalyst.nav/intensity":"-1",
			"catalyst.nav/hide-past":""}},
			"spec":{"routes":[{"match":"Host(` + "`m.talos00`" + `)","middlewares":` + mwNav + `}]}}]}`,

		"non-finite intensity spellings": `{"items":[{"metadata":{"name":"x","namespace":"x","annotations":{
			"gethomepage.dev/enabled":"true","catalyst.nav/intensity":"inf"}},
			"spec":{"routes":[{"match":"Host(` + "`inf.talos00`" + `)","middlewares":` + mwNav + `}]}},
			{"metadata":{"name":"y","namespace":"x","annotations":{
			"gethomepage.dev/enabled":"true","catalyst.nav/intensity":"nan"}},
			"spec":{"routes":[{"match":"Host(` + "`nan.talos00`" + `)","middlewares":` + mwNav + `}]}},
			{"metadata":{"name":"z","namespace":"x","annotations":{
			"gethomepage.dev/enabled":"true","catalyst.nav/intensity":"Infinity"}},
			"spec":{"routes":[{"match":"Host(` + "`infinity.talos00`" + `)","middlewares":` + mwNav + `}]}}]}`,

		"malformed bool becomes false not dropped": `{"items":[{"metadata":{"name":"x","namespace":"x","annotations":{
			"gethomepage.dev/enabled":"true","catalyst.nav/fx":"maybe","catalyst.nav/scroll-reveal":"ja"}},
			"spec":{"routes":[{"match":"Host(` + "`b.talos00`" + `)","middlewares":` + mwNav + `}]}}]}`,

		"bool truthy spellings": `{"items":[{"metadata":{"name":"x","namespace":"x","annotations":{
			"gethomepage.dev/enabled":"true","catalyst.nav/fx":" YES ","catalyst.nav/scroll-reveal":"On"}},
			"spec":{"routes":[{"match":"Host(` + "`t.talos00`" + `)","middlewares":` + mwNav + `}]}}]}`,

		"weight python int spellings": `{"items":[
			{"metadata":{"name":"a","namespace":"x","annotations":{"gethomepage.dev/enabled":"true","gethomepage.dev/name":"A","gethomepage.dev/weight":" 70 "}},
			 "spec":{"routes":[{"match":"Host(` + "`w1.talos00`" + `)","middlewares":` + mwNav + `}]}},
			{"metadata":{"name":"b","namespace":"x","annotations":{"gethomepage.dev/enabled":"true","gethomepage.dev/name":"B","gethomepage.dev/weight":"+30"}},
			 "spec":{"routes":[{"match":"Host(` + "`w2.talos00`" + `)","middlewares":` + mwNav + `}]}},
			{"metadata":{"name":"c","namespace":"x","annotations":{"gethomepage.dev/enabled":"true","gethomepage.dev/name":"C","gethomepage.dev/weight":"-10"}},
			 "spec":{"routes":[{"match":"Host(` + "`w3.talos00`" + `)","middlewares":` + mwNav + `}]}},
			{"metadata":{"name":"d","namespace":"x","annotations":{"gethomepage.dev/enabled":"true","gethomepage.dev/name":"D","gethomepage.dev/weight":"1_0"}},
			 "spec":{"routes":[{"match":"Host(` + "`w4.talos00`" + `)","middlewares":` + mwNav + `}]}},
			{"metadata":{"name":"e","namespace":"x","annotations":{"gethomepage.dev/enabled":"true","gethomepage.dev/name":"E","gethomepage.dev/weight":"heavy"}},
			 "spec":{"routes":[{"match":"Host(` + "`w5.talos00`" + `)","middlewares":` + mwNav + `}]}},
			{"metadata":{"name":"f","namespace":"x","annotations":{"gethomepage.dev/enabled":"true","gethomepage.dev/name":"F","gethomepage.dev/weight":""}},
			 "spec":{"routes":[{"match":"Host(` + "`w6.talos00`" + `)","middlewares":` + mwNav + `}]}}]}`,

		"enabled must be exactly true": `{"items":[
			{"metadata":{"name":"a","namespace":"x","annotations":{"gethomepage.dev/enabled":"True"}},
			 "spec":{"routes":[{"match":"Host(` + "`e1.talos00`" + `)","middlewares":` + mwNav + `}]}},
			{"metadata":{"name":"b","namespace":"x","annotations":{"gethomepage.dev/enabled":"yes"}},
			 "spec":{"routes":[{"match":"Host(` + "`e2.talos00`" + `)","middlewares":` + mwNav + `}]}},
			{"metadata":{"name":"c","namespace":"x","annotations":{"gethomepage.dev/enabled":"1"}},
			 "spec":{"routes":[{"match":"Host(` + "`e3.talos00`" + `)","middlewares":` + mwNav + `}]}}]}`,

		"item sort by weight then lowercased name": `{"items":[
			{"metadata":{"name":"a","namespace":"x","annotations":{"gethomepage.dev/enabled":"true","gethomepage.dev/name":"zeta","gethomepage.dev/group":"G"}},
			 "spec":{"routes":[{"match":"Host(` + "`s1.talos00`" + `)","middlewares":` + mwNav + `}]}},
			{"metadata":{"name":"b","namespace":"x","annotations":{"gethomepage.dev/enabled":"true","gethomepage.dev/name":"Alpha","gethomepage.dev/group":"G"}},
			 "spec":{"routes":[{"match":"Host(` + "`s2.talos00`" + `)","middlewares":` + mwNav + `}]}},
			{"metadata":{"name":"c","namespace":"x","annotations":{"gethomepage.dev/enabled":"true","gethomepage.dev/name":"First","gethomepage.dev/group":"G","gethomepage.dev/weight":"10"}},
			 "spec":{"routes":[{"match":"Host(` + "`s3.talos00`" + `)","middlewares":` + mwNav + `}]}}]}`,

		"themed groups sort first then alphabetically": `{"items":[
			{"metadata":{"name":"a","namespace":"x","annotations":{"gethomepage.dev/enabled":"true","gethomepage.dev/name":"A","gethomepage.dev/group":"Zebra"}},
			 "spec":{"routes":[{"match":"Host(` + "`g1.talos00`" + `)","middlewares":` + mwNav + `}]}},
			{"metadata":{"name":"b","namespace":"x","annotations":{"gethomepage.dev/enabled":"true","gethomepage.dev/name":"B","gethomepage.dev/group":"Alpha"}},
			 "spec":{"routes":[{"match":"Host(` + "`g2.talos00`" + `)","middlewares":` + mwNav + `}]}},
			{"metadata":{"name":"c","namespace":"x","annotations":{"gethomepage.dev/enabled":"true","gethomepage.dev/name":"C","gethomepage.dev/group":"Themed"}},
			 "spec":{"routes":[{"match":"Host(` + "`g3.talos00`" + `)","middlewares":[{"name":"catalyst-sonarr","namespace":"traefik"}]}]}}]}`,

		"group name case affects only the sort key": `{"items":[
			{"metadata":{"name":"a","namespace":"x","annotations":{"gethomepage.dev/enabled":"true","gethomepage.dev/name":"A","gethomepage.dev/group":"beta"}},
			 "spec":{"routes":[{"match":"Host(` + "`gc1.talos00`" + `)","middlewares":` + mwNav + `}]}},
			{"metadata":{"name":"b","namespace":"x","annotations":{"gethomepage.dev/enabled":"true","gethomepage.dev/name":"B","gethomepage.dev/group":"Alpha"}},
			 "spec":{"routes":[{"match":"Host(` + "`gc2.talos00`" + `)","middlewares":` + mwNav + `}]}}]}`,

		"classifier: shared middlewares alone": `{"items":[{"metadata":{"name":"x","namespace":"x",
			"annotations":{"gethomepage.dev/enabled":"true"}},
			"spec":{"routes":[{"match":"Host(` + "`sh.talos00`" + `)","middlewares":[
			{"name":"catalyst-compress","namespace":"traefik"},
			{"name":"catalyst-accept-encoding","namespace":"traefik"},
			{"name":"catalyst-asset-cache","namespace":"traefik"}]}]}}]}`,

		"classifier: merged nav injector": `{"items":[{"metadata":{"name":"x","namespace":"x",
			"annotations":{"gethomepage.dev/enabled":"true"}},
			"spec":{"routes":[{"match":"Host(` + "`mg.talos00`" + `)","middlewares":[
			{"name":"catalyst-nav-rum-grafana","namespace":"traefik"}]}]}}]}`,

		"classifier: bare catalyst prefix injects but does not theme": `{"items":[{"metadata":{"name":"x","namespace":"x",
			"annotations":{"gethomepage.dev/enabled":"true"}},
			"spec":{"routes":[{"match":"Host(` + "`bp.talos00`" + `)","middlewares":[
			{"name":"catalystnav","namespace":"traefik"}]}]}}]}`,

		"classifier: catalyst-inject would wrongly theme": `{"items":[{"metadata":{"name":"x","namespace":"x",
			"annotations":{"gethomepage.dev/enabled":"true"}},
			"spec":{"routes":[{"match":"Host(` + "`ij.talos00`" + `)","middlewares":[
			{"name":"catalyst-nav","namespace":"traefik"},
			{"name":"catalyst-inject-devoverlay","namespace":"traefik"}]}]}}]}`,

		"middlewares with a null name": `{"items":[{"metadata":{"name":"x","namespace":"x",
			"annotations":{"gethomepage.dev/enabled":"true"}},
			"spec":{"routes":[{"match":"Host(` + "`nn.talos00`" + `)","middlewares":[
			{"namespace":"traefik"},{"name":"catalyst-nav","namespace":"traefik"}]}]}}]}`,

		"middlewares spread across several routes": `{"items":[{"metadata":{"name":"x","namespace":"x",
			"annotations":{"gethomepage.dev/enabled":"true"}},"spec":{"routes":[
			{"match":"Host(` + "`sp.talos00`" + `)","middlewares":[{"name":"catalyst-nav","namespace":"traefik"}]},
			{"match":"Host(` + "`sp.talos00`" + `) && PathPrefix(` + "`/a/`" + `)","middlewares":[{"name":"catalyst-sonarr","namespace":"traefik"}]}]}}]}`,

		"applet plus a nav entry together": `{"items":[
			{"metadata":{"name":"ap","namespace":"dev-overlay","annotations":{"catalyst.nav/applet-src":"/catalyst/applets/d/d.js","catalyst.nav/applet-name":"dev-overlay"}},
			 "spec":{"routes":[{"match":"PathPrefix(` + "`/catalyst/x/`" + `)"}]}},
			{"metadata":{"name":"g","namespace":"x","annotations":{"gethomepage.dev/enabled":"true","gethomepage.dev/name":"G"}},
			 "spec":{"routes":[{"match":"Host(` + "`ap.talos00`" + `)","middlewares":` + mwNav + `}]}}]}`,

		"hostile applet srcs all refused": `{"items":[
			{"metadata":{"name":"a","namespace":"x","annotations":{"catalyst.nav/applet-src":"//evil.example/x.js"}},"spec":{"routes":[]}},
			{"metadata":{"name":"b","namespace":"x","annotations":{"catalyst.nav/applet-src":"https://evil.example/x.js"}},"spec":{"routes":[]}},
			{"metadata":{"name":"c","namespace":"x","annotations":{"catalyst.nav/applet-src":"javascript:alert(1)"}},"spec":{"routes":[]}},
			{"metadata":{"name":"d","namespace":"x","annotations":{"catalyst.nav/applet-src":"/catalyst/%2e%2e%2fx.js"}},"spec":{"routes":[]}},
			{"metadata":{"name":"e","namespace":"x","annotations":{"catalyst.nav/applet-src":"/catalyst/../../x.js"}},"spec":{"routes":[]}},
			{"metadata":{"name":"f","namespace":"x","annotations":{"catalyst.nav/applet-src":"/catalyst/\\evil.example/x.js"}},"spec":{"routes":[]}},
			{"metadata":{"name":"g","namespace":"x","annotations":{"catalyst.nav/applet-src":"/assets/x.js"}},"spec":{"routes":[]}},
			{"metadata":{"name":"h","namespace":"x","annotations":{"catalyst.nav/applet-src":""}},"spec":{"routes":[]}},
			{"metadata":{"name":"i","namespace":"x","annotations":{"catalyst.nav/applet-src":"/catalyst/ok.js"}},"spec":{"routes":[]}}]}`,

		"applets sorted regardless of document order": `{"items":[
			{"metadata":{"name":"z","namespace":"x","annotations":{"catalyst.nav/applet-src":"/catalyst/zzz/z.js"}},"spec":{"routes":[]}},
			{"metadata":{"name":"a","namespace":"x","annotations":{"catalyst.nav/applet-src":"/catalyst/aaa/a.js"}},"spec":{"routes":[]}}]}`,

		"non-ascii app name is escaped the same way": `{"items":[{"metadata":{"name":"x","namespace":"x","annotations":{
			"gethomepage.dev/enabled":"true","gethomepage.dev/name":"Café — Media"}},
			"spec":{"routes":[{"match":"Host(` + "`u.talos00`" + `)","middlewares":` + mwNav + `}]}}]}`,

		"quotes and backslashes in a name": `{"items":[{"metadata":{"name":"x","namespace":"x","annotations":{
			"gethomepage.dev/enabled":"true","gethomepage.dev/name":"He said \"hi\" \\ bye"}},
			"spec":{"routes":[{"match":"Host(` + "`q.talos00`" + `)","middlewares":` + mwNav + `}]}}]}`,
	}

	for name, input := range cases {
		t.Run(name, func(t *testing.T) {
			assertParity(t, name, input, Env{})
			// Re-run every case under NAV_SCOPE=all: the filter is the single biggest
			// behavioural switch and half these fixtures are shaped by it.
			assertParity(t, name+" [scope=all]", input, Env{Scope: "all"})
		})
	}
}

// TestParityHarnessCanFail guards the guard. A differential test whose oracle is never
// consulted, or whose comparison always passes, is worse than no test: it reports agreement it
// never checked. This mutates the input to ONE side and requires the comparison to notice.
func TestParityHarnessCanFail(t *testing.T) {
	script := buildNavPy(t)
	const mwNav = `[{"name":"catalyst-nav","namespace":"traefik"}]`
	a := `{"items":[{"metadata":{"name":"x","namespace":"x","annotations":{
		"gethomepage.dev/enabled":"true","gethomepage.dev/name":"A"}},
		"spec":{"routes":[{"match":"Host(` + "`h.talos00`" + `)","middlewares":` + mwNav + `}]}}]}`
	b := strings.Replace(a, `"A"`, `"B"`, 1)

	pyOut, _ := runPython(t, script, a, Env{})
	goOut, _ := runGo(t, b, Env{})
	if pyOut == goOut {
		t.Fatal("the harness compared two different inputs and saw no difference -- " +
			"the comparison is not actually looking at the manifest")
	}
	// And the oracle must really be the script: a Go-only round trip would agree with
	// itself even if both were wrong.
	if !strings.Contains(pyOut, `"name":"A"`) {
		t.Fatalf("python oracle produced %s, which does not look like a nav manifest", pyOut)
	}
}

// TestNullItemsDivergesFromBuildNavPy records the ONE input on which this port deliberately
// does not match the script: `{"items":null}`.
//
// FOUND BY THIS DIFFERENTIAL, not by reading the code. build_nav.py's main() does
// `doc.get("items", [])` with no `or []`, so a null items array raises
// `TypeError: 'NoneType' object is not iterable` and the script exits 1 — while
// discover_applets(), four lines of the same file away, writes `doc.get("items", []) or []`
// and handles it. The two spellings disagree and only one is guarded.
//
// Not reproduced, and not reported as a parity failure either, for three reasons:
//   - kubectl never emits `"items":null` for a list (an empty list is `[]`), so the branch is
//     unreachable through the sidecar's actual input path.
//   - discover.sh treats a non-zero exit as "keep serving the previous manifest", so even in
//     the cluster the script's behaviour here is a no-op, not an outage.
//   - a reconciler cannot adopt "crash the process" as its handling of a decode edge case.
//
// If build_nav.py is ever fixed to `or []`, this divergence closes and the case can move into
// TestParityOnEdgeCases.
func TestNullItemsDivergesFromBuildNavPy(t *testing.T) {
	script := buildNavPy(t)
	const input = `{"items":null}`

	// The oracle really does crash — asserted, not assumed, so this comment cannot rot into
	// a claim about behaviour nobody checked.
	cmd := exec.Command(python(t), script)
	cmd.Stdin = strings.NewReader(input)
	var errb bytes.Buffer
	cmd.Stderr = &errb
	if err := cmd.Run(); err == nil {
		t.Fatal("build_nav.py now accepts {\"items\":null} -- the divergence is closed; " +
			"move this case into TestParityOnEdgeCases and delete this test")
	}
	if !strings.Contains(errb.String(), "not iterable") {
		t.Fatalf("build_nav.py failed for an unexpected reason: %s", errb.String())
	}

	// This port returns an empty manifest instead.
	out, _ := runGo(t, input, Env{})
	if out != `{"groups":[]}` {
		t.Fatalf("render produced %s, want an empty manifest", out)
	}
}
