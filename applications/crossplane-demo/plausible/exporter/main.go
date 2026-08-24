// plausible-stats-exporter (TALOS-4gg)
//
// A tiny, dependency-free Prometheus exporter for the Plausible Stats API.
// It polls the Plausible Stats API v1 on an interval for every site listed in
// a mounted sites.json and exposes the results as Prometheus gauges on
// :8080/metrics.
//
// Stdlib-only on purpose: no go.sum, no module downloads, builds fully offline
// and compiles to a static binary that fits in a FROM scratch image.
//
// Stats API v1 endpoints used (self-hosted Plausible CE serves the same API as
// plausible.io; a Stats API key created in the UI authorizes it):
//
//	realtime : GET {base}/api/v1/stats/realtime/visitors?site_id={domain}
//	           -> body is a bare integer (visitors in the last 5 min)
//	aggregate: GET {base}/api/v1/stats/aggregate?site_id={domain}&period={p}
//	                &metrics=visitors,pageviews,bounce_rate,visit_duration
//	           -> {"results":{"visitors":{"value":N}, ...}}
//	           visit_duration is in seconds, bounce_rate is a percentage.
//
// Auth: Authorization: Bearer <stats-read-key>.
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

// periodLabels maps the Prometheus `period` label (fixed by the metric contract)
// to the Stats API v1 `period` query value. Plausible v1 has no rolling "24h"
// period, so the "24h" label is served by the API's "day" period (stats since
// midnight for the site's timezone) — the closest supported window.
var periodLabels = []struct{ label, apiPeriod string }{
	{"24h", "day"},
	{"7d", "7d"},
	{"30d", "30d"},
}

const aggregateMetrics = "visitors,pageviews,bounce_rate,visit_duration"

type site struct {
	Domain string `json:"domain"`
	Inject bool   `json:"inject"`
	GA     string `json:"ga"` // optional GA4 measurement ID (G-XXXX)
}

// registryCounts are derived purely from the mounted analytics-sites registry —
// they track analytics coverage (how many sites, how many carry a GA4 tag)
// without touching Google's API, and are emitted independently of plausible_up.
type registryCounts struct {
	total          float64
	plausibleSites float64
	gaSites        float64
}

// countRegistry derives coverage counts from the parsed registry. Every entry
// is a Plausible site; an entry counts toward GA if its `ga` field holds a
// non-empty GA4 measurement ID (G-...).
func countRegistry(sites []site) registryCounts {
	var rc registryCounts
	for _, s := range sites {
		if strings.TrimSpace(s.Domain) == "" {
			continue
		}
		rc.total++
		rc.plausibleSites++
		if isGA4(s.GA) {
			rc.gaSites++
		}
	}
	return rc
}

func isGA4(id string) bool {
	return strings.HasPrefix(strings.ToUpper(strings.TrimSpace(id)), "G-")
}

// aggregateResponse matches the /api/v1/stats/aggregate JSON shape.
type aggregateResponse struct {
	Results struct {
		Visitors      metricValue `json:"visitors"`
		Pageviews     metricValue `json:"pageviews"`
		BounceRate    metricValue `json:"bounce_rate"`
		VisitDuration metricValue `json:"visit_duration"`
	} `json:"results"`
}

type metricValue struct {
	Value float64 `json:"value"`
}

// aggKey identifies one aggregate sample.
type aggKey struct {
	site   string
	period string
	metric string
}

// store holds the most recently scraped values, guarded by a mutex. The poller
// writes; the /metrics handler reads. Gauges only.
type store struct {
	mu             sync.RWMutex
	up             float64
	scrapeDuration float64
	registry       registryCounts     // derived from the registry, independent of `up`
	realtime       map[string]float64 // site -> visitors
	aggregates     map[aggKey]float64
}

func newStore() *store {
	return &store{
		realtime:   map[string]float64{},
		aggregates: map[aggKey]float64{},
	}
}

type collector struct {
	baseURL string
	apiKey  string
	client  *http.Client
	store   *store
}

func (c *collector) collect(ctx context.Context, sites []site) {
	start := time.Now()
	realtime := map[string]float64{}
	aggregates := map[aggKey]float64{}
	ok := true

	for _, s := range sites {
		domain := strings.TrimSpace(s.Domain)
		if domain == "" {
			continue
		}

		if v, err := c.fetchRealtime(ctx, domain); err != nil {
			log.Printf("realtime %s: %v", domain, err)
			ok = false
		} else {
			realtime[domain] = v
		}

		for _, p := range periodLabels {
			agg, err := c.fetchAggregate(ctx, domain, p.apiPeriod)
			if err != nil {
				log.Printf("aggregate %s period=%s: %v", domain, p.label, err)
				ok = false
				continue
			}
			aggregates[aggKey{domain, p.label, "visitors"}] = agg.Results.Visitors.Value
			aggregates[aggKey{domain, p.label, "pageviews"}] = agg.Results.Pageviews.Value
			aggregates[aggKey{domain, p.label, "bounce_rate"}] = agg.Results.BounceRate.Value
			aggregates[aggKey{domain, p.label, "visit_duration"}] = agg.Results.VisitDuration.Value
		}
	}

	c.store.mu.Lock()
	c.store.realtime = realtime
	c.store.aggregates = aggregates
	c.store.scrapeDuration = time.Since(start).Seconds()
	if ok {
		c.store.up = 1
	} else {
		c.store.up = 0
	}
	c.store.mu.Unlock()
}

func (c *collector) get(ctx context.Context, path string, query map[string]string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.baseURL+path, nil)
	if err != nil {
		return nil, err
	}
	q := req.URL.Query()
	for k, v := range query {
		q.Set(k, v)
	}
	req.URL.RawQuery = q.Encode()
	req.Header.Set("Authorization", "Bearer "+c.apiKey)
	req.Header.Set("Accept", "application/json")

	resp, err := c.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("status %d: %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}
	return body, nil
}

func (c *collector) fetchRealtime(ctx context.Context, domain string) (float64, error) {
	body, err := c.get(ctx, "/api/v1/stats/realtime/visitors", map[string]string{"site_id": domain})
	if err != nil {
		return 0, err
	}
	// The realtime endpoint returns a bare integer.
	return strconv.ParseFloat(strings.TrimSpace(string(body)), 64)
}

func (c *collector) fetchAggregate(ctx context.Context, domain, apiPeriod string) (aggregateResponse, error) {
	var out aggregateResponse
	body, err := c.get(ctx, "/api/v1/stats/aggregate", map[string]string{
		"site_id": domain,
		"period":  apiPeriod,
		"metrics": aggregateMetrics,
	})
	if err != nil {
		return out, err
	}
	if err := json.Unmarshal(body, &out); err != nil {
		return out, fmt.Errorf("decode: %w", err)
	}
	return out, nil
}

// writeMetrics renders the Prometheus text exposition format.
func (s *store) writeMetrics(w io.Writer) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	fmt.Fprintln(w, "# HELP plausible_up 1 if the last scrape of the Plausible Stats API succeeded for all sites, 0 otherwise.")
	fmt.Fprintln(w, "# TYPE plausible_up gauge")
	fmt.Fprintf(w, "plausible_up %s\n", fmtFloat(s.up))

	fmt.Fprintln(w, "# HELP plausible_scrape_duration_seconds Duration of the last Plausible Stats API scrape cycle in seconds.")
	fmt.Fprintln(w, "# TYPE plausible_scrape_duration_seconds gauge")
	fmt.Fprintf(w, "plausible_scrape_duration_seconds %s\n", fmtFloat(s.scrapeDuration))

	fmt.Fprintln(w, "# HELP analytics_sites_total Number of entries in the analytics-sites registry.")
	fmt.Fprintln(w, "# TYPE analytics_sites_total gauge")
	fmt.Fprintf(w, "analytics_sites_total %s\n", fmtFloat(s.registry.total))

	fmt.Fprintln(w, "# HELP analytics_provider_sites Registry entries covered by each analytics provider.")
	fmt.Fprintln(w, "# TYPE analytics_provider_sites gauge")
	fmt.Fprintf(w, "analytics_provider_sites{provider=\"plausible\"} %s\n", fmtFloat(s.registry.plausibleSites))
	fmt.Fprintf(w, "analytics_provider_sites{provider=\"ga\"} %s\n", fmtFloat(s.registry.gaSites))

	fmt.Fprintln(w, "# HELP plausible_realtime_visitors Current visitors in the last 5 minutes.")
	fmt.Fprintln(w, "# TYPE plausible_realtime_visitors gauge")
	for _, domain := range sortedKeys(s.realtime) {
		fmt.Fprintf(w, "plausible_realtime_visitors{site=%q} %s\n", domain, fmtFloat(s.realtime[domain]))
	}

	writeAgg(w, s.aggregates, "plausible_visitors", "visitors", "Unique visitors over the period.")
	writeAgg(w, s.aggregates, "plausible_pageviews", "pageviews", "Total pageviews over the period.")
	writeAgg(w, s.aggregates, "plausible_bounce_rate_percent", "bounce_rate", "Bounce rate over the period, as a percentage.")
	writeAgg(w, s.aggregates, "plausible_visit_duration_seconds", "visit_duration", "Average visit duration over the period, in seconds.")
}

func writeAgg(w io.Writer, aggregates map[aggKey]float64, metricName, apiMetric, help string) {
	fmt.Fprintf(w, "# HELP %s %s\n", metricName, help)
	fmt.Fprintf(w, "# TYPE %s gauge\n", metricName)
	keys := make([]aggKey, 0, len(aggregates))
	for k := range aggregates {
		if k.metric == apiMetric {
			keys = append(keys, k)
		}
	}
	sort.Slice(keys, func(i, j int) bool {
		if keys[i].site != keys[j].site {
			return keys[i].site < keys[j].site
		}
		return keys[i].period < keys[j].period
	})
	for _, k := range keys {
		fmt.Fprintf(w, "%s{site=%q,period=%q} %s\n", metricName, k.site, k.period, fmtFloat(aggregates[k]))
	}
}

func fmtFloat(f float64) string {
	return strconv.FormatFloat(f, 'g', -1, 64)
}

func sortedKeys(m map[string]float64) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

func loadSites(path string) ([]site, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var sites []site
	if err := json.Unmarshal(data, &sites); err != nil {
		return nil, fmt.Errorf("parse %s: %w", path, err)
	}
	return sites, nil
}

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func main() {
	var (
		baseURL   = strings.TrimRight(env("PLAUSIBLE_BASE_URL", "http://plausible.crossplane-demo.svc.cluster.local:8000"), "/")
		apiKey    = os.Getenv("PLAUSIBLE_API_KEY")
		sitesFile = env("SITES_FILE", "/etc/plausible/sites.json")
		listen    = env("LISTEN_ADDR", ":8080")
		interval  = env("SCRAPE_INTERVAL", "60s")
	)

	if apiKey == "" {
		log.Fatal("PLAUSIBLE_API_KEY is required (Secret plausible-api-keys key stats-read-key)")
	}
	scrapeInterval, err := time.ParseDuration(interval)
	if err != nil {
		log.Fatalf("invalid SCRAPE_INTERVAL %q: %v", interval, err)
	}

	st := newStore()
	c := &collector{
		baseURL: baseURL,
		apiKey:  apiKey,
		client:  &http.Client{Timeout: 15 * time.Second},
		store:   st,
	}

	// Poller: reload sites.json each cycle so ConfigMap edits are picked up
	// without a pod restart.
	go func() {
		ticker := time.NewTicker(scrapeInterval)
		defer ticker.Stop()
		for {
			sites, err := loadSites(sitesFile)
			if err != nil {
				log.Printf("load sites: %v", err)
				st.mu.Lock()
				st.up = 0
				st.mu.Unlock()
			} else {
				// Registry-coverage gauges first: they're derived from the
				// registry alone, so publish them even if the Stats API is down.
				rc := countRegistry(sites)
				st.mu.Lock()
				st.registry = rc
				st.mu.Unlock()

				ctx, cancel := context.WithTimeout(context.Background(), scrapeInterval)
				c.collect(ctx, sites)
				cancel()
			}
			<-ticker.C
		}
	}()

	mux := http.NewServeMux()
	mux.HandleFunc("/metrics", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
		st.writeMetrics(w)
	})
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = io.WriteString(w, "ok\n")
	})

	srv := &http.Server{
		Addr:              listen,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}
	log.Printf("plausible-stats-exporter listening on %s (base=%s interval=%s)", listen, baseURL, scrapeInterval)
	log.Fatal(srv.ListenAndServe())
}
