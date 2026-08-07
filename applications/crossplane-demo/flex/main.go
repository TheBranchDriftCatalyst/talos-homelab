// Command flex is the crossplane-demo "service": a trivial exerciser that
// touches every provisioned backend (MinIO, RabbitMQ, Dragonfly, ClickHouse,
// OpenSearch, Argo Workflows, Crossplane, Celery) and reports per-subsystem
// OK / FAIL / SKIPPED. It is driven by a Jest integration test either over
// HTTP (GET /run) or via `kubectl exec ... /flex -once`.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"html/template"
	"log"
	"net/http"
	"os"
	"time"
)

func main() {
	var (
		once bool
		addr string
	)
	flag.BoolVar(&once, "once", false, "run all checks once, print JSON to stdout, and exit")
	flag.StringVar(&addr, "addr", envDefault("FLEX_ADDR", ":8080"), "HTTP listen address")
	flag.Parse()

	if once {
		// Give the whole run a generous ceiling; individual checks have their
		// own (shorter) timeouts enforced by the runner.
		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Minute)
		defer cancel()
		report := runAll(ctx)
		enc := json.NewEncoder(os.Stdout)
		enc.SetIndent("", "  ")
		_ = enc.Encode(report)
		if !report.AllOK {
			os.Exit(1)
		}
		return
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", handleHealthz)
	mux.HandleFunc("/run", handleRun)
	mux.HandleFunc("/status", handleStatus)
	mux.HandleFunc("/", handleRoot)

	srv := &http.Server{
		Addr:              addr,
		Handler:           mux,
		ReadHeaderTimeout: 10 * time.Second,
	}
	log.Printf("flex listening on %s", addr)
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("server error: %v", err)
	}
}

func handleHealthz(w http.ResponseWriter, _ *http.Request) {
	w.WriteHeader(http.StatusOK)
	_, _ = fmt.Fprintln(w, "ok")
}

func handleRoot(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		http.NotFound(w, r)
		return
	}
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	_, _ = fmt.Fprintln(w, "crossplane-demo flex\n\nGET /healthz  liveness\nGET /run      run all checks -> JSON\nGET /status   run all checks -> HTML table")
}

// handleRun always responds 200; per-item ok flags carry the real state.
func handleRun(w http.ResponseWriter, r *http.Request) {
	report := runAll(r.Context())
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	enc := json.NewEncoder(w)
	enc.SetIndent("", "  ")
	_ = enc.Encode(report)
}

func handleStatus(w http.ResponseWriter, r *http.Request) {
	report := runAll(r.Context())
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	if err := statusTmpl.Execute(w, report); err != nil {
		log.Printf("status template error: %v", err)
	}
}

var statusTmpl = template.Must(template.New("status").Funcs(template.FuncMap{
	"state": func(r Result) string {
		switch {
		case r.Skipped:
			return "SKIPPED"
		case r.OK:
			return "OK"
		default:
			return "FAIL"
		}
	},
	"cls": func(r Result) string {
		switch {
		case r.Skipped:
			return "skip"
		case r.OK:
			return "ok"
		default:
			return "fail"
		}
	},
}).Parse(`<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>flex status</title>
<style>
 body{font-family:system-ui,sans-serif;margin:2rem;background:#0f1117;color:#e6e6e6}
 h1{font-size:1.2rem}
 table{border-collapse:collapse;width:100%;max-width:900px}
 th,td{text-align:left;padding:.5rem .75rem;border-bottom:1px solid #2a2d38}
 .ok{color:#37d67a;font-weight:600}
 .fail{color:#ff5c5c;font-weight:600}
 .skip{color:#c9a227;font-weight:600}
 .summary{margin:.5rem 0 1rem}
</style></head><body>
<h1>crossplane-demo flex</h1>
<div class="summary">all_ok: <span class="{{if .AllOK}}ok{{else}}fail{{end}}">{{.AllOK}}</span></div>
<table>
 <thead><tr><th>Subsystem</th><th>State</th><th>Detail</th></tr></thead>
 <tbody>
 {{range .Results}}
  <tr><td>{{.Subsystem}}</td><td class="{{cls .}}">{{state .}}</td><td>{{.Detail}}</td></tr>
 {{end}}
 </tbody>
</table>
</body></html>`))
