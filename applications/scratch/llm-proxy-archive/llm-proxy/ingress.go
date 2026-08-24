package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"sort"
	"strings"
	"sync"
	"time"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/client-go/dynamic"
	"k8s.io/client-go/rest"
)

// TabInfo represents a discovered tab from IngressRoute
type TabInfo struct {
	ID    string `json:"id"`
	Label string `json:"label"`
	Icon  string `json:"icon"`
	URL   string `json:"url,omitempty"`
}

// IngressDiscovery discovers IngressRoutes in the namespace
type IngressDiscovery struct {
	client    dynamic.Interface
	namespace string
	cache     []TabInfo
	cacheMu   sync.RWMutex
	cacheTime time.Time
	cacheTTL  time.Duration
}

// NewIngressDiscovery creates a new ingress discovery instance
func NewIngressDiscovery() (*IngressDiscovery, error) {
	namespace := os.Getenv("POD_NAMESPACE")
	if namespace == "" {
		namespace = "catalyst-llm"
	}

	// Try in-cluster config first
	config, err := rest.InClusterConfig()
	if err != nil {
		log.Printf("⚠️  Not running in cluster, ingress discovery disabled: %v", err)
		return nil, err
	}

	client, err := dynamic.NewForConfig(config)
	if err != nil {
		return nil, err
	}

	d := &IngressDiscovery{
		client:    client,
		namespace: namespace,
		cacheTTL:  30 * time.Second,
	}

	log.Printf("   Ingress discovery: enabled (namespace: %s)", namespace)
	return d, nil
}

// iconForService returns an appropriate icon for a service name
func iconForService(name string) string {
	icons := map[string]string{
		"open-webui":    "message-circle",
		"chat":          "message-circle",
		"sillytavern":   "theater",
		"lobe":          "bot",
		"lobe-chat":     "bot",
		"ollama":        "llama",
		"rabbitmq":      "rabbit",
		"searxng":       "search",
		"llm-proxy":     "settings",
		"catalyst-llm":  "settings",
	}

	// Check for partial matches
	lower := strings.ToLower(name)
	for key, icon := range icons {
		if strings.Contains(lower, key) {
			return icon
		}
	}
	return "external-link" // default icon
}

// labelForHost converts host to a readable label
func labelForHost(host string) string {
	// Extract service name from host (e.g., "chat.talos00" -> "Chat")
	parts := strings.Split(host, ".")
	if len(parts) > 0 {
		name := parts[0]
		// Capitalize and prettify
		name = strings.ReplaceAll(name, "-", " ")
		words := strings.Split(name, " ")
		for i, word := range words {
			if len(word) > 0 {
				words[i] = strings.ToUpper(string(word[0])) + word[1:]
			}
		}
		return strings.Join(words, " ")
	}
	return host
}

// GetTabs returns discovered tabs from IngressRoutes
func (d *IngressDiscovery) GetTabs() []TabInfo {
	// Check cache
	d.cacheMu.RLock()
	if time.Since(d.cacheTime) < d.cacheTTL && d.cache != nil {
		tabs := d.cache
		d.cacheMu.RUnlock()
		return tabs
	}
	d.cacheMu.RUnlock()

	// Refresh cache
	tabs := d.discoverTabs()

	d.cacheMu.Lock()
	d.cache = tabs
	d.cacheTime = time.Now()
	d.cacheMu.Unlock()

	return tabs
}

// discoverTabs queries IngressRoutes from the Kubernetes API
func (d *IngressDiscovery) discoverTabs() []TabInfo {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	// IngressRoute GVR for Traefik
	gvr := schema.GroupVersionResource{
		Group:    "traefik.io",
		Version:  "v1alpha1",
		Resource: "ingressroutes",
	}

	list, err := d.client.Resource(gvr).Namespace(d.namespace).List(ctx, metav1.ListOptions{})
	if err != nil {
		log.Printf("⚠️  Failed to list IngressRoutes: %v", err)
		return nil
	}

	// Skip these internal routes
	skipRoutes := map[string]bool{
		"catalyst-llm-api": true, // Internal API route
		"ollama":           true, // Direct ollama route (goes through proxy)
		"ollama-direct":    true, // Direct bypass route
		"llm-proxy-dashboard": true, // The dashboard itself
	}

	var tabs []TabInfo
	for _, item := range list.Items {
		name := item.GetName()

		// Skip internal routes
		if skipRoutes[name] {
			continue
		}

		// Extract host from routes[0].match
		routes, found, _ := unstructured.NestedSlice(item.Object, "spec", "routes")
		if !found || len(routes) == 0 {
			continue
		}

		route, ok := routes[0].(map[string]interface{})
		if !ok {
			continue
		}

		match, _, _ := unstructured.NestedString(route, "match")
		// Parse Host(`hostname`) from match rule
		host := extractHost(match)
		if host == "" {
			continue
		}

		tabs = append(tabs, TabInfo{
			ID:    name,
			Label: labelForHost(host),
			Icon:  iconForService(name),
			URL:   "http://" + host,
		})
	}

	// Sort tabs alphabetically by label
	sort.Slice(tabs, func(i, j int) bool {
		return tabs[i].Label < tabs[j].Label
	})

	return tabs
}

// extractHost extracts hostname from Traefik match rule
// e.g., "Host(`chat.talos00`)" -> "chat.talos00"
func extractHost(match string) string {
	// Look for Host(`...`)
	start := strings.Index(match, "Host(`")
	if start == -1 {
		return ""
	}
	start += 6 // len("Host(`")

	end := strings.Index(match[start:], "`)")
	if end == -1 {
		return ""
	}

	return match[start : start+end]
}

// TabsHandler returns an HTTP handler for the tabs endpoint
func (d *IngressDiscovery) TabsHandler(w http.ResponseWriter, r *http.Request) {
	tabs := d.GetTabs()

	// Always include Control Panel as first tab
	allTabs := []TabInfo{
		{ID: "control", Label: "Control Panel", Icon: "settings"},
	}
	allTabs = append(allTabs, tabs...)

	writeJSON(w, http.StatusOK, allTabs)
}

// TabsHandlerFallback returns static tabs when not running in cluster
func TabsHandlerFallback(w http.ResponseWriter, r *http.Request) {
	// Fallback static tabs for development
	tabs := []TabInfo{
		{ID: "control", Label: "Control Panel", Icon: "settings"},
		{ID: "chat", Label: "Open WebUI", Icon: "message-circle", URL: "http://chat.talos00"},
		{ID: "sillytavern", Label: "SillyTavern", Icon: "theater", URL: "http://sillytavern.talos00"},
		{ID: "lobe", Label: "Lobe Chat", Icon: "bot", URL: "http://lobe.talos00"},
		{ID: "ollama", Label: "Ollama API", Icon: "llama", URL: "http://ollama.talos00"},
		{ID: "rabbitmq", Label: "RabbitMQ", Icon: "rabbit", URL: "http://rabbitmq.talos00"},
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(tabs)
}
