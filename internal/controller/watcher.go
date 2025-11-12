package controller

import (
	"context"
	"time"

	networkingv1 "k8s.io/api/networking/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/client-go/dynamic/dynamicinformer"
	"k8s.io/client-go/informers"
	"k8s.io/client-go/tools/cache"
)

// runWatchMode runs the controller in watch mode using Kubernetes informers
func (c *Controller) runWatchMode(ctx context.Context) error {
	c.logger.Info().Msg("Starting watch mode with Kubernetes informers")

	// Create informer factory for standard Ingresses
	factory := informers.NewSharedInformerFactory(c.k8sClient, c.cfg.ResyncInterval)

	// Setup Ingress informer
	ingressInformer := factory.Networking().V1().Ingresses().Informer()
	ingressInformer.AddEventHandler(cache.ResourceEventHandlerFuncs{
		AddFunc: func(obj interface{}) {
			ingress := obj.(*networkingv1.Ingress)
			c.handleIngressAdd(ingress)
		},
		UpdateFunc: func(oldObj, newObj interface{}) {
			ingress := newObj.(*networkingv1.Ingress)
			c.handleIngressUpdate(ingress)
		},
		DeleteFunc: func(obj interface{}) {
			ingress := obj.(*networkingv1.Ingress)
			c.handleIngressDelete(ingress)
		},
	})

	// Setup IngressRoute informer (dynamic)
	dynamicFactory := dynamicinformer.NewDynamicSharedInformerFactory(c.dynamicClient, c.cfg.ResyncInterval)
	ingressRouteGVR := schema.GroupVersionResource{
		Group:    "traefik.io",
		Version:  "v1alpha1",
		Resource: "ingressroutes",
	}

	ingressRouteInformer := dynamicFactory.ForResource(ingressRouteGVR).Informer()
	ingressRouteInformer.AddEventHandler(cache.ResourceEventHandlerFuncs{
		AddFunc: func(obj interface{}) {
			unstructuredObj := obj.(*unstructured.Unstructured)
			c.handleIngressRouteAdd(unstructuredObj)
		},
		UpdateFunc: func(oldObj, newObj interface{}) {
			unstructuredObj := newObj.(*unstructured.Unstructured)
			c.handleIngressRouteUpdate(unstructuredObj)
		},
		DeleteFunc: func(obj interface{}) {
			unstructuredObj := obj.(*unstructured.Unstructured)
			c.handleIngressRouteDelete(unstructuredObj)
		},
	})

	// Start informers
	factory.Start(ctx.Done())
	dynamicFactory.Start(ctx.Done())

	// Wait for cache sync
	c.logger.Info().Msg("Waiting for informer caches to sync")
	if !cache.WaitForCacheSync(ctx.Done(), ingressInformer.HasSynced) {
		return ctx.Err()
	}
	if !cache.WaitForCacheSync(ctx.Done(), ingressRouteInformer.HasSynced) {
		c.logger.Warn().Msg("IngressRoute informer cache sync failed (CRD might not exist)")
	}

	c.logger.Info().Msg("Informer caches synced, watching for changes")

	// Update sync lag metric periodically
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
			c.updateSyncLag()
		}
	}
}

// handleIngressAdd handles Ingress add events
func (c *Controller) handleIngressAdd(ingress *networkingv1.Ingress) {
	hostnames := c.ingressHandler.ExtractHostnames(ingress)
	key := c.ingressHandler.GetKey(ingress)

	c.logger.Info().
		Str("ingress", key).
		Strs("hostnames", hostnames).
		Msg("Ingress added")

	for _, hostname := range hostnames {
		if c.shouldManageHostname(hostname) {
			if err := c.ensureDNSRecord(hostname, key); err != nil {
				c.logger.Error().Err(err).
					Str("hostname", hostname).
					Msg("Failed to create DNS record")
			}
		}
	}
}

// handleIngressUpdate handles Ingress update events
func (c *Controller) handleIngressUpdate(ingress *networkingv1.Ingress) {
	// For updates, re-sync all hostnames for this ingress
	c.handleIngressAdd(ingress)
}

// handleIngressDelete handles Ingress delete events
func (c *Controller) handleIngressDelete(ingress *networkingv1.Ingress) {
	hostnames := c.ingressHandler.ExtractHostnames(ingress)
	key := c.ingressHandler.GetKey(ingress)

	c.logger.Info().
		Str("ingress", key).
		Strs("hostnames", hostnames).
		Msg("Ingress deleted")

	c.recordsMutex.Lock()
	defer c.recordsMutex.Unlock()

	for _, hostname := range hostnames {
		if c.shouldManageHostname(hostname) {
			// Only delete if this ingress was the source
			if source, exists := c.managedRecords[hostname]; exists && source == key {
				name := c.extractSubdomain(hostname)
				if err := c.dnsClient.DeleteRecord(c.cfg.TechnitiumZone, name, c.cfg.NodeIP); err != nil {
					c.logger.Error().Err(err).
						Str("hostname", hostname).
						Msg("Failed to delete DNS record")
				} else {
					delete(c.managedRecords, hostname)
				}
			}
		}
	}
}

// handleIngressRouteAdd handles IngressRoute add events
func (c *Controller) handleIngressRouteAdd(obj *unstructured.Unstructured) {
	hostnames := c.ingressRouteHandler.ExtractHostnames(obj)
	key := c.ingressRouteHandler.GetKey(obj)

	c.logger.Info().
		Str("ingressroute", key).
		Strs("hostnames", hostnames).
		Msg("IngressRoute added")

	for _, hostname := range hostnames {
		if c.shouldManageHostname(hostname) {
			if err := c.ensureDNSRecord(hostname, key); err != nil {
				c.logger.Error().Err(err).
					Str("hostname", hostname).
					Msg("Failed to create DNS record")
			}
		}
	}
}

// handleIngressRouteUpdate handles IngressRoute update events
func (c *Controller) handleIngressRouteUpdate(obj *unstructured.Unstructured) {
	c.handleIngressRouteAdd(obj)
}

// handleIngressRouteDelete handles IngressRoute delete events
func (c *Controller) handleIngressRouteDelete(obj *unstructured.Unstructured) {
	hostnames := c.ingressRouteHandler.ExtractHostnames(obj)
	key := c.ingressRouteHandler.GetKey(obj)

	c.logger.Info().
		Str("ingressroute", key).
		Strs("hostnames", hostnames).
		Msg("IngressRoute deleted")

	c.recordsMutex.Lock()
	defer c.recordsMutex.Unlock()

	for _, hostname := range hostnames {
		if c.shouldManageHostname(hostname) {
			if source, exists := c.managedRecords[hostname]; exists && source == key {
				name := c.extractSubdomain(hostname)
				if err := c.dnsClient.DeleteRecord(c.cfg.TechnitiumZone, name, c.cfg.NodeIP); err != nil {
					c.logger.Error().Err(err).
						Str("hostname", hostname).
						Msg("Failed to delete DNS record")
				} else {
					delete(c.managedRecords, hostname)
				}
			}
		}
	}
}

// updateSyncLag updates the sync lag metric
func (c *Controller) updateSyncLag() {
	// This is a simple implementation - in watch mode, lag should be minimal
	// You could enhance this to track actual lag if needed
}
