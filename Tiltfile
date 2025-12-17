# Root Tiltfile - Talos Homelab Ops Dashboard
# Observes Flux-managed cluster, provides ops UI and port-forwards
#
# Usage:
#   tilt up                    # Start dashboard
#   tilt up -- --port-forward  # Start with all port-forwards active
#
# This Tiltfile does NOT deploy anything - Flux manages all deployments.
# It only observes existing resources and provides ops tooling.

# Load Tilt extensions
load('ext://uibutton', 'cmd_button', 'location', 'text_input', 'bool_input', 'choice_input')
load('ext://k8s_attach', 'k8s_attach')

# Configuration
config.define_string('k8s_context', args=False, usage='Kubernetes context to use')
cfg = config.parse()

settings = {
    'k8s_context': cfg.get('k8s_context', 'admin@homelab-single'),
}

allow_k8s_contexts(settings['k8s_context'])

print("""
======================================================================
  Talos Homelab - Ops Dashboard (Observe-Only Mode)
======================================================================
  Context: %s
  Flux: ACTIVE (not suspended - Flux owns all deployments)

  This dashboard observes your cluster and provides:
  - Log streaming for all workloads
  - Port-forwards to services
  - Ops buttons for common tasks
  - Manual job triggers (GPU tests, cleanup, etc.)
======================================================================
""" % settings['k8s_context'])

# ============================================
# LABEL CONSTANTS - Controls UI grouping
# ============================================
LABEL_MEDIA = '1-apps-media'
LABEL_PLATFORM = '2-infra-platform'
LABEL_OBSERVE = '3-infra-observe'
LABEL_TOOLS = '4-tools'
LABEL_OPS = '5-ops'

# ============================================
# NAV BUTTONS - Quick actions
# ============================================

cmd_button(
    name='btn-flux',
    argv=['sh', '-c', '''
        case "$FLUX_ACTION" in
            "sync") flux reconcile kustomization flux-system --with-source && echo "Flux synced" ;;
            "suspend") flux suspend kustomization --all && echo "All kustomizations suspended" ;;
            "resume") flux resume kustomization --all && echo "All kustomizations resumed" ;;
            "status") flux get all ;;
            *) echo "Unknown action: $FLUX_ACTION" ;;
        esac
    '''],
    location=location.NAV,
    text='Flux',
    icon_name='sync',
    inputs=[
        choice_input('FLUX_ACTION', 'Action', ['status', 'sync', 'suspend', 'resume'])
    ]
)

cmd_button(
    name='btn-cluster-health',
    argv=['sh', '-c', '''echo "=== Nodes ===" && kubectl get nodes -o wide && \
        echo "" && echo "=== Problem Pods ===" && \
        kubectl get pods -A | grep -v Running | grep -v Completed | grep -v "^NAMESPACE" || echo "All pods healthy"'''],
    location=location.NAV,
    text='Health',
    icon_name='favorite'
)

cmd_button(
    name='btn-cleanup',
    argv=['sh', '-c', '''
        case "$CLEANUP_TYPE" in
            "failed") kubectl delete pods --field-selector=status.phase=Failed -A && echo "Failed pods deleted" ;;
            "completed") kubectl delete pods --field-selector=status.phase=Succeeded -A && echo "Completed pods deleted" ;;
            "evicted") kubectl get pods -A -o json | jq -r ".items[] | select(.status.reason==\"Evicted\") | .metadata.namespace + \" \" + .metadata.name" | xargs -r -n2 sh -c "kubectl delete pod -n \\$0 \\$1" && echo "Evicted pods deleted" ;;
            "all") kubectl delete pods --field-selector=status.phase=Failed -A 2>/dev/null; kubectl delete pods --field-selector=status.phase=Succeeded -A 2>/dev/null; echo "All stale pods deleted" ;;
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
        choice_input('NAMESPACE', 'Namespace', ['all', 'media', 'monitoring', 'observability', 'argocd', 'traefik', 'kube-system', 'intel-device-plugins'])
    ]
)

# ============================================
# OPS - Manual tasks and jobs
# ============================================

local_resource(
    'cluster-status',
    '''echo "CLUSTER STATUS" && echo "=================" && \
       echo "" && echo "Nodes:" && kubectl get nodes -o wide && \
       echo "" && echo "Resource Usage:" && kubectl top nodes 2>/dev/null || echo "(metrics-server not ready)" && \
       echo "" && echo "Problem Pods:" && \
       kubectl get pods -A | grep -v Running | grep -v Completed | grep -v "^NAMESPACE" || echo "All pods healthy"''',
    auto_init=True,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=[LABEL_OPS]
)

local_resource(
    'cluster-events',
    'kubectl get events -A --sort-by=.lastTimestamp | tail -50',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=[LABEL_OPS]
)

local_resource(
    'flux-status',
    'flux get all',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=[LABEL_OPS]
)

local_resource(
    'gpu-test',
    '''kubectl delete job gpu-encode-test -n intel-device-plugins --ignore-not-found && \
       kubectl apply -f infrastructure/base/intel-gpu/gpu-test-job.yaml && \
       echo "Waiting for job to complete..." && \
       kubectl wait --for=condition=complete job/gpu-encode-test -n intel-device-plugins --timeout=120s && \
       kubectl logs job/gpu-encode-test -n intel-device-plugins''',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=[LABEL_OPS]
)

local_resource(
    'gpu-vs-cpu-test',
    './scripts/gpu-vs-cpu-test.sh',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=[LABEL_OPS]
)

local_resource(
    'deploy-stack',
    './scripts/deploy-stack.sh',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=[LABEL_OPS]
)

local_resource(
    'validate-manifests',
    '''echo "Validating kustomizations..." && \
       kubectl apply --dry-run=client -k infrastructure/base/intel-gpu/ && \
       kubectl apply --dry-run=client -k infrastructure/base/monitoring/ && \
       echo "All manifests valid"''',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=[LABEL_OPS]
)

# ============================================
# MEDIA APPS - Observe Flux-managed workloads
# ============================================

k8s_attach('sonarr', 'deployment/sonarr', namespace='media',
           port_forwards=['8989:8989'], labels=[LABEL_MEDIA])
k8s_attach('radarr', 'deployment/radarr', namespace='media',
           port_forwards=['7878:7878'], labels=[LABEL_MEDIA])
k8s_attach('prowlarr', 'deployment/prowlarr', namespace='media',
           port_forwards=['9696:9696'], labels=[LABEL_MEDIA])
k8s_attach('overseerr', 'deployment/overseerr', namespace='media',
           port_forwards=['5055:5055'], labels=[LABEL_MEDIA])
k8s_attach('plex', 'deployment/plex', namespace='media',
           port_forwards=['32400:32400'], labels=[LABEL_MEDIA])
k8s_attach('jellyfin', 'deployment/jellyfin', namespace='media',
           port_forwards=['8096:8096'], labels=[LABEL_MEDIA])
k8s_attach('tdarr', 'deployment/tdarr', namespace='media',
           port_forwards=['8265:8265'], labels=[LABEL_MEDIA])
k8s_attach('homepage', 'deployment/homepage', namespace='media',
           port_forwards=['3001:3000'], labels=[LABEL_MEDIA])
k8s_attach('kometa', 'deployment/kometa', namespace='media', labels=[LABEL_MEDIA])
k8s_attach('posterizarr', 'deployment/posterizarr', namespace='media',
           port_forwards=['8000:8000'], labels=[LABEL_MEDIA])
k8s_attach('tautulli', 'deployment/tautulli', namespace='media',
           port_forwards=['8181:8181'], labels=[LABEL_MEDIA])
k8s_attach('posterr', 'deployment/posterr', namespace='media',
           port_forwards=['3002:3000'], labels=[LABEL_MEDIA])

# Kometa ops buttons
cmd_button(
    name='btn-kometa-run',
    resource='kometa',
    argv=['sh', '-c', '''
        echo "Starting Kometa run..." && \
        kubectl exec -n media deploy/kometa -c kometa -- python kometa.py --run && \
        echo "Kometa run complete"
    '''],
    text='Run Now',
    icon_name='play_arrow'
)

cmd_button(
    name='btn-kometa-overlays',
    resource='kometa',
    argv=['sh', '-c', '''
        echo "Running Kometa overlays only..." && \
        kubectl exec -n media deploy/kometa -c kometa -- python kometa.py --run --overlays-only && \
        echo "Overlays complete"
    '''],
    text='Overlays Only',
    icon_name='layers'
)

cmd_button(
    name='btn-kometa-collections',
    resource='kometa',
    argv=['sh', '-c', '''
        echo "Running Kometa collections only..." && \
        kubectl exec -n media deploy/kometa -c kometa -- python kometa.py --run --collections-only && \
        echo "Collections complete"
    '''],
    text='Collections Only',
    icon_name='folder_special'
)

cmd_button(
    name='btn-sync-api-keys',
    resource='homepage',
    argv=['sh', '-c', '''./applications/arr-stack/scripts/sync-api-keys.sh && \
        kubectl rollout restart deployment homepage -n media && \
        kubectl rollout status deployment homepage -n media --timeout=60s && \
        echo "" && echo "✓ Homepage restarted with updated API keys"'''],
    text='Sync API Keys',
    icon_name='sync'
)

# ============================================
# PLATFORM - Core infrastructure
# ============================================

# ArgoCD
k8s_attach('argocd-server', 'deployment/argocd-server', namespace='argocd',
           port_forwards=['8443:8080'], labels=[LABEL_PLATFORM])
k8s_attach('argocd-repo', 'deployment/argocd-repo-server', namespace='argocd', labels=[LABEL_PLATFORM])
k8s_attach('argocd-ctrl', 'statefulset/argocd-application-controller', namespace='argocd', labels=[LABEL_PLATFORM])

cmd_button(
    name='btn-argocd-password',
    resource='argocd-server',
    argv=['sh', '-c', 'kubectl get secret -n argocd argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d && echo'],
    text='Get Password',
    icon_name='password'
)

# Traefik (DaemonSet, not Deployment)
k8s_attach('traefik', 'daemonset/traefik', namespace='traefik',
           port_forwards=['9000:9000'], labels=[LABEL_PLATFORM])

# Registry
k8s_attach('registry', 'deployment/docker-registry', namespace='registry',
           port_forwards=['5000:5000'], labels=[LABEL_PLATFORM])

# External Secrets
k8s_attach('external-secrets', 'deployment/external-secrets', namespace='external-secrets', labels=[LABEL_PLATFORM])
k8s_attach('1password-connect', 'deployment/onepassword-connect', namespace='external-secrets', labels=[LABEL_PLATFORM])

# ============================================
# OBSERVABILITY - Monitoring & Logging
# ============================================

# Grafana Stack (grafana-operator managed)
k8s_attach('grafana', 'deployment/grafana-deployment', namespace='monitoring',
           port_forwards=['3000:3000'], labels=[LABEL_OBSERVE])
k8s_attach('mimir', 'deployment/mimir-nginx', namespace='monitoring',
           port_forwards=['9009:80'], labels=[LABEL_OBSERVE])
k8s_attach('loki', 'statefulset/loki', namespace='monitoring', labels=[LABEL_OBSERVE])
k8s_attach('tempo', 'statefulset/tempo', namespace='monitoring', labels=[LABEL_OBSERVE])
k8s_attach('alloy', 'deployment/alloy', namespace='monitoring', labels=[LABEL_OBSERVE])

cmd_button(
    name='btn-grafana-credentials',
    resource='grafana',
    argv=['sh', '-c', '''echo "=== Grafana Credentials ===" && \
        echo "Username: $(kubectl get secret -n monitoring grafana-admin-credentials -o jsonpath='{.data.GF_SECURITY_ADMIN_USER}' | base64 -d)" && \
        echo "Password: $(kubectl get secret -n monitoring grafana-admin-credentials -o jsonpath='{.data.GF_SECURITY_ADMIN_PASSWORD}' | base64 -d)"'''],
    text='Get Credentials',
    icon_name='password'
)

# Legacy observability (scaled to 0, uncomment if running)
# k8s_attach('graylog', 'statefulset/graylog', namespace='observability', labels=[LABEL_OBSERVE])
# k8s_attach('opensearch', 'statefulset/opensearch-cluster-master', namespace='observability', labels=[LABEL_OBSERVE])

# ============================================
# TOOLS - Infrastructure testing UIs
# ============================================
# NOTE: infra-testing namespace doesn't exist yet. Uncomment when deployed.

# k8s_attach('headlamp', 'deployment/headlamp', namespace='infra-testing',
#            port_forwards=['8080:4466'], labels=[LABEL_TOOLS])
# k8s_attach('kubeview', 'deployment/kubeview', namespace='infra-testing',
#            port_forwards=['8081:8000'], labels=[LABEL_TOOLS])
# k8s_attach('kube-ops-view', 'deployment/kube-ops-view', namespace='infra-testing',
#            port_forwards=['8082:8080'], labels=[LABEL_TOOLS])
# k8s_attach('goldilocks', 'deployment/goldilocks-dashboard', namespace='infra-testing',
#            port_forwards=['8083:8080'], labels=[LABEL_TOOLS])

# cmd_button(
#     name='btn-headlamp-token',
#     resource='headlamp',
#     argv=['sh', '-c', 'kubectl get secret -n infra-testing headlamp-admin -o jsonpath="{.data.token}" | base64 -d && echo'],
#     text='Get Token',
#     icon_name='key'
# )

# ============================================
# CONFIGURATION
# ============================================

update_settings(
    max_parallel_updates=3,
    k8s_upsert_timeout_secs=300,
    suppress_unused_image_warnings=None
)

print("""
Ready! UI Groups:
  1-apps-media     - Sonarr, Radarr, Plex, Jellyfin, etc.
  2-infra-platform - ArgoCD, Traefik, Registry, External Secrets
  3-infra-observe  - Grafana, Mimir, Loki, Tempo, Alloy
  5-ops            - Cluster status, GPU tests, deployments

Note: Some resources may show 'pending' if not yet deployed.
      Flux manages all deployments - Tilt only observes.
""")
