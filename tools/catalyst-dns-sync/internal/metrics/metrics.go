package metrics

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

const (
	namespace = "catalyst_dns_sync"
)

var (
	// RecordsTotal counts DNS records created/updated/deleted
	RecordsTotal = promauto.NewCounterVec(
		prometheus.CounterOpts{
			Namespace: namespace,
			Name:      "records_total",
			Help:      "Total number of DNS records created/updated/deleted",
		},
		[]string{"operation", "zone", "status"},
	)

	// APIRequestsTotal counts DNS API calls
	APIRequestsTotal = promauto.NewCounterVec(
		prometheus.CounterOpts{
			Namespace: namespace,
			Name:      "api_requests_total",
			Help:      "Total number of DNS API requests",
		},
		[]string{"endpoint", "method", "status_code"},
	)

	// APIRequestDuration tracks API request latency
	APIRequestDuration = promauto.NewHistogramVec(
		prometheus.HistogramOpts{
			Namespace: namespace,
			Name:      "api_request_duration_seconds",
			Help:      "Duration of DNS API requests in seconds",
			Buckets:   prometheus.DefBuckets,
		},
		[]string{"endpoint", "method"},
	)

	// ReconcileDuration tracks controller reconciliation time
	ReconcileDuration = promauto.NewHistogramVec(
		prometheus.HistogramOpts{
			Namespace: namespace,
			Name:      "reconcile_duration_seconds",
			Help:      "Duration of controller reconciliation in seconds",
			Buckets:   prometheus.DefBuckets,
		},
		[]string{"resource_type"},
	)

	// ReconcileErrorsTotal counts reconciliation errors
	ReconcileErrorsTotal = promauto.NewCounterVec(
		prometheus.CounterOpts{
			Namespace: namespace,
			Name:      "reconcile_errors_total",
			Help:      "Total number of reconciliation errors",
		},
		[]string{"resource_type", "error_type"},
	)

	// IngressResources tracks current watched Ingress resources
	IngressResources = promauto.NewGaugeVec(
		prometheus.GaugeOpts{
			Namespace: namespace,
			Name:      "ingress_resources",
			Help:      "Number of Ingress resources currently being watched",
		},
		[]string{"resource_type", "namespace"},
	)

	// ManagedHostnames tracks the number of managed DNS hostnames
	ManagedHostnames = promauto.NewGauge(
		prometheus.GaugeOpts{
			Namespace: namespace,
			Name:      "managed_hostnames",
			Help:      "Number of hostnames currently managed by the controller",
		},
	)

	// LastSyncTimestamp tracks when the last successful sync occurred
	LastSyncTimestamp = promauto.NewGauge(
		prometheus.GaugeOpts{
			Namespace: namespace,
			Name:      "last_sync_timestamp_seconds",
			Help:      "Unix timestamp of the last successful sync",
		},
	)
)

// RecordCreated increments the counter for a created record
func RecordCreated(zone string) {
	RecordsTotal.WithLabelValues("create", zone, "success").Inc()
}

// RecordUpdated increments the counter for an updated record
func RecordUpdated(zone string) {
	RecordsTotal.WithLabelValues("update", zone, "success").Inc()
}

// RecordDeleted increments the counter for a deleted record
func RecordDeleted(zone string) {
	RecordsTotal.WithLabelValues("delete", zone, "success").Inc()
}

// RecordFailed increments the counter for a failed operation
func RecordFailed(operation, zone string) {
	RecordsTotal.WithLabelValues(operation, zone, "error").Inc()
}
