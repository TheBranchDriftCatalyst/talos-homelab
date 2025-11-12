package k8s

import (
	"fmt"
	"regexp"
	"strings"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
)

// IngressRouteHandler extracts hostnames from Traefik IngressRoute CRDs
type IngressRouteHandler struct {
	hostRegex *regexp.Regexp
}

// NewIngressRouteHandler creates a new IngressRoute handler
func NewIngressRouteHandler() *IngressRouteHandler {
	// Regex to extract hostname from Host(`example.com`) or Host(`example.com`, `example2.com`)
	return &IngressRouteHandler{
		hostRegex: regexp.MustCompile(`Host\(` + "`" + `([^` + "`" + `]+)` + "`" + `\)`),
	}
}

// ExtractHostnames extracts all hostnames from an IngressRoute resource
func (h *IngressRouteHandler) ExtractHostnames(obj *unstructured.Unstructured) []string {
	var hostnames []string
	seen := make(map[string]bool)

	// Navigate to spec.routes[] array
	routes, found, err := unstructured.NestedSlice(obj.Object, "spec", "routes")
	if !found || err != nil {
		return hostnames
	}

	// Iterate through routes
	for _, route := range routes {
		routeMap, ok := route.(map[string]interface{})
		if !ok {
			continue
		}

		// Get the "match" field
		match, found, err := unstructured.NestedString(routeMap, "match")
		if !found || err != nil {
			continue
		}

		// Extract hosts from match expression
		// Examples:
		// - Host(`grafana.talos00`)
		// - Host(`grafana.talos00`) && PathPrefix(`/api`)
		// - Host(`app1.local`, `app2.local`)
		matches := h.hostRegex.FindAllStringSubmatch(match, -1)
		for _, m := range matches {
			if len(m) > 1 {
				// Split by comma in case of multiple hosts in one Host() clause
				hosts := strings.Split(m[1], ",")
				for _, host := range hosts {
					host = strings.TrimSpace(host)
					host = strings.Trim(host, "`")
					if host != "" && !seen[host] {
						hostnames = append(hostnames, host)
						seen[host] = true
					}
				}
			}
		}
	}

	return hostnames
}

// GetKey returns a unique key for the IngressRoute
func (h *IngressRouteHandler) GetKey(obj *unstructured.Unstructured) string {
	return fmt.Sprintf("%s/%s", obj.GetNamespace(), obj.GetName())
}
