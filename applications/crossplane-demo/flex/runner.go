package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"os"
	"time"
)

// Result is the per-subsystem outcome of a single check.
type Result struct {
	Subsystem string `json:"subsystem"`
	OK        bool   `json:"ok"`
	Skipped   bool   `json:"skipped,omitempty"`
	Detail    string `json:"detail"`
}

// Report is the aggregate returned by /run and -once.
type Report struct {
	Results []Result `json:"results"`
	AllOK   bool     `json:"all_ok"`
}

// checkFunc runs one subsystem probe.
//
// Contract:
//   - return (detail, false, nil)  => OK
//   - return (detail, true, nil)   => skipped (missing env / not applicable)
//   - return (_, _, err)           => failed, err.Error() becomes the detail
//
// A checkFunc must never call panic on purpose; the runner recovers anyway.
type checkFunc func(ctx context.Context) (detail string, skipped bool, err error)

type check struct {
	name    string
	timeout time.Duration
	fn      checkFunc
}

// allChecks is the ordered registry of subsystem probes. Order matters:
// celery runs last because it depends on rabbitmq + dragonfly being healthy
// and on an external worker having processed the task.
func allChecks() []check {
	return []check{
		{"minio", 10 * time.Second, checkMinio},
		{"rabbitmq", 10 * time.Second, checkRabbitMQ},
		{"dragonfly", 10 * time.Second, checkDragonfly},
		{"clickhouse", 10 * time.Second, checkClickHouse},
		{"opensearch", 10 * time.Second, checkOpenSearch},
		{"argo", 75 * time.Second, checkArgo},
		{"crossplane", 10 * time.Second, checkCrossplane},
		{"celery", 35 * time.Second, checkCelery},
	}
}

// runCheck enforces a per-check timeout and guarantees the check can never
// crash the process: panics are recovered and surfaced as a failed Result.
func runCheck(parent context.Context, c check) Result {
	ctx, cancel := context.WithTimeout(parent, c.timeout)
	defer cancel()

	type outcome struct {
		detail  string
		skipped bool
		err     error
	}
	done := make(chan outcome, 1)

	go func() {
		defer func() {
			if r := recover(); r != nil {
				done <- outcome{err: fmt.Errorf("panic: %v", r)}
			}
		}()
		d, s, e := c.fn(ctx)
		done <- outcome{detail: d, skipped: s, err: e}
	}()

	select {
	case o := <-done:
		switch {
		case o.skipped:
			return Result{Subsystem: c.name, OK: false, Skipped: true, Detail: o.detail}
		case o.err != nil:
			return Result{Subsystem: c.name, OK: false, Detail: o.err.Error()}
		default:
			return Result{Subsystem: c.name, OK: true, Detail: o.detail}
		}
	case <-ctx.Done():
		return Result{Subsystem: c.name, OK: false, Detail: "timeout: " + ctx.Err().Error()}
	}
}

// runAll executes every check sequentially and aggregates the report.
// all_ok is true when no check FAILED; skipped checks do not count against it.
func runAll(ctx context.Context) Report {
	checks := allChecks()
	results := make([]Result, 0, len(checks))
	allOK := true
	for _, c := range checks {
		r := runCheck(ctx, c)
		if !r.OK && !r.Skipped {
			allOK = false
		}
		results = append(results, r)
	}
	return Report{Results: results, AllOK: allOK}
}

// --- small env / random helpers -------------------------------------------

func env(key string) string { return os.Getenv(key) }

func envDefault(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

// randHex returns n random bytes hex-encoded (2n chars).
func randHex(n int) string {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		// Fall back to a timestamp-derived value; never panic.
		return hex.EncodeToString([]byte(time.Now().Format("150405.000000")))
	}
	return hex.EncodeToString(b)
}
