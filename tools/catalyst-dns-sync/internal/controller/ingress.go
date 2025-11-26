package controller

import (
	"context"
	"log/slog"
	"strings"
	"time"

	"github.com/talos-fix/catalyst-dns-sync/internal/config"
	"github.com/talos-fix/catalyst-dns-sync/internal/dns"
	"github.com/talos-fix/catalyst-dns-sync/internal/metrics"

	networkingv1 "k8s.io/api/networking/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/handler"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"
)

// IngressRouteGVK is the GroupVersionKind for Traefik IngressRoute
var IngressRouteGVK = schema.GroupVersionKind{
	Group:   "traefik.io",
	Version: "v1alpha1",
	Kind:    "IngressRoute",
}

// DNSSyncController reconciles Ingress and IngressRoute resources
type DNSSyncController struct {
	client    client.Client
	dnsClient dns.DNSClient
	cfg       *config.Config
	logger    *slog.Logger
	scheme    *runtime.Scheme
}

// NewDNSSyncController creates a new DNS sync controller
func NewDNSSyncController(
	k8sClient client.Client,
	dnsClient dns.DNSClient,
	cfg *config.Config,
	logger *slog.Logger,
	scheme *runtime.Scheme,
) *DNSSyncController {
	return &DNSSyncController{
		client:    k8sClient,
		dnsClient: dnsClient,
		cfg:       cfg,
		logger:    logger,
		scheme:    scheme,
	}
}

// SetupWithManager sets up the controller with the Manager
func (r *DNSSyncController) SetupWithManager(mgr ctrl.Manager) error {
	// Create controller for standard Ingress
	if err := ctrl.NewControllerManagedBy(mgr).
		For(&networkingv1.Ingress{}).
		Complete(&IngressReconciler{controller: r}); err != nil {
		return err
	}

	// Create controller for IngressRoute (Traefik CRD)
	// Use unstructured to avoid importing Traefik types
	ingressRoute := &unstructured.Unstructured{}
	ingressRoute.SetGroupVersionKind(IngressRouteGVK)

	return ctrl.NewControllerManagedBy(mgr).
		For(ingressRoute).
		Watches(
			ingressRoute,
			&handler.EnqueueRequestForObject{},
		).
		Complete(&IngressRouteReconciler{controller: r})
}

// IngressReconciler reconciles standard Ingress resources
type IngressReconciler struct {
	controller *DNSSyncController
}

// Reconcile handles Ingress reconciliation
func (r *IngressReconciler) Reconcile(ctx context.Context, req reconcile.Request) (reconcile.Result, error) {
	start := time.Now()
	logger := r.controller.logger.With(
		"resource", "Ingress",
		"namespace", req.Namespace,
		"name", req.Name,
	)

	defer func() {
		duration := time.Since(start).Seconds()
		metrics.ReconcileDuration.WithLabelValues("Ingress").Observe(duration)
	}()

	var ingress networkingv1.Ingress
	if err := r.controller.client.Get(ctx, req.NamespacedName, &ingress); err != nil {
		if client.IgnoreNotFound(err) != nil {
			logger.Error("Failed to get Ingress", "error", err)
			metrics.ReconcileErrorsTotal.WithLabelValues("Ingress", "get").Inc()
			return reconcile.Result{}, err
		}
		// Ingress was deleted - handle cleanup
		logger.Info("Ingress deleted, cleaning up DNS records")
		// Note: We can't get hostnames from a deleted resource
		// In production, we'd use finalizers or track state
		return reconcile.Result{}, nil
	}

	// Extract hostnames from Ingress rules
	hostnames := r.extractHostnames(&ingress)
	if len(hostnames) == 0 {
		logger.Debug("No hostnames found in Ingress")
		return reconcile.Result{}, nil
	}

	// Update DNS records
	for _, hostname := range hostnames {
		if !r.controller.isInZone(hostname) {
			continue
		}
		if err := r.controller.dnsClient.CreateOrUpdateRecord(ctx, hostname); err != nil {
			logger.Error("Failed to create DNS record", "hostname", hostname, "error", err)
			metrics.ReconcileErrorsTotal.WithLabelValues("Ingress", "dns_create").Inc()
			continue
		}
		logger.Info("DNS record synced", "hostname", hostname)
	}

	metrics.IngressResources.WithLabelValues("Ingress", req.Namespace).Set(1)
	metrics.LastSyncTimestamp.SetToCurrentTime()

	return reconcile.Result{RequeueAfter: r.controller.cfg.SyncInterval}, nil
}

// extractHostnames gets all hostnames from an Ingress resource
func (r *IngressReconciler) extractHostnames(ingress *networkingv1.Ingress) []string {
	var hostnames []string
	seen := make(map[string]bool)

	for _, rule := range ingress.Spec.Rules {
		if rule.Host != "" && !seen[rule.Host] {
			hostnames = append(hostnames, rule.Host)
			seen[rule.Host] = true
		}
	}

	// Also check TLS hosts
	for _, tls := range ingress.Spec.TLS {
		for _, host := range tls.Hosts {
			if !seen[host] {
				hostnames = append(hostnames, host)
				seen[host] = true
			}
		}
	}

	return hostnames
}

// IngressRouteReconciler reconciles Traefik IngressRoute resources
type IngressRouteReconciler struct {
	controller *DNSSyncController
}

// Reconcile handles IngressRoute reconciliation
func (r *IngressRouteReconciler) Reconcile(ctx context.Context, req reconcile.Request) (reconcile.Result, error) {
	start := time.Now()
	logger := r.controller.logger.With(
		"resource", "IngressRoute",
		"namespace", req.Namespace,
		"name", req.Name,
	)

	defer func() {
		duration := time.Since(start).Seconds()
		metrics.ReconcileDuration.WithLabelValues("IngressRoute").Observe(duration)
	}()

	// Use unstructured to read IngressRoute
	ingressRoute := &unstructured.Unstructured{}
	ingressRoute.SetGroupVersionKind(IngressRouteGVK)

	if err := r.controller.client.Get(ctx, req.NamespacedName, ingressRoute); err != nil {
		if client.IgnoreNotFound(err) != nil {
			logger.Error("Failed to get IngressRoute", "error", err)
			metrics.ReconcileErrorsTotal.WithLabelValues("IngressRoute", "get").Inc()
			return reconcile.Result{}, err
		}
		// IngressRoute was deleted
		logger.Info("IngressRoute deleted")
		return reconcile.Result{}, nil
	}

	// Extract hostnames from IngressRoute spec
	hostnames := r.extractHostnames(ingressRoute)
	if len(hostnames) == 0 {
		logger.Debug("No hostnames found in IngressRoute")
		return reconcile.Result{}, nil
	}

	// Update DNS records
	for _, hostname := range hostnames {
		if !r.controller.isInZone(hostname) {
			continue
		}
		if err := r.controller.dnsClient.CreateOrUpdateRecord(ctx, hostname); err != nil {
			logger.Error("Failed to create DNS record", "hostname", hostname, "error", err)
			metrics.ReconcileErrorsTotal.WithLabelValues("IngressRoute", "dns_create").Inc()
			continue
		}
		logger.Info("DNS record synced", "hostname", hostname)
	}

	metrics.IngressResources.WithLabelValues("IngressRoute", req.Namespace).Set(1)
	metrics.LastSyncTimestamp.SetToCurrentTime()

	return reconcile.Result{RequeueAfter: r.controller.cfg.SyncInterval}, nil
}

// extractHostnames parses Host() matchers from IngressRoute routes
func (r *IngressRouteReconciler) extractHostnames(ir *unstructured.Unstructured) []string {
	var hostnames []string
	seen := make(map[string]bool)

	// Navigate to spec.routes
	spec, found, err := unstructured.NestedMap(ir.Object, "spec")
	if !found || err != nil {
		return hostnames
	}

	routes, found, err := unstructured.NestedSlice(spec, "routes")
	if !found || err != nil {
		return hostnames
	}

	for _, route := range routes {
		routeMap, ok := route.(map[string]interface{})
		if !ok {
			continue
		}

		match, found, err := unstructured.NestedString(routeMap, "match")
		if !found || err != nil {
			continue
		}

		// Parse Host() matcher: Host(`example.com`) or Host(`a.com`, `b.com`)
		extracted := parseHostMatcher(match)
		for _, h := range extracted {
			if !seen[h] {
				hostnames = append(hostnames, h)
				seen[h] = true
			}
		}
	}

	return hostnames
}

// parseHostMatcher extracts hostnames from Traefik match rules
// Examples:
//   - Host(`grafana.talos00`)
//   - Host(`a.talos00`) && PathPrefix(`/api`)
//   - Host(`a.talos00`, `b.talos00`)
func parseHostMatcher(match string) []string {
	var hostnames []string

	// Find Host() or Host`` patterns
	// Look for Host( or Host`
	idx := strings.Index(match, "Host(")
	if idx == -1 {
		idx = strings.Index(match, "Host`")
		if idx == -1 {
			return hostnames
		}
	}

	// Extract the content after Host
	remaining := match[idx+4:] // Skip "Host"

	// Handle both Host(`...`) and Host`...` syntax
	if strings.HasPrefix(remaining, "(") {
		// Find closing )
		endIdx := strings.Index(remaining, ")")
		if endIdx == -1 {
			return hostnames
		}
		content := remaining[1:endIdx]
		hostnames = extractBacktickStrings(content)
	} else if strings.HasPrefix(remaining, "`") {
		// Direct backtick syntax: Host`hostname`
		endIdx := strings.Index(remaining[1:], "`")
		if endIdx == -1 {
			return hostnames
		}
		hostnames = append(hostnames, remaining[1:endIdx+1])
	}

	return hostnames
}

// extractBacktickStrings extracts strings from backtick-quoted content
// Input: `a.com`, `b.com` or just `a.com`
func extractBacktickStrings(content string) []string {
	var result []string
	inBacktick := false
	var current strings.Builder

	for _, ch := range content {
		if ch == '`' {
			if inBacktick {
				// End of backtick string
				if current.Len() > 0 {
					result = append(result, current.String())
				}
				current.Reset()
			}
			inBacktick = !inBacktick
		} else if inBacktick {
			current.WriteRune(ch)
		}
	}

	return result
}

// isInZone checks if a hostname belongs to the configured DNS zone
func (c *DNSSyncController) isInZone(hostname string) bool {
	return strings.HasSuffix(hostname, "."+c.cfg.DNSZone) || hostname == c.cfg.DNSZone
}

// FullSync performs a full synchronization of all Ingress/IngressRoute resources
func (c *DNSSyncController) FullSync(ctx context.Context) error {
	logger := c.logger.With("operation", "full_sync")
	var allHostnames []string

	// List all Ingress resources
	var ingressList networkingv1.IngressList
	if err := c.client.List(ctx, &ingressList); err != nil {
		logger.Error("Failed to list Ingress resources", "error", err)
		return err
	}

	for _, ingress := range ingressList.Items {
		reconciler := &IngressReconciler{controller: c}
		hostnames := reconciler.extractHostnames(&ingress)
		for _, h := range hostnames {
			if c.isInZone(h) {
				allHostnames = append(allHostnames, h)
			}
		}
	}

	// List all IngressRoute resources
	ingressRouteList := &unstructured.UnstructuredList{}
	ingressRouteList.SetGroupVersionKind(schema.GroupVersionKind{
		Group:   "traefik.io",
		Version: "v1alpha1",
		Kind:    "IngressRouteList",
	})

	if err := c.client.List(ctx, ingressRouteList); err != nil {
		// IngressRoute CRD might not exist, that's OK
		logger.Warn("Failed to list IngressRoute resources (CRD may not exist)", "error", err)
	} else {
		for _, ir := range ingressRouteList.Items {
			reconciler := &IngressRouteReconciler{controller: c}
			hostnames := reconciler.extractHostnames(&ir)
			for _, h := range hostnames {
				if c.isInZone(h) {
					allHostnames = append(allHostnames, h)
				}
			}
		}
	}

	// Deduplicate
	seen := make(map[string]bool)
	var unique []string
	for _, h := range allHostnames {
		if !seen[h] {
			unique = append(unique, h)
			seen[h] = true
		}
	}

	logger.Info("Full sync found hostnames", "count", len(unique))

	// For dev mode with HostsFileClient, we can do a batch update
	if hostsClient, ok := c.dnsClient.(*dns.HostsFileClient); ok {
		return hostsClient.SetHostnames(unique)
	}

	// For Technitium, create/update each record
	for _, hostname := range unique {
		if err := c.dnsClient.CreateOrUpdateRecord(ctx, hostname); err != nil {
			logger.Error("Failed to sync DNS record", "hostname", hostname, "error", err)
		}
	}

	metrics.ManagedHostnames.Set(float64(len(unique)))
	metrics.LastSyncTimestamp.SetToCurrentTime()

	return nil
}
