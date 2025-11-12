package metrics

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

var (
	// SyncOperationsTotal tracks total sync operations
	SyncOperationsTotal = promauto.NewCounterVec(
		prometheus.CounterOpts{
			Name: "catalyst_dns_sync_operations_total",
			Help: "Total number of DNS sync operations",
		},
		[]string{"status"}, // success, failure
	)

	// RecordsTotal tracks DNS records processed
	RecordsTotal = promauto.NewCounterVec(
		prometheus.CounterOpts{
			Name: "catalyst_dns_sync_records_total",
			Help: "Total number of DNS records processed",
		},
		[]string{"action"}, // created, updated, deleted, skipped
	)

	// RecordsCurrent tracks current record count per zone
	RecordsCurrent = promauto.NewGaugeVec(
		prometheus.GaugeOpts{
			Name: "catalyst_dns_sync_records_current",
			Help: "Current number of DNS records managed",
		},
		[]string{"zone"},
	)

	// SyncDuration tracks sync operation duration
	SyncDuration = promauto.NewHistogramVec(
		prometheus.HistogramOpts{
			Name:    "catalyst_dns_sync_duration_seconds",
			Help:    "Duration of DNS sync operations",
			Buckets: prometheus.DefBuckets,
		},
		[]string{"operation"}, // full_sync, partial_sync
	)

	// APIRequestDuration tracks Technitium API request duration
	APIRequestDuration = promauto.NewHistogramVec(
		prometheus.HistogramOpts{
			Name:    "catalyst_dns_sync_api_request_duration_seconds",
			Help:    "Duration of Technitium API requests",
			Buckets: []float64{.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5},
		},
		[]string{"method", "endpoint"},
	)

	// APIErrorsTotal tracks API errors
	APIErrorsTotal = promauto.NewCounterVec(
		prometheus.CounterOpts{
			Name: "catalyst_dns_sync_api_errors_total",
			Help: "Total number of Technitium API errors",
		},
		[]string{"method", "endpoint", "status_code"},
	)

	// LastSuccessTimestamp tracks last successful sync
	LastSuccessTimestamp = promauto.NewGauge(
		prometheus.GaugeOpts{
			Name: "catalyst_dns_sync_last_success_timestamp_seconds",
			Help: "Timestamp of last successful sync operation",
		},
	)

	// SyncLag tracks time since last sync
	SyncLag = promauto.NewGauge(
		prometheus.GaugeOpts{
			Name: "catalyst_dns_sync_lag_seconds",
			Help: "Time in seconds since last successful sync",
		},
	)

	// HealthStatus tracks overall health
	HealthStatus = promauto.NewGauge(
		prometheus.GaugeOpts{
			Name: "catalyst_dns_sync_healthy",
			Help: "Health status of the DNS sync daemon (1 = healthy, 0 = unhealthy)",
		},
	)

	// ErrorsTotal tracks errors by type
	ErrorsTotal = promauto.NewCounterVec(
		prometheus.CounterOpts{
			Name: "catalyst_dns_sync_errors_total",
			Help: "Total number of errors by type",
		},
		[]string{"type"}, // network, validation, api, kubernetes, etc.
	)

	// IngressesWatched tracks number of ingresses being monitored
	IngressesWatched = promauto.NewGaugeVec(
		prometheus.GaugeOpts{
			Name: "catalyst_dns_sync_ingresses_watched",
			Help: "Number of Ingress resources currently being watched",
		},
		[]string{"type"}, // ingress, ingressroute
	)
)

func init() {
	// Initialize health as healthy
	HealthStatus.Set(1)
}
