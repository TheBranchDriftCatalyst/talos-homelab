package k8s

import (
	"fmt"
	"strings"

	networkingv1 "k8s.io/api/networking/v1"
)

// IngressHandler extracts hostnames from standard Ingress resources
type IngressHandler struct{}

// NewIngressHandler creates a new Ingress handler
func NewIngressHandler() *IngressHandler {
	return &IngressHandler{}
}

// ExtractHostnames extracts all hostnames from an Ingress resource
func (h *IngressHandler) ExtractHostnames(ingress *networkingv1.Ingress) []string {
	var hostnames []string
	seen := make(map[string]bool)

	// Extract from rules
	for _, rule := range ingress.Spec.Rules {
		if rule.Host != "" && !seen[rule.Host] {
			hostnames = append(hostnames, rule.Host)
			seen[rule.Host] = true
		}
	}

	// Extract from TLS
	for _, tls := range ingress.Spec.TLS {
		for _, host := range tls.Hosts {
			if host != "" && !seen[host] {
				hostnames = append(hostnames, host)
				seen[host] = true
			}
		}
	}

	return hostnames
}

// GetKey returns a unique key for the Ingress
func (h *IngressHandler) GetKey(ingress *networkingv1.Ingress) string {
	return fmt.Sprintf("%s/%s", ingress.Namespace, ingress.Name)
}
