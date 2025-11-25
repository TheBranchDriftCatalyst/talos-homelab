# Root Tiltfile - Talos Homelab Infrastructure
# Orchestrates all namespace development environments
#
# Usage:
#   tilt up                          # Start all namespaces
#   tilt up arr-stack                # Start specific namespace
#   tilt up monitoring observability # Start multiple namespaces
#   SUSPEND_FLUX=false tilt up       # Start without suspending Flux
#
# Architecture:
#   This root Tiltfile orchestrates namespace-specific Tiltfiles:
#   - applications/arr-stack/Tiltfile     - Media automation
#   - infrastructure/base/monitoring/     - Monitoring (TODO: Phase 2)
#   - infrastructure/base/observability/  - Observability (TODO: Phase 2)
#
#   Each namespace Tiltfile is self-contained with its own:
#   - Kustomize overlays (dev/prod)
#   - Resource configurations
#   - Port forwards
#   - Dependencies

# Load Tilt extensions
load('ext://namespace', 'namespace_create')
load('ext://helm_resource', 'helm_resource', 'helm_repo')

# Configuration
config.define_string('k8s_context', args=False, usage='Kubernetes context to use')
config.define_bool('flux-suspend', args=False, usage='Suspend Flux reconciliation during development')
cfg = config.parse()

# Settings
settings = {
    'k8s_context': cfg.get('k8s_context', 'kubernetes-admin@talos00'),
    'flux_suspend': cfg.get('flux-suspend', True),
}

# Ensure we're using the correct k8s context
allow_k8s_contexts(settings['k8s_context'])

print("""
╔═══════════════════════════════════════════════════════════════╗
║  Talos Homelab Infrastructure Development with Tilt           ║
╚═══════════════════════════════════════════════════════════════╝

🎯 K8s Context: %s
🔧 Flux Auto-suspend: %s

Architecture: Orchestrated Namespace Pattern
  - Root Tiltfile orchestrates namespace-specific Tiltfiles
  - Each namespace manages its own overlays and resources
  - Flux-aware development (suspend/resume)

Available Commands:
  - Press SPACE to open the Tilt UI in your browser
  - Press 'r' to force rebuild a resource
  - Press 'k' to view Kubernetes events
""" % (settings['k8s_context'], settings['flux_suspend']))

# Suspend Flux if configured
if settings['flux_suspend']:
    print('⏸️  Suspending Flux reconciliation...')
    local('flux suspend kustomization flux-system')
    print('✅ Flux suspended')
    print('')

# ============================================
# Flux Control Resources
# ============================================

local_resource(
    'flux-reconcile',
    'flux reconcile kustomization flux-system --with-source',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=['flux-control']
)

local_resource(
    'flux-status',
    'flux get all',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=['flux-control']
)

local_resource(
    'flux-suspend-all',
    'flux suspend kustomization --all',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=['flux-control']
)

local_resource(
    'flux-resume-all',
    'flux resume kustomization --all',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=['flux-control']
)

# Resume Flux when Tilt shuts down
if settings['flux_suspend']:
    local_resource(
        'flux-resume-on-shutdown',
        cmd='flux resume kustomization flux-system',
        auto_init=False,
        trigger_mode=TRIGGER_MODE_MANUAL,
        labels=['flux-control']
    )

# ============================================
# Application Namespaces
# ============================================

print('📱 Loading Application Namespaces...')
print('')

# Arr-Stack - Media Automation
# Note: This includes its own Flux suspension logic, resource definitions,
# port-forwards, and dependencies. See applications/arr-stack/Tiltfile
print('  📺 Arr-Stack (Media Automation)')
include('./applications/arr-stack/Tiltfile')
print('')

# TODO: Add more application namespaces as they implement Tilt pattern
# include('./applications/other-app/Tiltfile')

# ============================================
# Infrastructure Namespaces (TODO: Phase 2)
# ============================================

print('🏗️  Infrastructure Namespaces (Phase 2 - TBD)...')
print('')

# TODO: Monitoring Stack
# print('  📊 Monitoring (Prometheus, Grafana)')
# include('./infrastructure/base/monitoring/Tiltfile')

# TODO: Observability Stack
# print('  🔍 Observability (OpenSearch, Graylog)')
# include('./infrastructure/base/observability/Tiltfile')

print('')

# ============================================
# Infrastructure Testing Tools
# ============================================

# Namespace
namespace_create('infra-testing')

# Deploy infra-testing stack with hot reload
watch_file('infrastructure/base/infra-testing/')
k8s_yaml(kustomize('infrastructure/base/infra-testing'))

# Headlamp
k8s_resource(
    workload='headlamp',
    new_name='infra-testing:headlamp',
    port_forwards=['8080:4466'],
    labels=['ui-tools'],
    links=[
        link('http://headlamp.talos00', 'Headlamp UI (via Traefik)'),
        link('http://localhost:8080', 'Headlamp UI (port-forward)')
    ]
)

# Kubeview
k8s_resource(
    workload='kubeview',
    new_name='infra-testing:kubeview',
    port_forwards=['8081:8000'],
    labels=['ui-tools'],
    links=[
        link('http://kubeview.talos00', 'Kubeview (via Traefik)'),
        link('http://localhost:8081', 'Kubeview (port-forward)')
    ]
)

# Kube-ops-view
k8s_resource(
    workload='kube-ops-view',
    new_name='infra-testing:kube-ops-view',
    port_forwards=['8082:8080'],
    labels=['ui-tools'],
    links=[
        link('http://kube-ops-view.talos00', 'Kube-ops-view (via Traefik)'),
        link('http://localhost:8082', 'Kube-ops-view (port-forward)')
    ]
)

# Goldilocks Dashboard
k8s_resource(
    workload='goldilocks-dashboard',
    new_name='infra-testing:goldilocks-dashboard',
    port_forwards=['8083:8080'],
    labels=['ui-tools'],
    links=[
        link('http://goldilocks.talos00', 'Goldilocks (via Traefik)'),
        link('http://localhost:8083', 'Goldilocks (port-forward)')
    ]
)

# Goldilocks Controller
k8s_resource(
    workload='goldilocks-controller',
    new_name='infra-testing:goldilocks-controller',
    labels=['ui-tools']
)

# VPA Recommender (in kube-system)
k8s_resource(
    workload='vpa-recommender',
    new_name='kube-system:vpa-recommender',
    labels=['ui-tools']
)

# ============================================
# Monitoring Stack
# ============================================

# Prometheus
k8s_resource(
    workload='prometheus-kube-prometheus-stack-prometheus',
    new_name='monitoring:prometheus',
    port_forwards=['9090:9090'],
    labels=['monitoring'],
    links=[
        link('http://prometheus.talos00', 'Prometheus (via Traefik)'),
        link('http://localhost:9090', 'Prometheus (port-forward)')
    ]
)

# Grafana
k8s_resource(
    workload='grafana',
    new_name='monitoring:grafana',
    port_forwards=['3000:3000'],
    labels=['monitoring'],
    links=[
        link('http://grafana.talos00', 'Grafana (via Traefik)'),
        link('http://localhost:3000', 'Grafana (port-forward)')
    ]
)

# Alertmanager
k8s_resource(
    workload='alertmanager-kube-prometheus-stack-alertmanager',
    new_name='monitoring:alertmanager',
    port_forwards=['9093:9093'],
    labels=['monitoring'],
    links=[
        link('http://alertmanager.talos00', 'Alertmanager (via Traefik)'),
        link('http://localhost:9093', 'Alertmanager (port-forward)')
    ]
)

# ============================================
# Observability Stack
# ============================================

# Graylog
k8s_resource(
    workload='graylog',
    new_name='observability:graylog',
    port_forwards=['9000:9000'],
    labels=['observability'],
    links=[
        link('http://graylog.talos00', 'Graylog (via Traefik)'),
        link('http://localhost:9000', 'Graylog (port-forward)')
    ]
)

# OpenSearch
k8s_resource(
    workload='opensearch',
    new_name='observability:opensearch',
    port_forwards=['9200:9200'],
    labels=['observability']
)

# ============================================
# ArgoCD
# ============================================

k8s_resource(
    workload='argocd-server',
    new_name='argocd:server',
    port_forwards=['8443:8080'],
    labels=['gitops'],
    links=[
        link('http://argocd.talos00', 'ArgoCD (via Traefik)'),
        link('http://localhost:8443', 'ArgoCD (port-forward)')
    ]
)

# ============================================
# Traefik Ingress Controller
# ============================================

k8s_resource(
    workload='traefik',
    new_name='traefik:ingress-controller',
    port_forwards=['8000:80', '8888:443'],
    labels=['networking'],
    links=[
        link('http://localhost:8000', 'Traefik HTTP'),
        link('https://localhost:8888', 'Traefik HTTPS')
    ]
)

# ============================================
# Docker Registry
# ============================================

k8s_resource(
    workload='docker-registry',
    new_name='registry:docker-registry',
    port_forwards=['5000:5000'],
    labels=['infrastructure'],
    links=[
        link('http://registry.talos00', 'Registry (via Traefik)'),
        link('http://localhost:5000', 'Registry (port-forward)')
    ]
)

# ============================================
# External Secrets Operator (Optional)
# ============================================

# Uncomment to include ESO in the dev loop
# helm_repo(
#     'external-secrets',
#     'https://charts.external-secrets.io',
#     resource_name='external-secrets-repo'
# )
#
# helm_resource(
#     'external-secrets-operator',
#     chart='external-secrets/external-secrets',
#     namespace='external-secrets',
#     flags=['--set=installCRDs=true'],
#     resource_deps=['external-secrets-repo'],
#     labels=['external-secrets'],
# )

# ============================================
# Cluster Information
# ============================================

local_resource(
    'cluster-health',
    'kubectl get nodes && echo "" && kubectl get pods -A | grep -v Running | grep -v Completed || echo "✅ All pods running"',
    auto_init=True,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=['cluster-info']
)

local_resource(
    'cluster-resources',
    'kubectl top nodes && echo "" && kubectl top pods -A --sort-by=memory | head -20',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=['cluster-info']
)

local_resource(
    'cluster-events',
    'kubectl get events -A --sort-by=.lastTimestamp | tail -20',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=['cluster-info']
)

# ============================================
# Setup & Configuration
# ============================================

local_resource(
    'update-hosts',
    'sudo ./scripts/update-hosts.sh || echo "⚠️  Run manually: sudo ./scripts/update-hosts.sh"',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=['setup']
)

local_resource(
    'kubeconfig-merge',
    'task kubeconfig-merge',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=['setup']
)

# ============================================
# Quick Deployment Actions
# ============================================

local_resource(
    'deploy-infra-testing',
    './scripts/deploy-infra-testing.sh',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=['quick-actions']
)

local_resource(
    'deploy-stack',
    './scripts/deploy-stack.sh',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=['quick-actions']
)

local_resource(
    'deploy-observability',
    './scripts/deploy-observability.sh',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=['quick-actions']
)

# ============================================
# Development Helpers
# ============================================

local_resource(
    'validate-manifests',
    'kubectl apply --dry-run=client -k infrastructure/base/infra-testing/',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=['validation']
)

local_resource(
    'lint-yaml',
    'task dev:lint',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=['validation']
)

# ============================================
# Tilt Configuration
# ============================================

# Update settings for better development experience
update_settings(
    max_parallel_updates=3,
    k8s_upsert_timeout_secs=300,
    suppress_unused_image_warnings=None
)

# Set up file watches for manifest hot-reload
watch_file('infrastructure/base/')
watch_file('infrastructure/overlays/')
watch_file('applications/')

print("""
═══════════════════════════════════════════════════════════════
🚀 Tilt is ready!
═══════════════════════════════════════════════════════════════

📦 Loaded Namespaces:
  ✅ arr-stack          Media automation (Sonarr, Radarr, Plex, etc.)
  📊 monitoring         Prometheus, Grafana, Alertmanager
  🔍 observability      OpenSearch, Graylog
  🧪 infra-testing      Headlamp, Kubeview, Kube-ops-view, Goldilocks
  🌐 networking         Traefik, ArgoCD, Registry

Quick Tips:
  - All resources are organized by labels (automation, media-server, monitoring, etc.)
  - Port forwards are automatically configured for local access
  - Use manual triggers for quick actions (deploy-stack, flux-reconcile, etc.)
  - Press 'r' on any resource to force a rebuild/reapply
  - Flux reconciliation can be triggered manually from 'flux-control' resources
  - File watching enabled - changes to manifests will auto-reload

Arr-Stack URLs (via Traefik - requires /etc/hosts):
  - Sonarr:         http://sonarr.talos00
  - Radarr:         http://radarr.talos00
  - Prowlarr:       http://prowlarr.talos00
  - Overseerr:      http://overseerr.talos00
  - Plex:           http://plex.talos00
  - Jellyfin:       http://jellyfin.talos00
  - Tdarr:          http://tdarr.talos00
  - Homepage:       http://homepage.talos00

Arr-Stack Port-forwards (from namespace Tiltfile):
  - Sonarr:         http://localhost:8989
  - Radarr:         http://localhost:7878
  - Prowlarr:       http://localhost:9696
  - Overseerr:      http://localhost:5055
  - Plex:           http://localhost:32400/web
  - Jellyfin:       http://localhost:8096
  - Tdarr:          http://localhost:8265
  - Homepage:       http://localhost:3000

Infrastructure URLs (via Traefik):
  - Headlamp:       http://headlamp.talos00
  - Grafana:        http://grafana.talos00
  - Prometheus:     http://prometheus.talos00
  - ArgoCD:         http://argocd.talos00
  - Graylog:        http://graylog.talos00

Infrastructure Port-forwards:
  - Headlamp:       http://localhost:8080
  - Grafana:        http://localhost:3000
  - Prometheus:     http://localhost:9090
  - Alertmanager:   http://localhost:9093
  - Graylog:        http://localhost:9000
  - Registry:       http://localhost:5000

⚠️  Flux Status: %s
%s
Happy developing! 🎉
═══════════════════════════════════════════════════════════════
""" % (
    'SUSPENDED' if settings['flux_suspend'] else 'ACTIVE',
    '   Flux will resume when you run: tilt down' if settings['flux_suspend'] else ''
))
