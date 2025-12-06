# Architecture

## Overview

This section documents the architectural patterns, design decisions, and infrastructure blueprints for the Talos Kubernetes homelab. Understanding these concepts is crucial for maintaining and extending the cluster's capabilities while following established patterns.

## Quick Navigation

| Topic | Description | When to Read |
|-------|-------------|--------------|
| [dual-gitops.md](dual-gitops.md) | **CRITICAL** - Dual GitOps architecture separating infrastructure and application deployments | Before making any infrastructure or application changes |
| [gitops-responsibilities.md](gitops-responsibilities.md) | Clarifies what Flux manages vs. what ArgoCD manages | Setting up GitOps controllers or troubleshooting sync issues |
| [networking.md](networking.md) | Traefik v3 ingress controller architecture and IngressRoute configuration | Adding new services or configuring ingress routing |
| [observability.md](observability.md) | Monitoring and logging stack architecture (Prometheus, Grafana, OpenSearch, Graylog) | Setting up monitoring or troubleshooting observability stack |
| [infrastructure-diagrams.md](infrastructure-diagrams.md) | Visual diagrams of cluster architecture and component relationships | Understanding overall system design |
| [service-mesh.md](service-mesh.md) | **PLANNING** - Service mesh strategy (Linkerd, Istio) for hybrid cluster integration | Evaluating service mesh implementation |
| [auth-implementation-guide.md](auth-implementation-guide.md) | **PLANNING** - Authentication and authorization patterns (LDAP, Authelia, Authentik) | Implementing cluster-wide authentication |

## Key Concepts

- **Dual GitOps Pattern**: Infrastructure (scripts + kubectl) vs. Application (ArgoCD) deployments are intentionally separated for stability and control
- **Traefik v3**: Uses IngressRoute CRDs instead of traditional Ingress resources, deployed via Helm with full CRD support
- **Domain Pattern**: All services use `*.talos00` domains with `/etc/hosts` entries pointing to `192.168.1.54`
- **Observability Stack**: Dual-stack approach with Prometheus/Grafana for metrics and OpenSearch/Graylog for logs
- **GitOps Responsibilities**: Flux manages infrastructure, ArgoCD manages applications - never mix the two

## Common Tasks

### Understanding GitOps Workflow
- [Dual GitOps rules](dual-gitops.md#rules-and-standards) - Separation of concerns and repository patterns
- [Infrastructure deployment](dual-gitops.md#deployment-workflows) - How to add new infrastructure components
- [Application deployment](dual-gitops.md#adding-new-application) - How to add new ArgoCD-managed applications
- [GitOps responsibilities](gitops-responsibilities.md) - What each tool manages

### Configuring Ingress
- [IngressRoute examples](networking.md#ingressroute-example) - Traefik CRD patterns
- [Middleware configuration](networking.md#middleware-example) - Request/response modification
- [Adding new services](networking.md#adding-new-services) - Step-by-step ingress setup

### Working with Observability
- [Access monitoring services](observability.md) - Grafana, Prometheus, Alertmanager URLs
- [Configure log collection](observability.md) - Fluent Bit and Graylog setup
- [View metrics and logs](observability.md) - Dashboard access and query patterns

### Planning Enhancements
- [Service mesh evaluation](service-mesh.md) - Comparing Linkerd vs. Istio
- [Authentication patterns](auth-implementation-guide.md) - LDAP, Authelia, Authentik comparison
- [Infrastructure diagrams](infrastructure-diagrams.md) - Visualizing architecture

---

## Related Issues
<!-- Beads tracking for this section -->
- [CILIUM-kkw] - Initial creation of section README
