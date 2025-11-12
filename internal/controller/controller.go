package controller

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/rs/zerolog"
	"github.com/yourusername/catalyst-dns-sync/internal/config"
	"github.com/yourusername/catalyst-dns-sync/internal/k8s"
	"github.com/yourusername/catalyst-dns-sync/internal/metrics"
	"github.com/yourusername/catalyst-dns-sync/internal/technitium"

	networkingv1 "k8s.io/api/networking/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/client-go/dynamic"
	"k8s.io/client-go/informers"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/cache"
	"k8s.io/client-go/tools/clientcmd"
)

// Controller manages DNS synchronization
type Controller struct {
	cfg               *config.Config
	k8sClient         *kubernetes.Clientset
	dynamicClient     dynamic.Interface
	dnsClient         *technitium.Client
	ingressHandler    *k8s.IngressHandler
	ingressRouteHandler *k8s.IngressRouteHandler
	logger            zerolog.Logger

	// Track managed DNS records
	managedRecords map[string]string // hostname -> source (ingress key)
	recordsMutex   sync.RWMutex
}

// NewController creates a new DNS sync controller
func NewController(cfg *config.Config, logger zerolog.Logger) (*Controller, error) {
	// Build Kubernetes config
	var restConfig *rest.Config
	var err error

	if cfg.InCluster {
		restConfig, err = rest.InClusterConfig()
	} else {
		restConfig, err = clientcmd.BuildConfigFromFlags("", cfg.Kubeconfig)
	}
	if err != nil {
		return nil, fmt.Errorf("failed to build kubernetes config: %w", err)
	}

	// Create Kubernetes clients
	k8sClient, err := kubernetes.NewForConfig(restConfig)
	if err != nil {
		return nil, fmt.Errorf("failed to create kubernetes client: %w", err)
	}

	dynamicClient, err := dynamic.NewForConfig(restConfig)
	if err != nil {
		return nil, fmt.Errorf("failed to create dynamic client: %w", err)
	}

	// Create Technitium client
	dnsClient := technitium.NewClient(cfg.TechnitiumURL, cfg.TechnitiumUsername, cfg.TechnitiumPassword, logger)

	// Login to Technitium
	if err := dnsClient.Login(); err != nil {
		return nil, fmt.Errorf("failed to login to Technitium: %w", err)
	}

	return &Controller{
		cfg:                 cfg,
		k8sClient:           k8sClient,
		dynamicClient:       dynamicClient,
		dnsClient:           dnsClient,
		ingressHandler:      k8s.NewIngressHandler(),
		ingressRouteHandler: k8s.NewIngressRouteHandler(),
		logger:              logger.With().Str("component", "controller").Logger(),
		managedRecords:      make(map[string]string),
	}, nil
}

// Run starts the controller in the configured mode
func (c *Controller) Run(ctx context.Context) error {
	c.logger.Info().
		Str("mode", c.cfg.Mode).
		Str("zone", c.cfg.TechnitiumZone).
		Str("node_ip", c.cfg.NodeIP).
		Msg("Starting DNS sync controller")

	// Initial sync
	if err := c.syncAll(ctx); err != nil {
		c.logger.Error().Err(err).Msg("Initial sync failed")
		metrics.HealthStatus.Set(0)
		return err
	}

	if c.cfg.Mode == "watch" {
		return c.runWatchMode(ctx)
	}
	return c.runPollMode(ctx)
}

// syncAll performs a full synchronization of all Ingress resources
func (c *Controller) syncAll(ctx context.Context) error {
	start := time.Now()
	c.logger.Info().Msg("Starting full sync")

	defer func() {
		duration := time.Since(start).Seconds()
		metrics.SyncDuration.WithLabelValues("full_sync").Observe(duration)
		c.logger.Info().
			Float64("duration_seconds", duration).
			Msg("Full sync completed")
	}()

	desiredRecords := make(map[string]string) // hostname -> source

	// Sync standard Ingresses
	if err := c.syncIngresses(ctx, desiredRecords); err != nil {
		metrics.SyncOperationsTotal.WithLabelValues("failure").Inc()
		metrics.ErrorsTotal.WithLabelValues("kubernetes").Inc()
		return err
	}

	// Sync Traefik IngressRoutes
	if err := c.syncIngressRoutes(ctx, desiredRecords); err != nil {
		metrics.SyncOperationsTotal.WithLabelValues("failure").Inc()
		metrics.ErrorsTotal.WithLabelValues("kubernetes").Inc()
		return err
	}

	// Ensure DNS records
	for hostname, source := range desiredRecords {
		if err := c.ensureDNSRecord(hostname, source); err != nil {
			c.logger.Error().Err(err).
				Str("hostname", hostname).
				Str("source", source).
				Msg("Failed to ensure DNS record")
			continue
		}
	}

	// Clean up orphaned records
	c.cleanupOrphanedRecords(desiredRecords)

	// Update metrics
	c.recordsMutex.RLock()
	metrics.RecordsCurrent.WithLabelValues(c.cfg.TechnitiumZone).Set(float64(len(c.managedRecords)))
	c.recordsMutex.RUnlock()

	metrics.SyncOperationsTotal.WithLabelValues("success").Inc()
	metrics.LastSuccessTimestamp.SetToCurrentTime()
	metrics.HealthStatus.Set(1)

	return nil
}

// syncIngresses syncs standard Ingress resources
func (c *Controller) syncIngresses(ctx context.Context, desiredRecords map[string]string) error {
	ingresses, err := c.k8sClient.NetworkingV1().Ingresses("").List(ctx, metav1.ListOptions{})
	if err != nil {
		return fmt.Errorf("failed to list ingresses: %w", err)
	}

	count := 0
	for _, ingress := range ingresses.Items {
		hostnames := c.ingressHandler.ExtractHostnames(&ingress)
		key := c.ingressHandler.GetKey(&ingress)

		for _, hostname := range hostnames {
			if c.shouldManageHostname(hostname) {
				desiredRecords[hostname] = key
				count++
			}
		}
	}

	metrics.IngressesWatched.WithLabelValues("ingress").Set(float64(len(ingresses.Items)))
	c.logger.Debug().
		Int("ingresses", len(ingresses.Items)).
		Int("hostnames", count).
		Msg("Synced standard Ingresses")

	return nil
}

// syncIngressRoutes syncs Traefik IngressRoute CRDs
func (c *Controller) syncIngressRoutes(ctx context.Context, desiredRecords map[string]string) error {
	// Define IngressRoute GVR
	ingressRouteGVR := schema.GroupVersionResource{
		Group:    "traefik.io",
		Version:  "v1alpha1",
		Resource: "ingressroutes",
	}

	ingressRoutes, err := c.dynamicClient.Resource(ingressRouteGVR).Namespace("").List(ctx, metav1.ListOptions{})
	if err != nil {
		// IngressRoute CRD might not exist, log warning and continue
		c.logger.Warn().Err(err).Msg("Failed to list IngressRoutes (CRD might not exist)")
		return nil
	}

	count := 0
	for _, item := range ingressRoutes.Items {
		hostnames := c.ingressRouteHandler.ExtractHostnames(&item)
		key := c.ingressRouteHandler.GetKey(&item)

		for _, hostname := range hostnames {
			if c.shouldManageHostname(hostname) {
				desiredRecords[hostname] = key
				count++
			}
		}
	}

	metrics.IngressesWatched.WithLabelValues("ingressroute").Set(float64(len(ingressRoutes.Items)))
	c.logger.Debug().
		Int("ingressroutes", len(ingressRoutes.Items)).
		Int("hostnames", count).
		Msg("Synced Traefik IngressRoutes")

	return nil
}

// shouldManageHostname checks if a hostname should be managed
func (c *Controller) shouldManageHostname(hostname string) bool {
	// Only manage hostnames in our zone
	return strings.HasSuffix(hostname, "."+c.cfg.TechnitiumZone) || hostname == c.cfg.TechnitiumZone
}

// ensureDNSRecord ensures a DNS record exists
func (c *Controller) ensureDNSRecord(hostname, source string) error {
	// Extract subdomain from hostname
	name := c.extractSubdomain(hostname)

	action, err := c.dnsClient.EnsureRecord(c.cfg.TechnitiumZone, name, c.cfg.NodeIP, c.cfg.TTL)
	if err != nil {
		metrics.ErrorsTotal.WithLabelValues("api").Inc()
		return err
	}

	// Track managed record
	c.recordsMutex.Lock()
	c.managedRecords[hostname] = source
	c.recordsMutex.Unlock()

	// Update metrics
	metrics.RecordsTotal.WithLabelValues(action).Inc()

	return nil
}

// cleanupOrphanedRecords removes DNS records that are no longer needed
func (c *Controller) cleanupOrphanedRecords(desiredRecords map[string]string) {
	c.recordsMutex.Lock()
	defer c.recordsMutex.Unlock()

	for hostname := range c.managedRecords {
		if _, exists := desiredRecords[hostname]; !exists {
			// Record is orphaned, delete it
			name := c.extractSubdomain(hostname)
			if err := c.dnsClient.DeleteRecord(c.cfg.TechnitiumZone, name, c.cfg.NodeIP); err != nil {
				c.logger.Error().Err(err).
					Str("hostname", hostname).
					Msg("Failed to delete orphaned DNS record")
				metrics.ErrorsTotal.WithLabelValues("api").Inc()
				continue
			}

			delete(c.managedRecords, hostname)
			metrics.RecordsTotal.WithLabelValues("deleted").Inc()

			c.logger.Info().
				Str("hostname", hostname).
				Msg("Deleted orphaned DNS record")
		}
	}
}

// extractSubdomain extracts the subdomain part from a hostname
// Example: "grafana.talos00" -> "grafana", "talos00" -> "@"
func (c *Controller) extractSubdomain(hostname string) string {
	if hostname == c.cfg.TechnitiumZone {
		return "@" // Root record
	}

	suffix := "." + c.cfg.TechnitiumZone
	if strings.HasSuffix(hostname, suffix) {
		return strings.TrimSuffix(hostname, suffix)
	}

	return hostname
}
