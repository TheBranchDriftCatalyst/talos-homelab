# Root Tiltfile - Talos Homelab Infrastructure
# Orchestrates all namespace development environments
#
# Usage:
#   tilt up                          # Start all namespaces
#   tilt up arr-stack                # Start specific namespace
#   tilt up monitoring observability # Start multiple namespaces
#   SUSPEND_FLUX=false tilt up       # Start without suspending Flux
#
# UI Organization:
#   Labels create collapsible groups in the sidebar. We use these groups:
#   - 1-apps-media      → Arr-stack applications (Sonarr, Radarr, etc.)
#   - 2-infra-platform  → Core platform (ArgoCD, Traefik, Registry)
#   - 3-infra-observe   → Monitoring & Observability
#   - 4-tools           → UI tools & utilities
#   - 5-ops             → Operations (cluster health, cleanup, deploy)

# Load Tilt extensions
load('ext://helm_resource', 'helm_resource', 'helm_repo')
load('ext://dotenv', 'dotenv')
load('ext://uibutton', 'cmd_button', 'location', 'text_input', 'bool_input', 'choice_input')
load('ext://k8s_attach', 'k8s_attach')

# Load environment variables from .env file (if exists)
dotenv()

# Configuration
config.define_string('k8s_context', args=False, usage='Kubernetes context to use')
config.define_bool('flux-suspend', args=False, usage='Suspend Flux reconciliation during development')
cfg = config.parse()

# Settings
settings = {
    'k8s_context': cfg.get('k8s_context', 'admin@homelab-single'),
    'flux_suspend': cfg.get('flux-suspend', False),
}

allow_k8s_contexts(settings['k8s_context'])

print("""
╔═══════════════════════════════════════════════════════════════╗
║  Talos Homelab - Tilt Development Environment                 ║
╚═══════════════════════════════════════════════════════════════╝
Context: %s | Flux: %s
""" % (settings['k8s_context'], 'SUSPENDED' if settings['flux_suspend'] else 'active'))

# Suspend Flux if configured
if settings['flux_suspend']:
    local('flux suspend kustomization flux-system')

# ============================================
# LABEL CONSTANTS - Controls UI grouping
# ============================================
# Labels must be alphanumeric with '-', '_', '.' only (no colons)
# Numbered prefixes ensure consistent ordering in sidebar

LABEL_MEDIA = '1-apps-media'
LABEL_PLATFORM = '2-infra-platform'
LABEL_OBSERVE = '3-infra-observe'
LABEL_TOOLS = '4-tools'
LABEL_OPS = '5-ops'

# ============================================
# NAV BUTTONS - Only essential actions
# ============================================
# Keep nav bar minimal - detailed actions go on resources

# Flux operations dropdown
cmd_button(
    name='btn-flux',
    argv=['sh', '-c', '''
        case "$FLUX_ACTION" in
            "sync") flux reconcile kustomization flux-system --with-source && echo "✅ Flux synced" ;;
            "suspend") flux suspend kustomization --all && echo "✅ All kustomizations suspended" ;;
            "resume") flux resume kustomization --all && echo "✅ All kustomizations resumed" ;;
            "status") flux get all ;;
            *) echo "Unknown action: $FLUX_ACTION" ;;
        esac
    '''],
    location=location.NAV,
    text='Flux',
    icon_name='sync',
    inputs=[
        choice_input('FLUX_ACTION', 'Action', ['sync', 'status', 'suspend', 'resume'])
    ]
)

cmd_button(
    name='btn-cluster-health',
    argv=['sh', '-c', '''echo "=== Nodes ===" && kubectl get nodes -o wide && \
        echo "" && echo "=== Problem Pods ===" && \
        kubectl get pods -A | grep -v Running | grep -v Completed | grep -v "^NAMESPACE" || echo "✅ All healthy"'''],
    location=location.NAV,
    text='Health',
    icon_name='favorite'
)

# Cleanup with dropdown selection
cmd_button(
    name='btn-cleanup',
    argv=['sh', '-c', '''
        case "$CLEANUP_TYPE" in
            "failed") kubectl delete pods --field-selector=status.phase=Failed -A && echo "✅ Failed pods deleted" ;;
            "completed") kubectl delete pods --field-selector=status.phase=Succeeded -A && echo "✅ Completed pods deleted" ;;
            "evicted") kubectl get pods -A -o json | jq -r ".items[] | select(.status.reason==\"Evicted\") | .metadata.namespace + \" \" + .metadata.name" | xargs -r -n2 sh -c "kubectl delete pod -n \\$0 \\$1" && echo "✅ Evicted pods deleted" ;;
            "all") kubectl delete pods --field-selector=status.phase=Failed -A 2>/dev/null; kubectl delete pods --field-selector=status.phase=Succeeded -A 2>/dev/null; echo "✅ All stale pods deleted" ;;
            *) echo "Unknown cleanup type: $CLEANUP_TYPE" ;;
        esac
    '''],
    location=location.NAV,
    text='Cleanup',
    icon_name='auto_delete',
    inputs=[
        choice_input('CLEANUP_TYPE', 'Type', ['all', 'failed', 'completed', 'evicted'])
    ],
    requires_confirmation=True
)

# Deploy dropdown
cmd_button(
    name='btn-deploy',
    argv=['sh', '-c', '''
        case "$DEPLOY_TARGET" in
            "full-stack") ./scripts/deploy-stack.sh && echo "✅ Full stack deployed" ;;
            "monitoring") DEPLOY_MONITORING=true DEPLOY_OBSERVABILITY=false DEPLOY_MEDIA=false ./scripts/deploy-stack.sh && echo "✅ Monitoring deployed" ;;
            "observability") ./scripts/deploy-observability.sh && echo "✅ Observability deployed" ;;
            "media") DEPLOY_MONITORING=false DEPLOY_OBSERVABILITY=false DEPLOY_MEDIA=true ./scripts/deploy-stack.sh && echo "✅ Media stack deployed" ;;
            "infra-testing") kubectl apply -k infrastructure/base/infra-testing/ && echo "✅ Infra-testing deployed" ;;
            *) echo "Unknown target: $DEPLOY_TARGET" ;;
        esac
    '''],
    location=location.NAV,
    text='Deploy',
    icon_name='rocket_launch',
    inputs=[
        choice_input('DEPLOY_TARGET', 'Target', ['full-stack', 'monitoring', 'observability', 'media', 'infra-testing'])
    ],
    requires_confirmation=True
)

# Quick namespace viewer
cmd_button(
    name='btn-pods',
    argv=['sh', '-c', '''
        case "$NAMESPACE" in
            "all") kubectl get pods -A ;;
            *) kubectl get pods -n "$NAMESPACE" ;;
        esac
    '''],
    location=location.NAV,
    text='Pods',
    icon_name='view_list',
    inputs=[
        choice_input('NAMESPACE', 'Namespace', ['all', 'media', 'monitoring', 'observability', 'argocd', 'traefik', 'registry', 'infra-testing', 'kube-system'])
    ]
)

# ============================================
# OPERATIONS GROUP - Cluster management
# ============================================

local_resource(
    'cluster-status',
    '''echo "📊 CLUSTER STATUS" && echo "=================" && \
       echo "" && echo "Nodes:" && kubectl get nodes -o wide && \
       echo "" && echo "Resource Usage:" && kubectl top nodes 2>/dev/null || echo "(metrics-server not ready)" && \
       echo "" && echo "Problem Pods:" && \
       kubectl get pods -A | grep -v Running | grep -v Completed | grep -v "^NAMESPACE" || echo "✅ All pods healthy"''',
    auto_init=True,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=[LABEL_OPS]
)

local_resource(
    'cluster-events',
    'kubectl get events -A --sort-by=.lastTimestamp | tail -30',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=[LABEL_OPS]
)

local_resource(
    'stale-pods',
    '''echo "Failed:    $(kubectl get pods -A --field-selector=status.phase=Failed --no-headers 2>/dev/null | wc -l | tr -d ' ')" && \
       echo "Succeeded: $(kubectl get pods -A --field-selector=status.phase=Succeeded --no-headers 2>/dev/null | wc -l | tr -d ' ')" && \
       echo "" && kubectl get pods -A | grep -v Running | grep -v "^NAMESPACE" || echo "✅ All pods running"''',
    auto_init=True,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=[LABEL_OPS]
)


# Setup helpers
local_resource(
    'setup-hosts',
    'sudo ./scripts/update-hosts.sh || echo "⚠️  Run: sudo ./scripts/update-hosts.sh"',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=[LABEL_OPS]
)

local_resource(
    'setup-kubeconfig',
    'task kubeconfig-merge',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=[LABEL_OPS]
)

local_resource(
    'validate-manifests',
    'kubectl apply --dry-run=client -k infrastructure/base/infra-testing/ && echo "✅ Valid"',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=[LABEL_OPS]
)

# Resume Flux on shutdown if it was suspended
if settings['flux_suspend']:
    local_resource(
        'flux-resume-on-shutdown',
        cmd='flux resume kustomization flux-system',
        auto_init=False,
        trigger_mode=TRIGGER_MODE_MANUAL,
        labels=[LABEL_OPS]
    )

# ============================================
# APPLICATIONS - Media Stack
# ============================================

print('Loading: Media Stack (arr-stack)')
include('./applications/arr-stack/Tiltfile')

# ============================================
# APPLICATIONS - Scratch/Experimental
# ============================================

print('Loading: Scratch Stack (grpc-example)')
include('./applications/scratch/Tiltfile')

# ============================================
# TOOLS - Infrastructure Testing UIs
# ============================================

watch_file('infrastructure/base/infra-testing/')
k8s_yaml(kustomize('infrastructure/base/infra-testing'))

k8s_resource(
    workload='headlamp',
    new_name='headlamp',
    port_forwards=['8080:4466'],
    labels=[LABEL_TOOLS],
    links=[
        link('http://headlamp.talos00', 'Headlamp (Traefik)'),
        link('http://localhost:8080', 'Headlamp (local)')
    ]
)

cmd_button(
    name='btn-headlamp-token',
    resource='headlamp',
    argv=['sh', '-c', 'kubectl get secret -n infra-testing headlamp-admin -o jsonpath="{.data.token}" | base64 -d && echo'],
    text='Get Token',
    icon_name='key'
)

k8s_resource(
    workload='kubeview',
    new_name='kubeview',
    port_forwards=['8081:8000'],
    labels=[LABEL_TOOLS],
    links=[
        link('http://kubeview.talos00', 'Kubeview (Traefik)'),
        link('http://localhost:8081', 'Kubeview (local)')
    ]
)

k8s_resource(
    workload='kube-ops-view',
    new_name='kube-ops-view',
    port_forwards=['8082:8080'],
    labels=[LABEL_TOOLS],
    links=[
        link('http://kube-ops-view.talos00', 'Kube-ops-view (Traefik)'),
        link('http://localhost:8082', 'Kube-ops-view (local)')
    ]
)

k8s_resource(
    workload='goldilocks-dashboard',
    new_name='goldilocks',
    port_forwards=['8083:8080'],
    labels=[LABEL_TOOLS],
    links=[
        link('http://goldilocks.talos00', 'Goldilocks (Traefik)'),
        link('http://localhost:8083', 'Goldilocks (local)')
    ]
)

k8s_resource(
    workload='goldilocks-controller',
    new_name='goldilocks-ctrl',
    labels=[LABEL_TOOLS]
)

cmd_button(
    name='btn-goldilocks-refresh',
    resource='goldilocks-ctrl',
    argv=['kubectl', 'rollout', 'restart', 'deployment/goldilocks-controller', '-n', 'infra-testing'],
    text='Refresh VPAs',
    icon_name='refresh'
)

k8s_resource(
    workload='vpa-recommender',
    new_name='vpa-recommender',
    labels=[LABEL_TOOLS]
)

# ============================================
# PLATFORM - Core Infrastructure (k8s_attach)
# ============================================
# Read-only observation of Flux-managed resources

# ArgoCD
k8s_attach('argocd-server', 'deployment/argocd-server', namespace='argocd', labels=[LABEL_PLATFORM])
k8s_attach('argocd-repo', 'deployment/argocd-repo-server', namespace='argocd', labels=[LABEL_PLATFORM])
k8s_attach('argocd-ctrl', 'statefulset/argocd-application-controller', namespace='argocd', labels=[LABEL_PLATFORM])

cmd_button(
    name='btn-argocd-password',
    resource='argocd-server',
    argv=['sh', '-c', 'kubectl get secret -n argocd argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d && echo'],
    text='Get Password',
    icon_name='password'
)

# Traefik
k8s_attach('traefik', 'deployment/traefik', namespace='traefik', labels=[LABEL_PLATFORM])

# Registry
k8s_attach('registry', 'deployment/docker-registry', namespace='registry', labels=[LABEL_PLATFORM])

cmd_button(
    name='btn-registry-catalog',
    resource='registry',
    argv=['sh', '-c', 'kubectl port-forward -n registry svc/docker-registry 5000:5000 & sleep 2 && curl -s http://localhost:5000/v2/_catalog | jq . ; kill %1 2>/dev/null'],
    text='List Images',
    icon_name='inventory'
)

# External Secrets
k8s_attach('external-secrets', 'deployment/external-secrets', namespace='external-secrets', labels=[LABEL_PLATFORM])
k8s_attach('1password-connect', 'deployment/onepassword-connect', namespace='external-secrets', labels=[LABEL_PLATFORM])

# ============================================
# OBSERVABILITY - Monitoring & Logging
# ============================================

# Prometheus Stack
k8s_attach('prometheus', 'statefulset/prometheus-kube-prometheus-stack-prometheus', namespace='monitoring', labels=[LABEL_OBSERVE])
k8s_attach('grafana', 'deployment/kube-prometheus-stack-grafana', namespace='monitoring', labels=[LABEL_OBSERVE])
k8s_attach('alertmanager', 'statefulset/alertmanager-kube-prometheus-stack-alertmanager', namespace='monitoring', labels=[LABEL_OBSERVE])

cmd_button(
    name='btn-grafana-password',
    resource='grafana',
    argv=['sh', '-c', 'kubectl get secret -n monitoring kube-prometheus-stack-grafana -o jsonpath="{.data.admin-password}" | base64 -d && echo'],
    text='Get Password',
    icon_name='password'
)

# Logging Stack
k8s_attach('graylog', 'statefulset/graylog', namespace='observability', labels=[LABEL_OBSERVE])
k8s_attach('opensearch', 'statefulset/opensearch', namespace='observability', labels=[LABEL_OBSERVE])
k8s_attach('mongodb', 'deployment/mongodb', namespace='observability', labels=[LABEL_OBSERVE])
k8s_attach('fluent-bit', 'daemonset/fluent-bit', namespace='observability', labels=[LABEL_OBSERVE])

cmd_button(
    name='btn-graylog-restart',
    resource='graylog',
    argv=['kubectl', 'rollout', 'restart', 'statefulset/graylog', '-n', 'observability'],
    text='Restart',
    icon_name='refresh',
    requires_confirmation=True
)

# ============================================
# CONFIGURATION
# ============================================

update_settings(
    max_parallel_updates=3,
    k8s_upsert_timeout_secs=300,
    suppress_unused_image_warnings=None
)

watch_file('infrastructure/base/')
watch_file('infrastructure/overlays/')
watch_file('applications/')

print("""
Ready! UI Groups:
  1-apps-media     → Sonarr, Radarr, Plex, etc.
  2-infra-platform → ArgoCD, Traefik, Registry
  3-infra-observe  → Prometheus, Grafana, Graylog
  4-tools          → Headlamp, Kubeview, Goldilocks
  5-ops            → Cluster health, cleanup, deploy

Tip: Collapse groups you don't need in the sidebar.
""")
