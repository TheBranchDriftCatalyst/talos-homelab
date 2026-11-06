package render

// THE PARITY PROOF. Compares this package's output, BYTE FOR BYTE, against
// infrastructure/base/themepark/server/nav/build_nav.py — the sidecar implementation this
// port replaced.
//
// THE SCRIPT IS GONE. It was deleted when the operator became the sole producer of the nav
// manifest, which is what this port existed to make possible. Its output did not go with it:
// every fixture below was run through the real script first and its stdout and refusal
// reasons transcribed into testdata/golden/build_nav_oracle.json. See oracle_test.go for why
// that is still a genuine oracle and not the self-confirming golden file this header used to
// (correctly) argue against — the short version is that the regeneration path is what made
// golden files dangerous, and there is no longer any code in this repo that can rewrite those
// bytes.
//
// WHAT THE GATE STILL PROVES: that the Go renderer reproduces, exactly, what the deleted
// Python produced for 85 recorded (input, environment) pairs — the whole committed
// IngressRoute corpus under eight environments, plus 38 hand-built edge cases under two
// scopes each. A regression in navmodel shows up here as a byte diff.
//
// WHAT IT NO LONGER PROVES: anything about an input nobody recorded. A new fixture has no
// oracle and cannot acquire one, so assertParity FAILS on an unrecorded case rather than
// skipping it. That is deliberate — the alternative is a gate that quietly shrinks.

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func runGo(t *testing.T, input string, env Env) (stdout, stderr string) {
	t.Helper()
	var out, errb bytes.Buffer
	if err := Run(strings.NewReader(input), &out, &errb, env); err != nil {
		t.Fatalf("render.Run failed: %v", err)
	}
	return out.String(), errb.String()
}

// assertParity is the whole point: identical bytes on stdout, and the same refusal reasons on
// stderr, against what build_nav.py produced for this exact input and environment.
func assertParity(t *testing.T, name, input string, env Env) {
	t.Helper()
	want := oracleFor(t, input, env)
	goOut, goErr := runGo(t, input, env)
	if want.Stdout != goOut {
		t.Errorf("%s: MANIFEST BYTES DIFFER\n  build_nav.py: %s\n            go: %s",
			name, want.Stdout, goOut)
	}
	// stderr is compared by reason, not verbatim: the script interleaved applet-name
	// progress lines with refusals and the order of the two passes was never part of the
	// contract. The REASONS are.
	if got := reasons(goErr); want.Reasons != got {
		t.Errorf("%s: refusal reasons differ\n  build_nav.py: %v\n            go: %v",
			name, want.Reasons, got)
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
	for _, env := range corpusEnvs() {
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
	cases := edgeCaseInputs()

	for name, input := range cases {
		t.Run(name, func(t *testing.T) {
			assertParity(t, name, input, Env{})
			// Re-run every case under NAV_SCOPE=all: the filter is the single biggest
			// behavioural switch and half these fixtures are shaped by it.
			assertParity(t, name+" [scope=all]", input, Env{Scope: "all"})
		})
	}
}

// TestParityHarnessCanFail guards the guard. A gate whose oracle is never consulted, or whose
// comparison always passes, is worse than no test: it reports agreement it never checked. This
// mutates the input on the GO side only and requires the comparison against the frozen oracle
// to notice.
//
// It matters MORE now than when the oracle was a live subprocess, not less. A frozen golden
// set can fail silently in ways a subprocess cannot: an empty `cases` map, a key scheme that
// never matches, an oracleFor that returns a zero value instead of failing. Each of those
// would make every assertParity compare "" against "" and pass. So this test asserts all
// three of the things that could rot — that the oracle is non-empty, that it looks like a nav
// manifest, and that a one-byte input change is actually detected.
func TestParityHarnessCanFail(t *testing.T) {
	want := oracleFor(t, harnessCanFailInput, Env{})

	// 1. The frozen oracle must really hold build_nav.py's manifest, not a zero value. A
	//    Go-only round trip would agree with itself even if both sides were wrong.
	if !strings.Contains(want.Stdout, `"name":"A"`) {
		t.Fatalf("frozen oracle produced %q, which does not look like a nav manifest",
			want.Stdout)
	}

	// 2. The unmutated input must MATCH, or the comparison is broken in the other
	//    direction and every case below is failing for an unrelated reason.
	if goOut, _ := runGo(t, harnessCanFailInput, Env{}); goOut != want.Stdout {
		t.Fatalf("unmutated fixture already differs from the oracle:\n  oracle: %s\n      go: %s",
			want.Stdout, goOut)
	}

	// 3. A mutated input must DIFFER. This is the assertion that fails if the comparison
	//    is not actually looking at the manifest.
	mutated := strings.Replace(harnessCanFailInput, `"A"`, `"B"`, 1)
	if mutated == harnessCanFailInput {
		t.Fatal("the mutation did not change the fixture; this test proves nothing")
	}
	if goOut, _ := runGo(t, mutated, Env{}); goOut == want.Stdout {
		t.Fatal("the harness compared two different inputs and saw no difference -- " +
			"the comparison is not actually looking at the manifest")
	}

	// 4. The oracle set must be populated. An empty map would make oracleFor fail, but
	//    only for cases that are actually run; stating the count here means a truncated
	//    golden file cannot pass as a smaller gate.
	if n := len(loadOracle(t).Cases); n < 80 {
		t.Fatalf("frozen oracle holds only %d cases; the golden file is truncated", n)
	}
}

// TestNullItemsDoesNotCrashThisPort records the ONE input on which this port deliberately did
// not match the script: `{"items":null}`.
//
// FOUND BY THE DIFFERENTIAL, not by reading the code. build_nav.py's main() did
// `doc.get("items", [])` with no `or []`, so a null items array raised
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
// THE CRASH IS NO LONGER ASSERTED, because the script is deleted and there is nothing left to
// run. It WAS asserted, by the previous revision of this test, against the real build_nav.py:
// the subprocess exited non-zero with "TypeError: 'NoneType' object is not iterable" on
// stderr. That is a recorded historical observation now, not a live claim, and the distinction
// is stated here rather than left for a reader to discover — a comment that describes
// behaviour nothing checks is exactly the rot this file is careful about elsewhere.
//
// Deliberately NOT frozen into the oracle either: the golden set records stdout and refusal
// reasons for inputs the script HANDLED, and an entry whose meaning is "this crashed" would
// have to be special-cased by assertParity, putting a branch for one unreachable input into
// the comparison every other case flows through.
//
// What remains testable, and is the half that actually constrains the shipped code, is this
// port's behaviour: an empty manifest rather than a crash.
func TestNullItemsDoesNotCrashThisPort(t *testing.T) {
	const input = `{"items":null}`
	out, _ := runGo(t, input, Env{})
	if out != `{"groups":[]}` {
		t.Fatalf("render produced %s, want an empty manifest", out)
	}
}

// corpusEnvs is the environment matrix the cluster corpus is rendered under. Package-level,
// not inline in the test, because the frozen-oracle golden set is keyed by (input, env) and
// the generator that produced it walked EXACTLY this list. Adding an entry here without a
// matching golden fails with "no frozen oracle output" rather than silently passing --
// see the header of this file.
func corpusEnvs() []Env {
	return []Env{
		{}, // unset NAV_SCOPE, which falls back to themed
		// The LITERAL value the operator's Deployment sets (and the deleted sidecar set
		// before it). Added when the oracle was frozen, because the matrix had only ever
		// covered the UNSET case and "unset behaves like themed" was an inference from
		// `.lower() != "all"` rather than something recorded. `task nav:parity` looks this
		// case up by name, so the shipped configuration is now the one the gate checks.
		{Scope: "themed"},
		{Scope: "all"}, // the escape hatch
		{Scope: "all", Defaults: `{"revealAt":4}`}, // cluster-wide defaults
		{Defaults: `{"fx":false,"intensity":1}`},   // intensity 1 -> must render 1.0
		{Defaults: `{"notAKey":1,"mode":"push"}`},  // key filtering
		{Defaults: `[1]`},                          // non-object: ignored with a log
		{Scope: "ALL"},                             // .lower() on NAV_SCOPE
		{Scope: "themed-ish"},                      // anything != all keeps the filter
	}
}

// edgeCaseInputs pins the cases a real cluster does not currently contain. Package-level for
// the same reason as corpusEnvs above.
func edgeCaseInputs() map[string]string {
	const mwNav = `[{"name":"catalyst-nav","namespace":"traefik"}]`
	return map[string]string{
		"empty document": `{"items":[]}`,
		"no items key":   `{}`,
		// `{"items":null}` is NOT here: it crashes build_nav.py, so there is no oracle
		// output to compare against. See TestNullItemsDoesNotCrashThisPort, which records
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
}
