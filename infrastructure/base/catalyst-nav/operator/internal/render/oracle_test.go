package render

// THE FROZEN ORACLE: build_nav.py's output, transcribed to data because the script itself is
// gone.
//
// WHY THIS IS NOT THE THING parity_test.go's ORIGINAL HEADER WARNED AGAINST. That header
// rejected golden files on the grounds that "a golden file records what the port does today
// and would be regenerated from the port the first time it disagreed with the script". That
// objection is about the REGENERATION PATH, not about the file format — and the regeneration
// path is what has been removed. These bytes were produced by running the real build_nav.py
// over the real fixtures (see oracle_freeze_gen_test.go in the commit that added this file),
// and that generator was deleted in the same commit as its oracle. Nothing in the tree can
// now rewrite them from the Go port.
//
// So the oracle property is preserved, with one honest loss: a NEW fixture can no longer be
// parity-checked, because there is nothing left to ask. assertParity fails loudly rather than
// skipping when a case has no frozen output — so the loss presents as a failure to be
// reckoned with, not as a quiet gap. New behaviour belongs in navmodel's own table tests,
// asserted against the documented contract rather than against a script nobody can run.
//
// Keyed by CONTENT, not by case name: renaming a fixture must not orphan its oracle, and
// editing a fixture's input must not silently keep comparing against the old one. A key miss
// is a failure; a key hit is proof the bytes being compared were produced from this exact
// input under this exact environment.

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
	"testing"
)

// harnessCanFailInput is the fixture TestParityHarnessCanFail mutates. Named rather than
// inline because the frozen oracle has to carry an entry for it.
const harnessCanFailInput = `{"items":[{"metadata":{"name":"x","namespace":"x","annotations":{
		"gethomepage.dev/enabled":"true","gethomepage.dev/name":"A"}},
		"spec":{"routes":[{"match":"Host(` + "`h.talos00`" + `)","middlewares":` +
	`[{"name":"catalyst-nav","namespace":"traefik"}]` + `}]}}]}`

type oracleMeta struct {
	Producer string `json:"producer"`
	Note     string `json:"note"`
}

type oracleCase struct {
	Scope    string `json:"scope"`
	Defaults string `json:"defaults"`
	Stdout   string `json:"stdout"`
	Reasons  string `json:"reasons"`
}

type oracleFile struct {
	Meta  oracleMeta            `json:"_meta"`
	Cases map[string]oracleCase `json:"cases"`
}

// oracleKey identifies a fixture by its full input, which is (stdin, NAV_SCOPE, NAV_DEFAULTS)
// — the complete set of things build_nav.py read. NUL-separated so no concatenation of two
// fields can collide with a different split of the same bytes.
func oracleKey(input string, env Env) string {
	h := sha256.New()
	h.Write([]byte(input))
	h.Write([]byte{0})
	h.Write([]byte(env.Scope))
	h.Write([]byte{0})
	h.Write([]byte(env.Defaults))
	return hex.EncodeToString(h.Sum(nil))
}

var (
	oracleOnce sync.Once
	oracleData oracleFile
	oracleErr  error
)

func loadOracle(t *testing.T) oracleFile {
	t.Helper()
	oracleOnce.Do(func() {
		path := filepath.Join("..", "..", "testdata", "golden", "build_nav_oracle.json")
		b, err := os.ReadFile(path)
		if err != nil {
			oracleErr = err
			return
		}
		oracleErr = json.Unmarshal(b, &oracleData)
	})
	if oracleErr != nil {
		// Fatal, never Skip. The whole point of freezing the oracle was that the gate
		// keeps running after the script is gone; a missing golden set must stop the
		// suite, not quietly reduce it to the Go port agreeing with itself.
		t.Fatalf("frozen oracle unreadable: %v", oracleErr)
	}
	return oracleData
}

// oracleFor returns the frozen build_nav.py output for one fixture.
func oracleFor(t *testing.T, input string, env Env) oracleCase {
	t.Helper()
	key := oracleKey(input, env)
	got, ok := loadOracle(t).Cases[key]
	if !ok {
		t.Fatalf("no frozen oracle output for this fixture (key %s, scope=%q defaults=%q).\n"+
			"build_nav.py is deleted, so one cannot be generated: this fixture's input or "+
			"environment was changed, or it is new. Revert the fixture, or move the case "+
			"into navmodel's table tests and assert it against the documented contract.",
			key, env.Scope, env.Defaults)
	}
	return got
}
